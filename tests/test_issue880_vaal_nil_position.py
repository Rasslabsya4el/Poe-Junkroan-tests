"""#880: PoB saves a nil mainActiveSkill as the string "nil"; delivery reads it as PoB's loader does (non-number = 1)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.vaal_delivery import deliver_vaal_twins
from tests.test_issue802_vaal_delivery import FakePob, _xml


class NilTolerantPob(FakePob):
    """The fake's own state read, with PoB's `tonumber(x) or 1` for the index."""

    def read_state(self) -> dict:
        root = ET.fromstring(self.xml)
        copy = ET.fromstring(self.xml)
        for skill in copy.find("Skills").find("SkillSet").findall("Skill"):
            try:
                skill.set("mainActiveSkill", str(int(skill.get("mainActiveSkill"))))
            except (TypeError, ValueError):
                skill.set("mainActiveSkill", "1")
        saved, self.xml = self.xml, ET.tostring(copy, encoding="unicode")
        try:
            return super().read_state()
        finally:
            self.xml = saved
            del root


def _run(main: str, gems: list) -> tuple[NilTolerantPob, list]:
    pob = NilTolerantPob(_xml((1, gems)).replace('mainActiveSkill="1"', f'mainActiveSkill="{main}"'))
    pairs = deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), lambda _m: None, level_rail=18, quality_rail=0)
    return pob, pairs


def _main_attr(pob: FakePob) -> str:
    return ET.fromstring(pob.xml).find("Skills").find("SkillSet").find("Skill").get("mainActiveSkill")


def test_nil_main_active_skill_is_position_1() -> None:
    pob, pairs = _run("nil", [("Domination", 18, 0), ("Clarity", 18, 0)])
    assert pairs == [("Clarity", "Vaal Clarity")]
    assert _main_attr(pob) == "nil"  # position 1 is Domination before and after: nothing to fix


def test_numeric_main_active_skill_stays() -> None:
    pob, pairs = _run("3", [("Added Fire Damage Support", 18, 0), ("Added Cold Damage Support", 18, 0), ("Domination", 18, 0), ("Clarity", 18, 0)])
    assert pairs == [("Clarity", "Vaal Clarity")]
    assert _main_attr(pob) == "3"
