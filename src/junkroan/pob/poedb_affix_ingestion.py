"""Discover, snapshot, and normalize PoEDB affix data for equipable base items."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

PARSER_VERSION = "op2f10b-poedb-affix-ingestion-v1"
DISCOVERY_SCHEMA_VERSION = "1.0.0"
SNAPSHOT_SCHEMA_VERSION = "1.0.0"
CATALOG_SCHEMA_VERSION = "1.0.0"
CATALOG_ID = "poedb_affix_catalog"
USER_AGENT = "PoeJunkroan-OP2F10B-poedb-affix-ingestion/1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EQUIPPABLE_SLOT_FAMILIES = (
    "amulet",
    "axe",
    "belt",
    "body",
    "boots",
    "bow",
    "claw",
    "dagger",
    "gloves",
    "helmet",
    "mace",
    "quiver",
    "ring",
    "shield",
    "staff",
    "sword",
    "wand",
)
IGNORED_SLOT_FAMILIES = ("flask", "graft", "jewel", "tincture")
MODSVIEW_METADATA_KEYS = frozenset({"baseitem", "gen", "ids", "opt"})


@dataclass(frozen=True)
class BaseItemRecord:
    name: str
    slot_family: str
    type_value: str
    sub_type: str | None
    tags: tuple[str, ...]
    implicit_text: str | None


@dataclass(frozen=True)
class PageSpec:
    page_id: str
    discovery_kind: str
    slot_families: tuple[str, ...] = ()
    type_values: tuple[str, ...] = ()
    sub_types: tuple[str | None, ...] = ()
    base_names: tuple[str, ...] = ()
    notes: str = ""

    @property
    def source_url(self) -> str:
        return f"https://poedb.tw/us/{self.page_id}"

    def matches(self, record: BaseItemRecord) -> bool:
        if self.slot_families and record.slot_family not in self.slot_families:
            return False
        if self.type_values and record.type_value not in self.type_values:
            return False
        if self.sub_types and record.sub_type not in self.sub_types:
            return False
        if self.base_names and record.name not in self.base_names:
            return False
        return True


SHARED_PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec("Rings", "shared", slot_families=("ring",), type_values=("Ring",)),
    PageSpec("Amulets", "shared", slot_families=("amulet",), type_values=("Amulet",)),
    PageSpec("Belts", "shared", slot_families=("belt",), type_values=("Belt",)),
    PageSpec("Quivers", "shared", slot_families=("quiver",), type_values=("Quiver",)),
    PageSpec("Wands", "shared", slot_families=("wand",), type_values=("Wand",)),
    PageSpec("Sceptres", "shared", slot_families=("mace",), type_values=("Sceptre",)),
    PageSpec("Claws", "shared", slot_families=("claw",), type_values=("Claw",)),
    PageSpec("Bows", "shared", slot_families=("bow",), type_values=("Bow",)),
    PageSpec("Daggers", "shared", slot_families=("dagger",), type_values=("Dagger",), sub_types=(None,)),
    PageSpec(
        "Rune_Daggers",
        "shared",
        slot_families=("dagger",),
        type_values=("Dagger",),
        sub_types=("Rune Dagger",),
    ),
    PageSpec(
        "One_Hand_Swords",
        "shared",
        slot_families=("sword",),
        type_values=("One Handed Sword",),
        sub_types=(None,),
    ),
    PageSpec(
        "Thrusting_One_Hand_Swords",
        "shared",
        slot_families=("sword",),
        type_values=("One Handed Sword",),
        sub_types=("Thrusting",),
    ),
    PageSpec("Two_Hand_Swords", "shared", slot_families=("sword",), type_values=("Two Handed Sword",)),
    PageSpec("One_Hand_Axes", "shared", slot_families=("axe",), type_values=("One Handed Axe",)),
    PageSpec("Two_Hand_Axes", "shared", slot_families=("axe",), type_values=("Two Handed Axe",)),
    PageSpec("One_Hand_Maces", "shared", slot_families=("mace",), type_values=("One Handed Mace",)),
    PageSpec("Two_Hand_Maces", "shared", slot_families=("mace",), type_values=("Two Handed Mace",)),
    PageSpec("Staves", "shared", slot_families=("staff",), type_values=("Staff",), sub_types=(None,)),
    PageSpec("Warstaves", "shared", slot_families=("staff",), type_values=("Staff",), sub_types=("Warstaff",)),
    PageSpec("Helmets_str", "shared", slot_families=("helmet",), type_values=("Helmet",), sub_types=("Armour",)),
    PageSpec("Helmets_dex", "shared", slot_families=("helmet",), type_values=("Helmet",), sub_types=("Evasion",)),
    PageSpec(
        "Helmets_int",
        "shared",
        slot_families=("helmet",),
        type_values=("Helmet",),
        sub_types=("Energy Shield",),
    ),
    PageSpec(
        "Helmets_str_dex",
        "shared",
        slot_families=("helmet",),
        type_values=("Helmet",),
        sub_types=("Armour/Evasion",),
    ),
    PageSpec(
        "Helmets_str_int",
        "shared",
        slot_families=("helmet",),
        type_values=("Helmet",),
        sub_types=("Armour/Energy Shield",),
    ),
    PageSpec(
        "Helmets_dex_int",
        "shared",
        slot_families=("helmet",),
        type_values=("Helmet",),
        sub_types=("Evasion/Energy Shield",),
    ),
    PageSpec("Gloves_str", "shared", slot_families=("gloves",), type_values=("Gloves",), sub_types=("Armour",)),
    PageSpec("Gloves_dex", "shared", slot_families=("gloves",), type_values=("Gloves",), sub_types=("Evasion",)),
    PageSpec(
        "Gloves_int",
        "shared",
        slot_families=("gloves",),
        type_values=("Gloves",),
        sub_types=("Energy Shield",),
    ),
    PageSpec(
        "Gloves_str_dex",
        "shared",
        slot_families=("gloves",),
        type_values=("Gloves",),
        sub_types=("Armour/Evasion",),
    ),
    PageSpec(
        "Gloves_str_int",
        "shared",
        slot_families=("gloves",),
        type_values=("Gloves",),
        sub_types=("Armour/Energy Shield",),
    ),
    PageSpec(
        "Gloves_dex_int",
        "shared",
        slot_families=("gloves",),
        type_values=("Gloves",),
        sub_types=("Evasion/Energy Shield",),
    ),
    PageSpec("Boots_str", "shared", slot_families=("boots",), type_values=("Boots",), sub_types=("Armour",)),
    PageSpec("Boots_dex", "shared", slot_families=("boots",), type_values=("Boots",), sub_types=("Evasion",)),
    PageSpec("Boots_int", "shared", slot_families=("boots",), type_values=("Boots",), sub_types=("Energy Shield",)),
    PageSpec(
        "Boots_str_dex",
        "shared",
        slot_families=("boots",),
        type_values=("Boots",),
        sub_types=("Armour/Evasion",),
    ),
    PageSpec(
        "Boots_str_int",
        "shared",
        slot_families=("boots",),
        type_values=("Boots",),
        sub_types=("Armour/Energy Shield",),
    ),
    PageSpec(
        "Boots_dex_int",
        "shared",
        slot_families=("boots",),
        type_values=("Boots",),
        sub_types=("Evasion/Energy Shield",),
    ),
    PageSpec("Body_Armours_str", "shared", slot_families=("body",), type_values=("Body Armour",), sub_types=("Armour",)),
    PageSpec("Body_Armours_dex", "shared", slot_families=("body",), type_values=("Body Armour",), sub_types=("Evasion",)),
    PageSpec(
        "Body_Armours_int",
        "shared",
        slot_families=("body",),
        type_values=("Body Armour",),
        sub_types=("Energy Shield",),
    ),
    PageSpec(
        "Body_Armours_str_dex",
        "shared",
        slot_families=("body",),
        type_values=("Body Armour",),
        sub_types=("Armour/Evasion",),
    ),
    PageSpec(
        "Body_Armours_str_int",
        "shared",
        slot_families=("body",),
        type_values=("Body Armour",),
        sub_types=("Armour/Energy Shield",),
    ),
    PageSpec(
        "Body_Armours_dex_int",
        "shared",
        slot_families=("body",),
        type_values=("Body Armour",),
        sub_types=("Evasion/Energy Shield",),
    ),
    PageSpec(
        "Body_Armours_str_dex_int",
        "shared",
        slot_families=("body",),
        type_values=("Body Armour",),
        sub_types=("Armour/Evasion/Energy Shield",),
    ),
    PageSpec("Shields_str", "shared", slot_families=("shield",), type_values=("Shield",), sub_types=("Armour",)),
    PageSpec("Shields_dex", "shared", slot_families=("shield",), type_values=("Shield",), sub_types=("Evasion",)),
    PageSpec(
        "Shields_int",
        "shared",
        slot_families=("shield",),
        type_values=("Shield",),
        sub_types=("Energy Shield",),
    ),
    PageSpec(
        "Shields_str_dex",
        "shared",
        slot_families=("shield",),
        type_values=("Shield",),
        sub_types=("Armour/Evasion",),
    ),
    PageSpec(
        "Shields_str_int",
        "shared",
        slot_families=("shield",),
        type_values=("Shield",),
        sub_types=("Armour/Energy Shield",),
    ),
    PageSpec(
        "Shields_dex_int",
        "shared",
        slot_families=("shield",),
        type_values=("Shield",),
        sub_types=("Evasion/Energy Shield",),
    ),
)

SPECIAL_PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        "Bone_Ring",
        "special",
        slot_families=("ring",),
        type_values=("Ring",),
        base_names=("Bone Ring",),
        notes="Special implicit ring base with its own PoEDB modifier pool.",
    ),
    PageSpec(
        "Convoking_Wand",
        "special",
        slot_families=("wand",),
        type_values=("Wand",),
        base_names=("Convoking Wand",),
        notes="Minion wand base with its own PoEDB modifier pool.",
    ),
    PageSpec(
        "Bone_Spirit_Shield",
        "special",
        slot_families=("shield",),
        type_values=("Shield",),
        base_names=("Bone Spirit Shield",),
        notes="Minion shield base with its own PoEDB modifier pool.",
    ),
    PageSpec(
        "Runic_Crown",
        "special",
        slot_families=("helmet",),
        type_values=("Helmet",),
        sub_types=("Ward",),
        notes="Representative PoEDB ward helmet page covering all ward helmet bases.",
    ),
    PageSpec(
        "Runic_Gauntlets",
        "special",
        slot_families=("gloves",),
        type_values=("Gloves",),
        sub_types=("Ward",),
        notes="Representative PoEDB ward glove page covering all ward glove bases.",
    ),
    PageSpec(
        "Runic_Sabatons",
        "special",
        slot_families=("boots",),
        type_values=("Boots",),
        sub_types=("Ward",),
        notes="Representative PoEDB ward boot page covering all ward boot bases.",
    ),
)


def default_data_dir() -> Path:
    return Path(__file__).resolve().parent / "mod_data" / "poedb_affix_catalog"


def default_discovery_path() -> Path:
    return default_data_dir() / "discovery.json"


def default_snapshot_dir() -> Path:
    return default_data_dir() / "snapshots"


def default_snapshot_manifest_path() -> Path:
    return default_snapshot_dir() / "manifest.json"


def default_catalog_path() -> Path:
    return default_data_dir() / "catalog.json"


def default_items_corpus_path() -> Path:
    return Path(__file__).resolve().parent / "corpus_data" / "items.json"


def discover_affix_pages(
    *,
    items_corpus_path: Path | None = None,
    discovery_path: Path | None = None,
    fetch_url: Callable[[str], bytes] | None = None,
    generated_at: str | None = None,
) -> Mapping[str, Any]:
    items_corpus_path = (items_corpus_path or default_items_corpus_path()).resolve()
    discovery_path = (discovery_path or default_discovery_path()).resolve()
    generated_at = generated_at or _timestamp()
    base_records = load_base_item_records(items_corpus_path)
    page_entries: list[dict[str, Any]] = []
    covered_base_names: set[str] = set()

    for spec in SHARED_PAGE_SPECS:
        matched = [record for record in base_records if spec.matches(record)]
        if not matched:
            continue
        matched_names = sorted({record.name for record in matched})
        covered_base_names.update(matched_names)
        page_entries.append(_page_entry(spec, matched, has_shared_coverage=True))

    for spec in SPECIAL_PAGE_SPECS:
        matched = [record for record in base_records if spec.matches(record)]
        if not matched:
            continue
        page_entries.append(_page_entry(spec, matched, has_shared_coverage=all(record.name in covered_base_names for record in matched)))
        covered_base_names.update(record.name for record in matched)

    uncovered_records = [
        record
        for record in base_records
        if record.name not in covered_base_names
    ]
    discovery = {
        "record_kind": "poedb_affix_page_discovery",
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": generated_at,
        "scope": {
            "equipable_slot_families": list(EQUIPPABLE_SLOT_FAMILIES),
            "ignored_slot_families": list(IGNORED_SLOT_FAMILIES),
            "items_corpus_path": _relative_path(items_corpus_path),
            "items_corpus_sha256": _sha256_file(items_corpus_path),
            "items_corpus_base_count": len(base_records),
        },
        "pages": sorted(page_entries, key=lambda entry: (entry["discovery_kind"], entry["page_id"])),
        "uncovered_bases": [
            {
                "name": record.name,
                "slot_family": record.slot_family,
                "type": record.type_value,
                "sub_type": record.sub_type,
                "tags": list(record.tags),
                "candidate_page_id": _explicit_special_page_id(record),
                "candidate_reason": _uncovered_reason(record),
            }
            for record in sorted(uncovered_records, key=lambda record: (record.slot_family, record.name))
        ],
        "special_probe_failures": [],
        "coverage_summary": {
            "page_count": len(page_entries),
            "shared_page_count": sum(1 for entry in page_entries if entry["discovery_kind"] == "shared"),
            "special_page_count": sum(1 for entry in page_entries if entry["discovery_kind"] == "special"),
            "covered_base_count": len(covered_base_names),
            "uncovered_base_count": len(uncovered_records),
        },
    }
    _write_json(discovery_path, discovery)
    return discovery


def fetch_snapshots(
    *,
    discovery_path: Path | None = None,
    snapshot_dir: Path | None = None,
    fetch_url: Callable[[str], bytes] | None = None,
    fetched_at: str | None = None,
) -> Mapping[str, Any]:
    discovery_path = (discovery_path or default_discovery_path()).resolve()
    snapshot_dir = (snapshot_dir or default_snapshot_dir()).resolve()
    fetch_url = fetch_url or _fetch_url
    fetched_at = fetched_at or _timestamp()
    discovery = validate_discovery_manifest(discovery_path)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    page_entries: list[dict[str, Any]] = []
    for page in _sequence(discovery.get("pages")):
        if not isinstance(page, Mapping):
            continue
        page_id = _string(page.get("page_id"))
        source_url = _string(page.get("source_url"))
        source_bytes = fetch_url(source_url)
        mods_view = extract_mods_view(source_bytes.decode("utf-8", errors="replace"))
        snapshot = build_snapshot(page, mods_view, source_bytes=source_bytes, fetched_at=fetched_at)
        snapshot_path = snapshot_dir / f"{page_id}.modsview.snapshot.json"
        _write_json(snapshot_path, snapshot)
        page_entries.append(_snapshot_manifest_entry(snapshot_dir, snapshot_path, snapshot))
    manifest = {
        "record_kind": "poedb_affix_snapshot_manifest",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": fetched_at,
        "source_discovery_manifest": {
            "discovery_path": _relative_path(discovery_path),
            "discovery_sha256": _sha256_file(discovery_path),
        },
        "pages": page_entries,
    }
    _write_json(snapshot_dir / "manifest.json", manifest)
    return manifest


def build_snapshot(
    page: Mapping[str, Any],
    mods_view: Mapping[str, Any],
    *,
    source_bytes: bytes,
    fetched_at: str,
) -> Mapping[str, Any]:
    return {
        "record_kind": "poedb_affix_page_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "page_id": _string(page.get("page_id")),
        "discovery_kind": _string(page.get("discovery_kind")),
        "source_url": _string(page.get("source_url")),
        "fetched_at": fetched_at,
        "source_sha256": _sha256_bytes(source_bytes),
        "source_size_bytes": len(source_bytes),
        "coverage": {
            "slot_families": _sorted_strings(page.get("slot_families")),
            "item_types": _sorted_strings(page.get("item_types")),
            "sub_types": _sorted_strings(value for value in _sequence(page.get("sub_types")) if value is not None),
            "matched_base_names": _sorted_strings(page.get("matched_base_names")),
            "matched_base_count": _int_value(page.get("matched_base_count")) or 0,
            "has_shared_coverage": bool(page.get("has_shared_coverage")),
        },
        "mods_view": mods_view,
    }


def validate_discovery_manifest(discovery_path: Path | None = None) -> Mapping[str, Any]:
    discovery_path = (discovery_path or default_discovery_path()).resolve()
    discovery = _load_json(discovery_path)
    if _string(discovery.get("record_kind")) != "poedb_affix_page_discovery":
        raise ValueError(f"{discovery_path} is not a PoEDB affix discovery manifest")
    if _string(discovery.get("parser_version")) != PARSER_VERSION:
        raise ValueError(f"{discovery_path} parser_version does not match {PARSER_VERSION}")
    page_ids: set[str] = set()
    for page in _sequence(discovery.get("pages")):
        if not isinstance(page, Mapping):
            raise ValueError("Discovery manifest contains a non-object page entry")
        page_id = _string(page.get("page_id"))
        if not page_id:
            raise ValueError("Discovery manifest contains an empty page_id")
        if page_id in page_ids:
            raise ValueError(f"Discovery manifest contains duplicate page_id {page_id}")
        page_ids.add(page_id)
        if _string(page.get("source_url")) != f"https://poedb.tw/us/{page_id}":
            raise ValueError(f"Discovery source_url mismatch for {page_id}")
        matched_base_names = _sequence(page.get("matched_base_names"))
        matched_base_count = _int_value(page.get("matched_base_count"))
        if matched_base_count != len(matched_base_names):
            raise ValueError(f"Discovery matched_base_count mismatch for {page_id}")
    return discovery


def validate_snapshot_manifest(manifest_path: Path | None = None) -> Mapping[str, Any]:
    manifest_path = (manifest_path or default_snapshot_manifest_path()).resolve()
    manifest = _load_json(manifest_path)
    if _string(manifest.get("record_kind")) != "poedb_affix_snapshot_manifest":
        raise ValueError(f"{manifest_path} is not a PoEDB affix snapshot manifest")
    if _string(manifest.get("parser_version")) != PARSER_VERSION:
        raise ValueError(f"{manifest_path} parser_version does not match {PARSER_VERSION}")
    discovery_ref = _mapping(manifest.get("source_discovery_manifest"))
    discovery_path = (PROJECT_ROOT / _string(discovery_ref.get("discovery_path"))).resolve()
    discovery = validate_discovery_manifest(discovery_path)
    if _string(discovery_ref.get("discovery_sha256")) != _sha256_file(discovery_path):
        raise ValueError(f"Snapshot manifest discovery hash mismatch: {manifest_path}")
    discovery_pages = {
        _string(page.get("page_id")): page
        for page in _sequence(discovery.get("pages"))
        if isinstance(page, Mapping)
    }
    observed_page_ids: set[str] = set()
    for page in _sequence(manifest.get("pages")):
        if not isinstance(page, Mapping):
            raise ValueError("Snapshot manifest contains a non-object page entry")
        page_id = _string(page.get("page_id"))
        observed_page_ids.add(page_id)
        snapshot_path = manifest_path.parent / _string(page.get("snapshot_path"))
        snapshot = _load_json(snapshot_path)
        if _sha256_file(snapshot_path) != _string(page.get("snapshot_sha256")):
            raise ValueError(f"Snapshot hash mismatch: {snapshot_path}")
        if _string(snapshot.get("parser_version")) != PARSER_VERSION:
            raise ValueError(f"Snapshot parser_version mismatch: {snapshot_path}")
        if page_id not in discovery_pages:
            raise ValueError(f"Snapshot manifest page not present in discovery manifest: {page_id}")
        for key in ("page_id", "discovery_kind", "source_url", "source_sha256", "source_size_bytes"):
            if snapshot.get(key) != page.get(key):
                raise ValueError(f"Snapshot manifest mismatch for {snapshot_path}: {key}")
    expected_page_ids = set(discovery_pages)
    if observed_page_ids != expected_page_ids:
        raise ValueError(f"Snapshot manifest page ids {sorted(observed_page_ids)} != {sorted(expected_page_ids)}")
    return manifest


def generate_catalog_from_snapshot_manifest(manifest_path: Path | None = None) -> Mapping[str, Any]:
    manifest_path = (manifest_path or default_snapshot_manifest_path()).resolve()
    manifest = validate_snapshot_manifest(manifest_path)
    discovery_ref = _mapping(manifest.get("source_discovery_manifest"))
    discovery_path = (PROJECT_ROOT / _string(discovery_ref.get("discovery_path"))).resolve()
    discovery = validate_discovery_manifest(discovery_path)
    discovery_pages = {
        _string(page.get("page_id")): page
        for page in _sequence(discovery.get("pages"))
        if isinstance(page, Mapping)
    }

    pages: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    affixes: list[dict[str, Any]] = []
    for page_entry in _sequence(manifest.get("pages")):
        if not isinstance(page_entry, Mapping):
            continue
        snapshot_path = manifest_path.parent / _string(page_entry.get("snapshot_path"))
        snapshot = _load_json(snapshot_path)
        page_id = _string(snapshot.get("page_id"))
        page_discovery = _mapping(discovery_pages.get(page_id))
        mods_view = _mapping(snapshot.get("mods_view"))
        page_sections: list[dict[str, Any]] = []
        for section_kind, raw_rows in sorted(mods_view.items()):
            if section_kind in MODSVIEW_METADATA_KEYS:
                continue
            rows = [row for row in _sequence(raw_rows) if isinstance(row, Mapping)]
            if not rows:
                continue
            section_entry = {
                "page_id": page_id,
                "section_kind": section_kind,
                "row_count": len(rows),
            }
            sections.append(section_entry)
            page_sections.append(section_entry)
            for position, row in enumerate(rows):
                affixes.append(
                    _normalize_affix_row(
                        page_id=page_id,
                        discovery_kind=_string(snapshot.get("discovery_kind")),
                        section_kind=section_kind,
                        position=position,
                        row=row,
                    )
                )
        pages.append(
            {
                "page_id": page_id,
                "discovery_kind": _string(snapshot.get("discovery_kind")),
                "source_url": _string(snapshot.get("source_url")),
                "slot_families": _sorted_strings(page_discovery.get("slot_families")),
                "item_types": _sorted_strings(page_discovery.get("item_types")),
                "sub_types": _sorted_strings(value for value in _sequence(page_discovery.get("sub_types")) if value is not None),
                "matched_base_names": _sorted_strings(page_discovery.get("matched_base_names")),
                "matched_base_count": _int_value(page_discovery.get("matched_base_count")) or 0,
                "has_shared_coverage": bool(page_discovery.get("has_shared_coverage")),
                "mods_view_metadata": {key: mods_view.get(key) for key in sorted(MODSVIEW_METADATA_KEYS) if key in mods_view},
                "sections": page_sections,
                "snapshot_path": _string(page_entry.get("snapshot_path")),
                "snapshot_sha256": _string(page_entry.get("snapshot_sha256")),
            }
        )
    return {
        "catalog_id": CATALOG_ID,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "generated_at": manifest.get("generated_at"),
        "source_discovery_manifest": {
            "discovery_path": _relative_path(discovery_path),
            "discovery_sha256": _sha256_file(discovery_path),
        },
        "source_snapshot_manifest": {
            "snapshot_manifest_path": _relative_path(manifest_path),
            "snapshot_manifest_sha256": _sha256_file(manifest_path),
        },
        "scope": discovery.get("scope"),
        "coverage_summary": discovery.get("coverage_summary"),
        "pages": pages,
        "affix_sections": sections,
        "affixes": affixes,
        "uncovered_bases": discovery.get("uncovered_bases"),
    }


def write_catalog(
    *,
    manifest_path: Path | None = None,
    catalog_path: Path | None = None,
) -> Mapping[str, Any]:
    catalog_path = (catalog_path or default_catalog_path()).resolve()
    catalog = generate_catalog_from_snapshot_manifest(manifest_path or default_snapshot_manifest_path())
    _write_json(catalog_path, catalog)
    return catalog


def extract_mods_view(page_html: str) -> Mapping[str, Any]:
    marker = "new ModsView("
    marker_index = page_html.index(marker)
    object_start = page_html.index("{", marker_index)
    payload, _ = json.JSONDecoder().raw_decode(page_html[object_start:])
    if not isinstance(payload, Mapping):
        raise ValueError("PoEDB ModsView payload is not an object")
    return payload


def load_base_item_records(items_corpus_path: Path | None = None) -> list[BaseItemRecord]:
    items_corpus_path = (items_corpus_path or default_items_corpus_path()).resolve()
    payload = _load_json(items_corpus_path)
    records: list[BaseItemRecord] = []
    for row in _sequence(payload.get("records")):
        if not isinstance(row, Mapping):
            continue
        if _string(row.get("item_kind")) != "base":
            continue
        slot_family = _string(row.get("slot_family"))
        if slot_family not in EQUIPPABLE_SLOT_FAMILIES:
            continue
        records.append(
            BaseItemRecord(
                name=_string(row.get("name")),
                slot_family=slot_family,
                type_value=_string(row.get("type")),
                sub_type=row.get("sub_type") if isinstance(row.get("sub_type"), str) else None,
                tags=tuple(sorted({tag for tag in _sequence(row.get("tags")) if isinstance(tag, str)})),
                implicit_text=row.get("implicit_text") if isinstance(row.get("implicit_text"), str) else None,
            )
        )
    return sorted(records, key=lambda record: (record.slot_family, record.name))


def _page_entry(spec: PageSpec, records: Sequence[BaseItemRecord], *, has_shared_coverage: bool) -> dict[str, Any]:
    return {
        "page_id": spec.page_id,
        "discovery_kind": spec.discovery_kind,
        "source_url": spec.source_url,
        "slot_families": _sorted_strings(record.slot_family for record in records),
        "item_types": _sorted_strings(record.type_value for record in records),
        "sub_types": sorted({record.sub_type for record in records}, key=lambda value: "" if value is None else value),
        "matched_base_names": _sorted_strings(record.name for record in records),
        "matched_base_count": len({record.name for record in records}),
        "has_shared_coverage": has_shared_coverage,
        "notes": spec.notes,
    }


def _normalize_affix_row(
    *,
    page_id: str,
    discovery_kind: str,
    section_kind: str,
    position: int,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    mapped_keys = {
        "DropChance",
        "Level",
        "ModFamilyList",
        "ModGenerationTypeID",
        "Name",
        "Tier",
        "TierName",
        "adds_no",
        "fossil_no",
        "hover",
        "influence",
        "mod_no",
        "spanClass",
        "spawn_no",
        "str",
        "type",
    }
    affix_id_seed = json.dumps(
        {
            "page_id": page_id,
            "section_kind": section_kind,
            "position": position,
            "row": row,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "affix_id": f"poedb.affix.{hashlib.sha256(affix_id_seed.encode('utf-8')).hexdigest()[:16]}",
        "page_id": page_id,
        "discovery_kind": discovery_kind,
        "section_kind": section_kind,
        "position": position,
        "name": _clean_mod_text(row.get("Name")),
        "text": _clean_mod_text(row.get("str")),
        "affix_type": _affix_type(row.get("ModGenerationTypeID")),
        "mod_generation_type_id": _string(row.get("ModGenerationTypeID")),
        "required_level": _int_value(row.get("Level")),
        "drop_chance": _string(row.get("DropChance")),
        "mod_family_list": _sorted_strings(row.get("ModFamilyList")),
        "source_mod_ref": _string(row.get("hover")),
        "source_mod_id": _string(row.get("mod_no")),
        "spawn_weight": _int_value(row.get("spawn_no")),
        "fossil_weight": _int_value(row.get("fossil_no")),
        "adds_weight": _int_value(row.get("adds_no")),
        "tier": _string(row.get("Tier")),
        "tier_name": _string(row.get("TierName")),
        "row_type": _string(row.get("type")),
        "influence": _string(row.get("influence")),
        "span_class": _string(row.get("spanClass")),
        "extra_fields": {
            key: value
            for key, value in row.items()
            if key not in mapped_keys
        },
    }


def _explicit_special_page_id(record: BaseItemRecord) -> str | None:
    for spec in SPECIAL_PAGE_SPECS:
        if spec.matches(record):
            return spec.page_id
    return None


def _uncovered_reason(record: BaseItemRecord) -> str:
    if _explicit_special_page_id(record):
        return "known_special_page_not_selected"
    if record.sub_type == "Ward":
        return "no_dedicated_modsview_page_in_poedb"
    if record.sub_type == "Talisman":
        return "talisman_modifiers_not_split_into_wearable_modsview_pages"
    if "demigods" in record.tags:
        return "promo_base_without_distinct_modifier_page"
    return "no_matching_supported_modsview_page"


def _fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _snapshot_manifest_entry(snapshot_dir: Path, snapshot_path: Path, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "page_id": snapshot.get("page_id"),
        "discovery_kind": snapshot.get("discovery_kind"),
        "source_url": snapshot.get("source_url"),
        "source_sha256": snapshot.get("source_sha256"),
        "source_size_bytes": snapshot.get("source_size_bytes"),
        "snapshot_path": snapshot_path.relative_to(snapshot_dir).as_posix(),
        "snapshot_sha256": _sha256_file(snapshot_path),
    }


def _clean_mod_text(value: Any) -> str:
    text = _string(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:div|p|li)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<span[^>]+class=[\"']ndash[\"'][^>]*>.*?</span>", "-", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2212", "-")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _affix_type(value: Any) -> str:
    if _string(value) == "1":
        return "prefix"
    if _string(value) == "2":
        return "suffix"
    return "unknown"


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(_stable_json(payload))
    temp_path.replace(path)


def _load_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sorted_strings(values: Any) -> list[str]:
    if isinstance(values, str):
        return [values] if values else []
    if isinstance(values, Mapping):
        return []
    if not isinstance(values, Iterable):
        return []
    return sorted({str(value) for value in values if isinstance(value, str) and value})


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="Discover PoEDB affix pages for equipable items.")
    discover.add_argument("--items-corpus", type=Path, default=default_items_corpus_path())
    discover.add_argument("--output", type=Path, default=default_discovery_path())

    fetch = subparsers.add_parser("fetch", help="Fetch PoEDB ModsView snapshots for discovered pages.")
    fetch.add_argument("--discovery", type=Path, default=default_discovery_path())
    fetch.add_argument("--snapshot-dir", type=Path, default=default_snapshot_dir())

    generate = subparsers.add_parser("generate", help="Generate normalized catalog from committed snapshots.")
    generate.add_argument("--snapshot-manifest", type=Path, default=default_snapshot_manifest_path())
    generate.add_argument("--output", type=Path, default=default_catalog_path())

    validate = subparsers.add_parser("validate", help="Validate discovery, snapshots, and regenerate catalog in memory.")
    validate.add_argument("--discovery", type=Path, default=default_discovery_path())
    validate.add_argument("--snapshot-manifest", type=Path, default=default_snapshot_manifest_path())

    refresh = subparsers.add_parser("refresh", help="Discover, fetch, and generate the catalog in one pass.")
    refresh.add_argument("--items-corpus", type=Path, default=default_items_corpus_path())
    refresh.add_argument("--discovery", type=Path, default=default_discovery_path())
    refresh.add_argument("--snapshot-dir", type=Path, default=default_snapshot_dir())
    refresh.add_argument("--output", type=Path, default=default_catalog_path())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "discover":
        discovery = discover_affix_pages(items_corpus_path=args.items_corpus, discovery_path=args.output)
        print(json.dumps({"status": "discovered", "pages": len(discovery["pages"])}, sort_keys=True))
        return 0
    if args.command == "fetch":
        manifest = fetch_snapshots(discovery_path=args.discovery, snapshot_dir=args.snapshot_dir)
        print(json.dumps({"status": "fetched", "pages": len(manifest["pages"])}, sort_keys=True))
        return 0
    if args.command == "generate":
        catalog = write_catalog(manifest_path=args.snapshot_manifest, catalog_path=args.output)
        print(json.dumps({"status": "generated", "affixes": len(catalog["affixes"])}, sort_keys=True))
        return 0
    if args.command == "validate":
        validate_discovery_manifest(args.discovery)
        catalog = generate_catalog_from_snapshot_manifest(args.snapshot_manifest)
        print(json.dumps({"status": "validated", "affixes": len(catalog["affixes"])}, sort_keys=True))
        return 0
    if args.command == "refresh":
        discovery = discover_affix_pages(items_corpus_path=args.items_corpus, discovery_path=args.discovery)
        fetch_snapshots(discovery_path=args.discovery, snapshot_dir=args.snapshot_dir)
        catalog = write_catalog(manifest_path=args.snapshot_dir / "manifest.json", catalog_path=args.output)
        print(
            json.dumps(
                {"status": "refreshed", "pages": len(discovery["pages"]), "affixes": len(catalog["affixes"])},
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
