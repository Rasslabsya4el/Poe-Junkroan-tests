"""Deterministic tree payload normalization for Direct Build agents.

This module does not choose passive nodes, masteries, or ascendancy packages.
It only separates ids already present in an agent-authored tree payload into
the fields PoB apply/readback can reconcile.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tree_version_contract import canonical_tree_version

TREE_PAYLOAD_NORMALIZATION_RECORD_KIND = "tree_payload_normalization_report"
TREE_PAYLOAD_NORMALIZATION_SCHEMA_VERSION = "0.1.0"
TREE_NODE_CLASSIFICATION_CATEGORIES = (
    "ordinary_connector_path",
    "payoff_notable",
    "mastery_group",
    "mastery_effect_ref",
    "ascendancy",
    "start_root_proxy",
    "unknown",
    "namespace_collision",
    "ambiguous_bare_id",
)
TREE_NODE_PASSIVE_NAMESPACES = {
    "passive_node",
    "user_allocated_node_ids",
    "allocated_node_ids",
    "selected_route_node_ids",
    "tree_spec_nodes",
}
TREE_NODE_MASTERY_EFFECT_NAMESPACES = {"mastery_effect", "mastery_effect_ids"}


def normalize_tree_payload(
    tree_state: Mapping[str, Any],
    *,
    tree_corpus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a normalized tree payload plus fail-closed blockers.

    The normalized payload is a representation cleanup only:
    - ordinary passives remain in user_allocated_node_ids;
    - selected mastery group ids move to mastery_effect_ids evidence only;
    - ascendancy ids move to ascendancy_node_ids;
    - start/root/proxy ids move to metadata.

    Unknown ids and incomplete mastery payloads block.
    """

    original = dict(tree_state)
    authority = _tree_payload_authority(_mapping(tree_corpus))
    blockers: list[dict[str, Any]] = []
    original_user_ids = _payload_user_allocated_node_ids(original)
    mastery_payloads = _mastery_payloads(original)
    valid_mastery_pairs = [
        (payload["node_id"], payload["effect_id"])
        for payload in mastery_payloads
        if payload["node_id"] is not None and _int_value(payload["effect_id"]) is not None
    ]
    selected_mastery_node_ids = {node_id for node_id, _ in valid_mastery_pairs}
    selected_mastery_effect_ids = {_int_value(effect_id) for _, effect_id in valid_mastery_pairs}
    selected_mastery_effect_ids.discard(None)

    invalid_mastery_payloads = [payload["raw"] for payload in mastery_payloads if payload["node_id"] is None or not payload["effect_id"]]
    if invalid_mastery_payloads:
        blockers.append(
            _blocker(
                "tree_payload_mastery_effect_payload_invalid",
                f"Invalid mastery payload entries: {invalid_mastery_payloads}",
                "Use mastery_effect_ids entries as '<node_id>:<effect_id>' or objects with node_id/effect_id.",
            )
        )

    duplicate_mastery_nodes = sorted(
        node_id for node_id, count in Counter(node_id for node_id, _ in valid_mastery_pairs).items() if count > 1
    )
    if duplicate_mastery_nodes:
        blockers.append(
            _blocker(
                "tree_payload_multiple_mastery_effects_for_group",
                f"Multiple mastery effects selected for mastery group nodes: {duplicate_mastery_nodes}",
                "Select at most one mastery effect for each mastery group node.",
            )
        )

    for node_id, effect_id in valid_mastery_pairs:
        if authority.mastery_node_ids and node_id not in authority.mastery_node_ids:
            blockers.append(
                _blocker(
                    "tree_payload_mastery_effect_group_unknown",
                    f"Mastery effect payload references unknown mastery group node {node_id}.",
                    "Use a mastery group node from the canonical tree corpus.",
                )
            )
            continue
        allowed_effects = authority.mastery_effects_by_node.get(node_id, set())
        if allowed_effects and _normalized_key(effect_id) not in allowed_effects:
            blockers.append(
                _blocker(
                    "tree_payload_mastery_effect_not_valid_for_group",
                    f"Mastery effect {effect_id} is not valid for mastery group node {node_id}.",
                    "Use a mastery effect id exposed by the active tree corpus for that mastery node.",
                )
            )

    ordinary_user_ids: list[int] = []
    moved_mastery_node_ids: list[int] = []
    unselected_mastery_node_ids: list[int] = []
    moved_ascendancy_node_ids: list[int] = []
    moved_start_root_proxy_node_ids: list[int] = []
    moved_mastery_effect_ids: list[int] = []
    unknown_node_ids: list[int] = []
    normalized_ascendancy_ids = set(_int_sequence(original.get("ascendancy_node_ids")))
    normalized_start_root_proxy_ids = set(_int_sequence(original.get("start_root_proxy_node_ids")))

    for node_id in original_user_ids:
        if node_id in authority.mastery_node_ids:
            if node_id in selected_mastery_node_ids:
                moved_mastery_node_ids.append(node_id)
            else:
                unselected_mastery_node_ids.append(node_id)
            continue
        if node_id in authority.ascendancy_node_ids:
            moved_ascendancy_node_ids.append(node_id)
            normalized_ascendancy_ids.add(node_id)
            continue
        if node_id in authority.start_root_proxy_node_ids:
            moved_start_root_proxy_node_ids.append(node_id)
            normalized_start_root_proxy_ids.add(node_id)
            continue
        if node_id in authority.ordinary_node_ids or node_id in authority.payoff_node_ids:
            ordinary_user_ids.append(node_id)
            continue
        if node_id in authority.mastery_effect_ids or node_id in selected_mastery_effect_ids:
            moved_mastery_effect_ids.append(node_id)
            continue
        if authority.known_node_ids and node_id not in authority.known_node_ids:
            unknown_node_ids.append(node_id)
            continue
        ordinary_user_ids.append(node_id)

    if unselected_mastery_node_ids:
        blockers.append(
            _blocker(
                "tree_payload_mastery_group_without_effect",
                f"Mastery group nodes in user_allocated_node_ids have no selected mastery effect: {sorted(set(unselected_mastery_node_ids))}",
                "Drop unselected mastery group nodes or add an explicit node_id:effect_id mastery payload.",
            )
        )
    if moved_mastery_effect_ids:
        blockers.append(
            _blocker(
                "tree_payload_mastery_effect_id_in_user_allocated_node_ids",
                f"Mastery effect ids cannot appear in user_allocated_node_ids: {sorted(set(moved_mastery_effect_ids))}",
                "Keep mastery effect ids only inside mastery_effect_ids node:effect entries.",
            )
        )
    if unknown_node_ids:
        blockers.append(
            _blocker(
                "tree_payload_unknown_node_ids",
                f"Unknown tree node ids: {sorted(set(unknown_node_ids))}",
                "Query the canonical active tree corpus before applying tree payload ids.",
            )
        )

    normalized = dict(original)
    normalized["user_allocated_node_ids"] = sorted(set(ordinary_user_ids))
    if valid_mastery_pairs:
        normalized["mastery_effect_ids"] = [f"{node_id}:{effect_id}" for node_id, effect_id in sorted(set(valid_mastery_pairs))]
    if normalized_ascendancy_ids:
        normalized["ascendancy_node_ids"] = sorted(normalized_ascendancy_ids)
    if normalized_start_root_proxy_ids:
        normalized["start_root_proxy_node_ids"] = sorted(normalized_start_root_proxy_ids)

    evidence = {
        "original_user_allocated_node_ids": original_user_ids,
        "normalized_user_allocated_node_ids": normalized["user_allocated_node_ids"],
        "original_user_allocated_node_count": len(original_user_ids),
        "normalized_user_allocated_node_count": len(normalized["user_allocated_node_ids"]),
        "selected_mastery_node_ids": sorted(selected_mastery_node_ids),
        "normalized_mastery_effect_ids": list(normalized.get("mastery_effect_ids") or []),
        "normalized_ascendancy_node_ids": sorted(normalized_ascendancy_ids),
        "normalized_start_root_proxy_node_ids": sorted(normalized_start_root_proxy_ids),
        "moved_mastery_node_ids": sorted(set(moved_mastery_node_ids)),
        "unselected_mastery_node_ids": sorted(set(unselected_mastery_node_ids)),
        "moved_ascendancy_node_ids": sorted(set(moved_ascendancy_node_ids)),
        "moved_start_root_proxy_node_ids": sorted(set(moved_start_root_proxy_node_ids)),
        "moved_mastery_effect_ids": sorted(set(moved_mastery_effect_ids)),
        "unknown_node_ids": sorted(set(unknown_node_ids)),
        "invalid_mastery_payloads": invalid_mastery_payloads,
        "normalization_changed_payload": _normalization_changed(original, normalized),
        "authority": {
            "known_node_ids_checked": bool(authority.known_node_ids),
            "mastery_node_count": len(authority.mastery_node_ids),
            "ascendancy_node_count": len(authority.ascendancy_node_ids),
            "start_root_proxy_node_count": len(authority.start_root_proxy_node_ids),
        },
    }
    status = "blocked" if blockers else "accepted"
    return {
        "record_kind": TREE_PAYLOAD_NORMALIZATION_RECORD_KIND,
        "schema_version": TREE_PAYLOAD_NORMALIZATION_SCHEMA_VERSION,
        "status": status,
        "blockers": _dedupe_blockers(blockers),
        "normalized_tree_state": normalized,
        "evidence": evidence,
    }


def classify_tree_node_ids(
    node_ids: Any,
    *,
    namespace: str = "bare",
    tree_corpus: Mapping[str, Any] | None = None,
) -> dict[str, list[int]]:
    """Classify submitted/readback ids against the active tree authority.

    This is a read-only accounting helper. It does not add, remove, or choose
    nodes for a candidate. When the caller has field-level context, pass a
    namespace such as ``passive_node`` or ``mastery_effect`` so numeric ids that
    collide across namespaces remain typed instead of being compared as bare
    integers.
    """

    authority = _tree_payload_authority(_mapping(tree_corpus))
    result: dict[str, list[int]] = {category: [] for category in TREE_NODE_CLASSIFICATION_CATEGORIES}
    normalized_namespace = _normalized_key(namespace) or "bare"
    raw_node_ids = list(node_ids) if isinstance(node_ids, set) else node_ids
    for node_id in sorted(set(_int_sequence(raw_node_ids))):
        memberships = _node_namespace_memberships(node_id, authority)
        if len(memberships) > 1:
            result["namespace_collision"].append(node_id)
        if normalized_namespace == "bare" and len(memberships) > 1:
            result["ambiguous_bare_id"].append(node_id)
            continue
        if normalized_namespace in TREE_NODE_MASTERY_EFFECT_NAMESPACES:
            if "mastery_effect_ref" in memberships:
                result["mastery_effect_ref"].append(node_id)
            else:
                result["unknown"].append(node_id)
            continue
        if node_id in authority.mastery_node_ids:
            result["mastery_group"].append(node_id)
        elif node_id in authority.ascendancy_node_ids:
            result["ascendancy"].append(node_id)
        elif node_id in authority.start_root_proxy_node_ids:
            result["start_root_proxy"].append(node_id)
        elif node_id in authority.payoff_node_ids:
            result["payoff_notable"].append(node_id)
        elif node_id in authority.ordinary_node_ids or (authority.known_node_ids and node_id in authority.known_node_ids):
            result["ordinary_connector_path"].append(node_id)
        elif node_id in authority.mastery_effect_ids:
            result["mastery_effect_ref"].append(node_id)
        else:
            result["unknown"].append(node_id)
    return result


def tree_node_id_namespace_memberships(
    node_ids: Any,
    *,
    tree_corpus: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return all corpus namespaces each numeric id belongs to."""

    authority = _tree_payload_authority(_mapping(tree_corpus))
    raw_node_ids = list(node_ids) if isinstance(node_ids, set) else node_ids
    return {
        str(node_id): _node_namespace_memberships(node_id, authority)
        for node_id in sorted(set(_int_sequence(raw_node_ids)))
    }


@lru_cache(maxsize=1)
def canonical_active_tree_corpus() -> dict[str, Any]:
    """Return the skill-owned active passive tree authority used before PoB apply."""

    base = Path(__file__).resolve().parent / "corpus_data"
    passive_records = _records_from_json(base / "passives.json")
    mastery_records = _records_from_json(base / "masteries.json")
    ascendancy_records = _records_from_json(base / "ascendancies.json")
    known_node_ids: set[int] = set()
    available_node_ids: set[int] = set()
    inactive_or_unavailable_node_ids: set[int] = set()
    ordinary_node_ids: set[int] = set()
    payoff_node_ids: set[int] = set()
    mastery_node_ids: set[int] = set()
    mastery_effects_by_node: dict[int, list[str]] = {}
    mastery_prerequisites_by_node: dict[str, list[int]] = {}
    ascendancy_node_ids: set[int] = set()
    start_root_proxy_node_ids: set[int] = set()
    adjacency: dict[str, list[int]] = {}

    for record in passive_records:
        node_id = _record_node_id(record)
        if node_id is None:
            continue
        known_node_ids.add(node_id)
        neighbors = sorted(set(_int_sequence(record.get("incoming_node_ids")) + _int_sequence(record.get("outgoing_node_ids"))))
        if neighbors:
            adjacency[str(node_id)] = neighbors
        is_start_proxy = (
            _truthy(record.get("is_proxy"))
            or _truthy(record.get("is_ascendancy_start"))
            or record.get("class_start_index") is not None
        )
        if is_start_proxy:
            start_root_proxy_node_ids.add(node_id)
            if neighbors:
                available_node_ids.add(node_id)
            continue
        if _truthy(record.get("is_notable")) or _truthy(record.get("is_keystone")):
            payoff_node_ids.add(node_id)
        else:
            ordinary_node_ids.add(node_id)
        if neighbors:
            available_node_ids.add(node_id)
        else:
            inactive_or_unavailable_node_ids.add(node_id)

    for record in mastery_records:
        node_id = _record_node_id(record)
        if node_id is None:
            continue
        known_node_ids.add(node_id)
        mastery_node_ids.add(node_id)
        effects: list[str] = []
        for effect in _sequence(record.get("mastery_effects")):
            effect_id = _int_value(_mapping(effect).get("effect_id"))
            if effect_id is not None:
                effects.append(str(effect_id))
        if effects:
            mastery_effects_by_node[str(node_id)] = sorted(set(effects))
        prerequisites = sorted(set(_int_sequence(record.get("incoming_node_ids"))))
        if prerequisites:
            mastery_prerequisites_by_node[str(node_id)] = prerequisites

    for ascendancy in ascendancy_records:
        for start_node_id in _int_sequence(_mapping(ascendancy).get("start_node_ids")):
            known_node_ids.add(start_node_id)
            start_root_proxy_node_ids.add(start_node_id)
        for node in _sequence(_mapping(ascendancy).get("nodes")):
            node_id = _record_node_id(_mapping(node))
            if node_id is None:
                continue
            known_node_ids.add(node_id)
            if _truthy(_mapping(node).get("is_ascendancy_start")) or node_id in start_root_proxy_node_ids:
                start_root_proxy_node_ids.add(node_id)
            else:
                ascendancy_node_ids.add(node_id)

    return {
        "record_kind": "canonical_active_tree_node_availability_corpus",
        "canonical_tree_version": canonical_tree_version(),
        "tree_version": canonical_tree_version(),
        "available_node_ids": sorted(available_node_ids),
        "active_allocatable_node_ids": sorted(available_node_ids),
        "known_node_ids": sorted(known_node_ids),
        "inactive_or_unavailable_node_ids": sorted(inactive_or_unavailable_node_ids),
        "ordinary_node_ids": sorted(ordinary_node_ids),
        "payoff_node_ids": sorted(payoff_node_ids),
        "mastery_node_ids": sorted(mastery_node_ids),
        "mastery_effects_by_node_id": mastery_effects_by_node,
        "mastery_prerequisite_node_ids_by_node_id": mastery_prerequisites_by_node,
        "ascendancy_node_ids": sorted(ascendancy_node_ids),
        "start_root_proxy_node_ids": sorted(start_root_proxy_node_ids),
        "adjacency": adjacency,
    }


def _node_namespace_memberships(node_id: int, authority: "_TreePayloadAuthority") -> list[str]:
    memberships: list[str] = []
    if node_id in authority.ordinary_node_ids:
        memberships.append("ordinary_connector_path")
    if node_id in authority.payoff_node_ids:
        memberships.append("payoff_notable")
    if node_id in authority.mastery_node_ids:
        memberships.append("mastery_group")
    if node_id in authority.mastery_effect_ids:
        memberships.append("mastery_effect_ref")
    if node_id in authority.ascendancy_node_ids:
        memberships.append("ascendancy")
    if node_id in authority.start_root_proxy_node_ids:
        memberships.append("start_root_proxy")
    if not memberships and authority.known_node_ids and node_id in authority.known_node_ids:
        memberships.append("ordinary_connector_path")
    return memberships


class _TreePayloadAuthority:
    def __init__(
        self,
        *,
        known_node_ids: set[int],
        mastery_node_ids: set[int],
        mastery_effect_ids: set[int],
        mastery_effects_by_node: dict[int, set[str]],
        ascendancy_node_ids: set[int],
        start_root_proxy_node_ids: set[int],
        payoff_node_ids: set[int],
        ordinary_node_ids: set[int],
    ) -> None:
        self.known_node_ids = known_node_ids
        self.mastery_node_ids = mastery_node_ids
        self.mastery_effect_ids = mastery_effect_ids
        self.mastery_effects_by_node = mastery_effects_by_node
        self.ascendancy_node_ids = ascendancy_node_ids
        self.start_root_proxy_node_ids = start_root_proxy_node_ids
        self.payoff_node_ids = payoff_node_ids
        self.ordinary_node_ids = ordinary_node_ids


def _tree_payload_authority(tree_corpus: Mapping[str, Any]) -> _TreePayloadAuthority:
    if tree_corpus:
        return _authority_from_tree_corpus(tree_corpus)
    return _canonical_tree_payload_authority()


def _authority_from_tree_corpus(tree_corpus: Mapping[str, Any]) -> _TreePayloadAuthority:
    mastery_effects_by_node = _mastery_effects_by_node(tree_corpus)
    mastery_effect_ids = {
        _int_value(effect)
        for effects in mastery_effects_by_node.values()
        for effect in effects
        if _int_value(effect) is not None
    }
    mastery_effect_ids.discard(None)
    mastery_node_ids = _int_set(tree_corpus.get("mastery_node_ids")) | set(mastery_effects_by_node)
    ascendancy_node_ids = _int_set(
        tree_corpus.get("ascendancy_node_ids")
        or tree_corpus.get("allocated_ascendancy_node_ids")
        or tree_corpus.get("all_ascendancy_node_ids")
    )
    start_root_proxy_node_ids = _int_set(
        tree_corpus.get("start_root_proxy_node_ids")
        or tree_corpus.get("proxy_node_ids")
        or tree_corpus.get("root_proxy_node_ids")
        or tree_corpus.get("engine_default_node_ids")
    )
    for key in ("start_node_id", "class_start_node_id", "root_node_id", "ascendancy_start_node_id"):
        node_id = _int_value(tree_corpus.get(key))
        if node_id is not None and node_id not in _int_set(tree_corpus.get("available_node_ids")):
            start_root_proxy_node_ids.add(node_id)
    known_node_ids = (
        _int_set(tree_corpus.get("known_node_ids"))
        | _int_set(tree_corpus.get("available_node_ids") or tree_corpus.get("node_ids"))
        | mastery_node_ids
        | ascendancy_node_ids
        | start_root_proxy_node_ids
    )
    payoff_node_ids = _int_set(tree_corpus.get("payoff_node_ids") or tree_corpus.get("notable_node_ids"))
    ordinary_node_ids = _int_set(tree_corpus.get("ordinary_node_ids") or tree_corpus.get("ordinary_passive_node_ids"))
    if known_node_ids and not ordinary_node_ids:
        ordinary_node_ids = known_node_ids - mastery_node_ids - ascendancy_node_ids - start_root_proxy_node_ids - payoff_node_ids
    return _TreePayloadAuthority(
        known_node_ids=known_node_ids,
        mastery_node_ids=mastery_node_ids,
        mastery_effect_ids={int(effect_id) for effect_id in mastery_effect_ids if effect_id is not None},
        mastery_effects_by_node=mastery_effects_by_node,
        ascendancy_node_ids=ascendancy_node_ids,
        start_root_proxy_node_ids=start_root_proxy_node_ids,
        payoff_node_ids=payoff_node_ids,
        ordinary_node_ids=ordinary_node_ids,
    )


@lru_cache(maxsize=1)
def _canonical_tree_payload_authority() -> _TreePayloadAuthority:
    base = Path(__file__).resolve().parent / "corpus_data"
    passive_records = _records_from_json(base / "passives.json")
    mastery_records = _records_from_json(base / "masteries.json")
    ascendancy_records = _records_from_json(base / "ascendancies.json")

    known_node_ids: set[int] = set()
    mastery_node_ids: set[int] = set()
    mastery_effect_ids: set[int] = set()
    mastery_effects_by_node: dict[int, set[str]] = {}
    ascendancy_node_ids: set[int] = set()
    start_root_proxy_node_ids: set[int] = set()
    payoff_node_ids: set[int] = set()
    ordinary_node_ids: set[int] = set()

    for record in passive_records:
        node_id = _record_node_id(record)
        if node_id is None:
            continue
        known_node_ids.add(node_id)
        if _truthy(record.get("is_proxy")) or _truthy(record.get("is_ascendancy_start")) or record.get("class_start_index") is not None:
            start_root_proxy_node_ids.add(node_id)
        elif _truthy(record.get("is_notable")) or _truthy(record.get("is_keystone")):
            payoff_node_ids.add(node_id)
        else:
            ordinary_node_ids.add(node_id)

    for record in mastery_records:
        node_id = _record_node_id(record)
        if node_id is None:
            continue
        known_node_ids.add(node_id)
        mastery_node_ids.add(node_id)
        effects: set[str] = set()
        for effect in _sequence(record.get("mastery_effects")):
            effect_id = _int_value(_mapping(effect).get("effect_id"))
            if effect_id is not None:
                mastery_effect_ids.add(effect_id)
                effects.add(str(effect_id))
        if effects:
            mastery_effects_by_node[node_id] = effects

    for ascendancy in ascendancy_records:
        for start_node_id in _int_sequence(_mapping(ascendancy).get("start_node_ids")):
            known_node_ids.add(start_node_id)
            start_root_proxy_node_ids.add(start_node_id)
        for node in _sequence(_mapping(ascendancy).get("nodes")):
            node_map = _mapping(node)
            node_id = _record_node_id(node_map)
            if node_id is None:
                continue
            known_node_ids.add(node_id)
            if _truthy(node_map.get("is_ascendancy_start")) or node_id in start_root_proxy_node_ids:
                start_root_proxy_node_ids.add(node_id)
            else:
                ascendancy_node_ids.add(node_id)

    return _TreePayloadAuthority(
        known_node_ids=known_node_ids,
        mastery_node_ids=mastery_node_ids,
        mastery_effect_ids=mastery_effect_ids,
        mastery_effects_by_node=mastery_effects_by_node,
        ascendancy_node_ids=ascendancy_node_ids,
        start_root_proxy_node_ids=start_root_proxy_node_ids,
        payoff_node_ids=payoff_node_ids,
        ordinary_node_ids=ordinary_node_ids,
    )


def _records_from_json(path: Path) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return []
    return [record for record in records if isinstance(record, Mapping)]


def _record_node_id(record: Mapping[str, Any]) -> int | None:
    return _int_value(record.get("node_id") if record.get("node_id") is not None else record.get("skill_id"))


def _payload_user_allocated_node_ids(tree_state: Mapping[str, Any]) -> list[int]:
    for key in ("user_allocated_node_ids", "allocated_node_ids"):
        node_ids = _int_sequence(tree_state.get(key))
        if node_ids:
            return sorted(set(node_ids))
    return []


def _mastery_payloads(tree_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for entry in _sequence(tree_state.get("mastery_effect_ids")):
        payloads.append(_parse_mastery_payload(entry))
    for entry in _sequence(tree_state.get("allocated_masteries") or tree_state.get("masteries")):
        if isinstance(entry, Mapping):
            payloads.append(_parse_mastery_payload(entry))
    return payloads


def _parse_mastery_payload(entry: Any) -> dict[str, Any]:
    if isinstance(entry, Mapping):
        return {
            "node_id": _int_value(entry.get("node_id") if entry.get("node_id") is not None else entry.get("mastery_node_id")),
            "effect_id": _string(entry.get("effect_id") if entry.get("effect_id") is not None else entry.get("mastery_effect_id")),
            "raw": dict(entry),
        }
    if isinstance(entry, str):
        if ":" in entry:
            node_id, effect_id = entry.split(":", 1)
            return {"node_id": _int_value(node_id), "effect_id": effect_id.strip(), "raw": entry}
        return {"node_id": None, "effect_id": "", "raw": entry}
    return {"node_id": None, "effect_id": "", "raw": entry}


def _mastery_effects_by_node(tree_corpus: Mapping[str, Any]) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    raw = _mapping(tree_corpus.get("mastery_effects_by_node_id") or tree_corpus.get("mastery_effect_ids_by_node_id"))
    for node_id, effects in raw.items():
        parsed = _int_value(node_id)
        if parsed is None:
            continue
        result[parsed] = {_normalized_key(effect) for effect in _sequence(effects) if _string(effect)}
    return result


def _normalization_changed(original: Mapping[str, Any], normalized: Mapping[str, Any]) -> bool:
    keys = ("user_allocated_node_ids", "mastery_effect_ids", "ascendancy_node_ids", "start_root_proxy_node_ids")
    return any(_sequence(original.get(key)) != _sequence(normalized.get(key)) for key in keys)


def _blocker(code: str, summary: str, repair_hint: str) -> dict[str, Any]:
    return {
        "code": code,
        "blocker_id": code,
        "severity": "blocking",
        "summary": summary,
        "repair_hint": repair_hint,
    }


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        code = _string(blocker.get("code") or blocker.get("blocker_id")) or "tree_payload_normalization_blocker"
        summary = _string(blocker.get("summary"))
        key = (code, summary)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(blocker))
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
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
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else str(value).strip() if isinstance(value, (int, float)) else ""


def _normalized_key(value: Any) -> str:
    return "_".join(_string(value).lower().replace("-", "_").split())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "yes", "true", "accepted", "proven"}
    return bool(value)
