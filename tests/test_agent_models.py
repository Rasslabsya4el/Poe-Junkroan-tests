"""Tests for #253: workers leave Opus 5. `worker-strong` runs on Sonnet 5 high, `worker` on
Sonnet 5 medium; nothing under `.claude/agents/` names Opus 5 (not Opus 5.5).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

_OPUS5_PATTERN = re.compile(r"claude-opus-5([^-]|$)|Opus 5([^.]|$)")


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    body = text[4:end]
    fields: dict[str, str] = {}
    for line in body.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_worker_strong_is_sonnet_high() -> None:
    fields = _frontmatter(AGENTS_DIR / "worker-strong.md")
    assert fields["model"] == "claude-sonnet-5-5"
    assert fields["effort"] == "high"


def test_worker_is_haiku_high() -> None:
    fields = _frontmatter(AGENTS_DIR / "worker.md")
    assert fields["model"] == "claude-haiku-5-5"
    assert fields["effort"] == "high"


def test_orch_is_sonnet_5_5_high() -> None:
    # #644: ORCH runs on Sonnet 5.5 at effort high (rollback: Opus 5.5 high).
    fields = _frontmatter(AGENTS_DIR / "orch.md")
    assert fields["model"] == "claude-sonnet-5-5"
    assert fields["effort"] == "high"


def test_brain_is_opus_5_5_high() -> None:
    # #640: the autopilot (`--agent brain`) runs on Opus 5.5 high, not Fable.
    fields = _frontmatter(AGENTS_DIR / "brain.md")
    assert fields["model"] == "claude-opus-5-5"
    assert fields["effort"] == "high"


def test_no_agent_definition_names_opus_5() -> None:
    hits = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if _OPUS5_PATTERN.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line}")
    assert hits == [], "\n".join(hits)


def test_opus5_agent_files_removed() -> None:
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert not (AGENTS_DIR / f"opus5-{level}.md").exists()


# #636 pinned the effort-* subagents to Opus 5.5; the core update a44bd78f (commit 6859cb49) removed those five
# files on purpose, so the assertion follows the new behaviour: no effort-*.md role file exists.
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def test_effort_agent_files_removed() -> None:
    for level in _EFFORT_LEVELS:
        assert not (AGENTS_DIR / f"effort-{level}.md").exists(), level


def test_researcher_find_is_haiku_5_5_medium() -> None:
    """#635: pinned by full name; the bare `haiku` alias at low is what the role ran before."""

    fields = _frontmatter(AGENTS_DIR / "researcher-find.md")
    assert fields["model"] == "claude-haiku-5-5"
    assert fields["effort"] == "medium"
