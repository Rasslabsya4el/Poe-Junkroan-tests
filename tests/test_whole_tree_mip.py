"""Exact additive connected-tree MIP tests (no PoB runtime)."""

from __future__ import annotations

import pytest

pytest.importorskip("highspy")

from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.whole_tree_mip import solve_connected_tree


def _two_arms() -> TreeGraph:
    # Root 0; short arm 0-1-2 pays 5, long arm 0-3-4-5 pays 100.
    nodes = {node_id: TreeNode(node_id, str(node_id), "normal", (), None, None) for node_id in range(6)}
    return TreeGraph(
        tree_version="test",
        nodes=nodes,
        adjacency={
            0: frozenset((1, 3)),
            1: frozenset((0, 2)),
            2: frozenset((1,)),
            3: frozenset((0, 4)),
            4: frozenset((3, 5)),
            5: frozenset((4,)),
        },
        allocatable=frozenset((1, 2, 3, 4, 5)),
        class_starts={"Test": 0},
    )


def test_connected_mip_does_not_nest_across_budgets() -> None:
    graph = _two_arms()
    weights = {1: 0.0, 2: 5.0, 3: 0.0, 4: 0.0, 5: 100.0}

    budget_three = solve_connected_tree(graph, root=0, weights=weights, point_budget=3)
    budget_four = solve_connected_tree(graph, root=0, weights=weights, point_budget=4)

    assert budget_three.nodes == {1, 2}
    assert budget_four.nodes == {3, 4, 5}
    assert budget_three.optimal and budget_four.optimal


def test_connected_mip_respects_hamming_radius() -> None:
    graph = _two_arms()
    weights = {1: 0.0, 2: 5.0, 3: 0.0, 4: 0.0, 5: 100.0}
    incumbent = {1, 2}

    radius_four = solve_connected_tree(
        graph,
        root=0,
        weights=weights,
        point_budget=4,
        incumbent=incumbent,
        hamming_radius=4,
    )
    radius_five = solve_connected_tree(
        graph,
        root=0,
        weights=weights,
        point_budget=4,
        incumbent=incumbent,
        hamming_radius=5,
    )

    assert radius_four.nodes == incumbent
    assert radius_five.nodes == {3, 4, 5}
