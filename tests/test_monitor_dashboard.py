"""Tests for tools/agentops/monitor_dashboard.py (#56): the four tabs' JSON payloads on fixtures,
and the cache honouring its refresh interval. No PobSession, no network -- `gh` is faked wherever
a panel would otherwise call it.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

sys.path.insert(0, str(ROOT))
from tools.agentops import monitor_dashboard as md  # noqa: E402
import progress  # noqa: E402

TOKEN_METER_FIXTURES = ROOT / "tests" / "fixtures" / "token_meter"
TOKEN_METER_PROJECTS = TOKEN_METER_FIXTURES / "projects"
TOKEN_METER_PRICES = TOKEN_METER_FIXTURES / "prices.json"


# ------------------------------------------------------------------------------- helpers ----


def make_row(slug: str, seed: int, ratio: float, *, audit_errors: int = 0) -> dict:
    return {"ok": True, "slug": slug, "seed": seed, "variant": "", "ratio_lane": ratio,
            "audit_errors": audit_errors, "ours": 1000.0}


def make_run(benchmark_dir: Path, stamp: str, rows: list[dict]) -> Path:
    run_dir = benchmark_dir / stamp
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    return run_dir


def make_repo(tmp_path: Path) -> Path:
    """A minimal repo root: docs/ROADMAP.md, docs/STATE.md, tests/fixtures/tuadh_329,
    artifacts/benchmark -- everything panel_progress / panel_results read from `root`."""

    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "ROADMAP.md").write_text("## Phase 7. Prototype\n\n### State\n\n- Updated: test.\n", encoding="utf-8")
    (root / "tests" / "fixtures" / "tuadh_329").mkdir(parents=True)
    (root / "artifacts" / "benchmark").mkdir(parents=True)
    return root


# ------------------------------------------------------------------------------ progress ----


def test_panel_progress_reshapes_stage_rows_into_bars(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    (root / "tests" / "fixtures" / "tuadh_329" / "cold_dot.pob.txt").write_text("", encoding="utf-8")
    make_run(root / "artifacts" / "benchmark", "20260926-0100", [
        make_row("cold_dot", 1, 1.05), make_row("cold_dot", 2, 1.06), make_row("cold_dot", 3, 1.07),
    ])

    def fake_gh(args):
        raise progress.GhUnavailable("gh not available in this test")

    monkeypatch.setattr(progress, "_gh", fake_gh)

    out = md.panel_progress(root=root)
    assert out["offline_note"] and "gh not available" in out["offline_note"]
    coverage = next(b for b in out["bars"] if b["stage"] == "7.2 coverage")
    assert coverage["done"] == 1
    assert coverage["of"] == 1
    assert coverage["pct"] == pytest.approx(1.0)


def test_panel_progress_tracker_rows_included_when_gh_answers(tmp_path, monkeypatch):
    root = make_repo(tmp_path)

    calls = {
        "repos/Rasslabsya4el/Poe-Junkroan/issues/1/sub_issues": [
            {"number": 2, "state": "closed", "title": "a"},
            {"number": 3, "state": "open", "title": "b"},
        ],
    }

    def fake_gh(args):
        if args[:2] == ["api", "repos/Rasslabsya4el/Poe-Junkroan/issues/1/sub_issues"]:
            return json.dumps(calls["repos/Rasslabsya4el/Poe-Junkroan/issues/1/sub_issues"])
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 3, "state": "OPEN", "labels": [{"name": "ready-for-agent"}], "title": "b"}])
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(progress, "_gh", fake_gh)

    out = md.panel_progress(root=root)
    assert out["offline_note"] is None
    acceptance = next(b for b in out["bars"] if b["stage"] == "#1 acceptance")
    assert acceptance == {"stage": "#1 acceptance", "unit": "sub-issues closed", "done": 1, "of": 2,
                          "pct": 0.5, "note": "b"}


# -------------------------------------------------------------------------------- results ----


def test_set_snapshot_latest_and_previous(tmp_path):
    bench = tmp_path / "benchmark"
    make_run(bench, "20260924-0100-core14-a", [
        make_row("cold_dot", 1, 1.00), make_row("cold_dot", 2, 1.00), make_row("cold_dot", 3, 1.00),
        make_row("bleed_bow", 1, 1.20), make_row("bleed_bow", 2, 1.20), make_row("bleed_bow", 3, 1.20),
    ])
    make_run(bench, "20260926-0100-core14-b", [
        make_row("cold_dot", 1, 1.05), make_row("cold_dot", 2, 1.06), make_row("cold_dot", 3, 1.07),
        make_row("bleed_bow", 1, 1.20), make_row("bleed_bow", 2, 1.20), make_row("bleed_bow", 3, 1.20),
    ])

    snap = md.set_snapshot(bench, "core14")
    assert snap["set"] == "core14"
    assert snap["run"] == "20260926-0100-core14-b"
    assert snap["previous_run"] == "20260924-0100-core14-a"
    # cold_dot median 106.0 (points), bleed_bow median 120.0 -> set median 113.0
    assert snap["median"] == pytest.approx(113.0)
    # cold_dot moved +6.0, bleed_bow +0.0 -> median of medians delta = median(6.0, 0.0) = 3.0
    assert snap["change"] == pytest.approx(3.0)
    assert snap["noise"] == 2.4
    assert snap["inside_noise"] is False  # 3.0 > 2.4
    slugs = {r["slug"] for r in snap["references"]}
    assert slugs == {"cold_dot", "bleed_bow"}


def test_set_snapshot_no_runs_is_empty(tmp_path):
    bench = tmp_path / "benchmark"
    bench.mkdir()
    snap = md.set_snapshot(bench, "ziz")
    assert snap == {"set": "ziz", "run": None, "previous_run": None, "median": None,
                    "change": None, "noise": 1.0, "inside_noise": None, "references": []}


def test_set_snapshot_inside_noise_is_true_for_a_small_change(tmp_path):
    bench = tmp_path / "benchmark"
    make_run(bench, "20260924-0100-smoke-a", [make_row("cold_dot", 1, 1.00)])
    make_run(bench, "20260926-0100-smoke-b", [make_row("cold_dot", 1, 1.02)])  # +2.0 points

    snap = md.set_snapshot(bench, "smoke")
    assert snap["change"] == pytest.approx(2.0)
    assert snap["noise"] == 11.5
    assert snap["inside_noise"] is True


def test_panel_results_covers_all_four_sets(tmp_path):
    bench = tmp_path / "benchmark"
    make_run(bench, "20260926-0100-new18-x", [make_row("cold_dot", 1, 1.10)])
    out = md.panel_results(benchmark_dir=bench)
    names = [s["set"] for s in out["sets"]]
    assert names == ["smoke", "new18", "core14", "ziz"]
    assert next(s for s in out["sets"] if s["set"] == "new18")["run"] == "20260926-0100-new18-x"
    assert next(s for s in out["sets"] if s["set"] == "smoke")["run"] is None


# ---------------------------------------------------------------------------------- cost ----


def test_panel_cost_by_day_and_by_model(monkeypatch):
    monkeypatch.setattr(md.token_meter, "run_gh", lambda args: "[]")
    prices = md.token_meter.load_prices(TOKEN_METER_PRICES)
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    out = md.panel_cost(projects_dir=TOKEN_METER_PROJECTS, prices=prices,
                        gh_runner=lambda args: "[]", now=now)
    assert out["gh_error"] is None
    assert {r["key"] for r in out["by_model"]} >= {"claude-opus-5-5", "claude-sonnet-5"}
    assert len(out["by_day"]) >= 1
    assert out["refactor"]["claude_md_target_kb"] == 10.0
    assert out["refactor"]["spawn_first_turn_target"] == 30_000
    assert out["refactor"]["weekly_median_context_target"] == 150_000


def test_panel_cost_before_after_refactor_split(monkeypatch):
    closed = [
        {"number": 47, "closedAt": "2026-09-15T00:00:00Z"},   # before #45
        {"number": 6, "closedAt": "2026-09-27T00:00:00Z"},    # after #45
    ]

    def fake_gh(args):
        return json.dumps(closed)

    prices = md.token_meter.load_prices(TOKEN_METER_PRICES)
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    out = md.panel_cost(projects_dir=TOKEN_METER_PROJECTS, prices=prices, gh_runner=fake_gh, now=now)
    assert out["refactor"]["cost_per_issue_before_n"] == 1
    assert out["refactor"]["cost_per_issue_after_n"] == 1
    assert out["refactor"]["cost_per_issue_before_usd"] is not None
    assert out["refactor"]["cost_per_issue_after_usd"] is not None


def test_panel_cost_gh_failure_still_renders(monkeypatch):
    def broken_gh(args):
        raise RuntimeError("gh: not authenticated")

    prices = md.token_meter.load_prices(TOKEN_METER_PRICES)
    out = md.panel_cost(projects_dir=TOKEN_METER_PROJECTS, prices=prices, gh_runner=broken_gh,
                        now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    assert out["gh_error"] and "not authenticated" in out["gh_error"]
    assert out["by_issue"] == []


# -------------------------------------------------------------------------------- events ----


def test_panel_events_newest_first_with_human_age(tmp_path):
    path = tmp_path / "events.jsonl"
    lines = [
        {"ts": "2026-09-26T10:00:00+00:00", "kind": "orch_start", "issue": 1},
        {"ts": "2026-09-26T10:05:00+00:00", "kind": "orch_end", "issue": 1, "outcome": "closed"},
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")

    now = datetime(2026, 9, 26, 10, 6, 0, tzinfo=timezone.utc)
    out = md.panel_events(events_path=path, now=now)
    assert out["path_exists"] is True
    assert [e["kind"] for e in out["events"]] == ["orch_end", "orch_start"]
    assert out["events"][0]["age_human"] == "60 s ago"
    assert out["events"][1]["age_human"] == "6 min ago"
    assert out["events"][0]["outcome"] == "closed"


def test_panel_events_missing_file(tmp_path):
    out = md.panel_events(events_path=tmp_path / "missing.jsonl")
    assert out == {"events": [], "path_exists": False}


def test_panel_events_naive_ts_is_host_local_time(tmp_path):
    """#460: an events.jsonl row without a zone (the runs daemon writes the host's
    local clock) must not raise against an aware `now`."""
    path = tmp_path / "events.jsonl"
    lines = [
        {"ts": "2026-10-04T00:12:32", "kind": "end", "issue": 531},
        {"ts": "2026-10-04T00:12:32Z", "kind": "end", "issue": 530},
    ]
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")

    now = datetime(2026, 10, 4, 13, 12, 32, tzinfo=timezone.utc)
    out = md.panel_events(events_path=path, now=now)
    zoned, naive = out["events"]
    assert zoned["issue"] == 530 and naive["issue"] == 531
    assert zoned["age_human"] == f"{md.human_duration(13 * 3600)} ago"
    local = datetime(2026, 10, 4, 0, 12, 32).astimezone()
    assert naive["age_human"] == f"{md.human_duration((now - local).total_seconds())} ago"
    assert all(e["age_human"].endswith(" ago") for e in out["events"])


def test_panel_events_limit_100_and_malformed_line(tmp_path):
    path = tmp_path / "events.jsonl"
    lines = [json.dumps({"ts": f"2026-09-26T00:{i:02d}:00+00:00", "kind": "tick"}) for i in range(59)]
    lines.append("not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = md.panel_events(events_path=path, limit=100, now=datetime(2026, 9, 26, 1, 0, 0, tzinfo=timezone.utc))
    assert len(out["events"]) == 60
    assert out["events"][0]["raw"] == "not json"


# ----------------------------------------------------------------------------------- cache ----
#
# DashboardCache never blocks get() on compute(): it returns the last value at once (None before
# the first one exists) and refreshes in a background thread. These tests use a real thread but
# a controllable, blocking `compute` (an Event) so the assertions are deterministic without a
# real 5-min wait or a fake clock racing a real scheduler.


def test_cache_first_call_returns_none_and_starts_exactly_one_refresh():
    calls = []
    started = threading.Event()
    release = threading.Event()

    def compute():
        calls.append(1)
        started.set()
        assert release.wait(timeout=5)
        return {"n": len(calls)}

    cache = md.DashboardCache(ttl_seconds=300.0, now_fn=lambda: 0.0)
    first = cache.get(compute)  # "the first call returns loading"
    assert first is None
    assert started.wait(timeout=5)  # the refresh really started in the background

    second = cache.get(compute)  # a second snapshot while the refresh is in flight
    assert second is None
    release.set()
    cache.wait(timeout=5)
    assert len(calls) == 1  # exactly one refresh started, not two


def test_cache_stale_returns_old_value_at_once_and_starts_one_refresh():
    clock = [0.0]
    calls = []
    release = threading.Event()

    def compute():
        calls.append(1)
        if len(calls) == 1:
            return {"n": 1}
        assert release.wait(timeout=5)
        return {"n": 2}

    cache = md.DashboardCache(ttl_seconds=300.0, now_fn=lambda: clock[0])
    assert cache.get(compute) is None  # nothing computed yet
    cache.wait(timeout=5)
    assert cache.get(compute) == {"n": 1}  # the first refresh's result

    clock[0] = 301.0  # now stale (past the 300 s ttl)
    stale = cache.get(compute)
    assert stale == {"n": 1}  # the old value, returned at once, not blocked on the new compute
    again = cache.get(compute)  # a second snapshot request while that refresh is still running
    assert again == {"n": 1}  # same old value; no second refresh started
    release.set()
    cache.wait(timeout=5)
    assert cache.get(compute) == {"n": 2}
    assert len(calls) == 2  # exactly one refresh happened while stale


def test_dashboard_snapshot_uses_its_own_cache_instance(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setattr(progress, "_gh", lambda args: (_ for _ in ()).throw(progress.GhUnavailable("offline")))

    cache = md.DashboardCache(ttl_seconds=300.0, now_fn=lambda: 0.0)

    def fake_gh_runner(args):
        return "[]"

    kwargs = dict(cache=cache, root=root, projects_dir=TOKEN_METER_PROJECTS,
                 prices=md.token_meter.load_prices(TOKEN_METER_PRICES),
                 gh_runner=fake_gh_runner, benchmark_dir=root / "artifacts" / "benchmark",
                 events_path=root / "artifacts" / "runs" / "events.jsonl")

    snap1 = md.dashboard_snapshot(**kwargs)
    assert snap1 == {name: {"loading": True} for name in ("progress", "results", "cost", "events")}

    cache.wait(timeout=5)
    snap2 = md.dashboard_snapshot(**kwargs)
    assert set(snap2) == {"progress", "results", "cost", "events"}
    assert [s["set"] for s in snap2["results"]["sets"]] == list(md.SET_NAMES)


def test_dashboard_snapshot_returns_loading_per_tab_while_a_refresh_runs(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    release = threading.Event()
    real_compute_dashboard = md.compute_dashboard

    def slow_compute_dashboard(**kwargs):
        release.wait(timeout=5)
        return real_compute_dashboard(**kwargs)

    monkeypatch.setattr(md, "compute_dashboard", slow_compute_dashboard)
    monkeypatch.setattr(progress, "_gh", lambda args: (_ for _ in ()).throw(progress.GhUnavailable("offline")))
    cache = md.DashboardCache(ttl_seconds=300.0, now_fn=lambda: 0.0)

    kwargs = dict(cache=cache, root=root, projects_dir=TOKEN_METER_PROJECTS,
                 prices=md.token_meter.load_prices(TOKEN_METER_PRICES),
                 gh_runner=lambda args: "[]", benchmark_dir=root / "artifacts" / "benchmark",
                 events_path=root / "artifacts" / "runs" / "events.jsonl")

    snap = md.dashboard_snapshot(**kwargs)
    assert snap["progress"] == {"loading": True}
    assert snap["results"] == {"loading": True}
    assert snap["cost"] == {"loading": True}
    assert snap["events"] == {"loading": True}

    release.set()
    cache.wait(timeout=5)
    snap2 = md.dashboard_snapshot(**kwargs)
    assert "loading" not in snap2["results"]
    assert [s["set"] for s in snap2["results"]["sets"]] == list(md.SET_NAMES)
