"""#510 unit 5: a mod line the request forces is on every rare its slot is tried with.

The PoB-free half: the resolver over a faked `list_item_mods`, and `LootGear.fill_slot` over a fake
pob (every trial of the slot carries the line, an incumbent without it is dropped, a bench craft
never costs the line). The `pob` half rolls real rares with `forced=` and reads their item text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from junkroan.optimizer.loot_gear import LootGear, forced_mod_choices, raw_carries
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

LINE = "+1 to Level of all Fire Spell Skill Gems"
MODS = {
    "mods": [
        {"mod_id": "GlobalFireSpellGemsLevel1_", "type": "Prefix", "lines": ["+1 to Level of all Fire Spell Skill Gems"], "level": 2, "weight": 250},
        {"mod_id": "GlobalFireSpellGemsLevel2", "type": "Prefix", "lines": ["+(1-2) to Level of all Fire Spell Skill Gems"], "level": 60, "weight": 100},
        {"mod_id": "LocalIncreasedLife1", "type": "Suffix", "lines": ["+(10-15) to maximum Life"], "level": 1, "weight": 1000},
        {"mod_id": "HybridX", "type": "Prefix", "lines": ["(10-15)% increased Spell Damage", "+(10-15) to maximum Mana"], "level": 1, "weight": 10},
    ]
}
DPS = Objective(maximize="CombinedDPS")


class _ModsPob:
    def list_item_mods(self, base, *, ilvl=None, pool="explicit"):
        self.asked = (base, ilvl, pool)
        return MODS


def test_resolver_returns_every_tier_of_the_line() -> None:
    pob = _ModsPob()
    assert forced_mod_choices(pob, "Imbued Wand", [LINE], 84) == [["GlobalFireSpellGemsLevel1_", "GlobalFireSpellGemsLevel2"]]
    assert pob.asked == ("Imbued Wand", 84, "explicit")


def test_resolver_matches_a_range_line_by_template_and_a_hybrid_through_any_of_its_lines() -> None:
    pob = _ModsPob()
    assert forced_mod_choices(pob, "Imbued Wand", ["+12 to maximum Life", "+30 to maximum Mana"], 84) == [["LocalIncreasedLife1"], ["HybridX"]]


def test_resolver_raises_for_a_line_the_base_cannot_roll() -> None:
    with pytest.raises(ValueError, match=r"mod line '\+1 to Level of Socketed Melee Gems' cannot roll on Imbued Wand"):
        forced_mod_choices(_ModsPob(), "Imbued Wand", [LINE, "+1 to Level of Socketed Melee Gems"], 84)


def test_raw_carries_reads_through_pobs_line_prefixes() -> None:
    raw = "Rarity: RARE\nX\nImbued Wand\n{tags:elemental,fire,caster,gem}{prefix}+1 to Level of all Fire Spell Skill Gems\n{crafted}+30 to maximum Mana"
    assert raw_carries(raw, LINE) and raw_carries(raw, "+12 to maximum Mana")
    assert not raw_carries(raw, "+1 to Level of Socketed Melee Gems")


# -- fill_slot over a fake pob ----------------------------------------------------


def _item(name: str, with_line: bool, dps: float) -> dict:
    lines = ["Rarity: RARE", name, "Imbued Wand", "{tags:life}{suffix}+30 to maximum Life"]
    if with_line:
        lines.append("{tags:elemental,fire,caster,gem}{prefix}" + LINE)
    return {"raw": "\n".join(lines), "mod_ids": ["m"], "dps": dps}


class _SlotPob:
    """The roll hands back items with and without the line (a stand-in for the headless side
    ignoring `forced`): the filler must still send only carriers to PoB."""

    def __init__(self) -> None:
        self.random_calls: list[dict] = []
        self.trials: list[str] = []
        self.equipped: list[dict] = []
        self.dps = {}

    def stats(self, keys):
        return {"CombinedDPS": 100.0}

    def list_item_mods(self, base, *, ilvl=None, pool="explicit"):
        return MODS

    def random_rares(self, base, **kw):
        self.random_calls.append(dict(kw))
        rolls = [_item("a", True, 300.0), _item("b", False, 900.0), _item("c", True, 500.0)]
        for r in rolls:
            self.dps[r["raw"]] = r.pop("dps")
        return rolls

    def trial_stats(self, trials, keys, mode="fast"):
        for t in trials:
            self.trials.append(t["item"]["raw"])
        return [{"ok": True, "stats": {"CombinedDPS": self.dps.get(t["item"]["raw"], 50.0)}} for t in trials]

    def equip(self, items):
        self.equipped.append(dict(items))


def test_every_trial_for_the_slot_carries_the_forced_line() -> None:
    pob = _SlotPob()
    loot = LootGear(pob, DPS, Rails.load())
    loot.forced_lines = {"Weapon 1": [LINE]}

    res = loot.fill_slot("Weapon 1", "Imbued Wand", n=3, bench=False)

    assert pob.random_calls[0]["forced"] == [["GlobalFireSpellGemsLevel1_", "GlobalFireSpellGemsLevel2"]]
    assert len(pob.trials) == 2 and all(raw_carries(raw, LINE) for raw in pob.trials)
    assert raw_carries(res.raw, LINE) and res.after_loot.value == 500.0  # the 900-DPS roll without the line never competed
    assert res.rolled == 2


def test_an_incumbent_without_the_line_is_dropped_and_one_with_it_competes() -> None:
    pob = _SlotPob()
    loot = LootGear(pob, DPS, Rails.load())
    loot.forced_lines = {"Weapon 1": [LINE]}
    bare = _item("old", False, 0)["raw"]
    pob.dps[bare] = 5000.0
    loot.current_raw["Weapon 1"] = bare

    loot.fill_slot("Weapon 1", "Imbued Wand", n=3, bench=False)

    assert bare not in pob.trials and all(raw_carries(raw, LINE) for raw in pob.trials)

    pob2 = _SlotPob()
    loot2 = LootGear(pob2, DPS, Rails.load())
    loot2.forced_lines = {"Weapon 1": [LINE]}
    held = _item("old", True, 0)["raw"]
    pob2.dps[held] = 5000.0
    loot2.current_raw["Weapon 1"] = held
    res = loot2.fill_slot("Weapon 1", "Imbued Wand", n=3, bench=False)
    assert held in pob2.trials and res.raw == held


def test_a_slot_with_nothing_forced_rolls_as_before() -> None:
    pob = _SlotPob()
    loot = LootGear(pob, DPS, Rails.load())
    loot.forced_lines = {"Weapon 1": [LINE]}

    res = loot.fill_slot("Helmet", "Iron Hat", n=3, bench=False)

    assert "forced" not in pob.random_calls[0]  # the call is byte-for-byte the old one
    assert len(pob.trials) == 3 and res.raw.count(LINE) == 0  # the best roll (900) has no line and is welcome here


def test_a_roll_that_never_carries_the_line_raises() -> None:
    pob = _SlotPob()
    pob.random_rares = lambda base, **kw: [_item("b", False, 1.0)]
    loot = LootGear(pob, DPS, Rails.load())
    loot.forced_lines = {"Weapon 1": [LINE]}

    with pytest.raises(RuntimeError, match="carries the forced lines"):
        loot.fill_slot("Weapon 1", "Imbued Wand", n=1, bench=False)


class _BenchPob(_SlotPob):
    def list_bench_mods(self, base, *, ilvl=None, range_=None):
        return {"mods": [{"mod_id": "B1", "type": "Suffix", "level": 50, "group": "g1", "families": ["f1"], "rolled_lines": ["+40 to maximum Mana"], "unlock": None}]}


def test_the_bench_craft_only_adds_to_an_item_that_keeps_its_line() -> None:
    pob = _BenchPob()
    loot = LootGear(pob, DPS, Rails.load())
    loot.forced_lines = {"Weapon 1": [LINE]}

    res = loot.fill_slot("Weapon 1", "Imbued Wand", n=3, bench=True)

    assert len(pob.trials) >= 3 and all(raw_carries(raw, LINE) for raw in pob.trials)
    assert raw_carries(res.raw, LINE)


# -- against the pinned PoB --------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-loot-forced", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()))
        yield session


@pytest.mark.pob
@needs_pob
def test_forced_rolls_all_carry_the_line_inside_the_mod_count(pob: PobSession) -> None:
    ilvl = 84
    choices = forced_mod_choices(pob, "Imbued Wand", [LINE], ilvl)
    mod_counts = (4, 4, 4, 5, 5, 6)
    rolls = pob.random_rares("Imbued Wand", n=100, ilvl=ilvl, seed=7, forced=choices)

    assert len(rolls) == 100
    carrying = [r for r in rolls if raw_carries(r["raw"], LINE)]
    assert len(carrying) == 100
    assert all(len([m for m in r["mod_ids"] if m in choices[0]]) == 1 for r in rolls)  # one mod for the line, never two
    assert all(min(mod_counts) <= len(r["mod_ids"]) <= max(mod_counts) for r in rolls)
    tiers = sorted({m for r in rolls for m in r["mod_ids"] if m in choices[0]})
    print(f"forced rolls: {len(rolls)}, carrying the line: {len(carrying)}, tiers seen: {tiers} of {choices[0]}")


@pytest.mark.pob
@needs_pob
def test_an_empty_forced_rolls_exactly_as_the_call_without_it(pob: PobSession) -> None:
    plain = pob.random_rares("Imbued Wand", n=20, ilvl=84, seed=11)
    empty = pob.random_rares("Imbued Wand", n=20, ilvl=84, seed=11, forced=())
    assert plain == empty
