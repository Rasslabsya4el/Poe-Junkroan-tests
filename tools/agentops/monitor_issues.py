"""Data for the monitor's "Waiting on you" and "Issues" tabs (#55).

One `gh issue list` call per refresh (`GhIssuesCli.list_all`, cached `CACHE_SECONDS` by
`cached_issue_records`), one `Store().jobs()` read for "Waiting for a run", and the live ORCH
session names `monitor.py` already reads off `claude agents --json --all` (passed in as
`held_issues`, never fetched again here). Nothing here writes to GitHub or starts PoB.

`build_dashboard` is the one entry point `monitor.py`'s extension point calls; everything else is
plumbing kept testable with a fake `gh` (no real subprocess) and a fake job list.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .dispatch import IssueSummary
from .gh_call import run_gh
from .runs_marker import RUNS_DAEMON_MARKER, order as order_candidates
from .worktree import ROOT

REPO = "Rasslabsya4el/Poe-Junkroan"
CACHE_SECONDS = 60.0

WAITING_LABELS = ("ready-for-human", "needs-info")
NEXT_LABEL = "ready-for-agent"

#: `gh issue list --json` fields this module needs across every column (one call for all of them).
ISSUE_FIELDS = "number,title,body,createdAt,closedAt,state,labels,assignees,comments,blockedBy"


def _issue_url(number: int) -> str:
    return f"https://github.com/{REPO}/issues/{number}"


# ---------------------------------------------------------------------------------------- gh -----

class GhIssuesCli:
    """The one `gh` call this module makes: every issue, open and closed, one page."""

    def __init__(self, repo: str = REPO, cwd: Path = ROOT, timeout: float = 60.0) -> None:
        self.repo = repo
        self.cwd = Path(cwd)
        self.timeout = timeout

    def list_all(self) -> list[dict[str, Any]]:
        result = run_gh(
            ["issue", "list", "-R", self.repo, "--state", "all", "--json", ISSUE_FIELDS, "--limit", "500"],
            cwd=self.cwd, timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh issue list failed: {(result.stderr or '').strip()[:200]}")
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []


@dataclass(slots=True)
class IssueRecord:
    """One issue, as every column needs it."""

    number: int
    title: str
    body: str
    created_at: str
    closed_at: str | None
    open: bool
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    latest_comment: str | None
    open_blockers: tuple[int, ...]
    runs_daemon_result: bool


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def parse_issue_records(data: list[dict]) -> list[IssueRecord]:
    """`gh issue list --json ISSUE_FIELDS` output -> `IssueRecord`s, no filtering."""

    out: list[IssueRecord] = []
    for item in data if isinstance(data, list) else []:
        comments = item.get("comments") or []
        latest = comments[-1] if comments else None
        latest_body = (latest or {}).get("body") if latest else None
        nodes = ((item.get("blockedBy") or {}).get("nodes")) or []
        blockers = tuple(sorted(int(n["number"]) for n in nodes
                                if str(n.get("state") or "").upper() != "CLOSED" and "number" in n))
        labels = tuple(label.get("name", "") for label in item.get("labels") or [])
        assignees = tuple(a.get("login", "") for a in item.get("assignees") or [])
        out.append(IssueRecord(
            number=int(item["number"]),
            title=str(item.get("title") or ""),
            body=str(item.get("body") or ""),
            created_at=str(item.get("createdAt") or ""),
            closed_at=item.get("closedAt") or None,
            open=str(item.get("state") or "").upper() != "CLOSED",
            labels=labels,
            assignees=assignees,
            latest_comment=latest_body,
            open_blockers=blockers,
            runs_daemon_result=bool(latest_body) and str(latest_body).startswith(RUNS_DAEMON_MARKER),
        ))
    return out


# ------------------------------------------------------------------------------------- caching ----

@dataclass(slots=True)
class _IssuesCache:
    fetched_at: float | None = None
    records: list[IssueRecord] = field(default_factory=list)


_CACHE = _IssuesCache()


def cached_issue_records(gh: GhIssuesCli, *, cache_seconds: float = CACHE_SECONDS,
                         clock: Callable[[], float] = time.monotonic,
                         cache: _IssuesCache | None = None) -> list[IssueRecord]:
    """`gh.list_all()` parsed to records, refetched only every `cache_seconds` (the page itself
    refreshes every ~3 s; one real `gh` call every 60 s is the point)."""

    cache = cache if cache is not None else _CACHE
    now = clock()
    if cache.fetched_at is not None and (now - cache.fetched_at) < cache_seconds:
        return cache.records
    cache.records = parse_issue_records(gh.list_all())
    cache.fetched_at = now
    return cache.records


# ---------------------------------------------------------------------------- age (human, #7) -----

def age_human(seconds: float | None) -> str:
    """A human age: seconds, minutes, hours, then days (principle 7; longer-lived than a PoB
    run's `human_duration`, an open issue can sit for weeks)."""

    if seconds is None:
        return "-"
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{seconds:.0f} s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} min"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.0f} h"
    return f"{hours / 24:.0f} d"


def _seconds_since(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds())


# -------------------------------------------------------------------------- Waiting on you --------

def waiting_on_you(records: list[IssueRecord], *, now: datetime) -> dict[str, Any]:
    """Open issues labelled `ready-for-human` or `needs-info`, oldest first."""

    matches = [r for r in records if r.open and any(label in WAITING_LABELS for label in r.labels)]
    matches.sort(key=lambda r: r.created_at)
    items = []
    for r in matches:
        ask = _first_line(r.latest_comment) if r.latest_comment else _first_line(r.body)
        items.append({
            "number": r.number, "title": r.title, "url": _issue_url(r.number),
            "age_human": age_human(_seconds_since(r.created_at, now)), "ask": ask,
        })
    return {"badge": len(items), "items": items}


# ---------------------------------------------------------------------------------- the board -----

def _next_column(records: list[IssueRecord]) -> list[dict[str, Any]]:
    """`ready-for-agent`, unassigned, in the dispatcher's own order (runs-daemon results first, then
    oldest, blocked ones dropped to the bottom -- `runs_marker.order`, imported, not copied)."""

    candidates = [
        IssueSummary(number=r.number, created_at=r.created_at,
                     latest_comment=r.latest_comment or "", open_blockers=r.open_blockers)
        for r in records
        if r.open and NEXT_LABEL in r.labels and not r.assignees
    ]
    by_number = {r.number: r for r in records}
    unblocked = order_candidates([c for c in candidates if not c.open_blockers])
    blocked = order_candidates([c for c in candidates if c.open_blockers])

    cards = []
    for c in unblocked + blocked:
        r = by_number[c.number]
        tag = f"blocked by {', '.join(f'#{b}' for b in c.open_blockers)}" if c.open_blockers else ""
        cards.append({"number": r.number, "title": r.title, "url": _issue_url(r.number), "tag": tag})
    return cards


def _in_progress_column(records: list[IssueRecord], *, held_issues: dict[int, str]) -> list[dict[str, Any]]:
    """Assigned, open issues; tagged with the live ORCH session name when one works it."""

    cards = []
    for r in records:
        if not r.open or not r.assignees:
            continue
        tag = held_issues.get(r.number) or ", ".join(r.assignees)
        cards.append({"number": r.number, "title": r.title, "url": _issue_url(r.number), "tag": tag})
    cards.sort(key=lambda c: c["number"])
    return cards


def _waiting_for_run_column(records: list[IssueRecord], *, job_issues: set[int]) -> list[dict[str, Any]]:
    cards = []
    for r in records:
        if r.open and r.number in job_issues:
            cards.append({"number": r.number, "title": r.title, "url": _issue_url(r.number), "tag": "queued/running"})
    cards.sort(key=lambda c: c["number"])
    return cards


def _needs_owner_column(records: list[IssueRecord]) -> list[dict[str, Any]]:
    cards = []
    for r in records:
        if not r.open:
            continue
        matched = [label for label in r.labels if label in WAITING_LABELS]
        if matched:
            cards.append({"number": r.number, "title": r.title, "url": _issue_url(r.number), "tag": matched[0]})
    cards.sort(key=lambda c: c["number"])
    return cards


def _done_this_week_column(records: list[IssueRecord], *, now: datetime) -> list[dict[str, Any]]:
    cards = []
    for r in records:
        if r.open or not r.closed_at:
            continue
        age = _seconds_since(r.closed_at, now)
        if age is not None and age <= 7 * 24 * 3600:
            cards.append({"number": r.number, "title": r.title, "url": _issue_url(r.number),
                         "tag": age_human(age) + " ago"})
    cards.sort(key=lambda c: c["number"])
    return cards


def live_job_issues(jobs: list | None = None) -> set[int]:
    """Open issue numbers with a queued or running job in the runs store (`junkroan.runs.store`,
    the same file `scripts/machine_load.py` reads). `jobs` overrides the real store, for tests."""

    if jobs is None:
        from junkroan.runs.store import LIVE_STATES, Store

        jobs = [j for j in Store().jobs() if j.state in LIVE_STATES]
    return {j.issue for j in jobs if getattr(j, "issue", None) is not None}


def build_board(records: list[IssueRecord], *, now: datetime, held_issues: dict[int, str] | None = None,
                job_issues: set[int] | None = None) -> dict[str, Any]:
    held_issues = held_issues or {}
    job_issues = job_issues if job_issues is not None else set()
    return {
        "next": _next_column(records),
        "in_progress": _in_progress_column(records, held_issues=held_issues),
        "waiting_for_run": _waiting_for_run_column(records, job_issues=job_issues),
        "needs_owner": _needs_owner_column(records),
        "done_this_week": _done_this_week_column(records, now=now),
    }


# --------------------------------------------------------------------------------- entry point -----

def build_dashboard(records: list[IssueRecord], *, now: datetime, held_issues: dict[int, str] | None = None,
                    job_issues: set[int] | None = None) -> dict[str, Any]:
    """`monitor.build_snapshot`'s "issues" key: both tabs' data from one set of records."""

    return {
        "waiting_on_you": waiting_on_you(records, now=now),
        "board": build_board(records, now=now, held_issues=held_issues, job_issues=job_issues),
    }


__all__ = [
    "CACHE_SECONDS",
    "GhIssuesCli",
    "IssueRecord",
    "age_human",
    "build_board",
    "build_dashboard",
    "cached_issue_records",
    "live_job_issues",
    "parse_issue_records",
    "waiting_on_you",
]
