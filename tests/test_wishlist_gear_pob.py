"""The D79 template filler against the pinned PoB.

Skipped without the runtime. The fixture's own slot, the rails' objective (so the movement
floor and the attribute relations are in), and the three questions that matter: is the item
legal and small, does the base choice answer the attribute the build is short of, and is it
the same item the next time the filler is asked?
"""

from __future__ import annotations

import json
from dataclasses import replace
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.item_bases import bases_of_type, type_of
from junkroan.optimizer.config_rules import derive_config
from junkroan.optimizer.judging import write_lanes
from junkroan.optimizer.loot_gear import RARE_SLOT_ORDER, _affix_counts
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def _base_of_slot(xml: str, slot: str) -> str:
    """The base type the reference wears in that slot (line 3 of PoB's item text)."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    item_id = next(s.get("itemId") for s in items.iter("Slot") if s.get("name") == slot)
    text = next(i.text for i in items.iter("Item") if i.get("id") == item_id)
    return [line.strip() for line in text.splitlines() if line.strip()][2]


def _reset(cold_dot):
    pob, xml = cold_dot
    pob.load_xml(xml)
    return pob, xml


@pytest.fixture(scope="module")
def cold_dot():
    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-wishlist", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(xml)
        yield session, xml


def test_the_wishlist_boots_have_the_fixed_template_shape_and_movement_speed(cold_dot) -> None:
    pob, xml = _reset(cold_dot)
    base = _base_of_slot(xml, "Boots")
    rails = Rails.load()
    objective = rails.objective()  # the rails' own floors: life, the three resists, movement speed
    assert "EffectiveMovementSpeedMod" in objective.floors

    pob.equip({"Boots": None})
    res = WishlistGear(pob, objective, rails).fill_slot("Boots", base)

    # the class is the slot's, the base inside it is the filler's (D73)
    assert res.base in bases_of_type("Boots", max_level=rails.gear.wishlist.area_level)
    assert type_of(res.base) == type_of(base) == "Boots" and res.ilvl == 72  # rails: the authors' pooled median item level
    assert res.rolled == 3  # life, resistance, movement speed
    prefixes, suffixes, _ids = _affix_counts(res.raw)
    assert prefixes <= 3 and suffixes <= 3 and prefixes + suffixes == len(res.affixes)
    assert "Movement Speed" in res.raw, res.raw  # the movement floor is a boots floor (D28)
    assert res.affixes[0].group == "IncreasedLife"
    assert res.affixes[1].group in {"FireResistance", "ColdResistance", "LightningResistance"}


def test_the_same_build_and_base_give_the_same_item_again(cold_dot) -> None:
    pob, xml = _reset(cold_dot)
    base = _base_of_slot(xml, "Boots")
    rails = Rails.load()
    objective = rails.objective()

    pob.equip({"Boots": None})
    first = WishlistGear(pob, objective, rails).fill_slot("Boots", base)
    pob.equip({"Boots": None})
    second = WishlistGear(pob, objective, rails).fill_slot("Boots", base)  # a fresh filler: no incumbent, no cache

    assert first.raw == second.raw
    assert first.base == second.base and first.bases_filled == second.bases_filled
    assert [m.mod_id for m in first.affixes] == [m.mod_id for m in second.affixes]
    assert first.bench_line == second.bench_line


def _fixed_template_rails() -> Rails:
    """The fixed template as constructed: the template v4 move switches (default on since 8a57b1f) are off, as in
    tests/test_wishlist_gear.py::_rails."""

    rails = Rails.load()
    wishlist = replace(rails.gear.wishlist, flexible_lines=False, boots_movement_floor=False)
    return replace(rails, gear=replace(rails.gear, wishlist=wishlist))


def test_cold_dot_template_fill_has_life_everywhere_caps_resists_and_never_uses_all_spell_gem_levels(cold_dot) -> None:
    """D79's real-PoB acceptance: every rare gets its fixed template lines, not only damage."""

    pob, xml = _reset(cold_dot)
    rails = _fixed_template_rails()
    root = ET.fromstring(xml)
    items = root.find("Items")
    by_id = {item.get("id"): item.text or "" for item in items.findall("Item")}
    active = items.get("activeItemSet") or "1"
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    rare_slots = {
        slot.get("name"): [line.strip() for line in by_id[slot.get("itemId")].splitlines() if line.strip()][2]
        for slot in item_set.findall("Slot")
        if slot.get("itemId") in by_id
        and next((line.strip() for line in by_id[slot.get("itemId")].splitlines() if line.strip()), "") == "Rarity: RARE"
        and slot.get("name") in RARE_SLOT_ORDER
    }
    pob.equip({slot: None for slot in rare_slots})
    results = WishlistGear(pob, rails.objective(), rails).fill(rare_slots, passes=1)
    by_slot = {result.slot: result for result in results}

    for result in results:
        print(f"{result.slot}:\n{result.raw}")

    assert all(result.raw for result in results)
    assert all(by_slot[slot].affixes[0].group == "IncreasedLife" for slot in rare_slots if slot not in {"Weapon 1", "Weapon 2"})
    assert all(by_slot[slot].affixes[1].group in {"FireResistance", "ColdResistance", "LightningResistance"}
               for slot in rare_slots if slot not in {"Weapon 1", "Weapon 2"})
    assert "Movement Speed" in by_slot["Boots"].raw
    # D79 rule 1 as moved by d0949dd: the rails' open lines (an open mod may cost two, #428) plus one craft
    weapon = by_slot["Weapon 1"]
    assert sum(m.line_cost for m in weapon.affixes) == rails.gear.wishlist.weapon_open_lines
    assert weapon.rolled == len(weapon.affixes) + 1
    assert "+1 to Level of all Spell Skill Gems" not in by_slot["Weapon 1"].raw
    resists = pob.stats(("FireResist", "ColdResist", "LightningResist"))
    assert all(resists[key] >= 75 for key in resists)


def test_the_amulet_base_is_chosen_for_the_attribute_the_build_is_short_of(cold_dot) -> None:
    """D73 against PoB. cold_dot without its amulet is 6 Dexterity short of what its gems ask
    for (96 against 102), and the amulet implicits are exactly the cheap, certain place that is
    paid from: the filler has to come back with a base whose implicit grants Dexterity, and to
    say in the log which base and which implicit."""

    pob, xml = _reset(cold_dot)
    rails = Rails.load()
    objective = rails.objective()
    assert ("Dex", "ReqDex", 1.0) in objective.relations

    pob.equip({"Amulet": None})
    short = pob.stats(("Dex", "ReqDex"))
    assert short["Dex"] < short["ReqDex"], short  # the fixture's own state, with the amulet off
    lines: list[str] = []

    res = WishlistGear(pob, objective, rails, log=lines.append).fill_slot("Amulet", _base_of_slot(xml, "Amulet"))

    assert res.base in bases_of_type("Amulet", max_level=rails.gear.wishlist.area_level)
    assert "Dexterity" in res.implicit or "all Attributes" in res.implicit, res.implicit
    assert res.after.violation < res.before.violation
    after = pob.stats(("Dex", "ReqDex"))
    assert after["Dex"] >= after["ReqDex"], after  # the implicit paid the requirement
    assert any(f"wishlist template: {res.base} ({res.implicit})" in line for line in lines), lines
    assert sum(1 for m in res.affixes if m.attribute) <= rails.gear.wishlist.attribute_affixes_max


def test_bleed_bow_wishlist_fills_the_bow_before_its_quiver() -> None:
    """The gear-pass-1 state is the skeleton with its conservative lane and no rare items.
    Weapon 1 must restore a main-skill number before the Weapon 2 quiver is equipped."""

    from build_from_skeleton import skeleton_from_xml

    xml = decode_import_code((FIXTURES / "bleed_bow.pob.txt").read_text(encoding="utf-8").strip())
    rails = Rails.load()
    with PobSession(run_id="test-wishlist-bleed-bow", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        skeleton = skeleton_from_xml(xml, pob=pob)
        skeleton.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        pob.equip({slot: None for slot in skeleton.rare_bases})
        pipeline = BuildPipeline(pob, rails)
        write_lanes(pob, skeleton, derive_config(pob, prefer_rules=True), log=pipeline.log)
        gear = WishlistGear(pob, pipeline.objective, rails)

        bow = gear.fill_slot("Weapon 1", skeleton.rare_bases["Weapon 1"], sockets=skeleton.sockets.get("Weapon 1"))
        quiver = gear.fill_slot("Weapon 2", skeleton.rare_bases["Weapon 2"], sockets=skeleton.sockets.get("Weapon 2"))
        stats = pob.stats(("CombinedDPS",))

    assert bow.raw and bow.after.value > 0
    # rails' open lines plus one craft; an open mod costing two lines (#428) takes the place of two
    open_lines = rails.gear.wishlist.weapon_open_lines
    assert sum(m.line_cost for m in bow.affixes) == open_lines and bow.bench is not None
    assert bow.rolled == len(bow.affixes) + 1
    assert quiver.raw
    assert stats["CombinedDPS"] > 0
