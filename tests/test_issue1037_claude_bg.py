"""#1037 protocol 3: `claude --bg` argv, session-id regex, start / list / stop live in one module
(`tools/agentops/claude_bg.py`); the dispatcher, the anomaly guard and the autopilot call it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from junkroan.runs import anomalies as an
from tools.agentops import autopilot, claude_bg
from tools.agentops import dispatch as dp

ROOT = Path(__file__).resolve().parents[1]
THREE_FILES = [ROOT / "tools" / "agentops" / "dispatch.py",
               ROOT / "src" / "junkroan" / "runs" / "anomalies.py",
               ROOT / "tools" / "agentops" / "autopilot.py"]


# -- (a) the old inline forms are gone from the three files ------------------------------------

def test_no_other_session_id_regex_definition() -> None:
    for path in THREE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "_BACKGROUNDED_RE" not in text, path
        assert "backgrounded" not in text, path


def test_no_other_bg_argv_literal() -> None:
    for path in THREE_FILES:
        text = path.read_text(encoding="utf-8")
        assert '"--bg"' not in text and "'--bg'" not in text, path
    assert '"--bg"' in (ROOT / "tools" / "agentops" / "claude_bg.py").read_text(encoding="utf-8")


# -- (b) the function: the three argvs are the ones the base commit built -----------------------

def test_orch_argv_identical_to_base() -> None:
    cmd = dp.build_command([54, 55], "claude.exe", tag="ab12")
    assert cmd == [
        "claude.exe", "--bg", "--name", f"orch {dp.REPO_NAME} #54 #55 ~ab12", "--agent", "orch",
        "--effort", "high", "--permission-mode", "bypassPermissions",
        "Take every ready issue (ready now, in dispatch order: #54, #55). Follow docs/agents/orch.md.",
    ]


def test_autopilot_argv_identical_to_base() -> None:
    assert autopilot.build_autopilot_command(116, "claude.exe", "S.json") == [
        "claude.exe", "--bg", "--name", "autopilot #116", "--agent", "brain",
        "--permission-mode", "bypassPermissions", "--settings", "S.json",
        "Autopilot on #116. Follow docs/agents/autopilot.md.",
    ]


def test_keymaster_argv_identical_to_base() -> None:
    plain = an.Anomaly(kind="job_failed", key="job_failed:j-1", job="j-1", detail="boom")
    assert an.build_command(plain, "claude.exe") == [
        "claude.exe", "--bg", "--name", f"keymaster: job_failed {plain.target}", "--agent", "keymaster",
        "--effort", "medium", "--permission-mode", "bypassPermissions", an.build_prompt(plain),
    ]
    remote = an.Anomaly(kind="job_failed", key="job_failed:j-1", job="j-1", detail="boom", origin="laptop")
    assert an.build_command(remote, "claude.exe")[3] == f"keymaster: job_failed laptop {remote.target}"


def test_session_id_found_in_coloured_and_plain_line() -> None:
    coloured = "backgrounded · \x1b[36ma97c7c60\x1b[39m · autopilot #999"
    plain = "backgrounded · a97c7c60 · autopilot #999"
    assert claude_bg.parse_session_id(coloured) == "a97c7c60"
    assert claude_bg.parse_session_id(plain) == "a97c7c60"
    assert claude_bg.parse_session_id("nothing here") is None
    assert claude_bg.parse_session_id(None) is None


def _completed(stdout: str = "", rc: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)


def test_keymaster_start_strips_ansi_too() -> None:
    """The one stated fix: the anomaly guard's copy had no ANSI group."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(list(argv))
        return _completed("backgrounded · \x1b[36mkm-9\x1b[39m · keymaster")

    anomaly = an.Anomaly(kind="job_failed", key="job_failed:j-1", job="j-1", detail="d")
    session_id = claude_bg.start_session(an.build_command(anomaly, "claude.exe"), cwd=ROOT, timeout=5,
                                         run=run, who=f" for {anomaly.key}")
    assert session_id == "km-9" and calls[0][1] == "--bg"


def test_start_errors_keep_their_words() -> None:
    bad = lambda argv, **kw: _completed(rc=1, stderr="x" * 400)  # noqa: E731
    for chars in (200, 300):
        try:
            claude_bg.start_session(["c"], cwd=ROOT, timeout=5, run=bad, stderr_chars=chars)
        except RuntimeError as exc:
            assert str(exc) == f"claude --bg failed: {'x' * chars}"
    none = lambda argv, **kw: _completed("hello")  # noqa: E731
    try:
        claude_bg.start_session(["c"], cwd=ROOT, timeout=5, run=none, who=" for k")
    except RuntimeError as exc:
        assert str(exc) == "claude --bg for k: no session id in 'hello'"


def test_list_and_stop_helpers() -> None:
    logged: list[str] = []
    seen: list[list[str]] = []

    def run(argv, **kw):
        seen.append(list(argv))
        return _completed(json.dumps([{"id": "a"}]))

    assert claude_bg.list_sessions("c.exe", cwd=ROOT, timeout=5, log=logged.append, run=run) == [{"id": "a"}]
    assert claude_bg.stop_session("c.exe", "a", cwd=ROOT, timeout=5, log=logged.append, run=run) is True
    assert seen == [["c.exe", "agents", "--json", "--all"], ["c.exe", "stop", "a"]]
    assert claude_bg.list_sessions("c.exe", cwd=ROOT, timeout=5, log=logged.append,
                                   run=lambda a, **k: _completed("not json")) == []
    assert claude_bg.stop_session("c.exe", "a", cwd=ROOT, timeout=5, log=logged.append,
                                  run=lambda a, **k: _completed(rc=1, stderr="no")) is False
    assert logged[0].startswith("claude agents --json --all: invalid JSON")
    assert logged[1] == "claude stop a failed: no"
