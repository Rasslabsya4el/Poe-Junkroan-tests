"""#1147 unit 5a: the stand from a PoB XML and the acceptance bundles chosen by rule (PoB-free).

The synthetic tests run on a small graph and a hand-written stand XML. The real-stand tests decode the three seed-4
stands (artifacts/stands-1124) with decode_import_code: no PobSession is opened anywhere in this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.bundle_fit import GRAPH_PATH, BundleGraph, BundleNode, Stand, load_bundle_graph
from junkroan.optimizer.bundle_select import (
    acceptance_bundles,
    does_not_fit_probe,
    first_unique_bundle,
    stand_from_xml,
    unique_probe,
)
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
from junkroan.pob.session import decode_import_code

ROOT = Path(__file__).resolve().parents[1]
STANDS = ROOT / "artifacts" / "stands-1124"
STAND_NAMES = ("spark", "smite", "summon_raging_spirits")
ASCENDANCY_OF = {"spark": "inquisitor", "smite": "slayer", "summon_raging_spirits": "guardian"}
# independent literals of the real stands, read from the graph and the stands once (names in the issue report)
EXPECTED_ACCEPTANCE = {
    "spark": [("notable:10115", "notable:14813"), ("notable:18174", "notable:20832")],
    "smite": [("notable:18174", "notable:20832"), ("notable:10115", "notable:21634")],
    "summon_raging_spirits": [("notable:10115", "notable:14813"), ("notable:18174", "notable:20832")],
}
EXPECTED_UNIQUE = ("keystone:39713", "unique:Cybil's Paw, Thresher Claw")
needs_stands = pytest.mark.skipif(
    not ((ROOT / "var" / "cache").is_dir() and all((STANDS / f"{n}-s4.pob.txt").is_file() for n in STAND_NAMES)),
    reason="var/cache or the seed-4 stand files are not present",
)


def _stand_xml(name: str) -> str:
    return decode_import_code((STANDS / f"{name}-s4.pob.txt").read_text(encoding="utf-8"))


# -- synthetic stand XML and graph --------------------------------------------------------------------------------------

def _xml(ascendancy="Inquisitor", allocated=(), slots=None) -> str:
    slots = {"Weapon 1": "1", "Helmet": "0"} if slots is None else slots
    slot_xml = "".join(f'<Slot name="{name}" itemId="{item}"/>' for name, item in slots.items())
    return (
        f'<PathOfBuilding><Build ascendClassName="{ascendancy}"/>'
        f'<Tree><Spec nodes="{",".join(str(n) for n in allocated)}"/></Tree>'
        f'<Items activeItemSet="1"><ItemSet id="1">{slot_xml}</ItemSet></Items></PathOfBuilding>'
    )


def _node(node_id, surface, tree_id=None, ascendancy=None, item_types=()) -> BundleNode:
    return BundleNode(id=node_id, surface=surface, name=node_id, tree_id=tree_id, ascendancy=ascendancy,
                      item_types=tuple(item_types))


NODES = [
    _node("notable:1", "notable", 1),
    _node("notable:2", "notable", 2),
    _node("keystone:3", "keystone", 3),
    _node("mastery:4", "mastery", 4),
    _node("notable:7", "notable", 7),  # allocated on the synthetic stand
    _node("notable:8", "notable", 8),  # not on the active tree
    _node("ascendancy:5", "ascendancy", 5, ascendancy="inquisitor"),
    _node("ascendancy:6", "ascendancy", 6, ascendancy="slayer"),
    _node("unique:Wand A, Goat", "unique", None, item_types=("Wand",)),
]
GRAPH = BundleGraph(nodes={n.id: n for n in NODES})
ALLOCATABLE = frozenset({1, 2, 3, 4, 5, 6, 7})  # 8 is not on the tree
STAND = Stand(ascendancy="inquisitor", equipped_slots=frozenset({"Weapon 1", "Helmet"}))
# the edges, written in no order: the module must sort them by (from, to)
EDGES = [
    {"from": "notable:2", "to": "mastery:4", "kind": "x"},
    {"from": "notable:1", "to": "notable:7", "kind": "x"},
    {"from": "notable:1", "to": "notable:8", "kind": "x"},
    {"from": "notable:1", "to": "ascendancy:6", "kind": "x"},
    {"from": "keystone:3", "to": "notable:1", "kind": "x"},
    {"from": "notable:2", "to": "keystone:3", "kind": "x"},
    {"from": "ascendancy:5", "to": "notable:1", "kind": "x"},
    {"from": "notable:1", "to": "notable:2", "kind": "x"},
]


def _graph_json(tmp_path: Path, edges=EDGES) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": [], "edges": edges}), encoding="utf-8")
    return path


# -- stand_from_xml -----------------------------------------------------------------------------------------------------

def test_stand_takes_the_lower_cased_ascendancy_and_the_filled_slots_only():
    stand = stand_from_xml(_xml(ascendancy="Inquisitor", slots={"Weapon 1": "1", "Helmet": "0", "Belt": "2"}))
    assert stand.ascendancy == "inquisitor"
    assert stand.equipped_slots == frozenset({"Weapon 1", "Belt"})  # Helmet is listed with itemId 0: not worn
    assert stand.fixed_slots == frozenset()
    assert stand.forbidden_nodes == frozenset()
    assert stand.forbidden_keystones == frozenset()


def test_stand_of_a_build_without_slots_holds_no_slot():
    assert stand_from_xml(_xml(slots={"Helmet": "0"})).equipped_slots == frozenset()


# -- acceptance bundles, synthetic ---------------------------------------------------------------------------------------

def test_acceptance_takes_the_first_two_edges_by_sorted_ends_that_pass_every_filter(tmp_path):
    xml = _xml(allocated=[7])
    bundles = acceptance_bundles(_graph_json(tmp_path), xml, GRAPH, STAND, ALLOCATABLE)
    # sorted edges: (keystone:3, notable:1) (notable:1, ascendancy:6) (notable:1, notable:2) ...
    # the mastery, the allocated notable:7, the off-tree notable:8, the ascendancy ends and the foreign ascendancy are out
    assert [b.ids for b in bundles] == [("keystone:3", "notable:1"), ("notable:1", "notable:2")]
    assert [b.edge for b in bundles] == [EDGES[4], EDGES[7]]
    assert all(b.fit.fits for b in bundles)


def test_acceptance_skips_an_edge_with_an_allocated_end(tmp_path):
    xml = _xml(allocated=[1])  # notable:1 allocated: every edge through it is out
    bundles = acceptance_bundles(_graph_json(tmp_path), xml, GRAPH, STAND, ALLOCATABLE)
    assert [b.ids for b in bundles] == [("keystone:3", "notable:2")]  # the edge (notable:2, keystone:3), sorted


def test_acceptance_is_the_same_list_on_every_call(tmp_path):
    path = _graph_json(tmp_path)
    xml = _xml(allocated=[7])
    assert acceptance_bundles(path, xml, GRAPH, STAND, ALLOCATABLE) == acceptance_bundles(path, xml, GRAPH, STAND, ALLOCATABLE)


def test_acceptance_gives_fewer_than_two_when_fewer_edges_pass(tmp_path):
    path = _graph_json(tmp_path, edges=[{"from": "notable:1", "to": "notable:8"}])
    assert acceptance_bundles(path, _xml(), GRAPH, STAND, ALLOCATABLE) == []


def test_probe_is_the_first_sorted_edge_with_a_foreign_ascendancy_end(tmp_path):
    probe = does_not_fit_probe(_graph_json(tmp_path), GRAPH, STAND)
    assert probe is not None
    assert probe.ids == ("ascendancy:6", "notable:1")  # the own ascendancy:5 edge does not count
    assert not probe.fit.fits
    assert "slayer" in probe.fit.reason and "inquisitor" in probe.fit.reason


def test_probe_is_none_without_a_foreign_ascendancy_edge(tmp_path):
    path = _graph_json(tmp_path, edges=[{"from": "notable:1", "to": "notable:2"}])
    assert does_not_fit_probe(path, GRAPH, STAND) is None


def test_unique_probe_is_the_first_sorted_unique_edge_that_fits_and_has_a_free_tree_end(tmp_path):
    edges = EDGES + [
        {"from": "notable:1", "to": "unique:Wand A, Goat", "kind": "x"},
        {"from": "notable:7", "to": "unique:Wand A, Goat", "kind": "x"},  # allocated tree end: out
    ]
    path = _graph_json(tmp_path, edges=edges)
    pick = first_unique_bundle(path, GRAPH, STAND, {7}, ALLOCATABLE)
    assert pick is not None
    assert pick.ids == ("notable:1", "unique:Wand A, Goat")
    assert unique_probe(path, _xml(allocated=[7]), GRAPH, STAND, ALLOCATABLE) == pick


def test_unique_probe_skips_a_unique_with_no_slot_on_the_stand(tmp_path):
    path = _graph_json(tmp_path, edges=[{"from": "notable:1", "to": "unique:Wand A, Goat"}])
    no_weapon = Stand(ascendancy="inquisitor", equipped_slots=frozenset({"Helmet"}))
    assert unique_probe(path, _xml(), GRAPH, no_weapon, ALLOCATABLE) is None


# -- the real stands -----------------------------------------------------------------------------------------------------

@needs_stands
@pytest.mark.parametrize("name", STAND_NAMES)
def test_stand_from_its_xml_has_its_ascendancy_and_its_worn_slots(name):
    xml = _stand_xml(name)
    stand = stand_from_xml(xml)
    items = ET.fromstring(xml).find("Items")
    active = next(s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1"))
    worn = {s.get("name") for s in active.findall("Slot") if s.get("itemId") != "0"}
    assert stand.ascendancy == ASCENDANCY_OF[name]
    assert stand.equipped_slots == frozenset(worn) and worn
    assert stand.fixed_slots == frozenset() and stand.forbidden_nodes == frozenset()


@needs_stands
@pytest.mark.parametrize("name", STAND_NAMES)
def test_real_stand_gets_two_acceptance_bundles_that_fit_and_are_free_on_the_tree(name):
    xml = _stand_xml(name)
    graph = load_bundle_graph()
    stand = stand_from_xml(xml)
    allocatable = TreeGraph.load().allocatable
    allocated = set(parse_allocated_from_xml(xml))
    bundles = acceptance_bundles(GRAPH_PATH, xml, graph, stand, allocatable)
    assert len(bundles) == 2
    edges = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))["edges"]
    for bundle in bundles:
        assert bundle.fit.fits
        assert bundle.ids == tuple(sorted((bundle.edge["from"], bundle.edge["to"])))
        for node_id in bundle.ids:
            node = graph.node(node_id)
            assert node.surface in ("notable", "keystone")
            assert node.tree_id not in allocated
            assert node.tree_id in allocatable
    keys = [(b.edge["from"], b.edge["to"]) for b in bundles]
    assert keys == sorted(keys)  # the first two in (from, to) order
    assert all(b.edge in edges for b in bundles)
    assert [b.ids for b in bundles] == EXPECTED_ACCEPTANCE[name]  # independent literals, read off the graph once


@needs_stands
@pytest.mark.parametrize("name", STAND_NAMES)
def test_real_stand_selection_is_deterministic(name):
    xml = _stand_xml(name)
    graph = load_bundle_graph()
    stand = stand_from_xml(xml)
    allocatable = TreeGraph.load().allocatable
    first = acceptance_bundles(GRAPH_PATH, xml, graph, stand, allocatable)
    assert first == acceptance_bundles(GRAPH_PATH, xml, graph, stand, allocatable)
    assert does_not_fit_probe(GRAPH_PATH, graph, stand) == does_not_fit_probe(GRAPH_PATH, graph, stand)
    assert unique_probe(GRAPH_PATH, xml, graph, stand, allocatable) == unique_probe(GRAPH_PATH, xml, graph, stand, allocatable)


@needs_stands
@pytest.mark.parametrize("name", STAND_NAMES)
def test_real_stand_probe_is_does_not_fit_and_names_the_foreign_ascendancy(name):
    graph = load_bundle_graph()
    stand = stand_from_xml(_stand_xml(name))
    probe = does_not_fit_probe(GRAPH_PATH, graph, stand)
    assert probe is not None and not probe.fit.fits
    foreign = [graph.node(i).ascendancy for i in probe.ids if graph.node(i).surface == "ascendancy"]
    assert foreign and foreign[0] != stand.ascendancy
    assert foreign[0] in probe.fit.reason


@needs_stands
@pytest.mark.parametrize("name", STAND_NAMES)
def test_real_stand_unique_probe_is_a_fitting_unique_edge_with_a_free_tree_end(name):
    xml = _stand_xml(name)
    graph = load_bundle_graph()
    stand = stand_from_xml(xml)
    allocated = set(parse_allocated_from_xml(xml))
    pick = unique_probe(GRAPH_PATH, xml, graph, stand, TreeGraph.load().allocatable)
    assert pick is not None and pick.fit.fits
    assert pick.ids == EXPECTED_UNIQUE  # independent literal: the first fitting unique edge of each stand
    tree_end = next(i for i in pick.ids if graph.node(i).surface != "unique")
    assert graph.node(tree_end).tree_id not in allocated
