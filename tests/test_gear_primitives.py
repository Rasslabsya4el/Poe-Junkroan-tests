"""Gear primitives against the pinned PoB: legal mod listing, crafting, equipping,
and item trials through the what-if calculator. Skipped without the runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

KEYS = ("CombinedDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist")


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-gear", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


def _ladder(mods: dict, group: str) -> list[dict]:
    return [m for m in mods["mods"] if m["group"] == group]


def test_list_item_mods_gives_legal_ladders_with_weights(pob: PobSession) -> None:
    mods = pob.list_item_mods("Titan Greaves", ilvl=70)
    assert mods["type"] == "Boots" and "str_armour" in mods["base_tags"]
    assert 80 < len(mods["mods"]) < 200
    life = _ladder(mods, "IncreasedLife")
    assert life and life[0]["type"] == "Prefix" and life[0]["level"] <= 70
    assert all(a["level"] >= b["level"] for a, b in zip(life, life[1:]))  # T1 first
    assert all(m["weight"] > 0 for m in mods["mods"])
    assert all(m["level"] <= 70 for m in mods["mods"])
    # boots cannot roll spell damage prefixes
    assert not _ladder(mods, "SpellDamage")
    # regular drop pool only: no delve / essence / influence / synthesis / eldritch mods
    assert not [m["mod_id"] for m in mods["mods"] if any(k in m["mod_id"] for k in ("Delve", "Essence", "Influence", "Maven", "Synth", "Eldritch"))]
    merged = pob.list_item_mods("Titan Greaves", ilvl=70, pool="all")
    assert len(merged["mods"]) > len(mods["mods"])
    # ilvl cap: a lower ilvl removes the top tiers
    low = pob.list_item_mods("Titan Greaves", ilvl=30)
    assert len(_ladder(low, "IncreasedLife")) < len(life)

    with pytest.raises(Exception):
        pob.list_item_mods("Not A Base")


def test_list_bench_mods_annotates_every_pob_craft_row(pob: PobSession) -> None:
    """Every ModMaster row is matched to its current-league unlock recipe or a permissive data gap."""

    corpus = json.loads((PROJECT_ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "items.json").read_text(encoding="utf-8"))
    bases: dict[str, str] = {}
    for record in corpus["records"]:
        if record.get("item_kind") == "base" and record.get("type"):
            bases.setdefault(str(record["type"]), str(record["name"]))
    rows = {
        row["index"]: row
        for base in bases.values()
        for row in pob.list_bench_mods(base, ilvl=84)["mods"]
    }
    assert len(rows) == 732
    assert sum(row["mod_id"] is not None for row in rows.values()) == 716
    assert all(row["unlock"] is not None for row in rows.values())


def test_craft_rare_is_validated_by_pob(pob: PobSession) -> None:
    mods = pob.list_item_mods("Titan Greaves", ilvl=70)
    life = _ladder(mods, "IncreasedLife")[0]["mod_id"]
    fire = _ladder(mods, "FireResistance")[0]["mod_id"]
    cold = _ladder(mods, "ColdResistance")[0]["mod_id"]

    ok = pob.craft_rare("Titan Greaves", prefixes=[life], suffixes=[fire, {"mod_id": cold, "range": 1.0}], ilvl=70, quality=20, sockets="R-R-R-R")
    assert ok["problems"] == [] and ok["unsupported_lines"] == []
    assert len(ok["explicit_lines"]) == 3
    assert ok["raw"].startswith("Rarity: RARE")
    assert "Titan Greaves" in ok["raw"]
    assert any("Cold Resistance" in line for line in ok["explicit_lines"])

    # two mods of one game mod family: the family, not PoB's own group, is what the game forbids
    dup = pob.craft_rare("Titan Greaves", prefixes=[life, "IncreasedLife0"], suffixes=[fire], ilvl=70)
    assert any("duplicate mod family IncreasedLife" in p for p in dup["problems"])
    too_high = pob.craft_rare("Titan Greaves", prefixes=[life], suffixes=[fire], ilvl=20)
    assert any("requires ilvl" in p for p in too_high["problems"])
    wrong_base = pob.craft_rare("Titan Greaves", prefixes=["SpellDamage5"], suffixes=[], ilvl=70)
    assert wrong_base["problems"]


def test_item_trial_matches_real_equip_and_equip_keeps_other_slots(pob: PobSession) -> None:
    before = pob.stats(KEYS)
    mods = pob.list_item_mods("Titan Greaves", ilvl=70)
    life = _ladder(mods, "IncreasedLife")[0]["mod_id"]
    fire = _ladder(mods, "FireResistance")[0]["mod_id"]
    crafted = pob.craft_rare("Titan Greaves", prefixes=[life], suffixes=[fire], ilvl=70, quality=20, sockets="R-R-R-R")

    trial = pob.trial_stats([{"item": {"slot": "Boots", "raw": crafted["raw"]}}], KEYS, mode="fast")[0]
    assert trial["ok"]
    # the build is untouched by a trial
    assert pob.stats(KEYS) == before

    result = pob.equip({"Boots": crafted["raw"]})
    assert result["equipped"][0]["slot"] == "Boots"
    real = pob.stats(KEYS)
    for key in KEYS:
        assert abs(real[key] - trial["stats"][key]) <= 1e-6 * max(1.0, abs(real[key])), key
    # other slots stayed: DPS unchanged by boots without damage mods, resists still capped
    assert real["CombinedDPS"] == before["CombinedDPS"]
    assert real["FireResist"] >= 75

    pob.equip({"Boots": None})
    assert pob.stats(KEYS)["Life"] < real["Life"]
