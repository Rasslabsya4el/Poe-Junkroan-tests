"""The real wiring of issue #1183: `scripts/runs.py _build_anomaly_guard` gives the PC's guard the laptop
daemon's status reader, the fixed-jobs reader and the `on_daemon_dead` reclaim.

Seams: `_build_anomaly_guard` (what the built guard holds) and the built guard's `check` (one tick, a fake
clock). No real ssh, claude.exe, gh or PoB: the probe, the snapshot reader (a fake daemon), the launcher,
the issue fakes and `reclaim_from_dead_host` are all injected or replaced. `JUNKROAN_RUNS_EVENTS` and the
anomalies file go to `tmp_path`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import remote_store  # noqa: E402
from junkroan.runs.store import Job  # noqa: E402

#: The real `reclaim_from_dead_host`, kept before the fixture replaces it with a recording fake.
REAL_RECLAIM = runs.runs_rebalance.reclaim_from_dead_host

#: A clock base far from 1970 so that "last tick an hour ago" is still a positive epoch on Windows.
BASE = 2_000_000.0
DEAD_KEY = "host_daemon_dead:laptop"
LAPTOP_CFG = {"ssh": "laptop"}


# -- fakes ------------------------------------------------------------------------------------

class FakeDaemon:
    """The PC daemon object `_build_anomaly_guard` reaches through its daemon box: the snapshot reader
    (`_read_remote_snapshot`, one ssh round trip in the real daemon) and `log`."""

    def __init__(self, status_fn=lambda: None, jobs=(), raises: BaseException | None = None) -> None:
        self.status_fn = status_fn
        self.jobs = list(jobs)
        self.raises = raises
        self.host = "pc"
        self._hosts_config = None  # the real reclaim reads it: None = load_hosts_config()
        self.snapshot_calls: list[tuple[dict, str]] = []
        self.lines: list[str] = []

    def _read_remote_snapshot(self, host_cfg, host):
        self.snapshot_calls.append((dict(host_cfg), host))
        if self.raises is not None:
            raise self.raises
        return remote_store.RemoteSnapshot(jobs=list(self.jobs), daemon_status=self.status_fn(), budget=None)

    def log(self, message: str) -> None:
        self.lines.append(message)


class FakeLauncher:
    """No keymaster session is ever live or started."""

    def list_sessions(self) -> list[dict[str, Any]]:
        return []

    def start(self, anomaly):  # pragma: no cover - a dead daemon never starts a keymaster
        raise AssertionError("a keymaster must not start for host_daemon_dead")

    def end(self, session) -> bool:  # pragma: no cover
        return True


def stale_status(clock_t: float) -> dict[str, Any]:
    """The laptop daemon's status file as it reads an hour after its last tick: never live."""

    last = datetime.fromtimestamp(clock_t - 3600, timezone.utc)
    return {"pid": 4242, "last_tick": last.isoformat(), "tick_seconds": 10.0}


def live_status(clock_t: float) -> dict[str, Any]:
    last = datetime.fromtimestamp(clock_t, timezone.utc)
    return {"pid": 4242, "last_tick": last.isoformat(), "tick_seconds": 10.0}


@pytest.fixture
def events_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(path))
    return path


@pytest.fixture
def fake_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every collaborator `_build_anomaly_guard` makes from the real machine is replaced by a fake."""

    monkeypatch.setattr(runs.runs_hosts, "load_hosts_config", lambda: {"laptop": dict(LAPTOP_CFG)})
    monkeypatch.setattr(runs.runs_anomalies, "make_budget_checker", lambda *a, **k: (lambda: True))
    monkeypatch.setattr(runs.runs_anomalies, "make_host_prober", lambda cfg, **k: (lambda: True))
    monkeypatch.setattr(runs.runs_anomalies, "make_slot_lister", lambda: (lambda: []))
    monkeypatch.setattr(runs.runs_anomalies, "make_reservation_lister", lambda host: (lambda: []))
    monkeypatch.setattr(runs.runs_anomalies, "make_issue_finder", lambda *a, **k: (lambda key: None))
    monkeypatch.setattr(runs.runs_anomalies, "make_issue_commenter", lambda *a, **k: (lambda n, b: True))
    monkeypatch.setattr(runs.runs_anomalies, "default_anomalies_path", lambda: tmp_path / "anomalies.json")
    reclaims: list[tuple[Any, str]] = []

    def fake_reclaim(d, host_name):
        reclaims.append((d, host_name))
        return runs.runs_rebalance.ReclaimResult(moved=["j-1"], stayed_fixed=["j-2"], failed=[])

    monkeypatch.setattr(runs.runs_rebalance, "reclaim_from_dead_host", fake_reclaim)
    return {"reclaims": reclaims}


def dead_events(events_file: Path) -> list[dict[str, Any]]:
    if not events_file.exists():
        return []
    rows = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "host_daemon_dead"]


# -- (a) the built guard's collaborators ------------------------------------------------------

def test_the_pc_guard_has_the_three_daemon_collaborators(fake_world: dict[str, Any]) -> None:
    guard = runs._build_anomaly_guard("pc", None, {})
    assert guard.daemon_status_reader is not None
    assert guard.fixed_jobs_reader is not None
    assert guard.on_daemon_dead is not None


def test_the_laptop_guard_has_none_of_the_daemon_collaborators(fake_world: dict[str, Any]) -> None:
    guard = runs._build_anomaly_guard("laptop", None, {})
    assert guard.daemon_status_reader is None
    assert guard.fixed_jobs_reader is None
    assert guard.on_daemon_dead is None


# -- (b) the status reader: a failed read is never "dead" ------------------------------------

def test_the_status_reader_returns_none_when_the_snapshot_read_raises(fake_world: dict[str, Any]) -> None:
    box = {"daemon": FakeDaemon(raises=OSError("ssh: connection refused"))}
    guard = runs._build_anomaly_guard("pc", None, box)
    assert guard.daemon_status_reader() is None


def test_the_status_reader_returns_the_status_dict_otherwise(fake_world: dict[str, Any]) -> None:
    status = {"pid": 7, "last_tick": "2026-10-17T10:00:00+00:00", "tick_seconds": 10.0}
    fake = FakeDaemon(status_fn=lambda: status)
    guard = runs._build_anomaly_guard("pc", None, {"daemon": fake})
    assert guard.daemon_status_reader() == status
    assert fake.snapshot_calls == [(LAPTOP_CFG, "laptop")]  # the laptop's own cfg, read as "laptop"


def test_the_status_reader_is_none_before_the_daemon_exists(fake_world: dict[str, Any]) -> None:
    guard = runs._build_anomaly_guard("pc", None, {})
    assert guard.daemon_status_reader() is None


def test_the_fixed_jobs_reader_names_the_queued_host_fixed_jobs(fake_world: dict[str, Any]) -> None:
    jobs = [SimpleNamespace(id="j-1", state="queued", host_fixed=True),
            SimpleNamespace(id="j-2", state="queued", host_fixed=False),
            SimpleNamespace(id="j-3", state="done", host_fixed=True)]
    guard = runs._build_anomaly_guard("pc", None, {"daemon": FakeDaemon(jobs=jobs)})
    assert list(guard.fixed_jobs_reader()) == ["j-1"]


# -- (c) end to end on fakes: 10 minutes of a dead daemon on an ok probe ---------------------

def test_a_dead_laptop_daemon_writes_one_event_and_reclaims_once_at_ten_minutes(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any]) -> None:
    clock = {"t": BASE}
    fake = FakeDaemon(status_fn=lambda: stale_status(clock["t"]))
    guard = runs._build_anomaly_guard("pc", None, {"daemon": fake})
    guard.clock = lambda: clock["t"]
    guard.probe_interval = 0.0
    guard._launcher = FakeLauncher()  # `launcher` is a read-only property; its backing field takes the fake
    guard.log = fake.log

    guard.check()                                   # the streak starts
    clock["t"] += 9 * 60 + 59
    guard.check()                                   # 9 min 59 s: neither the event nor the reclaim
    assert dead_events(events_file) == []
    assert fake_world["reclaims"] == []

    clock["t"] += 1
    guard.check()                                   # 10 min: one event, one reclaim, host "laptop"
    events = dead_events(events_file)
    assert len(events) == 1 and events[0]["key"] == DEAD_KEY and events[0]["host"] == "laptop"
    assert fake_world["reclaims"] == [(fake, "laptop")]
    assert any("reclaim" in line and "j-1" in line and "j-2" in line for line in fake.lines)

    clock["t"] += 60
    guard.check()                                   # inside the cooldown: still one event, one reclaim
    assert len(dead_events(events_file)) == 1
    assert len(fake_world["reclaims"]) == 1


def test_a_live_laptop_daemon_writes_nothing_and_reclaims_nothing(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any]) -> None:
    clock = {"t": BASE}
    fake = FakeDaemon(status_fn=lambda: live_status(clock["t"]))
    guard = runs._build_anomaly_guard("pc", None, {"daemon": fake})
    guard.clock = lambda: clock["t"]
    guard.probe_interval = 0.0
    guard._launcher = FakeLauncher()  # `launcher` is a read-only property; its backing field takes the fake
    guard.log = fake.log

    for _ in range(3):
        guard.check()
        clock["t"] += 10 * 60
    assert dead_events(events_file) == []
    assert fake_world["reclaims"] == []


# -- (d) on_daemon_dead raising does not break the guard -------------------------------------

def test_a_raising_reclaim_is_logged_and_the_event_is_still_written(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(d, host_name):
        raise RuntimeError("store locked")

    monkeypatch.setattr(runs.runs_rebalance, "reclaim_from_dead_host", boom)
    clock = {"t": BASE}
    fake = FakeDaemon(status_fn=lambda: stale_status(clock["t"]))
    guard = runs._build_anomaly_guard("pc", None, {"daemon": fake})
    guard.clock = lambda: clock["t"]
    guard.probe_interval = 0.0
    guard._launcher = FakeLauncher()  # `launcher` is a read-only property; its backing field takes the fake
    guard.log = fake.log

    guard.check()
    clock["t"] += 10 * 60
    guard.check()                                   # must not raise
    assert len(dead_events(events_file)) == 1
    assert any("store locked" in line for line in fake.lines)


# -- end to end: a fixed job, a failed read, and the lock ------------------------------------

def fixed_laptop_job(job_id: str) -> Job:
    return Job(id=job_id, host="laptop", priority="P1", issue=None, submitter="test", tag="test", pin=None,
               cmd="python scripts/benchmark.py", resumable=False, state="queued",
               submit_ts="2026-10-17T10:00:00+00:00", host_fixed=True)


def lock_is_free(path: Path) -> bool:
    """One non-waiting attempt at the anomalies lock: free = this process can take it now."""
    try:
        with an._FileLock(path, timeout=0.0):
            return True
    except TimeoutError:
        return False


def wired_guard(clock: dict[str, float], fake: FakeDaemon) -> an.AnomalyGuard:
    guard = runs._build_anomaly_guard("pc", None, {"daemon": fake})
    guard.clock = lambda: clock["t"]
    guard.probe_interval = 0.0
    guard._launcher = FakeLauncher()  # `launcher` is a read-only property; its backing field takes the fake
    guard.log = fake.log
    return guard


def test_a_queued_fixed_laptop_job_is_named_in_the_event_and_stays_in_the_reclaim_line(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs.runs_rebalance, "reclaim_from_dead_host", REAL_RECLAIM)  # the real split, no fake
    clock = {"t": BASE}
    fake = FakeDaemon(status_fn=lambda: stale_status(clock["t"]), jobs=[fixed_laptop_job("j-fixed")])
    guard = wired_guard(clock, fake)

    guard.check()
    clock["t"] += 10 * 60
    guard.check()
    events = dead_events(events_file)
    assert len(events) == 1
    assert "j-fixed" in events[0]["detail"]                              # the event names the fixed job
    assert any("stayed fixed j-fixed" in line and "moved none" in line for line in fake.lines)


def test_a_failed_snapshot_read_for_fifteen_minutes_is_never_dead(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any]) -> None:
    clock = {"t": BASE}
    fake = FakeDaemon(raises=OSError("ssh: connection refused"))  # the probe answers ok; the read does not
    guard = wired_guard(clock, fake)

    guard.check()
    for _ in range(15):                                                  # 15 minutes of ticks, one a minute
        clock["t"] += 60
        guard.check()
    assert dead_events(events_file) == []
    assert fake_world["reclaims"] == []


def test_on_daemon_dead_runs_after_the_anomalies_lock_is_released(
        tmp_path: Path, events_file: Path, fake_world: dict[str, Any]) -> None:
    lock_path = tmp_path / "anomalies.json.lock"
    clock = {"t": BASE}
    fake = FakeDaemon(status_fn=lambda: stale_status(clock["t"]))
    guard = wired_guard(clock, fake)
    probes: list[bool] = []
    reclaim_call = guard.on_daemon_dead

    def probe_then_reclaim(host: str) -> None:
        probes.append(lock_is_free(lock_path))  # the anomalies lock must already be released here
        reclaim_call(host)

    guard.on_daemon_dead = probe_then_reclaim
    with an._FileLock(lock_path, timeout=5.0):                           # sanity: a held lock reads as not free
        assert lock_is_free(lock_path) is False

    guard.check()
    clock["t"] += 10 * 60
    guard.check()
    assert probes == [True]                                              # once, and with the lock free
    assert fake_world["reclaims"] == [(fake, "laptop")]
