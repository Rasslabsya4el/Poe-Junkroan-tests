"""The runs daemon restarts itself at a job boundary (issue #340, unit 2). No PoB, no real process.

The watch and the respawn are duck-typed fakes: the daemon only calls `watch.due()` and `respawn()`.
"""

from __future__ import annotations

from pathlib import Path

from junkroan.runs import daemon as daemon_mod

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: F401  (tests/ is on sys.path)
from test_runs_daemon import _isolated_daemon_status  # noqa: F401  (autouse fixture of that file)

START = "a" * 40
HEAD = "b" * 40


class FakeWatch:
    def __init__(self, result=(START, HEAD), error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def due(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class FakeRespawn:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def build(tmp_path: Path, watch: FakeWatch, respawn: FakeRespawn, *, with_job: bool):
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    lines: list[str] = []
    daemon.log = lines.append
    daemon._restart_watch = watch
    daemon._respawn = respawn
    if with_job:
        store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    return daemon, launcher, lines


def test_running_job_holds_nothing_while_the_watch_is_quiet(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=True)
    sleeps: list[float] = []

    rc = daemon.run(ticks=3, sleep=sleeps.append)

    assert rc == 0
    assert launcher.started  # the job did start and never exited
    assert watch.calls == 3  # consulted every tick since #489
    assert respawn.calls == 0
    assert len(sleeps) == 2
    assert not any("restart at boundary" in line for line in lines)


def test_restart_happens_once_the_job_has_ended(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=True)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:  # the job is running for tick 1; HEAD moves, the job exits before tick 2
            watch.result = (START, HEAD)
            launcher.finish(launcher.started[0]["pid"], 0)

    rc = daemon.run(ticks=5, sleep=sleep)

    assert rc == 0
    assert respawn.calls == 1
    assert [line for line in lines if "restart at boundary" in line] == [
        f"restart at boundary: {START[:12]} -> {HEAD[:12]}"
    ]
    assert len(sleeps) == 1  # returned at tick 2, before its 5-tick budget and without a sleep


def test_no_job_and_watch_not_due_runs_every_tick(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, _, lines = build(tmp_path, watch, respawn, with_job=False)
    sleeps: list[float] = []

    rc = daemon.run(ticks=3, sleep=sleeps.append)

    assert rc == 0
    assert watch.calls == 3
    assert respawn.calls == 0
    assert len(sleeps) == 2
    assert not any("restart at boundary" in line for line in lines)


def test_respawn_failure_is_logged_and_the_loop_continues(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(), FakeRespawn(error=OSError("no python"))
    daemon, _, lines = build(tmp_path, watch, respawn, with_job=False)
    sleeps: list[float] = []

    rc = daemon.run(ticks=3, sleep=sleeps.append)

    assert rc == 0
    assert len(sleeps) == 2  # every tick ran
    assert respawn.calls == 3  # due again on each idle tick: the retry is fine
    failed = [line for line in lines if line.startswith("restart at boundary failed")]
    assert len(failed) == 3 and "no python" in failed[0]


def test_watch_failure_is_logged_and_the_loop_continues(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(error=RuntimeError("git gone")), FakeRespawn()
    daemon, _, lines = build(tmp_path, watch, respawn, with_job=False)
    sleeps: list[float] = []

    rc = daemon.run(ticks=3, sleep=sleeps.append)

    assert rc == 0
    assert len(sleeps) == 2
    assert respawn.calls == 0
    failed = [line for line in lines if line.startswith("restart watch failed")]
    assert len(failed) == 3 and "git gone" in failed[0]


def test_both_unset_is_todays_behaviour(tmp_path: Path) -> None:
    daemon, _, _ = make_daemon(tmp_path)
    sleeps: list[float] = []

    assert daemon.run(ticks=3, sleep=sleeps.append) == 0
    assert len(sleeps) == 2


# -- #489: the boundary is between jobs, not after a tick that already filled ------------------------

def two_jobs(tmp_path: Path, watch: FakeWatch, respawn: FakeRespawn):
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    store = daemon.store
    for tag in ("a", "b"):
        store.submit(host="pc", priority="P2", tag=tag, cmd="echo " + tag, workers=5)
    return daemon, launcher, lines, store


def queued(store) -> list[str]:
    return [j.tag for j in store.jobs() if j.state == "queued"]


def test_head_moves_and_job_ends_restarts_before_the_next_job(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines, store = two_jobs(tmp_path, watch, respawn)
    first = daemon.tick()
    assert len(first.started) == 1 and len(launcher.started) == 1
    watch.result = (START, HEAD)
    launcher.finish(launcher.started[0]["pid"], 0)

    report = daemon.tick()

    assert report.started == [] and report.restarting
    assert respawn.calls == 1
    assert any("restart at boundary" in line for line in lines)
    assert len(launcher.started) == 1 and queued(store) == ["b"]


def test_run_returns_zero_at_the_restart_tick(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines, store = two_jobs(tmp_path, watch, respawn)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            watch.result = (START, HEAD)
            launcher.finish(launcher.started[0]["pid"], 0)

    assert daemon.run(ticks=6, sleep=sleep) == 0
    assert respawn.calls == 1 and len(sleeps) == 1 and queued(store) == ["b"]


def test_no_head_move_next_job_starts_in_the_tick_the_first_ends(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines, store = two_jobs(tmp_path, watch, respawn)
    daemon.tick()
    launcher.finish(launcher.started[0]["pid"], 0)

    report = daemon.tick()

    assert len(report.started) == 1 and not report.restarting
    assert respawn.calls == 0 and queued(store) == []


def test_head_moved_while_job_runs_starts_go_on_then_restarts(tmp_path: Path) -> None:
    # #598: a moved HEAD no longer holds starts; the daemon restarts at the first idle tick
    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    store = daemon.store
    store.submit(host="pc", priority="P2", tag="a", cmd="echo a", workers=1)
    daemon.tick()
    store.submit(host="pc", priority="P2", tag="c", cmd="echo c", workers=1)
    watch.result = (START, HEAD)

    report = daemon.tick()  # the small job still starts, nothing is held

    assert len(report.started) == 1 and not report.restarting and respawn.calls == 0
    assert queued(store) == []
    assert not any("holding new starts" in line for line in lines)

    for row in list(launcher.started):
        launcher.finish(row["pid"], 0)
    assert daemon.tick().restarting and respawn.calls == 1


def test_replacement_whose_start_is_head_restarts_nothing(tmp_path: Path) -> None:
    watch, respawn = FakeWatch(result=None), FakeRespawn()  # RestartWatch.due() is None when start == HEAD
    daemon, launcher, lines, store = two_jobs(tmp_path, watch, respawn)
    for _ in range(3):
        assert not daemon.tick().restarting
    assert respawn.calls == 0


# -- #517: a running filler never holds the restart ---------------------------------------------


def _filler_daemon(tmp_path: Path, *, with_p1: bool, kill_ok: bool = True):
    from junkroan.runs.store import CLASS_FILLER

    watch, respawn = FakeWatch(result=None), FakeRespawn()
    daemon, launcher, lines = build(tmp_path, watch, respawn, with_job=False)
    daemon._spike_killer = lambda pid: kill_ok
    store = daemon.store
    p1 = None
    if with_p1:
        p1 = store.submit(host="pc", priority="P1", tag="p1", cmd="echo p1")
    filler = store.submit(host="pc", priority="P2", tag="fill", cmd="echo f", job_class=CLASS_FILLER)
    daemon.fill()
    assert store.get(filler.id).state == "running"
    watch.result = (START, HEAD)
    return daemon, store, launcher, respawn, lines, filler, p1


def test_only_a_filler_running_neither_stopped_nor_holding_the_restart(tmp_path: Path) -> None:
    daemon, store, _, respawn, lines, filler, _ = _filler_daemon(tmp_path, with_p1=False)
    killed: list[int] = []
    daemon._spike_killer = lambda pid: killed.append(pid) or True
    report = daemon_mod.TickReport()

    daemon._restart_gate(report)

    assert store.get(filler.id).state == "running" and killed == []  # #751 rule 6: 0 stopped
    assert respawn.calls == 1 and report.restarting is True
    assert not any("holding new starts" in line for line in lines)


def test_p1_and_filler_running_both_kept_restart_waits_for_p1_only(tmp_path: Path) -> None:
    daemon, store, launcher, respawn, lines, filler, p1 = _filler_daemon(tmp_path, with_p1=True)
    killed: list[int] = []
    daemon._spike_killer = lambda pid: killed.append(pid) or True
    report = daemon_mod.TickReport()
    assert store.get(p1.id).state == "running"

    assert daemon._restart_gate(report) is False  # P1 still runs, 900 s not reached: no hold, no restart

    assert store.get(filler.id).state == "running" and killed == []
    assert respawn.calls == 0
    assert not any("holding new starts" in line for line in lines)

    launcher.finish(store.get(p1.id).pid, 0)
    daemon.reap()
    report2 = daemon_mod.TickReport()
    daemon._restart_gate(report2)  # the filler still runs: it does not hold the restart
    assert respawn.calls == 1 and report2.restarting is True
    assert store.get(filler.id).state == "running" and killed == []
