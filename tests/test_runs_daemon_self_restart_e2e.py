"""Acceptance of issue #340: the daemon restarts itself at a job boundary. Real `RestartWatch` on a fake git,
real `self_restart.respawn` on a fake popen, `cmd_daemon` through `runs.main`. No PoB, no real process."""

from __future__ import annotations

import functools
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: F401  (tests/ is on sys.path)
from test_runs_daemon import _isolated_daemon_status  # noqa: F401  (autouse fixture of that file)
from test_runs_daemon import _RecordingDaemon, runs

from junkroan.runs import daemon as daemon_mod
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import self_restart

A = "a" * 40
B = "b" * 40
C = "c" * 40


class FakeGit:
    """Answers `rev-parse HEAD` and `diff --name-only A..X -- <paths>` from dicts the test mutates."""

    def __init__(self, head: str) -> None:
        self.head = head
        self.diffs: dict[str, str] = {}

    def __call__(self, args: list[str]) -> str:
        if args == ["rev-parse", "HEAD"]:
            return self.head + "\n"
        if args[0] == "diff" and args[1] == "--name-only":
            return self.diffs.get(args[2].split("..")[1], "")
        raise AssertionError(f"unexpected git call {args}")


class FakePopen:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return type("Child", (), {"pid": 4242})()


def build(tmp_path: Path, git: FakeGit, popen: FakePopen, *, with_job: bool):
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher)
    lines: list[str] = []
    daemon.log = lines.append
    daemon._restart_watch = self_restart.RestartWatch(A, git)
    daemon._respawn = functools.partial(self_restart.respawn, popen=popen)
    if with_job:
        store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    return daemon, launcher, lines


def restart_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "restart at boundary" in line]


def test_code_change_restarts_only_after_the_job_ends(tmp_path: Path) -> None:
    git, popen = FakeGit(A), FakePopen()
    daemon, launcher, lines = build(tmp_path, git, popen, with_job=True)
    daemon.tick()  # HEAD unmoved: the job starts
    git.head = B
    git.diffs[B] = "src/junkroan/runs/daemon.py\n"

    assert daemon.run(ticks=3, sleep=lambda s: None) == 0
    assert launcher.started and popen.calls == [] and restart_lines(lines) == []

    launcher.finish(launcher.started[0]["pid"], 0)
    sleeps: list[float] = []
    assert daemon.run(ticks=3, sleep=sleeps.append) == 0

    assert restart_lines(lines) == [f"restart at boundary: {A[:12]} -> {B[:12]}"]
    assert sleeps == []  # within the first tick
    assert len(popen.calls) == 1
    cmd, kwargs = popen.calls[0]
    assert cmd == [sys.executable, *sys.argv]
    assert kwargs["env"][self_restart.REPLACES_ENV] == str(os.getpid())


def test_commit_outside_the_watched_paths_restarts_nothing(tmp_path: Path) -> None:
    git, popen = FakeGit(A), FakePopen()
    daemon, _, lines = build(tmp_path, git, popen, with_job=False)
    git.head = C  # a docs/STATE.md commit: the diff over the watched paths is blank
    git.diffs[C] = ""

    assert daemon.run(ticks=3, sleep=lambda s: None) == 0
    assert popen.calls == [] and restart_lines(lines) == []


# -- cmd_daemon ---------------------------------------------------------------------------------

def run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> dict:
    monkeypatch.setattr(self_restart.RestartWatch, "from_repo",
                        classmethod(lambda cls, repo, log=None: cls(A, FakeGit(A), log=log)))
    monkeypatch.setattr(daemon_mod, "Daemon", _RecordingDaemon)
    _RecordingDaemon.instances = []
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "daemon", "--host", "pc", *args])
    assert rc == 0
    return _RecordingDaemon.instances[-1]


def test_cli_default_turns_self_restart_on(tmp_path, monkeypatch, capsys) -> None:
    kwargs = run_cli(tmp_path, monkeypatch)
    assert isinstance(kwargs["restart_watch"], self_restart.RestartWatch)
    assert kwargs["respawn"] is self_restart.respawn
    assert f"self-restart on {A[:12]}" in capsys.readouterr().out


@pytest.mark.parametrize("args", [("--ticks", "1"), ("--no-self-restart",)])
def test_cli_ticks_or_flag_turns_it_off(tmp_path, monkeypatch, capsys, args) -> None:
    kwargs = run_cli(tmp_path, monkeypatch, *args)
    assert kwargs["restart_watch"] is None and kwargs["respawn"] is None
    assert "self-restart off" in capsys.readouterr().out


def test_cli_replacement_waits_for_its_predecessor_then_starts(tmp_path, monkeypatch, capsys) -> None:
    pid = 987654
    daemon_mod.write_daemon_status(runs_hosts.daemon_status_path("pc"), {
        "host": "pc", "pid": pid, "started": "2026-09-27T00:00:00+00:00",
        "last_tick": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tick_seconds": 10.0, "running": [], "queued": 0,
    })
    polls = {"n": 0}

    def pid_alive(self, p: int) -> bool:
        polls["n"] += 1
        return polls["n"] <= 2 or p != pid

    monkeypatch.setattr(daemon_mod.QueueBackend, "pid_alive", pid_alive)
    real_wait = self_restart.wait_for_predecessor
    monkeypatch.setattr(self_restart, "wait_for_predecessor",
                        lambda env, alive: real_wait(env, alive, sleep=lambda s: None))
    monkeypatch.setenv(self_restart.REPLACES_ENV, str(pid))

    kwargs = run_cli(tmp_path, monkeypatch)

    assert kwargs is not None  # the guard did not exit: the daemon was built
    out = capsys.readouterr().out
    assert f"replacing pid {pid}" in out and "already live" not in out
