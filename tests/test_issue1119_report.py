"""Issue #1119 unit 4 (report): the surface x outcome and group x surface tables, per-group summaries, the doc text.

A fixture of eleven rows only: no PoB session, no corpus files. Every expected value is worked out by hand from
the rules (outcome per row as written; group per `scripts/day1_groups.py` first-match order), never recomputed by
the code under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_groups import GROUPS, group_of  # noqa: E402
from day1_red_lines_report import (  # noqa: E402
    group_summaries,
    group_surface_table,
    render,
    surface_outcome_table,
)


def row(surface: str, source, line: str, outcome: str) -> dict:
    return {"line": line, "surface": surface, "source": source, "outcome": outcome}


# group each line falls in, by hand: plain_stat (rows 1, 8), on_kill (2, 3, 4), on_hit (5),
# cannot_immune (6, 7), recovery (9), other (10, 11)
FIXTURE = [
    row("notable", 6, "+10% increased Damage", "full"),
    row("notable", 7, "10% chance to gain a Power Charge on Kill", "none"),
    row("keystone", 3354, "Kills grant Life", "full"),
    row("unique", "Doom Tool", "Enemies you kill are Shocked", "partial"),
    row("unique", "Doom Tool", "Chill Enemy when Hit", "none"),
    row("gear_affix", "Mod2", "Cannot be Stunned", "none"),
    row("gear_affix", "Mod3", "Cannot be Stunned", "none"),
    row("gear_affix", "Mod4", "+30 to maximum Life", "full"),
    row("flask", "Flask1", "Flask gives 20% increased Recovery", "partial"),
    row("gear_affix", "Mod5", "Some unknown line", "missing"),
    row("mastery", 9, "Mastery text here", "full"),
]


# the group each fixture text falls in, written by hand from the family order in scripts/day1_groups.py
EXPECTED_GROUP = {
    "+10% increased Damage": "plain_stat",
    "10% chance to gain a Power Charge on Kill": "on_kill",
    "Kills grant Life": "on_kill",
    "Enemies you kill are Shocked": "on_kill",
    "Chill Enemy when Hit": "on_hit",
    "Cannot be Stunned": "cannot_immune",
    "+30 to maximum Life": "plain_stat",
    "Flask gives 20% increased Recovery": "recovery",
    "Some unknown line": "other",
    "Mastery text here": "other",
}


def test_groups_list_has_other_last_and_no_repeats():
    assert GROUPS[-1] == "other"
    assert len(GROUPS) == len(set(GROUPS))


def test_fixture_lines_fall_in_their_hand_groups():
    assert {r["line"] for r in FIXTURE} == set(EXPECTED_GROUP)
    wrong = [(r["line"], EXPECTED_GROUP[r["line"]], group_of(r["line"])) for r in FIXTURE if group_of(r["line"]) != EXPECTED_GROUP[r["line"]]]
    assert wrong == [], wrong


def test_surface_outcome_counts():
    table = surface_outcome_table(FIXTURE)
    assert table["notable"] == {"full": 1, "partial": 0, "none": 1, "missing": 0}
    assert table["keystone"] == {"full": 1, "partial": 0, "none": 0, "missing": 0}
    assert table["unique"] == {"full": 0, "partial": 1, "none": 1, "missing": 0}
    assert table["gear_affix"] == {"full": 1, "partial": 0, "none": 2, "missing": 1}
    assert table["flask"] == {"full": 0, "partial": 1, "none": 0, "missing": 0}
    assert table["mastery"] == {"full": 1, "partial": 0, "none": 0, "missing": 0}
    assert table["unique_jewel"] == {"full": 0, "partial": 0, "none": 0, "missing": 0}


def test_group_surface_line_counts():
    table = group_surface_table(FIXTURE)
    assert sum(sum(cells.values()) for cells in table.values()) == len(FIXTURE)
    assert table["on_kill"] == {"notable": 1, "keystone": 1, "unique": 1}
    assert table["cannot_immune"] == {"gear_affix": 2}
    assert table["recovery"] == {"flask": 1}
    assert table["other"] == {"gear_affix": 1, "mastery": 1}
    assert table["item_text"] == {}


def test_per_group_summary_lines_sources_red_and_partial_share():
    by_group = {g["group"]: g for g in group_summaries(FIXTURE)}
    assert by_group["on_kill"]["lines"] == 3
    assert by_group["on_kill"]["sources"] == 3  # (notable, 7), (keystone, 3354), (unique, Doom Tool)
    assert by_group["on_kill"]["red"] == 2  # none + partial; the keystone line is full
    assert round(by_group["on_kill"]["partial_share"], 4) == round(1 / 3, 4)  # partial / all lines of the group
    assert round(by_group["on_kill"]["partial_of_red"], 4) == round(1 / 2, 4)  # partial / red lines
    assert by_group["cannot_immune"]["sources"] == 2  # two different mod ids carry the same line
    assert by_group["cannot_immune"]["partial_share"] == 0.0
    assert by_group["cannot_immune"]["partial_of_red"] == 0.0
    assert by_group["recovery"]["partial_share"] == 1.0
    assert by_group["recovery"]["partial_of_red"] == 1.0
    assert by_group["plain_stat"]["red"] == 0
    assert by_group["plain_stat"]["partial_of_red"] is None
    assert by_group["other"]["sources"] == 2
    assert by_group["item_text"]["lines"] == 0
    assert by_group["item_text"]["partial_share"] is None


def test_examples_take_red_lines_first_then_fall_back_to_non_red_with_outcome():
    by_group = {g["group"]: g for g in group_summaries(FIXTURE)}
    # two red lines in on_kill (none, partial), so one non-red line fills the third slot
    assert by_group["on_kill"]["examples"] == [
        "[none] 10% chance to gain a Power Charge on Kill",
        "[partial] Enemies you kill are Shocked",
        "[full] Kills grant Life",
    ]
    assert by_group["cannot_immune"]["examples"] == ["[none] Cannot be Stunned"]
    assert by_group["on_hit"]["examples"] == ["[none] Chill Enemy when Hit"]
    # no red line at all: the first three non-red texts, sorted, each with its outcome
    assert by_group["plain_stat"]["examples"] == ["[full] +10% increased Damage", "[full] +30 to maximum Life"]
    assert by_group["other"]["examples"] == ["[full] Mastery text here", "[missing] Some unknown line"]


def test_group_summaries_follow_the_group_order_with_other_last():
    names = [g["group"] for g in group_summaries(FIXTURE)]
    assert names == list(GROUPS)
    assert names[-1] == "other"


def test_doc_text_for_the_fixture():
    text = render(FIXTURE)
    lines = text.splitlines()
    # first paragraph: red lines defined, and the count with its split
    first_paragraph = next(p for p in text.split("\n\n") if p.strip() and not p.startswith("#"))
    assert "`partial`" in first_paragraph and "`none`" in first_paragraph
    assert "6 of 11" in first_paragraph  # red = partial 2 + none 4
    # table (a) rows and total row
    assert "| notable | 1 | 0 | 1 | 0 | 2 |" in lines
    assert "| gear_affix | 1 | 0 | 2 | 1 | 4 |" in lines
    assert "| total | 4 | 2 | 4 | 1 | 11 |" in lines
    # table (b) rows: on_kill across notable, keystone, unique; the total row
    assert "| on_kill | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 3 |" in lines
    assert "| cannot_immune | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2 |" in lines
    assert "| other | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 2 |" in lines
    group_rows = [line for line in lines if line.startswith("| ") and line.split("|")[1].strip() in GROUPS]
    assert group_rows[-1].split("|")[1].strip() == "other"
    # per-group line: red count, distinct sources, partial share, examples
    assert "| total | 2 | 1 | 0 | 1 | 2 | 0 | 4 | 1 | 11 |" in lines
    # per-group row: group | lines | by surface | distinct sources | red | partial share | examples
    assert any(line.startswith("| on_kill |") and "| 3 | 2 | 33.3% | 50.0% |" in line for line in lines)
    assert any(line.startswith("| recovery |") and "| 1 | 1 | 100.0% | 100.0% |" in line for line in lines)
    assert any(line.startswith("| on_kill |") and "[none] 10% chance to gain a Power Charge on Kill" in line for line in lines)
    assert "| group | lines | by surface | distinct sources (node id / unique name / mod id) | red | partial share (partial / all lines of the group) | partial of red (partial / red lines) | examples |" in lines
    assert "1 of the 11 rows repeat a text another row already has (10 distinct texts in all)" in text
    assert "Distinct sources can be fewer than lines" in text
    assert "- jewel_conditional: 0 lines" in text
    assert "- unique_jewel: 0 rows." in text
    assert "## (d) How to regenerate" in text
    assert "python scripts/day1_red_lines_report.py" in text
