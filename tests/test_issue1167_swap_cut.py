"""#1167 unit 2: a zero-gain candidate with the best defence add probe gets a swap trial (row 1).

`refine` gives only the first `top_candidates` of the rank list a swap trial. The rank key is gain per point, so a
candidate whose gain is not in the objective (Melding: CombinedDPS +0.0, Life and the maximum hits up) ties with every
other zero-gain candidate, and the stable sort leaves the tie in `(cost, node_id)` order: every zero-gain cost-1 node
ahead of the cost-2 one. A1 (#1159): Melding ranked 157 of 300, `top_candidates` = 80. Here the notable TARGET (cost 2,
add probe: bossing defence +169) comes after six zero-gain cost-1 candidates and `top_candidates` is 3. The fake PoB is
the unit-1 harness (nodes' weights, Life and the four maximum hits).
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from tests.test_issue1167_swap_accept import FLOORS, _StatPob
from tests.test_tree_plan_b import START, _graph, _node

L1, L2 = 40, 41
FILLERS = (50, 51, 52, 53, 54)  # zero-gain notables at cost 1, ahead of TARGET in (cost, node_id) order
PATH, TARGET = 60, 61  # TARGET: a notable at cost 2 behind the normal node PATH
GAIN = 99  # a notable at cost 1 with real CombinedDPS gain, last of the cost-1 ids


def _case(*, gain: float = 0.0) -> tuple[_StatPob, TreeOptimizer]:
    nodes = {START: _node(START, "Witch", "class_start"), L1: _node(L1, "leaf 1", "normal"), L2: _node(L2, "leaf 2", "normal"),
             PATH: _node(PATH, "path", "normal"), TARGET: _node(TARGET, "target", "notable"), GAIN: _node(GAIN, "gain", "notable")}
    edges = [(START, L1), (START, L2), (START, PATH), (PATH, TARGET), (START, GAIN)]
    for node_id in FILLERS:
        nodes[node_id] = _node(node_id, f"filler {node_id}", "notable")
        edges.append((START, node_id))
    graph = _graph(nodes, edges)
    pob = _StatPob(graph, {START, L1, L2}, {GAIN: gain}, life={TARGET: -33.0}, hit={TARGET: 169.0})
    return pob, TreeOptimizer(pob, Objective(maximize="CombinedDPS", floors=FLOORS), graph=graph)


def _swap_trials_with(pob: _StatPob, node_id: int) -> list[dict]:
    return [t for batch in pob.batches for t in batch if t.get("remove") and node_id in (t.get("add") or ())]


def test_a_zero_gain_candidate_with_the_best_defence_add_probe_gets_a_swap_trial() -> None:
    pob, opt = _case()
    opt.refine(max_rounds=3, top_candidates=3)

    assert _swap_trials_with(pob, TARGET), "generated > 0: the swap trial that removes leaves for the cost-2 candidate exists"
    assert TARGET in pob.allocated and not {L1, L2} & pob.allocated, "and PoB's verdict (defence up, Life 4,502 >= 4,500) keeps it"


def test_a_candidate_with_real_gain_keeps_its_place_ahead_of_a_better_defence_tie() -> None:
    pob, opt = _case(gain=20.0)
    opt.refine(max_rounds=1, top_candidates=1)  # one swap slot: the gain candidate, not the defence-only one

    assert GAIN in pob.allocated, "the order of candidates whose gain is not tied is unchanged"
    assert not _swap_trials_with(pob, TARGET), "the one slot went to the candidate with the gain"
