"""#1082 unit 2: the brain's protocol holds the five-step procedure "update the Pocock skills"."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "docs" / "agents" / "brain.md"
HEADING = "## Updating the Pocock skills"
TRIGGER = "обнови Покок скиллы"
CHECK_COMMAND = "core pocock-check"
MAX_LINES = 14


def _section() -> list[str]:
    """The heading and the lines under it, up to the next level-2 heading."""
    lines = BRAIN.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == HEADING]
    assert len(starts) == 1, f"expected one '{HEADING}' heading in brain.md, found {len(starts)}"
    body: list[str] = []
    for line in lines[starts[0] + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return [HEADING, *body]


def test_section_heading_exists():
    assert _section()[0] == HEADING


def test_trigger_phrase_is_in_section():
    assert TRIGGER in "\n".join(_section())


def test_five_steps_numbered_in_order():
    numbers = []
    for line in _section():
        match = re.match(r"^\s*(\d)[.)]\s", line)
        if match:
            numbers.append(int(match.group(1)))
    assert numbers == [1, 2, 3, 4, 5], f"step numbers in section: {numbers}"


def test_section_names_the_check_command():
    assert CHECK_COMMAND in "\n".join(_section())


def test_section_is_short():
    non_empty = [line for line in _section() if line.strip()]
    assert len(non_empty) <= MAX_LINES, f"section has {len(non_empty)} non-empty lines, limit {MAX_LINES}"
