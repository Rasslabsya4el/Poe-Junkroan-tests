"""#1167 unit 1: the refine swap's accept rule gets a tie-break (row 1b).

A swap at equal CombinedDPS whose floors all hold and whose bossing defence (the smallest maximum hit taken,
`bossing_defence`) is higher is kept; the old rule (`trial > score` and a `min_gain` clear) never could, because
`Score` at equal value and violation 0 is equal. Floors stay hard: Life 4,499 against the floor 4,500 is refused.
The fake PoB values a build as the sum of its nodes' weights (the plan-B harness), with Life and the four
maximum-hit stats on top of it; the A1 swap of #1159 is the case (Life 4,535 -> 4,502, PhysicalMaximumHitTaken
5,046 -> 5,215, CombinedDPS unchanged).
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from tests.test_tree_plan_b import START, _Pob, _graph, _node

LEAF, NEW, KEEP = 40, 50, 41
HIT_KEYS = ("PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken")
FLOORS = {"Life": 4500.0, "PhysicalMaximumHitTaken": 4700.0}


class _StatPob(_Pob):
    """The plan-B fake plus Life and the maximum hits, each the base plus the allocated nodes' deltas."""

    def __init__(self, *args, life: dict[int, float], hit: dict[int, float], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.life, self.hit = life, hit

    def _stats(self, nodes) -> dict:
        out = {"CombinedDPS": self._value(nodes), "Life": 4535.0 + sum(self.life.get(int(n), 0.0) for n in nodes)}
        for key in HIT_KEYS:
            out[key] = 5046.0 + sum(self.hit.get(int(n), 0.0) for n in nodes)
        return out

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        outs = super().trial_stats(trials, keys, mode)
        for trial, out in zip(trials, outs):
            nodes = (self.allocated | set(out["added_node_ids"])) - set(out["removed_node_ids"])
            out["stats"] = self._stats(nodes)
        return outs

    def stats(self, keys) -> dict:
        return self._stats(self.allocated)


def _case(*, dps: float = 0.0, life: float = -33.0, hit: float = 169.0) -> tuple[_StatPob, TreeOptimizer]:
    """The leaf LEAF is swapped for the notable NEW; the swap moves DPS by `dps`, Life by `life`, the hits by `hit`."""

    nodes = {START: _node(START, "Witch", "class_start"), LEAF: _node(LEAF, "leaf", "normal"),
             KEEP: _node(KEEP, "keep", "normal"), NEW: _node(NEW, "new", "notable")}
    graph = _graph(nodes, [(START, LEAF), (START, KEEP), (START, NEW)])
    pob = _StatPob(graph, {START, LEAF, KEEP}, {KEEP: 5.0, NEW: dps}, life={NEW: life}, hit={NEW: hit})
    return pob, TreeOptimizer(pob, Objective(maximize="CombinedDPS", floors=FLOORS), graph=graph)


def _refine(life: float = -33.0, hit: float = 169.0, dps: float = 0.0) -> _StatPob:
    pob, opt = _case(dps=dps, life=life, hit=hit)
    opt.refine(max_rounds=3)
    return pob


def test_an_equal_value_swap_with_higher_bossing_defence_and_floors_held_is_kept() -> None:
    pob = _refine()  # Life 4,502 >= 4,500, PhysicalMaximumHitTaken 5,215 > 5,046, CombinedDPS equal

    assert NEW in pob.allocated and LEAF not in pob.allocated, "the swap that raises the bossing defence at equal value is kept"
    assert pob.stats(())["Life"] == 4502.0


def test_the_same_swap_with_life_4499_against_the_floor_4500_is_refused() -> None:
    pob = _refine(life=-36.0)  # Life 4,499

    assert LEAF in pob.allocated and NEW not in pob.allocated, "a floor stays a hard limit; the tie-break never trades one"


def test_an_equal_value_swap_that_lowers_the_bossing_defence_is_not_kept() -> None:
    pob = _refine(hit=-100.0)  # PhysicalMaximumHitTaken 4,946 (floor 4,700 held) < 5,046

    assert LEAF in pob.allocated and NEW not in pob.allocated


def test_an_equal_value_swap_with_an_equal_bossing_defence_is_not_kept() -> None:
    pob = _refine(hit=0.0)

    assert LEAF in pob.allocated and NEW not in pob.allocated, "no secondary gain, no swap: nothing churns"


def test_a_swap_that_lowers_the_value_is_not_kept_whatever_the_bossing_defence() -> None:
    pob = _refine(dps=-1.0, hit=5000.0)

    assert LEAF in pob.allocated and NEW not in pob.allocated


def test_a_swap_that_raises_the_value_keeps_the_old_rule() -> None:
    pob = _refine(dps=20.0, hit=-100.0)  # +20 on 1,005 clears min_gain; the lower bossing defence is not asked about

    assert NEW in pob.allocated and LEAF not in pob.allocated
