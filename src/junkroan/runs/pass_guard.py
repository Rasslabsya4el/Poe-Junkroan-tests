"""#998: one daemon pass never waits on the same dead outside service twice.

Every outside call of a pass (`gh`, ssh to a host, scp) asks the guard first: a key (`"gh"`,
`"ssh:<host>"`) that already timed out or failed to answer in THIS pass is `down`, and the call is skipped
(treated as a failed read: no job touched, the same rule the `gh could not read` line follows). The daemon's
`tick` calls `begin()` first, so the next pass tries the service again. The cost of a dead service in one
pass is one call's timeout, not one per issue or job.
"""

from __future__ import annotations

import time
from typing import Callable

#: a pass longer than this writes one slow-pass line (`Daemon.tick`, #998 row 3).
SLOW_PASS_SECONDS = 30.0
#: #998: the slow-pass line names every step of the pass that took MORE than this (strictly over), in step order.
STEP_LINE_SECONDS = 5.0
#: a process that never calls `begin()` (the monitor's refresh, a CLI) must not keep a service down for good:
#: a mark older than this no longer counts.
DOWN_TTL_SECONDS = 60.0
#: #998: once a pass has used this long, no further outside call of the pass is started: every `down` is true
#: and the call is skipped as a failed read. Only a pass that began (`begin()`) has a budget.
PASS_BUDGET_SECONDS = 45.0


class PassGuard:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._down: dict[str, tuple[str, float]] = {}
        self._steps: list[tuple[str, float]] = []
        self._started = clock()
        self._begun = False

    def begin(self) -> None:
        """A new pass: every service is tried again, the step timings start from zero, the budget restarts."""
        self._down.clear()
        self._steps.clear()
        self._started = self._clock()
        self._begun = True

    def budget_spent(self) -> bool:
        """True once this pass has used `PASS_BUDGET_SECONDS`; False for a guard whose pass never began."""
        return self._begun and self.pass_seconds() >= PASS_BUDGET_SECONDS

    def down(self, key: str) -> bool:
        if self.budget_spent():
            return True
        mark = self._down.get(key)
        if mark is None:
            return False
        if self._clock() - mark[1] > DOWN_TTL_SECONDS:
            del self._down[key]
            return False
        return True

    def mark_down(self, key: str, why: str = "") -> bool:
        """Record that `key` did not answer in this pass; True the first time (the caller logs once)."""
        first = not self.down(key)
        if first:
            self._down[key] = (why, self._clock())
        return first

    def step(self, name: str, started: float) -> None:
        """Record one tick step that began at `started` (a value of this guard's clock)."""
        self._steps.append((name, self._clock() - started))

    def now(self) -> float:
        return self._clock()

    def slowest(self) -> tuple[str, float] | None:
        return max(self._steps, key=lambda s: s[1]) if self._steps else None

    def steps_over(self, seconds: float) -> list[tuple[str, float]]:
        """Every recorded step that took more than `seconds`, in the order the steps ran."""
        return [step for step in self._steps if step[1] > seconds]

    def pass_seconds(self) -> float:
        return self._clock() - self._started


#: the daemon's single guard; tests build their own `PassGuard` or `GUARD.begin()`.
GUARD = PassGuard()
