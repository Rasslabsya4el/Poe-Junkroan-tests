"""Skill-owned item base and explicit mod lookup for proof items.

This module is a small publication-gate lookup, not an item optimizer. It
validates that Early Game proof items cite known base items, real explicit
affix tiers/ranges, and source-backed crafting-bench mods from the packaged
catalog.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

EARLY_GAME_PROOF_ITEM_MOD_CATALOG_ID = "early_game_proof_item_mod_lookup_mvp"
EARLY_GAME_BEST_ALLOWED_AFFIX_TIER = 3
EARLY_GAME_MIN_PROGRESSION_BASE_REQUIRED_LEVEL = 68
EARLY_GAME_MAX_PROGRESSION_BASE_REQUIRED_LEVEL = 70
EARLY_GAME_MAX_BASE_REQUIRED_LEVEL = EARLY_GAME_MAX_PROGRESSION_BASE_REQUIRED_LEVEL


def normalize_catalog_key(value: Any) -> str:
    text = value.strip().lower() if isinstance(value, str) else str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


@lru_cache(maxsize=1)
def load_item_base_records() -> dict[str, Mapping[str, Any]]:
    payload = _load_json(_data_path("corpus_data", "items.json"))
    records: dict[str, Mapping[str, Any]] = {}
    for row in payload.get("records", []):
        if not isinstance(row, Mapping):
            continue
        name = _string(row.get("name"))
        if not name:
            continue
        records.setdefault(normalize_catalog_key(name), row)
    return records


@lru_cache(maxsize=1)
def load_early_game_mod_catalog() -> Mapping[str, Any]:
    payload = _load_json(_data_path("mod_data", "early_game_proof_item_mods.json"))
    if _string(payload.get("catalog_id")) != EARLY_GAME_PROOF_ITEM_MOD_CATALOG_ID:
        raise ValueError("early_game_proof_item_mods.json catalog_id is invalid")
    return payload


def resolve_item_base(base_id: Any, base_name: Any) -> Mapping[str, Any] | None:
    records = load_item_base_records()
    base_name_key = normalize_catalog_key(base_name)
    base_id_key = normalize_catalog_key(base_id)
    if base_name_key and base_name_key in records:
        return records[base_name_key]
    if base_id_key and base_id_key in records:
        return records[base_id_key]
    return None


def base_identity_matches(base_record: Mapping[str, Any], base_id: Any, base_name: Any) -> bool:
    expected = normalize_catalog_key(base_record.get("name"))
    base_id_key = normalize_catalog_key(base_id)
    base_name_key = normalize_catalog_key(base_name)
    return bool(expected and base_id_key == expected and base_name_key == expected)


def item_class_for_base(base_record: Mapping[str, Any]) -> str:
    return _string(base_record.get("type") or base_record.get("slot_family"))


def base_required_level(base_record: Mapping[str, Any]) -> int:
    requirements = base_record.get("requirements")
    if isinstance(requirements, Mapping):
        value = requirements.get("level")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 1


def base_implicit_matches(base_record: Mapping[str, Any], implicit_mods: Sequence[str]) -> bool:
    expected = _string(base_record.get("implicit_text"))
    if not expected:
        return not [entry for entry in implicit_mods if _string(entry)]
    if not implicit_mods:
        return False
    expected_semantic = _semantic_mod_text(expected)
    return all(_semantic_mod_text(entry) == expected_semantic for entry in implicit_mods if _string(entry))


def affix_exists_anywhere(affix_id: Any) -> bool:
    affix_key = normalize_catalog_key(affix_id)
    catalog = load_early_game_mod_catalog()
    for class_affixes in _mapping(catalog.get("item_classes")).values():
        if isinstance(class_affixes, Mapping) and affix_key in class_affixes:
            return True
    return False


def lookup_affix_tier(affix_id: Any, item_class: str, tier: Any) -> Mapping[str, Any] | None:
    affix_key = normalize_catalog_key(affix_id)
    tier_key = _string(tier).upper()
    catalog = load_early_game_mod_catalog()
    class_affixes = _mapping(_mapping(catalog.get("item_classes")).get(item_class))
    tiers = class_affixes.get(affix_key)
    if not isinstance(tiers, Sequence) or isinstance(tiers, (str, bytes, bytearray)):
        return None
    for row in tiers:
        if isinstance(row, Mapping) and _string(row.get("tier")).upper() == tier_key:
            return row
    return None


def lookup_crafting_bench_affix(
    affix_id: Any,
    item_class: str,
    *,
    source_ref: Any = None,
    source_mod_ref: Any = None,
    affix_type: Any = None,
    tier: Any = None,
    values: Sequence[float] | None = None,
) -> Mapping[str, Any] | None:
    affix_key = normalize_catalog_key(affix_id)
    catalog = load_early_game_mod_catalog()
    class_affixes = _mapping(_mapping(catalog.get("crafting_bench_item_classes")).get(item_class))
    records = class_affixes.get(affix_key)
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return None
    source_refs = {_string(source_ref), _string(source_mod_ref)}
    source_refs.discard("")
    requested_type = normalize_catalog_key(affix_type)
    requested_tier = _string(tier).upper()
    source_mod_ref_text = _string(source_mod_ref)
    candidates: list[Mapping[str, Any]] = []
    for row in records:
        if not isinstance(row, Mapping):
            continue
        if requested_type and normalize_catalog_key(row.get("affix_type")) != requested_type:
            continue
        if requested_tier and _string(row.get("tier")).upper() != requested_tier:
            continue
        if values and not _values_inside_record(values, row):
            continue
        candidates.append(row)
    if not candidates:
        return None

    # Exact source_mod_ref identifies a concrete PoEDB row. A broad source_ref
    # such as crafting_bench.poedb.master.increased_life intentionally does not.
    if source_mod_ref_text:
        exact_matches = [
            row
            for row in candidates
            if source_mod_ref_text == _string(row.get("source_mod_ref"))
            or source_mod_ref_text in {_string(entry) for entry in _sequence(row.get("source_refs"))}
        ]
        if exact_matches:
            return exact_matches[0]
        if _looks_like_exact_source_ref(source_mod_ref_text):
            return None

    if source_refs:
        candidates = [row for row in candidates if source_refs.intersection(_record_source_refs(row))]
    if candidates:
        return candidates[0]
    return None


def affix_allowed_on_item_class(affix_id: Any, item_class: str) -> bool:
    affix_key = normalize_catalog_key(affix_id)
    catalog = load_early_game_mod_catalog()
    class_affixes = _mapping(_mapping(catalog.get("item_classes")).get(item_class))
    return affix_key in class_affixes


def crafting_bench_affix_allowed_on_item_class(affix_id: Any, item_class: str) -> bool:
    affix_key = normalize_catalog_key(affix_id)
    catalog = load_early_game_mod_catalog()
    class_affixes = _mapping(_mapping(catalog.get("crafting_bench_item_classes")).get(item_class))
    return affix_key in class_affixes


def tier_number(tier: Any) -> int | None:
    match = re.fullmatch(r"T(\d+)", _string(tier).upper())
    return int(match.group(1)) if match else None


def tier_value_range(tier_record: Mapping[str, Any]) -> tuple[float | None, float | None]:
    low = _float_value(tier_record.get("value_min"))
    high = _float_value(tier_record.get("value_max"))
    return low, high


def proof_affix_numeric_values(affix: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for key in ("value", "min_value", "max_value", "roll_value"):
        numeric = _float_value(affix.get(key))
        if numeric is not None:
            values.append(numeric)
    value_range = affix.get("value_range")
    if isinstance(value_range, Mapping):
        for key in ("min", "max", "minimum", "maximum"):
            numeric = _float_value(value_range.get(key))
            if numeric is not None:
                values.append(numeric)
    for entry in _sequence(value_range):
        numeric = _float_value(entry)
        if numeric is not None:
            values.append(numeric)
    for entry in _sequence(affix.get("values")):
        numeric = _float_value(entry)
        if numeric is not None:
            values.append(numeric)
    return values


def _data_path(*parts: str) -> Path:
    return Path(__file__).resolve().parent.joinpath(*parts)


def _load_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_mod_text(value: Any) -> str:
    text = _string(value).lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[-+]?\d+(?:\.\d+)?", " ", text)
    text = re.sub(r"[^a-z]+", " ", text)
    return " ".join(text.split())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _record_source_refs(row: Mapping[str, Any]) -> set[str]:
    refs = {
        _string(row.get("source_ref")),
        _string(row.get("source_mod_ref")),
        _string(row.get("bench_source_ref")),
    }
    refs.update(_string(entry) for entry in _sequence(row.get("source_refs")))
    return {entry for entry in refs if entry}


def _looks_like_exact_source_ref(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://")) or "poe_data_mods_hover" in lowered


def _values_inside_record(values: Sequence[float], row: Mapping[str, Any]) -> bool:
    low, high = tier_value_range(row)
    if high is not None and max(values) > high:
        return False
    if low is not None and min(values) < low:
        return False
    return True
