"""#1169 unit 1: the audit names three error kinds of the 16.10 reading that only a rail blocked before.

1. `movement-pair-missing`: no gem of the movement spell slot or of the movement skill slot (`movement_pair_missing`'s rail, #1153).
2. `movement-gem-refused`: Smoke Mine / Lightning Warp socketed (the rails' `movement_forbidden`, #1153).
6. `flask-utility-crafted` (XML; the day-1 rail `flask_utility_crafting` false, #1162) and `flask-uptime` (PoB's "Flask uptime"
   line, D115; the `pob` test).

Every case is the 16.10 read build that had the error (decoded from its saved import code) and the same build with a minimal
edit; the synthetic cases need no artifacts. Read builds: A1 Contagion (Dash only, four utility flasks), B1 Searing Bond (Flame
Dash only), C1 Armageddon Brand (Smoke Mine, four utility flasks); no read build had Lightning Warp.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_flask_uptime, audit_xml
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import decode_import_code

ROOT = Path(__file__).resolve().parents[1]
A1 = ROOT / "artifacts/search-contagion/20261015-0336/01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
B1 = ROOT / "artifacts/search-searing_bond/20261015-0004/01 templar_inquisitor_demon_dagger.pob.txt"
C1 = ROOT / "artifacts/search-armageddon_brand/20261014-2358/01 templar_hierophant_demon_dagger.pob.txt"
needs_artifacts = pytest.mark.skipif(not (A1.exists() and B1.exists() and C1.exists()), reason="16.10 read builds not linked")

PAIR = "movement-pair-missing"
REFUSED = "movement-gem-refused"
CRAFTED = "flask-utility-crafted"
UPTIME = "flask-uptime"


def _load(path: Path) -> str:
    return decode_import_code(path.read_text(encoding="utf-8").strip())


def _kind(findings, check):
    return [f for f in findings if f.check == check]


def _rename_gem(xml: str, old: str, new: str) -> str:
    return xml.replace(f'nameSpec="{old}"', f'nameSpec="{new}"')


def _add_group(xml: str, gem: str, slot: str = "Gloves") -> str:
    group = f'<Skill includeInFullDPS="false" mainActiveSkill="1" enabled="true" slot="{slot}" label="{gem}"><Gem skillId="{gem}" level="18" enabled="true" quality="0" nameSpec="{gem}"/></Skill>'
    return xml.replace("</SkillSet>", group + "</SkillSet>", 1)


def _without_utility_flasks(xml: str) -> str:
    return re.sub(r'(<Slot itemId=")\d+(" name="Flask [2-5]")', r"\g<1>0\g<2>", xml)


def _synthetic(gems: list[str], *, main: str = "Fireball", flasks: list[str] | None = None, weapon: str | None = None) -> str:
    groups = f'<Skill mainActiveSkill="1" enabled="true" slot="Body Armour"><Gem enabled="true" level="18" quality="0" nameSpec="{main}"/></Skill>'
    groups += "".join(f'<Skill enabled="true" slot="Helmet"><Gem enabled="true" level="18" quality="0" nameSpec="{g}"/></Skill>' for g in gems)
    items, slots = "", ""
    for n, name in enumerate(flasks or [], start=1):
        items += f'<Item id="{n}">Rarity: MAGIC\n{name}\nItem Level: 70\n</Item>'
        slots += f'<Slot name="Flask {n}" itemId="{n}"/>'
    if weapon:
        items += f'<Item id="9">Rarity: RARE\nRandom 1\n{weapon}\n</Item>'
        slots += '<Slot name="Weapon 1" itemId="9"/>'
    return (f'<PathOfBuilding><Skills activeSkillSet="1"><SkillSet id="1">{groups}</SkillSet></Skills>'
            f'<Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>')


def _flask_rails(utility: bool) -> Rails:
    base = Rails.load()
    return dataclasses.replace(base, gear=dataclasses.replace(base.gear, flasks=dataclasses.replace(base.gear.flasks, flask_utility_crafting=utility)))


# ---- 1: no movement skill pair ------------------------------------------------------------------------------------------

@needs_artifacts
@pytest.mark.parametrize("path, spell", [(A1, "Dash"), (B1, "Flame Dash"), (C1, None)])
def test_check1_the_read_builds_have_no_movement_skill(path: Path, spell: str | None) -> None:
    found = _kind(audit_xml(_load(path)), PAIR)
    assert len(found) == 1 and found[0].severity == "error"
    assert "movement skill" in found[0].detail and "Leap Slam" in found[0].detail  # the rail's own words and list
    assert (spell is None) == ("movement spell" in found[0].detail)  # C1 has no spell either: both slots named


@needs_artifacts
def test_check1_a_leap_slam_group_removes_the_finding() -> None:
    assert _kind(audit_xml(_add_group(_load(A1), "Leap Slam")), PAIR) == []
    assert _kind(audit_xml(_add_group(_load(B1), "Leap Slam")), PAIR) == []


def test_check1_synthetic_pairs() -> None:
    assert _kind(audit_xml(_synthetic(["Frostblink", "Shield Charge"])), PAIR) == []
    assert _kind(audit_xml(_synthetic(["Dash", "Leap Slam"])), PAIR) == []
    only_skill = _kind(audit_xml(_synthetic(["Leap Slam"])), PAIR)
    assert len(only_skill) == 1 and "movement spell" in only_skill[0].detail and "movement skill" not in only_skill[0].detail
    assert len(_kind(audit_xml(_synthetic([])), PAIR)) == 1


def test_check1_the_main_skill_counts_as_a_movement_gem() -> None:
    assert _kind(audit_xml(_synthetic(["Dash"], main="Leap Slam")), PAIR) == []


def test_check1_a_disabled_movement_gem_does_not_count() -> None:
    xml = _synthetic(["Dash", "Leap Slam"]).replace('enabled="true" level="18" quality="0" nameSpec="Leap Slam"', 'enabled="false" level="18" quality="0" nameSpec="Leap Slam"')
    assert len(_kind(audit_xml(xml), PAIR)) == 1


def test_check1_a_staff_may_skip_the_movement_skill_but_never_the_spell() -> None:
    """The rail skips Leap Slam on a slow Staff build (Attack Time is a PoB number), so the XML check cannot call it missing."""

    assert _kind(audit_xml(_synthetic(["Dash"], weapon="Coiled Staff")), PAIR) == []
    assert len(_kind(audit_xml(_synthetic([], weapon="Coiled Staff")), PAIR)) == 1


def test_check1_does_not_apply_when_the_rails_do_not_require_a_pair() -> None:
    rails = dataclasses.replace(Rails.load(), movement_skill_required=False)
    assert _kind(audit_xml(_synthetic([]), rails), PAIR) == []


# ---- 2: Smoke Mine as the movement skill --------------------------------------------------------------------------------

@needs_artifacts
def test_check2_c1_smoke_mine_is_named() -> None:
    found = _kind(audit_xml(_load(C1)), REFUSED)
    assert len(found) == 1 and found[0].severity == "error"
    assert "Smoke Mine" in found[0].detail and "Helmet" in found[0].detail


@needs_artifacts
def test_check2_builds_without_smoke_mine_have_no_finding() -> None:
    assert _kind(audit_xml(_load(A1)), REFUSED) == []
    assert _kind(audit_xml(_load(B1)), REFUSED) == []
    assert _kind(audit_xml(_rename_gem(_load(C1), "Smoke Mine", "Flame Dash")), REFUSED) == []


def test_check2_lightning_warp_is_the_other_refused_gem() -> None:
    found = _kind(audit_xml(_synthetic(["Lightning Warp", "Leap Slam"])), REFUSED)
    assert len(found) == 1 and "Lightning Warp" in found[0].detail
    assert _kind(audit_xml(_synthetic(["Flame Dash", "Leap Slam"])), REFUSED) == []


def test_check2_does_not_apply_when_the_rails_do_not_require_a_pair() -> None:
    rails = dataclasses.replace(Rails.load(), movement_skill_required=False)
    assert _kind(audit_xml(_synthetic(["Smoke Mine"]), rails), REFUSED) == []


# ---- 6: a crafted utility flask on day 1, and a flask without 100 % Flask uptime ------------------------------------------

@needs_artifacts
@pytest.mark.parametrize("path, names", [
    (A1, ["Sulphur", "Jade", "Amethyst", "Granite"]),
    (C1, ["Silver", "Diamond", "Sulphur", "Amethyst"]),
])
def test_check6_read_builds_with_four_utility_flasks(path: Path, names: list[str]) -> None:
    found = _kind(audit_xml(_load(path), _flask_rails(False)), CRAFTED)
    assert len(found) == 4 and all(f.severity == "error" for f in found)
    for name in names:
        assert any(f"{name} Flask" in f.detail for f in found)
    assert all("Flask 1" not in f.detail for f in found)  # the Divine Life Flask is a life flask: allowed
    assert "Life, Mana or Hybrid" in found[0].detail


@needs_artifacts
def test_check6_a_build_with_only_the_life_flask_has_no_finding() -> None:
    xml = _without_utility_flasks(_load(A1))
    assert _kind(audit_xml(xml, _flask_rails(False)), CRAFTED) == []


@needs_artifacts
def test_check6_does_not_apply_where_the_rails_craft_utility_flasks() -> None:
    assert _kind(audit_xml(_load(A1), _flask_rails(True)), CRAFTED) == []


def test_check6_synthetic_bases() -> None:
    day1 = _flask_rails(False)
    life = _synthetic([], flasks=["Undiluted Divine Life Flask", "Hallowed Hybrid Flask", "Sanctified Mana Flask"])
    assert _kind(audit_xml(life, day1), CRAFTED) == []
    tincture = _synthetic([], flasks=["Rosethorn Tincture of Fury"])
    assert len(_kind(audit_xml(tincture, day1), CRAFTED)) == 1  # tinctures are utility too (#1162: "tinctures included")
    assert _kind(audit_xml(tincture, _flask_rails(True)), CRAFTED) == []


@pytest.mark.pob
@pytest.mark.skipif(not (ROOT / "var/cache/pob").exists(), reason="PoB runtime not present (var/cache/pob)")
@needs_artifacts
def test_check6_pob_uptime_of_the_read_flasks() -> None:
    """PoB's own "Flask uptime" line: the four Ibex flasks of A1 print less than 100 %, so each is an error; the Divine Life Flask is not judged."""

    from junkroan.pob.session import PobSession

    xml = _load(A1)
    with PobSession(run_id="issue1169-flask-uptime") as pob:
        pob.load_xml(xml)
        found = _kind(audit_flask_uptime(pob, xml), UPTIME)
        pob.load_xml(_without_utility_flasks(xml))
        clean = _kind(audit_flask_uptime(pob, _without_utility_flasks(xml)), UPTIME)
    assert len(found) == 4 and all(f.severity == "error" for f in found)
    assert all("Flask uptime" in f.detail and "Flask 1" not in f.detail for f in found)
    assert clean == []
