"""#958: the pools of `scripts/replay_bench.py` and `scripts/search.py` give way to the owner's yield.

PoB-free: the pool is a fake whose futures finish on a timer, and the yield is a scripted reader. The
helper under test is `limited_completions` (`junkroan.runs.yield_plan`), which both scripts use with
`allowed = max(0, workers - read_yield())` builds in flight, re-read before each submission.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future

from junkroan.runs.yield_plan import limited_completions

ITEMS = [f"build-{n}" for n in range(6)]


class Owner:
    """The yield as the reader sees it: ``values`` in turn over the reads, the last value sticks."""

    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.reads = 0
        self.last = None

    def read(self) -> int:
        self.reads += 1
        self.last = self.values[min(self.reads, len(self.values)) - 1]
        return self.last


class TimedPool:
    """Stands in for a ProcessPoolExecutor: each submitted item finishes ``delay`` seconds later.

    ``log`` keeps, per submission, the yield value last read and how many builds were in flight after it.
    """

    def __init__(self, owner: Owner, delay: float = 0.03) -> None:
        self.owner = owner
        self.delay = delay
        self.lock = threading.Lock()
        self.live = 0
        self.peak = 0
        self.submitted: list[str] = []
        self.log: list[tuple[str, int | None, int]] = []

    def submit(self, item: str) -> Future:
        fut: Future = Future()
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.submitted.append(item)
            self.log.append((item, self.owner.last, self.live))

        def finish() -> None:
            with self.lock:
                self.live -= 1
            fut.set_result(item)

        threading.Timer(self.delay, finish).start()
        return fut


def run(owner: Owner, pool: TimedPool, workers: int, sleeps: list[float] | None = None) -> list[str]:
    sleeps = sleeps if sleeps is not None else []
    out = [item for _fut, item in limited_completions(pool.submit, ITEMS, workers, read_yield=owner.read, poll=0.01, sleep=sleeps.append)]
    return out


def test_yield_1_of_3_keeps_two_builds_in_flight() -> None:
    # workers 3, yield 1 -> allowed 2: never more than 2 submitted and unfinished at once
    owner = Owner([1])
    pool = TimedPool(owner)
    done = run(owner, pool, 3)
    assert sorted(done) == sorted(ITEMS)
    assert pool.submitted == ITEMS
    assert pool.peak == 2
    assert all(live <= 2 for _item, seen, live in pool.log if seen == 1)


def test_after_the_yield_file_drops_three_builds_run_at_once() -> None:
    # yield 1 for the first three reads (allowed 2), then the file is gone (read_yield 0 -> allowed 3)
    owner = Owner([1, 1, 1, 0])
    pool = TimedPool(owner)
    done = run(owner, pool, 3)
    assert sorted(done) == sorted(ITEMS)
    assert pool.submitted == ITEMS
    assert all(live <= 2 for _item, seen, live in pool.log if seen == 1)
    assert any(live == 3 for _item, seen, live in pool.log if seen == 0)
    assert pool.peak == 3


def test_yield_at_least_workers_submits_nothing_until_it_drops() -> None:
    # workers 3, yield 3 -> allowed 0: idle (sleep between reads) until the file drops, then all of it runs
    owner = Owner([3, 3, 3, 3, 0])
    pool = TimedPool(owner)
    sleeps: list[float] = []
    done = run(owner, pool, 3, sleeps)
    assert pool.log and all(seen == 0 for _item, seen, _live in pool.log)  # nothing went out while yield 3
    assert len(sleeps) >= 4  # the idle reads before the drop
    assert sorted(done) == sorted(ITEMS)  # the helper returned once everything ran
    assert pool.peak == 3


def test_yield_0_is_the_old_pool_with_all_workers_in_flight() -> None:
    owner = Owner([0])
    pool = TimedPool(owner)
    done = run(owner, pool, 3)
    assert sorted(done) == sorted(ITEMS)
    assert pool.submitted == ITEMS
    assert pool.peak == 3
