"""tools/hooks/autopilot_checkpoint.py (issue #116, numbers item 5).

No real `gh` call: `AGENTOPS_HOOK_GH` points at `tests/fixtures/gh_comments_stub.py`. No real Claude
Code session is involved: transcripts are small fixture files written by these tests."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.timing_bound import bound

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "autopilot_checkpoint.py"
GH_STUB = PROJECT_ROOT / "tests" / "fixtures" / "gh_comments_stub.py"

sys.path.insert(0, str(PROJECT_ROOT / "tools" / "hooks"))
import autopilot_checkpoint as hook  # noqa: E402


def _transcript(tmp_path: Path, agent_name: str | None) -> Path:
    lines = []
    if agent_name is not None:
        lines.append({"type": "custom-title", "customTitle": agent_name, "sessionId": "s1"})
        lines.append({"type": "agent-name", "agentName": agent_name, "sessionId": "s1"})
    else:
        lines.append({"type": "queue-operation", "operation": "enqueue", "content": "hi"})
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    return path


def _scale_gh_timeout(monkeypatch) -> None:
    """`_gh_comments`' default `timeout=GH_TIMEOUT_SECONDS` (5 s, product, autopilot_checkpoint.py:79/:89) is
    bound at definition; a python-stub spawn on a loaded PC outlasted it and the read came back None =
    "unknown" (#844). The product limit stays; the tests call it with a machine-scaled one."""
    monkeypatch.setattr(hook, "_gh_comments",
                        functools.partial(hook._gh_comments, timeout=bound(float(hook.GH_TIMEOUT_SECONDS), 40.0)))


def _run_hook(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=bound(10.0, 60.0), env=full_env,
    )


# -- autopilot_issue_number: reading the session's name off its own transcript ------------------

def test_autopilot_issue_number_reads_agent_name(tmp_path):
    transcript = _transcript(tmp_path, "autopilot #116")
    assert hook.autopilot_issue_number(str(transcript)) == 116


def test_autopilot_issue_number_none_for_orch(tmp_path):
    transcript = _transcript(tmp_path, "orch #58 #59")
    assert hook.autopilot_issue_number(str(transcript)) is None


def test_autopilot_issue_number_none_with_no_agent_name(tmp_path):
    transcript = _transcript(tmp_path, None)
    assert hook.autopilot_issue_number(str(transcript)) is None


def test_autopilot_issue_number_none_for_missing_transcript():
    assert hook.autopilot_issue_number(None) is None
    assert hook.autopilot_issue_number("Z:/does/not/exist.jsonl") is None


# -- latest_checkpoint: last matching comment wins -----------------------------------------------

def test_latest_checkpoint_picks_the_last_matching_comment():
    comments = [
        "Autopilot checkpoint at 01:00: step 1 done",
        "unrelated comment",
        "Autopilot checkpoint at 02:00: step 2 done",
    ]
    assert hook.latest_checkpoint(comments) == "Autopilot checkpoint at 02:00: step 2 done"


def test_latest_checkpoint_none_when_absent():
    assert hook.latest_checkpoint(["hello", "world"]) is None


# -- latest_terms: last matching `Autopilot terms` comment wins (#127) ---------------------------

def test_latest_terms_picks_the_last_matching_comment():
    comments = [
        "Autopilot terms at 22:00\n\n```\nchat: brain\n```",
        "unrelated comment",
        "Autopilot terms at 23:30\n\n```\nchat: brain\n```",
    ]
    assert hook.latest_terms(comments) == "Autopilot terms at 23:30\n\n```\nchat: brain\n```"


def test_latest_terms_none_when_absent():
    assert hook.latest_terms(["hello", "Autopilot checkpoint: x"]) is None


# -- the full hook, in process (numbers item 5) --------------------------------------------------

def test_5_checkpoint_at_0100_and_0200_injects_the_0200_one(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path, "autopilot #116")
    _scale_gh_timeout(monkeypatch)
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS",
                        "Autopilot checkpoint at 01:00: step 1\x1fAutopilot checkpoint at 02:00: step 2")
    payload = {"hook_event_name": "SessionStart", "source": "compact", "transcript_path": str(transcript)}

    output = hook.run(payload)

    assert output["hookSpecificOutput"]["additionalContext"] == (
        "Autopilot checkpoint at 02:00: step 2\n\ncheckpoint comment: 1001"
    )


def test_5_a_session_not_named_autopilot_gets_nothing(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path, "orch #58")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint at 02:00: step 2")
    payload = {"hook_event_name": "SessionStart", "source": "startup", "transcript_path": str(transcript)}

    assert hook.run(payload) is None


def test_no_checkpoint_yet_injects_first_session(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path, "autopilot #200")
    _scale_gh_timeout(monkeypatch)
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "")

    output = hook.run({"hook_event_name": "SessionStart", "source": "startup",
                       "transcript_path": str(transcript)})

    assert output["hookSpecificOutput"]["additionalContext"] == "first session on #200\n\ncheckpoint comment: none"


def test_562_gh_failure_injects_unknown_not_none(tmp_path, monkeypatch):
    """A failed read (rc != 0, a timeout) is not "no checkpoint": `none` would make the session post
    a second checkpoint comment, so the hook says `unknown` (#562)."""
    transcript = _transcript(tmp_path, "autopilot #200")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {tmp_path / 'missing_gh.py'}")

    output = hook.run({"hook_event_name": "SessionStart", "source": "startup",
                       "transcript_path": str(transcript)})

    assert output["hookSpecificOutput"]["additionalContext"].endswith("checkpoint comment: unknown")



def test_563_gh_rc1_injects_failed_read_sentence_not_first_session(tmp_path, monkeypatch):
    """A failed read (rc != 0) says so in words and is never a fresh start (#563)."""
    transcript = _transcript(tmp_path, "autopilot #200")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {tmp_path / 'missing_gh.py'}")

    context = hook.run({"hook_event_name": "SessionStart", "source": "startup",
                        "transcript_path": str(transcript)})["hookSpecificOutput"]["additionalContext"]

    assert context.startswith("checkpoint read failed on #200: run gh api "
                              "repos/{owner}/{repo}/issues/200/comments?per_page=100 --paginate")
    assert "never start the goal fresh on a failed read" in context
    assert context.endswith("checkpoint comment: unknown")
    assert "first session" not in context


def test_563_gh_invalid_json_injects_failed_read_sentence_not_first_session(tmp_path, monkeypatch):
    """A gh that prints invalid JSON is a failed read too (#563)."""
    transcript = _transcript(tmp_path, "autopilot #200")
    bad_gh = tmp_path / "bad_gh.py"
    bad_gh.write_text("print('not json {')", encoding="utf-8")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {bad_gh}")

    context = hook.run({"hook_event_name": "SessionStart", "source": "startup",
                        "transcript_path": str(transcript)})["hookSpecificOutput"]["additionalContext"]

    assert context.startswith("checkpoint read failed on #200: ")
    assert context.endswith("checkpoint comment: unknown")
    assert "first session" not in context

# -- numbers item 1: terms beside the checkpoint --------------------------------------------------

def test_1_terms_at_2200_and_2330_and_checkpoint_at_0100_injects_2330_terms_and_0100_checkpoint(
    tmp_path, monkeypatch,
):
    transcript = _transcript(tmp_path, "autopilot #116")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "\x1f".join([
        "Autopilot terms at 22:00\n\n```\nchat: brain\n```",
        "Autopilot terms at 23:30\n\n```\nchat: brain\n```",
        "Autopilot checkpoint at 01:00: step 1",
    ]))
    payload = {"hook_event_name": "SessionStart", "source": "compact", "transcript_path": str(transcript)}

    output = hook.run(payload)

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Autopilot terms at 23:30" in context
    assert "Autopilot terms at 22:00" not in context
    assert "Autopilot checkpoint at 01:00: step 1" in context


def test_1_no_terms_comment_injects_only_the_checkpoint_as_today(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path, "autopilot #116")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint at 01:00: step 1")

    output = hook.run({"hook_event_name": "SessionStart", "source": "compact",
                       "transcript_path": str(transcript)})

    assert output["hookSpecificOutput"]["additionalContext"] == (
        "Autopilot checkpoint at 01:00: step 1\n\ncheckpoint comment: 1000"
    )


@pytest.mark.parametrize("event,source", [("UserPromptSubmit", "startup"), ("SessionStart", "resume")])
def test_only_sessionstart_startup_compact_clear_fire(tmp_path, monkeypatch, event, source):
    transcript = _transcript(tmp_path, "autopilot #116")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint x")

    assert hook.run({"hook_event_name": event, "source": source, "transcript_path": str(transcript)}) is None


# -- the script as a real subprocess (stdin -> stdout), like brain_reset_nudge's tests -----------

def test_subprocess_matches_in_process_output(tmp_path):
    transcript = _transcript(tmp_path, "autopilot #7")
    env = {"AGENTOPS_HOOK_GH": f"{sys.executable} {GH_STUB}",
           "AGENTOPS_HOOK_GH_COMMENTS": "Autopilot checkpoint hi"}
    payload = {"hook_event_name": "SessionStart", "source": "clear", "transcript_path": str(transcript)}

    result = _run_hook(payload, env=env)

    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"] == (
        "Autopilot checkpoint hi\n\ncheckpoint comment: 1000"
    )


def test_bad_stdin_exits_zero_no_output():
    result = subprocess.run([sys.executable, str(HOOK_SCRIPT)], input="not json",
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- #116 numbers items 1-3: `session_title` read before the transcript exists -------------------

def test_1_session_title_with_missing_transcript_still_injects_checkpoint(tmp_path, monkeypatch):
    missing_transcript = tmp_path / "does-not-exist.jsonl"
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint at 01:00: step 1")
    payload = {"hook_event_name": "SessionStart", "source": "startup",
               "session_title": "autopilot #116", "transcript_path": str(missing_transcript)}

    output = hook.run(payload)

    assert output["hookSpecificOutput"]["additionalContext"] == (
        "Autopilot checkpoint at 01:00: step 1\n\ncheckpoint comment: 1000"
    )


def test_2_session_title_not_autopilot_and_no_transcript_gets_nothing(tmp_path, monkeypatch):
    missing_transcript = tmp_path / "does-not-exist.jsonl"
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint at 01:00: step 1")

    payload_orch_title = {"hook_event_name": "SessionStart", "source": "startup",
                           "session_title": "orch #116", "transcript_path": str(missing_transcript)}
    assert hook.run(payload_orch_title) is None

    payload_no_title = {"hook_event_name": "SessionStart", "source": "startup",
                         "transcript_path": str(missing_transcript)}
    assert hook.run(payload_no_title) is None


def test_3_no_session_title_falls_back_to_transcript_agent_name(tmp_path, monkeypatch):
    transcript = _transcript(tmp_path, "autopilot #116")
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_COMMENTS", "Autopilot checkpoint at 01:00: step 1")
    payload = {"hook_event_name": "SessionStart", "source": "startup", "transcript_path": str(transcript)}

    output = hook.run(payload)

    assert output["hookSpecificOutput"]["additionalContext"] == (
        "Autopilot checkpoint at 01:00: step 1\n\ncheckpoint comment: 1000"
    )


# -- #562: the hook names the ONE checkpoint comment a session edits in place ---------------------

GH_STATE_STUB = PROJECT_ROOT / "tests" / "fixtures" / "gh_state_stub.py"


class _FakeGoal:
    """A goal's comments as a JSON file the fake gh prints; the methods mutate it as a session would."""

    def __init__(self, path: Path):
        self.path = path
        self.next_id = 9000
        self._write([])

    def _read(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))["comments"]

    def _write(self, comments: list[dict]) -> None:
        self.path.write_text(json.dumps({"comments": comments}), encoding="utf-8")

    def create(self, body: str) -> int:
        self.next_id += 1
        comments = self._read()
        comments.append({"id": f"IC_kw{self.next_id}", "body": body,
                         "url": f"https://example.test/o/r/issues/562#issuecomment-{self.next_id}"})
        self._write(comments)
        return self.next_id

    def edit(self, comment_id: int, body: str) -> None:
        comments = self._read()
        hits = [c for c in comments if c["url"].endswith(f"#issuecomment-{comment_id}")]
        assert len(hits) == 1
        hits[0]["body"] = body
        self._write(comments)

    def count(self, prefix: str) -> int:
        return sum(1 for c in self._read() if c["body"].startswith(prefix))


def _session_start(monkeypatch, state: Path) -> str:
    monkeypatch.setenv("AGENTOPS_HOOK_GH", f"{sys.executable} {GH_STATE_STUB}")
    monkeypatch.setenv("AGENTOPS_HOOK_GH_STATE", str(state))
    out = hook.run({"hook_event_name": "SessionStart", "source": "startup",
                    "session_title": "autopilot #562"})
    return out["hookSpecificOutput"]["additionalContext"]


def test_562_last_checkpoint_body_and_numeric_id_injected(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    goal.create("Autopilot terms at 22:00\n\nchat: brain")
    goal.create("Autopilot checkpoint at 01:00: first")
    last = goal.create("Autopilot checkpoint at 02:00: second")

    context = _session_start(monkeypatch, goal.path)

    assert "Autopilot checkpoint at 02:00: second" in context
    assert "Autopilot checkpoint at 01:00: first" not in context
    assert context.endswith(f"checkpoint comment: {last}")


def test_562_no_checkpoint_injects_none(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    goal.create("Autopilot terms at 22:00\n\nchat: brain")

    assert _session_start(monkeypatch, goal.path).endswith("checkpoint comment: none")


def test_562_unparsable_url_injects_unknown(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"comments": [
        {"id": "IC_x", "body": "Autopilot checkpoint at 01:00", "url": "garbage"}]}), encoding="utf-8")

    assert _session_start(monkeypatch, state).endswith("checkpoint comment: unknown")


def test_562_walk_three_sessions_keep_one_checkpoint_comment(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    goal.create("Autopilot terms at 22:00\n\nchat: brain")
    counts = []
    cid = None
    for session in (1, 2, 3):
        context = _session_start(monkeypatch, goal.path)
        body = f"Autopilot checkpoint session {session}"
        if session == 1:
            assert context.endswith("checkpoint comment: none")
            cid = goal.create(body)
        else:
            assert context.endswith(f"checkpoint comment: {cid}")
            goal.edit(int(context.rsplit(": ", 1)[1]), body)
        counts.append((goal.count("Autopilot checkpoint"), goal.count("Autopilot terms")))
    print("(checkpoint, terms) comments after sessions 1..3:", counts)
    assert counts == [(1, 1)] * 3

    final = _session_start(monkeypatch, goal.path)
    assert "Autopilot checkpoint session 3" in final
    assert final.endswith(f"checkpoint comment: {cid}")
    print("injected after session 3:", final.rsplit("\n", 1)[1])


# -- #564: the checkpoint cap -----------------------------------------------------------------------

def _checkpoint_of_length(n: int) -> str:
    head = "Autopilot checkpoint "
    return head + "x" * (n - len(head))


def test_564_over_cap_checkpoint_gets_fold_line_first(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    body = _checkpoint_of_length(12000)
    goal.create(body)

    context = _session_start(monkeypatch, goal.path)

    assert context.splitlines()[0] == "checkpoint 12000 chars over the cap 10,000: fold it in this session before any other step"
    assert body in context
    assert context.index(body) > 0


def test_564_9999_chars_no_fold_line(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    goal.create(_checkpoint_of_length(9999))

    assert "over the cap" not in _session_start(monkeypatch, goal.path)


def test_564_10000_chars_no_fold_line(tmp_path, monkeypatch):
    goal = _FakeGoal(tmp_path / "state.json")
    goal.create(_checkpoint_of_length(10000))

    assert "over the cap" not in _session_start(monkeypatch, goal.path)
