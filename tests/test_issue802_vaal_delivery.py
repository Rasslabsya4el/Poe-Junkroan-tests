"""#802 unit 2b: at delivery every gem with a Vaal version is written as it (Vaal half off, level / quality unchanged).

Pure tests: the helper against the corpus, the swap on a synthetic gem list, the trace counts. One PoB test file part
(mark `pob`, 1 session): row 8, a hypothesis whose main skill is the Vaal twin of a core-set main skill, and the swap
on real fixtures (tests/test_issue802_vaal_delivery_pob.py).
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_gems import ABOVE_RAIL, count_delivered_gem
from junkroan.optimizer.vaal_delivery import deliver_vaal_twins
from junkroan.search.hypothesis import active_gems, support_gems
from junkroan.search.skeleton import Skeleton
from junkroan.search.vaal_twin import plain_of_vaal, vaal_twin, vaal_twins


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


# --- the helper ---------------------------------------------------------------------------------------------------


def test_twin_map_is_what_the_corpus_says() -> None:
    gems = active_gems()
    expected = {
        r["name"][5:].lower(): r["name"]
        for r in gems.values()
        if r.get("is_vaal_gem") and r["name"].startswith("Vaal ") and r["name"][5:].lower() in gems and not gems[r["name"][5:].lower()].get("is_vaal_gem")
    }
    assert vaal_twins() == expected and len(expected) > 40  # 52 Vaal records, 5 of them with no plain gem in the corpus
    for plain, vaal in expected.items():
        assert gems[vaal.lower()]["is_vaal_gem"] and vaal == "Vaal " + gems[plain]["name"]


def test_a_gem_with_a_twin_is_mapped_without_one_none_supports_never() -> None:
    assert vaal_twin("Spark") == "Vaal Spark" and vaal_twin("spark ") == "Vaal Spark"
    assert vaal_twin("Fireball") == "Vaal Fireball"
    assert vaal_twin("Vaal Spark") is None  # a Vaal gem has no twin of its own
    assert vaal_twin("Domination") is None  # the corpus holds "Vaal Domination" with no plain gem beside it
    assert vaal_twin("Not A Gem") is None
    assert plain_of_vaal("Vaal Spark") == "Spark" and plain_of_vaal("Spark") is None
    supports = {r["name"] for r in support_gems().values()}
    assert not [n for n in supports if vaal_twin(n)]  # supports never get a twin
    assert not set(vaal_twins().values()) & supports  # and the "Vaal ..." supports are not a twin of anything


# --- the swap on a synthetic gem list -------------------------------------------------------------------------------


class FakePob:
    """A PoB that holds an XML and answers the reads the swap makes. It lists active skills the way PoB does for most
    Vaal gems (the Vaal skill before the plain one), so the main skill's index shifts."""

    def __init__(self, xml: str) -> None:
        self.xml, self.loads = xml, 0

    def export_xml(self) -> str:
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.xml, self.loads = xml, self.loads + 1

    def read_state(self) -> dict:
        groups = []
        for skill in ET.fromstring(self.xml).find("Skills").find("SkillSet").findall("Skill"):
            entries = []
            for gem in skill.findall("Gem"):
                name = gem.get("nameSpec")
                entries += [{"name": name}, {"name": name[5:]}] if name.startswith("Vaal ") else [{"name": name}]
            groups.append({"active_skill_entries": entries, "main_active_skill_index": int(skill.get("mainActiveSkill") or 1)})
        return {"skills_state": {"socket_groups": groups}}

    def stats(self, keys) -> dict:
        return {"CombinedDPS": 1000.0}


def _xml(*groups: tuple[int, list[tuple[str, int, int]]]) -> str:
    skills = "".join(
        f'<Skill mainActiveSkill="{main}" enabled="true" slot="Body Armour">'
        + "".join(
            f'<Gem nameSpec="{n}" gemId="G/{n}" skillId="{n}" variantId="{n}" level="{lv}" quality="{q}" enabled="true" count="1" enableGlobal1="true" enableGlobal2="false"/>'
            for n, lv, q in gems
        )
        + "</Skill>"
        for main, gems in groups
    )
    return f'<PathOfBuilding><Build mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1">{skills}</SkillSet></Skills></PathOfBuilding>'


def _gems(xml: str) -> list[dict]:
    return [dict(g.attrib) for g in ET.fromstring(xml).iter("Gem")]


def _mains(pob: FakePob) -> list[str]:
    return [g["active_skill_entries"][g["main_active_skill_index"] - 1]["name"] for g in pob.read_state()["skills_state"]["socket_groups"]]


def test_swap_writes_n_of_n_twins_flags_false_true_level_quality_unchanged_main_kept() -> None:
    xml = _xml((1, [("Spark", 18, 0), ("Added Fire Damage Support", 18, 0), ("Righteous Fire", 17, 3)]), (3, [("Fireball", 18, 0), ("Clarity", 18, 0), ("Domination", 18, 0)]))
    pob = FakePob(xml)
    assert _mains(pob) == ["Spark", "Domination"]
    logs: list[str] = []
    pairs = deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), logs.append, level_rail=18, quality_rail=0)
    assert pairs == [("Spark", "Vaal Spark"), ("Righteous Fire", "Vaal Righteous Fire"), ("Fireball", "Vaal Fireball"), ("Clarity", "Vaal Clarity")]
    before, after = _gems(xml), _gems(pob.xml)
    assert [g["nameSpec"] for g in after] == ["Vaal Spark", "Added Fire Damage Support", "Vaal Righteous Fire", "Vaal Fireball", "Vaal Clarity", "Domination"]
    for old, new in zip(before, after):
        assert (old["level"], old["quality"], old["count"], old["enabled"]) == (new["level"], new["quality"], new["count"], new["enabled"])
        if new["nameSpec"].startswith("Vaal "):
            assert (new["enableGlobal1"], new["enableGlobal2"]) == ("false", "true") and not {"gemId", "skillId", "variantId"} & set(new)
        else:
            assert new == old  # a gem with no twin (a support, Domination) is not touched at all
    # the lists now read [Vaal Spark, Spark, ...] and [Vaal Fireball, Fireball, Vaal Clarity, Clarity, Domination]:
    # each group's main skill is kept by the name it had, never by its old index
    assert _mains(pob) == ["Spark", "Domination"]
    assert any("4 of 4" in line and "Spark -> Vaal Spark" in line for line in logs)


def test_swap_with_no_twin_writes_nothing() -> None:
    pob = FakePob(_xml((1, [("Domination", 18, 0), ("Added Fire Damage Support", 18, 0)])))
    assert deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), lambda _m: None, level_rail=18, quality_rail=0) == [] and pob.loads == 0


def test_swap_is_reverted_when_a_main_skill_cannot_be_kept() -> None:
    class Losing(FakePob):
        def read_state(self) -> dict:
            state = super().read_state()
            if "Vaal " in self.xml:
                for g in state["skills_state"]["socket_groups"]:
                    g["active_skill_entries"] = [{"name": "Something Else"}]
            return state

    xml = _xml((1, [("Spark", 18, 0)]))
    pob, logs = Losing(xml), []
    assert deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), logs.append, level_rail=18, quality_rail=0) == []
    assert pob.xml == xml and any("reverted" in line for line in logs)


# --- the trace counter -------------------------------------------------------------------------------------------------


def test_trace_generated_and_evaluated_vaal_at_delivery_and_above_rail_is_counted() -> None:
    pob = FakePob(_xml((1, [("Spark", 18, 0), ("Clarity", 18, 0)])))
    deliver_vaal_twins(pob, Objective(maximize="CombinedDPS"), lambda _m: None, level_rail=18, quality_rail=0)
    row = TRACE.considered()["vaal delivery"]
    assert row["vaal"] == {"generated": 2, "evaluated": 2} and row["gem:Vaal Spark"] == {"generated": 1, "evaluated": 1}
    assert ABOVE_RAIL not in row  # evaluated(a Vaal or transfigured gem above 18/0 on day1) = 0

    TRACE.reset()
    count_delivered_gem("Vaal Spark", level=20, quality=0, level_rail=18, quality_rail=0)
    count_delivered_gem("Vaal Spark", level=18, quality=20, level_rail=18, quality_rail=0)
    count_delivered_gem("Spark", level=21, quality=20, level_rail=18, quality_rail=0)  # a plain gem is not this rule's
    TRACE.flush("x")
    assert TRACE.considered()["x"][ABOVE_RAIL]["evaluated"] == 2


# --- a skeleton keeps the plain gem (rule 3), the PoB-free half --------------------------------------------------------


def test_a_vaal_main_skill_is_searched_as_the_plain_gem() -> None:
    assert Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Vaal Spark", "Added Fire Damage Support"]).main_link == ["Spark", "Added Fire Damage Support"]
    assert Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Spark"]).main_link == ["Spark"]
    assert Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Vaal Domination"]).main_link == ["Vaal Domination"]  # no plain gem: kept as named
