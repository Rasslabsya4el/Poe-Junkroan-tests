"""scripts/extract_loadout.py: one loadout of a multi-loadout author PoB, as a single-loadout build.

The first tests need no PoB: a synthetic build with three of everything is reduced to one loadout,
and what PoB reads (`activeSpec` by position, `activeItemSet` / `activeSkillSet` / `activeConfigSet`
by id, `mainSocketGroup` by position in the active skill set) must come out consistent. The last
one loads an extracted fixture into the pinned runtime and is skipped without it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from conftest import copy_omitted_fixtures

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from extract_loadout import extract_loadout, league_folders, main_skill_names, manifest_rows, markers, plain_title, select_titled  # noqa: E402

from junkroan.pob.session import PobSession, decode_import_code, encode_import_code  # noqa: E402

EARLY = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_329" / "early"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

# three item sets, three specs, three skill sets, two config sets; the build is left on its endgame
# stage, exactly as a guide PoB is. Item 7 hangs off the early spec's jewel socket, 9 off the endgame
# one, so an extraction that only reads the item set would lose a jewel.
MULTI = """<PathOfBuilding>
<Build level="90" className="Witch" ascendClassName="Elementalist" mainSocketGroup="1" characterLevelAutoMode="true" bandit="None"/>
<Tree activeSpec="3">
 <Spec title="Level 12" treeVersion="3_28" nodes="11,12"><URL>x</URL><Sockets/></Spec>
 <Spec title="^4Early Game {1}" treeVersion="3_28" nodes="11,12,13,14"><URL>x</URL><Sockets><Socket nodeId="100" itemId="7"/><Socket nodeId="101" itemId="0"/></Sockets></Spec>
 <Spec title="Endgame {2}" treeVersion="3_28" nodes="11,12,13,14,15,16"><URL>x</URL><Sockets><Socket nodeId="100" itemId="9"/></Sockets></Spec>
</Tree>
<Skills activeSkillSet="7">
 <SkillSet id="7" title="Endgame {2}"><Skill slot="Body Armour"><Gem nameSpec="Firestorm" level="20"/></Skill></SkillSet>
 <SkillSet id="4" title="^4Early Game {1}">
  <Skill slot="Boots" mainActiveSkill="1"><Gem nameSpec="Flame Dash" level="18"/></Skill>
  <Skill slot="Body Armour" mainActiveSkill="1"><Gem nameSpec="Fireball" level="18"/><Gem nameSpec="Spell Echo" level="18"/></Skill>
 </SkillSet>
 <SkillSet id="2" title="Level 12"><Skill><Gem nameSpec="Freezing Pulse" level="6"/></Skill></SkillSet>
</Skills>
<Config activeConfigSet="5">
 <ConfigSet id="5" title="Endgame {2}"><Input name="enemyIsBoss" string="Pinnacle"/></ConfigSet>
 <ConfigSet id="3" title="Default {1}"><Input name="enemyIsBoss" string="None"/></ConfigSet>
</Config>
<Items activeItemSet="6" useSecondWeaponSet="true">
 <Item id="5">Rarity: RARE\nFoo\nWand</Item>
 <Item id="6">Rarity: RARE\nBar\nIron Hat</Item>
 <Item id="7">Rarity: RARE\nJewel\nCobalt Jewel</Item>
 <Item id="8">Rarity: UNIQUE\nEndgame Thing\nWand</Item>
 <Item id="9">Rarity: RARE\nEndgame Jewel\nCobalt Jewel</Item>
 <ItemSet id="6" title="Endgame {2}" useSecondWeaponSet="true"><Slot name="Weapon 1" itemId="8"/><Slot name="Helmet" itemId="0"/></ItemSet>
 <ItemSet id="1" title="^4Early Game {1}" useSecondWeaponSet="false"><Slot name="Weapon 1" itemId="5"/><Slot name="Helmet" itemId="6"/><Slot name="Boots" itemId="0"/></ItemSet>
 <ItemSet id="2" title="Level 12" useSecondWeaponSet="false"><Slot name="Weapon 1" itemId="5"/></ItemSet>
</Items>
</PathOfBuilding>
"""


def early_loadout() -> tuple[str, dict]:
    return extract_loadout(MULTI, item_set="Early Game {1}", spec="Early Game {1}", skill_set="Early Game {1}",
                           level=68, main_skill="Fireball (Spell Echo)")


def test_one_loadout_keeps_one_of_every_set_and_renumbers_it() -> None:
    xml, report = early_loadout()
    root = ET.fromstring(xml)

    specs = root.find("Tree").findall("Spec")
    assert len(specs) == 1 and plain_title(specs[0].get("title")) == "Early Game {1}"
    assert root.find("Tree").get("activeSpec") == "1"  # a position in the spec list, not an id

    skill_sets = root.find("Skills").findall("SkillSet")
    assert len(skill_sets) == 1 and skill_sets[0].get("id") == "1" and root.find("Skills").get("activeSkillSet") == "1"

    item_sets = root.find("Items").findall("ItemSet")
    assert len(item_sets) == 1 and item_sets[0].get("id") == "1" and root.find("Items").get("activeItemSet") == "1"
    # PoB saves <Items useSecondWeaponSet> off the active set, so it follows the kept one
    assert root.find("Items").get("useSecondWeaponSet") == "false"

    config_sets = root.find("Config").findall("ConfigSet")
    assert len(config_sets) == 1 and config_sets[0].get("id") == "1" and root.find("Config").get("activeConfigSet") == "1"
    assert plain_title(config_sets[0].get("title")) == "Default {1}", "the config set is chosen by the loadout's {1} marker"

    assert report["spec"]["was_position"] == 2 and report["skill_set"]["was_id"] == "4" and report["item_set"]["was_id"] == "1"
    assert report["config_set"]["was_id"] == "3" and report["spec"]["allocated_nodes"] == 4


def test_only_the_items_the_kept_loadout_points_at_survive() -> None:
    """The item set's slots and the kept spec's tree-jewel sockets; everything else goes."""

    xml, report = early_loadout()
    items = ET.fromstring(xml).find("Items")
    assert {i.get("id") for i in items.findall("Item")} == {"5", "6", "7"}  # 7 hangs off the spec's jewel socket
    assert report["items_kept"] == 3 and report["items_dropped"] == 2 and report["tree_jewels"] == 1


def test_the_level_is_written_and_pobs_auto_level_mode_switched_off() -> None:
    xml, report = early_loadout()
    build = ET.fromstring(xml).find("Build")
    assert build.get("level") == "68" and report["level"] == 68
    # PoB's auto mode would overwrite the level from the node count (Build.lua EstimatePlayerProgress)
    assert build.get("characterLevelAutoMode") == "false"

    kept, _ = extract_loadout(MULTI, item_set="Early Game {1}", spec="Early Game {1}", skill_set="Early Game {1}")
    assert ET.fromstring(kept).find("Build").get("level") == "90", "without a level the build keeps its own"


def test_the_main_socket_group_moves_to_the_group_holding_the_main_skill() -> None:
    """`mainSocketGroup` is a position in the *active* skill set, so the author's index points at
    whatever stage they left the file on ("Flame Dash" here)."""

    xml, report = early_loadout()
    root = ET.fromstring(xml)
    groups = root.find("Skills").find("SkillSet").findall("Skill")
    assert root.find("Build").get("mainSocketGroup") == "2"
    assert [g.get("nameSpec") for g in groups[1].findall("Gem")] == ["Fireball", "Spell Echo"]
    assert report["main_socket_group"] == 2 and report["main_group_gems"] == ["Fireball", "Spell Echo"]
    assert any("mainSocketGroup 1" in n for n in report["notes"])
    # the main skill's own position inside the group is PoB's mainActiveSkill (1 of 1 active gem here)
    assert groups[1].get("mainActiveSkill") == "1"


def test_a_title_can_be_named_exactly_with_or_without_colour_codes_or_as_a_regex() -> None:
    specs = ET.fromstring(MULTI).find("Tree").findall("Spec")
    assert select_titled(specs, "^4Early Game {1}", "spec")[1] == 2  # the raw title
    assert select_titled(specs, "Early Game {1}", "spec")[1] == 2  # without PoB's colour escape
    assert select_titled(specs, "early game .1.", "spec")[1] == 2  # as a regex, case-insensitively
    assert select_titled(specs, "Endgame {2}", "spec")[1] == 3
    with pytest.raises(ValueError, match="Level 99"):
        select_titled(specs, "Level 99", "spec")
    with pytest.raises(ValueError, match="matches 2"):
        select_titled(specs, "Level|Endgame", "spec")


def test_markers_and_plain_titles_are_read_the_way_the_authors_write_them() -> None:
    assert markers("Endgame {2,4}") == {"2", "4"} and markers("^4Early Game {1}") == {"1"}
    assert markers("Early Game") == set() and markers("Maps {1,2,3}") == {"1", "2", "3"}
    assert plain_title("^4Early Game {1}") == "Early Game {1}" and plain_title("^xFF0000Endgame") == "Endgame"


def test_a_main_skill_the_early_loadout_does_not_run_falls_back_to_the_largest_group() -> None:
    """An early loadout often maps on another skill than the build's headline one (the Ice Nova
    Hierophant of 3.25 maps on Firestorm): then the main link is the longest live group, never the
    author's leftover index into a group of buffs."""

    xml, report = extract_loadout(MULTI, item_set="Early Game {1}", spec="Early Game {1}", skill_set="Early Game {1}",
                                  main_skill="Ice Nova of Frostbolts")
    assert report["main_socket_group"] == 2 and report["main_group_gems"] == ["Fireball", "Spell Echo"]
    assert ET.fromstring(xml).find("Build").get("mainSocketGroup") == "2"
    assert any("no socket group of the kept skill set holds" in n and "largest live group" in n for n in report["notes"])


def test_the_main_skill_is_read_with_its_alternatives_and_without_its_parenthetical() -> None:
    assert main_skill_names("Explosive Arrow (Ballista Totem)") == ["Explosive Arrow (Ballista Totem)", "Explosive Arrow"]
    assert main_skill_names("Sunder / Eviscerate") == ["Sunder / Eviscerate", "Sunder", "Eviscerate"]
    assert main_skill_names("Essence Drain (+ Contagion / Bane)") == ["Essence Drain (+ Contagion / Bane)", "Essence Drain"]
    assert main_skill_names("Winter Orb") == ["Winter Orb"] and main_skill_names(None) == []


@copy_omitted_fixtures
def test_every_league_folder_is_covered_and_a_build_without_an_early_loadout_is_skipped() -> None:
    """One manifest per Zizaran league; a build whose `early_loadout` is null has no staged
    loadouts and is named rather than guessed at."""

    folders = league_folders()
    assert [f.name for f in folders] == sorted(f.name for f in folders) and len(folders) >= 5
    assert league_folders("327") == league_folders("3.27") == [PROJECT_ROOT / "tests" / "fixtures" / "zizaran_327"]

    skipped_total, extracted_total = [], 0
    for folder in folders:
        _manifest, rows, skipped = manifest_rows(folder)
        extracted_total += len(rows)
        skipped_total += [f"{folder.name}/{s}" for s in skipped]
        assert all(r["early_loadout"] for r in rows)
        # every extracted build has its file, and nothing else is in the folder
        assert {r["slug"] for r in rows} == {p.name[: -len(".pob.txt")] for p in (folder / "early").glob("*.pob.txt")}
    assert skipped_total == ["zizaran_326/necromancer_zombie_army_late", "zizaran_327/assassin_poison_cremation"]
    assert extracted_total == 31


def test_the_result_is_a_valid_pob_import_code_round_trip() -> None:
    xml, _ = early_loadout()
    assert decode_import_code(encode_import_code(xml)) == xml


def test_a_loadout_whose_sets_carry_no_shared_marker_keeps_the_builds_own_config_set() -> None:
    """Nothing in the loadout names a config set: the author's active one is kept, and said so."""

    xml, report = extract_loadout(MULTI, item_set="Level 12", spec="Level 12", skill_set="Level 12")
    assert plain_title(ET.fromstring(xml).find("Config").find("ConfigSet").get("title")) == "Endgame {2}"
    assert report["config_set"]["was_id"] == "5"
    assert any("kept the build's active set" in n for n in report["notes"])


@pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
@pytest.mark.pob
def test_an_extracted_fixture_loads_into_pob_with_its_level_and_tree(tmp_path: Path) -> None:
    """The reference the benchmark will read: it must load, carry the level and the node count the
    loadout was cut at, and report damage (a wrong main skill or main group reads as 0)."""

    code = (EARLY / "occultist_essence_drain.pob.txt").read_text(encoding="utf-8").strip()
    with PobSession(run_id="test-extract-loadout", artifacts_root=tmp_path) as pob:
        pob.load_import_code(code)
        stats = pob.stats(("CombinedDPS", "FullDPS", "Life"))
        after = ET.fromstring(pob.export_xml())

    assert after.find("Build").get("level") == "68"  # PoB keeps the level the extraction wrote
    spec = after.find("Tree").findall("Spec")
    assert len(spec) == 1 and len([n for n in spec[0].get("nodes").split(",") if n.strip()]) == 99
    assert len(after.find("Items").findall("ItemSet")) == 1 and len(after.find("Skills").findall("SkillSet")) == 1
    assert max(stats["CombinedDPS"], stats["FullDPS"] or 0) > 10_000 and stats["Life"] > 2000
