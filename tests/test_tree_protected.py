"""#510 unit 2: a forced passive node (and the path to it) is never removed by a tree move.

PoB-free: the fake PoB of `test_tree_plan_b` records every trial batch and every real mutation; the
graph is the real `TreeGraph.load()` (Witch start, Elemental Overload, a far notable and the paths
PoB would allocate for them). Every mover is run twice on the same build: with `protected` set no
recorded `remove` holds a protected id or a node of its path, with `protected` empty the same mover
DOES remove one (so it is the guard that holds, not the shape of the build).

The Skeleton.apply readback is the one `pob` test at the end of the file.
"""

from __future__ import annotations

import random

import pytest

from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.optimizer.tree_hygiene import analyze_tree_leaves
from tests.test_tree_plan_b import (
    C1, C2, C3, C4, HUB, L1, L2, B1, B2, B3, B4, B5, TAIL, START as PB_START, _Pob, _corridor_case, _opt,
)

ELEMENTAL_OVERLOAD = 22088
FAR_NOTABLE = 8135  # Practical Application, 7 points from the Witch start
OTHER_NOTABLES = (11420, 27929, 27203, 27611)  # Arcanist's Dominion, Deep Wisdom, Heart and Soul, Lord of the Dead


class _Weights(dict):
    """Unlisted nodes are worth 5: every candidate to add is attractive, so swaps are tried."""

    def get(self, key, default=0.0):  # noqa: D401
        return super().get(key, 5.0)


def _real_case():
    graph = TreeGraph.load()
    start = graph.class_starts["Witch"]
    costs = graph.bfs_costs({start}, max_depth=40)
    protected = {ELEMENTAL_OVERLOAD, FAR_NOTABLE}
    guarded = set()  # the protected nodes and every node of their paths: no move may remove one
    for node in protected:
        guarded |= set(costs[node][1])
    allocated = set(guarded)
    for node in OTHER_NOTABLES:
        allocated |= set(costs[node][1])
    # the guarded nodes are worth LESS than nothing: removing them is the best move on offer
    weights = _Weights({n: 1.0 for n in allocated} | {n: -50.0 for n in guarded})
    pob = _Pob(graph, allocated, weights)
    return graph, pob, protected, guarded


def _removed_ids(pob: _Pob) -> set[int]:
    ids: set[int] = set()
    for batch in pob.batches:
        for trial in batch:
            ids |= {int(n) for n in trial.get("remove") or ()}
    for _add, remove in pob.mutations:
        ids |= {int(n) for n in remove}
    return ids


def _refine(opt):
    opt.refine(max_rounds=4)


def _reoptimize(opt):
    opt.reoptimize(rounds=2, ruin_points=10, refine_rounds=2, seed=3)


def _swap_subtrees(opt):
    opt.swap_subtrees(max_candidates=8, max_seconds=None)


def _challenge_regions(opt):
    opt.challenge_regions(max_challenges=3, replacements=4)


def _random_branches(opt):
    allocated = opt.current_allocated()
    for seed in range(40):
        for node in opt._random_branches(allocated, 12, random.Random(seed)):
            opt.pob.mutations.append(((), (node,)))  # the pipeline removes exactly these


def _weakest_leaves(opt):
    opt._weakest_leaves(opt.current_allocated(), None)


MOVERS = {
    "refine": _refine,
    "reoptimize": _reoptimize,
    "swap_subtrees": _swap_subtrees,
    "challenge_regions": _challenge_regions,
    "random_branches": _random_branches,
    "weakest_leaves": _weakest_leaves,
}


@pytest.mark.parametrize("mover", sorted(MOVERS))
def test_no_move_removes_a_protected_node_or_its_path(mover: str) -> None:
    graph, pob, protected, guarded = _real_case()
    opt = _opt(pob, graph)
    opt.protected = frozenset(protected)

    MOVERS[mover](opt)

    assert _removed_ids(pob) & guarded == set(), f"{mover} removed a protected node or a node on its path"
    assert protected <= pob.allocated and guarded <= pob.allocated, "the forced nodes and their paths are still allocated"
    assert pob.batches or mover == "random_branches", f"{mover} sent PoB nothing: the check is empty"


@pytest.mark.parametrize("mover", sorted(MOVERS))
def test_the_same_move_without_protection_does_remove_them(mover: str) -> None:
    graph, pob, protected, guarded = _real_case()
    opt = _opt(pob, graph)
    assert opt.protected == frozenset()

    MOVERS[mover](opt)

    assert _removed_ids(pob) & guarded, f"{mover} never tried to remove a guarded node even unprotected: the test above proves nothing"


# -- the corridor exchange and its leaf payment (hand-made graph) --------------------------------

CORRIDOR_WEIGHTS = {B1: 50.0, B2: 50.0, B3: 50.0, B4: 50.0, B5: 50.0, HUB: 10.0, TAIL: 10.0, L1: 1.0, L2: 5.0}


def test_a_protected_node_inside_a_corridor_keeps_the_corridor() -> None:
    graph, pob, opt = _corridor_case(CORRIDOR_WEIGHTS)
    opt.protected = frozenset({C2})

    result = opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert result.steps == []
    assert _removed_ids(pob) & {C1, C2, C3, C4} == set()
    assert {C1, C2, C3, C4} <= pob.allocated


def test_the_leaf_that_pays_for_a_longer_bypass_is_never_a_protected_one() -> None:
    graph, pob, opt = _corridor_case(CORRIDOR_WEIGHTS)
    opt.protected = frozenset({L1})  # the weakest leaf: unprotected it pays (see test_tree_plan_b)

    opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert L1 in pob.allocated and L1 not in _removed_ids(pob)
    assert L2 not in pob.allocated or not ({B1, B2, B3, B4, B5} & pob.allocated), "L2 paid instead, or no exchange"
    assert PB_START in pob.allocated


def test_the_corridor_exchange_still_runs_when_nothing_in_it_is_protected() -> None:
    graph, pob, opt = _corridor_case(CORRIDOR_WEIGHTS)
    opt.protected = frozenset({HUB})  # an endpoint stays allocated by construction

    result = opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert len(result.steps) == 1 and HUB in pob.allocated


# -- the helpers ---------------------------------------------------------------------------------

def test_removable_leaves_skips_a_node_whose_removal_cuts_the_path_to_a_protected_one() -> None:
    graph, pob, protected, guarded = _real_case()
    allocated = pob.allocated
    plain = set(graph.removable_leaves(allocated))
    held = set(graph.removable_leaves(allocated, protected=protected))

    assert plain & protected and not (held & protected)
    assert held <= plain
    assert graph.keeps_connected(allocated, [], protected)
    for path_node in guarded - protected:
        assert not graph.keeps_connected(allocated, [path_node], protected), path_node
    assert not graph.keeps_connected(allocated, [ELEMENTAL_OVERLOAD], protected)


def test_resolve_forced_reads_a_mastery_effect_through_its_cheapest_mastery() -> None:
    graph = TreeGraph.load()
    effect = next(e for n in graph.nodes.values() for e, _stats in n.mastery_effects if e not in graph.nodes)
    plain, masteries = graph.resolve_forced([ELEMENTAL_OVERLOAD, effect, ELEMENTAL_OVERLOAD], class_name="Witch")
    assert plain == [ELEMENTAL_OVERLOAD]
    ((node, got),) = masteries.items()
    assert got == effect and node in graph.mastery_effect_holders(effect)
    assert graph.protected_nodes([ELEMENTAL_OVERLOAD, effect], {node: effect}) == frozenset({ELEMENTAL_OVERLOAD, node})
    with pytest.raises(ValueError):
        graph.resolve_forced([next(n.node_id for n in graph.nodes.values() if n.kind == "mastery")])
    with pytest.raises(ValueError):
        graph.resolve_forced([-5])


# -- the hygiene report's what-ifs -----------------------------------------------------------------

@pytest.mark.parametrize("how", ["argument", "trace"])
def test_the_hygiene_report_never_asks_what_a_build_without_a_forced_node_is_worth(how: str) -> None:
    graph, pob, protected, guarded = _real_case()
    try:
        if how == "trace":
            TRACE.set_forced({"nodes": sorted(protected)})
            analyze_tree_leaves(pob, rederive_proofs=False)
        else:
            analyze_tree_leaves(pob, rederive_proofs=False, protected=protected)
        assert pob.batches and _removed_ids(pob) & guarded == set()
    finally:
        TRACE.set_forced(None)

    pob2 = _real_case()[1]
    analyze_tree_leaves(pob2, rederive_proofs=False)
    assert _removed_ids(pob2) & protected, "unprotected, the report measures the forced leaf too"


# -- Skeleton.apply readback (PoB) ----------------------------------------------------------------

@pytest.mark.pob
def test_apply_allocates_the_forced_nodes_in_pob() -> None:
    from junkroan.pob.session import PobSession
    from junkroan.search.skeleton import Skeleton

    graph = TreeGraph.load()
    skeleton = Skeleton(class_name="Witch", ascendancy="Elementalist", forced_nodes=[ELEMENTAL_OVERLOAD, FAR_NOTABLE])
    with PobSession(run_id="tree-protected") as pob:
        skeleton.apply(pob)
        allocated = {int(n) for n in pob.tree_light().get("user_allocated_node_ids") or ()}
    assert {ELEMENTAL_OVERLOAD, FAR_NOTABLE} <= allocated
    costs = graph.bfs_costs({graph.class_starts["Witch"]}, max_depth=40)
    assert set(costs[ELEMENTAL_OVERLOAD][1]) <= allocated, "the path to the keystone came with it"


@pytest.mark.pob
def test_apply_allocates_a_forced_mastery_effect_in_pob() -> None:
    from junkroan.pob.session import PobSession
    from junkroan.search.skeleton import Skeleton

    graph = TreeGraph.load()
    effect = next(e for n in graph.nodes.values() for e, _stats in n.mastery_effects if e not in graph.nodes)
    ((mastery_node, _),) = graph.resolve_forced([effect], class_name="Witch")[1].items()
    skeleton = Skeleton(class_name="Witch", ascendancy="Elementalist", forced_nodes=[effect])
    with PobSession(run_id="tree-protected-mastery") as pob:
        skeleton.apply(pob)
        state = pob.tree_light()
    assert f"{mastery_node}:{effect}" in (state.get("mastery_effect_ids") or [])
    assert mastery_node in {int(n) for n in state.get("user_allocated_node_ids") or ()}
