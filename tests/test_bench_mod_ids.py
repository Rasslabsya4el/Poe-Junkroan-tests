"""A crafting-bench row is a game mod: which one, and which families it occupies.

PoB's bench table (`data.masterMods`) carries no mod id, so the bench filter used
to fall back to PoB's `group`. The group is not the game's family: the
"+(28-33) to maximum Life / Regenerate 2 Mana per second" craft is PoB group
`BaseLifeAndManaRegen` but family `IncreasedLife`, and the game never puts it on
an item that already carries a flat-life prefix. `bench_mod_ids` recognises the
row by its text against RePoE's crafted domain (`corpus_data/bench_mods.json`).

No PoB runtime is needed: everything here is the corpus and a pure filter.
"""

from __future__ import annotations

import json

from junkroan.optimizer.loot_gear import bench_candidates
from junkroan.optimizer.rails import Rails
from junkroan.pob.bench_mod_ids import bench_mod_families, bench_mod_id, canonical_lines, corpus_path, crafted_text_families, crafted_text_mods
from junkroan.pob.mod_families import families_of

RAILS = Rails()
LIFE_MANA_REGEN = ("+(28-33) to maximum Life", "Regenerate 2 Mana per second")
# the same craft one and two ranks up (PoB ModMaster levels 60 / 72 / 81)
RANKS = (
    (60, ["+(28-33) to maximum Life", "Regenerate 2 Mana per second"]),
    (72, ["+(34-40) to maximum Life", "Regenerate 3 Mana per second"]),
    (81, ["+(41-45) to maximum Life", "Regenerate 4 Mana per second"]),
)


def _row(affix: str, group: str, level: int, lines: list[str] | tuple[str, ...]) -> dict:
    """A row shaped like `PobSession.list_bench_mods` returns them."""

    return {"index": 1, "type": affix, "affix": "Upgraded", "group": group, "level": level, "lines": list(lines), "rolled_lines": list(lines), "mod_tags": []}


def test_the_corpus_carries_the_crafted_mods_with_level_text_and_families() -> None:
    raw = json.loads(corpus_path().read_text(encoding="utf-8"))
    assert raw["count"] > 1000 and raw["sha256"]
    entry = raw["mods"]["JunMaster2BaseLifeAndManaRegen1"]
    assert entry["type"] == "prefix" and entry["level"] == 60
    assert entry["lines"] == list(LIFE_MANA_REGEN)
    assert entry["families"] == ["IncreasedLife"]
    # the stat ids are per minute while the text is per second: the numbers cannot
    # identify the mod, which is why the text does
    assert ["base_mana_regeneration_rate_per_minute", 120, 120] in entry["stats"]
    # every corpus entry agrees with the family index the rest of the code reads
    for mod_id, mod in raw["mods"].items():
        assert list(families_of(mod_id)) == mod["families"], mod_id


def test_the_life_and_mana_regen_bench_row_is_the_flat_life_family() -> None:
    row = _row("Prefix", "BaseLifeAndManaRegen", 60, LIFE_MANA_REGEN)
    assert bench_mod_id(row) == "JunMaster2BaseLifeAndManaRegen1"
    assert bench_mod_families(row) == ("IncreasedLife",)  # not PoB's BaseLifeAndManaRegen


def test_the_three_ranks_of_that_craft_are_three_different_mods() -> None:
    ids = [bench_mod_id(_row("Prefix", "BaseLifeAndManaRegen", level, lines)) for level, lines in RANKS]
    assert ids == ["JunMaster2BaseLifeAndManaRegen1", "JunMaster2BaseLifeAndManaRegen2_", "JunMaster2BaseLifeAndManaRegen3"]
    assert len(set(ids)) == 3
    assert all(bench_mod_families(_row("Prefix", "BaseLifeAndManaRegen", level, lines)) == ("IncreasedLife",) for level, lines in RANKS)


def test_a_row_no_crafted_mod_matches_has_no_id_and_no_family() -> None:
    row = _row("Prefix", "NoSuchBenchGroupAnywhere", 60, ["+(1-2) to Nothing at All"])
    assert bench_mod_id(row) is None
    assert bench_mod_families(row) == ()


def test_the_affix_type_and_the_level_pick_the_rank_apart() -> None:
    # the level-60 text read as a suffix is not a mod the bench has
    assert bench_mod_id(_row("Suffix", "BaseLifeAndManaRegen", 60, LIFE_MANA_REGEN)) is None
    # a level PoB never lists for this craft: the text still names the mod, the
    # level only breaks ties, so the row stays resolvable
    assert bench_mod_id(_row("Prefix", "BaseLifeAndManaRegen", 99, LIFE_MANA_REGEN)) == "JunMaster2BaseLifeAndManaRegen1"


def test_rows_whose_group_names_no_crafted_id_still_resolve() -> None:
    # RePoE calls it ...FireAndColdResist, PoB's group is FireAndColdResistance:
    # the id never contains the group, and the text is what identifies the mod
    row = _row("Suffix", "FireAndColdResistance", 30, ["+(10-12)% to Fire and Cold Resistances"])
    assert bench_mod_id(row) == "EinharMasterFireAndColdResist1"
    assert bench_mod_families(row) == ("FireAndColdResistance",)
    # RePoE writes some ranges high-low and orders a two-stat mod's lines the other way
    reversed_row = _row("Suffix", "ReducedElementalAilmentEffectOnSelf", 30, ["(24-30)% reduced Effect of Chill and Shock on you"])
    assert bench_mod_id(reversed_row) == "EinharMasterReducedElementalAilmentEffect1"  # RePoE text: "(30-24)%"
    assert canonical_lines(["(30-24)% Reduced  Effect"]) == canonical_lines(["(24-30)% reduced Effect"])


def test_the_bench_filter_rejects_a_craft_of_a_family_the_item_already_has() -> None:
    """The gap: a rare with a flat-life prefix must not get the life / mana regen craft."""

    life_craft = _row("Prefix", "BaseLifeAndManaRegen", 60, LIFE_MANA_REGEN)
    life_craft["mod_id"] = bench_mod_id(life_craft)
    life_craft["families"] = list(bench_mod_families(life_craft))
    resist_craft = _row("Suffix", "FireResistance", 50, ["+(29-35)% to Fire Resistance"])
    resist_craft["mod_id"] = bench_mod_id(resist_craft)
    resist_craft["families"] = list(bench_mod_families(resist_craft))
    rows = [life_craft, resist_craft]

    item_mod_ids = ["IncreasedLife7"]  # a T-whatever flat life prefix, family IncreasedLife
    assert families_of("IncreasedLife7") == ("IncreasedLife",)
    families = {"IncreasedLife7": frozenset(("IncreasedLife", "pob:IncreasedLife"))}
    kept = bench_candidates(rows, item_mod_ids, lambda mod_id: families[mod_id], 1, 0, RAILS)
    assert [row["group"] for row in kept] == ["FireResistance"]

    # on an item without a life prefix the same craft is legal again
    kept = bench_candidates(rows, [], lambda mod_id: frozenset(), 0, 0, RAILS)
    assert sorted(row["group"] for row in kept) == ["BaseLifeAndManaRegen", "FireResistance"]


def test_the_bench_filter_keeps_pobs_group_as_a_fallback_and_counts_affixes() -> None:
    row = _row("Suffix", "FireResistance", 50, ["+(29-35)% to Fire Resistance"])
    item_families = {"FireResistance5": frozenset(("FireResistance", "pob:FireResistance"))}
    assert bench_candidates([row], ["FireResistance5"], lambda m: item_families[m], 0, 0, RAILS) == []
    # a row the corpus does not know is still blocked by PoB's group alone
    unknown = _row("Suffix", "FireResistance", 50, ["+(29-35)% to Made Up Resistance"])
    assert bench_mod_families(unknown) == ()
    assert bench_candidates([unknown], ["FireResistance5"], lambda m: item_families[m], 0, 0, RAILS) == []
    # a full set of suffixes leaves no room for a suffix craft
    assert bench_candidates([row], [], lambda m: frozenset(), 0, RAILS.gear.max_suffixes, RAILS) == []


def test_the_filter_offers_the_highest_rank_first() -> None:
    rows = [_row("Prefix", "BaseLifeAndManaRegen", level, lines) for level, lines in RANKS]
    kept = bench_candidates(rows, [], lambda m: frozenset(), 0, 0, RAILS)
    assert [row["level"] for row in kept] == [81, 72, 60]


def test_a_finished_items_crafted_text_resolves_to_its_mod_and_families() -> None:
    """A finished item carries the craft as rolled text, no id: "{crafted}+31 to maximum Life" /
    "{crafted}Regenerate 2 Mana per second" is the level-60 hybrid, family IncreasedLife."""

    assert crafted_text_mods(["+31 to maximum Life", "Regenerate 2 Mana per second"]) == ("JunMaster2BaseLifeAndManaRegen1",)
    assert crafted_text_families(["Regenerate 2 Mana per second", "+31 to maximum Life"]) == ("IncreasedLife",)  # order ignored
    # the number picks the rank: 38 is the level-72 craft, 99 is no craft at all
    assert crafted_text_mods(["+38 to maximum Life", "Regenerate 3 Mana per second"]) == ("JunMaster2BaseLifeAndManaRegen2_",)
    assert crafted_text_mods(["+99 to maximum Life", "Regenerate 2 Mana per second"]) == ()
    # one line of a two-line mod is not that mod; a resistance craft fits several masters' rows
    # with one family between them
    assert crafted_text_mods(["Regenerate 2 Mana per second"]) == ()
    assert len(crafted_text_mods(["+19% to Cold Resistance"])) > 1
    assert crafted_text_families(["+19% to Cold Resistance"]) == ("ColdResistance",)
    assert crafted_text_families(["+13 to Dexterity and Intelligence"]) == ("Dexterity", "Intelligence")
    assert crafted_text_families([]) == () and crafted_text_families(["not a mod"]) == ()
