"""#647 unit 2: a hanging `claude agents` list must not stall the daemon's tick.

No real `claude.exe`: the launcher's `list_sessions` blocks on an Event. The scale is 1:10 of
production (hang 6 s = 6 x tick_seconds 1 s); the ratio is what is tested.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import watchdog  # noqa: E402
from timing_bound import bound  # noqa: E402
from test_runs_anomalies import FakeKeymasterCli, make_job  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

TICK = 1.0
HANG = 6.0


class HangingCli(FakeKeymasterCli):
    """`list_sessions` blocks until `release` is set (or 30 s pass)."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.calls = 0

    def list_sessions(self) -> list[dict]:
        self.calls += 1
        self.release.wait(30)
        return super().list_sessions()


@pytest.fixture(autouse=True)
def _fast_wait(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(an, "SESSION_LIST_WAIT_SECONDS", 0.05)
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


def _guard(tmp_path: Path, launcher: FakeKeymasterCli) -> an.AnomalyGuard:
    return an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=launcher, host_prober=None,
                           budget_checker=None, log=lambda message: None, probe_interval=0.0)


def test_hanging_list_does_not_stall_last_tick_or_trigger_takeover(tmp_path: Path) -> None:
    """#811: the full run is BELOW_NORMAL on a PC at 100 % cpu (#775), so one attempt can be starved of 7 s
    by the scheduler (c31aaae4: gap 7.75 s) with the code unchanged; a stall the hang causes repeats in every
    attempt. Up to 3 attempts, each in its own folder; the last failure is raised."""

    for attempt in range(3):
        try:
            _hanging_list_attempt(tmp_path / f"attempt{attempt}")
            return
        except AssertionError:
            if attempt == 2:
                raise


def _hanging_list_attempt(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    daemon, _store, _ = make_daemon(tmp_path)
    launcher = HangingCli()
    daemon.anomaly_guard = _guard(tmp_path, launcher)
    writes: list[float] = []
    real_write = daemon.write_status

    def write_status(*, interval: float) -> None:
        real_write(interval=interval)
        writes.append(time.monotonic())

    daemon.write_status = write_status  # type: ignore[method-assign]
    try:
        started = time.monotonic()
        # 8 ticks of ~1 s: longer than the 6 s hang, which is still in flight at the end of the loop
        daemon.run(ticks=8, interval=TICK)
        elapsed = time.monotonic() - started
        assert elapsed > HANG, "the loop must cover the whole hang"
        assert launcher.calls == 1, "one list call in flight at most"
        gaps = [b - a for a, b in zip(writes, writes[1:])]
        max_gap = max(gaps)
        print(f"max gap between last_tick writes during the hang: {max_gap:.2f} s (tick {TICK} s)")
        # #870: the gap bound follows the machine (spin timed now, after the run, so it sees the load the run saw);
        # idle: the 2 s floor rules and a 6 s hang (gap ~ HANG) still breaks it; loaded: starvation is not a stall
        gap_bound = bound(2 * TICK, 8)
        print(f"gap bound {gap_bound:.2f} s (hang {HANG} s)")
        assert max_gap <= gap_bound
        # the watchdog, reading the status file the worst gap after its last write: 0 takeovers
        path = daemon_mod.runs_hosts.daemon_status_path("pc")
        status = daemon_mod.read_daemon_status(path)
        last_tick = datetime.fromisoformat(status["last_tick"])
        if last_tick.tzinfo is None:
            last_tick = last_tick.replace(tzinfo=timezone.utc)
        kills: list[int] = []
        launches: list[int] = []
        code = watchdog.ensure(
            "pc", status_path=path, pid_alive=lambda pid: True,
            launch=lambda cmd, cwd: launches.append(1) or 1, kill=lambda pid: kills.append(pid) or True,
            now=lambda: last_tick + timedelta(seconds=max_gap), out=lambda line: None,
        ) if _is_pc() else 0
        assert code == 0 and kills == [] and launches == []
    finally:
        launcher.release.set()
        thread = daemon.anomaly_guard._list_thread
        if thread is not None:
            thread.join(10)
            assert not thread.is_alive()


def _is_pc() -> bool:
    from junkroan.pob import slot_budget

    return slot_budget.current_host() == "pc"


def test_no_keymaster_while_list_not_ready_then_the_list_is_used(tmp_path: Path) -> None:
    launcher = HangingCli()
    guard = _guard(tmp_path, launcher)
    job = make_job(Store(tmp_path / "jobs.jsonl"), rc=1, issue=7)
    try:
        assert guard.check(ended_jobs=[job]) == []
        assert launcher.started == [], "list not ready: no keymaster"
        launcher.release.set()
        thread = guard._list_thread
        assert thread is not None
        thread.join(10)
        started = guard.check()
        assert [a.key for a in started] == [f"job_failed:{job.id}"]
        assert len(launcher.started) == 1
    finally:
        launcher.release.set()
        if guard._list_thread is not None:
            guard._list_thread.join(10)
