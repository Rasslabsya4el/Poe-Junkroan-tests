"""tools/agentops/monitor_issues.py (#55): "Waiting on you" and the "Issues" board -- against a
fake `gh` (no real subprocess, no writes to GitHub) and a fake job list."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools.agentops import monitor_issues as mi  # noqa: E402

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _label(name: str) -> dict:
    return {"name": name}


def _issue(number: int, *, title: str = "", body: str = "", created_at: str = "2026-09-20T12:00:00Z",
          closed_at: str | None = None, state: str = "OPEN", labels: tuple[str, ...] = (),
          assignees: tuple[str, ...] = (), comments: list[dict] | None = None,
          blocked_by: tuple[int, ...] = ()) -> dict:
    return {
        "number": number, "title": title or f"issue {number}", "body": body,
        "createdAt": created_at, "closedAt": closed_at, "state": state,
        "labels": [_label(l) for l in labels],
        "assignees": [{"login": a} for a in assignees],
        "comments": comments or [],
        "blockedBy": {"nodes": [{"number": b, "state": "OPEN"} for b in blocked_by]},
    }


class FakeGh:
    """A fake `gh`: one canned page, and a call counter (the "one call per refresh" check)."""

    def __init__(self, data: list[dict]) -> None:
        self._data = data
        self.calls = 0

    def list_all(self) -> list[dict]:
        self.calls += 1
        return self._data


# ------------------------------------------------------------------------------ parsing ----------

def test_parse_issue_records_blockers_and_runs_daemon_marker():
    data = [
        _issue(1, blocked_by=(2,), comments=[{"body": "<!-- runs-daemon result -->\nfoo"}]),
        _issue(2, blocked_by=(1,) + (), state="CLOSED"),
    ]
    # blocker #2 is CLOSED itself but blocks #1 as an open node in #1's own list; #1's blockedBy
    # node carries its own state, not #2's -- set explicitly:
    data[0]["blockedBy"] = {"nodes": [{"number": 2, "state": "OPEN"}]}
    records = mi.parse_issue_records(data)
    by_number = {r.number: r for r in records}
    assert by_number[1].open_blockers == (2,)
    assert by_number[1].runs_daemon_result is True
    assert by_number[2].open is False


# ------------------------------------------------------------------------- waiting on you ---------

def test_waiting_on_you_oldest_first_with_ask_line():
    data = [
        _issue(10, title="old one", created_at="2026-09-20T00:00:00Z", labels=("ready-for-human",),
              body="First body line.\nmore"),
        _issue(11, title="newer", created_at="2026-09-25T00:00:00Z", labels=("needs-info",),
              comments=[{"body": "First comment line?\nmore"}]),
        _issue(12, title="not waiting", labels=("ready-for-agent",)),
        _issue(13, title="closed waiting", state="CLOSED", labels=("needs-info",)),
    ]
    result = mi.waiting_on_you(mi.parse_issue_records(data), now=NOW)
    assert result["badge"] == 2
    numbers = [it["number"] for it in result["items"]]
    assert numbers == [10, 11]  # oldest first
    assert result["items"][0]["ask"] == "First body line."  # no comment -> issue's first line
    assert result["items"][1]["ask"] == "First comment line?"  # latest comment's first line
    for it in result["items"]:
        assert it["url"] == f"https://github.com/Rasslabsya4el/Poe-Junkroan/issues/{it['number']}"


def test_age_human_units():
    assert mi.age_human(5) == "5 s"
    assert mi.age_human(200) == "3 min"
    assert mi.age_human(3 * 3600) == "3 h"
    assert mi.age_human(2 * 24 * 3600) == "2 d"


# -------------------------------------------------------------------------------- board ------------

def test_next_column_order_and_blocked_at_bottom():
    data = [
        _issue(20, title="oldest, plain", created_at="2026-09-20T00:00:00Z", labels=("ready-for-agent",)),
        _issue(21, title="runs-daemon result", created_at="2026-09-24T00:00:00Z",
              labels=("ready-for-agent",), comments=[{"body": "<!-- runs-daemon result -->\nx"}]),
        _issue(22, title="blocked", created_at="2026-09-19T00:00:00Z", labels=("ready-for-agent",),
              blocked_by=(20,)),
        _issue(23, title="assigned, excluded", labels=("ready-for-agent",), assignees=("bob",)),
        _issue(24, title="wrong label, excluded", labels=("needs-info",)),
    ]
    board = mi.build_board(mi.parse_issue_records(data), now=NOW)
    numbers = [c["number"] for c in board["next"]]
    assert numbers == [21, 20, 22]  # runs-daemon result first, then oldest, blocked at the bottom
    blocked_card = board["next"][-1]
    assert blocked_card["tag"] == "blocked by #20"


def test_in_progress_column_uses_held_session_name():
    data = [
        _issue(30, title="worked by orch", labels=(), assignees=("bob",)),
        _issue(31, title="assigned, no live session", labels=(), assignees=("carol",)),
        _issue(32, title="unassigned", labels=("ready-for-agent",)),
    ]
    board = mi.build_board(mi.parse_issue_records(data), now=NOW, held_issues={30: "orch #30"})
    by_number = {c["number"]: c for c in board["in_progress"]}
    assert set(by_number) == {30, 31}
    assert by_number[30]["tag"] == "orch #30"
    assert by_number[31]["tag"] == "carol"


def test_waiting_for_run_column_matches_job_issues():
    data = [
        _issue(40, title="has a queued job"),
        _issue(41, title="no job"),
        _issue(42, title="closed with a job", state="CLOSED"),
    ]
    board = mi.build_board(mi.parse_issue_records(data), now=NOW, job_issues={40, 42})
    numbers = [c["number"] for c in board["waiting_for_run"]]
    assert numbers == [40]  # #42 is closed -> excluded


def test_needs_owner_column():
    data = [
        _issue(50, labels=("ready-for-human",)),
        _issue(51, labels=("needs-info",)),
        _issue(52, labels=("ready-for-agent",)),
    ]
    board = mi.build_board(mi.parse_issue_records(data), now=NOW)
    numbers = {c["number"] for c in board["needs_owner"]}
    assert numbers == {50, 51}


def test_done_this_week_column_excludes_older_closures():
    data = [
        _issue(60, state="CLOSED", closed_at="2026-09-24T12:00:00Z"),  # 2 days ago
        _issue(61, state="CLOSED", closed_at="2026-09-01T12:00:00Z"),  # weeks ago
        _issue(62, state="OPEN"),
    ]
    board = mi.build_board(mi.parse_issue_records(data), now=NOW)
    numbers = [c["number"] for c in board["done_this_week"]]
    assert numbers == [60]


def test_live_job_issues_from_injected_jobs():
    class FakeJob:
        def __init__(self, issue):
            self.issue = issue

    assert mi.live_job_issues(jobs=[FakeJob(7), FakeJob(None), FakeJob(9)]) == {7, 9}


# ---------------------------------------------------------------------------------- caching --------

def test_cached_issue_records_one_gh_call_within_window():
    data = [_issue(70)]
    gh = FakeGh(data)
    clock = {"t": 1000.0}
    cache = mi._IssuesCache()

    first = mi.cached_issue_records(gh, cache_seconds=60.0, clock=lambda: clock["t"], cache=cache)
    clock["t"] += 30.0
    second = mi.cached_issue_records(gh, cache_seconds=60.0, clock=lambda: clock["t"], cache=cache)
    assert gh.calls == 1  # within the 60 s window: no second gh call
    assert first == second

    clock["t"] += 40.0  # now 70 s after the first fetch
    mi.cached_issue_records(gh, cache_seconds=60.0, clock=lambda: clock["t"], cache=cache)
    assert gh.calls == 2  # past the window: refetched


def test_build_dashboard_shape():
    dashboard = mi.build_dashboard(mi.parse_issue_records([_issue(80, labels=("ready-for-human",))]), now=NOW)
    assert set(dashboard) == {"waiting_on_you", "board"}
    assert set(dashboard["board"]) == {"next", "in_progress", "waiting_for_run", "needs_owner", "done_this_week"}
