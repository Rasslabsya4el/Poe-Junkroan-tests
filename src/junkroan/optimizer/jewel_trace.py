"""Option classes of the day-1 rare jewel step for the trace counter (#434, #498).

A candidate `JewelLine` is ONE mod even when it has two text lines (a hybrid): the rulebook counts mods.
The forbidden classes (`jewel-mods:2+`, `jewel-corrupted`, `jewel-base:other`) are no candidate the step can
build, so they are written as 0/0 to show as 0, not as absent.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from junkroan.optimizer.trace import TRACE

FORBIDDEN_CLASSES: tuple[str, ...] = ("jewel-mods:2+", "jewel-corrupted", "jewel-base:other")


def jewel_classes(candidate: Any) -> list[str]:
    return [f"jewel-base:{candidate.base}", "jewel-mods:1"]


def count_generated(candidates: Iterable[Any]) -> None:
    """`generated` per candidate, and the forbidden classes as 0/0; under the caller's `TRACE.move`."""

    for c in candidates:
        TRACE.add_generated(jewel_classes(c))
    for forbidden in FORBIDDEN_CLASSES:
        TRACE.add_generated([forbidden], 0)
        TRACE.add_evaluated([forbidden], 0)


class TracingJewelProbe:
    """Forwards every `JewelProbe` method to `inner`; each `put_jewel` counts `evaluated` for the candidate's classes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def score(self) -> float:
        return self._inner.score()

    def snapshot(self) -> Any:
        return self._inner.snapshot()

    def restore(self, snap: Any) -> None:
        self._inner.restore(snap)

    def sockets(self) -> list:
        return self._inner.sockets()

    def allocate(self, nodes: Sequence[int]) -> None:
        self._inner.allocate(nodes)

    def put_jewel(self, socket_id: int, candidate: Any) -> None:
        TRACE.add_evaluated(jewel_classes(candidate))
        self._inner.put_jewel(socket_id, candidate)

    def remove_jewel(self, socket_id: int) -> None:
        self._inner.remove_jewel(socket_id)

    def removable_leaves(self) -> list[int]:
        return self._inner.removable_leaves()

    def remove(self, node_id: int) -> int | None:
        return self._inner.remove(node_id)  # the count of nodes PoB took: `_free_points` refuses a cascade by it (#1164)

    def points_over(self) -> int:
        return self._inner.points_over()
