from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from junkroan.pob.skill_requirements import (
    POB_SKILL_REQUIREMENTS_RECORD_KIND,
    PoBSkillRequirementsContractError,
    build_skill_requirements_packet,
    build_validation_set,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "pob" / "pob.skill-requirements.schema.json"

from conftest import needs_skill_source  # noqa: E402

pytestmark = needs_skill_source


def requirements_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def assert_packet_contract(packet: dict) -> None:
    requirements_validator().validate(packet)
    assert packet["record_kind"] == POB_SKILL_REQUIREMENTS_RECORD_KIND
    assert packet["publication_outputs_absent"] is True
    assert all(value is False for value in packet["forbidden_decision_outputs_absent"].values())


def test_fireball_spell_packet_exposes_hard_facts_and_unknowns() -> None:
    packet = build_skill_requirements_packet("Fireball")

    assert_packet_contract(packet)
    assert packet["skill_identity"]["skill_id"] == "Fireball"
    assert "Spell" in packet["hard_requirements"]["skill_types"]["values"]
    assert packet["hard_requirements"]["base_flags"]["values"] == ["projectile", "spell"]
    assert packet["hard_requirements"]["legality_flags"]["flags"]["triggerable"] is True
    assert packet["hard_requirements"]["legality_flags"]["flags"]["can_be_trapped"] is True
    assert packet["hard_requirements"]["legality_flags"]["flags"]["can_be_mined"] is True
    assert packet["hard_requirements"]["legality_flags"]["flags"]["can_be_totem"] is True
    assert {"self_cast_spell", "trap_spell", "mine_spell", "totem_spell", "triggered_spell"} <= set(
        packet["derived_axes"]["possible_delivery_axes"]
    )
    assert {"spell_damage", "fire"} <= set(packet["derived_axes"]["possible_damage_axes"])
    assert packet["hard_requirements"]["requirements"]["attributes"]["values"]["intelligence"] == 100
    assert packet["hard_requirements"]["requirements"]["levels"]["natural_max_character_level"] == 70
    assert packet["hard_requirements"]["cost_and_reservation"]["costs"]["resource_keys"] == ["Mana"]
    assert packet["hard_requirements"]["weapon_types"]["state"] == "not_required_by_pinned_skill_data"
    assert {entry["field"] for entry in packet["unknowns_or_unsupported_fields"]} >= {
        "reservation",
        "full_support_legality",
    }


def test_lightning_arrow_attack_packet_preserves_weapon_and_offhand_legality() -> None:
    packet = build_skill_requirements_packet("Lightning Arrow")

    assert_packet_contract(packet)
    assert packet["skill_identity"]["skill_id"] == "LightningArrow"
    assert packet["hard_requirements"]["weapon_types"]["state"] == "known"
    assert packet["hard_requirements"]["weapon_types"]["values"] == ["Bow"]
    assert packet["hard_requirements"]["legal_weapon_offhand_families"]["values"] == [
        "bow_with_quiver_or_empty_offhand"
    ]
    assert packet["hard_requirements"]["base_flags"]["values"] == ["attack", "projectile"]
    assert {"self_attack", "trap_attack", "mine_attack", "totem_attack", "triggered_attack"} <= set(
        packet["derived_axes"]["possible_delivery_axes"]
    )
    assert {"attack_damage", "lightning"} <= set(packet["derived_axes"]["possible_damage_axes"])
    assert packet["hard_requirements"]["requirements"]["attributes"]["values"]["dexterity"] == 100
    assert any(
        restriction["restriction_id"] == "weapon_types"
        for restriction in packet["hard_requirements"]["notable_restrictions"]
    )


def test_blade_trap_packet_distinguishes_native_trap_from_trappable_route() -> None:
    packet = build_skill_requirements_packet("Blade Trap")

    assert_packet_contract(packet)
    assert packet["hard_requirements"]["legality_flags"]["flags"]["native_trap"] is True
    assert packet["hard_requirements"]["legality_flags"]["flags"]["can_be_trapped"] is False
    assert "native_trap" in packet["derived_axes"]["possible_delivery_axes"]
    assert packet["hard_requirements"]["weapon_types"]["values"] == [
        "Claw",
        "Dagger",
        "One Handed Sword",
        "Thrusting One Handed Sword",
    ]
    assert {
        restriction["restriction_id"]
        for restriction in packet["hard_requirements"]["notable_restrictions"]
    } >= {"weapon_types", "native_trap_delivery"}
    assert any(
        concern["concern_id"] == "native_trap_support_boundary"
        for concern in packet["support_concerns_pending_pob_proof"]
    )


def test_shockwave_totem_packet_covers_native_totem_and_requirement_pressure() -> None:
    packet = build_skill_requirements_packet("Shockwave Totem")

    assert_packet_contract(packet)
    assert packet["skill_identity"]["skill_id"] == "ShockwaveTotem"
    assert packet["hard_requirements"]["legality_flags"]["flags"]["native_totem"] is True
    assert packet["hard_requirements"]["legality_flags"]["flags"]["can_be_totem"] is False
    assert "native_totem" in packet["derived_axes"]["possible_delivery_axes"]
    assert {"spell_damage", "physical"} <= set(packet["derived_axes"]["possible_damage_axes"])
    assert packet["hard_requirements"]["requirements"]["attributes"]["values"]["strength"] == 100
    assert any(
        restriction["restriction_id"] == "native_totem_delivery"
        for restriction in packet["hard_requirements"]["notable_restrictions"]
    )


def test_unresolved_skill_fails_closed_instead_of_guessing() -> None:
    with pytest.raises(PoBSkillRequirementsContractError) as exc_info:
        build_skill_requirements_packet("Definitely Not A Pinned Skill")

    assert exc_info.value.failure_state == "unresolved_skill"


def test_validation_set_covers_representative_branch_pruning_facts() -> None:
    validation_set = build_validation_set(
        ["Fireball", "Lightning Arrow", "Blade Trap", "Shockwave Totem"],
        task_id="R18-POBAUTH-176-SKILLREQUIREMENTS",
    )

    assert validation_set["record_kind"] == "pob_skill_requirements_validation_set"
    assert validation_set["packet_count"] == 4
    assert validation_set["publication_outputs_absent"] is True
    assert {"Fireball", "Shockwave Totem"} <= set(validation_set["coverage"]["spell_packets"])
    assert {"Lightning Arrow", "Blade Trap"} <= set(validation_set["coverage"]["attack_weapon_packets"])
    assert {"native_trap", "native_totem", "triggered_spell"} <= set(validation_set["coverage"]["delivery_axes"])
    assert {"reservation", "full_support_legality"} <= set(
        validation_set["coverage"]["unknown_or_unsupported_fields"]
    )
    for packet in validation_set["packets"]:
        assert_packet_contract(packet)
