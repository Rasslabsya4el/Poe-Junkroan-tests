"""The hand-off rule reads as one fenced start line (issue #1127, owner's word 2026-10-15 in #1086).

A read-only check over the three rule files that describe a new-chat hand-off. Neither starts PoB.

(a) None of the retired phrasings remains: the follow-up "under 20 lines", the "Контекст на" context block,
    and "never the opening line alone" (the follow-up that was a paste block of many lines).
(b) Each hand-off-describing file names the one-line form: it contains "one start line" and "fenced".
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF_FILES = (
    ROOT / "docs" / "agents" / "sessions.md",
    ROOT / "docs" / "agents" / "workflow.md",
    ROOT / "docs" / "agents" / "brain.md",
    ROOT / "docs" / "agents" / "local" / "sessions.md",
)
RETIRED_PHRASES = ("under 20 lines", "Контекст на", "never the opening line alone")
REQUIRED_PHRASES = ("one start line", "fenced")


def _text(path: Path) -> str:
    # Phrases wrap across lines in the rule files; compare on words, not on line breaks.
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize("path", HANDOFF_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
@pytest.mark.parametrize("phrase", RETIRED_PHRASES)
def test_retired_handoff_phrase_is_gone(path: Path, phrase: str) -> None:
    hits = _text(path).count(phrase)
    assert hits == 0, f"{path.relative_to(ROOT)}: {hits} hit(s) of {phrase!r}"


@pytest.mark.parametrize("path", HANDOFF_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_handoff_file_names_the_one_line_form(path: Path, phrase: str) -> None:
    assert phrase in _text(path), f"{path.relative_to(ROOT)} lacks {phrase!r}"
