"""Player buff proofs come from PoB parser flags, never word matches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_conservative_generator_inputs
from junkroan.optimizer import config_rules
from junkroan.optimizer.config_rules import clear_parse_mods_cache, derive_config, parse_mods_batch, parsed_buff_proof
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.skill_facts import granted_effect_lines
from junkroan.pob.session import PobSession
from junkroan.mechanics.skill_use_ending_buffs import load as load_skill_use_ending_buffs

from conftest import needs_skill_source


def _row(line: str, *mods: dict) -> dict:
    return {"line": line, "ok": True, "unsupported": False, "mods": list(mods)}


def _flag(condition: str, *tags: str) -> dict:
    return {
        "name": f"Condition:{condition}",
        "type": "FLAG",
        "tags": [{"type": "Condition", "var": tag} for tag in tags],
    }


ARCANE_OPTION = {"condition_flags": [{"name": "ArcaneSurge", "conditions": ["Combat"]}]}
ONSLAUGHT_OPTION = {"condition_flags": [{"name": "Onslaught", "conditions": ["Combat"]}]}
PHASING_OPTION = {"condition_flags": [{"name": "Phasing", "conditions": ["Combat"]}]}
FORTIFICATION_OPTION = {"condition_flags": [{"name": "Fortified", "conditions": ["Combat"]}]}
UNHOLY_OPTION = {"condition_flags": [{"name": "UnholyMight", "conditions": ["Combat"]}]}
ELUSIVE_OPTION = {"condition_flags": [{"name": "Elusive", "conditions": ["CanBeElusive", "Combat"]}]}


@pytest.mark.parametrize("line,mod", [
    ("+3 to maximum Fortification", {"name": "MaximumFortification", "type": "BASE", "tags": []}),
    ("Nearby Allies count as having Fortification equal to yours", {"name": "MinionModifier", "type": "LIST", "tags": []}),
    ("20% increased Effect of Arcane Surge on you", {"name": "ArcaneSurgeEffect", "type": "INC", "tags": []}),
    ("Arcane Surge also grants 20% more Spell Damage to you", {"name": "SpellDamage", "type": "MORE", "tags": [{"type": "Condition", "var": "ArcaneSurge"}]}),
    ("Minions have Unholy Might", {"name": "MinionModifier", "type": "LIST", "tags": []}),
    ("40% increased Elusive Effect", {"name": "ElusiveEffect", "type": "INC", "tags": []}),
])
def test_consumers_caps_effects_and_minion_modifiers_are_not_sources(line: str, mod: dict) -> None:
    parsed = {line: _row(line, mod)}
    assert not parsed_buff_proof("buffArcaneSurge", {}, parsed, ARCANE_OPTION, frozenset({"spell"}), frozenset({"spell"}))[0]


def test_unparsed_and_leech_text_are_not_proofs() -> None:
    assert not parsed_buff_proof("buffArcaneSurge", {}, {"Melee Hits Fortify": {"line": "Melee Hits Fortify", "ok": False, "unsupported": True, "mods": []}}, ARCANE_OPTION, frozenset(), frozenset())[0]
    assert not parsed_buff_proof("conditionLeeching", {}, {"43% increased Damage while Leeching": _row("43% increased Damage while Leeching", {"name": "Damage", "type": "INC", "tags": [{"type": "Condition", "var": "Leeching"}]})}, None, frozenset(), frozenset())[0]
    assert not parsed_buff_proof("conditionLeeching", {}, {"Enemies Cannot Leech Life From you": {"line": "Enemies Cannot Leech Life From you", "ok": False, "unsupported": True, "mods": []}}, None, frozenset(), frozenset())[0]
    assert not parsed_buff_proof("conditionLeeching", {}, {"0.4% of Spell Damage Leeched as Energy Shield": _row("0.4% of Spell Damage Leeched as Energy Shield", _flag("Leeching"))}, None, frozenset(), frozenset())[0]


def test_arcane_surge_requires_a_spell_main_skill() -> None:
    line = "Gain Arcane Surge on Hit with Spells"
    parsed = {line: _row(line, _flag("ArcaneSurge", "HitSpellRecently"))}
    assert parsed_buff_proof("buffArcaneSurge", {}, parsed, ARCANE_OPTION, frozenset({"spell"}), frozenset({"spell"}))[0]
    allowed, why = parsed_buff_proof("buffArcaneSurge", {}, parsed, ARCANE_OPTION, frozenset({"spell"}), frozenset({"attack"}))
    assert not allowed and "spell main skill" in why


def test_low_life_precondition_is_not_free_and_unconditional_phasing_is() -> None:
    low_life = {"You have Onslaught while on Low Life": _row("You have Onslaught while on Low Life", _flag("Onslaught", "LowLife"))}
    assert not parsed_buff_proof("buffOnslaught", {}, low_life, ONSLAUGHT_OPTION, frozenset(), frozenset())[0]
    phasing = {"You have Phasing": _row("You have Phasing", _flag("Phasing"))}
    assert parsed_buff_proof("buffPhasing", {}, phasing, PHASING_OPTION, frozenset(), frozenset())[0]


def test_adrenaline_needs_its_low_life_precondition() -> None:
    line = "Gain Adrenaline for 20 seconds when you reach Low Life"
    parsed = {line: _row(line, _flag("Adrenaline", "LowLife"))}
    assert not parsed_buff_proof("buffAdrenaline", {}, parsed, {"condition_flags": [{"name": "Adrenaline", "conditions": ["Combat"]}]}, frozenset(), frozenset())[0]


def test_player_condition_is_not_confused_with_minion_or_effect_flag() -> None:
    minion = {"Minions have Unholy Might": _row("Minions have Unholy Might", {"name": "MinionModifier", "type": "LIST", "tags": []})}
    assert not parsed_buff_proof("buffUnholyMight", {}, minion, UNHOLY_OPTION, frozenset(), frozenset())[0]
    effect = {"40% increased Elusive Effect": _row("40% increased Elusive Effect", {"name": "ElusiveEffect", "type": "INC", "tags": []})}
    assert not parsed_buff_proof("buffElusive", {}, effect, ELUSIVE_OPTION, frozenset(), frozenset())[0]


def test_skill_use_ending_buff_facts_use_corpus_effect_ids() -> None:
    facts = load_skill_use_ending_buffs()
    assert set(facts) == {"WitheringStep", "PhaseRun"}
    assert facts["WitheringStep"].config_inputs == frozenset({"buffElusive", "buffPhasing"})
    assert facts["PhaseRun"].disable_gem is True
    assert "Using any skill ends Withering Step's effects" in facts["WitheringStep"].quote
    assert "https://www.poewiki.net/wiki/Phase_Run" == facts["PhaseRun"].source


@needs_skill_source
def test_withering_step_alone_does_not_prove_elusive_but_a_crit_source_does() -> None:
    denied, why = parsed_buff_proof(
        "buffElusive",
        {},
        {},
        ELUSIVE_OPTION,
        frozenset({"spell"}),
        frozenset({"spell"}),
        gem_names=("Withering Step",),
    )
    assert not denied
    assert "Withering Step's buffs end when any skill is used (wiki)" in why

    withering_line = granted_effect_lines("WitheringStep", level=18)[0]
    withering_parser_row = {withering_line.lower(): _row(withering_line.lower(), _flag("CanBeElusive"))}
    denied, why = parsed_buff_proof(
        "buffElusive",
        {},
        withering_parser_row,
        ELUSIVE_OPTION,
        frozenset({"spell"}),
        frozenset({"spell"}),
        gem_names=("Withering Step",),
    )
    assert not denied and "Withering Step's buffs end when any skill is used (wiki)" in why

    crit_source = {"Gain Elusive on Critical Strike": _row("Gain Elusive on Critical Strike", _flag("CanBeElusive", "CritRecently"))}
    allowed, why = parsed_buff_proof(
        "buffElusive",
        {"CritChance": 100, "Speed": 1},
        crit_source,
        ELUSIVE_OPTION,
        frozenset({"spell"}),
        frozenset({"spell"}),
        gem_names=("Withering Step",),
    )
    assert allowed and "source parsed by PoB" in why


def test_lane_with_withering_step_alone_does_not_get_elusive(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePob:
        def config_options(self, predicates=None, *, condition_flag_vars=()):
            return [{"var": "buffElusive", "shown": True, "refs": [], "condition_flags": ELUSIVE_OPTION["condition_flags"]}]

        def stats(self, keys=None):
            return {}

        def config_inputs(self):
            return {}

        def read_state(self):
            return {"skills_state": {}, "tree_state": {}}

        def parse_mods(self, lines):
            return [_row(line) for line in lines]

    monkeypatch.setattr(config_rules, "build_text", lambda _pob, _graph: "Withering Step")
    monkeypatch.setattr(config_rules, "_gem_names", lambda _pob: ["Withering Step"])
    monkeypatch.setattr(config_rules, "_main_skill_name", lambda _pob: "Fireball")
    monkeypatch.setattr(config_rules, "_main_skill_tags", lambda _pob, _main: frozenset({"spell"}))
    derived = derive_config(FakePob(), graph=TreeGraph.load(), assumptions={})
    assert "buffElusive" not in derived.conservative.inputs
    assert derived.conservative.reasons["buffElusive"] == "off: Withering Step's buffs end when any skill is used (wiki)"


def test_parser_batch_is_one_call_and_memoized_by_line() -> None:
    class FakePob:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def parse_mods(self, lines: list[str]) -> list[dict]:
            self.calls.append(lines)
            return [_row(line) for line in lines]

    clear_parse_mods_cache()


def test_derivation_parses_buff_candidates_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePob:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def config_options(self, predicates=None, *, condition_flag_vars=()):
            return [{"var": "buffPhasing", "shown": True, "refs": [], "condition_flags": PHASING_OPTION["condition_flags"]}]

        def stats(self, keys=None):
            return {}

        def config_inputs(self):
            return {}

        def read_state(self):
            return {"skills_state": {}, "tree_state": {}}

        def parse_mods(self, lines):
            self.calls.append(lines)
            return [_row(line, _flag("Phasing")) for line in lines]

    monkeypatch.setattr(config_rules, "build_text", lambda _pob, _graph: "You have Phasing\nGain Onslaught")
    monkeypatch.setattr(config_rules, "_gem_names", lambda _pob: [])
    monkeypatch.setattr(config_rules, "_main_skill_name", lambda _pob: None)
    monkeypatch.setattr(config_rules, "_main_skill_tags", lambda _pob, _main: frozenset())
    clear_parse_mods_cache()
    pob = FakePob()
    derived = derive_config(pob, graph=TreeGraph.load(), assumptions={})
    assert derived.conservative.inputs["buffPhasing"] is True
    assert pob.calls == [["You have Phasing", "Gain Onslaught"]]
    clear_parse_mods_cache()
    pob = FakePob()
    assert set(parse_mods_batch(pob, ["one", "two", "one"])) == {"one", "two"}
    assert pob.calls == [["one", "two"]]
    parse_mods_batch(pob, ["two", "three"])
    assert pob.calls == [["one", "two"], ["three"]]
    clear_parse_mods_cache()


def test_audit_uses_the_same_parser_proof() -> None:
    parsed = {"20% increased Effect of Arcane Surge on you": _row("20% increased Effect of Arcane Surge on you", {"name": "ArcaneSurgeEffect", "type": "INC", "tags": []})}
    found = audit_conservative_generator_inputs(
        {"buffArcaneSurge": True},
        {},
        "20% increased Effect of Arcane Surge on you",
        frozenset({"spell"}),
        frozenset({"spell"}),
        parsed=parsed,
        options=[{"var": "buffArcaneSurge", **ARCANE_OPTION}],
    )
    assert len(found) == 1 and found[0].check == "conservative generator proof"


def test_audit_rejects_an_elusive_input_held_only_by_withering_step() -> None:
    found = audit_conservative_generator_inputs(
        {"buffElusive": True},
        {},
        "Withering Step",
        frozenset({"spell"}),
        frozenset({"spell"}),
        options=[{"var": "buffElusive", **ELUSIVE_OPTION}],
        gem_names=("Withering Step",),
    )
    assert len(found) == 1
    assert found[0].severity == "error" and found[0].check == "buff ended by skill use"
    assert "Withering Step's buffs end when any skill is used (wiki)" in found[0].detail


def test_audit_leech_uses_computed_positive_gain_only() -> None:
    off = audit_conservative_generator_inputs(
        {"conditionLeeching": True},
        {},
        "0.4% of Spell Damage Leeched as Energy Shield",
        frozenset(),
        frozenset(),
    )
    assert len(off) == 1 and "no positive life, mana, or energy shield leech gain rate" in off[0].detail
    assert audit_conservative_generator_inputs(
        {"conditionLeeching": True},
        {"LifeLeechGainRate": 1.0},
        "Enemies Cannot Leech Life From you",
        frozenset(),
        frozenset(),
    ) == []


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


@pytest.mark.pob
@needs_pob
def test_pob_parser_contract_for_buff_proof_lines(tmp_path: Path) -> None:
    lines = [
        "43% increased Damage while Leeching",
        "Gain Arcane Surge on Hit with Spells",
        "You have Onslaught while on Low Life",
        "You have Phasing",
        "+3 to maximum Fortification",
        "20% increased Effect of Arcane Surge on you",
        "Minions have Unholy Might",
        "Enemies Cannot Leech Life From you",
        "Melee Hits Fortify",
    ]
    with PobSession(run_id="test-buff-parser-contract", artifacts_root=tmp_path) as pob:
        rows = {row["line"]: row for row in pob.parse_mods(lines)}
    assert rows[lines[0]]["mods"][0]["name"] == "Damage"
    assert rows[lines[0]]["mods"][0]["tags"][0]["var"] == "Leeching"
    assert rows[lines[1]]["mods"][0]["name"] == "Condition:ArcaneSurge"
    assert rows[lines[1]]["mods"][0]["tags"][0]["var"] == "HitSpellRecently"
    assert rows[lines[2]]["mods"][0]["name"] == "Condition:Onslaught"
    assert rows[lines[2]]["mods"][0]["tags"][0]["var"] == "LowLife"
    assert rows[lines[3]]["mods"][0]["name"] == "Condition:Phasing"
    assert rows[lines[4]]["mods"][0]["name"] == "MaximumFortification"
    assert rows[lines[5]]["mods"][0]["name"] == "ArcaneSurgeEffect"
    assert rows[lines[6]]["mods"][0]["name"] == "MinionModifier"
    assert rows[lines[7]]["ok"] is False and rows[lines[8]]["ok"] is False
