"""junkroan.runs.anomalies (issue #1183): the laptop answers ssh but its runs daemon is not live.

Seams: `AnomalyGuard.check` (one tick) and the pure `detect_host_daemon_dead`. No real ssh, claude.exe
or PoB: the probe, the daemon-status reader, the launcher and the issue fakes are all injected.
`JUNKROAN_RUNS_EVENTS` is redirected to `tmp_path` in every test that writes events.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402

#: A clock base far from 1970 so that "last tick an hour ago" is still a positive epoch on Windows.
BASE = 2_000_000.0
DEAD_KEY = "host_daemon_dead:laptop"


# -- fakes ------------------------------------------------------------------------------------

class FakeLauncher:
    """Records every `start` and `end`; no session is ever live."""

    def __init__(self) -> None:
        self.started: list[tuple[an.Anomaly, list[str]]] = []
        self.ended: list[dict[str, Any]] = []

    def list_sessions(self) -> list[dict[str, Any]]:
        return []

    def start(self, anomaly: an.Anomaly) -> tuple[str, list[str]]:
        cmd = an.build_command(anomaly, "claude.exe")
        self.started.append((anomaly, cmd))
        return "km-1", cmd

    def end(self, session: dict[str, Any]) -> bool:
        self.ended.append(dict(session))
        return True


def stale_status(clock_t: float) -> dict[str, Any]:
    """The laptop daemon's status file as it reads an hour after its last tick: never live."""

    last = datetime.fromtimestamp(clock_t - 3600, timezone.utc)
    return {"pid": 4242, "last_tick": last.isoformat(), "tick_seconds": 10.0}


def live_status(clock_t: float) -> dict[str, Any]:
    last = datetime.fromtimestamp(clock_t, timezone.utc)
    return {"pid": 4242, "last_tick": last.isoformat(), "tick_seconds": 10.0}


def make_dead_guard(tmp_path: Path, clock: dict[str, float], *, probe=lambda: True,
                    status_reader=None, fixed_jobs_reader=None, issue_calls: list | None = None,
                    ) -> tuple[an.AnomalyGuard, FakeLauncher]:
    launcher = FakeLauncher()
    calls = issue_calls if issue_calls is not None else []
    if status_reader is None:
        status_reader = lambda: stale_status(clock["t"])  # noqa: E731
    guard = an.AnomalyGuard(
        path=tmp_path / "anomalies.json", launcher=launcher,
        host_prober=probe, clock=lambda: clock["t"], log=lambda message: None,
        probe_interval=0.0,
        daemon_status_reader=status_reader,
        fixed_jobs_reader=fixed_jobs_reader,
        issue_finder=lambda key: calls.append(("find", key)) or None,
        issue_commenter=lambda number, body: calls.append(("comment", number)) or True,
    )
    return guard, launcher


def dead_events(events_file: Path) -> list[dict[str, Any]]:
    if not events_file.exists():
        return []
    rows = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "host_daemon_dead"]


@pytest.fixture
def events_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(path))
    return path


# -- detection (pure) -------------------------------------------------------------------------

def test_detect_host_daemon_dead_below_the_span_is_none() -> None:
    assert an.detect_host_daemon_dead("laptop", 10 * 60 - 1, span=10 * 60) is None
    assert an.detect_host_daemon_dead("laptop", None) is None


def test_detect_host_daemon_dead_at_the_span_names_the_key_and_the_fixed_jobs() -> None:
    anomaly = an.detect_host_daemon_dead("laptop", 10 * 60, span=10 * 60, fixed_jobs=["j-7"])
    assert anomaly is not None
    assert anomaly.kind == "host_daemon_dead" and anomaly.key == DEAD_KEY and anomaly.host == "laptop"
    assert "j-7" in anomaly.detail


# -- one tick ---------------------------------------------------------------------------------

def test_probe_ok_and_daemon_dead_for_ten_minutes_writes_exactly_one_event(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    guard, launcher = make_dead_guard(tmp_path, clock)

    assert guard.check() == []                 # first observation: the streak starts
    clock["t"] += 10 * 60
    guard.check()                              # 10 min of a dead daemon on ok probes: one event

    events = dead_events(events_file)
    assert len(events) == 1
    assert events[0]["key"] == DEAD_KEY and events[0]["host"] == "laptop"


def test_nine_minutes_fifty_nine_seconds_of_dead_daemon_writes_no_event(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    guard, _ = make_dead_guard(tmp_path, clock)

    guard.check()
    clock["t"] += 10 * 60 - 1
    guard.check()

    assert dead_events(events_file) == []


def test_a_probe_failure_in_between_resets_the_streak(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    probe_ok = {"v": True}
    guard, _ = make_dead_guard(tmp_path, clock, probe=lambda: probe_ok["v"])

    guard.check()                              # dead streak starts at t0
    clock["t"] += 5 * 60
    probe_ok["v"] = False
    guard.check()                              # probe fails: the dead streak is reset
    clock["t"] += 60
    probe_ok["v"] = True
    guard.check()                              # new streak starts 6 min in
    clock["t"] += 10 * 60 - 1
    guard.check()                              # 14 min 59 s from t0, but only 9 min 59 s of the new streak

    assert dead_events(events_file) == []


def test_a_second_tick_inside_the_cooldown_does_not_write_a_second_event(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    guard, _ = make_dead_guard(tmp_path, clock)

    guard.check()
    clock["t"] += 10 * 60
    guard.check()                              # the one event
    clock["t"] += 60
    guard.check()
    clock["t"] += 20 * 60
    guard.check()                              # 31 min after the event: still inside the hour

    assert len(dead_events(events_file)) == 1


def test_the_daemon_coming_back_live_resets_the_streak(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    state = {"live": False}
    guard, _ = make_dead_guard(
        tmp_path, clock,
        status_reader=lambda: live_status(clock["t"]) if state["live"] else stale_status(clock["t"]),
    )

    guard.check()
    clock["t"] += 5 * 60
    state["live"] = True
    guard.check()                              # live: the streak is reset
    clock["t"] += 5 * 60
    state["live"] = False
    guard.check()                              # a new streak starts here
    clock["t"] += 9 * 60 + 59
    guard.check()

    assert dead_events(events_file) == []


def test_an_unreadable_status_never_counts_as_dead(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}

    def broken() -> dict[str, Any]:
        raise RuntimeError("status file unreadable over ssh")

    guard, _ = make_dead_guard(tmp_path, clock, status_reader=broken)
    for _ in range(3):
        guard.check()
        clock["t"] += 10 * 60

    no_reader, _ = make_dead_guard(tmp_path, clock, status_reader=lambda: None)
    for _ in range(3):
        no_reader.check()
        clock["t"] += 10 * 60

    assert dead_events(events_file) == []


def test_a_fixed_laptop_job_is_named_in_the_event_line(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    guard, _ = make_dead_guard(tmp_path, clock, fixed_jobs_reader=lambda: ["j-7"])

    guard.check()
    clock["t"] += 10 * 60
    guard.check()

    events = dead_events(events_file)
    assert len(events) == 1
    assert "j-7" in events[0]["detail"]


def test_the_dead_daemon_starts_no_keymaster_no_issue_and_no_comment(tmp_path: Path, events_file: Path) -> None:
    clock = {"t": BASE}
    issue_calls: list = []
    guard, launcher = make_dead_guard(tmp_path, clock, issue_calls=issue_calls)

    guard.check()
    clock["t"] += 10 * 60
    guard.check()
    clock["t"] += 60
    guard.check()

    assert len(dead_events(events_file)) == 1
    assert launcher.started == [] and launcher.ended == []
    assert issue_calls == []
    assert an._read_state(tmp_path / "anomalies.json").queue == []
