"""The floors the user's 2026-09-18 reading added to the objective (docs/readings/
2026-09-18-frozen-campaigns-part1.md and part2.md): hit chance on attack builds, full sustain
on channelled skills, no degen while idle, and Mind over Matter's unreserved mana.

No PoB: every rule is a floor over stats, so it is measured on stat dictionaries.
"""

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.objective import ELEMENTAL_RESIST_RELATIONS
from junkroan.optimizer.objective_select import HIT_CHANCE_FLOOR, maximized_stat, objective_for, with_skill_floors
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.castability import MANA_COST_POOL_STAT

FEASIBLE = {  # a build that misses nothing the rails ask for
    "CombinedDPS": 500_000, "Life": 5000, "TotalEHP": 12000, "PhysicalMaximumHitTaken": 9000,
    "FireMaximumHitTaken": 30000, "ColdMaximumHitTaken": 30000, "LightningMaximumHitTaken": 30000,
    "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "EffectiveMovementSpeedMod": 1.25,
    "NetLifeRegen": 100, "NetEnergyShieldRegen": 0, "Mana": 1000, "ManaUnreserved": 400, "HitChance": 100,
}


def _sustain(objective: Objective) -> dict[str, float]:
    return {r[0]: float(r[2]) for r in objective.relations if "PerSecond" in r[1]}


def test_an_attack_build_keeps_hit_chance_at_95() -> None:
    """The user's rail (kinetic_bolt_wander s1 at 83%): below 95 an attack build misses too often
    to play. Spells have no accuracy to buy and are not floored."""

    rails = Rails.load()
    attack = objective_for(rails, "Kinetic Bolt")
    spell = objective_for(rails, "Spark")
    assert attack.floors["HitChance"] == HIT_CHANCE_FLOOR == 95.0
    assert "HitChance" not in spell.floors and "HitChance" in attack.stat_keys

    assert attack.score({**FEASIBLE, "HitChance": 96}).feasible
    bad = attack.score({**FEASIBLE, "HitChance": 83})
    assert not bad.feasible and abs(bad.violation - (95 - 83) / 95) < 1e-9
    assert spell.score({**FEASIBLE, "HitChance": 83}).feasible  # not the spell's gate


def test_elemental_resists_follow_pobs_current_maximums() -> None:
    """A maximum-resistance modifier raises the cap the rail must fill, rather
    than leaving the old fixed 75 floor behind."""

    obj = Rails.load().objective()
    assert all(relation in obj.relations for relation in ELEMENTAL_RESIST_RELATIONS)
    assert not {"FireResist", "ColdResist", "LightningResist"} & set(obj.floors)
    capped = {**FEASIBLE, "FireResistMax": 80, "ColdResistMax": 76, "LightningResistMax": 75,
              "FireResist": 79, "ColdResist": 76, "LightningResist": 75}
    assert not obj.score(capped).feasible
    assert obj.violations(capped)["FireResist>=FireResistMax"] == 1 / 80
    assert obj.score({**capped, "FireResist": 80}).feasible


def test_main_skill_cost_relations_stay_live_and_use_the_eb_pool() -> None:
    obj = Rails.load().objective()
    mana_relation = (MANA_COST_POOL_STAT, "ManaCost", 1.0, "Mana")
    life_relation = ("LifeUnreserved", "LifeCost", 1.0, "Life")

    assert mana_relation in obj.relations and life_relation in obj.relations
    assert mana_relation in obj.without_sustain().relations
    stats = {"CombinedDPS": 1, "Mana": 100, "ManaUnreserved": 0, "EnergyShield": 20,
             "EnergyShieldProtectsMana": 1, "ManaCost": 20, "Life": 100, "LifeUnreserved": 51, "LifeCost": 50}
    assert "ManaCostPool>=ManaCost" not in obj.violations(stats)
    assert obj.violations({**stats, "ManaCost": 21})["ManaCostPool>=ManaCost"] == 1 / 21


def test_a_channelled_main_skill_sustains_all_of_its_cost() -> None:
    """Cyclone at 39.3 mana/s regen against 43.84/s cost passed the rails' 85% and the channel
    still stops the moment the mana runs out (the user, shockwave_cyclone s1)."""

    rails = Rails.load()
    cyclone, spark = objective_for(rails, "Cyclone"), objective_for(rails, "Spark")
    assert set(_sustain(spark).values()) == {rails.sustain_factor} == {0.85}
    assert set(_sustain(cyclone).values()) == {1.0} and len(_sustain(cyclone)) == 3

    stats = {**FEASIBLE, "ManaRegenRecovery": 39.3, "ManaLeechGainRate": 0, "ManaRecoup": 0, "ManaPerSecondCost": 43.84}
    assert spark.score(stats).feasible, "89.6% of the cost passes the rails' 85%"
    assert not cyclone.score(stats).feasible
    assert cyclone.score({**stats, "ManaRegenRecovery": 44.0}).feasible


def test_eb_recharge_sustains_energy_shield_costs_only_without_damage_taken_from_mana() -> None:
    """EB recharge is continuous through costs, but a MoM hit interrupts it."""
    from junkroan.optimizer.keystone_floors import ES_RECHARGE_FOR_COSTS_KEYS, ES_RECHARGE_FOR_COSTS_STAT, energy_shield_recharge_for_costs

    obj = Rails.load().objective()
    relation = next(r for r in obj.relations if r[1] == "ESSustainPerSecondCost")
    assert relation[0] == "EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts"
    assert ES_RECHARGE_FOR_COSTS_STAT not in obj.stat_keys
    assert set(ES_RECHARGE_FOR_COSTS_KEYS) <= set(obj.stat_keys)

    base = {
        **FEASIBLE,
        "EnergyShieldProtectsMana": 1,
        "sharedMindOverMatter": 0,
        "PhysicalMindOverMatter": 0,
        "LightningMindOverMatter": 0,
        "ColdMindOverMatter": 0,
        "FireMindOverMatter": 0,
        "ChaosMindOverMatter": 0,
        "EnergyShieldRegenRecovery": 0,
        "EnergyShieldLeechGainRate": 0,
        "EnergyShieldRecoup": 0,
        "EnergyShieldRecharge": 120,
        "ESPerSecondCost": 151.62,
    }
    expected = (0.85 * 151.62 - 120) / (0.85 * 151.62)
    assert energy_shield_recharge_for_costs(base) == 120
    assert obj.violations(base)["EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts>=ESSustainPerSecondCost"] == pytest.approx(expected)
    assert obj.score({**base, "EnergyShieldRecharge": 130}).feasible

    shared_mom = {**base, "sharedMindOverMatter": 30}
    typed_mom = {**base, "LightningMindOverMatter": 10}
    missing_mom = {key: value for key, value in base.items() if key != "ChaosMindOverMatter"}
    assert energy_shield_recharge_for_costs(shared_mom) == 0
    assert energy_shield_recharge_for_costs(typed_mom) == 0
    assert energy_shield_recharge_for_costs(missing_mom) == 0
    for stats in (shared_mom, typed_mom, missing_mom):
        assert obj.violations(stats)["EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts>=ESSustainPerSecondCost"] == pytest.approx(1.0)

    plain_es = {**base, "EnergyShieldProtectsMana": 0, "EnergyShieldRecharge": 500}
    missing_eb = {key: value for key, value in {**base, "EnergyShieldRecharge": 500}.items() if key != "EnergyShieldProtectsMana"}
    assert energy_shield_recharge_for_costs(plain_es) == 0
    assert energy_shield_recharge_for_costs(missing_eb) == 0
    assert obj.violations(plain_es)["EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts>=ESSustainPerSecondCost"] == pytest.approx(1.0)
    assert obj.violations({**plain_es, "EnergyShieldRecharge": 0}) == obj.violations(plain_es)
    assert obj.without_sustain().score(base).feasible


def test_a_build_that_loses_life_while_idle_is_infeasible_however_much_it_leeches() -> None:
    """The user, 2026-09-18 (lightning_trap s2 at -12/s, inside D34's -100): idle is not hitting,
    so leech and recoup are not recovery. The shortfall is scaled by the life pool, not by a floor
    of zero, so a small degen reads small and an RF degen reads large."""

    obj = Rails.load().objective()
    idle = next(r for r in obj.relations if r[0].startswith("NetLifeRegen"))
    assert idle == ("NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond", "Life", 0.0, "Life")
    assert "LifeLeechGainRate" not in idle[0] and "LifeRecoup" not in idle[0]

    leeching = {**FEASIBLE, "NetLifeRegen": -12, "NetEnergyShieldRegen": 0, "LifeLeechGainRate": 400, "LifeRecoup": 100}
    assert not obj.score(leeching).feasible, "400 life/s of leech is not recovery while idle"
    assert abs(obj.violations(leeching)["NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond>=Life"] - 12 / 5000) < 1e-9
    assert abs(obj.violations({**leeching, "NetLifeRegen": -1316})["NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond>=Life"] - 1316 / 5000) < 1e-9
    assert obj.score({**leeching, "NetLifeRegen": 0}).feasible
    assert obj.score({**leeching, "NetLifeRegen": -12, "NetEnergyShieldRegen": 30}).feasible  # PoB sends degen to ES first

    # the audit says so with the numbers, as an error
    from junkroan.optimizer.audit import audit_stats

    findings = audit_stats(leeching, obj)
    assert any(f.severity == "error" and f.check == "relation" and "NetLifeRegen" in f.detail for f in findings), findings


def test_mind_over_matter_floor_is_casts_after_the_max_hit() -> None:
    """#608: the floor is the casts left after a hit through the keystone (tests/test_issue608_mom_casts_rail.py
    has the numbers); it is neutral without the keystone, so it is visible inside the what-if trial that allocates it."""

    from junkroan.optimizer.keystone_floors import STAT_NAME

    obj = Rails.load().objective()
    assert obj.floors[STAT_NAME] == 3 and "sharedMindOverMatter" in obj.stat_keys and STAT_NAME not in obj.stat_keys

    without = {**FEASIBLE, "sharedMindOverMatter": 0, "Mana": 666, "ManaUnreserved": 67}
    assert obj.score(without).feasible, "10% unreserved costs nothing while nothing is paid from mana"
    took_it = {**without, "sharedMindOverMatter": 40, "ManaCost": 50, "EnergyShield": 0, "PhysicalMaximumHitTaken": 5000}
    assert not obj.score(took_it).feasible
    assert obj.score({**took_it, "Mana": 2000, "ManaUnreserved": 1900}).feasible  # 1900 - 0.4 x 4000 = 300 left = 6 casts


def test_the_skill_floors_survive_a_changed_stat_and_a_second_application() -> None:
    """`objective_for` is called again by the pipeline on an objective the benchmark already
    built (maximize FullDPS by then): the skill's own floors must not depend on that order."""

    rails = Rails.load()
    ballista = objective_for(rails, "Shrapnel Ballista")  # totem: judged on FullDPS
    assert ballista.maximize == "FullDPS" and ballista.floors["HitChance"] == 95.0
    assert with_skill_floors("Shrapnel Ballista", ballista) == ballista
    assert objective_for(rails, "Shrapnel Ballista", ballista) == ballista
    cyclone = objective_for(rails, "Cyclone")
    assert with_skill_floors("Cyclone", cyclone) == cyclone  # the sustain factor is rewritten to the 1.0 it already is


@pytest.mark.parametrize("skill, mode, stat", [
    ("Storm Brand", "hit", "FullDPS"),          # a brand: the mode used to win and gave TotalDPS, one brand
    ("Shrapnel Ballista", "hit", "FullDPS"),    # a totem: same, one ballista of six
    ("Summon Raging Spirit", "minion", "FullDPS"),
    ("Summon Raging Spirit", "hit", "FullDPS"),
    ("Storm Brand", None, "FullDPS"),           # the benchmark's call, unchanged
    ("Spark", "hit", "TotalDPS"),               # counted once: the mode's own number
    ("Spark", "ignite", "IgniteDPS"),
    ("Spark", None, "CombinedDPS"),
])
def test_an_instance_counted_main_skill_maximizes_full_dps_whatever_the_mode(skill: str, mode: str | None, stat: str) -> None:
    """The CLI smoke, 2026-09-18: `junkroan build --skill "Storm Brand" --mode hit` maximized
    TotalDPS (one brand) while the benchmark's `objective_for(rails, "Storm Brand")` maximized
    FullDPS (all of them), so the same skeleton was optimized for two different numbers depending
    on which path built it. The instance count is a PoB number the tree and the ascendancy move
    (D37, D56, D57), so it outranks the mode; the mode stat applies to skills counted once."""

    rails = Rails.load()
    assert objective_for(rails, skill, mode=mode).maximize == stat
    assert maximized_stat(skill, mode) == stat
    # whichever stat it lands on, the skill's own floors are there and applying it twice is a no-op
    obj = objective_for(rails, skill, mode=mode)
    assert objective_for(rails, skill, obj, mode=mode) == obj == with_skill_floors(skill, obj)


def test_the_mode_probe_ranks_ascendancies_on_the_stat_the_build_will_maximize() -> None:
    """`search.modes.probe_skill` builds its own objective; it must be the same rule, or the probe
    ranks Hierophant on one brand while the pipeline builds for all of them. The report keeps
    showing the mode's own stat (`MODES`), which is what its columns mean."""

    from junkroan.search.modes import MODES

    assert {m: s for m, (s, _e) in MODES.items()} == {m: maximized_stat("Spark", m) for m in MODES}
    assert maximized_stat("Storm Brand", "hit") == "FullDPS" != MODES["hit"][0]


def test_elemental_overload_needs_crit_recently_up_nine_tenths_of_the_time() -> None:
    """The user's reading 2026-09-18 (burning_arrow_snipe: 7% crit on a slow channelled skill got
    the keystone's whole 40%): PoB grants it at any crit chance above zero. The floor is neutral
    without the keystone (`HaveElementalOverload`, the wrapper's witness) and the 8 s window's
    uptime with it, so the trial that allocates it pays."""

    from junkroan.optimizer.keystone_floors import EO_STAT_NAME, EO_WITNESS, elemental_overload_uptime

    rails = Rails.load()
    obj = objective_for(rails, "Burning Arrow")
    assert obj.floors[EO_STAT_NAME] == 0.9 and EO_WITNESS in obj.stat_keys and EO_STAT_NAME not in obj.stat_keys

    assert elemental_overload_uptime({EO_WITNESS: 0, "CritChance": 1.0, "Speed": 1.0}) == 1.0
    slow = {EO_WITNESS: 1, "CritChance": 10.584, "Speed": 0.968}  # the author's Burning Arrow: 10.6% effective crit, 0.97 hits/s
    assert abs(elemental_overload_uptime(slow) - (1 - (1 - 0.10584) ** (8 * 0.968))) < 1e-9  # 58%
    fast = {EO_WITNESS: 1, "CritChance": 68.4, "Speed": 3.36}  # kinetic_fusillade: 100%
    assert elemental_overload_uptime(fast) > 0.999
    assert elemental_overload_uptime(slow, minion_main=True) == 0.0  # the minions' crits are theirs

    without = {**FEASIBLE, **{EO_WITNESS: 0, "CritChance": 10.584, "Speed": 0.968}}
    assert obj.score(without).feasible
    took_it = {**without, EO_WITNESS: 1}
    assert not obj.score(took_it).feasible and abs(obj.violations(took_it)[EO_STAT_NAME] - (0.9 - elemental_overload_uptime(slow))) < 1e-9  # a floor below 1 is scaled by 1
    assert obj.score({**took_it, "CritChance": 30.0}).feasible  # 30% at 0.97 hits/s: 94%
    minions = objective_for(rails, "Summon Raging Spirit")
    assert not minions.score({**took_it, "CritChance": 99.0, "FullDPS": 1}).feasible  # the keystone is per skill
    assert with_skill_floors("Burning Arrow", obj) == obj  # idempotent, like the other skill floors
