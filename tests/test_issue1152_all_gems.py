"""#1152: a day-1 weapon slot never carries "+N to Level of all Spell Skill Gems" / "all Skill Gems" (search-space rail, kind A)."""

from __future__ import annotations

from junkroan.optimizer import trace
from junkroan.optimizer.loot_gear import drop_weapon_all_gems, weapon_line_forbidden
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import WishlistGear
from tests.test_wishlist_gear import FakePob, _mod, _rails

ALL = "+1 to Level of all Spell Skill Gems"
ALL_SKILL = "+1 to Level of all Skill Gems"
CHAOS = "+1 to Level of all Chaos Spell Skill Gems"
WANDS = "Rarity: Rare\nDoom Bite\nOpal Wand\n"
SHIELD = "Rarity: Rare\nMind Emblem\nHarmonic Spirit Shield\n"


def _mods() -> list[dict]:
    return [
        _mod("Ordinary", "Prefix", weight=5_000),
        _mod("AllSpellGems", "Prefix", mod_id="all", weight=500, line=ALL, tags=("caster", "gem")),
        _mod("ChaosSpellGems", "Prefix", mod_id="chaos", weight=500, line=CHAOS, tags=("caster", "chaos", "gem")),
    ]


def _gear(**kw) -> WishlistGear:
    return WishlistGear(FakePob(_mods(), **kw), Objective(maximize="CombinedDPS"), _rails())


def test_the_rail_key_holds_both_forbidden_texts() -> None:
    forbidden = Rails.load().gear.weapon_forbidden_lines
    assert "to Level of all Spell Skill Gems" in forbidden and "to Level of all Skill Gems" in forbidden


def test_the_discriminator_is_the_whole_text_after_the_number() -> None:
    forbidden = Rails.load().gear.weapon_forbidden_lines
    for line in (ALL, ALL_SKILL, "{range:0.328}+2 to Level of all Spell Skill Gems", "{crafted}+(1-2) to Level of all Skill Gems", "+1 TO LEVEL OF ALL SPELL SKILL GEMS"):
        assert weapon_line_forbidden(line, forbidden), line
    for line in (CHAOS, "+1 to Level of all Minion Skill Gems", "+2 to Level of Socketed Melee Gems", "+(20-24)% to Fire Resistance"):
        assert not weapon_line_forbidden(line, forbidden), line


def test_median_mods_refuse_the_all_gems_line_on_both_weapon_slots_and_keep_the_element_line() -> None:
    gear = _gear()
    for slot in ("Weapon 1", "Weapon 2"):
        ids = {mod.mod_id for mod in gear._median_mods("Fake Wand", 76, affix_type="Prefix", slot=slot)}
        assert "all" not in ids and {"chaos", "Ordinary"} <= ids, (slot, ids)
    assert "all" in {mod.mod_id for mod in gear._median_mods("Fake Wand", 76, affix_type="Prefix", slot="Helmet")}
    assert "all" in {mod.mod_id for mod in gear._median_mods("Fake Wand", 76, affix_type="Prefix")}


def test_bench_candidates_refuse_the_all_gems_craft_on_both_weapon_slots() -> None:
    bench = [
        {"type": "Prefix", "group": "SpellGemLevel", "level": 1, "rolled_lines": [ALL], "mod_tags": ["gem"], "families": ["SpellGemLevel"], "mod_id": None},
        {"type": "Prefix", "group": "ChaosGemLevel", "level": 1, "rolled_lines": [CHAOS], "mod_tags": ["gem"], "families": ["ChaosGemLevel"], "mod_id": None},
    ]
    gear = _gear(bench=bench)
    for slot in ("Weapon 1", "Weapon 2"):
        groups = {row["group"] for row in gear._bench_candidates("Fake Wand", 76, [], allow_gem_level=True, slot=slot)}
        assert groups == {"ChaosGemLevel"}, (slot, groups)
    assert {row["group"] for row in gear._bench_candidates("Fake Wand", 76, [], allow_gem_level=True, slot="Amulet")} == {"SpellGemLevel", "ChaosGemLevel"}


def test_open_candidates_and_choose_trial_refuse_the_all_gems_line() -> None:
    gear = _gear(worth={"all": 100_000, "chaos": 50_000})
    line = gear._template_for("Fake Wand", "Weapon 1")[0]
    for slot in ("Weapon 1", "Weapon 2"):
        pool = gear._open_candidates("Fake Wand", 76, line, [], None, reserve=None, pure_es=False, bench_allowed=False,
                                     payment_budget_used=0, allow_gem_level=True, slot=slot)
        assert {m.mod_id for m, _c in pool if m is not None} >= {"chaos"} and "all" not in {m.mod_id for m, _c in pool if m is not None}
    # the pick itself drops a forbidden candidate even if a caller built it without the slot
    everything = [(m, None) for m in gear._median_mods("Fake Wand", 76, affix_type="Prefix")]
    assert any(m.mod_id == "all" for m, _c in everything)
    picked = gear._choose_trial("Weapon 1", "Fake Wand", 76, [], None, everything, sockets=None, buys_value=True)
    assert picked is not None and picked[0].mod_id == "chaos"
    elsewhere = gear._choose_trial("Helmet", "Fake Wand", 76, [], None, everything, sockets=None, buys_value=True)
    assert elsewhere is not None and elsewhere[0].mod_id == "all"


def test_a_weapon_fill_never_keeps_the_all_gems_line_and_may_keep_the_element_line() -> None:
    mods = [
        _mod("SpellGemLevel", "Prefix", mod_id="gem1", weight=5_000, line=ALL, tags=("caster", "gem")),
        _mod("ChaosGemLevel", "Prefix", mod_id="gem2", weight=5_000, line=CHAOS, tags=("caster", "chaos", "gem")),
        _mod("OpenB", "Suffix", weight=5_000),
        _mod("OpenC", "Suffix", weight=5_000),
    ]
    worth = {"gem1": 100_000, "gem2": 90_000, "OpenB": 9_000, "OpenC": 8_000}
    result = WishlistGear(FakePob(mods, worth=worth), Objective(maximize="CombinedDPS"), _rails()).fill_slot("Weapon 1", "Fake Wand")
    assert "gem1" not in result.mod_ids and result.mod_ids == ["gem2"]


def test_a_loot_roll_with_the_all_gems_line_is_dropped_on_a_weapon_slot_only() -> None:
    rails = Rails.load()
    clean = {"raw": WANDS + "Item Level: 80\nImplicits: 0\n" + CHAOS}
    dirty = {"raw": WANDS + "Item Level: 80\nImplicits: 0\nPrefix: {range:0.328}GlobalSpellGemsLevel1\n{range:0.328}" + ALL}
    rolls = [clean, dirty]
    assert drop_weapon_all_gems(rolls, "Weapon 1", rails) == [clean]
    assert drop_weapon_all_gems(rolls, "Weapon 2", rails) == [clean]
    assert drop_weapon_all_gems(rolls, "Amulet", rails) == rolls
    # an owner-forced all-gems line keeps its rolls (a forced direction is never dropped)
    assert drop_weapon_all_gems(rolls, "Weapon 1", rails, forced=[ALL]) == rolls


def test_trace_classes_weapon_all_gems_and_weapon_element_gems() -> None:
    wand = WANDS + "Item Level: 80\nImplicits: 0\n"
    classes = lambda slot, raw: trace.classify({"item": {"slot": slot, "raw": raw}})  # noqa: E731
    assert "weapon-all-gems-level" in classes("Weapon 1", wand + ALL)
    assert "weapon-all-gems-level" in classes("Weapon 2", SHIELD + ALL_SKILL)
    assert "weapon-all-gems-level" in classes("", wand + "{range:0.3}" + ALL)  # a delivered item has no slot in the output count
    assert "weapon-all-gems-level" not in classes("Weapon 1", wand + CHAOS)
    assert "weapon-all-gems-level" not in classes("Amulet", "Rarity: Rare\nX\nOnyx Amulet\nItem Level: 80\nImplicits: 0\n" + ALL_SKILL)
    assert "weapon-all-gems-level" not in classes("", "Rarity: Rare\nX\nOnyx Amulet\nItem Level: 80\nImplicits: 0\n" + ALL_SKILL)
    assert "weapon-all-gems-level" not in classes("Weapon 1", "Rarity: Unique\nX\nOpal Wand\n" + ALL)
    assert "weapon-element-gems-level" in classes("Weapon 1", wand + CHAOS)
    assert "weapon-element-gems-level" not in classes("Weapon 1", wand + ALL)
    assert "weapon-element-gems-level" not in classes("Weapon 1", wand + "+2 to Level of Socketed Melee Gems")
    TRACE.reset()
    TRACE.add_generated(classes("Weapon 1", wand + CHAOS))
    TRACE.add_evaluated(classes("Weapon 1", wand + CHAOS))
    counts = TRACE._pending["weapon-element-gems-level"]
    assert counts["generated"] > 0 and counts["evaluated"] > 0
    assert "weapon-all-gems-level" not in TRACE._pending


def test_the_headroom_ranking_never_sends_a_weapon_roll_with_the_all_gems_line() -> None:
    from loop_fakes import _Loot, _Pob, _skeleton, loop_over

    def roll(*mods: str) -> dict:
        return {"raw": WANDS + "Item Level: 80\nImplicits: 0\n" + "\n".join(mods)}

    class RollPob(_Pob):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self.trialled: list[dict] = []

        def random_rares(self, base, **kwargs):
            return [roll(ALL), roll(CHAOS), roll(ALL, "+80 to maximum Life")]

        def trial_stats(self, trials, keys, mode="fast"):
            self.trialled.extend(trials)
            for trial in trials:
                TRACE.count_trial(trial)
            return []

    TRACE.reset()
    pob = RollPob(1000.0)
    loot = _Loot(pob, {})
    skeleton = _skeleton({"Weapon 1": "Opal Wand"})
    from types import SimpleNamespace

    rails = SimpleNamespace(gear=SimpleNamespace(loot_best_of_n=200, item_level=86, quality=20, weapon_forbidden_lines=Rails.load().gear.weapon_forbidden_lines))
    loop_over(pob, tree=None, gear=loot, skeleton=skeleton, rails=rails).headroom(skeleton, loot, ["Weapon 1"], 5, 1)
    counts: dict[str, dict[str, int]] = {}
    for moves in TRACE.considered().values():
        for name, n in moves.items():
            acc = counts.setdefault(name, {"generated": 0, "evaluated": 0})
            acc["generated"] += n.get("generated", 0)
            acc["evaluated"] += n.get("evaluated", 0)
    assert counts.get("weapon-all-gems-level", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
    assert counts["weapon-element-gems-level"]["evaluated"] > 0
    assert len(pob.trialled) == 1


# -- review fixes: the bench craft list, and the forced-line exemption is the forced line alone ------------------------


def test_a_bench_craft_carrying_the_all_gems_line_is_never_tried_on_a_weapon() -> None:
    # PoB's own bench table (ModMaster.lua) has no "Level of all" craft; the filter keeps that true if a table ever gains one
    from junkroan.optimizer.loot_gear import LootGear
    from tests.test_loot_forced import DPS, _BenchPob

    class Pob(_BenchPob):
        def list_bench_mods(self, base, *, ilvl=None, range_=None):
            rows = [{"mod_id": f"B{i}", "type": "Prefix", "level": 50, "group": f"g{i}", "families": [f"f{i}"], "rolled_lines": [line], "unlock": None}
                    for i, line in enumerate((ALL, ALL_SKILL, CHAOS))]
            return {"mods": rows}

    pob = Pob()
    loot = LootGear(pob, DPS, Rails.load())
    loot.fill_slot("Weapon 1", "Imbued Wand", n=3, bench=True)
    crafted = [raw for raw in pob.trials if "{crafted}" in raw]
    assert crafted and all("{crafted}" + CHAOS in raw for raw in crafted), crafted
    assert not any(weapon_line_forbidden(ln, Rails.load().gear.weapon_forbidden_lines) for raw in crafted for ln in raw.splitlines()[3:])


def test_a_forced_all_gems_line_exempts_only_itself() -> None:
    rails = Rails.load()
    forced_only = {"raw": WANDS + "Item Level: 80\nImplicits: 0\n" + ALL}
    with_other = {"raw": WANDS + "Item Level: 80\nImplicits: 0\n" + ALL + "\n" + ALL_SKILL}
    other_only = {"raw": WANDS + "Item Level: 80\nImplicits: 0\n" + ALL_SKILL}
    rolls = [forced_only, with_other, other_only]
    assert drop_weapon_all_gems(rolls, "Weapon 1", rails, forced=[ALL]) == [forced_only]
    assert drop_weapon_all_gems(rolls, "Weapon 1", rails) == []
    # the wishlist: the forced text stays offered, the other forbidden text is still refused
    gear = _gear()
    gear.forced_lines = {"Weapon 1": [ALL]}
    assert not gear._refuses("Weapon 1", [ALL]) and gear._refuses("Weapon 1", [ALL_SKILL])
    assert gear._refuses("Weapon 2", [ALL])
