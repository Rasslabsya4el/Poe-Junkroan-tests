"""Time to full DPS (D39): derived from PoB's stack numbers, a ceiling in the rails."""

import pytest

from junkroan.optimizer.audit import audit_ailment_stack_caps, audit_stats
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.ramp import RampContext, ramp_budget, ramp_dps, ramp_seconds, stages_in_part, with_ramp


def _bleed(potential: float, max_stacks: float, duration: float = 5.0, dps: float = 800_000.0) -> dict:
    return {"BleedDPS": dps, "BleedStackPotential": potential, "BleedStacksMax": max_stacks, "BleedDuration": duration, "Speed": 1.2, "HitSpeed": 1.2}


def test_crimson_dance_on_a_slow_attack_ramps_for_seconds_a_plain_bleed_does_not() -> None:
    # 1.2 aps, 5 s bleeds, Crimson Dance: 6 bleeds applied per duration, all 6 needed -> 5 s to the steady state, 4 s to 80%
    slow = ramp_seconds(_bleed(potential=6 / 8, max_stacks=8), "BleedDPS", RampContext(fraction=0.8))
    assert abs(slow - 4.0) < 0.01
    # 2.5 aps: 12.5 bleeds per duration, 8 needed -> 3.2 s, 80% at 2.56 s (just above the 2.5 s rail)
    fast = ramp_seconds(_bleed(potential=12.5 / 8, max_stacks=8), "BleedDPS", RampContext(fraction=0.8))
    assert abs(fast - 2.56) < 0.01
    # no Crimson Dance: the first bleed is the steady state (one hit)
    plain = ramp_seconds(_bleed(potential=6.0, max_stacks=1), "BleedDPS", RampContext(fraction=0.8))
    assert abs(plain - 5 / 6 * 0.8) < 0.01


def test_poison_ramps_over_its_duration_and_hits_are_immediate() -> None:
    stats = {"TotalPoisonDPS": 500_000, "PoisonStacks": 16, "PoisonDuration": 2.0, "Speed": 8}
    assert abs(ramp_seconds(stats, "TotalPoisonDPS") - 1.6) < 0.01
    assert ramp_seconds({"TotalDPS": 1_000_000, "Speed": 3}, "TotalDPS") == 0.0
    # mixed: 70% hit, 30% poison under CombinedDPS -> 80% is reached before the poison is up
    mixed = {"CombinedDPS": 1_000_000, "TotalPoisonDPS": 300_000, "PoisonStacks": 16, "PoisonDuration": 2.0, "Speed": 8}
    assert 0 < ramp_seconds(mixed, "CombinedDPS") < 1.0
    assert ramp_seconds({"CombinedDPS": 0}, "CombinedDPS") is None


def test_pinnacle_ramp_projection_uses_the_same_component_model_at_its_budget() -> None:
    stats = {"TotalPoisonDPS": 500_000, "PoisonStacks": 16, "PoisonDuration": 8.0, "Speed": 2}
    assert ramp_dps(stats, "TotalPoisonDPS", 2.5) == pytest.approx(156_250)
    assert ramp_dps(stats, "TotalPoisonDPS", 10.0) == pytest.approx(500_000)


def test_stacked_parts_and_withered_per_hit_multiply_the_ramp() -> None:
    assert stages_in_part("10 Blades") == 10 and stages_in_part("Default") == 0 and stages_in_part(None) == 0
    stats = {"TotalDPS": 1_000_000, "Speed": 4.0, "HitSpeed": 10.0}  # Blade Vortex: 4 casts/s, blades hit faster
    assert abs(ramp_seconds(stats, "TotalDPS", RampContext(fraction=0.8, stages=10)) - 2.0) < 0.01
    withered = RampContext(fraction=0.8, withered_stacks=9, withered_per_hit=True)
    t = ramp_seconds({"TotalDPS": 1_000_000, "Speed": 5.0}, "TotalDPS", withered)
    assert 0 < t < 9 / 5  # 1.54x at 9 stacks: 80% of it needs ~4 stacks, not all 9


def test_the_ramp_floor_judges_only_a_stacked_skill_part_and_reports_the_rest() -> None:
    """D62 amendment: a slow ailment ramp is reported, not a cliff (bleed_perforate lost a
    647,425 Sand Stance to a 189,005 Blood one over 13% of budget). The floor keeps the one
    state no config count can hold at a partial value: the stacked skill part."""

    rails = Rails.load()
    obj = rails.objective(maximize="BleedDPS")
    assert ("RampBudget", "RampStages", 1.0) in obj.relations and not any(r[1] == "RampSeconds" for r in obj.relations)
    assert "RampSeconds" not in obj.stat_keys and "RampStages" not in obj.stat_keys and "BleedStackPotential" in obj.stat_keys
    good = {**_bleed(potential=25 / 8, max_stacks=8), "Life": 5000, "TotalEHP": 12000, "PhysicalMaximumHitTaken": 9000, "FireMaximumHitTaken": 30000, "ColdMaximumHitTaken": 30000, "LightningMaximumHitTaken": 30000, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "EffectiveMovementSpeedMod": 1.25, "NetLifeRegen": 0}
    slow = {**good, **_bleed(potential=6 / 8, max_stacks=8), "Speed": 1.0, "HitSpeed": 1.0, "BleedDuration": 6.0}  # 6 stacks over 6 s -> 4.8 s to 80%
    assert obj.score(good).feasible and obj.score(slow).feasible  # the bleed's own ramp is no floor any more
    assert any(f.check == "ramp" and f.severity == "error" and "RampSeconds = 4.8 > RampBudget = 2.5" in f.detail for f in audit_stats(slow, obj))
    assert not any(f.check == "ramp" for f in audit_stats(good, obj))
    # a stacked skill part is still a floor: 20 blades at 4 casts/s need 4 s of the 2.5 s budget
    blades = {**good, "Speed": 4.0, "HitSpeed": 10.0}
    assert with_ramp(obj, stages=10).score(blades).feasible and not with_ramp(obj, stages=20).score(blades).feasible
    assert any(f.check == "relation" and f.severity == "error" and "RampBudget = 2.5 < 1 x RampStages = 4.0" in f.detail for f in audit_stats(blades, with_ramp(obj, stages=20)))
    # the floor survives a change of the maximized stat and of the context
    hit = obj.replace(maximize="TotalDPS")
    assert hit.relations == obj.relations and all(d.context.stages == 10 for d in with_ramp(hit, stages=10).derived if d.name in ("RampSeconds", "RampBudget", "RampStages"))
    assert with_ramp(Objective(maximize="TotalDPS"), stages=10).derived == ()


def test_the_audit_rejects_an_ailment_override_above_the_budget_cap() -> None:
    obj = Rails.load().objective(maximize="BleedDPS")
    stats = {"BleedDPS": 10, "BleedStackPotential": 1, "BleedStacks": 8, "BleedStacksMax": 8, "BleedDuration": 5.1}
    xml = ('<PathOfBuilding><Config><ConfigSet title="Baseline">'
           '<Input name="overrideBleedStackPotential" number="8"/>'
           '</ConfigSet></Config></PathOfBuilding>')
    findings = audit_ailment_stack_caps(xml, stats, obj)
    assert len(findings) == 1 and findings[0].severity == "error" and "only 3 fit" in findings[0].detail


def test_the_audit_rejects_the_old_poison_damage_surrogate() -> None:
    obj = Rails.load().objective(maximize="TotalPoisonDPS")
    stats = {"TotalPoisonDPS": 10, "PoisonStacks": 8, "PoisonDuration": 5.1}
    xml = ('<PathOfBuilding><Config><ConfigSet title="Baseline">'
           '<CustomModifierBlock title="junkroan: poison stacks 3 of 8.00 inside 2.5 s" enabled="true">50% less Damage with Poison</CustomModifierBlock>'
           '</ConfigSet></Config></PathOfBuilding>')
    findings = audit_ailment_stack_caps(xml, stats, obj)
    assert len(findings) == 1 and findings[0].severity == "error"
    assert "PoisonStackLimit" in findings[0].detail


def test_the_audit_rejects_a_poison_effective_dps_count_above_the_cap() -> None:
    obj = Rails.load().objective(maximize="TotalPoisonDPS")
    stats = {"TotalPoisonDPS": 10, "PoisonStacks": 8, "PoisonDuration": 5.1}
    xml = ('<PathOfBuilding><Config><ConfigSet title="Baseline">'
           '<Input name="multiplierPoisonOnEnemy" number="8"/>'
           '<CustomModifierBlock title="junkroan: poison stacks 3 of 8.00 inside 2.5 s" enabled="true">Cannot Poison Enemies with at least 3 Poisons on them</CustomModifierBlock>'
           '</ConfigSet></Config></PathOfBuilding>')
    findings = audit_ailment_stack_caps(xml, stats, obj)
    assert len(findings) == 1 and findings[0].severity == "error"
    assert "effective DPS counts 8 stacks but only 3 fit" in findings[0].detail


def test_the_audit_accepts_a_readable_poison_custom_modifier() -> None:
    obj = Rails.load().objective(maximize="TotalPoisonDPS")
    stats = {"TotalPoisonDPS": 10, "PoisonStacks": 8, "PoisonDuration": 5.1}
    xml = ('<PathOfBuilding><Config><ConfigSet title="Baseline">'
           '<CustomModifierBlock title="junkroan: poison stacks 3 of 8.00 inside 2.5 s" enabled="true"># poison: 3 delivered stacks\n'
           'Cannot Poison Enemies with at least 3 Poisons on them</CustomModifierBlock>'
           '</ConfigSet></Config></PathOfBuilding>')
    assert audit_ailment_stack_caps(xml, stats, obj) == []


def test_poison_gets_its_own_budget_weighted_by_its_share() -> None:
    rails = Rails.load()
    obj = rails.objective()
    base = {"Life": 5000, "TotalEHP": 12000, "PhysicalMaximumHitTaken": 9000, "FireMaximumHitTaken": 30000, "ColdMaximumHitTaken": 30000, "LightningMaximumHitTaken": 30000, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "EffectiveMovementSpeedMod": 1.25, "NetLifeRegen": 0}
    viper = {**base, "CombinedDPS": 893_000, "TotalPoisonDPS": 815_000, "PoisonStacks": 18.4, "PoisonDuration": 5.4, "Speed": 3.4}
    ctx = RampContext(seconds=rails.ramp_seconds, seconds_by_component=dict(rails.ramp_seconds_by_component))
    budget = ramp_budget(viper, "CombinedDPS", ctx)
    assert abs(budget - (815 / 893 * 4.0 + 78 / 893 * 2.5)) < 0.01  # 3.87 s
    assert abs(ramp_budget({**base, "TotalDPS": 100, "CombinedDPS": 100}, "CombinedDPS", ctx) - 2.5) < 1e-9
    # the author's Viper Strike (4.2 s) is just over its budget: a warning in the report since the
    # D62 amendment, not an infeasible build; a 4.8 s poison (3.6 s to 80%) is inside it
    assert obj.score(viper).feasible
    assert [f.check for f in audit_stats(viper, obj)].count("ramp") == 1
    assert not any(f.check == "ramp" for f in audit_stats({**viper, "PoisonDuration": 4.5}, obj))
