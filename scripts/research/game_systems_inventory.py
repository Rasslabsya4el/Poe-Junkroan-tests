"""Read-only inventory facts for the pinned Path of Building game-data release.

Run from the repository root:

    python scripts/research/game_systems_inventory.py

The script deliberately reports data surfaces rather than judging availability.
It is the reproducible input for docs/research/2026-09-19-game-systems-inventory.md.
"""

from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "vendor" / "pob" / "source" / "src"
CORPUS = ROOT / "src" / "junkroan" / "pob" / "corpus_data"
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.lua_tables import LuaParseError, parse_lua_assignment_table, parse_lua_local_value, parse_lua_return_value  # noqa: E402


def load_json(name: str) -> dict[str, Any]:
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))


def lua_table(relative: str) -> dict[str, Any] | list[Any]:
    path = SOURCE / relative
    try:
        value = parse_lua_return_value(path.read_text(encoding="utf-8"))
    except LuaParseError as exc:
        raise RuntimeError(f"Could not parse {path.relative_to(ROOT).as_posix()}: {exc}") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError(f"{path.relative_to(ROOT).as_posix()} did not return a table")
    return value


def count(value: dict[str, Any] | list[Any]) -> int:
    return len(value)


def samples(value: dict[str, Any] | list[Any], limit: int = 3) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in list(value)[:limit]]
    return [str(entry) for entry in value[:limit]]


def source_lines(relative: str, pattern: str, limit: int = 3) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE)
    lines = (SOURCE / relative).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if regex.search(line)][:limit]


def table_fact(relative: str) -> dict[str, Any]:
    table = lua_table(relative)
    return {"file": f"vendor/pob/source/src/{relative}", "record_count": count(table), "examples": samples(table)}


def assignment_fact(relative: str, variable: str) -> dict[str, Any]:
    """Count a PoB `var["key"] = ...` data module without evaluating its values."""

    text = (SOURCE / relative).read_text(encoding="utf-8")
    keys = re.findall(rf'^\s*{re.escape(variable)}\["([^"]+)"\]\s*=', text, flags=re.MULTILINE)
    return {
        "file": f"vendor/pob/source/src/{relative}",
        "record_count": len(keys),
        "examples": keys[:3],
        "count_method": f'{variable}["key"] assignments',
    }


def gem_facts() -> dict[str, Any]:
    active = load_json("active_gems.json")["records"]
    supports = load_json("support_gems.json")["records"]
    transfigured = [r for r in active if str(r["variant_id"]).endswith(("AltX", "AltY", "AltZ"))]
    vaal = [r for r in active if r["is_vaal_gem"]]
    awakened = [r for r in supports if str(r["name"]).startswith("Awakened ")]
    exceptional = [r for r in supports if int(r["natural_max_level"] or 0) < 20 and not str(r["name"]).startswith("Awakened ")]
    return {
        "active": {"record_count": len(active), "examples": [r["name"] for r in active[:3]]},
        "support": {"record_count": len(supports), "examples": [r["name"] for r in supports[:3]]},
        "vaal": {"record_count": len(vaal), "examples": [r["name"] for r in vaal[:3]]},
        "transfigured": {"record_count": len(transfigured), "examples": [r["name"] for r in transfigured[:3]]},
        "awakened_support": {"record_count": len(awakened), "examples": [r["name"] for r in awakened[:3]]},
        "other_exceptional_support": {"record_count": len(exceptional), "examples": [r["name"] for r in exceptional[:3]]},
    }


def base_facts() -> dict[str, Any]:
    records = load_json("items.json")["records"]
    groups = Counter(str(r["slot_family"]) for r in records)
    raw_bases: list[tuple[str, dict[str, Any]]] = []
    for path in sorted((SOURCE / "Data" / "Bases").glob("*.lua")):
        for name, payload in parse_lua_assignment_table(path.read_text(encoding="utf-8"), "itemBases").items():
            if isinstance(payload, dict):
                raw_bases.append((name, payload))
    drop_level = [(name, raw.get("dropLevel")) for name, raw in raw_bases if raw.get("dropLevel") is not None]
    socket_limits = [(name, raw.get("socketLimit")) for name, raw in raw_bases if raw.get("socketLimit") is not None]
    influence_tags = Counter(
        str(tag)
        for _, raw in raw_bases
        for tag in (raw.get("influenceTags") or {})
    )
    return {
        "record_count": len(records),
        "by_source_file": dict(sorted(groups.items())),
        "examples": [r["name"] for r in records[:3]],
        "requirements_field": "requirements.level",
        "records_with_drop_level_field": len(drop_level),
        "drop_level_examples": drop_level[:3],
        "records_with_socket_limit_field": len(socket_limits),
        "socket_limit_values": dict(sorted(Counter(value for _, value in socket_limits).items())),
        "influence_tags": dict(sorted(influence_tags.items())),
    }


def unique_facts() -> dict[str, Any]:
    records = load_json("uniques.json")["records"]
    tiers = load_json("unique_tiers.json")["tiers"]
    return {
        "record_count": len(records),
        "availability": dict(sorted(Counter(str(r.get("availability", "")) for r in records).items())),
        "examples": [r["name"] for r in records[:3]],
        "tier_records": len(tiers),
        "tier_examples": list(tiers)[:3],
    }


def enchantment_facts() -> dict[str, Any]:
    files = [
        "Data/EnchantmentBelt.lua",
        "Data/EnchantmentBody.lua",
        "Data/EnchantmentBoots.lua",
        "Data/EnchantmentFlask.lua",
        "Data/EnchantmentGloves.lua",
        "Data/EnchantmentHelmet.lua",
        "Data/EnchantmentWeapon.lua",
    ]
    facts = [table_fact(path) for path in files]
    return {"record_count": sum(f["record_count"] for f in facts), "files": facts}


def nested_table_fact(relative: str, key: str) -> dict[str, Any]:
    table = lua_table(relative)
    nested = table.get(key) if isinstance(table, dict) else None
    if not isinstance(nested, (dict, list)):
        raise RuntimeError(f"{relative} has no table at {key!r}")
    return {"file": f"vendor/pob/source/src/{relative}", "record_count": count(nested), "examples": samples(nested)}


def local_table_fact(relative: str, variable: str) -> dict[str, Any]:
    value = parse_lua_local_value((SOURCE / relative).read_text(encoding="utf-8"), variable)
    if not isinstance(value, (dict, list)):
        raise RuntimeError(f"{relative} {variable} is not a table")
    return {"file": f"vendor/pob/source/src/{relative}", "record_count": count(value), "examples": samples(value)}


def tagged_mod_fact(relative: str, tag: str) -> dict[str, Any]:
    table = lua_table(relative)
    assert isinstance(table, dict)
    matched = [str(key) for key, value in table.items() if isinstance(value, dict) and tag in (value.get("modTags") or [])]
    return {
        "file": f"vendor/pob/source/src/{relative}",
        "record_count": len(matched),
        "examples": matched[:3],
        "mod_tag": tag,
    }


def currency_name_fact(pattern: str) -> dict[str, Any]:
    table = lua_table("Data/CurrencyNames.lua")
    assert isinstance(table, dict)
    regex = re.compile(pattern, re.IGNORECASE)
    names = [str(name) for key, name in table.items() if regex.search(str(key))]
    return {
        "file": "vendor/pob/source/src/Data/CurrencyNames.lua",
        "record_count": len(names),
        "examples": names[:3],
        "key_pattern": pattern,
    }


def build_facts() -> dict[str, Any]:
    manifest = load_json("manifest.json")
    passives = load_json("passives.json")
    masteries = load_json("masteries.json")
    keystones = load_json("keystones.json")
    ascendancies = load_json("ascendancies.json")
    config = load_json("config_surfaces.json")
    return {
        "pinned_pob": {
            "release": manifest["source_lane"]["pinned_ref"],
            "commit": manifest["source_lane"]["pinned_commit"],
            "tree_version": manifest["source_lane"]["tree_version"],
        },
        "committed_corpora": {
            "passives": {"record_count": passives["record_count"], "examples": [r["name"] for r in passives["records"][:3]]},
            "masteries": {"record_count": masteries["record_count"], "examples": [r["mastery_effects"][0]["stats"][0] for r in masteries["records"][:3]]},
            "keystones": {"record_count": keystones["record_count"], "examples": [r["name"] for r in keystones["records"][:3]]},
            "ascendancies": {"record_count": ascendancies["record_count"], "examples": [r["display_name"] for r in ascendancies["records"][:3]]},
            "config_options": {"record_count": config["record_count"], "examples": [r["label"] for r in config["records"][:3]]},
            "gems": gem_facts(),
            "bases": base_facts(),
            "uniques": unique_facts(),
            "bench_mods": {"record_count": load_json("bench_mods.json")["count"], "examples": list(load_json("bench_mods.json")["mods"])[:3]},
        },
        "lua_data_tables": {
            "regular_explicit_modifiers": table_fact("Data/ModExplicit.lua"),
            "minion_tagged_regular_modifiers": tagged_mod_fact("Data/ModExplicit.lua", "minion"),
            "veiled_modifiers": table_fact("Data/ModVeiled.lua"),
            "eldritch_implicit_modifiers": table_fact("Data/ModEldritch.lua"),
            "corruption_implicit_modifiers": table_fact("Data/ModCorrupted.lua"),
            "synthesis_implicit_modifiers": table_fact("Data/ModSynthesis.lua"),
            "delve_modifiers": table_fact("Data/ModDelve.lua"),
            "scourge_modifiers": table_fact("Data/ModScourge.lua"),
            "necropolis_modifiers": table_fact("Data/ModNecropolis.lua"),
            "flask_modifiers": table_fact("Data/ModFlask.lua"),
            "tincture_modifiers": table_fact("Data/ModTincture.lua"),
            "regular_jewel_modifiers": table_fact("Data/ModJewel.lua"),
            "abyss_jewel_modifiers": table_fact("Data/ModJewelAbyss.lua"),
            "cluster_jewel_modifiers": table_fact("Data/ModJewelCluster.lua"),
            "charm_modifiers": table_fact("Data/ModJewelCharm.lua"),
            "foulborn_jewel_modifiers": table_fact("Data/ModFoulborn.lua"),
            "item_exclusive_modifiers": table_fact("Data/ModItemExclusive.lua"),
            "graft_modifiers": table_fact("Data/ModGraft.lua"),
            "essences": table_fact("Data/Essence.lua"),
            "bench_modifiers": table_fact("Data/ModMaster.lua"),
            "beast_crafts": table_fact("Data/BeastCraft.lua"),
            "cluster_jewel_types": nested_table_fact("Data/ClusterJewels.lua", "jewels"),
            "pantheons": table_fact("Data/Pantheons.lua"),
            "tattoos": nested_table_fact("Data/TattooPassives.lua", "nodes"),
            "timeless_jewel_types": local_table_fact("Modules/Data.lua", "data.timelessJewelTypes"),
            "crucible": table_fact("Data/Crucible.lua"),
            "enchantments": enchantment_facts(),
            "catalysts": currency_name_fact(r"CurrencyJewelleryQuality"),
            "oils": currency_name_fact(r"Mushrune"),
            "runegrafts": currency_name_fact(r"Runegraft"),
            "spectres": assignment_fact("Data/Spectres.lua", "minions"),
            "minions": assignment_fact("Data/Minions.lua", "minions"),
        },
        "source_wording": {
            "passive_points": source_lines("Modules/Build.lua", r"Act [0-9].*passive|passive.*points"),
            "ascendancy_points": source_lines("Modules/Build.lua", r"Ascendancy points|ascMax"),
            "bandits": source_lines("Modules/CalcSetup.lua", r"Bandit"),
            "anoints": source_lines("Modules/CalcSetup.lua", r"granted passives|anoint"),
            "timeless": source_lines("Modules/Data.lua", r"timelessJewelTypes|timelessJewelSeed"),
            "tinctures": source_lines("Modules/CalcPerform.lua", r"tincture"),
            "runegrafts": source_lines("Modules/CalcOffence.lua", r"Runegraft"),
        },
    }


def compact_summary(facts: dict[str, Any]) -> str:
    corpora = facts["committed_corpora"]
    tables = facts["lua_data_tables"]
    gems = corpora["gems"]
    bases = corpora["bases"]
    uniques = corpora["uniques"]
    availability = uniques["availability"]
    sockets = bases["socket_limit_values"]
    return "\n".join([
        f"pinned_pob: {facts['pinned_pob']['release'].removeprefix('refs/tags/')} / {facts['pinned_pob']['commit']} / tree {facts['pinned_pob']['tree_version']}",
        f"corpora: passives={corpora['passives']['record_count']} masteries={corpora['masteries']['record_count']} keystones={corpora['keystones']['record_count']} ascendancies={corpora['ascendancies']['record_count']} config={corpora['config_options']['record_count']}",
        f"gems: active={gems['active']['record_count']} support={gems['support']['record_count']} vaal={gems['vaal']['record_count']} transfigured={gems['transfigured']['record_count']} awakened={gems['awakened_support']['record_count']} exceptional={gems['other_exceptional_support']['record_count']}",
        f"bases={bases['record_count']} (socketLimit: 3={sockets[3]}, 4={sockets[4]}, 6={sockets[6]}); base records with dropLevel={bases['records_with_drop_level_field']}",
        f"uniques={uniques['record_count']} (core={availability['core']} boss={availability['boss']} boss_uber={availability['boss_uber']} mechanic={availability['mechanic']} legacy={availability['legacy']} upgrade={availability['upgrade']} vendor={availability['vendor']} other={availability['other']}); wiki-tier records={uniques['tier_records']}",
        f"regular explicit={tables['regular_explicit_modifiers']['record_count']} bench={tables['bench_modifiers']['record_count']} (committed bench index={corpora['bench_mods']['record_count']}) veiled={tables['veiled_modifiers']['record_count']} essence={tables['essences']['record_count']}",
        f"item-exclusive={tables['item_exclusive_modifiers']['record_count']} eldritch={tables['eldritch_implicit_modifiers']['record_count']} synthesis={tables['synthesis_implicit_modifiers']['record_count']} corrupted={tables['corruption_implicit_modifiers']['record_count']} delve={tables['delve_modifiers']['record_count']} scourge={tables['scourge_modifiers']['record_count']} necropolis={tables['necropolis_modifiers']['record_count']} crucible={tables['crucible']['record_count']}",
        f"flask={tables['flask_modifiers']['record_count']} tincture={tables['tincture_modifiers']['record_count']} regular-jewel={tables['regular_jewel_modifiers']['record_count']} abyss-jewel={tables['abyss_jewel_modifiers']['record_count']} cluster-jewel={tables['cluster_jewel_modifiers']['record_count']} charm={tables['charm_modifiers']['record_count']} graft={tables['graft_modifiers']['record_count']} foulborn={tables['foulborn_jewel_modifiers']['record_count']}",
        f"enchantments={tables['enchantments']['record_count']} beastcrafts={tables['beast_crafts']['record_count']} pantheons={tables['pantheons']['record_count']} tattoos={tables['tattoos']['record_count']} timeless-types={tables['timeless_jewel_types']['record_count']}",
        f"spectres={tables['spectres']['record_count']} minions={tables['minions']['record_count']} oils={tables['oils']['record_count']} catalysts={tables['catalysts']['record_count']} runegrafts={tables['runegrafts']['record_count']}",
    ])


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true", help="Print the compact report pasted into the inventory document.")
    args = parser.parse_args()
    facts = build_facts()
    print(compact_summary(facts) if args.summary else json.dumps(facts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
