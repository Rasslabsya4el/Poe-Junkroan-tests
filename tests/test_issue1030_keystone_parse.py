"""#1030 unit 1: keystone stat lines classified from PoB's parse rows, read from a fixture (no PoB)."""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.keystone_parse import KINDS, classify_keystone, classify_line, stat_lines

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "issue1030_keystone_parse.json"


def _rows() -> dict[str, dict]:
    return {row["keystone"]: row for row in json.loads(FIXTURE.read_text(encoding="utf-8"))}


def _classify(name: str) -> dict:
    row = _rows()[name]
    return classify_keystone(row["keystone"], row["stats"], row["parsed"])


def test_fixture_rows_match_their_stat_lines() -> None:
    for row in _rows().values():
        texts = stat_lines(row["stats"])
        assert [parsed["line"] for parsed in row["parsed"]] == texts


def test_chaos_inoculation_has_zero() -> None:
    result = _classify("Chaos Inoculation")
    assert "zero" in result["kinds"]
    assert result["kinds"] == ["zero"]


def test_blood_magic_has_zero_add_and_redirect() -> None:
    result = _classify("Blood Magic")
    assert result["kinds"] == ["add", "redirect", "zero"]
    by_text = {line["text"]: line["kind"] for line in result["lines"]}
    assert by_text["Removes all mana"] == "zero"
    assert by_text["10% more maximum Life"] == "add"
    assert by_text["Skills Cost Life instead of Mana"] == "redirect"
    assert by_text["Skills Reserve Life instead of Mana"] == "redirect"


def test_mind_over_matter_is_redirect() -> None:
    assert _classify("Mind Over Matter")["kinds"] == ["redirect"]


def test_pure_add_keystone_has_only_add() -> None:
    assert _classify("Iron Grip")["kinds"] == ["add"]


def test_unparsed_line_stays_unparsed_with_its_text() -> None:
    result = _classify("Elemental Equilibrium")
    assert result["kinds"] == ["unparsed"]
    texts = [line["text"] for line in result["lines"]]
    assert texts == stat_lines(_rows()["Elemental Equilibrium"]["stats"])
    assert all(line["kind"] == "unparsed" for line in result["lines"])


def test_stat_line_without_parse_row_is_unparsed() -> None:
    result = classify_keystone("Synthetic", ("Some line PoB never answered\n",), [])
    assert result["lines"] == [{"text": "Some line PoB never answered", "kind": "unparsed", "mods": []}]
    assert result["kinds"] == ["unparsed"]


def test_classify_is_deterministic() -> None:
    rows = _rows()
    for row in rows.values():
        for parsed in row["parsed"]:
            assert classify_line(parsed) == classify_line(json.loads(json.dumps(parsed)))
            assert classify_line(parsed) in KINDS
        first = classify_keystone(row["keystone"], row["stats"], row["parsed"])
        second = classify_keystone(row["keystone"], row["stats"], row["parsed"])
        assert first == second
