"""#1147 unit 1: the fit check of a bundle on a stand, decided before any PoB call.

PoB-free: the in-memory tests build their graph and stand by hand; the probes read the bundle graph corpus
(`bundle_graph_day1.json`) and the skeleton dataclass, never a PobSession.
"""

from __future__ import annotations

import json

import pytest

from junkroan.optimizer.bundle_fit import (
    GRAPH_PATH, BundleFit, BundleGraph, BundleNode, Stand, check_bundle, load_bundle_graph, stand_from_skeleton,
)
from junkroan.search.skeleton import Skeleton


def _notable(tree_id: int, name: str) -> BundleNode:
    return BundleNode(id=f"notable:{tree_id}", surface="notable", name=name, tree_id=tree_id, ascendancy=None)


def _keystone(tree_id: int, name: str) -> BundleNode:
    return BundleNode(id=f"keystone:{tree_id}", surface="keystone", name=name, tree_id=tree_id, ascendancy=None)


def _ascendancy(tree_id: int, owner: str) -> BundleNode:
    return BundleNode(id=f"ascendancy:{tree_id}", surface="ascendancy", name=f"node {tree_id}", tree_id=tree_id, ascendancy=owner)


def _unique(name: str, item_types: tuple[str, ...]) -> BundleNode:
    return BundleNode(id=f"unique:{name}", surface="unique", name=name, tree_id=None, ascendancy=None, item_types=item_types)


ALL_SLOTS = frozenset({"Body Armour", "Helmet", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2", "Weapon 1", "Weapon 2"})


def _stand(ascendancy: str | None = "necromancer", *, fixed: frozenset[str] = frozenset(), forbidden_nodes: frozenset[int] = frozenset(),
           forbidden_keystones: frozenset[str] = frozenset()) -> Stand:
    return Stand(ascendancy=ascendancy, equipped_slots=ALL_SLOTS, fixed_slots=fixed, forbidden_nodes=forbidden_nodes,
                 forbidden_keystones=forbidden_keystones)


def _graph(*nodes: BundleNode) -> BundleGraph:
    return BundleGraph(nodes={n.id: n for n in nodes})


# --- a fitting bundle -------------------------------------------------------------------------

def test_two_notable_bundle_fits():
    graph = _graph(_notable(1006, "Potency of Will"), _notable(10016, "Executioner"))
    fit = check_bundle(["notable:1006", "notable:10016"], graph, _stand())
    assert fit == BundleFit(fits=True, reason="fits")
    assert fit.verdict == "fits"


# --- the three does_not_fit reasons -----------------------------------------------------------

def test_ascendancy_node_of_another_ascendancy_does_not_fit():
    graph = _graph(_notable(1006, "Potency of Will"), _ascendancy(10099, "ascendant"))
    fit = check_bundle(["ascendancy:10099", "notable:1006"], graph, _stand("necromancer"))
    assert fit.fits is False
    assert fit.verdict == "does_not_fit"
    assert "ascendancy:10099" in fit.reason


def test_ascendancy_node_of_the_stands_own_ascendancy_fits():
    graph = _graph(_ascendancy(60791, "necromancer"))
    assert check_bundle(["ascendancy:60791"], graph, _stand("necromancer")).fits is True


def test_unique_with_no_free_slot_does_not_fit():
    graph = _graph(_unique("Test Helm", ("Helmet",)))
    fit = check_bundle(["unique:Test Helm"], graph, _stand(fixed=frozenset({"Helmet"})))
    assert fit.fits is False
    assert "unique:Test Helm" in fit.reason


def test_two_hander_needs_weapon_2_free_as_well_as_weapon_1():
    graph = _graph(_unique("Test Staff", ("Staff",)))
    assert check_bundle(["unique:Test Staff"], graph, _stand()).fits is True
    fit = check_bundle(["unique:Test Staff"], graph, _stand(fixed=frozenset({"Weapon 2"})))
    assert fit.fits is False
    assert "unique:Test Staff" in fit.reason


def test_unique_type_with_no_slot_at_all_does_not_fit():
    graph = _graph(_unique("Test Jewel", ("Jewel",)))
    fit = check_bundle(["unique:Test Jewel"], graph, _stand())
    assert fit.fits is False
    assert "unique:Test Jewel" in fit.reason


def test_unique_missing_from_the_uniques_corpus_does_not_fit():
    graph = _graph(_unique("Test Ghost", ()))
    fit = check_bundle(["unique:Test Ghost"], graph, _stand())
    assert fit.fits is False
    assert "unique:Test Ghost" in fit.reason


def test_forbidden_keystone_by_name_does_not_fit():
    graph = _graph(_keystone(10808, "Vaal Pact"), _notable(1006, "Potency of Will"))
    fit = check_bundle(["keystone:10808", "notable:1006"], graph, _stand(forbidden_keystones=frozenset({"vaal pact"})))
    assert fit.fits is False
    assert "keystone:10808" in fit.reason


def test_forbidden_node_id_does_not_fit():
    graph = _graph(_notable(1006, "Potency of Will"))
    fit = check_bundle(["notable:1006"], graph, _stand(forbidden_nodes=frozenset({1006})))
    assert fit.fits is False
    assert "notable:1006" in fit.reason


# --- determinism and input rules --------------------------------------------------------------

def test_the_same_check_twice_gives_the_same_verdict():
    graph = _graph(_notable(1006, "Potency of Will"), _ascendancy(10099, "ascendant"), _unique("Test Helm", ("Helmet",)))
    stand = _stand("necromancer", fixed=frozenset({"Helmet"}))
    ids = ["unique:Test Helm", "ascendancy:10099", "notable:1006"]
    assert check_bundle(ids, graph, stand) == check_bundle(ids, graph, stand)


def test_the_order_of_the_ids_does_not_change_the_verdict():
    graph = _graph(_notable(1006, "Potency of Will"), _ascendancy(10099, "ascendant"))
    stand = _stand("necromancer")
    forward = check_bundle(["ascendancy:10099", "notable:1006"], graph, stand)
    backward = check_bundle(["notable:1006", "ascendancy:10099"], graph, stand)
    assert forward == backward


def test_with_two_offenders_the_reason_names_the_first_in_sorted_order():
    graph = _graph(_ascendancy(10099, "ascendant"), _ascendancy(10143, "ascendant"))
    fit = check_bundle(["ascendancy:10143", "ascendancy:10099"], graph, _stand("necromancer"))
    assert "ascendancy:10099" in fit.reason


def test_an_unknown_id_is_an_error_not_a_verdict():
    graph = _graph(_notable(1006, "Potency of Will"))
    with pytest.raises(ValueError, match="notable:999999"):
        check_bundle(["notable:999999"], graph, _stand())


def test_an_empty_bundle_is_an_error():
    with pytest.raises(ValueError):
        check_bundle([], _graph(), _stand())


# --- the real bundle graph and the skeleton loader (PoB-free) ----------------------------------

def test_loaded_graph_owns_every_ascendancy_node_and_types_the_uniques():
    graph = load_bundle_graph()
    raw = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    ascendancy_ids = [n["id"] for n in raw["nodes"] if n["surface"] == "ascendancy"]
    assert ascendancy_ids and all(graph.nodes[i].ascendancy for i in ascendancy_ids)
    uniques = [n for n in graph.nodes.values() if n.surface == "unique"]
    assert uniques and any(n.item_types for n in uniques)


def test_first_ascendancy_edge_of_another_ascendancy_does_not_fit_on_the_real_graph():
    graph = load_bundle_graph()
    edges = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))["edges"]
    stand = _stand("necromancer")
    for edge in edges:
        ends = [graph.nodes[e] for e in (edge["from"], edge["to"]) if e in graph.nodes and graph.nodes[e].surface == "ascendancy"]
        other = [n for n in ends if n.ascendancy != "necromancer"]
        if other:
            fit = check_bundle(sorted({edge["from"], edge["to"]}), graph, stand)
            assert fit.fits is False
            assert any(n.id in fit.reason for n in other)
            return
    pytest.fail("the real graph has no ascendancy edge of another ascendancy")


def test_stand_from_skeleton_reads_ascendancy_forced_slots_and_forbidden_keystones():
    skeleton = Skeleton(class_name="Witch", ascendancy="Necromancer", forced_uniques={"Helmet": "Test Helm"},
                        forbid_keystones=["Vaal Pact"])
    stand = stand_from_skeleton(skeleton)
    assert stand.ascendancy == "necromancer"
    assert stand.fixed_slots == frozenset({"Helmet"})
    assert stand.forbidden_keystones == frozenset({"vaal pact"})
    assert "Weapon 1" in stand.equipped_slots
