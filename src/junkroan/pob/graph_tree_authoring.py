"""Graph-backed tree closure for Direct Build Agent-authored goals.

This module does not choose build goals and does not optimize a tree. It accepts
agent-chosen target nodes, mastery payloads, and roots, then resolves the legal
active-tree connector closure needed to connect those goals.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .tree_payload_normalization import canonical_active_tree_corpus, classify_tree_node_ids, normalize_tree_payload
from .tree_version_contract import canonical_tree_version

GRAPH_TREE_CLOSURE_RECORD_KIND = "direct_build_graph_tree_closure"
GRAPH_TREE_CLOSURE_SCHEMA_VERSION = "0.1.0"
LVL90_EXPECTED_PASSIVE_BUDGET = 113
LVL90_MIN_CLOSURE_PASSIVE_COUNT = 90
LVL90_MIN_TARGET_GOAL_COUNT = 8
LVL90_MAX_TRAVEL_TO_PAYOFF_RATIO = 1.25
LVL90_MIN_ASCENDANCY_GOAL_COUNT = 4


def resolve_graph_tree_closure(
    payload: Mapping[str, Any],
    *,
    tree_corpus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve connector closure for agent-authored passive tree goals."""

    corpus = _effective_tree_corpus(tree_corpus)
    goal_package = _first_mapping(payload.get("tree_goal_package"), payload.get("tree_goals"), payload)
    canonical_version = _string(corpus.get("canonical_tree_version") or corpus.get("tree_version") or canonical_tree_version())
    source_version = _string(
        goal_package.get("active_tree_version")
        or goal_package.get("tree_version")
        or goal_package.get("passive_tree_version")
    )
    blockers: list[dict[str, Any]] = []
    if source_version and canonical_version and source_version != canonical_version:
        blockers.append(
            _blocker(
                "graph_tree_version_mismatch",
                f"source tree version {source_version} != canonical tree version {canonical_version}",
                "Regenerate tree goals against the canonical active tree version.",
            )
        )

    available = _int_set(corpus.get("active_allocatable_node_ids") or corpus.get("available_node_ids"))
    ordinary = _int_set(corpus.get("ordinary_node_ids") or corpus.get("ordinary_passive_node_ids"))
    payoff = _int_set(corpus.get("payoff_node_ids") or corpus.get("notable_node_ids"))
    start_proxy = _int_set(corpus.get("start_root_proxy_node_ids") or corpus.get("proxy_node_ids"))
    graph = _active_graph(corpus, available | start_proxy)
    explicit_target_node_ids = _target_node_ids(goal_package)
    selected_masteries = _mastery_effect_ids(goal_package)
    mastery_prerequisite_node_ids, mastery_prerequisite_details, mastery_prerequisite_blockers = _mastery_prerequisite_closure(
        selected_masteries,
        corpus,
    )
    target_node_ids = sorted(dict.fromkeys([*explicit_target_node_ids, *mastery_prerequisite_node_ids]))
    goal_summary = _tree_goal_package_summary(
        goal_package,
        target_node_ids=explicit_target_node_ids,
        mastery_prerequisite_node_ids=mastery_prerequisite_node_ids,
    )
    root_node_ids = _root_node_ids(goal_package)
    current_user_ids = _int_set(
        goal_package.get("current_user_allocated_node_ids")
        or goal_package.get("current_allocated_node_ids")
        or goal_package.get("existing_user_allocated_node_ids")
    )
    if not root_node_ids:
        root_node_ids = sorted(current_user_ids)
    if not root_node_ids:
        blockers.append(
            _blocker(
                "graph_tree_closure_root_missing",
                "Graph closure requires class start/root ids or current allocated user node ids.",
                "Provide start_node_id/root_node_ids/current_user_allocated_node_ids before resolving goals.",
            )
        )

    blockers.extend(mastery_prerequisite_blockers)
    invalid_goal_details = _invalid_goal_details(target_node_ids, corpus, available)
    if invalid_goal_details:
        blockers.append(
            _blocker(
                "graph_tree_invalid_or_unavailable_goal_node",
                f"Invalid or unavailable target node ids: {invalid_goal_details}",
                "Choose target goals from canonical active-tree ordinary/payoff passive ids only.",
            )
        )

    root_details = _invalid_root_details(root_node_ids, corpus, available, start_proxy)
    if root_details:
        blockers.append(
            _blocker(
                "graph_tree_invalid_root_node",
                f"Invalid graph root node ids: {root_details}",
                "Use active class start/root/proxy ids or currently allocated active passive ids as graph roots.",
            )
        )
    blockers.extend(_pre_closure_goal_package_contract_blockers(goal_summary))

    selected_target_set = set(target_node_ids)
    connected_nodes: set[int] = set(current_user_ids)
    connected_nodes.update(root_node_ids)
    paths: list[dict[str, Any]] = []
    unreachable: list[int] = []
    non_target_payoff_connectors: set[int] = set()
    if not blockers:
        for target_id in target_node_ids:
            path = _shortest_legal_path(
                graph,
                connected_nodes,
                target_id,
                target_node_ids=selected_target_set,
                payoff_node_ids=payoff,
            )
            if path is None:
                unreachable.append(target_id)
                continue
            path_connectors = [
                node_id
                for node_id in path
                if node_id not in connected_nodes
                and node_id not in selected_target_set
                and node_id not in start_proxy
            ]
            non_target_payoff_connectors.update(node_id for node_id in path_connectors if node_id in payoff)
            connected_nodes.update(path)
            paths.append(
                {
                    "target_node_id": target_id,
                    "path_node_ids": path,
                    "connector_node_ids": path_connectors,
                    "path_cost": len([node_id for node_id in path if node_id not in current_user_ids and node_id not in start_proxy]),
                }
            )

    if unreachable:
        blockers.append(
            _blocker(
                "graph_tree_goal_unreachable",
                f"Unreachable target node ids from supplied roots/current tree: {sorted(unreachable)}",
                "Choose reachable goals or provide the active current allocated tree as root context.",
            )
        )
    if non_target_payoff_connectors:
        blockers.append(
            _blocker(
                "graph_tree_non_target_payoff_connector",
                f"Graph closure would add non-target payoff nodes as connectors: {sorted(non_target_payoff_connectors)}",
                "Do not hide extra payoff goals inside connector closure; choose them explicitly or choose different goals.",
            )
        )

    connector_node_ids = sorted(
        node_id
        for row in paths
        for node_id in _int_sequence(row.get("connector_node_ids"))
        if node_id in ordinary and node_id not in selected_target_set
    )
    full_user_allocated_node_ids = sorted(
        node_id
        for node_id in connected_nodes
        if node_id in available and node_id not in start_proxy
    )
    ascendancy_node_ids = _int_sequence(goal_package.get("ascendancy_node_ids"))
    travel_ratio = _ratio(len(connector_node_ids), len(target_node_ids))
    blockers.extend(
        _post_closure_goal_package_contract_blockers(
            goal_summary,
            full_user_allocated_node_ids=full_user_allocated_node_ids,
            travel_to_payoff_ratio=travel_ratio,
        )
    )
    tree_state = {
        "active_tree_version": canonical_version,
        "class_id": _string(goal_package.get("class_id") or goal_package.get("class_name")) or None,
        "start_node_id": _int_value(goal_package.get("start_node_id") or goal_package.get("class_start_node_id")),
        "user_allocated_node_ids": full_user_allocated_node_ids,
        "mastery_effect_ids": selected_masteries,
        "ascendancy_node_ids": ascendancy_node_ids,
        "route_shape_metrics": {
            "source": GRAPH_TREE_CLOSURE_RECORD_KIND,
            "selected_route_node_ids": full_user_allocated_node_ids,
            "travel_node_ids": connector_node_ids,
            "payoff_node_ids": sorted(target_node_ids),
            "connector_node_ids": connector_node_ids,
            "target_node_ids": sorted(target_node_ids),
            "explicit_target_node_ids": sorted(explicit_target_node_ids),
            "mastery_prerequisite_node_ids": sorted(mastery_prerequisite_node_ids),
            "travel_to_payoff_ratio": travel_ratio,
            "dead_end_travel_count": 0,
            "long_connector_corridor_count": _long_connector_corridor_count(paths, set(connector_node_ids)),
            "longest_connector_corridor_length": _long_connector_corridor_length(paths, set(connector_node_ids)),
            "disconnected_component_count": 1 if full_user_allocated_node_ids else 0,
        },
    }
    graph_evidence = {
        "record_kind": GRAPH_TREE_CLOSURE_RECORD_KIND,
        "schema_version": GRAPH_TREE_CLOSURE_SCHEMA_VERSION,
        "status": "blocked" if blockers else "accepted",
        "canonical_tree_version": canonical_version,
        "source_declared_tree_version": source_version or None,
        "root_node_ids": root_node_ids,
        "target_node_ids": sorted(target_node_ids),
        "explicit_target_node_ids": sorted(explicit_target_node_ids),
        "mastery_prerequisite_node_ids": sorted(mastery_prerequisite_node_ids),
        "mastery_prerequisite_details": mastery_prerequisite_details,
        "connector_node_ids": connector_node_ids,
        "full_user_allocated_node_ids": full_user_allocated_node_ids,
        "tree_goal_package_summary": goal_summary,
        "mastery_effect_ids": selected_masteries,
        "ascendancy_node_ids": ascendancy_node_ids,
        "passive_cost": len(set(full_user_allocated_node_ids) - current_user_ids),
        "full_passive_count": len(full_user_allocated_node_ids),
        "travel_to_payoff_ratio": travel_ratio,
        "longest_connector_corridor_length": _long_connector_corridor_length(paths, set(connector_node_ids)),
        "path_count": len(paths),
        "paths": paths,
        "unreachable_target_node_ids": sorted(unreachable),
        "invalid_goal_details": invalid_goal_details,
        "invalid_root_details": root_details,
        "route_alternatives": [],
        "route_alternative_policy": "not_computed_when_no_cheap_same-goal_alternative_is_available",
        "tool_boundary": {
            "chooses_build_goals": False,
            "chooses_replacement_nodes": False,
            "optimizes_tree": False,
            "selects_damage_life_clusters": False,
            "adds_connectors_only_between_agent_chosen_goals": True,
            "adds_mastery_prerequisite_closure_for_agent_selected_masteries": True,
        },
        "lvl90_goal_package_contract": _lvl90_goal_package_contract_report(
            blockers,
            goal_summary=goal_summary,
            full_passive_count=len(full_user_allocated_node_ids),
            travel_to_payoff_ratio=travel_ratio,
        ),
    }
    tree_state["graph_closure_evidence"] = {
        key: graph_evidence[key]
        for key in (
            "record_kind",
            "schema_version",
            "status",
            "canonical_tree_version",
            "root_node_ids",
            "target_node_ids",
            "explicit_target_node_ids",
            "mastery_prerequisite_node_ids",
            "mastery_prerequisite_details",
            "connector_node_ids",
            "full_user_allocated_node_ids",
            "tree_goal_package_summary",
            "passive_cost",
            "travel_to_payoff_ratio",
            "longest_connector_corridor_length",
            "lvl90_goal_package_contract",
        )
    }
    normalization = normalize_tree_payload(tree_state, tree_corpus=corpus)
    if _string(normalization.get("status")) == "blocked":
        for blocker in _sequence(normalization.get("blockers")):
            blockers.append(_normalize_blocker(blocker))
    status = "blocked" if blockers else "accepted"
    graph_evidence["status"] = status
    tree_state["graph_closure_evidence"]["status"] = status
    return {
        "record_kind": GRAPH_TREE_CLOSURE_RECORD_KIND,
        "schema_version": GRAPH_TREE_CLOSURE_SCHEMA_VERSION,
        "status": status,
        "blockers": _dedupe_blockers(blockers),
        "graph_closure_evidence": graph_evidence,
        "tree_state": tree_state,
        "safe_next_actions": ["run_structural_preflight"] if status == "accepted" else ["revise_agent_chosen_tree_goals_or_block"],
    }


def _effective_tree_corpus(tree_corpus: Mapping[str, Any] | None) -> Mapping[str, Any]:
    provided = _mapping(tree_corpus)
    return provided if provided else canonical_active_tree_corpus()


def _target_node_ids(goal_package: Mapping[str, Any]) -> list[int]:
    result: list[int] = []
    for key in (
        "offense_goal_node_ids",
        "offensive_goal_node_ids",
        "damage_goal_node_ids",
        "ignite_goal_node_ids",
        "hit_goal_node_ids",
        "crit_goal_node_ids",
        "defense_goal_node_ids",
        "defensive_goal_node_ids",
        "life_goal_node_ids",
        "attribute_goal_node_ids",
        "requirement_goal_node_ids",
        "attribute_requirement_goal_node_ids",
        "target_node_ids",
        "target_notable_node_ids",
        "target_cluster_node_ids",
        "goal_node_ids",
        "keystone_node_ids",
        "utility_node_ids",
    ):
        result.extend(_int_sequence(goal_package.get(key)))
    return sorted(dict.fromkeys(result))


def _tree_goal_package_summary(
    goal_package: Mapping[str, Any],
    *,
    target_node_ids: Sequence[int],
    mastery_prerequisite_node_ids: Sequence[int] = (),
) -> dict[str, Any]:
    offense = _goal_ids(
        goal_package,
        (
            "offense_goal_node_ids",
            "offensive_goal_node_ids",
            "damage_goal_node_ids",
            "ignite_goal_node_ids",
            "hit_goal_node_ids",
            "crit_goal_node_ids",
        ),
    )
    defense = _goal_ids(goal_package, ("defense_goal_node_ids", "defensive_goal_node_ids", "life_goal_node_ids"))
    attributes = _goal_ids(
        goal_package,
        ("attribute_goal_node_ids", "requirement_goal_node_ids", "attribute_requirement_goal_node_ids"),
    )
    utility = _goal_ids(goal_package, ("utility_goal_node_ids", "keystone_node_ids"))
    mastery_effect_ids = _mastery_effect_ids(goal_package)
    ascendancy_node_ids = _int_sequence(goal_package.get("ascendancy_node_ids"))
    ascendancy_notable_node_ids = _int_sequence(goal_package.get("ascendancy_notable_node_ids"))
    rationale = _string(goal_package.get("rationale") or goal_package.get("goal_rationale") or goal_package.get("archetype_rationale"))
    archetype = _string(goal_package.get("archetype") or goal_package.get("build_archetype") or goal_package.get("tested_archetype"))
    return {
        "record_kind": "direct_build_tree_goal_package_summary",
        "target_node_ids": sorted(set(target_node_ids)),
        "target_goal_count": len(set(target_node_ids)),
        "mastery_prerequisite_node_ids": sorted(set(mastery_prerequisite_node_ids)),
        "mastery_prerequisite_goal_count": len(set(mastery_prerequisite_node_ids)),
        "offense_goal_node_ids": offense,
        "offense_goal_count": len(offense),
        "defense_goal_node_ids": defense,
        "defense_goal_count": len(defense),
        "attribute_requirement_goal_node_ids": attributes,
        "attribute_requirement_goal_count": len(attributes),
        "utility_goal_node_ids": utility,
        "utility_goal_count": len(utility),
        "mastery_effect_ids": mastery_effect_ids,
        "mastery_goal_count": len(mastery_effect_ids),
        "ascendancy_node_ids": ascendancy_node_ids,
        "ascendancy_goal_count": len(ascendancy_node_ids),
        "ascendancy_notable_node_ids": ascendancy_notable_node_ids,
        "ascendancy_notable_goal_count": len(ascendancy_notable_node_ids),
        "has_archetype_rationale": bool(archetype and rationale),
        "archetype": archetype or None,
        "rationale": rationale or None,
    }


def _goal_ids(goal_package: Mapping[str, Any], keys: Sequence[str]) -> list[int]:
    result: list[int] = []
    for key in keys:
        result.extend(_int_sequence(goal_package.get(key)))
    return sorted(dict.fromkeys(result))


def _pre_closure_goal_package_contract_blockers(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if (_int_value(summary.get("target_goal_count")) or 0) < LVL90_MIN_TARGET_GOAL_COUNT:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_too_few_targets",
                f"target_goal_count={summary.get('target_goal_count')} < {LVL90_MIN_TARGET_GOAL_COUNT}",
                "Author a complete lvl90-oriented target package before graph closure.",
            )
        )
    if (_int_value(summary.get("offense_goal_count")) or 0) <= 0:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_missing_offense_goals",
                "No offense goals are declared for the archetype.",
                "Add offense_goal_node_ids tied to the requested skill/archetype.",
            )
        )
    if (_int_value(summary.get("defense_goal_count")) or 0) <= 0:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_missing_life_defense_goals",
                "No life/defense goals are declared.",
                "Add life_goal_node_ids or defense_goal_node_ids before graph closure.",
            )
        )
    if (_int_value(summary.get("attribute_requirement_goal_count")) or 0) <= 0:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_missing_attribute_requirement_plan",
                "No attribute/requirement goals are declared.",
                "Add attribute_goal_node_ids or requirement_goal_node_ids before graph closure.",
            )
        )
    if (_int_value(summary.get("mastery_goal_count")) or 0) <= 0:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_missing_mastery_effects",
                "No mastery node/effect goals are declared.",
                "Add mastery_effect_ids as node_id:effect_id entries.",
            )
        )
    if (_int_value(summary.get("ascendancy_goal_count")) or 0) < LVL90_MIN_ASCENDANCY_GOAL_COUNT:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_missing_ascendancy_goals",
                f"ascendancy_goal_count={summary.get('ascendancy_goal_count')} < {LVL90_MIN_ASCENDANCY_GOAL_COUNT}",
                "Add the planned ascendancy node ids separately from ordinary passive goals.",
            )
        )
    if not _truthy(summary.get("has_archetype_rationale")):
        blockers.append(
            _blocker(
                "graph_tree_goal_package_rationale_missing",
                "Tree goal package lacks archetype rationale.",
                "Carry archetype and rationale tying goal categories to the requested build.",
            )
        )
    return blockers


def _post_closure_goal_package_contract_blockers(
    summary: Mapping[str, Any],
    *,
    full_user_allocated_node_ids: Sequence[int],
    travel_to_payoff_ratio: float | None,
) -> list[dict[str, Any]]:
    del summary
    blockers: list[dict[str, Any]] = []
    passive_count = len(set(full_user_allocated_node_ids))
    if passive_count < LVL90_MIN_CLOSURE_PASSIVE_COUNT:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_closure_passive_budget_too_low",
                f"closure_passive_count={passive_count} < {LVL90_MIN_CLOSURE_PASSIVE_COUNT} for lvl90 target budget {LVL90_EXPECTED_PASSIVE_BUDGET}",
                "Author enough lvl90 tree goals so graph closure approaches the Early Game passive budget before metric probes.",
            )
        )
    if travel_to_payoff_ratio is not None and travel_to_payoff_ratio > LVL90_MAX_TRAVEL_TO_PAYOFF_RATIO:
        blockers.append(
            _blocker(
                "graph_tree_goal_package_travel_to_payoff_too_high",
                f"travel_to_payoff_ratio={travel_to_payoff_ratio:g} > {LVL90_MAX_TRAVEL_TO_PAYOFF_RATIO}",
                "Compare alternative goal packages and reject goal sets that create excessive travel.",
            )
        )
    return blockers


def _lvl90_goal_package_contract_report(
    blockers: Sequence[Mapping[str, Any]],
    *,
    goal_summary: Mapping[str, Any],
    full_passive_count: int,
    travel_to_payoff_ratio: float | None,
) -> dict[str, Any]:
    contract_codes = [
        _string(blocker.get("code") or blocker.get("blocker_id"))
        for blocker in blockers
        if _string(blocker.get("code") or blocker.get("blocker_id")).startswith("graph_tree_goal_package_")
    ]
    return {
        "record_kind": "direct_build_lvl90_tree_goal_package_contract",
        "status": "blocked" if contract_codes else "accepted",
        "expected_passive_budget": LVL90_EXPECTED_PASSIVE_BUDGET,
        "minimum_closure_passive_count": LVL90_MIN_CLOSURE_PASSIVE_COUNT,
        "minimum_target_goal_count": LVL90_MIN_TARGET_GOAL_COUNT,
        "maximum_travel_to_payoff_ratio": LVL90_MAX_TRAVEL_TO_PAYOFF_RATIO,
        "full_passive_count": full_passive_count,
        "travel_to_payoff_ratio": travel_to_payoff_ratio,
        "tree_goal_package_summary": dict(goal_summary),
        "blocker_codes": sorted(set(contract_codes)),
    }


def _root_node_ids(goal_package: Mapping[str, Any]) -> list[int]:
    result: list[int] = []
    for key in ("root_node_ids", "start_node_ids", "class_start_node_ids"):
        result.extend(_int_sequence(goal_package.get(key)))
    start = _int_value(goal_package.get("start_node_id") or goal_package.get("class_start_node_id") or goal_package.get("root_node_id"))
    if start is not None:
        result.append(start)
    return sorted(dict.fromkeys(result))


def _mastery_effect_ids(goal_package: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for entry in _sequence(goal_package.get("mastery_effect_ids") or goal_package.get("selected_mastery_effect_ids")):
        text = _string(entry)
        if text:
            result.append(text)
    return sorted(dict.fromkeys(result))


def _mastery_prerequisite_closure(
    mastery_effect_ids: Sequence[str],
    corpus: Mapping[str, Any],
) -> tuple[list[int], list[dict[str, Any]], list[dict[str, Any]]]:
    prerequisites_by_node = _mastery_prerequisites_by_node(corpus)
    has_authority = _has_mastery_prerequisite_authority(corpus)
    prerequisite_ids: set[int] = set()
    details: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for entry in mastery_effect_ids:
        node_id, effect_id = _parse_mastery_effect_entry(entry)
        if node_id is None:
            continue
        prerequisites = sorted(prerequisites_by_node.get(node_id, set()))
        if not prerequisites and has_authority:
            blockers.append(
                _blocker(
                    "graph_tree_mastery_prerequisite_authority_missing",
                    f"Selected mastery group {node_id} has no prerequisite/anchor node in the active tree corpus.",
                    "Regenerate the active tree corpus or choose mastery payloads with corpus-backed prerequisite anchors.",
                )
            )
        prerequisite_ids.update(prerequisites)
        details.append(
            {
                "mastery_effect_id": entry,
                "mastery_node_id": node_id,
                "effect_id": effect_id,
                "prerequisite_node_ids": prerequisites,
            }
        )
    return sorted(prerequisite_ids), details, blockers


def _parse_mastery_effect_entry(entry: Any) -> tuple[int | None, str]:
    if isinstance(entry, Mapping):
        node_id = _int_value(entry.get("node_id") if entry.get("node_id") is not None else entry.get("mastery_node_id"))
        effect_id = _string(entry.get("effect_id") if entry.get("effect_id") is not None else entry.get("mastery_effect_id"))
        return node_id, effect_id
    text = _string(entry)
    if ":" not in text:
        return None, ""
    node_text, effect_text = text.split(":", 1)
    return _int_value(node_text), effect_text.strip()


def _mastery_prerequisites_by_node(corpus: Mapping[str, Any]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {}
    for key in (
        "mastery_prerequisite_node_ids_by_node_id",
        "mastery_anchor_node_ids_by_node_id",
        "mastery_incoming_node_ids_by_node_id",
        "mastery_prerequisites_by_node_id",
    ):
        raw = _mapping(corpus.get(key))
        for node_id_text, prerequisites in raw.items():
            node_id = _int_value(node_id_text)
            if node_id is None:
                continue
            result.setdefault(node_id, set()).update(_int_sequence(prerequisites))
    if result:
        return result

    mastery_node_ids = _int_set(corpus.get("mastery_node_ids"))
    adjacency = _mapping(corpus.get("adjacency"))
    for node_id_text, neighbors in adjacency.items():
        node_id = _int_value(node_id_text)
        if node_id is not None and node_id in mastery_node_ids:
            result.setdefault(node_id, set()).update(_int_sequence(neighbors))
        for neighbor_id in _int_sequence(neighbors):
            if neighbor_id in mastery_node_ids and node_id is not None:
                result.setdefault(neighbor_id, set()).add(node_id)
    return result


def _has_mastery_prerequisite_authority(corpus: Mapping[str, Any]) -> bool:
    if any(
        key in corpus
        for key in (
            "mastery_prerequisite_node_ids_by_node_id",
            "mastery_anchor_node_ids_by_node_id",
            "mastery_incoming_node_ids_by_node_id",
            "mastery_prerequisites_by_node_id",
        )
    ):
        return True
    mastery_node_ids = _int_set(corpus.get("mastery_node_ids"))
    if not mastery_node_ids:
        return False
    adjacency = _mapping(corpus.get("adjacency"))
    return any(_int_value(node_id) in mastery_node_ids for node_id in adjacency) or any(
        neighbor_id in mastery_node_ids for neighbors in adjacency.values() for neighbor_id in _int_sequence(neighbors)
    )


def _active_graph(corpus: Mapping[str, Any], allowed_node_ids: set[int]) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for node_id_text, neighbors in _mapping(corpus.get("adjacency")).items():
        node_id = _int_value(node_id_text)
        if node_id is None or node_id not in allowed_node_ids:
            continue
        graph.setdefault(node_id, set())
        for neighbor_id in _int_sequence(neighbors):
            if neighbor_id in allowed_node_ids:
                graph.setdefault(neighbor_id, set()).add(node_id)
                graph[node_id].add(neighbor_id)
    return graph


def _shortest_legal_path(
    graph: Mapping[int, set[int]],
    source_ids: set[int],
    target_id: int,
    *,
    target_node_ids: set[int],
    payoff_node_ids: set[int],
) -> list[int] | None:
    if target_id in source_ids:
        return [target_id]
    queue: deque[tuple[int, list[int]]] = deque()
    visited: set[int] = set()
    for source_id in sorted(source_ids):
        if source_id not in graph:
            continue
        queue.append((source_id, [source_id]))
        visited.add(source_id)
    while queue:
        node_id, path = queue.popleft()
        for neighbor_id in sorted(graph.get(node_id, set())):
            if neighbor_id in visited:
                continue
            if neighbor_id != target_id and neighbor_id in payoff_node_ids and neighbor_id not in target_node_ids:
                continue
            next_path = [*path, neighbor_id]
            if neighbor_id == target_id:
                return next_path
            visited.add(neighbor_id)
            queue.append((neighbor_id, next_path))
    return None


def _invalid_goal_details(node_ids: Sequence[int], corpus: Mapping[str, Any], available: set[int]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    known = _int_set(corpus.get("known_node_ids"))
    inactive = _int_set(corpus.get("inactive_or_unavailable_node_ids"))
    for node_id in sorted(set(node_ids)):
        memberships = _memberships(node_id, corpus)
        reason = ""
        if known and node_id not in known:
            reason = "unknown_goal_node_id"
        elif node_id in inactive or node_id not in available:
            reason = "inactive_or_not_allocatable_in_canonical_active_tree"
        elif any(member in memberships for member in ("mastery_group", "mastery_effect_ref", "ascendancy", "start_root_proxy")):
            reason = "wrong_namespace_for_tree_goal"
        if reason:
            details.append({"node_id": node_id, "reason": reason, "memberships": memberships})
    return details


def _invalid_root_details(node_ids: Sequence[int], corpus: Mapping[str, Any], available: set[int], start_proxy: set[int]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    known = _int_set(corpus.get("known_node_ids"))
    for node_id in sorted(set(node_ids)):
        memberships = _memberships(node_id, corpus)
        if known and node_id not in known:
            details.append({"node_id": node_id, "reason": "unknown_root_node_id", "memberships": memberships})
        elif node_id not in available and node_id not in start_proxy:
            details.append({"node_id": node_id, "reason": "root_node_not_active_allocatable_or_start_proxy", "memberships": memberships})
    return details


def _memberships(node_id: int, corpus: Mapping[str, Any]) -> list[str]:
    classification = classify_tree_node_ids([node_id], namespace="passive_node", tree_corpus=corpus)
    result: list[str] = []
    for key in (
        "ordinary_connector_path",
        "payoff_notable",
        "mastery_group",
        "mastery_effect_ref",
        "ascendancy",
        "start_root_proxy",
        "unknown",
        "namespace_collision",
    ):
        if node_id in _int_set(classification.get(key)):
            result.append(key)
    return result


def _long_connector_corridor_length(paths: Sequence[Mapping[str, Any]], connector_ids: set[int]) -> int:
    longest = 0
    for path in paths:
        current = 0
        for node_id in _int_sequence(path.get("path_node_ids")):
            if node_id in connector_ids:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
    return longest


def _long_connector_corridor_count(paths: Sequence[Mapping[str, Any]], connector_ids: set[int], *, threshold: int = 8) -> int:
    return sum(1 for path in paths if _long_connector_corridor_length([path], connector_ids) > threshold)


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "yes", "true", "accepted", "proven"}
    return bool(value)


def _blocker(code: str, summary: str, repair_hint: str) -> dict[str, Any]:
    return {
        "code": code,
        "blocker_id": code,
        "severity": "blocking",
        "summary": summary,
        "repair_hint": repair_hint,
    }


def _normalize_blocker(blocker: Mapping[str, Any]) -> dict[str, Any]:
    code = _string(blocker.get("code") or blocker.get("blocker_id")) or "graph_tree_closure_blocker"
    return _blocker(
        code,
        _string(blocker.get("summary")) or code,
        _string(blocker.get("repair_hint") or blocker.get("unblock_condition")) or "Repair graph tree closure input.",
    )


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        code = _string(blocker.get("code") or blocker.get("blocker_id")) or "graph_tree_closure_blocker"
        summary = _string(blocker.get("summary"))
        key = (code, summary)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(blocker))
    return result


def _first_mapping(*values: Any) -> Mapping[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return value
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return []


def _int_sequence(value: Any) -> list[int]:
    result: list[int] = []
    for entry in _sequence(value):
        parsed = _int_value(entry)
        if parsed is not None:
            result.append(parsed)
    return result


def _int_set(value: Any) -> set[int]:
    return set(_int_sequence(value))


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _read_json_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit(f"{label} must be a JSON object: {path}")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve graph-backed Direct Build tree closure from agent-authored goals.")
    parser.add_argument("--input", required=True, type=Path, help="Agent-authored tree goal package JSON.")
    parser.add_argument("--output", type=Path, help="Optional output path for graph closure report.")
    parser.add_argument("--tree-corpus", type=Path, help="Optional active tree corpus snapshot JSON.")
    args = parser.parse_args(argv)

    payload = _read_json_mapping(args.input, label="input")
    tree_corpus = _read_json_mapping(args.tree_corpus, label="tree corpus") if args.tree_corpus else None
    report = resolve_graph_tree_closure(payload, tree_corpus=tree_corpus)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
