"""#1164 rule 1: the repair's weakest-leaf trim removes exactly one node per cut (PoB-free).

The graph's leaf list and PoB's real removal can disagree (a class start adjacent to the allocation made a trunk node look
like a leaf; PoB's own removal then cascaded ninety nodes). The what-if guard of `_weakest_leaves` reads the fast
calculator, which does not cascade, so only the real `removed_node_ids` of `remove_nodes` shows it. These tests run the
real pipeline trim (`BuildPipeline.repair`, force) over the fake session of test_issue1064_repair, whose real removal of a
named leaf takes a second node with it, as PoB's did.
"""

from __future__ import annotations

import pytest

from junkroan.optimizer.repair import RepairChoice

from test_issue1064_repair import A, B, FORCED, G, K, L1, L2, L3, L4, START, _Rig, _ScriptedPob


class _CascadingPob(_ScriptedPob):
    """A session whose REAL removal of a key takes the nodes listed for it along; the fast what-if (trial_stats) does not."""

    cascades: dict[int, set[int]] = {}

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        extra = set()
        for node in remove or ():
            extra |= self.cascades.get(int(node), set()) & self.allocated
        return super().mutate_nodes(add=add, remove=sorted({int(n) for n in remove or ()} | extra) if remove else remove, mastery_effects=mastery_effects)


def _rig(monkeypatch, cascades: dict[int, set[int]]):
    rig = _Rig(monkeypatch, allocated={START, A, B, L1, L2, L3, L4}, budget=7, gains=[0.005])
    rig.pob.__class__ = _CascadingPob
    rig.pob.cascades = cascades
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    return rig


def test_a_cut_that_takes_two_nodes_is_refused_the_tree_restored_and_the_next_leaf_removed_alone(monkeypatch):
    rig = _rig(monkeypatch, {L1: {L3}})  # L1 is the weakest leaf; PoB's removal of it also takes L3
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED, "force"))
    assert {L1, L3} <= rig.pob.allocated, "the refused cut is put back whole: both nodes it took"
    assert not {L2, B} & rig.pob.allocated, "the next leaves in the ranking went, each alone"
    assert {A, G, K, L4} <= rig.pob.allocated
    assert len(rig.pob.allocated) == 7
    removals = [remove for _add, remove in rig.pob.mutations if remove]
    assert set(removals[0]) == {L1, L3}  # the refused cut really cascaded
    assert removals[1:] == [(L2,), (B,)]  # and every cut after it took one node


def test_the_tree_state_after_a_refused_cut_is_the_state_before_it(monkeypatch):
    rig = _rig(monkeypatch, {L1: {L3}})
    rig.pob.weights[L2] = rig.pob.weights[B] = 50.0  # L1 refused, then L3 is the next-weakest, then L4: two cuts of one node
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED, "force"))
    assert {L1, L2, B, A, G, K} <= rig.pob.allocated
    assert len(rig.pob.allocated) == 7


def test_no_leaf_left_after_the_refusals_raises(monkeypatch):
    others = {L1: {L2}, L2: {L1}, L3: {L4}, L4: {L3}, B: {L1}}
    rig = _rig(monkeypatch, others)  # every leaf cascades
    with pytest.raises(RuntimeError, match="no leaf to remove"):
        rig.run(RepairChoice(FORCED, "force"))
    assert {L1, L2, L3, L4, B, A} <= rig.pob.allocated, "every refused cut was put back"


def test_a_clean_trim_is_unchanged(monkeypatch):
    rig = _rig(monkeypatch, {})
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED, "force"))
    assert not {L1, L2} & rig.pob.allocated and {B, L3, L4} <= rig.pob.allocated
    assert [add for add, _remove in rig.pob.mutations if add] == [(K,)], "no restore call without a refusal"


def test_a_cascade_that_takes_a_forced_node_is_refused_and_the_repair_goes_on_with_the_next_leaf(monkeypatch):
    rig = _rig(monkeypatch, {L1: {G}})  # L1's removal also takes G, and with it the pinned keystone K behind G
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED, "force"))
    assert {L1, G, K} <= rig.pob.allocated, "the forced path is back after the refused cut"
    assert not {L2, B} & rig.pob.allocated and len(rig.pob.allocated) == 7
    removals = [remove for _add, remove in rig.pob.mutations if remove]
    assert K in rig.skeleton.forced_nodes and set(removals[0]) == {L1, G} and removals[1:] == [(L2,), (B,)]


def test_the_taken_nodes_go_back_nearest_first_from_the_surviving_tree():
    """PoB adds in list order, each by its shortest path from what is allocated then: a far node first pulls extras in."""

    from junkroan.optimizer.pipeline import BuildPipeline
    from test_tree_plan_b import _Pob, _graph, _node, _opt

    near, mid, far = 50, 40, 30  # connection order START - 50 - 40 - 30: descending ids, so sorted-by-id is far first
    nodes = {START: _node(START, "Witch", "class_start"), **{n: _node(n, f"n{n}", "normal") for n in (near, mid, far)}}
    graph = _graph(nodes, [(START, near), (near, mid), (mid, far)])

    class Pob(_Pob):
        def add_nodes(self, ids, *, mastery_effects=None):
            return self.mutate_nodes(add=ids, mastery_effects=mastery_effects)

    pob = Pob(graph, {START, near, mid, far})
    tree = _opt(pob, graph)
    before = tree.current_allocated()
    removed = pob.mutate_nodes(remove=[near])  # the cascade takes the whole chain
    assert set(removed["removed_node_ids"]) == {near, mid, far}
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p._restore_cut(tree, removed, removed["removed_node_ids"], before)
    assert pob.mutations[-1][0] == (near, mid, far)
    assert tree.current_allocated() == before
