"""#750 unit 3: the PC daemon takes the weekly cut at Friday 20:00 (no PoB, a temp origin + clone)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from junkroan.runs import weekly_cut
from tests.test_runs_daemon import make_daemon

TZ = timezone(timedelta(hours=2))
FRI = "2026-10-16"  # the Friday before Monday 2026-10-19


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return res.stdout.strip()


def make_repos(tmp_path: Path) -> tuple[Path, Path, str]:
    origin, clone, work = tmp_path / "origin.git", tmp_path / "clone", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    git(work, "remote", "add", "origin", str(origin))
    git(work, "commit", "--allow-empty", "-m", "early", date=f"2026-10-14T12:00:00+02:00")
    git(work, "commit", "--allow-empty", "-m", "fri1950", date=f"{FRI}T19:50:00+02:00")
    cut = git(work, "rev-parse", "HEAD")
    git(work, "commit", "--allow-empty", "-m", "fri2010", date=f"{FRI}T20:10:00+02:00")
    git(work, "push", "origin", "main")
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    return origin, clone, cut


def daemon_at(tmp_path: Path, clone: Path, when: datetime, *, host: str = "pc", switch: bool = True):
    daemon, _store, _queue = make_daemon(tmp_path, host=host, hosts_config={"pc": {"fillers": switch}, "laptop": {}})
    daemon.timestamp = lambda: when
    daemon._cut_repo = clone
    daemon._cut_tz = TZ
    return daemon


def at(day: str, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hh, mm, ss, tzinfo=TZ)


def folders(clone: Path) -> list[Path]:
    base = clone / "artifacts" / "benchmark"
    return sorted(base.iterdir()) if base.is_dir() else []


def test_row1_friday_tick_takes_the_1950_commit(tmp_path: Path) -> None:
    _o, clone, cut = make_repos(tmp_path)
    daemon = daemon_at(tmp_path, clone, at(FRI, 20, 0, 10))
    daemon.tick()
    folder = weekly_cut.find_week_folder(clone, weekly_cut.monday_of(at(FRI, 20)))
    assert folder is not None
    assert json.loads((folder / "args.json").read_text(encoding="utf-8"))["commit"] == cut


def test_row1_saturday_first_tick_takes_the_same_commit(tmp_path: Path) -> None:
    _o, clone, cut = make_repos(tmp_path)
    daemon = daemon_at(tmp_path, clone, at("2026-10-17", 3))
    daemon.tick()
    folder = weekly_cut.find_week_folder(clone, weekly_cut.monday_of(at(FRI, 20)))
    assert json.loads((folder / "args.json").read_text(encoding="utf-8"))["commit"] == cut


def test_row2_folder_holds_the_weekly_args(tmp_path: Path) -> None:
    _o, clone, cut = make_repos(tmp_path)
    logs: list[str] = []
    daemon = daemon_at(tmp_path, clone, at(FRI, 21))
    daemon.log = logs.append
    folder = daemon.take_cut_pass()
    assert folder is not None and folder.name.endswith("-week-20261019")
    args = json.loads((folder / "args.json").read_text(encoding="utf-8"))
    assert len(args["slugs"]) == 14 and args["seeds"] == 3 and args["seed"] == 4
    assert args["loop_seconds"] is None and args["commit"] == cut
    assert list((folder / "rows").iterdir()) == []
    assert f"weekly cut {cut[:7]} for 2026-10-19" in logs


def test_second_tick_makes_no_second_folder(tmp_path: Path) -> None:
    _o, clone, _cut = make_repos(tmp_path)
    daemon = daemon_at(tmp_path, clone, at(FRI, 20, 5))
    daemon.take_cut_pass()
    daemon.timestamp = lambda: at(FRI, 20, 6)
    daemon.take_cut_pass()
    daemon.timestamp = lambda: at("2026-10-18", 9)
    daemon.take_cut_pass()
    assert len(folders(clone)) == 1


def test_switch_off_no_folder(tmp_path: Path) -> None:
    _o, clone, _cut = make_repos(tmp_path)
    daemon_at(tmp_path, clone, at(FRI, 21), switch=False).take_cut_pass()
    assert folders(clone) == []


def test_laptop_no_folder(tmp_path: Path) -> None:
    _o, clone, _cut = make_repos(tmp_path)
    daemon_at(tmp_path, clone, at(FRI, 21), host="laptop").take_cut_pass()
    assert folders(clone) == []


def test_before_friday_20_no_folder(tmp_path: Path) -> None:
    _o, clone, _cut = make_repos(tmp_path)
    daemon_at(tmp_path, clone, at(FRI, 19, 59)).take_cut_pass()
    daemon_at(tmp_path, clone, at("2026-10-15", 22)).take_cut_pass()
    assert folders(clone) == []


def test_fetch_failure_does_not_raise_and_retries_after_5_min(tmp_path: Path) -> None:
    _o, clone, cut = make_repos(tmp_path)
    git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    now = [1000.0]
    daemon = daemon_at(tmp_path, clone, at(FRI, 21))
    daemon.clock = lambda: now[0]
    assert daemon.take_cut_pass() is None and folders(clone) == []
    # the origin comes back; inside 5 min nothing is tried, after it the cut is taken
    git(clone, "remote", "set-url", "origin", str(tmp_path / "origin.git"))
    now[0] += 60
    assert daemon.take_cut_pass() is None
    now[0] += 300
    folder = daemon.take_cut_pass()
    assert folder is not None and json.loads((folder / "args.json").read_text(encoding="utf-8"))["commit"] == cut
