"""#714: a green suite is not run again when main moved during it only by docs commits.

Real ``run_merge`` over a bare origin in ``tmp_path``; the commit that "lands during the suite" is
pushed from a second clone inside the suite hook (``_run_suite``), a later wave inside the
``_sync_up`` hook (after the re-merge synced, so origin refuses the push). No PoB."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_agentops_merge import (  # fixtures + helpers of the sibling file
    NO_LOAD_REACHES, _clone, _git, _green_default_commit_suite, _origin_main_head,
    _protect_real_agentops_var, _push_branch, _world, suite_cmd,
)
from tests.test_agentops_merge_batch import _Queue, _merge_jobs
from tools.agentops import merge as merge_mod
from tools.agentops.merge import run_merge

_ = (_protect_real_agentops_var, _green_default_commit_suite)  # autouse fixtures, imported so they apply here


class _Mover:
    """A second clone that lands commits on origin/main while the merge works."""

    def __init__(self, bare: Path, tmp_path: Path):
        self.repo = _clone(bare, tmp_path / "mover")
        self.n = 0

    def land(self, name: str, content: str, message: str) -> None:
        self.n += 1
        target = self.repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git("add", name, cwd=self.repo)
        _git("commit", "-q", "-m", message, cwd=self.repo)
        _git("push", "-q", "origin", "main", cwd=self.repo)

    def state(self, k: int = 1) -> None:
        for _ in range(k):
            self.land("docs/STATE.md", f"state {self.n + 1}\n", f"State: update {self.n + 1}")


def _seed_state(bare: Path, tmp_path: Path) -> None:
    seed = _clone(bare, tmp_path / "seeder")
    (seed / "docs").mkdir()
    (seed / "docs" / "STATE.md").write_text("state 0\n", encoding="utf-8")
    _git("add", "docs/STATE.md", cwd=seed)
    _git("commit", "-q", "-m", "State: seed", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)


def _hook_suite(monkeypatch, on_first_run) -> None:
    real = merge_mod._run_suite
    seen = {"n": 0}

    def hooked(cmd, cwd, env=None, output_path=None, head_line="", **kw):
        ok, output = real(cmd, cwd, env, output_path, head_line, **kw)
        seen["n"] += 1
        if seen["n"] == 1:
            on_first_run()
        return ok, output

    monkeypatch.setattr(merge_mod, "_run_suite", hooked)


def _subjects(bare: Path, tmp_path: Path) -> list[str]:
    fresh = _clone(bare, tmp_path / "verify")
    return _git("log", "--format=%s", "main", cwd=fresh).stdout.splitlines()


def test_row1_a_state_commit_during_the_suite_lands_without_a_second_suite(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _seed_state(bare, tmp_path)
    _push_branch(bare, tmp_path, "worker-f", "feature-f", "f.py", "f = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    mover = _Mover(bare, tmp_path)
    _hook_suite(monkeypatch, mover.state)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-f", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok and result.pushed, result.message
    assert (result.suite_runs, result.rebases) == (1, 1)
    assert int(counter.read_text()) == 1
    subjects = _subjects(bare, tmp_path)
    assert "State: update 1" in subjects and "add f.py" in subjects
    assert _git("rev-parse", "main", cwd=checkout).stdout.strip() == _origin_main_head(bare)


def test_row2_a_py_commit_during_the_suite_still_runs_the_suite_again(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-f", "feature-f", "f.py", "f = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    mover = _Mover(bare, tmp_path)
    _hook_suite(monkeypatch, lambda: mover.land("mover.py", "mover = 1\n", "a code commit"))

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-f", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok and result.pushed, result.message
    assert (result.suite_runs, result.rebases) == (2, 1)
    assert int(counter.read_text()) == 2


def test_row3_seven_docs_commits_in_three_waves_end_at_one_suite_run(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _seed_state(bare, tmp_path)
    _push_branch(bare, tmp_path, "worker-f", "feature-f", "f.py", "f = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    mover = _Mover(bare, tmp_path)
    _hook_suite(monkeypatch, lambda: mover.state(3))  # wave 1: three, during the suite

    real_sync = merge_mod._sync_up
    syncs = {"n": 0}

    def sync_then_land(cwd, remote, main):
        out = real_sync(cwd, remote, main)
        syncs["n"] += 1
        if syncs["n"] == 2:       # the first re-merge synced: wave 2 (two commits) beats its push
            mover.state(2)
        elif syncs["n"] == 3:     # the second re-merge synced: wave 3 (two commits) beats its push
            mover.state(2)
        return out

    monkeypatch.setattr(merge_mod, "_sync_up", sync_then_land)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-f", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok and result.pushed, result.message
    assert result.suite_runs == 1 and result.rebases == 3
    assert int(counter.read_text()) == 1
    assert mover.n == 7
    subjects = _subjects(bare, tmp_path)
    assert sum(s.startswith("State: update") for s in subjects) == 7 and "add f.py" in subjects


def test_row4_a_batch_of_two_lands_on_one_suite_run_past_a_docs_commit(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _seed_state(bare, tmp_path)
    _push_branch(bare, tmp_path, "w1", "f1", "a.py", "a = 1\n")
    _push_branch(bare, tmp_path, "w2", "f2", "b.py", "b = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    mover = _Mover(bare, tmp_path)
    _hook_suite(monkeypatch, mover.state)

    counter, flag, log = tmp_path / "counter.txt", tmp_path / "flag.txt", tmp_path / "merge.log"
    lock_path = tmp_path / "merge.lock"
    results: dict = {}
    q = _Queue(lock_path)
    for job in _merge_jobs(tmp_path, checkout, lock_path, ["f1", "f2"], suite_cmd(counter, flag), results, log):
        q.add(job)
    q.release_and_join()

    assert int(counter.read_text()) == 1
    assert all(r.ok and r.pushed and r.suite_runs == 1 for r in results.values()), \
        {k: (r.reason, r.message) for k, r in results.items()}
    assert sorted(r.batched for r in results.values()) == [False, True]
    assert sorted(r.rebases for r in results.values()) == [0, 1]  # the holder re-merged once
    subjects = _subjects(bare, tmp_path)
    assert sum(s.startswith("Merge branch") for s in subjects) == 2 and "State: update 1" in subjects
    for r in results.values():
        assert r.head_after == _origin_main_head(bare)
