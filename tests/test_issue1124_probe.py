"""#1124 unit 5a: the counter probe's pure parts and the lane wiring (PoB-free).

The probe (`scripts/probe_1124_marks.py`) opens PoB only in its stand runs; everything it decides from their
numbers (which lines to mark, the counters of rows 2, 3 and 5) is plain data, tested here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import probe_1124_marks as probe  # noqa: E402

from junkroan.optimizer.ramp_inputs import BASELINE_SET, _MARK_LANE_SETS  # noqa: E402
from junkroan.optimizer.red_line_marks import RedLineMarks, load_marks  # noqa: E402
from junkroan.optimizer.trace import TRACE, classify  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402


def test_records_are_a_valid_marks_store_with_the_probe_value_on_both_lanes():
    records = probe.make_records(["Red node line", "Red affix line"], zero=["Red zero line"])
    marks = RedLineMarks(records)
    assert len(marks) == 3
    assert marks.is_marked("Red node line", "boss") and marks.is_marked("Red node line", "optimistic")
    assert marks.record("Red node line")["boss_lane"] == [probe.PROBE_MARK_LINE]
    zero = marks.record("Red zero line")
    assert zero["boss_lane"] == [] and zero["optimistic_lane"] == [] and zero["zero_reason"]
    assert not marks.is_marked("Red zero line", "boss")


def test_records_drop_duplicates_and_a_zero_that_is_also_marked():
    records = probe.make_records(["A", "A", "B"], zero=["B", "C"])
    assert [r["line"] for r in records] == ["A", "B", "C"]
    assert [bool(r["boss_lane"]) for r in records] == [True, True, False]


def test_red_lines_are_the_ones_pob_cannot_parse():
    rows = [
        {"line": "10% increased Damage", "ok": True, "unsupported": False},
        {"line": "10% chance to create a Smoke Cloud on Kill", "ok": True, "unsupported": True, "extra": "x"},
        {"line": "Nothing parses here", "ok": False, "unsupported": True},
        {"line": "10% chance to create a Smoke Cloud on Kill", "ok": True, "unsupported": True},
    ]
    assert probe.red_lines(rows) == ["10% chance to create a Smoke Cloud on Kill", "Nothing parses here"]


def test_node_stat_lines_are_looked_up_by_their_newline_parts():
    assert probe.stat_parts(["one\ntwo", "three", " "]) == ["one", "two", "three"]


def test_counter_sums_over_moves():
    considered = {
        "refine": {"mark:X": {"generated": 3, "evaluated": 2}, "other": {"generated": 9, "evaluated": 9}},
        "gear": {"mark:X": {"generated": 1, "evaluated": 1}},
    }
    assert probe.counter(considered, "mark:X") == (4, 3)
    assert probe.counter(considered, "mark:missing") == (0, 0)


def test_item_classes_name_marked_affix_unique_and_the_unmarked_control():
    sets = probe.ItemLines(affix={"+5 to Stuff"}, unique={"Unique red line"}, control={"Unrecorded red line"})
    rare = "Rarity: RARE\nBrimstone\nCoral Ring\nImplicits: 0\n{range:0.5}+5 to Stuff\n+10 to Life\n"
    assert probe.item_classes(rare, sets) == {"probe-affix:+5 to Stuff"}
    unique = "Rarity: UNIQUE\nSomething, Ring\nCoral Ring\n{variant:1}Unique red line\n"
    assert probe.item_classes(unique, sets) == {"probe-unique:Unique red line"}
    control = "Rarity: RARE\nX\nCoral Ring\n{crafted}Unrecorded red line\n"
    assert probe.item_classes(control, sets) == {"probe-norecord:Unrecorded red line"}
    assert probe.item_classes("Rarity: RARE\nX\nCoral Ring\n+10 to Life\n", sets) == set()


def test_item_class_function_feeds_the_trace_for_item_trials():
    sets = probe.ItemLines(affix={"+5 to Stuff"}, unique=set(), control={"Unrecorded red line"})
    fn = probe.register_item_classes(sets)
    try:
        trial = {"item": {"slot": "Ring 1", "raw": "Rarity: RARE\nB\nCoral Ring\n+5 to Stuff\nUnrecorded red line\n"}}
        got = classify(trial)
        assert {"probe-affix:+5 to Stuff", "probe-norecord:Unrecorded red line"} <= got
        TRACE.reset()
        TRACE.count_trial(trial)
        assert probe.counter(TRACE.considered(), "probe-affix:+5 to Stuff") == (0, 1)
    finally:
        probe.unregister_item_classes(fn)
        TRACE.reset()
    assert "probe-affix:+5 to Stuff" not in classify(trial)


def test_recorder_keeps_rejected_lines_in_first_seen_order_with_counts():
    rec = probe.RejectedLines()
    rec.add(["b line", "a line"])
    rec.add(["a line"])
    assert rec.lines() == ["a line", "b line"]  # most often seen first, ties by first seen
    assert rec.count("a line") == 2


def test_row2_needs_generated_and_evaluated_for_node_affix_unique_and_zero_evaluated_for_the_control():
    considered = {
        "refine": {"mark:N": {"generated": 4, "evaluated": 4}},
        "gear": {
            "probe-affix:A": {"generated": 2, "evaluated": 1},
            "mark:U": {"generated": 1, "evaluated": 1},
            "probe-norecord:C": {"generated": 0, "evaluated": 0},
        },
    }
    sel = probe.Selection(node=["N"], affix=["A"], unique=["U"], control=["C"])
    verdict = probe.row2(considered, sel)
    assert verdict["node"] == {"line": "N", "generated": 4, "evaluated": 4, "ok": True}
    assert verdict["affix"]["ok"] and verdict["unique"]["ok"]
    assert verdict["control"] == {"line": "C", "generated": 0, "evaluated": 0, "ok": True}
    assert probe.row2_ok(verdict)
    considered["gear"]["probe-norecord:C"]["evaluated"] = 1
    assert not probe.row2_ok(probe.row2(considered, sel))


def test_row2_without_a_class_is_a_failure_not_a_pass():
    verdict = probe.row2({}, probe.Selection(node=["N"], affix=[], unique=[], control=[]))
    assert verdict["node"]["ok"] is False and verdict["affix"]["ok"] is False
    assert verdict["control"]["ok"] is False  # nothing to test: stated, never a silent pass


def test_row3_equal_to_the_digit():
    a = {"CombinedDPS": 123456.789012345, "TotalEHP": 40000.5}
    assert probe.row3(a, dict(a))["equal"] is True
    b = {"CombinedDPS": 123456.789012346, "TotalEHP": 40000.5}
    verdict = probe.row3(a, b)
    assert verdict["equal"] is False and verdict["diff"] == ["CombinedDPS"]
    assert probe.row3(a, {"CombinedDPS": 1.0})["equal"] is False  # a missing key is a difference


def test_row5_slowdown_percent_and_the_twenty_percent_limit():
    ok = probe.row5(100.0, 119.0)
    assert round(ok["percent"], 1) == 19.0 and ok["ok"] is True
    assert probe.row5(100.0, 121.0)["ok"] is False
    assert probe.row5(100.0, 80.0)["ok"] is True  # faster is fine
    assert probe.row5(0.0, 5.0)["ok"] is False and probe.row5(0.0, 5.0)["percent"] is None


def test_report_uses_human_durations_and_names_each_row():
    text = "\n".join(probe.report_lines("spark", row2=None, row3=probe.row3({"CombinedDPS": 1.0}, {"CombinedDPS": 1.0}),
                                      row5=probe.row5(300.0, 330.0)))
    assert "spark" in text and "row 3" in text and "row 5" in text
    assert "5 min" in text and "5.5 min" in text and "300" not in text
    assert "+10.0%" in text


def test_the_fixture_marks_schema_and_the_probe_marks_file_agree(tmp_path):
    path = tmp_path / "marks.json"
    probe.write_marks_file(path, probe.make_records(["A line"], zero=["Z line"]))
    marks = load_marks(path)
    assert marks.is_marked("A line", "boss") and not marks.is_marked("Z line", "boss")


# --- wiring (what lane the tree trial's marks are written for) ----------------------------------------------------


def test_tree_optimizer_judges_under_the_boss_lane_which_is_the_baseline_set():
    assert TreeOptimizer.mark_lane == "boss"
    assert _MARK_LANE_SETS["boss"] is BASELINE_SET


def test_nothing_in_src_sets_the_mark_lane_or_the_marks_store_of_a_tree_optimizer():
    """Every search evaluation runs under PoB's active config set, Baseline (`PobSession.set_config`'s
    `active_config_set_id: config.main`); the Conditional set is only read by `calc("conditional")` for the delivered
    numbers. So there is no site that judges a TreeOptimizer under the optimistic lane, and the class default stands."""

    hits = []
    for path in (ROOT / "src" / "junkroan").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in ("mark_lane", "red_marks"):
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert hits == []
    session = (ROOT / "src" / "junkroan" / "pob" / "session.py").read_text(encoding="utf-8")
    assert '"active_config_set_id": "config.main"' in session
    assert 'config_set("config.main", "Baseline", {})' in session


def test_plan_selection_marks_the_most_met_lines_and_leaves_the_next_ones_as_the_control():
    found = {
        "held_affix": ["held affix"], "held_unique": ["held unique"], "held_node": ["held node"],
        "touched_node": {"node a": 5, "node b": 9},
        "rejected": {"r1": 9, "r2": 8, "r3": 7, "r4": 6, "c1": 5, "c2": 4},
    }
    selection, zero = probe.plan_selection(found)
    assert selection.node == ["node b", "node a", "held node"]
    assert selection.affix == ["r1", "r2", "r3", "r4", "held affix"]
    assert selection.control == ["c1", "c2"] and selection.unique == ["held unique"]
    assert not set(selection.control) & set(selection.marked())
    assert zero == ["held affix", "held unique", "held node"]


def test_a_held_marked_affix_counts_through_the_lane_writers_mark_class():
    # measured 2026-10-16 on spark-s4: the held red affix is a magic Flask line; no rare candidate carries a red line
    considered = {"refine": {"mark:Held Flask Affix": {"generated": 6, "evaluated": 6}}}
    sel = probe.Selection(node=[], affix=["Held Flask Affix"], unique=[], control=[])
    verdict = probe.row2(considered, sel)
    assert verdict["affix"] == {"line": "Held Flask Affix", "generated": 6, "evaluated": 6, "ok": True}


def test_the_gate_candidate_row_is_information_never_a_failure():
    considered = {"refine": {"mark:N": {"generated": 1, "evaluated": 1}, "mark:A": {"generated": 1, "evaluated": 1},
                             "mark:U": {"generated": 1, "evaluated": 1}}}
    sel = probe.Selection(node=["N"], affix=["A"], unique=["U"], control=["C"])
    verdict = probe.row2(considered, sel)
    assert verdict["affix_gate"]["generated"] == 0 and verdict["affix_gate"]["evaluated"] == 0
    assert verdict["affix_gate"]["ok"] is None  # no rare candidate with a red line: stated, not a failure
    assert probe.row2_ok(verdict)
    assert any("affix_gate" in line and "INFO" in line for line in probe.report_lines("s", row2=verdict, row3=probe.row3({}, {}), row5=probe.row5(1.0, 1.0)))


def test_control_falls_back_to_touched_node_lines_that_were_left_without_a_record():
    found = {"touched_node": {f"node {i}": 20 - i for i in range(10)}, "rejected": {}}
    selection, _zero = probe.plan_selection(found)
    assert selection.node == [f"node {i}" for i in range(6)]
    assert selection.control == ["node 6", "node 7", "node 8"]


def test_a_node_control_reads_through_the_mark_class():
    considered = {"refine": {"mark:node 6": {"generated": 0, "evaluated": 0}}}
    sel = probe.Selection(node=[], affix=[], unique=[], control=["node 6"])
    assert probe.row2(considered, sel)["control"]["ok"] is True
    considered["refine"]["mark:node 6"]["evaluated"] = 2
    assert probe.row2(considered, sel)["control"]["ok"] is False
