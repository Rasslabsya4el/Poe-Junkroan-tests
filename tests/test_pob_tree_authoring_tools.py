from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from junkroan.pob.tree_authoring_tools import (
    ASCENDANCY_NODE_REPORT_RECORD_KIND,
    PASSIVE_TREE_QUERY_RESULT_RECORD_KIND,
    TREE_MUTATION_RESULT_RECORD_KIND,
    TREE_NODE_POWER_RESULT_RECORD_KIND,
    TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND,
    TREE_READBACK_QUALITY_REPORT_RECORD_KIND,
    TREE_STATE_OBSERVATION_RECORD_KIND,
    PoBTreeAuthoringToolError,
    apply_tree_only_fixture_authoring_packet,
    build_tree_authoring_readback_quality_report,
    inspect_tree_state,
    mutate_tree_state,
    query_passive_tree_nodes,
    read_ascendancy_node_report,
    read_tree_node_power,
    validate_tree_only_fixture_authoring_packet,
)


@dataclass(frozen=True)
class _Handle:
    pob_run_id: str = "pob.run.tree-authoring-001"


class _Runtime:
    def __init__(self) -> None:
        self.tree_state = _tree_state(user_nodes=[100, 101], ascendancy_nodes=[])
        self.applied_tree_payloads: list[dict[str, Any]] = []

    def read_state(self, handle: _Handle) -> dict[str, Any]:
        return {
            "identity_state": {},
            "items_state": {},
            "gear_slots": {},
            "tree_state": dict(self.tree_state),
            "skills_state": {},
            "config_state": {},
        }

    def apply_tree_state(self, handle: _Handle, tree_payload: dict[str, Any]) -> None:
        self.applied_tree_payloads.append(dict(tree_payload))
        self.tree_state = _tree_state(
            user_nodes=list(tree_payload.get("user_allocated_node_ids", [])),
            ascendancy_nodes=list(tree_payload.get("ascendancy_node_ids", [])),
        )

    def read_node_power_report(self, handle: _Handle, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "record_kind": "pob_headless_node_power_report",
            "status": "accepted",
            "selected_metric": {"stat": request.get("metric_stat", "FullDPS")},
            "rows": [
                {
                    "row_id": "row.001",
                    "node_id": 555,
                    "node_name": "Strong Arm",
                    "target_kind": "notable",
                    "node_power_score": 17.5,
                    "path_power_score": 4.2,
                    "point_cost": 4,
                }
            ],
            "source_refs": [{"ref_id": "pob.node-power.001"}],
        }

    def read_ascendancy_node_report(self, handle: _Handle) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "record_kind": "pob_ascendancy_node_report",
            "status": "accepted",
            "active_class_id": "Duelist",
            "active_ascendancy_id": "Champion",
            "row_count": 2,
            "rows": [
                {
                    "row_id": "pob.ascendancy-node.700",
                    "node_id": 700,
                    "node_name": "Conqueror",
                    "target_kind": "ascendancy_notable",
                    "is_notable": True,
                    "allocated": False,
                    "stats_or_supporting_text": ["20% increased Attack Damage"],
                },
                {
                    "row_id": "pob.ascendancy-node.701",
                    "node_id": 701,
                    "node_name": "Champion small passive",
                    "target_kind": "ascendancy_small_passive",
                    "is_notable": False,
                    "allocated": False,
                    "stats_or_supporting_text": ["10% increased Attack Damage"],
                },
            ],
        }


def _tree_state(*, user_nodes: list[int], ascendancy_nodes: list[int]) -> dict[str, Any]:
    return {
        "state_kind": "nondefault",
        "active_spec_id": "spec.main",
        "class_id": "Duelist",
        "ascendancy_id": "Champion",
        "secondary_ascendancy_id": None,
        "default_root_state_present": True,
        "engine_default_node_ids": [50459],
        "user_allocated_node_ids": user_nodes,
        "keystone_node_ids": [31961] if 31961 in user_nodes else [],
        "allocated_ascendancy_node_ids": ascendancy_nodes,
        "allocated_ascendancy_notable_node_ids": ascendancy_nodes,
        "allocated_ascendancy_notables": [],
        "allocated_ascendancy_points": len(ascendancy_nodes),
        "allocated_ascendancy_notable_count": len(ascendancy_nodes),
        "mastery_effect_ids": [],
        "cluster_jewel_socket_ids": [],
        "socketed_jewel_node_ids": [],
        "anoint_allocations": [],
    }


def _valid_decision_trace(*, action_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    observation_id = observation["observation_id"]
    return {
        "record_kind": "direct_build_decision_trace",
        "trace_id": "trace.tree-agent-001",
        "candidate_id": "candidate.tree-agent-001",
        "variant_id": "variant.tree-agent-001",
        "pob_run_id": "pob.run.tree-authoring-001",
        "fixture_ref": "fixture.early-game-cleave.seed-001",
        "locked_surfaces": ["skill", "items", "config"],
        "editable_surfaces": ["tree"],
        "authored_surfaces": ["tree"],
        "decisions": [
            {
                "decision_id": "decision.tree-001",
                "rationale": "Spend passive points only where the current PoB evidence supports attack damage or life value.",
                "value_hypothesis": "The selected target/path improves the current attack build more than the nearby alternatives.",
                "expected_readback_check": {
                    "must_start_from_observation_id": observation_id,
                    "must_match_pre_apply_state_version": observation["state_version"],
                    "expected_tree_accounting_delta": {
                        "normal_passive_delta": 2,
                        "ascendancy_node_delta": 0,
                        "added_user_allocated_node_ids": [102, 31961],
                        "removed_user_allocated_node_ids": [],
                    },
                    "expected_present_node_sets": {
                        "selected_target_node_ids": [102, 31961],
                        "connector_node_ids": [],
                        "ascendancy_node_ids": [],
                        "mastery_effect_ids": [],
                    },
                },
                "choice_cost": {
                    "scarce_resource": "passive_points",
                    "resource_cost": {
                        "passive_points": 2,
                        "ascendancy_points": 0,
                        "mastery_choices": 0,
                        "added_user_allocated_node_ids": [102, 31961],
                        "removed_user_allocated_node_ids": [],
                    },
                    "value_evidence_refs": [{"ref_id": "pob.node-power.001"}],
                    "rejected_alternatives": [{"ref_id": "target.rejected.001", "reason": "Lower value per point."}],
                },
            }
        ],
        "actions": [
            {
                "action_id": action_id,
                "llm_decision_ref": "decision.tree-001",
                "target_mutation_kind": "tree",
                "agent_rationale": "Apply the currently selected passive target/path set and verify read-back diff.",
                "input_refs": [{"ref_id": observation_id, "state_version": observation["state_version"]}],
            }
        ],
        "observations": [{"observation_id": observation_id}],
        "publication_precondition": {"status": "not_requested"},
        "suppressed_outputs": {"pob_code": True},
    }


def _valid_tree_payload() -> dict[str, Any]:
    return {
        "active_spec_id": "spec.main",
        "class_id": "Duelist",
        "ascendancy_id": "Champion",
        "secondary_ascendancy_id": None,
        "ascendancy_node_ids": [],
        "ascendancy_notable_node_ids": [],
        "user_allocated_node_ids": [100, 101, 102, 31961],
        "keystone_node_ids": [31961],
        "mastery_effect_ids": [],
        "cluster_jewel_socket_ids": [],
        "socketed_jewel_node_ids": [],
        "override_carrier_node_ids": [],
        "override_carriers": [],
        "cluster_jewel_items": [],
        "socketed_jewel_items": [],
    }


def _valid_authoring_packet(*, observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "record_kind": TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND,
        "status": "ready_to_apply",
        "fixture_ref": "fixture.early-game-cleave.seed-001",
        "candidate_id": "candidate.tree-agent-001",
        "variant_id": "variant.tree-agent-001",
        "pob_run_id": "pob.run.tree-authoring-001",
        "expected_state_version": observation["state_version"],
        "observation_ref": {
            "observation_id": observation["observation_id"],
            "ref_kind": TREE_STATE_OBSERVATION_RECORD_KIND,
            "state_version": observation["state_version"],
        },
        "authored_surfaces": ["tree"],
        "direct_build_decision_trace": _valid_decision_trace(action_id="action.tree-001", observation=observation),
        "tree_payload": _valid_tree_payload(),
        "blockers": [],
    }


def _quality_mutation_result(
    *,
    user_nodes_after: list[int],
    added_nodes: list[int] | None = None,
    ascendancy_nodes_after: list[int] | None = None,
    ascendancy_notable_nodes_after: list[int] | None = None,
) -> dict[str, Any]:
    ascendancy_nodes = [] if ascendancy_nodes_after is None else ascendancy_nodes_after
    ascendancy_notable_nodes = [] if ascendancy_notable_nodes_after is None else ascendancy_notable_nodes_after
    return {
        "record_kind": TREE_MUTATION_RESULT_RECORD_KIND,
        "result_id": "tree.mutation.quality-budget-001",
        "state_version": "after-state",
        "diff": {
            "user_allocated_node_ids": {
                "added": added_nodes if added_nodes is not None else [102, 31961],
            }
        },
        "data": {
            "before_observation": {
                "data": {
                    "tree_accounting": {
                        "normal_passive_count": 2,
                        "ascendancy_node_count": 0,
                        "allocated_ascendancy_notable_count": 0,
                        "user_allocated_node_ids": [100, 101],
                        "allocated_ascendancy_node_ids": [],
                        "allocated_ascendancy_notable_node_ids": [],
                    }
                }
            },
            "after_observation": {
                "data": {
                    "tree_accounting": {
                        "normal_passive_count": len(user_nodes_after),
                        "ascendancy_node_count": len(ascendancy_nodes),
                        "allocated_ascendancy_notable_count": len(ascendancy_notable_nodes),
                        "user_allocated_node_ids": user_nodes_after,
                        "allocated_ascendancy_node_ids": ascendancy_nodes,
                        "allocated_ascendancy_notable_node_ids": ascendancy_notable_nodes,
                    }
                }
            },
        },
    }


def test_inspect_tree_state_returns_tree_accounting_and_fresh_ref() -> None:
    runtime = _Runtime()

    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )

    assert observation["record_kind"] == TREE_STATE_OBSERVATION_RECORD_KIND
    assert observation["status"] == "accepted"
    assert observation["data"]["tree_accounting"]["normal_passive_count"] == 2
    assert observation["output_refs"][0]["ref_id"] == observation["observation_id"]
    assert observation["safe_next_actions"] == ["read_tree_node_power", "mutate_tree_state"]


def test_read_tree_node_power_marks_ranked_rows_as_evidence_not_allocations() -> None:
    result = read_tree_node_power(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
        action_id="action.node-power-001",
        node_power_request={"metric_stat": "FullDPS", "max_rows": 5},
    )

    assert result["record_kind"] == TREE_NODE_POWER_RESULT_RECORD_KIND
    assert result["summary"]["ranked_rows_are_allocated_passives"] is False
    assert result["data"]["ranked_rows_are_allocated_passives"] is False
    assert result["data"]["node_power_report"]["rows"][0]["node_id"] == 555


def test_read_ascendancy_node_report_marks_rows_as_evidence_not_allocations() -> None:
    result = read_ascendancy_node_report(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
        action_id="action.ascendancy-report-001",
    )

    assert result["record_kind"] == ASCENDANCY_NODE_REPORT_RECORD_KIND
    assert result["summary"]["active_ascendancy_id"] == "Champion"
    assert result["summary"]["row_count"] == 2
    assert result["summary"]["notable_row_count"] == 1
    assert result["data"]["ascendancy_report_rows_are_allocated_nodes"] is False


def test_query_passive_tree_nodes_returns_facts_and_route_cost_without_selecting_tree(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "keystones.json").write_text(
        """{"records":[
          {"node_id":1,"name":"Start","stats":[],"incoming_node_ids":[],"outgoing_node_ids":[2],"is_keystone":false,"is_notable":false,"is_mastery":false},
          {"node_id":2,"name":"Travel","stats":[],"incoming_node_ids":[1],"outgoing_node_ids":[3],"is_keystone":false,"is_notable":false,"is_mastery":false},
          {"node_id":3,"name":"Resolute Technique","stats":["Your hits can't be Evaded\\nNever deal Critical Strikes"],"incoming_node_ids":[2],"outgoing_node_ids":[],"is_keystone":true,"is_notable":false,"is_mastery":false}
        ]}""",
        encoding="utf-8",
    )
    (corpus_root / "passives.json").write_text('{"records":[]}', encoding="utf-8")
    (corpus_root / "masteries.json").write_text('{"records":[]}', encoding="utf-8")

    result = query_passive_tree_nodes(
        search_terms=["evaded"],
        current_tree_state={"user_allocated_node_ids": [1]},
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
        action_id="action.passive-query-001",
        corpus_root=corpus_root,
    )

    assert result["record_kind"] == PASSIVE_TREE_QUERY_RESULT_RECORD_KIND
    assert result["status"] == "accepted"
    assert result["summary"]["query_rows_are_allocated_passives"] is False
    assert result["data"]["rows"][0]["node_id"] == 3
    assert result["data"]["rows"][0]["target_kind"] == "keystone"
    assert result["data"]["rows"][0]["added_path_node_ids"] == [2, 3]
    assert result["data"]["rows"][0]["point_cost"] == 2


def test_query_passive_tree_nodes_exposes_mastery_selection_token(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "passives.json").write_text(
        """{"records":[
          {"node_id":1,"name":"Eagle Eye","stats":["Accuracy"],"incoming_node_ids":[],"outgoing_node_ids":[2],"is_keystone":false,"is_notable":true,"is_mastery":false}
        ]}""",
        encoding="utf-8",
    )
    (corpus_root / "keystones.json").write_text('{"records":[]}', encoding="utf-8")
    (corpus_root / "masteries.json").write_text(
        """{"records":[
          {"node_id":2,"name":"Accuracy Mastery","stats":[],"incoming_node_ids":[1],"outgoing_node_ids":[],"is_keystone":false,"is_notable":false,"is_mastery":true,
           "mastery_effects":[{"effect_id":9755,"stats":["+500 to Accuracy Rating"]}]}
        ]}""",
        encoding="utf-8",
    )

    result = query_passive_tree_nodes(
        search_terms=["accuracy"],
        current_tree_state={"user_allocated_node_ids": [1]},
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
        action_id="action.passive-query-001",
        corpus_root=corpus_root,
    )

    mastery_row = next(row for row in result["data"]["rows"] if row["node_id"] == 2)
    assert mastery_row["mastery_effects"][0]["selection_token"] == "2:9755"


def test_mutate_tree_state_requires_fresh_tree_observation() -> None:
    runtime = _Runtime()
    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    trace = _valid_decision_trace(action_id="action.tree-001", observation=observation)

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        mutate_tree_state(
            runtime,
            _Handle(),
            candidate_id="candidate.tree-agent-001",
            variant_id="variant.tree-agent-001",
            action_id="action.tree-001",
            tree_payload=_valid_tree_payload(),
            decision_trace=trace,
            expected_state_version="stale",
            observation_ref={"observation_id": observation["observation_id"], "state_version": "stale"},
        )

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {"stale_tree_observation"}
    assert runtime.applied_tree_payloads == []


def test_mutate_tree_state_rejects_partial_tree_payload_snapshot() -> None:
    runtime = _Runtime()
    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    trace = _valid_decision_trace(action_id="action.tree-001", observation=observation)

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        mutate_tree_state(
            runtime,
            _Handle(),
            candidate_id="candidate.tree-agent-001",
            variant_id="variant.tree-agent-001",
            action_id="action.tree-001",
            tree_payload={"user_allocated_node_ids": [100, 101, 102]},
            decision_trace=trace,
            expected_state_version=observation["state_version"],
            observation_ref={"observation_id": observation["observation_id"], "state_version": observation["state_version"]},
        )

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_tree_payload_not_full_snapshot"
    }
    assert runtime.applied_tree_payloads == []


def test_mutate_tree_state_rejects_script_authored_payload_without_agent_trace() -> None:
    runtime = _Runtime()
    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        mutate_tree_state(
            runtime,
            _Handle(),
            candidate_id="candidate.tree-agent-001",
            variant_id="variant.tree-agent-001",
            action_id="action.tree-001",
            tree_payload=_valid_tree_payload(),
            decision_trace={"record_kind": "tree_lab_candidate_set"},
            expected_state_version=observation["state_version"],
            observation_ref={"observation_id": observation["observation_id"], "state_version": observation["state_version"]},
        )

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {"script_authored_direct_build_payload"}
    assert runtime.applied_tree_payloads == []


def test_mutate_tree_state_rejects_fixture_owned_surface_authorship_claim() -> None:
    runtime = _Runtime()
    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    trace = _valid_decision_trace(action_id="action.tree-001", observation=observation)
    trace["authored_surfaces"] = ["tree", "items"]

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        mutate_tree_state(
            runtime,
            _Handle(),
            candidate_id="candidate.tree-agent-001",
            variant_id="variant.tree-agent-001",
            action_id="action.tree-001",
            tree_payload=_valid_tree_payload(),
            decision_trace=trace,
            expected_state_version=observation["state_version"],
            observation_ref={"observation_id": observation["observation_id"], "state_version": observation["state_version"]},
            fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
        )

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {"fixture_authorship_violation"}
    assert runtime.applied_tree_payloads == []


def test_mutate_tree_state_rejects_observation_ref_not_listed_in_trace() -> None:
    runtime = _Runtime()
    observation = inspect_tree_state(
        runtime,
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    trace = _valid_decision_trace(action_id="action.tree-001", observation=observation)
    trace["observations"] = [{"observation_id": "observation.other"}]

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        mutate_tree_state(
            runtime,
            _Handle(),
            candidate_id="candidate.tree-agent-001",
            variant_id="variant.tree-agent-001",
            action_id="action.tree-001",
            tree_payload=_valid_tree_payload(),
            decision_trace=trace,
            expected_state_version=observation["state_version"],
            observation_ref={"observation_id": observation["observation_id"], "state_version": observation["state_version"]},
            fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
        )

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {"tree_action_observation_ref_not_in_trace"}
    assert runtime.applied_tree_payloads == []


def test_mutate_tree_state_applies_agent_authored_payload_and_returns_readback_diff() -> None:
    runtime = _Runtime()
    handle = _Handle()
    observation = inspect_tree_state(
        runtime,
        handle,
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    trace = _valid_decision_trace(action_id="action.tree-001", observation=observation)

    result = mutate_tree_state(
        runtime,
        handle,
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
        action_id="action.tree-001",
        tree_payload=_valid_tree_payload(),
        decision_trace=trace,
        expected_state_version=observation["state_version"],
        observation_ref={"observation_id": observation["observation_id"], "state_version": observation["state_version"]},
        fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
    )

    assert result["record_kind"] == TREE_MUTATION_RESULT_RECORD_KIND
    assert result["status"] == "accepted"
    assert result["diff"]["user_allocated_node_ids"]["added"] == [102, 31961]
    assert result["summary"]["normal_passive_count_after"] == 4
    assert runtime.applied_tree_payloads == [_valid_tree_payload()]


def test_validate_tree_only_fixture_authoring_packet_accepts_strict_agent_packet() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    validated = validate_tree_only_fixture_authoring_packet(
        packet,
        expected_observation=observation,
        fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
    )

    assert validated["record_kind"] == TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND
    assert validated["tree_payload"]["user_allocated_node_ids"] == [100, 101, 102, 31961]


def test_apply_tree_only_fixture_authoring_packet_validates_applies_and_attaches_quality_report() -> None:
    runtime = _Runtime()
    handle = _Handle()
    observation = inspect_tree_state(
        runtime,
        handle,
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    result = apply_tree_only_fixture_authoring_packet(
        runtime,
        handle,
        packet=packet,
        fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
        quality_contract={"max_added_nodes_per_selected_target": 1},
    )

    assert result["record_kind"] == TREE_MUTATION_RESULT_RECORD_KIND
    assert result["status"] == "accepted"
    assert result["quality_report"]["status"] == "accepted"
    assert result["diff"]["user_allocated_node_ids"]["added"] == [102, 31961]
    assert runtime.applied_tree_payloads == [_valid_tree_payload()]


def test_apply_tree_only_fixture_authoring_packet_accepts_equivalent_reopen_state_version() -> None:
    runtime = _Runtime()
    handle = _Handle()
    observation = inspect_tree_state(
        runtime,
        handle,
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    result = apply_tree_only_fixture_authoring_packet(
        runtime,
        _Handle(pob_run_id="pob.run.reopen-002"),
        packet=packet,
        fixture_contract={"locked_surfaces": ["skill", "items", "config"], "editable_surfaces": ["tree"]},
        quality_contract={"max_added_nodes_per_selected_target": 1},
    )

    assert result["status"] == "accepted"
    assert result["diff"]["user_allocated_node_ids"]["added"] == [102, 31961]


def test_validate_tree_only_fixture_authoring_packet_rejects_partial_tree_payload() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    packet["tree_payload"] = {"user_allocated_node_ids": [100, 101, 102]}

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_tree_payload_not_full_snapshot"
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_cost_that_does_not_match_payload_delta() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    packet["direct_build_decision_trace"]["decisions"][0]["choice_cost"]["resource_cost"]["passive_points"] = 1

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_passive_point_cost_mismatch"
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_itemized_delta_mismatch() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    decision = packet["direct_build_decision_trace"]["decisions"][0]
    decision["expected_readback_check"]["expected_tree_accounting_delta"]["added_user_allocated_node_ids"] = [102]
    decision["choice_cost"]["resource_cost"]["added_user_allocated_node_ids"] = [102]
    packet["direct_build_decision_trace"]["actions"][0]["added_user_allocated_node_ids"] = [102]

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_itemized_delta_mismatch",
        "tree_authoring_packet_resource_cost_delta_mismatch",
        "tree_authoring_packet_action_added_nodes_mismatch",
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_claimed_target_missing_from_payload() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    packet["tree_payload"]["user_allocated_node_ids"] = [100, 101, 102]
    packet["tree_payload"]["keystone_node_ids"] = []
    packet["direct_build_decision_trace"]["decisions"][0]["expected_readback_check"]["expected_tree_accounting_delta"][
        "normal_passive_delta"
    ] = 1
    packet["direct_build_decision_trace"]["decisions"][0]["choice_cost"]["resource_cost"]["passive_points"] = 1

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_selected_targets_missing_from_payload"
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_claimed_mastery_missing_from_payload() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    decision = packet["direct_build_decision_trace"]["decisions"][0]
    decision["expected_readback_check"]["expected_present_node_sets"]["mastery_effect_ids"] = ["102:9755"]
    packet["direct_build_decision_trace"]["actions"][0]["selected_mastery_effect_ids"] = ["102:9755"]

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_expected_mastery_effect_missing_from_payload",
        "tree_authoring_packet_action_mastery_effect_missing_from_payload",
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_mastery_replacement_delta_mismatch() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    observation["data"]["tree_state"]["mastery_effect_ids"] = ["102:old"]
    observation["data"]["tree_accounting"]["mastery_effect_ids"] = ["102:old"]
    packet = _valid_authoring_packet(observation=observation)
    packet["tree_payload"]["mastery_effect_ids"] = ["102:new"]
    decision = packet["direct_build_decision_trace"]["decisions"][0]
    decision["expected_readback_check"]["expected_tree_accounting_delta"]["added_mastery_effect_ids"] = ["102:claimed"]
    decision["expected_readback_check"]["expected_tree_accounting_delta"]["removed_mastery_effect_ids"] = ["102:old"]
    decision["choice_cost"]["resource_cost"]["mastery_effect_replacements"] = [
        {"before": "102:old", "after": "102:claimed"}
    ]

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_authoring_packet_mastery_delta_mismatch",
        "tree_authoring_packet_mastery_replacement_delta_mismatch",
    }


def test_validate_tree_only_fixture_authoring_packet_rejects_missing_value_cost_reasoning() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    decision = packet["direct_build_decision_trace"]["decisions"][0]
    decision.pop("value_hypothesis")
    decision["choice_cost"].pop("value_evidence_refs")
    decision["choice_cost"]["rejected_alternatives"] = []
    decision["choice_cost"]["no_alternative_reason"] = ""

    with pytest.raises(PoBTreeAuthoringToolError) as exc_info:
        validate_tree_only_fixture_authoring_packet(packet, expected_observation=observation)

    assert {blocker["code"] for blocker in exc_info.value.blockers} >= {
        "tree_decision_missing_value_hypothesis",
        "tree_decision_missing_value_evidence_refs",
        "tree_decision_missing_alternative_or_no_alternative_reason",
    }


def test_validate_tree_only_fixture_authoring_packet_accepts_blocked_packet_with_smallest_missing_fact() -> None:
    packet = {
        "schema_version": "0.1.0",
        "record_kind": TREE_ONLY_FIXTURE_AUTHORING_PACKET_RECORD_KIND,
        "status": "blocked",
        "blockers": [
            {
                "code": "missing_fresh_tree_observation",
                "message": "The worker cannot choose a tree without a current wrapper observation.",
                "smallest_missing": "pob_tree_state_observation",
            }
        ],
    }

    validated = validate_tree_only_fixture_authoring_packet(packet)

    assert validated["status"] == "blocked"
    assert validated["blockers"][0]["code"] == "missing_fresh_tree_observation"


def test_tree_authoring_quality_report_rejects_expensive_route_and_failed_requirements() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    mutation_result = {
        "record_kind": TREE_MUTATION_RESULT_RECORD_KIND,
        "result_id": "tree.mutation.quality-001",
        "state_version": "after-state",
        "diff": {
            "user_allocated_node_ids": {
                "added": [102, 31961, 200, 201, 202],
            }
        },
        "data": {
            "before_observation": {
                "data": {
                    "tree_accounting": {
                        "user_allocated_node_ids": [100, 101],
                    }
                }
            },
            "after_observation": {
                "data": {
                    "tree_accounting": {
                        "user_allocated_node_ids": [100, 101, 102, 31961, 200, 201, 202],
                    }
                }
            },
        },
    }
    calc_snapshot = {
        "baseline": {
            "calc_snapshot": {
                "warning_codes": ["unmet_strength_requirement"],
                "calcs_output": {
                    "HitChance": 63.0,
                    "Str": 128.0,
                },
            }
        }
    }

    report = build_tree_authoring_readback_quality_report(
        packet,
        mutation_result,
        calc_snapshot=calc_snapshot,
        quality_contract={
            "max_connector_or_path_node_count": 1,
            "max_added_nodes_per_selected_target": 2,
            "fail_on_warning_codes": ["unmet_strength_requirement"],
            "min_baseline_metrics": {"HitChance": 97, "Str": 149},
        },
    )

    assert report["record_kind"] == TREE_READBACK_QUALITY_REPORT_RECORD_KIND
    assert report["status"] == "rejected"
    assert report["summary"]["selected_target_node_ids"] == [102, 31961]
    assert report["summary"]["connector_or_path_node_count"] == 3
    assert {blocker["code"] for blocker in report["blockers"]} >= {
        "tree_quality_connector_or_path_count_exceeded",
        "tree_quality_added_nodes_per_selected_target_exceeded",
        "tree_quality_fail_warning_still_present",
        "tree_quality_min_metric_not_met",
    }


def test_tree_authoring_quality_report_accepts_bounded_readback() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    mutation_result = {
        "record_kind": TREE_MUTATION_RESULT_RECORD_KIND,
        "result_id": "tree.mutation.quality-002",
        "state_version": "after-state",
        "diff": {
            "user_allocated_node_ids": {
                "added": [102, 31961],
            }
        },
        "data": {
            "before_observation": {
                "data": {
                    "tree_accounting": {
                        "user_allocated_node_ids": [100, 101],
                    }
                }
            },
            "after_observation": {
                "data": {
                    "tree_accounting": {
                        "user_allocated_node_ids": [100, 101, 102, 31961],
                    }
                }
            },
        },
    }
    calc_snapshot = {
        "baseline": {
            "calc_snapshot": {
                "warning_codes": [],
                "calcs_output": {
                    "HitChance": 98.0,
                    "Str": 150.0,
                },
            }
        }
    }

    report = build_tree_authoring_readback_quality_report(
        packet,
        mutation_result,
        calc_snapshot=calc_snapshot,
        quality_contract={
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
            "fail_on_warning_codes": ["unmet_strength_requirement"],
            "min_baseline_metrics": {"HitChance": 97, "Str": 149},
        },
    )

    assert report["status"] == "accepted"
    assert report["blockers"] == []


def test_tree_authoring_quality_report_reads_raw_headless_calc_shape() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    mutation_result = {
        "record_kind": TREE_MUTATION_RESULT_RECORD_KIND,
        "result_id": "tree.mutation.quality-raw-001",
        "state_version": "after-state",
        "diff": {"user_allocated_node_ids": {"added": [102, 31961]}},
        "data": {
            "before_observation": {"data": {"tree_accounting": {"user_allocated_node_ids": [100, 101]}}},
            "after_observation": {
                "data": {"tree_accounting": {"user_allocated_node_ids": [100, 101, 102, 31961]}}
            },
        },
    }
    calc_snapshot = {
        "baseline": {
            "warning_codes": [],
            "calcs_output": {
                "HitChance": 98.0,
                "Str": 150.0,
            },
        }
    }

    report = build_tree_authoring_readback_quality_report(
        packet,
        mutation_result,
        calc_snapshot=calc_snapshot,
        quality_contract={"min_baseline_metrics": {"HitChance": 97, "Str": 149}},
    )

    assert report["status"] == "accepted"


def test_tree_authoring_quality_report_repair_delta_does_not_require_full_passive_budget() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(user_nodes_after=[100, 101, 102, 31961]),
        quality_contract={
            "budget_mode": "repair_delta",
            "passive_budget_contract": {"target_normal_passive_count": 90},
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
        },
    )

    assert report["status"] == "accepted"
    assert report["summary"]["budget_mode"] == "repair_delta"
    assert report["summary"]["normal_passive_count_after"] == 4


def test_tree_authoring_quality_report_rejects_underfilled_budgeted_full_tree() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(user_nodes_after=[100, 101, 102, 31961]),
        quality_contract={
            "budget_mode": "budgeted_full_tree",
            "passive_budget_contract": {"target_normal_passive_count": 90},
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
        },
    )

    assert report["status"] == "rejected"
    assert {blocker["code"] for blocker in report["blockers"]} >= {
        "tree_quality_passive_budget_underfilled"
    }
    budget_blocker = next(blocker for blocker in report["blockers"] if blocker["code"] == "tree_quality_passive_budget_underfilled")
    assert budget_blocker["observed"] == 4
    assert budget_blocker["expected_min"] == 90


def test_tree_authoring_quality_report_rejects_budgeted_full_tree_without_budget_contract() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(user_nodes_after=[100, 101, 102, 31961]),
        quality_contract={"budget_mode": "budgeted_full_tree"},
    )

    assert report["status"] == "rejected"
    assert {blocker["code"] for blocker in report["blockers"]} >= {
        "tree_quality_passive_budget_contract_missing"
    }


def test_tree_authoring_quality_report_accepts_budgeted_full_tree_at_budget() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    after_nodes = [100, 101, 102, 31961, *range(200, 286)]

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(user_nodes_after=after_nodes, added_nodes=[102, 31961]),
        quality_contract={
            "budget_mode": "budgeted_full_tree",
            "passive_budget_contract": {"target_normal_passive_count": 90},
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
        },
    )

    assert report["status"] == "accepted"
    assert report["summary"]["budget_mode"] == "budgeted_full_tree"
    assert report["summary"]["normal_passive_count_after"] == 90


def test_tree_authoring_quality_report_rejects_underfilled_ascendancy_budget() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    after_nodes = [100, 101, 102, 31961, *range(200, 286)]

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(user_nodes_after=after_nodes, added_nodes=[102, 31961]),
        quality_contract={
            "budget_mode": "budgeted_full_tree",
            "passive_budget_contract": {"target_normal_passive_count": 90},
            "ascendancy_budget_contract": {
                "target_ascendancy_node_count": 8,
                "target_ascendancy_notable_count": 4,
            },
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
        },
    )

    assert report["status"] == "rejected"
    assert {blocker["code"] for blocker in report["blockers"]} >= {
        "tree_quality_ascendancy_budget_underfilled",
        "tree_quality_ascendancy_notable_budget_underfilled",
    }
    assert report["summary"]["ascendancy_node_count_after"] == 0
    assert report["summary"]["ascendancy_notable_count_after"] == 0


def test_tree_authoring_quality_report_accepts_full_tree_with_ascendancy_budget() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    after_nodes = [100, 101, 102, 31961, *range(200, 286)]

    report = build_tree_authoring_readback_quality_report(
        packet,
        _quality_mutation_result(
            user_nodes_after=after_nodes,
            added_nodes=[102, 31961],
            ascendancy_nodes_after=[700, 701, 702, 703, 704, 705, 706, 707],
            ascendancy_notable_nodes_after=[700, 702, 704, 706],
        ),
        quality_contract={
            "budget_mode": "budgeted_full_tree",
            "passive_budget_contract": {"target_normal_passive_count": 90},
            "ascendancy_budget_contract": {
                "target_ascendancy_node_count": 8,
                "target_ascendancy_notable_count": 4,
            },
            "max_connector_or_path_node_count": 0,
            "max_added_nodes_per_selected_target": 1,
        },
    )

    assert report["status"] == "accepted"
    assert report["summary"]["ascendancy_node_count_after"] == 8
    assert report["summary"]["ascendancy_notable_count_after"] == 4


def test_tree_authoring_quality_report_reads_ascendancy_counts_from_tree_state_fallback() -> None:
    observation = inspect_tree_state(
        _Runtime(),
        _Handle(),
        candidate_id="candidate.tree-agent-001",
        variant_id="variant.tree-agent-001",
    )
    packet = _valid_authoring_packet(observation=observation)
    mutation_result = _quality_mutation_result(user_nodes_after=[100, 101, 102, 31961])
    after_accounting = mutation_result["data"]["after_observation"]["data"]["tree_accounting"]
    after_accounting.pop("ascendancy_node_count")
    after_accounting.pop("allocated_ascendancy_node_ids")
    after_accounting.pop("allocated_ascendancy_notable_count")
    after_accounting.pop("allocated_ascendancy_notable_node_ids")
    mutation_result["data"]["after_observation"]["data"]["tree_state"] = {
        "allocated_ascendancy_points": 8,
        "allocated_ascendancy_node_ids": [700, 701, 702, 703, 704, 705, 706, 707],
        "allocated_ascendancy_notable_count": 4,
        "allocated_ascendancy_notable_node_ids": [700, 702, 704, 706],
    }

    report = build_tree_authoring_readback_quality_report(
        packet,
        mutation_result,
        quality_contract={
            "ascendancy_budget_contract": {
                "target_ascendancy_node_count": 8,
                "target_ascendancy_notable_count": 4,
            },
        },
    )

    assert report["status"] == "accepted"
    assert report["summary"]["ascendancy_node_count_after"] == 8
    assert report["summary"]["ascendancy_notable_count_after"] == 4
