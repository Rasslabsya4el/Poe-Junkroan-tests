"""#1044 unit 1: a forced passive node that is not in the tree after `Skeleton._apply_forced_nodes` raises, naming
the node (its tree-graph name and id) and the class. PoB-free: a fake session answers `tree_light` and `add_nodes`.

A fake that does not allocate a forced keystone raises; a fake that allocates it does not; a request with no forced
nodes never touches the session.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.search.skeleton import Skeleton

GRAPH = TreeGraph.load()
CLASS = "Witch"


def _keystone_id(name: str) -> int:
    return next(n.node_id for n in GRAPH.nodes.values() if n.kind == "keystone" and n.name == name)


class FakePob:
    """`allocate=False`: add_nodes answers without allocating anything (the tree stays bare)."""

    def __init__(self, *, allocate: bool = True, start: int | None = None) -> None:
        self.tree: set[int] = {start} if start is not None else set()
        self.allocate = allocate
        self.add_calls: list[list[int]] = []

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": sorted(self.tree)}

    def add_nodes(self, node_ids, *, mastery_effects=None) -> dict:
        ids = [int(n) for n in node_ids]
        self.add_calls.append(ids)
        if self.allocate:
            self.tree |= set(ids)
        return {"allocated_node_ids": sorted(self.tree)}


def test_a_forced_keystone_pob_did_not_allocate_raises_naming_it_and_the_class() -> None:
    keystone = _keystone_id("Chaos Inoculation")
    sk = Skeleton(class_name=CLASS, ascendancy="Elementalist", forced_nodes=[keystone])
    pob = FakePob(allocate=False)
    with pytest.raises(RuntimeError) as exc:
        sk._apply_forced_nodes(pob)
    message = str(exc.value)
    assert "Chaos Inoculation" in message
    assert f"id {keystone}" in message
    assert CLASS in message
    assert pob.add_calls == [[keystone]], "the node was asked for once; the check is the only thing that fails"


def test_a_forced_keystone_pob_allocated_raises_nothing() -> None:
    keystone = _keystone_id("Chaos Inoculation")
    sk = Skeleton(class_name=CLASS, ascendancy="Elementalist", forced_nodes=[keystone])
    pob = FakePob(allocate=True)
    sk._apply_forced_nodes(pob)
    assert keystone in pob.tree
    assert pob.add_calls == [[keystone]]


def test_a_forced_node_already_allocated_is_not_asked_again_and_raises_nothing() -> None:
    keystone = _keystone_id("Chaos Inoculation")
    sk = Skeleton(class_name=CLASS, ascendancy="Elementalist", forced_nodes=[keystone])
    pob = FakePob(allocate=False, start=keystone)
    sk._apply_forced_nodes(pob)
    assert pob.add_calls == []


def test_a_request_with_no_forced_nodes_is_untouched() -> None:
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"a request with no forced nodes called PoB: {name}")

    sk = Skeleton(class_name=CLASS, ascendancy="Elementalist", forced_nodes=[])
    sk.apply_forced_nodes(Untouchable())  # the public entry point: no forced nodes, no PoB call
    sk.apply_forced_nodes(SimpleNamespace())  # and not even the attributes of a session


def test_a_forced_mastery_node_pob_did_not_allocate_raises_naming_it() -> None:
    costs = GRAPH.bfs_costs({GRAPH.class_starts[CLASS]}, max_depth=40)
    pick = None
    for node in GRAPH.nodes.values():
        if node.kind != "mastery" or node.node_id not in costs or costs[node.node_id][0] > 12:
            continue
        for effect_id, _sd in node.mastery_effects:
            if effect_id not in GRAPH.nodes and GRAPH.mastery_effect_holders(effect_id):
                pick = (node, effect_id)
                break
        if pick:
            break
    assert pick is not None, "the tree has a cheap mastery effect for the check"
    holder, effect_id = pick
    sk = Skeleton(class_name=CLASS, ascendancy="Elementalist", forced_nodes=[effect_id])
    # PoB allocates the path to the mastery (add_nodes on path[:-1] works) but never the mastery node itself
    pob = FakePob(allocate=True, start=GRAPH.class_starts[CLASS])
    original_add = pob.add_nodes

    def add_without_mastery(node_ids, *, mastery_effects=None):
        return original_add([n for n in node_ids if n != holder.node_id], mastery_effects=None)

    pob.add_nodes = add_without_mastery
    with pytest.raises(RuntimeError) as exc:
        sk._apply_forced_nodes(pob)
    message = str(exc.value)
    assert holder.name in message
    assert f"id {holder.node_id}" in message
    assert CLASS in message
