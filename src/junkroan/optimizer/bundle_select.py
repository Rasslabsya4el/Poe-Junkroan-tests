"""The stand of a PoB build XML and the acceptance bundles chosen by rule (#1147, unit 5a): PoB-free.

A stand is read from its XML (the ascendancy, the slots it wears). The acceptance bundles of a stand are the first
two edges of the bundle graph, sorted by (from, to), that pass every filter below; the probes are the first edge
of each of two kinds. Nothing here is chosen by hand or by a language model: the same inputs give the same list.

- acceptance: both ends are notable or keystone, both on the active tree (`TreeGraph.allocatable`), neither
  allocated on the stand, and `bundle_fit.check_bundle` says the bundle fits;
- does-not-fit probe: the first edge with an ascendancy end of another ascendancy than the stand's;
- unique probe: the first edge with one unique end that fits, and one on-tree notable / keystone end that the
  stand does not allocate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Collection
from xml.etree import ElementTree as ET

from junkroan.optimizer.bundle_fit import BundleFit, BundleGraph, BundleNode, Stand, check_bundle
from junkroan.optimizer.tree_graph import parse_allocated_from_xml
from junkroan.search.hypothesis import ascendancy

ACCEPTANCE_PER_STAND = 2
TREE_SURFACES = ("notable", "keystone")


@dataclass(frozen=True)
class Bundle:
    """A bundle of two graph node ids (sorted), the graph edge it came from and its fit on the stand."""

    ids: tuple[str, str]
    edge: dict
    fit: BundleFit


def stand_from_xml(xml_text: str) -> Stand:
    """The stand a PoB build XML describes: its ascendancy as a lower-case PoB id (no ascendancy = None), the slots
    of the active item set that hold an item (itemId other than "0"), and no forced slot, forbidden node or
    forbidden keystone (a stand carries no request)."""

    root = ET.fromstring(xml_text)
    build = root.find("Build")
    if build is None:
        raise ValueError("PoB XML has no Build element")
    name = (build.get("ascendClassName") or "").strip()
    record = ascendancy(name) if name and name != "None" else None
    owner = record["ascendancy_id"] if record else (None if name in ("", "None") else name)
    return Stand(
        ascendancy=owner.lower() if owner else None,
        equipped_slots=frozenset(_worn_slots(root)),
    )


def _worn_slots(root: ET.Element) -> set[str]:
    items = root.find("Items")
    if items is None:
        return set()
    active_id = items.get("activeItemSet") or "1"
    worn: set[str] = set()
    for item_set in items.findall("ItemSet"):
        if item_set.get("id") != active_id:
            continue
        for slot in item_set.findall("Slot"):
            if slot.get("itemId") not in (None, "", "0"):
                worn.add(slot.get("name"))
    return worn


def acceptance_bundles(graph_json_path: Path | str, xml_text: str, graph: BundleGraph, stand: Stand,
                       tree_allocatable: Collection[int]) -> list[Bundle]:
    """The stand's acceptance bundles: the first `ACCEPTANCE_PER_STAND` edges, sorted by (from, to), that pass every
    filter of the module docstring. Fewer when fewer edges pass."""

    allocated = set(parse_allocated_from_xml(xml_text))
    out: list[Bundle] = []
    for edge in _sorted_edges(graph_json_path):
        ends = (edge["from"], edge["to"])
        if ends[0] == ends[1] or not all(_free_tree_node(graph.node(e), allocated, tree_allocatable) for e in ends):
            continue
        bundle = tuple(sorted(ends))
        fit = check_bundle(bundle, graph, stand)
        if fit.fits:
            out.append(Bundle(ids=bundle, edge=edge, fit=fit))
            if len(out) == ACCEPTANCE_PER_STAND:
                break
    return out


def does_not_fit_probe(graph_json_path: Path | str, graph: BundleGraph, stand: Stand) -> Bundle | None:
    """The first edge (sorted by (from, to)) with an ascendancy end of another ascendancy than the stand's, as the
    bundle it makes; check_bundle rejects it, and its reason names the foreign ascendancy. None when no edge has one."""

    for edge in _sorted_edges(graph_json_path):
        ends = (edge["from"], edge["to"])
        if not any(_foreign_ascendancy(graph.node(e), stand) for e in ends):
            continue
        bundle = tuple(sorted(ends))
        fit = check_bundle(bundle, graph, stand)
        if not fit.fits:
            return Bundle(ids=bundle, edge=edge, fit=fit)
    return None


def unique_probe(graph_json_path: Path | str, xml_text: str, graph: BundleGraph, stand: Stand,
                 tree_allocatable: Collection[int]) -> Bundle | None:
    """The stand's unique probe: `first_unique_bundle` with the stand's allocated nodes read from its XML."""

    return first_unique_bundle(graph_json_path, graph, stand, parse_allocated_from_xml(xml_text), tree_allocatable)


def first_unique_bundle(graph_json_path: Path | str, graph: BundleGraph, stand: Stand, allocated: Collection[int],
                        tree_allocatable: Collection[int]) -> Bundle | None:
    """The first edge (sorted by (from, to)) with exactly one unique end and one notable / keystone end that is on the
    active tree and not allocated, whose bundle fits the stand. None when no edge does. The one rule of the unique
    probe (the rail tests of #1147 unit 4 use it too)."""

    allocated_set = {int(n) for n in allocated}
    for edge in _sorted_edges(graph_json_path):
        ends = (edge["from"], edge["to"])
        nodes = [graph.node(e) for e in ends]
        uniques = [n for n in nodes if n.surface == "unique"]
        trees = [n for n in nodes if n.surface in TREE_SURFACES]
        if len(uniques) != 1 or len(trees) != 1 or not _free_tree_node(trees[0], allocated_set, tree_allocatable):
            continue
        bundle = tuple(sorted(ends))
        fit = check_bundle(bundle, graph, stand)
        if fit.fits:
            return Bundle(ids=bundle, edge=edge, fit=fit)
    return None


def _sorted_edges(graph_json_path: Path | str) -> list[dict]:
    """The bundle graph's edges sorted by (from, to); a stable sort, so one file always gives one order."""

    edges = json.loads(Path(graph_json_path).read_text(encoding="utf-8"))["edges"]
    return sorted(edges, key=lambda e: (e["from"], e["to"]))


def _free_tree_node(node: BundleNode, allocated: Collection[int], tree_allocatable: Collection[int]) -> bool:
    """A notable or keystone on the active tree that the stand does not allocate."""

    return (node.surface in TREE_SURFACES and node.tree_id is not None
            and node.tree_id not in allocated and node.tree_id in tree_allocatable)


def _foreign_ascendancy(node: BundleNode, stand: Stand) -> bool:
    return node.surface == "ascendancy" and node.ascendancy != stand.ascendancy


__all__ = ["ACCEPTANCE_PER_STAND", "Bundle", "acceptance_bundles", "does_not_fit_probe", "first_unique_bundle",
           "stand_from_xml", "unique_probe"]
