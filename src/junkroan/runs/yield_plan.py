"""Yield plan: how many workers each running job gives up when the owner's
reservation shrinks the host to an effective total (#621), and the per-job
yield file the daemon writes and the benchmark pool reads."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, wait
from datetime import datetime
from pathlib import Path
from typing import TypeVar

ENV_VAR = "JUNKROAN_YIELD_FILE"

T = TypeVar("T")


def plan_yield(workers: Mapping[str, int], effective_total: int) -> dict[str, int]:
    """Per job, how many workers it gives up so the host fits `effective_total`."""
    give = {j: 0 for j in workers}
    in_use = sum(max(0, w) for w in workers.values())
    if effective_total <= 0:
        return {j: max(0, w) for j, w in workers.items()}
    excess = max(0, in_use - effective_total)
    if excess == 0:
        return give
    order = sorted(workers, key=lambda j: (-workers[j], j))
    for j in order:
        w = workers[j]
        if w <= 1:
            continue
        share = (2 * excess * w + in_use) // (2 * in_use)  # round half-up
        give[j] = min(share, w)
    total = sum(give.values())
    while total < excess:
        pick = next((j for j in order if workers[j] > 1 and give[j] < workers[j]), None)
        if pick is None:
            pick = next((j for j in order if give[j] < workers[j]), None)
        if pick is None:
            break
        give[pick] += 1
        total += 1
    while total > excess:
        pick = next(j for j in order if give[j] > 0)
        give[pick] -= 1
        total -= 1
    return give


def yield_path(job_id: str, root: Path) -> Path:
    return Path(root) / "artifacts/runs/yield" / f"{job_id}.json"


def write_yield(path: Path, give_up: int, reserved: int, until: datetime | None, ram: int = 0) -> None:
    """Write the yield file; ``ram`` is the part of ``give_up`` that free RAM holds back (#960).

    A reader takes ``give_up`` alone; ``ram`` is for the daemon, which restores its own
    count from the file after a restart (:func:`read_ram_give`).
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "give_up": int(give_up),
        "reserved": int(reserved),
        "until": until.isoformat() if until is not None else None,
    }
    if ram > 0:
        data["ram_give"] = int(ram)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == 4:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (attempt + 1))


def read_yield(path: Path) -> int:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        value = data["give_up"]
    except Exception:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def read_ram_give(path: Path) -> int:
    """The RAM part of a yield file (#960), 0 when absent or unreadable."""

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8")).get("ram_give", 0)
    except Exception:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def clear_yield(path: Path) -> None:
    try:
        Path(path).unlink()
    except Exception:
        pass


def read_yield_from_env() -> int:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return 0
    return read_yield(Path(raw))


def limited_completions(submit: Callable[[T], Future], items: Iterable[T], workers: int, *,
                        read_yield: Callable[[], int] = read_yield_from_env, poll: float = 5.0,
                        sleep: Callable[[float], None] = time.sleep) -> Iterator[tuple[Future, T]]:
    """A pool's map that gives way to the owner's yield (#958), for the scripts whose pool runs one
    build or skeleton per worker and cannot be stopped mid-build.

    Submits an item only while fewer than ``allowed = max(0, workers - read_yield())`` are in flight,
    re-reading the yield before each submission. Yields ``(future, item)`` as each finishes, in
    completion order like ``as_completed``. An item already in flight runs to its end (no stop file).
    With allowed 0 and nothing in flight it idles, ``sleep(poll)`` between reads, until the file drops.
    """

    pending = list(items)
    running: dict[Future, T] = {}  # future -> item
    while pending or running:
        while pending and len(running) < max(0, workers - read_yield()):
            item = pending.pop(0)
            running[submit(item)] = item
        if not running:
            sleep(poll)
            continue
        for fut in wait(list(running), timeout=poll, return_when=FIRST_COMPLETED).done:
            yield fut, running.pop(fut)
