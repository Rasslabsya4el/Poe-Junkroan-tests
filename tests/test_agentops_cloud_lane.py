"""tools/agentops/cloud_lane.py (#121): the cloud lane, driven through a FAKE `gh` runner and a
FAKE `claude` runner -- no real `gh` call, no real cloud session, no issue or label created on
GitHub. Every acceptance number of #121 has its own test, named after it.

The fakes sit at the runner seam (`(args, stdin) -> CompletedProcess`), so the real `LaneGh` /
`CloudCli` / `dispatch.GhCli` code (argv, JSON parsing, label edits) is what runs.
"""

from __future__ import annotations

import json
import subprocess
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.agentops import cloud_lane as cl
from tools.agentops import monitor_issues
from tools.agentops.dispatch import Dispatcher, GhCli, build_command
from tools.agentops.worktree import ROOT

LOCAL = timezone(timedelta(hours=3))  # the owner's local zone, fixed so the reset test is exact
UTC_NOW = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)  # a Monday
LANE_ISSUE = 200


@pytest.fixture(autouse=True)
def _no_settings(monkeypatch):
    monkeypatch.setattr(cl, "_settings", lambda: {})


# ------------------------------------------------------------------------------------ the fakes ---

def _done(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGhRunner:
    """A fake `gh`: one in-memory issue table, driven by the real argv the code builds."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.calls: list[list[str]] = []
        self.labels_created: list[str] = []
        self.issues_created: list[tuple[str, str]] = []
        self.next_number = 900
        self.now = "2026-09-28T09:00:00Z"
        self.fail_in_cloud_list = False

    # -- the table, as the test sets it up ---------------------------------------------------------
    def add(self, number: int, *, labels: tuple[str, ...] = (), open: bool = True,
            assignees: tuple[str, ...] = (), created_at: str | None = None,
            comments: list[dict] | None = None, blockers: tuple[int, ...] = ()) -> None:
        self.issues[number] = {
            "number": number, "labels": list(labels), "open": open, "assignees": list(assignees),
            "createdAt": created_at or f"2026-09-{min(28, number % 28 + 1):02d}T00:00:00Z",
            "comments": list(comments or []), "blockers": list(blockers),
        }

    def comment_bodies(self, number: int) -> list[str]:
        return [c["body"] for c in self.issues[number]["comments"]]

    def labels(self, number: int) -> list[str]:
        return list(self.issues[number]["labels"])

    def close_issue(self, number: int) -> None:
        self.issues[number]["open"] = False

    # -- the runner ---------------------------------------------------------------------------------
    def __call__(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if args[:2] == ["label", "create"]:
            self.labels_created.append(args[2])
            return _done(0, "")
        if args[:2] == ["issue", "list"]:
            return self._list(args)
        if args[:2] == ["issue", "view"]:
            return self._view(args)
        if args[:2] == ["issue", "comment"]:
            number = int(args[2])
            self.issues[number]["comments"].append({"body": stdin or "", "createdAt": self.now})
            return _done(0, "")
        if args[:2] == ["issue", "edit"]:
            return self._edit(args)
        if args[:2] == ["issue", "create"]:
            number = self.next_number
            self.next_number += 1
            title = args[args.index("--title") + 1]
            self.add(number, labels=tuple(self._flag_values(args, "--label")))
            self.issues_created.append((title, stdin or ""))
            return _done(0, f"https://github.com/Rasslabsya4el/Poe-Junkroan/issues/{number}\n")
        raise AssertionError(f"the fake gh got an unexpected call: {args!r}")

    def _flag_values(self, args: list[str], flag: str) -> list[str]:
        return [args[i + 1] for i, a in enumerate(args) if a == flag and i + 1 < len(args)]

    def _record(self, issue: dict) -> dict:
        return {
            "number": issue["number"], "createdAt": issue["createdAt"],
            "state": "OPEN" if issue["open"] else "CLOSED",
            "labels": [{"name": name} for name in issue["labels"]],
            "assignees": [{"login": login} for login in issue["assignees"]],
            "comments": list(issue["comments"]),
            "blockedBy": {"nodes": [{"number": b, "state": "OPEN"} for b in issue["blockers"]]},
        }

    def _list(self, args: list[str]) -> subprocess.CompletedProcess:
        wanted_labels = self._flag_values(args, "--label")
        if self.fail_in_cloud_list and cl.IN_CLOUD_LABEL in wanted_labels:
            return _done(1, "", "gh: API rate limit")
        state = (self._flag_values(args, "--state") or ["open"])[0]
        search = " ".join(self._flag_values(args, "--search"))
        assignee = self._flag_values(args, "--assignee")
        out = []
        for issue in self.issues.values():
            if state == "open" and not issue["open"]:
                continue
            if state == "closed" and issue["open"]:
                continue
            if any(label not in issue["labels"] for label in wanted_labels):
                continue
            if "no:assignee" in search and issue["assignees"]:
                continue
            if assignee and not issue["assignees"]:
                continue
            out.append(self._record(issue))
        return _done(0, json.dumps(out))

    def _view(self, args: list[str]) -> subprocess.CompletedProcess:
        number = int(args[2])
        if number not in self.issues:
            return _done(1, "", "not found")
        return _done(0, json.dumps(self._record(self.issues[number])))

    def _edit(self, args: list[str]) -> subprocess.CompletedProcess:
        number = int(args[2])
        issue = self.issues[number]
        for label in self._flag_values(args, "--add-label"):
            if label not in issue["labels"]:
                issue["labels"].append(label)
        for label in self._flag_values(args, "--remove-label"):
            issue["labels"] = [x for x in issue["labels"] if x != label]
        for _ in self._flag_values(args, "--remove-assignee"):
            issue["assignees"] = []
        return _done(0, "")


class FakeClaudeRunner:
    """A fake `claude -p --cloud <id> --output-format json`: records every message, answers with
    the #98 shapes (`{ok, session_id, url}` / `{ok: false, session_id, error}`)."""

    def __init__(self, session: str = "cse_017nWUZBDWZ6JhFHD4UKuJQH") -> None:
        self.session = session
        self.sent: list[str] = []
        self.args: list[list[str]] = []
        self.ok = True
        self.returncode = 0

    def __call__(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        self.args.append(list(args))
        self.sent.append(stdin or "")
        if self.ok:
            body = json.dumps({"ok": True, "session_id": self.session,
                               "url": f"https://claude.ai/code/session_x?from=cli&m={len(self.sent)}"})
        else:
            body = json.dumps({"ok": False, "session_id": self.session, "error": "session not found"})
        return _done(self.returncode, body)

    @property
    def messages(self) -> list[str]:
        return [m for m in self.sent if m != "/compact"]

    @property
    def compacts(self) -> int:
        return sum(1 for m in self.sent if m == "/compact")


class FakeLocalClaude:
    """The local ORCH side of `dispatch.Dispatcher`: `start` / `list_sessions` / `wake` (#137) are
    reached; `wake` just records the call, these tests never assert on it."""

    def __init__(self) -> None:
        self.cwd = ROOT
        self.started: list[list[int]] = []
        self.waked: list[tuple[str, str]] = []
        self._sessions: dict[str, dict] = {}
        self._next = 1

    def start(self, offered: list[int]) -> tuple[str, list[str]]:
        session_id = f"sess-{self._next}"
        self._next += 1
        self.started.append(list(offered))
        self._sessions[session_id] = {"id": session_id, "sessionId": f"uuid-{session_id}",
                                      "kind": "background", "state": "working", "status": "busy",
                                      "name": f"orch {' '.join('#' + str(n) for n in offered)}"}
        return session_id, build_command(offered, "claude.exe")

    def list_sessions(self) -> list[dict]:
        return list(self._sessions.values())

    def wake(self, target: str, message: str) -> tuple[bool, str]:
        self.waked.append((target, message))
        return True, '{"success":true}'

    def stop(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return True

    def end_process(self, pid: int) -> bool:
        return True


# ------------------------------------------------------------------------------------- fixtures ---

def _open_comment(session: str = "cse_017nWUZBDWZ6JhFHD4UKuJQH", created: str = "2026-09-27T09:00:00Z") -> dict:
    return {"body": f"{cl.OPEN_PREFIX}{session}\n\nsetup done.", "createdAt": created}


def _closed_comment(why: str = "the owner said so", created: str = "2026-09-27T12:00:00Z") -> dict:
    return {"body": f"{cl.CLOSED_PREFIX}{why}", "createdAt": created}


def _lane(tmp_path: Path, gh_runner: FakeGhRunner, claude_runner: FakeClaudeRunner, *,
          local: datetime | None = None, messages: list[str] | None = None) -> cl.CloudLane:
    lane = cl.CloudLane(
        gh=cl.LaneGh(runner=gh_runner, log=(messages.append if messages is not None else (lambda m: None))),
        cloud=cl.CloudCli(runner=claude_runner),
        state_file=tmp_path / "cloud_lane.json", credits_file=tmp_path / "cloud_credits.json",
        log=(messages.append if messages is not None else (lambda m: None)),
        now=lambda: UTC_NOW, local_now=lambda: (local or UTC_NOW.astimezone(LOCAL)),
    )
    return lane


def _dispatcher(tmp_path: Path, gh_runner: FakeGhRunner, lane: cl.CloudLane,
                claude: FakeLocalClaude | None = None) -> tuple[Dispatcher, FakeLocalClaude]:
    claude = claude or FakeLocalClaude()
    d = Dispatcher(claude=claude, gh=GhCli(runner=gh_runner),
                   events_file=tmp_path / "events.jsonl", state_file=tmp_path / "orch_session.json",
                   projects_dir=tmp_path / "projects", clock=lambda: 0.0, log=lambda m: None)
    d.lane = lane  # what `register`'s `start` step wires into the real dispatcher (#150)
    return d, claude


def _two_pob_free_and_one_plain(gh: FakeGhRunner, *, lane_comments: list[dict]) -> None:
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=lane_comments)
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL), created_at="2026-09-20T00:00:00Z")
    gh.add(42, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL), created_at="2026-09-21T00:00:00Z")
    gh.add(74, labels=(cl.READY_LABEL,), created_at="2026-09-22T00:00:00Z")


# ----------------------------------------------------------- acceptance: the lane is closed -------

def test_closed_lane_sends_nothing_over_three_ticks(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_closed_comment()])
    lane = _lane(tmp_path, gh, claude)

    for _ in range(3):
        result = lane.tick()

    assert claude.sent == []  # 0 sends over 3 ticks with 2 pob-free issues ready
    assert result.open is False and result.sent == ()
    assert gh.labels(35) == [cl.READY_LABEL, cl.POB_FREE_LABEL]  # never labelled in-cloud
    assert cl.monitor_line(tmp_path / "cloud_lane.json")["line"] == \
        "Cloud lane: closed (the owner said so)"


def test_no_lane_issue_at_all_is_a_closed_lane(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL))
    lane = _lane(tmp_path, gh, claude)

    assert lane.tick().open is False
    assert claude.sent == []


# ------------------------------------------------ #566: a broken state file is set aside ---------

def _closed_lane(tmp_path: Path, messages: list[str]) -> cl.CloudLane:
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_closed_comment()])
    return _lane(tmp_path, gh, claude, messages=messages)


def test_a_broken_state_file_is_set_aside_and_the_tick_goes_on(tmp_path: Path):
    messages: list[str] = []
    lane = _closed_lane(tmp_path, messages)
    (tmp_path / "cloud_lane.json").write_bytes(b"\x00" * 187)

    assert isinstance(lane.tick(), cl.LaneTick)  # a closed-lane tick writes a record: a fresh file appears

    broken = [p for p in tmp_path.iterdir() if ".broken-" in p.name]
    assert len(broken) == 1 and broken[0].name.startswith("cloud_lane.json.broken-")
    assert broken[0].read_bytes() == b"\x00" * 187
    fresh = json.loads((tmp_path / "cloud_lane.json").read_text(encoding="utf-8"))
    assert fresh["batches"] == [] and fresh["closes"] == []
    assert len([m for m in messages if "unreadable" in m]) == 1

    lane.tick()  # second tick on the fresh file
    assert len([m for m in messages if "unreadable" in m]) == 1  # 0 further lines


def test_a_valid_state_file_is_left_alone(tmp_path: Path):
    messages: list[str] = []
    lane = _closed_lane(tmp_path, messages)
    (tmp_path / "cloud_lane.json").write_text('{"batches": [], "closes": []}', encoding="utf-8")

    lane.tick()

    assert [m for m in messages if "unreadable" in m] == []
    assert not [p for p in tmp_path.iterdir() if ".broken-" in p.name]


def test_a_broken_name_clash_gets_a_numbered_suffix(tmp_path: Path):
    messages: list[str] = []
    lane = _closed_lane(tmp_path, messages)
    stamp = UTC_NOW.astimezone(LOCAL).strftime("%Y%m%d-%H%M%S")
    (tmp_path / f"cloud_lane.json.broken-{stamp}").write_bytes(b"old")
    (tmp_path / "cloud_lane.json").write_bytes(b"\x00" * 5)

    lane.tick()

    assert (tmp_path / f"cloud_lane.json.broken-{stamp}").read_bytes() == b"old"
    assert (tmp_path / f"cloud_lane.json.broken-{stamp}-2").read_bytes() == b"\x00" * 5


# -------------------------------------------- acceptance: open lane, one message, `in-cloud` ------

def test_open_lane_sends_one_message_with_the_two_pob_free_issues_only(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    lane = _lane(tmp_path, gh, claude)
    d, local = _dispatcher(tmp_path, gh, lane)

    d.tick()

    assert len(claude.messages) == 1
    message = claude.messages[0]
    assert "#35, #42" in message and "#74" not in message
    assert "docs/agents/orch.md" in message and "No PoB here" in message
    assert cl.IN_CLOUD_LABEL in gh.labels(35) and cl.IN_CLOUD_LABEL in gh.labels(42)
    assert cl.IN_CLOUD_LABEL not in gh.labels(74)
    assert local.started == [[74]]  # the local ORCH is offered only the plain issue

    d.tick()  # nothing new
    assert len(claude.messages) == 1

    gh.add(90, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL), created_at="2026-09-23T00:00:00Z")
    d.tick()
    assert len(claude.messages) == 2 and "#90" in claude.messages[1]
    assert "#35" not in claude.messages[1] and "#42" not in claude.messages[1]
    assert len(local.started) == 1  # still exactly one local ORCH session


def test_the_monitor_line_shows_the_open_lane(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    cl.record_credits(1.49, credits_file=tmp_path / "cloud_credits.json", now=lambda: UTC_NOW)
    lane = _lane(tmp_path, gh, claude)

    lane.tick()

    line = cl.monitor_line(tmp_path / "cloud_lane.json")
    assert line["open"] is True and line["in_cloud"] == [35, 42]
    assert line["line"] == ("Cloud lane: open · session cse_017nWUZBDWZ6JhFHD4UKuJQH · "
                            "~$248.51 left · in the cloud: #35, #42")


# -------------------------------------------------------- acceptance: one `/compact`, then none ---

def test_a_batch_whose_issues_all_closed_gets_exactly_one_compact(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    lane = _lane(tmp_path, gh, claude)

    lane.tick()
    assert claude.compacts == 0

    gh.close_issue(35)
    result = lane.tick()  # only one of the two: no compact yet
    assert claude.compacts == 0 and result.closes == (35,)
    assert cl.IN_CLOUD_LABEL not in gh.labels(35)  # a close on GitHub is the issue's end (#58)

    gh.close_issue(42)
    result = lane.tick()
    assert claude.compacts == 1 and result.compacted is True

    for _ in range(3):
        lane.tick()
    assert claude.compacts == 1  # and none on the following ticks


# ---------------------------------------------------------------- acceptance: `ok:false` ----------

def test_ok_false_closes_the_lane_and_gives_the_issues_back(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    lane = _lane(tmp_path, gh, claude)
    d, local = _dispatcher(tmp_path, gh, lane)

    d.tick()
    assert cl.IN_CLOUD_LABEL in gh.labels(35) and cl.IN_CLOUD_LABEL in gh.labels(42)

    claude.ok = False
    gh.add(90, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL), created_at="2026-09-23T00:00:00Z")
    result = d.tick()

    bodies = gh.comment_bodies(LANE_ISSUE)
    closed = [b for b in bodies if b.startswith(cl.CLOSED_PREFIX)]
    assert len(closed) == 1 and closed[0].startswith(f"{cl.CLOSED_PREFIX}{cl.GONE_WHY}")
    assert bodies[-1] == cl.GONE_ASK
    assert cl.HUMAN_LABEL in gh.labels(LANE_ISSUE)
    assert cl.IN_CLOUD_LABEL not in gh.labels(35) and cl.IN_CLOUD_LABEL not in gh.labels(42)
    assert result.lane.closed == cl.GONE_WHY

    # one "Waiting on you" item, with that exact ask (the monitor's own rule, #55)
    records = monitor_issues.parse_issue_records([{
        "number": LANE_ISSUE, "title": cl.LANE_TITLE, "state": "OPEN", "createdAt": "2026-09-27T09:00:00Z",
        "labels": [{"name": n} for n in gh.labels(LANE_ISSUE)],
        "comments": [{"body": b} for b in bodies],
    }])
    waiting = monitor_issues.waiting_on_you(records, now=UTC_NOW)
    assert waiting["badge"] == 1 and waiting["items"][0]["ask"] == cl.GONE_ASK

    # the next tick: the local ORCH is offered them again (the lane sends nothing more)
    local._sessions.clear()  # the first session ended; the dispatcher may start the next one
    d.sessions.clear()
    before = len(claude.sent)
    d.tick()
    assert local.started[-1] == [35, 42, 74, 90] and len(claude.sent) == before


def test_a_non_zero_rc_is_the_same_gone_path(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    claude.returncode = 1
    lane = _lane(tmp_path, gh, claude)

    result = lane.tick()

    assert result.closed == cl.GONE_WHY
    assert [b for b in gh.comment_bodies(LANE_ISSUE) if b.startswith(cl.CLOSED_PREFIX)]


def test_parse_send_result_reads_the_98_shapes():
    ok = cl.parse_send_result(0, '﻿{"ok":true,"session_id":"cse_1","url":"https://claude.ai/code/x"}')
    assert ok.ok is True and ok.session_id == "cse_1"
    bad = cl.parse_send_result(0, '{"ok":false,"session_id":"cse_1","error":"session not found"}')
    assert bad.ok is False and bad.error == "session not found"
    assert cl.parse_send_result(1, "", "boom").ok is False
    assert cl.parse_send_result(0, "not json").ok is False


# ------------------------------------------------------- acceptance: the credits estimate ---------

def test_the_credits_estimate_numbers():
    assert cl.credits_left(1.49, 29) == 16.51
    assert cl.credits_left(1.49, 30) == 8.51
    assert cl.credits_left(None, 30) is None


def test_29_cloud_closes_keep_the_lane_open_and_30_close_it(tmp_path: Path):
    def run(closes: int) -> tuple[FakeGhRunner, cl.LaneTick]:
        gh, claude = FakeGhRunner(), FakeClaudeRunner()
        gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment()])
        cl.record_credits(1.49, credits_file=tmp_path / f"credits-{closes}.json", now=lambda: UTC_NOW)
        state = tmp_path / f"lane-{closes}.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"batches": [], "closes": [
            {"issue": 1000 + i, "ts": "2026-09-28T09:30:00+00:00"} for i in range(closes)]}), encoding="utf-8")
        lane = cl.CloudLane(gh=cl.LaneGh(runner=gh, log=lambda m: None),
                            cloud=cl.CloudCli(runner=claude), state_file=state,
                            credits_file=tmp_path / f"credits-{closes}.json", log=lambda m: None,
                            now=lambda: UTC_NOW, local_now=lambda: UTC_NOW.astimezone(LOCAL))
        return gh, lane.tick()

    gh29, result29 = run(29)
    assert result29.dollars_left == 16.51 and result29.open is True
    assert [b for b in gh29.comment_bodies(LANE_ISSUE) if b.startswith(cl.CLOSED_PREFIX)] == []

    gh30, result30 = run(30)
    assert result30.dollars_left == 8.51 and result30.open is False
    closed = [b for b in gh30.comment_bodies(LANE_ISSUE) if b.startswith(cl.CLOSED_PREFIX)]
    assert len(closed) == 1 and "$8.51" in closed[0]


def test_a_reading_only_counts_the_closes_after_it(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment()])
    credits = tmp_path / "cloud_credits.json"
    cl.record_credits(1.49, credits_file=credits, now=lambda: UTC_NOW)
    state = tmp_path / "cloud_lane.json"
    state.write_text(json.dumps({"batches": [], "closes": [
        {"issue": 1, "ts": "2026-09-20T00:00:00+00:00"},          # before the reading: not counted
        {"issue": 2, "ts": "2026-09-28T09:30:00+00:00"},          # after it: counted
    ]}), encoding="utf-8")
    lane = cl.CloudLane(gh=cl.LaneGh(runner=gh, log=lambda m: None), cloud=cl.CloudCli(runner=claude),
                        state_file=state, credits_file=credits, log=lambda m: None,
                        now=lambda: UTC_NOW, local_now=lambda: UTC_NOW.astimezone(LOCAL))

    assert lane.tick().dollars_left == cl.credits_left(1.49, 1) == 240.51


# ------------------------------------------------------- acceptance: the weekly reset (Thu 20:00) --

def test_a_tick_at_thursday_20_00_local_closes_the_lane(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,),
           comments=[_open_comment(created="2026-10-01T10:00:00Z")])  # Thu 13:00 local
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL))
    lane = _lane(tmp_path, gh, claude, local=datetime(2026, 10, 1, 20, 0, tzinfo=LOCAL))

    result = lane.tick()

    closed = [b for b in gh.comment_bodies(LANE_ISSUE) if b.startswith(cl.CLOSED_PREFIX)]
    assert len(closed) == 1 and closed[0].startswith(f"{cl.CLOSED_PREFIX}weekly reset")
    assert result.closed == "weekly reset" and claude.sent == []  # nothing is sent into a closing lane


def test_one_minute_before_the_reset_the_lane_stays_open(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment(created="2026-10-01T10:00:00Z")])
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL))
    lane = _lane(tmp_path, gh, claude, local=datetime(2026, 10, 1, 19, 59, tzinfo=LOCAL))

    result = lane.tick()

    assert result.open is True and result.sent == (35,)
    assert [b for b in gh.comment_bodies(LANE_ISSUE) if b.startswith(cl.CLOSED_PREFIX)] == []


def test_last_weekly_reset_is_the_latest_thursday_20_00():
    assert cl.last_weekly_reset(datetime(2026, 10, 1, 20, 0, tzinfo=LOCAL)) == \
        datetime(2026, 10, 1, 20, 0, tzinfo=LOCAL)
    assert cl.last_weekly_reset(datetime(2026, 10, 1, 19, 59, tzinfo=LOCAL)) == \
        datetime(2026, 9, 24, 20, 0, tzinfo=LOCAL)
    assert cl.last_weekly_reset(datetime(2026, 9, 28, 12, 0, tzinfo=LOCAL)) == \
        datetime(2026, 9, 24, 20, 0, tzinfo=LOCAL)


# --------------------------------------------------------------- the lane's state on the issue ----

def test_the_latest_state_comment_is_the_lane():
    assert cl.parse_lane_state([]) == (False, None, None, None)
    assert cl.parse_lane_state([_open_comment("cse_a"), {"body": "a report", "createdAt": "x"}]) == \
        (True, "cse_a", None, "2026-09-27T09:00:00Z")
    open_, session, why, _ = cl.parse_lane_state([_open_comment("cse_a"), _closed_comment("weekly reset")])
    assert (open_, session, why) == (False, None, "weekly reset")
    open_, session, _, _ = cl.parse_lane_state([_closed_comment(), _open_comment("cse_b")])
    assert (open_, session) == (True, "cse_b")


def test_a_new_session_clears_the_waiting_on_you_ask(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL, cl.HUMAN_LABEL),
           comments=[_closed_comment(cl.GONE_WHY), {"body": cl.GONE_ASK, "createdAt": "x"},
                     _open_comment("cse_new")])
    lane = _lane(tmp_path, gh, claude)

    result = lane.tick()

    assert result.open is True and result.session == "cse_new"
    assert cl.HUMAN_LABEL not in gh.labels(LANE_ISSUE)


def test_an_in_cloud_issue_that_closes_after_the_lane_closed_still_loses_the_label(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_closed_comment("weekly reset")])
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL, cl.IN_CLOUD_LABEL), open=False)

    result = _lane(tmp_path, gh, claude).tick()

    assert result.closes == (35,) and cl.IN_CLOUD_LABEL not in gh.labels(35)
    assert claude.sent == []


def test_an_unreadable_in_cloud_read_skips_the_tick(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    _two_pob_free_and_one_plain(gh, lane_comments=[_open_comment()])
    gh.fail_in_cloud_list = True

    result = _lane(tmp_path, gh, claude).tick()

    assert claude.sent == [] and result.sent == ()


def test_a_blocked_pob_free_issue_is_not_sent(tmp_path: Path):
    gh, claude = FakeGhRunner(), FakeClaudeRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment()])
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL), blockers=(42,))
    gh.add(42, labels=(cl.READY_LABEL,))
    messages: list[str] = []

    result = _lane(tmp_path, gh, claude, messages=messages).tick()

    assert result.sent == () and claude.sent == []
    assert any("#35 (blocked by #42)" in m for m in messages)


# ------------------------------------------------------------------------- the three CLI commands --

def test_lane_link_creates_the_labels_and_the_issue_on_first_use_then_prints_the_link():
    gh = FakeGhRunner()

    text = cl.lane_link_command(cl.LaneGh(runner=gh, log=lambda m: None))

    assert gh.labels_created == [cl.LANE_LABEL, cl.POB_FREE_LABEL, cl.IN_CLOUD_LABEL]
    assert len(gh.issues_created) == 1 and gh.issues_created[0][0] == cl.LANE_TITLE
    number = next(iter(gh.issues))
    assert f"Cloud lane issue: #{number}" in text
    link = text.split("\n\n")[-1].strip()
    assert link.startswith(cl.LINK_BASE + "?")
    assert "scripts%2Fcloud_setup.sh" in link and "Cloud+lane+open%3A+session" in link
    assert f"issue+%23{number}" in link


def test_lane_link_reuses_the_standing_issue():
    gh = FakeGhRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,))

    text = cl.lane_link_command(cl.LaneGh(runner=gh, log=lambda m: None))

    assert gh.issues_created == [] and f"#{LANE_ISSUE}" in text


def test_the_open_prompt_names_the_setup_script_and_the_state_line():
    prompt = cl.build_open_prompt(LANE_ISSUE)
    assert cl.SETUP_SCRIPT in prompt and cl.OPEN_PREFIX in prompt and f"#{LANE_ISSUE}" in prompt


def test_lane_close_posts_the_closed_comment():
    gh = FakeGhRunner()
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment()])

    assert cl.lane_close_command("the owner said so", cl.LaneGh(runner=gh, log=lambda m: None)) is True
    assert gh.comment_bodies(LANE_ISSUE)[-1] == f"{cl.CLOSED_PREFIX}the owner said so"
    assert cl.parse_lane_state([{"body": b} for b in gh.comment_bodies(LANE_ISSUE)])[0] is False


def test_lane_credits_records_the_reading_with_its_time(tmp_path: Path):
    path = tmp_path / "cloud_credits.json"

    first = cl.record_credits(1.49, credits_file=path, now=lambda: UTC_NOW)
    second = cl.record_credits(12.30, credits_file=path,
                               now=lambda: UTC_NOW + timedelta(hours=5))

    assert first["used_dollars"] == 1.49 and first["read_at"] == "2026-09-28T09:00:00+00:00"
    assert second["used_dollars"] == 12.30 and len(second["readings"]) == 2
    assert cl.read_credits(path)["used_dollars"] == 12.30


def test_the_cli_wires_the_three_lane_commands(tmp_path: Path, monkeypatch, capsys):
    from tools.agentops import cli

    calls: list[tuple] = []
    # since #150 the `lane` command is registered by this module, not imported into the core's CLI.
    monkeypatch.setattr(cl, "lane_link_command", lambda: calls.append(("link",)) or "LINK TEXT")
    monkeypatch.setattr(cl, "lane_close_command", lambda why: calls.append(("close", why)) or True)
    monkeypatch.setattr(cl, "lane_credits_command",
                        lambda used: calls.append(("credits", used)) or {"used_dollars": used, "read_at": "t"})

    assert cli.main(["lane", "link"]) == 0
    assert cli.main(["lane", "close", "--why", "owner"]) == 0
    assert cli.main(["lane", "credits", "--used", "1.49"]) == 0
    assert calls == [("link",), ("close", "owner"), ("credits", 1.49)]
    assert "LINK TEXT" in capsys.readouterr().out


# ------------------------------------------------------- the dispatcher never offers an in-cloud ---

def test_the_local_orch_is_never_offered_an_in_cloud_issue(tmp_path: Path):
    gh = FakeGhRunner()
    gh.add(35, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL, cl.IN_CLOUD_LABEL))
    gh.add(74, labels=(cl.READY_LABEL,))
    d, local = _dispatcher(tmp_path, gh, lane=None)

    d.tick()

    assert local.started == [[74]]


def test_a_lane_that_raises_never_ends_the_dispatcher_tick(tmp_path: Path):
    class Boom:
        def tick(self):
            raise RuntimeError("gh exploded")

    gh = FakeGhRunner()
    gh.add(74, labels=(cl.READY_LABEL,))
    d, local = _dispatcher(tmp_path, gh, lane=Boom())

    d.tick()

    assert local.started == [[74]]


# ------------------------------------------------------------------------------- areas (#319) ---

AREAS = ["area:orchestration", "area:builds", "area:runs", "area:crafting"]


def _three_area_cases(gh: FakeGhRunner) -> None:
    gh.add(1, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL, "area:builds"))
    gh.add(2, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL))
    gh.add(3, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL, "area:builds", "area:runs"))


def test_area_rule_drops_no_area_and_two_areas_once(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "_settings", lambda: {"areas": AREAS})
    gh = FakeGhRunner()
    _three_area_cases(gh)
    messages: list[str] = []
    lane = _lane(tmp_path, gh, FakeClaudeRunner(), messages=messages)
    assert lane._candidates({}) == [1]
    lines = [m for m in messages if "no area" in m or "two areas" in m]
    assert len(lines) == 2
    assert any("#2" in m and "no area" in m for m in lines)
    assert any("#3" in m and "two areas" in m for m in lines)
    assert lane._candidates({}) == [1]
    assert len([m for m in messages if "no area" in m or "two areas" in m]) == 2


def test_area_rule_off_when_areas_empty(tmp_path):
    gh = FakeGhRunner()
    _three_area_cases(gh)
    assert sorted(_lane(tmp_path, gh, FakeClaudeRunner())._candidates({})) == [1, 2, 3]


def test_lane_issue_created_with_one_area_label(monkeypatch):
    for setting, expected in (("area:orchestration", ["area:orchestration"]), ("", [])):
        monkeypatch.setattr(cl, "_settings", lambda s=setting: {"code_issue_area": s})
        gh = FakeGhRunner()
        number = cl.LaneGh(runner=gh, log=lambda m: None).ensure_lane_issue()
        assert [x for x in gh.labels(number) if x.startswith("area:")] == expected


def test_lane_issue_passes_the_ticket_shape_check():
    from tools.agentops.ticket_shape import check

    gh = FakeGhRunner()
    cl.lane_link_command(cl.LaneGh(runner=gh, log=lambda m: None))
    title, body = gh.issues_created[0]
    assert check(title, body) == []
