"""Estimate how long one build of a slug takes, from rows already measured.

A row (`<run>/rows/<slug>-s<seed>[-variant].json`) carries `slug`, `seconds` and `ok`;
the loop budget is not in the row but in the run's `args.json` (`loop_seconds`).
A weekly run is a folder whose name holds the word `gate`.
"""

from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path


FALLBACK_SECONDS = 68.6 * 60


def _read_rows(run_dir: Path) -> list[tuple[str, float]]:
    """(slug, seconds) of every readable finished row of one run."""

    out: list[tuple[str, float]] = []
    for path in (run_dir / "rows").glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            seconds = float(row["seconds"])
            slug = str(row["slug"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if row.get("ok") is False or seconds <= 0:
            continue
        out.append((slug, seconds))
    return out


def _loop_seconds(run_dir: Path) -> float | None:
    try:
        value = json.loads((run_dir / "args.json").read_text(encoding="utf-8")).get("loop_seconds")
        return None if value is None else float(value)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _construction_only(run_dir: Path) -> bool:
    try:
        return bool(json.loads((run_dir / "args.json").read_text(encoding="utf-8")).get("construction_only"))
    except (OSError, ValueError, AttributeError):
        return False


def finished_rows(run_dir: Path) -> list[tuple[str, float]]:
    """(slug, seconds) of every finished ok row of one run (the monitor reads a running run's own pace from it)."""

    return _read_rows(Path(run_dir))


def _runs_newest_first(bench_root: Path) -> list[Path]:
    try:
        dirs = [p for p in bench_root.iterdir() if p.is_dir()]
    except OSError:
        return []
    return sorted(dirs, key=lambda p: p.name, reverse=True)


@lru_cache(maxsize=256)
def _from_history(
    bench_root: Path, slug: str, loop_seconds: float | None, construction_only: bool | None = None
) -> tuple[float, str] | None:
    """`construction_only` None = any run (the benchmark's own planning); True / False = only runs of that kind: a
    construction-only build is far shorter than a full one (#985)."""

    runs = _runs_newest_first(bench_root)
    for run in runs:
        if loop_seconds is not None and _loop_seconds(run) != loop_seconds:
            continue
        if construction_only is not None and _construction_only(run) != construction_only:
            continue
        mine = [s for sl, s in _read_rows(run) if sl == slug]
        if mine:
            return statistics.median(mine), f"{run.name}'s median of {len(mine)} {slug} builds"
    if construction_only is not None:
        return None
    for run in runs:
        if "gate" not in run.name:
            continue
        rows = [s for _, s in _read_rows(run)]
        if rows:
            return statistics.median(rows), f"the weekly run {run.name}'s median of all {len(rows)} builds"
    return None


def estimate_build(
    slug: str, run_dir: Path, loop_seconds: float | None, bench_root: Path
) -> tuple[float, str]:
    """(estimated seconds of one build of `slug`, the source in words)."""

    mine = [s for sl, s in _read_rows(Path(run_dir)) if sl == slug]
    if mine:
        return statistics.median(mine), f"this run's median of {len(mine)} {slug} builds"
    found = _from_history(Path(bench_root), slug, loop_seconds)
    if found:
        return found
    return FALLBACK_SECONDS, f"no rows: the fallback 68.6 min"


def history_seconds(
    slug: str, loop_seconds: float | None, bench_root: Path, construction_only: bool = False
) -> float | None:
    """Median seconds of one build of `slug` in the newest earlier run of the same loop budget and kind that holds
    one; None when no run does (no weekly-run guess, no fallback: the caller knows better what to put there)."""

    found = _from_history(Path(bench_root), slug, loop_seconds, bool(construction_only))
    return None if found is None else found[0]
