"""Local live agent monitor (#52): one page, `python -m tools.agentops monitor [--port 8765]`.

Read-only, 127.0.0.1 only. One HTTP server serves the whole thing: `GET /` is a small HTML shell
that fetches `GET /api/snapshot` every ~3 s and renders it as TABS -- "Agents" (sessions + their
subagents, requirements 2-3) and "PoB runs" (the queue + the slot budget, requirement 4) -- so the
owner never opens a second page (the owner, 2026-09-26: "everything I open in a browser lives on
ONE local page with tabs"). The selected tab is kept in the URL hash (`#agents` / `#pob-runs`) so
a reload stays put.

TO ADD A THIRD TAB LATER: write one `_panel_<name>(...)` function that returns its JSON-able dict,
add its key to `build_snapshot`'s returned mapping, add one `<button data-tab="...">` + one
`<section id="tab-...">` + one `render<Name>(data)` JS function in `_PAGE_HTML` next to the
existing two, and list the tab name in `_TAB_IDS`. Nothing else in this file changes shape.

Never writes to a transcript. Never starts PoB (the runs panel only reads the jobs log and the
slot-budget files `scripts/machine_load.py` already reads). Binds `127.0.0.1` only -- never
`0.0.0.0`, never a hostname -- and prints no key or token value.

A control strip above the tabs (#54) lets the owner set a host's mode ("Free the PC" = `play`,
"Free the laptop" = `browser`) with an optional 30 min/1 h/2 h/4 h timer, through `junkroan.runs.
hosts.apply_timed_mode`; every `POST /api/mode` carries a random per-server token the page receives
embedded in its own HTML, so no other local page can call it. The timer's expiry itself lives in
`hosts.revert_expired_modes`, called once per `/api/snapshot` here and once per tick by the runs
daemon (#48) -- the file lock in `hosts.py` makes either caller winning harmless.

Cost and pricing arithmetic come from `scripts/token_meter.py` / `config/model_prices.json` by
import (this issue's own requirement 2), not reimplemented: `scripts/` has no `__init__.py`, so it
is put on `sys.path` the same way `token_meter.py` puts `src/` on it for `junkroan`.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import webbrowser
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping

# The agents panel moved to `monitor_agents` (E2a) so the collector can read it in a repo without this
# file. Every name below stays importable as `monitor.<name>` (re-export, explicit names).
from .monitor_agents import (  # noqa: F401
    _ANSWERED_CACHE, _COMPLETED_CACHE, _ISSUE_IN_NAME_RE, _MAIN_CACHE, _MODEL_ALIASES, _MODEL_ID_RE,
    _ORCH_NAME_RE, _SUBAGENT_CACHE, _Cache, _cache_key, _is_orch, _issue_from_name, _matches_state,
    _seconds_since, _tool_summary, DEFAULT_PRICES_PATH, DEFAULT_PROJECTS_DIR, REPO, ROOT, MainScan,
    answered_tool_use_ids, attach_held_issues, build_session_row, build_subagent_row, cached_main_scan,
    cached_subagent_turns, completed_agent_ids, display_model, live_sessions_raw, load_orch_state,
    model_display_name, panel_agents, scan_main_transcript, turn_cost_total,
)

SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
# The monitor is this repo's own module and reads the product's run hosts; `src` goes first so
# `junkroan` is the package, not `scripts/junkroan.py` (token_meter no longer adds it, #147).
SRC_DIR = ROOT / "src"
if str(SRC_DIR) in sys.path:
    sys.path.remove(str(SRC_DIR))
sys.path.insert(0, str(SRC_DIR))

import token_meter  # noqa: E402

from .cloud_lane import LANE_STATE_FILE, monitor_line as cloud_lane_line  # noqa: E402
from .dispatch import STATE_FILE as ORCH_STATE_FILE, ended_task_ids, find_claude_exe  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402

from .util import human_duration, no_window_flags  # noqa: E402
from . import monitor_issues  # noqa: E402
from . import monitor_dashboard  # noqa: E402  (Progress / Results / Cost / Events tabs, #56)

DEFAULT_PORT = 8765


#: #55: "Waiting on you" is the first tab, "Issues" (the board) goes after "PoB runs"; #56's four
#: tabs (Progress/Results/Cost/Events) go last.
_TAB_IDS = ("waiting-on-you", "agents", "pob-runs", "issues", "progress", "results", "cost", "events")


# ------------------------------------------------------------------------------------ PoB runs ---

def _job_duration_seconds(job, now: datetime) -> float | None:
    from junkroan.runs.store import STATES  # noqa: F401  (documents the state vocabulary in use)

    start = job.start_ts or job.submit_ts
    if not start:
        return None
    start_dt = token_meter.parse_timestamp(start)
    if start_dt is None:
        return None
    if job.state == "running":
        return _seconds_since(start_dt, now)
    end_dt = token_meter.parse_timestamp(job.end_ts) if job.end_ts else None
    if end_dt is None:
        return None
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    return max(0.0, (end_dt - start_dt).total_seconds())


def _job_row(job, *, now: datetime) -> dict[str, Any]:
    duration_seconds = _job_duration_seconds(job, now)
    return {
        "id": job.id,
        "host": job.host,
        "priority": job.priority,
        "issue": job.issue,
        "tag": job.tag,
        "state": job.state,
        # The filler mark (#132 requirement 6): a Filler is a run no issue waits for, so its row must
        # be readable as one at a glance and never look like work that is waiting on the owner.
        "filler": bool(getattr(job, "is_filler", False)),
        "duration_seconds": duration_seconds,
        "duration_human": human_duration(duration_seconds) if duration_seconds is not None else "-",
    }


def _daemon_row(
    host: str, status: dict[str, Any] | None, *,
    now: datetime, pid_alive: Callable[[int], bool] | None,
) -> dict[str, Any]:
    """One row of the daemon table (issue #73, requirement 3): host, pid, state, last-tick age,
    running/queued counts. `pid_alive` is `None` for a host this process cannot check locally (the
    laptop): its state then comes from the freshness of `last_tick` alone -- a dead laptop daemon's
    file simply goes stale within a few ticks, which is "keep it simple" per the spec."""

    if not status:
        return {"host": host, "pid": None, "state": "not running", "last_tick_age_human": None,
                "running": 0, "queued": 0, "fillers": "-", "fillers_ran_out": False,
                "fillers_message_pending": None}

    pid = status.get("pid")
    age_seconds: float | None = None
    last_tick = status.get("last_tick")
    if last_tick:
        try:
            last_dt = datetime.fromisoformat(str(last_tick))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_seconds = (now - last_dt).total_seconds()
        except ValueError:
            age_seconds = None

    from junkroan.runs.daemon import TICK_SECONDS, stale_after

    threshold = stale_after(status.get("tick_seconds", TICK_SECONDS))
    alive = True
    if pid_alive is not None and pid:
        try:
            alive = pid_alive(int(pid))
        except Exception:
            alive = True  # cannot tell locally; do not punish a host this process cannot probe

    if not pid or (pid_alive is not None and not alive):
        state = "not running"
    elif age_seconds is not None and age_seconds < threshold:
        state = "live"
    else:
        state = "stale"

    running = status.get("running") or []
    return {
        "host": host, "pid": pid, "state": state,
        "last_tick_age_human": human_duration(age_seconds) if age_seconds is not None else None,
        "running": len(running) if isinstance(running, list) else 0,
        "queued": status.get("queued") or 0,
        **_fillers_cell(status),
    }


def _fillers_cell(status: Mapping[str, Any]) -> dict[str, Any]:
    """The daemon row's filler columns (#132 requirement 6): how many are left and for how long.

    The hours come from the rule file's own `est_hours` and are rendered as a human duration
    (CLAUDE.md principle 7); `fillers ran out` says the host is taking its list again at the next
    seeds, and a pending message is one the host could not deliver to the brain itself (the laptop
    has no `claude`), so the owner sees it here instead of nowhere.
    """

    left = status.get("fillers_left")
    hours = status.get("fillers_hours_left")
    if left is None:
        cell = "-"
    else:
        cell = f"{left}"
        if hours is not None:
            try:
                cell = f"{left} / {human_duration(float(hours) * 3600)}"
            except (TypeError, ValueError):
                pass
        if status.get("fillers_ran_out"):
            cell += " (ran out)"
    broken = status.get("fillers_rule_broken")
    if broken:
        cell = "rule broken"
    return {
        "fillers": cell,
        "fillers_ran_out": bool(status.get("fillers_ran_out")),
        "fillers_message_pending": status.get("fillers_message_pending"),
    }


def panel_daemons(*, now: datetime | None = None, status_path: Path | None = None,
                  pid_alive: Callable[[int], bool] | None = None,
                  laptop_cache: Any = None) -> dict[str, Any]:
    """The runs-daemon status table (issue #73, requirement 3): one row for `pc` (read from the
    local `daemon-pc.json`), one for `laptop` (read from `laptop_cache`'s own reading -- the SAME
    SSH round trip #81 already pays for the laptop's jobs, never a second one).

    `status_path` / `pid_alive` are injected for tests; production leaves both `None`
    (`junkroan.runs.hosts.daemon_status_path("pc")` and the real `QueueBackend().pid_alive`).
    """

    from junkroan.runs import daemon as runs_daemon
    from junkroan.runs import hosts as runs_hosts

    now = now or datetime.now(timezone.utc)
    pc_path = status_path if status_path is not None else runs_hosts.daemon_status_path("pc")
    pc_status = runs_daemon.read_daemon_status(pc_path)
    pc_pid_alive = pid_alive if pid_alive is not None else runs_daemon.QueueBackend().pid_alive
    rows = [_daemon_row("pc", pc_status, now=now, pid_alive=pc_pid_alive)]

    if laptop_cache is not None:
        reading = laptop_cache.read()
        laptop_status = getattr(reading, "daemon_status", None)
        rows.append(_daemon_row("laptop", laptop_status, now=now, pid_alive=None))

    return {"rows": rows}


def panel_pob_runs(*, store=None, budget=None, slot_folder: Path | None = None,
                   now: datetime | None = None, max_rows: int = 50,
                   laptop_cache: Any = None, daemon_status_path: Path | None = None,
                   daemon_pid_alive: Callable[[int], bool] | None = None) -> dict[str, Any]:
    """Requirement 4 (#55) plus the laptop's own jobs next to the PC's (#81, requirement 1): the
    runs store (id, host, priority, issue, tag, state, duration) and the slot budget (busy /
    total), without starting PoB -- the same files `scripts/machine_load.py` reads. `daemons`
    (issue #73) is one row per host from `panel_daemons`.

    `laptop_cache` is a `junkroan.runs.remote_store.LaptopJobsCache` (or a fake with the same
    `.read()` shape in tests); `None` (the default) skips the laptop read entirely -- callers that
    want it pass the real process-wide cache (`junkroan.runs.remote_store.get_default_cache()`,
    one SSH-backed read of the laptop's own `jobs.jsonl` AND its `daemon-laptop.json`, cached so
    this call never blocks on a slow laptop for longer than the cache's own short read timeout).
    `build_snapshot` (the live monitor server) is the one production caller that passes it; tests
    never do, so no test opens a real SSH connection.
    """

    from junkroan.runs.store import LIVE_STATES, Store

    now = now or datetime.now(timezone.utc)
    store = store if store is not None else Store()
    jobs = list(store.jobs())

    laptop_status: dict[str, Any] | None = None
    if laptop_cache is not None:
        reading = laptop_cache.read()
        jobs = jobs + list(reading.jobs)
        laptop_status = {
            "ok": reading.ok,
            "stale": reading.stale,
            "pending": reading.pending,
            "age_human": human_duration(reading.age_seconds) if reading.age_seconds is not None else None,
            "error": reading.error,
        }

    jobs.sort(key=lambda j: (j.state not in LIVE_STATES, j.state != "running", j.submit_ts), reverse=False)
    jobs = jobs[:max_rows]
    job_rows = [_job_row(job, now=now) for job in jobs]

    slots: dict[str, Any]
    try:
        from junkroan.pob import slot_budget as _slot_budget

        folder = slot_folder if slot_folder is not None else _slot_budget.slot_dir()
        active_budget = budget if budget is not None else _slot_budget.load_budget()
        used = _slot_budget.busy_slots(folder, budget=active_budget)
        slots = {
            "host": _slot_budget.current_host(),
            "busy": len(used),
            "total": active_budget.total,
            "others_limit": active_budget.limit_for(_slot_budget.ROLE_OTHER),
            "period": active_budget.period,
            "window": active_budget.window(),
        }
    except Exception as exc:  # the panel must render even when the budget files are unreadable
        slots = {"error": str(exc)}

    daemons = panel_daemons(
        now=now, status_path=daemon_status_path, pid_alive=daemon_pid_alive, laptop_cache=laptop_cache,
    )

    result: dict[str, Any] = {"jobs": job_rows, "slots": slots, "daemons": daemons["rows"]}
    if laptop_status is not None:
        result["laptop"] = laptop_status
    return result


# ----------------------------------------------------------------------------------- snapshot ----

def _held_issues(sessions_raw: list[dict], *, repo_cwd: Path) -> dict[int, str]:
    """{issue number: session name} for every live `orch #N` session of this repo (#55's "In
    progress" column; reuses `_issue_from_name` / the same cwd filter `panel_agents` applies)."""

    repo_cwd_resolved = str(Path(repo_cwd).resolve())
    held: dict[int, str] = {}
    for raw in sessions_raw:
        name = raw.get("name")
        if not name or not _is_orch({"name": name}):
            continue
        cwd = raw.get("cwd")
        if cwd is not None and str(Path(cwd).resolve()) != repo_cwd_resolved:
            continue
        # one ORCH holds every ready issue (#60): "orch #54 #55 #56" maps each of them.
        for match in _ISSUE_IN_NAME_RE.findall(name):
            held[int(match)] = name
    return held


def git_main_ahead(repo_cwd: Path, *, runner: Callable[[list[str], Path], Any] | None = None) -> int | None:
    """How far local `main` is ahead of `origin/main` (#78): `git rev-list --count
    origin/main..main` from `repo_cwd`, no fetch -- it reads whatever `origin/main` the last
    fetch or push already left in the local repo, so a tick never blocks on the network. A missed
    `git push origin main` after ORCH merges shows up here as a nonzero count. `runner(args, cwd)`
    is injected for tests (a fake git, never a real subprocess call there); it must return an
    object with `.returncode` and `.stdout`, the same shape as `subprocess.run(..., text=True)`.
    `None` when git is unavailable, times out, or the ref doesn't exist yet."""

    if runner is None:
        def runner(args: list[str], cwd: Path):
            import subprocess

            return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=10,
                                  creationflags=no_window_flags())
    try:
        result = runner(["git", "rev-list", "--count", "origin/main..main"], repo_cwd)
    except Exception:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    try:
        return int(result.stdout.strip())
    except (AttributeError, ValueError):
        return None


def build_snapshot(sessions_raw: list[dict], *, projects_dir: Path = DEFAULT_PROJECTS_DIR,
                   prices: dict[str, dict] | None = None, repo_cwd: Path = ROOT,
                   store=None, now: datetime | None = None,
                   orch_state: dict[str, Any] | None = None,
                   gh_issues: Any = None, issue_records: list | None = None,
                   dashboard_kwargs: dict[str, Any] | None = None,
                   git_runner: Callable[[list[str], Path], Any] | None = None,
                   laptop_cache: Any = None, lane_state_file: Path = LANE_STATE_FILE) -> dict[str, Any]:
    """The whole `/api/snapshot` payload: one key per tab (`_TAB_IDS`).

    `issue_records` overrides the (cached) `gh` fetch entirely -- for tests; production leaves it
    `None` and goes through `monitor_issues.cached_issue_records`. `dashboard_kwargs` forwards to
    `monitor_dashboard.dashboard_snapshot` (#56) -- tests pass a fake `gh_runner` + a fresh
    `DashboardCache` there the same way.
    """

    now = now or datetime.now(timezone.utc)
    prices = prices if prices is not None else token_meter.load_prices(DEFAULT_PRICES_PATH)

    if issue_records is not None:
        records = issue_records
    else:
        gh_issues = gh_issues if gh_issues is not None else monitor_issues.GhIssuesCli()
        records = monitor_issues.cached_issue_records(gh_issues)

    if store is not None:
        from junkroan.runs.store import LIVE_STATES

        job_issues = monitor_issues.live_job_issues(jobs=[j for j in store.jobs() if j.state in LIVE_STATES])
    else:
        job_issues = monitor_issues.live_job_issues()

    held_issues = _held_issues(sessions_raw, repo_cwd=repo_cwd)
    if orch_state:  # #60: the dispatcher's own record of what the one ORCH holds
        for n in orch_state.get("held") or []:
            held_issues.setdefault(int(n), f"orch {orch_state.get('session')}")
    issues_dashboard = monitor_issues.build_dashboard(
        records, now=now, held_issues=held_issues, job_issues=job_issues,
    )

    dashboard = monitor_dashboard.dashboard_snapshot(
        root=repo_cwd, projects_dir=projects_dir, prices=prices, now=now,
        **(dashboard_kwargs or {}),
    )
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "main_ahead": git_main_ahead(repo_cwd, runner=git_runner),
        #: #121 item 7: one line above the tabs -- lane open / closed, session id, estimated $ left,
        #: the issues in the cloud; read from the file the dispatcher's lane tick writes.
        "cloud_lane": cloud_lane_line(lane_state_file),
        "waiting_on_you": issues_dashboard["waiting_on_you"],
        "agents": panel_agents(sessions_raw, projects_dir=projects_dir, prices=prices,
                               repo_cwd=repo_cwd, now=now, orch_state=orch_state)["sessions"],
        "pob_runs": panel_pob_runs(store=store, now=now, laptop_cache=laptop_cache),
        "issues": issues_dashboard["board"],
        "progress": dashboard["progress"],
        "results": dashboard["results"],
        "cost": dashboard["cost"],
        "events": dashboard["events"],
    }


# -------------------------------------------------------------------------------------- server ---

_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>poe-junkroan agent monitor</title>
<style>
  :root { color-scheme: dark; }
  body { background: #0e1116; color: #d7dde5; font: 13px/1.4 "Segoe UI", sans-serif; margin: 0; padding: 12px 16px; }
  h1 { font-size: 15px; margin: 0 0 8px 0; color: #9fb4cc; }
  .tabs { display: flex; gap: 6px; margin-bottom: 10px; }
  .tabs button { background: #1b2028; color: #b7c2d0; border: 1px solid #2b323c; border-radius: 4px 4px 0 0;
                padding: 5px 12px; cursor: pointer; font: inherit; }
  .tabs button.active { background: #232a35; color: #fff; border-bottom-color: #232a35; }
  section { display: none; }
  section.active { display: block; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 14px; }
  th, td { text-align: left; padding: 3px 8px; border-bottom: 1px solid #232a35; white-space: nowrap; }
  th { color: #8493a8; font-weight: 600; }
  tr.subagent td:first-child { padding-left: 22px; color: #9fb4cc; }
  tr.subagent { background: #12161c; }
  .running { color: #7ee787; }
  .done { color: #8493a8; }
  .stale { color: #f0883e; }
  .muted { color: #6b7787; }
  .actions { color: #6b7787; font-size: 12px; }
  #meta { color: #6b7787; font-size: 11px; margin-bottom: 8px; }
  #waiting-badge { background: #f0883e; color: #0e1116; border-radius: 8px; padding: 0 5px; margin-left: 4px; font-size: 11px; }
  .board { display: flex; gap: 10px; align-items: flex-start; }
  .board .column { flex: 1; min-width: 0; }
  .board h3 { font-size: 12px; color: #8493a8; margin: 0 0 4px 0; }
  .board .card { display: block; padding: 3px 6px; margin-bottom: 4px; background: #1b2028; border-radius: 3px; color: #d7dde5; text-decoration: none; }
  .board .card:hover { background: #232a35; }
  .board .card .tag { color: #6b7787; font-size: 11px; display: block; }
  a { color: #9fb4cc; }
  #control-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 10px;
                   padding: 6px 8px; background: #171c24; border: 1px solid #2b323c; border-radius: 4px; }
  #control-strip .mode-host { color: #8493a8; margin-left: 10px; }
  #control-strip .mode-host:first-child { margin-left: 0; }
  #control-strip select, #control-strip button { font: inherit; background: #1b2028; color: #b7c2d0;
                                                  border: 1px solid #2b323c; border-radius: 3px; padding: 2px 6px; }
  #control-strip button { cursor: pointer; }
  #mode-error { color: #f0883e; }
  .bar { display: inline-block; height: 10px; background: #2b323c; width: 120px; vertical-align: middle; margin-right: 6px; }
  .bar > span { display: block; height: 100%; background: #4c8bf5; }
  .grey { color: #6b7787; }
  .note { color: #6b7787; font-size: 11px; }
</style>
</head>
<body>
<h1>poe-junkroan agent monitor</h1>
<div id="meta">loading...</div>
<div id="cloud-lane" class="note"></div>
<div id="control-strip">
  <span class="mode-host">PC:</span> <span id="mode-pc">-</span>
  <select id="dur-pc">
    <option value="30">30 min</option>
    <option value="60" selected>1 h</option>
    <option value="120">2 h</option>
    <option value="240">4 h</option>
    <option value="">no timer</option>
  </select>
  <button onclick="setMode('pc','play')">Play</button>
  <button onclick="setMode('pc','normal')">Back to normal</button>
  <span class="mode-host">Laptop:</span> <span id="mode-laptop">-</span>
  <select id="dur-laptop">
    <option value="30">30 min</option>
    <option value="60" selected>1 h</option>
    <option value="120">2 h</option>
    <option value="240">4 h</option>
    <option value="">no timer</option>
  </select>
  <button onclick="setMode('laptop','browser')">Browser</button>
  <button onclick="setMode('laptop','normal')">Back to normal</button>
  <span id="mode-error"></span>
</div>
<div class="tabs">
  <button data-tab="waiting-on-you">Waiting on you<span id="waiting-badge"></span></button>
  <button data-tab="agents">Agents</button>
  <button data-tab="pob-runs">PoB runs</button>
  <button data-tab="issues">Issues</button>
  <button data-tab="progress">Progress</button>
  <button data-tab="results">Results</button>
  <button data-tab="cost">Cost</button>
  <button data-tab="events">Events</button>
</div>
<section id="tab-waiting-on-you"><table id="waiting-table"></table></section>
<section id="tab-agents"><table id="agents-table"></table></section>
<section id="tab-pob-runs">
  <div id="slots"></div>
  <table id="daemons-table"></table>
  <table id="runs-table"></table>
</section>
<section id="tab-issues"><div id="board" class="board"></div></section>
<section id="tab-progress">
  <div id="progress-offline" class="note"></div>
  <table id="progress-table"></table>
</section>
<section id="tab-results"><div id="results-body"></div></section>
<section id="tab-cost"><div id="cost-body"></div></section>
<section id="tab-events"><table id="events-table"></table></section>
<script>
const TABS = ["waiting-on-you", "agents", "pob-runs", "issues", "progress", "results", "cost", "events"];
const MONITOR_TOKEN = "__MONITOR_TOKEN__";

function formatLeft(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds <= 0) return "0 min";
  const mins = Math.round(seconds / 60);
  return mins < 90 ? (mins + " min") : ((mins / 60).toFixed(1) + " h");
}

async function setMode(host, mode) {
  const durEl = document.getElementById("dur-" + host);
  const minutes = (durEl && durEl.value) ? Number(durEl.value) : null;
  const errEl = document.getElementById("mode-error");
  errEl.textContent = "";
  try {
    const res = await fetch("/api/mode", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Monitor-Token": MONITOR_TOKEN},
      body: JSON.stringify({host: host, mode: mode, minutes: minutes}),
    });
    const data = await res.json();
    if (!data.ok) errEl.textContent = host + ": " + data.error;
  } catch (e) {
    errEl.textContent = host + ": " + e;
  }
  refreshModes();
}

async function refreshModes() {
  try {
    const res = await fetch("/api/modes");
    const data = await res.json();
    for (const host of ["pc", "laptop"]) {
      const entry = data[host] || {mode: "normal", seconds_left: null};
      const left = formatLeft(entry.seconds_left);
      document.getElementById("mode-" + host).textContent = entry.mode + (left ? " (" + left + " left)" : "");
    }
  } catch (e) {
    // transient failure; the next 3 s tick retries
  }
}
refreshModes();
setInterval(refreshModes, 3000);

function selectTab(tab) {
  if (!TABS.includes(tab)) tab = TABS[0];
  for (const t of TABS) {
    document.getElementById("tab-" + t).classList.toggle("active", t === tab);
  }
  for (const b of document.querySelectorAll(".tabs button")) {
    b.classList.toggle("active", b.dataset.tab === tab);
  }
  location.hash = "#" + tab;
}

for (const b of document.querySelectorAll(".tabs button")) {
  b.addEventListener("click", () => selectTab(b.dataset.tab));
}
selectTab((location.hash || "#agents").slice(1));

function esc(s) { return (s === null || s === undefined) ? "" : String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function renderAgents(data) {
  const rows = [];
  rows.push("<tr><th>session</th><th>issue</th><th>state</th><th>model</th><th>context</th><th>turns</th><th>cost</th><th>age</th><th>last actions</th></tr>");
  for (const s of data.agents) {
    const issue = s.issue ? `<a href="${esc(s.issue.url)}" target="_blank">#${s.issue.number}</a>` : "";
    const stateClass = (s.state === "done") ? "done" : (s.state === "working" || s.status === "busy") ? "running" : "stale";
    const actions = (s.last_actions || []).map(a => `${esc(a.tool)}: ${esc(a.summary)}`).join(" | ");
    rows.push(`<tr><td>${esc(s.name || s.session_id)}</td><td>${issue}</td><td class="${stateClass}">${esc(s.state)}</td>` +
              `<td>${esc(s.model)}</td><td>${esc(s.context)}</td><td>${esc(s.turns)}</td>` +
              `<td>$${Number(s.cost_usd).toFixed(2)}</td><td>${esc(s.age_human)}</td><td class="actions">${actions}</td></tr>`);
    for (const h of (s.held_issues || [])) {
      rows.push(`<tr class="subagent"><td><a href="${esc(h.url)}" target="_blank">#${h.number}</a>` +
                `${h.claimed ? "" : " (ended)"}</td><td></td><td colspan="7"></td></tr>`);
      for (const a of h.subagents) rows.push(subagentRow(a, true));
    }
    for (const a of (s.subagents || [])) rows.push(subagentRow(a, false));
  }
  document.getElementById("agents-table").innerHTML = rows.join("");
}

function subagentRow(a, nested) {
  const cls = a.running ? "running" : "done";
  const indent = nested ? ' style="padding-left:40px"' : "";
  return `<tr class="subagent"><td${indent}>${esc(a.agent_type)}: ${esc(a.task)}</td><td></td>` +
         `<td class="${cls}">${a.running ? "running" : "done"}</td><td>${esc(a.model)}</td>` +
         `<td>${esc(a.context)}</td><td>${esc(a.turns)}</td><td>$${Number(a.cost_usd).toFixed(2)}</td>` +
         `<td>${esc(a.duration_human)}</td><td></td></tr>`;
}

function renderPobRuns(data) {
  const slots = data.pob_runs.slots || {};
  const slotsText = slots.error ?
    ("slot budget: " + slots.error) :
    `slots: ${slots.busy} / ${slots.total} busy on ${slots.host} (${slots.period}, ${slots.window})`;
  const laptop = data.pob_runs.laptop;
  let laptopText = "";
  if (laptop && laptop.pending) {
    laptopText = " · laptop: reading...";
  } else if (laptop && !laptop.ok) {
    laptopText = laptop.age_human ?
      ` · laptop unreachable (last read ${laptop.age_human} ago)` : " · laptop unreachable";
  }
  document.getElementById("slots").textContent = slotsText + laptopText;

  const dRows = [];
  dRows.push("<tr><th>daemon</th><th>pid</th><th>state</th><th>last tick</th><th>running</th><th>queued</th><th>fillers left</th></tr>");
  for (const d of (data.pob_runs.daemons || [])) {
    const cls = d.state === "live" ? "running" : (d.state === "stale" ? "stale" : "done");
    const fillers = esc(d.fillers) + (d.fillers_message_pending ? ` <span class="tag">tell the brain</span>` : "");
    dRows.push(`<tr><td>${esc(d.host)}</td><td>${esc(d.pid)}</td><td class="${cls}">${esc(d.state)}</td>` +
              `<td>${esc(d.last_tick_age_human)}</td><td>${esc(d.running)}</td><td>${esc(d.queued)}</td>` +
              `<td>${fillers}</td></tr>`);
  }
  document.getElementById("daemons-table").innerHTML = dRows.join("");

  const rows = [];
  rows.push("<tr><th>id</th><th>host</th><th>priority</th><th>issue</th><th>tag</th><th>state</th><th>duration</th></tr>");
  for (const j of data.pob_runs.jobs) {
    rows.push(`<tr><td>${esc(j.id)}</td><td>${esc(j.host)}</td><td>${esc(j.priority)}${j.filler ? " filler" : ""}</td>` +
              `<td>${j.issue ? "#" + j.issue : ""}</td><td>${esc(j.tag)}` +
              `${j.filler ? ' <span class="tag">filler</span>' : ""}</td><td>${esc(j.state)}</td>` +
              `<td>${esc(j.duration_human)}</td></tr>`);
  }
  document.getElementById("runs-table").innerHTML = rows.join("");
}

function renderWaitingOnYou(data) {
  const w = data.waiting_on_you || {items: [], badge: 0};
  document.getElementById("waiting-badge").textContent = w.badge ? String(w.badge) : "";
  const rows = ["<tr><th>issue</th><th>age</th><th>asks</th></tr>"];
  for (const it of w.items) {
    rows.push(`<tr><td><a href="${esc(it.url)}" target="_blank">#${it.number} ${esc(it.title)}</a></td>` +
              `<td>${esc(it.age_human)}</td><td>${esc(it.ask)}</td></tr>`);
  }
  document.getElementById("waiting-table").innerHTML = rows.join("");
}

function renderIssueColumn(title, cards) {
  const items = (cards || []).map(c =>
    `<a class="card" href="${esc(c.url)}" target="_blank">#${c.number} ${esc(c.title)}` +
    (c.tag ? `<span class="tag">${esc(c.tag)}</span>` : "") + `</a>`).join("");
  return `<div class="column"><h3>${esc(title)} (${(cards || []).length})</h3>${items}</div>`;
}

function renderIssues(data) {
  const b = data.issues || {};
  document.getElementById("board").innerHTML = [
    renderIssueColumn("Next", b.next),
    renderIssueColumn("In progress", b.in_progress),
    renderIssueColumn("Waiting for a run", b.waiting_for_run),
    renderIssueColumn("Needs the owner", b.needs_owner),
    renderIssueColumn("Done this week", b.done_this_week),
  ].join("");
}

function renderProgress(data) {
  if (data.progress.loading) {
    document.getElementById("progress-offline").textContent = "";
    document.getElementById("progress-table").innerHTML = "<tr><td>...</td></tr>";
    return;
  }
  const rows = [];
  document.getElementById("progress-offline").textContent = data.progress.offline_note || "";
  for (const b of data.progress.bars) {
    const pct = b.pct === null || b.pct === undefined ? null : Math.max(0, Math.min(1, b.pct));
    const barHtml = pct === null ? "" :
      `<span class="bar"><span style="width:${(pct * 100).toFixed(0)}%"></span></span>`;
    rows.push(`<tr><td>${esc(b.stage)}</td><td class="note">${esc(b.unit)}</td>` +
              `<td>${barHtml}${esc(b.done)} / ${esc(b.of)}</td><td class="note">${esc(b.note)}</td></tr>`);
  }
  document.getElementById("progress-table").innerHTML = rows.join("");
}

function renderResults(data) {
  if (data.results.loading) { document.getElementById("results-body").innerHTML = "..."; return; }
  const parts = [];
  for (const s of data.results.sets) {
    if (!s.run) { parts.push(`<h3>${esc(s.set)}</h3><div class="note">no run yet</div>`); continue; }
    const changeCls = s.change === null ? "" : (s.inside_noise ? "grey" : "");
    const changeText = s.change === null ? "-" : `${s.change >= 0 ? "+" : ""}${s.change.toFixed(1)}`;
    parts.push(`<h3>${esc(s.set)} <span class="note">(${esc(s.run)})</span></h3>` +
      `<div>median ${esc(s.median === null ? "-" : s.median.toFixed(1))}% ` +
      `<span class="${changeCls}">change ${changeText} (noise ${esc(s.noise)})</span></div>`);
    const refRows = s.references.map(r =>
      `<tr><td>${esc(r.slug)}</td><td>${esc(r.median === null ? "-" : r.median.toFixed(1))}%</td>` +
      `<td>${esc(r.spread === null ? "-" : r.spread.toFixed(1))}</td><td>${esc(r.seeds)}</td></tr>`).join("");
    parts.push(`<table><tr><th>reference</th><th>% of author</th><th>spread</th><th>seeds</th></tr>${refRows}</table>`);
  }
  document.getElementById("results-body").innerHTML = parts.join("");
}

function renderCost(data) {
  if (data.cost.loading) { document.getElementById("cost-body").innerHTML = "..."; return; }
  const c = data.cost;
  const parts = [];
  if (c.gh_error) parts.push(`<div class="note">gh: ${esc(c.gh_error)}</div>`);
  parts.push("<h3>per closed issue (14d)</h3><table><tr><th>issue</th><th>closed</th><th>cost</th></tr>" +
    c.by_issue.map(i => `<tr><td>#${esc(i.number)}</td><td>${esc(i.closed_at)}</td><td>$${Number(i.cost_usd).toFixed(2)}</td></tr>`).join("") +
    "</table>");
  parts.push("<h3>per day</h3><table><tr><th>day</th><th>cost</th></tr>" +
    c.by_day.map(r => `<tr><td>${esc(r.key)}</td><td>$${Number(r.cost_usd).toFixed(2)}</td></tr>`).join("") +
    "</table>");
  parts.push("<h3>per model</h3><table><tr><th>model</th><th>cost</th></tr>" +
    c.by_model.map(r => `<tr><td>${esc(r.key)}</td><td>$${Number(r.cost_usd).toFixed(2)}</td></tr>`).join("") +
    "</table>");
  const r = c.refactor;
  parts.push("<h3>the four refactor numbers</h3><table>" +
    `<tr><td>CLAUDE.md size</td><td>${esc(r.claude_md_kb === null ? "-" : r.claude_md_kb.toFixed(1))} KB (target <= ${esc(r.claude_md_target_kb)})</td></tr>` +
    `<tr><td>spawn first turn (median)</td><td>target <= ${esc(r.spawn_first_turn_target)}</td></tr>` +
    `<tr><td>brain/ORCH weekly median context</td><td>target <= ${esc(r.weekly_median_context_target)}</td></tr>` +
    `<tr><td>cost per closed issue before / after</td><td>${esc(r.cost_per_issue_before_usd === null ? "-" : "$" + r.cost_per_issue_before_usd.toFixed(2))} (n=${esc(r.cost_per_issue_before_n)}) / ` +
    `${esc(r.cost_per_issue_after_usd === null ? "-" : "$" + r.cost_per_issue_after_usd.toFixed(2))} (n=${esc(r.cost_per_issue_after_n)})</td></tr>` +
    "</table>");
  document.getElementById("cost-body").innerHTML = parts.join("");
}

function renderEvents(data) {
  if (data.events.loading) { document.getElementById("events-table").innerHTML = "<tr><td>...</td></tr>"; return; }
  const rows = [];
  rows.push("<tr><th>age</th><th>kind</th><th>details</th></tr>");
  for (const e of data.events.events) {
    if (e.raw !== undefined) { rows.push(`<tr><td>${esc(e.age_human)}</td><td colspan="2">${esc(e.raw)}</td></tr>`); continue; }
    const details = Object.entries(e).filter(([k]) => !["ts", "age_human", "kind"].includes(k))
      .map(([k, v]) => `${k}=${esc(typeof v === "object" ? JSON.stringify(v) : v)}`).join(" ");
    rows.push(`<tr><td>${esc(e.age_human)}</td><td>${esc(e.kind)}</td><td class="note">${details}</td></tr>`);
  }
  document.getElementById("events-table").innerHTML = rows.join("");
}

async function refresh() {
  try {
    const res = await fetch("/api/snapshot");
    const data = await res.json();
    const aheadMark = (data.main_ahead) ? (" · main +" + data.main_ahead + " ahead of origin") : "";
    document.getElementById("meta").textContent = "updated " + data.generated_at + aheadMark;
    const lane = data.cloud_lane || {};
    document.getElementById("cloud-lane").textContent = lane.line || "";
    renderWaitingOnYou(data);
    renderAgents(data);
    renderPobRuns(data);
    renderIssues(data);
    renderProgress(data);
    renderResults(data);
    renderCost(data);
    renderEvents(data);
  } catch (e) {
    document.getElementById("meta").textContent = "refresh failed: " + e;
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def _mode_left_seconds(until: str | None, now: datetime) -> float | None:
    if not until:
        return None
    try:
        until_dt = datetime.fromisoformat(str(until))
    except ValueError:
        return None
    return max(0.0, (until_dt - now).total_seconds())


def make_handler(
    snapshot_fn: Callable[[], dict[str, Any]],
    *,
    token: str = "",
    apply_mode_fn: Callable[[str, str, float | None], dict[str, Any]] | None = None,
    read_modes_fn: Callable[[], dict[str, Any]] | None = None,
    revert_fn: Callable[[], Any] | None = None,
    mode_hosts: tuple[str, ...] = ("pc", "laptop"),
) -> type[BaseHTTPRequestHandler]:
    """``apply_mode_fn``/``read_modes_fn``/``revert_fn`` are the "Free the PC" / "Free the laptop"
    strip (#54): ``POST /api/mode`` calls ``apply_mode_fn(host, mode, minutes)`` behind ``token``
    (``X-Monitor-Token``; a missing/wrong token is refused, nothing applied); ``GET /api/modes``
    reads current mode + time left for the strip; one ``revert_fn()`` call sits in the
    ``/api/snapshot`` path so the timer works even if the runs daemon (#48) is not running."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # keep stdout quiet
            pass

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            self._send(json.dumps(payload).encode("utf-8"), "application/json", status=status)

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler's own naming)
            if self.path in ("/", "/index.html"):
                page = _PAGE_HTML.replace("__MONITOR_TOKEN__", token)
                self._send(page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/snapshot":
                if revert_fn is not None:
                    try:
                        revert_fn()
                    except Exception:  # the snapshot must render even if the timer check fails
                        pass
                payload = json.dumps(snapshot_fn()).encode("utf-8")
                self._send(payload, "application/json")
                return
            if self.path == "/api/modes":
                modes = read_modes_fn() if read_modes_fn is not None else {}
                now = datetime.now()
                data = {}
                for host in mode_hosts:
                    entry = modes.get(host) or {}
                    until = entry.get("until")
                    data[host] = {
                        "mode": entry.get("mode", "normal"),
                        "until": until,
                        "seconds_left": _mode_left_seconds(until, now),
                    }
                self._send_json(data)
                return
            self._send(b"not found", "text/plain", status=404)

        def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler's own naming)
            if self.path != "/api/mode":
                self._send(b"not found", "text/plain", status=404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            supplied = self.headers.get("X-Monitor-Token") or ""
            if not token or supplied != token:
                self._send_json({"ok": False, "error": "bad or missing token"}, status=403)
                return
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"ok": False, "error": "bad json body"}, status=400)
                return
            host, mode, minutes = body.get("host"), body.get("mode"), body.get("minutes")
            if not host or not mode or apply_mode_fn is None:
                self._send_json({"ok": False, "error": "host and mode are required"}, status=400)
                return
            try:
                result = apply_mode_fn(host, mode, minutes)
            except Exception as exc:  # HostModeError from a bad host/mode/transport, kept generic
                self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._send_json({"ok": True, "until": result.get("until")})

    return Handler


def run_monitor(*, port: int = DEFAULT_PORT, host: str = "127.0.0.1", exe: Path | str | None = None,
                projects_dir: Path = DEFAULT_PROJECTS_DIR, open_browser: bool = False) -> int:
    prices = token_meter.load_prices(DEFAULT_PRICES_PATH)
    token = secrets.token_urlsafe(24)  # per-server; only this page's own JS ever sees it

    from junkroan.runs import remote_store as _remote_store

    laptop_cache = _remote_store.get_default_cache("laptop")

    def snapshot() -> dict[str, Any]:
        return build_snapshot(live_sessions_raw(exe), projects_dir=projects_dir, prices=prices,
                              orch_state=load_orch_state(), laptop_cache=laptop_cache)

    def apply_mode_fn(mode_host: str, mode: str, minutes: float | None) -> dict[str, Any]:
        return runs_hosts.apply_timed_mode(mode_host, mode, minutes)

    handler = make_handler(
        snapshot, token=token, apply_mode_fn=apply_mode_fn,
        read_modes_fn=runs_hosts.read_modes, revert_fn=runs_hosts.revert_expired_modes,
    )
    server = ThreadingHTTPServer((host, port), handler)
    bound_port = server.server_address[1]
    print(f"agentops monitor on http://{host}:{bound_port}/  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(f"http://{host}:{bound_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops monitor", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)
    return run_monitor(port=args.port, open_browser=args.open)


if __name__ == "__main__":
    sys.exit(main())


# -- what the core loads this module for ------------------------------------------------------------
#
# The page is a local module of this installation (ADR 0109, extension point 4): the core's CLI knows
# nothing of it and gets the subcommand below only when the settings file names this module.


def _add_monitor_parser(sub) -> None:
    monitor = sub.add_parser("monitor", help="local live agent monitor page (issue #52)")
    monitor.add_argument("--port", type=int, default=DEFAULT_PORT)
    monitor.add_argument("--open", action="store_true", help="open the page in the default browser")


def _run_monitor_command(args) -> int:
    return run_monitor(port=args.port, open_browser=args.open)


def register(core) -> None:
    core.command("monitor", _add_monitor_parser, _run_monitor_command, after="dispatch")


__all__ = [
    "DEFAULT_PORT",
    "build_snapshot",
    "build_session_row",
    "build_subagent_row",
    "completed_agent_ids",
    "display_model",
    "model_display_name",
    "live_sessions_raw",
    "main",
    "make_handler",
    "panel_agents",
    "panel_daemons",
    "panel_pob_runs",
    "register",
    "run_monitor",
    "scan_main_transcript",
]
