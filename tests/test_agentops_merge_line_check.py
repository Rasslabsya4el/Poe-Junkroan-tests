"""#765 unit 2: a waiter checks its own branch while it waits behind a live holder (the hook in
``MergeLock._acquire``, ``merge._LineCheckHook``). Real ``run_merge`` calls in threads, stub suites, no PoB.

The stub suite logs every call (``FULL <files> @<worktree name>`` / ``RE <ids> @...``) and every pid; the
holder's first suite waits for the test's release file (its "30 min", capped), a branch holding ``b.py`` fails every run, and the
check of a branch holding ``u.py`` sleeps 60 s (a check that is still running when the holder ends)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from timing_bound import bound

import pytest

from tests.test_agentops_merge import (
    NO_LOAD_REACHES, _git, _push_branch, _protect_real_agentops_var, _ThreadCapture, _world,
    _green_default_commit_suite,
)
from tools.agentops import detach, line_check, merge as merge_module
from tools.agentops.dispatch import GhCli
from tools.agentops.merge import MergeLock, run_merge
from tools.agentops.util import now, pid_alive

_ = (_protect_real_agentops_var, _green_default_commit_suite)  # autouse fixtures, imported so they apply here

HOLDER_CAP = 300.0   # the holder's "30 min" suite ends when the test releases it, at the latest after this

STUB = """\
import os, pathlib, sys, time
d = pathlib.Path(sys.argv[1]); ids = sys.argv[2:]
cwd = pathlib.Path.cwd(); tag = cwd.name
here = sorted(p.name for p in cwd.glob("?.py"))
with (d / "calls.txt").open("a") as f:
    f.write((("RE " + " ".join(ids)) if ids else ("FULL " + ",".join(here))) + " @" + tag + chr(10))
with (d / "pids.txt").open("a") as f:
    f.write(tag + " " + ",".join(here) + " " + str(os.getpid()) + chr(10))
if not ids and tag != "check" and not (d / "napped").exists():
    (d / "napped").write_text("x")
    end = time.time() + %(cap)s
    while not (d / "release").exists() and time.time() < end:
        time.sleep(0.05)
if not ids and tag == "check" and "u.py" in here:
    time.sleep(60)
if "b.py" in here:
    if ids and (d / "flaky").exists():
        print("1 passed"); sys.exit(0)
    print("FAILED tests/t.py::bad - boom")
    print("1 failed, 2 passed in 0.1s")
    sys.exit(1)
print("1 passed")
"""


@pytest.fixture(autouse=True)
def _stub_is_not_pytest(monkeypatch):
    # tmp_path itself contains "pytest-of-<user>": only `-m pytest` marks a pytest command here
    monkeypatch.setattr(merge_module, "_PYTEST_RE", re.compile(r"-m pytest"))


class Scenario:
    """A holder ``h`` whose suite naps, then waiters queued behind it one by one (each queued before the
    next starts), all joined at the end."""

    def __init__(self, tmp: Path, *, disabled: bool = False, monkeypatch=None):
        self.tmp = tmp
        self.bare, self.checkout = _world(tmp)
        self.dir = tmp / "stubdir"
        self.dir.mkdir()
        stub = tmp / "stub.py"
        stub.write_text(STUB % {"cap": HOLDER_CAP}, encoding="utf-8")
        self.suite = f'"{sys.executable}" "{stub}" "{self.dir}"'
        self.lock = tmp / "merge.lock"
        self.log = tmp / "merge.log"
        self.out = tmp / "suite_out"
        self.results: dict = {}
        self.ends: dict[str, float] = {}
        self.threads: list[tuple[threading.Thread, _ThreadCapture]] = []
        if disabled:
            monkeypatch.setattr(merge_module, "_make_line_check_hook", lambda *a, **k: None)

    def branch(self, name: str, file: str) -> None:
        _push_branch(self.bare, self.tmp, f"w_{name}", name, file, f"{name} = 1\n")
        _git("fetch", "-q", "origin", cwd=self.checkout)

    def _start(self, name: str, issues=()) -> None:
        def job():
            try:
                self.results[name] = run_merge(f"origin/{name}", self.suite, cwd=self.checkout, lock_path=self.lock,
                                               lock_timeout=NO_LOAD_REACHES, merge_log_path=self.log,
                                               suite_output_dir=self.out, issues=issues)
            finally:
                self.ends[name] = time.monotonic()
        cap = _ThreadCapture(job)
        t = threading.Thread(target=cap)
        t.start()
        self.threads.append((t, cap))

    def start_holder(self) -> None:
        self._start("h")
        self.wait(lambda: self.suite_fulls(), "the holder's suite to start")

    def add_waiter(self, name: str, issues=()) -> None:
        n = len(self.threads)
        self._start(name, issues)
        queue = self.lock.with_name(self.lock.name + ".queue")
        self.wait(lambda: queue.exists() and len(list(queue.iterdir())) >= n, f"{name} queued")

    def wait(self, cond, what: str, timeout: float = 300.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cond():
                return
            time.sleep(0.02)
        raise AssertionError(f"timed out waiting for {what}")

    def release(self) -> None:
        """The holder's suite ends now."""
        (self.dir / "release").write_text("x")

    def checked(self, branch: str) -> bool:
        """The waiter's check of ``branch`` has written a final status (its result is there)."""
        d = line_check.checks_dir(self.lock)
        for f in (list(d.glob("*.json")) if d.exists() else []):
            try:
                st = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if st.get("branch") == branch and st.get("state") in ("green", "red"):
                return True
        return False

    def join(self) -> None:
        for t, _cap in self.threads:
            t.join(timeout=NO_LOAD_REACHES)
            assert not t.is_alive(), "a merge hung past its bound"
        for _t, cap in self.threads:
            cap.reraise()

    def calls(self) -> list[str]:
        f = self.dir / "calls.txt"
        return f.read_text().splitlines() if f.exists() else []

    def suite_fulls(self) -> list[str]:
        return [ln for ln in self.calls() if ln.startswith("FULL") and not ln.endswith("@check")]

    def check_calls(self) -> list[str]:
        return [ln for ln in self.calls() if ln.endswith("@check")]

    def pids(self, tag: str, files: str) -> list[int]:
        f = self.dir / "pids.txt"
        rows = [ln.split() for ln in f.read_text().splitlines()] if f.exists() else []
        return [int(r[2]) for r in rows if r[0] == tag and files in r[1].split(",")]

    def log_lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def main_tree(self) -> str:
        return _git("rev-parse", "main^{tree}", cwd=self.bare).stdout.strip()


def _gone(pids: list[int]) -> bool:
    return all(not pid_alive(p) for p in pids)


# -- rows 1 and 6: a branch with an always-failing test leaves the line before the holder ends ---------

def test_row1_failing_branch_leaves_before_the_holder_ends_and_row6_hands_back(tmp_path):
    s = Scenario(tmp_path)
    s.branch("h", "h.py")
    s.branch("b", "b.py")
    s.start_holder()
    s.add_waiter("b", issues=[7])
    s.wait(lambda: "b" in s.results, "b to leave the line on its check")
    time.sleep(2.0)      # b is out well before the holder's suite ends
    s.release()
    s.join()

    b, h = s.results["b"], s.results["h"]
    assert not b.ok and b.reason == "red-on-branch" and not b.batched, b.render()
    assert b.failed_tests == ["tests/t.py::bad"] and b.failed_count == 1 and b.suite_runs == 0
    assert "(the output: " in b.message and Path(b.suite_output_path).exists()
    assert s.ends["b"] < s.ends["h"] - 1.0, "B must leave before the holder's suite ends"
    assert h.ok and h.pushed
    # the next batch never contained B: the only suite round of the line is the holder's own
    assert len(s.suite_fulls()) == 1 and all("b.py" not in ln for ln in s.suite_fulls()), s.suite_fulls()
    # the check ran the branch and then re-ran the failed id alone
    assert s.check_calls()[0].startswith("FULL b.py") and s.check_calls()[-1] == "RE tests/t.py::bad @check"
    lines = s.log_lines()
    assert any("| origin/b | red-on-branch | " in ln and "1 failed" in ln for ln in lines), lines
    assert _gone(s.pids("check", "b.py"))
    assert not list((s.lock.with_name(s.lock.name + ".queue")).iterdir())

    # row 6: the detached runner hands the result back to --issue 7
    text = f"{b.render()}\n{merge_module._stats_line(time.monotonic() - 5, {}, b)}"
    calls = []

    def fake(args, stdin):
        calls.append((args, stdin))
        if args[:2] == ["issue", "view"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"state": "OPEN", "labels": [], "assignees": []}), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    gh = GhCli(repo="o/r", cwd=tmp_path, runner=fake)
    code = f"import sys; print({text!r}); sys.exit(1)"
    rc = detach.run_and_record([sys.executable, "-c", code, "--cwd", str(s.checkout), "--issue", "7"],
                               tmp_path / "r.json", "merge", "b", merge_log=tmp_path / "handback.log", gh=gh)
    assert rc == 1
    record = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert record["reason"] == "red-on-branch" and record["failed"] == 1
    writes = [c for c in calls if c[0][:2] != ["issue", "view"]]
    comments = [c for c in writes if c[0][:2] == ["issue", "comment"]]
    assert len(comments) == 1 and comments[0][1].splitlines()[0] == "<!-- merge result -->"
    assert "did not land (red-on-branch)" in comments[0][1] and "tests/t.py::bad" in comments[0][1]
    assert any(c[0][:3] == ["issue", "edit", "7"] and c[0][-2:] == ["--add-label", "ready-for-agent"] for c in writes)


# -- row 2: the failing test passes when re-run alone: the branch stays and is batched -----------------

def test_row2_a_flaky_failure_stays_in_the_line_and_is_batched(tmp_path):
    s = Scenario(tmp_path)
    (s.dir / "flaky").write_text("x")
    for name, f in (("h", "h.py"), ("g", "g.py"), ("b", "b.py")):
        s.branch(name, f)
    s.start_holder()
    s.add_waiter("g")
    s.add_waiter("b")
    s.wait(lambda: s.checked("origin/b") or s.checked("b"), "the check of b to finish")
    s.release()
    s.join()

    assert all(r.ok for r in s.results.values()), {k: r.render() for k, r in s.results.items()}
    assert s.results["b"].batched and not s.results["g"].batched
    assert any(ln.startswith("FULL b.py") for ln in s.check_calls())
    assert "RE tests/t.py::bad @check" in s.check_calls()      # the check re-ran the failed id alone, green
    batch = [ln for ln in s.suite_fulls() if "b.py" in ln]
    assert len(batch) == 1 and "g.py" in batch[0], s.suite_fulls()


# -- row 3: a green check changes nothing in what the line runs -------------------------------------

def _green_run(tmp: Path, disabled: bool, monkeypatch):
    tmp.mkdir()
    s = Scenario(tmp, disabled=disabled, monkeypatch=monkeypatch)
    for name, f in (("h", "h.py"), ("g", "g.py"), ("k", "k.py")):
        s.branch(name, f)
    s.start_holder()
    s.add_waiter("g")
    s.add_waiter("k")
    if not disabled:
        s.wait(lambda: s.checked("origin/k") or s.checked("k"), "the check of k to finish")
    s.release()
    s.join()
    return s


def test_row3_green_waiters_are_batched_exactly_as_without_the_feature(tmp_path, monkeypatch):
    on = _green_run(tmp_path / "on", False, monkeypatch)
    off = _green_run(tmp_path / "off", True, monkeypatch)

    for s in (on, off):
        assert all(r.ok for r in s.results.values()), {k: r.render() for k, r in s.results.items()}
        assert len(s.suite_fulls()) == 2          # the holder's suite, then ONE batch suite for g and k
        assert "g.py" in s.suite_fulls()[1] and "k.py" in s.suite_fulls()[1]
        assert any("batch of 2" in ln and "pushed" in ln for ln in s.log_lines()), s.log_lines()
        assert sorted(r.batched for k, r in s.results.items() if k != "h") == [False, True]
    assert on.main_tree() == off.main_tree()
    assert len(on.check_calls()) >= 2 and off.check_calls() == []
    # the queue's checks are one at a time: the front waiter's check starts first
    assert on.check_calls()[0].startswith("FULL g.py")


# -- row 4: a check still running when the holder ends delays nothing and leaves no process ----------

def test_row4_an_unfinished_check_is_stopped_when_the_waiter_is_claimed(tmp_path):
    s = Scenario(tmp_path)
    for name, f in (("h", "h.py"), ("w", "w.py"), ("u", "u.py")):
        s.branch(name, f)
    s.start_holder()
    s.add_waiter("w")
    s.add_waiter("u")
    s.wait(lambda: s.pids("check", "u.py"), "U's check to run")
    assert not _gone(s.pids("check", "u.py")), "U's check must be alive while the holder runs"
    s.release()
    batch = s.lock.with_name(s.lock.name + ".batch")
    s.wait(lambda: batch.exists() and any(p.name.endswith(".claim") for p in batch.iterdir()), "the claim of U")
    claimed_at = time.monotonic()
    s.wait(lambda: _gone(s.pids("check", "u.py")), "U's check process to be gone", timeout=5.0)
    # bound = max(floor, factor x a CPU spin timed here) (#826)
    bound_s = bound(5.0, 33.0)
    assert time.monotonic() - claimed_at <= bound_s, f"{time.monotonic() - claimed_at:.2f}s, bound {bound_s:.1f}s"
    s.join()

    assert s.results["u"].ok and s.results["u"].batched and s.results["w"].ok
    assert abs(s.ends["u"] - s.ends["w"]) < 2.0, "the stopped check must not delay the claimed waiter"
    assert len([ln for ln in s.suite_fulls() if "u.py" in ln]) == 1
    time.sleep(1.0)
    assert _gone(s.pids("check", "u.py"))


# -- row 5: no live holder: no check at all, the branch holds the lock at once ----------------------

def test_row5_no_live_holder_starts_no_check(tmp_path, monkeypatch):
    built = []
    real = merge_module.LineCheck
    monkeypatch.setattr(merge_module, "LineCheck", lambda *a, **k: built.append(a) or real(*a, **k))
    s = Scenario(tmp_path)
    (s.dir / "napped").write_text("x")   # no nap: nobody waits behind this suite
    s.branch("h", "h.py")
    s._start("h")
    s.join()
    assert s.results["h"].ok and s.results["h"].pushed
    assert built == [] and s.check_calls() == []


# -- the hook protocol of the lock itself ------------------------------------------------------------

def test_hook_result_leaves_the_line_without_the_lock_and_removes_the_ticket(tmp_path):
    lock_path = tmp_path / "merge.lock"
    holder = MergeLock(lock_path)
    assert holder.acquire(NO_LOAD_REACHES) is None
    seen = []

    def hook(ticket, holder_live, claimed):
        seen.append((holder_live, claimed))
        return {"ok": False, "reason": "red-on-branch"} if len(seen) >= 3 else None

    waiter = MergeLock(lock_path)
    posted = waiter.acquire(30, ticket_info={"kind": "merge", "branch": "x", "cwd": "c"}, waiter_hook=hook)
    assert posted == {"ok": False, "reason": "red-on-branch"}
    assert seen == [(True, False)] * 3
    assert not list(lock_path.with_name(lock_path.name + ".queue").iterdir())
    assert not waiter._own and holder._own     # the waiter does not hold the lock
    holder.release()


def test_hook_sees_the_claim_and_a_claimed_waiter_cannot_leave(tmp_path):
    lock_path = tmp_path / "merge.lock"
    holder = MergeLock(lock_path)
    assert holder.acquire(NO_LOAD_REACHES) is None
    batch = lock_path.with_name(lock_path.name + ".batch")
    claims: list[bool] = []
    result = {}

    def hook(ticket, holder_live, claimed):
        claims.append(claimed)
        if not claimed:
            batch.mkdir(parents=True, exist_ok=True)       # a holder claims this waiter between two turns
            (batch / f"{ticket}.claim").write_text(json.dumps({"pid": os.getpid(), "started": now()}))
            return {"ok": False, "reason": "red-on-branch"}  # tries to leave while claimed: refused
        if claimed and not result:
            result["x"] = 1
            (batch / f"{ticket}.result").write_text(json.dumps({"ok": True, "reason": "pushed"}))
        return None

    waiter = MergeLock(lock_path)
    posted = waiter.acquire(30, ticket_info={"kind": "merge", "branch": "x", "cwd": "c"}, waiter_hook=hook)
    assert posted == {"ok": True, "reason": "pushed"}
    assert claims[0] is False and claims[-1] is True
    holder.release()
