"""Issue #1125 unit 1 (mod records): PoB's mod list for every day-1 line with outcome full or partial.

A fake `parse_mods` only: no PoB session. The expected values are literal, written from the rules in
`scripts/day1_mod_records.py` and the record shape `scripts/build_unique_index.py:92` keeps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_mod_records import mod_record_entry, mod_records_lines, parse_records  # noqa: E402

FULL = "+10 to Life"
PARTIAL = "Gain 1 Charge while you are on fire"
NONE = "Nothing parsed here"
MISSING = "Gain 1 Charge"
RANGED = "Adds (10-20) to Life"


def full_result(line: str) -> dict:
    return {
        "line": line, "ok": True, "unsupported": False, "extra": "",
        "mods": [{"name": "Life", "type": "BASE", "value": 10, "flags": 0, "keyword_flags": 0,
                  "tags": [{"type": "Condition", "var": "Fire"}]}],
    }


def partial_result(line: str) -> dict:
    return {
        "line": line, "ok": False, "unsupported": False, "extra": "while you are on fire",
        "mods": [{"name": "Charge", "type": "LIST", "value": 1, "flags": 0, "keyword_flags": 0, "tags": []}],
    }


class FakePob:
    """Stands in for PobSession.parse_mods: records each call and answers each line from a table."""

    def __init__(self, answers: dict[str, dict] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answers = answers or {}

    def __call__(self, lines: list[str]) -> list[dict]:
        self.calls.append(list(lines))
        return [self.answers.get(line, full_result(line)) for line in lines]


def rows() -> list[dict]:
    return [
        {"line": FULL, "surface": "notable", "source": 1, "outcome": "full"},
        {"line": PARTIAL, "surface": "notable", "source": 2, "outcome": "partial"},
        {"line": NONE, "surface": "notable", "source": 3, "outcome": "none"},
        {"line": MISSING, "surface": "keystone", "source": 4, "outcome": "missing"},
        {"line": FULL, "surface": "unique", "source": "X", "outcome": "full"},
    ]


def test_lines_are_the_distinct_full_and_partial_lines_sorted() -> None:
    assert mod_records_lines(rows()) == sorted([FULL, PARTIAL])


def test_record_shape_is_the_unique_index_mod_shape(tmp_path: Path) -> None:
    path = tmp_path / "day1_mod_records.json"
    parse_records([FULL], FakePob(), path)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        FULL: [{"name": "Life", "type": "BASE", "value": 10, "flags": 0, "keyword_flags": 0,
                "tags": [{"type": "Condition", "var": "Fire"}]}],
    }


def test_none_and_missing_lines_get_no_record_and_no_pob_call(tmp_path: Path) -> None:
    path = tmp_path / "day1_mod_records.json"
    pob = FakePob()
    parse_records(mod_records_lines(rows()), pob, path)
    sent = sorted({line for call in pob.calls for line in call})
    assert sent == sorted([FULL, PARTIAL])
    assert sorted(json.loads(path.read_text(encoding="utf-8"))) == sorted([FULL, PARTIAL])


def test_partial_line_is_included_with_its_mods(tmp_path: Path) -> None:
    path = tmp_path / "day1_mod_records.json"
    parse_records([PARTIAL], FakePob(answers={PARTIAL: partial_result(PARTIAL)}), path)
    record = json.loads(path.read_text(encoding="utf-8"))[PARTIAL]
    assert record == [{"name": "Charge", "type": "LIST", "value": 1, "flags": 0, "keyword_flags": 0, "tags": []}]


def test_file_bytes_do_not_depend_on_input_order(tmp_path: Path) -> None:
    forward, backward = tmp_path / "forward.json", tmp_path / "backward.json"
    parse_records([FULL, PARTIAL], FakePob(answers={PARTIAL: partial_result(PARTIAL)}), forward, batch_size=1)
    parse_records([PARTIAL, FULL], FakePob(answers={PARTIAL: partial_result(PARTIAL)}), backward, batch_size=2)
    assert forward.read_bytes() == backward.read_bytes()


def test_ranges_are_rolled_at_the_midpoint_before_pob_and_the_key_keeps_the_range(tmp_path: Path) -> None:
    path = tmp_path / "day1_mod_records.json"
    pob = FakePob()
    parse_records([RANGED], pob, path)
    assert pob.calls == [["Adds 15 to Life"]]
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [RANGED]


def test_mod_record_entry_keeps_only_the_six_fields() -> None:
    result = full_result(FULL)
    result["mods"][0]["extra_key"] = "dropped"
    assert mod_record_entry(result) == [
        {"name": "Life", "type": "BASE", "value": 10, "flags": 0, "keyword_flags": 0,
         "tags": [{"type": "Condition", "var": "Fire"}]},
    ]
