"""#1024: a saved minion build keeps its minion values through the replay's `_pipeline_state`. Row 1 on PoB: the saved
absolution_minions s4 build (its main gem is Vaal Absolution, count 3, `skillMinionSkill` 2; Raise Zombie count 7,
`skillMinionSkill` 3) reads FullDPS 635,471 / CombinedDPS 66,423 saved and read 135,953 / 0 after the rewrite (count
3 -> 1 by `PobReads.minion_counts` handing `refresh_minion_counts` the Vaal-named link, `skillMinionSkill` 2 -> 1 and
3 -> 1 because `skeleton_from_xml` left `gem_minion_skills` empty). Row 2: a build with minions that is not a Vaal
main (summon_raging_spirits s4) reads what it read on the base commit. The unit tests run without PoB."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.search.skeleton import Skeleton, SocketGroup  # noqa: E402

BENCH = ROOT / "artifacts" / "benchmark" / "20261013-0101-P2-core-3"
RUNTIME = ROOT / "var" / "cache" / "pob"

SKILLS = """<Skills activeSkillSet="1"><SkillSet id="1">
<Skill label="Main" enabled="true" slot="Body Armour" includeInFullDPS="true" mainActiveSkill="1">
<Gem count="3" enabled="true" skillMinionSkill="2" nameSpec="Vaal Absolution" level="18"/>
<Gem count="1" enabled="true" nameSpec="Spell Echo" level="18"/></Skill>
<Skill label="Raise Zombie" enabled="true" slot="Helmet" includeInFullDPS="true" mainActiveSkill="1">
<Gem count="7" enabled="true" skillMinionSkill="3" nameSpec="Raise Zombie" level="18"/>
<Gem count="1" enabled="true" skillMinionSkill="4" nameSpec="Summon Carrion Golem" level="18"/></Skill>
<Skill label="Other" enabled="true" slot="Gloves" includeInFullDPS="false" mainActiveSkill="1">
<Gem count="1" enabled="true" skillMinionSkill="2" nameSpec="Summon Sentinel of Radiance" level="18"/></Skill>
</SkillSet></Skills>"""


def test_minion_skills_from_xml_keys_a_vaal_gem_by_its_plain_name_and_reads_carried_groups_only() -> None:
    from build_from_skeleton import minion_skills_from_xml

    skills = ET.fromstring(SKILLS)
    skeleton = Skeleton(class_name="Witch", ascendancy="None", main_link=["Absolution", "Spell Echo"], main_slot="Body Armour",
                        extra_groups=[SocketGroup(gems=["Raise Zombie", "Summon Carrion Golem"], slot="Helmet", enabled=True, source_index=2)])

    assert minion_skills_from_xml(skills, skeleton, 1) == {"Absolution": 2, "Raise Zombie": 3, "Summon Carrion Golem": 4}  # group 3 is not carried


def test_the_skeleton_writes_the_saved_minion_skills_on_its_gems() -> None:
    skeleton = Skeleton(class_name="Witch", ascendancy="None", main_link=["Absolution"], main_slot="Body Armour",
                        gem_minion_skills={"Absolution": 2})

    gems = skeleton.skill_payload()["main_minion_skills"]
    assert gems == {"Absolution": 2}


def test_minion_counts_names_the_held_vaal_link_the_skeletons_way() -> None:
    from junkroan.optimizer.judging import PobReads

    seen: dict = {}
    skeleton = SimpleNamespace(gem_counts={}, main_link=["Absolution", "Spell Echo"],
                               refresh_minion_counts=lambda pob, **kw: seen.update(kw))
    pob = SimpleNamespace(read_state=lambda: {"skills_state": {"main_socket_group_id": "g", "socket_groups": [
        {"socket_group_id": "g", "gems": [{"gem_name": "Vaal Absolution"}, {"gem_name": "Spell Echo"}]}]}})
    gems = SimpleNamespace(level=18, quality=0, main_quality=0)

    PobReads(pob, gems=gems).minion_counts(skeleton)
    assert seen["main_link"] is None  # the build's Vaal link is the skeleton's own link, not a trial

    pob = SimpleNamespace(read_state=lambda: {"skills_state": {"main_socket_group_id": "g", "socket_groups": [
        {"socket_group_id": "g", "gems": [{"gem_name": "Vaal Absolution"}, {"gem_name": "Added Lightning Damage"}]}]}})
    PobReads(pob, gems=gems).minion_counts(skeleton)
    assert seen["main_link"] == ["Absolution", "Added Lightning Damage"]  # a real trial still goes through, in plain names


def _run(name: str) -> dict:
    import replay_bench as rb
    from junkroan.pob.session import PobSession

    path = BENCH / f"{name}.pob.txt"
    info = rb.source_info(path)
    logs: list[str] = []
    with PobSession(run_id="test-1024") as pob:
        prepared = rb._prepared_author(pob, info["slug"], info["stat"], logs.append)
        pob.load_import_code(path.read_text(encoding="utf-8").strip())
        before = pob.stats(("CombinedDPS", "FullDPS"))
        rb._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
        return {"before": before, "after": pob.stats(("CombinedDPS", "FullDPS"))}


@pytest.mark.pob
@pytest.mark.skipif(not (BENCH / "absolution_minions-s4.pob.txt").is_file() or not RUNTIME.is_dir(), reason="saved build or pinned PoB runtime not present")
def test_row1_the_saved_absolution_s4_build_keeps_its_counts_and_minion_skills_after_the_replay_pipeline_state() -> None:
    got = _run("absolution_minions-s4")

    assert got["before"]["FullDPS"] == pytest.approx(635_471, rel=1e-3)
    assert got["after"]["FullDPS"] >= 629_116  # was 135,953.2
    assert got["after"]["CombinedDPS"] == pytest.approx(66_423, rel=1e-3)  # was 0


@pytest.mark.pob
@pytest.mark.skipif(not (BENCH / "summon_raging_spirits-s4.pob.txt").is_file() or not RUNTIME.is_dir(), reason="saved build or pinned PoB runtime not present")
def test_row2_a_non_vaal_minion_build_reads_the_same_number() -> None:
    got = _run("summon_raging_spirits-s4")

    assert got["after"]["FullDPS"] == pytest.approx(1_173_290.59, rel=1e-4)  # the number on the base commit (95220c33)
    assert got["after"]["CombinedDPS"] == pytest.approx(0, abs=1e-6)
