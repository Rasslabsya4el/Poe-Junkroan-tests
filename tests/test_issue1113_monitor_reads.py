"""#1113 unit 1: the monitor's shared cache makes one `gh api graphql` read per window for tickets, from every caller.

Before: a caller that found a live collector on the lock waited 10 s (50 polls of 0.2 s) and then computed beside it,
without a lock. A tickets read longer than 10 s therefore came out as 2-3 reads 17 s apart (02:40:36 / :53 / 02:41:09,
2026-10-16). A waiter now waits for the holder's file, and the slow mode's closed-issue lists are read once per process.

Send-back (#1113 unit 1): the stale-lock limit and the waiter's deadline are per mode (`shared_limits`); a dead holder's
lock is stolen at once; at the deadline a waiter serves the holder's last file, else computes itself, and never raises.

No PoB, no network: `subprocess.run` is a counting fake of `gh`, the cache and the lock live in tmp_path. The second
caller is a thread: the lock is a file, so it is the same contract as a second collector process.

    python -m pytest -q -p no:faulthandler tests/test_issue1113_monitor_reads.py
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "mods" / "pob-slots" / "bin"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

import collect  # noqa: E402

REAL_SLEEP = time.sleep
REAL_TIME = time.time
# one empty GraphQL page: tickets() reads no issue, the merge line is absent
GRAPHQL_PAGE = json.dumps({"data": {"repository": {"issues": {
    "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}})


class FakeGh:
    """Counts the `gh api graphql` (tickets) and `gh issue list` (closed issues) reads; the closed list is split by
    its reader (`fetch_closed_issues` asks for closedAt, `issue_info` for stateReason). The merge line's command fails
    at once, so `_live_merge_branches` reads it as absent. `hold` runs inside a read, before it answers."""

    def __init__(self, hold=None):
        self.graphql = 0  # open-issue reads of tickets(); the closed read (#18) is `closed_graphql`
        self.closed_graphql = 0
        self.issue_list = 0
        self.closed_fetch = 0
        self.closed_info = 0
        self.hold = hold
        self.lock = threading.Lock()

    def __call__(self, cmd, *args, **kwargs):
        if cmd[:3] == ["gh", "api", "graphql"]:
            closed = any("states: [CLOSED]" in part for part in cmd)  # #18: the closed read is apart from the open one
            with self.lock:
                if closed:
                    self.closed_graphql += 1
                    return subprocess.CompletedProcess(cmd, 0, GRAPHQL_PAGE, "")
                self.graphql += 1
            if self.hold:
                self.hold()
            return subprocess.CompletedProcess(cmd, 0, GRAPHQL_PAGE, "")
        if cmd[:3] == ["gh", "issue", "list"]:
            fetch = any("closedAt" in part for part in cmd)  # the real argv is one "number,closedAt" element
            with self.lock:
                self.issue_list += 1
                if fetch:
                    self.closed_fetch += 1
                else:
                    self.closed_info += 1
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 1, "", "no merge line in this test")


class Polls:
    """Stands in for time.sleep: counts the waiter's polls and sleeps `real` seconds of real time. With `cap`, the
    (cap+1)-th poll raises: a waiter that never gives up is a red test, not a hang."""

    def __init__(self, real=0.001, cap=None):
        self.n = 0
        self.real = real
        self.cap = cap
        self.lock = threading.Lock()

    def __call__(self, seconds):
        with self.lock:
            self.n += 1
            n = self.n
        if self.cap is not None and n > self.cap:
            raise AssertionError(f"the waiter polled more than {self.cap} times and never gave up")
        REAL_SLEEP(self.real)


def _age(path, seconds):
    t = REAL_TIME() - seconds
    os.utime(path, (t, t))


def test_sequential_callers_in_one_window_make_one_graphql_read(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "CACHE_DIR", tmp_path / ".cache")
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    outs = [collect.shared_result("tickets", 170, collect.tickets) for _ in range(5)]
    assert gh.graphql == 1, f"5 calls inside one 3-minute window made {gh.graphql} tickets reads"
    assert len(set(outs)) == 1


def test_caller_arriving_while_a_collector_computes_waits_and_reads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "CACHE_DIR", tmp_path / ".cache")
    polls = Polls()
    monkeypatch.setattr(collect.time, "sleep", polls)
    entered = threading.Event()

    def hold():
        # the holder's read stays open until the waiter has polled 60 times (the old wait gave up at 50)
        entered.set()
        t0 = REAL_TIME()
        while polls.n < 60 and REAL_TIME() - t0 < 20:
            REAL_SLEEP(0.001)

    gh = FakeGh(hold=hold)
    monkeypatch.setattr(collect.subprocess, "run", gh)
    holder: dict = {}
    errors: list = []

    def collector():
        try:
            holder["text"] = collect.shared_result("tickets", 170, collect.tickets)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    thread = threading.Thread(target=collector, daemon=True)
    thread.start()
    assert entered.wait(10), "the holder never reached its read"
    waiter_text = collect.shared_result("tickets", 170, collect.tickets)
    thread.join(20)
    assert not thread.is_alive() and not errors, errors
    assert gh.graphql == 1, f"a waiter beside a live collector made the read again: {gh.graphql} tickets reads"
    assert polls.n >= 60, "the waiter gave up before the collector finished"
    assert waiter_text == holder["text"]


def test_closed_issue_list_is_read_once_per_slow_window(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "CACHE_DIR", tmp_path / ".cache")
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    for _ in range(4):
        collect.shared_result("slow", 590, collect.issue_info)
    assert gh.issue_list == 1, f"4 slow calls inside one 10-minute window read the closed list {gh.issue_list} times"


# ---- send-back (#1113 unit 1): per-mode limits, a dead holder, the deadline, the slow path


def test_dead_holder_lock_is_stolen_at_once_and_read_once(tmp_path, monkeypatch):
    """(a) a crashed holder left its lock 200 s old: older than tickets' stale limit (150 s), no live holder.
    The waiter steals it on its first look and makes exactly one read."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    monkeypatch.setattr(collect, "CACHE_DIR", cache)
    lock = cache / "shared-tickets.lock"
    lock.write_text("")
    _age(lock, 200)
    polls = Polls(real=0.01, cap=20)
    monkeypatch.setattr(collect.time, "sleep", polls)
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    text = collect.shared_result("tickets", 170, collect.tickets)
    assert gh.graphql == 1, f"a dead holder's lock made {gh.graphql} tickets reads"
    assert isinstance(json.loads(text), dict)
    assert not lock.exists(), "the stolen lock was not released after the read"
    assert polls.n == 0, f"the waiter polled {polls.n} times beside a dead holder's lock"


def test_deadline_with_a_live_looking_lock_reads_itself_and_raises_nothing(tmp_path, monkeypatch):
    """(b) a lock that looks live (touched every 50 ms, never released) and no file: at the deadline the waiter
    computes its own read, returns it, and leaves the lock alone."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    monkeypatch.setattr(collect, "CACHE_DIR", cache)
    monkeypatch.setattr(collect, "SHARED_LIMITS", {"tickets": 0.6}, raising=False)
    monkeypatch.setattr(collect, "SHARED_WAIT_MARGIN_S", 0.4, raising=False)
    lock = cache / "shared-tickets.lock"
    lock.write_text("")
    stop = threading.Event()

    def keep_alive():
        while not stop.is_set():
            _age(lock, 0)
            REAL_SLEEP(0.05)

    keeper = threading.Thread(target=keep_alive, daemon=True)
    keeper.start()
    monkeypatch.setattr(collect.time, "sleep", Polls(real=0.2, cap=30))  # the 1 s deadline is about 5 polls
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    try:
        text = collect.shared_result("tickets", 170, collect.tickets)
    finally:
        stop.set()
        keeper.join(5)
    assert gh.graphql == 1, f"the deadline read made {gh.graphql} tickets reads, expected 1"
    assert isinstance(json.loads(text), dict)
    assert lock.exists(), "a waiter released a lock it does not hold"


def test_deadline_serves_the_holders_last_file_without_a_read(tmp_path, monkeypatch):
    """(b2) at the deadline with the holder's last file on disk, the waiter serves that file and reads nothing."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    monkeypatch.setattr(collect, "CACHE_DIR", cache)
    monkeypatch.setattr(collect, "SHARED_LIMITS", {"tickets": 0.6}, raising=False)
    monkeypatch.setattr(collect, "SHARED_WAIT_MARGIN_S", 0.4, raising=False)
    last = '{"issues": {}, "last": true}'
    shared = cache / "shared-tickets.json"
    shared.write_text(last, encoding="utf-8")
    _age(shared, 1000)  # not fresh: the 170 s window is over
    lock = cache / "shared-tickets.lock"
    lock.write_text("")
    stop = threading.Event()

    def keep_alive():
        while not stop.is_set():
            _age(lock, 0)
            REAL_SLEEP(0.05)

    keeper = threading.Thread(target=keep_alive, daemon=True)
    keeper.start()
    monkeypatch.setattr(collect.time, "sleep", Polls(real=0.2, cap=30))
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    try:
        text = collect.shared_result("tickets", 170, collect.tickets)
    finally:
        stop.set()
        keeper.join(5)
    assert text == last
    assert gh.graphql == 0, f"the deadline read the tickets again ({gh.graphql} reads) instead of serving the file"


def test_fast_mode_has_the_short_limits():
    """(c) the stale limit and the waiter's deadline (stale + a few seconds) per mode; fast keeps its 90 s."""
    assert collect.shared_limits("fast") == (90, 95)
    assert collect.shared_limits("tickets") == (150, 155)
    assert collect.shared_limits("orch") == (200, 205)
    assert collect.shared_limits("slow") == (330, 335)


def test_slow_reads_the_closed_lists_once_per_process_over_two_calls(tmp_path, monkeypatch):
    """(d) two consecutive `slow()` calls in one process, the real `slow()` and the real `monitor_dashboard.panel_cost`:
    only the file scans are stubbed (no transcripts read), so `fetch_closed_issues` and `issue_info` run their own
    `gh issue list` reads. Each closed list must be read once in the process."""
    import tools.agentops.monitor_dashboard as md

    tm = md.token_meter
    cache = tmp_path / ".cache"
    monkeypatch.setattr(collect, "CACHE_DIR", cache)
    monkeypatch.setattr(collect, "_settings_module", lambda key: md if key == "monitor_dashboard" else None)
    monkeypatch.setattr(collect, "_closed_by_session", lambda: ({}, set()))
    monkeypatch.setattr(tm, "scan_projects_dir", lambda *a, **k: tm.ScanResult(turns=[], compactions=0))
    monkeypatch.setattr(tm, "discover_main_transcripts", lambda *a, **k: [])
    # `slow()` wraps these in a memo on the module; monkeypatch restores the module's own functions at teardown
    monkeypatch.setattr(tm, "fetch_closed_issues", tm.fetch_closed_issues)
    # one process = one memo of the closed list; a test starts from a fresh one, as a new process would
    monkeypatch.setattr(collect, "_ISSUE_INFO_ONCE", collect._memo(collect.issue_info), raising=False)
    gh = FakeGh()
    monkeypatch.setattr(collect.subprocess, "run", gh)
    first = collect.slow()
    second = collect.slow()
    assert gh.closed_fetch == 1, f"two slow() calls read the closed list through fetch_closed_issues {gh.closed_fetch} times"
    assert gh.closed_info == 1, f"two slow() calls read the closed list through issue_info {gh.closed_info} times"
    assert "cost_day" in first and "cost_day" in second, "the slow() path did not reach panel_cost"
