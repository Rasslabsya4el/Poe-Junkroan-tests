"""Fail-closed Early Game Direct Build rails report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET

from .artifacts import write_json
from .tree_payload_normalization import classify_tree_node_ids

SCHEMA_VERSION = "0.1.0"
RECORD_KIND = "direct_build_early_game_rails_report"
DIRECT_BUILD_DECISION_TRACE_RECORD_KIND = "direct_build_decision_trace"
TREE_LAB_RECORD_KIND = "tree_lab_candidate_set"
DIRECT_BUILD_EARLY_GAME_LEVEL = 90
DIRECT_BUILD_EARLY_GAME_PASSIVE_BUDGET = 113
DIRECT_BUILD_EARLY_GAME_ALLOWED_BANDIT_VALUES = {"kill_all", "kill all", "none"}
DIRECT_BUILD_EARLY_GAME_ASCENDANCY_POLICIES = {
    "champion": {
        "class_name": "Duelist",
        "ascendancy_name": "Champion",
        "node_ids": {
            6982,
            11412,
            13374,
            25111,
            27604,
            31700,
            33940,
            35185,
            35750,
            41433,
            42469,
            43725,
            56967,
            60508,
            61478,
        },
        "notable_node_ids": {11412, 13374, 27604, 31700, 33940, 35750, 42469, 56967},
    },
    "elementalist": {
        "class_name": "Witch",
        "ascendancy_name": "Elementalist",
        "node_ids": {
            258,
            4917,
            6052,
            12475,
            12738,
            19595,
            27038,
            37114,
            40810,
            47873,
            53123,
            54279,
            56461,
            57197,
            58998,
            61259,
        },
        "notable_node_ids": {258, 4917, 27038, 40810, 53123, 56461, 57197, 61259},
    },
    "inquisitor": {
        "class_name": "Templar",
        "ascendancy_name": "Inquisitor",
        "node_ids": {
            662,
            10635,
            13851,
            19417,
            27055,
            32816,
            37486,
            39790,
            40059,
            43193,
            48214,
            53884,
            57222,
            60769,
        },
        "notable_node_ids": {13851, 19417, 32816, 39790, 40059, 48214, 53884},
    },
}
RESOLUTE_TECHNIQUE_NODE_ID = 31961
MINIMUM_BASELINE_LIFE = 4500.0
MINIMUM_BASELINE_HIT_CHANCE = 97.0
MINIMUM_BASELINE_FULL_DPS = 200000.0
MINIMUM_BASELINE_TOTAL_EHP = 15000.0
MINIMUM_BASELINE_ELEMENTAL_RESIST = 75.0
MINIMUM_BASELINE_CHAOS_RESIST = 25.0
MINIMUM_MANA_CAST_BUFFER = 2.0
EXPECTED_MAIN_LINK_COUNT = 5
REQUIRED_AUTHORING_ACTION_KINDS = ("identity", "skill", "tree", "item", "config", "observe")


class DirectBuildEarlyGameRailsError(RuntimeError):
    """Raised when the rails report input cannot be read."""


def build_direct_build_early_game_rails_report(
    *,
    candidate_payload: Mapping[str, Any],
    pob_xml_text: str,
    normalized_calc_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    root = ET.fromstring(pob_xml_text)
    build_node = _required_child(root, "Build")
    spec_node = _required_child(_required_child(root, "Tree"), "Spec")
    skill_node = _main_skill_node(root)
    main_skill_gem_names = _main_skill_gem_names(skill_node)
    baseline_calc_snapshot = _baseline_calc_snapshot(normalized_calc_snapshot)
    baseline_main_output = _baseline_main_output(baseline_calc_snapshot)
    authoring_blockers = _authoring_trace_blockers(candidate_payload)

    spec_node_ids = _csv_ints(spec_node.attrib.get("nodes", ""))
    identity_policy = _expected_ascendancy_policy(
        candidate_payload,
        observed_class_name=build_node.attrib.get("className"),
        observed_ascendancy_name=build_node.attrib.get("ascendClassName"),
    )
    known_ascendancy_node_ids = set(identity_policy.get("node_ids", set())) if identity_policy else set()
    candidate_ascendancy_node_ids = set(_candidate_ascendancy_node_ids(candidate_payload))
    ascendancy_node_policy_ids = known_ascendancy_node_ids | candidate_ascendancy_node_ids
    ascendancy_node_ids = sorted(set(spec_node_ids) & ascendancy_node_policy_ids)
    node_classification = classify_tree_node_ids(spec_node_ids, namespace="tree_spec_nodes")
    passive_accounting_excluded_node_ids = (
        ascendancy_node_policy_ids
        | set(node_classification["mastery_group"])
        | set(node_classification["mastery_effect_ref"])
        | set(node_classification["start_root_proxy"])
    )
    normal_node_ids = [node_id for node_id in spec_node_ids if node_id not in passive_accounting_excluded_node_ids]
    selected_keystone_ids = sorted(set(spec_node_ids) & {RESOLUTE_TECHNIQUE_NODE_ID})

    metrics = {
        "baseline_life": _numeric_metric(baseline_main_output, "Life"),
        "baseline_hit_chance": _numeric_metric(baseline_main_output, "HitChance"),
        "baseline_full_dps": _numeric_metric(baseline_main_output, "FullDPS"),
        "baseline_combined_dps": _numeric_metric(baseline_main_output, "CombinedDPS"),
        "baseline_total_ehp": _numeric_metric(baseline_main_output, "TotalEHP"),
        "baseline_fire_resist": _numeric_metric_any(baseline_main_output, ("FireResist", "FireResistance")),
        "baseline_cold_resist": _numeric_metric_any(baseline_main_output, ("ColdResist", "ColdResistance")),
        "baseline_lightning_resist": _numeric_metric_any(baseline_main_output, ("LightningResist", "LightningResistance")),
        "baseline_chaos_resist": _numeric_metric_any(baseline_main_output, ("ChaosResist", "ChaosResistance")),
        "baseline_mana_unreserved": _numeric_metric_any(
            baseline_main_output,
            ("ManaUnreserved", "UnreservedMana", "ManaUnreservedAfterReservation"),
        ),
        "baseline_mana_cost": _numeric_metric_any(
            baseline_main_output,
            ("ManaCost", "SkillManaCost", "MainSkillManaCost"),
        ),
    }
    ascendancy_notable_node_ids = _candidate_ascendancy_notable_node_ids(
        candidate_payload,
        ascendancy_node_ids,
        identity_policy,
    )
    observed = {
        "level": _optional_int(build_node.attrib.get("level")),
        "class_name": build_node.attrib.get("className"),
        "ascendancy_name": build_node.attrib.get("ascendClassName"),
        "expected_class_name": identity_policy.get("class_name") if identity_policy else _expected_identity_value(candidate_payload, "class_name"),
        "expected_ascendancy_name": identity_policy.get("ascendancy_name")
        if identity_policy
        else _expected_identity_value(candidate_payload, "ascendancy"),
        "identity_policy_key": _normalized_key(identity_policy.get("ascendancy_name")) if identity_policy else None,
        "bandit": build_node.attrib.get("bandit"),
        "bandit_normalized": _normalized_bandit(build_node.attrib.get("bandit")),
        "character_level_auto_mode": build_node.attrib.get("characterLevelAutoMode"),
        "spec_class_id": _optional_int(spec_node.attrib.get("classId")),
        "spec_ascendancy_id": _optional_int(spec_node.attrib.get("ascendClassId")),
        "expected_spec_ascendancy_id": _expected_spec_ascendancy_id(candidate_payload),
        "normal_passive_count": len(normal_node_ids),
        "spec_node_count": len(spec_node_ids),
        "candidate_passives_spent": len(normal_node_ids),
        "passive_accounting_excluded_mastery_node_ids": node_classification["mastery_group"],
        "passive_accounting_excluded_start_root_proxy_node_ids": node_classification["start_root_proxy"],
        "passive_accounting_unknown_node_ids": node_classification["unknown"],
        "candidate_has_resolute_technique": RESOLUTE_TECHNIQUE_NODE_ID in spec_node_ids,
        "selected_keystone_node_ids": selected_keystone_ids,
        "main_link_count": len(skill_node.findall("Gem")),
        "main_skill_gem_names": main_skill_gem_names,
        "main_skill_hit_count": _skill_hit_count(skill_node),
        "main_skill_include_in_full_dps": skill_node.attrib.get("includeInFullDPS"),
        "ascendancy_node_ids": ascendancy_node_ids,
        "ascendancy_node_count": len(ascendancy_node_ids),
        "ascendancy_notable_node_ids": ascendancy_notable_node_ids,
        "baseline_warning_codes": _string_list(baseline_calc_snapshot.get("warning_codes")),
        "baseline_requirement_shortfalls": _requirement_shortfalls(baseline_calc_snapshot),
        "authoring_trace_record_kind": candidate_payload.get("record_kind"),
        "authoring_trace_status": candidate_payload.get("status"),
        "authoring_action_kinds": sorted(_authoring_action_kinds(candidate_payload)),
    }
    blockers = [*authoring_blockers, *_blockers(observed, metrics, candidate_payload)]
    return {
        "schema_version": SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "status": "passed" if not blockers else "blocked",
        "loadout_id": "early_game",
        "candidate_id": _candidate_id(candidate_payload),
        "observed": observed,
        "metrics": metrics,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def _authoring_trace_blockers(candidate_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    record_kind = candidate_payload.get("record_kind")
    if record_kind == TREE_LAB_RECORD_KIND:
        return [
            {
                "code": "script_authored_tree_lab_payload",
                "observed": record_kind,
                "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND,
            }
        ]

    blockers: list[dict[str, Any]] = []
    if record_kind != DIRECT_BUILD_DECISION_TRACE_RECORD_KIND:
        blockers.append(
            {
                "code": "missing_agent_decision_trace",
                "observed": record_kind,
                "expected": DIRECT_BUILD_DECISION_TRACE_RECORD_KIND,
            }
        )
    if candidate_payload.get("status") not in {"accepted", "publication_ready"}:
        blockers.append(
            {
                "code": "agent_decision_trace_not_accepted",
                "observed": candidate_payload.get("status"),
                "expected": ["accepted", "publication_ready"],
            }
        )

    decisions = candidate_payload.get("decisions")
    actions = candidate_payload.get("actions")
    observations = candidate_payload.get("observations")
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)) or not decisions:
        blockers.append({"code": "agent_decision_trace_missing_decisions", "observed": 0, "expected_minimum": 1})
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)) or not actions:
        blockers.append({"code": "agent_decision_trace_missing_actions", "observed": 0, "expected_minimum": 1})
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)) or not observations:
        blockers.append({"code": "agent_decision_trace_missing_observations", "observed": 0, "expected_minimum": 1})

    action_kinds = _authoring_action_kinds(candidate_payload)
    missing_action_kinds = [kind for kind in REQUIRED_AUTHORING_ACTION_KINDS if kind not in action_kinds]
    if missing_action_kinds:
        blockers.append(
            {
                "code": "agent_decision_trace_missing_authoring_actions",
                "observed": sorted(action_kinds),
                "expected": list(REQUIRED_AUTHORING_ACTION_KINDS),
                "missing": missing_action_kinds,
            }
        )

    forbidden_script_fields = [
        field
        for field in ("fixed_shell", "agent_decision", "runtime_export", "profile", "profiles")
        if field in candidate_payload
    ]
    if forbidden_script_fields:
        blockers.append(
            {
                "code": "agent_decision_trace_contains_script_authoring_fields",
                "observed": forbidden_script_fields,
                "expected": [],
            }
        )
    return blockers


def _authoring_action_kinds(candidate_payload: Mapping[str, Any]) -> set[str]:
    actions = candidate_payload.get("actions")
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        return set()
    kinds: set[str] = set()
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        kind = action.get("target_mutation_kind") or action.get("mutation_kind")
        if isinstance(kind, str) and kind:
            kinds.add(kind)
    return kinds


def _candidate_id(candidate_payload: Mapping[str, Any]) -> str | None:
    candidate_id = candidate_payload.get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        return candidate_id
    final_candidate = candidate_payload.get("final_candidate")
    if isinstance(final_candidate, Mapping):
        candidate_id = final_candidate.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id:
            return candidate_id
    return None


def _blockers(
    observed: Mapping[str, Any],
    metrics: Mapping[str, float | None],
    candidate_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    _expect_equal(blockers, "level_not_90", observed["level"], DIRECT_BUILD_EARLY_GAME_LEVEL)
    _expect_equal(blockers, "passive_budget_not_113", observed["normal_passive_count"], DIRECT_BUILD_EARLY_GAME_PASSIVE_BUDGET)
    _expect_equal(
        blockers,
        "candidate_passives_not_113",
        observed["candidate_passives_spent"],
        DIRECT_BUILD_EARLY_GAME_PASSIVE_BUDGET,
    )
    _expect_equal(blockers, "main_skill_not_5_link", observed["main_link_count"], EXPECTED_MAIN_LINK_COUNT)
    _expect_equal(blockers, "main_skill_not_in_full_dps", observed["main_skill_include_in_full_dps"], "true")
    if observed["bandit_normalized"] not in DIRECT_BUILD_EARLY_GAME_ALLOWED_BANDIT_VALUES:
        blockers.append(
            {
                "code": "bandit_not_kill_all",
                "observed": observed["bandit"],
                "expected": "Kill All",
            }
        )
    if not observed["identity_policy_key"]:
        blockers.append(
            {
                "code": "ascendancy_identity_policy_missing",
                "observed": {
                    "class_name": observed["class_name"],
                    "ascendancy_name": observed["ascendancy_name"],
                    "expected_class_name": observed["expected_class_name"],
                    "expected_ascendancy_name": observed["expected_ascendancy_name"],
                },
                "expected_supported_ascendancies": sorted(
                    policy["ascendancy_name"] for policy in DIRECT_BUILD_EARLY_GAME_ASCENDANCY_POLICIES.values()
                ),
            }
        )
    if observed["expected_class_name"]:
        _expect_equal(blockers, "class_missing", observed["class_name"], observed["expected_class_name"])
    if observed["expected_ascendancy_name"]:
        _expect_equal(blockers, "ascendancy_missing", observed["ascendancy_name"], observed["expected_ascendancy_name"])
    if observed["expected_spec_ascendancy_id"] is not None:
        _expect_equal(
            blockers,
            "ascendancy_id_missing",
            observed["spec_ascendancy_id"],
            observed["expected_spec_ascendancy_id"],
        )
    _expect_equal(blockers, "ascendancy_points_not_8", observed["ascendancy_node_count"], 8)
    _expect_equal(blockers, "ascendancy_notables_not_4", len(observed["ascendancy_notable_node_ids"]), 4)
    if (
        observed["candidate_has_resolute_technique"] is True
        and _main_skill_is_fireball(observed)
        and not _candidate_has_resolute_technique_justification(candidate_payload)
    ):
        blockers.append(
            {
                "code": "resolute_technique_unjustified_for_fireball",
                "observed": observed["selected_keystone_node_ids"],
                "expected": "No Resolute Technique on a Fireball spell route unless explicitly justified.",
            }
        )
    hit_count = observed["main_skill_hit_count"]
    if isinstance(hit_count, int) and hit_count > 1 and not _candidate_has_skill_count_evidence(candidate_payload):
        blockers.append(
            {
                "code": "skill_count_evidence_missing",
                "observed": hit_count,
                "expected": "Baseline skill hit/overlap/count above 1 requires skill-count evidence.",
            }
        )
    _expect_at_least(blockers, "baseline_life_below_floor", metrics["baseline_life"], MINIMUM_BASELINE_LIFE)
    _expect_at_least(blockers, "baseline_total_ehp_below_floor", metrics["baseline_total_ehp"], MINIMUM_BASELINE_TOTAL_EHP)
    _expect_at_least(
        blockers,
        "baseline_fire_resistance_below_cap",
        metrics["baseline_fire_resist"],
        MINIMUM_BASELINE_ELEMENTAL_RESIST,
    )
    _expect_at_least(
        blockers,
        "baseline_cold_resistance_below_cap",
        metrics["baseline_cold_resist"],
        MINIMUM_BASELINE_ELEMENTAL_RESIST,
    )
    _expect_at_least(
        blockers,
        "baseline_lightning_resistance_below_cap",
        metrics["baseline_lightning_resist"],
        MINIMUM_BASELINE_ELEMENTAL_RESIST,
    )
    _expect_at_least(
        blockers,
        "baseline_chaos_resistance_below_floor",
        metrics["baseline_chaos_resist"],
        MINIMUM_BASELINE_CHAOS_RESIST,
    )
    _expect_mana_usability(blockers, metrics["baseline_mana_unreserved"], metrics["baseline_mana_cost"])
    _expect_at_least(
        blockers,
        "baseline_hit_chance_below_floor",
        metrics["baseline_hit_chance"],
        MINIMUM_BASELINE_HIT_CHANCE,
    )
    _expect_at_least(blockers, "baseline_full_dps_below_floor", metrics["baseline_full_dps"], MINIMUM_BASELINE_FULL_DPS)
    unmet_requirement_warnings = [
        code
        for code in observed["baseline_warning_codes"]
        if code.startswith("unmet_") and code.endswith("_requirement")
    ]
    if unmet_requirement_warnings:
        blockers.append(
            {
                "code": "baseline_unmet_requirement_warning",
                "observed": unmet_requirement_warnings,
                "expected": [],
            }
        )
    if observed["baseline_requirement_shortfalls"]:
        blockers.append(
            {
                "code": "baseline_requirement_shortfall",
                "observed": observed["baseline_requirement_shortfalls"],
                "expected": {},
            }
        )
    return blockers


def _candidate_ascendancy_node_ids(candidate_payload: Mapping[str, Any]) -> list[int]:
    return _nested_int_sequence(
        candidate_payload,
        (
            ("ascendancy_node_ids",),
            ("tree_state", "ascendancy_node_ids"),
            ("materialization_payload", "tree_state", "ascendancy_node_ids"),
        ),
    )


def _candidate_ascendancy_notable_node_ids(
    candidate_payload: Mapping[str, Any],
    ascendancy_node_ids: Sequence[int],
    identity_policy: Mapping[str, Any] | None,
) -> list[int]:
    explicit = _nested_int_sequence(
        candidate_payload,
        (
            ("ascendancy_notable_node_ids",),
            ("tree_state", "ascendancy_notable_node_ids"),
            ("materialization_payload", "tree_state", "ascendancy_notable_node_ids"),
        ),
    )
    if explicit:
        return sorted(set(explicit) & set(ascendancy_node_ids))
    if identity_policy:
        notable_node_ids = set(identity_policy.get("notable_node_ids", set()))
        selected_notables = sorted(set(ascendancy_node_ids) & notable_node_ids)
        if selected_notables:
            return selected_notables
    if len(ascendancy_node_ids) >= 8:
        return sorted(ascendancy_node_ids)[:4]
    if len(ascendancy_node_ids) >= 6:
        return sorted(ascendancy_node_ids)[:3]
    if len(ascendancy_node_ids) >= 4:
        return sorted(ascendancy_node_ids)[:2]
    return sorted(ascendancy_node_ids)


def _expected_ascendancy_policy(
    candidate_payload: Mapping[str, Any],
    *,
    observed_class_name: Any,
    observed_ascendancy_name: Any,
) -> Mapping[str, Any] | None:
    for value in (
        _expected_identity_value(candidate_payload, "ascendancy"),
        _nested_string_value(
            candidate_payload,
            (
                ("tree_state", "ascendancy_id"),
                ("tree_state", "ascendancy_name"),
                ("materialization_payload", "tree_state", "ascendancy_id"),
                ("materialization_payload", "tree_state", "ascendancy_name"),
            ),
        ),
        observed_ascendancy_name,
    ):
        key = _normalized_key(value)
        if key in DIRECT_BUILD_EARLY_GAME_ASCENDANCY_POLICIES:
            return DIRECT_BUILD_EARLY_GAME_ASCENDANCY_POLICIES[key]
    return None


def _expected_identity_value(candidate_payload: Mapping[str, Any], field_name: str) -> str:
    if field_name == "ascendancy":
        paths = (
            ("build_identity", "ascendancy"),
            ("identity", "ascendancy"),
            ("composition_summary", "ascendancy"),
            ("tree_state", "ascendancy_id"),
            ("tree_state", "ascendancy_name"),
            ("materialization_payload", "tree_state", "ascendancy_id"),
            ("materialization_payload", "tree_state", "ascendancy_name"),
        )
    else:
        paths = (
            ("build_identity", field_name),
            ("identity", field_name),
            ("composition_summary", field_name),
        )
    return _nested_string_value(candidate_payload, paths)


def _expected_spec_ascendancy_id(candidate_payload: Mapping[str, Any]) -> int | None:
    return _nested_int_value(
        candidate_payload,
        (
            ("spec_ascendancy_id",),
            ("ascendancy_class_id",),
            ("tree_state", "spec_ascendancy_id"),
            ("tree_state", "ascendancy_class_id"),
            ("materialization_payload", "tree_state", "spec_ascendancy_id"),
            ("materialization_payload", "tree_state", "ascendancy_class_id"),
        ),
    )


def _nested_string_value(payload: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> str:
    for path in paths:
        value: Any = payload
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _nested_int_value(payload: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> int | None:
    for path in paths:
        value: Any = payload
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _normalized_key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _nested_int_sequence(payload: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> list[int]:
    for path in paths:
        value: Any = payload
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        parsed = _int_sequence(value)
        if parsed:
            return parsed
    return []


def _expect_equal(blockers: list[dict[str, Any]], code: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        blockers.append({"code": code, "observed": observed, "expected": expected})


def _expect_at_least(blockers: list[dict[str, Any]], code: str, observed: float | None, expected: float) -> None:
    if observed is None or observed < expected:
        blockers.append({"code": code, "observed": observed, "expected_minimum": expected})


def _required_child(root: ET.Element, tag: str) -> ET.Element:
    child = root.find(tag)
    if child is None:
        raise DirectBuildEarlyGameRailsError(f"PoB XML is missing <{tag}>.")
    return child


def _main_skill_node(root: ET.Element) -> ET.Element:
    for skill_nodes in _skill_search_groups(root):
        full_dps_nodes = [
            skill_node
            for skill_node in skill_nodes
            if _string_value(skill_node.attrib.get("includeInFullDPS")).lower() == "true"
        ]
        for skill_node in full_dps_nodes:
            return skill_node
    for skill_nodes in _skill_search_groups(root):
        gem_skill_nodes = [skill_node for skill_node in skill_nodes if skill_node.findall("Gem")]
        candidate_nodes = gem_skill_nodes or skill_nodes
        for skill_node in candidate_nodes:
            return skill_node
    raise DirectBuildEarlyGameRailsError("PoB XML is missing <Skill>.")


def _main_skill_gem_names(skill_node: ET.Element) -> list[str]:
    names = []
    for gem_node in skill_node.findall("Gem"):
        name = _string_value(gem_node.attrib.get("nameSpec") or gem_node.attrib.get("name") or gem_node.attrib.get("skillId"))
        if name:
            names.append(name)
    return names


def _skill_hit_count(skill_node: ET.Element) -> int | None:
    for key in ("hitCount", "hit_count", "fullDPSHitCount", "full_dps_hit_count", "count", "projectileCount", "overlapCount"):
        value = _optional_int(skill_node.attrib.get(key))
        if value is not None:
            return value
    for gem_node in skill_node.findall("Gem"):
        for key in ("hitCount", "hit_count", "fullDPSHitCount", "full_dps_hit_count", "count", "projectileCount", "overlapCount"):
            value = _optional_int(gem_node.attrib.get(key))
            if value is not None:
                return value
    return None


def _main_skill_is_fireball(observed: Mapping[str, Any]) -> bool:
    names = observed.get("main_skill_gem_names")
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes)):
        return False
    return any(isinstance(name, str) and "fireball" in name.lower() for name in names[:1])


def _candidate_has_skill_count_evidence(candidate_payload: Mapping[str, Any]) -> bool:
    return _candidate_has_any_evidence_ref(
        candidate_payload,
        (
            "skill_count_evidence_refs",
            "skill_mechanics_evidence_refs",
            "overlap_evidence_refs",
            "multi_hit_evidence_refs",
            "full_dps_count_evidence_refs",
            "projectile_count_evidence_refs",
        ),
    )


def _candidate_has_resolute_technique_justification(candidate_payload: Mapping[str, Any]) -> bool:
    return bool(
        _string_value(candidate_payload.get("resolute_technique_justification"))
        or _candidate_has_any_evidence_ref(candidate_payload, ("resolute_technique_evidence_refs",))
    )


def _candidate_has_any_evidence_ref(candidate_payload: Mapping[str, Any], keys: Sequence[str]) -> bool:
    for key in keys:
        if _non_empty_sequence(candidate_payload.get(key)):
            return True
    for row in _sequence_values(candidate_payload.get("decisions")) + _sequence_values(candidate_payload.get("actions")):
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            if _non_empty_sequence(row.get(key)):
                return True
    return False


def _non_empty_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and bool(value)


def _sequence_values(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _skill_search_groups(root: ET.Element) -> list[list[ET.Element]]:
    skills_node = root.find("Skills") if root.tag == "PathOfBuilding" else root.find("./Skills")
    if skills_node is None:
        return [list(root.findall(".//Skill"))]

    groups: list[list[ET.Element]] = []
    active_skill_set_id = _string_value(skills_node.attrib.get("activeSkillSet"))
    skill_set_nodes = list(skills_node.findall("SkillSet"))
    if active_skill_set_id:
        groups.extend(
            list(skill_set_node.findall(".//Skill"))
            for skill_set_node in skill_set_nodes
            if _string_value(skill_set_node.attrib.get("id")) == active_skill_set_id
        )
    direct_skill_nodes = list(skills_node.findall("Skill"))
    if direct_skill_nodes:
        groups.append(direct_skill_nodes)
    if skill_set_nodes:
        groups.append(list(skills_node.findall(".//Skill")))
    if not groups:
        groups.append(list(root.findall(".//Skill")))
    return [group for group in groups if group]


def _baseline_calc_snapshot(normalized_calc_snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    baseline = normalized_calc_snapshot.get("baseline")
    if isinstance(baseline, Mapping):
        calc_snapshot = baseline.get("calc_snapshot")
        if isinstance(calc_snapshot, Mapping):
            return _normalized_calc_snapshot_payload(calc_snapshot)
        if _has_calc_output_surface(baseline):
            return _normalized_calc_snapshot_payload(baseline)
    if _has_calc_output_surface(normalized_calc_snapshot):
        return _normalized_calc_snapshot_payload(normalized_calc_snapshot)
    raise DirectBuildEarlyGameRailsError(
        "Normalized calc snapshot is missing baseline.calc_snapshot or baseline main_output/calcs_output."
    )


def _baseline_main_output(calc_snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    main_output = calc_snapshot.get("main_output")
    if isinstance(main_output, Mapping):
        return main_output
    calcs_output = calc_snapshot.get("calcs_output")
    if isinstance(calcs_output, Mapping):
        return calcs_output
    raise DirectBuildEarlyGameRailsError("baseline.calc_snapshot.main_output must be an object.")


def _numeric_metric(payload: Mapping[str, Any], key: str) -> float | None:
    return _optional_float(payload.get(key))


def _numeric_metric_any(payload: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = _numeric_metric(payload, key)
        if value is not None:
            return value
    return None


def _expect_mana_usability(
    blockers: list[dict[str, Any]],
    mana_unreserved: float | None,
    mana_cost: float | None,
) -> None:
    if mana_cost is None or mana_cost <= 0:
        return
    expected = mana_cost * MINIMUM_MANA_CAST_BUFFER
    if mana_unreserved is None or mana_unreserved < expected:
        blockers.append(
            {
                "code": "baseline_mana_usability_below_floor",
                "observed": {
                    "mana_unreserved": mana_unreserved,
                    "mana_cost": mana_cost,
                },
                "expected_minimum": {
                    "mana_unreserved": expected,
                    "casts_buffer": MINIMUM_MANA_CAST_BUFFER,
                },
            }
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(entry) for entry in value if isinstance(entry, str) and entry]


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized_bandit(value: Any) -> str:
    text = _string_value(value).lower().replace("_", " ").replace("-", " ")
    if text == "kill all":
        return "kill_all"
    return text


def _has_calc_output_surface(payload: Mapping[str, Any]) -> bool:
    return isinstance(payload.get("main_output"), Mapping) or isinstance(payload.get("calcs_output"), Mapping)


def _normalized_calc_snapshot_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = dict(payload)
    if not isinstance(snapshot.get("main_output"), Mapping) and isinstance(snapshot.get("calcs_output"), Mapping):
        snapshot["main_output"] = dict(snapshot["calcs_output"])
    return snapshot


def _requirement_shortfalls(calc_snapshot: Mapping[str, Any]) -> dict[str, dict[str, float | bool | None]]:
    triage = calc_snapshot.get("triage")
    if not isinstance(triage, Mapping):
        return _requirement_shortfalls_from_main_output(_baseline_main_output(calc_snapshot))
    requirement_pressure = triage.get("requirement_pressure")
    if not isinstance(requirement_pressure, Mapping):
        return _requirement_shortfalls_from_main_output(_baseline_main_output(calc_snapshot))

    shortfalls: dict[str, dict[str, float | bool | None]] = {}
    for requirement_name, payload in requirement_pressure.items():
        if not isinstance(requirement_name, str) or not isinstance(payload, Mapping):
            continue
        satisfied = payload.get("satisfied")
        shortfall = _optional_float(payload.get("shortfall"))
        if satisfied is not True or (shortfall is not None and shortfall > 0):
            shortfalls[requirement_name] = {
                "satisfied": bool(satisfied),
                "shortfall": shortfall,
                "available": _optional_float(payload.get("available")),
                "required": _optional_float(payload.get("required")),
            }
    return shortfalls


def _requirement_shortfalls_from_main_output(main_output: Mapping[str, Any]) -> dict[str, dict[str, float | bool | None]]:
    shortfalls: dict[str, dict[str, float | bool | None]] = {}
    for requirement_name, available_key, required_key in (
        ("strength", "Str", "ReqStr"),
        ("dexterity", "Dex", "ReqDex"),
        ("intelligence", "Int", "ReqInt"),
        ("omniscience", "Omni", "ReqOmni"),
    ):
        available = _optional_float(main_output.get(available_key))
        required = _optional_float(main_output.get(required_key))
        if available is None or required is None:
            continue
        shortfall = max(required - available, 0.0)
        if shortfall > 0:
            shortfalls[requirement_name] = {
                "satisfied": False,
                "shortfall": shortfall,
                "available": available,
                "required": required,
            }
    return shortfalls


def _optional_int(value: Any) -> int | None:
    numeric = _optional_float(value)
    return None if numeric is None else int(numeric)


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _csv_ints(value: str) -> list[int]:
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError:
            continue
    return result


def _int_sequence(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[int] = []
    for entry in value:
        parsed = _optional_int(entry)
        if parsed is not None:
            result.append(parsed)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DirectBuildEarlyGameRailsError(f"JSON file must contain an object: {path}")
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Early Game Direct Build rails.")
    parser.add_argument("--candidate-json", type=Path, required=True)
    parser.add_argument("--pob-xml", type=Path, required=True)
    parser.add_argument("--calc-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_direct_build_early_game_rails_report(
        candidate_payload=_load_json(args.candidate_json),
        pob_xml_text=args.pob_xml.read_text(encoding="utf-8"),
        normalized_calc_snapshot=_load_json(args.calc_snapshot),
    )
    write_json(args.output, report)
    print(args.output)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
