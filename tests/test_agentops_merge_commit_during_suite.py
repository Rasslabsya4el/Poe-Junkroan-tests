"""#733: a commit that needs no suite lands at once while a merge suite runs.

The real merge flow (``run_merge`` in a thread, the suite script sleeping) and the real
``run_commit`` in the same checkout, over a bare origin in ``tmp_path``. No PoB."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from tests.test_agentops_merge import (  # fixtures + helpers of the sibling file
    _git, _origin_main_head, _protect_real_agentops_var, _green_default_commit_suite,
    _push_branch, _world, suite_cmd,
)
from tools.agentops import merge as merge_mod
from tools.agentops.merge import run_commit, run_merge

_ = (_protect_real_agentops_var, _green_default_commit_suite)  # autouse fixtures, imported so they apply here

SUITE_SECONDS = 8.0   # the merge's suite sleeps this long (the issue's 20 s, scaled down)
COMMIT_AT = 1.0       # the commit starts this long after the merge thread starts
GATE_SECONDS = 180    # the merge's suite waits at most this long for the test's gate (a deadline, not a bound on commits)
JOIN_SECONDS = 180    # every thread join in this file: the full run's load makes a git call take seconds


class _Run:
    """One merge thread; ``t0`` is its start, ``ended`` its end on the monotonic clock. With ``gate``,
    the merge's suite step waits on it before the suite runs (``gate_timed_out`` if it never opened)."""

    def __init__(self, checkout: Path, lock_path: Path, tmp_path: Path, monkeypatch,
                 gate: threading.Event | None = None):
        self.checkout, self.lock_path = checkout, lock_path
        self.suite_started = threading.Event()
        self.gate, self.gate_timed_out = gate, False
        real = merge_mod._run_merge_suite

        def hooked(*args, **kwargs):
            self.suite_started.set()
            if self.gate is not None:
                self.gate_timed_out = not self.gate.wait(timeout=GATE_SECONDS)
            return real(*args, **kwargs)

        monkeypatch.setattr(merge_mod, "_run_merge_suite", hooked)
        self.counter, self.flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
        self.result = None
        self.ended = None
        self.t0 = time.monotonic()
        self.thread = threading.Thread(target=self._go)

    def _go(self) -> None:
        self.result = run_merge("origin/feature-f", suite_cmd(self.counter, self.flag, SUITE_SECONDS),
                                cwd=self.checkout, lock_path=self.lock_path, lock_timeout=60)
        self.ended = time.monotonic()

    def start_and_wait_for_suite(self) -> None:
        self.thread.start()
        assert self.suite_started.wait(timeout=60), "the merge never reached its suite"
        time.sleep(COMMIT_AT)


def _world_with_branch(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    (checkout / "docs" / "agents").mkdir(parents=True)
    _push_branch(bare, tmp_path, "worker-f", "feature-f", "f.py", "f = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    return bare, checkout


def _subjects(bare: Path) -> list[str]:
    return _git("log", "--format=%s", "main", cwd=bare).stdout.splitlines()


def _forced_pushes(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []
    real = merge_mod._git

    def spy(cwd, *args, **kwargs):
        if args and args[0] == "push" and any(a in ("-f", "--force", "--force-with-lease")
                                              or a.startswith("+") for a in args[1:]):
            seen.append(args)
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(merge_mod, "_git", spy)
    return seen


def test_rows1_2_a_state_commit_lands_during_the_suite_and_the_merge_takes_one_rebase(tmp_path: Path, monkeypatch):
    bare, checkout = _world_with_branch(tmp_path)
    forced = _forced_pushes(monkeypatch)
    (checkout / "docs" / "STATE.md").write_text("state 1\n", encoding="utf-8")
    run = _Run(checkout, tmp_path / "merge.lock", tmp_path, monkeypatch)
    run.start_and_wait_for_suite()

    t1 = time.monotonic()
    commit = run_commit(["docs/STATE.md"], "State: update 1", cwd=checkout,
                        lock_path=tmp_path / "merge.lock", lock_timeout=60)
    took = time.monotonic() - t1
    merge_still_running = run.thread.is_alive()
    main_after_commit = _subjects(bare)
    run.thread.join(timeout=60)

    print(f"row1: commit {took:.1f}s, suite still running: {merge_still_running}")
    assert commit.ok and commit.pushed, commit.message
    assert merge_still_running is True, "the commit returned only after the suite"   # row 1: order, not seconds
    assert main_after_commit[0] == "State: update 1"
    result = run.result
    assert result.ok and result.pushed, result.message                        # row 2
    assert (result.suite_runs, result.rebases) == (1, 1)
    subjects = _subjects(bare)
    assert "State: update 1" in subjects and "add f.py" in subjects
    assert _git("rev-parse", "main", cwd=checkout).stdout.strip() == _origin_main_head(bare)
    assert forced == []


def test_row3_two_suite_free_commits_during_the_suite_both_land_without_force(tmp_path: Path, monkeypatch):
    """#1025: the merge's suite step holds at a gate until both commits have returned, so "the commits
    returned while the merge was still in its suite" is decided by order, not by a wall clock (the old
    10 s bound measured git calls under the full run's load: 17 s to 62 s, with every other row green)."""
    bare, checkout = _world_with_branch(tmp_path)
    forced = _forced_pushes(monkeypatch)
    (checkout / "docs" / "STATE.md").write_text("state 1\n", encoding="utf-8")
    (checkout / "docs" / "agents" / "x.md").write_text("x 1\n", encoding="utf-8")
    gate = threading.Event()
    run = _Run(checkout, tmp_path / "merge.lock", tmp_path, monkeypatch, gate=gate)
    run.start_and_wait_for_suite()

    out: dict[str, object] = {}

    def commit(name: str, path: str) -> None:
        out[name] = run_commit([path], f"docs: {name}", cwd=checkout,
                               lock_path=tmp_path / "merge.lock", lock_timeout=60)

    t1 = time.monotonic()
    threads = [threading.Thread(target=commit, args=("a", "docs/STATE.md")),
               threading.Thread(target=commit, args=("b", "docs/agents/x.md"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=JOIN_SECONDS)
    took = time.monotonic() - t1
    merge_still_running = run.thread.is_alive()
    gate.set()  # both commits are back (or the join ended): the merge's suite may now run
    run.thread.join(timeout=JOIN_SECONDS)

    print(f"row3: both commits {took:.1f}s, suite still running: {merge_still_running}")
    assert sorted(out) == ["a", "b"], f"a commit did not return: {sorted(out)}"
    assert all(r.ok and r.pushed for r in out.values()), {k: r.message for k, r in out.items()}
    assert merge_still_running and not run.gate_timed_out, "a suite-free commit waited for the merge's suite"
    subjects = _subjects(bare)
    assert "docs: a" in subjects and "docs: b" in subjects                    # neither push lost
    assert run.result.ok and run.result.pushed, run.result.message
    assert run.result.suite_runs == 1 and run.result.rebases >= 1
    assert "add f.py" in subjects
    assert forced == []
    assert _git("rev-parse", "main", cwd=checkout).stdout.strip() == _origin_main_head(bare)


def test_row4_a_py_commit_during_the_suite_waits_for_the_lock_as_today(tmp_path: Path, monkeypatch):
    bare, checkout = _world_with_branch(tmp_path)
    (checkout / "state.py").write_text("state = 1\n", encoding="utf-8")
    run = _Run(checkout, tmp_path / "merge.lock", tmp_path, monkeypatch)
    run.start_and_wait_for_suite()

    t1 = time.monotonic()
    commit = run_commit(["state.py"], "state: py", cwd=checkout,
                        lock_path=tmp_path / "merge.lock", lock_timeout=60)
    returned = time.monotonic()
    run.thread.join(timeout=60)

    print(f"row4: py commit waited {returned - t1:.1f}s")
    assert commit.ok and commit.pushed, commit.message
    assert run.result.ok and run.result.pushed, run.result.message
    assert returned - t1 > SUITE_SECONDS - COMMIT_AT - 2.0                    # it sat out the suite
    assert run.ended is not None and returned >= run.ended - 0.5              # and went after the merge
    assert (run.result.suite_runs, run.result.rebases) == (1, 0)
    subjects = _subjects(bare)
    assert subjects[0] == "state: py" and "add f.py" in subjects
