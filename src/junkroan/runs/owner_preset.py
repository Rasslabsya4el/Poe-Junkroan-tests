"""Owner preset sizing (#958, unit 3a): how many live PoB workers on the laptop
give way for an owner's film or sleep preset.

Pure functions: every reading (idle cores, free RAM, the live workers' mean
cost) is an argument. Nothing here reads the machine."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GiveWay:
    """`workers` PoB workers give way. `short_ram_mb` / `short_cpu_cores` are
    the shortfall left even if every running worker gives way (0 = covered)."""

    workers: int
    short_ram_mb: int = 0
    short_cpu_cores: float = 0.0

    def short_lines(self) -> list[str]:
        lines: list[str] = []
        if self.short_ram_mb > 0:
            lines.append(f"short by {self.short_ram_mb:,} MB")
        if self.short_cpu_cores > 0:
            lines.append(f"short by {self.short_cpu_cores:.1f} cores")
        return lines


def _ceil(value: float) -> int:
    # round first so float noise (1.3000000000000003) never adds a worker
    return math.ceil(round(value, 6))


def _workers_for(deficit: float, per_worker: float, running: int) -> int:
    if deficit <= 0:
        return 0
    if per_worker <= 0:
        # a worker frees nothing measurable: only all of them could help
        return running
    return _ceil(deficit / per_worker)


def size_give_way(
    *,
    need_cpu_cores: float,
    need_ram_mb: float,
    idle_cores: float,
    free_ram_mb: float,
    running_workers: int,
    worker_cores: float,
    worker_ram_mb: float,
) -> GiveWay:
    """n = min(running, max(ceil(cpu deficit / worker cores), ceil(ram deficit / worker RAM)));
    no live worker gives n = 0. The short shortfall is computed with every
    running worker giving way."""
    running = max(0, int(running_workers))
    cpu_deficit = need_cpu_cores - idle_cores
    ram_deficit = need_ram_mb - free_ram_mb

    if running == 0:
        n = 0
    else:
        n = min(
            running,
            max(
                _workers_for(cpu_deficit, worker_cores, running),
                _workers_for(ram_deficit, worker_ram_mb, running),
            ),
        )

    cpu_left = cpu_deficit - running * worker_cores
    ram_left = ram_deficit - running * worker_ram_mb
    short_ram = _ceil(ram_left) if ram_left > 0 else 0
    short_cpu = math.ceil(round(cpu_left * 10, 6)) / 10 if cpu_left > 0 else 0.0
    return GiveWay(workers=n, short_ram_mb=short_ram, short_cpu_cores=short_cpu)


def slots_give_way(slots: int, running_workers: int) -> GiveWay:
    """A preset that names a fixed slot count: that many workers give way,
    never more than are running; nothing is read from the machine."""
    running = max(0, int(running_workers))
    return GiveWay(workers=min(running, max(0, int(slots))))
