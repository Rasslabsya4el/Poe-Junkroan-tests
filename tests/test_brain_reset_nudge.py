"""Tests for tools/hooks/brain_reset_nudge.py (issues #93, #196).

Reproduces the issue's numbers table. Cases 1-5 run the script as a real
subprocess (stdin -> stdout, matching how Claude Code invokes a hook). Case 6
additionally times the UserPromptSubmit path in-process, per the issue
("under 100 ms ... time the function in-process, not python startup").

#196's ``PostToolUse`` cases read the tool call's own output (``tool_response``
stdout/stderr) for gh's own success line, never the command text: a close is
credited only when that line names the issue, matching
``scripts/cost_levers.py`` ``session_gh_closes``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from timing_bound import bound

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "brain_reset_nudge.py"
GH_STUB = PROJECT_ROOT / "tests" / "fixtures" / "gh_stub.py"
GH_COMMENT_183_FIXTURE = (
    PROJECT_ROOT / "tests" / "fixtures" / "brain_reset_nudge" / "gh_issue_comment_183.json"
)


def _gh_close_output(*ns: int) -> str:
    """gh's own success line for each issue number, the shape ``CLOSED_OUTPUT_RE`` reads."""
    return "\n".join(f"✓ Closed issue Rasslabsya4el/Poe-Junkroan#{n} (Not Planned)" for n in ns)

sys.path.insert(0, str(PROJECT_ROOT))
from tools.agentops.core_settings import load as _load_settings  # noqa: E402

#: the brain chat's title (config/orchestration.json "brain_chat_title"): a brain payload carries it as
#: ``session_title``, else the hook reads the session as role ``unknown`` and stays silent (#1230).
BRAIN_TITLE = _load_settings()["brain_chat_title"]

REAL_TRANSCRIPT = (
    Path.home() / ".claude" / "projects" / _load_settings()["claude_projects_dir"] /
    "11243e8a-5542-4d2d-8cdf-1ff2b3cdd3de.jsonl"
)

sys.path.insert(0, str(PROJECT_ROOT / "tools" / "hooks"))
import brain_reset_nudge  # noqa: E402


@pytest.fixture(autouse=True)
def _hook_log(tmp_path, monkeypatch):
    """Keep every test's log lines out of the real var/agentops log."""
    path = tmp_path / "brain_nudge.log"
    monkeypatch.setenv("AGENTOPS_HOOK_LOG", str(path))
    return path


def _run_hook(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # A load that starts after the spin is timed is not seen by `bound`; one retry with a freshly
    # timed, doubled bound covers it (#870). A hook that never returns still ends: two bounded tries.
    for attempt in (1, 2):
        try:
            return subprocess.run(
                [sys.executable, str(HOOK_SCRIPT)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=bound(10.0, 66.0) * attempt,
                env=full_env,
            )
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise


def _write_transcript(tmp_path: Path, last_usage_sum: int, head: dict | None = None) -> Path:
    """Write a small fixture transcript whose last assistant usage sums to
    ``last_usage_sum``. Includes an earlier, unrelated assistant usage and
    non-assistant lines so the "last" logic is exercised. ``head`` extra keys
    go on the first line (an ORCH transcript carries sessionKind/agentSetting)."""
    lines = [
        {"type": "user", "message": {"content": "hi"}, **(head or {})},
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 1,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 4000,
                }
            },
        },
        {"type": "user", "message": {"content": "go on"}},
        {"type": "system", "subtype": "stop_hook_summary"},
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 408,
                    "cache_read_input_tokens": last_usage_sum - 2 - 408,
                }
            },
        },
    ]
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def test_context_reminder_at_219815(tmp_path):
    transcript = _write_transcript(tmp_path, 219815)
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript), "session_title": BRAIN_TITLE}
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "220k" in result.stdout


def test_reminder_at_150000(tmp_path):
    transcript = _write_transcript(tmp_path, 150000)
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript), "session_title": BRAIN_TITLE}
    result = _run_hook(payload)
    assert result.returncode == 0
    assert "150k" in result.stdout


def test_no_reminder_at_149999(tmp_path):
    transcript = _write_transcript(tmp_path, 149999)
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript), "session_title": BRAIN_TITLE}
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_wayfinder_ticket_close_names_issue():
    """Acceptance 2: gh's success line in the output -> 1 nudge, naming that n."""
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_title": BRAIN_TITLE,
        "tool_input": {"command": "gh issue close 84 --comment x"},
        "tool_response": {"stdout": _gh_close_output(84), "stderr": ""},
    }
    env = {
        "AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}",
        "AGENTOPS_HOOK_GH_LABELS": "wayfinder:task",
    }
    result = _run_hook(payload, env=env)
    assert result.returncode == 0
    assert "#84" in result.stdout


def test_ready_for_agent_close_no_output():
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_title": BRAIN_TITLE,
        "tool_input": {"command": "gh issue close 81"},
        "tool_response": {"stdout": _gh_close_output(81), "stderr": ""},
    }
    env = {
        "AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}",
        "AGENTOPS_HOOK_GH_LABELS": "ready-for-agent",
    }
    result = _run_hook(payload, env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_real_comment_quoting_close_commands_raises_nothing(tmp_path, _hook_log):
    """Acceptance 1: the real `gh issue comment 183` call whose body quotes `gh issue
    close 84`, `81` and `93` as text. 0 nudges, one skip line in the log."""
    fixture = json.loads(GH_COMMENT_183_FIXTURE.read_text(encoding="utf-8"))
    assert "gh issue close 84" in fixture["tool_input"]["command"]
    assert "gh issue close 81" in fixture["tool_input"]["command"]
    assert "gh issue close 93" in fixture["tool_input"]["command"]
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "brain-183",
        "session_title": BRAIN_TITLE,
        **fixture,
    }
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    lines = _hook_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["action"] == "skipped"
    assert row["event"] == "PostToolUse"


def test_close_command_with_no_success_line_raises_nothing():
    """Acceptance 3: the call failed (no success line in the output) -> 0 nudges."""
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_title": BRAIN_TITLE,
        "tool_input": {"command": "gh issue close 84"},
        "tool_response": {"stdout": "", "stderr": "GraphQL: Could not resolve to an issue (issue)"},
    }
    env = {
        "AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}",
        "AGENTOPS_HOOK_GH_LABELS": "wayfinder:task",
    }
    result = _run_hook(payload, env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_one_call_closing_two_wayfinder_tickets_names_both():
    """Acceptance 4: one call, two success lines, both wayfinder -> one nudge naming both."""
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "session_title": BRAIN_TITLE,
        "tool_input": {"command": "gh issue close 84 && gh issue close 93"},
        "tool_response": {"stdout": _gh_close_output(84, 93), "stderr": ""},
    }
    env = {
        "AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}",
        "AGENTOPS_HOOK_GH_LABELS": "wayfinder:task",
    }
    result = _run_hook(payload, env=env)
    assert result.returncode == 0
    assert "#84" in result.stdout
    assert "#93" in result.stdout
    # exactly one nudge (one hookSpecificOutput JSON object, one line of output)
    assert len(result.stdout.strip().splitlines()) == 1


def test_brain_nudge_is_logged(tmp_path, _hook_log):
    transcript = _write_transcript(tmp_path, 219815)
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript), "session_id": "b1",
               "session_title": BRAIN_TITLE}
    result = _run_hook(payload)
    assert "220k" in result.stdout
    row = json.loads(_hook_log.read_text(encoding="utf-8").splitlines()[-1])
    assert (row["session"], row["action"], row["context_k"]) == ("b1", "nudged", 220)


def test_orch_background_session_is_skipped_and_logged(tmp_path, _hook_log):
    transcript = _write_transcript(tmp_path, 219815, head={"sessionKind": "bg", "agentSetting": "orch"})
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript), "session_id": "o1"}
    result = _run_hook(payload)
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    row = json.loads(_hook_log.read_text(encoding="utf-8").splitlines()[-1])
    assert (row["session"], row["action"], row["why"]) == ("o1", "skipped", "background session")


def test_orch_closing_a_wayfinder_ticket_is_skipped(tmp_path):
    transcript = _write_transcript(tmp_path, 1000, head={"sessionKind": "bg", "agentSetting": "orch"})
    payload = {
        "hook_event_name": "PostToolUse",
        "transcript_path": str(transcript),
        "tool_input": {"command": "gh issue close 84"},
        "tool_response": {"stdout": _gh_close_output(84), "stderr": ""},
    }
    env = {"AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}", "AGENTOPS_HOOK_GH_LABELS": "wayfinder:task"}
    result = _run_hook(payload, env=env)
    assert result.stdout.strip() == ""


def test_subagent_agent_type_is_skipped():
    payload = {
        "hook_event_name": "PostToolUse",
        "agent_type": "worker",
        "tool_input": {"command": "gh issue close 84"},
        "tool_response": {"stdout": _gh_close_output(84), "stderr": ""},
    }
    env = {"AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}", "AGENTOPS_HOOK_GH_LABELS": "wayfinder:task"}
    result = _run_hook(payload, env=env)
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


@pytest.mark.skipif(
    not REAL_TRANSCRIPT.is_file(),
    reason=f"real transcript not present at {REAL_TRANSCRIPT}",
)
def test_real_transcript_fast_and_correct(capsys):
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "transcript_path": str(REAL_TRANSCRIPT),
        "session_title": BRAIN_TITLE,
    }
    start = time.perf_counter()
    output = brain_reset_nudge.handle_user_prompt_submit(payload)
    elapsed_s = time.perf_counter() - start
    # 0.1 s on a quiet machine, else 0.5 x a CPU spin timed here (0.15 s quiet) scales the bound when the machine is
    # busy, since a load that slows the spin slows the call too (#824, same shape as #823).
    bound_s = bound(0.1, 0.5)
    assert elapsed_s < bound_s, f"in-process call took {elapsed_s * 1000:.1f} ms, bound {bound_s * 1000:.0f} ms"
    assert output is not None
    assert "220k" in output["hookSpecificOutput"]["additionalContext"]

    # Also report (not assert) the subprocess wall time, for information.
    sub_start = time.perf_counter()
    result = _run_hook(payload)
    sub_elapsed_s = time.perf_counter() - sub_start
    assert result.returncode == 0
    assert "220k" in result.stdout
    print(f"subprocess wall time on real transcript: {sub_elapsed_s * 1000:.0f} ms")


# ---- #311: three texts by context size and by what of the session is still live ----

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
from test_hooks_transcript_live import _agent, _bash, _monitor, _notice  # noqa: E402


def _settings_file(tmp_path: Path, line: int, ceiling: int) -> dict:
    """Env pointing the hook at a copy of the real settings with other sizes (one way, every test)."""
    data = dict(_load_settings())
    data.update(context_line=line, context_ceiling=ceiling)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"AGENTOPS_HOOK_SETTINGS": str(path)}


def _transcript_with(tmp_path: Path, n: int, records: list[dict], head: dict | None = None) -> Path:
    """`_write_transcript` plus launch/notification records placed before the last usage."""
    base = _write_transcript(tmp_path, n, head)
    rows = base.read_text(encoding="utf-8").splitlines()
    extra = [json.dumps(r) for r in records]
    base.write_text("\n".join(rows[:-1] + extra + rows[-1:]) + "\n", encoding="utf-8")
    return base


def _nudge(tmp_path: Path, n: int, records=(), sizes=(150000, 200000), head=None,
           payload_extra=None, brain=True) -> str:
    env = _settings_file(tmp_path, *sizes)
    transcript = _transcript_with(tmp_path, n, list(records), head)
    payload = {"hook_event_name": "UserPromptSubmit", "transcript_path": str(transcript),
               **(payload_extra or {})}
    if brain:
        # the brain title the test's own settings file names (#1230); the ORCH / subagent cases pass brain=False
        settings_path = Path(env["AGENTOPS_HOOK_SETTINGS"])
        payload["session_title"] = json.loads(settings_path.read_text(encoding="utf-8"))["brain_chat_title"]
    result = _run_hook(payload, env=env)
    assert result.returncode == 0
    out = result.stdout.strip()
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def _kind(text: str) -> str:
    if not text:
        return "none"
    if "wait for them" in text:
        return "wait"
    return "ceiling" if "do nothing but the hand-off" in text else "line"


def _rows(_hook_log) -> list[dict]:
    return [json.loads(x) for x in _hook_log.read_text(encoding="utf-8").splitlines() if x]


SIZE_SETS = [((150000, 200000), (149999, 150000, 199999, 200000)),
             ((100000, 120000), (99999, 100000, 119999, 120000))]
NOTHING = ["none", "line", "line", "ceiling"]


def test_311_row1_nothing_live(tmp_path):
    for sizes, ns in SIZE_SETS:
        got = [_kind(_nudge(tmp_path, n, sizes=sizes)) for n in ns]
        assert got == NOTHING
    assert "150k" in _nudge(tmp_path, 150000)


def test_311_row2_live_subagents(tmp_path):
    for sizes, ns in SIZE_SETS:
        one = [_nudge(tmp_path, n, _agent("1"), sizes) for n in ns]
        assert [_kind(t) for t in one] == ["none", "wait", "wait", "wait"]
        assert all("1 thing(s) of this session live" in t and "no hand-off yet" in t for t in one[1:])
        assert "Start nothing new" in one[3] and "Start nothing new" not in one[1]
        two = [_nudge(tmp_path, n, _agent("1") + _agent("2"), sizes) for n in ns]
        assert all("2 thing(s) of this session live (2 subagent(s)" in t for t in two[1:])
        done = _agent("1") + _agent("2") + [_notice("agent1", "completed"), _notice("agent2", "completed")]
        assert [_kind(_nudge(tmp_path, n, done, sizes)) for n in ns] == NOTHING


def test_311_row3_live_shell_and_monitor(tmp_path):
    for records, label in ((_bash("1"), "1 background shell(s)"), (_monitor("1"), "1 monitor(s)")):
        for sizes, ns in SIZE_SETS:
            got = [_nudge(tmp_path, n, records, sizes) for n in ns]
            assert [_kind(t) for t in got] == ["none", "wait", "wait", "wait"]
            assert all("1 thing(s) of this session live" in t and label in t for t in got[1:])


def test_311_row4_no_limit_word(tmp_path):
    texts = [_nudge(tmp_path, n, r) for n in (150000, 200000) for r in ((), _agent("1"))]
    for t in texts:
        assert "limit" not in t.lower()
    assert "context line" in texts[0] and "context ceiling" in texts[2]
    import ast
    tree = ast.parse(HOOK_SCRIPT.read_text(encoding="utf-8"))
    strings = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not [s for s in strings if "limit" in s.lower()]


def test_1086_line_reminder_names_the_copy_block(tmp_path):
    text = _nudge(tmp_path, 160000)
    assert _kind(text) == "line"
    assert "the reply is the hand-off, ending with one ```text copy block that holds only the next chat's start line." in text


def test_1086_reopened_first_action_goes_into_the_copy_line(tmp_path):
    """#1086 (reopened): what the next chat must do first is in the copy line's arguments, in both
    reminder texts (the line one and the ceiling one), never a separate sentence in prose."""
    sentence = "What the next chat must do first goes into that same line as its arguments, never a separate sentence in prose."
    assert sentence in _nudge(tmp_path, 160000)
    assert sentence in _nudge(tmp_path, 210000)


def test_311_row5_not_brain_and_log_rows(tmp_path, _hook_log):
    assert _nudge(tmp_path, 210000, head={"sessionKind": "bg"}, brain=False) == ""
    assert _nudge(tmp_path, 210000, payload_extra={"agent_type": "worker"}, brain=False) == ""
    assert [r["action"] for r in _rows(_hook_log)] == ["skipped", "skipped"]
    _nudge(tmp_path, 160000)
    _nudge(tmp_path, 210000, _agent("1"))
    _nudge(tmp_path, 210000)
    nudged = [r for r in _rows(_hook_log) if r["action"] == "nudged"]
    assert [(r["text"], r["live"], r["context_k"]) for r in nudged] == [
        ("line", 0, 160), ("wait", 1, 210), ("ceiling", 0, 210)]
