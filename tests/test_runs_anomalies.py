"""junkroan.runs.anomalies (issue #57): anomaly detection + the on-demand keymaster launch.

No real `claude.exe`, SSH or PoB: the launcher, the host probe and the budget check are all
faked. `var/anomalies.json` is redirected to `tmp_path` in every test.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


# -- fakes ------------------------------------------------------------------------------------

class FakeKeymasterCli:
    """Records every `start`; `list_sessions` reports whatever the test sets."""

    def __init__(self) -> None:
        self.started: list[tuple[an.Anomaly, list[str]]] = []
        self._sessions: list[dict] = []
        self._next_id = 1
        self.ended: list[dict] = []
        self.end_result = True

    def end(self, session: dict) -> bool:
        self.ended.append(dict(session))
        if self.end_result:
            self._sessions = [s for s in self._sessions if s.get("id") != session.get("id")]
        return self.end_result

    def set_row(self, state: str, status: str) -> None:
        self._sessions = [{"name": "keymaster: job_failed j-1", "id": "km-live",
                           "state": state, "status": status}]

    def list_sessions(self) -> list[dict]:
        return list(self._sessions)

    def start(self, anomaly: an.Anomaly) -> tuple[str, list[str]]:
        session_id = f"km-{self._next_id}"
        self._next_id += 1
        cmd = an.build_command(anomaly, "claude.exe")
        self.started.append((anomaly, cmd))
        self._sessions.append({"name": f"keymaster: {anomaly.kind} {anomaly.target}",
                               "id": session_id, "state": "working"})
        return session_id, cmd

    # test helpers
    def finish_all(self) -> None:
        self._sessions = []

    def set_live(self, *, kind: str = "job_failed", target: str = "j-1", state: str = "working") -> None:
        self._sessions = [{"name": f"keymaster: {kind} {target}", "id": "km-live", "state": state}]


def make_job(store: Store, *, rc: int, issue: int = 1) -> object:
    job = store.submit(host="pc", priority="P1", tag=f"t-{rc}-{issue}", cmd="echo x", issue=issue)
    store.start(job.id, out=str(ROOT), pid=1)
    return store.end(job.id, rc=rc)


def make_guard(tmp_path: Path, *, launcher: FakeKeymasterCli | None = None,
              host_prober=None, budget_checker=None, clock=time.time,
              probe_interval: float = 0.0) -> tuple[an.AnomalyGuard, FakeKeymasterCli]:
    launcher = launcher if launcher is not None else FakeKeymasterCli()
    guard = an.AnomalyGuard(
        path=tmp_path / "anomalies.json", launcher=launcher, host_prober=host_prober,
        budget_checker=budget_checker, clock=clock, log=lambda message: None,
        probe_interval=probe_interval,
    )
    return guard, launcher


# -- detection (pure) -------------------------------------------------------------------------

def test_detect_job_failed_on_a_failed_job(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=48)
    anomaly = an.detect_job_failed(job)
    assert anomaly is not None
    assert anomaly.kind == "job_failed" and anomaly.key == f"job_failed:{job.id}"
    assert "rc 1" in anomaly.detail


def _cmd_job(tmp_path: Path, cmd: str, rc: int | None):
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t-cmd", cmd=cmd, issue=501)
    store.start(job.id, out=str(ROOT), pid=1)
    return store.end(job.id, rc=rc)


PYTEST_C = "python -c \"import sys, pytest; sys.exit(pytest.main(['tests/x.py', '-q']))\""


@pytest.mark.parametrize("cmd", ["python -m pytest tests/x.py -q", PYTEST_C, "pytest tests/x.py",
                                 "C:\\py\\Scripts\\pytest.exe tests/x.py"])
def test_pytest_rc1_is_the_reading(tmp_path: Path, cmd: str) -> None:
    assert an.is_pytest_command(cmd)
    assert an.detect_job_failed(_cmd_job(tmp_path, cmd, 1)) is None


@pytest.mark.parametrize("rc", [2, 3, 4, 5, None])
def test_pytest_other_rc_stays_an_anomaly(tmp_path: Path, rc) -> None:
    assert an.detect_job_failed(_cmd_job(tmp_path, "python -m pytest tests/x.py -q", rc)) is not None


def test_non_pytest_rc1_stays_an_anomaly(tmp_path: Path) -> None:
    cmd = "python scripts/benchmark.py --set smoke"
    assert not an.is_pytest_command(cmd)
    assert an.detect_job_failed(_cmd_job(tmp_path, cmd, 1)) is not None


def test_is_pytest_command_never_raises() -> None:
    assert an.is_pytest_command("") is False
    assert an.is_pytest_command(None) is False  # type: ignore[arg-type]
    assert isinstance(an.is_pytest_command('python -c "unterminated'), bool)


@pytest.mark.parametrize("rc,expected_none", [(1, True), (3, True), (None, False)])
def test_rc_is_reading_job(tmp_path: Path, rc, expected_none: bool) -> None:
    import dataclasses

    job = dataclasses.replace(_cmd_job(tmp_path, "python scripts/benchmark.py", rc), rc_is_reading=True)
    assert (an.detect_job_failed(job) is None) is expected_none


def test_detect_job_failed_is_none_for_a_clean_job(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=0)
    assert an.detect_job_failed(job) is None


def test_detect_job_stuck_on_a_stale_out_file(tmp_path: Path) -> None:
    out = tmp_path / "stale.out"
    out.write_text("still going\n", encoding="utf-8")
    old_mtime = time.time() - 3600
    import os

    os.utime(out, (old_mtime, old_mtime))
    anomaly = an.detect_job_stuck("j-9", out, now=time.time())
    assert anomaly is not None and anomaly.kind == "job_stuck" and anomaly.key == "job_stuck:j-9"


def test_detect_job_stuck_is_none_for_a_fresh_out_file(tmp_path: Path) -> None:
    out = tmp_path / "fresh.out"
    out.write_text("just wrote\n", encoding="utf-8")
    assert an.detect_job_stuck("j-9", out, now=time.time()) is None


def test_detect_host_unreachable_needs_the_full_span() -> None:
    assert an.detect_host_unreachable("laptop", None) is None
    assert an.detect_host_unreachable("laptop", 9 * 60) is None
    anomaly = an.detect_host_unreachable("laptop", 10 * 60)
    assert anomaly is not None and anomaly.key == "host_unreachable:laptop"


def test_detect_budget_unreadable_has_a_stable_key() -> None:
    anomaly = an.detect_budget_unreadable("BOM")
    assert anomaly.key == "budget_unreadable:machine_budget"


# -- issue #76: lease_overrun (a slot or a reservation held past its allowance) ----------------

def _slot_row(*, role: str = "other", pid: int = 4242, slot: int = 3, age_seconds: float = 0.0) -> dict:
    return {"slot": slot, "pid": pid, "role": role, "cmd": "pytest -q", "started": "2026-09-26T10:00:00",
            "age_seconds": age_seconds}


def test_detect_lease_overrun_slot_over_the_threshold(tmp_path: Path) -> None:
    row = _slot_row(age_seconds=an.LEASE_OVERRUN_SECONDS + 30)
    anomaly = an.detect_lease_overrun_slot(row, now=time.time())
    assert anomaly is not None
    assert anomaly.kind == "lease_overrun"
    assert anomaly.key == "lease_overrun:slot:4242:2026-09-26T10:00:00"
    assert anomaly.pid == 4242 and anomaly.issue is None
    assert anomaly.held_for == an.LEASE_OVERRUN_SECONDS + 30


def test_detect_lease_overrun_slot_under_the_threshold_is_none() -> None:
    row = _slot_row(age_seconds=an.LEASE_OVERRUN_SECONDS - 1)
    assert an.detect_lease_overrun_slot(row, now=time.time()) is None


def test_detect_lease_overrun_slot_ignores_the_queue_role() -> None:
    row = _slot_row(role="queue", age_seconds=an.LEASE_OVERRUN_SECONDS + 999)
    assert an.detect_lease_overrun_slot(row, now=time.time()) is None


def test_detect_lease_overrun_reservation_past_expires(tmp_path: Path) -> None:
    now = time.time()
    expires = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - an.LEASE_OVERRUN_SECONDS - 30))
    entry = {"id": 7, "host": "pc", "slots": 2, "issue": 61, "expires": expires}
    anomaly = an.detect_lease_overrun_reservation(entry, now=now)
    assert anomaly is not None
    assert anomaly.kind == "lease_overrun" and anomaly.key == "lease_overrun:reservation:7"
    assert anomaly.issue == 61 and anomaly.pid is None
    assert anomaly.held_for >= an.LEASE_OVERRUN_SECONDS + 29


def test_detect_lease_overrun_reservation_not_yet_expired_is_none() -> None:
    now = time.time()
    expires = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + 60))
    entry = {"id": 8, "host": "pc", "slots": 1, "issue": None, "expires": expires}
    assert an.detect_lease_overrun_reservation(entry, now=now) is None


def test_detect_lease_overrun_reservation_expired_but_under_threshold_is_none() -> None:
    now = time.time()
    expires = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 30))  # expired, but < 10 min ago
    entry = {"id": 9, "host": "pc", "slots": 1, "issue": None, "expires": expires}
    assert an.detect_lease_overrun_reservation(entry, now=now) is None


def test_a_lease_overrun_slot_writes_one_event_and_is_deduped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(events_file))

    guard = an.AnomalyGuard(
        path=tmp_path / "anomalies.json", launcher=FakeKeymasterCli(),
        slot_lister=lambda: [_slot_row(age_seconds=an.LEASE_OVERRUN_SECONDS + 5)],
        clock=time.time, log=lambda message: None,
    )

    started = guard.check()
    guard.check()  # a second tick: still over the threshold, must not write a second event
    guard.check()

    assert [a.kind for a in started] == ["lease_overrun"]
    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    lease_events = [e for e in events if e.get("kind") == "lease_overrun"]
    assert lease_events == [
        {"kind": "lease_overrun", "pid": 4242, "issue": None, "held_for": an.LEASE_OVERRUN_SECONDS + 5},
    ]


def test_a_lease_overrun_reservation_is_included_in_the_anomaly_queue(tmp_path: Path) -> None:
    now = time.time()
    expires = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - an.LEASE_OVERRUN_SECONDS - 5))
    guard, launcher = make_guard(
        tmp_path,
        clock=lambda: now,
    )
    guard.reservation_lister = lambda: [{"id": 3, "host": "pc", "slots": 1, "issue": 61, "expires": expires}]

    started = guard.check()

    assert [a.key for a in started] == ["lease_overrun:reservation:3"]
    assert len(launcher.started) == 1
    anomaly, cmd = launcher.started[0]
    assert "keymaster: lease_overrun issue-61" in " ".join(cmd)


# -- requirement 2: one anomaly starts one keymaster session ---------------------------------

def test_a_failed_job_starts_one_keymaster_session_with_the_right_command_line(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=48)
    guard, launcher = make_guard(tmp_path)

    started = guard.check(ended_jobs=[job])

    assert [a.key for a in started] == [f"job_failed:{job.id}"]
    assert len(launcher.started) == 1
    anomaly, cmd = launcher.started[0]
    assert cmd == [
        "claude.exe", "--bg", "--name", f"keymaster: job_failed {job.id}",
        "--agent", "keymaster", "--effort", "medium", "--permission-mode", "bypassPermissions",
        an.build_prompt(anomaly),
    ]
    assert f"Follow {an.KEYMASTER_DOC}." in cmd[-1]


def test_a_second_anomaly_while_one_is_live_is_queued_not_started(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    first = make_job(store, rc=1, issue=1)
    second = make_job(store, rc=1, issue=2)
    guard, launcher = make_guard(tmp_path)

    guard.check(ended_jobs=[first])
    assert len(launcher.started) == 1

    # A keymaster session is now live (the fake launcher records it as such).
    started_second = guard.check(ended_jobs=[second])
    assert started_second == []
    assert len(launcher.started) == 1                     # nothing new started

    state = an._read_state(tmp_path / "anomalies.json")
    assert [a.key for a in state.queue] == [f"job_failed:{second.id}"]
    assert state.handled == {f"job_failed:{first.id}", f"job_failed:{second.id}"}


def test_the_queued_anomaly_starts_once_the_live_session_ends(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    first = make_job(store, rc=1, issue=1)
    second = make_job(store, rc=1, issue=2)
    guard, launcher = make_guard(tmp_path)

    guard.check(ended_jobs=[first])
    guard.check(ended_jobs=[second])
    assert len(launcher.started) == 1

    launcher.finish_all()                                   # the first session ended
    started = guard.check(ended_jobs=[])
    assert [a.key for a in started] == [f"job_failed:{second.id}"]
    assert len(launcher.started) == 2

    state = an._read_state(tmp_path / "anomalies.json")
    assert state.queue == []


def _queued_guard(tmp_path: Path, clock: dict, state: str = "blocked", status: str = "idle"):
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=7)
    guard, launcher = make_guard(tmp_path, clock=lambda: clock["t"])
    launcher.set_row(state, status)
    return guard, launcher, job


@pytest.mark.parametrize("state,status", [("blocked", "idle"), ("working", "idle")])
def test_a_waiting_keymaster_session_counts_live_and_queues_the_next(tmp_path: Path, state: str, status: str) -> None:
    guard, launcher, job = _queued_guard(tmp_path, {"t": 1000.0}, state, status)

    assert guard.check(ended_jobs=[job]) == []
    assert launcher.started == []
    assert [a.key for a in an._read_state(tmp_path / "anomalies.json").queue] == [f"job_failed:{job.id}"]


@pytest.mark.parametrize("state", ["done", "stopped"])
def test_a_finished_keymaster_session_is_not_live(tmp_path: Path, state: str) -> None:
    guard, launcher, job = _queued_guard(tmp_path, {"t": 1000.0}, state, "idle")

    assert len(guard.check(ended_jobs=[job])) == 1
    assert len(launcher.started) == 1


def test_a_done_keymaster_is_ended_at_once_and_only_once(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(events_file))
    guard, launcher = make_guard(tmp_path)
    launcher.end_result = False                         # stays listed on every pass
    launcher.set_row("done", "idle")

    guard.check()
    guard.check()

    assert [row["id"] for row in launcher.ended] == ["km-live"]
    assert not events_file.exists() or "keymaster_ended" not in events_file.read_text(encoding="utf-8")


def test_a_done_keymaster_end_records_an_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(events_file))
    guard, launcher = make_guard(tmp_path)
    launcher.set_row("done", "idle")

    guard.check()
    guard.check()

    assert [row["id"] for row in launcher.ended] == ["km-live"]
    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    ended = [e for e in events if e.get("kind") == "keymaster_ended"]
    assert len(ended) == 1 and ended[0]["reason"] == "done" and ended[0]["session"] == "km-live"


def test_done_non_keymaster_and_working_keymaster_are_not_ended(tmp_path: Path) -> None:
    guard, launcher = make_guard(tmp_path)
    launcher._sessions = [
        {"name": "ORCH #1", "id": "orch-1", "state": "done"},
        {"name": "keymaster: job_failed j-2", "id": "km-w", "state": "working", "status": "busy"},
        {"name": "keymaster: job_failed j-3", "id": "km-s", "state": "stopped"},
    ]

    guard.check()

    assert launcher.ended == []


def test_a_session_waiting_past_the_limit_is_ended_and_the_queue_head_starts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(events_file))
    clock = {"t": 1000.0}
    guard, launcher, job = _queued_guard(tmp_path, clock)

    guard.check(ended_jobs=[job])                       # t0: seen waiting, anomaly queued
    assert an._read_state(tmp_path / "anomalies.json").waiting == {"km-live": 1000.0}
    clock["t"] = 1000.0 + 9 * 60
    assert guard.check() == [] and launcher.ended == []
    clock["t"] = 1000.0 + 11 * 60
    started = guard.check()

    assert [a.key for a in started] == [f"job_failed:{job.id}"]
    assert [row["id"] for row in launcher.ended] == ["km-live"]
    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    ended = [e for e in events if e.get("kind") == "keymaster_ended"]
    assert len(ended) == 1
    assert ended[0]["session"] == "km-live" and ended[0]["waited_seconds"] == 660.0
    assert ended[0]["waited"] == an.human_duration(660.0)
    state = an._read_state(tmp_path / "anomalies.json")
    assert state.waiting == {} and state.queue == []


def test_a_session_that_goes_busy_resets_its_wait(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    guard, launcher, job = _queued_guard(tmp_path, clock)

    guard.check(ended_jobs=[job])                       # waiting at t0
    clock["t"] = 1000.0 + 5 * 60
    launcher.set_row("working", "busy")
    guard.check()
    assert an._read_state(tmp_path / "anomalies.json").waiting == {}
    clock["t"] = 1000.0 + 6 * 60
    launcher.set_row("blocked", "idle")
    guard.check()
    clock["t"] = 1000.0 + 15 * 60
    guard.check()

    assert launcher.ended == [] and launcher.started == []


def test_an_end_that_returns_false_leaves_the_session_live(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    guard, launcher, job = _queued_guard(tmp_path, clock)
    launcher.end_result = False

    guard.check(ended_jobs=[job])
    clock["t"] = 1000.0 + 11 * 60
    assert guard.check() == []
    assert len(launcher.ended) == 1 and launcher.started == []
    assert "km-live" in an._read_state(tmp_path / "anomalies.json").waiting


def test_the_same_anomaly_key_never_starts_twice(tmp_path: Path) -> None:
    """A job that stays `failed` is seen every tick; only the first tick starts a session."""

    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=48)
    guard, launcher = make_guard(tmp_path)

    guard.check(ended_jobs=[job])
    guard.check(ended_jobs=[job])
    guard.check(ended_jobs=[job])

    assert len(launcher.started) == 1
    state = an._read_state(tmp_path / "anomalies.json")
    assert state.handled == {f"job_failed:{job.id}"}
    assert state.queue == []


def test_a_stuck_output_job_is_detected_and_starts_a_session(tmp_path: Path) -> None:
    out = tmp_path / "stuck.out"
    out.write_text("running\n", encoding="utf-8")
    import os

    old_mtime = time.time() - an.STUCK_OUTPUT_SECONDS - 60
    os.utime(out, (old_mtime, old_mtime))
    guard, launcher = make_guard(tmp_path)

    started = guard.check(running={"j-stuck": str(out)})

    assert [a.key for a in started] == ["job_stuck:j-stuck"]
    assert len(launcher.started) == 1


def test_an_unreachable_laptop_after_ten_minutes_of_failed_probes_is_detected(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    guard, launcher = make_guard(tmp_path, host_prober=lambda: False, clock=lambda: clock["t"])

    assert guard.check() == []                              # first failure at t0
    clock["t"] += 9 * 60
    assert guard.check() == []                              # 9 min of failures: none
    clock["t"] += 60
    assert guard.check() == []                              # 10 min: recorded only, no session (#674)
    assert launcher.started == []
    assert an._read_state(tmp_path / "anomalies.json").queue == []


def test_a_recovering_probe_restarts_the_span(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    outcomes = {"ok": False}
    guard, launcher = make_guard(tmp_path, host_prober=lambda: outcomes["ok"], clock=lambda: clock["t"])
    guard.check()                                           # fails at 0
    clock["t"] += 5 * 60
    outcomes["ok"] = True
    guard.check()                                           # success at 5 min resets the streak
    outcomes["ok"] = False
    clock["t"] += 60
    guard.check()                                           # new streak starts at 6 min
    clock["t"] += 9 * 60 + 59
    assert guard.check() == []                              # 15 min from the start, 9:59 into the new streak
    clock["t"] += 1
    assert guard.check() == []
    assert "host_unreachable:laptop" in an._read_state(tmp_path / "anomalies.json").handled  # raised, recorded


def test_the_probe_runs_at_most_once_per_probe_interval(tmp_path: Path) -> None:
    """10 s ticks, a 60 s probe interval: the prober is called every 6th tick, not every tick."""

    calls = {"n": 0}

    def prober() -> bool:
        calls["n"] += 1
        return True

    clock = {"t": 0.0}
    guard, _ = make_guard(tmp_path, host_prober=prober, clock=lambda: clock["t"],
                          probe_interval=60.0)

    for _ in range(12):                                     # 12 ticks of 10 s = 120 s
        guard.check()
        clock["t"] += 10.0

    assert calls["n"] == 2                                  # probed at t=0 and t=60, not t=10..50


def test_an_unreadable_budget_file_is_detected(tmp_path: Path) -> None:
    guard, launcher = make_guard(tmp_path, budget_checker=lambda: False)
    started = guard.check()
    assert [a.key for a in started] == ["budget_unreadable:machine_budget"]


def test_anomalies_json_is_bom_free_and_has_stable_keys(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=48)
    guard, _ = make_guard(tmp_path)
    guard.check(ended_jobs=[job])

    path = tmp_path / "anomalies.json"
    raw = path.read_bytes()
    assert raw[:3] != an._BOM
    data = json.loads(raw.decode("utf-8"))
    assert list(data.keys()) == sorted(data.keys())


# -- daemon integration: a small, injectable call from tick -----------------------------------

def test_daemon_tick_calls_the_anomaly_guard_when_given_one(tmp_path: Path) -> None:
    from junkroan.runs import daemon as daemon_mod
    from junkroan.pob import slot_budget

    calls: list[dict] = []

    class RecordingGuard:
        def check(self, **kwargs):
            calls.append(kwargs)
            return []

    store = Store(tmp_path / "jobs.jsonl")
    d = daemon_mod.Daemon(
        store, host="pc",
        launcher=_NullLauncher(), gh=_NullGh(), queue=_NullQueue(tmp_path),
        budget_loader=lambda: slot_budget.Budget(period="day", hours=(0, 24), total=1, others=0,
                                                 min_free_ram_gb=0.0, strict_reserve=False),
        slot_lister=lambda: [],
        events_file=tmp_path / "events.jsonl", runs_dir=tmp_path / "runs", archive=False,
        log=lambda message: None, anomaly_guard=RecordingGuard(),
    )
    d.tick()
    assert len(calls) == 1
    assert "ended_jobs" in calls[0] and "running" in calls[0] and "wrong_host" in calls[0]


def test_daemon_wrong_host_jobs_excludes_own_host_and_any(tmp_path: Path) -> None:
    """#120: `Daemon.wrong_host_jobs` -- this host's own queued jobs addressed elsewhere."""

    from junkroan.runs import daemon as daemon_mod
    from junkroan.pob import slot_budget

    store = Store(tmp_path / "jobs.jsonl")
    mine = store.submit(host="pc", priority="P1", tag="mine", cmd="echo a")
    any_job = store.submit(host="any", priority="P1", tag="any-job", cmd="echo b")
    wrong = store.submit(host="laptop", priority="P1", tag="wrong", cmd="echo c")
    d = daemon_mod.Daemon(
        store, host="pc",
        launcher=_NullLauncher(), gh=_NullGh(), queue=_NullQueue(tmp_path),
        budget_loader=lambda: slot_budget.Budget(period="day", hours=(0, 24), total=1, others=0,
                                                 min_free_ram_gb=0.0, strict_reserve=False),
        slot_lister=lambda: [], events_file=tmp_path / "events.jsonl",
        runs_dir=tmp_path / "runs", archive=False, log=lambda message: None,
    )
    assert [job.id for job in d.wrong_host_jobs()] == [wrong.id]
    assert mine.id not in [j.id for j in d.wrong_host_jobs()]
    assert any_job.id not in [j.id for j in d.wrong_host_jobs()]


def test_daemon_tick_raises_one_wrong_host_anomaly_and_dedupes_across_ticks(tmp_path: Path) -> None:
    """#120 acceptance: 1 anomaly on the next tick, 0 on the following ticks."""

    from junkroan.runs import daemon as daemon_mod
    from junkroan.runs import anomalies as an
    from junkroan.pob import slot_budget

    store = Store(tmp_path / "jobs.jsonl")
    wrong = store.submit(host="laptop", priority="P1", tag="wrong-host-daemon", cmd="echo c")
    launcher = FakeKeymasterCli()
    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", host="pc",
                            launcher=launcher, log=lambda message: None)
    d = daemon_mod.Daemon(
        store, host="pc",
        launcher=_NullLauncher(), gh=_NullGh(), queue=_NullQueue(tmp_path),
        budget_loader=lambda: slot_budget.Budget(period="day", hours=(0, 24), total=0, others=0,
                                                 min_free_ram_gb=0.0, strict_reserve=False),
        slot_lister=lambda: [], events_file=tmp_path / "events.jsonl",
        runs_dir=tmp_path / "runs", archive=False, log=lambda message: None, anomaly_guard=guard,
    )
    d.tick()
    assert [a.key for a, _cmd in launcher.started] == [f"job_wrong_host:{wrong.id}"]

    launcher.finish_all()  # free the "at most one keymaster session" slot before the next tick
    d.tick()
    d.tick()
    assert [a.key for a, _cmd in launcher.started] == [f"job_wrong_host:{wrong.id}"], (
        "still exactly one session started: the same job never raises a second anomaly"
    )
    state = an._read_state(guard.path)
    assert state.handled == {f"job_wrong_host:{wrong.id}"}


def test_daemon_tick_without_a_guard_never_touches_anomalies(tmp_path: Path) -> None:
    from junkroan.runs import daemon as daemon_mod
    from junkroan.pob import slot_budget

    store = Store(tmp_path / "jobs.jsonl")
    d = daemon_mod.Daemon(
        store, host="pc",
        launcher=_NullLauncher(), gh=_NullGh(), queue=_NullQueue(tmp_path),
        budget_loader=lambda: slot_budget.Budget(period="day", hours=(0, 24), total=1, others=0,
                                                 min_free_ram_gb=0.0, strict_reserve=False),
        slot_lister=lambda: [],
        events_file=tmp_path / "events.jsonl", runs_dir=tmp_path / "runs", archive=False,
        log=lambda message: None,
    )
    d.tick()  # must not raise with anomaly_guard=None


class _NullLauncher:
    def start(self, cmd, *, cwd, out, env):
        raise AssertionError("no job submitted; start must not be called")

    def alive(self, pid):
        return True


class _NullGh:
    def comment(self, issue, body):
        return True

    def add_label(self, issue, label):
        return True


class _NullQueue:
    def __init__(self, tmp_path: Path) -> None:
        self._runs_dir = tmp_path / "runs"

    def runs_dir(self) -> Path:
        return self._runs_dir

    def out_name(self, cmd, now, runs_dir):
        return "x"

    def wants_snapshot(self, cmd):
        return False

    def make_snapshot(self, name, pin):
        return None

    def drop_snapshot(self, snapshot):
        pass

    def pid_alive(self, pid):
        return True

    def find_run_dir(self, cmd, out, started_at):
        return None

    def archive(self, cmd, run_dir, out):
        return 0


# -- issue #82: a job held by a predecessor that did not end rc 0 ------------------------------

def test_82_a_held_follower_raises_one_anomaly_and_one_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The follower's hold is reported once, however many ticks it stays held."""

    events_file = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(events_file))
    store = Store(tmp_path / "jobs.jsonl")
    predecessor = store.submit(host="pc", priority="P1", tag="a", cmd="echo a", issue=61)
    follower = store.submit(host="pc", priority="P1", tag="b", cmd="echo b", after=[predecessor.id])
    store.start(predecessor.id, out=str(tmp_path / "a.out"), pid=1)
    failed = store.end(predecessor.id, rc=3)
    guard, launcher = make_guard(tmp_path)

    started = guard.check(held=[(follower, failed)])
    guard.check(held=[(follower, failed)])          # a second tick: still held, nothing new
    guard.check(held=[(follower, failed)])

    assert [a.key for a in started] == [f"held_by_failed_predecessor:{follower.id}:{predecessor.id}"]
    assert len(launcher.started) == 1
    anomaly, cmd = launcher.started[0]
    assert f"keymaster: held_by_failed_predecessor {follower.id}" in " ".join(cmd)
    assert "rc 3" in anomaly.detail and predecessor.id in anomaly.detail

    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    held_events = [e for e in events if e.get("kind") == "held_by_failed_predecessor"]
    assert len(held_events) == 1 and held_events[0]["job"] == follower.id


# -- #120: a queued job in this host's own store addressed to some other host -------------------

def test_detect_job_wrong_host(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="laptop", priority="P1", tag="wrong-host-t", cmd="echo hi")
    anomaly = an.detect_job_wrong_host(job, "pc")
    assert anomaly.kind == "job_wrong_host" and anomaly.key == f"job_wrong_host:{job.id}"
    assert anomaly.job == job.id and anomaly.host == "laptop"
    assert "laptop" in anomaly.detail and "pc" in anomaly.detail


def test_120_a_wrong_host_queued_job_raises_one_anomaly_and_is_deduped(tmp_path: Path) -> None:
    """1 anomaly on the first `check` that sees it, 0 on the following ones (dedup, #120)."""

    store = Store(tmp_path / "jobs.jsonl")
    wrong = store.submit(host="laptop", priority="P1", tag="wrong-host", cmd="echo hi")
    guard, launcher = make_guard(tmp_path)

    started = guard.check(wrong_host=[wrong])
    assert [a.key for a in started] == [f"job_wrong_host:{wrong.id}"]
    assert len(launcher.started) == 1

    again = guard.check(wrong_host=[wrong])          # still queued, same job: no new anomaly
    assert again == []
    assert len(launcher.started) == 1

    still_more = guard.check(wrong_host=[wrong])
    assert still_more == []
    assert len(launcher.started) == 1


def test_82_a_predecessor_still_running_is_no_anomaly(tmp_path: Path) -> None:
    """`waiting` is the normal state of a chain: only the daemon's `blocked` pairs reach the guard."""

    store = Store(tmp_path / "jobs.jsonl")
    predecessor = store.submit(host="pc", priority="P1", tag="a", cmd="echo a")
    store.submit(host="pc", priority="P1", tag="b", cmd="echo b", after=[predecessor.id])
    store.start(predecessor.id, out=str(tmp_path / "a.out"), pid=1)
    guard, launcher = make_guard(tmp_path)

    assert guard.check() == []
    assert launcher.started == []


# -- issue #395: a hand-back anomaly an open issue already carries becomes a comment ------------------

def _three_raises(guard: an.AnomalyGuard, clock: dict) -> None:
    for _ in range(3):
        guard.note_handback("laptop", False)
        clock["t"] += an.UNREACHABLE_SPAN_SECONDS
        guard.note_handback("laptop", False)
        guard.check()
        clock["t"] += an.HANDBACK_COOLDOWN_SECONDS + 60


def _handback_guard(tmp_path: Path, clock: dict, finder, comments: list, logs: list | None = None):
    launcher = FakeKeymasterCli()
    guard = an.AnomalyGuard(
        path=tmp_path / "anomalies.json", launcher=launcher, clock=lambda: clock["t"],
        log=(logs.append if logs is not None else (lambda m: None)),
        issue_finder=finder, issue_commenter=lambda n, text: comments.append((n, text)) or True,
    )
    return guard, launcher


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_674_three_lost_laptop_links_start_nothing_and_call_no_gh(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    clock = {"t": 1_000_000.0}
    gh_calls: list = []
    guard, launcher = _handback_guard(tmp_path, clock, lambda key: gh_calls.append(("find", key)) or 382, gh_calls)
    _three_raises(guard, clock)
    assert launcher.started == []
    assert gh_calls == []
    assert an._read_state(tmp_path / "anomalies.json").queue == []
    events = _events(tmp_path / "events.jsonl")
    assert [e["kind"] for e in events] == ["host_unreachable"] * 3
    assert events[0]["key"] == "host_unreachable:laptop"


def test_674_a_job_failed_anomaly_with_the_same_stubs_starts_one_session(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    clock = {"t": 1_000_000.0}
    gh_calls: list = []
    guard, launcher = _handback_guard(tmp_path, clock, lambda key: gh_calls.append(("find", key)) or None, gh_calls)
    job = make_job(Store(tmp_path / "jobs.jsonl"), rc=1, issue=48)
    started = guard.check(ended_jobs=[job])
    assert [a.kind for a in started] == ["job_failed"]
    assert len(launcher.started) == 1


class _FakeRun:
    def __init__(self, rc: int, out: str) -> None:
        self.rc, self.out, self.argv = rc, out, None

    def __call__(self, argv, **kwargs):
        self.argv = argv

        class R:
            returncode = self.rc
            stdout = self.out
            stderr = ""
        return R()


def test_395_real_finder_picks_the_lowest_number_and_asks_for_open_issues() -> None:
    run = _FakeRun(0, '[{"number": 390}, {"number": 382}]')
    assert an.make_issue_finder(run)("host_unreachable:laptop") == 382
    assert "--state" in run.argv and run.argv[run.argv.index("--state") + 1] == "open"
    assert '"host_unreachable:laptop" in:body' in run.argv
    assert an.make_issue_finder(_FakeRun(1, "[]"))("k") is None
    assert an.make_issue_finder(_FakeRun(0, "[]"))("k") is None
    assert an.make_issue_finder(_FakeRun(0, "not json"))("k") is None


# -- #466: a stale job_stuck is dropped; a --loop-seconds run has a longer line ---------------------

def _age(path: Path, seconds: float, now: float) -> None:
    import os

    os.utime(path, (now - seconds, now - seconds))


def test_stuck_line_follows_loop_seconds(tmp_path: Path) -> None:
    now = 1_000_000.0
    out = tmp_path / "loop.out"
    out.write_text("x" + chr(10), encoding="utf-8")
    cmd = "python scripts/benchmark.py --loop --loop-seconds 5400"
    line = an.stuck_line_seconds(cmd)
    assert line == 5400 + 15 * 60
    _age(out, 60 * 60, now)
    assert an.detect_job_stuck("j", out, now=now, stale_seconds=line) is None
    _age(out, 5400 + 16 * 60, now)
    assert an.detect_job_stuck("j", out, now=now, stale_seconds=line) is not None
    assert an.stuck_line_seconds("python scripts/benchmark.py --loop-seconds 5400") == line
    plain = an.stuck_line_seconds("echo x")
    assert plain == an.STUCK_OUTPUT_SECONDS
    assert an.stuck_line_seconds("python scripts/benchmark.py --loop-seconds 600") == an.STUCK_OUTPUT_SECONDS
    _age(out, 46 * 60, now)
    assert an.detect_job_stuck("j", out, now=now, stale_seconds=plain) is not None


def test_guard_uses_the_loop_line_for_a_running_job(tmp_path: Path) -> None:
    now = 1_000_000.0
    out = tmp_path / "loop.out"
    out.write_text("x" + chr(10), encoding="utf-8")
    _age(out, 60 * 60, now)
    guard, launcher = make_guard(tmp_path, clock=lambda: now)
    assert guard.check(running={"j": str(out)}, commands={"j": "b.py --loop-seconds 5400"}) == []
    assert [a.key for a in guard.check(running={"j": str(out)}, commands={"j": "b.py"})] == ["job_stuck:j"]


import pytest  # noqa: E402


@pytest.mark.parametrize("rc", [0, 1])
def test_queued_job_stuck_is_dropped_when_its_job_ended(tmp_path: Path, rc: int) -> None:
    logs: list[str] = []
    cli = FakeKeymasterCli()
    cli.set_live()  # a keymaster is busy: the anomaly waits in the queue
    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=cli, clock=lambda: 1.0,
                            log=logs.append, probe_interval=0.0)
    other = an.Anomaly(kind="job_failed", key="job_failed:o", job="o", detail="d")
    running = an.Anomaly(kind="job_stuck", key="job_stuck:R", job="R", detail="d")
    stuck = an.Anomaly(kind="job_stuck", key="job_stuck:X", job="X", detail="d")
    an._write_state(guard.path, an.AnomalyState(handled={"job_stuck:X"}, queue=[stuck, other, running]))
    states = {"X": "running"}
    guard.check(job_state=lambda j: states.get(j, "running"))
    assert [a.key for a in an._read_state(guard.path).queue] == ["job_stuck:X", "job_failed:o", "job_stuck:R"]
    states["X"] = "done" if rc == 0 else "failed"
    cli.finish_all()
    started = guard.check(job_state=lambda j: states.get(j, "running"))
    assert [a.key for a in started] == ["job_failed:o"]  # X never started
    assert all(a.key != "job_stuck:X" for a, _ in cli.started)
    assert [a.key for a in an._read_state(guard.path).queue] == ["job_stuck:R"]
    assert sum("job_stuck:X dropped" in line for line in logs) == 1


def test_a_failed_job_anomaly_carries_the_jobs_issue_into_the_keymaster_prompt(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=467)
    anomaly = an.detect_job_failed(job)
    assert anomaly is not None and anomaly.issue == 467 and anomaly.key == f"job_failed:{job.id}"
    assert "issue: #467 (the job's issue: write your finding there, docs/agents/keymaster.md step 4)"         in an.build_prompt(anomaly)
    no_issue = an.Anomaly(kind=anomaly.kind, key=anomaly.key, job=anomaly.job, detail=anomaly.detail,
                          out=anomaly.out, issue=None)
    assert "issue:" not in an.build_prompt(no_issue)
