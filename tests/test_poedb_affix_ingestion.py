from __future__ import annotations

import json
from pathlib import Path

from junkroan.pob.poedb_affix_ingestion import (
    _sorted_strings,
    discover_affix_pages,
    fetch_snapshots,
    generate_catalog_from_snapshot_manifest,
    validate_snapshot_manifest,
)


def _write_items_corpus(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"records": records}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mods_view_html(payload: dict[str, object]) -> bytes:
    return (
        "<html><body><script>new ModsView("
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + ")</script></body></html>"
    ).encode("utf-8")


def test_sorted_strings_accepts_generators() -> None:
    assert _sorted_strings(value for value in ("wand", "", "ring", "wand")) == ["ring", "wand"]


def test_discover_affix_pages_includes_shared_and_special_equipable_pages(tmp_path: Path) -> None:
    items_corpus = tmp_path / "items.json"
    discovery_path = tmp_path / "discovery.json"
    _write_items_corpus(
        items_corpus,
        [
            {"item_kind": "base", "name": "Gold Ring", "slot_family": "ring", "type": "Ring", "sub_type": None, "tags": []},
            {
                "item_kind": "base",
                "name": "Bone Ring",
                "slot_family": "ring",
                "type": "Ring",
                "sub_type": None,
                "tags": ["minion_modifiers"],
            },
            {
                "item_kind": "base",
                "name": "Convoking Wand",
                "slot_family": "wand",
                "type": "Wand",
                "sub_type": None,
                "tags": ["minion_modifiers"],
            },
            {"item_kind": "base", "name": "Ruby Flask", "slot_family": "flask", "type": "Life Flask", "sub_type": None, "tags": []},
            {"item_kind": "unique", "name": "Ignored Unique", "slot_family": "ring", "type": "Ring", "sub_type": None, "tags": []},
        ],
    )

    def fake_fetcher(url: str) -> bytes:
        page_id = url.rsplit("/", 1)[-1]
        payloads = {
            "Bone_Ring": {"normal": []},
            "Convoking_Wand": {"normal": []},
        }
        return _mods_view_html(payloads[page_id])

    discovery = discover_affix_pages(
        items_corpus_path=items_corpus,
        discovery_path=discovery_path,
        fetch_url=fake_fetcher,
        generated_at="2026-07-22T10:00:00Z",
    )

    assert discovery_path.exists()
    assert discovery["coverage_summary"] == {
        "page_count": 4,
        "shared_page_count": 2,
        "special_page_count": 2,
        "covered_base_count": 3,
        "uncovered_base_count": 0,
    }
    assert {page["page_id"] for page in discovery["pages"]} == {"Rings", "Wands", "Bone_Ring", "Convoking_Wand"}
    assert discovery["special_probe_failures"] == []

    bone_ring_page = next(page for page in discovery["pages"] if page["page_id"] == "Bone_Ring")
    assert bone_ring_page["discovery_kind"] == "special"
    assert bone_ring_page["matched_base_names"] == ["Bone Ring"]
    assert bone_ring_page["has_shared_coverage"] is True


def test_discover_affix_pages_maps_ward_bases_to_representative_special_pages(tmp_path: Path) -> None:
    items_corpus = tmp_path / "items.json"
    discovery_path = tmp_path / "discovery.json"
    _write_items_corpus(
        items_corpus,
        [
            {"item_kind": "base", "name": "Runic Crown", "slot_family": "helmet", "type": "Helmet", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Crest", "slot_family": "helmet", "type": "Helmet", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Helm", "slot_family": "helmet", "type": "Helmet", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Gauntlets", "slot_family": "gloves", "type": "Gloves", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Gages", "slot_family": "gloves", "type": "Gloves", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Gloves", "slot_family": "gloves", "type": "Gloves", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Sabatons", "slot_family": "boots", "type": "Boots", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Greaves", "slot_family": "boots", "type": "Boots", "sub_type": "Ward", "tags": []},
            {"item_kind": "base", "name": "Runic Sollerets", "slot_family": "boots", "type": "Boots", "sub_type": "Ward", "tags": []},
        ],
    )

    def fake_fetcher(url: str) -> bytes:
        page_id = url.rsplit("/", 1)[-1]
        payloads = {
            "Runic_Crown": {"normal": []},
            "Runic_Gauntlets": {"normal": []},
            "Runic_Sabatons": {"normal": []},
        }
        return _mods_view_html(payloads[page_id])

    discovery = discover_affix_pages(
        items_corpus_path=items_corpus,
        discovery_path=discovery_path,
        fetch_url=fake_fetcher,
        generated_at="2026-07-22T10:00:00Z",
    )

    assert discovery["coverage_summary"] == {
        "page_count": 3,
        "shared_page_count": 0,
        "special_page_count": 3,
        "covered_base_count": 9,
        "uncovered_base_count": 0,
    }
    assert {page["page_id"] for page in discovery["pages"]} == {"Runic_Crown", "Runic_Gauntlets", "Runic_Sabatons"}

    runic_crown_page = next(page for page in discovery["pages"] if page["page_id"] == "Runic_Crown")
    assert runic_crown_page["matched_base_names"] == ["Runic Crest", "Runic Crown", "Runic Helm"]

    runic_gauntlets_page = next(page for page in discovery["pages"] if page["page_id"] == "Runic_Gauntlets")
    assert runic_gauntlets_page["matched_base_names"] == ["Runic Gages", "Runic Gauntlets", "Runic Gloves"]

    runic_sabatons_page = next(page for page in discovery["pages"] if page["page_id"] == "Runic_Sabatons")
    assert runic_sabatons_page["matched_base_names"] == ["Runic Greaves", "Runic Sabatons", "Runic Sollerets"]


def test_snapshot_manifest_and_catalog_flatten_all_non_metadata_sections(tmp_path: Path) -> None:
    items_corpus = tmp_path / "items.json"
    discovery_path = tmp_path / "discovery.json"
    snapshot_dir = tmp_path / "snapshots"
    _write_items_corpus(
        items_corpus,
        [
            {"item_kind": "base", "name": "Gold Ring", "slot_family": "ring", "type": "Ring", "sub_type": None, "tags": []},
            {
                "item_kind": "base",
                "name": "Bone Ring",
                "slot_family": "ring",
                "type": "Ring",
                "sub_type": None,
                "tags": ["minion_modifiers"],
            },
        ],
    )

    discovery_fetch_payloads = {
        "Bone_Ring": {"normal": []},
    }

    def discovery_fetcher(url: str) -> bytes:
        return _mods_view_html(discovery_fetch_payloads[url.rsplit("/", 1)[-1]])

    discover_affix_pages(
        items_corpus_path=items_corpus,
        discovery_path=discovery_path,
        fetch_url=discovery_fetcher,
        generated_at="2026-07-22T10:00:00Z",
    )

    snapshot_payloads = {
        "Rings": {
            "baseitem": ["Ring"],
            "gen": {"source": "test"},
            "ids": {"normal": 1},
            "normal": [
                {
                    "Name": "Heavy",
                    "str": "+(20-29) to maximum Life<br>Regenerate 2 Mana per second",
                    "ModGenerationTypeID": "1",
                    "Level": "8",
                    "ModFamilyList": ["maximum_life"],
                    "hover": "https://cdn.poedb.tw/mods/heavy",
                    "mod_no": "100",
                    "spawn_no": "1000",
                    "fossil_no": "1000",
                    "adds_no": "1000",
                    "Tier": "T3",
                    "TierName": "Sanguine",
                    "type": "explicit",
                }
            ],
            "master": [
                {
                    "Name": "FireResistCrafted",
                    "str": "+(16-20)% to Fire Resistance",
                    "ModGenerationTypeID": "2",
                    "Level": "20",
                    "ModFamilyList": ["fire_resistance"],
                    "hover": "https://cdn.poedb.tw/mods/fire_resist_crafted",
                    "mod_no": "200",
                    "spawn_no": "0",
                    "fossil_no": "0",
                    "adds_no": "0",
                    "Tier": "T3",
                    "TierName": "of the Magma",
                    "type": "crafted",
                }
            ],
            "essence": [
                {
                    "Name": "EssenceFlatCold",
                    "str": "Adds (5-8) to (12-16) Cold Damage to Attacks",
                    "ModGenerationTypeID": "1",
                    "Level": "24",
                    "ModFamilyList": ["added_cold_attack"],
                    "hover": "https://cdn.poedb.tw/mods/essence_flat_cold",
                    "mod_no": "300",
                    "spawn_no": "0",
                    "fossil_no": "0",
                    "adds_no": "0",
                    "Tier": "Essence",
                    "TierName": "of Suffering",
                    "type": "essence",
                    "special_tag": "keep-me",
                }
            ],
        },
        "Bone_Ring": {
            "baseitem": ["Bone Ring"],
            "normal": [
                {
                    "Name": "MinionDamage",
                    "str": "Minions deal (10-15)% increased Damage",
                    "ModGenerationTypeID": "1",
                    "Level": "12",
                    "ModFamilyList": ["minion_damage"],
                    "hover": "https://cdn.poedb.tw/mods/minion_damage",
                    "mod_no": "400",
                    "spawn_no": "800",
                    "fossil_no": "800",
                    "adds_no": "800",
                    "Tier": "T2",
                    "TierName": "of the Grave",
                    "type": "explicit",
                }
            ],
        },
    }

    def snapshot_fetcher(url: str) -> bytes:
        return _mods_view_html(snapshot_payloads[url.rsplit("/", 1)[-1]])

    manifest = fetch_snapshots(
        discovery_path=discovery_path,
        snapshot_dir=snapshot_dir,
        fetch_url=snapshot_fetcher,
        fetched_at="2026-07-22T10:05:00Z",
    )

    assert len(manifest["pages"]) == 2
    validated = validate_snapshot_manifest(snapshot_dir / "manifest.json")
    assert validated["record_kind"] == "poedb_affix_snapshot_manifest"

    catalog = generate_catalog_from_snapshot_manifest(snapshot_dir / "manifest.json")

    assert catalog["coverage_summary"]["page_count"] == 2
    assert {page["page_id"] for page in catalog["pages"]} == {"Rings", "Bone_Ring"}
    assert {section["section_kind"] for section in catalog["affix_sections"]} == {"normal", "master", "essence"}
    assert len(catalog["affixes"]) == 4

    rings_page = next(page for page in catalog["pages"] if page["page_id"] == "Rings")
    assert rings_page["slot_families"] == ["ring"]
    assert rings_page["item_types"] == ["Ring"]
    assert rings_page["mods_view_metadata"]["baseitem"] == ["Ring"]

    heavy_life = next(affix for affix in catalog["affixes"] if affix["name"] == "Heavy")
    assert heavy_life["text"] == "+(20-29) to maximum Life\nRegenerate 2 Mana per second"
    assert heavy_life["affix_type"] == "prefix"
    assert heavy_life["required_level"] == 8
    assert heavy_life["spawn_weight"] == 1000

    crafted_fire = next(affix for affix in catalog["affixes"] if affix["name"] == "FireResistCrafted")
    assert crafted_fire["affix_type"] == "suffix"
    assert crafted_fire["section_kind"] == "master"

    essence_row = next(affix for affix in catalog["affixes"] if affix["name"] == "EssenceFlatCold")
    assert essence_row["section_kind"] == "essence"
    assert essence_row["extra_fields"] == {"special_tag": "keep-me"}
