"""Game mod families: an item cannot carry two mods of one family, and PoB's own `group`
field is not that family (it splits 185 of the 512 families and 10 of its groups span two).
The corpus comes from RePoE, keyed by PoB's mod ids (scripts/build_mod_families.py).

The corpus and audit tests need no PoB; the loot / craft test skips without the runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_xml
from junkroan.pob.mod_families import conflicting, corpus_path, families_of
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

CHAOS_DOT = "ChaosDamageOverTimeMultiplier1_"  # PoB group ChaosDamageOverTimeMultiplier
PHYS_DOT = "PhysicalDamageOverTimeMultiplier2"  # PoB group PhysicalDamageOverTimeMultiplier
GLOBAL_DOT = "GlobalDamageOverTimeMultiplier1h3"  # a family of its own, fine beside a typed one


def _xml(*affix_lines: str) -> str:
    """A minimal build with one rare in Weapon 1, written the way our loot items are."""

    item = "\n".join(("Rarity: RARE", "Probe Wand", "Driftwood Wand", "Item Level: 86", *affix_lines))
    return (
        "<PathOfBuilding><Build/><Tree/><Items activeItemSet=\"1\">"
        f'<Item id="1">{item}</Item>'
        '<ItemSet id="1"><Slot name="Weapon 1" itemId="1"/></ItemSet>'
        "</Items></PathOfBuilding>"
    )


def test_the_corpus_carries_the_game_family_not_pobs_group() -> None:
    assert corpus_path().is_file() and json.loads(corpus_path().read_text(encoding="utf-8"))["count"] > 20000
    # four PoB groups, one family: a wand cannot carry two typed damage-over-time multipliers
    assert families_of(CHAOS_DOT) == ("DamageOverTimeMultiplier",)
    assert families_of(PHYS_DOT) == ("DamageOverTimeMultiplier",)
    # the generic one is its own family and may sit beside a typed one
    assert families_of(GLOBAL_DOT) == ("GlobalDamageOverTimeMultiplier",)
    # the bench "+life / mana regen" craft is family IncreasedLife (PoB group BaseLifeAndManaRegen)
    assert families_of("JunMaster2BaseLifeAndManaRegen1") == ("IncreasedLife",)
    # a mod occupies all of its families: PoB group FireDamagePhysConvertedToFire is two of them
    assert families_of("AddedFireDamageEnhancedMod") == ("ConvertPhysicalToFire", "FireDamage")
    assert families_of("NoSuchModAnywhere") == ()


def test_conflicting_names_the_pair_and_the_family() -> None:
    pairs = conflicting([CHAOS_DOT, PHYS_DOT, GLOBAL_DOT])
    assert pairs == [(CHAOS_DOT, PHYS_DOT, "DamageOverTimeMultiplier")]
    assert conflicting([CHAOS_DOT, GLOBAL_DOT]) == []
    assert conflicting([CHAOS_DOT]) == [] and conflicting([]) == []
    assert conflicting(["NoSuchModAnywhere", "NoSuchModEither"]) == []  # unknown mods never conflict


def test_the_audit_flags_two_mods_of_one_family_on_an_item() -> None:
    findings = audit_xml(_xml(f"Suffix: {{range:0.500}}{CHAOS_DOT}", f"Suffix: {{range:0.500}}{PHYS_DOT}"))
    family = [f for f in findings if f.check == "mod family"]
    assert len(family) == 1 and family[0].severity == "error"
    assert "Weapon 1" in family[0].detail and "DamageOverTimeMultiplier" in family[0].detail
    assert CHAOS_DOT in family[0].detail and PHYS_DOT in family[0].detail
    # the generic multiplier is a different family: a legal item
    ok = audit_xml(_xml(f"Suffix: {{range:0.500}}{CHAOS_DOT}", f"Suffix: {{range:0.500}}{GLOBAL_DOT}"))
    assert [f for f in ok if f.check == "mod family"] == []


def test_the_audit_judges_the_bench_craft_by_its_text() -> None:
    """The craft is rolled text without an id ("{crafted}+31 to maximum Life"): the hybrid
    life / mana regen craft is family IncreasedLife and cannot sit next to a flat-life prefix
    (the user's reading of run E); an attribute craft beside it is fine."""

    life = "Prefix: {range:0.500}IncreasedLife1"
    findings = audit_xml(_xml(life, "{crafted}+31 to maximum Life", "{crafted}Regenerate 2 Mana per second"))
    family = [f for f in findings if f.check == "mod family"]
    assert len(family) == 1 and family[0].severity == "error"
    assert "IncreasedLife1" in family[0].detail and "IncreasedLife" in family[0].detail and "+31 to maximum Life" in family[0].detail
    ok = audit_xml(_xml(life, "{crafted}+13 to Dexterity and Intelligence"))
    assert [f for f in ok if f.check == "mod family"] == []
    # a craft no crafted mod fits is not judged; an explicit line with tags is not a craft
    quiet = audit_xml(_xml(life, "{crafted}+999 to maximum Life", "{tags:resource,life}{prefix}+14 to maximum Life"))
    assert [f for f in quiet if f.check == "mod family"] == []


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-mod-families", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


@pytest.mark.pob
@needs_pob
def test_rolled_loot_never_carries_two_mods_of_one_family(pob: PobSession) -> None:
    items = pob.random_rares("Driftwood Wand", n=200, ilvl=86)
    assert len(items) == 200
    offenders = [(item["mod_ids"], conflicting(item["mod_ids"])) for item in items if conflicting(item["mod_ids"])]
    assert offenders == []
    # the roll still uses the whole pool, so the typed multipliers do turn up, one per item
    assert any(any("DamageOverTimeMultiplier" in mod_id for mod_id in item["mod_ids"]) for item in items)


@pytest.mark.pob
@needs_pob
def test_craft_rare_reports_two_typed_dot_multipliers_as_one_family(pob: PobSession) -> None:
    clash = pob.craft_rare("Driftwood Wand", suffixes=[CHAOS_DOT, PHYS_DOT], ilvl=86)
    assert any("duplicate mod family DamageOverTimeMultiplier" in problem for problem in clash["problems"])
    fine = pob.craft_rare("Driftwood Wand", suffixes=[CHAOS_DOT, GLOBAL_DOT], ilvl=86)
    assert fine["problems"] == []
