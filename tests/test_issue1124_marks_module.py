"""#1124 unit 1 of 5: the red-line marks module, PoB-free rail tests (kind A, D113).

The module `junkroan.optimizer.red_line_marks` reads `mechanics/red_line_marks.json` (or the fixture, or the
env override) and turns the red lines an item or node holds into the PoB custom-modifier lines of one lane. Rules
checked here, all with no PobSession: a missing file is an empty marks object (rule 4/5: nothing changes); the env
override is read; `is_marked` is per lane; a zero record is unmarked on both lanes; the block carries the lane's own
lines, one comment per source, a `formula` placeholder filled from outputs; an empty-lane record changes nothing;
the output is deterministic; a line held by two sources is written once.

Expected values are literals written from the fixture and from the spec, never recomputed by the module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from junkroan.optimizer.red_line_marks import RedLineMarks, load_marks

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "red_line_marks_fixture.json"
ENV = "JUNKROAN_RED_LINE_MARKS"

SMOKE = "10% chance to create a Smoke Cloud on Kill"
MANA = "10% chance to Recover 10% of Mana when you use a Skill"
DUELIST = "Can Allocate Passives from the Duelist's starting point"
ARCANE = "10% increased Effect of Arcane Surge on you per\n200 Mana spent Recently, up to 50%"
FRENZY = "5% chance to gain a Frenzy Charge on Kill"


@pytest.fixture
def fixture_marks(monkeypatch: pytest.MonkeyPatch) -> RedLineMarks:
    monkeypatch.delenv(ENV, raising=False)
    return load_marks(FIXTURE)


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _record(line: str, **over) -> dict:
    base = {
        "line": line,
        "surfaces": ["notable"],
        "sources": ["1"],
        "group": "on_kill",
        "kind": "custom_mod",
        "boss_lane": [],
        "optimistic_lane": [],
        "zero_reason": "",
        "why": "fixture",
        "partial_part": "fixture",
    }
    base.update(over)
    return base


# --- missing file, env override ------------------------------------------------------------------

def test_missing_file_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    marks = load_marks(tmp_path / "absent.json")
    assert marks.records == ()
    assert marks.has_record(SMOKE) is False
    assert marks.is_marked(SMOKE, "optimistic") is False
    assert marks.block_for([(SMOKE, "13790")], "optimistic") == []
    assert marks.block_for([(SMOKE, "13790")], "boss") == []


def test_env_override_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, str(FIXTURE))
    marks = load_marks()
    assert len(marks.records) >= 6
    assert marks.has_record(SMOKE) is True


def test_env_pointing_at_missing_file_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, str(tmp_path / "nowhere.json"))
    marks = load_marks()
    assert marks.records == ()
    assert marks.block_for([(MANA, "2841")], "boss") == []


def test_cache_follows_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    path = _write(tmp_path / "marks.json", [_record(SMOKE, optimistic_lane=[SMOKE])])
    first = load_marks(path)
    assert load_marks(path) is first
    _write(path, [_record(MANA, optimistic_lane=[MANA])])
    os.utime(path, (path.stat().st_atime + 10, path.stat().st_mtime + 10))
    second = load_marks(path)
    assert second.has_record(MANA) is True
    assert second.has_record(SMOKE) is False


# --- lookup and lanes -----------------------------------------------------------------------------

def test_record_is_exact_text_with_surrounding_whitespace_only(fixture_marks: RedLineMarks) -> None:
    assert fixture_marks.record(f"  {SMOKE}\n")["sources"] == ["13790"]
    assert fixture_marks.record("10% chance to create a Smoke Cloud") is None
    assert fixture_marks.record(SMOKE.lower()) is None


def test_is_marked_per_lane(fixture_marks: RedLineMarks) -> None:
    # optimistic lane only (a kill chance)
    assert fixture_marks.is_marked(SMOKE, "optimistic") is True
    assert fixture_marks.is_marked(SMOKE, "boss") is False
    # both lanes (a Mana recovery trigger)
    assert fixture_marks.is_marked(MANA, "boss") is True
    assert fixture_marks.is_marked(MANA, "optimistic") is True
    # unknown line
    assert fixture_marks.is_marked("Not a red line", "boss") is False
    with pytest.raises(ValueError):
        fixture_marks.is_marked(SMOKE, "conservative")


def test_zero_record_is_unmarked_on_both_lanes(fixture_marks: RedLineMarks) -> None:
    assert fixture_marks.has_record(DUELIST) is True
    assert fixture_marks.is_marked(DUELIST, "boss") is False
    assert fixture_marks.is_marked(DUELIST, "optimistic") is False
    assert fixture_marks.block_for([(DUELIST, "63357")], "boss") == []
    assert fixture_marks.block_for([(DUELIST, "63357")], "optimistic") == []


# --- block content --------------------------------------------------------------------------------

def test_block_content_per_lane(fixture_marks: RedLineMarks) -> None:
    held = [(SMOKE, "13790"), (MANA, "2841"), (DUELIST, "63357")]
    assert fixture_marks.block_for(held, "boss") == [
        "# red line: 10% chance to Recover 10% of Mana when you use a Skill | source: 2841",
        "10% chance to Recover 10% of Mana when you use a Skill",
    ]
    assert fixture_marks.block_for(held, "optimistic") == [
        "# red line: 10% chance to Recover 10% of Mana when you use a Skill | source: 2841",
        "10% chance to Recover 10% of Mana when you use a Skill",
        "# red line: 10% chance to create a Smoke Cloud on Kill | source: 13790",
        "10% chance to create a Smoke Cloud on Kill",
    ]


def test_formula_placeholder_is_filled_from_outputs(fixture_marks: RedLineMarks) -> None:
    # ManaSpentRecently / 200 * 10 with ManaSpentRecently = 400 is 20
    block = fixture_marks.block_for([(ARCANE, "51108")], "optimistic", {"ManaSpentRecently": 400})
    assert block == [
        "# red line: 10% increased Effect of Arcane Surge on you per 200 Mana spent Recently, up to 50% | source: 51108",
        "20% increased Effect of Arcane Surge on you",
    ]
    assert fixture_marks.block_for([(ARCANE, "51108")], "boss", {"ManaSpentRecently": 400}) == []


def test_formula_missing_name_raises_keyerror(fixture_marks: RedLineMarks) -> None:
    with pytest.raises(KeyError, match="ManaSpentRecently"):
        fixture_marks.block_for([(ARCANE, "51108")], "optimistic", {"Life": 5000})
    with pytest.raises(KeyError, match="ManaSpentRecently"):
        fixture_marks.block_for([(ARCANE, "51108")], "optimistic", None)


def test_bad_formula_and_stray_placeholder_fail_at_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    unsafe = _write(tmp_path / "unsafe.json", [
        _record(ARCANE, optimistic_lane=["{formula}% x"], formula="__import__('os').getpid()"),
    ])
    with pytest.raises(ValueError):
        load_marks(unsafe)
    stray = _write(tmp_path / "stray.json", [_record(ARCANE, optimistic_lane=["{formula}% x"])])
    with pytest.raises(ValueError):
        load_marks(stray)


def test_empty_lane_record_changes_nothing(fixture_marks: RedLineMarks) -> None:
    # FRENZY is optimistic-only: the boss lane gets nothing from it, and a held set with no marked line gives []
    assert fixture_marks.block_for([(FRENZY, "ChanceToGainFrenzyChargeOnKillUber1")], "boss") == []
    assert fixture_marks.block_for([(DUELIST, "63357")], "boss") == []
    assert fixture_marks.block_for([], "optimistic") == []
    assert fixture_marks.block_for([], "boss") == []


# --- determinism and sharing ----------------------------------------------------------------------

def test_output_is_deterministic(fixture_marks: RedLineMarks) -> None:
    held = [(SMOKE, "13790"), (MANA, "2841"), (FRENZY, "ChanceToGainFrenzyChargeOnKillUber1")]
    first = fixture_marks.block_for(held, "optimistic")
    assert fixture_marks.block_for(list(reversed(held)), "optimistic") == first
    assert fixture_marks.block_for(held, "optimistic") == first


def test_line_held_by_two_sources_is_written_once(fixture_marks: RedLineMarks) -> None:
    held = [(SMOKE, "99999"), (SMOKE, "13790")]
    assert fixture_marks.block_for(held, "optimistic") == [
        "# red line: 10% chance to create a Smoke Cloud on Kill | source: 13790",
        "# red line: 10% chance to create a Smoke Cloud on Kill | source: 99999",
        "10% chance to create a Smoke Cloud on Kill",
    ]


def test_comment_lines_never_contain_a_newline(fixture_marks: RedLineMarks) -> None:
    block = fixture_marks.block_for([(ARCANE, "51108")], "optimistic", {"ManaSpentRecently": 400})
    assert all("\n" not in entry for entry in block)
    assert block[0].startswith("# ")
