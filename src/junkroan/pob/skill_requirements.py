"""Agent-facing skill requirement facts from pinned PoB skill data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from .game_corpus import DEFAULT_CORPUS_ROOT, DEFAULT_SOURCE_ROOT
from .lua_tables import LuaParseError, parse_lua_return_value

POB_SKILL_REQUIREMENTS_SCHEMA_VERSION = "1.0.0"
POB_SKILL_REQUIREMENTS_RECORD_KIND = "pob_skill_requirements"
POB_SKILL_REQUIREMENTS_VALIDATION_SET_KIND = "pob_skill_requirements_validation_set"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAG_CORPUS_ROOT = Path(__file__).with_name("tag_data")
DEFAULT_ACTIVE_GEMS_PATH = DEFAULT_CORPUS_ROOT / "active_gems.json"
DEFAULT_SUPPORT_GEMS_PATH = DEFAULT_CORPUS_ROOT / "support_gems.json"
DEFAULT_ACTIVE_TAGS_PATH = DEFAULT_TAG_CORPUS_ROOT / "active_gems.json"
DEFAULT_SUPPORT_TAGS_PATH = DEFAULT_TAG_CORPUS_ROOT / "support_gems.json"

SKILL_SOURCE_RELATIVE_PATHS = (
    "src/Data/Skills/act_dex.lua",
    "src/Data/Skills/act_int.lua",
    "src/Data/Skills/act_str.lua",
    "src/Data/Skills/minion.lua",
    "src/Data/Skills/other.lua",
    "src/Data/Skills/sup_dex.lua",
    "src/Data/Skills/sup_int.lua",
    "src/Data/Skills/sup_str.lua",
)

SKILL_TYPE_PATTERN = re.compile(r"\[SkillType\.([A-Za-z0-9_]+)\]\s*=\s*true")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")

DAMAGE_TYPE_NAMES = {
    "Physical": "physical",
    "Fire": "fire",
    "Cold": "cold",
    "Lightning": "lightning",
    "Chaos": "chaos",
    "Elemental": "elemental",
}

DELIVERY_SKILL_TYPES = {
    "Projectile": "projectile",
    "Area": "area",
    "Melee": "melee",
    "MeleeSingleTarget": "melee_single_target",
    "Strike": "strike",
    "Slam": "slam",
    "Duration": "duration",
    "Brand": "brand",
    "Aura": "aura",
    "Curse": "curse",
    "Hex": "hex",
    "Mark": "mark",
    "Warcry": "warcry",
    "Movement": "movement",
    "Nova": "nova",
    "Channelling": "channelling",
    "Channel": "channelling",
}

ONE_HAND_WEAPON_TYPES = {
    "Claw",
    "Dagger",
    "One Handed Axe",
    "One Handed Mace",
    "One Handed Sword",
    "Sceptre",
    "Thrusting One Handed Sword",
    "Wand",
}
TWO_HAND_WEAPON_TYPES = {
    "Bow",
    "Staff",
    "Two Handed Axe",
    "Two Handed Mace",
    "Two Handed Sword",
    "Warstaff",
}


class PoBSkillRequirementsContractError(RuntimeError):
    """Raised when a skill requirement packet cannot be built honestly."""

    def __init__(self, failure_state: str, message: str) -> None:
        super().__init__(message)
        self.failure_state = failure_state


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    source_path: Path
    source_line: int
    fields: Mapping[str, str]


@dataclass(frozen=True)
class GemRecord:
    family: str
    bundle_path: Path
    payload: Mapping[str, Any]


def _fail(failure_state: str, message: str) -> None:
    raise PoBSkillRequirementsContractError(failure_state, message)


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_key(value: Any) -> str:
    return NORMALIZE_PATTERN.sub("", str(value).lower())


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


def _dedupe_ints(values: Iterable[Any]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _sorted_unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})


def _skip_ignored(text: str, pos: int) -> int:
    length = len(text)
    while pos < length:
        if text[pos].isspace():
            pos += 1
            continue
        if text.startswith("--", pos):
            pos += 2
            while pos < length and text[pos] not in "\r\n":
                pos += 1
            continue
        break
    return pos


def _scan_balanced(text: str, opening_brace: int) -> int:
    depth = 0
    pos = opening_brace
    quote: str | None = None
    long_string = False
    while pos < len(text):
        if quote is not None:
            if text[pos] == "\\":
                pos += 2
                continue
            if text[pos] == quote:
                quote = None
            pos += 1
            continue
        if long_string:
            if text.startswith("]]", pos):
                long_string = False
                pos += 2
                continue
            pos += 1
            continue
        if text.startswith("--", pos):
            pos += 2
            while pos < len(text) and text[pos] not in "\r\n":
                pos += 1
            continue
        if text.startswith("[[", pos):
            long_string = True
            pos += 2
            continue

        char = text[pos]
        if char in {'"', "'"}:
            quote = char
            pos += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    _fail("invalid_skill_source", "Failed to close a Data/Skills Lua table.")


def _capture_expression(text: str, start: int) -> tuple[str, int]:
    pos = _skip_ignored(text, start)
    expression_start = pos
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
    function_depth = 0
    quote: str | None = None
    long_string = False
    while pos < len(text):
        if quote is not None:
            if text[pos] == "\\":
                pos += 2
                continue
            if text[pos] == quote:
                quote = None
            pos += 1
            continue
        if long_string:
            if text.startswith("]]", pos):
                long_string = False
                pos += 2
                continue
            pos += 1
            continue
        if text.startswith("--", pos):
            pos += 2
            while pos < len(text) and text[pos] not in "\r\n":
                pos += 1
            continue
        if text.startswith("[[", pos):
            long_string = True
            pos += 2
            continue

        identifier = IDENTIFIER_PATTERN.match(text, pos)
        if identifier is not None:
            token = identifier.group(0)
            if token == "function":
                function_depth += 1
                pos = identifier.end()
                continue
            if token == "end" and function_depth > 0:
                function_depth -= 1
                pos = identifier.end()
                continue

        char = text[pos]
        if char in {'"', "'"}:
            quote = char
            pos += 1
            continue
        if char == "{":
            brace_depth += 1
            pos += 1
            continue
        if char == "}":
            if brace_depth == 0 and bracket_depth == 0 and paren_depth == 0 and function_depth == 0:
                break
            brace_depth -= 1
            pos += 1
            continue
        if char == "[":
            bracket_depth += 1
            pos += 1
            continue
        if char == "]":
            bracket_depth -= 1
            pos += 1
            continue
        if char == "(":
            paren_depth += 1
            pos += 1
            continue
        if char == ")":
            paren_depth -= 1
            pos += 1
            continue
        if (
            char == ","
            and brace_depth == 0
            and bracket_depth == 0
            and paren_depth == 0
            and function_depth == 0
        ):
            break
        pos += 1
    return text[expression_start:pos].strip(), pos


def _top_level_field_expressions(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = _skip_ignored(block, 0)
    if pos >= len(block) or block[pos] != "{":
        _fail("invalid_skill_source", "Expected a Data/Skills block to start with a table.")
    pos += 1
    while pos < len(block):
        pos = _skip_ignored(block, pos)
        if pos >= len(block) or block[pos] == "}":
            break
        checkpoint = pos
        match = IDENTIFIER_PATTERN.match(block, pos)
        if match is not None:
            field_name = match.group(0)
            after_name = _skip_ignored(block, match.end())
            if after_name < len(block) and block[after_name] == "=":
                expression, pos = _capture_expression(block, after_name + 1)
                fields.setdefault(field_name, expression)
            else:
                _, pos = _capture_expression(block, checkpoint)
        else:
            _, pos = _capture_expression(block, checkpoint)
        pos = _skip_ignored(block, pos)
        if pos < len(block) and block[pos] in {",", ";"}:
            pos += 1
    return fields


def _iter_skill_definitions_for_file(path: Path) -> Iterable[SkillDefinition]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"skills\[\s*([\"'])(?P<skill_id>.+?)\1\s*\]\s*=\s*\{")
    for match in pattern.finditer(text):
        opening = text.find("{", match.end() - 1)
        if opening == -1:
            _fail("invalid_skill_source", f"Skill {match.group('skill_id')} is missing its table body.")
        closing = _scan_balanced(text, opening)
        block = text[opening : closing + 1]
        yield SkillDefinition(
            skill_id=match.group("skill_id"),
            source_path=path,
            source_line=text.count("\n", 0, match.start()) + 1,
            fields=_top_level_field_expressions(block),
        )


@lru_cache(maxsize=4)
def _load_skill_definitions_cached(source_root_text: str) -> dict[str, SkillDefinition]:
    source_root = Path(source_root_text)
    definitions: dict[str, SkillDefinition] = {}
    for relative_path in SKILL_SOURCE_RELATIVE_PATHS:
        source_path = source_root / relative_path
        if not source_path.is_file():
            _fail("missing_skill_source", f"Missing pinned skill source file: {_relative_path(source_path)}")
        for definition in _iter_skill_definitions_for_file(source_path):
            definitions.setdefault(definition.skill_id, definition)
    if not definitions:
        _fail("missing_skill_source", "No skill definitions were loaded from pinned PoB Data/Skills.")
    return definitions


def load_skill_definitions(source_root: Path = DEFAULT_SOURCE_ROOT) -> dict[str, SkillDefinition]:
    """Load top-level skill definitions from the accepted pinned PoB skill files."""

    return dict(_load_skill_definitions_cached(str(source_root.resolve())))


def _literal_from_expression(expression: str | None) -> Any | None:
    if expression is None:
        return None
    try:
        return parse_lua_return_value(f"return {expression}")
    except LuaParseError:
        return None


def _literal_string(fields: Mapping[str, str], field_name: str) -> str | None:
    value = _literal_from_expression(fields.get(field_name))
    return value if isinstance(value, str) and value.strip() else None


def _parse_skill_types(expression: str | None) -> dict[str, Any]:
    if expression is None:
        return {"state": "unknown", "values": [], "unsupported_reason": "skillTypes field is absent."}
    values = sorted(set(SKILL_TYPE_PATTERN.findall(expression)))
    if not values:
        return {
            "state": "unknown",
            "values": [],
            "unsupported_reason": "skillTypes field was present but did not match literal SkillType keys.",
        }
    return {"state": "known", "values": values}


def _parse_bool_key_table(expression: str | None, *, absent_reason: str) -> dict[str, Any]:
    if expression is None:
        return {"state": "unknown", "values": [], "unsupported_reason": absent_reason}
    parsed = _literal_from_expression(expression)
    if not isinstance(parsed, dict):
        return {
            "state": "unknown",
            "values": [],
            "unsupported_reason": "field was present but not a safely parsed literal bool table.",
        }
    values = sorted(str(key) for key, value in parsed.items() if value is True)
    return {"state": "known", "values": values}


def _parse_string_stat_ids(expression: str | None) -> list[str]:
    parsed = _literal_from_expression(expression)
    if not isinstance(parsed, list):
        return []
    values: list[str] = []
    for entry in parsed:
        if isinstance(entry, str):
            values.append(entry)
        elif isinstance(entry, list) and entry and isinstance(entry[0], str):
            values.append(entry[0])
    return _dedupe_preserve(values)


def _normalize_numeric_map(payload: Any) -> dict[str, int | float]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, int | float] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            normalized[str(key)] = int(value) if isinstance(value, float) and value.is_integer() else value
    return normalized


def _level_rows(expression: str | None) -> list[tuple[int, Mapping[str, Any]]]:
    parsed = _literal_from_expression(expression)
    rows: list[tuple[int, Mapping[str, Any]]] = []
    if isinstance(parsed, list):
        for index, row in enumerate(parsed, start=1):
            if isinstance(row, dict):
                rows.append((index, row))
    elif isinstance(parsed, dict):
        for key, row in parsed.items():
            if isinstance(key, int) and isinstance(row, dict):
                rows.append((key, row))
    return sorted(rows, key=lambda item: item[0])


def _level_requirement_facts(
    fields: Mapping[str, str],
    *,
    natural_max_level: int | None,
) -> dict[str, Any]:
    rows = _level_rows(fields.get("levels"))
    if not rows:
        return {
            "state": "unknown",
            "natural_max_level": natural_max_level,
            "unsupported_reason": "levels field was absent or not a safely parsed literal table.",
            "sampled_level_requirements": [],
        }

    level_requirements = [
        {
            "gem_level": gem_level,
            "character_level": int(row["levelRequirement"]),
        }
        for gem_level, row in rows
        if isinstance(row.get("levelRequirement"), (int, float)) and not isinstance(row.get("levelRequirement"), bool)
    ]
    requirement_by_level = {entry["gem_level"]: entry["character_level"] for entry in level_requirements}
    sample_levels = _dedupe_ints(
        [
            1,
            natural_max_level,
            rows[-1][0],
        ]
    )
    sampled = [
        {
            "gem_level": level,
            "character_level": int(requirement_by_level[level]),
        }
        for level in sample_levels
        if level in requirement_by_level
    ]
    character_levels = list(requirement_by_level.values())
    return {
        "state": "known",
        "natural_max_level": natural_max_level,
        "parsed_level_count": len(rows),
        "min_character_level": min(character_levels) if character_levels else None,
        "natural_max_character_level": requirement_by_level.get(natural_max_level) if natural_max_level else None,
        "max_parsed_character_level": max(character_levels) if character_levels else None,
        "sampled_level_requirements": sampled,
    }


def _cost_and_reservation_facts(fields: Mapping[str, str], *, natural_max_level: int | None) -> dict[str, Any]:
    rows = _level_rows(fields.get("levels"))
    cost_by_level: dict[int, dict[str, int | float]] = {}
    for gem_level, row in rows:
        cost = _normalize_numeric_map(row.get("cost"))
        if cost:
            cost_by_level[gem_level] = cost
    resource_keys = sorted({key for cost in cost_by_level.values() for key in cost})
    sample_levels = _dedupe_ints([1, natural_max_level, rows[-1][0] if rows else None])
    sampled_costs = [
        {"gem_level": level, "cost": cost_by_level[level]}
        for level in sample_levels
        if level in cost_by_level
    ]
    reservation_like_keys = [
        key
        for key in resource_keys
        if "reservation" in key.lower() or "reserved" in key.lower() or "reserve" in key.lower()
    ]
    reservation_state = "known" if reservation_like_keys else "unknown"
    reservation_reason = None if reservation_like_keys else "No reservation-like cost keys were present in parsed level data."
    return {
        "costs": {
            "state": "known" if cost_by_level else "unknown",
            "resource_keys": resource_keys,
            "sampled_costs": sampled_costs,
        },
        "reservation": {
            "state": reservation_state,
            "resource_keys": reservation_like_keys,
            "unsupported_reason": reservation_reason,
        },
    }


def _load_gem_records(active_path: Path, support_path: Path) -> list[GemRecord]:
    records: list[GemRecord] = []
    for family, bundle_path in (("active_gems", active_path), ("support_gems", support_path)):
        bundle = _load_json(bundle_path)
        for record in bundle.get("records", []):
            if isinstance(record, dict):
                records.append(GemRecord(family=family, bundle_path=bundle_path, payload=record))
    return records


def _gem_lookup_keys(record: GemRecord) -> list[str]:
    payload = record.payload
    return [
        _normalize_key(value)
        for value in (
            payload.get("record_id"),
            payload.get("game_id"),
            payload.get("variant_id"),
            payload.get("granted_effect_id"),
            payload.get("secondary_granted_effect_id"),
            payload.get("name"),
            payload.get("base_type_name"),
        )
        if value
    ]


def _find_gem_record(query: str, records: Iterable[GemRecord]) -> GemRecord | None:
    normalized = _normalize_key(query)
    for record in records:
        if normalized in _gem_lookup_keys(record):
            return record
    return None


def _definition_name(definition: SkillDefinition) -> str | None:
    return _literal_string(definition.fields, "name")


def _find_definition(query: str, definitions: Mapping[str, SkillDefinition]) -> SkillDefinition | None:
    normalized = _normalize_key(query)
    for skill_id, definition in definitions.items():
        if normalized == _normalize_key(skill_id):
            return definition
    for definition in definitions.values():
        name = _definition_name(definition)
        if name and normalized == _normalize_key(name):
            return definition
    return None


def _resolve_definition_and_record(
    query: str,
    *,
    definitions: Mapping[str, SkillDefinition],
    gem_records: Iterable[GemRecord],
) -> tuple[SkillDefinition, GemRecord | None]:
    records = list(gem_records)
    definition = _find_definition(query, definitions)
    record = _find_gem_record(query, records)
    if definition is None and record is not None:
        for key in (
            record.payload.get("granted_effect_id"),
            record.payload.get("variant_id"),
            record.payload.get("secondary_granted_effect_id"),
            record.payload.get("name"),
        ):
            if key:
                definition = _find_definition(str(key), definitions)
                if definition is not None:
                    break
    if definition is None:
        _fail("unresolved_skill", f"Skill {query!r} could not be resolved in pinned PoB skill definitions.")
    if record is None:
        record = _find_gem_record(definition.skill_id, records)
    return definition, record


def _find_tag_record(
    record: GemRecord | None,
    *,
    active_tags_path: Path,
    support_tags_path: Path,
) -> tuple[Mapping[str, Any] | None, Path | None]:
    if record is None:
        return None, None
    target_path = active_tags_path if record.family == "active_gems" else support_tags_path
    if not target_path.is_file():
        return None, None
    bundle = _load_json(target_path)
    variant_id = record.payload.get("variant_id")
    name = record.payload.get("name")
    for tag_record in bundle.get("records", []):
        if not isinstance(tag_record, dict):
            continue
        source_context = tag_record.get("source_context")
        if not isinstance(source_context, dict):
            continue
        if source_context.get("variant_id") == variant_id or tag_record.get("source_name") == name:
            return tag_record, target_path
    return None, target_path


def _weapon_type_facts(
    fields: Mapping[str, str],
    *,
    is_attack: bool,
) -> dict[str, Any]:
    parsed = _parse_bool_key_table(
        fields.get("weaponTypes"),
        absent_reason="weaponTypes field is absent.",
    )
    if parsed["state"] == "known":
        return {
            "state": "known",
            "values": parsed["values"],
            "source_field": "weaponTypes",
        }
    if is_attack:
        return {
            "state": "unknown",
            "values": [],
            "unsupported_reason": "Attack skill has no safely parsed weaponTypes field; do not infer broad weapon legality.",
        }
    return {
        "state": "not_required_by_pinned_skill_data",
        "values": [],
        "unsupported_reason": "No weaponTypes field was present, and the skill is not flagged as an attack.",
    }


def _derive_offhand_families(weapon_types: Mapping[str, Any]) -> dict[str, Any]:
    if weapon_types.get("state") != "known":
        return {
            "state": weapon_types.get("state", "unknown"),
            "values": [],
            "unsupported_reason": weapon_types.get("unsupported_reason"),
        }
    values = set(str(value) for value in weapon_types.get("values", []))
    families: list[str] = []
    if "Bow" in values:
        families.append("bow_with_quiver_or_empty_offhand")
    if values & ONE_HAND_WEAPON_TYPES:
        families.append("one_hand_weapon_with_shield_or_dual_wield")
    if values & (TWO_HAND_WEAPON_TYPES - {"Bow"}):
        families.append("two_hand_weapon_no_shield")
    if not families:
        families.append("weapon_offhand_family_not_classified")
    return {
        "state": "derived_from_weapon_types",
        "values": _dedupe_preserve(families),
        "source_field": "weaponTypes",
    }


def _legality_flags(skill_types: Iterable[str], base_flags: Iterable[str]) -> dict[str, Any]:
    type_set = set(skill_types)
    flag_set = set(base_flags)
    evidence: dict[str, list[str]] = {
        "triggerable": ["SkillType.Triggerable"] if "Triggerable" in type_set else [],
        "can_be_trapped": ["SkillType.Trappable"] if "Trappable" in type_set else [],
        "native_trap": [
            *(("SkillType.Trapped",) if "Trapped" in type_set else ()),
            *(("baseFlags.trap",) if "trap" in flag_set else ()),
        ],
        "can_be_mined": ["SkillType.Mineable"] if "Mineable" in type_set else [],
        "native_mine": [
            *(("SkillType.Mined",) if "Mined" in type_set else ()),
            *(("baseFlags.mine",) if "mine" in flag_set else ()),
        ],
        "can_be_totem": ["SkillType.Totemable"] if "Totemable" in type_set else [],
        "native_totem": [
            *(("SkillType.SummonsTotem",) if "SummonsTotem" in type_set else ()),
            *(("baseFlags.totem",) if "totem" in flag_set else ()),
        ],
        "brand": [
            *(("SkillType.Brand",) if "Brand" in type_set else ()),
            *(("baseFlags.brand",) if "brand" in flag_set else ()),
        ],
        "minion": [
            *(("SkillType.Minion",) if "Minion" in type_set else ()),
            *(("SkillType.CreatesMinion",) if "CreatesMinion" in type_set else ()),
            *(("baseFlags.minion",) if "minion" in flag_set else ()),
            *(("baseFlags.permanentMinion",) if "permanentMinion" in flag_set else ()),
        ],
        "aura": [
            *(("SkillType.Aura",) if "Aura" in type_set else ()),
            *(("baseFlags.aura",) if "aura" in flag_set else ()),
        ],
    }
    return {
        "state": "known",
        "flags": {flag_name: bool(entries) for flag_name, entries in evidence.items()},
        "evidence": evidence,
    }


def _base_mode(skill_types: Iterable[str], base_flags: Iterable[str]) -> str:
    type_set = set(skill_types)
    flag_set = set(base_flags)
    if "Attack" in type_set or "attack" in flag_set:
        return "attack"
    if "Spell" in type_set or "spell" in flag_set:
        return "spell"
    return "skill"


def _delivery_axes(
    skill_types: Iterable[str],
    base_flags: Iterable[str],
    legality: Mapping[str, Any],
) -> list[str]:
    type_set = set(skill_types)
    flag_map = dict(legality.get("flags") or {})
    mode = _base_mode(type_set, base_flags)
    axes: list[str] = []
    if mode == "spell":
        axes.append("self_cast_spell")
    elif mode == "attack":
        axes.append("self_attack")
    if flag_map.get("native_trap"):
        axes.append("native_trap")
    elif flag_map.get("can_be_trapped"):
        axes.append(f"trap_{mode}")
    if flag_map.get("native_mine"):
        axes.append("native_mine")
    elif flag_map.get("can_be_mined"):
        axes.append(f"mine_{mode}")
    if flag_map.get("native_totem"):
        axes.append("native_totem")
    elif flag_map.get("can_be_totem"):
        axes.append(f"totem_{mode}")
    if flag_map.get("triggerable"):
        axes.append(f"triggered_{mode}")
    if flag_map.get("brand"):
        axes.append("brand")
    if flag_map.get("minion"):
        axes.append("minion")
    for skill_type, axis in DELIVERY_SKILL_TYPES.items():
        if skill_type in type_set:
            axes.append(axis)
    if any("Channel" in skill_type for skill_type in type_set):
        axes.append("channelling")
    return _dedupe_preserve(axes)


def _damage_axes(skill_types: Iterable[str], tag_keys: Iterable[str]) -> list[str]:
    type_set = set(skill_types)
    tag_set = {str(tag).lower() for tag in tag_keys}
    axes: list[str] = []
    if "Attack" in type_set or "attack" in tag_set:
        axes.append("attack_damage")
    if "Spell" in type_set or "spell" in tag_set:
        axes.append("spell_damage")
    if "Minion" in type_set or "minion" in tag_set:
        axes.append("minion_damage")
    for skill_type, axis in DAMAGE_TYPE_NAMES.items():
        if skill_type in type_set or axis in tag_set:
            axes.append(axis)
    if "DamageOverTime" in type_set or "dot" in tag_set:
        axes.append("damage_over_time")
    if "Hit" in type_set:
        axes.append("hit")
    return _dedupe_preserve(axes)


def _resource_axes(cost_and_reservation: Mapping[str, Any]) -> list[str]:
    axes: list[str] = []
    costs = cost_and_reservation.get("costs")
    if isinstance(costs, Mapping):
        for key in costs.get("resource_keys", []):
            axes.append(f"{str(key).lower()}_cost")
    reservation = cost_and_reservation.get("reservation")
    if isinstance(reservation, Mapping) and reservation.get("state") == "known":
        axes.append("reservation")
    return _dedupe_preserve(axes)


def _notable_restrictions(
    *,
    weapon_types: Mapping[str, Any],
    legality: Mapping[str, Any],
    stats: Iterable[str],
    fields: Mapping[str, str],
) -> list[dict[str, Any]]:
    restrictions: list[dict[str, Any]] = []
    if weapon_types.get("state") == "known" and weapon_types.get("values"):
        restrictions.append(
            {
                "restriction_id": "weapon_types",
                "restriction_kind": "hard_weapon_requirement",
                "evidence_path": "/hard_requirements/weapon_types",
                "summary": "Pinned skill data provides explicit legal weaponTypes.",
            }
        )
    flags = dict(legality.get("flags") or {})
    if flags.get("native_trap"):
        restrictions.append(
            {
                "restriction_id": "native_trap_delivery",
                "restriction_kind": "native_delivery",
                "evidence_path": "/hard_requirements/legality_flags/flags/native_trap",
                "summary": "Skill is natively trap-delivered in pinned skill data.",
            }
        )
    if flags.get("native_totem"):
        restrictions.append(
            {
                "restriction_id": "native_totem_delivery",
                "restriction_kind": "native_delivery",
                "evidence_path": "/hard_requirements/legality_flags/flags/native_totem",
                "summary": "Skill is natively totem-delivered in pinned skill data.",
            }
        )
    if flags.get("minion"):
        restrictions.append(
            {
                "restriction_id": "minion_ownership",
                "restriction_kind": "minion_skill",
                "evidence_path": "/hard_requirements/legality_flags/flags/minion",
                "summary": "Skill creates or owns minion behavior; support and scaling claims need minion-aware PoB proof.",
            }
        )
    stat_set = set(stats)
    if "skill_cannot_gain_repeat_bonuses" in stat_set:
        restrictions.append(
            {
                "restriction_id": "repeat_bonus_block",
                "restriction_kind": "stat_restriction",
                "evidence_path": "/hard_requirements/stat_ids",
                "summary": "Pinned stat ids include a repeat-bonus restriction.",
            }
        )
    cannot_be_supported = _literal_from_expression(fields.get("cannotBeSupported"))
    if cannot_be_supported is True:
        restrictions.append(
            {
                "restriction_id": "cannot_be_supported",
                "restriction_kind": "support_restriction",
                "evidence_path": "/hard_requirements/raw_fields/cannotBeSupported",
                "summary": "Pinned skill data marks this skill as cannotBeSupported.",
            }
        )
    return restrictions


def _unknowns_or_unsupported_fields(
    *,
    skill_types: Mapping[str, Any],
    base_flags: Mapping[str, Any],
    weapon_types: Mapping[str, Any],
    cost_and_reservation: Mapping[str, Any],
    tag_record: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    unknowns: list[dict[str, Any]] = []
    for field_name, facts in (
        ("skillTypes", skill_types),
        ("baseFlags", base_flags),
        ("weaponTypes", weapon_types),
    ):
        if facts.get("state") == "unknown":
            unknowns.append(
                {
                    "field": field_name,
                    "state": "unknown",
                    "reason": str(facts.get("unsupported_reason") or "No safe extraction available."),
                }
            )
    reservation = cost_and_reservation.get("reservation")
    if isinstance(reservation, Mapping) and reservation.get("state") == "unknown":
        unknowns.append(
            {
                "field": "reservation",
                "state": "unknown",
                "reason": str(reservation.get("unsupported_reason")),
            }
        )
    if tag_record is None:
        unknowns.append(
            {
                "field": "tag_surface",
                "state": "unknown",
                "reason": "No matching committed tag record was found; packet falls back to corpus tags and skillTypes.",
            }
        )
    unknowns.append(
        {
            "field": "full_support_legality",
            "state": "unsupported",
            "reason": "Support compatibility requires PoB support read-back; this packet exposes facts and concerns only.",
        }
    )
    return unknowns


def _support_concerns(legality: Mapping[str, Any]) -> list[dict[str, Any]]:
    flags = dict(legality.get("flags") or {})
    concerns = [
        {
            "concern_id": "full_support_matrix_pending_pob_proof",
            "status": "pending_pob_proof",
            "summary": "Do not infer full support compatibility from tags, name similarity, or this packet alone.",
        }
    ]
    for flag_name in ("native_trap", "native_mine", "native_totem", "minion", "brand"):
        if flags.get(flag_name):
            concerns.append(
                {
                    "concern_id": f"{flag_name}_support_boundary",
                    "status": "pending_pob_proof",
                    "summary": f"{flag_name} changes support legality boundaries; verify selected supports in PoB.",
                }
            )
    return concerns


def _source_refs(
    *,
    definition: SkillDefinition,
    gem_record: GemRecord | None,
    tag_path: Path | None,
) -> list[dict[str, Any]]:
    refs = [
        {
            "ref_id": f"pob.skill_definition.{definition.skill_id}",
            "source_kind": "pinned_pob_skill_definition",
            "locator": _relative_path(definition.source_path),
            "line": definition.source_line,
            "sha256": _sha256_file(definition.source_path),
            "authority_role": "authoritative_skill_fact",
            "summary": "Pinned PoB Data/Skills definition used for skillTypes, baseFlags, weaponTypes, levels, and cost facts.",
        }
    ]
    if gem_record is not None:
        refs.append(
            {
                "ref_id": f"corpus.{gem_record.family}.{gem_record.payload.get('variant_id')}",
                "source_kind": "committed_pob_game_corpus",
                "locator": _relative_path(gem_record.bundle_path),
                "line": None,
                "sha256": _sha256_file(gem_record.bundle_path),
                "authority_role": "authoritative_corpus_fact",
                "summary": "Committed game corpus record used for gem identity, tags, natural max level, and attribute requirements.",
            }
        )
    if tag_path is not None:
        refs.append(
            {
                "ref_id": f"tag_surface.{gem_record.family if gem_record else 'unknown'}",
                "source_kind": "committed_pob_tag_corpus",
                "locator": _relative_path(tag_path),
                "line": None,
                "sha256": _sha256_file(tag_path),
                "authority_role": "derived_tag_fact",
                "summary": "Committed tag corpus record used only as derived search/facet context.",
            }
        )
    return refs


def build_skill_requirements_packet(
    query: str,
    *,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    active_gems_path: Path = DEFAULT_ACTIVE_GEMS_PATH,
    support_gems_path: Path = DEFAULT_SUPPORT_GEMS_PATH,
    active_tags_path: Path = DEFAULT_ACTIVE_TAGS_PATH,
    support_tags_path: Path = DEFAULT_SUPPORT_TAGS_PATH,
) -> dict[str, Any]:
    """Build one schema-facing facts packet for a pinned PoB skill definition."""

    if not isinstance(query, str) or not query.strip():
        _fail("invalid_query", "Skill query must be a non-empty string.")

    definitions = load_skill_definitions(source_root=source_root)
    gem_records = _load_gem_records(active_gems_path, support_gems_path)
    definition, gem_record = _resolve_definition_and_record(
        query,
        definitions=definitions,
        gem_records=gem_records,
    )
    tag_record, tag_path = _find_tag_record(
        gem_record,
        active_tags_path=active_tags_path,
        support_tags_path=support_tags_path,
    )
    fields = definition.fields
    gem_payload = dict(gem_record.payload) if gem_record is not None else {}
    tag_payload = dict(tag_record) if tag_record is not None else {}
    skill_types = _parse_skill_types(fields.get("skillTypes"))
    base_flags = _parse_bool_key_table(fields.get("baseFlags"), absent_reason="baseFlags field is absent.")
    skill_type_values = list(skill_types.get("values", []))
    base_flag_values = list(base_flags.get("values", []))
    is_attack = "Attack" in skill_type_values or "attack" in base_flag_values
    weapon_types = _weapon_type_facts(fields, is_attack=is_attack)
    legality = _legality_flags(skill_type_values, base_flag_values)
    natural_max_level = (
        int(gem_payload["natural_max_level"])
        if isinstance(gem_payload.get("natural_max_level"), int)
        else None
    )
    level_requirements = _level_requirement_facts(fields, natural_max_level=natural_max_level)
    cost_and_reservation = _cost_and_reservation_facts(fields, natural_max_level=natural_max_level)
    stats = _parse_string_stat_ids(fields.get("stats"))
    constant_stats = _parse_string_stat_ids(fields.get("constantStats"))
    quality_stats = _parse_string_stat_ids(fields.get("qualityStats"))
    tag_keys = _sorted_unique(gem_payload.get("tag_keys", []))
    source_context = tag_payload.get("source_context") if isinstance(tag_payload.get("source_context"), dict) else {}

    return {
        "schema_version": POB_SKILL_REQUIREMENTS_SCHEMA_VERSION,
        "record_kind": POB_SKILL_REQUIREMENTS_RECORD_KIND,
        "query": {
            "input": query,
            "normalized": _normalize_key(query),
            "resolution": "pinned_pob_skill_definition",
        },
        "skill_identity": {
            "skill_id": definition.skill_id,
            "variant_id": str(gem_payload.get("variant_id") or definition.skill_id),
            "name": _literal_string(fields, "name") or str(gem_payload.get("name") or definition.skill_id),
            "base_type_name": _literal_string(fields, "baseTypeName")
            or str(gem_payload.get("base_type_name") or gem_payload.get("name") or definition.skill_id),
            "gem_family": gem_record.family if gem_record is not None else "unknown",
            "record_id": gem_payload.get("record_id"),
            "game_id": gem_payload.get("game_id"),
            "granted_effect_id": gem_payload.get("granted_effect_id"),
            "secondary_granted_effect_id": gem_payload.get("secondary_granted_effect_id"),
            "source_file": _relative_path(definition.source_path),
            "source_line": definition.source_line,
        },
        "source_refs": _source_refs(definition=definition, gem_record=gem_record, tag_path=tag_path),
        "hard_requirements": {
            "tags": {
                "state": "known" if tag_keys else "unknown",
                "values": tag_keys,
                "tag_string": gem_payload.get("tag_string"),
            },
            "tag_facets": {
                "state": "known" if tag_record is not None else "unknown",
                "search_tags": tag_payload.get("search_tags", []),
                "scaling_facets": tag_payload.get("scaling_facets", []),
                "source_context": source_context,
            },
            "skill_types": skill_types,
            "base_flags": base_flags,
            "weapon_types": weapon_types,
            "legal_weapon_offhand_families": _derive_offhand_families(weapon_types),
            "legality_flags": legality,
            "requirements": {
                "attributes": {
                    "state": "known" if isinstance(gem_payload.get("required_attributes"), dict) else "unknown",
                    "values": gem_payload.get("required_attributes") or {},
                },
                "levels": level_requirements,
            },
            "cost_and_reservation": cost_and_reservation,
            "stat_ids": _dedupe_preserve([*stats, *constant_stats, *quality_stats]),
            "notable_restrictions": _notable_restrictions(
                weapon_types=weapon_types,
                legality=legality,
                stats=[*stats, *constant_stats, *quality_stats],
                fields=fields,
            ),
        },
        "derived_axes": {
            "possible_delivery_axes": _delivery_axes(skill_type_values, base_flag_values, legality),
            "possible_damage_axes": _damage_axes(skill_type_values, tag_keys),
            "possible_resource_axes": _resource_axes(cost_and_reservation),
            "possible_item_defense_base_families": {
                "state": "not_determined_by_skill_requirements",
                "values": [],
                "reason": "Armour, Evasion, ES, Ward, and hybrid base choices remain branch decisions outside this fact packet.",
            },
        },
        "support_concerns_pending_pob_proof": _support_concerns(legality),
        "unknowns_or_unsupported_fields": _unknowns_or_unsupported_fields(
            skill_types=skill_types,
            base_flags=base_flags,
            weapon_types=weapon_types,
            cost_and_reservation=cost_and_reservation,
            tag_record=tag_record,
        ),
        "forbidden_decision_outputs_absent": {
            "class_selected": False,
            "ascendancy_selected": False,
            "tree_route_selected": False,
            "item_plan_selected": False,
            "support_setup_selected": False,
            "final_build_decision": False,
            "publication_output": False,
        },
        "publication_outputs_absent": True,
    }


def build_validation_set(
    queries: Iterable[str],
    *,
    task_id: str,
) -> dict[str, Any]:
    packets = [build_skill_requirements_packet(query) for query in queries]
    coverage = {
        "spell_packets": [
            packet["skill_identity"]["name"]
            for packet in packets
            if "spell_damage" in packet["derived_axes"]["possible_damage_axes"]
        ],
        "attack_weapon_packets": [
            packet["skill_identity"]["name"]
            for packet in packets
            if packet["hard_requirements"]["weapon_types"]["state"] == "known"
        ],
        "delivery_axes": sorted(
            {
                axis
                for packet in packets
                for axis in packet["derived_axes"]["possible_delivery_axes"]
            }
        ),
        "unknown_or_unsupported_fields": sorted(
            {
                entry["field"]
                for packet in packets
                for entry in packet["unknowns_or_unsupported_fields"]
            }
        ),
    }
    return {
        "schema_version": POB_SKILL_REQUIREMENTS_SCHEMA_VERSION,
        "record_kind": POB_SKILL_REQUIREMENTS_VALIDATION_SET_KIND,
        "task_id": task_id,
        "packet_count": len(packets),
        "coverage": coverage,
        "packets": packets,
        "publication_outputs_absent": all(packet["publication_outputs_absent"] is True for packet in packets),
    }


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m junkroan.pob.skill_requirements")
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_parser = subparsers.add_parser("query", help="Build one skill requirements packet.")
    query_parser.add_argument("skill_query")
    query_parser.set_defaults(handler=_handle_query)

    validation_parser = subparsers.add_parser("validation-set", help="Build a deterministic validation packet set.")
    validation_parser.add_argument("--task-id", required=True)
    validation_parser.add_argument("skill_queries", nargs="+")
    validation_parser.set_defaults(handler=_handle_validation_set)
    return parser


def _handle_query(args: argparse.Namespace) -> dict[str, Any]:
    return build_skill_requirements_packet(args.skill_query)


def _handle_validation_set(args: argparse.Namespace) -> dict[str, Any]:
    return build_validation_set(args.skill_queries, task_id=args.task_id)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except (PoBSkillRequirementsContractError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "POB_SKILL_REQUIREMENTS_RECORD_KIND",
    "POB_SKILL_REQUIREMENTS_SCHEMA_VERSION",
    "POB_SKILL_REQUIREMENTS_VALIDATION_SET_KIND",
    "PoBSkillRequirementsContractError",
    "build_skill_requirements_packet",
    "build_validation_set",
    "load_skill_definitions",
]
