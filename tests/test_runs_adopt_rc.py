"""#598 unit 3: a job adopted from a dead daemon ends with its own rc, not `lost pid`."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from junkroan.runs import daemon as daemon_mod

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: F401  (tests/ is on sys.path)
from test_runs_daemon import _isolated_daemon_status  # noqa: F401  (autouse fixture of that file)

windows_only = pytest.mark.skipif(os.name != "nt", reason="exit code of an adopted pid is Windows-only")


def _adopt_and_wait(tmp_path: Path, exit_code: int):
    child = subprocess.Popen([sys.executable, "-c", f"import time,sys; time.sleep(3); sys.exit({exit_code})"])
    try:
        daemon, store, _ = make_daemon(tmp_path, launcher=daemon_mod.ProcessLauncher())
        job = store.submit(host="pc", priority="P1", tag="adopt", cmd="x", workers=1)
        store.start(job.id, out=str(tmp_path / "runs" / "adopt.out"), pid=child.pid)
        logs: list[str] = []
        daemon.log = logs.append
        daemon.recover()
        assert any(f"adopted running job {job.id} (pid {child.pid})" in line for line in logs)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            daemon.reap()
            if job.id not in daemon._active:
                break
            time.sleep(0.2)
        return store.get(job.id) if hasattr(store, "get") else next(j for j in store.jobs() if j.id == job.id), job, child
    finally:
        child.kill()
        child.wait()


@windows_only
def test_adopted_job_ends_failed_with_its_own_rc(tmp_path: Path) -> None:
    ended, job, child = _adopt_and_wait(tmp_path, 3)
    assert ended.state == "failed" and ended.rc == 3
    assert ended.id == job.id and int(ended.pid) == child.pid
    assert "lost pid" not in (ended.reason or "")


@windows_only
def test_adopted_job_with_rc_zero_is_done(tmp_path: Path) -> None:
    ended, job, child = _adopt_and_wait(tmp_path, 0)
    assert ended.state == "done" and ended.rc == 0
    assert "lost pid" not in (ended.reason or "")


def test_launcher_without_exit_watch_keeps_the_lost_pid_path(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    job = store.submit(host="pc", priority="P1", tag="nw", cmd="x", workers=1)
    store.start(job.id, out=str(tmp_path / "runs" / "nw.out"), pid=7777)
    daemon.recover()
    assert daemon._active[job.id].watch is None
    launcher.dead_pids.add(7777)
    assert daemon.reap() == [job.id]
    ended = next(j for j in store.jobs() if j.id == job.id)
    assert ended.state == "failed" and ended.rc is None and ended.reason == f"lost pid 7777"


def test_exit_watch_that_raises_still_adopts(tmp_path: Path) -> None:
    class Boom(FakeLauncher):
        def exit_watch(self, pid: int):
            raise OSError("no handle")

    launcher = Boom()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    job = store.submit(host="pc", priority="P1", tag="boom", cmd="x", workers=1)
    store.start(job.id, out=str(tmp_path / "runs" / "boom.out"), pid=6666)
    daemon.recover()
    assert job.id in daemon._active and daemon._active[job.id].watch is None
    launcher.dead_pids.add(6666)
    assert daemon.reap() == [job.id]
    ended = next(j for j in store.jobs() if j.id == job.id)
    assert ended.rc is None and ended.reason == "lost pid 6666"
