"""Audit: golem gems above ActiveGolemLimit (7.2, from reading loop-smoke-2's Cold DoT builds);
config: mines detonated recently derived from PoB's throw rate (D57 rule 3)."""

from junkroan.optimizer.audit import audit_conservative_generator_inputs, audit_conservative_generator_proofs, audit_golem_limit
from junkroan.optimizer.config_rules import _numeric_rule


def _xml(*groups: str) -> str:
    return ('<PathOfBuilding><Build mainSocketGroup="1"/><Tree/><Skills activeSkillSet="1"><SkillSet id="1">'
            + "".join(groups) + "</SkillSet></Skills><Items/></PathOfBuilding>")


def _gem(name: str, skill_id: str, enabled: str = "true") -> str:
    return f'<Gem nameSpec="{name}" skillId="{skill_id}" enabled="{enabled}" level="18" quality="0"/>'


GOLEMS = _xml('<Skill enabled="true">' + _gem("Summon Flame Golem", "SummonFlameGolem") + _gem("Summon Stone Golem", "SummonStoneGolem")
              + _gem("Summon Chaos Golem", "SummonChaosGolem") + _gem("Vortex", "Vortex") + "</Skill>")


def test_more_golem_gems_than_the_limit_is_a_warning() -> None:
    found = audit_golem_limit(GOLEMS, {"ActiveGolemLimit": 1})
    assert len(found) == 1 and found[0].severity == "warning" and found[0].check == "golem limit"
    assert "3 golem gems" in found[0].detail and "limit of 1" in found[0].detail


def test_golems_at_or_under_the_limit_pass_and_disabled_gems_do_not_count() -> None:
    assert audit_golem_limit(GOLEMS, {"ActiveGolemLimit": 3}) == []
    assert audit_golem_limit(GOLEMS, {"ActiveGolemLimit": 4}) == []
    assert audit_golem_limit(GOLEMS, {}) == []  # no limit stat: nothing to judge
    two = _xml('<Skill enabled="true">' + _gem("Summon Flame Golem", "SummonFlameGolem") + _gem("Summon Stone Golem", "SummonStoneGolem", "false") + "</Skill>")
    assert audit_golem_limit(two, {"ActiveGolemLimit": 1}) == []


def test_mines_detonated_recently_is_the_window_times_the_throw_rate() -> None:
    value, why = _numeric_rule("multiplierMineDetonatedRecently", {"Speed": 9.543}, "", ["Pyroclast Mine", "Minefield"], {})
    assert value == 38 and "9.54 mines per second" in why  # 4 s x 9.543 (Pyroclast with Minefield, PoB)
    value, _ = _numeric_rule("multiplierMineDetonatedRecently", {"Speed": 10.571}, "", ["Exsanguinate", "High-Impact Mine"], {"mine_detonation_fraction": 0.5})
    assert value == 21  # Exsanguinate is a mine only through its support; half the mines detonated
    assert _numeric_rule("multiplierMineDetonatedRecently", {"Speed": 9.543}, "", ["Fireball"], {})[0] is None
    assert _numeric_rule("multiplierMineDetonatedRecently", {}, "", ["Pyroclast Mine"], {})[0] is None


class _GeneratorProofPob:
    def __init__(self, source: str, main_gem: str = "Fireball") -> None:
        self._state = {
            "gear_slots": {"slots": {"Weapon 1": {"item": {"raw": source}}}},
            "skills_state": {"main_socket_group_id": "main", "socket_groups": [{
                "socket_group_id": "main", "enabled": True,
                "gems": [{"gem_name": main_gem, "enabled": True, "is_support": False}],
            }]},
            "tree_state": {},
        }

    def read_state(self) -> dict:
        return self._state

    def parse_mods(self, lines: list[str]) -> list[dict]:
        rows = []
        for line in lines:
            if line == "gain onslaught while channelling":
                rows.append({"line": line, "ok": True, "unsupported": False, "mods": [{"name": "Condition:Onslaught", "type": "FLAG", "tags": [{"type": "Condition", "var": "Channelling"}]}]})
            else:
                rows.append({"line": line, "ok": True, "unsupported": False, "mods": []})
        return rows

    def config_options(self, predicates=None, *, condition_flag_vars=()) -> list[dict]:
        return [{"var": "buffOnslaught", "condition_flags": [{"name": "Onslaught", "conditions": ["Combat"]}]}]


def _baseline(var: str) -> str:
    return ("<PathOfBuilding><Config><ConfigSet id=\"1\" title=\"Baseline\">"
            f"<Input name=\"{var}\" boolean=\"true\"/>"
            "</ConfigSet><ConfigSet id=\"2\" title=\"Conditional\"/></Config></PathOfBuilding>")


def test_audit_rejects_baseline_charge_without_main_channelling() -> None:
    found = audit_conservative_generator_proofs(
        _GeneratorProofPob("Gain a Power Charge each second while Channelling a Spell"),
        _baseline("usePowerCharges"),
        {"PowerChargesMax": 3, "PowerChargesDuration": 10},
    )
    assert len(found) == 1 and found[0].severity == "error"
    assert found[0].check == "conservative generator proof"
    assert "usePowerCharges" in found[0].detail and "needs a channelling skill" in found[0].detail


def test_audit_rejects_mixed_on_kill_and_non_channelled_power_sources() -> None:
    found = audit_conservative_generator_proofs(
        _GeneratorProofPob("8% chance to gain a Power Charge on Kill\nGain a Power Charge each second while Channelling a Spell"),
        _baseline("usePowerCharges"),
        {"PowerChargesMax": 3, "PowerChargesDuration": 10},
    )
    assert len(found) == 1 and found[0].severity == "error"
    assert "no kills on a boss" in found[0].detail and "needs a channelling skill" in found[0].detail


def test_audit_rejects_baseline_charge_with_only_an_on_kill_source() -> None:
    found = audit_conservative_generator_proofs(
        _GeneratorProofPob("8% chance to gain a Power Charge on Kill"),
        _baseline("usePowerCharges"),
        {"PowerChargesMax": 3, "PowerChargesDuration": 10},
    )
    assert len(found) == 1 and "no kills on a boss" in found[0].detail


def test_audit_rejects_baseline_charge_with_only_an_unclassified_source() -> None:
    found = audit_conservative_generator_proofs(
        _GeneratorProofPob("Gain a Power Charge while Focused"),
        _baseline("usePowerCharges"),
        {"PowerChargesMax": 3, "PowerChargesDuration": 10},
    )
    assert len(found) == 1 and "unclassified source: not counted" in found[0].detail


def test_audit_rejects_baseline_buff_without_main_channelling() -> None:
    found = audit_conservative_generator_proofs(
        _GeneratorProofPob("Gain Onslaught while Channelling"),
        _baseline("buffOnslaught"),
        {},
    )
    assert len(found) == 1 and "Channelling needs a channelling main skill" in found[0].detail


def test_audit_accepts_a_channelled_main_skill() -> None:
    assert audit_conservative_generator_proofs(
        _GeneratorProofPob("Gain a Power Charge each second while Channelling a Spell", main_gem="Cyclone"),
        _baseline("usePowerCharges"),
        {"PowerChargesMax": 3, "PowerChargesDuration": 10},
    ) == []


def test_audit_uses_the_independent_generator_skill_context() -> None:
    line = "performs an attack with a ranged weapon that gives the character a frenzy charge if it hits"
    contexts = {line: [{"name": "Frenzy", "triggered": True, "proxy": False, "stats": {"Speed": 1.0, "HitChance": 100}}]}
    assert audit_conservative_generator_inputs(
        {"useFrenzyCharges": True},
        {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 2.19},
        line,
        frozenset({"attack", "totem"}),
        frozenset({"attack", "totem"}),
        source_contexts=contexts,
    ) == []
