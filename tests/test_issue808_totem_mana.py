"""#808 rows 2 and 5: a totem main skill's sustain relation is held to `<resource>Cost x TotemsSummoned / TotemDuration`.

PoB's `ManaPerSecondCost` of a totem skill is `ManaCost x TotemPlacementSpeed` (CalcOffence.lua:5793-5824): the cost
of re-placing totems at full speed forever. A build pays one placement per totem lifetime. The outputs below are
impale_ballista's, read in docs/research/2026-10-11-totem-mana-reading.md (row 1)."""

import pytest

from junkroan.optimizer.rails import Rails

BALLISTA = {  # the author build, row 1 of docs/research/2026-10-11-totem-mana-reading.md
    "ManaCost": 35, "TotemsSummoned": 6, "TotemDuration": 8.019, "TotemPlacementTime": 0.29411764705882,
    "ManaPerSecondCost": 119, "LifeCost": 0, "LifePerSecondCost": 0, "ESCost": 0, "ESPerSecondCost": 0,
    "ManaRegenRecovery": 20.6, "ManaLeechGainRate": 0, "ManaRecoup": 0, "Mana": 769, "ManaUnreserved": 186,
}
NEW_COST = 35 * 6 / 8.019  # 26.19
NEEDS = 0.85 * NEW_COST  # 22.26


def _mana_cost_side(stats: dict) -> float | None:
    """The per-second cost the objective's Mana sustain relation holds this build to."""

    obj = Rails.load().objective()
    relation = next(r for r in obj.relations if r[0].startswith("ManaRegenRecovery"))
    assert float(relation[2]) == 0.85
    return obj.derived_values(stats).get(relation[1]) if relation[1] in {d.name for d in obj.derived} else stats.get(relation[1])


def _mana_shortfall(stats: dict) -> float:
    obj = Rails.load().objective()
    relation = next(r for r in obj.relations if r[0].startswith("ManaRegenRecovery"))
    return obj.violations(stats).get(f"{relation[0]}>={relation[1]}", 0.0)


def test_row2_a_totem_skill_is_held_to_cost_times_totems_over_duration() -> None:
    assert _mana_cost_side(BALLISTA) == pytest.approx(26.19, abs=0.005)
    # 20.6 regen against 0.85 x 26.19 = 22.26: short by 1.66 / 22.26 (the old 0.85 x 119 = 101.15 gave 0.796)
    assert _mana_shortfall(BALLISTA) == pytest.approx((NEEDS - 20.6) / NEEDS, abs=1e-6)
    # 23 regen covers the new cost, and would not have covered PoB's 119
    assert _mana_shortfall({**BALLISTA, "ManaRegenRecovery": 23.0}) == 0.0
    # ours (smoke, row 1): 15 x 4 / 8.019 = 7.48 against 46.2 recovery
    ours = {**BALLISTA, "ManaCost": 15, "TotemsSummoned": 4, "ManaPerSecondCost": 49.5, "ManaRegenRecovery": 36.2, "ManaRecoup": 10.0}
    assert _mana_cost_side(ours) == pytest.approx(7.48, abs=0.005)
    assert _mana_shortfall(ours) == 0.0


@pytest.mark.parametrize("missing", [{"TotemDuration": None}, {"TotemDuration": 0}, {"TotemsSummoned": None}, {"TotemsSummoned": 0}])
def test_row5_without_duration_or_totems_the_relation_keeps_pobs_per_second_cost(missing: dict) -> None:
    stats = {k: v for k, v in {**BALLISTA, **missing}.items() if v is not None}
    assert _mana_cost_side(stats) == 119
    assert _mana_shortfall(stats) == pytest.approx((0.85 * 119 - 20.6) / (0.85 * 119), abs=1e-6)


def test_a_non_totem_skill_keeps_pobs_per_second_cost() -> None:
    spell = {k: v for k, v in BALLISTA.items() if k not in {"TotemPlacementTime", "TotemsSummoned", "TotemDuration"}}
    assert _mana_cost_side(spell) == 119
    # a skill with no PerSecondCost at all adds no relation, totem or not
    assert _mana_cost_side({k: v for k, v in BALLISTA.items() if k != "ManaPerSecondCost"}) is None
    assert _mana_shortfall({k: v for k, v in BALLISTA.items() if k != "ManaPerSecondCost"}) == 0.0


def test_life_and_energy_shield_costs_follow_the_resource_the_skill_pays_in() -> None:
    obj = Rails.load().objective()
    life = {**BALLISTA, "ManaCost": 0, "ManaPerSecondCost": 0, "LifeCost": 7.2, "LifePerSecondCost": 23.76}
    assert obj.derived_values(life)["LifeSustainPerSecondCost"] == pytest.approx(7.2 * 6 / 8.019)
    assert obj.derived_values(life)["ManaSustainPerSecondCost"] == 0
    # EnergyShieldProtectsMana: PoB books the Mana cost under ESPerSecondCost and no ManaPerSecondCost
    eb = {**BALLISTA, "EnergyShieldProtectsMana": 1, "ESPerSecondCost": 119}
    eb.pop("ManaPerSecondCost")
    values = obj.derived_values(eb)
    assert values["ESSustainPerSecondCost"] == pytest.approx(NEW_COST)
    assert values["ManaSustainPerSecondCost"] is None


def test_without_sustain_drops_the_new_cost_side_with_the_old_one() -> None:
    obj = Rails.load().objective()
    assert [r for r in obj.relations if "PerSecond" in r[1]]
    assert not [r for r in obj.without_sustain().relations if "PerSecond" in r[1]]
    assert _mana_shortfall(BALLISTA) > 0.0
    assert not any(k.endswith("PerSecondCost") and k.startswith("Mana") for k in obj.without_sustain().violations(BALLISTA))
    assert {"TotemDuration", "TotemsSummoned", "ManaPerSecondCost", "ManaCost"} <= set(obj.stat_keys)
