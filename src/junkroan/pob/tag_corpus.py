"""Repo-owned tag and facet surface derived from the committed PoB game corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from .game_corpus import (
    DEFAULT_MANIFEST_PATH as DEFAULT_SOURCE_MANIFEST_PATH,
    FAMILY_FILE_NAMES as SOURCE_FAMILY_FILE_NAMES,
    load_game_corpus_bundle,
    load_game_corpus_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAG_CORPUS_ROOT = Path(__file__).with_name("tag_data")
DEFAULT_MANIFEST_PATH = DEFAULT_TAG_CORPUS_ROOT / "manifest.json"
SCHEMA_VERSION = "1.0.0"
CORPUS_ID = "pob_tag_corpus"
SOURCE_CORPUS_ID = "pob_game_corpus"
FAMILY_FILE_NAMES = dict(SOURCE_FAMILY_FILE_NAMES)
EXPECTED_FAMILIES = tuple(FAMILY_FILE_NAMES)
FIELD_ORDER = {
    "manifest": [
        "schema_version",
        "corpus_id",
        "source_corpus",
        "families",
        "downstream_policy",
        "field_order",
    ],
    "bundle": [
        "schema_version",
        "corpus_id",
        "family",
        "record_count",
        "provenance",
        "metadata",
        "records",
    ],
    "record": [
        "source_id",
        "source_name",
        "search_tags",
        "scaling_facets",
        "supporting_text",
        "source_context",
    ],
    "facet": [
        "facet",
        "values",
    ],
}
FACET_ORDER = (
    "item_slot",
    "item_class",
    "item_kind",
    "influence",
    "gem_role",
    "node_kind",
    "class",
    "config_section",
    "config_control_type",
    "config_scope",
    "config_predicate",
    "attribute",
    "damage_type",
    "mechanic",
    "weapon",
    "resource",
    "defence",
    "charge",
    "ailment",
    "scaling_stat",
)
SEARCH_TAG_STOPWORDS = {
    "a",
    "an",
    "and",
    "always",
    "are",
    "by",
    "can",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "into",
    "mode",
    "none",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "under",
    "with",
    "you",
    "your",
}
CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
POB_FORMAT_CODE = re.compile(r"\^[A-Za-z0-9]+")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
FACET_PATTERN_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "attribute": {
        "strength": (r"\bstrength\b", r"\bstr\b"),
        "dexterity": (r"\bdexterity\b", r"\bdex\b"),
        "intelligence": (r"\bintelligence\b", r"\bint\b"),
    },
    "damage_type": {
        "physical": (r"\bphysical\b",),
        "fire": (r"\bfire\b",),
        "cold": (r"\bcold\b",),
        "lightning": (r"\blightning\b",),
        "chaos": (r"\bchaos\b",),
        "elemental": (r"\belemental\b",),
    },
    "mechanic": {
        "attack": (r"\battack(?:s)?\b",),
        "spell": (r"\bspell(?:s)?\b",),
        "projectile": (r"\bprojectile(?:s)?\b",),
        "melee": (r"\bmelee\b",),
        "area": (r"\barea\b", r"\baoe\b", r"area of effect"),
        "duration": (r"\bduration\b",),
        "minion": (
            r"\bminion(?:s)?\b",
            r"\bgolem(?:s)?\b",
            r"\bskeleton(?:s)?\b",
            r"\bzombie(?:s)?\b",
            r"\bspectre(?:s)?\b",
        ),
        "trap": (r"\btrap(?:s)?\b",),
        "mine": (r"\bmine(?:s)?\b",),
        "totem": (r"\btotem(?:s)?\b",),
        "brand": (r"\bbrand(?:s)?\b",),
        "aura": (r"\baura(?:s)?\b",),
        "curse": (r"\bcurse(?:s)?\b",),
        "hex": (r"\bhex(?:es)?\b",),
        "mark": (r"\bmark(?:s)?\b",),
        "warcry": (r"\bwarcry\b", r"\bwarcries\b"),
        "movement": (r"\bmovement\b", r"\bblink\b", r"\btravel\b"),
        "trigger": (r"\btrigger(?:ed)?\b",),
        "guard": (r"\bguard\b",),
        "banner": (r"\bbanner(?:s)?\b",),
        "herald": (r"\bherald(?:s)?\b",),
        "golem": (r"\bgolem(?:s)?\b",),
        "slam": (r"\bslam(?:s)?\b",),
        "strike": (r"\bstrike(?:s)?\b",),
        "channelling": (r"\bchannelling\b", r"\bchanneling\b"),
        "link": (r"\blink(?:ed|s)?\b",),
        "orb": (r"\borb(?:s)?\b",),
        "nova": (r"\bnova\b",),
        "chaining": (r"\bchain(?:ing)?\b",),
        "retaliation": (r"\bretaliation\b",),
        "vaal": (r"\bvaal\b",),
        "corpse": (r"\bcorpse(?:s)?\b",),
        "stance": (r"\bstance\b",),
    },
    "weapon": {
        "sword": (r"\bsword(?:s)?\b",),
        "axe": (r"\baxe(?:s)?\b",),
        "mace": (r"\bmace(?:s)?\b",),
        "sceptre": (r"\bsceptre(?:s)?\b",),
        "bow": (r"\bbow\b", r"\bbows\b"),
        "claw": (r"\bclaw(?:s)?\b",),
        "dagger": (r"\bdagger(?:s)?\b",),
        "staff": (r"\bstaff\b", r"\bstaves\b"),
        "warstaff": (r"\bwarstaff\b", r"\bwarstaffs\b"),
        "wand": (r"\bwand(?:s)?\b",),
        "shield": (r"\bshield(?:s)?\b",),
        "quiver": (r"\bquiver(?:s)?\b",),
        "unarmed": (r"\bunarmed\b",),
        "dual_wield": (r"\bdual wield(?:ing)?\b",),
        "one_hand": (r"\bone hand(?:ed)?\b", r"\bonehand\b"),
        "two_hand": (r"\btwo hand(?:ed)?\b", r"\btwohand\b"),
    },
    "resource": {
        "life": (r"\blife\b",),
        "mana": (r"\bmana\b",),
        "energy_shield": (r"\benergy shield\b", r"\bes\b"),
        "ward": (r"\bward\b",),
        "rage": (r"\brage\b",),
        "flask": (r"\bflask(?:s)?\b",),
        "reservation": (r"\breservation\b", r"\breserved\b"),
        "leech": (r"\bleech(?:ed|es|ing)?\b", r"\bleeched\b"),
        "recoup": (r"\brecoup(?:ed)?\b",),
        "recovery": (r"\brecover(?:ed|y)?\b", r"\brecovery\b"),
        "regeneration": (r"\bregenerat(?:e|ed|es|ing|ion)\b",),
        "cost": (r"\bcost(?:s)?\b",),
        "soul": (r"\bsoul(?:s)?\b",),
    },
    "defence": {
        "armour": (r"\barmour\b",),
        "evasion": (r"\bevasion\b",),
        "energy_shield": (r"\benergy shield\b", r"\bes\b"),
        "ward": (r"\bward\b",),
        "block": (r"\bblock\b", r"\bblocked\b"),
        "spell_suppression": (r"\bspell suppression\b",),
        "resistances": (r"\bresistance(?:s)?\b",),
        "fortify": (r"\bfortify\b",),
    },
    "charge": {
        "endurance_charge": (r"\bendurance charge(?:s)?\b",),
        "frenzy_charge": (r"\bfrenzy charge(?:s)?\b",),
        "power_charge": (r"\bpower charge(?:s)?\b",),
    },
    "ailment": {
        "ignite": (r"\bignite(?:d)?\b", r"\bignited\b"),
        "chill": (r"\bchill(?:ed)?\b", r"\bchilled\b"),
        "freeze": (r"\bfreez(?:e|es|ing|en)\b", r"\bfrozen\b"),
        "shock": (r"\bshock(?:ed)?\b", r"\bshocked\b"),
        "scorch": (r"\bscorch(?:ed)?\b", r"\bscorched\b"),
        "brittle": (r"\bbrittle\b",),
        "sap": (r"\bsap(?:ped)?\b", r"\bsapped\b"),
        "poison": (r"\bpoison(?:ed)?\b", r"\bpoisoned\b"),
        "bleed": (r"\bbleed(?:ing)?\b", r"\bbleeding\b"),
        "impale": (r"\bimpale(?:d)?\b",),
        "stun": (r"\bstun(?:ned)?\b", r"\bstunned\b"),
        "exposure": (r"\bexposure\b",),
    },
    "scaling_stat": {
        "critical_strike_chance": (r"\bcritical strike chance\b", r"\bcrit chance\b"),
        "critical_strike_multiplier": (r"\bcritical strike multiplier\b",),
        "attack_speed": (r"\battack speed\b",),
        "cast_speed": (r"\bcast speed\b",),
        "movement_speed": (r"\bmovement speed\b",),
        "projectile_speed": (r"\bprojectile speed\b",),
        "area_of_effect": (r"\barea of effect\b", r"\baoe\b"),
        "cooldown_recovery": (r"\bcooldown recovery\b",),
        "aura_effect": (r"\beffect of auras?\b", r"\baura effect\b"),
        "curse_effect": (r"\beffect of curses?\b", r"\bcurse effect\b"),
        "reservation_efficiency": (r"\breservation efficiency\b",),
        "mana_cost": (r"\bmana cost\b", r"\bcost of skills?\b"),
        "life_regeneration": (r"\blife regeneration\b", r"\bregenerate .* life\b"),
        "mana_regeneration": (r"\bmana regeneration\b", r"\bregenerate .* mana\b"),
        "accuracy": (r"\baccuracy\b",),
        "block_chance": (r"\bchance to block\b", r"\bblock chance\b"),
        "armour": (r"\barmour\b",),
        "evasion": (r"\bevasion\b",),
        "energy_shield": (r"\benergy shield\b",),
        "spell_suppression": (r"\bspell suppression\b",),
        "leech": (r"\bleech(?:ed|es|ing)?\b",),
        "recoup": (r"\brecoup(?:ed)?\b",),
        "flask_effect": (r"\bflask effect\b",),
        "flask_charges": (r"\bflask charges?\b",),
        "damage_over_time": (r"\bdamage over time\b",),
        "duration": (r"\bduration\b",),
    },
}
COMPILED_FACET_PATTERNS = {
    facet: {
        value: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
        for value, patterns in value_map.items()
    }
    for facet, value_map in FACET_PATTERN_SPECS.items()
}


class TagCorpusContractError(RuntimeError):
    """Raised when the committed PoB tag corpus contract cannot be satisfied."""


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_stable_json(payload), encoding="utf-8", newline="\n")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slugify(value: Any) -> str:
    if value is None:
        return ""
    text = CAMEL_CASE_BOUNDARY.sub(" ", str(value))
    text = POB_FORMAT_CODE.sub(" ", text)
    text = text.replace("&", " and ")
    text = text.replace("%", " percent ")
    text = text.replace("+", " plus ")
    text = text.replace("/", " ")
    text = text.replace("'", "")
    lowered = text.lower()
    return NON_ALNUM.sub("_", lowered).strip("_")


def _dedupe_preserve(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _sorted_unique_tags(values: Iterable[Any]) -> list[str]:
    return sorted({_slugify(value) for value in values if _slugify(value)})


def _normalize_string_list(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return _dedupe_preserve(payload)
    return _dedupe_preserve([payload])


def _normalize_nested_string_lists(payload: Any) -> list[list[str]]:
    if not isinstance(payload, list):
        return []
    normalized: list[list[str]] = []
    for item in payload:
        if isinstance(item, list):
            values = _dedupe_preserve(item)
        else:
            values = _dedupe_preserve([item])
        if values:
            normalized.append(values)
    return normalized


def _normalize_numeric_map(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    aliases = {
        "str": "strength",
        "dex": "dexterity",
        "int": "intelligence",
    }
    normalized: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            normalized[aliases.get(str(key), str(key))] = value
    return normalized


def _normalize_text_for_matching(values: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        slug = _slugify(value)
        if slug:
            normalized.append(slug.replace("_", " "))
    return normalized


def _identifier_tags(values: Iterable[Any]) -> list[str]:
    tags: set[str] = set()
    for value in values:
        slug = _slugify(value)
        if not slug:
            continue
        if not _is_noise_tag(slug):
            tags.add(slug)
        for token in slug.split("_"):
            if len(token) >= 3 and not _is_noise_tag(token):
                tags.add(token)
    return sorted(tags)


def _is_noise_tag(value: str) -> bool:
    if value in SEARCH_TAG_STOPWORDS:
        return True
    if value.isdigit():
        return True
    return any(character.isdigit() for character in value) and all(character in "0123456789abcdef" for character in value)


def _match_facet_values(text_fragments: Iterable[Any]) -> dict[str, list[str]]:
    haystack = "\n".join(_normalize_text_for_matching(text_fragments))
    matches: dict[str, list[str]] = {}
    if not haystack:
        return matches
    for facet, value_map in COMPILED_FACET_PATTERNS.items():
        facet_hits = [
            value
            for value, patterns in value_map.items()
            if any(pattern.search(haystack) for pattern in patterns)
        ]
        if facet_hits:
            matches[facet] = sorted(set(facet_hits))
    return matches


def _facet_list(*facet_maps: dict[str, list[str]]) -> list[dict[str, Any]]:
    merged: dict[str, set[str]] = {}
    for facet_map in facet_maps:
        for facet, values in facet_map.items():
            cleaned = {_slugify(value) for value in values if _slugify(value)}
            if not cleaned:
                continue
            merged.setdefault(facet, set()).update(cleaned)
    return [
        {
            "facet": facet,
            "values": sorted(merged[facet]),
        }
        for facet in FACET_ORDER
        if merged.get(facet)
    ]


def _search_tags(
    *,
    identifier_values: Iterable[Any],
    raw_tags: Iterable[Any],
    scaling_facets: list[dict[str, Any]],
) -> list[str]:
    tags = set(_identifier_tags(identifier_values))
    tags.update(_sorted_unique_tags(raw_tags))
    for facet in scaling_facets:
        tags.update(facet["values"])
    return sorted(tags)


def _build_facet_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    values: dict[str, set[str]] = {}
    for record in records:
        for facet in record["scaling_facets"]:
            facet_name = str(facet["facet"])
            counts[facet_name] = counts.get(facet_name, 0) + 1
            values.setdefault(facet_name, set()).update(str(value) for value in facet["values"])
    return [
        {
            "facet": facet_name,
            "record_count": counts[facet_name],
            "values": sorted(values[facet_name]),
        }
        for facet_name in FACET_ORDER
        if facet_name in counts
    ]


def _normalize_list_values(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "label": str(item["label"]) if item.get("label") is not None else None,
                "value": item.get("value"),
            }
        )
    return normalized


def _source_bundle_path(source_manifest_path: Path, family: str) -> Path:
    return source_manifest_path.parent / SOURCE_FAMILY_FILE_NAMES[family]


def _require_fields(record: dict[str, Any], *, family: str, index: int, fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise TagCorpusContractError(f"{family} record {index} is missing required fields: {missing_fields}")


def _load_source_corpus(source_manifest_path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    if not source_manifest_path.exists():
        raise TagCorpusContractError(f"Committed game corpus manifest is missing: {source_manifest_path}")

    source_manifest = load_game_corpus_manifest(source_manifest_path)
    if source_manifest.get("corpus_id") != SOURCE_CORPUS_ID:
        raise TagCorpusContractError(
            f"Expected source corpus id {SOURCE_CORPUS_ID}, found {source_manifest.get('corpus_id')!r}."
        )

    source_lane = source_manifest.get("source_lane")
    if not isinstance(source_lane, dict):
        raise TagCorpusContractError("Committed game corpus manifest is missing source_lane provenance.")
    if source_lane.get("observed_commit") != source_lane.get("pinned_commit"):
        raise TagCorpusContractError("Committed game corpus manifest must reflect a pinned, matching PoB source lane.")

    family_summaries = source_manifest.get("families")
    if not isinstance(family_summaries, list):
        raise TagCorpusContractError("Committed game corpus manifest is missing family summaries.")
    observed_families = {
        str(summary.get("family"))
        for summary in family_summaries
        if isinstance(summary, dict) and summary.get("family") is not None
    }
    expected = set(EXPECTED_FAMILIES)
    if observed_families != expected:
        raise TagCorpusContractError(
            f"Committed game corpus families do not match the accepted contract: {sorted(observed_families)}"
        )

    bundle_paths: dict[str, Path] = {}
    bundles: dict[str, dict[str, Any]] = {}
    for family in EXPECTED_FAMILIES:
        bundle_path = _source_bundle_path(source_manifest_path, family)
        if not bundle_path.exists():
            raise TagCorpusContractError(f"Committed game corpus bundle is missing for family {family}: {bundle_path}")
        bundle = load_game_corpus_bundle(family, manifest_path=source_manifest_path)
        if bundle.get("family") != family:
            raise TagCorpusContractError(
                f"Committed game corpus bundle {bundle_path} reports family {bundle.get('family')!r}, expected {family!r}."
            )
        records = bundle.get("records")
        if not isinstance(records, list) or not records:
            raise TagCorpusContractError(f"Committed game corpus bundle {bundle_path} has no records.")
        if bundle.get("record_count") != len(records):
            raise TagCorpusContractError(
                f"Committed game corpus bundle {bundle_path} has record_count {bundle.get('record_count')} but "
                f"{len(records)} records."
            )
        bundle_paths[family] = bundle_path
        bundles[family] = bundle

    return source_manifest, bundle_paths, bundles


def collect_tag_corpus_source_inputs(source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST_PATH) -> dict[str, Path]:
    """Return the committed game corpus inputs required to derive the tag surface."""

    _, bundle_paths, _ = _load_source_corpus(source_manifest_path)
    return {
        "manifest": source_manifest_path,
        **bundle_paths,
    }


def _item_record(record: dict[str, Any], *, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family="items",
        index=index,
        fields=("name", "slot_family", "item_kind", "type", "requirements", "tags", "source_file"),
    )
    implicit_text = _normalize_string_list(record.get("implicit_text"))
    flavour_text = _normalize_string_list(record.get("flavour_text"))
    implicit_mod_types = _normalize_nested_string_lists(record.get("implicit_mod_types"))
    influence_tags = sorted(str(key) for key in (record.get("influence_tags") or {}).keys())
    requirements = _normalize_numeric_map(record.get("requirements"))
    raw_tags = [
        *record.get("tags", []),
        record["slot_family"],
        record["item_kind"],
        record["type"],
        record.get("sub_type"),
        *influence_tags,
        *(tag for group in implicit_mod_types for tag in group),
        *(key for key, value in requirements.items() if key in {"strength", "dexterity", "intelligence"} and value > 0),
    ]
    supporting_text = _dedupe_preserve(
        [
            record["name"],
            record["type"],
            record.get("sub_type"),
            *implicit_text,
            *flavour_text,
        ]
    )
    explicit_facets = {
        "item_slot": [record["slot_family"]],
        "item_class": [record["type"], record.get("sub_type")],
        "item_kind": [record["item_kind"]],
        "influence": influence_tags,
    }
    scaling_facets = _facet_list(explicit_facets, _match_facet_values([*supporting_text, *raw_tags]))
    source_context = {
        "slot_family": str(record["slot_family"]),
        "item_kind": str(record["item_kind"]),
        "type": str(record["type"]),
        "sub_type": str(record["sub_type"]) if record.get("sub_type") is not None else None,
        "requirements": requirements,
        "raw_tags": _sorted_unique_tags(record.get("tags", [])),
        "source_file": str(record["source_file"]),
        "implicit_text": implicit_text,
        "implicit_mod_types": implicit_mod_types,
        "influence_tags": _sorted_unique_tags(influence_tags),
    }
    return {
        "source_id": f"items:{_slugify(record['name'])}",
        "source_name": str(record["name"]),
        "search_tags": _search_tags(
            identifier_values=[
                record["name"],
                record["type"],
                record.get("sub_type"),
                *influence_tags,
            ],
            raw_tags=raw_tags,
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _gem_record(record: dict[str, Any], *, family: str, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family=family,
        index=index,
        fields=(
            "name",
            "variant_id",
            "record_id",
            "game_id",
            "granted_effect_id",
            "tag_keys",
            "required_attributes",
            "natural_max_level",
            "is_vaal_gem",
            "grants_active_skill",
        ),
    )
    required_attributes = _normalize_numeric_map(record.get("required_attributes"))
    tag_keys = _sorted_unique_tags(record.get("tag_keys", []))
    gem_role = "support_gem" if family == "support_gems" else "active_gem"
    raw_tags = [
        *tag_keys,
        *(attribute for attribute, value in required_attributes.items() if value > 0),
        gem_role,
    ]
    supporting_text = _dedupe_preserve(
        [
            record["name"],
            record.get("base_type_name"),
            record.get("tag_string"),
            record.get("secondary_granted_effect_id"),
        ]
    )
    scaling_facets = _facet_list({"gem_role": [gem_role]}, _match_facet_values([*supporting_text, *raw_tags]))
    source_context = {
        "base_type_name": str(record.get("base_type_name") or record["name"]),
        "variant_id": str(record["variant_id"]),
        "record_id": str(record["record_id"]),
        "game_id": str(record["game_id"]),
        "granted_effect_id": str(record["granted_effect_id"]),
        "secondary_granted_effect_id": (
            str(record["secondary_granted_effect_id"])
            if record.get("secondary_granted_effect_id") is not None
            else None
        ),
        "required_attributes": required_attributes,
        "natural_max_level": int(record["natural_max_level"]),
        "tag_keys": tag_keys,
        "is_vaal_gem": bool(record["is_vaal_gem"]),
        "grants_active_skill": bool(record["grants_active_skill"]),
    }
    return {
        "source_id": f"{family}:{_slugify(record['variant_id'])}",
        "source_name": str(record["name"]),
        "search_tags": _search_tags(
            identifier_values=[
                record["name"],
                record.get("base_type_name"),
                record["variant_id"],
                record["granted_effect_id"],
                record.get("secondary_granted_effect_id"),
            ],
            raw_tags=raw_tags,
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _tree_node_base_context(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": int(record["node_id"]),
        "skill_id": int(record["skill_id"]),
        "stats": _normalize_string_list(record.get("stats")),
        "reminder_text": _normalize_string_list(record.get("reminder_text")),
        "recipe": _normalize_string_list(record.get("recipe")),
        "is_notable": bool(record.get("is_notable")),
        "is_keystone": bool(record.get("is_keystone")),
        "is_mastery": bool(record.get("is_mastery")),
        "is_blighted": bool(record.get("is_blighted")),
        "is_proxy": bool(record.get("is_proxy")),
        "is_ascendancy_start": bool(record.get("is_ascendancy_start")),
        "class_start_index": int(record["class_start_index"]) if record.get("class_start_index") is not None else None,
        "ascendancy_name": str(record["ascendancy_name"]) if record.get("ascendancy_name") is not None else None,
    }


def _tree_node_record(record: dict[str, Any], *, family: str, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family=family,
        index=index,
        fields=(
            "node_id",
            "skill_id",
            "name",
            "stats",
            "reminder_text",
            "recipe",
            "is_notable",
            "is_keystone",
            "is_mastery",
            "is_blighted",
            "is_proxy",
            "is_ascendancy_start",
            "class_start_index",
            "ascendancy_name",
        ),
    )
    stats = _normalize_string_list(record.get("stats"))
    reminder_text = _normalize_string_list(record.get("reminder_text"))
    recipe = _normalize_string_list(record.get("recipe"))
    raw_tags: list[Any] = []
    node_kind: list[str] = []
    if record.get("is_notable"):
        raw_tags.append("notable")
        node_kind.append("notable")
    if record.get("is_keystone"):
        raw_tags.append("keystone")
        node_kind.append("keystone")
    if record.get("is_mastery"):
        raw_tags.append("mastery")
        node_kind.append("mastery")
    if record.get("is_blighted"):
        raw_tags.append("blighted")
        node_kind.append("blighted")
    if record.get("is_proxy"):
        raw_tags.append("proxy")
        node_kind.append("proxy")
    if record.get("is_ascendancy_start"):
        raw_tags.append("ascendancy_start")
        node_kind.append("ascendancy_start")
    if record.get("class_start_index") is not None:
        raw_tags.append("class_start")
        node_kind.append("class_start")
    if recipe:
        raw_tags.append("anointable")
    if record.get("ascendancy_name") is not None:
        raw_tags.append(record["ascendancy_name"])
    supporting_text = _dedupe_preserve(
        [
            record["name"],
            *stats,
            *reminder_text,
            *recipe,
            *_normalize_string_list(record.get("flavour_text")),
        ]
    )
    scaling_facets = _facet_list({"node_kind": node_kind}, _match_facet_values([*supporting_text, *raw_tags]))
    source_context = _tree_node_base_context(record)
    return {
        "source_id": f"{family}:{record['node_id']}",
        "source_name": str(record["name"]),
        "search_tags": _search_tags(
            identifier_values=[record["name"], record.get("ascendancy_name"), *recipe],
            raw_tags=raw_tags,
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _mastery_record(record: dict[str, Any], *, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family="masteries",
        index=index,
        fields=(
            "node_id",
            "skill_id",
            "name",
            "mastery_effects",
            "stats",
            "reminder_text",
            "recipe",
            "is_notable",
            "is_keystone",
            "is_mastery",
            "is_blighted",
            "is_proxy",
            "is_ascendancy_start",
            "class_start_index",
            "ascendancy_name",
        ),
    )
    mastery_effects = []
    mastery_lines: list[str] = []
    for effect in record.get("mastery_effects", []):
        if not isinstance(effect, dict):
            continue
        stats = _normalize_string_list(effect.get("stats"))
        reminder_text = _normalize_string_list(effect.get("reminder_text"))
        mastery_effects.append(
            {
                "effect_id": int(effect["effect_id"]),
                "stats": stats,
                "reminder_text": reminder_text,
            }
        )
        mastery_lines.extend(stats)
        mastery_lines.extend(reminder_text)
    base_context = _tree_node_base_context(record)
    supporting_text = _dedupe_preserve([record["name"], *mastery_lines])
    scaling_facets = _facet_list({"node_kind": ["mastery"]}, _match_facet_values([*supporting_text, "mastery"]))
    source_context = {
        **base_context,
        "mastery_effects": mastery_effects,
    }
    return {
        "source_id": f"masteries:{record['node_id']}",
        "source_name": str(record["name"]),
        "search_tags": _search_tags(
            identifier_values=[record["name"]],
            raw_tags=["mastery"],
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _ascendancy_record(record: dict[str, Any], *, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family="ascendancies",
        index=index,
        fields=("ascendancy_id", "display_name", "class_name", "source_kind", "node_count", "start_node_ids", "nodes"),
    )
    node_names: list[str] = []
    stat_excerpt: list[str] = []
    for node in record.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if node.get("name") is not None:
            node_names.append(str(node["name"]))
        stat_excerpt.extend(_normalize_string_list(node.get("stats")))
        stat_excerpt.extend(_normalize_string_list(node.get("reminder_text")))
    node_names = _dedupe_preserve(node_names)
    stat_excerpt = _dedupe_preserve(stat_excerpt)
    raw_tags = [
        record["ascendancy_id"],
        record["display_name"],
        record.get("class_name"),
        record.get("source_kind"),
        "ascendancy",
    ]
    class_facets = [record["class_name"]] if record.get("class_name") is not None else []
    supporting_text = _dedupe_preserve(
        [
            record["display_name"],
            record.get("class_name"),
            *node_names,
            *stat_excerpt,
            *_normalize_string_list(record.get("flavour_text")),
        ]
    )
    scaling_facets = _facet_list({"class": class_facets}, _match_facet_values([*supporting_text, *raw_tags]))
    source_context = {
        "ascendancy_id": str(record["ascendancy_id"]),
        "class_name": str(record["class_name"]) if record.get("class_name") is not None else None,
        "source_kind": str(record["source_kind"]),
        "node_count": int(record["node_count"]),
        "start_node_ids": [int(node_id) for node_id in record.get("start_node_ids", [])],
        "node_names": node_names,
        "stat_excerpt": stat_excerpt,
        "flavour_text": _normalize_string_list(record.get("flavour_text")),
    }
    return {
        "source_id": f"ascendancies:{_slugify(record['ascendancy_id'])}",
        "source_name": str(record["display_name"]),
        "search_tags": _search_tags(
            identifier_values=[
                record["display_name"],
                record["ascendancy_id"],
                record.get("class_name"),
                *node_names,
            ],
            raw_tags=raw_tags,
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _config_scope(record: dict[str, Any]) -> list[str]:
    scopes: set[str] = set()
    predicates = {str(key) for key in (record.get("predicates") or {}).keys()}
    section = str(record.get("section") or "")
    searchable = " ".join(
        _normalize_text_for_matching(
            [
                section,
                record.get("label"),
                record.get("var"),
                record.get("tooltip_text"),
            ]
        )
    )
    if section == "Custom Modifiers":
        scopes.add("custom_modifier")
    if section == "Map Modifiers and Player Debuffs" or re.search(r"\bmap\b", searchable):
        scopes.add("map")
    if section == "Skill Options" or any(key.startswith("ifSkill") for key in predicates):
        scopes.add("skill")
    if any(key.startswith("ifEnemy") for key in predicates) or re.search(r"\benemy\b", searchable):
        scopes.add("enemy")
    if "ifMinionCond" in predicates or re.search(r"\bminion(?:s)?\b", searchable):
        scopes.add("minion")
    if not scopes:
        scopes.add("player")
    return sorted(scopes)


def _config_record(record: dict[str, Any], *, index: int) -> dict[str, Any]:
    _require_fields(
        record,
        family="config_surfaces",
        index=index,
        fields=(
            "var",
            "section",
            "type",
            "predicates",
            "list_values",
            "tooltip_text",
            "include_transfigured",
            "has_apply_function",
            "has_tooltip_function",
            "column",
            "order",
            "default_index",
            "default_placeholder",
            "list_source",
        ),
    )
    label = str(record["label"]) if record.get("label") is not None else None
    source_name = label or str(record["var"])
    predicates = _sorted_unique_tags((record.get("predicates") or {}).keys())
    list_values = _normalize_list_values(record.get("list_values"))
    list_labels = [value["label"] for value in list_values if value["label"] is not None]
    raw_tags = [
        record["var"],
        record["section"],
        record["type"],
        *predicates,
        *(["include_transfigured"] if record.get("include_transfigured") else []),
    ]
    supporting_text = _dedupe_preserve(
        [
            source_name,
            record["var"],
            record["section"],
            record["type"],
            record.get("tooltip_text"),
            *list_labels,
        ]
    )
    explicit_facets = {
        "config_section": [record["section"]],
        "config_control_type": [record["type"]],
        "config_scope": _config_scope(record),
        "config_predicate": predicates,
    }
    scaling_facets = _facet_list(explicit_facets, _match_facet_values([*supporting_text, *raw_tags]))
    source_context = {
        "var": str(record["var"]),
        "label": label,
        "section": str(record["section"]),
        "type": str(record["type"]),
        "predicates": predicates,
        "list_values": list_values,
        "tooltip_text": str(record["tooltip_text"]) if record.get("tooltip_text") is not None else None,
        "include_transfigured": bool(record["include_transfigured"]),
        "has_apply_function": bool(record["has_apply_function"]),
        "has_tooltip_function": bool(record["has_tooltip_function"]),
        "column": int(record["column"]),
        "order": int(record["order"]),
        "default_index": int(record["default_index"]) if record.get("default_index") is not None else None,
        "default_placeholder": (
            str(record["default_placeholder"]) if record.get("default_placeholder") is not None else None
        ),
        "list_source": str(record["list_source"]) if record.get("list_source") is not None else None,
    }
    return {
        "source_id": f"config_surfaces:{_slugify(record['var'])}",
        "source_name": source_name,
        "search_tags": _search_tags(
            identifier_values=[record["var"], *list_labels],
            raw_tags=raw_tags,
            scaling_facets=scaling_facets,
        ),
        "scaling_facets": scaling_facets,
        "supporting_text": supporting_text,
        "source_context": source_context,
    }


def _derive_family_records(family: str, source_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    records = source_bundle["records"]
    derived_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TagCorpusContractError(f"{family} record {index} is not an object.")
        if family == "items":
            derived_records.append(_item_record(record, index=index))
        elif family in {"active_gems", "support_gems"}:
            derived_records.append(_gem_record(record, family=family, index=index))
        elif family in {"passives", "keystones"}:
            derived_records.append(_tree_node_record(record, family=family, index=index))
        elif family == "masteries":
            derived_records.append(_mastery_record(record, index=index))
        elif family == "ascendancies":
            derived_records.append(_ascendancy_record(record, index=index))
        elif family == "config_surfaces":
            derived_records.append(_config_record(record, index=index))
        else:
            raise TagCorpusContractError(f"Unsupported tag corpus family: {family}")
    if len(derived_records) != len(records):
        raise TagCorpusContractError(f"Failed to derive every record for family {family}.")
    return derived_records


def _build_family_bundle(
    family: str,
    derived_records: list[dict[str, Any]],
    *,
    source_manifest: dict[str, Any],
    source_manifest_path: Path,
    source_bundle_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": family,
        "record_count": len(derived_records),
        "provenance": {
            "derived_from_corpus_id": source_manifest["corpus_id"],
            "derived_from_manifest_path": _relative_path(source_manifest_path),
            "derived_from_manifest_sha256": _sha256_file(source_manifest_path),
            "derived_from_family": family,
            "derived_from_bundle_path": _relative_path(source_bundle_path),
            "derived_from_bundle_sha256": _sha256_file(source_bundle_path),
            "source_lane": source_manifest["source_lane"],
        },
        "metadata": {
            "record_field_order": FIELD_ORDER["record"],
            "facet_field_order": FIELD_ORDER["facet"],
            "facet_coverage": _build_facet_coverage(derived_records),
        },
        "records": derived_records,
    }


def _build_manifest(
    bundles: dict[str, dict[str, Any]],
    *,
    source_manifest: dict[str, Any],
    source_manifest_path: Path,
    source_bundle_paths: dict[str, Path],
    output_root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "source_corpus": {
            "corpus_id": source_manifest["corpus_id"],
            "manifest_path": _relative_path(source_manifest_path),
            "manifest_sha256": _sha256_file(source_manifest_path),
            "source_lane": source_manifest["source_lane"],
        },
        "families": [
            {
                "family": family,
                "relative_path": _relative_path(output_root / FAMILY_FILE_NAMES[family]),
                "record_count": bundle["record_count"],
                "derived_from_bundle_path": _relative_path(source_bundle_paths[family]),
                "derived_from_bundle_sha256": _sha256_file(source_bundle_paths[family]),
                "derived_from_record_count": bundle["record_count"],
            }
            for family, bundle in sorted(bundles.items())
        ],
        "downstream_policy": {
            "read_root": _relative_path(output_root),
            "derivation_source_root": _relative_path(source_manifest_path.parent),
            "consumer_rule": (
                "Downstream agents must read committed tag bundles for ordinary tag-driven lookup instead of "
                "reparsing committed game corpus bundles."
            ),
            "loader_boundary": "junkroan.pob.tag_corpus",
            "source_lane_authority": "vendor/pob/source",
            "authority_rule": "Use vendor/pob/source only when updating the accepted game corpus or auditing tag derivation rules.",
        },
        "field_order": FIELD_ORDER,
    }


def build_tag_corpus(
    *,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST_PATH,
    output_root: Path = DEFAULT_TAG_CORPUS_ROOT,
) -> Path:
    """Materialize the committed PoB tag corpus from the committed game corpus."""

    source_manifest, source_bundle_paths, source_bundles = _load_source_corpus(source_manifest_path)
    bundles: dict[str, dict[str, Any]] = {}
    for family in EXPECTED_FAMILIES:
        derived_records = _derive_family_records(family, source_bundles[family])
        bundles[family] = _build_family_bundle(
            family,
            derived_records,
            source_manifest=source_manifest,
            source_manifest_path=source_manifest_path,
            source_bundle_path=source_bundle_paths[family],
        )

    output_root.mkdir(parents=True, exist_ok=True)
    for family, bundle in bundles.items():
        _write_json(output_root / FAMILY_FILE_NAMES[family], bundle)

    manifest = _build_manifest(
        bundles,
        source_manifest=source_manifest,
        source_manifest_path=source_manifest_path,
        source_bundle_paths=source_bundle_paths,
        output_root=output_root,
    )
    _write_json(output_root / "manifest.json", manifest)
    return output_root / "manifest.json"


def load_tag_corpus_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load the committed tag corpus manifest."""

    return _load_json(manifest_path)


def load_tag_corpus_bundle(family: str, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load one committed tag corpus family bundle."""

    if family not in FAMILY_FILE_NAMES:
        raise TagCorpusContractError(f"Unknown tag corpus family: {family}")
    return _load_json(manifest_path.parent / FAMILY_FILE_NAMES[family])


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m junkroan.pob.tag_corpus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Materialize the committed PoB tag corpus surface.")
    build_parser.add_argument("--output-root", default=str(DEFAULT_TAG_CORPUS_ROOT), help="Directory to write tag bundles into.")
    build_parser.add_argument(
        "--source-manifest",
        default=str(DEFAULT_SOURCE_MANIFEST_PATH),
        help="Committed game corpus manifest to derive from.",
    )
    build_parser.set_defaults(handler=_handle_build)

    show_parser = subparsers.add_parser("show-manifest", help="Show the current committed tag corpus manifest.")
    show_parser.set_defaults(handler=_handle_show_manifest)
    return parser


def _handle_build(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = build_tag_corpus(
        source_manifest_path=Path(args.source_manifest),
        output_root=Path(args.output_root),
    )
    return _load_json(manifest_path)


def _handle_show_manifest(_: argparse.Namespace) -> dict[str, Any]:
    return load_tag_corpus_manifest()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except TagCorpusContractError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
