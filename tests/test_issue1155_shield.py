"""#1155: the loot path never tries a shield that carries a gem-level line AND another mod (no PoB).

A1 (Contagion, loot gear) delivered a Titanium Spirit Shield with "+1 to Level of all Chaos Spell Skill Gems", an
elemental resistance and a bench-crafted Mana Regeneration line: `LootGear.fill_slot` rolled it, and the bench craft
could add to it. The shield rule (#601: a gem-level line takes the whole shield) lived in the template filler only.
"""

from __future__ import annotations

from junkroan.optimizer.loot_gear import LootGear, drop_shield_gem_with_other
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import is_shield_gem_level_with_other

GEM = "+1 to Level of all Chaos Spell Skill Gems"
RES = "+16% to all Elemental Resistances"
LIFE = "+60 to maximum Life"
HEAD = "Rarity: RARE\nRandom 2\nTitanium Spirit Shield\nItem Level: 70\nImplicits: 0\n"
DPS = Objective(maximize="CombinedDPS")


def _shield(*lines: str) -> str:
    return HEAD + "\n".join(lines)


GEM_WITH_OTHER = _shield("{tags:chaos,caster,gem}{prefix}" + GEM, "{tags:elemental,resistance}{suffix}" + RES)
GEM_ALONE = _shield("{tags:chaos,caster,gem}{prefix}" + GEM)
ORDINARY = _shield("{tags:resource,life}{prefix}" + LIFE, "{tags:elemental,resistance}{suffix}" + RES)
DPS_OF = {GEM_WITH_OTHER: 900.0, GEM_ALONE: 400.0, ORDINARY: 100.0}


class _ShieldPob:
    def __init__(self, rolls: list[str]) -> None:
        self.rolls = rolls
        self.trials: list[str] = []

    def stats(self, keys):
        return {"CombinedDPS": 50.0}

    def list_item_mods(self, base, *, ilvl=None, pool="explicit"):
        return {"mods": []}

    def list_bench_mods(self, base, *, ilvl=None, range_=None):
        return {"mods": [{"mod_id": "B1", "type": "Suffix", "level": 50, "group": "g1", "families": ["f1"], "rolled_lines": ["36% increased Mana Regeneration Rate"], "unlock": None}]}

    def random_rares(self, base, **kw):
        return [{"raw": raw, "mod_ids": ["m"]} for raw in self.rolls]

    def trial_stats(self, trials, keys, mode="fast"):
        for t in trials:
            self.trials.append(t["item"]["raw"])
            TRACE.count_trial(t)
        return [{"ok": True, "stats": {"CombinedDPS": DPS_OF.get(t["item"]["raw"], 60.0)}} for t in trials]

    def equip(self, items):
        pass

    def recraft(self, raw):
        return raw


def _counts() -> dict[str, dict[str, int]]:
    acc: dict[str, dict[str, int]] = {}
    for moves in TRACE.considered().values():
        for name, n in moves.items():
            row = acc.setdefault(name, {"generated": 0, "evaluated": 0})
            row["generated"] += n.get("generated", 0)
            row["evaluated"] += n.get("evaluated", 0)
    return acc


def test_the_fixtures_are_what_the_trace_class_calls_them() -> None:
    assert is_shield_gem_level_with_other("Weapon 2", GEM_WITH_OTHER)
    assert not is_shield_gem_level_with_other("Weapon 2", GEM_ALONE)
    assert not is_shield_gem_level_with_other("Weapon 2", ORDINARY)


def test_the_drop_keeps_every_roll_but_a_shield_gem_line_with_another_mod() -> None:
    rolls = [{"raw": GEM_WITH_OTHER}, {"raw": GEM_ALONE}, {"raw": ORDINARY}]
    assert drop_shield_gem_with_other(rolls, "Weapon 2") == rolls[1:]
    assert drop_shield_gem_with_other(rolls, "Weapon 1") == rolls  # only the shield slot holds a shield
    assert drop_shield_gem_with_other(rolls, "Helmet") == rolls


def test_a_loot_fill_of_the_shield_slot_never_tries_a_gem_level_shield_with_another_mod() -> None:
    TRACE.reset()
    pob = _ShieldPob([GEM_WITH_OTHER, GEM_ALONE, ORDINARY])
    res = LootGear(pob, DPS, Rails.load()).fill_slot("Weapon 2", "Titanium Spirit Shield", n=3, bench=True)
    counts = _counts()
    TRACE.reset()
    assert pob.trials and not any(is_shield_gem_level_with_other("Weapon 2", raw) for raw in pob.trials)
    assert counts.get("shield-gem-level-with-other", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
    assert counts["shield-gem-level"]["generated"] > 0 and counts["shield-gem-level"]["evaluated"] > 0  # the allowed half stays reachable
    assert res.raw == GEM_ALONE and res.rolled == 2  # the 900-DPS roll with a second mod never competed


def test_a_bench_craft_is_never_added_to_a_gem_level_shield() -> None:
    TRACE.reset()
    pob = _ShieldPob([GEM_ALONE, ORDINARY])
    LootGear(pob, DPS, Rails.load()).fill_slot("Weapon 2", "Titanium Spirit Shield", n=2, bench=True)
    TRACE.reset()
    crafted = [raw for raw in pob.trials if "{crafted}" in raw]
    assert crafted, "the ordinary shield still gets its craft"
    assert not any(is_shield_gem_level_with_other("Weapon 2", raw) for raw in crafted)
    assert not any(GEM in raw for raw in crafted)


def test_an_incumbent_gem_shield_with_another_mod_does_not_compete() -> None:
    TRACE.reset()
    pob = _ShieldPob([ORDINARY])
    loot = LootGear(pob, DPS, Rails.load())
    loot.current_raw["Weapon 2"] = GEM_WITH_OTHER
    res = loot.fill_slot("Weapon 2", "Titanium Spirit Shield", n=1, bench=False)
    TRACE.reset()
    assert not any(is_shield_gem_level_with_other("Weapon 2", raw) for raw in pob.trials)
    assert res.raw == ORDINARY
