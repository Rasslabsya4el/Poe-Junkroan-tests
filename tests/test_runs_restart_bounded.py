"""#598: a moved HEAD never holds job starts; the restart comes at the first idle tick or 900 s later."""

from __future__ import annotations

from pathlib import Path

from junkroan.runs import daemon as daemon_mod

from test_runs_daemon_restart import (  # noqa: F401
    HEAD, START, FakeRespawn, FakeWatch, _isolated_daemon_status, build, queued,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _setup(tmp_path: Path, *, small: bool = True):
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    clock = Clock()
    daemon.clock = clock
    store = daemon.store
    store.submit(host="pc", priority="P2", tag="long", cmd="echo long", workers=1)
    daemon.tick()
    assert len(launcher.started) == 1
    if small:
        store.submit(host="pc", priority="P2", tag="small", cmd="echo small", workers=1)
    return daemon, launcher, lines, store, watch, respawn, clock


def test_constant() -> None:
    assert daemon_mod.RESTART_MAX_WAIT_SECONDS == 900


def test_a_small_job_starts_after_head_moved(tmp_path: Path) -> None:
    daemon, launcher, lines, store, watch, respawn, clock = _setup(tmp_path)
    watch.result = (START, HEAD)

    report = daemon.tick()

    assert len(report.started) == 1 and queued(store) == []
    assert len(launcher.started) == 2 and respawn.calls == 0
    assert not any("holding new starts" in line for line in lines)


def test_respawn_at_900_seconds_adopting_the_running_job(tmp_path: Path) -> None:
    daemon, launcher, lines, store, watch, respawn, clock = _setup(tmp_path, small=False)
    watch.result = (START, HEAD)
    running = [j for j in store.jobs() if j.state == "running"][0]
    t0 = clock.now
    for offset in (0, 600, 899):
        clock.now = t0 + offset
        assert not daemon.tick().restarting
    assert respawn.calls == 0

    clock.now = t0 + 900
    report = daemon.tick()

    assert report.restarting and respawn.calls == 1
    assert [x for x in lines if "restart at boundary" in x] == [
        f"restart at boundary: {START[:12]} -> {HEAD[:12]}, adopting 1 running job(s)"]
    after = store.get(running.id)
    assert after.state == "running" and after.pid == running.pid
    assert not getattr(launcher, "killed", [])


def test_a_second_head_move_does_not_reset_the_wait(tmp_path: Path) -> None:
    daemon, launcher, lines, store, watch, respawn, clock = _setup(tmp_path, small=False)
    watch.result = (START, HEAD)
    t0 = clock.now
    daemon.tick()
    clock.now = t0 + 600
    watch.result = (START, "c" * 40)
    assert not daemon.tick().restarting
    clock.now = t0 + 900
    assert daemon.tick().restarting and respawn.calls == 1


def test_nothing_running_restarts_at_once_without_adopting(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=(START, HEAD)), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    daemon.clock = Clock()

    assert daemon.tick().restarting and respawn.calls == 1
    assert [x for x in lines if "restart at boundary" in x] == [
        f"restart at boundary: {START[:12]} -> {HEAD[:12]}"]


def test_a_running_filler_is_stopped_and_the_queued_job_still_starts(tmp_path: Path) -> None:
    from junkroan.runs.store import CLASS_FILLER

    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    daemon._spike_killer = lambda pid: True
    store = daemon.store
    filler = store.submit(host="pc", priority="P2", tag="fill", cmd="echo f", job_class=CLASS_FILLER)
    daemon.fill()
    assert store.get(filler.id).state == "running"
    store.submit(host="pc", priority="P1", tag="job", cmd="echo j", workers=1)
    watch.result = (START, HEAD)

    report = daemon.tick()

    assert store.get(filler.id).state == "stopped"
    assert len(report.started) == 1 or report.restarting
    assert not any("holding new starts" in line for line in lines)
