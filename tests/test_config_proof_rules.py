"""What a config lane may claim, from the user's reading of run E (2026-09-16). Pure: no PoB.

Four rules measured on real seeds:
- a damaging ailment needs its damage *and* its uptime (toxic_rain's Ignited came from an
  IgniteChance of 33.6 with IgniteDPS 0; cold_dot's from an IgniteDPS of 10.67 with a 2% chance);
- a socket group with no active gem proves nothing (smite's helmet held only "Fortify");
- a charge count is written only where its use flag is on (smite carried overrideFrenzyCharges
  without useFrenzyCharges);
- "been hit" is a fact of the fight, true in both lanes (Wind Dancer was taken on PoB's
  "you have not been hit" default).
"""

from __future__ import annotations

from typing import Any

from junkroan.optimizer.config_rules import _conservative_allows, _gem_names, build_text, derive_config
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.session import PobSession

IGNITED_PREDS = {"ifEnemyCond": "Ignited"}


# -- an ailment needs damage and uptime -------------------------------------------------


def test_ignite_chance_without_ignite_damage_is_not_proof() -> None:
    # toxic_rain s1: 33.6% ignite chance at 3.9 hits/s, but no fire in the hit
    ok, why = _conservative_allows("conditionEnemyIgnited", IGNITED_PREDS, {"IgniteChance": 33.6, "Speed": 3.9, "IgniteDPS": 0}, "")
    assert not ok and "IgniteDPS" in why


def test_ignite_damage_without_uptime_is_not_proof() -> None:
    # cold_dot s2: one item's fire damage ignites, with a chance that never keeps it up
    ok, why = _conservative_allows("conditionEnemyIgnited", IGNITED_PREDS, {"IgniteDPS": 10.67, "IgniteChance": 2, "Speed": 1.0}, "")
    assert not ok and "IgniteChance" in why


def test_both_together_prove_the_ailment() -> None:
    ok, why = _conservative_allows("conditionEnemyIgnited", IGNITED_PREDS, {"IgniteDPS": 5000, "IgniteChance": 100, "Speed": 2}, "")
    assert ok and "IgniteDPS" in why and "IgniteChance" in why


def test_burning_and_poison_follow_the_same_rule() -> None:
    assert not _conservative_allows("conditionEnemyBurning", {"ifEnemyCond": "Burning"}, {"IgniteChance": 100, "Speed": 4}, "")[0]
    assert not _conservative_allows("conditionEnemyPoisoned", {"ifEnemyCond": "Poisoned"}, {"PoisonChance": 100, "Speed": 4}, "")[0]
    assert _conservative_allows("conditionEnemyPoisoned", {"ifEnemyCond": "Poisoned"}, {"PoisonChance": 100, "TotalPoisonDPS": 5000, "Speed": 4}, "")[0]


def test_a_non_damaging_ailment_keeps_the_chance_only_rule() -> None:
    ok, why = _conservative_allows("conditionEnemyBlinded", {"ifEnemyCond": "Blinded"}, {"BlindChance": 100, "Speed": 2}, "")
    assert ok and "Blinded" in why


# -- a group with no active gem ---------------------------------------------------------


def _group(names: list[str], enabled: bool = True) -> dict[str, Any]:
    return {"enabled": enabled, "gems": [{"gem_name": n, "enabled": True} for n in names]}


class _SkillsPob:
    def __init__(self, groups: list[dict[str, Any]]) -> None:
        self._groups = groups

    def read_state(self) -> dict[str, Any]:
        return {"skills_state": {"socket_groups": self._groups}, "tree_state": {}}


def test_a_support_only_group_names_no_gems() -> None:
    assert _gem_names(_SkillsPob([_group(["Fortify"])])) == []


def test_a_group_with_an_active_gem_keeps_its_supports() -> None:
    pob = _SkillsPob([_group(["Smite", "Fortify"]), _group(["Fortify"])])
    assert _gem_names(pob) == ["Smite", "Fortify"]


def test_a_disabled_group_is_skipped_as_before() -> None:
    assert _gem_names(_SkillsPob([_group(["Smite", "Fortify"], enabled=False)])) == []


def test_build_text_does_not_read_a_support_only_group() -> None:
    graph = TreeGraph.load()
    assert "fortif" not in build_text(_SkillsPob([_group(["Fortify"])]), graph)
    assert "fortif" in build_text(_SkillsPob([_group(["Smite", "Fortify"])]), graph)


# -- a charge count only where the use flag is on ---------------------------------------


class _RecordingAdapter:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def apply_config_state(self, handle: Any, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class _ConfigSession(PobSession):
    def config_inputs(self) -> dict[str, Any]:
        return {"overrideFrenzyCharges": 1, "multiplierPoisonOnEnemy": 5}


def test_a_charge_override_is_written_only_where_its_use_flag_is_on() -> None:
    session = _ConfigSession.__new__(_ConfigSession)
    session._adapter = _RecordingAdapter()
    session._handle = object()
    session.set_config(inputs={"usePowerCharges": True}, conditional={"inputs": {"useFrenzyCharges": True}})

    sets = {c["title"]: c["inputs"] for c in session._adapter.payloads[0]["config_sets"]}
    assert "overrideFrenzyCharges" not in sets["Baseline"]  # the flag is off in this lane
    assert sets["Baseline"]["multiplierPoisonOnEnemy"] == 5 and sets["Baseline"]["usePowerCharges"] is True
    assert sets["Conditional"]["overrideFrenzyCharges"] == 1 and sets["Conditional"]["useFrenzyCharges"] is True


# -- "been hit" is a fact of the fight ---------------------------------------------------


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


def _derive(options: list[dict[str, Any]]):
    return derive_config(_OptionsPob(options), graph=TreeGraph.load(), assumptions={})


def test_been_hit_by_an_attack_is_true_in_both_lanes() -> None:
    d = _derive([{"var": "conditionBeenHitByAttackRecently", "shown": True, "refs": []}])
    assert d.conservative.inputs["conditionBeenHitByAttackRecently"] is True
    assert d.optimistic.inputs["conditionBeenHitByAttackRecently"] is True
    assert d.conservative.reasons["conditionBeenHitByAttackRecently"] == "a boss attacks you"
    assert d.optimistic.reasons["conditionBeenHitByAttackRecently"] == "a boss attacks you"


def test_been_hit_recently_too_and_a_build_that_does_not_show_it_has_no_entry() -> None:
    d = _derive([{"var": "conditionBeenHitRecently", "shown": True, "refs": []}])
    assert d.conservative.inputs["conditionBeenHitRecently"] is True and d.optimistic.inputs["conditionBeenHitRecently"] is True
    off = _derive([{"var": "conditionBeenHitByAttackRecently", "shown": False, "refs": []}])
    assert "conditionBeenHitByAttackRecently" not in off.conservative.inputs
    assert "conditionBeenHitByAttackRecently" not in off.optimistic.inputs
