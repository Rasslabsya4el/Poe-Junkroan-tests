"""Guard skills and other cooldown-limited buffs count for nothing (the user's reading
2026-09-18, shockwave_cyclone: "гард скиллы ... должны быть выключены"). PoB has no config
input for them, so the rule lives in the skills surface: the gem stays, disabled."""

from __future__ import annotations

from typing import Any

import pytest

from junkroan.optimizer import buff_gems
from junkroan.optimizer.buff_gems import (
    disable_unreliable_buff_gems,
    disable_unreliable_buff_gems_xml,
    unreliable_reason,
)
from junkroan.pob.skill_facts import SKILL_DATA_DIRS

needs_skill_data = pytest.mark.skipif(
    not SKILL_DATA_DIRS[0].is_dir(), reason=f"PoB skill data not present at {SKILL_DATA_DIRS[0]}"
)


# -- which gems the rule names (PoB's own skillTypes + duration / cooldown) ---------------


@needs_skill_data
@pytest.mark.parametrize("name", ["Steelskin", "Immortal Call", "Molten Shell", "Arcane Cloak", "Vaal Molten Shell"])
def test_guard_skills_are_always_off(name: str) -> None:
    why = unreliable_reason(name)
    assert why and "guard skill" in why


@needs_skill_data
@pytest.mark.parametrize("name,uptime", [("Convocation", "67%"), ("Vaal Immortal Call", "1%")])
def test_other_buff_skills_go_by_their_uptime(name: str, uptime: str) -> None:
    why = unreliable_reason(name)
    assert why and uptime in why


def test_phase_run_is_disabled_from_the_skill_use_ending_buff_fact() -> None:
    why = unreliable_reason("Phase Run")
    assert why and "primary buff is replaced when any skill is used (wiki)" in why


def test_phase_run_group_is_disabled_from_the_skill_use_ending_buff_fact() -> None:
    groups = [_group(["Phase Run"])]
    reasons = disable_unreliable_buff_gems(groups)
    assert reasons and "primary buff is replaced when any skill is used (wiki)" in reasons[0]
    assert groups[0]["gems"][0]["enabled"] is False and groups[0]["enabled"] is False


@needs_skill_data
@pytest.mark.parametrize("name", [
    "Seismic Trap", "Bear Trap", "Frost Bomb", "Void Sphere",  # damage skills: duration / cooldown is a throw rate
    "War Banner", "Dread Banner",                              # a planted banner is permanent
    "Fireball", "Cyclone", "Determination",                    # nothing cooldown-limited about them
])
def test_damage_banner_and_ordinary_skills_are_left_alone(name: str) -> None:
    assert unreliable_reason(name) is None


# -- what the helper does to a build (fakes, no PoB, no skill data) -----------------------


@pytest.fixture()
def only_steelskin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buff_gems, "unreliable_reason", lambda name: "Steelskin: a guard skill" if name == "Steelskin" else None)


def _group(names: list[str]) -> dict[str, Any]:
    return {"label": names[0], "enabled": True, "gems": [{"gem_name": n, "enabled": True} for n in names]}


def test_the_gem_is_disabled_and_never_removed(only_steelskin: None) -> None:
    groups = [_group(["Steelskin", "Increased Duration"])]
    reasons = disable_unreliable_buff_gems(groups)
    assert reasons and "guard skill" in reasons[0]
    assert [g["gem_name"] for g in groups[0]["gems"]] == ["Steelskin", "Increased Duration"]
    assert groups[0]["gems"][0]["enabled"] is False
    assert groups[0]["enabled"] is False  # nothing active left: the supports are not a live group


def test_a_group_that_keeps_an_active_gem_stays_enabled(only_steelskin: None) -> None:
    groups = [_group(["Cyclone", "Steelskin"]), _group(["Determination"])]
    disable_unreliable_buff_gems(groups)
    assert groups[0]["enabled"] is True and groups[0]["gems"][1]["enabled"] is False
    assert groups[1]["enabled"] is True and groups[1]["gems"][0]["enabled"] is True  # untouched group


def test_nothing_to_disable_changes_nothing(only_steelskin: None) -> None:
    groups = [_group(["Cyclone", "Melee Physical Damage"])]
    assert disable_unreliable_buff_gems(groups) == []
    assert groups[0]["enabled"] is True and all(g["enabled"] for g in groups[0]["gems"])


XML = (
    '<PathOfBuilding><Skills><SkillSet id="1">'
    '<Skill enabled="true"><Gem nameSpec="Cyclone" enabled="true"/><Gem nameSpec="Melee Physical Damage" enabled="true"/></Skill>'
    '<Skill enabled="true"><Gem nameSpec="Steelskin" enabled="true"/><Gem nameSpec="Increased Duration" enabled="true"/></Skill>'
    "</SkillSet></Skills></PathOfBuilding>"
)


def test_the_same_rule_on_the_authors_xml(only_steelskin: None) -> None:
    out, reasons = disable_unreliable_buff_gems_xml(XML)
    assert len(reasons) == 1
    assert 'nameSpec="Steelskin" enabled="false"' in out and "Increased Duration" in out
    assert out.count('<Skill enabled="false">') == 1  # only the guard group


def test_an_xml_with_nothing_to_disable_comes_back_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buff_gems, "unreliable_reason", lambda name: None)
    assert disable_unreliable_buff_gems_xml(XML) == (XML, [])
