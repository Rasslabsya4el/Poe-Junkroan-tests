"""Fakes shared by the autopilot test files (#1176): the fake `claude.exe`, `gh`, clocks and the
dispatcher helpers that those files used to import from the deleted tests/test_agentops_dispatch_autopilot.py.
A plain helper module (no `test_` prefix), so a core update does not delete it; pytest collects no test
from it. Only the names the autopilot test files import are here; ORCH's own fakes stay in
tests/test_agentops_dispatch.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from tools.agentops.autopilot import (
    AUTOPILOT_CHECKPOINT_PREFIX,
    AUTOPILOT_STUCK_LABEL,
    AUTOPILOT_TERMS_PREFIX,
    build_autopilot_command,
)
from tools.agentops.dispatch import Dispatcher
from tools.agentops.worktree import ROOT


class FakeClaude:
    """A fake `claude.exe`: `start`/`start_autopilot` hand out sequential session ids,
    `list_sessions` reports whatever state the test sets."""

    def __init__(self) -> None:
        self.cwd = ROOT
        self.started: list[list[int]] = []
        self.autopilot_started: list[tuple[int, list[str]]] = []
        self.stopped: list[str] = []
        self.ended_pids: list[int] = []
        self.start_autopilot_fails: dict[int, str] = {}
        self._sessions: dict[str, dict] = {}
        self._next_id = 1
        #: wake(chat, message) calls, in order; `wake_results[chat] = (success, raw_text)` overrides
        #: the default success reply.
        self.wake_calls: list[tuple[str, str]] = []
        self.wake_results: dict[str, tuple[bool, str]] = {}

    def start(self, offered: list[int]) -> tuple[str, list[str]]:
        session_id = f"orch-{self._next_id}"
        self._next_id += 1
        self.started.append(list(offered))
        self._sessions[session_id] = {"id": session_id, "kind": "background",
                                      "state": "working", "status": "busy", "name": "orch"}
        return session_id, ["claude.exe", "--bg"]

    def start_autopilot(self, goal: int) -> tuple[str, list[str]]:
        if goal in self.start_autopilot_fails:
            raise RuntimeError(self.start_autopilot_fails[goal])
        session_id = f"ap-{self._next_id}"
        self._next_id += 1
        cmd = build_autopilot_command(goal, "claude.exe")
        self.autopilot_started.append((goal, cmd))
        self._sessions[session_id] = {"id": session_id, "kind": "background", "state": "working",
                                      "status": "busy", "name": f"autopilot #{goal}"}
        return session_id, cmd

    def list_sessions(self) -> list[dict]:
        return list(self._sessions.values())

    def stop(self, session_id: str) -> bool:
        self.stopped.append(session_id)
        self._sessions.pop(session_id, None)
        return True

    def end_process(self, pid: int) -> bool:
        self.ended_pids.append(pid)
        return True

    def wake(self, chat: str, message: str) -> tuple[bool, str]:
        self.wake_calls.append((chat, message))
        return self.wake_results.get(chat, (True, '{"success":true,"message":"queued"}'))

    # test helpers
    def set_state(self, session_id: str, *, state: str, status: str = "idle") -> None:
        self._sessions[session_id].update(state=state, status=status)

    def add_session(self, session_id: str, **fields) -> None:
        self._sessions[session_id] = {"id": session_id, "kind": "background", **fields}


class FakeGh:
    """A fake `gh`: no candidates for ORCH (never offered here) plus the autopilot surface --
    `autopilot_goals`, `latest_checkpoint_comment`, `add_label`, `comment`."""

    def __init__(self) -> None:
        self.goals: dict[int, set[str]] = {}  # goal number -> label set (open only while present)
        self.checkpoints: dict[int, list[str]] = {}
        self.terms: dict[int, list[str]] = {}
        self.comment_calls: list[tuple[int, str]] = []
        self.added_labels: list[tuple[int, str]] = []
        self.removed_labels: list[tuple[int, str]] = []
        self.removed_assignees: list[int] = []
        #: #146: arbitrary comments on a goal issue, `{number: [{"id": ..., "body": ...}, ...]}`
        #: (oldest first) -- `checkpoints`/`terms` above stay a separate, older concept.
        self._goal_comments: dict[int, list[dict]] = {}
        self._next_comment_id = 1
        #: #146: `"Part of #{goal}"` child issues, `{goal: {number: {"state", "labels", "comments"}}}`.
        self._children: dict[int, dict[int, dict]] = {}
        #: `None` -> the next `comments`/`child_issues` call for this number/goal fails once (#146
        #: "a `gh` failure never itself counts as a change").
        self.comments_fail: set[int] = set()
        self.children_fail: set[int] = set()

    # ORCH surface: never exercised by these tests, kept minimal
    def ready_for_agent_issues(self):
        return []

    def claimed_issues(self):
        return []

    # autopilot surface
    def autopilot_goal(self, number: int, labels: tuple[str, ...] = ("autopilot",)) -> None:
        self.goals[number] = set(labels)

    def close_goal(self, number: int) -> None:
        self.goals.pop(number, None)

    def remove_autopilot_label(self, number: int) -> None:
        self.goals.get(number, set()).discard("autopilot")

    def autopilot_goals(self) -> list[int]:
        return sorted(n for n, labels in self.goals.items()
                      if "autopilot" in labels and AUTOPILOT_STUCK_LABEL not in labels)

    def set_checkpoints(self, number: int, bodies: list[str]) -> None:
        self.checkpoints[number] = list(bodies)

    def latest_checkpoint_comment(self, number: int) -> str | None:
        bodies = self.checkpoints.get(number) or []
        for body in reversed(bodies):
            if body.startswith("Autopilot checkpoint"):
                return body
        return None

    def set_terms(self, number: int, bodies: list[str]) -> None:
        """`bodies`: full `Autopilot terms` comment bodies, oldest first (#127)."""

        self.terms[number] = list(bodies)

    def latest_terms_comment(self, number: int) -> str | None:
        bodies = self.terms.get(number) or []
        for body in reversed(bodies):
            if body.startswith("Autopilot terms"):
                return body
        return None

    def add_label(self, number: int, label: str) -> bool:
        self.added_labels.append((number, label))
        self.goals.setdefault(number, set()).add(label)
        return True

    def remove_label(self, number: int, label: str) -> bool:
        self.removed_labels.append((number, label))
        self.goals.get(number, set()).discard(label)
        return True

    def comment(self, number: int, body: str) -> bool:
        self.comment_calls.append((number, body))
        return True

    def remove_assignee(self, number: int, login: str = "@me") -> bool:
        self.removed_assignees.append(number)
        return True

    def issue_status(self, number: int):  # never called with no ORCH issue held
        raise AssertionError("issue_status should not be called by these autopilot-only tests")

    # -- #146: the goal's own comments and its "Part of #N" children ------------------------------

    def add_goal_comment(self, number: int, body: str) -> None:
        cid = f"c{self._next_comment_id}"
        self._next_comment_id += 1
        self._goal_comments.setdefault(number, []).append({"id": cid, "body": body})

    def comments(self, number: int, *, fresh: bool = False) -> list[dict] | None:  # #1113: GhCli.comments' flag
        if number in self.comments_fail:
            self.comments_fail.discard(number)
            return None
        return list(self._goal_comments.get(number, []))

    def add_child(self, goal: int, number: int, *, state: str = "OPEN",
                 labels: tuple[str, ...] = ()) -> None:
        self._children.setdefault(goal, {})[number] = {
            "state": state, "labels": list(labels), "comments": [],
        }

    def close_child(self, goal: int, number: int) -> None:
        self._children[goal][number]["state"] = "CLOSED"

    def reopen_child(self, goal: int, number: int) -> None:
        self._children[goal][number]["state"] = "OPEN"

    def add_label_to_child(self, goal: int, number: int, label: str) -> None:
        self._children[goal][number]["labels"].append(label)

    def remove_label_from_child(self, goal: int, number: int, label: str) -> None:
        self._children[goal][number]["labels"].remove(label)

    def add_comment_to_child(self, goal: int, number: int, body: str = "an update") -> None:
        self._children[goal][number]["comments"].append({"body": body})

    def child_issues(self, goal: int) -> list[dict] | None:
        if goal in self.children_fail:
            self.children_fail.discard(goal)
            return None
        out = []
        for number, child in self._children.get(goal, {}).items():
            out.append({
                "number": number, "state": child["state"],
                "labels": [{"name": lbl} for lbl in child["labels"]],
                "comments": list(child["comments"]),
            })
        return out


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeTimestamp:
    """A fake wall clock for `Dispatcher(timestamp=...)`, independent of `FakeClock` (which is a
    fake `time.monotonic`) -- the terms deadline is compared against this one (#127)."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def _terms_body(**fields: str) -> str:
    """One `Autopilot terms` comment body with a fenced `key: value` block (#127)."""

    lines = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"{AUTOPILOT_TERMS_PREFIX}\n\nthe owner's words, echoed.\n\n```\n{lines}\n```"


def _dispatcher(tmp_path: Path, claude: FakeClaude, gh: FakeGh, **kwargs) -> Dispatcher:
    return Dispatcher(claude=claude, gh=gh, events_file=tmp_path / "events.jsonl",
                      state_file=tmp_path / "orch_session.json", projects_dir=tmp_path / "projects",
                      clock=kwargs.pop("clock", None) or FakeClock(), **kwargs)


def _events(tmp_path: Path) -> list[dict]:
    path = tmp_path / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _InPlaceGh(FakeGh):
    """The checkpoint is read from the goal's own comments, so an edit keeps the comment id."""

    def latest_checkpoint_comment(self, number: int) -> str | None:
        for comment in reversed(self._goal_comments.get(number, [])):
            if str(comment["body"]).startswith(AUTOPILOT_CHECKPOINT_PREFIX):
                return comment["body"]
        return None

    def edit_goal_comment(self, number: int, body: str) -> None:
        self._goal_comments[number][0]["body"] = body


def _started_lines(logs: list[str], goal: int) -> list[str]:
    return [m for m in logs if m.startswith(f"autopilot #{goal} started (")]
