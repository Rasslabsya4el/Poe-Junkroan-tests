"""#723: the build report's progress lines and rank tables print durations through human_duration."""

import re
from pathlib import Path

import pytest

from junkroan.report_format import human_duration
from junkroan.search.request import full_done_line, mutation_done_line, prepared_line, rig_supports_line, screen_done_line, total_line

SEARCH = Path(__file__).resolve().parents[1] / "scripts" / "search.py"

LINES = [
    (rig_supports_line("Marauder", "Chieftain", 156, ["A"]), 156),
    (prepared_line(1, 44), 44),
    (screen_done_line(139), 139),
    (full_done_line(7055, 1, 3), 7055),
    (mutation_done_line(4069, 2, 2), 4069),
    (total_line(7055), 7055),
]


@pytest.mark.parametrize("line,seconds", LINES)
def test_line_holds_human_duration(line, seconds):
    assert human_duration(seconds) in line
    assert not re.search(r"\b%d(\.\d+)?s\b" % seconds, line)


def test_known_renderings():
    assert "1 h 58 min" in LINES[3][0]
    assert "68 min" in LINES[4][0]


def test_report_fixture_has_no_raw_seconds():
    report = "\n".join(line for line, _ in LINES)
    assert not re.search(r"\(\d{3,}s", report)


def test_rank_tables_headed_time():
    text = SEARCH.read_text(encoding="utf-8")
    assert "| seconds |" not in text
    assert text.count("| time |") == 2
