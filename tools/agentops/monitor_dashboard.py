"""Data logic for the monitor's four "where are we" tabs (#56): Progress, Results, Cost, Events.
`tools/agentops/monitor.py` only wires these into its extension points (one key in
`build_snapshot`'s mapping, one button/section/render function per tab); every number here comes
from an existing script by import, never re-derived:

- Progress: `scripts/progress.py` (`report`, `tracker_rows`) -- the same coverage/stability figures
  and tracker rows `python scripts/progress.py` prints, reshaped into (done, of, pct) bars.
- Results: `scripts/compare_runs.py` (`summarize`, `_rows`) over `artifacts/benchmark/*/results.json`,
  grouped into the four named sets (`SET_NAMES`) by a substring in the run's tag -- the naming
  this repo's own run tags already use (`core14-tpl-main3-s4`, `new18-main3`, `ziz-main3-s4`,
  `main3-smoke-s4`). The seed-noise table (`SEED_NOISE`) is the one measured in docs/STATE.md
  2026-09-26 (@42565a9, seeds 4-6 vs 1-3, absolute median change over the references both runs
  count): a change smaller than its set's figure is inside the noise, not a real move.
- Cost: `scripts/token_meter.py` (`scan_projects_dir`, `grouped_table`, `cost_per_closed_issue`,
  `claude_md_kb`, `subagent_first_turn_context_by_type`, `weekly_median_context`). The fourth
  refactor number ("cost per closed issue before vs after") splits `cost_per_closed_issue`'s own
  per-issue totals by `closedAt` against `REFACTOR_CUTOFF` -- issue #45's own `closedAt`, the
  CLAUDE.md-under-10-KB rewrite this dashboard's own target numbers come from -- rather than
  reimplementing the split inside token_meter.py.
- Events: the last `EVENTS_LIMIT` lines of `artifacts/runs/events.jsonl`, newest first, each with
  an age in `human_duration` form (never a bare timestamp with a big second count).

Heavy computation (the token meter over every transcript, the results.json parse over every
benchmark run) never runs inside a snapshot request: `DashboardCache` recomputes the whole
`dashboard_snapshot()` payload in a background thread at most once per `ttl_seconds` (default
300, "at most every 5 min"), started the moment the cached value goes stale and none is already
running; `get()` itself always returns instantly (the last value, or `None` before the first one
exists -- `dashboard_snapshot()` turns that into a `{"loading": true}` payload per tab). `now_fn`
and `thread_factory` are injectable so tests advance a fake clock and control a fake "compute"
without a real background thread's timing.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import compare_runs  # noqa: E402
import progress  # noqa: E402
import token_meter  # noqa: E402

from junkroan.report_format import human_duration  # noqa: E402

DEFAULT_REPO = token_meter.DEFAULT_REPO
DEFAULT_ROADMAP = ROOT / "docs" / "ROADMAP.md"
DEFAULT_STATE = ROOT / "docs" / "STATE.md"
DEFAULT_FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
DEFAULT_BENCHMARK_DIR = ROOT / "artifacts" / "benchmark"
DEFAULT_EVENTS_PATH = ROOT / "artifacts" / "runs" / "events.jsonl"
EVENTS_LIMIT = 100

#: #45 ("Orchestration v2 ... CLAUDE.md under 10 KB") closed here -- the split point for the
#: fourth refactor number, "cost per closed issue before vs after".
REFACTOR_CUTOFF = datetime(2026, 9, 26, 16, 26, 33, tzinfo=timezone.utc)
REFACTOR_TARGETS = {
    "claude_md_kb": 10.0,
    "spawn_first_turn_tokens": 30_000,
    "weekly_median_context_tokens": 150_000,
}

#: token_meter's own defaults for classifying a main chat as "brain" or "ORCH" by its custom title.
DEFAULT_BRAIN_PATTERN = r"opus|fable"
DEFAULT_ORCH_PATTERN = r"orch"

#: The four benchmark sets the owner tracks by name, and each one's measured seed noise: absolute
#: median-of-medians change, seeds 4-6 vs 1-3 @42565a9, over the references both runs count
#: (docs/STATE.md, 2026-09-26). A |change| at or under this is grey -- inside the noise.
SEED_NOISE: dict[str, float] = {
    "smoke": 11.5,
    "new18": 15.5,
    "core14": 2.4,
    "ziz": 1.0,
}
SET_NAMES: tuple[str, ...] = ("smoke", "new18", "core14", "ziz")


# --------------------------------------------------------------------------------- cache ----


class DashboardCache:
    """Never blocks a snapshot request on `compute()`: `get()` always returns the last computed
    value (or `None` before the first one exists) at once, and starts `compute()` in a background
    thread when the value is stale (older than `ttl_seconds`, default 300 -- "at most every
    5 min") and no refresh is already running. `now_fn` (default `time.monotonic`) and
    `thread_factory` (default `threading.Thread`) are injectable so a test can advance a fake
    clock and run a fake, controllable "compute" without a real 5-min wait."""

    def __init__(self, ttl_seconds: float = 300.0, now_fn: Callable[[], float] = time.monotonic,
                thread_factory: Callable[..., threading.Thread] = threading.Thread):
        self._ttl = ttl_seconds
        self._now_fn = now_fn
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._value: Any = None
        self._computed_at: float | None = None
        self._thread: threading.Thread | None = None

    def get(self, compute: Callable[[], Any]) -> Any:
        """The current value (`None` if none has been computed yet). Starts exactly one
        background refresh when the value is missing or stale and none is already in flight."""

        thread_to_start: threading.Thread | None = None
        with self._lock:
            is_stale = self._value is None or (self._now_fn() - self._computed_at) >= self._ttl
            already_refreshing = self._thread is not None and self._thread.is_alive()
            if is_stale and not already_refreshing:
                thread_to_start = self._thread_factory(target=self._refresh, args=(compute,), daemon=True)
                self._thread = thread_to_start
            value = self._value
        if thread_to_start is not None:
            thread_to_start.start()
        return value

    def _refresh(self, compute: Callable[[], Any]) -> None:
        result = compute()
        with self._lock:
            self._value = result
            self._computed_at = self._now_fn()

    def wait(self, timeout: float | None = None) -> None:
        """Test hook: block until the in-flight refresh (if any) finishes."""

        thread = self._thread
        if thread is not None:
            thread.join(timeout)


# ------------------------------------------------------------------------------ progress ----


def panel_progress(*, root: Path = ROOT, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """`scripts/progress.py`'s stage + tracker rows, reshaped into bars (done, of, pct)."""

    roadmap = (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    state_path = root / "docs" / "STATE.md"
    live_state = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else None
    fixtures_dir = root / "tests" / "fixtures" / "tuadh_329"
    benchmark_dir = root / "artifacts" / "benchmark"
    stages, refs, _state = progress.report(roadmap, fixtures_dir, benchmark_dir, state=live_state)

    offline_note: str | None = None
    try:
        tracker = progress.tracker_rows(repo)
    except progress.GhUnavailable as exc:
        tracker = []
        offline_note = str(exc)

    bars = []
    for row in [*tracker, *stages]:
        of = row.get("of") or 0
        done = row.get("done") or 0
        pct = (done / of) if of else None
        bars.append({
            "stage": row.get("stage"),
            "unit": row.get("unit"),
            "done": done,
            "of": of,
            "pct": pct,
            "note": row.get("note") or "",
        })
    return {"bars": bars, "offline_note": offline_note, "references": len(refs)}


# ------------------------------------------------------------------------------- results ----


def _runs_for_set(benchmark_dir: Path, set_name: str) -> list[Path]:
    """Every run folder tagged with `set_name`, oldest first (its stamp sorts lexically)."""

    if not benchmark_dir.is_dir():
        return []
    return sorted(
        d for d in benchmark_dir.iterdir()
        if d.is_dir() and progress.STAMP.match(d.name) and set_name in d.name
    )


def _rows(run_dir: Path) -> list[dict]:
    return compare_runs._rows(run_dir)


def _median_of_medians(summary: dict[str, dict], keys) -> float | None:
    values = [summary[k]["median"] for k in keys if summary.get(k, {}).get("median") is not None]
    return statistics.median(values) if values else None


def set_snapshot(benchmark_dir: Path, set_name: str) -> dict[str, Any]:
    """The latest run of `set_name`: per-reference % of the author, the set's median, and the
    change against the previous run of the same set (`compare_runs.summarize`'s own numbers,
    never re-derived)."""

    runs = _runs_for_set(benchmark_dir, set_name)
    if not runs:
        return {"set": set_name, "run": None, "previous_run": None, "median": None,
                "change": None, "noise": SEED_NOISE.get(set_name), "inside_noise": None,
                "references": []}

    latest = runs[-1]
    previous = runs[-2] if len(runs) > 1 else None
    latest_summary = compare_runs.summarize(_rows(latest))
    references = [
        {"slug": slug, "median": v["median"], "spread": v["spread"], "seeds": v["seeds"]}
        for slug, v in sorted(latest_summary.items())
    ]
    set_median = _median_of_medians(latest_summary, latest_summary.keys())

    change = None
    previous_name = None
    if previous is not None:
        previous_name = previous.name
        previous_summary = compare_runs.summarize(_rows(previous))
        common = [k for k in latest_summary if k in previous_summary
                  and latest_summary[k]["median"] is not None
                  and previous_summary[k]["median"] is not None]
        if common:
            change = _median_of_medians(latest_summary, common) - _median_of_medians(previous_summary, common)

    noise = SEED_NOISE.get(set_name)
    inside_noise = (change is not None and noise is not None and abs(change) <= noise)
    return {
        "set": set_name,
        "run": latest.name,
        "previous_run": previous_name,
        "median": set_median,
        "change": change,
        "noise": noise,
        "inside_noise": inside_noise,
        "references": references,
    }


def panel_results(*, benchmark_dir: Path = DEFAULT_BENCHMARK_DIR) -> dict[str, Any]:
    return {"sets": [set_snapshot(benchmark_dir, name) for name in SET_NAMES]}


# ---------------------------------------------------------------------------------- cost ----


def panel_cost(*, projects_dir: Path = token_meter.DEFAULT_PROJECTS_DIR,
               prices: dict[str, dict] | None = None, repo: str = DEFAULT_REPO,
               gh_runner: token_meter.GhRunner = token_meter.run_gh,
               claude_md_path: Path = token_meter.DEFAULT_CLAUDE_MD,
               now: datetime | None = None, days: int = 14) -> dict[str, Any]:
    """Cost per closed issue (last `days`), per day, per model, and the four refactor numbers --
    all from `scripts/token_meter.py` by import."""

    now = now or datetime.now(timezone.utc)
    since, until = token_meter.default_window(now=now, days=days)
    prices = prices if prices is not None else token_meter.load_prices(token_meter.DEFAULT_PRICES_PATH)
    result = token_meter.scan_projects_dir(projects_dir)

    try:
        closed_issues = token_meter.fetch_closed_issues(repo, runner=gh_runner)
        gh_error = None
    except Exception as exc:  # gh missing/offline/non-zero -- the panel still renders (progress.py's own rule)
        closed_issues = []
        gh_error = str(exc)

    issue_costs = token_meter.cost_per_closed_issue(result.turns, closed_issues, prices, since=since, until=until)
    by_day = token_meter.grouped_table(result.turns, prices, by="day", since=since, until=until)
    by_model = token_meter.grouped_table(result.turns, prices, by="model", since=since, until=until)

    def _row(g: token_meter.GroupRow) -> dict[str, Any]:
        return {"key": g.key, "turns": g.turns, "context": g.context, "cost_usd": g.cost_usd,
                "unpriced_turns": g.unpriced_turns}

    kb = token_meter.claude_md_kb(claude_md_path)
    by_type = token_meter.subagent_first_turn_context_by_type(result, since=since, until=until)
    weekly = token_meter.weekly_median_context(
        result.turns, since=since, until=until,
        brain_pattern=DEFAULT_BRAIN_PATTERN, orch_pattern=DEFAULT_ORCH_PATTERN,
    )

    # Before/after #45's own closedAt (REFACTOR_CUTOFF): the same per-issue costs
    # cost_per_closed_issue already computed, bucketed by closedAt, over the whole history rather
    # than the 14-day window (a 14-day window would be all-before or all-after by construction).
    all_time_costs = token_meter.cost_per_closed_issue(
        result.turns, closed_issues, prices,
        since=datetime(2000, 1, 1, tzinfo=timezone.utc), until=now,
    )
    before, after = [], []
    for ic in all_time_costs:
        closed_at = token_meter.parse_timestamp(ic.closed_at) if ic.closed_at else None
        (after if (closed_at is not None and closed_at >= REFACTOR_CUTOFF) else before).append(ic.cost_usd)

    refactor = {
        "claude_md_kb": kb,
        "claude_md_target_kb": REFACTOR_TARGETS["claude_md_kb"],
        "spawn_first_turn": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "spawn_first_turn_target": REFACTOR_TARGETS["spawn_first_turn_tokens"],
        "weekly_median_context": {f"{chat} {week}": median for (chat, week), median in sorted(weekly.items())},
        "weekly_median_context_target": REFACTOR_TARGETS["weekly_median_context_tokens"],
        "cost_per_issue_before_usd": statistics.mean(before) if before else None,
        "cost_per_issue_before_n": len(before),
        "cost_per_issue_after_usd": statistics.mean(after) if after else None,
        "cost_per_issue_after_n": len(after),
    }

    return {
        "since": since.isoformat(timespec="seconds"),
        "until": until.isoformat(timespec="seconds"),
        "gh_error": gh_error,
        "by_issue": [{"number": ic.number, "closed_at": ic.closed_at, "cost_usd": ic.cost_usd,
                      "turns": ic.turns, "unpriced_turns": ic.unpriced_turns} for ic in issue_costs],
        "by_day": [_row(g) for g in by_day],
        "by_model": [_row(g) for g in by_model],
        "refactor": refactor,
    }


# -------------------------------------------------------------------------------- events ----


def panel_events(*, events_path: Path = DEFAULT_EVENTS_PATH, limit: int = EVENTS_LIMIT,
                 now: datetime | None = None) -> dict[str, Any]:
    """The last `limit` lines of `events_path`, newest first, each with an age in
    `human_duration` form."""

    now = now or datetime.now(timezone.utc)
    if not events_path.is_file():
        return {"events": [], "path_exists": False}

    tail: deque[str] = deque(maxlen=limit)
    with events_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                tail.append(line)

    events = []
    for line in reversed(tail):
        try:
            obj = json.loads(line)
        except ValueError:
            events.append({"raw": line, "age_human": "-"})
            continue
        ts = token_meter.parse_timestamp(obj.get("ts")) if isinstance(obj, dict) else None
        if ts is not None and ts.tzinfo is None:
            ts = ts.astimezone()  # events.jsonl rows carry no zone: the host's local clock (#460)
        age_human = f"{human_duration((now - ts).total_seconds())} ago" if ts is not None else "-"
        rest = {k: v for k, v in obj.items() if k != "ts"} if isinstance(obj, dict) else {}
        events.append({"ts": obj.get("ts") if isinstance(obj, dict) else None,
                       "age_human": age_human, **rest})
    return {"events": events, "path_exists": True}


# ------------------------------------------------------------------------------ snapshot ----


def compute_dashboard(*, root: Path = ROOT, repo: str = DEFAULT_REPO,
                      projects_dir: Path = token_meter.DEFAULT_PROJECTS_DIR,
                      prices: dict[str, dict] | None = None,
                      gh_runner: token_meter.GhRunner = token_meter.run_gh,
                      benchmark_dir: Path | None = None,
                      events_path: Path | None = None,
                      now: datetime | None = None) -> dict[str, Any]:
    """The whole payload behind the four tabs, one call each -- no caching here (`DashboardCache`
    wraps this)."""

    return {
        "progress": panel_progress(root=root, repo=repo),
        "results": panel_results(benchmark_dir=benchmark_dir or (root / "artifacts" / "benchmark")),
        "cost": panel_cost(projects_dir=projects_dir, prices=prices, repo=repo, gh_runner=gh_runner, now=now),
        "events": panel_events(events_path=events_path or (root / "artifacts" / "runs" / "events.jsonl"), now=now),
    }


_DEFAULT_CACHE = DashboardCache()

#: every tab's payload before `DashboardCache` has ever finished a `compute_dashboard()` (the
#: page shows "..." for that tab instead of blocking the snapshot request on it).
_TAB_KEYS = ("progress", "results", "cost", "events")
_LOADING_TAB = {"loading": True}


def dashboard_snapshot(*, cache: DashboardCache | None = None, **kwargs: Any) -> dict[str, Any]:
    """`compute_dashboard(**kwargs)`, refreshed in the background at most every 5 min
    (`DashboardCache`, module-level default unless a test passes its own). Never blocks a
    snapshot request: returns the last computed value at once, or a small `{"loading": true}`
    payload per tab before the first value exists."""

    cache = cache if cache is not None else _DEFAULT_CACHE
    value = cache.get(lambda: compute_dashboard(**kwargs))
    if value is None:
        return {key: dict(_LOADING_TAB) for key in _TAB_KEYS}
    return value


__all__ = [
    "DEFAULT_BENCHMARK_DIR",
    "DEFAULT_EVENTS_PATH",
    "REFACTOR_CUTOFF",
    "REFACTOR_TARGETS",
    "SEED_NOISE",
    "SET_NAMES",
    "DashboardCache",
    "compute_dashboard",
    "dashboard_snapshot",
    "panel_cost",
    "panel_events",
    "panel_progress",
    "panel_results",
    "set_snapshot",
]
