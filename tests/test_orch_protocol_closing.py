"""ORCH's closing comment rules (issue #268): the core protocol holds the four rules, the role file
points to them, and the old one-sentence rule is gone."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "agents" / "orch.md"
ROLE_FILE = ROOT / ".claude" / "agents" / "orch.md"


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_protocol_holds_the_four_closing_rules():
    text = _flat(PROTOCOL)
    rules = [
        # 1: every row with its number, command and commit
        "one line per row: the number, the exact command that printed it, and the commit it was read on",
        # 2: read on main after the merge, a branch-only number names the branch's commit
        "The numbers are read on `main` after the merge; a number that can only be read on the branch says so "
        "and names the branch's commit",
        # 3: an unmeasured row says so; "tests pass" alone is no answer
        'A row no command measured is written "not measured" with the reason; "tests pass" without a command '
        "and a count answers no row",
        # 4: an own piece is named before it starts with its expected turns, and closed with the turns it took
        "A piece ORCH works itself is named in the issue's checkpoint before it starts: the piece and the own "
        "turns it expects; the closing comment gives the turns it took",
    ]
    found = [rule for rule in rules if rule in text]
    assert len(found) == 4, [rule for rule in rules if rule not in text]


def test_old_closing_sentence_is_replaced():
    assert "Close the issue with its numbers in the closing comment" not in _flat(PROTOCOL)


def test_role_file_points_to_the_closing_rules():
    bullets = [line for line in ROLE_FILE.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
    pointing = [line for line in bullets if '"Closing"' in line]
    assert len(pointing) == 1
