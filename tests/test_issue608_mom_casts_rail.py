"""#608: the Mind over Matter floor is the casts left after a hit, not a share of unreserved mana.

Plain tests on stats dicts (no PoB). The numbers: stormbrand-s4 of the 2026-10-05 gate
(docs/research/2026-10-06-mom-pool-balance.md section 5)."""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.optimizer.keystone_floors import NOT_APPLICABLE, STAT_NAME, mom_casts_after_max_hit, mom_casts_stat
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE

STORMBRAND_S4 = {
    "Life": 4194, "Mana": 716, "ManaUnreserved": 358, "EnergyShield": 770, "ManaCost": 61,
    "PhysicalMaximumHitTaken": 5315, "EnergyShieldProtectsMana": 1, "sharedMindOverMatter": 40,
}


def test_stormbrand_s4_has_no_casts_left_and_fails() -> None:
    # D = 0.8 x 5315 = 4252; drained = 0.4 x 4252 - 770 = 930.8 > 358 unreserved mana
    assert mom_casts_after_max_hit(STORMBRAND_S4) == 0.0
    obj = Rails.load().objective()
    assert obj.floors[STAT_NAME] == 3
    stats = {**STORMBRAND_S4, **obj.derived_values(STORMBRAND_S4)}
    assert STAT_NAME in obj.violations(stats)


def test_a_balanced_build_passes() -> None:
    # Life 4000, ES 0, max hit 6000: D = 4800, drained = 1920; 2300 unreserved leaves 380 = 6.2 casts of 61
    balanced = {**STORMBRAND_S4, "EnergyShield": 0, "EnergyShieldProtectsMana": 0, "ManaUnreserved": 2300, "PhysicalMaximumHitTaken": 6000}
    casts = mom_casts_after_max_hit(balanced)
    assert abs(casts - 380 / 61) < 1e-9 and casts >= 3
    assert STAT_NAME not in Rails.load().objective().violations({**balanced, STAT_NAME: casts})


def test_eldritch_battery_pays_the_keystone_share_first() -> None:
    base = {**STORMBRAND_S4, "ManaUnreserved": 1000}
    with_eb = mom_casts_after_max_hit(base)  # drained 930.8, 69.2 left
    without_eb = mom_casts_after_max_hit({**base, "EnergyShieldProtectsMana": 0})  # 0.4 x (4252 - 770) = 1392.8 > 1000
    assert abs(with_eb - (1000 - 930.8) / 61) < 1e-9 and without_eb == 0.0


def test_not_applicable_without_the_keystone_or_with_a_free_skill() -> None:
    assert mom_casts_after_max_hit({**STORMBRAND_S4, "sharedMindOverMatter": 0}) == NOT_APPLICABLE
    assert mom_casts_after_max_hit({**STORMBRAND_S4, "ManaCost": 0}) == NOT_APPLICABLE
    obj = Objective(maximize="CombinedDPS", floors={STAT_NAME: 3.0}, derived=(mom_casts_stat(),))
    for stats in ({**STORMBRAND_S4, "sharedMindOverMatter": 0}, {**STORMBRAND_S4, "ManaCost": 0}):
        assert STAT_NAME not in obj.violations(stats)


def test_the_old_hand_rule_is_gone() -> None:
    raw = json.loads((Path(__file__).resolve().parents[1] / "src/junkroan/optimizer/rails_default.json").read_text(encoding="utf-8"))
    assert "MoMUnreservedShare" not in raw["floors"]
    assert raw["floors"]["MoMCastsAfterMaxHit"] == 3 and raw["floors"]["MoMHitFraction"] == 0.8
    obj = Rails.load().objective()
    assert "MoMUnreservedShare" not in obj.floors and "MoMHitFraction" not in obj.floors


def test_trace_counts_checked_evaluations_and_feasible_ones_below_n() -> None:
    obj = Objective(maximize="CombinedDPS", floors={STAT_NAME: 3.0}, derived=(mom_casts_stat(),))
    ok = {**STORMBRAND_S4, "EnergyShield": 0, "EnergyShieldProtectsMana": 0, "ManaUnreserved": 2300, "PhysicalMaximumHitTaken": 6000}

    def counts(stats: dict) -> tuple[int, int]:
        before = TRACE.considered()
        obj.score(stats)
        after = TRACE.considered()

        def n(snapshot: dict, cls: str) -> int:
            return sum(c.get(cls, {}).get("evaluated", 0) for c in snapshot.values())
        return (n(after, "mom-casts-rail-checked") - n(before, "mom-casts-rail-checked"),
                n(after, "mom-casts-below-n") - n(before, "mom-casts-below-n"))

    assert counts(ok) == (1, 0)
    assert counts(STORMBRAND_S4) == (1, 0), "infeasible: not an accepted evaluation"
    assert counts({**ok, "sharedMindOverMatter": 0}) == (0, 0)
