"""#1152 send-back: a day-1 weapon never carries the all-gems line, not even as the INCUMBENT kept as a competitor.

B1 (replay `--move gear`, artifacts/replay/20261016-1222-m-gear-b1): the recorded build's Weapon 1 is a random roll
with `{range:0.328}GlobalSpellGemsLevel1` ("+1 to Level of all Spell Skill Gems"); no request forces it. The loot
rolls were already filtered (#1152), but `LootGear.fill_slot` added the incumbent after the filter (3 trials counted
as `weapon-all-gems-level`, 1 in the output). Same shape as the shield incumbent of #1155.
"""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.loot_gear import LootGear, weapon_all_gems_raw
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import WishlistGear
from tests.test_wishlist_gear import FakePob, _mod, _rails

ALL = "+1 to Level of all Spell Skill Gems"
CHAOS = "+1 to Level of all Chaos Spell Skill Gems"
HEAD = "Rarity: RARE\nRandom 134\nDemon Dagger\nItem Level: 70\nImplicits: 0\n"
BARE_DIRTY = HEAD + ALL
DIRTY = HEAD + "{range:0.328}{tags:caster,gem}{prefix}" + ALL
CLEAN = HEAD + "{tags:caster,chaos,gem}{prefix}" + CHAOS
ROLL = HEAD + "{tags:life}{prefix}+60 to maximum Life"
FORBIDDEN = Rails.load().gear.weapon_forbidden_lines
DPS = Objective(maximize="CombinedDPS")
DPS_OF = {DIRTY: 900.0, CLEAN: 300.0, ROLL: 100.0}


class _Pob:
    def __init__(self, rolls: list[str]) -> None:
        self.rolls = rolls
        self.trials: list[str] = []

    def stats(self, keys):
        return {"CombinedDPS": 50.0}

    def list_item_mods(self, base, *, ilvl=None, pool="explicit"):
        return {"mods": []}

    def list_bench_mods(self, base, *, ilvl=None, range_=None):
        return {"mods": []}

    def random_rares(self, base, **kw):
        return [{"raw": raw, "mod_ids": ["m"]} for raw in self.rolls]

    def trial_stats(self, trials, keys, mode="fast"):
        for trial in trials:
            self.trials.append(trial["item"]["raw"])
            TRACE.count_trial(trial)
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


def test_the_fixtures_are_what_the_rule_calls_them() -> None:
    assert weapon_all_gems_raw("Weapon 1", DIRTY, FORBIDDEN)
    assert not weapon_all_gems_raw("Weapon 1", CLEAN, FORBIDDEN)
    assert not weapon_all_gems_raw("Weapon 1", ROLL, FORBIDDEN)


def test_a_loot_fill_never_tries_an_incumbent_weapon_with_the_all_gems_line() -> None:
    TRACE.reset()
    pob = _Pob([ROLL, CLEAN])
    loot = LootGear(pob, DPS, Rails.load())
    loot.current_raw["Weapon 1"] = DIRTY
    res = loot.fill_slot("Weapon 1", "Demon Dagger", n=2, bench=False)
    counts = _counts()
    TRACE.reset()
    assert pob.trials and DIRTY not in pob.trials and not any(weapon_all_gems_raw("Weapon 1", raw, FORBIDDEN) for raw in pob.trials)
    assert counts.get("weapon-all-gems-level", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
    assert counts["weapon-element-gems-level"]["evaluated"] > 0
    assert res.raw == CLEAN and not weapon_all_gems_raw("Weapon 1", res.raw, FORBIDDEN)  # the best allowed roll replaces it


def test_a_clean_incumbent_weapon_still_competes() -> None:
    TRACE.reset()
    pob = _Pob([ROLL])
    loot = LootGear(pob, DPS, Rails.load())
    loot.current_raw["Weapon 1"] = CLEAN
    res = loot.fill_slot("Weapon 1", "Demon Dagger", n=1, bench=False)
    TRACE.reset()
    assert CLEAN in pob.trials and res.raw == CLEAN


def test_a_forced_all_gems_line_keeps_its_incumbent_in_the_competition() -> None:
    TRACE.reset()
    pob = _Pob([DIRTY, ROLL])
    loot = LootGear(pob, DPS, Rails.load())
    loot._forced_for = lambda slot, base: ([ALL], ())  # the request forces the line itself
    loot.current_raw["Weapon 1"] = DIRTY
    res = loot.fill_slot("Weapon 1", "Demon Dagger", n=2, bench=False)
    TRACE.reset()
    assert DIRTY in pob.trials and res.raw == DIRTY


def _wishlist(**kw) -> WishlistGear:
    mods = [_mod("Ordinary", "Prefix", weight=5_000), _mod("OpenB", "Suffix", weight=5_000)]
    gear = WishlistGear(FakePob(mods, worth={ALL: 100_000}, **kw), DPS, _rails())
    gear._resistance_assignments["Weapon 1"] = None  # a slot with no resistance plan keeps its incumbent by score (`_keep_incumbent`), as in a later pass
    return gear


def test_the_wishlist_does_not_keep_an_incumbent_weapon_with_the_all_gems_line_over_a_template_item() -> None:
    gear = _wishlist()
    gear.current_raw["Weapon 1"] = BARE_DIRTY  # the fake prices a line by its bare text
    result = gear.fill_slot("Weapon 1", "Fake Wand")
    assert result.raw and not result.kept_incumbent and result.raw != BARE_DIRTY
    assert gear.current_raw["Weapon 1"] == result.raw


def test_the_wishlist_with_no_template_item_does_not_fall_back_to_a_forbidden_incumbent() -> None:
    gear = _wishlist()
    gear.current_raw["Weapon 1"] = DIRTY
    result = gear.fill_slot("Weapon 1", "Fake Wand", _base_candidates=[])  # no base candidate: no attempt, the old fallback
    assert not result.kept_incumbent and not result.raw
    # a clean incumbent is still the fallback, and so is a forced one
    gear.current_raw["Weapon 1"] = CLEAN
    assert gear.fill_slot("Weapon 1", "Fake Wand", _base_candidates=[]).raw == CLEAN
    gear.forced_lines = {"Weapon 1": [ALL]}
    gear.current_raw["Weapon 1"] = DIRTY
    assert gear.fill_slot("Weapon 1", "Fake Wand", _base_candidates=[]).raw == DIRTY


def test_the_weapon_base_move_never_copies_the_all_gems_line_onto_another_base(monkeypatch) -> None:
    import junkroan.optimizer.improvement_loop as improvement_loop_module
    import junkroan.optimizer.item_bases as item_bases_module
    from junkroan.optimizer.pipeline import BuildResult
    from loop_fakes import loop_over

    import test_weapon_base_move as wbm

    dirty_raw = wbm.RAW + "{range:0.328}{tags:caster,gem}{prefix}" + ALL + "\n"

    class Pob(wbm._Pob):
        def craft_rare(self, base, **kwargs):
            out = super().craft_rare(base, **kwargs)
            return {**out, "raw": out["raw"] + "{range:0.328}{tags:caster,gem}{prefix}" + ALL + "\n"} if out["raw"] else out

    pob = Pob()
    loot = wbm._Loot(pob)
    loot.current_raw = {"Weapon 1": dirty_raw}
    skeleton = SimpleNamespace(rare_bases={"Weapon 1": "Low Base"}, uniques={})
    rails = SimpleNamespace(gear=SimpleNamespace(item_level=86, weapon_forbidden_lines=FORBIDDEN))
    pipeline = loop_over(pob, tree=None, gear=loot, skeleton=skeleton, objective=DPS, rails=rails)
    monkeypatch.setattr(item_bases_module, "bases_of_type", lambda _type, max_level: ["Low Base", "High Base"])
    monkeypatch.setattr(item_bases_module, "type_of", lambda value: "One Handed Sword" if "Base" in value else "")
    monkeypatch.setattr(improvement_loop_module, "type_of", lambda value: "One Handed Sword" if "Base" in value else "")
    result = BuildResult(skeleton=skeleton)
    TRACE.reset()
    pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=DPS.score({"CombinedDPS": 100.0}), min_gain=0.005,
        move_state=wbm._state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=wbm._judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: wbm._restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )
    counts = _counts()
    TRACE.reset()
    assert pob.crafts, "the move still crafted its candidates"
    assert not any(weapon_all_gems_raw("Weapon 1", raw, FORBIDDEN) for raw in pob.trials)
    assert counts.get("weapon-all-gems-level", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
