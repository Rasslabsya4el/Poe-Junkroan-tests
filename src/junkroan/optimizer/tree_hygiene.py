"""Measured explanations and audit data for allocated passive-tree leaves.

The optimizer deliberately judges tree moves with config frozen. A finished-build
reader needs one extra check: an otherwise inert leaf can be the proof for a
conservative config input. This module keeps that slow, real removal separate
from the one batched frozen-config measurement used for every leaf.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from xml.etree import ElementTree as ET

from junkroan.optimizer.judging import read_lanes, write_lanes_preserving_numbers
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import CORPUS_ROOT, TreeGraph
from junkroan.optimizer.trace import TRACE, register_class


LEAF_KEYS = (
    "CombinedDPS", "FullDPS", "Life", "EnergyShield", "Mana", "ManaUnreserved", "LifeUnreserved", "TotalEHP",
    "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken", "ChaosMaximumHitTaken",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist", "EffectiveMovementSpeedMod", "Str", "Dex", "Int",
    "LifeRegenRecovery", "ManaRegenRecovery", "NetLifeRegen", "LifeLeechGainRate", "ManaPerSecondCost", "LifePerSecondCost",
    "ReqStr", "ReqDex", "ReqInt", "Speed", "HitChance",
)
_WEAK_DEFENCE_KEYS = (
    "Life", "EnergyShield", "TotalEHP", "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
    "LightningMaximumHitTaken", "ChaosMaximumHitTaken", "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "EffectiveMovementSpeedMod", "ManaUnreserved", "LifeRegenRecovery", "ManaRegenRecovery", "NetLifeRegen", "Str", "Dex", "Int",
)
_VALUE_EPSILON = 0.0005
_WEAK_DPS = 0.002
_WEAK_DEFENCE = 0.005
_MASTERY_COUNT_TEXT = re.compile(r"\b(?:for each|per)\b.*\b(?:different )?(?:types? of )?master(?:y|ies)\b", re.IGNORECASE)
_TREE_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "pob" / "source" / "src" / "TreeData"


@dataclass(slots=True)
class TreeLeaf:
    node_id: int
    name: str
    kind: str
    stats: tuple[str, ...]
    judged_stat: str = "CombinedDPS"
    changes: dict[str, float] = field(default_factory=dict)  # signed percentage after removal
    judged_change: float = 0.0  # signed percentage after removal
    floor_breaks: tuple[str, ...] = ()
    status: str = "live"  # live | weak | dead | proof | travel
    proof_inputs: tuple[str, ...] = ()
    reason: str = ""

    @property
    def judged_cost(self) -> float:
        """Positive means removing the node lowers the objective stat."""

        return -self.judged_change


def stat_keys(objective: Objective | None) -> tuple[str, ...]:
    """The objective's keys plus the fixed reader-facing safety context.

    Older callers did not carry an objective. In that case this is exactly the
    measured key list from the original dead-node report.
    """

    own = tuple(objective.stat_keys) if objective is not None else ()
    return tuple(dict.fromkeys((*own, *LEAF_KEYS)))


def _protected_ids(pob: Any, graph: TreeGraph, protected: Iterable[int] | None) -> frozenset[int]:
    """Nodes no trial of this module may remove (#510): the caller's set, else the forced nodes of the
    build being searched (`TRACE.forced()`), a forced mastery effect read as the mastery node carrying it."""

    if protected is not None:
        return frozenset(int(n) for n in protected)
    forced = (TRACE.forced() or {}).get("nodes") or ()
    return graph.protected_nodes(forced, selected_masteries(pob, graph)) if forced else frozenset()


def analyze_tree_leaves(pob: Any, *, objective: Objective | None = None, rederive_proofs: bool = True,
                        mastery_context: bool = False, protected: Iterable[int] | None = None,
                        links: Mapping[int, frozenset[int]] | None = None) -> list[TreeLeaf]:
    """Measure every removable leaf once, then verify tentative leftovers.

    ``trial_stats`` keeps the tree and config untouched for the main batch and does
    not cascade, so a bridge node can look inert there. Only dead/weak candidates
    get a real removal (which cascades the way PoB's own removal does) followed by
    ``derive_config``; that is what distinguishes a genuine dead leaf from a proof
    holder, a travel node, or a node the frozen batch mis-measured.
    """

    graph = TreeGraph.load()
    tree = pob.tree_light()
    allocated = {int(n) for n in tree.get("user_allocated_node_ids") or ()}
    start = graph.class_starts.get(str(tree.get("class_id") or ""))
    if start is not None:
        allocated.add(start)
    protect = _protected_ids(pob, graph, protected)
    leaves = [node_id for node_id in graph.removable_leaves(allocated, protected=protect, links=links) if node_id in graph.allocatable]
    if not leaves:
        return []

    keys = stat_keys(objective)
    base = pob.stats(keys)
    judged = _judged_key(base, objective)
    removal_ids = tuple(leaves)
    hyg_trials = [{"remove": [node_id]} for node_id in removal_ids]
    TRACE.count_candidates(hyg_trials)
    outcomes = pob.trial_stats(hyg_trials, keys, mode="fast")
    removal_stats = {node_id: _trial_values(outcome) for node_id, outcome in zip(removal_ids, outcomes)}
    rows: list[TreeLeaf] = []
    for node_id in leaves:
        trial = removal_stats[node_id]
        node = graph.node(node_id)
        changes = {
            key: _signed_change(base.get(key), trial.get(key))
            for key in keys
            if _changed(base.get(key), trial.get(key))
        }
        judged_change = _signed_change(base.get(judged), trial.get(judged))
        floor_breaks = _new_floor_breaks(base, trial, objective)
        weak = (
            bool(changes)
            and abs(judged_change) < _WEAK_DPS
            and max((abs(changes.get(key, 0.0)) for key in _WEAK_DEFENCE_KEYS), default=0.0) < _WEAK_DEFENCE
            and not _mana_broke(base, trial, objective)
        )
        rows.append(TreeLeaf(
            node_id=node_id,
            name=node.name if node else str(node_id),
            kind=node.kind if node else "unknown",
            stats=_selected_stats(node_id, node, tree),
            judged_stat=judged,
            changes=changes,
            judged_change=judged_change,
            floor_breaks=floor_breaks,
            status="dead" if not changes else "weak" if weak else "live",
        ))

    if mastery_context:
        _mastery_type_reasons(rows, pob, graph, base, objective, protect)
    if rederive_proofs and callable(getattr(pob, "mutate_nodes", None)):
        before_lane: tuple | None = None
        for row in rows:
            if row.status in {"dead", "weak"}:
                if before_lane is None:
                    before_lane = _lane_fingerprint(_derive_config(pob))
                _check_config_proof(pob, row, base, keys, objective, graph=graph, before_lane=before_lane)
    return sorted(rows, key=lambda row: (row.judged_cost, row.name.lower(), row.node_id))


def audit_findings(rows: Sequence[TreeLeaf], *, objective: Objective | None = None) -> list[tuple[str, str]]:
    """``(severity, detail)`` records for the audit without importing audit.py.

    Keeping the finding construction at the integration boundary avoids an
    audit/tree-hygiene import cycle.
    """

    judged = objective.maximize if objective is not None else (rows[0].judged_stat if rows else "CombinedDPS")
    out: list[tuple[str, str]] = []
    for row in rows:
        if row.status == "dead":
            out.append(("error", f"{row.name} (node {row.node_id}) moves none of the objective or floor stats when removed"))
        elif row.status == "weak":
            moved = _format_changes(row.changes)
            out.append(("warning", f"{row.name} (node {row.node_id}) costs {row.judged_cost:+.2%} {judged} when removed; moves {moved}"))
    return out


DEAD_ASCENDANCY_SHARE = 0.001  # 0.1 %: under it on both the objective and TotalEHP, an ascendancy node is dead (#1157)


@lru_cache(maxsize=1)
def ascendancy_node_names() -> dict[int, str]:
    """Every ascendancy node by id, start nodes excluded (#1157). They sit in the ascendancy corpus, not in
    TreeGraph (the same reason audit.py and config_rules.py read the file): TreeGraph omits them."""

    recs = json.loads((CORPUS_ROOT / "ascendancies.json").read_text(encoding="utf-8"))["records"]
    return {
        int(n["node_id"]): str(n.get("name") or "")
        for r in recs for n in (r.get("nodes") or [])
        if not n.get("is_ascendancy_start")
    }


@dataclass(frozen=True, slots=True)
class AscendancyRemoval:
    """What PoB's own removal of one allocated ascendancy node moves; changes are signed fractions."""

    node_id: int
    name: str
    judged_stat: str
    judged_change: float
    ehp_change: float

    @property
    def dead(self) -> bool:
        return abs(self.judged_change) < DEAD_ASCENDANCY_SHARE and abs(self.ehp_change) < DEAD_ASCENDANCY_SHARE


def _allocated_ascendancy_ids(pob: Any) -> list[int]:
    names = ascendancy_node_names()
    allocated = {int(n) for n in pob.tree_light().get("user_allocated_node_ids") or ()}
    return sorted(n for n in allocated if n in names)


def ascendancy_removals(pob: Any, *, objective: Objective | None = None) -> list[AscendancyRemoval]:
    """Removal value of every allocated ascendancy node, one full trial each (#1157).

    Full mode, not the frozen fast batch: a real removal cascades to the nodes it holds up, as PoB does
    when the build is played. The ascendancy start is never in `user_allocated_node_ids`, so it is not measured.
    """

    return _measure_ascendancy(pob, _allocated_ascendancy_ids(pob), objective)


def _measure_ascendancy(pob: Any, asc_ids: list[int], objective: Objective | None) -> list[AscendancyRemoval]:
    names = ascendancy_node_names()
    if not asc_ids:
        return []
    keys = stat_keys(objective)
    base = pob.stats(keys)
    judged = _judged_key(base, objective)
    outcomes = pob.trial_stats([{"remove": [node_id]} for node_id in asc_ids], keys, mode="full")
    rows: list[AscendancyRemoval] = []
    for node_id, outcome in zip(asc_ids, outcomes):
        if isinstance(outcome, Mapping) and outcome.get("ok") is False:
            raise RuntimeError(f"PoB could not remove ascendancy node {node_id}: {outcome.get('error')}")
        trial = _trial_values(outcome)
        rows.append(AscendancyRemoval(
            node_id=node_id,
            name=names[node_id],
            judged_stat=judged,
            judged_change=_signed_change(base.get(judged), trial.get(judged)),
            ehp_change=_signed_change(base.get("TotalEHP"), trial.get("TotalEHP")),
        ))
    return rows


def dead_ascendancy_nodes(pob: Any, *, objective: Objective | None = None, points_budget: int) -> list[AscendancyRemoval]:
    """Allocated ascendancy nodes under 0.1 % on both the objective and TotalEHP (#1157).

    Reported only once the build has spent its `points_budget` ascendancy points. Below that the function
    returns [] before any trial runs (the full removals are not free); `ascendancy_removals` gives the values.
    """

    asc_ids = _allocated_ascendancy_ids(pob)
    if len(asc_ids) < points_budget:
        return []
    return [row for row in _measure_ascendancy(pob, asc_ids, objective) if row.dead]


@lru_cache(maxsize=1)
def _ascendancy_records() -> tuple[dict, ...]:
    return tuple(json.loads((CORPUS_ROOT / "ascendancies.json").read_text(encoding="utf-8"))["records"])


def ascendancy_swap_candidates(dead_node_id: int, allocated: Iterable[int]) -> list[int]:
    """The nodes the `ascendancy-swap` move tries in place of a dead ascendancy node (#1157): the ascendancy's own
    picks (`generator._ascendancy_picks`, the nodes the pick greedy may stop on) that are not allocated yet. The path
    to a pick is PoB's: the trial allocates it. Empty when the node is in no ascendancy."""

    from junkroan.search.generator import _ascendancy_picks  # lazy: the generator imports the optimizer

    record = next((r for r in _ascendancy_records() if any(int(n["node_id"]) == int(dead_node_id) for n in r.get("nodes") or ())), None)
    if record is None:
        return []
    nodes = {int(n["node_id"]): n for n in record["nodes"]}
    adjacency: dict[int, set[int]] = {}
    for node_id, node in nodes.items():
        for other in (*(node.get("incoming_node_ids") or ()), *(node.get("outgoing_node_ids") or ())):
            if int(other) in nodes:
                adjacency.setdefault(node_id, set()).add(int(other))
                adjacency.setdefault(int(other), set()).add(node_id)
    taken = {int(n) for n in allocated} | {int(dead_node_id)}
    return sorted(_ascendancy_picks(nodes, adjacency) - taken)


ASCENDANCY_SWAP_CLASS = "ascendancy-swap"


def _ascendancy_swap_class(trial: dict) -> Iterable[str]:
    """The trace class of an `ascendancy-swap` trial: one whose `add` holds an ascendancy node (#1157). The audit's own
    removal trials only remove, so they are not counted as swaps."""

    names = ascendancy_node_names()
    added = trial.get("add") if isinstance(trial, dict) else None
    if isinstance(added, (list, tuple, set, frozenset)) and any(int(n) in names for n in added):
        return (ASCENDANCY_SWAP_CLASS,)
    return ()


register_class(_ascendancy_swap_class)


def render_tree_leaf_table(rows: Sequence[TreeLeaf], *, objective: Objective | None = None) -> str:
    """Markdown table for a reader inspecting the thin end of the tree first."""

    judged = objective.maximize if objective is not None else (rows[0].judged_stat if rows else "CombinedDPS")
    lines = [
        f"Tree leaf removals, weakest first (`trial_stats`; PoB's node tooltip can show a smaller FullDPS percentage because it recomputes only the main skill):",
        f"| Leaf | Removing it: {judged} | Life | EHP | Floors / proof |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        life = _format_percent(row.changes.get("Life"))
        ehp = _format_percent(row.changes.get("TotalEHP"))
        held: list[str] = list(row.floor_breaks)
        if row.proof_inputs:
            held.append("holds the proof of " + ", ".join(row.proof_inputs))
        if row.reason:
            held.append(row.reason)
        if not held:
            held.append(row.status)
        lines.append(
            f"| {row.name} ({row.kind}) | {_format_percent(row.judged_change)} | {life} | {ehp} | {'; '.join(held)} |"
        )
    return "\n".join(lines)


def selected_masteries(pob: Any, graph: TreeGraph | None = None) -> dict[int, int]:
    """The selected effect on each allocated mastery node."""

    out: dict[int, int] = {}
    for entry in pob.tree_light().get("mastery_effect_ids") or ():
        node, sep, effect = str(entry).partition(":")
        if sep and node.isdigit() and effect.isdigit():
            out[int(node)] = int(effect)
    return out


def mastery_effect_tie_rows(pob: Any, *, objective: Objective | None = None, protected: Iterable[int] | None = None) -> list[dict[str, Any]]:
    """Report mastery effects that look like pure type-count tie-breaks.

    The selected effect is called zero-contribution only when every allocated
    mastery has the same removal cost and an allocated source explicitly scales
    with mastery count/type. Alternative effects are then tried in one batch per
    mastery, without changing any optimizer choice.
    """

    graph = TreeGraph.load()
    protect = _protected_ids(pob, graph, protected)
    selected = {n: e for n, e in selected_masteries(pob, graph).items() if n not in protect}
    if not selected:
        return []
    keys = stat_keys(objective)
    base = pob.stats(keys)
    judged = _judged_key(base, objective)
    ids = sorted(selected)
    hyg_trials = [{"remove": [node_id]} for node_id in ids]
    TRACE.count_candidates(hyg_trials)
    removals = pob.trial_stats(hyg_trials, keys, mode="fast")
    costs = {node_id: _signed_change(base.get(judged), _trial_values(outcome).get(judged)) for node_id, outcome in zip(ids, removals)}
    reason = _mastery_count_source(pob, graph)
    shared_cost = rounded_mode(costs.values()) if reason else 0.0
    snapshot = pob.export_xml()
    rows: list[dict[str, Any]] = []
    used_effects = set(selected.values())
    defence_keys = ("Life", "EnergyShield", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist")
    try:
        for node_id, effect_id in selected.items():
            cost = costs[node_id]
            node = graph.node(node_id)
            alternatives = [
                effect for effect, _stats in (node.mastery_effects if node else ())
                if effect != effect_id and effect not in used_effects
            ]
            if not alternatives:
                continue
            raises = []
            for effect in alternatives:
                pob.load_xml(_xml_with_mastery_effect(snapshot, node_id, effect_id, effect))
                trial = pob.stats(keys)
                gains = {key: _signed_change(base.get(key), trial.get(key)) for key in defence_keys if _signed_change(base.get(key), trial.get(key)) > _VALUE_EPSILON}
                if gains:
                    raises.append({"effect_id": effect, "gains": gains})
            removed = _trial_values(removals[ids.index(node_id)])
            selected_defence = any(abs(_signed_change(base.get(key), removed.get(key))) > _VALUE_EPSILON for key in defence_keys)
            zero_effect = not selected_defence and (abs(cost - shared_cost) <= _VALUE_EPSILON if reason else abs(cost) <= _VALUE_EPSILON)
            if zero_effect and raises:
                rows.append({
                    "node_id": node_id,
                    "name": node.name if node else str(node_id),
                    "selected_effect": effect_id,
                    "removal_change": cost,
                    "reason": reason or "selected effect moves no measured stat",
                    "raises": raises,
                })
    finally:
        pob.load_xml(snapshot)
    return rows


def _trial_values(outcome: Any) -> Mapping[str, Any]:
    return outcome.get("stats") if isinstance(outcome, Mapping) and isinstance(outcome.get("stats"), Mapping) else outcome if isinstance(outcome, Mapping) else {}


def _relative(before: Any, after: Any) -> float:
    if not isinstance(before, (int, float)) or isinstance(before, bool) or not isinstance(after, (int, float)) or isinstance(after, bool):
        return 0.0
    return abs(float(after) - float(before)) / max(abs(float(before)), 1e-9)


def _signed_change(before: Any, after: Any) -> float:
    if not isinstance(before, (int, float)) or isinstance(before, bool) or not isinstance(after, (int, float)) or isinstance(after, bool):
        return 0.0
    return (float(after) - float(before)) / max(abs(float(before)), 1e-9)


def _changed(before: Any, after: Any) -> bool:
    return _relative(before, after) > _VALUE_EPSILON


def _judged_key(stats: Mapping[str, Any], objective: Objective | None) -> str:
    if objective is None:
        return "FullDPS" if float(stats.get("FullDPS") or 0.0) > float(stats.get("CombinedDPS") or 0.0) else "CombinedDPS"
    key = objective.maximize
    if isinstance(stats.get(key), (int, float)) and float(stats.get(key) or 0.0) != 0.0:
        return key
    return "FullDPS" if float(stats.get("FullDPS") or 0.0) > float(stats.get("CombinedDPS") or 0.0) else "CombinedDPS"


def _new_floor_breaks(base: Mapping[str, Any], trial: Mapping[str, Any], objective: Objective | None) -> tuple[str, ...]:
    if objective is None:
        return ()
    before = set(objective.violations(_with_derived(base, objective)))
    after = objective.violations(_with_derived(trial, objective))
    return tuple(sorted(key for key in after if key not in before))


def _mana_broke(base: Mapping[str, Any], trial: Mapping[str, Any], objective: Objective | None) -> bool:
    if objective is None:
        return False
    before = objective.violations(_with_derived(base, objective))
    after = objective.violations(_with_derived(trial, objective))
    return any("Mana" in key and key not in before for key in after)


def _with_derived(stats: Mapping[str, Any], objective: Objective) -> Mapping[str, Any]:
    return {**stats, **objective.derived_values(stats)} if objective.derived else stats


def _selected_stats(node_id: int, node: Any, tree: Mapping[str, Any]) -> tuple[str, ...]:
    if node is None:
        return ()
    if node.kind != "mastery":
        return tuple(node.stats)
    selected = {
        int(raw.split(":", 1)[0]): int(raw.split(":", 1)[1])
        for raw in tree.get("mastery_effect_ids") or ()
        if ":" in str(raw) and all(part.isdigit() for part in str(raw).split(":", 1))
    }
    effect = selected.get(node_id)
    return next((tuple(stats) for effect_id, stats in node.mastery_effects if effect_id == effect), ())


def _check_config_proof(pob: Any, row: TreeLeaf, base: Mapping[str, Any], keys: Sequence[str], objective: Objective | None,
                        *, graph: TreeGraph | None = None, before_lane: tuple | None = None) -> None:
    """Judge a possibly dead leaf by a real removal, the way the tree moves do.

    ``trial_stats`` fast mode does not cascade, so a bridge node measures as inert
    there while PoB's own removal drops everything it connects. A real removal is
    the judge: a change under the frozen config makes the node a travel node (when
    other allocated nodes came with it) or a plain live node; a change only after
    ``derive_config`` makes it the proof holder of the lane the pipeline stands on.
    """

    snapshot = pob.export_xml()
    before_inputs = dict(pob.config_inputs()) if callable(getattr(pob, "config_inputs", None)) else {}
    before_allocated = _allocated_ids(pob)
    judged = _judged_key(base, objective)
    try:
        if before_lane is None:
            before_lane = _lane_fingerprint(_derive_config(pob))
        pob.mutate_nodes(remove=[row.node_id])
        cascade = sorted(before_allocated - _allocated_ids(pob) - {row.node_id})
        frozen = pob.stats(keys)
        derived = _derive_config(pob)
        write_lanes_preserving_numbers(pob, derived)  # the second lane writer (judging.py, #35 Q12)
        after = pob.stats(keys)
        input_changes = _lost_proof_inputs(before_inputs, pob.config_inputs() if callable(getattr(pob, "config_inputs", None)) else {})
        floor_breaks = _new_floor_breaks(base, after, objective)
        frozen_breaks = _new_floor_breaks(base, frozen, objective)
        if row.status == "dead" and (_changed(base.get(judged), frozen.get(judged)) or frozen_breaks):
            row.status = "travel" if cascade else "live"
            row.judged_change = _signed_change(base.get(judged), frozen.get(judged))
            row.changes = {key: _signed_change(base.get(key), frozen.get(key)) for key in keys if _changed(base.get(key), frozen.get(key))}
            row.floor_breaks = tuple(sorted(set((*row.floor_breaks, *frozen_breaks))))
            if cascade:
                row.reason = f"travel node: its removal disconnects {len(cascade)} allocated node(s): {_node_names(graph, cascade)}"
            else:
                row.reason = "live: the frozen trial batch did not cascade this removal; PoB's real removal costs the build"
        elif row.status == "dead" and _lane_fingerprint(derived) != before_lane and (_changed(base.get(judged), after.get(judged)) or floor_breaks):
            row.status = "proof"
            row.proof_inputs = tuple(input_changes) or ("re-derived lane",)
            row.judged_change = _signed_change(base.get(judged), after.get(judged))
            row.changes = {key: _signed_change(base.get(key), after.get(key)) for key in keys if _changed(base.get(key), after.get(key))}
            row.floor_breaks = tuple(sorted(set((*row.floor_breaks, *floor_breaks))))
        elif input_changes and (_changed(base.get(judged), after.get(judged)) or floor_breaks):
            row.status = "proof"
            row.proof_inputs = tuple(input_changes)
            row.floor_breaks = tuple(sorted(set((*row.floor_breaks, *floor_breaks))))
    finally:
        pob.load_xml(snapshot)


def _derive_config(pob: Any) -> Any:
    return read_lanes(pob)  # `derive_config(pob, prefer_rules=True)`, imported lazily there too


def _lane_fingerprint(derived: Any) -> tuple:
    """The conservative lane the pipeline would write: inputs and the custom-mod block."""

    return (
        tuple(sorted(derived.conservative.inputs.items())),
        tuple(sorted(derived.optimistic.inputs.items())),
        tuple(derived.custom_mods or ()),
    )


def _allocated_ids(pob: Any) -> set[int]:
    return {int(node_id) for node_id in (pob.tree_light().get("user_allocated_node_ids") or ()) if str(node_id).isdigit()}


def _node_names(graph: TreeGraph | None, node_ids: Sequence[int]) -> str:
    names = []
    for node_id in node_ids:
        node = graph.node(node_id) if graph is not None else None
        names.append(node.name if node is not None else str(node_id))
    return ", ".join(names)


def _lost_proof_inputs(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Inputs a leaf can actually prove.

    Re-derived numeric estimates (poison stacks, for example) can move after
    any stat change, but they do not establish that the node is a source. A
    conservative boolean that turns off is the direct proof-holder signal.
    """

    return sorted(key for key, value in before.items() if value is True and after.get(key) is not True)


def _mastery_type_reasons(rows: list[TreeLeaf], pob: Any, graph: TreeGraph, base: Mapping[str, Any], objective: Objective | None,
                          protect: frozenset[int] = frozenset()) -> None:
    masteries = [row for row in rows if row.kind == "mastery"]
    selected = {n: e for n, e in selected_masteries(pob, graph).items() if n not in protect}
    if not masteries or len(selected) < 2:
        return
    judged = _judged_key(base, objective)
    hyg_trials = [{"remove": [node_id]} for node_id in selected]
    TRACE.count_candidates(hyg_trials)
    outcomes = pob.trial_stats(hyg_trials, (judged,), mode="fast")
    changes = [_signed_change(base.get(judged), _trial_values(outcome).get(judged)) for outcome in outcomes]
    shared = rounded_mode(changes)
    if sum(abs(change - shared) <= _VALUE_EPSILON for change in changes) < 2:
        return
    reason = _mastery_count_source(pob, graph)
    if reason:
        for row in masteries:
            if abs(row.judged_change - shared) <= _VALUE_EPSILON:
                row.reason = reason


def rounded_mode(values: Iterable[float]) -> float:
    """The repeated leaf cost, rounded only to the trial-change tolerance."""

    buckets = Counter(round(float(value) / _VALUE_EPSILON) for value in values)
    return buckets.most_common(1)[0][0] * _VALUE_EPSILON if buckets else 0.0


def _mastery_count_source(pob: Any, graph: TreeGraph) -> str:
    for source, line in _allocated_source_lines(pob, graph):
        if _MASTERY_COUNT_TEXT.search(line):
            return f"mastery-type count: {source}: {line}"
    return ""


def _allocated_source_lines(pob: Any, graph: TreeGraph) -> Iterable[tuple[str, str]]:
    tree = pob.tree_light()
    version = str(tree.get("tree_version") or "")
    state = pob.read_state()
    tree_state = state.get("tree_state") or {}
    xml = pob.export_xml()
    node_ids = _xml_node_ids(xml)
    node_ids.update(int(node_id) for node_id in tree.get("user_allocated_node_ids") or () if str(node_id).isdigit())
    node_ids.update(int(node_id) for node_id in tree_state.get("allocated_ascendancy_node_ids") or () if str(node_id).isdigit())
    for node_id in node_ids:
        name, stats = _versioned_node(node_id, version)
        node = graph.node(node_id)
        for line in stats or (node.stats if node else ()):
            yield (name or (node.name if node else str(node_id)), line)
    for slot, lines in _item_lines(xml):
        for line in lines:
            yield (slot, line)


@lru_cache(maxsize=512)
def _versioned_node(node_id: int, version: str) -> tuple[str, tuple[str, ...]]:
    path = _TREE_ROOT / version / "tree.lua"
    if not version or not path.is_file():
        return "", ()
    text = _tree_text(version)
    start = re.search(rf"^\s*\[{node_id}\]\s*=\s*\{{", text, re.MULTILINE)
    if start is None:
        return "", ()
    following = re.search(r"^\s*\[\d+\]\s*=\s*\{", text[start.end():], re.MULTILINE)
    block = text[start.end(): start.end() + following.start()] if following is not None else text[start.end():]
    name = _lua_string(re.search(r'\["name"\]\s*=\s*"((?:\\.|[^"])*)"', block))
    match = re.search(r'\["stats"\]\s*=\s*\{(?P<stats>.*?)^\s*\},', block, re.DOTALL | re.MULTILINE)
    stats = tuple(_lua_string(value) for value in re.findall(r'"((?:\\.|[^"])*)"', match.group("stats"))) if match else ()
    return name, stats


@lru_cache(maxsize=8)
def _tree_text(version: str) -> str:
    return (_TREE_ROOT / version / "tree.lua").read_text(encoding="utf-8")


def _lua_string(match_or_value: Any) -> str:
    value = match_or_value.group(1) if hasattr(match_or_value, "group") else str(match_or_value)
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def _item_lines(xml: str) -> Iterable[tuple[str, tuple[str, ...]]]:
    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return ()
    by_id = {item.get("id"): item for item in items.findall("Item")}
    item_set = next((item_set for item_set in items.findall("ItemSet") if item_set.get("id") == (items.get("activeItemSet") or "1")), None)
    result = []
    for slot in item_set.findall("Slot") if item_set is not None else items.findall("Slot"):
        item = by_id.get(slot.get("itemId") or "")
        if item is not None:
            result.append((slot.get("name") or "item", tuple(line.strip() for line in (item.text or "").splitlines() if line.strip())))
    return result


def _xml_node_ids(xml: str) -> set[int]:
    root = ET.fromstring(xml)
    tree = root.find("Tree")
    if tree is None:
        return set()
    active = int(tree.get("activeSpec") or 1)
    specs = tree.findall("Spec")
    spec = specs[active - 1] if 0 < active <= len(specs) else (specs[0] if specs else None)
    return {int(node_id) for node_id in (spec.get("nodes") or "").split(",") if node_id.strip().isdigit()} if spec is not None else set()


def _xml_with_mastery_effect(xml: str, node_id: int, current_effect: int, new_effect: int) -> str:
    old, new = f"{{{node_id},{current_effect}}}", f"{{{node_id},{new_effect}}}"
    if old not in xml:
        raise ValueError(f"mastery {node_id}:{current_effect} is not selected in the active PoB XML")
    return xml.replace(old, new, 1)


def _format_percent(value: float | None) -> str:
    return "-" if value is None or abs(value) <= _VALUE_EPSILON else f"{value:+.2%}"


def _format_changes(changes: Mapping[str, float]) -> str:
    return ", ".join(f"{key} {_format_percent(value)}" for key, value in changes.items()) or "nothing"


__all__ = ["AscendancyRemoval", "LEAF_KEYS", "TreeLeaf", "ascendancy_node_names", "ascendancy_removals", "ascendancy_swap_candidates", "analyze_tree_leaves", "audit_findings", "dead_ascendancy_nodes", "mastery_effect_tie_rows", "render_tree_leaf_table", "selected_masteries", "stat_keys"]
