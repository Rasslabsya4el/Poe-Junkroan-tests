"""A ramp-type config number is arithmetic (D62 amendment): the count the build's own rates
reach inside the ramp budget, capped by the skill's own maximum. Never a ceiling typed in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.ramp_inputs import (
    BuildFacts,
    Gem,
    apply_ailment_stack_caps,
    apply_custom_mods,
    corpses_consumed_recently,
    note_param,
    perforate_spike_overlap,
    poisons_applied_recently,
    pride_ramp_mod,
    poison_stack_limit_mod,
    rage_stacks,
    ramped_input,
    reached,
    sigil_of_power_stages,
    stack_option,
    withered_stacks,
)
from junkroan.optimizer.ramp import ailment_stacks
from junkroan.pob import skill_facts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not skill_facts._blocks(), reason="PoB skill data not present (vendor/pob/source or the pinned runtime)")


def _facts(**stats) -> BuildFacts:
    gems = stats.pop("gems", ())
    return BuildFacts(stats=stats, budget=stats.pop("budget", 2.5), gems=gems, main_effect_id=stats.pop("main", ""), stance=stats.pop("stance", ""), text=stats.pop("text", ""))


def test_the_count_reached_is_floored_and_capped() -> None:
    assert reached(3.2, 2.5) == 8 and reached(3.2, 2.5, cap=4) == 4
    assert reached(0.3, 2.5) == 0 and reached(0.0, 2.5, cap=10) == 0 and reached(2.0, 0.0) == 0
    assert reached(0.4, 2.5, cap=4) == 1  # exactly one, no floating-point crumb


def test_stacking_ailments_hold_only_whole_stacks_reached_inside_the_budget() -> None:
    # Crimson Dance: 8 max, 1.6 applied/s, 5.1 s duration. The native PoB
    # override takes an integer, so 4 stacks are counted after 2.5 s, not 4.0
    # rounded up and never the 8-stack steady state.
    bleed = ailment_stacks({"BleedDPS": 1, "BleedStacksMax": 8, "BleedStackPotential": 8.16 / 8, "BleedDuration": 5.1}, 2.5)["bleed"]
    assert bleed.steady == pytest.approx(8) and bleed.rate == pytest.approx(1.6) and bleed.counted == 4 and bleed.limited
    # A shorter duration reaches its own steady state before the budget; no
    # native override or poison reduction is needed.
    short = ailment_stacks({"BleedDPS": 1, "BleedStacksMax": 8, "BleedStackPotential": 3.2 / 8, "BleedDuration": 2.0}, 2.5)["bleed"]
    assert short.steady == pytest.approx(3.2) and short.counted == 3 and not short.limited
    assert ailment_stacks({}, 2.5) == {}


def test_poison_stack_limit_is_the_count_pob_enforces() -> None:
    line, title, why = poison_stack_limit_mod(counted=4, steady=8, budget=2.5)
    assert line == "Cannot Poison Enemies with at least 4 Poisons on them"
    assert title == "junkroan: poison stacks 4 of 8.00 inside 2.5 s"
    assert "PoisonStackLimit" in why
    assert poison_stack_limit_mod(counted=8, steady=8, budget=2.5) is None


@needs_skill_data
def test_the_gem_numbers_come_from_pobs_own_skill_data() -> None:
    assert skill_facts.level_stat("SigilOfPower", "base_circle_of_power_mana_spend_per_upgrade", 18) == 379
    assert skill_facts.level_stat("SigilOfPower", "base_circle_of_power_mana_spend_per_upgrade", 20) == 400
    assert skill_facts.constant_stat("SigilOfPower", "circle_of_power_max_stages") == 4
    assert skill_facts.cast_time_seconds("Wither") == 0.28
    assert skill_facts.constant_stat("Perforate", "blood_spears_base_number_of_spears") == 7  # not the qualityStats 0.1
    assert skill_facts.level_stat("Pride", "physical_damage_aura_nearby_enemies_physical_damage_taken_+%", 18) == 19
    assert skill_facts.level_stat("Pride", "physical_damage_aura_nearby_enemies_physical_damage_taken_+%_max", 20) == 39


@needs_skill_data
def test_sigil_of_power_stages_come_from_mana_spent_per_second() -> None:
    # 54 mana x 3.2 casts/s = 173 mana/s, 379 per stage at level 18: 1 stage inside 2.5 s, not the ceiling
    gem = (Gem("sigil of power", "SigilOfPower", 18),)
    value, why = sigil_of_power_stages(BuildFacts(stats={"ManaCost": 54, "Speed": 3.2}, budget=2.5, gems=gem), cap=4.0)
    assert value == 1 and "379 per stage" in why and "1 of 4" in why
    # an Archmage-sized cost fills the sigil inside the budget (the user's arc_archmage remark)
    fast, _why = sigil_of_power_stages(BuildFacts(stats={"ManaCost": 600, "Speed": 4.0}, budget=2.5, gems=gem), cap=4.0)
    assert fast == 4
    none, why = sigil_of_power_stages(BuildFacts(stats={"ManaCost": 0, "Speed": 4.0}, budget=2.5, gems=gem), cap=4.0)
    assert none == 0 and why.startswith("off:")


def test_a_stack_option_builds_one_stack_per_cast() -> None:
    value, why = stack_option("intensifyIntensity", "# of Intensity", 4.0, _facts(Speed=6.5))
    assert value == 4 and "of 4" in why  # 6.5 casts/s: the cap inside the budget
    slow, _why = stack_option("frostShieldStages", "Stages", 8.0, _facts(Speed=1.1))
    assert slow == 2  # 1.1 casts/s x 2.5 s
    assert stack_option("intensifyIntensity", "# of Intensity", None, _facts(Speed=6.5)) is None


@needs_skill_data
def test_withered_stacks_come_from_the_casters_and_the_gems_cast_time() -> None:
    totem = Gem("wither", "Wither", 18, ("spell totem", "multiple totems"))
    value, why = withered_stacks(BuildFacts(stats={"ActiveTotemLimit": 2}, budget=2.5, gems=(totem,)))
    assert value == 15 and "0.28" in why and "2 totems" in why  # 2 totems x 1/0.28 s = 7.1 stacks/s
    one = Gem("wither", "Wither", 18)
    assert withered_stacks(BuildFacts(stats={}, budget=2.5, gems=(one,)))[0] == 8  # hand cast: 3.57 stacks/s
    assert withered_stacks(BuildFacts(stats={}, budget=1.0, gems=(one,)))[0] == 3
    hits, why = withered_stacks(_facts(HitSpeed=3.0))  # Withering Touch: one stack per hit
    assert hits == 7 and "per hit" in why
    # the optimistic lane runs the same arithmetic with all the time in the world: the cap
    from junkroan.optimizer.ramp_inputs import ramped_input

    assert ramped_input("multiplierWitheredStackCount", BuildFacts(stats={}, budget=2.5, gems=(one,)), optimistic=True)[0] == 15
    assert ramped_input("multiplierPoisonAppliedRecently", _facts(PoisonStacks=30, PoisonDuration=2.0), optimistic=True)[0] == 60  # 15/s over the 4 s window
    # ... except where a researched fact caps what the lane may claim: no more than about three
    # Blood Stance spikes reach one boss, however many the gem makes (pending fact
    # `perforate.max_overlap_on_boss`, tests/test_pending_facts.py)
    assert ramped_input("perforateSpikeOverlap", _facts(stance="BLOOD"), optimistic=True)[0] == 3


def test_poisons_applied_recently_use_pobs_own_application_rate() -> None:
    value, why = poisons_applied_recently(_facts(PoisonStacks=30, PoisonDuration=2.0))
    assert value == 37 and "the ramp budget" in why  # 15 poisons/s x 2.5 s, not the 4 s window
    chance, why = poisons_applied_recently(_facts(HitSpeed=4.0, PoisonChance=60.0))
    assert chance == 6 and "poison chance" in why
    assert poisons_applied_recently(_facts(Speed=4.0)) is None


@needs_skill_data
def test_corpses_consumed_are_halved_while_the_player_casts_both_skills() -> None:
    gems = (Gem("volatile dead", "VolatileDead", 18), Gem("desecrate", "Desecrate", 18))
    hand = BuildFacts(stats={"Speed": 3.0}, budget=2.5, gems=gems, main_effect_id="VolatileDead")
    value, why = corpses_consumed_recently(hand)
    assert value == 11 and "share the casting time" in why  # 3 casts/s x 3 corpses x 0.5 x 2.5 s
    auto = BuildFacts(stats={"Speed": 3.0}, budget=2.5, gems=gems, main_effect_id="VolatileDead", triggered=True)
    assert corpses_consumed_recently(auto)[0] == 22
    assert corpses_consumed_recently(BuildFacts(stats={"Speed": 3.0}, budget=2.5, gems=gems[:1], main_effect_id="VolatileDead")) is None
    assert corpses_consumed_recently(BuildFacts(stats={"Speed": 3.0}, budget=2.5, gems=gems, main_effect_id="Fireball")) is None


@needs_skill_data
def test_perforate_overlap_is_a_spike_count_and_a_stance() -> None:
    assert note_param("perforate.overlapping_spikes_on_one_target", "overlaps_blood_stance") == 1
    assert perforate_spike_overlap(_facts(stance="BLOOD"))[0] == 1
    assert perforate_spike_overlap(_facts(stance="SAND"))[0] == 0
    assert perforate_spike_overlap(_facts())[0] == 1  # PoB's default stance is Blood


@needs_skill_data
def test_pride_is_judged_at_the_value_its_ramp_reaches_inside_the_budget() -> None:
    facts = BuildFacts(stats={}, budget=2.5, gems=(Gem("pride", "Pride", 18),))
    line, title, why = pride_ramp_mod(facts)
    # level 18: 19% -> 38%; at 2.5 s of the 4 s ramp 30.9% is reached, 9.98% more on top of PoB's MIN,
    # rounded down to the whole percent PoB's mod parser accepts (a "9.98%" line parses as unsupported)
    assert line == "Nearby Enemies take 9% more Physical Damage" and title == "junkroan: Pride at 2.5 s of a 4 s ramp"
    assert "MIN" in why and "MAX" in why
    full = pride_ramp_mod(BuildFacts(stats={}, budget=8.0, gems=(Gem("pride", "Pride", 20),)))
    assert full[0] == "Nearby Enemies take 16% more Physical Damage"  # the whole ramp: 19% -> 39%
    assert pride_ramp_mod(BuildFacts(stats={}, budget=2.5)) is None
    assert pride_ramp_mod(BuildFacts(stats={}, budget=0.1, gems=(Gem("pride", "Pride", 18),))) is None  # nothing to add


@pytest.mark.pob
@needs_pob
def test_bleed_perforate_picks_sand_stance_once_the_ramp_is_not_a_cliff(tmp_path: Path) -> None:
    """The measured cliff (docs/readings/2026-09-18-frozen-campaigns-part2.md): the tuner tried Sand
    Stance, PoB scored it 647,425 against Blood's 189,005, and the ramp floor -- 13% over budget in
    Sand, from the bleed stacking -- made the 3.4x weaker Blood the only feasible choice. With the
    counts derived inside the budget and the floor left to the one state no count can hold, Sand is
    feasible and wins; Pride (MAX in that export) is judged at the value its 4 s ramp reaches in
    2.5 s, so the number was 601,832, not 647,425; with rage derived the same way (one "Gain 1
    Rage on Melee Hit" node x 1.15 hits/s x 2.5 s = 2 of 30, where the export typed 15) it is
    480,654."""

    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.optimizer.judging import tune_choices, write_lanes
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "generated" / "bleed_perforate-s3.pob.txt").read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    with PobSession(run_id="test-ramp-perforate", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        pipe = BuildPipeline(pob, Rails.load())
        pipe.objective = objective_for(pipe.rails, skeleton.main_link[0], pipe.objective, mode=skeleton.mode)
        derived = derive_config(pob, prefer_rules=True)
        assert derived.custom_mods == [("Nearby Enemies take 9% more Physical Damage", "junkroan: Pride at 2.5 s of a 4 s ramp")]
        assert derived.conservative.inputs["prideEffect"] == "MIN" and derived.optimistic.inputs["prideEffect"] == "MAX"
        assert "prideEffect" not in derived.choices and derived.choices["bloodSandStance"] == ["BLOOD", "SAND"]
        write_lanes(pob, skeleton, derived, log=pipe.log)
        chosen = tune_choices(pob, skeleton, derived, objective=pipe.objective,
                              write=lambda sk, lanes: write_lanes(pob, sk, lanes, log=pipe.log), log=pipe.log, guard=False)

        assert chosen["bloodSandStance"] == "SAND"
        stats = pob.stats(pipe.objective.stat_keys)
        score = pipe.objective.score(stats)
        # D78 reduces Crimson Dance from the old 8-stack steady state to the
        # stacks actually reached inside the ramp budget. Sand remains the PoB
        # winner, now at its delivered rather than steady-state bleed number.
        assert 300_000 < score.value < 400_000
        values = pipe.objective.derived_values(stats)
        assert values["RampSeconds"] <= values["RampBudget"]  # D78 writes the delivered bleed stacks inside the budget
        assert values["RampStages"] is None  # Perforate has no stacked skill part


@pytest.mark.pob
@needs_pob
def test_poison_stack_limit_caps_stacks_without_changing_hit_dps(tmp_path: Path) -> None:
    """PoB's parsed PoisonStackLimit stops applications at the delivered count.

    Unlike the old whole-percent surrogate, the cap changes `PoisonStacks`
    itself, so modifiers that count poisons on the enemy see the same state.
    """

    from junkroan.optimizer.config_rules import derive_config
    from junkroan.optimizer.judging import write_lanes
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml

    xml = decode_import_code((FIXTURES / "poison_spectral_throw.pob.txt").read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    with PobSession(run_id="test-d78-poison", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        pipe = BuildPipeline(pob, Rails.load())
        derived = derive_config(pob, prefer_rules=True)
        poison = derived.ailment_stack_caps["poison"]
        line, _title = next(block for block in derived.custom_mods if "Cannot Poison Enemies" in block[0])
        assert pob.parse_mods([line])[0]["mods"][0]["name"] == "PoisonStackLimit"
        assert derived.conservative.inputs.get("multiplierPoisonOnEnemy", poison.counted) <= poison.counted
        skeleton.user_config["multiplierPoisonOnEnemy"] = 99
        write_lanes(pob, skeleton, derived, log=pipe.log)
        write_lanes(pob, skeleton, derived, log=pipe.log)
        assert pob.export_xml().count("Cannot Poison Enemies with at least") == 1
        assert pob.config_inputs()["multiplierPoisonOnEnemy"] == poison.counted
        from junkroan.optimizer.ramp_inputs import apply_custom_mods

        apply_custom_mods(pob, [], replace_ailment_stacks=True)
        before = pob.stats(("PoisonStacks", "PoisonDPS", "TotalPoisonDPS", "CombinedDPS", "TotalDPS"))
        apply_custom_mods(pob, [block for block in derived.custom_mods if "Cannot Poison Enemies" in block[0]], replace_ailment_stacks=True)
        after = pob.stats(("PoisonStacks", "PoisonDPS", "TotalPoisonDPS", "CombinedDPS", "TotalDPS"))
        assert poison.counted < poison.steady
        assert after["PoisonStacks"] == pytest.approx(poison.counted)
        assert after["PoisonDPS"] == pytest.approx(before["PoisonDPS"])
        assert after["TotalPoisonDPS"] / before["TotalPoisonDPS"] == pytest.approx(poison.counted / before["PoisonStacks"], rel=0.01)
        assert after["TotalDPS"] == pytest.approx(before["TotalDPS"])


def test_custom_modifiers_are_written_into_the_baseline_set_only() -> None:
    class _Pob:
        def __init__(self) -> None:
            self.xml = ('<PathOfBuilding><Config activeConfigSet="1"><ConfigSet title="Baseline" id="1">'
                        '<Input name="enemyIsBoss" string="Pinnacle"/></ConfigSet>'
                        '<ConfigSet title="Conditional" id="2"/></Config></PathOfBuilding>')

        def export_xml(self) -> str:
            return self.xml

        def load_xml(self, xml: str) -> None:
            self.xml = xml

    pob = _Pob()
    apply_custom_mods(pob, [("Nearby Enemies take 9.98% more Physical Damage", "junkroan: Pride")])
    assert pob.xml.count("CustomModifierBlock") == 2  # one block: open and close
    assert pob.xml.index("CustomModifierBlock") < pob.xml.index('title="Conditional"')  # the conservative lane only
    assert "# conservative Pride\nNearby Enemies take 9.98% more Physical Damage" in pob.xml
    apply_custom_mods(pob, [("Nearby Enemies take 5.00% more Physical Damage", "junkroan: Pride")])
    assert pob.xml.count("CustomModifierBlock") == 2 and "5.00%" in pob.xml and "9.98%" not in pob.xml  # replaced, not stacked
    apply_custom_mods(pob, [])
    assert "5.00%" in pob.xml  # nothing to write: the build is left alone


@pytest.mark.pob
@needs_pob
def test_readable_custom_modifier_has_the_same_pob_stats_as_the_legacy_one_line_form(tmp_path: Path) -> None:
    """PoB ignores the standalone explanation comment rather than treating it as a mod."""

    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "generated" / "bleed_perforate-s3.pob.txt").read_text(encoding="utf-8").strip())
    line, title = "Nearby Enemies take 9% more Physical Damage", "junkroan: custom-mod-format"
    with PobSession(run_id="test-custom-mod-format", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        apply_custom_mods(pob, [(line, title)])
        readable = pob.export_xml()
        legacy = readable.replace("# conservative custom-mod-format\n", "")
        pob.load_xml(legacy)
        before = pob.stats(("CombinedDPS", "FullDPS", "Life", "TotalEHP"))
        pob.load_xml(readable)
        after = pob.stats(("CombinedDPS", "FullDPS", "Life", "TotalEHP"))
    assert "# conservative custom-mod-format\nNearby Enemies take 9% more Physical Damage" in readable
    assert after == before


def test_native_ailment_stack_caps_are_written_into_the_baseline_set_only() -> None:
    class _Pob:
        def __init__(self) -> None:
            self.xml = ('<PathOfBuilding><Config activeConfigSet="1"><ConfigSet title="Baseline" id="1">'
                        '<Input name="overrideBleedStackPotential" number="8"/></ConfigSet>'
                        '<ConfigSet title="Conditional" id="2"><Input name="overrideBleedStackPotential" number="8"/></ConfigSet>'
                        '</Config></PathOfBuilding>')

        def export_xml(self) -> str:
            return self.xml

        def load_xml(self, xml: str) -> None:
            self.xml = xml

    pob = _Pob()
    apply_ailment_stack_caps(pob, {"overrideBleedStackPotential": 4, "multiplierBleedsOnEnemy": 4})
    baseline, conditional = pob.xml.split('title="Conditional"')
    assert 'overrideBleedStackPotential" number="4"' in baseline and 'multiplierBleedsOnEnemy" number="4"' in baseline
    assert 'overrideBleedStackPotential' not in conditional and 'multiplierBleedsOnEnemy' not in conditional
    apply_ailment_stack_caps(pob, {})
    assert 'overrideBleedStackPotential' not in pob.xml and 'multiplierBleedsOnEnemy' not in pob.xml


def test_no_ailment_stack_cap_leaves_an_unrelated_config_byte_identical() -> None:
    class _Pob:
        def __init__(self) -> None:
            self.xml = ('<PathOfBuilding><Config><ConfigSet title="Baseline">'
                        '<Input name="multiplierBleedsOnEnemy" number="8"/></ConfigSet>'
                        '<ConfigSet title="Conditional"/></Config></PathOfBuilding>')

        def export_xml(self) -> str:
            return self.xml

        def load_xml(self, xml: str) -> None:
            self.xml = xml

    pob = _Pob()
    before = pob.xml
    apply_ailment_stack_caps(pob, {})
    assert pob.xml == before


def test_rage_on_hit_is_the_builds_hit_rate_throttled_to_one_hit_per_half_second() -> None:
    # Berserker: "Gain 1 Rage on Attack Hit" at 4 hits/s: PoB's own reminder says one hit per 0.5 s
    # gains rage, so 2/s x 2.5 s = 5 of 50, not 10 and never the rails' 25
    facts = _facts(MaximumRage=50, Speed=4.0, text="gain 1 rage on attack hit\n(only one hit every 0.5 seconds can cause you to gain rage)")
    value, why = rage_stacks(facts)
    assert value == 5 and "2.00 hits/s" in why and "one hit per 0.5 s" in why
    # a slow attacker is not throttled: 1.2 hits/s x 2 rage (two nodes, each a source) x 2.5 s = 6
    facts = _facts(MaximumRage=50, Speed=1.2, text="gain 1 rage on melee hit\ngain 1 rage on melee hit")
    assert rage_stacks(facts)[0] == 6
    # the optimistic lane has all the time it wants: the cap
    assert ramped_input("multiplierRage", facts, optimistic=True)[0] == 50


def test_rage_sources_the_boss_lane_cannot_count_stay_off() -> None:
    text = "gain 5 rage when you kill an enemy\ngain 3 rage when hit by an enemy\ngain 5 rage on hit with retaliation skills\ngain 10 rage when you use a life flask"
    facts = _facts(MaximumRage=50, Speed=3.0, text=text)
    value, why = rage_stacks(facts)
    assert value == 0 and why.startswith("off:") and "no kills on a boss" in why
    assert ramped_input("multiplierRage", facts) == (None, why)
    # kills exist in the optimistic lane's long fight: the cap; the others still count for nothing there
    assert ramped_input("multiplierRage", facts, optimistic=True)[0] == 50
    assert ramped_input("multiplierRage", _facts(MaximumRage=50, Speed=3.0, text="gain 3 rage when hit by an enemy"), optimistic=True) == (None, "off: gain 3 rage when hit by an enemy (the boss's hit rate is not in PoB)")
    assert rage_stacks(_facts(Speed=3.0, text="gain 1 rage on attack hit")) is None  # PoB shows no maximum: the input is not this build's


@needs_skill_data
def test_rage_support_warcries_mana_and_crit_are_rates_too() -> None:
    # Rage Support on the main link: PoB's constant 3 per attack hit, throttled to 2 hits/s: 6/s x 2.5 = 15
    gems = (Gem("cyclone", "Cyclone", 18, supports=("rage", "melee physical damage")),)
    value, why = rage_stacks(_facts(MaximumRage=50, Speed=6.0, gems=gems, main="Cyclone"))
    assert value == 15 and "3 rage per attack hit" in why
    # a warcry: one use inside the budget (10 rage), then one per its 8 s cooldown (PoB gem data)
    gems = (Gem("enduring cry", "EnduringCry", 18),)
    value, why = rage_stacks(_facts(MaximumRage=50, Speed=1.0, gems=gems, text="gain 10 rage when you use a warcry"))
    assert value == 10 + 3 and "8 s cooldown" in why  # 10 flat + 10/8 per second x 2.5 s = 3.125
    assert rage_stacks(_facts(MaximumRage=50, Speed=1.0, text="gain 10 rage when you use a warcry"))[0] == 0  # no warcry gem
    # "after spending a total of 200 mana": 40 mana x 5 casts/s = 200/s -> 9 rage per second x 2.5 s = 22
    value, why = rage_stacks(_facts(MaximumRage=50, ManaCost=40.0, Speed=5.0, text="gain 9 rage after spending a total of 200 mana"))
    assert value == 22 and "200 mana/s" in why
    # crit: 4 hits/s x 50% crit = 2 crits/s (at the throttle) x 1 rage x 2.5 s = 5
    assert rage_stacks(_facts(MaximumRage=50, Speed=4.0, CritChance=50.0, text="gain 1 rage on critical strike with attacks"))[0] == 5
    # PoB's own signed regeneration (Chainbreaker regenerates, "Lose 2 Rage per second" drains) and the skill's rage cost
    assert rage_stacks(_facts(MaximumRage=50, Speed=2.0, RageRegenRecovery=4.0, text="gain 1 rage on melee hit"))[0] == 15  # (2 + 4) x 2.5
    assert rage_stacks(_facts(MaximumRage=50, Speed=2.0, RageRegenRecovery=-2.0, RageCost=1.0, text="gain 3 rage on melee hit"))[0] == 5  # (6 - 2 - 2) x 2.5
