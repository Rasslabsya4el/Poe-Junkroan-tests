"""Tests for ``tools/hooks/transcript.py`` ``live_things`` (issue #311, unit 1).

Fixtures are small synthetic JSONL files copying the record shapes measured on real transcripts:
a launch is a ``tool_result`` whose text starts with a fixed phrase and names the id; an end is a
``<task-notification>`` (raw tags in ``queue-operation``/``user`` lines), a Monitor expiry notice
or a ``TaskStop`` result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools" / "hooks"))
from transcript import live_things  # noqa: E402

ZERO = {"subagent": 0, "shell": 0, "monitor": 0}


def _use(tool: str, tool_id: str, **inp) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": tool, "input": inp}]}}


def _result(tool_id: str, text, as_list: bool = False) -> dict:
    body = [{"type": "text", "text": text}] if as_list else text
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": body}]}}


def _agent(n: str) -> list[dict]:
    return [
        _use("Agent", f"t{n}", run_in_background=True, prompt="x"),
        _result(f"t{n}", f"Async agent launched successfully. (internal)\nagentId: agent{n} "
                         "(internal ID)\nThe agent is working in the background.", as_list=True),
    ]


def _bash(n: str) -> list[dict]:
    return [
        _use("Bash", f"t{n}", command="sleep 9", run_in_background=True),
        _result(f"t{n}", f"Command running in background with ID: shell{n}. Output is being "
                         "written to: /tmp/x.output. You will be notified when it completes."),
    ]


def _monitor(n: str) -> list[dict]:
    return [
        _use("Monitor", f"t{n}", command="tail -f x", timeout_ms=1800000),
        _result(f"t{n}", f"Monitor started (task mon{n}, expires in 30m unless the source ends "
                         "first; you get one notice at expiry)."),
    ]


def _notice(task_id: str, status: str, kind: str = "queue-operation") -> dict:
    text = (f"<task-notification>\n<task-id>{task_id}</task-id>\n<tool-use-id>toolu_1</tool-use-id>\n"
            f"<status>{status}</status>\n<summary>done</summary>\n</task-notification>")
    if kind == "queue-operation":
        return {"type": "queue-operation", "operation": "enqueue", "content": text}
    return {"type": "user", "message": {"role": "user", "content": text}}


def _write(tmp_path: Path, records: list[dict]) -> str:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return str(path)


def test_empty_and_missing_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert live_things(str(empty)) == ZERO
    assert live_things(str(tmp_path / "nope.jsonl")) == ZERO
    assert live_things(None) == ZERO


def test_background_agent_without_notification(tmp_path):
    assert live_things(_write(tmp_path, _agent("1")))["subagent"] == 1


def test_two_agents_one_then_both_notified(tmp_path):
    records = _agent("1") + _agent("2") + [_notice("agent1", "completed")]
    assert live_things(_write(tmp_path, records))["subagent"] == 1
    records.append(_notice("agent2", "failed", kind="user"))
    assert live_things(_write(tmp_path, records)) == ZERO


def test_running_notification_keeps_it_live(tmp_path):
    records = _agent("1") + [_notice("agent1", "running")]
    assert live_things(_write(tmp_path, records))["subagent"] == 1


def test_background_bash_and_its_notification(tmp_path):
    records = _bash("1")
    assert live_things(_write(tmp_path, records))["shell"] == 1
    records.append(_notice("shell1", "completed"))
    assert live_things(_write(tmp_path, records)) == ZERO


def test_bash_killed_by_taskstop(tmp_path):
    records = _bash("1") + [
        _use("TaskStop", "ts", task_id="shell1"),
        _result("ts", '{"message":"Successfully stopped task: shell1 (sleep 9)",'
                      '"task_id":"shell1","task_type":"local_bash"}'),
    ]
    assert live_things(_write(tmp_path, records)) == ZERO


def test_failed_taskstop_does_not_end_it(tmp_path):
    records = _bash("1") + [
        _use("TaskStop", "ts", task_id="shell1"),
        _result("ts", "No task found with ID: shell1"),
    ]
    assert live_things(_write(tmp_path, records))["shell"] == 1


def test_monitor_started_and_ended(tmp_path):
    records = _monitor("1")
    assert live_things(_write(tmp_path, records))["monitor"] == 1
    expiry = {"type": "queue-operation", "operation": "enqueue", "content": (
        "<task-notification>\n<task-id>mon1</task-id>\n<summary>Monitor event: \"x\"</summary>\n"
        "<event>[Monitor expired after 30m with no events delivered. Re-arm it if you still need "
        "the watch.]</event>\n</task-notification>")}
    assert live_things(_write(tmp_path, records + [expiry])) == ZERO


def test_monitor_event_is_not_an_end(tmp_path):
    event = {"type": "queue-operation", "operation": "enqueue", "content": (
        "<task-notification>\n<task-id>mon1</task-id>\n<summary>Monitor event: \"x\"</summary>\n"
        "<event>REPORT 20:19: done</event>\n</task-notification>")}
    assert live_things(_write(tmp_path, _monitor("1") + [event]))["monitor"] == 1


def test_foreground_agent_and_bash_are_not_counted(tmp_path):
    records = [
        _use("Agent", "a", prompt="x"),
        _result("a", "The report of a finished foreground agent.", as_list=True),
        _use("Bash", "b", command="ls"),
        _result("b", "file1\nfile2"),
    ]
    assert live_things(_write(tmp_path, records)) == ZERO


def test_phrase_quoted_inside_other_output_is_not_a_launch(tmp_path):
    records = [
        _use("Bash", "b", command="grep -n 'Command running in background' t.jsonl"),
        _result("b", "12:{... Command running in background with ID: shellX. ...}"),
    ]
    assert live_things(_write(tmp_path, records)) == ZERO


def test_mixed_kinds(tmp_path):
    records = _agent("1") + _bash("1") + _monitor("1") + [_notice("shell1", "completed")]
    assert live_things(_write(tmp_path, records)) == {"subagent": 1, "shell": 0, "monitor": 1}
