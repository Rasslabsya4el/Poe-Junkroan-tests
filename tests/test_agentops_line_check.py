"""#765 unit 1: ``LineCheck``, the check of one waiting branch, with stub suites (no PoB).

A bare origin and a checkout in ``tmp_path`` (the merge tests' own fixtures); the suite is a tiny python
stub that logs every call and its span, so the tests count what ran, in which order and how long it lived."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from timing_bound import bound
from pathlib import Path

import pytest

from tests import stood_clock
from tests.timing_bound import bound
from tests.test_agentops_merge import _commit, _git, _push_branch, _world
from tools.agentops import line_check as lc_module, merge as merge_module
from tools.agentops.line_check import CheckOutcome, LineCheck, checks_dir, read_status
from tools.agentops.util import now, pid_alive

STUB = """\
import os, pathlib, sys, time
d = pathlib.Path(sys.argv[1]); mode = sys.argv[2]; nap = float(sys.argv[3]); ids = sys.argv[4:]
here = sorted(p.name for p in pathlib.Path.cwd().glob("f?.py"))
with (d / "calls.txt").open("a") as f:
    f.write(("RE " + " ".join(ids) if ids else "FULL " + ",".join(here)) + chr(10))
with (d / "span.txt").open("a") as f:
    f.write("start " + ",".join(here) + " " + str(os.getpid()) + " " + str(time.time()) + chr(10))
time.sleep(nap)
with (d / "span.txt").open("a") as f:
    f.write("end " + ",".join(here) + " " + str(os.getpid()) + " " + str(time.time()) + chr(10))
if mode == "pass" or (mode == "flaky" and ids):
    print("1 passed"); sys.exit(0)
if mode == "silent":
    print("boom"); sys.exit(1)
print("FAILED tests/t.py::bad - boom")
print("1 failed, 2 passed in 0.1s")
sys.exit(1)
"""

_DEAD_PID = 2_000_000_000


@pytest.fixture(autouse=True)
def _protect(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_auto_out")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_auto.log")
    # tmp_path itself contains "pytest-of-<user>": only `-m pytest` marks a pytest command here
    monkeypatch.setattr(merge_module, "_PYTEST_RE", re.compile(r"-m pytest"))


class Rig:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bare, self.checkout = _world(tmp_path)
        stub = tmp_path / "stub.py"
        stub.write_text(STUB, encoding="utf-8")
        self.stub = stub
        self.dir = tmp_path / "stubdir"
        self.dir.mkdir()
        self.lock = tmp_path / "merge.lock"
        self.out = tmp_path / "out"
        self.checks: list[LineCheck] = []
        self.seq = 0

    def cmd(self, mode: str, nap: float = 0.0) -> str:
        return f'"{sys.executable}" "{self.stub}" "{self.dir}" {mode} {nap}'

    def branch(self, n: int) -> str:
        _push_branch(self.bare, self.tmp, f"w{n}", f"feat{n}", f"f{n}.py", f"x = {n}\n")
        _git("fetch", "-q", "origin", cwd=self.checkout)
        return _git("rev-parse", f"origin/feat{n}", cwd=self.checkout).stdout.strip()

    def ticket(self, suite: str, *, pid: int | None = None, info: dict | None = None) -> str:
        q = self.lock.with_name(self.lock.name + ".queue")
        q.mkdir(parents=True, exist_ok=True)
        self.seq += 1
        name = f"{time.time_ns():020d}-{os.getpid() if pid is None else pid}-{self.seq}"
        body = info if info is not None else {
            "kind": "merge", "branch": f"b{self.seq}", "suite": suite, "remote": "origin", "main": "main",
            "cwd": str(self.checkout.resolve())}
        (q / name).write_text(json.dumps(body), encoding="utf-8")
        time.sleep(0.002)  # distinct time_ns names
        return name

    def check(self, n: int, suite: str, ticket: str | None = None) -> LineCheck:
        sha = self.branch(n)
        name = ticket or self.ticket(suite)
        c = LineCheck(self.checkout, self.lock, name, f"feat{n}", sha, suite, suite_shared=(),
                      output_dir=self.out, retry_interval=0.0)
        self.checks.append(c)
        return c

    def calls(self) -> list[str]:
        f = self.dir / "calls.txt"
        return f.read_text().splitlines() if f.exists() else []

    def spans(self) -> list[list[str]]:
        f = self.dir / "span.txt"
        return [ln.split() for ln in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    for c in r.checks:
        c.stop()


def _drive(checks, until, timeout: float | None = None, holder_live: bool = True, sample=None):
    """Poll every check in order until ``until()``; returns the outcomes seen as ``{index: outcome}``."""
    seen: dict[int, CheckOutcome] = {}
    # each check = worktree prepare + stub, one after another (~13-22 s for three on a quiet PC): the deadline follows
    # the machine load like the other bounds here (#844), 90 s floor; play time is not counted (#779)
    started = time.time()
    limit = bound(90.0, 600.0) if timeout is None else timeout
    while not stood_clock.expired(started, limit):
        for i, c in enumerate(checks):
            out = c.poll(holder_live)
            if out is not None:
                seen[i] = out
            if sample is not None:
                sample()
        if until():
            return seen
        time.sleep(0.05)
    raise AssertionError(f"timeout; states {[c.state for c in checks]}")


def _final(c: LineCheck) -> bool:
    return c.state in lc_module.FINAL_STATES


def test_row1_always_failing_test_is_red_after_the_rerun_alone(rig):
    c = rig.check(1, rig.cmd("always"))
    seen = _drive([c], lambda: _final(c))
    out = seen[0]
    assert out.red and out.ids == ["tests/t.py::bad"], out
    assert "tests/t.py::bad" in out.message
    assert c.state == "red" and c.poll() is None  # the outcome is returned once
    st = read_status(rig.lock, c.ticket)
    assert st["state"] == "red" and st["ids"] == ["tests/t.py::bad"] and st["branch"] == "feat1"
    assert st["pid"] is None and st["since"]
    assert rig.calls() == ["FULL f1.py", "RE tests/t.py::bad"]
    path = Path(out.output_path)
    assert path.parent == rig.out and "-check-feat1.out" in path.name
    assert path.read_text(encoding="utf-8").count("FAILED tests/t.py::bad") == 2
    assert not (checks_dir(rig.lock) / "seat").exists()
    assert set(st) == {"state", "pid", "branch", "since", "ids"}


def test_row2_test_that_passes_alone_leaves_green_and_no_outcome(rig):
    c = rig.check(1, rig.cmd("flaky"))
    seen = _drive([c], lambda: _final(c))
    assert seen == {} and c.state == "green" and c.outcome is None
    assert read_status(rig.lock, c.ticket)["state"] == "green"
    assert rig.calls() == ["FULL f1.py", "RE tests/t.py::bad"]
    assert not (checks_dir(rig.lock) / "seat").exists()


def test_red_without_a_failed_id_is_skipped_never_red(rig):
    c = rig.check(1, rig.cmd("silent"))
    seen = _drive([c], lambda: _final(c))
    assert seen == {} and c.state == "skipped"
    assert read_status(rig.lock, c.ticket)["state"] == "skipped"
    assert rig.calls() == ["FULL f1.py"]


def test_row3_stop_mid_run_kills_the_child_and_frees_the_seat(rig):
    c = rig.check(1, rig.cmd("pass", 60))
    _drive([c], lambda: c.state == "running" and any(s[0] == "start" for s in rig.spans()))
    stub_pid = int(next(s for s in rig.spans() if s[0] == "start")[2])
    assert pid_alive(stub_pid) and pid_alive(c.child_pid)
    assert read_status(rig.lock, c.ticket)["state"] == "running"
    assert (checks_dir(rig.lock) / "seat").exists()
    shell_pid = c.child_pid
    t0 = time.time()
    c.stop()
    elapsed = time.time() - t0
    bound_s = bound(5.0, 33.0)  # max(floor, factor x CPU spin) (#826)
    assert elapsed < bound_s, (elapsed, bound_s)
    deadline = time.time() + 5
    while time.time() < deadline and (pid_alive(stub_pid) or pid_alive(shell_pid)):
        time.sleep(0.05)
    assert not pid_alive(stub_pid) and not pid_alive(shell_pid)
    assert c.state == "stopped" and read_status(rig.lock, c.ticket)["state"] == "stopped"
    assert not (checks_dir(rig.lock) / "seat").exists()
    c.stop()  # idempotent
    assert c.poll() is None and c.state == "stopped"
    c.cleanup()
    assert read_status(rig.lock, c.ticket) is None


def test_stop_during_preparation_frees_the_seat_and_starts_nothing(rig):
    c = rig.check(1, rig.cmd("pass", 5))
    c.poll(True)
    assert c.state == "preparing"
    c.stop()
    # the preparation thread (git merge-tree, worktree) ends and releases the seat: how long it takes depends on
    # the machine load (line_check.py:279-285 defers the free to that thread), so wait with a deadline
    deadline = time.time() + bound(10.0, 200.0)
    while time.time() < deadline and (checks_dir(rig.lock) / "seat").exists():
        time.sleep(0.05)
    assert c.poll(True) is None and c.child_pid is None and c.state == "stopped"
    assert not (checks_dir(rig.lock) / "seat").exists()
    assert rig.calls() == []


def test_row4_three_waiters_one_check_at_a_time_front_first(rig):
    suite = rig.cmd("pass", 1.0)
    tickets = [rig.ticket(suite) for _ in range(3)]
    cs = [rig.check(n, suite, tickets[n - 1]) for n in (1, 2, 3)]
    peak = [0]
    orders: list[str] = []

    def sample():
        alive = [c for c in cs if c.child_pid is not None and pid_alive(c.child_pid)]
        peak[0] = max(peak[0], len(alive))
        running = [i for i, c in enumerate(cs) if c.state in ("preparing", "running")]
        assert len(running) <= 1, [c.state for c in cs]
        for i in running:
            if i not in orders:
                orders.append(i)

    _drive(cs, lambda: all(_final(c) for c in cs), sample=sample)
    assert peak[0] == 1
    assert orders == [0, 1, 2]
    assert [c.state for c in cs] == ["green"] * 3
    starts = [s for s in rig.spans() if s[0] == "start"]
    assert [s[1] for s in starts] == ["f1.py", "f2.py", "f3.py"]
    spans = rig.spans()  # start/end alternate: no two stubs ever overlapped
    assert [s[0] for s in spans] == ["start", "end"] * 3


def test_row5_no_live_holder_starts_nothing(rig):
    c = rig.check(1, rig.cmd("pass"))
    assert c.should_check(False) is False and c.should_check(True) is True
    for _ in range(20):
        assert c.poll(holder_live=False) is None
        time.sleep(0.02)
    assert c.state == "idle" and c.child_pid is None
    assert rig.calls() == [] and not checks_dir(rig.lock).exists()


def test_row6_dead_seat_owner_is_taken_over(rig):
    checks_dir(rig.lock).mkdir(parents=True)
    (checks_dir(rig.lock) / "seat").write_text(
        json.dumps({"pid": _DEAD_PID, "ticket": "gone", "started": now()}), encoding="utf-8")
    c = rig.check(1, rig.cmd("pass"))
    _drive([c], lambda: _final(c))
    assert c.state == "green" and rig.calls() == ["FULL f1.py"]


def test_a_live_seat_owner_blocks_the_check(rig):
    checks_dir(rig.lock).mkdir(parents=True)
    (checks_dir(rig.lock) / "seat").write_text(
        json.dumps({"pid": os.getpid(), "ticket": "other", "started": now()}), encoding="utf-8")
    c = rig.check(1, rig.cmd("pass"))
    for _ in range(15):
        assert c.poll(True) is None
        time.sleep(0.02)
    assert c.state == "waiting" and rig.calls() == []
    assert json.loads((checks_dir(rig.lock) / "seat").read_text())["ticket"] == "other"
    c.stop()  # never frees a seat that is another ticket's
    assert (checks_dir(rig.lock) / "seat").exists()
    assert read_status(rig.lock, c.ticket)["state"] == "stopped"


def test_row6_merge_conflict_is_skipped_never_red(rig):
    _push_branch(rig.bare, rig.tmp, "wc", "featc", "README.md", "branch side\n")
    _git("fetch", "-q", "origin", cwd=rig.checkout)
    sha = _git("rev-parse", "origin/featc", cwd=rig.checkout).stdout.strip()
    _commit(rig.checkout, "README.md", "main side\n", "main moves")  # the branch changed README.md off the old main; local main changes it too
    suite = rig.cmd("always")
    c = LineCheck(rig.checkout, rig.lock, rig.ticket(suite), "featc", sha, suite, suite_shared=(),
                  output_dir=rig.out, retry_interval=0.0)
    rig.checks.append(c)
    seen = _drive([c], lambda: _final(c))
    assert seen == {} and c.state == "skipped" and "conflict" in c.message
    assert read_status(rig.lock, c.ticket)["state"] == "skipped"
    assert rig.calls() == [] and not (checks_dir(rig.lock) / "seat").exists()


def test_front_first_reads_the_older_tickets_of_the_same_line_only(rig):
    suite = rig.cmd("pass")
    other_line = rig.ticket(suite, info={"kind": "merge", "branch": "x", "suite": "another suite",
                                         "remote": "origin", "main": "main", "cwd": str(rig.checkout.resolve())})
    not_merge = rig.ticket(suite, info={"kind": "commit", "needs_suite": False})
    dead = rig.ticket(suite, pid=_DEAD_PID)
    older = rig.ticket(suite)  # same line, live pid, no status: blocks
    c = rig.check(1, suite)
    c.poll(True)
    assert c.state == "waiting" and rig.calls() == []
    lc_module._write_atomic(lc_module.status_path(rig.lock, older), json.dumps({"state": "running"}))
    c.poll(True)
    assert c.state == "waiting"
    lc_module._write_atomic(lc_module.status_path(rig.lock, older), json.dumps({"state": "stopped"}))
    _drive([c], lambda: _final(c))
    assert c.state == "green" and rig.calls() == ["FULL f1.py"]
    assert {other_line, not_merge, dead} and read_status(rig.lock, other_line) is None


def test_the_merges_own_selection_and_worker_helpers_shape_the_command(rig, monkeypatch):
    base_cmd = rig.cmd("pass")
    seen: dict = {}

    def plan(cwd, base, sha, run_cmd, output_path):
        seen["plan"] = (base, sha, run_cmd)
        return run_cmd, "selected 1 of 9: stub", False

    def with_workers(run_cmd, is_pytest, suite_dir):
        seen["workers"] = (is_pytest, Path(suite_dir).name)
        return run_cmd, 3, "workers 3: stub"

    monkeypatch.setattr(merge_module, "_is_pytest_command", lambda cmd: True)
    monkeypatch.setattr(merge_module, "_augmented_suite_cmd", lambda cmd: cmd)
    monkeypatch.setattr(merge_module, "resolve_select_tests", lambda: True)
    monkeypatch.setattr(merge_module, "_plan_selection", plan)
    monkeypatch.setattr(merge_module, "_with_workers", with_workers)
    c = rig.check(1, base_cmd)
    _drive([c], lambda: _final(c))
    assert c.state == "green"
    assert seen["workers"] == (True, "check")  # its own standing worktree, never the merge suite's
    base = _git("rev-parse", "main", cwd=rig.checkout).stdout.strip()
    assert seen["plan"][0] == base and seen["plan"][2] == base_cmd
    assert Path(c.output_path).read_text(encoding="utf-8").splitlines()[:2] == ["selected 1 of 9: stub", "workers 3: stub"]
    assert (rig.checkout / ".claude" / "worktrees" / "check").is_dir()
    assert not (rig.checkout / ".claude" / "worktrees" / "merge-suite").exists()


def test_an_empty_selection_runs_no_test_and_is_green(rig, monkeypatch):
    monkeypatch.setattr(merge_module, "_is_pytest_command", lambda cmd: True)
    monkeypatch.setattr(merge_module, "_augmented_suite_cmd", lambda cmd: cmd)
    monkeypatch.setattr(merge_module, "resolve_select_tests", lambda: True)
    monkeypatch.setattr(merge_module, "_plan_selection",
                        lambda cwd, base, sha, run_cmd, out: (run_cmd, "selected 0 of 9: nothing affected", True))
    c = rig.check(1, rig.cmd("always"))
    _drive([c], lambda: _final(c))
    assert c.state == "green" and rig.calls() == []


def test_a_check_output_does_not_break_the_prune_order(rig):
    out = rig.out
    out.mkdir()
    names = ["20261010T100000-000001-a.out", "20261010T100001-000002-check-b.out", "20261010T100002-000003-c.out"]
    for n in names:
        (out / n).write_text("x")
    merge_module._prune_suite_outputs(keep=2, output_dir=out)
    assert sorted(p.name for p in out.glob("*.out")) == names[1:]
