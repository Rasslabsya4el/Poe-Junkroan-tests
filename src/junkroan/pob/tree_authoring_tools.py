"""Agent-facing passive tree authoring tools over the pinned PoB wrapper.

This module deliberately does not choose passive nodes. It only enforces the
observe -> decide -> mutate -> observe loop and delegates all PoB state changes
to the runtime adapter.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "0.1.0"
TREE_STATE_OBSERVATION_RECORD_KIND = "pob_tree_state_observation"
TREE_MUTATION_RESULT_RECORD_KIND = "pob_tree_mutation_result"
TREE_NODE_POWER_RESULT_RECORD_KIND = "pob_tree_node_power_result"
ASCENDANCY_NODE_REPORT_RECORD_KIND = "pob_ascendancy_node_report"
PASSIVE_TREE_QUERY_RESULT_RECORD_KIND = "pob_passive_tree_query_result"
TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND = "tree_only_fixture_authoring_packet"
TREE_READBACK_QUALITY_REPORT_RECORD_KIND = "pob_tree_readback_quality_report"
DIRECT_BUILD_DECISION_TRACE_RECORD_KIND = "direct_build_decision_trace"
DEFAULT_PASSIVE_TREE_CORPUS_ROOT = Path(__file__).resolve().parent / "corpus_data"

_TREE_ONLY_FIXTURE_PACKET_STATUSES = {"ready_to_apply", "blocked"}
_TREE_QUALITY_BUDGET_MODES = {"repair_delta", "budgeted_full_tree"}
_FULL_TREE_PAYLOAD_KEYS = frozenset(
    {
        "active_spec_id",
        "class_id",
        "ascendancy_id",
        "secondary_ascendancy_id",
        "ascendancy_node_ids",
        "ascendancy_notable_node_ids",
        "user_allocated_node_ids",
        "keystone_node_ids",
        "mastery_effect_ids",
        "cluster_jewel_socket_ids",
        "socketed_jewel_node_ids",
        "override_carrier_node_ids",
        "override_carriers",
        "cluster_jewel_items",
        "socketed_jewel_items",
    }
)
_TREE_PAYLOAD_INT_LIST_FIELDS = frozenset(
    {
        "ascendancy_node_ids",
        "ascendancy_notable_node_ids",
        "user_allocated_node_ids",
        "keystone_node_ids",
        "cluster_jewel_socket_ids",
        "socketed_jewel_node_ids",
        "override_carrier_node_ids",
    }
)
_TREE_PAYLOAD_STRING_LIST_FIELDS = frozenset({"mastery_effect_ids"})
_TREE_PAYLOAD_OBJECT_LIST_FIELDS = frozenset({"override_carriers", "cluster_jewel_items", "socketed_jewel_items"})
_FORBIDDEN_PUBLICATION_FIELDS = {
    "pob_code",
    "pobCode",
    "ready_pob_import",
    "ready_import",
    "direct_build_output",
    "final_candidate",
    "public_url",
}

_FORBIDDEN_SCRIPT_AUTHORED_RECORD_KINDS = {
    "tree_lab_candidate_set",
    "script_authored_direct_build_payload",
    "direct_build_ready_import",
    "direct_build_output",
}


class PoBTreeAuthoringToolError(RuntimeError):
    """Raised when an agent-facing tree tool must fail closed."""

    def __init__(self, code: str, message: str, *, blockers: Sequence[Mapping[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.blockers = [dict(blocker) for blocker in blockers or [{"code": code, "message": message}]]


def inspect_tree_state(
    runtime_adapter: Any,
    handle: Any,
    *,
    candidate_id: str,
    variant_id: str,
    action_id: str | None = None,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read current passive tree state from pinned PoB without mutating it."""

    unified_state = runtime_adapter.read_state(handle)
    tree_state = _tree_state_from_unified_state(unified_state)
    state_version = _stable_hash(tree_state)
    observation_id = _tree_observation_id(handle, state_version)
    tree_accounting = _tree_accounting(tree_state)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": TREE_STATE_OBSERVATION_RECORD_KIND,
        "status": "accepted",
        "candidate_id": _require_non_empty_string(candidate_id, "candidate_id"),
        "variant_id": _require_non_empty_string(variant_id, "variant_id"),
        "pob_run_id": _handle_pob_run_id(handle),
        "action_id": action_id,
        "observation_id": observation_id,
        "state_version": state_version,
        "side_effect_class": "read_only",
        "input_refs": [dict(ref) for ref in input_refs or []],
        "output_refs": [
            {
                "ref_id": observation_id,
                "ref_kind": TREE_STATE_OBSERVATION_RECORD_KIND,
                "locator": "pinned_pob_runtime.read_state.tree_state",
                "json_pointer": "/data/tree_state",
                "summary": "Current passive tree state read back from pinned PoB.",
            }
        ],
        "summary": {
            "state_kind": tree_state.get("state_kind"),
            "class_id": tree_state.get("class_id"),
            "ascendancy_id": tree_state.get("ascendancy_id"),
            "normal_passive_count": tree_accounting["normal_passive_count"],
            "ascendancy_node_count": tree_accounting["ascendancy_node_count"],
            "allocated_node_count": tree_accounting["allocated_node_count"],
        },
        "data": {
            "tree_state": tree_state,
            "tree_accounting": tree_accounting,
        },
        "diff": {},
        "evidence": {
            "source_kind": "pinned_pob_runtime_readback",
            "state_version": state_version,
        },
        "warnings": [],
        "blockers": [],
        "missing_inputs": [],
        "invalid_reasons": [],
        "safe_next_actions": ["read_tree_node_power", "mutate_tree_state"],
        "trusted_input_boundary": "pinned_pob_runtime_readback",
        "untrusted_text_fields": [],
    }


def read_tree_node_power(
    runtime_adapter: Any,
    handle: Any,
    *,
    candidate_id: str,
    variant_id: str,
    action_id: str,
    node_power_request: Mapping[str, Any] | None = None,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read PoB-ranked passive rows without treating them as selected nodes."""

    report = runtime_adapter.read_node_power_report(handle, dict(node_power_request or {}))
    state_version = _stable_hash(report)
    result_id = f"tree.node_power.{_handle_pob_run_id(handle)}.{state_version[:12]}"
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": TREE_NODE_POWER_RESULT_RECORD_KIND,
        "status": "accepted",
        "candidate_id": _require_non_empty_string(candidate_id, "candidate_id"),
        "variant_id": _require_non_empty_string(variant_id, "variant_id"),
        "pob_run_id": _handle_pob_run_id(handle),
        "action_id": _require_non_empty_string(action_id, "action_id"),
        "result_id": result_id,
        "state_version": state_version,
        "side_effect_class": "read_only",
        "input_refs": [dict(ref) for ref in input_refs or []],
        "output_refs": [
            {
                "ref_id": result_id,
                "ref_kind": TREE_NODE_POWER_RESULT_RECORD_KIND,
                "locator": "pinned_pob_runtime.read_node_power_report",
                "json_pointer": "/data/node_power_report",
                "summary": "PoB-ranked passive rows; these are not allocated passives.",
            }
        ],
        "summary": {
            "row_count": len(rows),
            "selected_metric": report.get("selected_metric"),
            "ranked_rows_are_allocated_passives": False,
        },
        "data": {
            "node_power_report": report,
            "ranked_rows_are_allocated_passives": False,
        },
        "diff": {},
        "evidence": {
            "source_kind": "pinned_pob_native_node_power_report",
            "state_version": state_version,
        },
        "warnings": [
            {
                "code": "ranked_rows_not_allocated_passives",
                "message": "PoB Node Power rows are candidate evidence, not selected tree nodes.",
            }
        ],
        "blockers": [],
        "missing_inputs": [],
        "invalid_reasons": [],
        "safe_next_actions": ["mutate_tree_state", "inspect_tree_state"],
        "trusted_input_boundary": "pinned_pob_runtime_readback",
        "untrusted_text_fields": [],
    }


def read_ascendancy_node_report(
    runtime_adapter: Any,
    handle: Any,
    *,
    candidate_id: str,
    variant_id: str,
    action_id: str,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read selected-ascendancy nodes from pinned PoB without choosing them."""

    report = runtime_adapter.read_ascendancy_node_report(handle)
    state_version = _stable_hash(report)
    result_id = f"tree.ascendancy_nodes.{_handle_pob_run_id(handle)}.{state_version[:12]}"
    rows = report.get("rows") if isinstance(report.get("rows"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": ASCENDANCY_NODE_REPORT_RECORD_KIND,
        "status": "accepted",
        "candidate_id": _require_non_empty_string(candidate_id, "candidate_id"),
        "variant_id": _require_non_empty_string(variant_id, "variant_id"),
        "pob_run_id": _handle_pob_run_id(handle),
        "action_id": _require_non_empty_string(action_id, "action_id"),
        "result_id": result_id,
        "state_version": state_version,
        "side_effect_class": "read_only",
        "input_refs": [dict(ref) for ref in input_refs or []],
        "output_refs": [
            {
                "ref_id": result_id,
                "ref_kind": ASCENDANCY_NODE_REPORT_RECORD_KIND,
                "locator": "pinned_pob_runtime.read_ascendancy_node_report",
                "json_pointer": "/data/ascendancy_node_report",
                "summary": "Selected-ascendancy node facts; these are not selected by the tool.",
            }
        ],
        "summary": {
            "active_ascendancy_id": report.get("active_ascendancy_id"),
            "row_count": len(rows),
            "notable_row_count": sum(1 for row in rows if isinstance(row, Mapping) and row.get("is_notable") is True),
            "ascendancy_report_rows_are_allocated_nodes": False,
        },
        "data": {
            "ascendancy_node_report": report,
            "ascendancy_report_rows_are_allocated_nodes": False,
        },
        "diff": {},
        "evidence": {
            "source_kind": "pinned_pob_runtime_ascendancy_tree_readback",
            "state_version": state_version,
        },
        "warnings": [],
        "blockers": [],
        "missing_inputs": [],
        "invalid_reasons": [],
        "safe_next_actions": ["mutate_tree_state", "inspect_tree_state"],
        "trusted_input_boundary": "pinned_pob_runtime_readback",
        "untrusted_text_fields": [],
    }


def query_passive_tree_nodes(
    *,
    search_terms: Sequence[str],
    current_tree_state: Mapping[str, Any],
    candidate_id: str,
    variant_id: str,
    action_id: str,
    corpus_root: Path | str = DEFAULT_PASSIVE_TREE_CORPUS_ROOT,
    families: Sequence[str] = ("keystones", "passives", "masteries"),
    max_rows: int = 40,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Search passive-tree corpus facts and annotate route distance.

    This is an evidence tool. It does not choose targets and does not mutate PoB.
    """

    terms = [term.lower() for term in _string_sequence(search_terms)]
    if not terms:
        raise PoBTreeAuthoringToolError("invalid_passive_tree_query", "search_terms must contain at least one term.")
    root = Path(corpus_root)
    current_state = _require_mapping(current_tree_state, "current_tree_state")
    current_ids = set(_int_sequence(current_state.get("user_allocated_node_ids")))
    current_ids.update(_int_sequence(current_state.get("allocated_ascendancy_node_ids")))
    current_ids.update(_int_sequence(current_state.get("ascendancy_node_ids")))
    records = _load_passive_tree_corpus_records(root, families)
    graph = _passive_tree_graph(records)
    rows: list[dict[str, Any]] = []
    for record in records:
        searchable = _passive_record_search_text(record)
        matched_terms = [term for term in terms if term in searchable]
        if not matched_terms:
            continue
        node_id = record.get("node_id")
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            continue
        path_node_ids = _shortest_path_from_any(graph, current_ids, node_id)
        added_path_node_ids = [] if path_node_ids is None else [path_id for path_id in path_node_ids if path_id not in current_ids]
        rows.append(
            {
                "row_id": f"pob.passive-query.{node_id}",
                "node_id": node_id,
                "node_name": _string(record.get("name")) or f"node {node_id}",
                "target_kind": _passive_record_target_kind(record),
                "family": _string(record.get("_family")),
                "matched_terms": matched_terms,
                "allocated": node_id in current_ids,
                "stats": _passive_record_stats(record),
                "mastery_effects": _passive_record_mastery_effects(record, node_id=node_id),
                "path_node_ids": path_node_ids or [],
                "added_path_node_ids": added_path_node_ids,
                "point_cost": len(added_path_node_ids) if path_node_ids is not None else None,
                "route_status": "reachable" if path_node_ids is not None else "unreachable_from_current_allocated_tree",
                "source_ref": {
                    "ref_id": f"pob.corpus.passive.{node_id}",
                    "ref_kind": "pinned_passive_tree_corpus_record",
                    "locator": str((root / f"{record['_family']}.json").resolve(strict=False)),
                },
            }
        )

    rows.sort(key=lambda row: (row["point_cost"] is None, row["point_cost"] if row["point_cost"] is not None else 10**9, row["target_kind"] != "keystone", row["node_name"]))
    rows = rows[: max(0, int(max_rows))]
    result_hash = _stable_hash({"terms": terms, "rows": rows, "current_ids": sorted(current_ids)})
    result_id = f"tree.passive_query.{result_hash[:12]}"
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": PASSIVE_TREE_QUERY_RESULT_RECORD_KIND,
        "status": "accepted",
        "candidate_id": _require_non_empty_string(candidate_id, "candidate_id"),
        "variant_id": _require_non_empty_string(variant_id, "variant_id"),
        "action_id": _require_non_empty_string(action_id, "action_id"),
        "result_id": result_id,
        "side_effect_class": "read_only",
        "input_refs": [dict(ref) for ref in input_refs or []],
        "output_refs": [
            {
                "ref_id": result_id,
                "ref_kind": PASSIVE_TREE_QUERY_RESULT_RECORD_KIND,
                "locator": "pinned_passive_tree_corpus.query",
                "json_pointer": "/data/rows",
                "summary": "Passive-tree corpus matches with route-distance facts; these are not selected passives.",
            }
        ],
        "summary": {
            "search_terms": terms,
            "row_count": len(rows),
            "query_rows_are_allocated_passives": False,
            "route_distance_is_build_authority": False,
        },
        "data": {
            "rows": rows,
            "current_user_allocated_node_ids": sorted(current_ids),
        },
        "diff": {},
        "evidence": {
            "source_kind": "pinned_passive_tree_corpus",
            "corpus_root": str(root.resolve(strict=False)),
        },
        "warnings": [
            {
                "code": "passive_query_rows_not_selected_passives",
                "message": "Passive query rows are candidate facts only. The agent must still choose targets and PoB readback must verify the result.",
            }
        ],
        "blockers": [],
        "missing_inputs": [],
        "invalid_reasons": [],
        "safe_next_actions": ["author_tree_probe_or_mutation_packet", "inspect_tree_state"],
        "trusted_input_boundary": "pinned_passive_tree_corpus_readonly",
        "untrusted_text_fields": [],
    }


def mutate_tree_state(
    runtime_adapter: Any,
    handle: Any,
    *,
    candidate_id: str,
    variant_id: str,
    action_id: str,
    tree_payload: Mapping[str, Any],
    decision_trace: Mapping[str, Any],
    expected_state_version: str,
    observation_ref: Mapping[str, Any],
    fixture_contract: Mapping[str, Any] | None = None,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
    allow_source_pob_run_id: bool = False,
) -> dict[str, Any]:
    """Apply an agent-authored passive tree payload after fail-closed checks."""

    candidate_id = _require_non_empty_string(candidate_id, "candidate_id")
    variant_id = _require_non_empty_string(variant_id, "variant_id")
    action_id = _require_non_empty_string(action_id, "action_id")
    tree_payload = _require_mapping(tree_payload, "tree_payload")
    payload_blockers = _tree_only_fixture_payload_blockers(tree_payload)
    if payload_blockers:
        raise PoBTreeAuthoringToolError(
            "tree_payload_rejected",
            "Tree mutation payload must be a full explicit tree snapshot.",
            blockers=payload_blockers,
        )

    before_observation = inspect_tree_state(
        runtime_adapter,
        handle,
        candidate_id=candidate_id,
        variant_id=variant_id,
        action_id=f"{action_id}.pre_observe",
        input_refs=input_refs,
    )
    blockers = _validate_tree_mutation_request(
        candidate_id=candidate_id,
        variant_id=variant_id,
        pob_run_id=_handle_pob_run_id(handle),
        action_id=action_id,
        decision_trace=decision_trace,
        expected_state_version=expected_state_version,
        observed_state_version=before_observation["state_version"],
        observation_ref=observation_ref,
        fixture_contract=fixture_contract,
        allow_source_pob_run_id=allow_source_pob_run_id,
    )
    if blockers:
        raise PoBTreeAuthoringToolError(
            "tree_mutation_rejected",
            "Tree mutation request failed agent-authorship checks.",
            blockers=blockers,
        )

    consistency_blockers = _tree_payload_expected_observation_consistency_blockers(
        packet={"direct_build_decision_trace": decision_trace},
        trace=decision_trace,
        tree_payload=tree_payload,
        expected_observation=before_observation,
    )
    if consistency_blockers:
        raise PoBTreeAuthoringToolError(
            "tree_mutation_rejected",
            "Tree mutation request failed payload/accounting checks.",
            blockers=consistency_blockers,
        )

    runtime_adapter.apply_tree_state(handle, dict(tree_payload))
    after_observation = inspect_tree_state(
        runtime_adapter,
        handle,
        candidate_id=candidate_id,
        variant_id=variant_id,
        action_id=f"{action_id}.post_observe",
        input_refs=[*list(input_refs or []), observation_ref],
    )
    diff = _tree_diff(
        before_observation["data"]["tree_state"],
        after_observation["data"]["tree_state"],
    )
    result_id = f"tree.mutation.{_handle_pob_run_id(handle)}.{after_observation['state_version'][:12]}"
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": TREE_MUTATION_RESULT_RECORD_KIND,
        "status": "accepted",
        "candidate_id": candidate_id,
        "variant_id": variant_id,
        "pob_run_id": _handle_pob_run_id(handle),
        "action_id": action_id,
        "result_id": result_id,
        "state_version": after_observation["state_version"],
        "side_effect_class": "pob_tree_mutation",
        "idempotency_key": _stable_hash(
            {
                "pob_run_id": _handle_pob_run_id(handle),
                "candidate_id": candidate_id,
                "variant_id": variant_id,
                "action_id": action_id,
                "tree_payload": tree_payload,
                "expected_state_version": expected_state_version,
            }
        ),
        "input_refs": [*list(input_refs or []), dict(observation_ref)],
        "output_refs": [
            {
                "ref_id": result_id,
                "ref_kind": TREE_MUTATION_RESULT_RECORD_KIND,
                "locator": "pinned_pob_runtime.apply_tree_state",
                "json_pointer": "/diff",
                "summary": "Passive tree diff after applying an agent-authored tree payload.",
            },
            after_observation["output_refs"][0],
        ],
        "summary": {
            "before_state_version": before_observation["state_version"],
            "after_state_version": after_observation["state_version"],
            "added_user_allocated_node_count": len(diff["user_allocated_node_ids"]["added"]),
            "removed_user_allocated_node_count": len(diff["user_allocated_node_ids"]["removed"]),
            "normal_passive_count_after": after_observation["data"]["tree_accounting"]["normal_passive_count"],
            "ascendancy_node_count_after": after_observation["data"]["tree_accounting"]["ascendancy_node_count"],
        },
        "data": {
            "before_observation": before_observation,
            "after_observation": after_observation,
        },
        "diff": diff,
        "evidence": {
            "source_kind": "pinned_pob_runtime_readback_diff",
            "before_state_version": before_observation["state_version"],
            "after_state_version": after_observation["state_version"],
        },
        "warnings": [],
        "blockers": [],
        "missing_inputs": [],
        "invalid_reasons": [],
        "safe_next_actions": ["read_tree_node_power", "inspect_tree_state", "read_calc_snapshot"],
        "trusted_input_boundary": "agent_decision_trace_plus_pinned_pob_runtime_readback",
        "untrusted_text_fields": ["decision_trace.decisions[].rationale", "decision_trace.actions[].agent_rationale"],
    }


def apply_tree_only_fixture_authoring_packet(
    runtime_adapter: Any,
    handle: Any,
    *,
    packet: Mapping[str, Any],
    fixture_contract: Mapping[str, Any] | None = None,
    quality_contract: Mapping[str, Any] | None = None,
    calc_snapshot: Mapping[str, Any] | None = None,
    input_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and apply exactly one agent-authored tree-only fixture packet.

    This is the parent-side write path for tree-only fixture work. It performs a
    fresh pre-apply observation, validates packet identity/cost/payload against
    that observation, applies the explicit agent-authored tree snapshot, and
    attaches the generic readback quality report.
    """

    packet_payload = _require_mapping(packet, "tree_only_fixture_authoring_packet")
    candidate_id = _require_non_empty_string(packet_payload.get("candidate_id"), "candidate_id")
    variant_id = _require_non_empty_string(packet_payload.get("variant_id"), "variant_id")
    pre_observation = inspect_tree_state(
        runtime_adapter,
        handle,
        candidate_id=candidate_id,
        variant_id=variant_id,
        action_id="tree_only_fixture_packet.pre_validate",
        input_refs=input_refs,
    )
    expected_observation = _equivalent_expected_observation_for_packet(pre_observation, packet_payload)
    validated_packet = validate_tree_only_fixture_authoring_packet(
        packet_payload,
        fixture_contract=fixture_contract,
        expected_observation=expected_observation,
    )
    if validated_packet.get("status") != "ready_to_apply":
        raise PoBTreeAuthoringToolError(
            "tree_only_fixture_authoring_packet_not_ready",
            "Only ready_to_apply tree-only fixture packets can be applied.",
            blockers=_mapping_sequence(validated_packet.get("blockers")) or [{"code": "tree_only_fixture_authoring_packet_not_ready"}],
        )
    trace = _require_mapping(validated_packet.get("direct_build_decision_trace"), "direct_build_decision_trace")
    actions = _mapping_sequence(trace.get("actions"))
    action_id = _require_non_empty_string(actions[0].get("action_id") if actions else None, "action_id")
    mutation_result = mutate_tree_state(
        runtime_adapter,
        handle,
        candidate_id=candidate_id,
        variant_id=variant_id,
        action_id=action_id,
        tree_payload=_require_mapping(validated_packet.get("tree_payload"), "tree_payload"),
        decision_trace=trace,
        expected_state_version=_require_non_empty_string(validated_packet.get("expected_state_version"), "expected_state_version"),
        observation_ref=_require_mapping(validated_packet.get("observation_ref"), "observation_ref"),
        fixture_contract=fixture_contract,
        input_refs=[*list(input_refs or []), pre_observation["output_refs"][0]],
        allow_source_pob_run_id=True,
    )
    quality_report = build_tree_authoring_readback_quality_report(
        validated_packet,
        mutation_result,
        calc_snapshot=calc_snapshot,
        quality_contract=quality_contract,
    )
    result = json.loads(json.dumps(mutation_result, ensure_ascii=False, sort_keys=True))
    result["quality_report"] = quality_report
    result["safe_next_actions"] = (
        ["publish_or_continue_repair"] if quality_report["status"] == "accepted" else ["repair_tree_authoring_packet", "inspect_tree_state"]
    )
    return result


def _equivalent_expected_observation_for_packet(
    current_observation: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Use live tree data while preserving the agent's original observation id.

    Agent packets are often authored from one read-only supervisor session and
    later applied in a fresh reopen session. The PoB state hash is the freshness
    authority; the observation id includes the run id and can differ across
    equivalent sessions.
    """

    current = _require_mapping(current_observation, "current_observation")
    observation_ref = packet.get("observation_ref")
    if not isinstance(observation_ref, Mapping):
        return current
    packet_state_version = _string(packet.get("expected_state_version"))
    ref_state_version = _string(observation_ref.get("state_version"))
    current_state_version = _string(current.get("state_version"))
    if not packet_state_version or packet_state_version != ref_state_version or packet_state_version != current_state_version:
        return current
    packet_observation_id = _string(observation_ref.get("observation_id") or observation_ref.get("ref_id"))
    if not packet_observation_id:
        return current
    equivalent = json.loads(json.dumps(current, ensure_ascii=False, sort_keys=True))
    equivalent["observation_id"] = packet_observation_id
    output_refs = equivalent.get("output_refs")
    if isinstance(output_refs, list) and output_refs and isinstance(output_refs[0], dict):
        output_refs[0]["ref_id"] = packet_observation_id
    return equivalent


def validate_tree_only_fixture_authoring_packet(
    packet: Mapping[str, Any],
    *,
    fixture_contract: Mapping[str, Any] | None = None,
    expected_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the strict architect output packet before parent apply.

    This is a parent-side intake gate. It does not select or improve the tree.
    """

    payload = _require_mapping(packet, "tree_only_fixture_authoring_packet")
    blockers = _tree_only_fixture_authoring_packet_blockers(
        payload,
        fixture_contract=fixture_contract,
        expected_observation=expected_observation,
    )
    if blockers:
        raise PoBTreeAuthoringToolError(
            "tree_only_fixture_authoring_packet_rejected",
            "Tree-only fixture authoring packet failed validation.",
            blockers=blockers,
        )
    return json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_tree_authoring_readback_quality_report(
    packet: Mapping[str, Any],
    mutation_result: Mapping[str, Any],
    *,
    calc_snapshot: Mapping[str, Any] | None = None,
    quality_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn PoB readback facts into generic repair blockers.

    This report deliberately does not choose nodes or judge build archetypes. It
    only compares the agent-authored packet against wrapper readback, optional
    calc metrics, and an explicit caller-provided quality contract.
    """

    packet_payload = _require_mapping(packet, "tree_only_fixture_authoring_packet")
    mutation_payload = _require_mapping(mutation_result, "mutation_result")
    contract = dict(quality_contract or {})
    budget_mode = _string(contract.get("budget_mode")) or "repair_delta"
    passive_budget_contract = (
        dict(contract.get("passive_budget_contract")) if isinstance(contract.get("passive_budget_contract"), Mapping) else {}
    )
    ascendancy_budget_contract = (
        dict(contract.get("ascendancy_budget_contract")) if isinstance(contract.get("ascendancy_budget_contract"), Mapping) else {}
    )
    before_accounting = _readback_tree_accounting(mutation_payload, "before")
    after_accounting = _readback_tree_accounting(mutation_payload, "after")
    after_tree_state = _readback_tree_state(mutation_payload, "after")
    normal_passive_count_after = _tree_accounting_normal_passive_count(after_accounting)
    ascendancy_node_count_after = _tree_accounting_count(
        after_accounting,
        count_key="ascendancy_node_count",
        ids_key="allocated_ascendancy_node_ids",
    )
    if ascendancy_node_count_after is None:
        ascendancy_node_count_after = _tree_accounting_count(
            after_tree_state,
            count_key="allocated_ascendancy_points",
            ids_key="allocated_ascendancy_node_ids",
        )
    ascendancy_notable_count_after = _tree_accounting_count(
        after_accounting,
        count_key="allocated_ascendancy_notable_count",
        ids_key="allocated_ascendancy_notable_node_ids",
    )
    if ascendancy_notable_count_after is None:
        ascendancy_notable_count_after = _tree_accounting_count(
            after_tree_state,
            count_key="allocated_ascendancy_notable_count",
            ids_key="allocated_ascendancy_notable_node_ids",
        )

    selected_target_ids = _tree_packet_selected_target_ids(packet_payload)
    before_ids = set(_int_sequence(_nested_get(mutation_payload, ("diff", "user_allocated_node_ids", "before_values"))))
    after_ids = set(_int_sequence(after_accounting.get("user_allocated_node_ids")))
    if not before_ids:
        before_ids = set(_int_sequence(before_accounting.get("user_allocated_node_ids")))
    added_ids = set(_int_sequence(_nested_get(mutation_payload, ("diff", "user_allocated_node_ids", "added"))))
    selected_added_ids = sorted(selected_target_ids & added_ids)
    missing_selected_ids = sorted(selected_target_ids - after_ids)
    connector_or_path_ids = sorted(added_ids - set(selected_added_ids))

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not selected_target_ids:
        warnings.append(
            {
                "code": "tree_quality_selected_targets_missing_from_decision_trace",
                "message": "Quality report cannot distinguish selected target nodes from route/path nodes.",
            }
        )
    if missing_selected_ids:
        blockers.append(
            {
                "code": "tree_quality_selected_targets_missing_after_readback",
                "missing_selected_target_node_ids": missing_selected_ids,
            }
        )

    identity_diff = {
        field_name: mutation_payload.get("diff", {}).get(field_name)
        for field_name in ("active_spec_id", "class_id", "ascendancy_id", "secondary_ascendancy_id")
        if isinstance(mutation_payload.get("diff"), Mapping) and field_name in mutation_payload.get("diff", {})
    }
    if identity_diff:
        blockers.append({"code": "tree_quality_locked_identity_changed", "identity_diff": identity_diff})

    if budget_mode not in _TREE_QUALITY_BUDGET_MODES:
        blockers.append(
            {
                "code": "tree_quality_budget_mode_unsupported",
                "observed": budget_mode,
                "expected": sorted(_TREE_QUALITY_BUDGET_MODES),
            }
        )
    elif budget_mode == "budgeted_full_tree":
        min_normal_passives = _first_non_negative_number(
            passive_budget_contract.get("min_normal_passive_count"),
            passive_budget_contract.get("target_normal_passive_count"),
            contract.get("min_normal_passive_count"),
            contract.get("target_normal_passive_count"),
        )
        max_normal_passives = _first_non_negative_number(
            passive_budget_contract.get("max_normal_passive_count"),
            contract.get("max_normal_passive_count"),
        )
        if min_normal_passives is None:
            blockers.append(
                {
                    "code": "tree_quality_passive_budget_contract_missing",
                    "budget_mode": budget_mode,
                    "expected_any": [
                        "passive_budget_contract.min_normal_passive_count",
                        "passive_budget_contract.target_normal_passive_count",
                    ],
                }
            )
        elif normal_passive_count_after is None or normal_passive_count_after < min_normal_passives:
            blockers.append(
                {
                    "code": "tree_quality_passive_budget_underfilled",
                    "budget_mode": budget_mode,
                    "observed": normal_passive_count_after,
                    "expected_min": min_normal_passives,
                }
            )
        if max_normal_passives is not None and normal_passive_count_after is not None and normal_passive_count_after > max_normal_passives:
            blockers.append(
                {
                    "code": "tree_quality_passive_budget_overfilled",
                    "budget_mode": budget_mode,
                    "observed": normal_passive_count_after,
                    "expected_max": max_normal_passives,
                }
            )

    min_ascendancy_nodes = _first_non_negative_number(
        ascendancy_budget_contract.get("min_ascendancy_node_count"),
        ascendancy_budget_contract.get("target_ascendancy_node_count"),
        contract.get("min_ascendancy_node_count"),
        contract.get("target_ascendancy_node_count"),
    )
    max_ascendancy_nodes = _first_non_negative_number(
        ascendancy_budget_contract.get("max_ascendancy_node_count"),
        contract.get("max_ascendancy_node_count"),
    )
    min_ascendancy_notables = _first_non_negative_number(
        ascendancy_budget_contract.get("min_ascendancy_notable_count"),
        ascendancy_budget_contract.get("target_ascendancy_notable_count"),
        contract.get("min_ascendancy_notable_count"),
        contract.get("target_ascendancy_notable_count"),
    )
    max_ascendancy_notables = _first_non_negative_number(
        ascendancy_budget_contract.get("max_ascendancy_notable_count"),
        contract.get("max_ascendancy_notable_count"),
    )
    if min_ascendancy_nodes is not None and (
        ascendancy_node_count_after is None or ascendancy_node_count_after < min_ascendancy_nodes
    ):
        blockers.append(
            {
                "code": "tree_quality_ascendancy_budget_underfilled",
                "budget_mode": budget_mode,
                "observed": ascendancy_node_count_after,
                "expected_min": min_ascendancy_nodes,
            }
        )
    if max_ascendancy_nodes is not None and ascendancy_node_count_after is not None and ascendancy_node_count_after > max_ascendancy_nodes:
        blockers.append(
            {
                "code": "tree_quality_ascendancy_budget_overfilled",
                "budget_mode": budget_mode,
                "observed": ascendancy_node_count_after,
                "expected_max": max_ascendancy_nodes,
            }
        )
    if min_ascendancy_notables is not None and (
        ascendancy_notable_count_after is None or ascendancy_notable_count_after < min_ascendancy_notables
    ):
        blockers.append(
            {
                "code": "tree_quality_ascendancy_notable_budget_underfilled",
                "budget_mode": budget_mode,
                "observed": ascendancy_notable_count_after,
                "expected_min": min_ascendancy_notables,
            }
        )
    if (
        max_ascendancy_notables is not None
        and ascendancy_notable_count_after is not None
        and ascendancy_notable_count_after > max_ascendancy_notables
    ):
        blockers.append(
            {
                "code": "tree_quality_ascendancy_notable_budget_overfilled",
                "budget_mode": budget_mode,
                "observed": ascendancy_notable_count_after,
                "expected_max": max_ascendancy_notables,
            }
        )

    max_added = _optional_non_negative_number(contract.get("max_added_user_allocated_node_count"))
    if max_added is not None and len(added_ids) > max_added:
        blockers.append(
            {
                "code": "tree_quality_added_passive_count_exceeded",
                "observed": len(added_ids),
                "expected_max": max_added,
            }
        )

    max_connector = _optional_non_negative_number(contract.get("max_connector_or_path_node_count"))
    if max_connector is not None and len(connector_or_path_ids) > max_connector:
        blockers.append(
            {
                "code": "tree_quality_connector_or_path_count_exceeded",
                "observed": len(connector_or_path_ids),
                "expected_max": max_connector,
                "connector_or_path_node_ids": connector_or_path_ids,
            }
        )

    max_added_per_target = _optional_non_negative_number(contract.get("max_added_nodes_per_selected_target"))
    selected_target_count = len(selected_target_ids)
    added_per_target = None if selected_target_count == 0 else len(added_ids) / selected_target_count
    if max_added_per_target is not None and added_per_target is not None and added_per_target > max_added_per_target:
        blockers.append(
            {
                "code": "tree_quality_added_nodes_per_selected_target_exceeded",
                "observed": added_per_target,
                "expected_max": max_added_per_target,
                "added_user_allocated_node_count": len(added_ids),
                "selected_target_count": selected_target_count,
            }
        )

    calc_warning_codes = _calc_warning_codes(calc_snapshot)
    fail_on_warning_codes = set(_string_sequence(contract.get("fail_on_warning_codes")))
    remaining_fail_warnings = sorted(code for code in calc_warning_codes if code in fail_on_warning_codes)
    if remaining_fail_warnings:
        blockers.append(
            {
                "code": "tree_quality_fail_warning_still_present",
                "warning_codes": remaining_fail_warnings,
            }
        )

    min_metrics = contract.get("min_baseline_metrics")
    if isinstance(min_metrics, Mapping):
        for metric_name, expected_min in sorted(min_metrics.items()):
            expected_numeric = _optional_number(expected_min)
            if expected_numeric is None:
                continue
            observed_numeric = _calc_metric(calc_snapshot, str(metric_name))
            if observed_numeric is None or observed_numeric < expected_numeric:
                blockers.append(
                    {
                        "code": "tree_quality_min_metric_not_met",
                        "metric": str(metric_name),
                        "observed": observed_numeric,
                        "expected_min": expected_numeric,
                    }
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": TREE_READBACK_QUALITY_REPORT_RECORD_KIND,
        "status": "accepted" if not blockers else "rejected",
        "candidate_id": packet_payload.get("candidate_id"),
        "variant_id": packet_payload.get("variant_id"),
        "pob_run_id": packet_payload.get("pob_run_id"),
        "input_refs": [
            {
                "ref_kind": TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND,
                "variant_id": packet_payload.get("variant_id"),
            },
            {
                "ref_kind": TREE_MUTATION_RESULT_RECORD_KIND,
                "result_id": mutation_payload.get("result_id"),
                "state_version": mutation_payload.get("state_version"),
            },
        ],
        "summary": {
            "budget_mode": budget_mode,
            "normal_passive_count_after": normal_passive_count_after,
            "ascendancy_node_count_after": ascendancy_node_count_after,
            "ascendancy_notable_count_after": ascendancy_notable_count_after,
            "selected_target_node_count": selected_target_count,
            "selected_target_node_ids": sorted(selected_target_ids),
            "added_user_allocated_node_count": len(added_ids),
            "selected_targets_added_count": len(selected_added_ids),
            "connector_or_path_node_count": len(connector_or_path_ids),
            "added_nodes_per_selected_target": added_per_target,
            "calc_warning_codes": calc_warning_codes,
        },
        "data": {
            "selected_target_node_ids": sorted(selected_target_ids),
            "selected_added_node_ids": selected_added_ids,
            "connector_or_path_node_ids": connector_or_path_ids,
            "missing_selected_target_node_ids": missing_selected_ids,
            "quality_contract": json.loads(json.dumps(contract, ensure_ascii=False, sort_keys=True)),
            "passive_budget_contract": json.loads(json.dumps(passive_budget_contract, ensure_ascii=False, sort_keys=True)),
            "ascendancy_budget_contract": json.loads(json.dumps(ascendancy_budget_contract, ensure_ascii=False, sort_keys=True)),
        },
        "warnings": warnings,
        "blockers": blockers,
        "safe_next_actions": ["repair_tree_authoring_packet", "inspect_tree_state"],
        "trusted_input_boundary": "agent_packet_plus_pinned_pob_readback",
        "untrusted_text_fields": [],
    }


def _tree_only_fixture_authoring_packet_blockers(
    packet: Mapping[str, Any],
    *,
    fixture_contract: Mapping[str, Any] | None,
    expected_observation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if packet.get("schema_version") != SCHEMA_VERSION:
        blockers.append({"code": "tree_authoring_packet_schema_version_unsupported", "observed": packet.get("schema_version"), "expected": SCHEMA_VERSION})
    if packet.get("record_kind") != TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND:
        blockers.append(
            {
                "code": "tree_authoring_packet_wrong_record_kind",
                "observed": packet.get("record_kind"),
                "expected": TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND,
            }
        )
    status = _string(packet.get("status"))
    if status not in _TREE_ONLY_FIXTURE_PACKET_STATUSES:
        blockers.append({"code": "tree_authoring_packet_wrong_status", "observed": status, "expected": sorted(_TREE_ONLY_FIXTURE_PACKET_STATUSES)})
        return blockers

    forbidden = sorted(field for field in _FORBIDDEN_PUBLICATION_FIELDS if field in packet)
    if forbidden:
        blockers.append({"code": "tree_authoring_packet_contains_publication_payload", "observed": forbidden, "expected": []})

    packet_blockers = packet.get("blockers")
    if status == "blocked":
        if not _mapping_sequence(packet_blockers):
            blockers.append({"code": "blocked_tree_authoring_packet_missing_blockers", "expected_minimum": 1})
        return blockers
    if packet_blockers not in ([], (), None):
        blockers.append({"code": "ready_tree_authoring_packet_has_blockers", "observed": packet_blockers, "expected": []})

    required_top_strings = ("fixture_ref", "candidate_id", "variant_id", "pob_run_id", "expected_state_version")
    for field_name in required_top_strings:
        if not _string(packet.get(field_name)):
            blockers.append({"code": "tree_authoring_packet_missing_field", "field": field_name})

    if _string_sequence(packet.get("authored_surfaces")) != ["tree"]:
        blockers.append({"code": "tree_authoring_packet_authored_surfaces_not_tree_only", "observed": packet.get("authored_surfaces"), "expected": ["tree"]})

    observation_ref = packet.get("observation_ref")
    if not isinstance(observation_ref, Mapping):
        blockers.append({"code": "tree_authoring_packet_missing_observation_ref"})
        observation_id = ""
        observation_state_version = ""
    else:
        observation_id = _string(observation_ref.get("observation_id") or observation_ref.get("ref_id"))
        observation_state_version = _string(observation_ref.get("state_version"))
        if not observation_id or not observation_state_version:
            blockers.append({"code": "tree_authoring_packet_incomplete_observation_ref"})
        if observation_ref.get("ref_kind") not in (None, TREE_STATE_OBSERVATION_RECORD_KIND):
            blockers.append({"code": "tree_authoring_packet_wrong_observation_ref_kind", "observed": observation_ref.get("ref_kind"), "expected": TREE_STATE_OBSERVATION_RECORD_KIND})
        if observation_state_version and observation_state_version != _string(packet.get("expected_state_version")):
            blockers.append(
                {
                    "code": "tree_authoring_packet_state_version_mismatch",
                    "observed": {
                        "observation_ref.state_version": observation_state_version,
                        "expected_state_version": _string(packet.get("expected_state_version")),
                    },
                }
            )

    if expected_observation is not None:
        expected_obs = _require_mapping(expected_observation, "expected_observation")
        expected_observation_id = _string(expected_obs.get("observation_id"))
        expected_state_version = _string(expected_obs.get("state_version"))
        if observation_id != expected_observation_id or observation_state_version != expected_state_version:
            blockers.append(
                {
                    "code": "tree_authoring_packet_not_based_on_expected_observation",
                    "observed": {"observation_id": observation_id, "state_version": observation_state_version},
                    "expected": {"observation_id": expected_observation_id, "state_version": expected_state_version},
                }
            )

    if fixture_contract is not None:
        blockers.extend(_fixture_contract_blockers(fixture_contract, packet))

    trace = packet.get("direct_build_decision_trace")
    if not isinstance(trace, Mapping):
        blockers.append({"code": "tree_authoring_packet_missing_decision_trace", "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND})
    else:
        blockers.extend(
            _tree_only_fixture_trace_blockers(
                trace,
                packet=packet,
                observation_id=observation_id,
                observation_state_version=observation_state_version,
            )
        )

    tree_payload = packet.get("tree_payload")
    if not isinstance(tree_payload, Mapping):
        blockers.append({"code": "tree_authoring_packet_missing_tree_payload"})
    else:
        blockers.extend(_tree_only_fixture_payload_blockers(tree_payload))
        if isinstance(trace, Mapping):
            blockers.extend(
                _tree_payload_expected_observation_consistency_blockers(
                    packet=packet,
                    trace=trace,
                    tree_payload=tree_payload,
                    expected_observation=expected_observation,
                )
            )
    return blockers


def _tree_only_fixture_trace_blockers(
    trace: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    observation_id: str,
    observation_state_version: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if trace.get("record_kind") != DIRECT_BUILD_DECISION_TRACE_RECORD_KIND:
        blockers.append({"code": "missing_agent_decision_trace", "observed": trace.get("record_kind"), "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND})
    for field_name in ("candidate_id", "variant_id", "pob_run_id", "fixture_ref"):
        packet_value = _string(packet.get(field_name))
        trace_value = _string(trace.get(field_name))
        if packet_value and trace_value and packet_value != trace_value:
            blockers.append(
                {
                    "code": f"tree_authoring_packet_trace_{field_name}_mismatch",
                    "observed": trace_value,
                    "expected": packet_value,
                }
            )
    if _string_sequence(trace.get("authored_surfaces")) != ["tree"]:
        blockers.append({"code": "tree_authoring_packet_trace_not_tree_only", "observed": trace.get("authored_surfaces"), "expected": ["tree"]})

    decisions = _mapping_sequence(trace.get("decisions"))
    actions = _mapping_sequence(trace.get("actions"))
    observations = _mapping_sequence(trace.get("observations"))
    if not decisions:
        blockers.append({"code": "agent_decision_trace_missing_decisions", "expected_minimum": 1})
    if len(actions) != 1:
        blockers.append({"code": "tree_authoring_packet_requires_one_tree_action", "observed": len(actions), "expected": 1})
    if not observations:
        blockers.append({"code": "agent_decision_trace_missing_observations", "expected_minimum": 1})
    elif _find_by_id(observations, "observation_id", observation_id) is None:
        blockers.append({"code": "tree_action_observation_ref_not_in_trace", "observed": observation_id})

    if actions:
        action = actions[0]
        if _string(action.get("target_mutation_kind") or action.get("mutation_kind")) != "tree":
            blockers.append({"code": "tree_action_wrong_mutation_kind", "observed": action.get("target_mutation_kind"), "expected": "tree"})
        if not _string(action.get("action_id")):
            blockers.append({"code": "tree_action_missing_action_id"})
        if not _string(action.get("agent_rationale") or action.get("rationale")):
            blockers.append({"code": "tree_action_missing_agent_rationale"})
        action_refs = _mapping_sequence(action.get("input_refs"))
        if not _contains_observation_ref(action_refs, observation_id):
            blockers.append({"code": "tree_action_missing_input_observation_ref", "expected": observation_id})
        if observation_state_version and not any(_string(ref.get("state_version")) == observation_state_version for ref in action_refs):
            blockers.append({"code": "tree_action_missing_input_state_version", "expected": observation_state_version})
        decision_ref = _string(action.get("llm_decision_ref") or action.get("decision_ref"))
        if _find_by_id(decisions, "decision_id", decision_ref) is None:
            blockers.append({"code": "missing_tree_mutation_decision", "expected_decision_ref": decision_ref})

    for decision in decisions:
        blockers.extend(_tree_only_fixture_decision_blockers(decision, observation_id=observation_id, observation_state_version=observation_state_version))
    return blockers


def _tree_only_fixture_decision_blockers(
    decision: Mapping[str, Any],
    *,
    observation_id: str,
    observation_state_version: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    decision_id = _string(decision.get("decision_id"))
    if not decision_id:
        blockers.append({"code": "tree_decision_missing_decision_id"})
    if not _string(decision.get("rationale") or decision.get("agent_rationale")):
        blockers.append({"code": "tree_decision_missing_rationale", "decision_id": decision_id})
    if not _string(decision.get("value_hypothesis")):
        blockers.append({"code": "tree_decision_missing_value_hypothesis", "decision_id": decision_id})
    readback = decision.get("expected_readback_check")
    if not isinstance(readback, Mapping):
        blockers.append({"code": "tree_decision_missing_expected_readback_check", "decision_id": decision_id})
    else:
        if _string(readback.get("must_start_from_observation_id")) not in {"", observation_id}:
            blockers.append({"code": "tree_decision_readback_observation_mismatch", "decision_id": decision_id})
        if _string(readback.get("must_match_pre_apply_state_version")) not in {"", observation_state_version}:
            blockers.append({"code": "tree_decision_readback_state_version_mismatch", "decision_id": decision_id})
        if not isinstance(readback.get("expected_tree_accounting_delta"), Mapping):
            blockers.append({"code": "tree_decision_missing_expected_tree_accounting_delta", "decision_id": decision_id})
        else:
            accounting_delta = readback.get("expected_tree_accounting_delta")
            if _optional_number(accounting_delta.get("normal_passive_delta")) is None:
                blockers.append({"code": "tree_decision_missing_expected_normal_passive_delta", "decision_id": decision_id})
            if _optional_number(accounting_delta.get("ascendancy_node_delta")) is None:
                blockers.append({"code": "tree_decision_missing_expected_ascendancy_node_delta", "decision_id": decision_id})
            for field_name in ("added_user_allocated_node_ids", "removed_user_allocated_node_ids"):
                if not isinstance(accounting_delta.get(field_name), Sequence) or isinstance(accounting_delta.get(field_name), (str, bytes)):
                    blockers.append({"code": "tree_decision_missing_expected_itemized_node_delta", "decision_id": decision_id, "field": field_name})
        present_sets = readback.get("expected_present_node_sets")
        if not isinstance(present_sets, Mapping):
            blockers.append({"code": "tree_decision_missing_expected_present_node_sets", "decision_id": decision_id})
        elif not _int_sequence(present_sets.get("selected_target_node_ids")):
            blockers.append({"code": "tree_decision_missing_selected_target_node_ids", "decision_id": decision_id})

    choice_cost = decision.get("choice_cost")
    if not isinstance(choice_cost, Mapping):
        blockers.append({"code": "tree_decision_missing_choice_cost", "decision_id": decision_id})
        return blockers
    if _string(choice_cost.get("scarce_resource")) not in {"passive_points", "ascendancy_points", "mastery_choice"}:
        blockers.append({"code": "tree_decision_missing_passive_resource_cost", "decision_id": decision_id})
    resource_cost = choice_cost.get("resource_cost")
    if not isinstance(resource_cost, Mapping):
        blockers.append({"code": "tree_decision_missing_resource_cost", "decision_id": decision_id})
    else:
        if _optional_number(resource_cost.get("passive_points")) is None:
            blockers.append({"code": "tree_decision_missing_passive_point_cost", "decision_id": decision_id})
    if not _mapping_sequence(choice_cost.get("value_evidence_refs")):
        blockers.append({"code": "tree_decision_missing_value_evidence_refs", "decision_id": decision_id})
    if not _mapping_sequence(choice_cost.get("rejected_alternatives")) and not _string(choice_cost.get("no_alternative_reason")):
        blockers.append({"code": "tree_decision_missing_alternative_or_no_alternative_reason", "decision_id": decision_id})
    return blockers


def _tree_only_fixture_payload_blockers(tree_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    keys = set(tree_payload)
    missing = sorted(_FULL_TREE_PAYLOAD_KEYS - keys)
    extra = sorted(keys - _FULL_TREE_PAYLOAD_KEYS)
    if missing:
        blockers.append({"code": "tree_authoring_packet_tree_payload_not_full_snapshot", "missing": missing})
    if extra:
        code = "tree_local_anoint_not_allowed" if "anoint_allocations" in extra else "unsupported_tree_payload_field"
        blockers.append({"code": code, "observed": extra, "expected": sorted(_FULL_TREE_PAYLOAD_KEYS)})
    if not _string(tree_payload.get("active_spec_id")):
        blockers.append({"code": "tree_payload_missing_active_spec_id"})
    for field_name in ("class_id", "ascendancy_id"):
        value = tree_payload.get(field_name)
        if _string(value) == "" and not (isinstance(value, int) and not isinstance(value, bool)):
            blockers.append({"code": "tree_payload_missing_identity_field", "field": field_name})
    for field_name in _TREE_PAYLOAD_INT_LIST_FIELDS:
        values = tree_payload.get(field_name)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            blockers.append({"code": "tree_payload_field_must_be_int_list", "field": field_name})
            continue
        normalized = _int_sequence(values)
        if len(normalized) != len(values) or len(set(normalized)) != len(normalized):
            blockers.append({"code": "tree_payload_invalid_int_list", "field": field_name})
    for field_name in _TREE_PAYLOAD_STRING_LIST_FIELDS:
        values = tree_payload.get(field_name)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(_string_sequence(values)) != len(values):
            blockers.append({"code": "tree_payload_field_must_be_string_list", "field": field_name})
    for field_name in _TREE_PAYLOAD_OBJECT_LIST_FIELDS:
        if not isinstance(tree_payload.get(field_name), Sequence) or isinstance(tree_payload.get(field_name), (str, bytes)):
            blockers.append({"code": "tree_payload_field_must_be_object_list", "field": field_name})
        elif len(_mapping_sequence(tree_payload.get(field_name))) != len(tree_payload.get(field_name)):
            blockers.append({"code": "tree_payload_field_must_be_object_list", "field": field_name})
    return blockers


def _load_passive_tree_corpus_records(corpus_root: Path, families: Sequence[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for family in _string_sequence(families):
        if family not in {"passives", "keystones", "masteries"}:
            raise PoBTreeAuthoringToolError(
                "invalid_passive_tree_query",
                f"Unsupported passive-tree corpus family: {family}",
            )
        path = corpus_root / f"{family}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PoBTreeAuthoringToolError(
                "passive_tree_corpus_unavailable",
                f"Passive-tree corpus file is unavailable: {path}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise PoBTreeAuthoringToolError(
                "passive_tree_corpus_invalid",
                f"Passive-tree corpus file is invalid JSON: {path}",
            ) from exc
        family_records = payload.get("records") if isinstance(payload, Mapping) else None
        if not isinstance(family_records, Sequence) or isinstance(family_records, (str, bytes)):
            raise PoBTreeAuthoringToolError(
                "passive_tree_corpus_invalid",
                f"Passive-tree corpus file must expose records[]: {path}",
            )
        for row in family_records:
            if isinstance(row, Mapping):
                records.append({**dict(row), "_family": family})
    return records


def _passive_tree_graph(records: Sequence[Mapping[str, Any]]) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    known_ids = {node_id for record in records for node_id in _int_sequence([record.get("node_id")])}
    for record in records:
        node_values = _int_sequence([record.get("node_id")])
        if not node_values:
            continue
        node_id = node_values[0]
        graph.setdefault(node_id, set())
        for neighbor_id in [*_int_sequence(record.get("incoming_node_ids")), *_int_sequence(record.get("outgoing_node_ids"))]:
            if neighbor_id not in known_ids:
                continue
            graph.setdefault(neighbor_id, set()).add(node_id)
            graph[node_id].add(neighbor_id)
    return graph


def _shortest_path_from_any(graph: Mapping[int, set[int]], source_ids: set[int], target_id: int) -> list[int] | None:
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
            next_path = [*path, neighbor_id]
            if neighbor_id == target_id:
                return next_path
            visited.add(neighbor_id)
            queue.append((neighbor_id, next_path))
    return None


def _passive_record_search_text(record: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for field_name in ("name", "stats", "reminder_text", "flavour_text"):
        value = record.get(field_name)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    for mastery_effect in _mapping_sequence(record.get("mastery_effects")):
        parts.extend(_string_sequence(mastery_effect.get("stats")))
        parts.extend(_string_sequence(mastery_effect.get("reminder_text")))
    return "\n".join(parts).lower()


def _passive_record_target_kind(record: Mapping[str, Any]) -> str:
    if record.get("is_mastery") is True:
        return "mastery"
    if record.get("is_keystone") is True:
        return "keystone"
    if record.get("is_notable") is True:
        return "notable"
    return "small_passive"


def _passive_record_stats(record: Mapping[str, Any]) -> list[str]:
    return _string_sequence(record.get("stats"))


def _passive_record_mastery_effects(record: Mapping[str, Any], *, node_id: int) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for effect in _mapping_sequence(record.get("mastery_effects")):
        effect_id = effect.get("effect_id")
        if isinstance(effect_id, bool) or not isinstance(effect_id, int):
            continue
        effects.append(
            {
                "effect_id": effect_id,
                "selection_token": f"{node_id}:{effect_id}",
                "stats": _string_sequence(effect.get("stats")),
                "reminder_text": _string_sequence(effect.get("reminder_text")),
            }
        )
    return effects


def _tree_payload_expected_observation_consistency_blockers(
    *,
    packet: Mapping[str, Any],
    trace: Mapping[str, Any],
    tree_payload: Mapping[str, Any],
    expected_observation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if expected_observation is None:
        return []
    observation = _require_mapping(expected_observation, "expected_observation")
    observed_tree_state = _nested_get(observation, ("data", "tree_state"))
    if not isinstance(observed_tree_state, Mapping):
        return []

    blockers: list[dict[str, Any]] = []
    for field_name in ("active_spec_id", "class_id", "ascendancy_id", "secondary_ascendancy_id"):
        observed_value = observed_tree_state.get(field_name)
        if tree_payload.get(field_name) != observed_value:
            blockers.append(
                {
                    "code": "tree_authoring_packet_tree_payload_identity_mismatch",
                    "field": field_name,
                    "observed": tree_payload.get(field_name),
                    "expected": observed_value,
                }
            )

    before_accounting = observation.get("data", {}).get("tree_accounting") if isinstance(observation.get("data"), Mapping) else None
    if not isinstance(before_accounting, Mapping):
        before_accounting = _tree_accounting(observed_tree_state)
    before_user_ids = set(_int_sequence(before_accounting.get("user_allocated_node_ids")))
    before_ascendancy_ids = set(_int_sequence(before_accounting.get("allocated_ascendancy_node_ids")))
    before_mastery_effect_ids = set(_string_sequence(before_accounting.get("mastery_effect_ids")))
    if not before_mastery_effect_ids:
        before_mastery_effect_ids = set(_string_sequence(observed_tree_state.get("mastery_effect_ids")))
    after_user_ids = set(_int_sequence(tree_payload.get("user_allocated_node_ids")))
    after_ascendancy_ids = set(_int_sequence(tree_payload.get("ascendancy_node_ids")))
    after_mastery_effect_ids = set(_string_sequence(tree_payload.get("mastery_effect_ids")))
    before_normal_count = len(before_user_ids - before_ascendancy_ids)
    after_normal_count = len(after_user_ids - after_ascendancy_ids)
    actual_delta = {
        "normal_passive_delta": after_normal_count - before_normal_count,
        "ascendancy_node_delta": len(after_ascendancy_ids) - len(before_ascendancy_ids),
        "added_user_allocated_node_ids": sorted(after_user_ids - before_user_ids),
        "removed_user_allocated_node_ids": sorted(before_user_ids - after_user_ids),
        "added_mastery_effect_ids": sorted(after_mastery_effect_ids - before_mastery_effect_ids),
        "removed_mastery_effect_ids": sorted(before_mastery_effect_ids - after_mastery_effect_ids),
    }

    action = _mapping_sequence(trace.get("actions"))[0] if _mapping_sequence(trace.get("actions")) else None
    decision = None
    if action is not None:
        decision_ref = _string(action.get("llm_decision_ref") or action.get("decision_ref"))
        decision = _find_by_id(_mapping_sequence(trace.get("decisions")), "decision_id", decision_ref)
    if decision is None:
        return blockers

    readback = decision.get("expected_readback_check")
    if isinstance(readback, Mapping):
        expected_delta = readback.get("expected_tree_accounting_delta")
        if isinstance(expected_delta, Mapping):
            for field_name in ("normal_passive_delta", "ascendancy_node_delta"):
                expected_value = _optional_number(expected_delta.get(field_name))
                if expected_value is not None and expected_value != actual_delta[field_name]:
                    blockers.append(
                        {
                            "code": "tree_authoring_packet_accounting_delta_mismatch",
                            "field": field_name,
                            "observed": actual_delta[field_name],
                            "expected": expected_value,
                        }
                    )
            for field_name in ("added_user_allocated_node_ids", "removed_user_allocated_node_ids"):
                if field_name not in expected_delta:
                    continue
                expected_ids = sorted(_int_sequence(expected_delta.get(field_name)))
                if expected_ids != actual_delta[field_name]:
                    blockers.append(
                        {
                            "code": "tree_authoring_packet_itemized_delta_mismatch",
                            "field": field_name,
                            "observed": actual_delta[field_name],
                            "expected": expected_ids,
                        }
                    )
            for field_name in ("added_mastery_effect_ids", "removed_mastery_effect_ids"):
                if field_name not in expected_delta:
                    continue
                expected_effect_ids = sorted(_string_sequence(expected_delta.get(field_name)))
                if expected_effect_ids != actual_delta[field_name]:
                    blockers.append(
                        {
                            "code": "tree_authoring_packet_mastery_delta_mismatch",
                            "field": field_name,
                            "observed": actual_delta[field_name],
                            "expected": expected_effect_ids,
                        }
                    )
        present_sets = readback.get("expected_present_node_sets")
        if isinstance(present_sets, Mapping):
            selected_target_ids = set(_int_sequence(present_sets.get("selected_target_node_ids")))
            missing_selected = sorted(selected_target_ids - after_user_ids - after_ascendancy_ids)
            if missing_selected:
                blockers.append(
                    {
                        "code": "tree_authoring_packet_selected_targets_missing_from_payload",
                        "missing_selected_target_node_ids": missing_selected,
                    }
                )
            expected_mastery_effect_ids = set(_string_sequence(present_sets.get("mastery_effect_ids")))
            missing_mastery_effect_ids = sorted(expected_mastery_effect_ids - after_mastery_effect_ids)
            if missing_mastery_effect_ids:
                blockers.append(
                    {
                        "code": "tree_authoring_packet_expected_mastery_effect_missing_from_payload",
                        "missing_mastery_effect_ids": missing_mastery_effect_ids,
                    }
                )

    selected_target_ids = _tree_packet_selected_target_ids(packet)
    missing_selected = sorted(selected_target_ids - after_user_ids - after_ascendancy_ids)
    if missing_selected:
        blockers.append(
            {
                "code": "tree_authoring_packet_selected_targets_missing_from_payload",
                "missing_selected_target_node_ids": missing_selected,
            }
        )
    if action is not None:
        action_selected_target_ids = set(_int_sequence(action.get("selected_target_node_ids")))
        if action_selected_target_ids and action_selected_target_ids != selected_target_ids:
            blockers.append(
                {
                    "code": "tree_authoring_packet_action_selected_targets_mismatch",
                    "observed": sorted(action_selected_target_ids),
                    "expected": sorted(selected_target_ids),
                }
            )
        if "added_user_allocated_node_ids" in action:
            action_added_ids = sorted(_int_sequence(action.get("added_user_allocated_node_ids")))
            if action_added_ids != actual_delta["added_user_allocated_node_ids"]:
                blockers.append(
                    {
                        "code": "tree_authoring_packet_action_added_nodes_mismatch",
                        "observed": action_added_ids,
                        "expected": actual_delta["added_user_allocated_node_ids"],
                    }
                )
        action_mastery_effect_ids = set(_string_sequence(action.get("selected_mastery_effect_ids")))
        missing_action_mastery_effect_ids = sorted(action_mastery_effect_ids - after_mastery_effect_ids)
        if missing_action_mastery_effect_ids:
            blockers.append(
                {
                    "code": "tree_authoring_packet_action_mastery_effect_missing_from_payload",
                    "missing_mastery_effect_ids": missing_action_mastery_effect_ids,
                }
            )

    choice_cost = decision.get("choice_cost")
    if isinstance(choice_cost, Mapping):
        resource_cost = choice_cost.get("resource_cost")
        if isinstance(resource_cost, Mapping) and _string(choice_cost.get("scarce_resource")) == "passive_points":
            passive_points = _optional_number(resource_cost.get("passive_points"))
            if passive_points is None:
                blockers.append({"code": "tree_authoring_packet_missing_passive_point_cost"})
            elif not actual_delta["removed_user_allocated_node_ids"] and passive_points != actual_delta["normal_passive_delta"]:
                blockers.append(
                    {
                        "code": "tree_authoring_packet_passive_point_cost_mismatch",
                        "observed": passive_points,
                        "expected": actual_delta["normal_passive_delta"],
                    }
                )
            for field_name in ("added_user_allocated_node_ids", "removed_user_allocated_node_ids"):
                if field_name not in resource_cost:
                    continue
                expected_ids = sorted(_int_sequence(resource_cost.get(field_name)))
                if expected_ids != actual_delta[field_name]:
                    blockers.append(
                        {
                            "code": "tree_authoring_packet_resource_cost_delta_mismatch",
                            "field": field_name,
                            "observed": expected_ids,
                            "expected": actual_delta[field_name],
                        }
                    )
            mastery_replacements = _mapping_sequence(resource_cost.get("mastery_effect_replacements"))
            if mastery_replacements:
                replacement_removed = sorted(_string(row.get("before")) for row in mastery_replacements if _string(row.get("before")))
                replacement_added = sorted(_string(row.get("after")) for row in mastery_replacements if _string(row.get("after")))
                if replacement_removed != actual_delta["removed_mastery_effect_ids"] or replacement_added != actual_delta["added_mastery_effect_ids"]:
                    blockers.append(
                        {
                            "code": "tree_authoring_packet_mastery_replacement_delta_mismatch",
                            "observed": {
                                "removed_mastery_effect_ids": replacement_removed,
                                "added_mastery_effect_ids": replacement_added,
                            },
                            "expected": {
                                "removed_mastery_effect_ids": actual_delta["removed_mastery_effect_ids"],
                                "added_mastery_effect_ids": actual_delta["added_mastery_effect_ids"],
                            },
                        }
                    )
                declared_mastery_delta = True
            else:
                declared_mastery_delta = False
            expected_delta = readback.get("expected_tree_accounting_delta") if isinstance(readback, Mapping) else None
            if isinstance(expected_delta, Mapping):
                declared_mastery_delta = declared_mastery_delta or (
                    "added_mastery_effect_ids" in expected_delta or "removed_mastery_effect_ids" in expected_delta
                )
            if (actual_delta["added_mastery_effect_ids"] or actual_delta["removed_mastery_effect_ids"]) and not declared_mastery_delta:
                blockers.append(
                    {
                        "code": "tree_authoring_packet_undeclared_mastery_delta",
                        "observed": {
                            "removed_mastery_effect_ids": actual_delta["removed_mastery_effect_ids"],
                            "added_mastery_effect_ids": actual_delta["added_mastery_effect_ids"],
                        },
                    }
                )
    return blockers


def _validate_tree_mutation_request(
    *,
    candidate_id: str,
    variant_id: str,
    pob_run_id: str,
    action_id: str,
    decision_trace: Mapping[str, Any],
    expected_state_version: str,
    observed_state_version: str,
    observation_ref: Mapping[str, Any],
    fixture_contract: Mapping[str, Any] | None,
    allow_source_pob_run_id: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(decision_trace, Mapping):
        return [{"code": "missing_agent_decision_trace", "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND}]

    record_kind = decision_trace.get("record_kind")
    if record_kind in _FORBIDDEN_SCRIPT_AUTHORED_RECORD_KINDS:
        blockers.append(
            {
                "code": "script_authored_direct_build_payload",
                "observed": record_kind,
                "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND,
            }
        )
    elif record_kind != DIRECT_BUILD_DECISION_TRACE_RECORD_KIND:
        blockers.append(
            {
                "code": "missing_agent_decision_trace",
                "observed": record_kind,
                "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND,
            }
        )

    if _string(decision_trace.get("candidate_id")) not in {"", candidate_id}:
        blockers.append({"code": "decision_trace_candidate_mismatch", "observed": decision_trace.get("candidate_id")})
    if _string(decision_trace.get("variant_id")) not in {"", variant_id}:
        blockers.append({"code": "decision_trace_variant_mismatch", "observed": decision_trace.get("variant_id")})
    if not allow_source_pob_run_id and _string(decision_trace.get("pob_run_id")) not in {"", pob_run_id}:
        blockers.append({"code": "decision_trace_pob_run_mismatch", "observed": decision_trace.get("pob_run_id")})

    observation_state_version = _string(observation_ref.get("state_version")) if isinstance(observation_ref, Mapping) else ""
    observation_id = _string(observation_ref.get("observation_id")) if isinstance(observation_ref, Mapping) else ""
    if not observation_id or not observation_state_version:
        blockers.append(
            {
                "code": "missing_fresh_tree_observation",
                "expected": {"observation_id": "non-empty", "state_version": observed_state_version},
            }
        )
    if _string(expected_state_version) != observed_state_version or observation_state_version != observed_state_version:
        blockers.append(
            {
                "code": "stale_tree_observation",
                "observed": {
                    "expected_state_version": _string(expected_state_version),
                    "observation_state_version": observation_state_version,
                    "current_state_version": observed_state_version,
                },
                "expected": observed_state_version,
            }
        )

    if fixture_contract is not None:
        blockers.extend(_fixture_contract_blockers(fixture_contract, decision_trace))

    decisions = _mapping_sequence(decision_trace.get("decisions"))
    actions = _mapping_sequence(decision_trace.get("actions"))
    observations = _mapping_sequence(decision_trace.get("observations"))
    if not decisions:
        blockers.append({"code": "agent_decision_trace_missing_decisions", "expected_minimum": 1})
    if not actions:
        blockers.append({"code": "agent_decision_trace_missing_actions", "expected_minimum": 1})
    if not observations:
        blockers.append({"code": "agent_decision_trace_missing_observations", "expected_minimum": 1})
    elif _find_by_id(observations, "observation_id", observation_id) is None:
        blockers.append(
            {
                "code": "tree_action_observation_ref_not_in_trace",
                "observed": observation_id,
                "expected": [str(row.get("observation_id")) for row in observations],
            }
        )

    action = _find_by_id(actions, "action_id", action_id)
    if action is None:
        blockers.append({"code": "missing_tree_mutation_action", "expected_action_id": action_id})
        return blockers
    action_kind = _string(action.get("target_mutation_kind") or action.get("mutation_kind"))
    if action_kind != "tree":
        blockers.append({"code": "tree_action_wrong_mutation_kind", "observed": action_kind, "expected": "tree"})
    if _string(action.get("agent_rationale") or action.get("rationale")) == "":
        blockers.append({"code": "tree_action_missing_agent_rationale"})

    action_input_refs = _mapping_sequence(action.get("input_refs"))
    if not _contains_observation_ref(action_input_refs, observation_id):
        blockers.append(
            {
                "code": "tree_action_missing_input_observation_ref",
                "observed": [_string(ref.get("ref_id") or ref.get("observation_id")) for ref in action_input_refs],
                "expected": observation_id,
            }
        )

    decision_ref = _string(action.get("llm_decision_ref") or action.get("decision_ref"))
    decision = _find_by_id(decisions, "decision_id", decision_ref)
    if decision is None:
        blockers.append({"code": "missing_tree_mutation_decision", "expected_decision_ref": decision_ref})
        return blockers
    if _string(decision.get("rationale") or decision.get("agent_rationale")) == "":
        blockers.append({"code": "tree_decision_missing_rationale", "decision_id": decision_ref})

    choice_cost = decision.get("choice_cost")
    if not isinstance(choice_cost, Mapping):
        blockers.append({"code": "tree_decision_missing_choice_cost", "decision_id": decision_ref})
    else:
        if _string(choice_cost.get("scarce_resource")) not in {"passive_points", "ascendancy_points", "mastery_choice"}:
            blockers.append(
                {
                    "code": "tree_decision_missing_passive_resource_cost",
                    "decision_id": decision_ref,
                    "expected": ["passive_points", "ascendancy_points", "mastery_choice"],
                }
            )
        if not _mapping_sequence(choice_cost.get("value_evidence_refs")):
            blockers.append({"code": "tree_decision_missing_value_evidence_refs", "decision_id": decision_ref})
        alternatives = choice_cost.get("rejected_alternatives")
        no_alternative_reason = _string(choice_cost.get("no_alternative_reason"))
        if not _mapping_sequence(alternatives) and not no_alternative_reason:
            blockers.append({"code": "tree_decision_missing_alternative_or_no_alternative_reason", "decision_id": decision_ref})
    return blockers


def _fixture_contract_blockers(fixture_contract: Mapping[str, Any], decision_trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    editable_surfaces = set(_string_sequence(fixture_contract.get("editable_surfaces")))
    locked_surfaces = set(_string_sequence(fixture_contract.get("locked_surfaces")))
    if "tree" not in editable_surfaces:
        blockers.append({"code": "fixture_tree_surface_not_editable", "editable_surfaces": sorted(editable_surfaces)})
    authored_surfaces = set(_string_sequence(decision_trace.get("authored_surfaces")))
    invalid_claims = sorted(authored_surfaces & locked_surfaces)
    if invalid_claims:
        blockers.append(
            {
                "code": "fixture_authorship_violation",
                "observed": invalid_claims,
                "locked_surfaces": sorted(locked_surfaces),
            }
        )
    return blockers


def _tree_packet_selected_target_ids(packet: Mapping[str, Any]) -> set[int]:
    trace = packet.get("direct_build_decision_trace")
    if not isinstance(trace, Mapping):
        return set()
    selected: set[int] = set()
    for decision in _mapping_sequence(trace.get("decisions")):
        readback = decision.get("expected_readback_check")
        if not isinstance(readback, Mapping):
            continue
        accounting = readback.get("expected_tree_accounting_delta")
        if not isinstance(accounting, Mapping):
            continue
        selected.update(_int_sequence(accounting.get("selected_target_node_ids")))
        present_sets = readback.get("expected_present_node_sets")
        if isinstance(present_sets, Mapping):
            selected.update(_int_sequence(present_sets.get("selected_target_node_ids")))
        choice_cost = decision.get("choice_cost")
        if isinstance(choice_cost, Mapping):
            resource_cost = choice_cost.get("resource_cost")
            if isinstance(resource_cost, Mapping):
                selected.update(_int_sequence(resource_cost.get("selected_target_node_ids")))
    return selected


def _nested_get(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _readback_tree_accounting(mutation_payload: Mapping[str, Any], side: str) -> dict[str, Any]:
    diff_accounting = _nested_get(mutation_payload, ("diff", "tree_accounting", side))
    if isinstance(diff_accounting, Mapping):
        return dict(diff_accounting)
    observation_accounting = _nested_get(mutation_payload, ("data", f"{side}_observation", "data", "tree_accounting"))
    if isinstance(observation_accounting, Mapping):
        return dict(observation_accounting)
    return {}


def _readback_tree_state(mutation_payload: Mapping[str, Any], side: str) -> dict[str, Any]:
    tree_state = _nested_get(mutation_payload, ("data", f"{side}_observation", "data", "tree_state"))
    if isinstance(tree_state, Mapping):
        return dict(tree_state)
    return {}


def _tree_accounting_normal_passive_count(accounting: Mapping[str, Any]) -> float | None:
    direct_count = _optional_non_negative_number(accounting.get("normal_passive_count"))
    if direct_count is not None:
        return direct_count
    user_allocated = set(_int_sequence(accounting.get("user_allocated_node_ids")))
    if not user_allocated:
        return None
    ascendancy_nodes = set(_int_sequence(accounting.get("allocated_ascendancy_node_ids")))
    return float(len(user_allocated - ascendancy_nodes))


def _tree_accounting_count(accounting: Mapping[str, Any], *, count_key: str, ids_key: str) -> float | None:
    direct_count = _optional_non_negative_number(accounting.get(count_key))
    if direct_count is not None:
        return direct_count
    ids = _int_sequence(accounting.get(ids_key))
    if ids:
        return float(len(set(ids)))
    return 0.0 if ids_key in accounting else None


def _first_non_negative_number(*values: Any) -> float | None:
    for value in values:
        numeric = _optional_non_negative_number(value)
        if numeric is not None:
            return numeric
    return None


def _optional_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:
        return None
    return numeric


def _optional_non_negative_number(value: Any) -> float | None:
    numeric = _optional_number(value)
    if numeric is None or numeric < 0:
        return None
    return numeric


def _calc_warning_codes(calc_snapshot: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(calc_snapshot, Mapping):
        return []
    candidates = (
        _nested_get(calc_snapshot, ("baseline", "calc_snapshot", "warning_codes")),
        _nested_get(calc_snapshot, ("baseline", "warning_codes")),
        _nested_get(calc_snapshot, ("calc_snapshot", "warning_codes")),
        calc_snapshot.get("warning_codes"),
    )
    for candidate in candidates:
        values = _string_sequence(candidate)
        if values:
            return values
    return []


def _calc_metric(calc_snapshot: Mapping[str, Any] | None, metric_name: str) -> float | None:
    if not isinstance(calc_snapshot, Mapping):
        return None
    candidate_maps = (
        _nested_get(calc_snapshot, ("baseline", "calc_snapshot", "calcs_output")),
        _nested_get(calc_snapshot, ("baseline", "calc_snapshot", "requirements")),
        _nested_get(calc_snapshot, ("baseline", "calcs_output")),
        _nested_get(calc_snapshot, ("baseline", "requirements")),
        _nested_get(calc_snapshot, ("calc_snapshot", "calcs_output")),
        _nested_get(calc_snapshot, ("calc_snapshot", "requirements")),
        calc_snapshot.get("calcs_output"),
        calc_snapshot.get("requirements"),
    )
    for candidate in candidate_maps:
        if isinstance(candidate, Mapping) and metric_name in candidate:
            return _optional_number(candidate.get(metric_name))
    return None


def _tree_state_from_unified_state(unified_state: Any) -> dict[str, Any]:
    state = _require_mapping(unified_state, "unified_state")
    tree_state = _require_mapping(state.get("tree_state"), "unified_state.tree_state")
    return json.loads(json.dumps(tree_state, ensure_ascii=False, sort_keys=True))


def _tree_accounting(tree_state: Mapping[str, Any]) -> dict[str, Any]:
    user_allocated = set(_int_sequence(tree_state.get("user_allocated_node_ids")))
    ascendancy_nodes = set(_int_sequence(tree_state.get("allocated_ascendancy_node_ids")))
    keystones = set(_int_sequence(tree_state.get("keystone_node_ids")))
    mastery_effects = _string_sequence(tree_state.get("mastery_effect_ids"))
    return {
        "allocated_node_count": len(user_allocated),
        "normal_passive_count": len(user_allocated - ascendancy_nodes),
        "ascendancy_node_count": len(ascendancy_nodes),
        "keystone_node_count": len(keystones),
        "mastery_effect_count": len(mastery_effects),
        "user_allocated_node_ids": sorted(user_allocated),
        "allocated_ascendancy_node_ids": sorted(ascendancy_nodes),
        "keystone_node_ids": sorted(keystones),
        "mastery_effect_ids": mastery_effects,
    }


def _tree_diff(before_tree_state: Mapping[str, Any], after_tree_state: Mapping[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for field_name in (
        "user_allocated_node_ids",
        "keystone_node_ids",
        "allocated_ascendancy_node_ids",
        "allocated_ascendancy_notable_node_ids",
        "cluster_jewel_socket_ids",
        "socketed_jewel_node_ids",
    ):
        before_values = set(_int_sequence(before_tree_state.get(field_name)))
        after_values = set(_int_sequence(after_tree_state.get(field_name)))
        diff[field_name] = {
            "before_count": len(before_values),
            "after_count": len(after_values),
            "added": sorted(after_values - before_values),
            "removed": sorted(before_values - after_values),
        }
    for field_name in ("mastery_effect_ids", "anoint_allocations"):
        before_values = set(_string_sequence(before_tree_state.get(field_name)))
        after_values = set(_string_sequence(after_tree_state.get(field_name)))
        diff[field_name] = {
            "before_count": len(before_values),
            "after_count": len(after_values),
            "added": sorted(after_values - before_values),
            "removed": sorted(before_values - after_values),
        }
    for field_name in ("class_id", "ascendancy_id", "secondary_ascendancy_id", "active_spec_id"):
        before_value = before_tree_state.get(field_name)
        after_value = after_tree_state.get(field_name)
        if before_value != after_value:
            diff[field_name] = {"before": before_value, "after": after_value}

    before_accounting = _tree_accounting(before_tree_state)
    after_accounting = _tree_accounting(after_tree_state)
    diff["tree_accounting"] = {
        "before": before_accounting,
        "after": after_accounting,
        "normal_passive_delta": after_accounting["normal_passive_count"] - before_accounting["normal_passive_count"],
        "ascendancy_node_delta": after_accounting["ascendancy_node_count"] - before_accounting["ascendancy_node_count"],
    }
    return diff


def _find_by_id(rows: Sequence[Mapping[str, Any]], key: str, expected: str) -> Mapping[str, Any] | None:
    if not expected:
        return None
    for row in rows:
        if _string(row.get(key)) == expected:
            return row
    return None


def _contains_observation_ref(refs: Sequence[Mapping[str, Any]], observation_id: str) -> bool:
    if not observation_id:
        return False
    for ref in refs:
        if _string(ref.get("ref_id") or ref.get("observation_id")) == observation_id:
            return True
    return False


def _mapping_sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _int_sequence(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            result.append(item)
    return result


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PoBTreeAuthoringToolError("invalid_tree_tool_input", f"{field_name} must be an object.")
    return dict(value)


def _require_non_empty_string(value: Any, field_name: str) -> str:
    normalized = _string(value)
    if not normalized:
        raise PoBTreeAuthoringToolError("invalid_tree_tool_input", f"{field_name} must be a non-empty string.")
    return normalized


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _handle_pob_run_id(handle: Any) -> str:
    return _require_non_empty_string(getattr(handle, "pob_run_id", None), "handle.pob_run_id")


def _tree_observation_id(handle: Any, state_version: str) -> str:
    return f"tree.obs.{_handle_pob_run_id(handle)}.{state_version[:12]}"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
