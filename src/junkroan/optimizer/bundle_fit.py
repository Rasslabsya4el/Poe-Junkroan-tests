"""The fit check of a bundle on a stand (#1147, unit 1): whether a set of bundle-graph parts can be forced onto a stand.

PoB-free: the check reads only the in-memory graph and the stand shape. It answers three questions, in the order of
the bundle's sorted ids, and returns the first one that fails:

- (a) an ascendancy node belongs to another ascendancy than the stand's;
- (c) a node is forbidden by the skeleton (a forbidden tree id, or a keystone the request forbids by name);
- (b) a unique has no slot the stand can free (its item type fits no slot the stand holds, or every such slot is
  fixed by a forced direction; a two-hander also needs Weapon 2 free).

Not decided here: gear_affix and flask parts (a later ticket) and joint conflicts between two uniques of one bundle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from junkroan.search.forced import forced_of
from junkroan.search.generator import TWO_HAND_TYPES
from junkroan.search.hypothesis import RARE_SLOTS, UNIQUE_TYPE_SLOTS, ascendancy, uniques_by_name
from junkroan.search.skeleton import Skeleton

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
GRAPH_PATH = CORPUS / "bundle_graph_day1.json"
PASSIVE_SURFACES = ("notable", "keystone", "mastery", "ascendancy")


@dataclass(frozen=True)
class BundleNode:
    """One part of the bundle graph: its id, surface, name, passive tree id (passive surfaces only), the PoB id of the
    ascendancy an ascendancy node belongs to, and the PoB item types of a unique."""

    id: str
    surface: str
    name: str
    tree_id: int | None
    ascendancy: str | None
    item_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class BundleGraph:
    nodes: Mapping[str, BundleNode]

    def node(self, node_id: str) -> BundleNode:
        if node_id not in self.nodes:
            raise ValueError(f"no bundle-graph node {node_id!r}")
        return self.nodes[node_id]


@dataclass(frozen=True)
class Stand:
    """What the fit check needs of a stand: its ascendancy (PoB id, lower case), the slots it holds, the slots a forced
    direction fixes (they cannot be freed), the forbidden tree ids and the forbidden keystone names (lower case)."""

    ascendancy: str | None
    equipped_slots: frozenset[str]
    fixed_slots: frozenset[str] = frozenset()
    forbidden_nodes: frozenset[int] = frozenset()
    forbidden_keystones: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BundleFit:
    fits: bool
    reason: str

    @property
    def verdict(self) -> str:
        return "fits" if self.fits else "does_not_fit"


def check_bundle(bundle_ids: Iterable[str], graph: BundleGraph, stand: Stand) -> BundleFit:
    """Whether the bundle `bundle_ids` (graph node ids) can be forced onto `stand`. No PoB call. The ids are read in
    sorted order, so the same bundle gives the same verdict in any order; the reason names the first offending id."""

    ids = sorted(set(bundle_ids))
    if not ids:
        raise ValueError("an empty bundle has no fit to check")
    for node_id in ids:
        node = graph.node(node_id)
        if node.surface == "ascendancy" and node.ascendancy != stand.ascendancy:
            return BundleFit(False, f"{node_id}: ascendancy node of {node.ascendancy!r}, the stand is {stand.ascendancy!r}")
        if node.tree_id is not None and node.tree_id in stand.forbidden_nodes:
            return BundleFit(False, f"{node_id}: tree node {node.tree_id} is forbidden on the stand")
        if node.surface == "keystone" and node.name.lower() in stand.forbidden_keystones:
            return BundleFit(False, f"{node_id}: keystone {node.name!r} is forbidden on the stand")
        if node.surface == "unique":
            free = _free_slot(node, stand)
            if free is None:
                return BundleFit(False, f"{node_id}: no slot the stand can free for {', '.join(node.item_types) or 'a unique with no record'}")
    return BundleFit(True, "fits")


def _free_slot(node: BundleNode, stand: Stand) -> str | None:
    """The first slot of the unique's type the stand holds and no forced direction fixes; a two-hander also needs
    Weapon 2 free (it occupies both hands). None when no type of the unique has such a slot."""

    for item_type in node.item_types:
        slots = UNIQUE_TYPE_SLOTS.get(item_type, ())
        if item_type in TWO_HAND_TYPES and "Weapon 2" in stand.fixed_slots:
            continue
        for slot in slots:
            if slot in stand.equipped_slots and slot not in stand.fixed_slots:
                return slot
    return None


def load_bundle_graph(path: Path = GRAPH_PATH) -> BundleGraph:
    """The day-1 bundle graph from its corpus file, with each ascendancy node's ascendancy (from `ascendancies.json`)
    and each unique's item types (from the uniques corpus). PoB-free."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    owner = _ascendancy_of_tree_id()
    types = uniques_by_name()
    nodes: dict[str, BundleNode] = {}
    for row in raw["nodes"]:
        surface = row["surface"]
        tree_id = int(row["source"]) if surface in PASSIVE_SURFACES and str(row["source"]).isdigit() else None
        owned = owner.get(tree_id) if surface == "ascendancy" and tree_id is not None else None
        item_types: tuple[str, ...] = ()
        if surface == "unique":
            plain = row["name"].split(", ")[0].lower()
            item_types = tuple(sorted({rec["type"] for rec in types.get(plain, [])}))
        nodes[row["id"]] = BundleNode(id=row["id"], surface=surface, name=row["name"], tree_id=tree_id,
                                      ascendancy=owned.lower() if owned else None, item_types=item_types)
    return BundleGraph(nodes=nodes)


def _ascendancy_of_tree_id() -> dict[int, str]:
    records = json.loads((CORPUS / "ascendancies.json").read_text(encoding="utf-8"))["records"]
    return {int(node["node_id"]): record["ascendancy_id"] for record in records for node in record["nodes"]}


def stand_from_skeleton(skeleton: Skeleton, *, equipped_slots: Sequence[str] = RARE_SLOTS,
                        forbidden_nodes: Iterable[int] = ()) -> Stand:
    """The stand a finished skeleton describes: its ascendancy as a PoB id, its forced slots (uniques, bases, affix
    slots) as fixed, the request's forbidden keystones by name. A parsed skeleton, no PoB. The equipped slots default
    to the rare slots of a full gear set (no XML parser of the stand's items exists yet)."""

    forced = forced_of(skeleton)
    fixed = set(forced["uniques"]) | set(forced["bases"]) | set(forced["affixes"])
    pob_ascendancy = ascendancy(skeleton.ascendancy)
    owner = pob_ascendancy["ascendancy_id"] if pob_ascendancy else skeleton.ascendancy
    return Stand(
        ascendancy=owner.lower() if owner else None,
        equipped_slots=frozenset(equipped_slots),
        fixed_slots=frozenset(fixed),
        forbidden_nodes=frozenset(int(n) for n in forbidden_nodes),
        forbidden_keystones=frozenset(k.lower() for k in skeleton.forbid_keystones),
    )
