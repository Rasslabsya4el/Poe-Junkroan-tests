"""Elemental Overload with no uptime behind it (the user's reading 2026-09-18,
burning_arrow_snipe: "эфф крит 7% + очень долгая атака ... вероятность прока ЕО довольно
маленькая", against kinetic_fusillade's 17%).

PoB has no config input for the keystone: `CalcOffence` sets the CritInPast8Sec condition
whenever the skill's crit chance is not zero, so no lane can switch it off and the audit is
where it is named. The uptime rule itself is `config_rules._crit_recently`, the same one that
decides the crit-recently config inputs."""

from __future__ import annotations

from junkroan.optimizer.audit import audit_elemental_overload
from junkroan.search.hypothesis import keystones

EO_NODE = keystones()["elemental overload"]

BURNING_ARROW = {"CritChance": 10.584, "HitChance": 98, "Speed": 0.96807272727273}  # 58% uptime (PoB's CritChance already carries the accuracy roll; HitChance is not applied twice)
KINETIC_FUSILLADE = {"CritChance": 68.382, "HitChance": 100, "Speed": 3.35625}  # 100%


def _xml(nodes: str, *, main_gem: str = "Kinetic Bolt", item_lines: str = "") -> str:
    items = f'<Items activeItemSet="1"><Item id="1">{item_lines}</Item><ItemSet id="1"><Slot name="Amulet" itemId="1"/></ItemSet></Items>' if item_lines else "<Items/>"
    return ('<PathOfBuilding><Build mainSocketGroup="1"/><Tree><Spec nodes="' + nodes + '"/></Tree>'
            '<Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">'
            f'<Gem nameSpec="{main_gem}" enabled="true" level="18" quality="0"/>'
            "</Skill></SkillSet></Skills>" + items + "</PathOfBuilding>")


def test_a_slow_low_crit_build_with_the_keystone_is_named() -> None:
    found = audit_elemental_overload(_xml(f"{EO_NODE},12345"), BURNING_ARROW)
    assert len(found) == 1 and found[0].check == "elemental overload uptime"
    assert "58% of the time" in found[0].detail and "no config input gates it" in found[0].detail


def test_a_build_that_keeps_it_up_is_not_named() -> None:
    assert audit_elemental_overload(_xml(str(EO_NODE)), KINETIC_FUSILLADE) == []


def test_without_the_keystone_there_is_nothing_to_judge() -> None:
    assert audit_elemental_overload(_xml("12345"), BURNING_ARROW) == []


def test_the_keystone_off_an_item_counts_too() -> None:
    xml = _xml("12345", item_lines="Rarity: UNIQUE\nThe Wanderer\nAmulet\nElemental Overload\n")
    assert len(audit_elemental_overload(xml, BURNING_ARROW)) == 1


def test_a_minion_build_is_named_whatever_the_minions_crit() -> None:
    found = audit_elemental_overload(_xml(str(EO_NODE), main_gem="Summon Raging Spirit"), {"CritChance": 95, "HitChance": 100, "Speed": 5.0})
    assert len(found) == 1 and "minions" in found[0].detail


def test_a_build_with_no_crit_at_all_is_named( ) -> None:
    found = audit_elemental_overload(_xml(str(EO_NODE)), {"CritChance": 0, "HitChance": 100, "Speed": 4.0})
    assert len(found) == 1 and "no critical strikes" in found[0].detail
