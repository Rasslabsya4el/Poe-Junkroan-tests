"""Repo-owned PoB-derived stat/mod family extraction and loading."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from .game_corpus import (
    DEFAULT_MANIFEST_PATH as DEFAULT_GAME_CORPUS_MANIFEST_PATH,
    FAMILY_FILE_NAMES as GAME_FAMILY_FILE_NAMES,
    load_game_corpus_bundle,
    load_game_corpus_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOD_ROOT = Path(__file__).with_name("mod_data")
DEFAULT_MANIFEST_PATH = DEFAULT_MOD_ROOT / "manifest.json"
SCHEMA_VERSION = "1.0.0"
CORPUS_ID = "pob_mod_corpus"
SOURCE_CORPUS_ID = "pob_game_corpus"

SOURCE_FAMILIES = ("items", "passives", "keystones", "masteries")
SURFACE_KINDS = ("item_implicit", "passive_node", "keystone_node", "mastery_effect")
FAMILY_FILE_NAMES = {
    "mod_families": "mod_families.json",
    "stat_families": "stat_families.json",
}

NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:[+-]?(?:\d+(?:\.\d+)?|\.\d+))")
TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
WHITESPACE_RE = re.compile(r"\s+")
OPERATOR_PATTERNS = (
    ("more", re.compile(r"\bmore\b")),
    ("less", re.compile(r"\bless\b")),
    ("increased", re.compile(r"\bincreased\b")),
    ("reduced", re.compile(r"\breduced\b")),
    ("added", re.compile(r"\badds?\b")),
    ("conversion", re.compile(r"\bconvert(?:ed|s)?\b|\bconverted\b")),
    ("chance", re.compile(r"\bchance\b")),
    ("regeneration", re.compile(r"\bregenerate\b")),
    ("recovery", re.compile(r"\brecover\b")),
    ("leech", re.compile(r"\bleech(?:ed)?\b")),
    ("grant", re.compile(r"\bgrants?\b")),
    ("gain", re.compile(r"\bgain(?:s)?\b")),
)
QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "below",
    "by",
    "can",
    "cannot",
    "deal",
    "deals",
    "dealt",
    "do",
    "does",
    "each",
    "enemies",
    "enemy",
    "from",
    "have",
    "if",
    "is",
    "it",
    "of",
    "on",
    "or",
    "per",
    "second",
    "seconds",
    "the",
    "to",
    "up",
    "while",
    "with",
    "you",
    "your",
}
ID_STOPWORDS = QUERY_STOPWORDS | {
    "additional",
    "against",
    "all",
    "damage",
    "effect",
    "for",
    "have",
    "life",
    "mana",
    "maximum",
    "skill",
    "skills",
}


class ModCorpusContractError(RuntimeError):
    """Raised when the committed PoB mod corpus contract cannot be satisfied."""


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


def _text_lines(payload: Any) -> list[str]:
    if payload is None:
        return []
    values = payload if isinstance(payload, list) else [payload]
    lines: list[str] = []
    for value in values:
        text = str(value)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


def _sorted_strings(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _normalize_surface_text(text: str) -> str:
    normalized = str(text).replace("’", "'").replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = NUMBER_RE.sub("#", normalized)
    normalized = re.sub(r"\+\s*(?=#|\()", "", normalized)
    normalized = re.sub(r"#\s*%", "#%", normalized)
    normalized = re.sub(r"\(\s*#\s*\)", "#", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized.strip().lower())
    return normalized


def _query_tokens(*texts: str) -> list[str]:
    tokens: set[str] = set()
    for text in texts:
        for token in TOKEN_RE.findall(_normalize_surface_text(text)):
            if token in QUERY_STOPWORDS:
                continue
            tokens.add(token)
    return sorted(tokens)


def _operator_kind(text: str) -> str:
    normalized = _normalize_surface_text(text)
    for kind, pattern in OPERATOR_PATTERNS:
        if pattern.search(normalized):
            return kind
    if "# to " in normalized or normalized.startswith("to "):
        return "flat"
    return "other"


def _value_shape(text: str) -> str:
    normalized = _normalize_surface_text(text)
    if "#" not in normalized:
        return "none"
    if "# to #" in normalized or "#-#" in normalized:
        return "range_percent" if "#%" in normalized else "range"
    if "#%" in normalized:
        return "percent"
    return "flat"


def _slug_from_tokens(tokens: list[str], *, default: str) -> str:
    slug_tokens = [token.replace("'", "") for token in tokens if token not in ID_STOPWORDS][:6]
    if not slug_tokens:
        slug_tokens = [default]
    return "-".join(slug_tokens)[:64].strip("-") or default


def _family_id(prefix: str, seed: str, tokens: list[str], *, default_slug: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    slug = _slug_from_tokens(tokens, default=default_slug)
    return f"{prefix}.{slug}.{digest}"


def _surface_member_id(source_family: str, surface_kind: str, source_record_id: str, original_texts: list[str]) -> str:
    seed = json.dumps(
        {
            "original_texts": original_texts,
            "source_family": source_family,
            "source_record_id": source_record_id,
            "surface_kind": surface_kind,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"surface.{surface_kind}.{digest}"


def _require_dict(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ModCorpusContractError(f"{label} must be a JSON object.")
    return payload


def _load_source_game_corpus(
    manifest_path: Path = DEFAULT_GAME_CORPUS_MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise ModCorpusContractError(f"Required game corpus manifest is missing: {_relative_path(manifest_path)}")

    manifest = _require_dict(load_game_corpus_manifest(manifest_path=manifest_path), label="game corpus manifest")
    if manifest.get("corpus_id") != SOURCE_CORPUS_ID:
        raise ModCorpusContractError(f"Unsupported source game corpus id: {manifest.get('corpus_id')!r}")

    source_lane = _require_dict(manifest.get("source_lane"), label="game corpus source_lane")
    required_lane_keys = {
        "lane_id",
        "canonical_path",
        "lock_path",
        "repo",
        "repo_url",
        "pinned_ref",
        "pinned_commit",
        "observed_commit",
        "tree_version",
    }
    missing_lane_keys = sorted(required_lane_keys - source_lane.keys())
    if missing_lane_keys:
        raise ModCorpusContractError(f"Game corpus source_lane is missing required keys: {', '.join(missing_lane_keys)}")

    family_summaries = _require_dict(
        {entry["family"]: entry for entry in manifest.get("families", []) if isinstance(entry, dict)},
        label="game corpus families",
    )
    missing_families = sorted(set(SOURCE_FAMILIES) - family_summaries.keys())
    if missing_families:
        raise ModCorpusContractError(
            f"Game corpus manifest is missing required family summaries: {', '.join(missing_families)}"
        )

    bundles: dict[str, dict[str, Any]] = {}
    bundle_inputs: list[dict[str, Any]] = []
    for family in SOURCE_FAMILIES:
        bundle_path = manifest_path.parent / GAME_FAMILY_FILE_NAMES[family]
        if not bundle_path.is_file():
            raise ModCorpusContractError(f"Required game corpus bundle is missing: {_relative_path(bundle_path)}")
        bundle = _require_dict(load_game_corpus_bundle(family, manifest_path=manifest_path), label=f"{family} bundle")
        if bundle.get("family") != family:
            raise ModCorpusContractError(
                f"Game corpus bundle family mismatch for {family}: {bundle.get('family')!r}"
            )
        records = bundle.get("records")
        if not isinstance(records, list):
            raise ModCorpusContractError(f"Game corpus bundle {family} does not expose a records list.")
        if bundle.get("record_count") != len(records):
            raise ModCorpusContractError(f"Game corpus bundle {family} has a record_count mismatch.")

        summary = _require_dict(family_summaries[family], label=f"{family} family summary")
        bundle_inputs.append(
            {
                "family": family,
                "record_count": int(bundle["record_count"]),
                "relative_path": str(summary["relative_path"]),
                "sha256": _sha256_file(bundle_path),
            }
        )
        bundles[family] = bundle

    return {
        "bundle_inputs": bundle_inputs,
        "corpus_id": str(manifest["corpus_id"]),
        "manifest_path": _relative_path(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "schema_version": str(manifest["schema_version"]),
        "source_lane": source_lane,
    }, bundles


def _item_surface_members(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for record in records:
        lines = _text_lines(record.get("implicit_text"))
        if not lines:
            continue
        source_record_id = f"items::{record.get('source_file')}::{record.get('name')}"
        members.append(
            {
                "context": {
                    "implicit_mod_types": record.get("implicit_mod_types", []),
                    "influence_tags": record.get("influence_tags", {}),
                    "item_kind": record.get("item_kind"),
                    "slot_family": record.get("slot_family"),
                    "sub_type": record.get("sub_type"),
                    "tags": record.get("tags", []),
                    "type": record.get("type"),
                },
                "original_texts": lines,
                "reminder_text": [],
                "source_family": "items",
                "source_record_id": source_record_id,
                "source_record_name": str(record.get("name")),
                "surface_kind": "item_implicit",
                "surface_member_id": _surface_member_id("items", "item_implicit", source_record_id, lines),
            }
        )
    return members


def _passive_surface_members(records: list[dict[str, Any]], *, source_family: str, surface_kind: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for record in records:
        lines = _text_lines(record.get("stats"))
        if not lines:
            continue
        source_record_id = f"{source_family}::{record.get('node_id')}"
        members.append(
            {
                "context": {
                    "ascendancy_name": record.get("ascendancy_name"),
                    "class_start_index": record.get("class_start_index"),
                    "is_notable": record.get("is_notable"),
                    "node_id": record.get("node_id"),
                    "recipe": record.get("recipe", []),
                    "skill_id": record.get("skill_id"),
                },
                "original_texts": lines,
                "reminder_text": _text_lines(record.get("reminder_text")),
                "source_family": source_family,
                "source_record_id": source_record_id,
                "source_record_name": str(record.get("name")),
                "surface_kind": surface_kind,
                "surface_member_id": _surface_member_id(source_family, surface_kind, source_record_id, lines),
            }
        )
    return members


def _mastery_surface_members(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for record in records:
        for effect in record.get("mastery_effects", []):
            lines = _text_lines(effect.get("stats"))
            if not lines:
                continue
            effect_id = effect.get("effect_id")
            source_record_id = f"masteries::{record.get('node_id')}::{effect_id}"
            members.append(
                {
                    "context": {
                        "class_start_index": record.get("class_start_index"),
                        "effect_id": effect_id,
                        "mastery_name": record.get("name"),
                        "node_id": record.get("node_id"),
                        "recipe": record.get("recipe", []),
                    },
                    "original_texts": lines,
                    "reminder_text": _text_lines(effect.get("reminder_text")),
                    "source_family": "masteries",
                    "source_record_id": source_record_id,
                    "source_record_name": str(record.get("name")),
                    "surface_kind": "mastery_effect",
                    "surface_member_id": _surface_member_id("masteries", "mastery_effect", source_record_id, lines),
                }
            )
    return members


def _collect_surface_members(game_corpus_bundles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    members.extend(_item_surface_members(game_corpus_bundles["items"]["records"]))
    members.extend(
        _passive_surface_members(
            game_corpus_bundles["passives"]["records"],
            source_family="passives",
            surface_kind="passive_node",
        )
    )
    members.extend(
        _passive_surface_members(
            game_corpus_bundles["keystones"]["records"],
            source_family="keystones",
            surface_kind="keystone_node",
        )
    )
    members.extend(_mastery_surface_members(game_corpus_bundles["masteries"]["records"]))
    if not members:
        raise ModCorpusContractError("No source stat/mod surfaces were discovered in the committed game corpus.")
    return members


def _annotate_surface_members(surface_members: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    stat_metadata: dict[str, dict[str, Any]] = {}
    for member in surface_members:
        line_records: list[dict[str, Any]] = []
        for original_text in member["original_texts"]:
            normalized_text = _normalize_surface_text(original_text)
            metadata = stat_metadata.setdefault(
                normalized_text,
                {
                    "operator_kind": _operator_kind(normalized_text),
                    "query_tokens": _query_tokens(normalized_text),
                    "value_shapes": set(),
                },
            )
            metadata["value_shapes"].add(_value_shape(original_text))
            line_records.append(
                {
                    "normalized_text": normalized_text,
                    "original_text": original_text,
                    "value_shape": _value_shape(original_text),
                }
            )
        member["line_records"] = line_records

    stat_family_lookup: dict[str, dict[str, Any]] = {}
    for normalized_text in sorted(stat_metadata):
        metadata = stat_metadata[normalized_text]
        family_id = _family_id(
            "stat",
            normalized_text,
            metadata["query_tokens"],
            default_slug="family",
        )
        stat_family_lookup[normalized_text] = {
            "family_id": family_id,
            "normalized_text": normalized_text,
            "operator_kind": metadata["operator_kind"],
            "query_tokens": metadata["query_tokens"],
            "value_shapes": sorted(metadata["value_shapes"]),
        }

    for member in surface_members:
        stat_family_ids = [
            stat_family_lookup[line["normalized_text"]]["family_id"]
            for line in member.get("line_records", [])
        ]
        member["stat_family_ids"] = stat_family_ids
    return surface_members, stat_family_lookup


def _build_stat_families_bundle(
    surface_members: list[dict[str, Any]],
    *,
    source_game_corpus: dict[str, Any],
    stat_family_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    accumulators: dict[str, dict[str, Any]] = {}
    for member in surface_members:
        surface_family_ids = member["stat_family_ids"]
        for line_index, line_record in enumerate(member["line_records"]):
            normalized_text = line_record["normalized_text"]
            accumulator = accumulators.setdefault(
                normalized_text,
                {
                    "members": [],
                    "original_texts": set(),
                    "source_families": set(),
                    "surface_kinds": set(),
                    "value_shapes": set(),
                },
            )
            accumulator["members"].append(
                {
                    "context": member["context"],
                    "line_index": line_index,
                    "original_surface_texts": member["original_texts"],
                    "original_text": line_record["original_text"],
                    "reminder_text": member["reminder_text"],
                    "source_family": member["source_family"],
                    "source_record_id": member["source_record_id"],
                    "source_record_name": member["source_record_name"],
                    "surface_kind": member["surface_kind"],
                    "surface_member_id": member["surface_member_id"],
                    "surface_stat_family_ids": surface_family_ids,
                }
            )
            accumulator["original_texts"].add(line_record["original_text"])
            accumulator["source_families"].add(member["source_family"])
            accumulator["surface_kinds"].add(member["surface_kind"])
            accumulator["value_shapes"].add(line_record["value_shape"])

    records: list[dict[str, Any]] = []
    for normalized_text in sorted(accumulators):
        lookup_record = stat_family_lookup[normalized_text]
        accumulator = accumulators[normalized_text]
        records.append(
            {
                "family_id": lookup_record["family_id"],
                "member_count": len(accumulator["members"]),
                "members": accumulator["members"],
                "normalized_text": normalized_text,
                "operator_kind": lookup_record["operator_kind"],
                "original_texts": sorted(accumulator["original_texts"]),
                "query_tokens": lookup_record["query_tokens"],
                "source_families": sorted(accumulator["source_families"]),
                "surface_kinds": sorted(accumulator["surface_kinds"]),
                "value_shapes": sorted(accumulator["value_shapes"]),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "stat_families",
        "record_count": len(records),
        "provenance": source_game_corpus,
        "metadata": {
            "grouping_rule": "Numeric literals are masked and punctuation is normalized per stat line.",
            "source_families": list(SOURCE_FAMILIES),
        },
        "records": records,
    }


def _build_mod_families_bundle(
    surface_members: list[dict[str, Any]],
    *,
    source_game_corpus: dict[str, Any],
    stat_family_bundle: dict[str, Any],
) -> dict[str, Any]:
    stat_lookup = {
        record["family_id"]: {
            "normalized_text": record["normalized_text"],
            "operator_kind": record["operator_kind"],
            "query_tokens": record["query_tokens"],
        }
        for record in stat_family_bundle["records"]
    }
    accumulators: dict[tuple[str, ...], dict[str, Any]] = {}
    for member in surface_members:
        stat_family_ids = tuple(sorted(member["stat_family_ids"]))
        if not stat_family_ids:
            continue
        accumulator = accumulators.setdefault(
            stat_family_ids,
            {
                "members": [],
                "original_surface_examples": set(),
                "source_families": set(),
                "surface_kinds": set(),
            },
        )
        accumulator["members"].append(
            {
                "context": member["context"],
                "original_texts": member["original_texts"],
                "reminder_text": member["reminder_text"],
                "source_family": member["source_family"],
                "source_record_id": member["source_record_id"],
                "source_record_name": member["source_record_name"],
                "stat_family_ids": list(stat_family_ids),
                "surface_kind": member["surface_kind"],
                "surface_member_id": member["surface_member_id"],
            }
        )
        accumulator["original_surface_examples"].add(" || ".join(member["original_texts"]))
        accumulator["source_families"].add(member["source_family"])
        accumulator["surface_kinds"].add(member["surface_kind"])

    records: list[dict[str, Any]] = []
    for stat_family_ids in sorted(accumulators):
        accumulator = accumulators[stat_family_ids]
        normalized_surface_texts = [stat_lookup[family_id]["normalized_text"] for family_id in stat_family_ids]
        query_tokens = _sorted_strings(
            token
            for family_id in stat_family_ids
            for token in stat_lookup[family_id]["query_tokens"]
        )
        records.append(
            {
                "family_id": _family_id(
                    "mod",
                    "||".join(stat_family_ids),
                    query_tokens,
                    default_slug="surface",
                ),
                "member_count": len(accumulator["members"]),
                "members": accumulator["members"],
                "normalized_surface_texts": normalized_surface_texts,
                "operator_kinds": _sorted_strings(
                    stat_lookup[family_id]["operator_kind"] for family_id in stat_family_ids
                ),
                "original_surface_examples": sorted(accumulator["original_surface_examples"]),
                "query_tokens": query_tokens,
                "source_families": sorted(accumulator["source_families"]),
                "stat_family_ids": list(stat_family_ids),
                "surface_kinds": sorted(accumulator["surface_kinds"]),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "family": "mod_families",
        "record_count": len(records),
        "provenance": source_game_corpus,
        "metadata": {
            "grouping_rule": "Full mod surfaces are grouped by their sorted stat_family_ids.",
            "source_families": list(SOURCE_FAMILIES),
        },
        "records": records,
    }


def _build_manifest(
    bundles: dict[str, dict[str, Any]],
    *,
    output_root: Path,
    source_game_corpus: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "source_game_corpus": source_game_corpus,
        "families": [
            {
                "family": family,
                "member_count": sum(len(record["members"]) for record in bundle["records"]),
                "record_count": bundle["record_count"],
                "relative_path": _relative_path(output_root / FAMILY_FILE_NAMES[family]),
                "source_families": bundle["metadata"]["source_families"],
            }
            for family, bundle in sorted(bundles.items())
        ],
        "downstream_policy": {
            "consumer_rule": "Downstream agents must read committed mod-family bundles instead of deriving families ad hoc from the game corpus.",
            "non_goals": [
                "No build ranking.",
                "No craft advice.",
                "No DPS valuation.",
                "No item delta calculation.",
                "No shopping advice.",
            ],
            "read_root": _relative_path(output_root),
            "runtime_authority": "src/junkroan/pob/corpus_data",
        },
    }


def build_mod_corpus(
    *,
    game_corpus_manifest_path: Path = DEFAULT_GAME_CORPUS_MANIFEST_PATH,
    output_root: Path = DEFAULT_MOD_ROOT,
) -> Path:
    """Extract the committed PoB mod/stat family surface from the accepted game corpus."""

    source_game_corpus, game_corpus_bundles = _load_source_game_corpus(game_corpus_manifest_path)
    surface_members = _collect_surface_members(game_corpus_bundles)
    surface_members, stat_family_lookup = _annotate_surface_members(surface_members)

    bundles: dict[str, dict[str, Any]] = {}
    bundles["stat_families"] = _build_stat_families_bundle(
        surface_members,
        source_game_corpus=source_game_corpus,
        stat_family_lookup=stat_family_lookup,
    )
    bundles["mod_families"] = _build_mod_families_bundle(
        surface_members,
        source_game_corpus=source_game_corpus,
        stat_family_bundle=bundles["stat_families"],
    )

    output_root.mkdir(parents=True, exist_ok=True)
    for family, bundle in bundles.items():
        _write_json(output_root / FAMILY_FILE_NAMES[family], bundle)

    manifest = _build_manifest(bundles, output_root=output_root, source_game_corpus=source_game_corpus)
    _write_json(output_root / "manifest.json", manifest)
    return output_root / "manifest.json"


def load_mod_corpus_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load the committed mod/stat family manifest."""

    return _load_json(manifest_path)


def load_mod_corpus_bundle(family: str, manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load one committed mod/stat family bundle."""

    if family not in FAMILY_FILE_NAMES:
        raise ModCorpusContractError(f"Unknown mod corpus family: {family}")
    bundle_path = manifest_path.parent / FAMILY_FILE_NAMES[family]
    return _load_json(bundle_path)


def _query_terms(payload: str | Iterable[str]) -> tuple[list[str], str]:
    if isinstance(payload, str):
        normalized_text = _normalize_surface_text(payload)
        tokens = _query_tokens(payload)
        return tokens, normalized_text
    parts = [str(part) for part in payload if str(part)]
    return _query_tokens(*parts), _normalize_surface_text(" ".join(parts))


def _filter_records(
    records: list[dict[str, Any]],
    *,
    query: str | Iterable[str],
    source_family: str | None,
    surface_kind: str | None,
    text_fields: list[str],
) -> list[dict[str, Any]]:
    query_tokens, normalized_query = _query_terms(query)
    matches: list[dict[str, Any]] = []
    for record in records:
        if source_family is not None and source_family not in record.get("source_families", []):
            continue
        if surface_kind is not None and surface_kind not in record.get("surface_kinds", []):
            continue
        record_tokens = set(record.get("query_tokens", []))
        if query_tokens and not set(query_tokens).issubset(record_tokens):
            searchable = " ".join(str(record.get(field, "")) for field in text_fields)
            if normalized_query not in _normalize_surface_text(searchable):
                continue
        matches.append(record)
    return matches


def query_stat_families(
    query: str | Iterable[str],
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    source_family: str | None = None,
    surface_kind: str | None = None,
) -> list[dict[str, Any]]:
    """Query committed stat families by token overlap."""

    bundle = load_mod_corpus_bundle("stat_families", manifest_path=manifest_path)
    return _filter_records(
        bundle["records"],
        query=query,
        source_family=source_family,
        surface_kind=surface_kind,
        text_fields=["normalized_text", "original_texts"],
    )


def query_mod_families(
    query: str | Iterable[str],
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    source_family: str | None = None,
    surface_kind: str | None = None,
) -> list[dict[str, Any]]:
    """Query committed mod families by token overlap."""

    bundle = load_mod_corpus_bundle("mod_families", manifest_path=manifest_path)
    return _filter_records(
        bundle["records"],
        query=query,
        source_family=source_family,
        surface_kind=surface_kind,
        text_fields=["normalized_surface_texts", "original_surface_examples"],
    )


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m junkroan.pob.mod_corpus")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Materialize the committed PoB mod/stat family surface.")
    build_parser.add_argument("--output-root", default=str(DEFAULT_MOD_ROOT), help="Directory to write mod bundles into.")
    build_parser.add_argument(
        "--game-corpus-manifest",
        default=str(DEFAULT_GAME_CORPUS_MANIFEST_PATH),
        help="Path to the accepted game corpus manifest.",
    )
    build_parser.set_defaults(handler=_handle_build)

    show_parser = subparsers.add_parser("show-manifest", help="Show the current committed mod/stat family manifest.")
    show_parser.set_defaults(handler=_handle_show_manifest)

    query_parser = subparsers.add_parser("query", help="Query one committed mod/stat family bundle.")
    query_parser.add_argument("family", choices=sorted(FAMILY_FILE_NAMES))
    query_parser.add_argument("terms", nargs="+", help="Query terms matched against query_tokens and normalized text.")
    query_parser.add_argument("--source-family", choices=SOURCE_FAMILIES)
    query_parser.add_argument("--surface-kind", choices=SURFACE_KINDS)
    query_parser.set_defaults(handler=_handle_query)
    return parser


def _handle_build(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = build_mod_corpus(
        game_corpus_manifest_path=Path(args.game_corpus_manifest),
        output_root=Path(args.output_root),
    )
    return _load_json(manifest_path)


def _handle_show_manifest(_: argparse.Namespace) -> dict[str, Any]:
    return load_mod_corpus_manifest()


def _handle_query(args: argparse.Namespace) -> dict[str, Any]:
    if args.family == "stat_families":
        records = query_stat_families(
            args.terms,
            source_family=args.source_family,
            surface_kind=args.surface_kind,
        )
    else:
        records = query_mod_families(
            args.terms,
            source_family=args.source_family,
            surface_kind=args.surface_kind,
        )
    return {
        "family": args.family,
        "match_count": len(records),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except (ModCorpusContractError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
