"""The skeleton read off an author's XML: a socket group in a weapon swap is not a live group.
The Cold DoT author's "Weapon 1 Swap: Arcane Surge + Elemental Focus" was carried into every
generated build as a real group (swap item slots were already dropped)."""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_from_skeleton import socket_groups_from_xml  # noqa: E402


def _skills(*groups: str) -> ET.Element:
    return ET.fromstring('<Skills activeSkillSet="1"><SkillSet id="1">' + "".join(groups) + "</SkillSet></Skills>")


def _group(slot: str, *gems: str) -> str:
    return f'<Skill enabled="true" slot="{slot}">' + "".join(f'<Gem nameSpec="{g}" enabled="true"/>' for g in gems) + "</Skill>"


def test_a_weapon_swap_group_is_not_carried_into_the_skeleton() -> None:
    skills = _skills(_group("Body Armour", "Cold Snap", "Efficacy"), _group("Weapon 1 Swap", "Arcane Surge", "Elemental Focus"))
    main_link, main_slot, extra = socket_groups_from_xml(skills, 1)
    assert main_link == ["Cold Snap", "Efficacy"] and main_slot == "Body Armour"
    assert [(g.slot, g.gems) for g in extra] == [], "the swap group is the only other group and it is dropped"

    skills = _skills(_group("Body Armour", "Cold Snap"), _group("Weapon 2 Swap", "Arcane Surge"), _group("Helmet", "Hatred"))
    _main, _slot, extra = socket_groups_from_xml(skills, 1)
    assert [(g.slot, g.gems) for g in extra] == [("Helmet", ["Hatred"])]


def test_a_group_with_no_socket_still_gets_one() -> None:
    skills = _skills(_group("Body Armour", "Cold Snap"), _group("", "Hatred"))
    _main, _slot, extra = socket_groups_from_xml(skills, 1)
    assert len(extra) == 1 and extra[0].slot == "Helmet" and extra[0].gems == ["Hatred"]
