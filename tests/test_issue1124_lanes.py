"""#1124 unit 2 of 5: the lane writers put the red-line marks block into each lane (kind A, D113).

Rules checked PoB-free with a fake PoB: with no marks (empty store) or no held marked line the writers make exactly
the PoB calls they made before; the block `junkroan: red-line marks` is written into the Baseline set (boss lane lines)
and the Conditional set (optimistic lane lines) and nowhere else; a record with both lanes empty writes nothing; the
block is written again after every `set_config` and replaced, never stacked; a `formula` record takes its value from
the build's own `stats`; the trace counter sees `mark:<line>` generated and evaluated.

Expected values are literals written from the fixture (`tests/fixtures/red_line_marks_fixture.json`) and the spec.
One test marked `pob` writes the block into a real session and reads CombinedDPS before and after.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer import judging as judging_module
from junkroan.optimizer.judging import write_lanes, write_lanes_preserving_numbers
from junkroan.optimizer.ramp_inputs import MARKS_TITLE, apply_mark_blocks
from junkroan.optimizer.trace import TRACE, mark_class
from junkroan.pob.session import PobSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "red_line_marks_fixture.json"
ENV = "JUNKROAN_RED_LINE_MARKS"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

SMOKE = "10% chance to create a Smoke Cloud on Kill"
MANA = "10% chance to Recover 10% of Mana when you use a Skill"
GOBLINEDGE = "+3 seconds to Duration of Frenzy and Power Charges on Culling Strike"
FRENZY = "5% chance to gain a Frenzy Charge on Kill"
FLASK = "Removes 10% of Life Recovered from Mana when used"
DUELIST = "Can Allocate Passives from the Duelist's starting point"
ARCANE_LINE = "10% increased Effect of Arcane Surge on you per\n200 Mana spent Recently, up to 50%"
ARCANE_BLOCK_LINE = "20% increased Effect of Arcane Surge on you"  # ManaSpentRecently 400 / 200 * 10

BASE_XML = ('<PathOfBuilding><Config>'
            '<ConfigSet id="1" title="Baseline"><Input name="enemyLevel" number="84"/></ConfigSet>'
            '<ConfigSet id="2" title="Conditional"><Input name="enemyLevel" number="84"/></ConfigSet>'
            '</Config></PathOfBuilding>')

# what the writers did before this unit, with a fake that has all four reads: the literal of rule 5
BASELINE_WRITE_LANES = ["config_inputs", "set_config", "export_xml", "export_xml"]
BASELINE_PRESERVING = ["read_state", "set_config", "export_xml", "export_xml"]


def _state(*, lines: tuple[str, ...] = (), nodes: tuple[int, ...] = ()) -> dict:
    slots = {"Weapon 1": {"item": {"implicit_affixes": [], "explicit_affixes": list(lines)}}} if lines else {}
    return {"items_state": {"slots": slots}, "tree_state": {"user_allocated_node_ids": list(nodes), "mastery_effect_ids": []},
            "config_state": {"bandit": "None", "pantheon_major": "None", "pantheon_minor": "None"}}


class FakePob:
    """Every method a lane write can call; `set_config` rebuilds the config sets and drops every custom block, as PoB does."""

    def __init__(self, state: dict | None = None, outputs: dict | None = None) -> None:
        self.xml, self.state, self.outputs = BASE_XML, state or _state(), outputs or {"ManaSpentRecently": 400}
        self.calls: list[str] = []
        self.loaded: list[str] = []
        self.stats_keys: list = []

    def config_inputs(self) -> dict:
        self.calls.append("config_inputs")
        return {}

    def read_state(self) -> dict:
        self.calls.append("read_state")
        return self.state

    def set_config(self, **kwargs) -> None:
        self.calls.append("set_config")
        self.xml = BASE_XML

    def export_xml(self) -> str:
        self.calls.append("export_xml")
        return self.xml

    def load_xml(self, xml: str) -> None:
        self.calls.append("load_xml")
        self.loaded.append(xml)
        self.xml = xml

    def stats(self, keys=None) -> dict:
        self.calls.append("stats")
        self.stats_keys.append(tuple(keys) if keys else keys)
        return {key: self.outputs[key] for key in (keys or self.outputs) if key in self.outputs}


def _skeleton() -> SimpleNamespace:
    return SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})


def _lanes(custom_mods: tuple = ()) -> SimpleNamespace:
    lane = lambda: SimpleNamespace(inputs={}, reasons={}, proof_lines={})  # noqa: E731
    return SimpleNamespace(conservative=lane(), optimistic=lane(), custom_mods=custom_mods, ailment_stack_caps={})


def _marks_block(xml: str) -> dict[str, list[str]]:
    """Config set title -> the body lines of its `junkroan: red-line marks` blocks (one entry per block)."""

    out: dict[str, list[str]] = {}
    for config_set in ET.fromstring(xml).find("Config").findall("ConfigSet"):
        for block in config_set.findall("CustomModifierBlock"):
            if block.get("title") == MARKS_TITLE:
                out.setdefault(config_set.get("title"), []).append(block.text or "")
    return out


def _lines(body: str) -> list[str]:
    return [line for line in body.split("\n") if line and not line.startswith("#")]


@pytest.fixture
def fixture_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, str(FIXTURE))


@pytest.fixture
def no_marks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV, str(tmp_path / "absent.json"))


@pytest.fixture(autouse=True)
def _fresh_trace() -> None:
    TRACE.reset()


def _counts(line: str) -> dict[str, int]:
    for classes in TRACE.considered().values():
        if mark_class(line) in classes:
            return classes[mark_class(line)]
    return {}


HELD = _state(lines=(GOBLINEDGE, MANA, FRENZY, FLASK, DUELIST), nodes=(13790, 51108))


# -- rule 5: the same PoB calls as before ----------------------------------------------------------------------------


def test_empty_marks_write_lanes_makes_exactly_the_old_calls(no_marks) -> None:
    pob = FakePob(HELD)
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert pob.calls == BASELINE_WRITE_LANES
    assert TRACE.considered() == {}


def test_empty_marks_preserving_writer_makes_exactly_the_old_calls(no_marks) -> None:
    pob = FakePob(HELD)
    write_lanes_preserving_numbers(pob, _lanes())
    assert pob.calls == BASELINE_PRESERVING


def test_marks_but_nothing_held_loads_nothing_and_preserving_reuses_its_state_read(fixture_marks) -> None:
    pob = FakePob(_state(lines=("+10 to Strength",)))
    write_lanes_preserving_numbers(pob, _lanes())
    assert pob.calls == BASELINE_PRESERVING and pob.loaded == []
    pob = FakePob(_state(lines=("+10 to Strength",)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert pob.calls == BASELINE_WRITE_LANES + ["read_state"] and pob.loaded == []


def test_a_held_zero_record_alone_writes_no_block(fixture_marks) -> None:
    pob = FakePob(_state(lines=(DUELIST,)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert pob.loaded == [] and "red-line" not in pob.xml


# -- the block lands on the right lane only --------------------------------------------------------------------------


def test_each_lane_gets_its_own_lines_only(fixture_marks) -> None:
    pob = FakePob(HELD)
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    blocks = _marks_block(pob.xml)
    assert set(blocks) == {"Baseline", "Conditional"} and all(len(v) == 1 for v in blocks.values())
    assert _lines(blocks["Baseline"][0]) == [MANA, FLASK]  # boss_lane lines, sorted by held line text
    optimistic = _lines(blocks["Conditional"][0])
    assert sorted(optimistic) == sorted([SMOKE, MANA, GOBLINEDGE, FRENZY, FLASK, ARCANE_BLOCK_LINE])
    assert DUELIST not in blocks["Baseline"][0] + blocks["Conditional"][0]
    for forbidden in (SMOKE, GOBLINEDGE, FRENZY, ARCANE_BLOCK_LINE):
        assert forbidden not in _lines(blocks["Baseline"][0])


def test_a_line_only_the_optimistic_lane_marks_leaves_baseline_without_a_block(fixture_marks) -> None:
    pob = FakePob(_state(lines=(FRENZY,)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    blocks = _marks_block(pob.xml)
    assert set(blocks) == {"Conditional"} and _lines(blocks["Conditional"][0]) == [FRENZY]


def test_a_comment_names_each_source(fixture_marks) -> None:
    pob = FakePob(_state(lines=(FRENZY,)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert f"# red line: {FRENZY} | source: Weapon 1" in _marks_block(pob.xml)["Conditional"][0]


def test_the_held_lines_come_from_items_and_allocated_nodes(fixture_marks) -> None:
    pob = FakePob(_state(nodes=(13790,)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    block = _marks_block(pob.xml)["Conditional"][0]
    assert _lines(block) == [SMOKE] and "source: Smoking Remains" in block


def test_the_preserving_writer_writes_the_same_block_from_its_own_state_read(fixture_marks) -> None:
    pob = FakePob(HELD)
    write_lanes_preserving_numbers(pob, _lanes())
    blocks = _marks_block(pob.xml)
    assert _lines(blocks["Baseline"][0]) == [MANA, FLASK]
    assert pob.calls.count("read_state") == 1


def test_the_blocks_of_the_ramp_stay_next_to_the_marks_block(fixture_marks) -> None:
    pob = FakePob(HELD)
    write_lanes(pob, _skeleton(), _lanes(custom_mods=(("100% more Melee Physical Damage", "junkroan: pride"),)), log=lambda _m: None)
    titles = [b.get("title") for b in ET.fromstring(pob.xml).find("Config").findall("ConfigSet")[0].findall("CustomModifierBlock")]
    assert sorted(titles) == sorted(["junkroan: pride", MARKS_TITLE])


# -- re-applied after set_config, replaced never stacked -------------------------------------------------------------


def test_the_block_is_written_again_after_the_next_set_config(fixture_marks) -> None:
    pob = FakePob(HELD)
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    first = _marks_block(pob.xml)
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)  # set_config dropped the block; the writer wrote it back
    assert _marks_block(pob.xml) == first and all(len(v) == 1 for v in first.values())


def test_a_stale_marks_block_is_replaced_not_stacked() -> None:
    pob = FakePob()
    apply_mark_blocks(pob, {"boss": ["+1 to Strength"], "optimistic": ["+2 to Strength"]})
    apply_mark_blocks(pob, {"boss": ["+3 to Strength"], "optimistic": []})
    blocks = _marks_block(pob.xml)
    assert blocks == {"Baseline": ["+3 to Strength"]}  # the Conditional block went with the lane's lines


def test_apply_mark_blocks_with_no_lines_makes_no_call() -> None:
    pob = FakePob()
    apply_mark_blocks(pob, {"boss": [], "optimistic": []})
    assert pob.calls == []


def test_a_later_apply_custom_mods_strips_the_marks_which_is_why_the_writers_write_them_last(fixture_marks) -> None:
    from junkroan.optimizer.ramp_inputs import apply_custom_mods

    pob = FakePob()
    apply_mark_blocks(pob, {"boss": ["+3 to Strength"], "optimistic": ["+4 to Strength"]})
    apply_custom_mods(pob, (), replace_ailment_stacks=True)
    assert _marks_block(pob.xml) == {}


# -- the formula -----------------------------------------------------------------------------------------------------


def test_a_formula_record_takes_its_value_from_the_builds_own_stats(fixture_marks) -> None:
    pob = FakePob(_state(nodes=(51108,)), outputs={"ManaSpentRecently": 600})
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert pob.stats_keys == [("ManaSpentRecently",)]
    assert _lines(_marks_block(pob.xml)["Conditional"][0]) == ["30% increased Effect of Arcane Surge on you"]


def test_no_formula_held_no_stats_call(fixture_marks) -> None:
    pob = FakePob(_state(lines=(FRENZY,)))
    write_lanes(pob, _skeleton(), _lanes(), log=lambda _m: None)
    assert "stats" not in pob.calls


# -- the trace counter -----------------------------------------------------------------------------------------------


def test_trace_counts_a_written_mark_generated_and_evaluated_per_lane(fixture_marks) -> None:
    write_lanes(FakePob(HELD), _skeleton(), _lanes(), log=lambda _m: None)
    assert mark_class(SMOKE) == f"mark:{SMOKE}"
    assert _counts(SMOKE) == {"generated": 1, "evaluated": 1}  # optimistic lane only
    assert _counts(MANA) == {"generated": 2, "evaluated": 2}  # both lanes
    assert _counts(FRENZY) == {"generated": 1, "evaluated": 1}


def test_trace_sees_a_held_zero_record_as_zero_and_an_unheld_one_not_at_all(fixture_marks) -> None:
    write_lanes(FakePob(_state(lines=(DUELIST, FRENZY))), _skeleton(), _lanes(), log=lambda _m: None)
    assert _counts(DUELIST) == {"generated": 0, "evaluated": 0}
    assert _counts(ARCANE_LINE) == {}  # not held in this build: no class at all


def test_the_formula_class_is_the_whitespace_collapsed_line(fixture_marks) -> None:
    write_lanes(FakePob(_state(nodes=(51108,))), _skeleton(), _lanes(), log=lambda _m: None)
    assert mark_class(ARCANE_LINE) == "mark:10% increased Effect of Arcane Surge on you per 200 Mana spent Recently, up to 50%"
    assert _counts(ARCANE_LINE) == {"generated": 1, "evaluated": 1}


def test_empty_marks_count_nothing(no_marks) -> None:
    write_lanes_preserving_numbers(FakePob(HELD), _lanes())
    assert not any(c.startswith("mark:") for classes in TRACE.considered().values() for c in classes)


# -- the real PoB ----------------------------------------------------------------------------------------------------


@needs_pob
@pytest.mark.pob
def test_the_block_reaches_pob_and_the_boss_lane_number_moves(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    build = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "arc_archmage.pob.txt"
    held_line = "+1 to Level of all Spell Skill Gems"
    record = {"line": held_line, "surfaces": ["gear_affix"], "sources": ["probe"], "group": "other", "kind": "custom_mod",
              "boss_lane": ["100% increased Damage"], "optimistic_lane": [], "zero_reason": "", "why": "probe", "partial_part": "all"}
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps(json.loads(FIXTURE.read_text(encoding="utf-8")) + [record]), encoding="utf-8")
    monkeypatch.setenv(ENV, str(marks))
    with PobSession(run_id="test-1124-lanes", artifacts_root=tmp_path) as pob:
        pob.load_import_code(build.read_text(encoding="utf-8").strip())
        pob.set_config(bandit="None", pantheon_major="None", pantheon_minor="None", enemy_state={"is_boss": "Pinnacle"},
                       inputs={}, conditional={"inputs": {}}, preserve="numeric")  # both config sets, as a lane write leaves them
        before = pob.stats(("CombinedDPS",))["CombinedDPS"]
        written = judging_module.write_marks(pob, _state(lines=(held_line, FLASK)))
        after = pob.stats(("CombinedDPS",))["CombinedDPS"]
        bodies = _marks_block(pob.export_xml())
    print(f"CombinedDPS before {before:,.1f} after {after:,.1f}")
    assert [x for x in written["boss"] if not x.startswith("#")] == _lines(bodies["Baseline"][0]) == ["100% increased Damage", FLASK]
    assert _lines(bodies["Conditional"][0]) == [FLASK]  # the probe record marks the boss lane only; the flask mod both
    assert after > before
