"""#1015: the summon of a permanent minion (Raise Zombie, Raise Spectre, golems) is out of the sustain rule's cost side.

PoB books the main skill's cost as `<resource>PerSecondCost` = cost x cast speed (CalcOffence.lua:5793-5824), as if the
minion were re-summoned without a pause; a permanent minion is summoned once and stands until it dies (the owner,
2026-10-14: «Нет, не нужно»). PoB's marker is `skillFlags.permanentMinion`, set from `baseFlags.permanentMinion` or the
stat `infinite_minion_duration` (SkillStatMap.lua:25, CalcActiveSkill.lua:344); the worker hands it out as
`MainSkillPermanentMinion`. The outputs below are the authors' rows of docs/research/2026-10-11-mana-rule-vs-authors.md
(z326_necromancer_zombie_army_early, z327_necromancer_raise_spectre, absolution_minions; Row 1 and Row 2)."""

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.pob import skill_facts

ZOMBIE = {  # z326_necromancer_zombie_army_early: Raise Zombie, ManaCost 72 x 1.60 casts/s
    "ManaCost": 72, "ManaPerSecondCost": 115.2, "LifeCost": 12.8, "LifePerSecondCost": 20.48, "ESCost": 0, "ESPerSecondCost": 0,
    "ManaRegenRecovery": 41.4, "ManaLeechGainRate": 0, "ManaRecoup": 0, "Mana": 988, "ManaUnreserved": 75,
    "MainSkillPermanentMinion": 1,
}
SPECTRE = {  # z327_necromancer_raise_spectre: ManaCost 108 x 1.39 casts/s, Repeats 2
    "ManaCost": 108, "ManaPerSecondCost": 149.92941176471, "LifeCost": 0, "LifePerSecondCost": 0, "ESCost": 0, "ESPerSecondCost": 0,
    "ManaRegenRecovery": 36.4, "ManaLeechGainRate": 0, "ManaRecoup": 0, "Mana": 982, "ManaUnreserved": 144,
    "MainSkillPermanentMinion": 1,
}
ABSOLUTION = {  # absolution_minions: sentinels live 15 s, the skill is cast on a pause only as the PoB number says
    "ManaCost": 55, "ManaPerSecondCost": 110, "LifeCost": 9.6, "LifePerSecondCost": 19.2, "ESCost": 0, "ESPerSecondCost": 0,
    "ManaRegenRecovery": 89.2, "ManaLeechGainRate": 0, "ManaRecoup": 0, "Mana": 859, "ManaUnreserved": 100,
    "MainSkillPermanentMinion": 0,
}


def _relation(obj):
    relation = next(r for r in obj.relations if r[0].startswith("ManaRegenRecovery"))
    assert float(relation[2]) == 0.85  # the bar stays
    return relation


def _mana_cost_side(stats: dict) -> float | None:
    obj = Rails.load().objective()
    return obj.derived_values(stats).get(_relation(obj)[1])


def _mana_shortfall(stats: dict) -> float:
    obj = Rails.load().objective()
    relation = _relation(obj)
    return obj.violations(stats).get(f"{relation[0]}>={relation[1]}", 0.0)


@pytest.mark.parametrize("build", [ZOMBIE, SPECTRE], ids=["raise_zombie", "raise_spectre"])
def test_row2_a_permanent_minion_summon_keeps_the_rule(build: dict) -> None:
    assert _mana_cost_side(build) == 0
    assert _mana_shortfall(build) == 0.0


@pytest.mark.parametrize("build,short", [(ZOMBIE, (0.85 * 115.2 - 41.4) / (0.85 * 115.2)), (SPECTRE, (0.85 * 149.92941176471 - 36.4) / (0.85 * 149.92941176471))], ids=["raise_zombie", "raise_spectre"])
def test_row2_the_same_build_with_a_non_minion_skill_over_the_bar_still_breaks_it(build: dict, short: float) -> None:
    other = {**build, "MainSkillPermanentMinion": 0}
    assert _mana_cost_side(other) == build["ManaPerSecondCost"]
    assert _mana_shortfall(other) == pytest.approx(short, abs=1e-9)  # the study's 0.577 and 0.714
    # a build without the stat at all (older stats) is costed too
    without = {k: v for k, v in build.items() if k != "MainSkillPermanentMinion"}
    assert _mana_shortfall(without) == pytest.approx(short, abs=1e-9)


def test_row2_a_temporary_minion_skill_stays_costed() -> None:
    assert _mana_cost_side(ABSOLUTION) == 110
    assert _mana_shortfall(ABSOLUTION) == pytest.approx((0.85 * 110 - 89.2) / (0.85 * 110), abs=1e-9)  # 0.046 of the study
    raging_spirit = {**ABSOLUTION, "ManaPerSecondCost": 71.6, "ManaRegenRecovery": 20.2}  # Summon Raging Spirit, smoke row 5 cost
    assert _mana_shortfall(raging_spirit) > 0.0


def test_the_other_resources_of_the_summon_leave_with_it_and_the_bar_stays() -> None:
    obj = Rails.load().objective()
    life_paid = {**ZOMBIE, "ManaCost": 0, "ManaPerSecondCost": 0, "LifePerSecondCost": 20.48}
    assert obj.derived_values(life_paid)["LifeSustainPerSecondCost"] == 0
    assert obj.derived_values({**life_paid, "MainSkillPermanentMinion": 0})["LifeSustainPerSecondCost"] == 20.48
    # no PerSecondCost booked: still no relation, the flag adds nothing
    assert obj.derived_values({k: v for k, v in ZOMBIE.items() if k != "ManaPerSecondCost"})["ManaSustainPerSecondCost"] is None
    # the single cast still has to fit the pool: the permanent-minion exit touches only the sustain cost side
    assert {"MainSkillPermanentMinion", "ManaPerSecondCost", "ManaCost"} <= set(obj.stat_keys)


def test_a_totem_skill_keeps_the_totem_rule_beside_the_flag() -> None:
    totem = {"ManaCost": 35, "TotemsSummoned": 6, "TotemDuration": 8.019, "TotemPlacementTime": 0.294, "ManaPerSecondCost": 119, "MainSkillPermanentMinion": 0}
    assert _mana_cost_side(totem) == pytest.approx(35 * 6 / 8.019)


def test_row1_the_marker_is_in_pobs_skill_data() -> None:
    """`baseFlags.permanentMinion` (act_int.lua:15020 Raise Spectre, :15184 Raise Zombie) or `infinite_minion_duration`
    (SkillStatMap.lua:25); Summon Raging Spirit, Summon Skeletons and Absolution carry neither."""

    blocks = skill_facts._blocks()
    marked = lambda sid: "permanentMinion = true" in blocks[sid] or '"infinite_minion_duration"' in blocks[sid]  # noqa: E731
    assert marked("RaiseZombie") and marked("RaiseSpectre")
    assert not any(marked(sid) for sid in ("SummonRagingSpirit", "SummonSkeletons", "Absolution"))
