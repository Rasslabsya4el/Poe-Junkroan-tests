"""#860: the autopilot's protocol checks the result, not the report (docs test, no PoB)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTOPILOT = ROOT / "docs" / "agents" / "autopilot.md"
LOCAL = ROOT / "docs" / "agents" / "local" / "autopilot.md"

HEADING = "## Check the result, not the report"
# The five rules of #860, each as phrases the section must carry.
RULES = {
    1: ("Accepting a close", "reruns the ticket's own test", "A closing comment re-read is never the check", "reopens the ticket"),
    2: ("The whole, not the rows", "every difference from the previous state", "asked for by a ticket row", "sent back"),
    3: ("Before the owner is asked", "never the first look", "count of differences left", "once per pass"),
    4: ("A proof must draw what he sees", "judges the code, never the look", "real surface"),
    5: ("Parked tickets are read by state", "At every session start", "queue state, pid alive, log's last line", "the same session"),
}


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _section() -> str:
    text = AUTOPILOT.read_text(encoding="utf-8")
    assert HEADING in text, "the section is missing"
    body = text.split(HEADING, 1)[1]
    return " ".join(re.split(r"\n## ", body, maxsplit=1)[0].split())


def test_section_carries_the_five_rules():
    section = _section()
    for number, phrases in RULES.items():
        for phrase in phrases:
            assert phrase in section, f"rule {number} lacks: {phrase}"


def test_section_sits_after_orch_works_the_tickets():
    text = AUTOPILOT.read_text(encoding="utf-8")
    assert text.index("## ORCH works the tickets, never you") < text.index(HEADING) < text.index("## Provisional decisions")


def test_old_review_line_points_at_the_section_and_waiting_names_rule_5():
    text = _flat(AUTOPILOT)
    assert "Check the result, not the report" in text.split(HEADING)[0]
    waiting = text[text.index("- `waiting:` the tickets"):]
    assert "read by state" in waiting[:600]


def test_core_section_names_nothing_of_this_repo():
    section = _section()
    for word in ("PoB", "monitor", "#837", "#839", "Junkroan", "junkroan"):
        assert word not in section, word


def test_local_file_holds_the_two_cases_with_issue_and_date():
    text = _flat(LOCAL)
    assert "#837" in text and "#839" in text
    assert text.count("2026-10-11") >= 2
