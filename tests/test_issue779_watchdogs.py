"""#779 unit 6, row 7: no watchdog or deadline of the pipeline counts the time the machine stood in play.
For each one changed: across a 10 min play span it fires 0 times; with no span it fires as before.
Injected clocks and spans in a tmp AGENTOPS_MACHINE_DIR; no process is suspended, no PoB."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from junkroan.runs import anomalies, daemon
from tests import stood_clock
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue, _start
from tools.agentops import hold, machine_mode, merge as merge_module
from tools.agentops.merge import MergeLock, MergeLockTimeout

MIN = 60.0


def _utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc)


@pytest.fixture
def play_span(tmp_path, monkeypatch):
    """`span(start_epoch, minutes=10)` writes one play span into a tmp machine dir."""
    monkeypatch.setenv("AGENTOPS_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.setattr(hold, "keeper_pass", lambda *a, **k: {})

    def span(start: float, minutes: float = 10.0) -> None:
        machine_mode.set_mode("play", now=_utc(start))
        machine_mode.set_mode("normal", now=_utc(start + minutes * MIN))

    return span


# -- the runs daemon's anomalies ---------------------------------------------------------------------------------

@pytest.mark.parametrize("with_span, fires", [(True, 0), (False, 1)])
def test_job_stuck(tmp_path, play_span, with_span, fires):
    now = time.time()
    out = tmp_path / "job.out"
    out.write_text("x")
    os.utime(out, (now - 50 * MIN, now - 50 * MIN))  # silent 50 min; the stuck line is 45
    if with_span:
        play_span(now - 45 * MIN)
    assert len([a for a in [anomalies.detect_job_stuck("j1", out, now=now)] if a]) == fires


@pytest.mark.parametrize("with_span, fires", [(True, 0), (False, 1)])
def test_lease_overrun_slot_and_reservation(play_span, with_span, fires):
    now = time.time()
    if with_span:
        play_span(now - 12 * MIN)
    row = {"slot": 1, "pid": 5, "role": "other", "cmd": "x", "started": "s", "age_seconds": 11 * MIN + 30}
    assert len([a for a in [anomalies.detect_lease_overrun_slot(row, now=now)] if a]) == fires
    entry = {"id": "r1", "host": "pc", "issue": 1,
             "expires": datetime.fromtimestamp(now - 11 * MIN - 30).isoformat()}
    assert len([a for a in [anomalies.detect_lease_overrun_reservation(entry, now=now)] if a]) == fires


@pytest.mark.parametrize("with_span, inside", [(True, True), (False, False)])
def test_untracked_grace(play_span, with_span, inside):
    now = time.time()
    if with_span:
        play_span(now - 35 * MIN)
    tree = SimpleNamespace(slots=1, started=now - 35 * MIN)  # 35 min old; the grace is 30
    assert anomalies._untracked_within_rule(tree, now) is inside


@pytest.mark.parametrize("with_span, raised", [(True, 0), (False, 1)])
def test_host_unreachable_from_handbacks(play_span, with_span, raised):
    now = time.time()
    clock = [now - 11 * MIN]
    guard = anomalies.AnomalyGuard.__new__(anomalies.AnomalyGuard)
    guard.clock = lambda: clock[0]
    guard._handback_fail_since, guard._handback_raised_at, guard._handback_pending = {}, {}, []
    guard.note_handback("laptop", False)  # first failure, 11 min ago
    clock[0] = now
    if with_span:
        play_span(now - 11 * MIN)
    guard.note_handback("laptop", False)
    assert len(guard._handback_pending) == raised


@pytest.mark.parametrize("with_span, live", [(True, True), (False, False)])
def test_daemon_status_staleness(play_span, with_span, live):
    now = time.time()
    if with_span:
        play_span(now - 12 * MIN)
    status = {"pid": 1, "last_tick": _utc(now - 4 * MIN).isoformat(), "tick_seconds": 10.0}  # stale after 3 min
    ok, _ = daemon.status_liveness(status, now=_utc(now), pid_alive=lambda p: True)
    assert ok is live


# -- the merge lock ----------------------------------------------------------------------------------------------

class _Slept(Exception):
    pass


def _raise_slept(_seconds):
    raise _Slept


def _acquire_fired(lock_path, ceiling, takeover=None) -> int:
    try:
        MergeLock(lock_path).acquire(max_age_seconds=ceiling, silent_takeover_seconds=takeover)
    except MergeLockTimeout:
        return 1
    except _Slept:
        return 0  # reached the wait: the ceiling did not fire
    return 0


@pytest.mark.parametrize("with_span, fired", [(True, 0), (False, 1)])
def test_merge_lock_age_ceiling(tmp_path, play_span, monkeypatch, with_span, fired):
    now = time.time()
    lock_path = tmp_path / "merge.lock"
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 31 * MIN))
    lock_path.write_text(f'{{"pid": {os.getpid()}, "started": "{started}"}}', encoding="utf-8")
    monkeypatch.setattr(merge_module, "holder_is_live", lambda *a, **k: True)
    monkeypatch.setattr(merge_module.time, "sleep", _raise_slept)
    if with_span:
        play_span(now - 31 * MIN)
    assert _acquire_fired(lock_path, 30 * MIN) == fired  # a 31 min holder against the 30 min ceiling


@pytest.mark.parametrize("with_span, fired", [(True, 0), (False, 1)])
def test_merge_lock_held_and_silent_clocks(tmp_path, play_span, monkeypatch, with_span, fired):
    now = time.time()
    lock_path, progress = tmp_path / "merge.lock", tmp_path / "suite.out"
    progress.write_text("x")
    os.utime(progress, (now - 31 * MIN, now - 31 * MIN))  # output silent 31 min
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))  # held 1 min, ceiling 30 s
    lock_path.write_text(f'{{"pid": {os.getpid()}, "started": "{started}", "progress": "{progress.as_posix()}"}}',
                         encoding="utf-8")
    monkeypatch.setattr(merge_module, "holder_is_live", lambda *a, **k: True)
    monkeypatch.setattr(merge_module.time, "sleep", _raise_slept)
    if with_span:
        play_span(now - 70.0)  # covers the whole held minute (the span runs on into the future)
    # takeover 0 = off: the silent takeover (#62, 30 min) would free a 31 min silent holder before the ceiling is judged
    assert _acquire_fired(lock_path, 30.0, takeover=0.0) == fired


def test_merge_waiter_unreadable_holder_file_age(tmp_path, play_span):
    now = time.time()
    lock_path = tmp_path / "merge.lock"
    lock_path.write_bytes(b"")
    os.utime(lock_path, (now - 11 * MIN, now - 11 * MIN))
    play_span(now - 11 * MIN)  # 11 min old, 10 of them in play
    assert MergeLock(lock_path)._file_age() == pytest.approx(60.0, abs=5.0)


# -- the dispatcher ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("with_span, timeout", [(True, False), (False, True)])
def test_dispatcher_session_max_hours(tmp_path, play_span, with_span, timeout):
    clock = FakeClock()
    claude, gh, d, live_id = _start(tmp_path, [_issue(13)], max_hours=1.0, clock=clock)
    gh.claim(13)
    d.tick()
    clock.advance(63 * MIN)  # 3 min past the 1 h ceiling
    if with_span:
        play_span(time.time() - 63 * MIN)
    report = d.tick()
    assert (report.why == "timeout") is timeout


@pytest.mark.parametrize("with_span, wakes", [(True, 0), (False, 1)])
def test_dispatcher_idle_clock(tmp_path, play_span, monkeypatch, with_span, wakes):
    d = _dispatcher(tmp_path, claude=FakeClaude(), gh=FakeGh(candidates=[]), clock=FakeClock(100000.0))
    d.log = lambda m: None
    woken = []
    monkeypatch.setattr(d, "_wake_idle", lambda cur, now: woken.append(now))
    cur = SimpleNamespace(session="s", session_uuid=None, idle_since=100000.0 - 11 * MIN, idle_woken_at=None,
                          idle_woken_wall=None, finishing=False, name="n", wait_logged=None)
    if with_span:
        play_span(time.time() - 11 * MIN)
    d._idle_clock(cur, "#1")
    assert len(woken) == wakes


@pytest.mark.parametrize("with_span, stood, age", [(True, 10 * MIN, 1 * MIN), (False, 0.0, 11 * MIN)])
def test_dispatcher_stood_since_and_wall_age(tmp_path, play_span, with_span, stood, age):
    d = _dispatcher(tmp_path, claude=FakeClaude(), gh=FakeGh(candidates=[]), clock=FakeClock(100000.0))
    ts = d.timestamp()
    if with_span:
        play_span(ts.timestamp() - 11 * MIN)
    assert d._stood_since(100000.0 - 11 * MIN) == pytest.approx(stood, abs=2.0)
    assert d._wall_age(ts - timedelta(minutes=11)) == pytest.approx(age, abs=5.0)


# -- the tests' own clocks ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("with_span, expired", [(True, False), (False, True)])
def test_test_local_clocks_skip_play(play_span, with_span, expired):
    now = time.time()
    if with_span:
        play_span(now - 10 * MIN)  # ends now
    assert stood_clock.expired(now - 9 * MIN, 30.0) is expired  # the GIT_TIMEOUT clock
    assert stood_clock.expired(now - 9 * MIN, 90.0) is expired  # the _drive clock
