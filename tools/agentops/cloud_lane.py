"""The cloud lane (#121, decided in #91, grill `docs/research/2026-09-27-cloud-lane-grill.md`).

While the lane is OPEN, every PoB-free ready issue is worked by the owner's standing cloud session
on the Cloud session credits instead of by the local ORCH. The lane opens **only on the owner's
word through the brain** (never by a threshold): the brain prints the pre-filled link
(`python -m tools.agentops lane link`), the owner clicks twice, and the new session itself posts
`Cloud lane open: session <id>` on the standing lane issue. The lane's whole state is that issue's
latest state comment -- nothing here remembers a decision the owner did not make on GitHub.

    python -m tools.agentops lane link                  # the pre-filled claude.ai/code link
    python -m tools.agentops lane close --why "..."     # post `Cloud lane closed: <why>`
    python -m tools.agentops lane credits --used 1.49   # the exact `used_dollars` read in Chrome

Every tick the dispatcher (`dispatch.Dispatcher`, which owns the loop) calls `CloudLane.tick()`:

1. the lane issue is read (state comment + labels);
2. every issue labelled `in-cloud` that has closed on GitHub is recorded as a cloud close and
   loses the label -- the #58 path, a close on GitHub is an issue's end (done open or closed, so a
   lane the owner closed still lets its last issues out of the lane);
3. open lane only: the closing rules (Thu 20:00 local weekly reset; the credits estimate under
   `LOW_CREDITS_DOLLARS`), then one `/compact` per message whose issues have all closed, then ONE
   message with every PoB-free ready issue not already in the cloud (each gets `in-cloud`, so the
   local ORCH is never offered it);
4. a send that answers `ok:false` or exits non-zero: the lane closes (`session gone`), the issues in
   the cloud lose `in-cloud` and go back to the local ORCH, and the lane issue gets
   `ready-for-human` with the ask the monitor's "Waiting on you" shows.

Only `LaneGh` (gh) and `CloudCli` (claude) touch the world, both behind an injectable `runner`, so
the tests drive the whole tick with a fake `gh` and a fake `claude` and never a real cloud session.
`tools/agentops` imports no `junkroan` (`worktree.py`'s note), so this module is standard library
only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import core_settings
from .dispatch import ISSUE_WRITE_VERBS, READ_MEMO_SECONDS, ReadMemo
from .gh_call import GH_TIMEOUT_SECONDS, run_gh
from .util import AgentOpsError, no_window_flags, now as _now_str, read_json, write_json
from .worktree import ROOT

REPO = "Rasslabsya4el/Poe-Junkroan"
ORCH_DOC = "docs/agents/orch.md"
SETUP_SCRIPT = "scripts/cloud_setup.sh"

#: the standing lane issue: one open issue with this label, its state in its latest state comment.
LANE_LABEL = "cloud-lane"
LANE_TITLE = "Cloud lane"
#: the brain's label on an issue whose acceptance needs no PoB run (item 4).
POB_FREE_LABEL = "pob-free"
#: on an issue the cloud session is working, so the local ORCH is never offered it (item 5).
IN_CLOUD_LABEL = "in-cloud"
READY_LABEL = "ready-for-agent"
NEEDS_INFO_LABEL = "needs-info"
HUMAN_LABEL = "ready-for-human"

#: the two state comments (item 1). A comment starting with neither is not state (a report, a note).
OPEN_PREFIX = "Cloud lane open: session "
CLOSED_PREFIX = "Cloud lane closed: "

#: what "Waiting on you" shows when a send finds the session gone (item 6).
GONE_ASK = "Cloud lane: the session is gone; tell the brain if you want a new one"
GONE_WHY = "session gone"

#: the Cloud session credits pool (#39: $250, expire 2026-11-05) and the estimate's per-issue cost:
#: the TOP of #39's $3-8 an issue, so the lane closes early rather than draw the plan.
CREDITS_TOTAL_DOLLARS = 250.0
PER_ISSUE_DOLLARS = 8.0
LOW_CREDITS_DOLLARS = 10.0

#: the plan's weekly reset in LOCAL time: Thursday 20:00 (#39; the week began Thu 24.09 20:00).
WEEKLY_RESET_WEEKDAY = 3  # Monday is 0, so Thursday is 3
WEEKLY_RESET_HOUR = 20

CREDITS_FILE = ROOT / "var" / "agentops" / "cloud_credits.json"
#: what the monitor reads (item 7) and what groups the sent messages into batches for `/compact`.
LANE_STATE_FILE = ROOT / "var" / "agentops" / "cloud_lane.json"

#: The pre-filled new-session form of claude.ai/code (#98 arm A: opened in Chrome it fills the form
#: -- Default environment, Poe-Junkroan, main, Opus 5.5 High -- and the owner presses Send; the link
#: never sends by itself). Only these three constants change if the docs' pre-fill parameter names
#: differ from what the acceptance's Browser-pane check sees.
LINK_BASE = "https://claude.ai/code/new"
LINK_REPO_PARAM = "repo"
LINK_PROMPT_PARAM = "prompt"

_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")


def _log(message: str) -> None:
    sys.stderr.write(f"{_now_str()} cloud-lane: {message}\n")
    sys.stderr.flush()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    """Local wall clock, tz-aware (the weekly reset is Thu 20:00 LOCAL)."""

    return datetime.now(timezone.utc).astimezone()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


# -- gh -------------------------------------------------------------------------------------------

#: one `gh` process: `(args, stdin) -> CompletedProcess`. Injected, so tests use a fake.
GhRunner = Callable[[list[str], "str | None"], "subprocess.CompletedProcess[str]"]


@dataclass(slots=True)
class LaneIssue:
    """One PoB-free candidate for the cloud (the same ordering as the local queue: oldest first)."""

    number: int
    created_at: str
    labels: tuple[str, ...] = ()
    open_blockers: tuple[int, ...] = ()


@dataclass(slots=True)
class LaneState:
    """The lane as GitHub tells it: the standing issue and its latest state comment."""

    issue: int | None = None
    open: bool = False
    session: str | None = None
    why: str | None = None
    #: when the state comment was posted (the weekly-reset rule compares against it).
    since: str | None = None
    labels: tuple[str, ...] = ()


def parse_lane_state(comments: list[dict] | None) -> tuple[bool, str | None, str | None, str | None]:
    """`(open, session, why, since)` from an issue's comments: the LATEST comment starting with
    `Cloud lane open: session <id>` or `Cloud lane closed: <why>` wins; with neither present the
    lane is closed and nothing was ever opened."""

    for item in reversed(list(comments or [])):
        body = str((item or {}).get("body") or "")
        first = next((line.strip() for line in body.splitlines() if line.strip()), "")
        created = (item or {}).get("createdAt") or None
        if first.startswith(OPEN_PREFIX):
            rest = first[len(OPEN_PREFIX):].strip().strip("`").strip()
            session = rest.split()[0].strip("`") if rest else ""
            if session:
                return True, session, None, created
        if first.startswith(CLOSED_PREFIX):
            return False, None, first[len(CLOSED_PREFIX):].strip() or None, created
    return False, None, None, None


def _settings() -> dict:
    """The installation's settings; an unreadable file means no settings (area rules off)."""

    try:
        return core_settings.load()
    except RuntimeError:
        return {}


class LaneGh:
    """Every `gh` call the lane makes, behind one injectable runner (no caching: one call, one
    process). Nothing here creates an issue or a label except `ensure_lane_issue`, which is the
    one-time first-use step (item 1)."""

    def __init__(self, repo: str = REPO, cwd: Path = ROOT, timeout: float = GH_TIMEOUT_SECONDS,
                 runner: GhRunner | None = None, log: Callable[[str], None] = _log,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.repo = repo
        self.cwd = Path(cwd)
        self.timeout = timeout
        self.log = log
        self._runner = runner
        #: #1113: the lane's one-point reads are memoized inside a lane tick; a write drops the memo.
        self.memo = ReadMemo(clock)

    def _run(self, args: list[str], stdin: str | None = None) -> "subprocess.CompletedProcess[str]":
        try:
            if self._runner is not None:
                return self._runner(args, stdin)
            return run_gh(args, cwd=self.cwd, input=stdin, timeout=self.timeout)
        finally:
            if len(args) > 1 and args[0] == "issue" and args[1] in ISSUE_WRITE_VERBS:
                self.memo.drop()

    def _json(self, args: list[str], what: str, ttl: float | None = None) -> Any:
        """`ttl` (#1113) reads through the memo when given: `None` is no memo, not a tick-scoped read."""

        result = self._run(args) if ttl is None else self.memo.read(args, ttl, lambda: self._run(args))
        if result.returncode != 0:
            self.log(f"gh {what} failed: {(result.stderr or '').strip()[:200]}")
            return None
        try:
            return json.loads(result.stdout or "null")
        except ValueError as exc:
            self.log(f"gh {what}: invalid JSON ({exc})")
            return None

    # -- the standing lane issue -------------------------------------------------------------------

    def lane_issue(self) -> int | None:
        """The open issue labelled `cloud-lane` (the lowest number, so a stray second one never
        takes over); `None` when there is none yet or `gh` failed."""

        data = self._json(["issue", "list", "-R", self.repo, "--state", "open", "--label", LANE_LABEL,
                           "--json", "number", "--limit", "20"], "issue list --label cloud-lane",
                          READ_MEMO_SECONDS)
        numbers = sorted(int(item["number"]) for item in data or [] if "number" in item)
        return numbers[0] if numbers else None

    def lane_view(self, number: int) -> LaneState:
        """The lane issue's labels and comments in one read -> `LaneState`."""

        data = self._json(["issue", "view", str(number), "-R", self.repo, "--json",
                           "comments,labels,state"], f"issue view {number}")
        if not isinstance(data, dict):
            return LaneState(issue=number)
        open_, session, why, since = parse_lane_state(data.get("comments") or [])
        labels = tuple(str(label.get("name", "")) for label in data.get("labels") or [])
        return LaneState(issue=number, open=open_, session=session, why=why, since=since, labels=labels)

    def ensure_label(self, name: str, color: str, description: str) -> bool:
        """Create one label if it is missing (`gh label create`; "already exists" is success). The
        one-time first-use step: no test ever runs this against GitHub."""

        result = self._run(["label", "create", name, "-R", self.repo, "--color", color,
                            "--description", description])
        if result.returncode == 0:
            return True
        detail = (result.stderr or result.stdout or "").strip()
        if "already exists" in detail.lower():
            return True
        self.log(f"gh label create {name} failed: {detail[:200]}")
        return False

    def ensure_lane_issue(self) -> int | None:
        """The standing lane issue, created on first use together with the three labels."""

        for name, color, description in (
            (LANE_LABEL, "1d76db", "The standing cloud-lane issue: its latest state comment is the lane"),
            (POB_FREE_LABEL, "0e8a16", "Acceptance needs no PoB run, so the cloud lane can take it"),
            (IN_CLOUD_LABEL, "5319e7", "The standing cloud session is working it; not for the local ORCH"),
        ):
            self.ensure_label(name, color, description)
        existing = self.lane_issue()
        if existing is not None:
            return existing
        argv = ["issue", "create", "-R", self.repo, "--title", LANE_TITLE, "--label", LANE_LABEL]
        area = _settings().get("code_issue_area") or ""
        if area:
            argv += ["--label", area]
        result = self._run(argv + ["--body-file", "-"], stdin=LANE_ISSUE_BODY)
        if result.returncode != 0:
            self.log(f"gh issue create ({LANE_TITLE}) failed: {(result.stderr or '').strip()[:200]}")
            return None
        match = _ISSUE_URL_RE.search(result.stdout or "")
        if not match:
            self.log(f"gh issue create: no issue number in {(result.stdout or '')[:200]!r}")
            return None
        return int(match.group(1))

    # -- the issues ---------------------------------------------------------------------------------

    def pob_free_candidates(self) -> list[LaneIssue]:
        """Open, `ready-for-agent` AND `pob-free`, unassigned. `in-cloud` and natively blocked ones
        are dropped by the caller, which logs why."""

        data = self._json(["issue", "list", "-R", self.repo, "--state", "open", "--label", READY_LABEL,
                           "--label", POB_FREE_LABEL, "--search", "no:assignee", "--json",
                           "number,createdAt,labels,blockedBy", "--limit", "200"],
                          "issue list --label pob-free")
        out: list[LaneIssue] = []
        for item in data or []:
            nodes = ((item.get("blockedBy") or {}).get("nodes")) or []
            out.append(LaneIssue(
                number=int(item["number"]), created_at=str(item.get("createdAt") or ""),
                labels=tuple(str(label.get("name", "")) for label in item.get("labels") or []),
                open_blockers=tuple(sorted(int(n["number"]) for n in nodes
                                           if str(n.get("state") or "").upper() != "CLOSED" and "number" in n)),
            ))
        out.sort(key=lambda c: (c.created_at, c.number))
        return out

    def in_cloud_issues(self) -> dict[int, bool] | None:
        """`{number: still open}` for every issue labelled `in-cloud`, open OR closed (a closed one
        keeps the label until the tick removes it -- that is how a cloud close is seen). `None` when
        `gh` failed, never a false empty."""

        data = self._json(["issue", "list", "-R", self.repo, "--state", "all", "--label", IN_CLOUD_LABEL,
                           "--json", "number,state", "--limit", "200"], "issue list --label in-cloud")
        if data is None:
            return None
        return {int(item["number"]): str(item.get("state") or "").upper() != "CLOSED" for item in data
                if "number" in item}

    def comment(self, number: int, body: str) -> bool:
        result = self._run(["issue", "comment", str(number), "-R", self.repo, "--body-file", "-"], stdin=body)
        if result.returncode != 0:
            self.log(f"gh issue comment {number} failed: {(result.stderr or '').strip()[:200]}")
            return False
        return True

    def add_label(self, number: int, label: str) -> bool:
        result = self._run(["issue", "edit", str(number), "-R", self.repo, "--add-label", label])
        if result.returncode != 0:
            self.log(f"gh issue edit {number} --add-label {label} failed: {(result.stderr or '').strip()[:200]}")
            return False
        return True

    def remove_label(self, number: int, label: str) -> bool:
        result = self._run(["issue", "edit", str(number), "-R", self.repo, "--remove-label", label])
        if result.returncode != 0:
            self.log(f"gh issue edit {number} --remove-label {label} failed: "
                     f"{(result.stderr or '').strip()[:200]}")
            return False
        return True


LANE_ISSUE_BODY = f"""## For the human
- **What:** one standing issue that holds the state of the cloud lane, the session that takes tickets needing no PoB run.
- **Why:** the lane needs a single place whose latest state comment says whether it is open.
- **Plan:** the dispatcher reads and writes the state comments here; the issue stays open for good.
- **Result:** not set yet
- **Undo:** two-way door (one revert); touches the cloud lane only.

## For the agent
The standing **cloud lane** issue (#121). Its state is the LATEST comment here
starting with `{OPEN_PREFIX}<id>` or `{CLOSED_PREFIX}<why>`; nothing else in this issue is state.

While the lane is open, every open `{READY_LABEL}` + `{POB_FREE_LABEL}` issue is fed to that cloud
session by the dispatcher (`tools/agentops/cloud_lane.py`) and labelled `{IN_CLOUD_LABEL}`, so the
local ORCH is never offered it. The lane opens only on the owner's word through the brain
(`python -m tools.agentops lane link`), and closes at the plan's weekly reset (Thu 20:00 local), on
`lane close`, when the credits estimate falls under ${LOW_CREDITS_DOLLARS:.0f}, or when a send finds
the session gone.

Do not close this issue: it stands open for good.
"""


# -- claude -p --cloud ------------------------------------------------------------------------------

#: one `claude` process: `(args, stdin) -> CompletedProcess`. Injected, so tests use a fake.
ClaudeRunner = Callable[[list[str], "str | None"], "subprocess.CompletedProcess[str]"]


@dataclass(slots=True)
class SendResult:
    """What one `claude -p --cloud <id> --output-format json` send answered (#98: rc 0 in 2-3 s,
    `{ok, session_id, url}`, or `{ok: false, session_id, error}`)."""

    ok: bool
    session_id: str | None = None
    url: str | None = None
    error: str | None = None
    returncode: int = 0


def parse_send_result(returncode: int, stdout: str | None, stderr: str | None = None) -> SendResult:
    """The send's rc + stdout -> `SendResult`. Anything that is not `{"ok": true, ...}` is a
    failure, including a non-zero rc and unparsable output (the lane then closes, item 6)."""

    text = (stdout or "").lstrip("﻿").strip()
    data: Any = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    if isinstance(data, dict):
        ok = bool(data.get("ok")) and returncode == 0
        return SendResult(ok=ok, session_id=data.get("session_id"), url=data.get("url"),
                          error=None if ok else str(data.get("error") or f"rc {returncode}"),
                          returncode=returncode)
    detail = (text or (stderr or "").strip() or "no output")[:200]
    return SendResult(ok=False, error=f"rc {returncode}: {detail}", returncode=returncode)


class CloudCli:
    """The one `claude` call the lane makes: feed the standing session ONE message.

    `claude -p --cloud <id> --output-format json` with the message on stdin (#98's `send.ps1`, which
    is what was measured: rc 0 in 2-3 s). The process is hidden (no console window, like
    `ocserver.py`'s detached launch) but awaited, because its answer is what decides whether the lane
    stays open -- an `ok:false` closes it."""

    def __init__(self, exe: Path | str = "claude.exe", cwd: Path = ROOT, timeout: float = 120.0,
                 runner: ClaudeRunner | None = None, log: Callable[[str], None] = _log) -> None:
        self.exe = exe
        self.cwd = Path(cwd)
        self.timeout = timeout
        self.log = log
        self._runner = runner

    def send(self, session: str, message: str) -> SendResult:
        exe = self.exe() if callable(self.exe) else self.exe  # #611: a callable is looked up per send
        args = [str(exe), "-p", "--cloud", session, "--output-format", "json"]
        if self._runner is not None:
            result = self._runner(args, message)
            return parse_send_result(result.returncode, result.stdout, result.stderr)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            result = subprocess.run(args, cwd=str(self.cwd), input=message, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace",
                                    timeout=self.timeout, creationflags=flags)
        except (OSError, subprocess.SubprocessError) as exc:
            return SendResult(ok=False, error=f"send failed: {exc!r}"[:200], returncode=-1)
        return parse_send_result(result.returncode, result.stdout, result.stderr)


# -- the messages ------------------------------------------------------------------------------------

def build_cloud_message(issues: list[int] | tuple[int, ...]) -> str:
    """The one message a batch of PoB-free issues goes to the cloud session in (item 5)."""

    listed = ", ".join(f"#{n}" for n in issues) or "none"
    return (
        f"Work these ready issues now: {listed}. Follow {ORCH_DOC} as the local ORCH does: work them "
        f"in parallel through subagents (one per issue), and close each issue on GitHub with its "
        f"numbers, having merged and pushed main. No PoB here: this session runs on a Linux VM with "
        f"no Path of Building, so an issue that turns out to need a PoB run is parked back with a "
        f"comment saying so instead of guessed at. Do not touch issues other than {listed}."
    )


def build_open_prompt(lane_issue: int, repo: str = REPO) -> str:
    """The pre-filled first turn of a new standing session (item 2): set the image up, post the
    lane's open comment with this session's own id, then wait to be fed."""

    return (
        f"You are the standing cloud session of the cloud lane (issue #{lane_issue} of {repo}).\n"
        f"1. Run `bash {SETUP_SCRIPT}` (it builds the python3.12 `.venv` this repo needs).\n"
        f"2. Post one comment on issue #{lane_issue} whose FIRST line is exactly "
        f"`{OPEN_PREFIX}<this session's own cloud session id>` (the `cse_...` id of this session, "
        f"the one in this page's URL / in `claude --cloud`'s own output). Write nothing before that "
        f"line: the dispatcher reads it as the lane's state.\n"
        f"3. Then stop and wait. The dispatcher will send you follow-up messages, each naming the "
        f"issues to work; work each message as {ORCH_DOC} says and close every issue with its "
        f"numbers. Never start work that needs a PoB run: there is no Path of Building here."
    )


def lane_link(lane_issue: int, repo: str = REPO) -> str:
    """The pre-filled claude.ai/code link the brain gives the owner (two clicks: open, Send)."""

    query = urllib.parse.urlencode({LINK_REPO_PARAM: repo, LINK_PROMPT_PARAM: build_open_prompt(lane_issue, repo)})
    return f"{LINK_BASE}?{query}"


# -- the credits estimate ----------------------------------------------------------------------------

def credits_left(used_dollars: float | None, closes_since_reading: int, *,
                 total: float = CREDITS_TOTAL_DOLLARS, per_issue: float = PER_ISSUE_DOLLARS) -> float | None:
    """`total - used - per_issue x closes` (item 6b): the last exact `used_dollars` the brain read in
    Chrome, minus the TOP of #39's $3-8 an issue for every issue closed in the cloud since that
    reading, so the lane closes early rather than draw the plan. `None` without a reading."""

    if used_dollars is None:
        return None
    return round(total - float(used_dollars) - per_issue * int(closes_since_reading), 2)


def read_credits(credits_file: Path = CREDITS_FILE) -> dict[str, Any] | None:
    """The latest Chrome reading (`{used_dollars, read_at}`), or `None` when none was recorded."""

    data = read_json(Path(credits_file), default=None)
    if not isinstance(data, dict) or data.get("used_dollars") is None:
        return None
    return data


def record_credits(used_dollars: float, *, credits_file: Path = CREDITS_FILE,
                   now: Callable[[], datetime] = _utc_now) -> dict[str, Any]:
    """`lane credits --used <dollars>` (item 3): the exact reading with its time, appended to the
    file's history and kept as the latest."""

    path = Path(credits_file)
    data = read_json(path, default=None)
    history = list((data or {}).get("readings") or []) if isinstance(data, dict) else []
    reading = {"used_dollars": round(float(used_dollars), 2), "read_at": now().isoformat(timespec="seconds")}
    history.append(reading)
    out = {**reading, "readings": history}
    write_json(path, out)
    return out


# -- the weekly reset ---------------------------------------------------------------------------------

def last_weekly_reset(local: datetime) -> datetime:
    """The latest Thu 20:00 local at or before `local` (the plan's weekly reset, #39)."""

    days_back = (local.weekday() - WEEKLY_RESET_WEEKDAY) % 7
    candidate = (local - timedelta(days=days_back)).replace(
        hour=WEEKLY_RESET_HOUR, minute=0, second=0, microsecond=0)
    if candidate > local:
        candidate -= timedelta(days=7)
    return candidate


# -- one tick -----------------------------------------------------------------------------------------

@dataclass(slots=True)
class LaneTick:
    """What one `CloudLane.tick()` did, for the dispatcher's report and the tests."""

    open: bool = False
    session: str | None = None
    #: the issues named in the message sent this tick (empty when nothing was sent).
    sent: tuple[int, ...] = ()
    #: `/compact` was sent this tick (a batch whose every issue has closed).
    compacted: bool = False
    #: the lane closed this tick, with the reason written in the comment.
    closed: str | None = None
    #: still open and in the cloud after this tick.
    in_cloud: tuple[int, ...] = ()
    #: cloud closes seen this tick (the label was removed and the close recorded).
    closes: tuple[int, ...] = ()
    dollars_left: float | None = None


class CloudLane:
    """The lane's whole behaviour, one `tick()` per dispatcher tick. Owns no loop and no sleep."""

    def __init__(self, *, gh: LaneGh, cloud: CloudCli, state_file: Path | None = LANE_STATE_FILE,
                 credits_file: Path = CREDITS_FILE, log: Callable[[str], None] = _log,
                 now: Callable[[], datetime] = _utc_now,
                 local_now: Callable[[], datetime] = _local_now) -> None:
        self.gh = gh
        self.cloud = cloud
        self.state_file = Path(state_file) if state_file is not None else None
        self.credits_file = Path(credits_file)
        self.log = log
        self.now = now
        self.local_now = local_now
        #: the last set of skipped candidates logged, so one skip is logged once (dispatch.py's way).
        self._logged_skipped: tuple = ()
        self._logged_area: set[tuple[int, str]] = set()

    # -- the local record (batches for `/compact`, closes for the estimate, the monitor line) -------

    def _read_record(self) -> dict[str, Any]:
        data = None
        if self.state_file is not None:
            try:
                data = read_json(self.state_file, default=None)
            except AgentOpsError as exc:  # a broken file would fail every tick forever (#566)
                return self._set_broken_record_aside(exc)
        if not isinstance(data, dict):
            data = {}
        data.setdefault("batches", [])
        data.setdefault("closes", [])
        return data

    def _set_broken_record_aside(self, exc: Exception) -> dict[str, Any]:
        """Rename the unreadable state file to `<name>.broken-<stamp>` (never delete it); start empty."""
        name = self.state_file.name
        stamp = self.local_now().strftime("%Y%m%d-%H%M%S")
        target = self.state_file.with_name(f"{name}.broken-{stamp}")
        n = 2
        while target.exists():
            target = self.state_file.with_name(f"{name}.broken-{stamp}-{n}")
            n += 1
        try:
            os.replace(self.state_file, target)
            self.log(f"{name} unreadable ({exc}): moved to {target.name}, starting from an empty record")
        except OSError as os_exc:
            self.log(f"{name} unreadable ({exc}): could not move it aside ({os_exc!r}), "
                     "starting from an empty record")
        return {"batches": [], "closes": []}

    def _write_record(self, record: dict[str, Any]) -> None:
        if self.state_file is None:
            return
        try:
            write_json(self.state_file, record)
        except Exception as exc:  # the monitor's line is never worth breaking the loop for
            self.log(f"could not write {self.state_file.name} ({exc!r})")

    def _closes_since_reading(self, record: dict[str, Any], credits: dict[str, Any] | None) -> int:
        if credits is None:
            return 0
        read_at = _parse_ts(credits.get("read_at"))
        count = 0
        for entry in record.get("closes") or []:
            ts = _parse_ts((entry or {}).get("ts"))
            if read_at is None or (ts is not None and ts >= read_at):
                count += 1
        return count

    # -- the tick ------------------------------------------------------------------------------------

    def tick(self) -> LaneTick:
        if isinstance(self.gh, LaneGh):
            self.gh.memo.start_tick()  # #1113: the lane's memo is active from its first tick on
        number = self.gh.lane_issue()
        if number is None:  # no lane issue yet: the lane cannot be open (item 1)
            record = self._read_record()
            record.update({"updated": self.now().isoformat(timespec="seconds"), "open": False,
                           "session": None, "why": None, "issue": None, "in_cloud": [],
                           "dollars_left": None})
            self._write_record(record)
            return LaneTick()

        state = self.gh.lane_view(number)
        record = self._read_record()
        record["issue"] = number

        result = LaneTick(open=state.open, session=state.session)

        # (2) every in-cloud issue that closed on GitHub is done (the #58 path), open lane or not.
        in_cloud = self.gh.in_cloud_issues()
        if in_cloud is None:
            self.log("could not read the in-cloud issues; skipping this tick")
            return result
        closed_now = sorted(n for n, still_open in in_cloud.items() if not still_open)
        if closed_now:
            known = {int(e["issue"]) for e in record.get("closes") or [] if (e or {}).get("issue") is not None}
            stamp = self.now().isoformat(timespec="seconds")
            for issue in closed_now:
                if issue not in known:
                    record["closes"].append({"issue": issue, "ts": stamp})
                self.gh.remove_label(issue, IN_CLOUD_LABEL)
            self.log("closed in the cloud: " + ", ".join(f"#{n}" for n in closed_now))
            result.closes = tuple(closed_now)
        still = sorted(n for n, still_open in in_cloud.items() if still_open)
        result.in_cloud = tuple(still)

        credits = read_credits(self.credits_file)
        left = credits_left(None if credits is None else credits.get("used_dollars"),
                            self._closes_since_reading(record, credits))
        result.dollars_left = left

        if not state.open:
            self._save(record, state, result, left)
            return result

        # A new session answers the "the session is gone" ask: the lane issue stops waiting on the owner.
        if HUMAN_LABEL in state.labels:
            self.gh.remove_label(number, HUMAN_LABEL)

        # (6) the closing rules, before anything is sent into a lane that is about to close.
        why = self._closing_reason(state, left)
        if why is not None:
            self._close(number, why, record, result)
            self._save(record, state, result, left)
            return result

        # (5) one `/compact` per message whose issues have all closed.
        closed_ever = {int(e["issue"]) for e in record.get("closes") or [] if (e or {}).get("issue") is not None}
        for batch in record.get("batches") or []:
            if batch.get("compacted"):
                continue
            issues = [int(n) for n in batch.get("issues") or []]
            if issues and all(n in closed_ever for n in issues):
                sent = self.cloud.send(state.session or "", "/compact")
                if not sent.ok:
                    self._session_gone(number, sent, still, record, result)
                    self._save(record, state, result, left)
                    return result
                batch["compacted"] = True
                result.compacted = True
                self.log("every issue of the message " + ", ".join(f"#{n}" for n in issues)
                         + " has closed; sent /compact")
                break  # one `/compact` a tick is enough; the next batch compacts on the next tick

        # (5) one message with every PoB-free ready issue not already in the cloud.
        offered = self._candidates(in_cloud)
        if offered:
            message = build_cloud_message(offered)
            sent = self.cloud.send(state.session or "", message)
            if not sent.ok:
                self._session_gone(number, sent, still, record, result)
                self._save(record, state, result, left)
                return result
            for issue in offered:
                self.gh.add_label(issue, IN_CLOUD_LABEL)
            record["batches"].append({"sent_at": self.now().isoformat(timespec="seconds"),
                                      "issues": list(offered), "compacted": False})
            result.sent = tuple(offered)
            result.in_cloud = tuple(sorted(still + list(offered)))
            self.log(f"sent {', '.join(f'#{n}' for n in offered)} to the cloud session {state.session}")

        self._save(record, state, result, left)
        return result

    # -- the parts -------------------------------------------------------------------------------------

    def _candidates(self, in_cloud: dict[int, bool]) -> list[int]:
        """PoB-free, ready, unassigned, unblocked, not already in the cloud (one skip logged once)."""

        candidates = self.gh.pob_free_candidates()
        areas = set(_settings().get("areas") or [])
        if areas:
            dropped: set[tuple[int, str]] = set()
            kept = []
            for c in candidates:
                count = len(areas & set(c.labels))
                if count == 1:
                    kept.append(c)
                else:
                    dropped.add((c.number, "no area" if count == 0 else "two areas"))
            for number, why in sorted(dropped - self._logged_area):
                self.log(f"not sent: #{number} ({why})")
            self._logged_area = dropped
            candidates = kept
        skipped: list[tuple[int, str]] = []
        offered: list[int] = []
        for c in candidates:
            if c.number in in_cloud or IN_CLOUD_LABEL in c.labels:
                skipped.append((c.number, "already in the cloud"))
            elif NEEDS_INFO_LABEL in c.labels:
                skipped.append((c.number, "needs-info"))
            elif c.open_blockers:
                skipped.append((c.number, "blocked by " + ", ".join(f"#{b}" for b in c.open_blockers)))
            else:
                offered.append(c.number)
        key = tuple(skipped)
        if skipped and key != self._logged_skipped:
            self.log("not sent: " + "; ".join(f"#{n} ({why})" for n, why in skipped))
        self._logged_skipped = key
        return offered

    def _closing_reason(self, state: LaneState, left: float | None) -> str | None:
        """(a) the plan's weekly reset, (b) the credits estimate under $10 (item 6; (c) `lane close`
        is the owner's own comment, so it is already in `state`)."""

        local = self.local_now()
        reset = last_weekly_reset(local)
        opened = _parse_ts(state.since)
        if opened is not None and opened.astimezone(reset.tzinfo) < reset <= local:
            return "weekly reset"
        if left is not None and left < LOW_CREDITS_DOLLARS:
            return (f"credits estimate ${left:.2f} left, under ${LOW_CREDITS_DOLLARS:.0f} "
                    f"(${PER_ISSUE_DOLLARS:.0f} an issue since the last reading)")
        return None

    def _close(self, number: int, why: str, record: dict[str, Any], result: LaneTick) -> None:
        self.gh.comment(number, f"{CLOSED_PREFIX}{why}\n\nRestart the lane the same way it opened: the "
                                f"owner tells the brain \"открой lane\", the brain runs "
                                f"`python -m tools.agentops lane link` and the owner clicks twice. "
                                f"The dispatcher needs no restart.")
        record["batches"] = []
        result.open = False
        result.closed = why
        result.session = None
        self.log(f"cloud lane closed: {why}")

    def _session_gone(self, number: int, sent: SendResult, still_open: list[int],
                      record: dict[str, Any], result: LaneTick) -> None:
        """A send answered `ok:false` or exited non-zero (item 6): the lane closes, its issues go
        back to the local ORCH, and the lane issue waits on the owner."""

        self._close(number, GONE_WHY, record, result)
        self.log(f"the cloud send failed ({sent.error}); the lane is closed")
        for issue in still_open:
            self.gh.remove_label(issue, IN_CLOUD_LABEL)
        result.in_cloud = ()
        self.gh.comment(number, GONE_ASK)
        self.gh.add_label(number, HUMAN_LABEL)
        result.closed = GONE_WHY

    def _save(self, record: dict[str, Any], state: LaneState, result: LaneTick, left: float | None) -> None:
        record.update({
            "updated": self.now().isoformat(timespec="seconds"),
            "open": bool(result.open),
            "session": result.session,
            "why": result.closed if result.closed is not None else (state.why if not result.open else None),
            "in_cloud": list(result.in_cloud),
            "dollars_left": left,
        })
        self._write_record(record)


# -- the monitor's one line (item 7) ------------------------------------------------------------------

def monitor_line(state_file: Path = LANE_STATE_FILE) -> dict[str, Any]:
    """One line for the monitor's Overview: lane open / closed, session id, estimated $ left, the
    issues in the cloud. Read-only, from what the dispatcher's last tick wrote (the monitor never
    calls `gh` or `claude` for it)."""

    try:
        data = read_json(Path(state_file), default=None)
    except AgentOpsError:  # a half-written file must not break the whole snapshot (#565)
        return {"open": False, "session": None, "dollars_left": None, "in_cloud": [],
                "line": "Cloud lane: state file unreadable"}
    if not isinstance(data, dict):
        data = {}
    open_ = bool(data.get("open"))
    session = data.get("session") or None
    in_cloud = [int(n) for n in data.get("in_cloud") or []]
    left = data.get("dollars_left")
    if open_:
        parts = [f"session {session or '?'}",
                 f"~${float(left):.2f} left" if isinstance(left, (int, float)) else "credits not read yet",
                 ("in the cloud: " + ", ".join(f"#{n}" for n in in_cloud)) if in_cloud else "nothing in the cloud"]
        line = "Cloud lane: open · " + " · ".join(parts)
    else:
        why = data.get("why") or ("never opened" if not data else "closed")
        line = f"Cloud lane: closed ({why})"
        if in_cloud:
            line += " · still in the cloud: " + ", ".join(f"#{n}" for n in in_cloud)
    return {"open": open_, "session": session, "dollars_left": left if isinstance(left, (int, float)) else None,
            "in_cloud": in_cloud, "line": line}


# -- the CLI's three commands (item 2, 3) -------------------------------------------------------------

def lane_link_command(gh: LaneGh | None = None) -> str:
    """`lane link`: the label + the standing lane issue exist (created on first use), then the
    pre-filled link. Prints what the owner does with it: open in Chrome, press Send, twice a click."""

    gh = gh if gh is not None else LaneGh()
    number = gh.ensure_lane_issue()
    if number is None:
        return ""
    link = lane_link(number)
    return (f"Cloud lane issue: #{number}\nGive the owner this link (open in Chrome, then press Send "
            f"-- two clicks; the link never sends by itself):\n\n{link}\n")


def lane_close_command(why: str, gh: LaneGh | None = None) -> bool:
    """`lane close --why "<text>"`: post the closed comment; the next tick sees the lane closed."""

    gh = gh if gh is not None else LaneGh()
    number = gh.lane_issue()
    if number is None:
        return False
    return gh.comment(number, f"{CLOSED_PREFIX}{why}")


def lane_credits_command(used_dollars: float, *, credits_file: Path = CREDITS_FILE) -> dict[str, Any]:
    """`lane credits --used <dollars>`: the exact `used_dollars` the brain read in Chrome, with its
    time; every later estimate counts $8 an issue closed in the cloud since it."""

    return record_credits(used_dollars, credits_file=credits_file)


def build_cloud_lane(exe: Path | str | None = None) -> CloudLane:
    """The production lane: real `gh`, real `claude.exe` (found the way the dispatcher finds it)."""

    if exe is None:
        from .dispatch import find_claude_exe

        exe = find_claude_exe  # #611: called per send, never held
    return CloudLane(gh=LaneGh(), cloud=CloudCli(exe))


# -- what the core loads this module for ------------------------------------------------------------
#
# The lane is a local module of this installation (ADR 0109, extension point 4): the core's
# dispatcher and CLI know nothing of it, and it joins them only at the points `extensions.py` offers.


def _add_lane_parser(sub) -> None:
    lane = sub.add_parser("lane", help="the cloud lane: PoB-free issues to the standing cloud session (#121)")
    lane_sub = lane.add_subparsers(dest="lane_command", required=True)
    lane_sub.add_parser("link", help="print the pre-filled claude.ai/code link the owner clicks twice")
    lane_close = lane_sub.add_parser("close", help="post `Cloud lane closed: <why>` on the lane issue")
    lane_close.add_argument("--why", required=True)
    lane_credits = lane_sub.add_parser("credits", help="record the exact used_dollars read in Chrome")
    lane_credits.add_argument("--used", type=float, required=True, dest="used")


def _run_lane(args) -> int:
    if args.lane_command == "link":
        text = lane_link_command()
        if not text:
            print("error: no cloud-lane issue (gh failed); nothing printed")
            return 1
        print(text)
        return 0
    if args.lane_command == "close":
        if not lane_close_command(args.why):
            print("error: could not post the closed comment (no lane issue, or gh failed)")
            return 1
        print(f'cloud lane closed: {args.why}')
        return 0
    if args.lane_command == "credits":
        record = lane_credits_command(args.used)
        print(f"recorded used_dollars {record['used_dollars']} at {record['read_at']}")
        return 0
    return 2


def _add_no_lane_flag(parser) -> None:
    parser.add_argument("--no-lane", action="store_true",
                        help="do not tick the cloud lane (#121); by default it is ticked and is "
                             "inert until the owner opens it")


def _setup(dispatcher) -> None:
    #: the lane of this dispatcher, ticked before the local ORCH so an issue it takes is labelled
    #: `in-cloud` before the ready queue is read. `None`: no lane at all (tests, and `--no-lane`).
    dispatcher.lane = None
    #: the last set of candidates the lane holds that was logged, so one skip is logged once (#121).
    dispatcher._logged_in_cloud = ()


def _start(dispatcher, args) -> None:
    """The real dispatcher gets the production lane, unless the command line said `--no-lane`."""

    if getattr(args, "no_lane", False):
        return
    # #611: the lookup itself is handed over, not the path it found today
    resolve = getattr(dispatcher.claude, "resolve_exe", None)
    dispatcher.lane = build_cloud_lane(resolve if resolve is not None else dispatcher.claude.exe)


def _tick(dispatcher, report) -> None:
    """Registered with a guard under the name below: a failure is logged `cloud lane tick failed
    (...); continuing` and the dispatcher's loop goes on."""

    report.extras.setdefault("lane", None)
    lane = getattr(dispatcher, "lane", None)
    if lane is None:
        return
    report.extras["lane"] = lane.tick()


def _candidates(dispatcher, candidates: list, *, offering: bool) -> list:
    """What the lane holds is not offered to the local ORCH (#121); the offering call logs it once
    per changed set, the wake (#137) silently skips the same issues."""

    in_cloud = [c for c in candidates if IN_CLOUD_LABEL in c.labels]
    if offering:
        if in_cloud and tuple(c.number for c in in_cloud) != dispatcher._logged_in_cloud:
            dispatcher.log("in the cloud lane, not offered to the local ORCH: "
                           + ", ".join(f"#{c.number}" for c in in_cloud))
        dispatcher._logged_in_cloud = tuple(c.number for c in in_cloud)
    return [c for c in candidates if IN_CLOUD_LABEL not in c.labels]


def register(core) -> None:
    core.command("lane", _add_lane_parser, _run_lane, after="dispatch")
    core.dispatch_flag(_add_no_lane_flag)
    core.setup(_setup)
    core.start(_start)
    core.tick("cloud lane", _tick, phase="before", guard=True)
    core.candidates(_candidates)


__all__ = [
    "CREDITS_FILE",
    "CREDITS_TOTAL_DOLLARS",
    "CloudCli",
    "CloudLane",
    "GONE_ASK",
    "GONE_WHY",
    "HUMAN_LABEL",
    "IN_CLOUD_LABEL",
    "LANE_LABEL",
    "LANE_STATE_FILE",
    "LANE_TITLE",
    "LOW_CREDITS_DOLLARS",
    "LaneGh",
    "LaneIssue",
    "LaneState",
    "LaneTick",
    "OPEN_PREFIX",
    "CLOSED_PREFIX",
    "PER_ISSUE_DOLLARS",
    "POB_FREE_LABEL",
    "SendResult",
    "build_cloud_lane",
    "build_cloud_message",
    "build_open_prompt",
    "credits_left",
    "lane_close_command",
    "lane_credits_command",
    "lane_link",
    "lane_link_command",
    "last_weekly_reset",
    "monitor_line",
    "parse_lane_state",
    "parse_send_result",
    "read_credits",
    "record_credits",
    "register",
]
