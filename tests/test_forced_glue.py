"""#510 unit 8: the seams between the forced-node units agree on a mastery effect (A, B, D PoB-free; C one `pob` test).

A  validate puts a mastery effect's EFFECT id into `forced_nodes` (what `TreeGraph.resolve_forced` and
   `Skeleton._apply_forced_nodes` read); an effect id that is also a tree node id is one problem line.
B  the protected set holds the mastery node that carries a forced effect.
C  a regrow (`_reset_construction_tree`: `set_tree` + the re-add) leaves the forced nodes allocated.
D  the trace counts a mastery trial that takes the forced effect off its holder, not one that sets it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.pipeline import protected_nodes_of
from junkroan.optimizer.trace import forced_classes
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.search.hypothesis import passive_nodes
from junkroan.search.request import BuildRequest, expand

GRAPH = TreeGraph.load()
ELEMENTAL_OVERLOAD = 22088
FAR_NOTABLE = 8135  # Practical Application, 7 points from the Witch start


def _effect_names(colliding: bool) -> list[tuple[str, int]]:
    """(request name, effect id) of mastery effects whose text names exactly one effect id."""

    out = []
    for name, recs in passive_nodes().items():
        if any(r["kind"] != "mastery effect" for r in recs):
            continue
        ids = {int(r["effect_id"]) for r in recs}
        if len(ids) == 1 and (next(iter(ids)) in GRAPH.nodes) == colliding:
            out.append((name, next(iter(ids))))
    return sorted(out)


def _expand(**raw):
    return expand(BuildRequest.from_dict({"skill": "Fireball", "ascendancy": "Elementalist", "mode": "hit", **raw}))


# -- A ------------------------------------------------------------------------------------------------------------


def test_a_mastery_effect_name_forces_its_effect_id() -> None:
    name, effect_id = _effect_names(colliding=False)[0]
    exp = _expand(nodes=[name, "Elemental Overload"])
    assert exp.ok, exp.problems
    forced = exp.validations[0].skeleton.forced_nodes
    assert effect_id in forced and ELEMENTAL_OVERLOAD in forced
    plain, masteries = GRAPH.resolve_forced(forced, class_name="Witch")  # the id the skeleton carries resolves
    assert plain == [ELEMENTAL_OVERLOAD] and list(masteries.values()) == [effect_id]
    assert GRAPH.nodes[next(iter(masteries))].kind == "mastery"


def test_a_colliding_effect_id_is_one_problem_line_not_a_wrong_node() -> None:
    colliding = _effect_names(colliding=True)
    assert colliding, "the corpus has mastery effect ids that are also node ids (16 of 353)"
    name, effect_id = colliding[0]
    exp = _expand(nodes=[name])
    assert not exp.ok
    lines = [p for p in exp.problems if "cannot be forced" in p]
    assert len(lines) == 1, exp.problems
    assert name in lines[0] and f"collides with node {effect_id}" in lines[0]
    assert not exp.validations  # no skeleton is built, so no wrong node is forced


# -- B ------------------------------------------------------------------------------------------------------------


def test_b_protected_set_holds_the_holder_of_a_forced_effect() -> None:
    _name, effect_id = _effect_names(colliding=False)[0]
    holder = GRAPH.mastery_effect_holders(effect_id)[0]
    sk = SimpleNamespace(forced_nodes=[ELEMENTAL_OVERLOAD, effect_id])
    assert protected_nodes_of(sk, {holder: effect_id}) >= {ELEMENTAL_OVERLOAD, holder}
    assert holder not in protected_nodes_of(sk), "without the build's selections the effect pins nothing (the old behaviour)"
    other = next(h for h in GRAPH.nodes.values() if h.kind == "mastery" and h.node_id != holder)
    assert other.node_id not in protected_nodes_of(sk, {holder: effect_id, other.node_id: other.mastery_effects[0][0]})


# -- D ------------------------------------------------------------------------------------------------------------


def test_d_trace_classes_of_a_mastery_trial_on_a_forced_effect() -> None:
    _name, effect_id = _effect_names(colliding=False)[0]
    holders = GRAPH.mastery_effect_holders(effect_id)
    holder = holders[0]
    other_effect = next(e for e, _s in GRAPH.nodes[holder].mastery_effects if e != effect_id)
    forced = {"nodes": [ELEMENTAL_OVERLOAD, effect_id]}
    missing = {f"forced-missing:node:{effect_id}"}
    assert forced_classes({"mastery": {holder: other_effect}}, forced) == missing
    assert forced_classes({"mastery": {str(holder): other_effect}}, forced) == missing
    assert forced_classes({"mastery": {holder: effect_id}}, forced) == {"forced:kept"}
    # a node that does not hold it, whatever the swap, is not the forced effect's
    stranger = next(n.node_id for n in GRAPH.nodes.values() if n.kind == "mastery" and n.node_id not in holders)
    assert forced_classes({"mastery": {stranger: other_effect}}, forced) == {"forced:kept"}
    # the build's own holder, when the trace is given it, beats "any node that offers the effect"
    if len(holders) > 1:
        held = {"nodes": [effect_id], "mastery_holders": {holders[1]: effect_id}}
        assert forced_classes({"mastery": {holders[0]: other_effect}}, held) == {"forced:kept"}
        assert forced_classes({"mastery": {holders[1]: other_effect}}, held) == missing
    # a plain node id keeps the old rule: any effect swap on it counts
    plain = {"nodes": [holder]}
    assert forced_classes({"mastery": {holder: effect_id}}, plain) == {f"forced-missing:node:{holder}"}


# -- C (PoB) ------------------------------------------------------------------------------------------------------


@pytest.mark.pob
def test_c_reset_construction_tree_keeps_the_forced_nodes_in_pob() -> None:
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.pob.session import PobSession
    from junkroan.search.skeleton import Skeleton

    costs = GRAPH.bfs_costs({GRAPH.class_starts["Witch"]}, max_depth=40)
    effect_id = next(e for n in GRAPH.nodes.values() if n.kind == "mastery" for e, _s in n.mastery_effects
                     if e not in GRAPH.nodes and GRAPH.mastery_effect_holders(e) and n.node_id in costs and costs[n.node_id][0] <= 12)
    sk = Skeleton(class_name="Witch", ascendancy="Elementalist", forced_nodes=[ELEMENTAL_OVERLOAD, FAR_NOTABLE, effect_id])
    holder = next(iter(GRAPH.resolve_forced([effect_id], class_name="Witch")[1]))
    opt = SimpleNamespace(protected=frozenset(), history=[], invalidate_after_recovery=lambda: None)
    with PobSession(run_id="forced-glue-reset") as pob:
        p = BuildPipeline.__new__(BuildPipeline)
        p.pob = pob
        p.judging = SimpleNamespace(trees=lambda: ())
        sk.apply(pob)
        before = {int(n) for n in pob.tree_light().get("user_allocated_node_ids") or ()}
        p._reset_construction_tree(sk, opt)
        state = pob.tree_light()
    allocated = {int(n) for n in state.get("user_allocated_node_ids") or ()}
    assert {ELEMENTAL_OVERLOAD, FAR_NOTABLE, holder} <= allocated, sorted({ELEMENTAL_OVERLOAD, FAR_NOTABLE, holder} - allocated)
    assert f"{holder}:{effect_id}" in (state.get("mastery_effect_ids") or [])
    assert allocated == before, "the regrown bare tree is the applied skeleton's tree again"
    assert {ELEMENTAL_OVERLOAD, FAR_NOTABLE, holder} <= opt.protected, "the protected set follows the holder after the regrow"
