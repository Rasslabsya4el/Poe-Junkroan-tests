from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from junkroan.pob.support_legality_readback import (
    POB_SUPPORT_LEGALITY_READBACK_RECORD_KIND,
    PoBSupportLegalityReadbackContractError,
    build_support_legality_readback_packet,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "pob" / "pob.support-legality-readback.schema.json"


def readback_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def assert_packet_contract(packet: dict) -> None:
    readback_validator().validate(packet)
    assert packet["record_kind"] == POB_SUPPORT_LEGALITY_READBACK_RECORD_KIND
    assert packet["publication_outputs_absent"] is True
    assert all(value is False for value in packet["forbidden_decision_outputs_absent"].values())
    assert packet["tag_precheck"]["concerns_can_mark_legal"] is False


_SKILL_REQUIREMENTS_CONCERNS = {
    "support_concerns_pending_pob_proof": [
        {
            "concern_id": "full_support_matrix_pending_pob_proof",
            "status": "pending_pob_proof",
            "summary": "Do not infer full support compatibility from tags.",
        },
        {
            "concern_id": "minion_support_boundary",
            "status": "pending_pob_proof",
            "summary": "Minion support legality must be checked in PoB.",
        },
    ]
}


_OBSERVED_SKILLS_STATE = {
    "skills_state": {
        "state_kind": "nondefault",
        "active_skill_set_id": "skills.main",
        "skill_sets": [
            {
                "skill_set_id": "skills.main",
                "title": "Main",
                "socket_groups": [
                    {
                        "socket_group_id": "skills.main.socket_group.1",
                        "label": "Minions",
                        "slot": "Boots",
                        "enabled": True,
                        "gems": [
                            {
                                "gem_entry_id": "skills.main.socket_group.1.gem.1",
                                "gem_name": "Summon Skeletons",
                                "skill_id": "SummonSkeletons",
                                "is_support": False,
                                "enabled": True,
                            },
                            {
                                "gem_entry_id": "skills.main.socket_group.1.gem.2",
                                "gem_name": "Feeding Frenzy",
                                "skill_id": "SupportFeedingFrenzy",
                                "is_support": True,
                                "enabled": True,
                            },
                            {
                                "gem_entry_id": "skills.main.socket_group.1.gem.3",
                                "gem_name": "Brutality",
                                "skill_id": "SupportBrutality",
                                "is_support": True,
                                "enabled": False,
                            },
                            {
                                "gem_entry_id": "skills.main.socket_group.1.gem.4",
                                "gem_name": "Increased Critical Strikes",
                                "skill_id": "SupportIncreasedCriticalStrikes",
                                "is_support": True,
                                "enabled": True,
                            },
                        ],
                        "active_skill_entries": [
                            {
                                "active_skill_id": "skills.main.socket_group.1.active_skill.1",
                                "name": "Summon Skeletons",
                                "skill_id": "SummonSkeletons",
                                "support_links": [
                                    {
                                        "name": "Feeding Frenzy",
                                        "skill_id": "SupportFeedingFrenzy",
                                        "from_item": False,
                                        "source_gem_entry_id": "skills.main.socket_group.1.gem.2",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
}


def test_readback_reports_accepted_disabled_blocked_and_unresolved_support_rows() -> None:
    packet = build_support_legality_readback_packet(
        {
            "name": "Summon Skeletons",
            "skill_id": "SummonSkeletons",
            "socket_group_id": "skills.main.socket_group.1",
        },
        [
            "Feeding Frenzy",
            "Brutality",
            "Increased Critical Strikes",
            "Spell Echo",
        ],
        observed_state=_OBSERVED_SKILLS_STATE,
        skill_requirements_packet=_SKILL_REQUIREMENTS_CONCERNS,
        observation_ref="obs.skills.r18-180.fixture",
    )

    assert_packet_contract(packet)
    assert packet["runtime_observation"]["observation_state"] == "observed"
    assert packet["summary"]["packet_status"] == "blocked"
    assert packet["summary"]["accepted_count"] == 1
    assert packet["summary"]["disabled_count"] == 1
    assert packet["summary"]["blocked_count"] == 1
    assert packet["summary"]["unsupported_by_tooling_count"] == 1

    by_name = {row["support_name"]: row for row in packet["observed_rows"]}
    assert by_name["Feeding Frenzy"]["status"] == "accepted"
    assert by_name["Feeding Frenzy"]["matched_support_link"]["source_gem_entry_id"] == (
        "skills.main.socket_group.1.gem.2"
    )
    assert by_name["Brutality"]["status"] == "disabled"
    assert by_name["Brutality"]["matched_gem_entry"]["enabled"] is False
    assert by_name["Increased Critical Strikes"]["status"] == "blocked"
    assert by_name["Increased Critical Strikes"]["matched_gem_entry"]["is_support"] is True
    assert by_name["Spell Echo"]["status"] == "unsupported_by_tooling"
    assert by_name["Spell Echo"]["row_kind"] == "unresolved_requested_support"


def test_runtime_unavailable_fails_closed_even_with_tag_concerns() -> None:
    packet = build_support_legality_readback_packet(
        "Summon Skeletons",
        ["Feeding Frenzy"],
        observed_state=None,
        skill_requirements_packet=_SKILL_REQUIREMENTS_CONCERNS,
        observation_ref="obs.missing-runtime",
    )

    assert_packet_contract(packet)
    assert packet["runtime_observation"]["observation_state"] == "needs_pob_runtime"
    assert packet["summary"]["packet_status"] == "needs_pob_runtime"
    assert packet["summary"]["all_supports_accepted"] is False
    assert packet["observed_rows"][0]["status"] == "needs_pob_runtime"
    assert packet["observed_rows"][0]["tag_precheck_concern_ids"] == [
        "full_support_matrix_pending_pob_proof",
        "minion_support_boundary",
    ]


def test_tag_precheck_concerns_cannot_mark_missing_support_legal() -> None:
    packet = build_support_legality_readback_packet(
        "Summon Skeletons",
        ["Spell Echo"],
        observed_state=_OBSERVED_SKILLS_STATE,
        skill_requirements_packet=_SKILL_REQUIREMENTS_CONCERNS,
        observation_ref="obs.skills.r18-180.fixture",
    )

    assert_packet_contract(packet)
    row = packet["observed_rows"][0]
    assert row["support_name"] == "Spell Echo"
    assert row["status"] == "unsupported_by_tooling"
    assert row["observed_from_pob"] is True
    assert packet["tag_precheck"]["concerns"]
    assert packet["summary"]["all_supports_accepted"] is False


def test_unresolved_active_skill_fails_closed_without_guessing_support_legality() -> None:
    packet = build_support_legality_readback_packet(
        "Fireball",
        ["Feeding Frenzy"],
        observed_state=_OBSERVED_SKILLS_STATE,
        observation_ref="obs.skills.r18-180.fixture",
    )

    assert_packet_contract(packet)
    assert packet["runtime_observation"]["observation_state"] == "unsupported_by_tooling"
    assert packet["observed_rows"][0]["status"] == "unsupported_by_tooling"
    assert packet["observed_rows"][0]["source"] == "active_skill_unresolved"


def test_invalid_empty_support_request_is_rejected() -> None:
    with pytest.raises(PoBSupportLegalityReadbackContractError) as exc_info:
        build_support_legality_readback_packet(
            "Summon Skeletons",
            [],
            observed_state=_OBSERVED_SKILLS_STATE,
        )

    assert exc_info.value.failure_state == "invalid_support_readback_request"


def test_validation_artifact_matches_packet_schema() -> None:
    packet = build_support_legality_readback_packet(
        {
            "name": "Summon Skeletons",
            "skill_id": "SummonSkeletons",
            "socket_group_id": "skills.main.socket_group.1",
        },
        [
            "Feeding Frenzy",
            "Brutality",
            "Increased Critical Strikes",
            "Spell Echo",
        ],
        observed_state=_OBSERVED_SKILLS_STATE,
        skill_requirements_packet=_SKILL_REQUIREMENTS_CONCERNS,
        observation_ref="obs.skills.inline-validation",
    )

    assert_packet_contract(packet)
    assert {row["status"] for row in packet["observed_rows"]} >= {
        "accepted",
        "disabled",
        "blocked",
        "unsupported_by_tooling",
    }
