"""Issue #1119 unit 3 (parse pass): PoB's parse outcome for every missing day-1 line, batch by batch.

A fake `parse_mods` only: no PoB session. The expected values are literal, worked out from the
rules in `scripts/day1_parse_outcomes.py` and the entry shape `scripts/day1_lines.py` reads.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_lines import Day1Corpus, day1_rows  # noqa: E402
from day1_parse_outcomes import missing_lines, outcome_entry, parse_batches, read_outcomes  # noqa: E402
from junkroan.optimizer.rails import BenchRails, GearRails, Rails, WishlistRails  # noqa: E402


def fake_rails() -> Rails:
    return Rails(gear=GearRails(wishlist=WishlistRails(item_level={"default": 72}), bench=BenchRails(max_map_tier=10)))


def ok_result(line: str) -> dict:
    return {"line": line, "ok": True, "unsupported": False, "extra": "", "mods": [{"name": "Life", "type": "BASE"}]}


def red_result(line: str) -> dict:
    return {"line": line, "ok": False, "unsupported": True, "extra": "while you are on fire", "mods": []}


class FakePob:
    """Stands in for PobSession.parse_mods: records each call, answers every line from a table."""

    def __init__(self, answers: dict[str, dict] | None = None, fail_on_call: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answers = answers or {}
        self.fail_on_call = fail_on_call

    def __call__(self, lines: list[str]) -> list[dict]:
        self.calls.append(list(lines))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise KeyboardInterrupt("killed halfway")
        return [self.answers.get(line, ok_result(line)) for line in lines]


def test_missing_lines_are_the_missing_rows_sorted_and_unique() -> None:
    rows = [
        {"line": "+10 to Life", "outcome": "full"},
        {"line": "Gain 1 Charge", "outcome": "missing"},
        {"line": "Recover 4% Life", "outcome": "missing"},
        {"line": "Gain 1 Charge", "outcome": "missing"},
        {"line": "Nothing parsed here", "outcome": "none"},
    ]
    assert missing_lines(rows) == ["Gain 1 Charge", "Recover 4% Life"]


def test_only_missing_lines_reach_parse_mods(tmp_path: Path) -> None:
    path = tmp_path / "parse_outcomes.json"
    pob = FakePob()
    parse_batches(["Gain 1 Charge", "Recover 4% Life"], pob, path)
    assert pob.calls == [["Gain 1 Charge", "Recover 4% Life"]]


def test_existing_entries_are_kept_and_not_reparsed(tmp_path: Path) -> None:
    path = tmp_path / "parse_outcomes.json"
    existing = {"Old line": {"extra": "", "mod_types": ["BASE"], "ok": True, "unsupported": False}}
    path.write_text(
        '{\n  "Old line": {\n    "extra": "",\n    "mod_types": [\n      "BASE"\n    ],\n    "ok": true,\n    "unsupported": false\n  }\n}\n',
        encoding="utf-8",
    )
    pob = FakePob(answers={"Old line": red_result("Old line")})
    parse_batches(["Old line", "New line"], pob, path)
    assert pob.calls == [["New line"]]
    entries = read_outcomes(path)
    assert entries["Old line"] == existing["Old line"]
    assert entries["New line"] == outcome_entry(ok_result("New line"))


def test_batches_are_resumable_after_a_kill(tmp_path: Path) -> None:
    lines = ["e line", "a line", "d line", "b line", "c line"]
    one_shot = tmp_path / "one_shot.json"
    parse_batches(lines, FakePob(), one_shot, batch_size=2)

    killed = tmp_path / "killed.json"
    with pytest.raises(KeyboardInterrupt):
        parse_batches(lines, FakePob(fail_on_call=2), killed, batch_size=2)
    # the first batch (sorted: "a line", "b line") was written before the kill
    assert sorted(read_outcomes(killed)) == ["a line", "b line"]

    resumed = FakePob()
    parse_batches(lines, resumed, killed, batch_size=2)
    assert resumed.calls == [["c line", "d line"], ["e line"]]
    assert killed.read_bytes() == one_shot.read_bytes()


def test_file_bytes_do_not_depend_on_input_order(tmp_path: Path) -> None:
    forward, backward = tmp_path / "forward.json", tmp_path / "backward.json"
    parse_batches(["c line", "a line", "b line"], FakePob(), forward, batch_size=2)
    parse_batches(["b line", "c line", "a line"], FakePob(), backward, batch_size=2)
    assert forward.read_bytes() == backward.read_bytes()


def test_file_text_is_sorted_indented_and_ends_with_newline(tmp_path: Path) -> None:
    path = tmp_path / "parse_outcomes.json"
    answers = {"b line": red_result("b line")}
    parse_batches(["b line", "a line"], FakePob(answers=answers), path)
    expected = "\n".join([
        "{",
        '  "a line": {',
        '    "extra": "",',
        '    "mod_types": [',
        '      "BASE"',
        "    ],",
        '    "ok": true,',
        '    "unsupported": false',
        "  },",
        '  "b line": {',
        '    "extra": "while you are on fire",',
        '    "mod_types": [],',
        '    "ok": false,',
        '    "unsupported": true',
        "  }",
        "}",
        "",
    ])
    assert path.read_text(encoding="utf-8") == expected


def test_outcome_entry_from_pob_result() -> None:
    assert outcome_entry(ok_result("+10 to Life")) == {"extra": "", "mod_types": ["BASE"], "ok": True, "unsupported": False}
    assert outcome_entry(red_result("X")) == {"extra": "while you are on fire", "mod_types": [], "ok": False, "unsupported": True}
    two_types = {"line": "Y", "ok": True, "unsupported": False, "extra": "",
                 "mods": [{"name": "Life", "type": "INC"}, {"name": "Life", "type": "BASE"}, {"name": "Life", "type": "INC"}]}
    assert outcome_entry(two_types)["mod_types"] == ["BASE", "INC"]


def test_written_entries_read_back_as_unit_1_outcomes(tmp_path: Path) -> None:
    path = tmp_path / "parse_outcomes.json"
    parse_batches(["Gain 1 Charge", "Recover 4% Life"], FakePob(answers={"Gain 1 Charge": red_result("Gain 1 Charge")}), path)
    corpus = Day1Corpus(
        passives=[{"is_notable": True, "node_id": 1, "stats": ["Recover 4% Life", "Gain 1 Charge"]}],
        parse_outcomes=read_outcomes(path),
    )
    outcomes = {row["line"]: row["outcome"] for row in day1_rows(fake_rails(), corpus)}
    assert outcomes == {"Recover 4% Life": "full", "Gain 1 Charge": "none"}
