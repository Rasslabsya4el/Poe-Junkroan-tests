"""Option classes of the day-1 rare cluster jewel step for the trace counter (#433).

The forbidden classes are no candidate the step can build, so they are written as 0/0 to show as 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from junkroan.optimizer.jewel_trace import TracingJewelProbe
from junkroan.optimizer.trace import TRACE

FORBIDDEN_CLASSES: tuple[str, ...] = (
    "cluster-size:small",
    "cluster-notables:3+",
    "cluster-also-grant",
    "cluster-socket:plain",
    "cluster-socket:inner",
)


def cluster_classes(candidate: Any) -> list[str]:
    return [f"cluster-size:{candidate.size}", f"cluster-notables:{len(candidate.notables)}"]


def count_generated(candidates: Iterable[Any]) -> None:
    """`generated` per candidate, and the forbidden classes as 0/0; under the caller's `TRACE.move`."""

    for c in candidates:
        TRACE.add_generated(cluster_classes(c))
    for forbidden in FORBIDDEN_CLASSES:
        TRACE.add_generated([forbidden], 0)
        TRACE.add_evaluated([forbidden], 0)


def count_inner_skipped(n: int) -> None:
    """Inner sockets the step skipped: `generated` only, never evaluated; under the caller's `TRACE.move`."""

    TRACE.add_generated(["cluster-socket:inner"], n)


class TracingClusterProbe(TracingJewelProbe):
    """Forwards to `inner`; each `put_jewel` counts `evaluated` for the cluster candidate's classes."""

    def put_jewel(self, socket_id: int, candidate: Any) -> None:
        TRACE.add_evaluated(cluster_classes(candidate))
        self._inner.put_jewel(socket_id, candidate)

    def cluster_graph(self, socket_id: int) -> list:
        return self._inner.cluster_graph(socket_id)
