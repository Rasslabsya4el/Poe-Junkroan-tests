"""#1169 unit 2: the audit names three more error kinds of the 16.10 reading, each by the rail's own predicate.

3. `weapon-all-gems-level`: a day-1 Weapon 1 / Weapon 2 rare with "+1 to Level of all Spell Skill Gems" (or "Skill Gems"); the rail
   `weapon_forbidden_lines` through `weapon_all_gems_raw` (#1152). Day 1 only (`rails.loadout == "day1"`).
4. `base-excluded-by-loadout`: a worn item whose base is in `rails.excluded_bases` (`bases_excluded_by_loadout`, #1154): Prismatic
   Ring before endgame. Nothing in the endgame loadout.
5. `shield-gem-level-with-other`: a rare Weapon 2 Shield with a gem-level line AND another mod (`is_shield_gem_level_with_other`, #601).

Read builds with the error (decode doc docs/research/2026-10-16-reading-7-builds-decode.md): check 3 B1 Weapon 1 (Demon Dagger,
"+1 to Level of all Spell Skill Gems"); check 4 A1 Ring 1, B1 Ring 2, C1 Ring 2 (Prismatic Ring); check 5 A1 and B1 Weapon 2
(Titanium Spirit Shield with a gem-level line and other mods). A1 has only Chaos-level gem lines, so check 3 is absent on A1.
The without-cases are minimal edits of a read build (the item of one slot changed, the edit asserted to have happened).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.audit import audit_xml
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import decode_import_code

ROOT = Path(__file__).resolve().parents[1]
A1 = ROOT / "artifacts/search-contagion/20261015-0336/01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
B1 = ROOT / "artifacts/search-searing_bond/20261015-0004/01 templar_inquisitor_demon_dagger.pob.txt"
C1 = ROOT / "artifacts/search-armageddon_brand/20261014-2358/01 templar_hierophant_demon_dagger.pob.txt"
needs_artifacts = pytest.mark.skipif(not (A1.exists() and B1.exists() and C1.exists()), reason="16.10 read builds not linked")

ALL_GEMS = "weapon-all-gems-level"
EXCLUDED = "base-excluded-by-loadout"
SHIELD = "shield-gem-level-with-other"
CHAOS_GEM_LINE = "+1 to Level of all Chaos Spell Skill Gems"


def _load(path: Path) -> str:
    return decode_import_code(path.read_text(encoding="utf-8").strip())


def _kind(findings, check):
    return [f for f in findings if f.check == check]


def _rails(loadout: str) -> Rails:
    return Rails.load(loadout=loadout)


def _edit_item(xml: str, slot: str, edit: Callable[[str], str]) -> str:
    """The XML with the item of `slot` (active ItemSet) rewritten by `edit`; the caller asserts the edit took effect."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    iset = next(s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1"))
    item_id = next(s.get("itemId") for s in iset.findall("Slot") if s.get("name") == slot)
    item = next(i for i in items.findall("Item") if i.get("id") == item_id)
    item.text = edit(item.text or "")
    return ET.tostring(root, encoding="unicode")


# ---- 3: a day-1 weapon with a forbidden gem-level line ------------------------------------------------------------------

@needs_artifacts
def test_check3_b1_demon_dagger_carries_the_all_spell_gems_line() -> None:
    found = _kind(audit_xml(_load(B1), _rails("day1")), ALL_GEMS)
    assert len(found) == 1 and found[0].severity == "error"
    assert "Weapon 1" in found[0].detail and "Demon Dagger" in found[0].detail
    assert "+1 to Level of all Spell Skill Gems" in found[0].detail and "gear.weapon_forbidden_lines" in found[0].detail


@needs_artifacts
def test_check3_a1_has_only_chaos_gem_lines_so_no_finding() -> None:
    """"+1 to Level of all Chaos Spell Skill Gems" is a per-element line, allowed on day 1 (#1152)."""

    assert _kind(audit_xml(_load(A1), _rails("day1")), ALL_GEMS) == []


@needs_artifacts
def test_check3_does_not_apply_outside_day_1() -> None:
    """The rail is a day-1 rule: the same B1 weapon is not judged on the endgame loadout."""

    assert _kind(audit_xml(_load(B1), _rails("endgame")), ALL_GEMS) == []


@needs_artifacts
def test_check3_a_line_the_request_forces_on_that_weapon_is_the_only_exemption() -> None:
    """The rail's `unforced_forbidden`: B1's Weapon 1 line is not an error when the request forced it there, still one on another slot."""

    forced_here = {"Weapon 1": ["+1 to Level of all Spell Skill Gems"]}
    assert _kind(audit_xml(_load(B1), _rails("day1"), forced_here), ALL_GEMS) == []
    assert len(_kind(audit_xml(_load(B1), _rails("day1"), {"Weapon 2": forced_here["Weapon 1"]}), ALL_GEMS)) == 1


@needs_artifacts
def test_check3_the_forbidden_line_is_a_whole_match() -> None:
    """A line that differs only by an element word stays allowed: the B1 edit to "Fire" is the allowed sibling."""

    xml = _edit_item(_load(B1), "Weapon 1", lambda t: t.replace("+1 to Level of all Spell Skill Gems", "+1 to Level of all Fire Spell Skill Gems"))
    assert _kind(audit_xml(xml, _rails("day1")), ALL_GEMS) == []


# ---- 4: a base the loadout excludes (Prismatic Ring before endgame) -----------------------------------------------------

@needs_artifacts
@pytest.mark.parametrize("path, slot", [(A1, "Ring 1"), (B1, "Ring 2"), (C1, "Ring 2")])
def test_check4_prismatic_ring_is_excluded_before_endgame(path: Path, slot: str) -> None:
    found = _kind(audit_xml(_load(path), _rails("day1")), EXCLUDED)
    assert len(found) == 1 and found[0].severity == "error"
    assert "Prismatic Ring" in found[0].detail and slot in found[0].detail and "before endgame" in found[0].detail


@needs_artifacts
def test_check4_the_same_base_under_another_name_has_no_finding() -> None:
    xml = _edit_item(_load(A1), "Ring 1", lambda t: t.replace("Prismatic Ring", "Amethyst Ring"))
    assert _kind(audit_xml(xml, _rails("day1")), EXCLUDED) == []


@needs_artifacts
def test_check4_does_not_apply_on_the_endgame_loadout() -> None:
    assert _kind(audit_xml(_load(A1), _rails("endgame")), EXCLUDED) == []


# ---- 5: a rare Shield with a gem-level line AND another mod -------------------------------------------------------------

@needs_artifacts
@pytest.mark.parametrize("path", [A1, B1])
def test_check5_the_read_shields_carry_a_gem_line_with_other_mods(path: Path) -> None:
    found = _kind(audit_xml(_load(path), _rails("day1")), SHIELD)
    assert len(found) == 1 and found[0].severity == "error"
    assert "Weapon 2" in found[0].detail and "Titanium Spirit Shield" in found[0].detail
    assert "Level of all" in found[0].detail and "Resistance" in found[0].detail  # the gem line and another mod of the shield


@needs_artifacts
def test_check5_a_shield_with_the_gem_line_alone_has_no_finding() -> None:
    """The gem line takes the whole shield only with another mod: A1's shield without its Elemental Resistance and Mana Regeneration lines."""

    def only_gem_line(text: str) -> str:
        return "\n".join(ln for ln in text.splitlines() if "Resistance" not in ln and "Regeneration" not in ln)

    xml = _edit_item(_load(A1), "Weapon 2", only_gem_line)
    assert _kind(audit_xml(xml, _rails("day1")), SHIELD) == []


@needs_artifacts
def test_check5_a_shield_without_a_gem_line_has_no_finding() -> None:
    xml = _edit_item(_load(A1), "Weapon 2", lambda t: t.replace(CHAOS_GEM_LINE, "+1 to Dexterity"))
    assert _kind(audit_xml(xml, _rails("day1")), SHIELD) == []
