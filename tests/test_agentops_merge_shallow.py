"""tools/agentops/merge.py: the main checkout became shallow (issue #241).

A bare repo stands in for GitHub, exactly as ``tests/test_agentops_merge.py`` sets one up; the
same clone/commit/push helpers are imported from there rather than copied. Every clone lives
under ``tmp_path``; the real ``C:\\Coding\\poe-junkroan-v2\\.git`` is never touched."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.agentops import merge as merge_module
from tools.agentops.merge import run_commit, run_merge

from tests.test_agentops_merge import (
    SUITE_SCRIPT,
    _clone,
    _commit,
    _git,
    _git_allow_fail,
    _init_bare,
    _world,
    suite_cmd,
)


@pytest.fixture(autouse=True)
def _protect_real_agentops_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same protection as ``test_agentops_merge.py``'s own fixture (#234): every call in this
    file that omits its own path stays under ``tmp_path``, never the real ``var/agentops/``."""
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_autoprotect_merge_suite")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_autoprotect_merge.log")


def _is_shallow(cwd: Path) -> bool:
    return _git("rev-parse", "--is-shallow-repository", cwd=cwd).stdout.strip() == "true"


def _shallow_checkout_with_cut_branch_tip(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A full checkout (every branch's remote-tracking ref already known, exactly what the
    main checkout carries) whose ``main`` history then gets cut by a depth-1 fetch -- the
    shape #241's triage traced (a plain ``git fetch --depth 1 origin main`` after a normal
    clone; see the closing comment for the reflog evidence). ``feature`` branches off the
    *original* first commit, so its merge-base falls outside the now-shallow history of
    ``main``.

    Returns ``(bare, checkout, feature_ref)``."""
    bare = _init_bare(tmp_path)
    seed = _clone(bare, tmp_path / "seed")
    _commit(seed, "README.md", "hello\n", "initial")
    _git("push", "-q", "origin", "main", cwd=seed)

    checkout = _clone(bare, tmp_path / "checkout")

    _git("checkout", "-q", "-b", "feature", cwd=seed)
    _commit(seed, "f.txt", "branchfile\n", "add f.txt")
    _git("push", "-q", "origin", "feature", cwd=seed)

    _git("checkout", "-q", "main", cwd=seed)
    for i in range(3):
        _commit(seed, "README.md", f"hello\nrev{i}\n", f"main rev {i}")
    _git("push", "-q", "origin", "main", cwd=seed)

    _git("fetch", "-q", "origin", cwd=checkout)
    _git("merge", "-q", "--ff-only", "origin/main", cwd=checkout)
    assert not _is_shallow(checkout)

    # the incident: a depth-1 fetch of `main` cuts its own history, leaving `origin/feature`'s
    # remote-tracking ref (fetched above, in full) exactly as it was
    shallowing = _git_allow_fail("fetch", "--depth", "1", "origin", "main", cwd=checkout)
    assert shallowing.returncode == 0, shallowing.stderr
    _git("reset", "-q", "--hard", "origin/main", cwd=checkout)
    assert _is_shallow(checkout)

    return bare, checkout, "origin/feature"


# -- row 1: a shallow checkout whose branch tip is cut, run_merge on it -------------------------

def test_row1_shallow_checkout_is_repaired_then_merged_and_pushed(tmp_path: Path):
    bare, checkout, feature = _shallow_checkout_with_cut_branch_tip(tmp_path)
    merge_log_path = tmp_path / "merge.log"
    suite_output_dir = tmp_path / "suite-out"
    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"

    result = run_merge(feature, suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=suite_output_dir, merge_log_path=merge_log_path)

    assert result.ok, result.message
    assert result.reason == "pushed"
    assert not _is_shallow(checkout)

    log_lines = merge_log_path.read_text(encoding="utf-8").splitlines()
    repair_lines = [line for line in log_lines if "shallow-repaired" in line]
    assert len(repair_lines) == 1, log_lines
    assert f"fetch --unshallow origin" in repair_lines[0]

    remote_head = _git("rev-parse", "main", cwd=bare).stdout.strip()
    local_head = _git("rev-parse", "main", cwd=checkout).stdout.strip()
    assert remote_head == local_head


# -- row 2: the same clone, the remote gone -- the repair itself cannot run ----------------------

def test_row2_shallow_checkout_remote_gone_reason_is_shallow(tmp_path: Path):
    bare, checkout, feature = _shallow_checkout_with_cut_branch_tip(tmp_path)
    head_before = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

    # the remote is gone: point origin at a path that no longer exists
    _git("remote", "set-url", "origin", str(tmp_path / "no-such-origin.git"), cwd=checkout)

    result = run_merge(feature, suite_cmd(tmp_path / "counter2.txt", tmp_path / "flag2.txt"),
                       cwd=checkout, lock_path=tmp_path / "merge2.lock", lock_timeout=30,
                       suite_output_dir=tmp_path / "suite-out-2",
                       merge_log_path=tmp_path / "merge2.log")

    assert not result.ok
    assert result.reason == "shallow"
    assert result.suite_runs == 0
    head_after = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    assert head_after == head_before


# -- row 3: run_commit on a shallow clone --------------------------------------------------------

def test_row3_run_commit_repairs_shallow_checkout(tmp_path: Path):
    bare, checkout, _feature = _shallow_checkout_with_cut_branch_tip(tmp_path)

    (checkout / "notes.txt").write_text("a note\n", encoding="utf-8")

    # a non-docs path runs the merge suite (#375): a green stand-in, never the real settings' suite
    result = run_commit(["notes.txt"], "add notes.txt", cwd=checkout,
                        lock_path=tmp_path / "commit.lock", lock_timeout=30,
                        suite_cmd=f'"{sys.executable}" -c "pass"')

    assert result.ok, result.message
    assert result.reason == "pushed"
    assert "unshallow" in result.message.lower()
    assert not _is_shallow(checkout)

    remote_head = _git("rev-parse", "main", cwd=bare).stdout.strip()
    local_head = _git("rev-parse", "main", cwd=checkout).stdout.strip()
    assert remote_head == local_head


# -- row 4: unrelated histories in a full (non-shallow) clone ------------------------------------

def test_row4_unrelated_histories_full_clone_named_by_git_not_rollback_refused(tmp_path: Path):
    bare = _init_bare(tmp_path)
    seed_a = _clone(bare, tmp_path / "seed-a")
    _commit(seed_a, "a.txt", "a\n", "history a")
    _git("push", "-q", "origin", "main", cwd=seed_a)
    checkout = _clone(bare, tmp_path / "checkout")

    # a second, disconnected root pushed to its own branch (`--allow-unrelated-histories`
    # is what a real merge into `origin/main` would then need and does not get)
    seed_b = _clone(bare, tmp_path / "seed-b")
    _git("checkout", "-q", "--orphan", "unrelated", cwd=seed_b)
    _git("rm", "-rf", "--quiet", "-f", "a.txt", cwd=seed_b)
    _commit(seed_b, "b.txt", "b\n", "history b")
    _git("push", "-q", "origin", "unrelated", cwd=seed_b)

    _git("fetch", "-q", "origin", cwd=checkout)
    assert not _is_shallow(checkout)
    head_before = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

    result = run_merge("origin/unrelated", suite_cmd(tmp_path / "counter4.txt", tmp_path / "flag4.txt"),
                       cwd=checkout, lock_path=tmp_path / "merge4.lock", lock_timeout=30,
                       suite_output_dir=tmp_path / "suite-out-4",
                       merge_log_path=tmp_path / "merge4.log")

    assert not result.ok
    assert result.reason != "rollback-refused"
    assert "refusing to merge unrelated histories" in result.message
    head_after = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    assert head_after == head_before


# -- row 5: a checkout that is not shallow costs 0 extra fetches ---------------------------------

def test_row5_non_shallow_checkout_costs_no_extra_fetch(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    from tests.test_agentops_merge import _push_branch
    _push_branch(bare, tmp_path, "worker-r5", "feature-r5", "r5.py", "r5 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    assert not _is_shallow(checkout)

    fetch_calls: list[tuple[str, ...]] = []
    real_git = merge_module._git

    def counting_git(cwd, *args, **kw):
        if args and args[0] == "fetch":
            fetch_calls.append(args)
        return real_git(cwd, *args, **kw)

    merge_module._git = counting_git
    try:
        result = run_merge("origin/feature-r5",
                           suite_cmd(tmp_path / "counter5.txt", tmp_path / "flag5.txt"),
                           cwd=checkout, lock_path=tmp_path / "merge5.lock", lock_timeout=30,
                           suite_output_dir=tmp_path / "suite-out-5",
                           merge_log_path=tmp_path / "merge5.log")
    finally:
        merge_module._git = real_git

    assert result.ok, result.message
    # exactly the one fetch `_sync_up` always makes; the shallow check never fetches
    assert fetch_calls == [("fetch", "origin")], fetch_calls
