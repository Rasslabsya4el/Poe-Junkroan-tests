"""#967 check C of the build check's duration warnings, fed numbers (no PoB).

C: a skill FullDPS counts more than once whose copies end on a duration: the share of time spent recasting,
`copies x Time / duration`, always printed. The numbers are PoB's for the named builds of the 17-row reading queue
(2026-10-13). A Brand's copies are PoB's `AttachedBrandCount`; a duration minion's are the count FullDPS multiplies by.
"""

from __future__ import annotations

from conftest import needs_skill_source
from junkroan.optimizer.audit import Finding
from junkroan.optimizer.audit_duration import audit_duration, recast_findings, skill_counts


def test_hit_penance_brand_s6_recasts_25_percent_of_the_time() -> None:
    values = {"AttachedBrandCount": 2, "DurationSecondary": 2.54, "Time": 0.321}  # no `Duration` key
    found = recast_findings("hit_penance_brand s6", values)
    assert len(found) == 1
    assert "25 %" in found[0]
    assert "2 x 0.321 / 2.54" in found[0]
    assert "DurationSecondary 2.54 s" in found[0] and "AttachedBrandCount" in found[0]


def test_stormbrand_s6_uses_the_primary_duration_when_the_skill_has_one() -> None:
    values = {"AttachedBrandCount": 2, "Duration": 2.11, "DurationSecondary": 2.54, "Time": 0.295}
    found = recast_findings("stormbrand s6", values)
    assert len(found) == 1
    assert "Duration 2.11 s" in found[0] and "DurationSecondary" not in found[0]
    assert "28 %" in found[0]  # 2 x 0.295 / 2.11


def test_ignite_penance_brand_s4_warns() -> None:
    values = {"AttachedBrandCount": 2, "DurationSecondary": 8.41, "Time": 0.434}
    found = recast_findings("ignite_penance_brand s4", values)
    assert len(found) == 1 and "10 %" in found[0]  # 2 x 0.434 / 8.41


def test_summon_raging_spirits_s6_at_20_copies_recasts_86_percent_of_the_time() -> None:
    values = {"Duration": 8.22, "Time": 0.352}
    found = recast_findings("summon_raging_spirits s6", values, count=20, duration_minion=True)
    assert len(found) == 1
    assert "86 %" in found[0]
    assert "20 x 0.352 / 8.22" in found[0]


def test_a_single_copy_is_silent() -> None:
    assert recast_findings("brand", {"AttachedBrandCount": 1, "Duration": 5.0, "Time": 0.3}) == []
    assert recast_findings("minion", {"Duration": 8.22, "Time": 0.352}, count=1, duration_minion=True) == []


def test_a_skill_that_is_not_a_brand_or_a_duration_minion_is_silent() -> None:
    assert recast_findings("smite s6", {"Duration": 8.22, "Time": 0.352}, count=20) == []
    assert recast_findings("spark s5", {"Time": 0.3}, count=2, duration_minion=True) == []


def test_a_brand_without_any_duration_or_time_is_silent() -> None:
    assert recast_findings("brand", {"AttachedBrandCount": 2, "Time": 0.3}) == []
    assert recast_findings("brand", {"AttachedBrandCount": 2, "Duration": 5.0}) == []


def _state(group_count: int, gem_count: int) -> dict:
    entry = {"active_skill_id": "skills.main.socket_group.1.active_skill.1", "name": "Summon Raging Spirit", "granted_effect_id": "SummonRagingSpirit", "source_gem_entry_id": "g1", "enabled": True}
    return {
        "skills_state": {
            "active_skill_set_id": "skills.main",
            "skill_sets": [{"skill_set_id": "skills.main", "socket_groups": [{
                "include_in_full_dps": True, "enabled": True, "group_count": group_count,
                "gems": [{"gem_entry_id": "g1", "count": gem_count}, {"gem_entry_id": "g2", "count": 9}],
                "active_skill_entries": [entry],
            }]}],
        }
    }


def test_skill_counts_take_the_gem_count_and_a_group_count_over_it() -> None:
    skill_id = "skills.main.socket_group.1.active_skill.1"
    assert skill_counts(_state(1, 20)) == {skill_id: ("SummonRagingSpirit", 20)}
    assert skill_counts(_state(3, 20)) == {skill_id: ("SummonRagingSpirit", 3)}
    assert skill_counts(_state(1, 1)) == {skill_id: ("SummonRagingSpirit", 1)}


class _FakePob:
    def __init__(self, state: dict, per_skill: dict) -> None:
        self._state, self._per_skill, self.calls = state, per_skill, 0

    def read_state(self) -> dict:
        return self._state

    def active_skill_stats(self, skill_ids, keys):
        self.calls += 1
        assert {"Time", "Duration", "DurationSecondary", "AttachedBrandCount"} <= set(keys)
        return {skill_id: self._per_skill[skill_id] for skill_id in skill_ids}


def test_entry_warns_for_a_brand_in_one_read() -> None:
    skill_id = "skills.main.socket_group.1.active_skill.1"
    state = _state(1, 1)
    state["skills_state"]["skill_sets"][0]["socket_groups"][0]["active_skill_entries"][0]["granted_effect_id"] = "PenanceBrand"
    pob = _FakePob(state, {skill_id: {"AttachedBrandCount": 2, "DurationSecondary": 2.541, "Time": 0.32051282}})
    findings = audit_duration(pob)
    assert [type(f) for f in findings] == [Finding]
    assert findings[0].severity == "warning" and findings[0].check == "duration" and "25 %" in findings[0].detail
    assert pob.calls == 1


@needs_skill_source
def test_absolution_numbers_give_no_c_line_and_summon_raging_spirit_keeps_its_line() -> None:
    """PoB's own data tells the kinds apart: Absolution carries `base_secondary_skill_effect_duration` (the Sentinel's
    life, summoned by a kill), Summon Raging Spirit does not; decided on the gem's block, not on a name."""

    from junkroan.pob.skill_facts import is_cast_copy_duration_minion

    assert not is_cast_copy_duration_minion("Absolution") and not is_cast_copy_duration_minion("AbsolutionAltX")
    assert is_cast_copy_duration_minion("SummonRagingSpirit")

    def run(effect_id: str, count: int, values: dict) -> list:
        skill_id = "skills.main.socket_group.1.active_skill.1"
        state = _state(1, count)
        state["skills_state"]["skill_sets"][0]["socket_groups"][0]["active_skill_entries"][0]["granted_effect_id"] = effect_id
        return audit_duration(_FakePob(state, {skill_id: values}))

    assert run("Absolution", 3, {"Duration": 6.43, "Time": 0.185}) == []
    found = run("SummonRagingSpirit", 20, {"Duration": 8.22, "Time": 0.352})
    assert len(found) == 1 and "86 %" in found[0].detail and "20 x 0.352 / 8.22" in found[0].detail
