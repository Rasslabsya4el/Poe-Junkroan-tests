"""Proof rules from the user's reading of the frozen campaigns (2026-09-18):

- a generator line needs the skill kind its trigger names (no banner, no charges);
- a gem's own text is proof text (Frenzy generates frenzy charges);
- a buff proved by an on-kill source is off on the boss lane;
- an enabler gem turns its own Skill Option on (Flame Wall);
- "have you crit recently" is proven by uptime, not by a flat crit-chance bar;
- a corpse condition follows a creator plus a consumer in the build (rule 21).

Pure except for the marked tests: they load the references the rules came from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from junkroan.optimizer.config_rules import (
    CRIT_RECENTLY_WINDOW_SECONDS,
    _conservative_allows,
    _crit_recently,
    build_text,
    charge_rule,
    charge_sources,
    corpse_cycle,
    derive_config,
    missing_enabler,
)
from junkroan.optimizer.ramp_inputs import Gem
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.skill_facts import SKILL_DATA_DIRS, granted_effect_lines

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not SKILL_DATA_DIRS[0].is_dir(), reason=f"PoB skill data not present at {SKILL_DATA_DIRS[0]}")

STATS = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "EnduranceChargesMax": 3, "EnduranceChargesDuration": 10,
         "PowerChargesMax": 3, "PowerChargesDuration": 10, "Speed": 4.34, "CritChance": 50}
BANNER_LINE = "Gain 3 Endurance Charges when you consume maximum Valour to place a Banner"
ONSLAUGHT_OPTION = {"condition_flags": [{"name": "Onslaught", "conditions": ["Combat"]}]}


def _source(line: str, condition: str, *preconditions: str) -> dict[str, dict]:
    return {
        line: {
            "ok": True,
            "unsupported": False,
            "mods": [{
                "name": f"Condition:{condition}",
                "type": "FLAG",
                "tags": [{"type": "Condition", "var": condition} for condition in preconditions],
            }],
        },
    }


# -- R1.1 a generator needs its enabler ---------------------------------------------------


@pytest.mark.parametrize("line,kind", [
    (BANNER_LINE, "banner"),
    ("Gain a Frenzy Charge when you Warcry", "warcry"),
    ("Gain a Power Charge when your Mine is Detonated", "mine"),
    ("Gain an Endurance Charge when your Trap is Triggered", "trap"),
    ("Gain a Frenzy Charge when your Totem hits an enemy", "totem"),
    ("10% chance to gain a Frenzy Charge when you Hit your Marked Enemy", "mark"),
])
def test_the_kind_a_line_needs_is_named(line: str, kind: str) -> None:
    assert missing_enabler(line.lower(), frozenset()) == kind
    assert missing_enabler(line.lower(), frozenset({kind})) is None


def test_a_banner_cluster_without_a_banner_is_not_a_charge_source() -> None:
    # shockwave_cyclone and static_strike took maximum endurance and frenzy charges off this
    use, why, _override, rate = charge_rule("useEnduranceCharges", STATS, BANNER_LINE.lower(), frozenset())
    assert not use and rate == 0.0 and "needs a banner skill" in why
    # the same line in a build that does carry a banner is the proof it reads as
    assert charge_rule("useEnduranceCharges", STATS, BANNER_LINE.lower(), frozenset({"banner"}))[0]


def test_an_unparsed_banner_buff_line_is_not_a_proof() -> None:
    text = "gain onslaught when you place a banner"
    assert not _conservative_allows("buffOnslaught", {}, {}, text, frozenset())[0]
    assert not _conservative_allows("buffOnslaught", {}, {}, text, frozenset({"banner"}))[0]


def test_channelling_generator_requires_the_main_skill() -> None:
    line = "Gain a Power Charge each second while Channelling a Spell"
    # A channelled utility gem is not enough: the main skill must keep the source active.
    (source,) = charge_sources("Power", line, frozenset({"spell", "channelling"}), frozenset({"spell"}))
    assert source["needs"] == "channelling"
    (source,) = charge_sources("Power", line, frozenset({"spell", "channelling"}), frozenset({"spell", "channelling"}))
    assert source["needs"] is None
    assert source["trigger"] == "periodic" and source["period"] == 1.0 and source["chance"] == 1.0


def test_channelling_charge_preserves_its_chance() -> None:
    (source,) = charge_sources("Endurance", "25% chance to gain an Endurance Charge each second while Channelling", frozenset({"channelling"}), frozenset({"channelling"}))
    assert source["needs"] is None
    assert source["trigger"] == "periodic" and source["period"] == 1.0 and source["chance"] == 0.25
    use, _why, _override, rate = charge_rule("useEnduranceCharges", STATS, "25% chance to gain an Endurance Charge each second while Channelling", frozenset({"channelling"}), ramp_seconds=10.0, main_tags=frozenset({"channelling"}))
    assert use and rate == 0.25


def test_proxy_channelling_does_not_generate_player_charges() -> None:
    line = "Gain a Power Charge each second while Channelling a Spell"
    use, why, override, rate = charge_rule(
        "usePowerCharges", {"PowerChargesMax": 3, "PowerChargesDuration": 10}, line,
        frozenset({"spell", "channelling", "totem"}), main_tags=frozenset({"spell", "channelling", "totem"}),
    )
    assert not use and override is None and rate == 0.0
    assert "proxy main skill" in why


def test_proxy_main_skill_does_not_prove_a_parsed_hit_or_channelling_condition() -> None:
    onslaught = _source("gain onslaught while channelling", "Onslaught", "Channelling")
    ok, why = _conservative_allows(
        "buffOnslaught", {}, {}, "gain onslaught while channelling", frozenset({"spell", "channelling", "totem"}),
        main_tags=frozenset({"spell", "channelling", "totem"}), parsed=onslaught, option=ONSLAUGHT_OPTION,
    )
    assert not ok and "proxy main skill" in why


def test_proxy_subject_condition_remains_proven_by_the_proxy_main_skill() -> None:
    ok, why = _conservative_allows(
        "conditionTotemsHitRecently", {"ifCond": "HitRecently"}, {}, "", frozenset({"attack", "totem"}),
        main_tags=frozenset({"attack", "totem"}),
    )
    assert ok and "sustained by using the main skill" in why


def test_parsed_proxy_subject_condition_uses_the_proxy_not_the_player() -> None:
    assert _conservative_allows(
        "conditionTotemsHitRecently", {"ifCond": "TotemsHitRecently"}, {}, "", frozenset({"attack", "totem"}),
        main_tags=frozenset({"attack", "totem"}),
    )[0]
    ok, why = _conservative_allows(
        "conditionTotemsKilledRecently", {"ifCond": "TotemsKilledRecently"}, {}, "", frozenset({"attack", "totem"}),
        main_tags=frozenset({"attack", "totem"}),
    )
    assert not ok and "needs kills" in why


def test_channelling_buff_proof_requires_the_main_skill() -> None:
    text = "gain onslaught while channelling"
    parsed = _source(text, "Onslaught", "Channelling")
    assert not _conservative_allows("buffOnslaught", {}, {}, text, frozenset({"channelling"}), main_tags=frozenset(), parsed=parsed, option=ONSLAUGHT_OPTION)[0]
    assert _conservative_allows("buffOnslaught", {}, {}, text, frozenset({"channelling"}), main_tags=frozenset({"channelling"}), parsed=parsed, option=ONSLAUGHT_OPTION)[0]


# -- R1.2 the gems' own text is proof text ------------------------------------------------


FRENZY_TEXT = "performs an attack with a ranged weapon that gives the character a frenzy charge if it hits. frenzy charges increase your attack speed."


def test_a_skills_own_grant_line_is_classified_as_a_source() -> None:
    (source,) = charge_sources("Frenzy", FRENZY_TEXT)
    assert source["trigger"] == "hit" and source["chance"] == 1.0
    # "grants" and "gives" are the verbs a skill's text uses where an item says "gain"
    assert charge_sources("Endurance", "grants an endurance charge on hit")[0]["trigger"] == "hit"


def test_frenzy_turns_its_own_charges_on() -> None:
    # vd_spellslinger (Frenzy as the Spellslinger trigger) and burning_arrow_snipe
    # (Manaforged Arrows + Frenzy): a triggered Frenzy still hits, so it still generates
    use, why, override, _rate = charge_rule("useFrenzyCharges", STATS, FRENZY_TEXT, frozenset())
    assert use and override is None and "hits/s" in why


def test_a_skill_that_grants_its_charge_on_a_kill_does_not_count() -> None:
    # Power Siphon's own text; Blood Rage's rendered "25% chance to gain a Frenzy Charge on Kill"
    siphon = "fires your wand to fire a single projectile each at a number of nearby enemies, granting you a power charge if an enemy is killed by, or soon after, the hit."
    assert not charge_rule("usePowerCharges", STATS, siphon, frozenset())[0]
    assert not charge_rule("useFrenzyCharges", STATS, "25% chance to gain a frenzy charge on kill", frozenset())[0]
    # Assassin's Mark: "when slain" is a kill too (shockwave_cyclone and static_strike read it as a full source)
    assert not charge_rule("usePowerCharges", STATS, "cursed enemies have a 100% chance to grant a power charge when slain", frozenset({"mark", "curse"}))[0]


@needs_skill_data
def test_pob_is_the_source_of_the_gems_text() -> None:
    frenzy = " ".join(granted_effect_lines("Frenzy")).lower()
    assert "frenzy charge" in frenzy and "if it hits" in frenzy
    flicker = [line.lower() for line in granted_effect_lines("FlickerStrike")]
    assert "15% chance to gain a frenzy charge on hit" in flicker  # rendered from add_frenzy_charge_on_skill_hit_%
    assert granted_effect_lines("NoSuchSkill") == ()


@pytest.mark.pob
@needs_pob
def test_vd_spellslinger_gets_its_frenzy_charges(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-enabler-vd", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((FIXTURES / "vd_spellslinger.pob.txt").read_text(encoding="utf-8").strip()))
        assert "frenzy charge" in build_text(pob, TreeGraph.load())  # only gem names before this rule
        d = derive_config(pob, prefer_rules=True)
        assert d.conservative.inputs.get("useFrenzyCharges") is True
        assert "frenzy charge" in d.conservative.reasons["useFrenzyCharges"]


# -- R1.3 an on-kill source proves nothing on a boss --------------------------------------


def test_onslaught_on_kill_is_off_in_the_boss_lane() -> None:
    # impale_cyclone: buffOnslaught stood on "20% chance to gain Onslaught for 4 seconds on Kill"
    text = "20% chance to gain onslaught for 4 seconds on kill"
    ok, why = _conservative_allows("buffOnslaught", {}, {}, text, frozenset(), parsed=_source(text, "Onslaught", "KilledRecently"), option=ONSLAUGHT_OPTION)
    assert not ok and "KilledRecently needs kills" in why


def test_a_source_that_does_not_need_a_kill_still_proves_it() -> None:
    text = "you have onslaught while at maximum frenzy charges"
    ok, why = _conservative_allows("buffOnslaught", {}, {}, text, frozenset(), parsed=_source(text, "Onslaught"), option=ONSLAUGHT_OPTION)
    assert ok and "source parsed by PoB" in why


def test_leech_keeps_pobs_own_rate_as_a_fallback() -> None:
    ok, why = _conservative_allows("conditionLeeching", {}, {"LifeLeechGainRate": 120.0}, "", frozenset())
    assert ok and "leech rate" in why


# -- R1.4 an enabler gem turns its condition on -------------------------------------------


class _OptionsPob:
    def __init__(self, options: list[dict[str, Any]]) -> None:
        self._options = options

    def config_options(self, predicates: Any = None) -> list[dict[str, Any]]:
        return [dict(o) for o in self._options]

    def stats(self, keys: Any = None) -> dict[str, Any]:
        return {}

    def config_inputs(self) -> dict[str, Any]:
        return {}

    def read_state(self) -> dict[str, Any]:
        return {"skills_state": {}, "tree_state": {}}


def _derive(var: str):
    return derive_config(_OptionsPob([{"var": var, "shown": True, "refs": []}]), graph=TreeGraph.load(), assumptions={})


def test_flame_wall_in_the_build_means_projectiles_went_through_it() -> None:
    d = _derive("flameWallAddedDamage")  # kinetic_fusillade carried the wall with the input off
    assert d.conservative.inputs["flameWallAddedDamage"] is True
    assert "Flame Wall" in d.conservative.reasons["flameWallAddedDamage"]
    assert d.optimistic.inputs["flameWallAddedDamage"] is True


def test_a_skill_option_that_is_still_an_assumption_stays_off() -> None:
    d = _derive("ColdSnapBypassCD")  # bypassing a cooldown costs charges: not a fact of play
    assert "ColdSnapBypassCD" not in d.conservative.inputs
    assert d.optimistic.inputs["ColdSnapBypassCD"] is True


# -- R1.5 "have you crit recently" is proven by uptime ------------------------------------


BURNING_ARROW = {"CritChance": 10.584, "HitChance": 98, "Speed": 0.96807272727273}
KINETIC_FUSILLADE = {"CritChance": 68.382, "HitChance": 100, "Speed": 3.35625}


def test_a_slow_low_crit_attack_does_not_keep_it_up() -> None:
    ok, why = _crit_recently(BURNING_ARROW, frozenset())
    assert not ok and "58% of the time" in why and "10.6% effective crit" in why  # PoB's CritChance has the accuracy roll in: HitChance is not applied twice


def test_a_fast_critting_attack_does() -> None:
    ok, why = _crit_recently(KINETIC_FUSILLADE, frozenset())
    assert ok and "100% of the time" in why


def test_the_window_is_the_keystones_own_eight_seconds() -> None:
    assert CRIT_RECENTLY_WINDOW_SECONDS == 8.0
    # one hit per second: 26% crit is 1 - 0.74^8 = 91%, 24% is 1 - 0.76^8 = 89%, either side of the bar
    assert _crit_recently({"CritChance": 26, "HitChance": 100, "Speed": 1.0}, frozenset())[0]
    assert not _crit_recently({"CritChance": 24, "HitChance": 100, "Speed": 1.0}, frozenset())[0]


def test_minions_crit_for_themselves() -> None:
    ok, why = _crit_recently({"CritChance": 95, "HitChance": 100, "Speed": 5.0}, frozenset({"minion", "spell"}))
    assert not ok and "minions" in why


@pytest.mark.parametrize("cond", ["CritRecently", "SkillCritRecently", "DealtCritRecently"])
def test_the_config_inputs_follow_the_same_uptime(cond: str) -> None:
    assert not _conservative_allows(f"condition{cond}", {"ifCond": cond}, BURNING_ARROW, "", frozenset())[0]
    assert _conservative_allows(f"condition{cond}", {"ifCond": cond}, KINETIC_FUSILLADE, "", frozenset())[0]


# -- R21 a corpse condition follows a creator plus a consumer in the build -----------------


SPAWNED, CONSUMED = "conditionSpawnedCorpseRecently", "conditionConsumedCorpseRecently"
SPAWNED_PREDS, CONSUMED_PREDS = {"ifCond": "SpawnedCorpseRecently"}, {"ifCond": "ConsumedCorpseRecently"}
VD_CYCLE = ("desecrate", "volatile dead")


def test_a_creator_and_a_consumer_prove_both_corpse_conditions() -> None:
    ok, why = _conservative_allows(CONSUMED, CONSUMED_PREDS, {}, "", frozenset(), corpse=VD_CYCLE)
    assert ok and why == "Desecrate creates corpses and Volatile Dead consumes them every cast"
    ok, why = _conservative_allows(SPAWNED, SPAWNED_PREDS, {}, "", frozenset(), corpse=VD_CYCLE)
    assert ok and why == "Desecrate creates corpses every cast"


def test_a_creator_alone_spawns_corpses_and_consumes_none() -> None:
    assert _conservative_allows(SPAWNED, SPAWNED_PREDS, {}, "", frozenset(), corpse=("desecrate", None))[0]
    ok, why = _conservative_allows(CONSUMED, CONSUMED_PREDS, {}, "", frozenset(), corpse=("desecrate", None))
    assert not ok and "nothing in the build consumes them" in why


@pytest.mark.parametrize("var,preds", [(SPAWNED, SPAWNED_PREDS), (CONSUMED, CONSUMED_PREDS)])
def test_a_consumer_with_nothing_to_eat_proves_neither(var: str, preds: dict) -> None:
    ok, why = _conservative_allows(var, preds, {}, "", frozenset(), corpse=(None, "volatile dead"))
    assert not ok and "no gem in the build creates corpses" in why


@needs_skill_data
def test_the_cycle_is_read_off_the_gems_and_an_on_kill_corpse_is_not_one() -> None:
    gems = (Gem("fireball", "Fireball", 18), Gem("desecrate", "Desecrate", 18), Gem("volatile dead", "VolatileDead", 18))
    assert corpse_cycle(gems) == VD_CYCLE
    assert corpse_cycle(gems[:1]) == (None, None) and corpse_cycle(()) == (None, None)
    # a corpse a kill leaves (Undertaker, "enemies you kill leave a corpse") is text, not a gem:
    # it never proves the condition, so the on-kill verdict still holds it off on a boss
    ok, why = _conservative_allows(CONSUMED, CONSUMED_PREDS, {}, "enemies you kill leave a corpse", frozenset(), corpse=corpse_cycle(gems[:1]))
    assert not ok and "a kill leaves is not a source on a boss" in why


class _CountPob(_OptionsPob):
    """A build carrying a corpse count in its own config and no gem that makes a corpse."""

    def config_inputs(self) -> dict[str, Any]:
        return {"multiplierCorpseConsumedRecently": 25}


def test_the_count_of_corpses_is_off_when_its_condition_is() -> None:
    # archmage_volatile_dead held 25 in the boss lane on "kept from the build's config" while the
    # condition it counts was off: the count and the condition are one fact
    d = derive_config(_CountPob([{"var": "multiplierCorpseConsumedRecently", "shown": True, "refs": []}]), graph=TreeGraph.load(), assumptions={})
    assert "multiplierCorpseConsumedRecently" not in d.conservative.inputs
    assert "no gem in the build creates corpses" in d.conservative.reasons["multiplierCorpseConsumedRecently"]
    assert d.optimistic.inputs["multiplierCorpseConsumedRecently"] == 25  # the optimistic lane is untouched


@pytest.mark.pob
@needs_pob
def test_archmage_volatile_dead_makes_the_corpses_it_eats(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-enabler-corpse", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((FIXTURES / "archmage_volatile_dead.pob.txt").read_text(encoding="utf-8").strip()))
        d = derive_config(pob, prefer_rules=True)
        assert d.conservative.inputs.get(SPAWNED) is True and d.conservative.inputs.get(CONSUMED) is True
        assert d.conservative.reasons[CONSUMED].startswith("Desecrate creates corpses and Volatile Dead consumes them every cast")
        # and the count agrees with the condition: 3.38 casts/s x 3 corpses x 0.5 (both hand cast) x 2.5 s
        assert d.conservative.inputs["multiplierCorpseConsumedRecently"] == 12
