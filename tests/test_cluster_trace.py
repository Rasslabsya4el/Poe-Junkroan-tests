"""#433 unit 4: the trace classes of the cluster step. No PoB."""

from __future__ import annotations

from dataclasses import dataclass

from junkroan.optimizer.cluster_step import ClusterSocket, run_cluster_step
from junkroan.optimizer.cluster_trace import (
    FORBIDDEN_CLASSES,
    TracingClusterProbe,
    cluster_classes,
    count_generated,
    count_inner_skipped,
)
from junkroan.optimizer.trace import TRACE


@dataclass(frozen=True)
class Ench:
    id: str


@dataclass(frozen=True)
class Cand:
    size: str
    enchant: Ench
    notables: tuple[str, ...]


@dataclass(frozen=True)
class Node:
    id: int
    kind: str
    name: str
    linked: tuple[int, ...]


class Probe:
    def __init__(self):
        self.j = None

    def score(self):
        return 5.0 if self.j else 0.0

    def snapshot(self):
        return self.j

    def restore(self, s):
        self.j = s

    def sockets(self):
        return [ClusterSocket(7, (7,), 0, 2)]

    def allocate(self, nodes):
        pass

    def put_jewel(self, sid, c):
        self.j = c

    def remove_jewel(self, sid):
        self.j = None

    def cluster_graph(self, sid):
        return [Node(1, "entry", "", (2,)), Node(2, "notable", "N1", ())]

    def removable_leaves(self):
        return []

    def remove(self, n):
        pass

    def points_over(self):
        return 0


def test_classes():
    assert cluster_classes(Cand("large", Ench("e"), ("a", "b"))) == ["cluster-size:large", "cluster-notables:2"]


def test_generated_evaluated_allowed_and_forbidden_zero():
    TRACE.reset()
    cands = [Cand("large", Ench("e"), ()), Cand("large", Ench("e"), ("N1",))]
    with TRACE.move("cluster"):
        count_generated(cands)
        run_cluster_step(
            TracingClusterProbe(Probe()), {"large": [Ench("e")]}, lambda e, s: ["N1"],
            lambda s, e, n: Cand(s, e, n), count_max=1,
        )
    got = TRACE.considered()["cluster"]
    for cls in ("cluster-size:large", "cluster-notables:0", "cluster-notables:1"):
        assert got[cls]["generated"] > 0 and got[cls]["evaluated"] > 0, cls
    for cls in FORBIDDEN_CLASSES:
        assert got[cls] == {"generated": 0, "evaluated": 0}, cls


def test_inner_socket_never_put_and_counted_generated_only():
    class TwoSockets(Probe):
        def sockets(self):
            return [ClusterSocket(7, (7,), 0, 2), ClusterSocket(8, (), 0, 1)]

        def put_jewel(self, sid, c):
            puts.append(sid)
            super().put_jewel(sid, c)

    puts: list[int] = []
    TRACE.reset()
    with TRACE.move("cluster"):
        count_generated(())
        res = run_cluster_step(
            TracingClusterProbe(TwoSockets()), {"large": [Ench("e")], "medium": [Ench("m")]}, lambda e, s: ["N1"],
            lambda s, e, n: Cand(s, e, n), count_max=1, is_inner=lambda n: n == 8,
        )
        count_inner_skipped(len(res.inner_skipped))
    assert 8 not in puts and 7 in puts
    assert res.inner_skipped == [8]
    got = TRACE.considered()["cluster"]
    assert got["cluster-socket:inner"]["generated"] > 0 and got["cluster-socket:inner"]["evaluated"] == 0
    for cls in FORBIDDEN_CLASSES:
        assert got[cls]["evaluated"] == 0, cls
