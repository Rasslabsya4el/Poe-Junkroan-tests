"""Observation-only support legality read-back over pinned PoB skill state."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

POB_SUPPORT_LEGALITY_READBACK_SCHEMA_VERSION = "1.0.0"
POB_SUPPORT_LEGALITY_READBACK_RECORD_KIND = "pob_support_legality_readback"

_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_ROW_STATUSES = (
    "accepted",
    "disabled",
    "blocked",
    "warning",
    "unsupported_by_tooling",
    "needs_pob_runtime",
)


class PoBSupportLegalityReadbackContractError(RuntimeError):
    """Raised when a support read-back proposal is malformed."""

    def __init__(self, failure_state: str, message: str) -> None:
        super().__init__(message)
        self.failure_state = failure_state


def _fail(failure_state: str, message: str) -> None:
    raise PoBSupportLegalityReadbackContractError(failure_state, message)


def _normalize_key(value: Any) -> str:
    return _NORMALIZE_PATTERN.sub("", str(value).lower())


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_support_readback_request", f"{field_name} must be an object.")
    return dict(value)


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_support_readback_request", f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name)


def _normalize_active_skill_request(active_skill: str | Mapping[str, Any]) -> dict[str, str | None]:
    if isinstance(active_skill, str):
        return {
            "name": _require_non_empty_string(active_skill, "active_skill"),
            "skill_id": None,
            "socket_group_id": None,
            "active_skill_id": None,
        }
    payload = _require_mapping(active_skill, "active_skill")
    return {
        "name": _require_non_empty_string(payload.get("name"), "active_skill.name"),
        "skill_id": _optional_string(payload.get("skill_id"), "active_skill.skill_id"),
        "socket_group_id": _optional_string(payload.get("socket_group_id"), "active_skill.socket_group_id"),
        "active_skill_id": _optional_string(payload.get("active_skill_id"), "active_skill.active_skill_id"),
    }


def _normalize_support_request(support: str | Mapping[str, Any], *, index: int) -> dict[str, str | None]:
    if isinstance(support, str):
        return {
            "name": _require_non_empty_string(support, f"supports[{index}]"),
            "skill_id": None,
            "gem_entry_id": None,
        }
    payload = _require_mapping(support, f"supports[{index}]")
    return {
        "name": _require_non_empty_string(payload.get("name"), f"supports[{index}].name"),
        "skill_id": _optional_string(payload.get("skill_id"), f"supports[{index}].skill_id"),
        "gem_entry_id": _optional_string(payload.get("gem_entry_id"), f"supports[{index}].gem_entry_id"),
    }


def _normalize_support_requests(supports: Iterable[str | Mapping[str, Any]]) -> list[dict[str, str | None]]:
    if isinstance(supports, (str, bytes)):
        _fail("invalid_support_readback_request", "supports must be an array, not one string.")
    rows = [
        _normalize_support_request(support, index=index)
        for index, support in enumerate(supports)
    ]
    if not rows:
        _fail("invalid_support_readback_request", "supports must contain at least one support request.")
    return rows


def _extract_skills_state(observed_state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if observed_state is None:
        return None
    payload = dict(observed_state)
    skills_state = payload.get("skills_state")
    if isinstance(skills_state, Mapping):
        return dict(skills_state)
    if "skill_sets" in payload or "socket_groups" in payload:
        return payload
    return None


def _iter_socket_groups(skills_state: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    skill_sets = skills_state.get("skill_sets")
    yielded_ids: set[str] = set()
    if isinstance(skill_sets, list):
        for skill_set in skill_sets:
            if not isinstance(skill_set, Mapping):
                continue
            groups = skill_set.get("socket_groups")
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                group_payload = dict(group)
                group_id = str(group_payload.get("socket_group_id") or "")
                if group_id:
                    yielded_ids.add(group_id)
                yield group_payload

    groups = skills_state.get("socket_groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            group_payload = dict(group)
            group_id = str(group_payload.get("socket_group_id") or "")
            if group_id and group_id in yielded_ids:
                continue
            yield group_payload


def _entry_matches_request(entry: Mapping[str, Any], request: Mapping[str, str | None]) -> bool:
    if request.get("active_skill_id") and request["active_skill_id"] == entry.get("active_skill_id"):
        return True
    if request.get("skill_id") and request["skill_id"] == entry.get("skill_id"):
        return True
    return _normalize_key(entry.get("name")) == _normalize_key(request["name"])


def _find_active_skill(
    skills_state: Mapping[str, Any],
    request: Mapping[str, str | None],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    requested_group_id = request.get("socket_group_id")
    for group in _iter_socket_groups(skills_state):
        if requested_group_id is not None and group.get("socket_group_id") != requested_group_id:
            continue
        active_entries = group.get("active_skill_entries")
        if not isinstance(active_entries, list):
            continue
        for entry in active_entries:
            if isinstance(entry, Mapping) and _entry_matches_request(entry, request):
                return group, dict(entry)
    return None


def _support_matches(value: Mapping[str, Any], request: Mapping[str, str | None]) -> bool:
    if request.get("gem_entry_id") and request["gem_entry_id"] == value.get("source_gem_entry_id"):
        return True
    if request.get("gem_entry_id") and request["gem_entry_id"] == value.get("gem_entry_id"):
        return True
    if request.get("skill_id") and request["skill_id"] == value.get("skill_id"):
        return True
    return _normalize_key(value.get("name") or value.get("gem_name")) == _normalize_key(request["name"])


def _support_link_payload(link: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": _require_non_empty_string(link.get("name"), "support_link.name"),
        "skill_id": _optional_string(link.get("skill_id"), "support_link.skill_id"),
        "from_item": bool(link.get("from_item") is True),
        "source_gem_entry_id": _optional_string(link.get("source_gem_entry_id"), "support_link.source_gem_entry_id"),
    }


def _gem_entry_payload(gem: Mapping[str, Any]) -> dict[str, Any] | None:
    gem_name = gem.get("gem_name")
    if not isinstance(gem_name, str) or not gem_name.strip():
        return None
    return {
        "gem_entry_id": _optional_string(gem.get("gem_entry_id"), "gem.gem_entry_id"),
        "gem_name": gem_name.strip(),
        "skill_id": _optional_string(gem.get("skill_id"), "gem.skill_id"),
        "enabled": bool(gem.get("enabled") is True),
        "is_support": bool(gem.get("is_support") is True),
    }


def _matching_support_link(active_skill_entry: Mapping[str, Any], request: Mapping[str, str | None]) -> dict[str, Any] | None:
    links = active_skill_entry.get("support_links")
    if not isinstance(links, list):
        return None
    for link in links:
        if isinstance(link, Mapping) and _support_matches(link, request):
            return _support_link_payload(link)
    return None


def _matching_gem_entry(socket_group: Mapping[str, Any], request: Mapping[str, str | None]) -> dict[str, Any] | None:
    gems = socket_group.get("gems")
    if not isinstance(gems, list):
        return None
    for gem in gems:
        if isinstance(gem, Mapping) and _support_matches(gem, request):
            return _gem_entry_payload(gem)
    return None


def _concerns_from_skill_requirements(skill_requirements_packet: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if skill_requirements_packet is None:
        return []
    concerns = skill_requirements_packet.get("support_concerns_pending_pob_proof")
    if not isinstance(concerns, list):
        return []
    rows: list[dict[str, str]] = []
    for index, concern in enumerate(concerns):
        if not isinstance(concern, Mapping):
            continue
        concern_id = concern.get("concern_id") or f"support_concern.{index}"
        status = concern.get("status") or "pending_pob_proof"
        summary = concern.get("summary") or "Support concern requires PoB read-back."
        rows.append(
            {
                "concern_id": str(concern_id),
                "status": str(status),
                "summary": str(summary),
            }
        )
    return rows


def _runtime_unavailable_row(
    support: Mapping[str, str | None],
    *,
    index: int,
    concern_ids: list[str],
) -> dict[str, Any]:
    return {
        "support_name": str(support["name"]),
        "requested_index": index,
        "status": "needs_pob_runtime",
        "row_kind": "runtime_unavailable",
        "observed_from_pob": False,
        "authority": "none",
        "source": "runtime_unavailable",
        "matched_support_link": None,
        "matched_gem_entry": None,
        "tag_precheck_concern_ids": concern_ids,
        "reason": "No pinned PoB skills_state read-back was supplied, so support legality cannot be observed.",
    }


def _active_unresolved_row(
    support: Mapping[str, str | None],
    *,
    index: int,
    concern_ids: list[str],
) -> dict[str, Any]:
    return {
        "support_name": str(support["name"]),
        "requested_index": index,
        "status": "unsupported_by_tooling",
        "row_kind": "unresolved_requested_support",
        "observed_from_pob": False,
        "authority": "none",
        "source": "active_skill_unresolved",
        "matched_support_link": None,
        "matched_gem_entry": None,
        "tag_precheck_concern_ids": concern_ids,
        "reason": "Pinned PoB read-back did not expose the requested active skill entry.",
    }


def _observed_row(
    support: Mapping[str, str | None],
    *,
    index: int,
    socket_group: Mapping[str, Any],
    active_skill_entry: Mapping[str, Any],
    concern_ids: list[str],
) -> dict[str, Any]:
    link = _matching_support_link(active_skill_entry, support)
    gem = _matching_gem_entry(socket_group, support)
    if link is not None:
        return {
            "support_name": str(support["name"]),
            "requested_index": index,
            "status": "accepted",
            "row_kind": "pob_accepted_support",
            "observed_from_pob": True,
            "authority": "pob_support_link",
            "source": "active_skill_support_links",
            "matched_support_link": link,
            "matched_gem_entry": gem,
            "tag_precheck_concern_ids": concern_ids,
            "reason": "Pinned PoB read-back included this support in the active skill support_links.",
        }
    if gem is not None and gem["enabled"] is False:
        return {
            "support_name": str(support["name"]),
            "requested_index": index,
            "status": "disabled",
            "row_kind": "pob_disabled_support",
            "observed_from_pob": True,
            "authority": "pob_gem_entry",
            "source": "socket_group_gem_entry",
            "matched_support_link": None,
            "matched_gem_entry": gem,
            "tag_precheck_concern_ids": concern_ids,
            "reason": "Pinned PoB read-back found the support gem entry disabled.",
        }
    if gem is not None:
        row_kind = "pob_blocked_support"
        reason = "Pinned PoB read-back did not include this enabled support in the active skill support_links."
        if gem["is_support"] is False:
            reason = "Pinned PoB read-back found a matching gem entry, but it is not a support gem."
        return {
            "support_name": str(support["name"]),
            "requested_index": index,
            "status": "blocked",
            "row_kind": row_kind,
            "observed_from_pob": True,
            "authority": "pob_gem_entry",
            "source": "socket_group_gem_entry",
            "matched_support_link": None,
            "matched_gem_entry": gem,
            "tag_precheck_concern_ids": concern_ids,
            "reason": reason,
        }
    return {
        "support_name": str(support["name"]),
        "requested_index": index,
        "status": "unsupported_by_tooling",
        "row_kind": "unresolved_requested_support",
        "observed_from_pob": True,
        "authority": "none",
        "source": "unresolved_requested_support",
        "matched_support_link": None,
        "matched_gem_entry": None,
        "tag_precheck_concern_ids": concern_ids,
        "reason": "Pinned PoB read-back did not expose a matching support link or gem entry for this request.",
    }


def _summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_list = list(rows)
    counts = {
        status: sum(1 for row in row_list if row.get("status") == status)
        for status in _ROW_STATUSES
    }
    all_accepted = len(row_list) > 0 and counts["accepted"] == len(row_list)
    if counts["needs_pob_runtime"]:
        packet_status = "needs_pob_runtime"
    elif all_accepted:
        packet_status = "accepted"
    else:
        packet_status = "blocked"
    blockers = [
        f"{row['support_name']}: {row['reason']}"
        for row in row_list
        if row.get("status") != "accepted"
    ]
    return {
        "packet_status": packet_status,
        "all_supports_accepted": all_accepted,
        "accepted_count": counts["accepted"],
        "disabled_count": counts["disabled"],
        "blocked_count": counts["blocked"],
        "warning_count": counts["warning"],
        "unsupported_by_tooling_count": counts["unsupported_by_tooling"],
        "needs_pob_runtime_count": counts["needs_pob_runtime"],
        "fail_closed": not all_accepted,
        "blockers": blockers,
    }


def _forbidden_outputs_absent() -> dict[str, bool]:
    return {
        "class_selected": False,
        "ascendancy_selected": False,
        "tree_route_selected": False,
        "item_plan_selected": False,
        "support_setup_selected": False,
        "final_build_decision": False,
        "publication_output": False,
    }


def build_support_legality_readback_packet(
    active_skill: str | Mapping[str, Any],
    supports: Iterable[str | Mapping[str, Any]],
    *,
    observed_state: Mapping[str, Any] | None,
    skill_requirements_packet: Mapping[str, Any] | None = None,
    observation_ref: str | None = None,
) -> dict[str, Any]:
    """Compare proposed supports with pinned PoB-observed support links.

    This helper does not choose supports or infer compatibility from tags. A row
    becomes legal only when the supplied PoB skills_state exposes the support in
    the requested active skill's support_links.
    """

    active_request = _normalize_active_skill_request(active_skill)
    support_requests = _normalize_support_requests(supports)
    concerns = _concerns_from_skill_requirements(skill_requirements_packet)
    concern_ids = [concern["concern_id"] for concern in concerns]
    skills_state = _extract_skills_state(observed_state)

    if skills_state is None:
        rows = [
            _runtime_unavailable_row(support, index=index, concern_ids=concern_ids)
            for index, support in enumerate(support_requests)
        ]
        runtime_observation = {
            "observation_state": "needs_pob_runtime",
            "authority": "none",
            "observation_ref": observation_ref,
            "observed_socket_group_id": None,
            "observed_active_skill_id": None,
            "message": "Support legality requires pinned PoB skills_state read-back.",
        }
    else:
        match = _find_active_skill(skills_state, active_request)
        if match is None:
            rows = [
                _active_unresolved_row(support, index=index, concern_ids=concern_ids)
                for index, support in enumerate(support_requests)
            ]
            runtime_observation = {
                "observation_state": "unsupported_by_tooling",
                "authority": "none",
                "observation_ref": observation_ref,
                "observed_socket_group_id": None,
                "observed_active_skill_id": None,
                "message": "The supplied skills_state did not expose the requested active skill entry.",
            }
        else:
            socket_group, active_skill_entry = match
            rows = [
                _observed_row(
                    support,
                    index=index,
                    socket_group=socket_group,
                    active_skill_entry=active_skill_entry,
                    concern_ids=concern_ids,
                )
                for index, support in enumerate(support_requests)
            ]
            runtime_observation = {
                "observation_state": "observed",
                "authority": "pinned_pob_skills_state_readback",
                "observation_ref": observation_ref,
                "observed_socket_group_id": socket_group.get("socket_group_id"),
                "observed_active_skill_id": active_skill_entry.get("active_skill_id"),
                "message": "Pinned PoB skills_state read-back exposed the requested active skill entry.",
            }

    return {
        "schema_version": POB_SUPPORT_LEGALITY_READBACK_SCHEMA_VERSION,
        "record_kind": POB_SUPPORT_LEGALITY_READBACK_RECORD_KIND,
        "proposal": {
            "active_skill": active_request,
            "requested_supports": support_requests,
        },
        "runtime_observation": runtime_observation,
        "tag_precheck": {
            "source": "skill_requirements_packet" if skill_requirements_packet is not None else "absent",
            "concerns_can_mark_legal": False,
            "concerns": concerns,
        },
        "observed_rows": rows,
        "summary": _summary(rows),
        "forbidden_decision_outputs_absent": _forbidden_outputs_absent(),
        "publication_outputs_absent": True,
    }


__all__ = [
    "POB_SUPPORT_LEGALITY_READBACK_RECORD_KIND",
    "POB_SUPPORT_LEGALITY_READBACK_SCHEMA_VERSION",
    "PoBSupportLegalityReadbackContractError",
    "build_support_legality_readback_packet",
]
