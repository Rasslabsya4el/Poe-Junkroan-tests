"""Issue #444: a daemon running from a detached `daemon_repo_path` checkout follows `origin/main` at the
boundary. Real temporary git repos (a bare origin + a clone); no PoB, no real process."""

from __future__ import annotations

import functools
import os
import shutil
import stat
import subprocess
from pathlib import Path

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: F401  (tests/ is on sys.path)
from test_runs_daemon import _isolated_daemon_status  # noqa: F401  (autouse fixture of that file)
from test_runs_daemon_self_restart_e2e import FakePopen

from junkroan.runs import self_restart


def rmtree(path: Path) -> None:
    def onexc(func, p, exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=onexc)


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_pair(tmp_path: Path, *, detached: bool = True) -> tuple[Path, Path, str, str]:
    """(origin, clone, first sha, second sha): origin/main is one commit ahead of the clone's HEAD."""
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "init", "-q", "-b", "main")
    sh(work, "config", "user.email", "t@t")
    sh(work, "config", "user.name", "t")
    (work / "src" / "junkroan" / "runs").mkdir(parents=True)
    (work / "src" / "junkroan" / "runs" / "x.py").write_text("1\n")
    sh(work, "add", "-A")
    sh(work, "commit", "-q", "-m", "one")
    first = sh(work, "rev-parse", "HEAD")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    clone = tmp_path / "daemon"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    if detached:
        sh(clone, "checkout", "-q", "--detach", "origin/main")
    (work / "src" / "junkroan" / "runs" / "x.py").write_text("2\n")
    sh(work, "commit", "-q", "-am", "two")
    second = sh(work, "rev-parse", "HEAD")
    sh(work, "push", "-q", str(origin), "main")
    return origin, clone, first, second


def build(tmp_path: Path, clone: Path, daemon_repo_path: str | None, *, with_job: bool):
    (tmp_path / "d").mkdir()
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path / "d", launcher=launcher)
    lines: list[str] = []
    daemon.log = lines.append
    daemon._restart_watch = self_restart.RestartWatch.from_repo(clone, log=lines.append)
    popen = FakePopen()
    daemon._respawn = functools.partial(self_restart.respawn, popen=popen)
    daemon._follow_main = self_restart.FollowMain(
        clone, daemon_repo_path, self_restart.git_runner(clone), log=lines.append)
    if with_job:
        store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    return daemon, launcher, lines, popen


def test_no_job_running_moves_head_and_restarts(tmp_path: Path) -> None:
    _, clone, first, second = make_pair(tmp_path)
    daemon, _, lines, popen = build(tmp_path, clone, str(clone), with_job=False)

    assert daemon.tick().restarting is True
    assert sh(clone, "rev-parse", "HEAD") == second
    assert f"restart at boundary: {first[:12]} -> {second[:12]}" in lines
    assert len(popen.calls) == 1


def test_a_running_job_is_never_cut_by_a_restart(tmp_path: Path) -> None:
    _, clone, _, _ = make_pair(tmp_path)
    daemon, launcher, _, popen = build(tmp_path, clone, str(clone), with_job=True)

    follow, daemon._follow_main = daemon._follow_main, None
    daemon.tick()  # the job starts while nothing follows main
    assert launcher.started
    daemon._follow_main = follow
    daemon.run(ticks=2, sleep=lambda s: None)  # a job runs: HEAD may follow main (#489) but no restart
    assert popen.calls == []


def test_branch_or_other_path_runs_nothing(tmp_path: Path) -> None:
    _, clone, first, _ = make_pair(tmp_path, detached=False)  # a branch is checked out
    daemon, _, _, popen = build(tmp_path, clone, str(clone), with_job=False)
    assert daemon.tick().restarting is False
    assert sh(clone, "rev-parse", "HEAD") == first and popen.calls == []

    sh(clone, "checkout", "-q", "--detach", "HEAD")  # detached now, but not the daemon_repo_path
    other = self_restart.FollowMain(clone, str(tmp_path / "elsewhere"), self_restart.git_runner(clone))
    assert other.step() is False
    assert self_restart.FollowMain(clone, None, self_restart.git_runner(clone)).step() is False
    assert sh(clone, "rev-parse", "HEAD") == first


def test_failed_fetch_is_one_line_and_head_stays(tmp_path: Path) -> None:
    origin, clone, first, _ = make_pair(tmp_path)
    rmtree(origin)
    daemon, _, lines, popen = build(tmp_path, clone, str(clone), with_job=False)

    assert daemon.tick().restarting is False
    assert len([line for line in lines if "follow main: git fetch failed" in line]) == 1
    assert sh(clone, "rev-parse", "HEAD") == first and popen.calls == []


def test_fetch_is_rate_limited(tmp_path: Path) -> None:
    origin, clone, _, _ = make_pair(tmp_path)
    now = [1000.0]
    seen: list[list[str]] = []
    real = self_restart.git_runner(clone)

    def spy(args: list[str]) -> str:
        seen.append(args)
        return real(args)

    follow = self_restart.FollowMain(clone, str(clone), spy, clock=lambda: now[0])
    rmtree(origin)
    assert follow.step() is False
    now[0] += 10
    assert follow.step() is False
    assert seen.count(["fetch", "origin"]) == 1
    now[0] += 400
    follow.step()
    assert seen.count(["fetch", "origin"]) == 2


# -- #861: 3 failed checkouts in a row = one `follow_main_failed` anomaly ---------------------------

def _dirty_clone(clone: Path) -> None:
    (clone / "src" / "junkroan" / "runs" / "x.py").write_text("local edit\n")  # origin/main changes this file


def _guarded(tmp_path: Path, clone: Path):
    """A follow-main that retries every tick, and a real AnomalyGuard fed the way the daemon feeds it."""
    from test_runs_anomalies import make_guard

    follow = self_restart.FollowMain(clone, str(clone), self_restart.git_runner(clone), every=0.0)
    guard, launcher = make_guard(tmp_path)
    guard.host = "laptop"

    def tick() -> list[str]:
        follow.step()
        launcher.finish_all()  # one keymaster at a time: every new anomaly starts at once
        guard.check(follow_main=follow.streak())
        return [a.key for a, _ in launcher.started]

    return follow, guard, launcher, tick


def test_three_failed_checkouts_raise_one_anomaly(tmp_path: Path) -> None:
    _, clone, _, _ = make_pair(tmp_path)
    _dirty_clone(clone)
    follow, _, launcher, tick = _guarded(tmp_path, clone)

    assert tick() == [] and tick() == []
    keys = tick()
    assert len(keys) == 1 and keys[0].startswith("follow_main_failed:laptop:")
    anomaly = launcher.started[0][0]
    assert anomaly.kind == "follow_main_failed" and "x.py" in anomaly.detail
    assert len(tick()) == 1  # the 4th failure of the same streak adds 0
    assert follow.fail_count == 4


class ScriptedGit:
    """A git runner for the streak counting: origin/main is always ahead; `checkout` fails while `dirty`."""

    def __init__(self) -> None:
        self.dirty = True

    def __call__(self, args: list[str]) -> str:
        if args[0] == "symbolic-ref":
            raise subprocess.CalledProcessError(1, args)  # detached
        if args[0] == "rev-parse":
            return "aaaa" if args[1] == "HEAD" else "bbbb"
        if args[0] == "checkout" and self.dirty:
            raise subprocess.CalledProcessError(1, args, stderr="error: Your local changes would be overwritten\nAborting\n")
        return ""


def _scripted(tmp_path: Path):
    from test_runs_anomalies import make_guard

    git = ScriptedGit()
    ids = iter(range(1000, 2000))
    follow = self_restart.FollowMain(tmp_path, str(tmp_path), git, every=0.0)
    guard, launcher = make_guard(tmp_path)
    guard.host = "laptop"

    def tick() -> int:
        before = follow.streak_id
        follow.step()
        if follow.streak_id is not None and follow.streak_id != before:
            follow.streak_id = str(next(ids))  # a distinct id per streak, whatever the wall clock says
        launcher.finish_all()
        guard.check(follow_main=follow.streak())
        return len(launcher.started)

    return git, follow, launcher, tick


def test_a_success_resets_the_streak(tmp_path: Path) -> None:
    git, follow, launcher, tick = _scripted(tmp_path)
    tick(); tick()                      # 2 fails
    git.dirty = False
    tick()                              # success
    assert follow.fail_count == 0
    git.dirty = True
    tick(); tick()                      # 2 fails of a new streak
    assert launcher.started == []
    assert tick() == 1                  # the 3rd of the new streak


def test_a_new_streak_after_a_streak_and_a_success_raises_a_second_one(tmp_path: Path) -> None:
    git, follow, launcher, tick = _scripted(tmp_path)
    tick(); tick()
    assert tick() == 1 and "Your local changes" in launcher.started[0][0].detail
    assert tick() == 1                  # 4th of the same streak: still 1
    git.dirty = False
    tick()
    assert follow.streak() is None
    git.dirty = True
    tick(); tick()
    assert len(launcher.started) == 1
    assert tick() == 2
    assert launcher.started[0][0].key != launcher.started[1][0].key
