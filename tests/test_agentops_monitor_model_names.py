"""#643: the monitor names any Claude model id by rule; an unreadable new id fails here, not in the pane."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.agentops import monitor

_MODEL_FIELD = re.compile(r'"model":\s*"(claude-[^"]+)"')


@pytest.mark.parametrize("model_id, expected", [
    ("claude-haiku-5-5", "Haiku 5.5"),
    ("claude-opus-6-0", "Opus 6.0"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-opus-5", "Opus 5"),
    ("claude-sonnet-5", "Sonnet 5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("claude-fable-5-1", "Fable 5.1"),
    ("sonnet", "Sonnet"),
    ("<synthetic>", "<synthetic>"),
    ("gpt-6", "gpt-6"),
    (None, None),
])
def test_model_display_name(model_id, expected):
    assert monitor.model_display_name(model_id) == expected


def _recent_model_ids(projects_dir: Path, files: int = 40, tail_bytes: int = 200_000) -> set[str]:
    """The raw `claude-*` model ids of this repo's most recent transcripts (sessions and their
    subagents), read from each file's tail: the ids the monitor's model column will show."""

    paths = sorted(projects_dir.rglob("*.jsonl"), key=lambda q: q.stat().st_mtime, reverse=True)[:files]
    ids: set[str] = set()
    for path in paths:
        with path.open("rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(max(0, size - tail_bytes))
            text = fh.read().decode("utf-8", errors="replace")
        ids.update(_MODEL_FIELD.findall(text))
    return ids


def test_recent_claude_model_ids_are_named():
    """The early warning (#643): a new model's id that the rule cannot read fails here, in the test
    run, before it shows raw in the pane. `claude.exe agents --json` carries no model, so the ids
    come from the newest transcripts under the monitor's own projects dir."""

    projects_dir = Path(monitor.DEFAULT_PROJECTS_DIR)
    if not projects_dir.is_dir():
        pytest.skip(f"no projects dir {projects_dir}")
    ids = _recent_model_ids(projects_dir)
    if not ids:
        pytest.skip("no claude- model ids in the recent transcripts")
    raw = sorted(i for i in ids if monitor.model_display_name(i) == i)
    assert raw == [], f"model ids not readable by the rule: {raw}"
