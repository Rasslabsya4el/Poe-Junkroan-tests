"""#601: a day-1 shield carries a gem-level line under the weapon rule's conditions (rule 5, search-space rail)."""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from tests.test_wishlist_gear import FakePob, _mod, _rails, _tiers
from junkroan.optimizer.wishlist_gear import WishlistGear

GEM = "+1 to Level of all Cold Spell Skill Gems"


def _shield_mods() -> list[dict]:
    return [
        *_tiers("IncreasedLife", "Prefix", 8),
        *_tiers("FireResistance", "Suffix", 8, line="+(20-24)% to Fire Resistance"),
        *_tiers("ColdResistance", "Suffix", 8, line="+(20-24)% to Cold Resistance"),
        *_tiers("LightningResistance", "Suffix", 8, line="+(20-24)% to Lightning Resistance"),
        _mod("ColdSpellGems", "Prefix", mod_id="cold", weight=250, line=GEM, tags=("cold", "caster", "gem")),
        _mod("Ordinary", "Prefix", weight=66_910),
    ]


def _fill(gem_worth: float, slot: str = "Weapon 2", base: str = "Fake Shield"):
    gear = WishlistGear(FakePob(_shield_mods(), worth={"cold": gem_worth, "Ordinary": 50_000}),
                        Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments[slot] = "fire"
    return gear.fill_slot(slot, base)


def test_a_day1_shield_may_take_a_gem_level_line_and_it_takes_the_whole_shield() -> None:
    TRACE.reset()
    result = _fill(100_000)  # gem-only 100,000 beats the whole ordinary shield (Life + Fire Resistance + Ordinary 50,000)
    assert result.mod_ids == ["cold"]  # exactly the gem line: no IncreasedLife, no resistance, no other line
    assert result.gem_level_trials and result.gem_level_trials[0]["kept"] is True
    assert result.rolled == 1 and result.extra_resistance is None
    assert not any(entry["kind"] in {"life", "resistance_fixed", "extra_resistance"} for entry in result.shopping)
    assert "IncreasedLife" not in result.raw and "FireResistance" not in result.raw


def test_the_shield_gem_line_obeys_the_same_beats_ordinary_condition_as_a_weapon() -> None:
    result = _fill(10_000)  # worth less than the open line's ordinary mod: never picked
    assert "cold" not in result.mod_ids
    assert [mod.group for mod in result.affixes[:2]] == ["IncreasedLife", "FireResistance"]  # the ordinary shield keeps its fixed lines
    assert "Ordinary" in result.mod_ids


def test_the_gem_shield_is_measured_against_the_whole_ordinary_shield_not_the_bare_open_line() -> None:
    # Ordinary shield = Life (30,000) + Fire Resistance (30,000) + Ordinary (50,000) = 110,000 (+1,000 base);
    # a gem worth 100,000 is above the open line alone (50,000) but below the whole ordinary shield: it loses.
    gear = WishlistGear(FakePob(_shield_mods(), worth={"cold": 100_000, "Ordinary": 50_000, "IncreasedLife3": 30_000, "FireResistance3": 30_000}),
                        Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments["Weapon 2"] = "fire"
    result = gear.fill_slot("Weapon 2", "Fake Shield")
    assert result.gem_level_trials and result.gem_level_trials[0]["kept"] is False
    assert "cold" not in result.mod_ids and len(result.affixes) == 3
    assert [mod.group for mod in result.affixes[:2]] == ["IncreasedLife", "FireResistance"] and "Ordinary" in result.mod_ids


def test_trace_counts_a_shield_with_a_gem_level_line_as_generated_and_evaluated() -> None:
    from junkroan.optimizer import trace

    shield = "Rarity: Rare\nMind Emblem\nHarmonic Spirit Shield\n"
    assert "shield-gem-level" in trace.classify({"item": {"slot": "Weapon 2", "raw": shield + GEM}})
    assert "shield-gem-level" not in trace.classify({"item": {"slot": "Weapon 2", "raw": shield + "+(20-24)% to Fire Resistance"}})
    assert "shield-gem-level" not in trace.classify({"item": {"slot": "Weapon 1", "raw": "Rarity: Rare\nX\nOpal Wand\n" + GEM}})
    TRACE.reset()
    TRACE.add_generated(trace.classify({"item": {"slot": "Weapon 2", "raw": shield + GEM}}))
    TRACE.add_evaluated(trace.classify({"item": {"slot": "Weapon 2", "raw": shield + GEM}}))
    counts = TRACE._pending["shield-gem-level"]
    assert counts["generated"] > 0 and counts["evaluated"] > 0


def test_classify_a_shield_with_a_gem_line_and_another_line_is_shield_gem_level_with_other() -> None:
    from junkroan.optimizer import trace

    shield = "Rarity: Rare\nMind Emblem\nHarmonic Spirit Shield\n"
    other = "shield-gem-level-with-other"
    assert other in trace.classify({"item": {"slot": "Weapon 2", "raw": shield + GEM + "\n+(20-24)% to Fire Resistance"}})
    assert other not in trace.classify({"item": {"slot": "Weapon 2", "raw": shield + GEM}})
    assert other not in trace.classify({"item": {"slot": "Weapon 2", "raw": shield + "+(20-24)% to Fire Resistance"}})
    assert other not in trace.classify({"item": {"slot": "Weapon 1", "raw": "Rarity: Rare\nX\nOpal Wand\n" + GEM + "\n+1 a"}})
    real = shield + "Item Level: 84\nQuality: 20\nImplicits: 1\n+10% to Fire Resistance\n" + GEM
    assert other not in trace.classify({"item": {"slot": "Weapon 2", "raw": real}})  # the implicit is not a generated line
    assert other in trace.classify({"item": {"slot": "Weapon 2", "raw": real + "\n+80 to maximum Life"}})


class _RecordingPob(FakePob):
    """FakePob that keeps every raw sent to a trial (the PoB boundary the trace counts at)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.trial_raws: list[str] = []

    def trial_stats(self, trials, keys, mode="fast"):
        self.trial_raws.extend(trial["item"]["raw"] for trial in trials)
        return super().trial_stats(trials, keys, mode)


def _with_gem_tokens(raws: list[str]) -> list[list[str]]:
    return [raw.split("|")[1:] for raw in raws if "cold" in raw.split("|")]


def test_no_trial_ever_puts_a_gem_level_line_on_a_shield_beside_another_line() -> None:
    # #601 unit 3: the open line's candidate pool was tried on top of the placed Life + resistance lines, so every
    # gem candidate reached PoB as Life + resistance + gem (trace class shield-gem-level-with-other: 16 of 17 on cold_dot).
    for worth in ({"cold": 100_000, "Ordinary": 50_000}, {"cold": 10_000, "Ordinary": 50_000}):
        pob = _RecordingPob(_shield_mods(), worth=worth)
        gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails())
        gear._resistance_assignments["Weapon 2"] = "fire"
        gear.fill_slot("Weapon 2", "Fake Shield")
        gem_trials = _with_gem_tokens(pob.trial_raws)
        assert gem_trials, "the gem line is still tried"
        assert all(tokens == ["cold"] for tokens in gem_trials), gem_trials



# -- #601 unit 4: the joint kick's headroom ranking rolls random shields ------------------------------------------

SHIELD_BASE = "Vaal Spirit Shield"


def _roll(*mods: str) -> dict:
    return {"raw": f"Rarity: Rare\nDoom Wall\n{SHIELD_BASE}\nItem Level: 80\nImplicits: 0\n" + "\n".join(mods)}


def test_the_headroom_ranking_never_sends_a_shield_roll_with_a_gem_level_line_beside_another_line() -> None:
    # _joint_round ranks its victim slots by `_slots_with_damage_headroom`, which rolls random rares of every rare slot
    # and trials them at PoB: a random shield with "+1 to Level of all Cold Spell Skill Gems" and a Life line reached PoB
    # (the kick-joint draw's shield-gem-level-with-other 11 of 11 on cold_dot, 27 of 28 on summon_raging_spirits).
    from loop_fakes import _Loot, _Pob, _skeleton, loop_over

    class RollPob(_Pob):
        def __init__(self, *a, **k) -> None:
            super().__init__(*a, **k)
            self.trialled: list[dict] = []

        def random_rares(self, base, **kwargs):
            return [_roll(GEM, "+80 to maximum Life"), _roll(GEM), _roll("+80 to maximum Life", "+(20-24)% to Fire Resistance")]

        def trial_stats(self, trials, keys, mode="fast"):
            self.trialled.extend(trials)
            for trial in trials:
                TRACE.count_trial(trial)
            return []

    TRACE.reset()
    pob = RollPob(1000.0)
    loot = _Loot(pob, {})
    skeleton = _skeleton({"Weapon 2": SHIELD_BASE})
    loop_over(pob, tree=None, gear=loot, skeleton=skeleton).headroom(skeleton, loot, ["Weapon 2"], 5, 1)
    counts: dict[str, dict[str, int]] = {}
    for moves in TRACE.considered().values():
        for name, n in moves.items():
            acc = counts.setdefault(name, {"generated": 0, "evaluated": 0})
            acc["generated"] += n.get("generated", 0)
            acc["evaluated"] += n.get("evaluated", 0)
    other = counts.get("shield-gem-level-with-other", {"generated": 0, "evaluated": 0})
    assert other == {"generated": 0, "evaluated": 0}, other
    assert counts["shield-gem-level"]["evaluated"] > 0  # the gem-only roll is still ranked
    assert len(pob.trialled) == 2  # the gem-only roll and the ordinary roll
