"""scripts/benchmark.py without PoB: the named reference sets, the floors a reference is
rebuilt under, and the stage-loss flag (ROADMAP 7.1e)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import FIXTURE_DIRS, FIXTURES, SETS, ZIZ_REPUBLISHED, author_floors, author_memo_path, fixture_alias, fixture_path, fixture_slugs, lost_stages, normalize_author_gems, read_author_memo, write_author_memo  # noqa: E402

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.objective import ELEMENTAL_RESIST_RELATIONS  # noqa: E402


def test_the_seeds_of_one_reference_share_one_author_row(tmp_path: Path) -> None:
    """The author's row does not depend on the seed: the first seed of a reference measures it and
    writes the build as the measurement left it, the other seeds load exactly that (7.1h). The memo
    lives in the run's own output folder, so it can never be stale."""

    cache = str(tmp_path / "author")
    path = author_memo_path(cache, "spark", None)
    assert path == tmp_path / "author" / "spark-flasks-uptime-100.json"
    assert author_memo_path(cache, "spark", "FullDPS") != path  # the other stat is a different question
    assert author_memo_path(None, "spark", None) is None  # no cache dir: every seed measures its own

    assert read_author_memo(path) is None  # seed 1 finds nothing and measures the author itself
    measured = {"state_xml": "<PathOfBuilding>author</PathOfBuilding>", "author_raw": {"CombinedDPS": 898_678.0, "Life": 4156},
                "author_lane": {"CombinedDPS": 1_012_003.5, "Life": 4156}, "choices": {"waveOfConvictionExposureType": "Lightning"}}
    write_author_memo(path, measured)

    for _seed in (2, 3):  # every later seed replays the same row, field for field
        assert read_author_memo(path) == measured
    assert not list(path.parent.glob("*.tmp"))  # written through a temp file and renamed: no half-written memo is ever read

    path.write_text("{\"state_xml\": \"<PathOfBui", encoding="utf-8")  # a seed caught mid-write
    assert read_author_memo(path) is None  # unreadable is "measure it yourself", never a wrong row


def test_an_author_memo_measured_on_another_tree_is_not_replayed(tmp_path: Path) -> None:
    """The benchmark converts the author's build onto PoB's latest passive tree before it measures
    their row (`PobSession.convert_tree`). A memo written before that carries a row scored on the
    author's own older tree, and one stamped with another version answers another question: both
    are ignored, and the seed that finds them measures the author itself."""

    path = author_memo_path(str(tmp_path / "author"), "arc_archmage", None)
    old = {"state_xml": "<PathOfBuilding/>", "author_raw": {"CombinedDPS": 535_630.0}, "author_lane": {}, "choices": {}}
    write_author_memo(path, old)
    assert read_author_memo(path) == old, "with no version asked for, the memo is read as it is"
    assert read_author_memo(path, tree_version="3_29") is None, "written before the conversion: not replayed"

    write_author_memo(path, {**old, "tree_version": "3_28"})
    assert read_author_memo(path, tree_version="3_29") is None

    current = {**old, "tree_version": "3_29"}
    write_author_memo(path, current)
    assert read_author_memo(path, tree_version="3_29") == current


def test_an_author_memo_measured_on_other_gems_is_not_replayed(tmp_path: Path) -> None:
    """The same rule for the gem rails: the benchmark writes the rails' gems onto the author's build
    before it measures their row, so a memo written before that (or under other rails) carries a row
    scored on the author's own 20/20 gems and is not replayed."""

    path = author_memo_path(str(tmp_path / "author"), "z329_occultist_essence_drain", None)
    old = {"state_xml": "<PathOfBuilding/>", "author_raw": {"CombinedDPS": 1.0}, "author_lane": {}, "choices": {}, "tree_version": "3_29"}
    write_author_memo(path, old)
    assert read_author_memo(path, tree_version="3_29") == old, "with no rails asked for, the memo is read as it is"
    assert read_author_memo(path, tree_version="3_29", gem_rails="18/0/0") is None, "written before the normalization: not replayed"

    write_author_memo(path, {**old, "gem_rails": "20/20/20"})
    assert read_author_memo(path, tree_version="3_29", gem_rails="18/0/0") is None

    current = {**old, "gem_rails": "18/0/0"}
    write_author_memo(path, current)
    assert read_author_memo(path, tree_version="3_29", gem_rails="18/0/0") == current
    assert read_author_memo(path, tree_version="3_28", gem_rails="18/0/0") is None, "both stamps must match"


def test_the_floors_of_a_reference_carry_the_authors_life_and_total_ehp_in_full() -> None:
    """D59 and D61: a reference is rebuilt under the author's own defence, Life and TotalEHP at
    100% of theirs with no slack, TotalEHP read under the lane our build is judged under."""

    rails = Rails.load()
    objective = rails.objective()
    author = next(r for r in json.loads((FIXTURES / "stats.json").read_text(encoding="utf-8")) if r["slug"] == "stormbrand")
    raw = {**author, "EffectiveMovementSpeedMod": 1.24, "PhysicalMaximumHitTaken": 5000.0}
    lane = {**raw, "TotalEHP": raw["TotalEHP"] * 1.08, "FireResistMax": 80, "ColdResistMax": 76, "LightningResistMax": 75}  # our lane turns on what the author left untyped

    floors = author_floors(objective, raw, lane, rails)
    assert floors["TotalEHP"] == lane["TotalEHP"], "the floor is the author's EHP under our lane, not the rails'"
    assert "TotalEHP" not in objective.floors, "the rails floor the maximum hit taken, not EHP (D53)"
    assert floors["Life"] == raw["Life"] == 4156  # no slack on either (D59)
    assert floors["PhysicalMaximumHitTaken"] == 5000.0 * 0.95 and floors["EffectiveMovementSpeedMod"] == 1.2 * 0.97
    assert not {"FireResist", "ColdResist", "LightningResist"} & set(floors)
    assert all(relation in objective.relations for relation in ELEMENTAL_RESIST_RELATIONS)
    assert objective.floors["Life"] != floors["Life"]


def test_the_movement_floor_is_the_authors_movement_under_our_lane() -> None:
    """impale_cyclone: 1.35 with the author's own config, 1.0665 under ours (Cyclone); the floor is
    97% of the lane value, not of 1.2, or the author fails his own floor."""

    rails = Rails.load()
    objective = rails.objective()
    author = next(r for r in json.loads((FIXTURES / "stats.json").read_text(encoding="utf-8")) if r["slug"] == "stormbrand")
    raw = {**author, "EffectiveMovementSpeedMod": 1.35, "PhysicalMaximumHitTaken": 5000.0}
    lane = {**raw, "EffectiveMovementSpeedMod": 1.0665}

    assert author_floors(objective, raw, lane, rails)["EffectiveMovementSpeedMod"] == pytest.approx(1.0665 * 0.97)
    assert author_floors(objective, raw, {**raw}, rails)["EffectiveMovementSpeedMod"] == pytest.approx(1.2 * 0.97)


def test_the_authors_gems_are_written_onto_the_rails_before_their_row_is_measured() -> None:
    """D23 / CLAUDE.md: never compare a generated build with an author's on unequal gem levels. Our
    build is socketed at the rails' 18/0; Zizaran's early loadouts carry 20/20, so the author's own
    XML is rewritten before anything is read off it. The main skill takes the rails' own
    `main_skill_quality`, which is the quality `set_skills` gives ours."""

    from xml.etree import ElementTree as ET

    rails = Rails.load()
    xml = ('<PathOfBuilding><Build level="90" className="Templar" ascendClassName="Hierophant" mainSocketGroup="1"/>'
           '<Skills activeSkillSet="1"><SkillSet id="1">'
           '<Skill slot="Body Armour" mainActiveSkill="1" enabled="true">'
           '<Gem nameSpec="Archmage" level="20" quality="20"/><Gem nameSpec="Shock Nova" level="21" quality="23"/></Skill>'
           '<Skill slot="Boots" mainActiveSkill="1" enabled="true"><Gem nameSpec="Empower" level="4" quality="0"/></Skill>'
           '</SkillSet></Skills><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>')

    out, report = normalize_author_gems(xml, rails)
    gems = {g.get("nameSpec"): (g.get("level"), g.get("quality")) for g in ET.fromstring(out).iter("Gem")}
    assert gems == {"Archmage": ("18", "0"), "Shock Nova": ("18", str(rails.gems.main_quality)), "Empower": ("18", "0")}
    assert report["changed"] and report["gems"] == 3 and report["of"] == 3
    assert report["before"] == {"level": 20.0, "quality": 20.0}, "the author's own medians, kept for the results row"
    assert report["line"].startswith("author gems normalized to the rails: level 20/20 -> 18/0 on 3 gems")
    # a level above a gem's own range is PoB's to clamp (CalcTools.validateGemLevel), ours to write
    assert gems["Empower"][0] == "18"

    assert not normalize_author_gems(out, rails)[1]["changed"], "running it twice changes nothing"
    assert normalize_author_gems(out, rails)[1]["before"] == {"level": 18.0, "quality": 0.0}


def test_sets_name_fixtures_that_exist_and_partition_them() -> None:
    tuadh = {p.name[: -len(".pob.txt")] for p in FIXTURES.glob("*.pob.txt")}
    for name, slugs in SETS.items():
        for slug in slugs:
            assert fixture_path(slug).is_file(), (name, slug)  # in one of the fixture folders
        assert len(slugs) == len(set(slugs)), name
    assert not set(SETS["core14"]) & set(SETS["new18"])
    assert set(SETS["core14"]) | set(SETS["new18"]) == tuadh
    assert set(SETS["smoke"]) <= tuadh and len(SETS["smoke"]) == 6
    # the second reference set is every extracted Zizaran league starter, in its own folder per league,
    # minus the re-publications an author served unchanged under a later league (ZIZ_REPUBLISHED)
    assert not set(SETS["ziz"]) & tuadh
    assert set(SETS["ziz"]) | set(ZIZ_REPUBLISHED) == set(fixture_slugs()) - tuadh, "--set ziz plus the trimmed twins must cover every extracted early loadout"
    assert not set(SETS["ziz"]) & set(ZIZ_REPUBLISHED)
    assert all(s.startswith("z3") for s in SETS["ziz"])
    assert len(SETS["ziz"]) == 26


def test_a_republished_starter_is_counted_once_at_its_newest_league() -> None:
    """An author re-publishes a guide unchanged and the same build then appears under several
    leagues (champion_explosive_arrow in 327, 328 and 329). Counting each copy would weight that
    build 3x in the medians, so only the newest is a reference -- and "the same build" is PoB's
    verdict, not a guess: the two read identically in the folders' own stats.json. The files stay
    in place, so a trimmed one is still a fixture `fixture_path` finds."""

    def stats(reference: str) -> dict:
        league, slug = reference[1:4], reference[5:]
        rows = json.loads((FIXTURES.parent / f"zizaran_{league}" / "early" / "stats.json").read_text(encoding="utf-8"))
        return next(r for r in rows if r["slug"] == slug)

    for dropped, kept in ZIZ_REPUBLISHED.items():
        assert kept in SETS["ziz"] and dropped not in SETS["ziz"]
        assert dropped[5:] == kept[5:], "a twin is the same build, so the same slug"
        assert dropped[1:4] < kept[1:4], "the newest league's copy is the one kept"
        assert fixture_path(dropped).is_file(), "the fixture file itself is never removed"
        old, new = stats(dropped), stats(kept)
        for key in ("level", "Life", "TotalEHP", "CombinedDPS", "FullDPS"):
            assert old[key] == new[key], (dropped, kept, key, old[key], new[key])
        assert old["tree"]["allocated_nodes"] == new["tree"]["allocated_nodes"]

    # the builds that are NOT twins must stay: three of the four slugs also exist in a league PoB
    # reads differently (z325 Explosive Arrow, z329 Earthquake, z327 Boneshatter)
    for reference in ("z325_champion_explosive_arrow", "z329_gladiator_earthquake", "z327_juggernaut_boneshatter"):
        assert reference in SETS["ziz"]


def test_a_slug_is_looked_up_in_the_tuadh_folder_first() -> None:
    """The search order is tuadh_329, then zizaran_<league>/early newest league first; a bare run
    (no slugs, no --set) is still only the Tuadh references, so an existing call cannot silently
    grow a campaign."""

    assert FIXTURE_DIRS[0] == FIXTURES
    assert [d.parent.name for d in FIXTURE_DIRS[1:]] == sorted((d.parent.name for d in FIXTURE_DIRS[1:]), reverse=True)
    assert fixture_path("stormbrand").parent == FIXTURES
    assert set(fixture_slugs(FIXTURES)) == {p.name[: -len(".pob.txt")] for p in FIXTURES.glob("*.pob.txt")}
    assert set(fixture_slugs()) == set(fixture_slugs(FIXTURES)) | set(SETS["ziz"]) | set(ZIZ_REPUBLISHED)
    with pytest.raises(FileNotFoundError):
        fixture_path("no_such_reference")


def test_a_zizaran_reference_carries_its_league_because_the_slugs_repeat() -> None:
    """champion_explosive_arrow is a build of four leagues: the reference name says which one, and
    a bare slug takes the newest league that has it."""

    path = fixture_path("z327_juggernaut_boneshatter")
    assert path == FIXTURES.parent / "zizaran_327" / "early" / "juggernaut_boneshatter.pob.txt" and path.is_file()
    assert fixture_alias(path) == "z327_juggernaut_boneshatter"
    assert fixture_alias(FIXTURES / "stormbrand.pob.txt") == "stormbrand"
    assert fixture_path("juggernaut_boneshatter") == FIXTURES.parent / "zizaran_329" / "early" / "juggernaut_boneshatter.pob.txt"
    # four leagues carry the slug, two of them a build PoB reads differently: the rest are re-publications
    assert len([p for p in FIXTURES.parent.glob("zizaran_*/early/champion_explosive_arrow.pob.txt")]) == 4
    assert [s for s in SETS["ziz"] if s.endswith("_champion_explosive_arrow")] == ["z325_champion_explosive_arrow", "z329_champion_explosive_arrow"]


def test_a_stage_that_loses_more_than_10_percent_for_nothing_is_flagged() -> None:
    stages = [
        {"name": "tree greedy", "value": 100_000, "violation": 0.0},
        {"name": "gear pass 2 (with tree)", "value": 85_000, "violation": 0.0},  # -15%, same violation: flagged
        {"name": "tree rebuilt on gear", "value": 70_000, "violation": 0.0},  # -18%, violation unchanged: flagged
        {"name": "loop pass 1", "value": 60_000, "violation": 0.0},
    ]
    assert lost_stages(stages) == [
        "gear pass 2 (with tree) 100,000 -> 85,000 (-15%)",
        "tree rebuilt on gear 85,000 -> 70,000 (-18%)",
        "loop pass 1 70,000 -> 60,000 (-14%)",
    ]


def test_a_loss_that_lowers_the_violation_or_stays_under_10_percent_is_not_flagged() -> None:
    stages = [
        {"name": "tree greedy", "value": 100_000, "violation": 0.4},
        {"name": "tree refine", "value": 80_000, "violation": 0.1},  # a repair: DPS paid for a floor
        {"name": "loop pass 1", "value": 73_000, "violation": 0.1},  # -8.75%: under the threshold
    ]
    assert lost_stages(stages) == []
