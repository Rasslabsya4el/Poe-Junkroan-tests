from __future__ import annotations

from typing import Any

from junkroan.pob.graph_tree_authoring import resolve_graph_tree_closure
from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus, classify_tree_node_ids


def _codes(report: dict[str, Any]) -> set[str]:
    return {str(blocker.get("code") or blocker.get("blocker_id")) for blocker in report["blockers"]}


def test_graph_closure_blocks_op2f52_inactive_ids_before_emitting_payload() -> None:
    report = resolve_graph_tree_closure(
        {
            "tree_goal_package": {
                "active_tree_version": "3_28",
                "class_id": "Templar",
                "start_node_id": 61525,
                "target_node_ids": [784, 1581, 2220],
            }
        }
    )

    assert report["status"] == "blocked"
    assert "graph_tree_invalid_or_unavailable_goal_node" in _codes(report)
    details = report["graph_closure_evidence"]["invalid_goal_details"]
    assert [detail["node_id"] for detail in details] == [784, 1581, 2220]
    assert {
        detail["reason"]
        for detail in details
    } == {"inactive_or_not_allocatable_in_canonical_active_tree"}
    emitted_ids = set(report["tree_state"]["user_allocated_node_ids"])
    assert not emitted_ids.intersection({784, 1581, 2220})


def test_graph_closure_blocks_op2f54_style_tiny_goal_package_before_metric_probes() -> None:
    report = resolve_graph_tree_closure(
        {
            "tree_goal_package": {
                "active_tree_version": "3_28",
                "class_id": "Templar",
                "start_node_id": 61525,
                "current_user_allocated_node_ids": [54694],
                "target_node_ids": [54694, 33435],
                "mastery_effect_ids": ["41415:47642"],
                "ascendancy_node_ids": [662, 53884, 37486, 48214, 10635, 39790, 57222, 32816],
            }
        }
    )

    codes = _codes(report)
    assert report["status"] == "blocked"
    assert "graph_tree_goal_package_too_few_targets" in codes
    assert "graph_tree_goal_package_missing_offense_goals" in codes
    assert "graph_tree_goal_package_missing_life_defense_goals" in codes
    assert "graph_tree_goal_package_missing_attribute_requirement_plan" in codes
    assert "graph_tree_goal_package_closure_passive_budget_too_low" in codes
    assert report["graph_closure_evidence"]["lvl90_goal_package_contract"]["status"] == "blocked"
    _assert_active_graph_output(report)


def test_graph_closure_blocks_forty_passive_package_as_incomplete_lvl90_package() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    package = _synthetic_lvl90_goal_package(target_count=20)

    report = resolve_graph_tree_closure({"tree_goal_package": package}, tree_corpus=corpus)

    assert report["status"] == "blocked"
    assert "graph_tree_goal_package_closure_passive_budget_too_low" in _codes(report)
    assert report["graph_closure_evidence"]["full_passive_count"] == 40
    contract = report["graph_closure_evidence"]["lvl90_goal_package_contract"]
    assert contract["full_passive_count"] == 40
    assert contract["expected_passive_budget"] == 113


def test_graph_closure_blocks_package_without_life_defense_goals() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    package = _synthetic_lvl90_goal_package()
    package["defense_goal_node_ids"] = []

    report = resolve_graph_tree_closure({"tree_goal_package": package}, tree_corpus=corpus)

    assert report["status"] == "blocked"
    assert "graph_tree_goal_package_missing_life_defense_goals" in _codes(report)


def test_graph_closure_blocks_package_without_mastery_effect_goals() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    package = _synthetic_lvl90_goal_package()
    package["mastery_effect_ids"] = []

    report = resolve_graph_tree_closure({"tree_goal_package": package}, tree_corpus=corpus)

    assert report["status"] == "blocked"
    assert "graph_tree_goal_package_missing_mastery_effects" in _codes(report)


def test_graph_closure_blocks_package_without_attribute_requirement_plan() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    package = _synthetic_lvl90_goal_package()
    package["attribute_goal_node_ids"] = []

    report = resolve_graph_tree_closure({"tree_goal_package": package}, tree_corpus=corpus)

    assert report["status"] == "blocked"
    assert "graph_tree_goal_package_missing_attribute_requirement_plan" in _codes(report)


def test_graph_closure_accepts_valid_synthetic_lvl90_goal_package() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    report = resolve_graph_tree_closure({"tree_goal_package": _synthetic_lvl90_goal_package()}, tree_corpus=corpus)

    assert report["status"] == "accepted"
    evidence = report["graph_closure_evidence"]
    assert evidence["canonical_tree_version"] == "3_28"
    assert evidence["full_passive_count"] == 90
    assert evidence["travel_to_payoff_ratio"] == 1
    assert evidence["lvl90_goal_package_contract"]["status"] == "accepted"
    assert evidence["tool_boundary"]["chooses_build_goals"] is False
    assert evidence["tool_boundary"]["optimizes_tree"] is False
    assert set(evidence["connector_node_ids"]) == set(range(2, 47))
    assert set(evidence["target_node_ids"]) == set(range(51, 96))


def test_graph_closure_adds_mastery_prerequisite_anchor_path_for_selected_mastery() -> None:
    corpus = _synthetic_lvl90_tree_corpus_with_mastery_prerequisite()
    report = resolve_graph_tree_closure({"tree_goal_package": _synthetic_lvl90_goal_package()}, tree_corpus=corpus)

    assert report["status"] == "accepted"
    evidence = report["graph_closure_evidence"]
    assert evidence["explicit_target_node_ids"] == list(range(51, 96))
    assert evidence["mastery_prerequisite_node_ids"] == [96]
    assert evidence["mastery_prerequisite_details"] == [
        {
            "mastery_effect_id": "100:5001",
            "mastery_node_id": 100,
            "effect_id": "5001",
            "prerequisite_node_ids": [96],
        }
    ]
    assert 96 in report["tree_state"]["user_allocated_node_ids"]
    assert 47 in evidence["connector_node_ids"]
    assert 96 in evidence["target_node_ids"]


def test_graph_closure_blocks_selected_mastery_when_prerequisite_authority_has_no_anchor() -> None:
    corpus = _synthetic_lvl90_tree_corpus() | {"mastery_prerequisite_node_ids_by_node_id": {}}
    report = resolve_graph_tree_closure({"tree_goal_package": _synthetic_lvl90_goal_package()}, tree_corpus=corpus)

    assert report["status"] == "blocked"
    assert "graph_tree_mastery_prerequisite_authority_missing" in _codes(report)


def test_graph_closure_keeps_mastery_ascendancy_and_start_ids_typed_outside_user_passives() -> None:
    corpus = _synthetic_lvl90_tree_corpus()
    report = resolve_graph_tree_closure({"tree_goal_package": _synthetic_lvl90_goal_package()}, tree_corpus=corpus)

    user_ids = set(report["tree_state"]["user_allocated_node_ids"])
    assert report["status"] == "accepted"
    assert 1 not in user_ids
    assert 100 not in user_ids
    assert 5001 not in user_ids
    assert not user_ids.intersection({201, 202, 203, 204})
    assert report["tree_state"]["mastery_effect_ids"] == ["100:5001"]
    assert report["tree_state"]["ascendancy_node_ids"] == [201, 202, 203, 204]


def test_graph_closure_returns_precise_unreachable_target_blocker() -> None:
    target_ids = list(range(51, 59))
    report = resolve_graph_tree_closure(
        {
            "tree_goal_package": {
                "active_tree_version": "3_28",
                "class_id": "Witch",
                "start_node_id": 1,
                "target_node_ids": target_ids,
                "offense_goal_node_ids": [52, 53],
                "defense_goal_node_ids": [54, 55],
                "attribute_goal_node_ids": [56],
                "utility_goal_node_ids": [57, 58],
                "mastery_effect_ids": ["100:5001"],
                "ascendancy_node_ids": [201, 202, 203, 204],
                "archetype": "synthetic Fireball",
                "rationale": "Synthetic package exercises unreachable-goal reporting without build authorship.",
            }
        },
        tree_corpus={
            "canonical_tree_version": "3_28",
            "tree_version": "3_28",
            "available_node_ids": [1, 2, 3, *target_ids],
            "active_allocatable_node_ids": [1, 2, 3, *target_ids],
            "known_node_ids": [1, 2, 3, 100, 201, 202, 203, 204, 5001, *target_ids],
            "ordinary_node_ids": [1, 2, 3],
            "payoff_node_ids": target_ids,
            "mastery_node_ids": [100],
            "mastery_effects_by_node_id": {"100": ["5001"]},
            "ascendancy_node_ids": [201, 202, 203, 204],
            "start_root_proxy_node_ids": [],
            "adjacency": {
                "1": [2],
                "2": [1, 51],
                "51": [2],
                "52": [],
                "53": [],
                "54": [],
                "55": [],
                "56": [],
                "57": [],
                "58": [],
            },
        },
    )

    assert report["status"] == "blocked"
    assert "graph_tree_goal_unreachable" in _codes(report)
    assert set(report["graph_closure_evidence"]["unreachable_target_node_ids"]) == set(range(52, 59))


def _synthetic_lvl90_tree_corpus() -> dict[str, Any]:
    connectors = list(range(2, 47))
    targets = list(range(51, 96))
    adjacency: dict[str, list[int]] = {"1": connectors}
    for connector, target in zip(connectors, targets, strict=True):
        adjacency[str(connector)] = [1, target]
        adjacency[str(target)] = [connector]
    return {
        "canonical_tree_version": "3_28",
        "tree_version": "3_28",
        "class_id": "Templar",
        "start_node_id": 1,
        "available_node_ids": [*connectors, *targets],
        "active_allocatable_node_ids": [*connectors, *targets],
        "known_node_ids": [1, 100, 201, 202, 203, 204, 5001, *connectors, *targets],
        "ordinary_node_ids": connectors,
        "payoff_node_ids": targets,
        "mastery_node_ids": [100],
        "mastery_effects_by_node_id": {"100": ["5001"]},
        "ascendancy_node_ids": [201, 202, 203, 204],
        "start_root_proxy_node_ids": [1],
        "adjacency": adjacency,
    }


def _synthetic_lvl90_tree_corpus_with_mastery_prerequisite() -> dict[str, Any]:
    corpus = _synthetic_lvl90_tree_corpus()
    corpus["available_node_ids"] = [*corpus["available_node_ids"], 47, 96]
    corpus["active_allocatable_node_ids"] = [*corpus["active_allocatable_node_ids"], 47, 96]
    corpus["known_node_ids"] = [*corpus["known_node_ids"], 47, 96]
    corpus["ordinary_node_ids"] = [*corpus["ordinary_node_ids"], 47]
    corpus["payoff_node_ids"] = [*corpus["payoff_node_ids"], 96]
    corpus["mastery_prerequisite_node_ids_by_node_id"] = {"100": [96]}
    corpus["adjacency"] = dict(corpus["adjacency"]) | {
        "1": [*corpus["adjacency"]["1"], 47],
        "47": [1, 96],
        "96": [47, 100],
    }
    return corpus


def _synthetic_lvl90_goal_package(*, target_count: int = 45) -> dict[str, Any]:
    targets = list(range(51, 51 + target_count))
    offense = targets[: min(15, target_count)]
    defense = targets[min(15, target_count) : min(30, target_count)] or targets[-3:-2]
    attributes = targets[min(30, target_count) : min(35, target_count)] or targets[-2:-1]
    utility = targets[min(35, target_count) :] or targets[-1:]
    return {
        "active_tree_version": "3_28",
        "class_id": "Templar",
        "start_node_id": 1,
        "target_node_ids": targets,
        "offense_goal_node_ids": offense,
        "defense_goal_node_ids": defense,
        "attribute_goal_node_ids": attributes,
        "utility_goal_node_ids": utility,
        "mastery_effect_ids": ["100:5001"],
        "ascendancy_node_ids": [201, 202, 203, 204],
        "archetype": "synthetic hit spell",
        "rationale": "Synthetic lvl90 package includes offense, life/defense, attributes, mastery, and ascendancy goals.",
    }


def _assert_active_graph_output(report: dict[str, Any]) -> None:
    corpus = canonical_active_tree_corpus()
    available = set(corpus["active_allocatable_node_ids"])
    inactive = set(corpus["inactive_or_unavailable_node_ids"])
    ordinary = set(corpus["ordinary_node_ids"])
    user_ids = set(report["tree_state"]["user_allocated_node_ids"])
    connector_ids = set(report["graph_closure_evidence"]["connector_node_ids"])
    assert user_ids
    assert user_ids.issubset(available)
    assert not user_ids.intersection(inactive)
    assert connector_ids.issubset(ordinary)
    classification = classify_tree_node_ids(user_ids, namespace="passive_node")
    assert not classification["mastery_group"]
    assert not classification["mastery_effect_ref"]
    assert not classification["ascendancy"]
    assert not classification["start_root_proxy"]
