import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark import flag_main_group_for_full_dps  # noqa: E402

XML = """<PathOfBuilding><Build mainSocketGroup="2"/><Skills activeSkillSet="1"><SkillSet id="1">
<Skill label="header" includeInFullDPS="false"/>
<Skill label="6L 4-Frostbearers (Mortar projectile = 5x count)" includeInFullDPS="false">
<Gem nameSpec="Minion Damage" gemId="Metadata/Items/Gems/SupportGemMinionDamage" count="1"/>
<Gem nameSpec="Raise Spectre" gemId="Metadata/Items/Gems/SkillGemRaiseSpectre" count="20"/>
</Skill></SkillSet></Skills></PathOfBuilding>"""


def _gems(xml: str) -> dict:
    group = ET.fromstring(xml).find("Skills/SkillSet").findall("Skill")[1]
    return {g.get("nameSpec"): g.get("count") for g in group.findall("Gem")} | {"flag": group.get("includeInFullDPS")}


def test_the_derived_count_replaces_the_main_skills_count_not_the_first_supports():
    assert _gems(flag_main_group_for_full_dps(XML, count=3, main="Raise Spectre")) == {
        "Minion Damage": "1", "Raise Spectre": "3", "flag": "true"}


def test_without_a_name_the_first_active_gem_takes_the_count():
    assert _gems(flag_main_group_for_full_dps(XML, count=3))["Raise Spectre"] == "3"
