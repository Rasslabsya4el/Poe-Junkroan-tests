"""tools/agentops/merge.py builds the merge commit off the main checkout (#379): local main and
origin/main never sit at an unverified merge while the suite runs; only the verified commit is
pushed, with AGENTOPS_MAIN_PUSH=1 so a repo pre-push hook can refuse every other push of main."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

import tools.agentops.merge as merge_mod
from tests.test_agentops_merge import (  # noqa: F401  (autouse fixtures come with the import)
    _clone, _commit, _git, _git_allow_fail, _green_default_commit_suite, _protect_real_agentops_var,
    _push_branch, _world, suite_cmd,
)
from tools.agentops.merge import run_commit, run_merge


def _is_merge_free_history(bare: Path) -> bool:
    merges = _git("rev-list", "--merges", "main", cwd=bare).stdout.split()
    return not merges


def _install_writer(monkeypatch, checkout: Path, record: dict):
    """Wrap _run_suite: on the first suite run record the checkout's HEAD (must still be `base`),
    then a second writer commits on local main in the checkout and pushes with plain git. Every
    run records the suite worktree's tree."""
    real = merge_mod._run_suite
    record.update(runs=0, heads_during=[], trees=[], writer="")

    def wrapped(cmd, cwd, env=None, output_path=None, head_line="", **kw):
        record["runs"] += 1
        record["heads_during"].append(_git("rev-parse", "HEAD", cwd=checkout).stdout.strip())
        record["trees"].append(_git("rev-parse", "HEAD^{tree}", cwd=Path(cwd)).stdout.strip())
        ok, output = real(cmd, cwd, env, output_path, head_line, **kw)
        if record["runs"] == 1:
            _commit(checkout, "writer.txt", "writer\n", "second writer commits during the suite")
            _git("push", "-q", "origin", "main", cwd=checkout)
            record["writer"] = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
        return ok, output

    monkeypatch.setattr(merge_mod, "_run_suite", wrapped)


def test_a_red_suite_never_moves_main_while_a_writer_publishes(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    base = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    record: dict = {}
    _install_writer(monkeypatch, checkout, record)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    flag.write_text("red", encoding="utf-8")
    result = run_merge("origin/feature-a", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30, suite_shared=())

    assert not result.ok and result.reason == "red-suite"
    assert record["heads_during"] == [base]  # the checkout's HEAD == base during the suite
    origin_main = _git("rev-parse", "main", cwd=bare).stdout.strip()
    assert origin_main == record["writer"]  # origin/main == the writer's commit
    assert _is_merge_free_history(bare)  # no merge commit anywhere in origin/main's history


def test_b_green_suite_redoes_the_push_on_the_writers_head(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-b", "feature-b", "b.py", "b = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    base = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    record: dict = {}
    _install_writer(monkeypatch, checkout, record)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-b", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30, suite_shared=())

    assert result.ok, result.message
    assert result.pushed and result.suite_runs == 2 and result.rebases == 1
    assert record["heads_during"][0] == base
    assert record["heads_during"][1] == record["writer"]
    tree_pushed = _git("rev-parse", "main^{tree}", cwd=bare).stdout.strip()
    assert tree_pushed == record["trees"][-1]  # pushed tree == tree the last suite checked out
    parents = _git("rev-list", "--parents", "-n", "1", "main", cwd=bare).stdout.split()
    assert record["writer"] in parents[1:]  # the merge sits on the writer's head
    assert _git("rev-parse", "main", cwd=checkout).stdout == _git("rev-parse", "main", cwd=bare).stdout


def _install_hook(repo: Path, tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-push"
    hook.write_text('#!/bin/sh\n[ "$AGENTOPS_MAIN_PUSH" = "1" ] || { echo "plain push refused" >&2; exit 1; }\n',
                    encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    _git("config", "core.hooksPath", str(hooks), cwd=repo)  # this temp repo only


def test_c_pre_push_hook_refuses_plain_push_but_not_merge_or_commit(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _install_hook(checkout, tmp_path)
    _push_branch(bare, tmp_path, "worker-c", "feature-c", "c.py", "c = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-c", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30, suite_shared=())
    assert result.ok and result.pushed, result.message
    assert _git("rev-parse", "main", cwd=bare).stdout == _git("rev-parse", "main", cwd=checkout).stdout

    (checkout / "state.txt").write_text("state\n", encoding="utf-8")
    committed = run_commit(["state.txt"], "state: update", cwd=checkout,
                           lock_path=tmp_path / "merge.lock", lock_timeout=30)
    assert committed.ok and committed.pushed, committed.message
    assert _git("log", "-1", "--format=%s", "main", cwd=bare).stdout.strip() == "state: update"

    _commit(checkout, "plain.txt", "plain\n", "a plain push")
    plain = _git_allow_fail("push", "origin", "main", cwd=checkout)
    assert plain.returncode != 0 and "plain push refused" in plain.stderr
    assert _git("log", "-1", "--format=%s", "main", cwd=bare).stdout.strip() == "state: update"


def test_d_conflict_found_by_merge_tree_leaves_the_checkout_untouched(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-d", "feature-d", "conflict.py", "branch = 1\n")
    _commit(checkout, "conflict.py", "main = 1\n", "edit conflict.py on main")
    _git("push", "-q", "origin", "main", cwd=checkout)
    _git("fetch", "-q", "origin", cwd=checkout)
    head = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    content = (checkout / "conflict.py").read_bytes()

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-d", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30, suite_shared=())

    assert not result.ok and result.reason == "conflict"
    assert result.conflicting_files == ["conflict.py"]
    assert result.head_after == head
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == head
    assert (checkout / "conflict.py").read_bytes() == content
    assert _git("status", "--porcelain", cwd=checkout).stdout == ""
    assert not counter.exists()  # the suite never ran
