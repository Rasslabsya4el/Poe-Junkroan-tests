"""The source of a filler's work (#751 unit 1): how many to start and which build each one makes.

Pure: no git, no ssh, no clock, no files; every fact comes in as a parameter. A job's pin is a field of the
job (the snapshot it runs from, `docs/agents/runs.md` "A run sees one commit"), not part of the command line,
so a builder returns `FillerCommand(command, pin, ...)`.

Rule 3 (a cut in force and the week's folder not full): the next stem of `--missing` that no running or queued
filler of either host already makes, `--resume <week folder> --row <stem>`, pinned at the cut.
Rule 4 (otherwise): one of the 42 base rows of the weekly set on current main, tag `warn-<Monday>`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

WARN_SEEDS = (4, 5, 6)


@dataclass(frozen=True, slots=True)
class FillerCommand:
    command: str
    pin: str
    kind: str          # "cut" | "warn"
    key: str           # the stem (cut) or "<slug>:<seed>" (warn)


def filler_count(free_slots: int, free_mem_gb: float, mem_floor_gb: float, mem_per_worker_gb: float | None,
                 logical_cores: int, cpu_share: float) -> int:
    """min(free slots, memory room, CPU room), never negative; no measured memory per worker = 0."""

    if not mem_per_worker_gb or mem_per_worker_gb <= 0:
        return 0
    by_mem = math.floor((free_mem_gb - mem_floor_gb) / mem_per_worker_gb)
    by_cpu = math.floor(logical_cores * (1 - cpu_share))
    return max(0, min(int(free_slots), by_mem, by_cpu))


def next_stems(missing: Sequence[str], running_or_queued: Iterable[str], n: int) -> list[str]:
    """The first `n` stems of `missing` (order kept) that no running/queued filler (any host) makes; no repeats."""

    taken = set(running_or_queued)
    out: list[str] = []
    for stem in missing:
        if len(out) >= max(0, n):
            break
        if stem in taken:
            continue
        taken.add(stem)
        out.append(stem)
    return out


def cut_command(week_folder: str, stem: str, cut: str) -> FillerCommand:
    return FillerCommand(f"python scripts/benchmark.py --resume {week_folder} --row {stem}", cut, "cut", stem)


def weekly_slugs() -> list[str]:
    """The weekly set's slugs, in the set's own order (`SETS["core14"]`)."""

    import sys
    from pathlib import Path
    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import benchmark
    return list(benchmark.SETS["core14"])


def warn_rows(monday: date, n_done: int, slugs: Sequence[str] | None = None) -> list[tuple[str, int]]:
    """All base rows (slug, seed), slug-major in the set's order then seeds 4,5,6, starting at position
    `n_done % total` and wrapping once around. `monday` is not part of the order (it only names the tag)."""

    slugs = list(slugs if slugs is not None else weekly_slugs())
    rows = [(s, seed) for s in slugs for seed in WARN_SEEDS]
    k = n_done % len(rows)
    return rows[k:] + rows[:k]


def warn_command(slug: str, seed: int, monday: date, main_sha: str) -> FillerCommand:
    cmd = (f"python scripts/benchmark.py {slug} --seed {seed} --seeds 1 --no-variants --gear wishlist "
           f"--tag warn-{monday:%Y%m%d}")
    return FillerCommand(cmd, main_sha, "warn", f"{slug}:{seed}")


def choose(cut_in_force: str | None, week_folder: str | None, missing: Sequence[str],
           running_or_queued: Iterable[str], n: int, monday: date, n_done: int, main_sha: str,
           slugs: Sequence[str] | None = None) -> list[FillerCommand]:
    """Rule 3 when a cut (its sha) is in force and the week's folder still lacks stems; else rule 4.
    `running_or_queued` holds stems (cut fillers) and "<slug>:<seed>" keys (warn fillers) of both hosts."""

    taken = list(running_or_queued)
    if cut_in_force and week_folder and missing:
        return [cut_command(week_folder, s, cut_in_force) for s in next_stems(missing, taken, n)]
    out: list[FillerCommand] = []
    busy = set(taken)
    for slug, seed in warn_rows(monday, n_done, slugs):
        if len(out) >= max(0, n):
            break
        if f"{slug}:{seed}" in busy:
            continue
        out.append(warn_command(slug, seed, monday, main_sha))
    return out
