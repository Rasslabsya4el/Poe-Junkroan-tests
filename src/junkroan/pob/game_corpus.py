"""Repo-owned PoB-derived game corpus extraction and loading."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .lua_tables import LuaParseError, parse_lua_assignment_table, parse_lua_local_value, parse_lua_return_value

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "vendor" / "pob" / "source"
DEFAULT_SOURCE_LOCK_PATH = PROJECT_ROOT / "locks" / "pob.source.lock.json"
DEFAULT_CORPUS_ROOT = Path(__file__).with_name("corpus_data")
DEFAULT_MANIFEST_PATH = DEFAULT_CORPUS_ROOT / "manifest.json"
SCHEMA_VERSION = "1.0.0"
CORPUS_ID = "pob_game_corpus"
SOURCE_LANE_ID = "pob_source_lane"

FAMILY_FILE_NAMES = {
    "items": "items.json",
    "active_gems": "active_gems.json",
    "support_gems": "support_gems.json",
    "passives": "passives.json",
    "masteries": "masteries.json",
    "ascendancies": "ascendancies.json",
    "keystones": "keystones.json",
    "config_surfaces": "config_surfaces.json",
}

CONFIG_PREDICATE_FIELDS = (
    "ifCond",
    "ifMinionCond",
    "ifEnemyCond",
    "ifMult",
    "ifEnemyMult",
    "ifEnemyStat",
    "ifTagType",
    "ifMod",
    "ifNode",
    "ifOption",
    "ifCondTrue",
    "ifStat",
    "ifFlag",
    "ifSkill",
    "ifSkillFlag",
    "ifSkillData",
)


class GameCorpusContractError(RuntimeError):
    """Raised when the committed PoB game corpus contract cannot be satisfied."""


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


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


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _normalize_bool_keys(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return sorted(str(key) for key, value in payload.items() if value is True)


def _normalize_text_list(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        if not payload:
            return []
        return [str(value) for _, value in sorted(payload.items(), key=lambda item: str(item[0]))]
    if isinstance(payload, list):
        return [str(item) for item in payload]
    return [str(payload)]


def _normalize_nested_string_lists(payload: Any) -> list[list[str]]:
    if not isinstance(payload, list):
        return []
    normalized: list[list[str]] = []
    for item in payload:
        if isinstance(item, list):
            normalized.append([str(entry) for entry in item])
        else:
            normalized.append([str(item)])
    return normalized


def _maybe_int(value: Any) -> Any:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _normalize_connection_list(payload: Any) -> list[int | str]:
    if not isinstance(payload, list):
        return []
    return [_maybe_int(entry) for entry in payload]


def _normalize_requirement_map(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            normalized[str(key)] = value
        elif isinstance(value, float) and value.is_integer():
            normalized[str(key)] = int(value)
    return normalized


def _literal_from_expression(expression: str) -> Any | None:
    try:
        return parse_lua_return_value(f"return {expression}")
    except LuaParseError:
        return None


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


def _capture_expression(text: str, start: int) -> tuple[str, int]:
    pos = _skip_ignored(text, start)
    expression_start = pos
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
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
            brace_depth += 1
            pos += 1
            continue
        if char == "}":
            if brace_depth == 0 and bracket_depth == 0 and paren_depth == 0:
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
        if char == "," and brace_depth == 0 and bracket_depth == 0 and paren_depth == 0:
            break
        pos += 1
    return text[expression_start:pos].strip(), pos


def _extract_field_expression(block: str, field_name: str) -> str | None:
    match = re.search(rf"\b{re.escape(field_name)}\s*=", block)
    if match is None:
        return None
    expression, _ = _capture_expression(block, match.end())
    return expression or None


def _extract_return_table_blocks(text: str) -> list[str]:
    match = re.search(r"\breturn\s*\{", text)
    if match is None:
        raise GameCorpusContractError("Config options source does not expose a return table.")
    opening_brace = text.find("{", match.start())
    if opening_brace == -1:
        raise GameCorpusContractError("Config options source is missing the top-level opening brace.")

    blocks: list[str] = []
    depth = 0
    block_start: int | None = None
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
            if depth == 2 and block_start is None:
                block_start = pos
            pos += 1
            continue
        if char == "}":
            if depth == 2 and block_start is not None:
                blocks.append(text[block_start : pos + 1])
                block_start = None
            depth -= 1
            pos += 1
            if depth == 0:
                break
            continue
        pos += 1

    if depth != 0:
        raise GameCorpusContractError("Failed to parse config options top-level return table.")
    return blocks


def _discover_latest_tree_version(source_root: Path) -> str:
    game_versions_path = source_root / "src" / "GameVersions.lua"
    if not game_versions_path.is_file():
        raise GameCorpusContractError(f"Missing required upstream source input: {_relative_path(game_versions_path)}")
    tree_versions = parse_lua_local_value(game_versions_path.read_text(encoding="utf-8"), "treeVersionList")
    if not isinstance(tree_versions, list) or not tree_versions:
        raise GameCorpusContractError("GameVersions.lua did not expose a non-empty treeVersionList.")
    latest_tree_version = tree_versions[-1]
    if not isinstance(latest_tree_version, str):
        raise GameCorpusContractError("latest tree version must be a string.")
    return latest_tree_version


def _collect_source_inputs(source_root: Path, tree_version: str) -> list[Path]:
    required_paths = [
        source_root / "src" / "GameVersions.lua",
        source_root / "src" / "Data" / "Gems.lua",
        source_root / "src" / "Modules" / "ConfigOptions.lua",
        source_root / "src" / "Modules" / "ConfigVisibility.lua",
        source_root / "src" / "TreeData" / tree_version / "tree.lua",
    ]
    for path in required_paths:
        if not path.is_file():
            raise GameCorpusContractError(f"Missing required upstream source input: {_relative_path(path)}")

    bases_dir = source_root / "src" / "Data" / "Bases"
    if not bases_dir.is_dir():
        raise GameCorpusContractError(f"Missing required upstream source input directory: {_relative_path(bases_dir)}")
    base_paths = sorted(bases_dir.glob("*.lua"))
    if not base_paths:
        raise GameCorpusContractError("Expected at least one base item source file under vendor/pob/source/src/Data/Bases/.")

    return sorted(required_paths + base_paths)


def collect_game_corpus_source_inputs(source_root: Path = DEFAULT_SOURCE_ROOT) -> list[Path]:
    """Resolve the required upstream inputs for the current corpus contract."""

    tree_version = _discover_latest_tree_version(source_root)
    return _collect_source_inputs(source_root, tree_version)


def _source_input_records(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "source_path": _relative_path(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def _resolve_source_lane_provenance(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    source_lock_path: Path = DEFAULT_SOURCE_LOCK_PATH,
) -> dict[str, Any]:
    payload = _load_json(source_lock_path)
    required_keys = {"lane_id", "repo", "repo_url", "pinned_ref", "pinned_commit", "canonical_path"}
    missing = sorted(required_keys - payload.keys())
    if missing:
        raise GameCorpusContractError(f"Source lock is missing required keys: {', '.join(missing)}")

    expected_root = PROJECT_ROOT / str(payload["canonical_path"])
    if source_root.resolve() != expected_root.resolve():
        raise GameCorpusContractError(
            "PoB game corpus extraction must use the canonical source lane from locks/pob.source.lock.json."
        )
    if not source_root.is_dir():
        raise GameCorpusContractError(f"Canonical source lane is missing: {_relative_path(source_root)}")

    head_result = _run_git("rev-parse", "HEAD", cwd=source_root)
    if head_result.returncode != 0:
        raise GameCorpusContractError(head_result.stderr.strip() or "Failed to read source-lane HEAD.")
    observed_commit = head_result.stdout.strip()
    pinned_commit = str(payload["pinned_commit"])
    if observed_commit != pinned_commit:
        raise GameCorpusContractError(
            f"Source-lane HEAD mismatch: expected {pinned_commit}, observed {observed_commit}."
        )

    dirty_result = _run_git("status", "--short", cwd=source_root)
    if dirty_result.returncode != 0:
        raise GameCorpusContractError(dirty_result.stderr.strip() or "Failed to inspect source-lane status.")
    if dirty_result.stdout.strip():
        raise GameCorpusContractError("Source lane has local modifications; corpus extraction fails closed on dirty upstream input.")

    return {
        "lane_id": str(payload["lane_id"]),
        "canonical_path": _relative_path(source_root),
        "lock_path": _relative_path(source_lock_path),
        "repo": str(payload["repo"]),
        "repo_url": str(payload["repo_url"]),
        "pinned_ref": str(payload["pinned_ref"]),
        "pinned_commit": pinned_commit,
        "observed_commit": observed_commit,
    }


def _build_provenance(
    family_source_paths: list[Path],
    *,
    tree_version: str,
    source_lane: dict[str, Any],
) -> dict[str, Any]:
    return {
        **source_lane,
        "tree_version": tree_version,
        "source_inputs": _source_input_records(sorted(family_source_paths)),
    }


def _normalize_gem_record(record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "name": str(payload["name"]),
        "base_type_name": str(payload.get("baseTypeName", payload["name"])),
        "game_id": str(payload.get("gameId", record_id)),
        "variant_id": str(payload.get("variantId", record_id)),
        "granted_effect_id": str(payload.get("grantedEffectId", "")),
        "secondary_granted_effect_id": str(payload.get("secondaryGrantedEffectId", "")) or None,
        "is_support": bool(payload.get("tags", {}).get("support")),
        "grants_active_skill": bool(payload.get("tags", {}).get("grants_active_skill")),
        "is_vaal_gem": bool(payload.get("vaalGem")),
        "required_attributes": {
            "strength": int(payload.get("reqStr", 0)),
            "dexterity": int(payload.get("reqDex", 0)),
            "intelligence": int(payload.get("reqInt", 0)),
        },
        "natural_max_level": int(payload.get("naturalMaxLevel", 0)),
        "tag_keys": _normalize_bool_keys(payload.get("tags")),
        "tag_string": str(payload.get("tagString", "")),
    }


def _extract_gem_bundles(source_root: Path, *, tree_version: str, source_lane: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gems_path = source_root / "src" / "Data" / "Gems.lua"
    gems_payload = parse_lua_return_value(gems_path.read_text(encoding="utf-8"))
    if not isinstance(gems_payload, dict):
        raise GameCorpusContractError("Gems.lua did not parse into a dictionary surface.")

    active_gems: list[dict[str, Any]] = []
    support_gems: list[dict[str, Any]] = []
    for record_id, raw_payload in sorted(gems_payload.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_payload, dict):
            continue
        record = _normalize_gem_record(str(record_id), raw_payload)
        if record["is_support"]:
            support_gems.append(record)
        else:
            active_gems.append(record)

    active_bundle = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "active_gems",
        "record_count": len(active_gems),
        "provenance": _build_provenance([gems_path], tree_version=tree_version, source_lane=source_lane),
        "records": active_gems,
    }
    support_bundle = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "support_gems",
        "record_count": len(support_gems),
        "provenance": _build_provenance([gems_path], tree_version=tree_version, source_lane=source_lane),
        "records": support_gems,
    }
    return {
        "active_gems": active_bundle,
        "support_gems": support_bundle,
    }


def _extract_item_bundle(source_root: Path, *, tree_version: str, source_lane: dict[str, Any]) -> dict[str, Any]:
    item_records: list[dict[str, Any]] = []
    base_paths = sorted((source_root / "src" / "Data" / "Bases").glob("*.lua"))
    for base_path in base_paths:
        parsed_bases = parse_lua_assignment_table(base_path.read_text(encoding="utf-8"), "itemBases")
        for item_name, raw_payload in sorted(parsed_bases.items()):
            if not isinstance(raw_payload, dict):
                continue
            item_records.append(
                {
                    "name": item_name,
                    "item_kind": "base",
                    "slot_family": base_path.stem,
                    "type": str(raw_payload.get("type", "")),
                    "sub_type": str(raw_payload.get("subType", "")) or None,
                    "tags": _normalize_bool_keys(raw_payload.get("tags")),
                    "influence_tags": {
                        str(key): str(value) for key, value in sorted((raw_payload.get("influenceTags") or {}).items())
                    },
                    "implicit_text": str(raw_payload.get("implicit", "")) or None,
                    "implicit_mod_types": _normalize_nested_string_lists(raw_payload.get("implicitModTypes")),
                    "requirements": _normalize_requirement_map(raw_payload.get("req")),
                    "flavour_text": _normalize_text_list(raw_payload.get("flavourText")),
                    "source_file": _relative_path(base_path),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "items",
        "record_count": len(item_records),
        "provenance": _build_provenance(base_paths, tree_version=tree_version, source_lane=source_lane),
        "metadata": {
            "item_scope": "base_items_only",
            "upstream_lane": "src/Data/Bases/*.lua",
        },
        "records": item_records,
    }


def _normalize_tree_node_record(node_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "skill_id": int(payload.get("skill", node_id)),
        "name": str(payload.get("name", "")),
        "stats": _normalize_text_list(payload.get("stats")),
        "reminder_text": _normalize_text_list(payload.get("reminderText")),
        "flavour_text": _normalize_text_list(payload.get("flavourText")),
        "icon": str(payload.get("icon", "")) or None,
        "group_id": int(payload.get("group", 0)),
        "orbit": int(payload.get("orbit", 0)),
        "orbit_index": int(payload.get("orbitIndex", 0)),
        "incoming_node_ids": _normalize_connection_list(payload.get("in")),
        "outgoing_node_ids": _normalize_connection_list(payload.get("out")),
        "recipe": _normalize_text_list(payload.get("recipe")),
        "class_start_index": int(payload["classStartIndex"]) if "classStartIndex" in payload else None,
        "is_notable": bool(payload.get("isNotable")),
        "is_proxy": bool(payload.get("isProxy")),
        "is_blighted": bool(payload.get("isBlighted")),
        "is_mastery": bool(payload.get("isMastery")),
        "is_keystone": bool(payload.get("isKeystone")),
        "is_ascendancy_start": bool(payload.get("isAscendancyStart")),
        "ascendancy_name": str(payload.get("ascendancyName", "")) or None,
        "expansion_parent": (
            int(payload["expansionJewel"]["parent"])
            if isinstance(payload.get("expansionJewel"), dict) and "parent" in payload["expansionJewel"]
            else None
        ),
        "expansion_size": (
            int(payload["expansionJewel"]["size"])
            if isinstance(payload.get("expansionJewel"), dict) and "size" in payload["expansionJewel"]
            else None
        ),
    }


def _normalize_mastery_effect(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect_id": int(payload.get("effect", 0)),
        "stats": _normalize_text_list(payload.get("stats")),
        "reminder_text": _normalize_text_list(payload.get("reminderText")),
    }


def _extract_tree_bundles(source_root: Path, *, tree_version: str, source_lane: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tree_path = source_root / "src" / "TreeData" / tree_version / "tree.lua"
    tree_payload = parse_lua_return_value(tree_path.read_text(encoding="utf-8"))
    if not isinstance(tree_payload, dict):
        raise GameCorpusContractError(f"{_relative_path(tree_path)} did not parse into a dictionary surface.")

    raw_classes = tree_payload.get("classes")
    raw_alternate_ascendancies = tree_payload.get("alternate_ascendancies", [])
    raw_nodes = tree_payload.get("nodes")
    if not isinstance(raw_classes, list) or not isinstance(raw_nodes, dict):
        raise GameCorpusContractError("Tree data is missing classes or nodes surfaces.")

    ascendancy_metadata: dict[str, dict[str, Any]] = {}
    for raw_class in raw_classes:
        if not isinstance(raw_class, dict):
            continue
        class_name = str(raw_class.get("name", ""))
        for raw_ascendancy in raw_class.get("ascendancies", []):
            if not isinstance(raw_ascendancy, dict):
                continue
            ascendancy_id = str(raw_ascendancy.get("id", ""))
            ascendancy_metadata[ascendancy_id] = {
                "ascendancy_id": ascendancy_id,
                "display_name": str(raw_ascendancy.get("name", ascendancy_id)),
                "class_name": class_name or None,
                "source_kind": "class_ascendancy",
                "flavour_text": _normalize_text_list(raw_ascendancy.get("flavourText")),
            }

    if isinstance(raw_alternate_ascendancies, list):
        for raw_ascendancy in raw_alternate_ascendancies:
            if not isinstance(raw_ascendancy, dict):
                continue
            ascendancy_id = str(raw_ascendancy.get("id", ""))
            ascendancy_metadata[ascendancy_id] = {
                "ascendancy_id": ascendancy_id,
                "display_name": str(raw_ascendancy.get("name", ascendancy_id)),
                "class_name": None,
                "source_kind": "alternate_ascendancy",
                "flavour_text": _normalize_text_list(raw_ascendancy.get("flavourText")),
            }

    passive_records: list[dict[str, Any]] = []
    mastery_records: list[dict[str, Any]] = []
    keystone_records: list[dict[str, Any]] = []
    ascendancy_nodes: dict[str, list[dict[str, Any]]] = {}

    sortable_nodes: list[tuple[int, dict[str, Any]]] = []
    for raw_node_id, raw_node_payload in raw_nodes.items():
        try:
            node_id = int(raw_node_id)
        except (TypeError, ValueError):
            continue
        if not isinstance(raw_node_payload, dict):
            continue
        sortable_nodes.append((node_id, raw_node_payload))

    for node_id, raw_node_payload in sorted(sortable_nodes, key=lambda item: item[0]):
        if not isinstance(raw_node_payload, dict):
            continue
        node_record = _normalize_tree_node_record(node_id, raw_node_payload)

        if node_record["is_mastery"]:
            mastery_record = {
                **node_record,
                "mastery_effects": [
                    _normalize_mastery_effect(effect)
                    for effect in raw_node_payload.get("masteryEffects", [])
                    if isinstance(effect, dict)
                ],
            }
            mastery_records.append(mastery_record)
            continue

        if node_record["ascendancy_name"]:
            ascendancy_nodes.setdefault(str(node_record["ascendancy_name"]), []).append(node_record)
            if node_record["is_keystone"]:
                keystone_records.append(node_record)
            continue

        if node_record["is_keystone"]:
            keystone_records.append(node_record)
            continue

        passive_records.append(node_record)

    ascendancy_records: list[dict[str, Any]] = []
    for ascendancy_id, nodes in sorted(ascendancy_nodes.items()):
        metadata = ascendancy_metadata.get(
            ascendancy_id,
            {
                "ascendancy_id": ascendancy_id,
                "display_name": ascendancy_id,
                "class_name": None,
                "source_kind": "tree_only",
                "flavour_text": [],
            },
        )
        ascendancy_records.append(
            {
                **metadata,
                "node_count": len(nodes),
                "start_node_ids": sorted(
                    node["node_id"] for node in nodes if node.get("is_ascendancy_start")
                ),
                "nodes": nodes,
            }
        )

    provenance = _build_provenance([tree_path], tree_version=tree_version, source_lane=source_lane)
    return {
        "passives": {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": CORPUS_ID,
            "family": "passives",
            "record_count": len(passive_records),
            "provenance": provenance,
            "records": passive_records,
        },
        "masteries": {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": CORPUS_ID,
            "family": "masteries",
            "record_count": len(mastery_records),
            "provenance": provenance,
            "records": mastery_records,
        },
        "ascendancies": {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": CORPUS_ID,
            "family": "ascendancies",
            "record_count": len(ascendancy_records),
            "provenance": provenance,
            "records": ascendancy_records,
        },
        "keystones": {
            "schema_version": SCHEMA_VERSION,
            "corpus_id": CORPUS_ID,
            "family": "keystones",
            "record_count": len(keystone_records),
            "provenance": provenance,
            "records": keystone_records,
        },
    }


def _normalize_predicate_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_maybe_int(entry) for entry in value]
    return _maybe_int(value)


def _normalize_config_choices(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            normalized.append(
                {
                    "value": entry.get("val"),
                    "label": entry.get("label"),
                }
            )
        else:
            normalized.append({"value": entry, "label": str(entry)})
    return normalized


def _extract_config_bundle(source_root: Path, *, tree_version: str, source_lane: dict[str, Any]) -> dict[str, Any]:
    options_path = source_root / "src" / "Modules" / "ConfigOptions.lua"
    visibility_path = source_root / "src" / "Modules" / "ConfigVisibility.lua"
    options_text = options_path.read_text(encoding="utf-8")
    visibility_text = visibility_path.read_text(encoding="utf-8")

    current_section: str | None = None
    current_column: int | None = None
    option_records: list[dict[str, Any]] = []
    for block_index, block in enumerate(_extract_return_table_blocks(options_text), start=1):
        raw_section = _extract_field_expression(block, "section")
        raw_column = _extract_field_expression(block, "col")
        section_value = _literal_from_expression(raw_section) if raw_section is not None else None
        column_value = _literal_from_expression(raw_column) if raw_column is not None else None
        if raw_section is not None and _extract_field_expression(block, "var") is None:
            if isinstance(section_value, str):
                current_section = section_value
            if isinstance(column_value, int):
                current_column = column_value
            continue

        raw_var = _extract_field_expression(block, "var")
        if raw_var is None:
            continue
        var_value = _literal_from_expression(raw_var)
        if not isinstance(var_value, str):
            raise GameCorpusContractError(f"Config option block {block_index} is missing a string var name.")

        predicates: dict[str, Any] = {}
        for field_name in CONFIG_PREDICATE_FIELDS:
            expression = _extract_field_expression(block, field_name)
            if expression is None:
                continue
            literal = _literal_from_expression(expression)
            predicates[field_name] = _normalize_predicate_value(literal if literal is not None else expression)

        list_expression = _extract_field_expression(block, "list")
        list_literal = _literal_from_expression(list_expression) if list_expression is not None else None
        tooltip_expression = _extract_field_expression(block, "tooltip")
        tooltip_literal = _literal_from_expression(tooltip_expression) if tooltip_expression is not None else None
        default_index_literal = _literal_from_expression(_extract_field_expression(block, "defaultIndex") or "")
        default_placeholder_literal = _literal_from_expression(
            _extract_field_expression(block, "defaultPlaceholderState") or ""
        )

        option_records.append(
            {
                "order": block_index,
                "section": current_section,
                "column": current_column,
                "var": var_value,
                "type": _literal_from_expression(_extract_field_expression(block, "type") or "") or None,
                "label": _literal_from_expression(_extract_field_expression(block, "label") or "") or None,
                "default_index": default_index_literal if isinstance(default_index_literal, int) else None,
                "default_placeholder": default_placeholder_literal,
                "predicates": predicates,
                "list_values": _normalize_config_choices(list_literal),
                "list_source": list_expression if list_literal is None and list_expression is not None else None,
                "tooltip_text": str(tooltip_literal) if isinstance(tooltip_literal, str) else None,
                "include_transfigured": bool(_literal_from_expression(_extract_field_expression(block, "includeTransfigured") or "") is True),
                "has_apply_function": "apply = function" in block,
                "has_tooltip_function": "tooltipFunc =" in block or "tooltip = function" in block,
            }
        )

    exclude_keywords = parse_lua_local_value(visibility_text, "EXCLUDE_KEYWORDS")
    simple_predicates = parse_lua_local_value(visibility_text, "SIMPLE_PREDICATES")
    if not isinstance(exclude_keywords, list) or not isinstance(simple_predicates, list):
        raise GameCorpusContractError("Config visibility surface did not expose the expected literal tables.")

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "config_surfaces",
        "record_count": len(option_records),
        "provenance": _build_provenance(
            [options_path, visibility_path],
            tree_version=tree_version,
            source_lane=source_lane,
        ),
        "metadata": {
            "visibility": {
                "exclude_keywords": [str(keyword) for keyword in exclude_keywords],
                "simple_predicates": [
                    {
                        "key": str(predicate.get("key")),
                        "env": str(predicate.get("env")),
                        "can_imply": bool(predicate.get("canImply")),
                    }
                    for predicate in simple_predicates
                    if isinstance(predicate, dict)
                ],
            }
        },
        "records": option_records,
    }


def _build_manifest(
    bundles: dict[str, dict[str, Any]],
    *,
    tree_version: str,
    source_lane: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "source_lane": {
            **source_lane,
            "tree_version": tree_version,
        },
        "families": [
            {
                "family": family,
                "relative_path": _relative_path(output_root / FAMILY_FILE_NAMES[family]),
                "record_count": bundle["record_count"],
                "source_inputs": bundle["provenance"]["source_inputs"],
            }
            for family, bundle in sorted(bundles.items())
        ],
        "downstream_policy": {
            "read_root": _relative_path(output_root),
            "runtime_authority": "vendor/pob/source",
            "consumer_rule": "Downstream agents must read committed corpus bundles instead of reparsing vendor/pob/source.",
            "item_scope": "items family contains base item records from src/Data/Bases/*.lua only.",
        },
    }


def build_game_corpus(
    *,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    source_lock_path: Path = DEFAULT_SOURCE_LOCK_PATH,
    output_root: Path = DEFAULT_CORPUS_ROOT,
) -> Path:
    """Extract the committed PoB game corpus from the pinned source lane."""

    source_lane = _resolve_source_lane_provenance(source_root=source_root, source_lock_path=source_lock_path)
    tree_version = _discover_latest_tree_version(source_root)
    _collect_source_inputs(source_root, tree_version)

    bundles: dict[str, dict[str, Any]] = {}
    bundles["items"] = _extract_item_bundle(source_root, tree_version=tree_version, source_lane=source_lane)
    bundles.update(_extract_gem_bundles(source_root, tree_version=tree_version, source_lane=source_lane))
    bundles.update(_extract_tree_bundles(source_root, tree_version=tree_version, source_lane=source_lane))
    bundles["config_surfaces"] = _extract_config_bundle(
        source_root,
        tree_version=tree_version,
        source_lane=source_lane,
    )

    output_root.mkdir(parents=True, exist_ok=True)
    for family, bundle in bundles.items():
        _write_json(output_root / FAMILY_FILE_NAMES[family], bundle)

    manifest = _build_manifest(bundles, tree_version=tree_version, source_lane=source_lane, output_root=output_root)
    _write_json(output_root / "manifest.json", manifest)
    return output_root / "manifest.json"


def load_game_corpus_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load the committed game corpus manifest."""

    return _load_json(manifest_path)


def load_game_corpus_bundle(family: str, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load one committed game corpus family bundle."""

    if family not in FAMILY_FILE_NAMES:
        raise GameCorpusContractError(f"Unknown game corpus family: {family}")
    bundle_path = manifest_path.parent / FAMILY_FILE_NAMES[family]
    return _load_json(bundle_path)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m junkroan.pob.game_corpus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Materialize the committed PoB game corpus surface.")
    build_parser.add_argument("--output-root", default=str(DEFAULT_CORPUS_ROOT), help="Directory to write corpus bundles into.")
    build_parser.set_defaults(handler=_handle_build)

    show_parser = subparsers.add_parser("show-manifest", help="Show the current committed game corpus manifest.")
    show_parser.set_defaults(handler=_handle_show_manifest)
    return parser


def _handle_build(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = build_game_corpus(output_root=Path(args.output_root))
    return _load_json(manifest_path)


def _handle_show_manifest(_: argparse.Namespace) -> dict[str, Any]:
    return load_game_corpus_manifest()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except (GameCorpusContractError, LuaParseError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
