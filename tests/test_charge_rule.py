"""Charge generators quantified from PoB's numbers, with the boss-lane policies decided with the user
(mechanics/unsupported_lines.json): on kill off, on block off without a retaliation skill, stealing never."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import (
    ON_KILL_TRIGGER,
    NUMERIC_ASSUMPTION_DEFAULTS,
    _gem_names,
    _gem_tags,
    _main_skill_name,
    _main_skill_tags,
    build_text,
    charge_rule,
    charge_sources,
    conservative_generator_issue,
    derive_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

STATS = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "EnduranceChargesMax": 3, "EnduranceChargesDuration": 10, "PowerChargesMax": 3, "PowerChargesDuration": 10, "Speed": 4.34, "CritChance": 50}


def test_sources_are_classified_by_trigger() -> None:
    text = "8% chance to gain a frenzy charge on hit against unique enemies\n8% chance to gain a frenzy charge on kill\n25% chance to steal power, frenzy, and endurance charges on hit with claws\n20% chance to gain a frenzy charge when you block attack damage\n+1 to maximum frenzy charges\ngain a power charge on critical strike"
    kinds = {s["trigger"]: s for s in charge_sources("Frenzy", text)}
    assert set(kinds) == {"hit", "kill", "steal", "block"}
    assert kinds["hit"]["chance"] == 0.08 and kinds["block"]["chance"] == 0.20
    assert charge_sources("Power", text)[-1]["trigger"] == "crit" and charge_sources("Power", text)[-1]["chance"] == 1.0


def test_mine_trap_and_mana_charge_sources_are_classified() -> None:
    mine, trap, mana = (
        charge_sources("Power", "10% chance to gain a power charge when your Mine is Detonated targeting an Enemy")[0],
        charge_sources("Frenzy", "15% chance to gain a frenzy charge when your Trap is triggered by an Enemy")[0],
        charge_sources("Power", "Gain a power charge after Spending a total of 200 Mana")[0],
    )
    assert mine["trigger"] == "mine" and mine["chance"] == 0.10 and mine["count"] == 1
    assert trap["trigger"] == "trap" and trap["chance"] == 0.15 and trap["count"] == 1
    assert mana["trigger"] == "mana_spent" and mana["threshold"] == 200


def test_an_unclassified_charge_source_is_not_conservative_proof() -> None:
    use, why, override, rate = charge_rule("usePowerCharges", STATS, "gain a power charge while focused", frozenset())
    assert not use and override is None and rate == 0.0
    assert "unclassified source: not counted" in why


def test_conservative_generator_issue_uses_the_ramp_budget_it_is_given() -> None:
    source = "30% chance to gain a power charge on hit"
    # 30% x 4.34 hits/s x 0.5 s = 0.65 charges: not proven.
    assert conservative_generator_issue("usePowerCharges", STATS, source, frozenset(), ramp_seconds=0.5) is not None
    # 30% x 4.34 hits/s x 1 s = 1.30 charges: proven.
    assert conservative_generator_issue("usePowerCharges", STATS, source, frozenset(), ramp_seconds=1.0) is None


def test_sword_mastery_sustains_frenzy_on_a_boss_but_on_kill_block_and_steal_do_not() -> None:
    # 8% x 4.34 hits/s x 10 s = 3.5 of 3: sustained at the maximum
    use, why, override, rate = charge_rule("useFrenzyCharges", STATS, "8% chance to gain a frenzy charge on hit against unique enemies", frozenset(), ramp_seconds=10.0)
    assert use and override is None and abs(rate - 0.08 * 4.34) < 1e-9 and "3.5 sustained" in why
    # within the 2.5 s ramp budget only 0.87 charges are gained: off (the number is what the budget reaches, D39)
    assert not charge_rule("useFrenzyCharges", STATS, "8% chance to gain a frenzy charge on hit against unique enemies", frozenset(), ramp_seconds=2.5)[0]
    # 30% on hit: 1.3/s -> 3.3 within 2.5 s, capped at 3
    assert charge_rule("useFrenzyCharges", STATS, "30% chance to gain a frenzy charge on hit", frozenset(), ramp_seconds=2.5)[2] is None
    # 8% on kill: nothing on a boss
    use, why, _o, rate = charge_rule("useFrenzyCharges", STATS, "8% chance to gain a frenzy charge on kill", frozenset())
    assert not use and "no kills on a boss" in why and rate == 0.0
    # on block: off without a retaliation skill, full with one
    text = "25% chance to gain an endurance charge when you block"
    assert not charge_rule("useEnduranceCharges", STATS, text, frozenset())[0]
    assert charge_rule("useEnduranceCharges", STATS, text, frozenset({"retaliation"}))[0]
    # stealing never counts
    assert not charge_rule("usePowerCharges", STATS, "25% chance to steal power, frenzy, and endurance charges on hit with claws", frozenset())[0]
    # a partial count: 2% on hit -> 0.87 sustained -> off; 5% -> 2.2 -> on with the count overridden to 2
    assert not charge_rule("useFrenzyCharges", STATS, "2% chance to gain a frenzy charge on hit", frozenset())[0]
    use, _w, override, _r = charge_rule("useFrenzyCharges", STATS, "5% chance to gain a frenzy charge on hit", frozenset(), ramp_seconds=10.0)
    assert use and override == 2
    # on crit uses the crit chance: 10% x 4.34 x 50% x 10 s = 2.2
    use, _w, override, _r = charge_rule("usePowerCharges", STATS, "10% chance to gain a power charge on critical strike", frozenset(), ramp_seconds=10.0)
    assert use and override == 2
    # an add-spawning enabler turns on-kill into a rate
    use, why, _o, _r = charge_rule("useFrenzyCharges", STATS, "an enemy writhing worm spawns every 2 seconds\n50% chance to gain a frenzy charge on kill", frozenset(), ramp_seconds=10.0)
    assert use and "kills/s from adds" in why


def test_mine_rate_uses_speed_fraction_and_main_skill_tag() -> None:
    stats = {"PowerChargesMax": 3, "PowerChargesDuration": 30, "Speed": 4.0}
    use, why, override, rate = charge_rule(
        "usePowerCharges",
        stats,
        "10% chance to gain a power charge when your Mine is Detonated targeting an Enemy",
        frozenset({"mine"}),
        main_tags=frozenset({"mine", "spell"}),
    )
    assert use and rate == pytest.approx(0.40) and override == 1
    assert min(rate * 30, 3) == 3
    assert "4.00 mines/s" in why and "1.0 within" in why

    use, why, override, rate = charge_rule(
        "usePowerCharges",
        stats,
        "10% chance to gain a power charge when your Mine is Detonated targeting an Enemy",
        frozenset({"mine"}),
        main_tags=frozenset({"spell"}),
    )
    assert not use and override is None and rate == 0.0 and "main skill is not a mine" in why

    # The enabler remains based on all gem tags, not the main skill tags.
    use, why, _override, rate = charge_rule(
        "usePowerCharges",
        stats,
        "10% chance to gain a power charge when your Mine is Detonated targeting an Enemy",
        frozenset(),
        main_tags=frozenset({"mine", "spell"}),
    )
    assert not use and rate == 0.0 and "needs a mine skill" in why

    # A delivery support is still a mine gem for the enabler check.
    assert "mine" in _gem_tags(["Exsanguinate", "High-Impact Mine"])


def test_trap_rate_uses_speed_and_preserves_fractional_ramp_rounding() -> None:
    stats = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.0}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges",
        {**stats, "HitSpeed": 2.0, "Speed": 99.0},
        "15% chance to gain a frenzy charge when your Trap is triggered by an Enemy",
        frozenset({"trap"}),
        main_tags=frozenset({"trap"}),
    )
    assert not use and override is None and rate == pytest.approx(0.30)
    assert min(rate * 10, 3) == 3 and "0.75 within" in why


def test_mine_detonation_fraction_does_not_reduce_trap_rates() -> None:
    mine_stats = {"PowerChargesMax": 3, "PowerChargesDuration": 30, "Speed": 4.0}
    trap_stats = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.0}
    mine_line = "10% chance to gain a power charge when your Mine is Detonated targeting an Enemy"
    trap_line = "15% chance to gain a frenzy charge when your Trap is triggered by an Enemy"
    original = NUMERIC_ASSUMPTION_DEFAULTS["mine_detonation_fraction"]
    try:
        mine_rate = charge_rule("usePowerCharges", mine_stats, mine_line, frozenset({"mine"}), main_tags=frozenset({"mine"}))[3]
        trap_rate = charge_rule("useFrenzyCharges", trap_stats, trap_line, frozenset({"trap"}), main_tags=frozenset({"trap"}))[3]
        NUMERIC_ASSUMPTION_DEFAULTS["mine_detonation_fraction"] = 0.5
        assert charge_rule("usePowerCharges", mine_stats, mine_line, frozenset({"mine"}), main_tags=frozenset({"mine"}))[3] == pytest.approx(mine_rate * 0.5)
        assert charge_rule("useFrenzyCharges", trap_stats, trap_line, frozenset({"trap"}), main_tags=frozenset({"trap"}))[3] == pytest.approx(trap_rate)
    finally:
        NUMERIC_ASSUMPTION_DEFAULTS["mine_detonation_fraction"] = original


def test_mana_spent_rate_uses_pob_mana_cost_and_zero_cost_is_off() -> None:
    stats = {"PowerChargesMax": 3, "PowerChargesDuration": 10, "ManaPerSecondCost": 100}
    use, why, override, rate = charge_rule(
        "usePowerCharges",
        stats,
        "Gain a power charge after Spending a total of 200 Mana",
        frozenset(),
    )
    assert use and rate == pytest.approx(0.5) and override == 1
    assert rate * 2.5 == pytest.approx(1.25) and "1.2 within" in why

    use, _why, override, rate = charge_rule(
        "usePowerCharges",
        {**stats, "ManaPerSecondCost": 0},
        "Gain a power charge after Spending a total of 200 Mana",
        frozenset(),
    )
    assert not use and override is None and rate == 0.0


FRENZY_LINE = "performs an attack with a ranged weapon that gives the character a frenzy charge if it hits"


def test_proxy_main_skill_does_not_credit_its_hits_to_the_player() -> None:
    stats = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.19}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", stats, FRENZY_LINE, frozenset({"attack", "totem"}), main_tags=frozenset({"attack", "totem"})
    )
    assert not use and override is None and rate == 0.0
    assert "proxy main skill" in why


def test_triggered_frenzy_beside_a_totem_uses_its_own_pob_rate() -> None:
    stats = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.19}
    contexts = {FRENZY_LINE: [{"name": "Frenzy", "triggered": True, "proxy": False, "stats": {"Speed": 1.0, "HitChance": 100, "CritChance": 0}}]}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", stats, FRENZY_LINE, frozenset({"attack", "totem"}), ramp_seconds=2.5,
        main_tags=frozenset({"attack", "totem"}), source_contexts=contexts,
    )
    assert use and override == 2 and rate == pytest.approx(1.0)
    assert "Frenzy's own Speed 1.00/s" in why and "2.5 s ramp budget (2 of 3 max)" in why
    assert "2.19" not in why


def test_hand_used_frenzy_only_uses_time_left_after_placing_totems() -> None:
    stats = {
        "FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.19,
        "ActiveTotemLimit": 5, "TotemPlacementTime": 0.3, "TotemDuration": 10,
    }
    contexts = {FRENZY_LINE: [{"name": "Frenzy", "triggered": False, "proxy": False, "stats": {"Speed": 1.0, "HitChance": 100, "CritChance": 0}}]}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", stats, FRENZY_LINE, frozenset({"attack", "totem"}), ramp_seconds=2.5,
        main_tags=frozenset({"attack", "totem"}), source_contexts=contexts,
    )
    assert use and override == 1 and rate == pytest.approx(1.0)
    assert "5 placements x 0.300 s leaves 1.00 s" in why and "(1 of 3 max)" in why


def test_hand_used_critical_generator_uses_time_left_after_placing_totems() -> None:
    line = "gain a power charge on critical strike"
    stats = {
        "PowerChargesMax": 3, "PowerChargesDuration": 10, "Speed": 2.19,
        "ActiveTotemLimit": 5, "TotemPlacementTime": 0.3, "TotemDuration": 10,
    }
    contexts = {line: [{"name": "Generator", "triggered": False, "proxy": False, "stats": {"Speed": 1.0, "HitChance": 100, "CritChance": 100}}]}
    use, why, override, rate = charge_rule(
        "usePowerCharges", stats, line, frozenset({"attack", "totem"}), ramp_seconds=2.5,
        main_tags=frozenset({"attack", "totem"}), source_contexts=contexts,
    )
    assert use and override == 1 and rate == pytest.approx(1.0)
    assert "5 placements x 0.300 s leaves 1.00 s" in why


@pytest.mark.parametrize("delivery", ["mine", "trap"])
def test_hand_used_frenzy_has_no_time_beside_continuous_proxy_throws(delivery: str) -> None:
    contexts = {FRENZY_LINE: [{"name": "Frenzy", "triggered": False, "proxy": False, "stats": {"Speed": 1.0, "HitChance": 100}}]}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10}, FRENZY_LINE,
        frozenset({"attack", delivery}), main_tags=frozenset({"attack", delivery}), source_contexts=contexts,
    )
    assert not use and override is None and rate == 0.0
    assert "hand-used generator has no time" in why


def test_frenzy_delivered_by_a_totem_cannot_generate_player_charges() -> None:
    contexts = {FRENZY_LINE: [{"name": "Frenzy", "triggered": False, "proxy": True, "stats": {"Speed": 1.0, "HitChance": 100}}]}
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10}, FRENZY_LINE,
        frozenset({"attack", "totem"}), main_tags=frozenset({"attack", "totem"}), source_contexts=contexts,
    )
    assert not use and override is None and rate == 0.0
    assert "delivered by a proxy" in why


def test_non_proxy_main_skill_retains_the_existing_main_hit_rate() -> None:
    use, why, override, rate = charge_rule(
        "useFrenzyCharges", {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.19}, FRENZY_LINE,
        frozenset({"attack"}), main_tags=frozenset({"attack"}), ramp_seconds=2.5,
    )
    assert use and override is None and rate == pytest.approx(2.19)
    assert "2.19 hits/s" in why


def test_enemies_that_die_is_an_on_kill_trigger() -> None:
    source = charge_sources("Frenzy", "enemies that die while in the area have a chance to grant frenzy charges")[0]
    assert source["trigger"] == "kill"
    assert ON_KILL_TRIGGER.search("when a marked enemy dies")
    assert ON_KILL_TRIGGER.search("when a rare or unique enemy dies")
    assert not ON_KILL_TRIGGER.search("when a nearby minion dies")


@pytest.mark.pob
@needs_pob
def test_real_charge_triggers_are_counted_on_the_four_tuadh_fixtures(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    expected = {
        "exsanguinate_mines": (("Power", "mine"),),
        "pyroclast_mine": (("Power", "mine"),),
        "lightning_trap": (("Frenzy", "trap"), ("Power", "trap")),
        "winter_orb": (("Power", "mana_spent"),),
    }
    with PobSession(run_id="test-charge-triggers-fixtures", artifacts_root=tmp_path) as pob:
        for slug, triggers in expected.items():
            pob.load_xml(decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))
            derived = derive_config(pob, prefer_rules=True)
            text = build_text(pob)
            gem_names = _gem_names(pob)
            gem_tags = _gem_tags(gem_names)
            main_tags = _main_skill_tags(pob, _main_skill_name(pob))
            for kind, trigger in triggers:
                sources = [s for s in charge_sources(kind, text, gem_tags, main_tags) if s["trigger"] == trigger]
                assert sources and all(s["needs"] is None for s in sources), slug
                source_text = "\n".join(s["line"] for s in sources)
                use, why, _override, rate = charge_rule(
                    {"Power": "usePowerCharges", "Frenzy": "useFrenzyCharges"}[kind],
                    pob.stats(),
                    source_text,
                    gem_tags,
                    main_tags=main_tags,
                )
                var = {"Power": "usePowerCharges", "Frenzy": "useFrenzyCharges"}[kind]
                print(f"{slug} {var}: {rate:.4f}/s; {derived.conservative.reasons.get(var, why)}")
                assert rate > 0, (slug, kind, trigger, sources)
                assert derived.conservative.inputs.get(var) is True


@pytest.mark.pob
@needs_pob
def test_impale_ballista_uses_its_independent_frenzy_link_rate(tmp_path: Path) -> None:
    """D80: Manaforged Frenzy is the player's attack, not a Ballista hit."""

    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-d80-impale-ballista", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "impale_ballista.pob.txt").read_text(encoding="utf-8").strip()))
        derived = derive_config(pob, prefer_rules=True)
    reason = derived.conservative.reasons["useFrenzyCharges"]
    assert derived.conservative.inputs["useFrenzyCharges"] is True
    assert derived.conservative.inputs["overrideFrenzyCharges"] == 2
    assert derived.charge_rates["useFrenzyCharges"][1] == pytest.approx(0.9854845)
    assert "Frenzy's own Speed 0.99/s" in reason
    assert "2 of 3 max" in reason
    assert "2.19" not in reason


@pytest.mark.pob
@needs_pob
def test_poison_spectral_throw_boss_lane_drops_block_and_steal_charges(tmp_path: Path) -> None:
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-charges-pst", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "poison_spectral_throw.pob.txt").read_text(encoding="utf-8").strip()))
        state = pob.read_state()["config_state"]
        pob.set_config(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None", preserve="none")
        d = derive_config(pob, prefer_rules=True)
        # Deflection (endurance on block) and Claws of the Magpie (steal) are the build's only generators
        assert d.conservative.inputs.get("useEnduranceCharges") is not True
        assert "block" in d.conservative.reasons["useEnduranceCharges"]
        assert d.optimistic.inputs.get("useEnduranceCharges") is True


def test_chance_debuff_uptime_rule() -> None:
    from junkroan.optimizer.config_rules import _chance_debuff_uptime

    # Dismembering: 20% to maim on crit at 50% crit, 4.34 hits/s over 4 s: 1 - 0.9^17.4 = 84% (below the 90% bar)
    up, line = _chance_debuff_uptime("Maimed", STATS, "20% chance to maim enemies on critical strike with attacks")
    assert 0.8 < up < 0.9 and "maim" in line
    # 30% on hit: 1 - 0.7^17.4 -> 99.8%
    up, _l = _chance_debuff_uptime("Maimed", STATS, "30% chance to maim enemies on hit")
    assert up > 0.99
    assert _chance_debuff_uptime("Blinded", STATS, "20% chance to maim enemies on hit") is None



def test_self_cost_on_use_counts_the_main_skill_unless_triggered() -> None:
    from junkroan.optimizer.objective import Objective
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.self_cost import STAT_NAME, context_for, self_cost_per_second, with_self_cost

    text = "lose 10% of life and energy shield when you use a chaos skill\n+20% to chaos damage over time multiplier"
    ctx = context_for(text, frozenset({"chaos", "spell"}), main_triggered=False)
    assert dict(ctx.fractions) == {"EnergyShield": 0.1, "Life": 0.1}
    assert abs(self_cost_per_second({"Life": 4000, "EnergyShield": 500, "Speed": 4.0}, ctx) + 1800.0) < 1e-9
    assert context_for(text, frozenset({"chaos", "spell"}), main_triggered=True).fractions == ()  # Spellslinger: not "used"
    assert context_for(text, frozenset({"fire", "spell"}), main_triggered=False).fractions == ()  # not a chaos skill
    # the rails' idle-recovery relation names the stat: the mastery disqualifies a 4-casts-per-second chaos skill
    obj = with_self_cost(Rails.load().objective(), ctx)
    assert any(STAT_NAME in part for rel in obj.relations for part in rel[:2])
    base = {"CombinedDPS": 1.0, "Life": 4000, "EnergyShield": 500, "Speed": 4.0, "NetLifeRegen": 300, "NetEnergyShieldRegen": 0, "LifeLeechGainRate": 400, "LifeRecoup": 0}
    parts = obj.violations({**base, "PhysicalMaximumHitTaken": 9000, "FireMaximumHitTaken": 30000, "ColdMaximumHitTaken": 30000, "LightningMaximumHitTaken": 30000, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "EffectiveMovementSpeedMod": 1.3})
    assert any(STAT_NAME in k for k in parts)  # 300 regen - 1800 loss = -1500/s while idle, and the leech does not count
