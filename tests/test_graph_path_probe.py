from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from graph_path_probe import bfs_path  # noqa: E402


def test_bfs_path_found_through_the_removed_node():
    adjacency = {1: [2], 2: [1, 3], 3: [2]}
    allocated = {1, 2, 3}
    assert bfs_path(adjacency, allocated, [1], 3) == [1, 2, 3]


def test_bfs_path_not_found_when_only_bridge_removed():
    adjacency = {1: [2], 2: [1, 3], 3: [2]}
    allocated = {1, 2, 3}
    assert bfs_path(adjacency, allocated, [1], 3, excluded=[2]) is None


def test_bfs_path_survives_when_alternate_bridge_exists():
    adjacency = {1: [2, 4], 2: [1, 3], 3: [2], 4: [1, 5], 5: [4, 3]}
    allocated = {1, 2, 3, 4, 5}
    path = bfs_path(adjacency, allocated, [1], 3, excluded=[2])
    assert path == [1, 4, 5, 3]


def test_bfs_path_ignores_unallocated_nodes():
    adjacency = {1: [2], 2: [1, 9], 9: [2, 3], 3: [9]}
    allocated = {1, 2, 3}
    assert bfs_path(adjacency, allocated, [1], 3) is None


def test_bfs_path_target_excluded_returns_none():
    adjacency = {1: [2], 2: [1]}
    assert bfs_path(adjacency, {1, 2}, [1], 2, excluded=[2]) is None