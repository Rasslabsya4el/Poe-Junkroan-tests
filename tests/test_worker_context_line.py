"""Tests for tools/hooks/worker_context_line.py (issue #186).

Cases run the script as a real subprocess (stdin -> stdout), matching how
Claude Code invokes a hook.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from timing_bound import bound
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "worker_context_line.py"


@pytest.fixture(autouse=True)
def _hook_log(tmp_path, monkeypatch):
    """Keep every test's log lines out of the real var/agentops log."""
    path = tmp_path / "worker_context_line.log"
    monkeypatch.setenv("AGENTOPS_HOOK_LOG", str(path))
    return path


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=dict(os.environ),
    )


def _write_transcript(path: Path, last_usage_sum: int | None) -> None:
    """A small fixture transcript whose last assistant usage sums to
    ``last_usage_sum``. ``None`` writes a transcript with no usage entry at
    all (only non-assistant lines)."""
    lines = [{"type": "user", "message": {"content": "hi"}}]
    if last_usage_sum is not None:
        lines.append(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 1,
                        "cache_creation_input_tokens": 49,
                        "cache_read_input_tokens": last_usage_sum - 50,
                    }
                },
            }
        )
        lines.append({"type": "user", "message": {"content": "go on"}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _subagent_layout(tmp_path: Path, session_id: str, agent_id: str) -> tuple[Path, Path]:
    """<projects>/<session_id>.jsonl (main) + <projects>/<session_id>/subagents/agent-<id>.jsonl."""
    projects = tmp_path / "projects"
    main_transcript = projects / f"{session_id}.jsonl"
    main_transcript.parent.mkdir(parents=True, exist_ok=True)
    main_transcript.write_text("", encoding="utf-8")
    subagent_transcript = projects / session_id / "subagents" / f"agent-{agent_id}.jsonl"
    return main_transcript, subagent_transcript


def test_under_the_line_no_output(tmp_path):
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, 149999)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_past_the_line_prints_context_in_k(tmp_path):
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, 219815)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "220k" in result.stdout
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_no_usage_entry_no_output(tmp_path):
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, None)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_transcript_path_already_under_subagents(tmp_path):
    """The transcript_path payload key is itself the subagent's own file."""
    _, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, 219815)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(subagent_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "220k" in result.stdout


def test_transcript_path_built_from_session_id_and_agent_id(tmp_path):
    """transcript_path is the parent's own transcript: the subagent's file is
    derived from the session id stem + agent_id."""
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess2", "b7")
    _write_transcript(subagent_transcript, 150000)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "b7",
        "agent_type": "worker-strong",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "150k" in result.stdout


def test_missing_subagent_file_no_output(tmp_path):
    main_transcript, _ = _subagent_layout(tmp_path, "sess3", "missing")
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "missing",
        "agent_type": "worker",
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_bad_stdin_exits_zero_no_output():
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_log_line_written_under_and_past_line(tmp_path, _hook_log):
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, 219815)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    _run_hook(payload)
    row = json.loads(_hook_log.read_text(encoding="utf-8").splitlines()[-1])
    assert (row["agent_id"], row["agent_type"], row["context_k"], row["told"]) == (
        "a1",
        "worker",
        220,
        True,
    )


def test_log_line_written_when_no_usage_entry(tmp_path, _hook_log):
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sess1", "a1")
    _write_transcript(subagent_transcript, None)
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(main_transcript),
        "agent_id": "a1",
        "agent_type": "worker",
    }
    _run_hook(payload)
    row = json.loads(_hook_log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["told"] is False
    assert row["context_k"] is None


def test_timing_on_5mb_fixture_transcript(tmp_path):
    """One hook call on a 5 MB fixture transcript, timed in-process."""
    main_transcript, subagent_transcript = _subagent_layout(tmp_path, "sessbig", "big1")
    subagent_transcript.parent.mkdir(parents=True, exist_ok=True)
    filler = {"type": "user", "message": {"content": "x" * 500}}
    filler_line = json.dumps(filler)
    n_filler_lines = max(1, (5 * 1024 * 1024) // (len(filler_line) + 1))
    with open(subagent_transcript, "w", encoding="utf-8") as f:
        for _ in range(n_filler_lines):
            f.write(filler_line + "\n")
        f.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": 1,
                            "cache_creation_input_tokens": 49,
                            "cache_read_input_tokens": 219765,
                        }
                    },
                }
            )
            + "\n"
        )
    size_mb = subagent_transcript.stat().st_size / (1024 * 1024)
    assert size_mb >= 4.5

    sys.path.insert(0, str(PROJECT_ROOT / "tools" / "hooks"))
    import worker_context_line  # noqa: E402

    payload = {
        "transcript_path": str(main_transcript),
        "agent_id": "big1",
        "agent_type": "worker",
    }
    start = time.perf_counter()
    output = worker_context_line.run(payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"worker_context_line.run on a {size_mb:.1f} MB transcript: {elapsed_ms:.1f} ms")
    # bound = max(floor, factor x a CPU spin timed here): load that slows the spin slows the call (#824)
    bound_ms = bound(1.0, 6.0) * 1000
    assert elapsed_ms < bound_ms, f"in-process call took {elapsed_ms:.1f} ms, bound {bound_ms:.0f} ms"
    assert output is not None
    assert "220k" in output["hookSpecificOutput"]["additionalContext"]
