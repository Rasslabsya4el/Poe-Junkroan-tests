"""The repair rule of a keystone choice (#1064, unit 1): the pure stop rule and the verdict.

A keystone a finished build is tested with (forced on, or taken away) is first repaired for at most
`REPAIR_MAX_PASSES` loop passes from that build. This module decides, from the objective values after each pass,
whether another pass runs and what the repair says: "climbing", "take" or "drop". It imports nothing from PoB.

The values are the objective (`Score.value`) after each pass run; the gain of a pass is its change over the value
before it (`step_gain`). A repair ends after the first pass whose gain is under `REPAIR_GAIN_FLOOR` (patience
`REPAIR_PATIENCE` = 1) or after `REPAIR_MAX_PASSES` passes; a pass that cleared a violation (it started infeasible and
ended feasible) is never counted as under the floor, because it spent itself making the build feasible again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

REPAIR_GAIN_FLOOR = 0.01  # 1 % per pass: the value after the pass over the value before it
REPAIR_MAX_PASSES = 2  # r: at most two passes per repair
REPAIR_PATIENCE = 1  # k: the first pass under the floor ends the repair

DIRECTIONS = ("force", "forbid")


@dataclass(frozen=True)
class RepairChoice:
    """One choice to repair: a keystone (its name) held in a direction, or (#1147) a bundle forced on.

    A bundle is a sorted, duplicate-free list of graph node ids of `bundle_graph_day1.json` ("notable:10016",
    "keystone:10661", "ascendancy:53123", "mastery:10141", later "unique:<name>"); it is held on only (`force`). A mastery
    node carries one effect per line, so `mastery_lines` names the line (the graph edge's own `from_line` / `to_line`) whose
    effect is taken, by graph id. A choice names a keystone or a bundle, never both."""

    keystone: str = ""
    direction: str = "force"  # "force" (held on) or "forbid" (held off)
    bundle: tuple[str, ...] = ()
    mastery_lines: Mapping[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(f"unknown repair direction {self.direction!r}; legal: {', '.join(DIRECTIONS)}")
        object.__setattr__(self, "bundle", tuple(self.bundle))
        if not self.bundle:
            if not self.keystone:
                raise ValueError("a repair choice names nothing: give a keystone or a bundle")
            return
        if self.keystone:
            raise ValueError("a repair choice names either a keystone or a bundle, not both")
        if self.direction != "force":
            raise ValueError("a bundle is only forced; the direction forbid takes a keystone")
        if list(self.bundle) != sorted(set(self.bundle)):
            raise ValueError(f"a bundle is a sorted list of distinct graph node ids, got {list(self.bundle)}")


def resolve_keystone_id(graph: Any, name: str) -> int:
    """The node id of the keystone `name` (case-insensitive) in `graph.nodes`; ValueError when no keystone has that name."""

    wanted = name.strip().lower()
    ids = sorted(node.node_id for node in graph.nodes.values() if node.kind == "keystone" and node.name.lower() == wanted)
    if not ids:
        raise ValueError(f"no keystone named {name!r} in the tree {getattr(graph, 'tree_version', '?')}")
    return ids[0]


def _surface_and_source(graph_id: str) -> tuple[str, str]:
    surface, sep, source = str(graph_id).partition(":")
    if not sep or not source:
        raise ValueError(f"{graph_id!r} is not a graph node id (<surface>:<source>)")
    return surface, source


def _tree_node(graph: Any, surface: str, source: str) -> Any:
    try:
        node = graph.nodes.get(int(source))
    except ValueError:
        node = None
    if node is None:
        raise ValueError(f"no {surface} with id {source!r} in the tree {getattr(graph, 'tree_version', '?')}")
    if node.node_id not in graph.allocatable:  # 330 of 784 graph notables and 9 of 57 keystones are not on the active tree: PoB does not know them
        raise ValueError(f"no {surface} with id {source!r} on the active tree {getattr(graph, 'tree_version', '?')} ({node.name} is in the corpus only)")
    return node


def resolve_part_id(graph: Any, graph_id: str, *, line: str | None = None, ascendancy: str | None = None) -> int:
    """The id `skeleton.forced_nodes` takes for one tree part of the bundle graph (#1147); ValueError when it is none.

    notable / keystone: the tree node id (the node must be of that kind in `graph`). ascendancy: the ascendancy node id;
    with `ascendancy` given, the node must belong to it (name or display name, case-insensitive) and not be its start.
    mastery: the id of the effect whose stats hold `line` exactly, because a mastery is forced by its effect; an effect
    id that is also a node id is refused, since `TreeGraph.resolve_forced` would read it as the node."""

    surface, source = _surface_and_source(graph_id)
    if surface in ("notable", "keystone"):
        node = _tree_node(graph, surface, source)
        if node.kind != surface:
            raise ValueError(f"node {source} ({node.name}) is a {node.kind}, not a {surface}")
        return node.node_id
    if surface == "mastery":
        node = _tree_node(graph, surface, source)
        if node.kind != "mastery":
            raise ValueError(f"node {source} ({node.name}) is a {node.kind}, not a mastery")
        if not line:
            raise ValueError(f"mastery {graph_id} ({node.name}) needs the line of the effect to take")
        effects = [effect for effect, stats in node.mastery_effects if line in stats]
        if not effects:
            raise ValueError(f"no effect of {graph_id} ({node.name}) has the line {line!r}")
        if len(effects) > 1:
            raise ValueError(f"the line {line!r} is in {len(effects)} effects of {graph_id} ({node.name}): {effects}")
        if effects[0] in graph.nodes:
            raise ValueError(f"the effect {effects[0]} of {graph_id} is also a node id; the forced ids cannot tell them apart")
        return effects[0]
    if surface == "ascendancy":
        from junkroan.optimizer.tree_graph import ascendancy_node_owners

        try:
            owner = ascendancy_node_owners().get(int(source))
        except ValueError:
            owner = None
        if owner is None:
            raise ValueError(f"no ascendancy node with id {source!r}")
        owner_id, owner_display, name, is_start = owner
        if is_start:
            raise ValueError(f"{graph_id} ({name}) is the start of {owner_id}, not a node to allocate")
        if ascendancy is not None and ascendancy.strip().lower() not in (owner_id.lower(), owner_display.lower()):
            raise ValueError(f"{graph_id} ({name}) belongs to {owner_id}, not to {ascendancy}")
        return int(source)
    raise ValueError(f"{graph_id}: a {surface} part cannot be forced as a tree part")


@dataclass(frozen=True)
class BundleParts:
    """A bundle split into what `_repair_force_bundle` holds: the ids for `skeleton.forced_nodes` in bundle order
    (a mastery by its effect id), which of them are ascendancy nodes, the keystone names (the skeleton may forbid
    one), the part names for the stage note, and (#1147 unit 4) the uniques as (slot, name without its base) in bundle
    order, each with the slot it is forced into."""

    forced_ids: tuple[int, ...]
    ascendancy_ids: frozenset[int]
    keystone_names: tuple[str, ...]
    label: str
    uniques: tuple[tuple[str, str], ...] = ()


def unique_slot(skeleton: Any, name: str, taken: Mapping[str, str] | None = None) -> str:
    """The slot the unique `name` is forced into on `skeleton` (#1147): a slot of its item type that the gear holds
    (`RARE_SLOTS`) and the search may put it in (`runner.unique_pick_ok`: not a slot the request fixed, a two-hander not
    over a fixed Weapon 2, no off-hand PoB refuses), not one in `taken` (slot -> name of the bundle's earlier uniques); a slot with a
    unique of the skeleton comes last. ValueError when there is none (the fit check of `bundle_fit` normally stops it)."""

    from junkroan.search.hypothesis import RARE_SLOTS, UNIQUE_TYPE_SLOTS, uniques_by_name
    from junkroan.search.runner import unique_pick_ok

    held = getattr(skeleton, "uniques", {}) or {}
    taken = dict(taken or {})
    types = sorted({rec["type"] for rec in uniques_by_name().get(name.lower(), [])})
    slots = [slot for item_type in types for slot in UNIQUE_TYPE_SLOTS.get(item_type, ()) if slot in RARE_SLOTS and slot not in taken]
    for slot in sorted(dict.fromkeys(slots), key=lambda s: s in held):
        if unique_pick_ok(skeleton, slot, name, taken):
            return slot
    raise ValueError(f"no slot for the unique {name!r} (types {types or 'unknown'}): every slot of its type is fixed by the request or taken")


def split_bundle(choice: RepairChoice, graph: Any, skeleton: Any) -> BundleParts:
    """THE seam where a bundle splits into its parts (#1147). Tree parts (notable, keystone, ascendancy, mastery) become
    forced node ids here; a unique part (`unique:<name>[, <base>]`) gets its slot (`unique_slot`) and is held in `uniques`."""

    from junkroan.optimizer.tree_graph import ascendancy_node_owners

    ascendancy = getattr(skeleton, "ascendancy", None)
    ids: list[int] = []
    asc: set[int] = set()
    keystones: list[str] = []
    names: list[str] = []
    uniques: list[tuple[str, str]] = []
    for part in choice.bundle:
        surface, source = _surface_and_source(part)
        if surface == "unique":
            name = source.split(", ")[0]
            uniques.append((unique_slot(skeleton, name, dict(uniques)), name))
            names.append(name)
            continue
        node_id = resolve_part_id(graph, part, line=choice.mastery_lines.get(part), ascendancy=ascendancy)
        ids.append(node_id)
        if surface == "ascendancy":
            asc.add(node_id)
            names.append(ascendancy_node_owners()[node_id][2])
            continue
        name = graph.nodes[int(source)].name
        names.append(name)
        if surface == "keystone":
            keystones.append(name)
    return BundleParts(forced_ids=tuple(ids), ascendancy_ids=frozenset(asc), keystone_names=tuple(keystones), label=" + ".join(names), uniques=tuple(uniques))


def step_gain(before: float, after: float) -> float:
    """The relative gain of one pass: (after - before) / before. A non-positive `before` gives 0.0."""

    if before <= 0:
        return 0.0
    return (after - before) / before


def repair_gains(start: float, values: list[float]) -> list[float]:
    """The gain of each pass run: pass 1 against `start`, pass 2 against pass 1's value."""

    gains: list[float] = []
    before = start
    for value in values:
        gains.append(step_gain(before, value))
        before = value
    return gains


def should_continue(gains: list[float], cleared: list[bool] | None = None) -> bool:
    """True when another repair pass should run after the passes whose gains are given.

    The repair ends once `REPAIR_PATIENCE` passes in a row gained less than `REPAIR_GAIN_FLOOR`, or once
    `REPAIR_MAX_PASSES` passes have run. With no pass run yet, the first pass always runs. `cleared` holds one flag per
    pass run: True when the pass started with a violation and ended without one; such a pass is not under the floor
    (#1064). `cleared=None` counts every pass by its gain alone."""

    if len(gains) >= REPAIR_MAX_PASSES:
        return False
    under = 0
    for index in range(len(gains) - 1, -1, -1):
        if gains[index] >= REPAIR_GAIN_FLOOR or (cleared is not None and cleared[index]):
            break
        under += 1
    return under < REPAIR_PATIENCE


def repair_verdict(start: float, values: list[float]) -> str:
    """"climbing" when two passes ran and pass 2 gained at least `REPAIR_GAIN_FLOOR` over pass 1; else "take" when
    the last value is at least `start`; else "drop". `values` holds the value after each pass run (1 or 2 entries)."""

    if len(values) not in (1, 2):
        raise ValueError(f"a repair runs one or two passes, got {len(values)} values")
    if len(values) == 2 and step_gain(values[0], values[1]) >= REPAIR_GAIN_FLOOR:
        return "climbing"
    return "take" if values[-1] >= start else "drop"


@dataclass
class RepairOutcome:
    """The result of one repair: the start value, the value after each pass run, the gain of each pass, the verdict
    and the seconds the repair took."""

    start: float
    values: list[float] = field(default_factory=list)
    gains: list[float] = field(default_factory=list)
    verdict: str = ""
    seconds: float = 0.0
