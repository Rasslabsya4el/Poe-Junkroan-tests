"""Warcry charge arithmetic and the deliberately unresolved incoming-hit rate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import (
    build_facts,
    build_text,
    charge_rule,
    charge_sources,
    derive_config,
    _conservative_allows,
    warcry_charge_effect_ids,
    warcry_charge_sources,
    warcry_usage_proof,
)
from junkroan.optimizer.ramp_inputs import Gem
from junkroan.mechanics.pending_facts import fact
from junkroan.pob import skill_facts

ROOT = Path(__file__).resolve().parents[1]

LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not skill_facts._blocks(), reason="PoB skill data not present (vendor/pob/source or the pinned runtime)")

SEVEN_WARCRIES = (
    "z325_gladiator_spectral_shield_throw",
    "z325_slayer_ground_slam",
    "z326_berserker_volcanic_fissure",
    "z327_gladiator_earthquake",
    "z327_slayer_earthshatter",
    "z328_hierophant_shock_nova_archmage",
    "z329_gladiator_earthquake",
)
TWO_WHEN_HIT = ("z327_juggernaut_boneshatter", "z329_juggernaut_boneshatter")


def _ziz_path(reference: str) -> Path:
    league, slug = reference[1:4], reference[5:]
    return ROOT / "tests" / "fixtures" / f"zizaran_{league}" / "early" / f"{slug}.pob.txt"


@needs_skill_data
def test_enduring_cry_uses_pob_constant_power_and_effective_cooldown() -> None:
    stat, per_power = skill_facts.constant_stats_matching("EnduringCry", r"_charge_granted_per_X_monster_power")[0]
    assert stat == "endurance_charge_granted_per_X_monster_power_during_endurance_warcry"
    assert per_power == 5.0
    gems = (Gem("enduring cry", "EnduringCry", 18),)
    sources = warcry_charge_sources(gems, {"EnduringCry": {"WarcryPower": 20.0, "Cooldown": 8.0}})
    assert warcry_charge_effect_ids(gems) == ("EnduringCry",)
    assert sources == [
        {
            "kind": "Endurance",
            "count": int(20.0 // per_power),
            "power": 20.0,
            "per_power": per_power,
            "cooldown": 8.0,
            "effect_id": "EnduringCry",
            "line": "enduring cry",
            "trigger": "warcry",
            "chance": 1.0,
            "period": None,
            "needs": None,
        }
    ]
    use, why, override, rate = charge_rule(
        "useEnduranceCharges",
        {"EnduranceChargesMax": 3, "EnduranceChargesDuration": 10},
        "",
        frozenset({"warcry"}),
        warcry_sources=sources,
    )
    assert use and override is None and rate == 4.0 / 8.0
    assert "20 Warcry Power / 5 per charge" in why and "4.0 within the 2.5 s ramp budget (3 of 3 max)" in why

    # One immediate use at t=0 and two cooldown uses at t=1/2, not a fractional third use at t=2.5.
    fast = [{**sources[0], "cooldown": 1.0}]
    use, why, override, rate = charge_rule(
        "useEnduranceCharges",
        {"EnduranceChargesMax": 20, "EnduranceChargesDuration": 10},
        "",
        frozenset({"warcry"}),
        warcry_sources=fast,
    )
    assert use and override == 12 and rate == 4.0
    assert "12.0 within the 2.5 s ramp budget (12 of 20 max)" in why

    # A disabled gem never reaches BuildFacts, so it cannot become a warcry source or turn charges on.
    class DisabledWarcryPob:
        def read_state(self):
            return {"skills_state": {"main_socket_group_id": "main", "socket_groups": [{
                "socket_group_id": "main",
                "enabled": True,
                "gems": [
                    {"gem_name": "Fireball", "enabled": True, "is_support": False, "level": 18},
                    {"gem_name": "Enduring Cry", "enabled": False, "is_support": False, "level": 18},
                ],
                "active_skill_entries": [],
            }]}}

    facts = build_facts(DisabledWarcryPob(), {}, 2.5, {})
    assert not warcry_charge_sources(facts.gems, {"EnduringCry": {"WarcryPower": 20.0, "Cooldown": 8.0}})
    assert not charge_rule("useEnduranceCharges", {"EnduranceChargesMax": 3, "EnduranceChargesDuration": 10}, "", frozenset())[0]


def test_when_you_are_hit_is_classified_but_has_no_conservative_rate() -> None:
    line = "30% chance to gain an Endurance Charge when you are Hit"
    (source,) = charge_sources("Endurance", line)
    assert source["trigger"] == "when_hit" and source["chance"] == 0.30
    use, why, override, rate = charge_rule(
        "useEnduranceCharges",
        {"EnduranceChargesMax": 3, "EnduranceChargesDuration": 10},
        line,
        frozenset(),
    )
    assert not use and override is None and rate == 0.0
    assert "pending fact enemy_hits_per_second" in why
    pending = fact("enemy_hits_per_second")
    assert pending is not None and pending.pending and pending.value is None
    assert set(pending.moves) == set(TWO_WHEN_HIT)


@needs_skill_data
def test_autoexertion_only_excludes_warcries_in_its_own_socket_group() -> None:
    class AutoexertionWarcryPob:
        def read_state(self):
            return {"skills_state": {"socket_groups": [{
                "socket_group_id": "warcries",
                "enabled": True,
                "gems": [
                    {"gem_name": "Autoexertion", "skill_id": "Autoexertion", "enabled": True, "is_support": False, "level": 18},
                    {"gem_name": "Enduring Cry", "skill_id": "EnduringCry", "enabled": True, "is_support": False, "level": 18},
                ],
                "active_skill_entries": [{"name": "Enduring Cry", "triggered": False}],
            }]}}

    facts = build_facts(AutoexertionWarcryPob(), {}, 2.5, {})
    usage_proven, _reason = warcry_usage_proof(facts.gems)

    assert not usage_proven
    assert not warcry_charge_sources(
        facts.gems,
        {"EnduringCry": {"WarcryPower": 20.0, "Cooldown": 8.0}},
    )
    allowed, _reason = _conservative_allows(
        "conditionUsedWarcryRecently",
        {"ifCond": "UsedWarcryRecently"},
        {},
        "",
        frozenset({"warcry"}),
    )
    assert allowed


@needs_skill_data
def test_pob_triggered_warcry_is_not_a_charge_source() -> None:
    class TriggeredWarcryPob:
        def read_state(self):
            return {"skills_state": {"socket_groups": [{
                "socket_group_id": "warcry",
                "enabled": True,
                "gems": [{"gem_name": "Enduring Cry", "skill_id": "EnduringCry", "enabled": True, "is_support": False, "level": 18}],
                "active_skill_entries": [{"name": "Enduring Cry", "triggered": True}],
            }]}}

    facts = build_facts(TriggeredWarcryPob(), {}, 2.5, {})
    assert facts.gems[0].triggered
    assert not warcry_usage_proof(facts.gems)[0]
    assert not warcry_charge_sources(facts.gems, {"EnduringCry": {"WarcryPower": 20.0, "Cooldown": 8.0}})


@needs_skill_data
def test_item_trigger_granted_warcry_is_not_a_charge_source() -> None:
    class TriggeredItemWarcryPob:
        def read_state(self):
            return {
                "gear_slots": {"slots": {"Ring 1": {"item": {"explicit_affixes": [
                    "Trigger Level 10 Enduring Cry when you take a Savage Hit",
                ]}}}},
                "skills_state": {"socket_groups": [{
                    "socket_group_id": "ring-warcry",
                    "source_kind": "item",
                    "slot": "Ring 1",
                    "enabled": True,
                    "gems": [{"gem_name": "Enduring Cry", "skill_id": "EnduringCry", "enabled": True, "is_support": False, "level": 10}],
                    "active_skill_entries": [{"name": "Enduring Cry", "triggered": False}],
                }]},
            }

    facts = build_facts(TriggeredItemWarcryPob(), {}, 2.5, {})
    assert facts.gems[0].triggered
    assert not warcry_usage_proof(facts.gems)[0]
    assert not warcry_charge_sources(facts.gems, {"EnduringCry": {"WarcryPower": 20.0, "Cooldown": 8.0}})


@pytest.mark.pob
@needs_pob
def test_enabled_enduring_cries_are_reenabled_and_when_hit_reasons_remain_named(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-warcry-charge-fixtures", artifacts_root=tmp_path) as pob:
        for reference in SEVEN_WARCRIES:
            pob.load_xml(decode_import_code(_ziz_path(reference).read_text(encoding="utf-8").strip()))
            before_state = pob.read_state()
            before_stats = pob.stats(("CombinedDPS", "Life", "TotalEHP"))
            derived = derive_config(pob, prefer_rules=True)
            after_state = pob.read_state()
            after_stats = pob.stats(("CombinedDPS", "Life", "TotalEHP"))
            text = build_text(pob)
            facts = build_facts(pob, pob.stats(), 2.5, pob.config_inputs(), text)
            effects = warcry_charge_effect_ids(facts.gems)
            values = pob.active_skill_stats(effects, ("Cooldown", "WarcryPower"))
            print(f"{reference}: {values}")
            assert derived.conservative.inputs.get("useEnduranceCharges") is True
            assert "Warcry Power" in derived.conservative.reasons["useEnduranceCharges"]
            assert values["EnduringCry"]["WarcryPower"] == 20
            assert values["EnduringCry"]["Cooldown"] > 0
            assert before_state == after_state and before_stats == after_stats, "selecting a warcry for its cooldown must restore the build"

        pob.load_xml(decode_import_code(_ziz_path("z327_juggernaut_boneshatter").read_text(encoding="utf-8").strip()))
        derived = derive_config(pob, prefer_rules=True)
        assert derived.conservative.inputs.get("useEnduranceCharges") is True
        assert derived.conservative.inputs.get("overrideEnduranceCharges") == 4
        assert "20 Warcry Power / 5 per charge" in derived.conservative.reasons["useEnduranceCharges"]
