"""A socket group with nothing but supports in it supports nothing: the audit says so.
The author's weapon-swap "Arcane Surge + Elemental Focus" group came in as a live group and
sat in the build's sockets doing nothing."""

from junkroan.optimizer.audit import audit_xml


def _xml(*groups: str) -> str:
    return ('<PathOfBuilding><Build mainSocketGroup="1"/><Tree/><Skills activeSkillSet="1"><SkillSet id="1">'
            + "".join(groups) + "</SkillSet></Skills><Items/></PathOfBuilding>")


def _gem(name: str, enabled: str = "true") -> str:
    return f'<Gem nameSpec="{name}" enabled="{enabled}" level="18" quality="0"/>'


def _group(gems: str, enabled: str = "true", slot: str = "Body Armour") -> str:
    return f'<Skill enabled="{enabled}" slot="{slot}">{gems}</Skill>'


def _dead(xml: str):
    return [f for f in audit_xml(xml) if f.check == "dead support group"]


def test_a_support_only_group_is_flagged_once_with_its_gems() -> None:
    found = _dead(_xml(_group(_gem("Fortify"))))
    assert len(found) == 1 and found[0].severity == "warning"
    assert found[0].detail == "Fortify: a support with no active gem to support"

    pair = _dead(_xml(_group(_gem("Arcane Surge") + _gem("Elemental Focus"), slot="Weapon 1")))
    assert len(pair) == 1 and pair[0].detail == "Arcane Surge, Elemental Focus: supports with no active gem to support"


def test_a_support_beside_an_active_gem_is_not_flagged() -> None:
    assert _dead(_xml(_group(_gem("Smite") + _gem("Fortify")))) == []
    assert _dead(_xml(_group(_gem("Smite")))) == []


def test_a_disabled_group_or_gem_is_not_a_live_group() -> None:
    assert _dead(_xml(_group(_gem("Fortify"), enabled="false"))) == [], "a disabled group is not in the build"
    assert _dead(_xml(_group(_gem("Fortify", enabled="false")))) == [], "no enabled gem at all: nothing to flag"
    assert len(_dead(_xml(_group(_gem("Smite", enabled="false") + _gem("Fortify"))))) == 1, "the active gem is off: the support is alone"


def test_two_dead_groups_give_two_findings_and_an_unknown_gem_gives_none() -> None:
    assert len(_dead(_xml(_group(_gem("Fortify")), _group(_gem("Elemental Focus"), slot="Gloves")))) == 2
    assert _dead(_xml(_group(_gem("Not A Gem At All")))) == []
