"""Pure-Python tree graph tests (no PoB needed)."""

from __future__ import annotations

from pathlib import Path

from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
from junkroan.pob.session import decode_import_code

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
SPARK_S1_BUILD = FIXTURES.parent / "tree_graph" / "spark-s1.pob.txt"


def _stormbrand_nodes() -> list[int]:
    code = (FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()
    return parse_allocated_from_xml(decode_import_code(code))


def _spark_s1_nodes() -> list[int]:
    xml_text = decode_import_code(SPARK_S1_BUILD.read_text(encoding="utf-8"))
    return parse_allocated_from_xml(xml_text)


def test_graph_loads_current_tree() -> None:
    g = TreeGraph.load()
    assert g.tree_version == "3_29"
    assert len(g.allocatable) > 1500
    assert {"Witch", "Templar", "Duelist", "Ranger", "Marauder", "Shadow", "Scion"} <= set(g.class_starts)
    # adjacency is symmetric except at masteries: a mastery is reached from its notables but
    # expands to nothing (it is not a path between the notables of its cluster, 2026-09-23)
    for a, nbs in list(g.adjacency.items())[:500]:
        for b in nbs:
            if getattr(g.nodes.get(b), "kind", None) != "mastery":
                assert a in g.adjacency[b]
    assert all(not g.adjacency.get(n, ()) for n, node in g.nodes.items() if node.kind == "mastery")
    kinds = {n.kind for n in g.nodes.values()}
    assert {"normal", "notable", "keystone", "mastery", "class_start"} <= kinds  # ascendancy nodes live in ascendancies.json


def test_reference_tree_is_connected_and_has_frontier() -> None:
    g = TreeGraph.load()
    allocated = _stormbrand_nodes()
    assert len(allocated) > 100
    frontier = g.frontier(allocated)
    assert 20 < len(frontier) < 400
    assert not (frontier & set(allocated))

    costs = g.bfs_costs(allocated, max_depth=6)
    assert all(1 <= cost <= 6 for cost, _ in costs.values())
    assert all(path[-1] == node for node, (_, path) in costs.items())
    # cost-1 nodes are exactly the frontier
    assert {n for n, (c, _) in costs.items() if c == 1} == frontier

    cands = g.candidates(allocated, max_depth=6)
    assert any(c.kind == "notable" and c.cost > 1 for c in cands)
    assert all(c.node_id in g.allocatable for c in cands)


def test_leaves_and_cascades_on_reference_tree() -> None:
    g = TreeGraph.load()
    allocated = _stormbrand_nodes()
    leaves = g.removable_leaves(allocated)
    assert 5 < len(leaves) < len(allocated)
    for leaf in leaves[:10]:
        assert g.cascade_if_removed(allocated, leaf) == {leaf}
    # a class-start neighbour on a chain is not a leaf
    non_leaves = [n for n in allocated if n in g.allocatable and n not in leaves]
    assert non_leaves
    assert len(g.cascade_if_removed(allocated, non_leaves[0])) >= 2


def test_mastery_is_not_a_path_between_notables() -> None:
    g = TreeGraph.load()
    allocated = _spark_s1_nodes()
    # Divine Judgement (13164) hangs off Divine Wrath (14665) only through their own passives:
    # removing 8198 cascades to 13164 in PoB too, and the mastery 44298 is never a bridge.
    cascade = g.cascade_if_removed(allocated, 8198)
    assert 13164 in cascade
    assert 8198 in cascade
    assert g.neighbours(44298) == frozenset()
    assert 44298 in g.neighbours(14665)
