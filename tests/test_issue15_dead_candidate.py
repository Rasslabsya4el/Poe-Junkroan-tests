"""#15 unit 2: a dead candidate (value 0) never beats a live current build, at the two raw `>` sites.

`Score(0.0, 0.0) > Score(-0.012, 100.0)` was True (violation compared first), so a dead build was kept over a
live one. The ordering fix lives in `Score`; these two tests prove it where it is consumed. No PoB, fakes only.
"""

from __future__ import annotations

from dataclasses import dataclass

from junkroan.optimizer.jewel_step import SocketOption, run_jewel_step
from junkroan.optimizer.objective import Score

from test_tree_plan_b import F1, F2, F3, S1, S2, START, _target_case

LIVE = Score(-0.012, 100.0)
DEAD = Score(0.0, 0.0)


def test_reoptimize_rejects_a_dead_candidate_over_a_live_current_tree() -> None:
    graph, pob, opt = _target_case({S2: 30.0, F3: 90.0, S1: 1.0})
    original = {START, S1, S2, F1, F2, F3}
    pob.allocated = set(original)
    reads = {"live": 0, "dead": 0}

    def current_score():
        # the current tree scores LIVE; every build after the ruin's first mutation scores DEAD
        if pob.mutations:
            reads["dead"] += 1
            return DEAD, {}
        reads["live"] += 1
        return LIVE, {}

    opt.current_score = current_score
    opt.log = lambda _line: None

    result = opt.reoptimize(rounds=1, ruin_points=2, refine_rounds=0, seed=1)

    assert reads["dead"] >= 1 and pob.mutations, "the candidate was built and scored, so the comparison was reached"
    assert result.steps == [] and result.points_spent == 0
    assert result.final_score == LIVE
    assert pob.allocated == original


@dataclass(frozen=True)
class Line:
    id: str


class DeadJewelProbe:
    """One socket; the build scores LIVE alone and DEAD with any jewel in it (a candidate that kills the build)."""

    def __init__(self) -> None:
        self.allocated = {0}
        self.jewels: dict[int, Line] = {}
        self.score_calls = 0

    def score(self) -> Score:
        self.score_calls += 1
        return DEAD if self.jewels else LIVE

    def snapshot(self):
        return (frozenset(self.allocated), dict(self.jewels))

    def restore(self, snap) -> None:
        self.allocated, self.jewels = set(snap[0]), dict(snap[1])

    def sockets(self):
        return [] if 7 in self.jewels else [SocketOption(7, (7,), len({7} - self.allocated))]

    def allocate(self, nodes) -> None:
        self.allocated |= set(nodes)

    def put_jewel(self, socket_id, candidate) -> None:
        self.jewels[socket_id] = candidate

    def remove_jewel(self, socket_id) -> None:
        self.jewels.pop(socket_id, None)

    def removable_leaves(self):
        return []

    def remove(self, node_id) -> None:
        self.allocated.discard(node_id)

    def points_over(self) -> int:
        return 0


def test_jewel_step_rejects_a_dead_candidate_over_a_live_current_build() -> None:
    probe = DeadJewelProbe()

    result = run_jewel_step(probe, [Line("dead")], count_max=1)

    assert probe.score_calls >= 3, "build, empty socket and the candidate were measured: the comparison was reached"
    assert result.jewels == []
    assert result.stopped_reason == "jewel 1: no line beats the empty socket"
    assert probe.jewels == {}
