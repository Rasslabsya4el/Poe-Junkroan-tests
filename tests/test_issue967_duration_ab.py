"""#967 checks A and B of the build check's duration warnings, fed numbers (no PoB).

A: Ignite or Bleed on a skill included in FullDPS whose ailment DPS is larger than the skill's hit TotalDPS while
fewer than two applications overlap (`<Ailment>StackPotential` under 2). B: a skill's `*Uptime` under 100.
The numbers are the ones PoB gave for the named builds of the 17-row reading queue (2026-10-13). The entry
`audit_duration` is driven by a fake session that answers `read_state` and `active_skill_stats`.
"""

from __future__ import annotations

from junkroan.optimizer.audit import Finding
from junkroan.optimizer.audit_duration import ailment_findings, audit_duration, included_active_skills, uptime_findings


def test_ignite_on_marauder_chieftain_no_blood_magic_s2_warns() -> None:
    values = {"IgniteDuration": 1.12, "IgniteStackPotential": 1.00, "IgniteDPS": 156_945, "TotalDPS": 6_373}
    found = ailment_findings("03 marauder_chieftain_no_blood_magic_imperial_staff s2", values)
    assert len(found) == 1
    assert "Ignite lasts 1.12 s and is held by 1.00 applications at once" in found[0]
    assert "(IgniteDuration, IgniteStackPotential)" in found[0]


def test_ignite_on_ignite_penance_brand_s4_warns() -> None:
    values = {"IgniteDuration": 0.68, "IgniteStackPotential": 1.18, "IgniteDPS": 827_077, "TotalDPS": 202_827}
    found = ailment_findings("ignite_penance_brand s4", values)
    assert len(found) == 1
    assert "Ignite lasts 0.68 s and is held by 1.18 applications at once" in found[0]


def test_regular_viper_strike_s4_is_silent_because_its_ignite_dps_is_zero() -> None:
    # The real IgniteDuration of this build is not in the issue; 1.00 is a stand-in so that only the DPS condition decides.
    values = {"IgniteDuration": 1.00, "IgniteStackPotential": 0.55, "IgniteDPS": 0, "TotalDPS": 59_072}
    assert ailment_findings("regular_viper_strike s4", values) == []


def test_marauder_chieftain_s2_is_silent_at_a_stack_potential_of_5_42() -> None:
    # IgniteDPS and TotalDPS are set so that the DPS condition holds and only the stack bound decides.
    values = {"IgniteDuration": 6.6, "IgniteStackPotential": 5.42, "IgniteDPS": 2, "TotalDPS": 1}
    assert ailment_findings("01 marauder_chieftain s2", values) == []


def test_bleed_bow_s6_is_silent_at_a_stack_potential_of_3_93() -> None:
    values = {"BleedDuration": 7.5, "BleedStackPotential": 3.93, "BleedDPS": 2, "TotalDPS": 1}
    assert ailment_findings("bleed_bow s6", values) == []


def test_bleed_that_barely_holds_warns_with_bleed_wording() -> None:
    values = {"BleedDuration": 0.5, "BleedStackPotential": 1.0, "BleedDPS": 10, "TotalDPS": 5}
    found = ailment_findings("bleed_test s1", values)
    assert len(found) == 1
    assert "Bleed lasts 0.50 s and is held by 1.00 applications at once" in found[0]
    assert "(BleedDuration, BleedStackPotential)" in found[0]


def test_ailment_without_its_keys_is_silent() -> None:
    assert ailment_findings("smite s6", {"TotalDPS": 100.0}) == []


def test_uptime_of_60_warns_with_key_and_percent() -> None:
    found = uptime_findings("cooldown_test s1", {"DurationUptime": 60})
    assert len(found) == 1
    assert "DurationUptime" in found[0] and "60" in found[0]


def test_uptime_of_100_is_silent() -> None:
    assert uptime_findings("cold_dot s5", {"DurationUptime": 100}) == []
    assert uptime_findings("physical_dot s4", {"DurationUptime": 100}) == []


def test_each_uptime_key_is_checked() -> None:
    values = {"DurationSecondaryUptime": 80, "DurationTertiaryUptime": 100, "AuraDurationUptime": 50}
    found = uptime_findings("aura_test s1", values)
    assert len(found) == 2
    assert any("DurationSecondaryUptime" in line for line in found)
    assert any("AuraDurationUptime" in line for line in found)


class _FakePob:
    """Answers the two reads the entry makes; counts the PoB calls it gets."""

    def __init__(self, state: dict, per_skill: dict) -> None:
        self._state = state
        self._per_skill = per_skill
        self.active_skill_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def read_state(self) -> dict:
        return self._state

    def active_skill_stats(self, skill_ids, keys):
        self.active_skill_calls.append((tuple(skill_ids), tuple(keys)))
        return {skill_id: self._per_skill[skill_id] for skill_id in skill_ids if skill_id in self._per_skill}


def _state() -> dict:
    def entry(index: int, name: str, enabled: bool = True) -> dict:
        return {"active_skill_id": f"skills.main.socket_group.{index}.active_skill.1", "name": name, "enabled": enabled}

    return {
        "skills_state": {
            "active_skill_set_id": "skills.main",
            "skill_sets": [
                {
                    "skill_set_id": "skills.main",
                    "socket_groups": [
                        {"include_in_full_dps": True, "enabled": True, "active_skill_entries": [entry(1, "Ignite Penance Brand")]},
                        {"include_in_full_dps": False, "enabled": True, "active_skill_entries": [entry(2, "Smite")]},
                        {"include_in_full_dps": True, "enabled": False, "active_skill_entries": [entry(3, "Off Skill")]},
                    ],
                }
            ],
        }
    }


def test_included_active_skills_are_the_enabled_full_dps_groups_of_the_active_set() -> None:
    assert included_active_skills(_state()) == [("Ignite Penance Brand", "skills.main.socket_group.1.active_skill.1")]


def test_entry_warns_on_an_included_skill_and_makes_one_read_for_the_included_skills_only() -> None:
    per_skill = {"skills.main.socket_group.1.active_skill.1": {"IgniteDuration": 0.68, "IgniteStackPotential": 1.18, "IgniteDPS": 827_077, "TotalDPS": 202_827, "DurationUptime": 100}}
    pob = _FakePob(_state(), per_skill)
    findings = audit_duration(pob)
    assert [type(f) for f in findings] == [Finding] * len(findings)
    assert len(findings) == 1
    assert findings[0].severity == "warning" and findings[0].check == "duration"
    assert "Ignite Penance Brand" in findings[0].detail and "Ignite lasts 0.68 s" in findings[0].detail
    assert len(pob.active_skill_calls) == 1  # the one extra PoB call of #967 (read_state is cached by the session)
    ids, keys = pob.active_skill_calls[0]
    assert ids == ("skills.main.socket_group.1.active_skill.1",)
    assert {"IgniteDPS", "TotalDPS", "IgniteStackPotential", "IgniteDuration", "DurationUptime"} <= set(keys)


def test_entry_warns_on_an_uptime_under_100_of_an_included_skill() -> None:
    state = _state()
    pob = _FakePob(state, {"skills.main.socket_group.1.active_skill.1": {"DurationUptime": 60, "TotalDPS": 10, "IgniteDPS": 0}})
    findings = audit_duration(pob)
    assert len(findings) == 1 and "DurationUptime" in findings[0].detail


def test_entry_makes_no_read_when_nothing_is_included() -> None:
    state = {"skills_state": {"active_skill_set_id": "skills.main", "skill_sets": [{"skill_set_id": "skills.main", "socket_groups": [{"include_in_full_dps": False, "enabled": True, "active_skill_entries": []}]}]}}
    pob = _FakePob(state, {})
    assert audit_duration(pob) == []
    assert pob.active_skill_calls == []
