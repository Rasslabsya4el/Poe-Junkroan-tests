"""tools/hooks/autopilot_checkpoint.py (issue #1133, unit 2): a checkpoint's `questions:` entry must carry
a `one-way door: <what>` reason for each question it lists.

Seams: `questions_refusal(body)` (the check on one checkpoint body) and `handle_session_start` (what the
session is told). No `gh` call: the tests replace `hook._gh_comments`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT_ROOT / "tools" / "hooks"))
import autopilot_checkpoint as hook  # noqa: E402


def _checkpoint(questions_block: str) -> str:
    return (
        "Autopilot checkpoint at 02:00\n"
        "time: 02:00\n"
        "session: 3\n"
        "done: #1133 unit 1\n"
        "waiting: nothing\n"
        "next: unit 2\n"
        "decisions: none\n"
        f"{questions_block}"
    )


# -- questions_refusal: the check on one checkpoint body ---------------------------------------

def test_bare_question_is_refused():
    body = _checkpoint(
        "questions: 1\n"
        "- mortar_spectre_volley_overlap (#542): approve it for the conservative lane too?\n"
    )

    refusal = hook.questions_refusal(body)

    assert refusal is not None
    assert "one-way door:" in refusal
    assert "provisional decision" in refusal


def test_question_with_one_way_door_reason_passes():
    body = _checkpoint(
        "questions: 1\n"
        "- mortar_spectre_volley_overlap (#542): approve it? one-way door: a published PoB number changes\n"
    )

    assert hook.questions_refusal(body) is None


def test_inline_question_with_one_way_door_reason_passes():
    body = _checkpoint("questions: 1 (one-way door: deleting a published branch)\n")

    assert hook.questions_refusal(body) is None


def test_no_questions_passes_with_zero_none_or_no_line():
    assert hook.questions_refusal(_checkpoint("questions: 0\n")) is None
    assert hook.questions_refusal(_checkpoint("questions: none\n")) is None
    assert hook.questions_refusal(_checkpoint("")) is None


def test_count_without_any_reason_is_refused():
    refusal = hook.questions_refusal(_checkpoint("questions: 2\n"))

    assert refusal is not None
    assert "one-way door:" in refusal


def test_one_question_missing_its_reason_is_refused_and_named():
    body = _checkpoint(
        "questions: 2\n"
        "- approve the conservative lane? one-way door: the owner's published numbers change\n"
        "- keep the ORCH count wording as it is?\n"
    )

    refusal = hook.questions_refusal(body)

    assert refusal is not None
    assert "keep the ORCH count wording" in refusal


# -- handle_session_start: what the session is told --------------------------------------------

def _transcript(tmp_path: Path) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text(json.dumps({"type": "agent-name", "agentName": "autopilot #1133", "sessionId": "s1"}) + "\n",
                    encoding="utf-8")
    return path


def _run_with_checkpoint(tmp_path, monkeypatch, body: str) -> str:
    monkeypatch.setattr(hook, "_gh_comments",
                        lambda n, timeout=0: [{"body": body, "url": "https://github.com/x/y/issues/1133#issuecomment-2001"}])
    payload = {"hook_event_name": "SessionStart", "source": "compact",
               "transcript_path": str(_transcript(tmp_path))}
    output = hook.run(payload)
    return output["hookSpecificOutput"]["additionalContext"]


def test_session_is_told_when_the_checkpoint_question_is_refused(tmp_path, monkeypatch):
    context = _run_with_checkpoint(tmp_path, monkeypatch, _checkpoint(
        "questions: 1\n- approve it for the conservative lane too?\n"))

    assert "one-way door:" in context
    assert "checkpoint comment: 2001" in context


def test_session_gets_no_refusal_for_a_checkpoint_with_a_one_way_door(tmp_path, monkeypatch):
    body = _checkpoint("questions: 1\n- approve it? one-way door: a published PoB number changes\n")

    context = _run_with_checkpoint(tmp_path, monkeypatch, body)

    assert context == f"{body}\n\ncheckpoint comment: 2001"


def test_refused_checkpoint_still_injects_the_checkpoint_body(tmp_path, monkeypatch):
    body = _checkpoint("questions: 1\n- approve it for the conservative lane too?\n")

    context = _run_with_checkpoint(tmp_path, monkeypatch, body)

    assert body in context
