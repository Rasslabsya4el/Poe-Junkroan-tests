"""Issue #1123 unit 1: the day-1 red-line slices and the marks check, PoB-free.

Seams: `red_line_slices.red_records` / `slice_records` / `write_slices` (rows in, slice files out) and
`check_red_line_marks.check_marks` / `check_schema` / `load_marks` / `load_slice` / `main` (marks in, report out).
The rows are plain dicts shaped like `day1_lines.day1_rows`; the parse is a fake `parse_mods`, as in
tests/test_issue1119_parse_pass.py. Expected values are literals or worked out by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import check_red_line_marks as check  # noqa: E402
import red_line_slices as slices  # noqa: E402
from day1_groups import group_of  # noqa: E402


def row(line: str, surface: str = "notable", source: object = 1, outcome: str = "none") -> dict:
    return {"line": line, "surface": surface, "source": source, "outcome": outcome}


def good(line: str, *, boss: list[str] | None = None, optimistic: list[str] | None = None,
         zero_reason: str = "", kind: str = "uptime_dependent") -> dict:
    """A record that passes the schema; the group is the group rule's own answer for the line."""
    return {
        "line": line,
        "surfaces": ["notable"],
        "sources": ["1"],
        "group": group_of(line),
        "kind": kind,
        "boss_lane": list(boss or []),
        "optimistic_lane": list(optimistic or []),
        "zero_reason": zero_reason,
        "why": "one line of why",
        "partial_part": "",
    }


def ok_result(line: str) -> dict:
    return {"line": line, "ok": True, "unsupported": False, "extra": "", "mods": [{"name": "Life", "type": "BASE"}]}


class FakePob:
    """Stands in for PobSession.parse_mods: records the batches, answers from a table, can drop a line."""

    def __init__(self, answers: dict[str, dict] | None = None, drop: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answers = answers or {}
        self.drop = drop or set()

    def __call__(self, lines: list[str]) -> list[dict]:
        self.calls.append(list(lines))
        return [self.answers.get(line, ok_result(line)) for line in lines if line not in self.drop]


# -- the slicer ----------------------------------------------------------------------------------

def test_a_group_over_120_lines_is_split_into_numbered_parts_of_at_most_120() -> None:
    rows = [row(f"Gain {i} Charge", source=i, outcome="none") for i in range(250)]
    rows += [row(f"Lorem ipsum dolor {i}", outcome="partial") for i in range(5)]
    found = slices.slice_records(slices.red_records(rows))
    assert [s["name"] for s in found] == [
        "01-charges-p1.json", "02-charges-p2.json", "03-charges-p3.json", "04-other.json",
    ]
    assert [len(s["records"]) for s in found] == [120, 120, 10, 5]
    assert all(len(s["records"]) <= slices.CAP for s in found)
    assert slices.CAP == 120


def test_red_records_keep_distinct_red_texts_with_their_surfaces_and_sources() -> None:
    rows = [
        row("Gain 1 Charge", "notable", 10, "none"),
        row("Gain 1 Charge", "gear_affix", "mod9", "none"),
        row("+10 to Life", "notable", 11, "full"),
        row("Half red", "flask", "f1", "partial"),
    ]
    assert slices.red_records(rows) == [
        {"line": "Gain 1 Charge", "surfaces": ["gear_affix", "notable"], "sources": ["10", "mod9"],
         "group": "charges", "outcome": "none"},
        {"line": "Half red", "surfaces": ["flask"], "sources": ["f1"],
         "group": "other", "outcome": "partial"},
    ]


def test_a_text_partial_in_one_row_and_none_in_another_is_partial_with_both_sources() -> None:
    rows = [
        row("Gain 1 Charge", "notable", 10, "partial"),
        row("Gain 1 Charge", "gear_affix", "mod9", "none"),
    ]
    assert slices.red_records(rows) == [
        {"line": "Gain 1 Charge", "surfaces": ["gear_affix", "notable"], "sources": ["10", "mod9"],
         "group": "charges", "outcome": "partial"},
    ]


def test_slicing_and_writing_are_deterministic(tmp_path: Path) -> None:
    rows = [row(f"Gain {i} Charge", source=i, outcome="none") for i in range(130)]
    rows.append(row("Lorem ipsum dolor", source=1, outcome="partial"))
    forward = slices.slice_records(slices.red_records(rows))
    backward = slices.slice_records(slices.red_records(list(reversed(rows))))
    assert forward == backward
    a, b = tmp_path / "a", tmp_path / "b"
    slices.write_slices(forward, a)
    slices.write_slices(backward, b)
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()) == [s["name"] for s in forward]
    assert all((a / n).read_bytes() == (b / n).read_bytes() for n in names)
    part = json.loads((a / "01-charges-p1.json").read_text(encoding="utf-8"))
    assert part["group"] == "charges" and part["part"] == 1 and part["parts"] == 2
    assert len(part["records"]) == 120


# -- the marks check: schema -----------------------------------------------------------------------

def test_a_well_formed_record_has_no_schema_error() -> None:
    assert check.check_schema(good("Gain 1 Charge", optimistic=["You gain 1 Frenzy Charge on Kill"])) == []


def test_each_schema_break_is_reported() -> None:
    breaks = {
        "missing why": lambda r: r.pop("why"),
        "boss_lane as a string": lambda r: r.__setitem__("boss_lane", "x"),
        "unknown group": lambda r: r.__setitem__("group", "nope"),
        "kind not snake_case": lambda r: r.__setitem__("kind", "On Kill"),
        "unknown key": lambda r: r.__setitem__("note", "x"),
        "empty why": lambda r: r.__setitem__("why", ""),
        "formula of the wrong type": lambda r: r.__setitem__("formula", 3),
        "blank lane line": lambda r: r.__setitem__("optimistic_lane", [" "]),
    }
    for name, breakit in breaks.items():
        record = good("Gain 1 Charge", optimistic=["Line A"])
        breakit(record)
        assert check.check_schema(record), name


def test_stand_blind_is_accepted_with_each_known_reason_kind_and_a_why() -> None:
    for reason_kind in ("trap", "totem", "shield", "minion", "flag-only", "charge-without-consumer", "uptime-saturated",
                        "mechanic-absent"):
        record = good("Gain 1 Charge", optimistic=["Line A"])
        record["stand_blind"] = {"reason_kind": reason_kind, "why": "the stand has no such thing"}
        assert check.check_schema(record) == [], reason_kind


def test_mechanic_absent_is_a_stand_blind_kind_for_a_line_whose_mechanic_no_stand_carries() -> None:
    record = good("Gain 1 Charge", optimistic=["Line A"])
    record["stand_blind"] = {"reason_kind": "mechanic-absent", "why": "no stand carries Fortified"}
    assert "mechanic-absent" in check.STAND_BLIND_KINDS
    assert check.check_schema(record) == []
    record["stand_blind"]["reason_kind"] = "mechanic_absent"
    assert check.check_schema(record) != []


def test_stand_blind_rejects_an_unknown_or_missing_reason_kind_a_blank_or_missing_why_and_a_non_object() -> None:
    cases = {
        "unknown reason_kind": {"reason_kind": "bogus", "why": "x"},
        "missing reason_kind": {"why": "x"},
        "blank why": {"reason_kind": "trap", "why": "   "},
        "missing why": {"reason_kind": "trap"},
        "string instead of object": "trap",
        "list instead of object": [],
    }
    for name, value in cases.items():
        record = good("Gain 1 Charge", optimistic=["Line A"])
        record["stand_blind"] = value
        assert check.check_schema(record), name


# -- the marks check: counts, zero_reason, parse ----------------------------------------------------

def test_missing_duplicate_and_extra_records_are_counted() -> None:
    expected = {"Gain 1 Charge", "Gain 2 Charge", "Gain 3 Charge"}
    records = [
        good("Gain 1 Charge", zero_reason="steal_charges: never counts"),
        good("Gain 1 Charge", zero_reason="steal_charges: never counts"),
        good("Gain 2 Charge", zero_reason="steal_charges: never counts"),
        good("Lorem ipsum dolor", zero_reason="steal_charges: never counts"),
    ]
    report = check.check_marks(records, expected)
    assert report["records"] == 4
    assert report["missing"] == ["Gain 3 Charge"]
    assert report["duplicates"] == {"Gain 1 Charge": 2}
    assert report["extra"] == ["Lorem ipsum dolor"]
    assert report["ok"] is False


def test_a_zero_needs_a_reason_that_names_a_verdict_or_a_kind() -> None:
    cases = {
        "": False,
        "because it is hard": False,
        "steal_charges: never counts": True,
        "Ramp window 2.5 s: the loadout ramp, never the cap": True,
        "Guard skill: cooldown-limited buff, 0 on every lane": True,
    }
    for reason, passes in cases.items():
        report = check.check_marks([good("Gain 1 Charge", zero_reason=reason)], {"Gain 1 Charge"})
        assert (not report["zero_errors"]) is passes, reason
    counted = check.check_marks([good("Gain 1 Charge", optimistic=["Line A"], zero_reason="")], {"Gain 1 Charge"})
    assert counted["zero_errors"] == []


def test_a_slice_check_is_relative_to_the_slice_lines(tmp_path: Path) -> None:
    slice_file = tmp_path / "03-charges.json"
    slice_file.write_text(json.dumps({"group": "charges", "part": None, "parts": 1, "records": [
        {"line": "Gain 1 Charge"}, {"line": "Gain 2 Charge"}]}), encoding="utf-8")
    marks = tmp_path / "marks.json"
    marks.write_text(json.dumps({"records": [
        good("Gain 1 Charge", zero_reason="steal_charges: never counts"),
        good("Lorem ipsum dolor", zero_reason="steal_charges: never counts"),
    ]}), encoding="utf-8")
    assert check.main(["--no-parse", "--slice", str(slice_file), str(marks)]) == 1  # Gain 2 Charge missing
    marks.write_text(json.dumps([
        good("Gain 1 Charge", zero_reason="steal_charges: never counts"),
        good("Gain 2 Charge", zero_reason="steal_charges: never counts"),
        good("Lorem ipsum dolor", zero_reason="steal_charges: never counts"),
    ]), encoding="utf-8")
    assert check.main(["--no-parse", "--slice", str(slice_file), str(marks)]) == 0  # outside lines ignored


def test_marks_folder_of_part_files_is_read_as_one_set(tmp_path: Path) -> None:
    folder = tmp_path / "parts"
    folder.mkdir()
    (folder / "01-charges.json").write_text(json.dumps([good("Gain 1 Charge")]), encoding="utf-8")
    (folder / "02-other.json").write_text(json.dumps({"records": [good("Lorem ipsum dolor")]}), encoding="utf-8")
    assert [r["line"] for r in check.load_marks(folder)] == ["Gain 1 Charge", "Lorem ipsum dolor"]


def test_parse_failures_are_reported_per_lane_line() -> None:
    def fake_parse(lines: list[str]) -> list[dict]:
        out = []
        for line in lines:
            if line == "Line bad":
                out.append({"line": line, "ok": False, "unsupported": True, "extra": "while on fire", "mods": []})
            elif line == "Line extra":
                out.append({"line": line, "ok": True, "unsupported": False, "extra": "x", "mods": [{"name": "Life", "type": "BASE"}]})
            elif line == "Line unsupported":
                out.append({"line": line, "ok": True, "unsupported": True, "extra": "", "mods": [{"name": "Life", "type": "BASE"}]})
            else:
                out.append(ok_result(line))
        return out

    records = [
        good("Gain 1 Charge", optimistic=["Line A"]),
        good("Gain 2 Charge", boss=["Line bad", "Line extra"]),
        good("Gain 3 Charge", optimistic=["Line unsupported"]),
    ]
    report = check.check_marks(records, {"Gain 1 Charge", "Gain 2 Charge", "Gain 3 Charge"}, parse_mods=fake_parse)
    assert sorted(f["line"] for f in report["parse_failures"]) == ["Line bad", "Line extra", "Line unsupported"]
    assert report["ok"] is False


def test_lane_lines_are_parsed_in_batches_of_100() -> None:
    fake = FakePob()
    record = good("Gain 1 Charge", optimistic=[f"Line {i}" for i in range(250)])
    report = check.check_marks([record], {"Gain 1 Charge"}, parse_mods=fake)
    assert [len(batch) for batch in fake.calls] == [100, 100, 50]
    assert report["parse_failures"] == []
    assert report["lane_lines"] == 250


def test_a_lane_line_with_no_result_is_a_failure() -> None:
    fake = FakePob(drop={"Line B"})
    record = good("Gain 1 Charge", boss=["Line A", "Line B"])
    report = check.check_marks([record], {"Gain 1 Charge"}, parse_mods=fake)
    assert [f["line"] for f in report["parse_failures"]] == ["Line B"]
    assert report["ok"] is False


def test_a_zero_reason_names_a_token_in_any_case_or_a_json_kind_id() -> None:
    cases = {
        "STEAL charges, never counts": True,
        "Ramp Window 2.5 s": True,
        "uptime-dependent: parked #965": True,
        "on_block_generator: boss lane off": True,
        "Guard Skill and cooldown buffs": True,
        "because it is hard": False,
    }
    for reason, passes in cases.items():
        report = check.check_marks([good("Gain 1 Charge", zero_reason=reason)], {"Gain 1 Charge"})
        assert (not report["zero_errors"]) is passes, reason


def test_help_prints_the_verdict_tokens_with_their_meaning(capsys) -> None:
    with pytest.raises(SystemExit) as stop:
        check.main(["--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    for token, meaning in check.VERDICT_TOKENS.items():
        assert token in out and meaning in out, token
    assert "steal_charges" in out  # the JSON kind ids are listed too


def test_partial_part_follows_the_outcome_of_the_red_line() -> None:
    cases = [
        ("partial", "", ["Gain 1 Charge"]),       # partial with no unparsed part: a failure
        ("partial", "Frenzy part", []),
        ("none", "", []),
        ("none", "stray text", ["Gain 1 Charge"]),  # none has no partial part: a failure
    ]
    for outcome, part, errors in cases:
        record = good("Gain 1 Charge", optimistic=["Line A"])
        record["partial_part"] = part
        report = check.check_marks([record], {"Gain 1 Charge": outcome})
        assert report["partial_part_errors"] == errors, (outcome, part)
        assert report["ok"] is (not errors), (outcome, part)


def test_a_new_kind_with_a_boss_lane_is_an_error_a_json_kind_is_not() -> None:
    json_kind = good("Gain 1 Charge", boss=["Line A"], kind="steal_charges")
    new_kind_boss = good("Gain 2 Charge", boss=["Line B"], kind="frenzy_on_hit")
    new_kind_optimistic = good("Gain 3 Charge", optimistic=["Line C"], kind="frenzy_on_hit")
    report = check.check_marks([json_kind, new_kind_boss, new_kind_optimistic],
                               {"Gain 1 Charge", "Gain 2 Charge", "Gain 3 Charge"})
    assert report["kind_errors"] == ["Gain 2 Charge"]
    assert report["ok"] is False


def test_new_kinds_are_listed_with_line_count_and_three_examples(capsys) -> None:
    records = [good(f"Gain {i} Charge", optimistic=["Line A"], kind="frenzy_on_hit") for i in (4, 1, 3, 2)]
    records.append(good("Gain 9 Charge", optimistic=["Line B"], kind="steal_charges"))
    report = check.check_marks(records, {r["line"] for r in records})
    assert report["new_kinds"] == {
        "frenzy_on_hit": {"lines": 4, "examples": ["Gain 1 Charge", "Gain 2 Charge", "Gain 3 Charge"]},
    }
    check.print_report(report)
    out = capsys.readouterr().out
    assert "frenzy_on_hit: 4 lines" in out
    assert "e.g. Gain 1 Charge" in out and "e.g. Gain 3 Charge" in out


def test_type_and_vars_are_allowed_and_type_is_checked():
    """The stand check reads `type` (spell / attack / minion / any) and `vars` (formula names such as RampSeconds)."""
    import check_red_line_marks as c

    record = {
        "line": "x", "surfaces": ["notable"], "sources": ["a"], "group": "other", "kind": "uptime_dependent",
        "boss_lane": [], "optimistic_lane": ["Adds 1 to Life"], "zero_reason": "", "why": "w", "partial_part": "",
        "type": "spell", "vars": {"RampSeconds": 2.5},
    }
    assert c.check_schema(record) == []
    assert c.check_schema({**record, "type": "wand"}) != []


def test_formula_placeholder_is_filled_before_the_parse_check():
    """A lane line with `{formula}` is parsed with a stand-in number, the way the stand check fills the real value."""
    import check_red_line_marks as c

    seen = []

    def fake_parse(batch):
        seen.extend(batch)
        return [{"line": text, "ok": True, "unsupported": [], "extra": []} for text in batch]

    record = {
        "line": "x", "surfaces": ["notable"], "sources": ["a"], "group": "other", "kind": "uptime_dependent",
        "boss_lane": [], "optimistic_lane": ["Regenerate {formula} Life per second"], "zero_reason": "", "why": "w",
        "partial_part": "", "formula": "LifeRegen",
    }
    report = c.check_marks([record], {"x"}, parse_mods=fake_parse)
    assert seen == ["Regenerate 10 Life per second"]
    assert report["parse_failures"] == []


# -- the marks check: ramp_window / proxy_delivery carry the boss lane = the optimistic lane --------

BOSS_LANE_KINDS = check.BOSS_LANE_KINDS


def test_other_new_kind_with_a_boss_lane_is_a_kind_error_not_a_lane_equality_error() -> None:
    record = good("Gain 1 Charge", boss=["Line A"], optimistic=["Line A"], kind="frenzy_on_hit")
    report = check.check_marks([record], {"Gain 1 Charge"})
    assert report["kind_errors"] == ["Gain 1 Charge"]
    assert report["lane_equality_errors"] == []
    assert report["ok"] is False


def test_ramp_or_proxy_record_with_boss_lane_equal_to_optimistic_is_ok() -> None:
    for kind in BOSS_LANE_KINDS:
        record = good("Gain 1 Charge", boss=["Line A", "Line B"], optimistic=["Line A", "Line B"], kind=kind)
        report = check.check_marks([record], {"Gain 1 Charge"})
        assert report["kind_errors"] == [], kind
        assert report["lane_equality_errors"] == [], kind
        assert report["new_kinds"] == {kind: {"lines": 1, "examples": ["Gain 1 Charge"]}}, kind
        assert report["ok"] is True, kind


def test_ramp_window_with_boss_lane_different_from_optimistic_is_a_lane_equality_error() -> None:
    different = good("Gain 1 Charge", boss=["Line A"], optimistic=["Line A", "Line B"], kind="ramp_window")
    reordered = good("Gain 2 Charge", boss=["Line B", "Line A"], optimistic=["Line A", "Line B"], kind="ramp_window")
    report = check.check_marks([different, reordered], {"Gain 1 Charge", "Gain 2 Charge"})
    assert report["lane_equality_errors"] == ["Gain 1 Charge", "Gain 2 Charge"]
    assert report["kind_errors"] == []
    assert report["ok"] is False


def test_zero_ramp_window_record_with_empty_lanes_is_ok() -> None:
    record = good("Gain 1 Charge", zero_reason="ramp_window: 2.5 s window, zero on this loadout", kind="ramp_window")
    report = check.check_marks([record], {"Gain 1 Charge"})
    assert report["zero_errors"] == []
    assert report["lane_equality_errors"] == []
    assert report["ok"] is True


def test_print_report_prints_the_ramp_proxy_boss_lane_row(capsys) -> None:
    records = [
        good("Gain 1 Charge", boss=["Line A"], optimistic=["Line A"], kind="ramp_window"),
        good("Gain 2 Charge", boss=["Line B"], optimistic=["Line B"], kind="proxy_delivery"),
        good("Gain 3 Charge", zero_reason="ramp_window: zero", kind="ramp_window"),
        good("Gain 4 Charge", optimistic=["Line C"], kind="frenzy_on_hit"),
        good("Gain 5 Charge", boss=["Line D"], optimistic=["Line E"], kind="proxy_delivery"),
    ]
    report = check.check_marks(records, {r["line"] for r in records})
    check.print_report(report)
    out = capsys.readouterr().out
    assert "ramp_window/proxy_delivery records with a boss lane = 3 of 4" in out
    assert "boss lane != optimistic lane: Gain 5 Charge" in out
    assert report["ok"] is False
