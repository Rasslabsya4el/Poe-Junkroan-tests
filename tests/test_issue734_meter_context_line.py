"""#734: the context meter caps T at the context line and drops an ended session from the live ones."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import token_meter as tm  # noqa: E402

LINE = 150_000
SINCE = datetime(2026, 10, 10, tzinfo=timezone.utc)
UNTIL = datetime(2026, 10, 11, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 10, 12, 3, tzinfo=timezone.utc)


def _transcript(path: Path, title: str, contexts: list[int], claims: list[int], hour: int,
                last_minute: int = 2) -> None:
    lines = [{"type": "custom-title", "customTitle": title}]
    for i, ctx in enumerate(contexts):
        content = [{"type": "text", "text": "x"}]
        last = i == len(contexts) - 1
        if i < len(claims):
            content.append({"type": "tool_use", "id": f"t{i}", "name": "Bash",
                            "input": {"command": f"gh issue edit {claims[i]} --add-assignee @me"}})
        minute = last_minute if last else i
        lines.append({"type": "assistant", "timestamp": f"2026-10-10T{hour:02d}:{minute:02d}:00Z",
                      "message": {"id": f"{path.stem}-{i}", "model": "claude-opus-5-5", "content": content,
                                  "usage": {"input_tokens": ctx, "cache_read_input_tokens": 0,
                                            "cache_creation_input_tokens": 0, "output_tokens": 1}}})
        if i < len(claims):
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok", "is_error": False}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def _finished(tmp_path: Path) -> None:
    # B = 33.9k-ish, X = 22.6k-ish: two finished sessions, 10:00 hour, long ago
    _transcript(tmp_path / "f1.jsonl", "orch #1", [33_900, 56_500], [1], 8, last_minute=30)
    _transcript(tmp_path / "f2.jsonl", "orch #2", [33_900, 56_500], [2], 9, last_minute=30)


def _render(tmp_path: Path, **kw) -> str:
    return tm.render_orch_threshold(tmp_path, since=SINCE, until=UNTIL, now=NOW, **kw)


def test_row1_row2_over_the_line(tmp_path: Path):
    _finished(tmp_path)
    _transcript(tmp_path / "live1.jsonl", "orch #9", [33_900] + [100_000] * 7 + [166_300], list(range(100, 109)), 12)
    report = _render(tmp_path, context_line=LINE)
    assert "T(9) = 150.0k: over the context line 150.0k: take nothing new, finish or park, end" in report
    assert "N=6 150.0k" in report
    assert "169" not in report and "237" not in report


def test_row3_under_t_unchanged(tmp_path: Path):
    _finished(tmp_path)
    _transcript(tmp_path / "live3.jsonl", "orch #9", [33_900, 60_000], [100, 101], 12)
    report = _render(tmp_path, context_line=LINE)
    assert "context 60.0k, 2 issue(s) taken, T(2) = 79.1k: under T" in report or "T(2) = 79.2k: under T" in report


def test_row4_over_t_unchanged(tmp_path: Path):
    _finished(tmp_path)
    _transcript(tmp_path / "live4.jsonl", "orch #9", [33_900, 87_900], [100, 101], 12)
    report = _render(tmp_path, context_line=LINE)
    assert "T(2) = 79.1k: over T: take nothing new, finish or park, end" in report or \
        "T(2) = 79.2k: over T: take nothing new, finish or park, end" in report


def test_row5_ended_session_is_not_live(tmp_path: Path):
    _finished(tmp_path)
    _transcript(tmp_path / "d372708f.jsonl", "orch #9", [33_900] + [100_000] * 7 + [166_300], list(range(100, 109)), 12)
    log = "2026-10-10 10:58:54 orch-dispatch: orch d372708f ended (done): #727 closed\n"
    assert "live ORCH d372708f" in _render(tmp_path, context_line=LINE)
    report = _render(tmp_path, context_line=LINE, ended_ids=tm.parse_dispatch_ended(log))
    assert "live ORCH" not in report
