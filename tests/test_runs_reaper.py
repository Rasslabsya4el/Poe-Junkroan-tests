"""#353: a `running` job whose pid is gone never stays `running`; the next queued job starts at once."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_runs_daemon import FakeLauncher, make_daemon


def _submit(store, tag: str, workers: int = 1):
    return store.submit(host="pc", priority="P1", tag=tag, cmd=f"echo {tag}", workers=workers)


def test_killed_daemon_job_is_ended_lost_pid_and_next_starts_same_tick(tmp_path: Path) -> None:
    launcher_a = FakeLauncher()
    daemon_a, store_a, _ = make_daemon(tmp_path, launcher=launcher_a)
    job_j = _submit(store_a, "j", workers=2)
    assert daemon_a.tick().started == [job_j.id]
    pid = launcher_a.started[0]["pid"]
    del daemon_a  # the daemon dies mid-job; the store keeps J `running`

    launcher_b = FakeLauncher()
    launcher_b.dead_pids.add(pid)
    daemon_b, store_b, _ = make_daemon(tmp_path, launcher=launcher_b)
    job_k = _submit(store_b, "k", workers=2)
    assert daemon_b.recover() == [job_j.id]
    ended = store_b.get(job_j.id)
    assert ended.state == "failed" and ended.rc is None and f"lost pid {pid}" in ended.reason

    assert daemon_b.tick().started == [job_k.id]      # same tick, the freed slots count at once
    assert store_b.get(job_k.id).state == "running"


def test_recover_then_one_tick_frees_and_starts_when_recover_was_not_called(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    job_j = _submit(store, "j", workers=2)
    store.start(job_j.id, out=str(tmp_path / "runs" / "j.out"), pid=8148)
    launcher.dead_pids.add(8148)
    job_k = _submit(store, "k", workers=2)

    report = daemon.tick()                              # no recover(): the tick itself reaps it
    assert report.ended == [job_j.id] and report.started == [job_k.id]
    assert store.get(job_j.id).reason == "lost pid 8148" and store.get(job_j.id).rc is None


def test_adopted_job_whose_pid_dies_is_ended_on_the_next_tick(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    job = _submit(store, "j")
    store.start(job.id, out=str(tmp_path / "runs" / "j.out"), pid=8148)
    assert daemon.recover() == []                        # live pid: adopted, not ended
    assert store.get(job.id).state == "running"

    launcher.dead_pids.add(8148)
    assert daemon.tick().ended == [job.id]
    ended = store.get(job.id)
    assert ended.rc is None and ended.reason == "lost pid 8148"


def test_running_job_this_daemon_never_adopted_is_checked_every_tick(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    assert daemon.recover() == []
    job = _submit(store, "late")                          # written by someone else after recover()
    store.start(job.id, out=str(tmp_path / "runs" / "late.out"), pid=7777)
    assert daemon.tick().ended == []                      # alive
    launcher.dead_pids.add(7777)
    assert daemon.tick().ended == [job.id]
    assert store.get(job.id).reason == "lost pid 7777"


@pytest.mark.parametrize("pid", [8148, "8148"])
def test_pid_as_int_or_string_is_handled_the_same(tmp_path: Path, pid) -> None:
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    job = _submit(store, "j")
    store.start(job.id, out=str(tmp_path / "runs" / "j.out"), pid=pid)
    launcher.dead_pids.add(8148)
    assert daemon.recover() == [job.id]
    ended = store.get(job.id)
    assert ended.rc is None and ended.reason == "lost pid 8148"
