"""Cluster socket sizes from tree.lua's expansionJewel.size (no PoB needed)."""

from __future__ import annotations

import json
from collections import Counter

from junkroan.optimizer.tree_graph import TreeGraph, cluster_socket_size
from junkroan.pob.game_corpus import DEFAULT_CORPUS_ROOT


def test_cluster_socket_counts() -> None:
    g = TreeGraph.load()
    counts = Counter(n.expansion_size for n in g.nodes.values() if n.expansion_size is not None)
    assert counts == {2: 6, 1: 18, 0: 18}


def test_plain_jewel_socket_is_none() -> None:
    g = TreeGraph.load()
    plain = [n for n in g.nodes.values() if n.kind == "jewel" and n.expansion_size is None]
    assert plain
    assert all(cluster_socket_size(n) is None for n in plain)


def test_passives_record_of_large_socket() -> None:
    records = json.loads((DEFAULT_CORPUS_ROOT / "passives.json").read_text(encoding="utf-8"))
    recs = records["records"] if isinstance(records, dict) else records
    large = [r for r in recs if r.get("expansion_size") == 2]
    assert len(large) == 6
    assert all("Jewel" in r["name"] for r in large)


INNER = {61288: 21984, 48679: 7960, 6910: 32763, 64583: 21984, 13170: 21984}


def test_inner_sockets_not_allocatable() -> None:
    g = TreeGraph.load()
    for nid, parent in INNER.items():
        node = g.node(nid)
        assert node is not None and node.kind == "jewel"
        assert node.expansion_parent == parent
        assert nid not in g.allocatable
    for nid in (21984, 7960, 32763):
        assert nid in g.allocatable
        assert g.node(nid).expansion_parent is None


def test_bfs_skips_inner_sockets() -> None:
    g = TreeGraph.load()
    with_parent = {n.node_id for n in g.nodes.values() if n.expansion_parent is not None}
    for outer in (21984, 7960):
        reached = set(g.bfs_costs({outer}, max_depth=6))
        assert not reached & with_parent


def test_allocatable_drop_equals_parented_records() -> None:
    from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus

    g = TreeGraph.load()
    corpus = canonical_active_tree_corpus()
    before_ids = {int(n) for n in corpus["active_allocatable_node_ids"]}
    parented = {n.node_id for n in g.nodes.values() if n.expansion_parent is not None}
    dropped = len(parented & before_ids)
    print("parented", len(parented), "dropped from allocatable", dropped, "allocatable now", len(g.allocatable))
    assert dropped > 0
    assert not parented & g.allocatable
