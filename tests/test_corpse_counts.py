"""D57 rule 2, no PoB: a corpse-fed skill is instance-counted, the count is derived (corpses eaten
per cast, Spell Cascade's areas included, held down by the creator's capped pool), and the audit
flags a consumer no gem in the build feeds."""

import json
import sys
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_xml
from junkroan.optimizer.objective_select import counts_instances
from junkroan.pob.skill_facts import cascade_areas, corpses_consumed_per_cast, corpses_created_per_cast
from junkroan.search.skeleton import Skeleton, SocketGroup, derived_counts

from conftest import needs_skill_source

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class _Pob:
    """A corpse build asks PoB for no limit stat at all; the setter calls are recorded so a trial
    link can be checked against what was written into the session."""

    def __init__(self, allocated=()) -> None:
        self.skills: list[dict] = []
        self.allocated = list(allocated)

    def stats(self, keys):
        return {}

    def set_skills(self, **kwargs):
        self.skills.append(kwargs)

    def tree_light(self):
        return {"user_allocated_node_ids": self.allocated}


def _xml(*groups: str) -> str:
    return ('<PathOfBuilding><Build mainSocketGroup="1"/><Tree/><Skills activeSkillSet="1"><SkillSet id="1">'
            + "".join(groups) + "</SkillSet></Skills><Items/></PathOfBuilding>")


def _gem(name: str, skill_id: str, enabled: str = "true") -> str:
    return f'<Gem nameSpec="{name}" skillId="{skill_id}" enabled="{enabled}" level="18" quality="0"/>'


@needs_skill_source
def test_the_corpse_facts_come_from_pob_skill_data() -> None:
    assert corpses_consumed_per_cast("VolatileDead") == 3
    assert corpses_consumed_per_cast("Fireball") is None and corpses_consumed_per_cast("NoSuchSkill") is None
    assert corpses_created_per_cast("Desecrate") == (5, 10)
    assert corpses_created_per_cast("Unearth") == (1, 10)  # one Bone Archer per cast, the same 10-corpse cap as Desecrate in its block
    assert corpses_created_per_cast("Fireball") is None
    assert cascade_areas("SupportSpellCascade") == 3
    assert cascade_areas("Fireball") == 1 and cascade_areas("SupportConcentratedEffect") == 1 and cascade_areas("") == 1


@needs_skill_source
def test_the_count_is_the_corpses_eaten_per_cast_held_down_by_what_the_build_creates() -> None:
    def counts(*links):
        return derived_counts(_Pob(), [g for link in links for g in link], links=list(links))

    # Spell Cascade on both sides: 3 corpses x 3 areas eaten, Desecrate's 5 x 3 capped at 10 supplied
    assert counts(["Volatile Dead", "Spellslinger", "Spell Cascade"], ["Spellslinger", "Desecrate", "Spell Cascade"]) == {"Volatile Dead": 9}
    assert counts(["Volatile Dead"], ["Desecrate"]) == {"Volatile Dead": 3}
    # cascaded consumer, plain creator: the supply, not the appetite, is what PoB may multiply by
    assert counts(["Volatile Dead", "Spell Cascade"], ["Desecrate"]) == {"Volatile Dead": 5}
    assert counts(["Volatile Dead", "Spell Cascade"]) == {"Volatile Dead": 1}, "no corpse source: PoB's own default of one"
    assert counts(["Fireball", "Spell Cascade"], ["Desecrate"]) == {}, "no consumer: nothing to count"


@needs_skill_source
def test_the_creator_pool_cap_is_shared_and_undertaker_raises_it(monkeypatch) -> None:
    """A large fake appetite makes the ordinary 10 versus Undertaker's 12 cap observable."""

    from junkroan.pob import skill_facts

    original = skill_facts.corpses_consumed_per_cast
    monkeypatch.setattr(skill_facts, "corpses_consumed_per_cast", lambda effect_id: 20 if effect_id == "VolatileDead" else original(effect_id))
    links = [["Volatile Dead"], ["Desecrate", "Spell Cascade"]]

    assert derived_counts(_Pob(), ["Volatile Dead", "Desecrate", "Spell Cascade"], links=links) == {"Volatile Dead": 10}
    assert derived_counts(_Pob(allocated=[25439]), ["Volatile Dead", "Desecrate", "Spell Cascade"], links=links) == {"Volatile Dead": 12}


LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


@pytest.mark.pob
@needs_pob
def test_volatile_dead_fixtures_follow_the_creator_cascade_supply(tmp_path: Path) -> None:
    from xml.etree import ElementTree as ET

    from build_from_skeleton import skeleton_from_xml
    from junkroan.pob.session import PobSession, decode_import_code

    def links_of(xml: str, pob: PobSession) -> tuple[str, list[list[str]]]:
        skeleton = skeleton_from_xml(xml, pob=pob)
        return skeleton.main_link[0], [skeleton.main_link, *(group.gems for group in skeleton.extra_groups if group.enabled)]

    def count(xml: str, run_id: str) -> int:
        with PobSession(run_id=run_id, artifacts_root=tmp_path) as pob:
            pob.load_xml(xml)
            main, links = links_of(xml, pob)
            return derived_counts(pob, [main], links=links)[main]

    archmage = decode_import_code((ROOT / "tests" / "fixtures" / "tuadh_329" / "archmage_volatile_dead.pob.txt").read_text(encoding="utf-8").strip())
    spellslinger = decode_import_code((ROOT / "tests" / "fixtures" / "tuadh_329" / "vd_spellslinger.pob.txt").read_text(encoding="utf-8").strip())
    assert count(archmage, "test-vd-archmage") == 9
    assert count(spellslinger, "test-vd-spellslinger") == 9

    root = ET.fromstring(archmage)
    desecrate_group = next(group for group in root.findall(".//Skill") if any(gem.get("nameSpec") == "Desecrate" for gem in group.findall("Gem")))
    cascade = next(gem for gem in desecrate_group.findall("Gem") if gem.get("nameSpec") == "Spell Cascade")
    desecrate_group.remove(cascade)
    assert count(ET.tostring(root, encoding="unicode"), "test-vd-archmage-plain-creator") == 5


@pytest.mark.pob
@needs_pob
def test_volatile_dead_author_lane_full_dps_uses_the_derived_count(tmp_path: Path) -> None:
    """The benchmark replacement count is measured after its gem rail and conservative lane."""

    from build_from_skeleton import skeleton_from_xml
    from benchmark import flag_main_group_for_full_dps, normalize_author_gems
    from junkroan.optimizer.buff_gems import disable_unreliable_buff_gems_xml
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.optimizer.judging import tune_choices, write_lanes
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code
    from xml.etree import ElementTree as ET

    def author_lane(xml: str, expected_count: int, run_id: str) -> float:
        xml, _ = disable_unreliable_buff_gems_xml(xml)
        rails = Rails.load()
        with PobSession(run_id=run_id, artifacts_root=tmp_path) as pob:
            pob.load_xml(xml)
            pob.convert_tree()
            xml, _ = normalize_author_gems(xml, rails)
            pob.load_xml(xml)
            pob.convert_tree()
            skeleton = skeleton_from_xml(xml, pob=pob)
            links = [skeleton.main_link, *(group.gems for group in skeleton.extra_groups if group.enabled)]
            count = derived_counts(pob, [skeleton.main_link[0]], links=links)[skeleton.main_link[0]]
            assert count == expected_count
            xml = flag_main_group_for_full_dps(xml, count=count)
            pob.load_xml(xml)
            pob.convert_tree()
            current_uniques = {slot: pob.unique_item(name)["raw"] for slot, name in skeleton.uniques.items()}
            if current_uniques:
                pob.equip(current_uniques)
            derived = derive_config(pob, prefer_rules=True)
            pob.set_config(
                bandit=skeleton.bandit,
                pantheon_major=skeleton.pantheon_major,
                pantheon_minor=skeleton.pantheon_minor,
                inputs={key: value for key, value in derived.conservative.inputs.items() if key != "enemyIsBoss"},
                conditional={"inputs": {key: value for key, value in derived.optimistic.inputs.items() if key != "enemyIsBoss"}},
            )
            objective = objective_for(rails, skeleton.main_link[0])
            pipe = BuildPipeline(pob, rails, objective=objective, log=lambda _message: None)
            tune_choices(pob, skeleton, derived, objective=pipe.objective,
                         write=lambda sk, lanes: write_lanes(pob, sk, lanes, log=pipe.log), log=pipe.log, guard=False)
            return float(pob.stats(("FullDPS",))["FullDPS"])

    archmage = decode_import_code((ROOT / "tests" / "fixtures" / "tuadh_329" / "archmage_volatile_dead.pob.txt").read_text(encoding="utf-8").strip())
    spellslinger = decode_import_code((ROOT / "tests" / "fixtures" / "tuadh_329" / "vd_spellslinger.pob.txt").read_text(encoding="utf-8").strip())
    root = ET.fromstring(archmage)
    desecrate_group = next(group for group in root.findall(".//Skill") if any(gem.get("nameSpec") == "Desecrate" for gem in group.findall("Gem")))
    desecrate_group.remove(next(gem for gem in desecrate_group.findall("Gem") if gem.get("nameSpec") == "Spell Cascade"))

    actual = [
        author_lane(archmage, 9, "test-vd-author-archmage"),
        author_lane(spellslinger, 9, "test-vd-author-spellslinger"),
        author_lane(ET.tostring(root, encoding="unicode"), 5, "test-vd-author-archmage-plain-creator"),
    ]
    # vd_spellslinger links Momentum (the author's MomentumStacks = 1); since #17 (merge 71761b4) the stack judge
    # measures MomentumStacks at the gem's cap like any other stack option: 365,858.91 -> 422,116.85 (#620 bisect).
    assert actual == pytest.approx([936_332.00, 422_116.85, 522_055.16], abs=1.0)


@needs_skill_source
def test_links_default_to_one_gem_each_and_leave_minion_and_brand_counts_alone() -> None:
    # every name its own one-gem link: no cascade anywhere, VD eats 3, Desecrate supplies 5
    assert derived_counts(_Pob(), ["Volatile Dead", "Desecrate"]) == {"Volatile Dead": 3}
    assert derived_counts(_Pob(), ["Volatile Dead", "Spell Cascade"]) == {"Volatile Dead": 1}, "Spell Cascade in its own link cascades nothing, and no creator supplies anything"
    assert derived_counts(_Pob(), ["Fireball"]) == {}


@needs_skill_source
def test_a_corpse_fed_skill_is_judged_on_full_dps_like_a_minion() -> None:
    assert counts_instances("Volatile Dead")
    assert not counts_instances("Fireball")
    assert counts_instances("Raise Zombie")


@needs_skill_source
def test_the_audit_flags_a_corpse_consumer_with_no_creator_in_the_build() -> None:
    vd = f'<Skill enabled="true" slot="Body Armour">{_gem("Volatile Dead", "VolatileDead")}</Skill>'
    desecrate = f'<Skill enabled="true" slot="Gloves">{_gem("Desecrate", "Desecrate")}</Skill>'

    alone = [f for f in audit_xml(_xml(vd)) if f.check == "corpse source"]
    assert len(alone) == 1 and alone[0].severity == "error"
    assert alone[0].detail == "Volatile Dead consumes 3 corpses per cast and nothing in the build creates corpses"

    assert [f for f in audit_xml(_xml(vd, desecrate)) if f.check == "corpse source"] == []

    off_group = f'<Skill enabled="false" slot="Gloves">{_gem("Desecrate", "Desecrate")}</Skill>'
    assert len([f for f in audit_xml(_xml(vd, off_group)) if f.check == "corpse source"]) == 1, "a disabled group creates nothing"
    off_gem = f'<Skill enabled="true" slot="Gloves">{_gem("Desecrate", "Desecrate", enabled="nil")}</Skill>'
    assert len([f for f in audit_xml(_xml(vd, off_gem)) if f.check == "corpse source"]) == 1, "a disabled gem creates nothing"
    assert [f for f in audit_xml(_xml(f'<Skill enabled="true">{_gem("Volatile Dead", "VolatileDead", enabled="false")}</Skill>')) if f.check == "corpse source"] == []


@needs_skill_source
def test_refresh_uses_the_link_it_is_given_and_writes_it_back_with_the_count() -> None:
    pob = _Pob()
    sk = Skeleton(class_name="Witch", ascendancy="Necromancer", main_link=["Volatile Dead", "Spellslinger"],
                  extra_groups=[SocketGroup(gems=["Spellslinger", "Desecrate", "Spell Cascade"], slot="Gloves")])

    assert sk.refresh_minion_counts(pob, main_link=["Volatile Dead", "Spellslinger", "Spell Cascade"]) == {"Volatile Dead": 9}
    assert sk.gem_counts["Volatile Dead"] == 9
    assert pob.skills[-1]["main_link"] == ["Volatile Dead", "Spellslinger", "Spell Cascade"], "the trial link, not the skeleton's own"
    assert pob.skills[-1]["main_counts"]["Volatile Dead"] == 9

    assert sk.refresh_minion_counts(pob, main_link=["Volatile Dead", "Spellslinger"]) == {"Volatile Dead": 3}
    assert pob.skills[-1]["main_link"] == ["Volatile Dead", "Spellslinger"] and pob.skills[-1]["main_counts"]["Volatile Dead"] == 3

    sk.extra_groups[0].enabled = False
    assert sk.refresh_minion_counts(pob) == {"Volatile Dead": 1}, "a disabled group supplies no corpses"
    assert pob.skills[-1]["main_link"] == ["Volatile Dead", "Spellslinger"], "no trial link: the skeleton's own"
