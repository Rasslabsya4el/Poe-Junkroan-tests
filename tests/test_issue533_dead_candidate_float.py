"""#533: the jewel and cluster steps compare floats from `jewel_probe.scalar`; the float must keep `Score`'s key
(`(value > 0, neg_violation, value)`, #15 / D88 amd 1): a dead candidate (value 0) that meets its floors never beats
a live build with a small violation. PoB-free: a fake probe whose `score()` is the real `scalar` of a `Score` table."""

from __future__ import annotations

from dataclasses import dataclass

from junkroan.optimizer.cluster_step import ClusterSocket, run_cluster_step
from junkroan.optimizer.jewel_probe import DEAD_SCORE, NO_SCORE, scalar
from junkroan.optimizer.jewel_step import (
    PlacedJewel,
    SocketOption,
    _Counter,
    pick_line,
    place_jewel,
    repick_jewels,
)
from junkroan.optimizer.objective import Score

LIVE_INFEASIBLE = Score(neg_violation=-0.012, value=100.0)  # the current build
DEAD_FEASIBLE = Score(neg_violation=0.0, value=0.0)  # the candidate that killed the build but meets its floors
LIVE_FEASIBLE = Score(neg_violation=0.0, value=90.0)  # the control


@dataclass(frozen=True)
class Cand:
    id: str
    size: str = "large"
    enchant: object = None
    notables: tuple[str, ...] = ()


@dataclass(frozen=True)
class Node:
    id: int
    kind: str
    name: str
    linked: tuple[int, ...]


GRAPH = [Node(201, "entry", "", (202,)), Node(202, "small", "s", ())]


class TableProbe:
    """One socket (100, path (100,)); the build scores `base` without a jewel and `table[candidate.id]` with one.

    `score()` returns `scalar(Score)`: the exact floats the real `PobJewelProbe` hands the steps."""

    def __init__(self, base: Score, table: dict[str, Score]) -> None:
        self.base = base
        self.table = table
        self.allocated = {0, 1}
        self.jewels: dict[int, Cand] = {}

    def score(self) -> float:
        for sid, cand in self.jewels.items():
            if sid in self.allocated:
                return scalar(self.table[cand.id])
        return scalar(self.base)

    def snapshot(self):
        return (frozenset(self.allocated), dict(self.jewels))

    def restore(self, snap) -> None:
        self.allocated = set(snap[0])
        self.jewels = dict(snap[1])

    def sockets(self):
        return [ClusterSocket(100, (100,), 0 if 100 in self.allocated else 1, 2)] if 100 not in self.jewels else []

    def allocate(self, nodes) -> None:
        self.allocated |= set(nodes)

    def put_jewel(self, socket_id, candidate) -> None:
        self.jewels[socket_id] = candidate

    def remove_jewel(self, socket_id) -> None:
        self.jewels.pop(socket_id, None)

    def cluster_graph(self, socket_id):
        return GRAPH

    def removable_leaves(self):
        return sorted(n for n in self.allocated if n != 0)

    def remove(self, node_id) -> None:
        self.allocated.discard(node_id)

    def points_over(self) -> int:
        return 0  # the budget always holds: no leaf is freed, the score is the table's


def _placement(candidate_score: Score):
    probe = TableProbe(LIVE_INFEASIBLE, {"x": candidate_score})
    counter = _Counter(probe)
    before = counter.score()
    return probe, place_jewel(probe, Cand("x"), before, counter)


def test_placement_rejects_a_dead_feasible_candidate_over_a_live_infeasible_build():
    probe, placed = _placement(DEAD_FEASIBLE)
    assert placed is None
    assert probe.jewels == {}  # the build is as it was


def test_placement_keeps_a_live_feasible_candidate_over_a_live_infeasible_build():
    probe, placed = _placement(LIVE_FEASIBLE)
    assert placed is not None and placed[1] == 90.0
    assert probe.jewels[100].id == "x"


def _repick(candidate_score: Score):
    probe = TableProbe(LIVE_INFEASIBLE, {"cur": LIVE_INFEASIBLE, "x": candidate_score})
    probe.allocated.add(100)
    probe.put_jewel(100, Cand("cur"))
    jewel = PlacedJewel(100, Cand("cur"), 0.0, 0.0, 1, ((Cand("x"), 0.0),))
    (kept,) = repick_jewels(probe, [jewel])
    return probe, kept


def test_repick_rejects_a_dead_feasible_line_over_a_live_infeasible_current():
    probe, kept = _repick(DEAD_FEASIBLE)
    assert kept.candidate.id == "cur" and probe.jewels[100].id == "cur"


def test_repick_keeps_a_live_feasible_line_over_a_live_infeasible_current():
    probe, kept = _repick(LIVE_FEASIBLE)
    assert kept.candidate.id == "x" and probe.jewels[100].id == "x"


def _cluster(candidate_score: Score):
    probe = TableProbe(LIVE_INFEASIBLE, {"large//": candidate_score})
    result = run_cluster_step(
        probe,
        {"large": [object()]},
        lambda e, s: [],
        lambda s, e, n: Cand(f"{s}//{','.join(n)}", s, e, n),
        count_max=1,
    )
    return probe, result


def test_cluster_step_rejects_a_dead_feasible_cluster_over_a_live_infeasible_build():
    probe, result = _cluster(DEAD_FEASIBLE)
    assert result.placed == [] and probe.jewels == {}


def test_cluster_step_keeps_a_live_feasible_cluster_over_a_live_infeasible_build():
    probe, result = _cluster(LIVE_FEASIBLE)
    assert len(result.placed) == 1 and result.score_after == 90.0


def test_pick_line_rejects_a_dead_feasible_line_over_a_live_infeasible_empty_socket():
    probe = TableProbe(LIVE_INFEASIBLE, {"x": DEAD_FEASIBLE})
    best, ranking, empty = pick_line(probe, [Cand("x")])
    assert best is None and len(ranking) == 1


def test_scalar_orders_the_four_corners():
    live_feasible = scalar(Score(0.0, 90.0))
    live_infeasible = scalar(Score(-0.012, 100.0))
    dead_feasible = scalar(Score(0.0, 0.0))
    dead_infeasible = scalar(Score(-0.5, 0.0))
    assert live_feasible > live_infeasible > dead_feasible > dead_infeasible > NO_SCORE
    assert scalar(Score(-0.5, -3.0)) == scalar(Score(-0.5, 0.0))  # value <= 0 is dead whatever its value
    assert DEAD_SCORE == -1e9 and dead_feasible == DEAD_SCORE and DEAD_SCORE > NO_SCORE
    assert scalar(Score(-0.1, 5.0)) > scalar(Score(-0.2, 500.0))  # live infeasible: smaller violation first
