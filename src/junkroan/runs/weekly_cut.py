"""The weekly core run's cut (#750 unit 1): its arguments in one place, the commit it is pinned at, its folder.

The week is named by its Monday. The cut is the full sha `origin/main` had at 20:00 LOCAL time on the Friday
before that Monday, read from git history, never "main when called". A re-cut is an override in
`config/weekly_cut.json` on origin/main (`{"<YYYYmmdd of Monday>": "<sha>"}`) and wins. Nothing here fetches.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path

WEEKLY_ARGV = ["--set", "core14", "--gear", "wishlist", "--seed", "4", "--seeds", "3", "--workers", "auto"]
OVERRIDE_PATH = "config/weekly_cut.json"
CUT_HOUR = 20


def weekly_args() -> dict:
    """args.json of the weekly core run (without `commit`), as `benchmark.resolve_run_config` writes it for
    WEEKLY_ARGV: the parser defaults (loop_seconds is `LOOP_SECONDS_DEFAULT`, None: no clock, #956) plus core14, gear, seeds."""

    import argparse

    root = Path(__file__).resolve().parents[3]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import benchmark

    ns = argparse.Namespace(
        slugs=list(benchmark.SETS["core14"]), seeds=3, seed=4, loop_seconds=benchmark.LOOP_SECONDS_DEFAULT,
        no_variants=False, gear=benchmark.resolve_gear("wishlist"), construction="classic", construction_only=False,
        stat=None, ablate=None, tree_depth=6, tree_trials=300, cluster_candidates=False, skip_inert=False,
        fulldps_shortcut=False, fixed_point_check=True, record_calls=None, force_keystone=None)
    config = benchmark.resolve_run_config(ns)
    config.pop("commit", None)
    return config


def monday_of(dt: datetime | date) -> date:
    """The Monday naming the week a moment belongs to: the first Monday on or after its date. Mon -> that
    Monday; Tue-Fri (before or after the 20:00 cut), Sat, Sun -> the coming Monday. The cut of that Monday is
    the Friday 20:00 before it, so the time of day never changes the answer."""

    d = dt.date() if isinstance(dt, datetime) else dt
    return d + timedelta(days=(-d.weekday()) % 7)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def _override(repo: Path, monday: date) -> str | None:
    res = _git(repo, "show", f"origin/main:{OVERRIDE_PATH}")
    if res.returncode != 0:
        return None
    try:
        return json.loads(res.stdout).get(monday.strftime("%Y%m%d"))
    except (ValueError, AttributeError):
        return None


def cut_for_week(repo: Path, monday: date, tz: tzinfo | None = None) -> str:
    """Full sha of origin/main at Friday 20:00 (local, or `tz`) before `monday`; the override wins."""

    over = _override(repo, monday)
    if over:
        return over
    friday = datetime(monday.year, monday.month, monday.day, CUT_HOUR) - timedelta(days=3)
    friday = friday.replace(tzinfo=tz) if tz is not None else friday.astimezone()
    res = _git(repo, "rev-list", "-1", f"--before={friday.isoformat()}", "origin/main")
    sha = res.stdout.strip()
    if res.returncode != 0 or not sha:
        raise RuntimeError(f"no commit on origin/main at or before {friday.isoformat()} (week {monday:%Y%m%d}): {res.stderr.strip()}")
    return sha


def record_override(repo: Path, monday: date, sha: str) -> None:
    path = Path(repo) / OVERRIDE_PATH
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[monday.strftime("%Y%m%d")] = sha
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def find_week_folder(root: Path, monday: date) -> Path | None:
    base = Path(root) / "artifacts" / "benchmark"
    if not base.is_dir():
        return None
    pat = re.compile(rf"^\d{{8}}-\d{{4}}-week-{monday:%Y%m%d}$")
    hits = sorted(p for p in base.iterdir() if p.is_dir() and pat.match(p.name))
    return hits[0] if hits else None


def open_week_folder(root: Path, monday: date, cut: str, now: datetime | None = None) -> Path:
    existing = find_week_folder(root, monday)
    if existing is not None:
        return existing
    now = now or datetime.now()
    folder = Path(root) / "artifacts" / "benchmark" / f"{now:%Y%m%d-%H%M}-week-{monday:%Y%m%d}"
    (folder / "rows").mkdir(parents=True)
    (folder / "args.json").write_text(json.dumps({**weekly_args(), "commit": cut}, indent=1), encoding="utf-8")
    return folder


def drop_week_folder(folder: Path, old_cut: str) -> Path:
    target = folder.with_name(f"{folder.name}-dropped-{old_cut[:7]}")
    folder.rename(target)
    return target
