"""#692: a foreground subagent is finished once the parent holds the tool_result for its toolUseId."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from tools.agentops import monitor  # noqa: E402

NOW = datetime(2026, 10, 9, 21, 15, 0, tzinfo=timezone.utc)
TOOL_USE = "toolu_01PdVV6vucz3zxRY34evJtu7"
PRICES: dict = {}


def _sub(tmp: Path, name: str, shape: str, tool_use_id: str = TOOL_USE) -> tuple[Path, dict]:
    path = tmp / f"agent-{name}.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Trace one PoB ticket run"},
         "timestamp": "2026-10-09T19:35:27Z"},
        {"type": "assistant", "message": {"id": f"m_{name}", "model": "claude-sonnet-5-5",
         "usage": {"input_tokens": 10, "output_tokens": 5}}, "timestamp": "2026-10-09T19:35:27Z"},
        {"type": "assistant", "message": {"id": f"m2_{name}", "model": "claude-sonnet-5-5",
         "usage": {"input_tokens": 10, "output_tokens": 5}}, "timestamp": "2026-10-09T19:39:11Z"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    meta = {"agentId": name, "agentType": "x", "description": "Trace", "requestShape": shape,
            "toolUseId": tool_use_id}
    return path, meta


def _row(tmp: Path, name: str, shape: str, *, answered: set[str], completed: set[str] = frozenset()) -> dict:
    path, meta = _sub(tmp, name, shape)
    return monitor.build_subagent_row(path, meta, prices=PRICES, completed_ids=set(completed),
                                      now=NOW, answered_ids=answered)


def test_foreground_with_result_is_finished(tmp_path):
    row = _row(tmp_path, "fg1", "foreground", answered={TOOL_USE})
    assert row["running"] is False
    assert row["duration_seconds"] == 3 * 60 + 44
    assert row["duration_human"] == monitor.human_duration(224)


def test_foreground_without_result_runs(tmp_path):
    row = _row(tmp_path, "fg2", "foreground", answered=set())
    assert row["running"] is True
    assert row["duration_seconds"] == (NOW - datetime(2026, 10, 9, 19, 35, 27, tzinfo=timezone.utc)).total_seconds()


def test_background_launched_answer_only_runs(tmp_path):
    row = _row(tmp_path, "bg1", "background", answered={TOOL_USE})
    assert row["running"] is True


def test_background_notification_completed(tmp_path):
    row = _row(tmp_path, "bg2", "background", answered={TOOL_USE}, completed={"bg2"})
    assert row["running"] is False


def test_answered_tool_use_ids_scans_parent_once_per_mtime(tmp_path):
    parent = tmp_path / "sess.jsonl"
    parent.write_text(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": TOOL_USE, "content": "ok"}]}}), encoding="utf-8")
    assert monitor.answered_tool_use_ids(parent) == {TOOL_USE}
    assert monitor.answered_tool_use_ids(parent) is monitor.answered_tool_use_ids(parent)
