"""Plan B (2026-09-20): the trunk's own moves, on hand-made graphs with a fake PoB.

Three moves, one file:

* `exchange_corridors` -- a corridor (a run of ordinary allocated nodes between two key nodes)
  is swapped for another way between the same two key nodes; the extra points of a longer way
  are paid by dropping the weakest leaves; the final set is connected and the point count holds;
* `repair_target_first` -- the second repair policy picks the destination with the best value per
  connection point instead of the next cheap node;
* `challenge_regions` -- detachable regions are ranked by the best COMPLETED replacement found
  cheaply, not by what they cost to remove, and the regrow may not re-take the region it is
  challenging for the first half of its points.

The fake PoB allocates exactly the nodes it is asked for (a hand-made graph has no PoB pathing
to imitate) and values a build as the sum of its allocated nodes' weights.
"""

from __future__ import annotations

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

START = 1


def _node(node_id: int, name: str, kind: str, stats: tuple[str, ...] = ()) -> TreeNode:
    return TreeNode(node_id=node_id, name=name, kind=kind, stats=stats, ascendancy_name=None,
                    class_start_index=3 if kind == "class_start" else None)


def _graph(nodes: dict[int, TreeNode], edges: list[tuple[int, int]]) -> TreeGraph:
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    allocatable = frozenset(n for n, node in nodes.items() if node.kind != "class_start")
    return TreeGraph(tree_version="plan-b", nodes=nodes,
                     adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=allocatable, class_starts={"Witch": START})


class _Pob:
    """PoB's tree surfaces, faithfully enough for these moves; value = 1000 + node weights.

    Two behaviours the plan-B moves stand on are copied from the real worker:
    an ADD brings the node's whole shortest path with it (`_TRIAL_STATS_FAST_LUA` walks
    `node.path`, and the fast batch computes every path against the build as it stood when the
    batch started), while a real REMOVAL cascades (`spec:DeallocNode`) -- which is why the
    corridor exchange allocates its bypass before it removes the corridor.
    """

    def __init__(self, graph: TreeGraph, allocated: set[int], weights: dict[int, float] | None = None) -> None:
        self.graph = graph
        self.allocated = set(allocated)
        self.weights = dict(weights or {})
        self.masteries: dict[int, int] = {}
        self.loaded: list[str] = []
        self.batches: list[list[dict]] = []
        self.mutations: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        self._snapshots: dict[str, tuple[set[int], dict[int, int]]] = {}

    # -- surfaces the optimizer uses -------------------------------------
    def config_inputs(self) -> dict:
        return {}

    def tree_light(self) -> dict:
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.allocated - {START}),
                "mastery_effect_ids": [f"{n}:{e}" for n, e in sorted(self.masteries.items())]}

    def _value(self, nodes) -> float:
        return 1000.0 + sum(self.weights.get(int(n), 0.0) for n in nodes)

    def _cascade(self, nodes: set[int], removed: set[int]) -> set[int]:
        remaining = nodes - removed
        return remaining - self.graph._connected_from(self.graph.roots(remaining), remaining)

    def _paths_for(self, targets, allocated: set[int]) -> list[int]:
        """Every target's shortest path, all measured against the same allocation."""

        costs = self.graph.bfs_costs(allocated, max_depth=12)
        added: list[int] = []
        for target in targets:
            entry = costs.get(int(target))
            if int(target) in allocated or entry is None:
                continue
            for node_id in entry[1]:
                if node_id not in allocated and node_id not in added:
                    added.append(int(node_id))
        return added

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        self.batches.append(list(trials))
        out = []
        for trial in trials:
            removed = sorted(int(n) for n in (trial.get("remove") or ()) if int(n) in self.allocated)
            added = sorted(self._paths_for(trial.get("add") or (), self.allocated))
            # the fast calculator does not cascade: a momentarily disconnected set is evaluable
            nodes = (self.allocated | set(added)) - set(removed)
            out.append({"ok": True, "stats": {"CombinedDPS": self._value(nodes)},
                        "added_node_ids": added, "removed_node_ids": removed})
        return out

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        self.mutations.append((tuple(add or ()), tuple(remove or ())))
        asked = {int(n) for n in (remove or ()) if int(n) in self.allocated}
        gone = asked | self._cascade(self.allocated, asked)
        self.allocated -= gone
        for node_id in gone:
            self.masteries.pop(node_id, None)
        added: list[int] = []
        for target in (add or ()):  # PoB rebuilds every path inside AllocNode: one target at a time
            fresh = self._paths_for([target], self.allocated)
            self.allocated |= set(fresh)
            added.extend(fresh)
        added.sort()
        for node_id, effect in (mastery_effects or {}).items():
            self.masteries[int(node_id)] = int(effect)
        return {"added_node_ids": added, "removed_node_ids": sorted(gone),
                "allocated_node_ids": sorted(self.allocated - {START}), "removed_mastery_effects": [],
                "points_used": len(self.allocated)}

    def stats(self, keys) -> dict:
        return {"CombinedDPS": self._value(self.allocated)}

    def export_xml(self) -> str:
        token = f"xml{len(self._snapshots) + 1}"
        self._snapshots[token] = (set(self.allocated), dict(self.masteries))
        return token

    def load_xml(self, token: str) -> None:
        self.loaded.append(token)
        self.allocated, self.masteries = set(self._snapshots[token][0]), dict(self._snapshots[token][1])


def _opt(pob: _Pob, graph: TreeGraph, **kwargs) -> TreeOptimizer:
    return TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph, **kwargs)


# -- the corridor graph ---------------------------------------------------
#
#  START -- C1 -- C2 -- C3 -- C4 -- HUB(notable) -- TAIL(notable leaf)
#    |                                  |
#    +---- B1 -- B2 -- B3 -- B4 -- B5 --+          (the five-node bypass)
#    |
#    +---- L1(leaf)  +---- L2(leaf)

C1, C2, C3, C4 = 10, 11, 12, 13
HUB, TAIL = 20, 21
B1, B2, B3, B4, B5 = 30, 31, 32, 33, 34
L1, L2 = 40, 41


def _corridor_case(weights: dict[int, float] | None = None) -> tuple[TreeGraph, _Pob, TreeOptimizer]:
    nodes = {
        START: _node(START, "Witch", "class_start"),
        C1: _node(C1, "c1", "normal"), C2: _node(C2, "c2", "normal"),
        C3: _node(C3, "c3", "normal"), C4: _node(C4, "c4", "normal"),
        HUB: _node(HUB, "Hub", "notable"), TAIL: _node(TAIL, "Tail", "notable"),
        B1: _node(B1, "b1", "normal"), B2: _node(B2, "b2", "normal"), B3: _node(B3, "b3", "normal"),
        B4: _node(B4, "b4", "normal"), B5: _node(B5, "b5", "normal"),
        L1: _node(L1, "l1", "normal"), L2: _node(L2, "l2", "normal"),
    }
    edges = [(START, C1), (C1, C2), (C2, C3), (C3, C4), (C4, HUB), (HUB, TAIL),
             (START, B1), (B1, B2), (B2, B3), (B3, B4), (B4, B5), (B5, HUB),
             (START, L1), (START, L2)]
    graph = _graph(nodes, edges)
    allocated = {START, C1, C2, C3, C4, HUB, TAIL, L1, L2}
    pob = _Pob(graph, allocated, weights or {})
    return graph, pob, _opt(pob, graph)


def test_a_corridor_runs_between_two_key_nodes_and_leaves_are_not_one() -> None:
    graph, pob, opt = _corridor_case()

    keys = opt.key_nodes(pob.allocated)
    corridors = opt.corridors(pob.allocated)

    assert START in keys and HUB in keys and TAIL in keys, "start, branch point and notables are key"
    assert not ({C1, C2, C3, C4} & keys), "an ordinary run of two-neighbour nodes is not key"
    assert [(c.a, c.b, c.inner) for c in corridors] == [(START, HUB, (C1, C2, C3, C4))]
    assert corridors[0].points == 4


def test_the_exchange_is_found_scored_with_one_what_if_each_and_leaves_the_set_connected() -> None:
    """The bypass is one node longer than the corridor, so one weak leaf pays for it. The corridor
    itself is worthless, the bypass is worth a lot: PoB says take it."""

    weights = {B1: 50.0, B2: 50.0, B3: 50.0, B4: 50.0, B5: 50.0, HUB: 10.0, TAIL: 10.0, L1: 1.0, L2: 5.0}
    graph, pob, opt = _corridor_case(weights)
    before = pob.stats(())["CombinedDPS"]

    result = opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert len(result.steps) == 1, "the one corridor with a bypass is exchanged once"
    assert {B1, B2, B3, B4, B5} <= pob.allocated and not ({C1, C2, C3, C4} & pob.allocated)
    assert L1 not in pob.allocated and L2 in pob.allocated, "the weakest leaf paid for the extra point"
    assert len(pob.allocated) == 9, "the point count holds: -4 corridor -1 leaf +5 bypass"
    assert graph.is_connected(pob.allocated)
    assert pob.stats(())["CombinedDPS"] > before
    assert opt.plan_b_counts["corridors"] == 1 and opt.plan_b_counts["corridors_with_bypass"] == 1
    assert opt.plan_b_counts["corridor_kept"] == 1


def test_with_no_slack_the_corridor_has_no_bypass() -> None:
    """slack=0 forbids a bypass longer than the corridor: the five-node way round is out of
    bounds and the corridor is recorded as having none."""

    weights = {B1: 50.0, B2: 50.0, B3: 50.0, B4: 50.0, B5: 50.0}
    graph, pob, opt = _corridor_case(weights)
    logs: list[str] = []
    opt.log = logs.append

    result = opt.exchange_corridors(k=8, slack=0, min_gain=0.002)

    assert result.steps == [] and result.stopped_reason == "no bypass anywhere"
    assert opt.plan_b_counts["corridors_no_bypass"] == 1 and opt.plan_b_counts["corridors_with_bypass"] == 0
    assert any(line.startswith("no bypass: ") for line in logs)
    assert pob.allocated == {START, C1, C2, C3, C4, HUB, TAIL, L1, L2}, "nothing was touched"


def test_an_exchange_that_does_not_pay_leaves_the_build_exactly_as_it_was() -> None:
    weights = {C1: 50.0, C2: 50.0, C3: 50.0, C4: 50.0, L1: 1.0, L2: 5.0}
    graph, pob, opt = _corridor_case(weights)

    result = opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert result.steps == []
    assert pob.allocated == {START, C1, C2, C3, C4, HUB, TAIL, L1, L2}
    assert pob.mutations == [], "a candidate the what-if already prices below the incumbent is never applied"


def test_a_corridor_that_holds_a_proof_is_judged_honestly() -> None:
    """A proof holder is a key node, so it is never INSIDE a corridor; a weak leaf that holds one
    still is, and dropping it to pay for a longer bypass goes through the honest path: the real
    removal re-derives the lanes before the exchange is scored."""

    weights = {B1: 50.0, B2: 50.0, B3: 50.0, B4: 50.0, B5: 50.0, HUB: 10.0, TAIL: 10.0, L1: 1.0, L2: 5.0}
    graph, pob, opt = _corridor_case(weights)
    opt.proof_holders = {L1: {"usePowerCharges": True}}
    reconfigured: list[list[int]] = []
    opt.after_proof_removal_hook = lambda applied: reconfigured.append(list(applied["removed_node_ids"]))

    result = opt.exchange_corridors(k=8, slack=2, min_gain=0.002)

    assert len(result.steps) == 1 and L1 not in pob.allocated
    assert reconfigured and L1 in reconfigured[0], "the holder's removal re-derived the lanes"
    assert opt.plan_b_counts["honest_removals"] == 1


def test_a_proof_holder_inside_the_run_makes_it_a_key_node_and_splits_the_corridor() -> None:
    graph, pob, opt = _corridor_case()
    opt.proof_holders = {C2: {"usePowerCharges": True}}

    corridors = opt.corridors(pob.allocated)

    assert C2 in opt.key_nodes(pob.allocated)
    assert [(c.a, c.b, c.inner) for c in corridors] == [(C2, HUB, (C3, C4)), (START, C2, (C1,))]


def test_the_candidate_budget_is_a_count(monkeypatch) -> None:
    """`max_corridors` and `k` are counts, so a replay measurement of the move is deterministic."""

    graph, pob, opt = _corridor_case({B1: 50.0, B2: 50.0, B3: 50.0, B4: 50.0, B5: 50.0})
    opt.exchange_corridors(k=1, slack=2, max_corridors=1)

    assert opt.plan_b_counts["corridor_candidates"] == 1


def test_no_corridor_at_all_is_not_an_error() -> None:
    nodes = {START: _node(START, "Witch", "class_start"), HUB: _node(HUB, "Hub", "notable")}
    graph = _graph(nodes, [(START, HUB)])
    pob = _Pob(graph, {START, HUB})
    opt = _opt(pob, graph)

    result = opt.exchange_corridors()

    assert result.steps == [] and result.stopped_reason == "no corridors"


# -- the second repair policy ---------------------------------------------
#
#  START -- S1 -- S2(notable, small) and START -- F1 -- F2 -- F3(notable, large)
#  Greedy takes S1 first (a cheap frontier node next to a cheap payoff); target-first divides the
#  destination's value by the points its connection costs and commits to the far one.

S1, S2 = 50, 51
F1, F2, F3 = 60, 61, 62


def _target_case(weights: dict[int, float]) -> tuple[TreeGraph, _Pob, TreeOptimizer]:
    nodes = {
        START: _node(START, "Witch", "class_start"),
        S1: _node(S1, "s1", "normal"), S2: _node(S2, "Small", "notable"),
        F1: _node(F1, "f1", "normal"), F2: _node(F2, "f2", "normal"), F3: _node(F3, "Far", "notable"),
    }
    edges = [(START, S1), (S1, S2), (START, F1), (F1, F2), (F2, F3)]
    graph = _graph(nodes, edges)
    pob = _Pob(graph, {START}, weights)
    return graph, pob, _opt(pob, graph)


def test_target_first_takes_the_destination_with_the_best_value_per_connection_point() -> None:
    """Small is 30 for 2 points (15 per point); Far is 90 for 3 points (30 per point)."""

    graph, pob, opt = _target_case({S2: 30.0, F3: 90.0})

    result = opt.repair_target_first(3, max_targets=1)

    assert [step.name for step in result.steps] == ["target Far"]
    assert pob.allocated == {START, F1, F2, F3}


def test_target_first_fills_what_is_left_with_the_greedy_allocator() -> None:
    """Four points: Far takes three, no payoff node fits the last one, so greedy spends it."""

    graph, pob, opt = _target_case({S2: 30.0, F3: 90.0, S1: 1.0})

    result = opt.repair_target_first(4)

    assert [step.name for step in result.steps] == ["target Far", "s1"]
    assert pob.allocated == {START, F1, F2, F3, S1}
    assert result.points_spent == 4


def test_reoptimize_alternates_the_two_repair_policies_and_a_single_round_stays_greedy() -> None:
    """The loop's kick draws call `reoptimize(rounds=1)`: that round is greedy, exactly as before,
    which is what keeps `--move kick-tree` the control the plan-B acceptance is measured against."""

    graph, pob, opt = _target_case({S2: 30.0, F3: 90.0, S1: 1.0})
    pob.allocated = {START, S1, S2, F1, F2, F3}
    logs: list[str] = []
    opt.log = logs.append

    opt.reoptimize(rounds=1, ruin_points=2, refine_rounds=0, seed=1)
    opt.reoptimize(rounds=2, ruin_points=2, refine_rounds=0, seed=1)

    policies = [line.rsplit("(", 1)[1].rstrip(")") for line in logs if "ruined" in line]
    assert policies[:1] == ["greedy"], "one round is greedy: the control does not move"
    assert policies[1:] == ["greedy", "target-first"]

    with pytest.raises(ValueError, match="unknown repair policy"):
        opt.reoptimize(rounds=1, repair="wishful")


def test_the_radius_keeps_the_regrow_where_the_region_was() -> None:
    """Both destinations cost two points; only Near is inside the ball around the attachment."""

    nodes = {
        START: _node(START, "Witch", "class_start"),
        S1: _node(S1, "s1", "normal"), S2: _node(S2, "Near", "notable"),
        F1: _node(F1, "f1", "normal"), F2: _node(F2, "Far", "notable"),
    }
    graph = _graph(nodes, [(START, S1), (S1, S2), (START, F1), (F1, F2)])
    pob = _Pob(graph, {START}, {S2: 30.0, F2: 900.0})
    opt = _opt(pob, graph)

    result = opt.repair_target_first(2, attachment=[S1], radius=2, max_targets=1)

    assert [step.name for step in result.steps] == ["target Near"], "Far is three steps from s1"


# -- region ranking by completed replacement ------------------------------
#
# The research's own example (Astra A, 3.2): "a branch with loss 100 and replacement recovery 150
# is a better rebuild opportunity than a branch with loss 1 and recovery 1.2". Each region has a
# replacement of its OWN beside it, out of the other region's radius:
#
#   START -- CA -- cheap1 -- {cheap2, cheap3, cheap4(1)}      CA -- calt1 -- {calt2, calt3, calt4(1.2)}
#   START -- RA -- rich1  -- {rich2,  rich3,  rich4(100)}     RA -- ralt1 -- {ralt2, ralt3, ralt4(150)}

CA, RA = 69, 79
CHEAP = (70, 71, 72, 73)
CHEAP_ALT = (74, 75, 76, 77)
RICH = (80, 81, 82, 83)
RICH_ALT = (84, 85, 86, 87)


def _star(nodes: dict, edges: list, anchor: int, chain: tuple[int, ...], prefix: str) -> None:
    """anchor -- chain[0] -- {chain[1], chain[2], chain[3]}; the weights sit on the session."""

    nodes[chain[0]] = _node(chain[0], f"{prefix}1", "normal")
    edges.append((anchor, chain[0]))
    for i, node_id in enumerate(chain[1:], start=2):
        nodes[node_id] = _node(node_id, f"{prefix}{i}", "notable")
        edges.append((chain[0], node_id))


def _region_case() -> tuple[TreeGraph, _Pob, TreeOptimizer]:
    nodes = {START: _node(START, "Witch", "class_start"),
             CA: _node(CA, "ca", "normal"), RA: _node(RA, "ra", "normal")}
    edges: list[tuple[int, int]] = [(START, CA), (START, RA)]
    _star(nodes, edges, CA, CHEAP, "cheap")
    _star(nodes, edges, CA, CHEAP_ALT, "calt")
    _star(nodes, edges, RA, RICH, "rich")
    _star(nodes, edges, RA, RICH_ALT, "ralt")
    graph = _graph(nodes, edges)
    weights = {CHEAP[-1]: 1.0, CHEAP_ALT[-1]: 1.2, RICH[-1]: 100.0, RICH_ALT[-1]: 150.0}
    pob = _Pob(graph, {START, CA, RA, *CHEAP, *RICH}, weights)
    return graph, pob, _opt(pob, graph)


def test_regions_are_ranked_by_the_best_completed_replacement_not_by_what_they_cost_to_remove() -> None:
    graph, pob, opt = _region_case()
    before = len(pob.allocated)

    result = opt.challenge_regions(replacements=12, min_gain=0.002, radius=2, max_challenges=1)

    assert len(result.steps) == 1
    assert "rich1" in result.steps[0].name, "the costly region with the better replacement is challenged"
    assert RICH_ALT[-1] in pob.allocated, "the replacement the ranking promised is on the build"
    assert set(CHEAP) <= pob.allocated, "the cheap region, cheap to remove and worth 1.2 more, was not touched"
    assert len(pob.allocated) == before and graph.is_connected(pob.allocated)
    assert opt.plan_b_counts["regions_kept"] == 1
    assert opt.region_bucket_kept == {"4-6": 1} and set(opt.region_policy_kept) == {"target-first"}


def test_the_regrow_may_not_re_take_the_region_for_the_first_half_of_its_points() -> None:
    """Without the ban the greedy rebuilds the very trunk being challenged and the challenge tests
    nothing: here the region is the single best thing in the graph, so only the ban makes the
    first half of the points go somewhere else."""

    nodes = {START: _node(START, "Witch", "class_start"), CA: _node(CA, "ca", "normal")}
    edges: list[tuple[int, int]] = [(START, CA)]
    _star(nodes, edges, CA, CHEAP, "keep")
    _star(nodes, edges, CA, CHEAP_ALT, "other")
    graph = _graph(nodes, edges)
    pob = _Pob(graph, {START, CA, *CHEAP}, {CHEAP[-1]: 100.0, CHEAP_ALT[-1]: 1.0})
    opt = _opt(pob, graph)
    offered_the_region: list[bool] = []
    real_measure = opt._measure

    def watched(trials, keys, stats):
        if not set(CHEAP) & pob.allocated:  # the region is off the build: this is a regrow batch
            offered_the_region.append(any(set(CHEAP) & {int(n) for n in (t.get("add") or ())} for t in trials))
        return real_measure(trials, keys, stats)

    opt._measure = watched  # type: ignore[method-assign]
    opt.challenge_regions(replacements=4, max_challenges=1, radius=2)

    assert offered_the_region and offered_the_region[0] is False, "the first half was offered the old region"
    assert True in offered_the_region, "the ban is lifted for the second half"
    assert not (opt.excluded_nodes & set(CHEAP)), "the ban does not outlive the challenge"
    assert pob.allocated == {START, CA, *CHEAP}, "the challenge lost and the region came back"


def test_the_structural_counts_name_the_trunk_the_move_reached() -> None:
    graph, pob, opt = _region_case()
    before = opt.structural_counts(pob.allocated, trunk_min=4)

    opt.challenge_regions(replacements=12, max_challenges=1, radius=2)
    after = opt.structural_counts(trunk_min=4)

    assert before["trunk_considered"] == 0 and before["trunk_share"] == 0.0
    assert after["trunk_considered"] > 0 and after["trunk_share"] > 0.0
    assert after["regions"] >= 2 and after["region_candidates"] > 0


def test_a_build_with_no_detachable_region_is_not_an_error() -> None:
    nodes = {START: _node(START, "Witch", "class_start"), HUB: _node(HUB, "Hub", "notable")}
    graph = _graph(nodes, [(START, HUB)])
    pob = _Pob(graph, {START, HUB})
    opt = _opt(pob, graph)

    result = opt.challenge_regions()

    assert result.steps == [] and result.stopped_reason == "no regions"


# -- the graph primitives -------------------------------------------------


def test_bypass_paths_returns_the_shortest_ways_round_first_and_honours_its_limits() -> None:
    graph, pob, _opt_unused = _corridor_case()
    pool = {B1, B2, B3, B4, B5}

    inside = graph.bypass_paths(START, HUB, allowed=pool, max_inner=6, limit=8)
    outside = graph.bypass_paths(START, HUB, allowed=pool, max_inner=4, limit=8)

    assert inside == [(B1, B2, B3, B4, B5)]
    assert outside == [], "a way round longer than the budget is not offered"


def test_is_connected_sees_a_set_that_lost_its_way_to_the_start() -> None:
    graph, pob, _opt_unused = _corridor_case()

    assert graph.is_connected(pob.allocated)
    assert not graph.is_connected(pob.allocated - {C2})


@pytest.mark.parametrize("limit", [1, 2])
def test_bypass_paths_stops_at_its_limit(limit: int) -> None:
    """Two ways round of the same length: the limit is a count, so the enumeration is bounded."""

    nodes = {START: _node(START, "Witch", "class_start"), HUB: _node(HUB, "Hub", "notable")}
    for node_id in (B1, B2, B3, B4):
        nodes[node_id] = _node(node_id, f"b{node_id}", "normal")
    edges = [(START, B1), (B1, HUB), (START, B2), (B2, HUB), (START, B3), (B3, HUB), (START, B4), (B4, HUB)]
    graph = _graph(nodes, edges)

    assert len(graph.bypass_paths(START, HUB, allowed={B1, B2, B3, B4}, max_inner=1, limit=limit)) == limit
