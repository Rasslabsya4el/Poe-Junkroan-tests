"""Tests for tools/agentops/monitor.py (#52): the JSON snapshot behind the local agent monitor
page, against fixture transcripts (no real claude.exe, gh or PoB) and a fixture job store.

Fixture layout (tests/fixtures/agentops_monitor/):
  projects/sessM.jsonl                          main chat, names #52, two assistant turns with
                                                 six tool_use calls total (tests the "last 5"
                                                 cap), then a <task-notification> completing
                                                 subagent "r2".
  projects/sessM/subagents/agent-r1.jsonl(+meta)  one turn, no completion notification -> running.
  projects/sessM/subagents/agent-r2.jsonl(+meta)  two turns, completed by sessM's notification.

Prices reused from tests/fixtures/token_meter/prices.json (same fixture table #47 already uses).
The exact numbers below were computed by hand from these fixture files.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from tools.agentops import monitor  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agentops_monitor"
PROJECTS_DIR = FIXTURES / "projects"
PRICES_PATH = Path(__file__).resolve().parent / "fixtures" / "token_meter" / "prices.json"

NOW = datetime(2026, 9, 26, 10, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_daemon_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real `daemon-pc.json` on the machine running the suite must never be read by a test
    (issue #73): every test in this file gets its own status directory."""

    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))


@pytest.fixture()
def prices() -> dict:
    import token_meter as tm

    return tm.load_prices(PRICES_PATH)


def _raw_session(**overrides) -> dict:
    base = {
        "sessionId": "sessM",
        "name": "orch #52",
        "kind": "background",
        "status": "busy",
        "state": "working",
        "cwd": str(ROOT),
        "pid": 12345,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- session + turns ----


def test_session_row_model_context_turns_cost(prices):
    row = monitor.build_session_row(_raw_session(), projects_dir=PROJECTS_DIR, prices=prices, now=NOW)
    assert row["model"] == "Opus 5.5"  # last turn (msg_m2) is claude-opus-5-5
    assert row["context"] == 5000  # msg_m2: input 2000 + cache_write 0 + cache_read 3000
    assert row["turns"] == 2
    assert row["cost_usd"] == pytest.approx(0.02, abs=0.001)  # 0.0071 + 0.0136
    assert row["age_human"] == "10 min"  # now - first timestamp (10:00:00), 10 min


def test_session_row_issue_from_name():
    prices = {}
    row = monitor.build_session_row(_raw_session(), projects_dir=PROJECTS_DIR, prices=prices, now=NOW)
    assert row["issue"] == {"number": 52, "url": "https://github.com/Rasslabsya4el/Poe-Junkroan/issues/52"}


def test_last_five_actions_caps_and_orders(prices):
    row = monitor.build_session_row(_raw_session(), projects_dir=PROJECTS_DIR, prices=prices, now=NOW)
    tools = [a["tool"] for a in row["last_actions"]]
    assert tools == ["Read", "Edit", "Grep", "Bash", "SubagentHandback"]  # 6 emitted, last 5 kept
    assert row["last_actions"][0]["summary"] == "tools/agentops/monitor.py"  # Read's file_path


# ------------------------------------------------------------------------------- subagent rows ---


def test_subagents_running_and_done_states(prices):
    row = monitor.build_session_row(_raw_session(), projects_dir=PROJECTS_DIR, prices=prices, now=NOW)
    subagents = {s["agent_id"]: s for s in row["subagents"]}
    assert set(subagents) == {"r1", "r2"}

    r1 = subagents["r1"]
    assert r1["running"] is True  # no <task-notification> for r1 anywhere in sessM.jsonl
    assert r1["agent_type"] == "effort-medium"
    assert r1["task"] == "#52 monitor: build the panel"
    assert r1["model"] == "Sonnet 5"
    assert r1["context"] == 800  # 500 + 100 + 200
    assert r1["duration_human"] == "7 min"  # now - its one turn's timestamp (10:03:00)

    r2 = subagents["r2"]
    assert r2["running"] is False  # sessM.jsonl carries <task-id>r2</task-id><status>completed</status>
    assert r2["agent_type"] == "opus5-high"
    assert r2["model"] == "Opus 5"
    assert r2["context"] == 1000  # 400 + 0 + 600 (its last turn)
    assert r2["duration_human"] == "2 min"  # first turn 10:03:30 -> last turn 10:05:30
    assert r2["cost_usd"] == pytest.approx(0.01, abs=0.001)  # 0.0075 + 0.0038


def test_subagents_running_sorts_before_done(prices):
    row = monitor.build_session_row(_raw_session(), projects_dir=PROJECTS_DIR, prices=prices, now=NOW)
    assert [s["agent_id"] for s in row["subagents"]] == ["r1", "r2"]


def test_completed_agent_ids_reads_task_notification():
    ids = monitor.completed_agent_ids(PROJECTS_DIR / "sessM.jsonl")
    assert ids == {"r2"}


# ------------------------------------------------------------------------------------- panels ----


def test_panel_agents_filters_by_cwd_and_orders_orch_first(prices):
    sessions = [
        _raw_session(sessionId="sessM", name="orch #52", cwd=str(ROOT)),
        _raw_session(sessionId="sessOther", name="a different repo", cwd=r"C:\Somewhere\Else"),
        _raw_session(sessionId="sessChat", name="brain chat", kind="interactive", status="idle",
                    state=None, cwd=str(ROOT)),
    ]
    result = monitor.panel_agents(sessions, projects_dir=PROJECTS_DIR, prices=prices, repo_cwd=ROOT, now=NOW)
    names = [s["name"] for s in result["sessions"]]
    assert names == ["orch #52", "brain chat"]  # the other-repo session is filtered out
    assert names[0] == "orch #52"  # ORCH first (requirement 2's ordering)


def _no_network_dashboard_kwargs(monkeypatch) -> dict:
    """#56's four tabs (Progress/Results/Cost/Events) need their own `gh` and cache: a fresh
    `DashboardCache` per call keeps this test hermetic, a fake `gh_runner` keeps token_meter's
    gh calls offline, and faking progress's own `_gh` does the same for its tracker rows."""

    from tools.agentops import monitor_dashboard as md
    import progress

    monkeypatch.setattr(progress, "_gh", lambda args: "[]")
    return {"gh_runner": lambda args: "[]", "cache": md.DashboardCache()}


def _no_git_call(args, cwd):
    raise AssertionError(f"a test must never run real git ({args!r} in {cwd!r})")


def test_build_snapshot_shape(prices, monkeypatch, tmp_path):
    snapshot = monitor.build_snapshot([_raw_session()], projects_dir=PROJECTS_DIR, prices=prices,
                                      repo_cwd=ROOT, now=NOW, issue_records=[],
                                      dashboard_kwargs=_no_network_dashboard_kwargs(monkeypatch),
                                      git_runner=_no_git_call, lane_state_file=tmp_path / "cloud_lane.json")
    assert set(snapshot) == {"generated_at", "main_ahead", "cloud_lane", "waiting_on_you", "agents",
                             "pob_runs", "issues", "progress", "results", "cost", "events"}
    assert snapshot["cloud_lane"]["line"].startswith("Cloud lane: ")  # #121 item 7, one line
    assert snapshot["agents"][0]["session_id"] == "sessM"
    assert "jobs" in snapshot["pob_runs"] and "slots" in snapshot["pob_runs"]


def test_565_empty_lane_file_does_not_break_the_snapshot(prices, monkeypatch, tmp_path):
    lane = tmp_path / "cloud_lane.json"
    lane.write_text("", encoding="utf-8")  # a half-written file read by the monitor (#565)
    snapshot = monitor.build_snapshot([_raw_session()], projects_dir=PROJECTS_DIR, prices=prices,
                                      repo_cwd=ROOT, now=NOW, issue_records=[],
                                      dashboard_kwargs=_no_network_dashboard_kwargs(monkeypatch),
                                      git_runner=_no_git_call, lane_state_file=lane)
    assert snapshot["cloud_lane"]["line"].startswith("Cloud lane: ")


def test_565_write_json_uses_a_tmp_name_of_its_own(tmp_path, monkeypatch):
    from tools.agentops import util
    seen = []
    real = util.os.replace
    monkeypatch.setattr(util.os, "replace", lambda a, b: (seen.append(Path(a).name), real(a, b))[1])
    util.write_json(tmp_path / "x.json", {"a": 1})
    util.write_json(tmp_path / "x.json", {"a": 2})
    assert len(set(seen)) == 2 and all(n != "x.json.tmp" for n in seen)
    assert list(tmp_path.iterdir()) == [tmp_path / "x.json"]


# ------------------------------------------------------------------------------- main_ahead (#78) --


class _FakeGitResult:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_git_main_ahead_reads_the_count(tmp_path):
    calls = []

    def fake_runner(args, cwd):
        calls.append((args, cwd))
        return _FakeGitResult(0, "3\n")

    assert monitor.git_main_ahead(tmp_path, runner=fake_runner) == 3
    assert calls == [(["git", "rev-list", "--count", "origin/main..main"], tmp_path)]


def test_git_main_ahead_zero_when_pushed(tmp_path):
    assert monitor.git_main_ahead(tmp_path, runner=lambda args, cwd: _FakeGitResult(0, "0\n")) == 0


def test_git_main_ahead_none_on_nonzero_exit(tmp_path):
    assert monitor.git_main_ahead(tmp_path, runner=lambda args, cwd: _FakeGitResult(128, "")) is None


def test_git_main_ahead_none_when_git_missing(tmp_path):
    def raiser(args, cwd):
        raise FileNotFoundError("git")

    assert monitor.git_main_ahead(tmp_path, runner=raiser) is None


def test_build_snapshot_carries_main_ahead(prices, monkeypatch, tmp_path):
    snapshot = monitor.build_snapshot([_raw_session()], projects_dir=PROJECTS_DIR, prices=prices,
                                      repo_cwd=ROOT, now=NOW, issue_records=[],
                                      dashboard_kwargs=_no_network_dashboard_kwargs(monkeypatch),
                                      git_runner=lambda args, cwd: _FakeGitResult(0, "5\n"),
                                      lane_state_file=tmp_path / "cloud_lane.json")
    assert snapshot["main_ahead"] == 5


# ---------------------------------------------------------------------------------- PoB runs -----


def test_panel_pob_runs_reads_the_job_store(tmp_path, monkeypatch):
    store = Store(tmp_path / "jobs.jsonl")
    running = store.submit(host="pc", priority="P0", tag="running-job", cmd="echo hi", issue=52)
    store.start(running.id, pid=111)
    store.submit(host="laptop", priority="P2", tag="queued-job", cmd="echo bye", issue=7)

    class FakeBudget:
        total = 7
        period = "day"

        def limit_for(self, role):
            return 2

        def window(self):
            return "08:00-01:00"

    from junkroan.pob import slot_budget as real_slot_budget

    monkeypatch.setattr(real_slot_budget, "slot_dir", lambda: tmp_path / "slots")
    monkeypatch.setattr(real_slot_budget, "load_budget", lambda: FakeBudget())
    monkeypatch.setattr(real_slot_budget, "busy_slots", lambda folder, budget=None: [{"slot": 1}])
    monkeypatch.setattr(real_slot_budget, "current_host", lambda: "pc-test")

    result = monitor.panel_pob_runs(store=store, now=NOW)

    by_tag = {job["tag"]: job for job in result["jobs"]}
    assert by_tag["running-job"]["state"] == "running"
    assert by_tag["running-job"]["host"] == "pc"
    assert by_tag["running-job"]["issue"] == 52
    assert by_tag["queued-job"]["state"] == "queued"
    assert by_tag["queued-job"]["priority"] == "P2"

    assert result["slots"] == {
        "host": "pc-test", "busy": 1, "total": 7, "others_limit": 2,
        "period": "day", "window": "08:00-01:00",
    }


def test_panel_pob_runs_survives_unreadable_budget(tmp_path):
    store = Store(tmp_path / "jobs.jsonl")
    result = monitor.panel_pob_runs(store=store, slot_folder=tmp_path / "does-not-matter", now=NOW)
    assert "jobs" in result
    assert "slots" in result  # real slot_budget module ran; either real numbers or an "error" key
    assert "laptop" not in result  # no laptop_cache given: the laptop read is skipped entirely


def test_panel_pob_runs_omits_laptop_when_no_cache_given(tmp_path):
    """No `laptop_cache` (the default, and every test above): no real SSH is ever attempted."""

    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P0", tag="pc-job", cmd="echo hi", issue=1)
    result = monitor.panel_pob_runs(store=store, now=NOW)
    assert [job["tag"] for job in result["jobs"]] == ["pc-job"]
    assert "laptop" not in result


def test_81_panel_pob_runs_shows_pending_on_the_very_first_read(tmp_path):
    """Before the laptop's first background refresh completes: `pending=True`, not "no jobs"."""

    from junkroan.runs.remote_store import LaptopJobsCache

    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P0", tag="pc-job", cmd="echo hi", issue=1)
    cache = LaptopJobsCache(lambda: [], clock=lambda: 0.0, executor=lambda fn: None)  # never runs

    result = monitor.panel_pob_runs(store=store, now=NOW, laptop_cache=cache)

    assert [job["tag"] for job in result["jobs"]] == ["pc-job"]
    assert result["laptop"]["pending"] is True
    assert result["laptop"]["ok"] is False


def test_81_panel_pob_runs_shows_the_laptop_job_next_to_the_pc_job(tmp_path):
    from junkroan.runs.remote_store import LaptopJobsCache
    from junkroan.runs.store import Job

    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P0", tag="pc-job", cmd="echo hi", issue=1)

    laptop_job = Job(id="j-laptop-1", host="laptop", priority="P1", issue=81, submitter="",
                     tag="laptop-job", pin=None, cmd="echo bye", resumable=False,
                     state="queued", submit_ts="2026-09-26T09:00:00.000000+00:00")
    cache = LaptopJobsCache(lambda: [laptop_job], clock=lambda: 0.0, executor=lambda fn: fn())
    cache.read()  # warm it up: the first read only triggers the (synchronous, here) background fetch

    result = monitor.panel_pob_runs(store=store, now=NOW, laptop_cache=cache)

    by_tag = {job["tag"]: job for job in result["jobs"]}
    assert set(by_tag) == {"pc-job", "laptop-job"}
    assert by_tag["laptop-job"]["host"] == "laptop"
    assert by_tag["laptop-job"]["issue"] == 81
    assert result["laptop"] == {"ok": True, "stale": False, "pending": False, "age_human": "0 s", "error": None}


def test_81_panel_pob_runs_reports_an_unreachable_laptop_not_no_jobs(tmp_path):
    from junkroan.runs.remote_store import LaptopJobsCache, RemoteStoreUnreachable

    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P0", tag="pc-job", cmd="echo hi", issue=1)

    def broken_reader():
        raise RemoteStoreUnreachable("ssh: Connection timed out")

    cache = LaptopJobsCache(broken_reader, clock=lambda: 0.0, executor=lambda fn: fn())
    cache.read()  # warm it up: triggers the (synchronous, here) failing refresh

    result = monitor.panel_pob_runs(store=store, now=NOW, laptop_cache=cache)

    assert [job["tag"] for job in result["jobs"]] == ["pc-job"]  # no fake laptop job appears
    assert result["laptop"]["ok"] is False
    assert result["laptop"]["pending"] is False
    assert "Connection timed out" in result["laptop"]["error"]


# ------------------------------------------------------------------------------ daemons (#73) -----

class _FakeLaptopCache:
    """A `LaptopJobsCache`-shaped fake: `.read()` returns an object with a `.daemon_status`."""

    def __init__(self, daemon_status: dict | None) -> None:
        self._daemon_status = daemon_status

    def read(self):
        from types import SimpleNamespace

        return SimpleNamespace(jobs=[], ok=True, stale=False, age_seconds=0.0, error=None,
                               pending=False, daemon_status=self._daemon_status)


def test_panel_daemons_pc_live_when_pid_alive_and_tick_fresh(tmp_path):
    status_path = tmp_path / "daemon-pc.json"
    status_path.write_text(json.dumps({
        "host": "pc", "pid": 4242, "started": "2026-09-26T10:00:00+00:00",
        "last_tick": "2026-09-26T10:09:55+00:00", "tick_seconds": 10.0,
        "running": ["j-1", "j-2"], "queued": 3,
    }), encoding="utf-8")

    result = monitor.panel_daemons(now=NOW, status_path=status_path, pid_alive=lambda pid: True)

    pc_row = result["rows"][0]
    assert pc_row == {"host": "pc", "pid": 4242, "state": "live", "last_tick_age_human": "5 s",
                      "running": 2, "queued": 3,
                      # #132: no filler numbers in this status file, so the column reads "-"
                      "fillers": "-", "fillers_ran_out": False, "fillers_message_pending": None}


def test_panel_daemons_pc_stale_when_the_tick_is_old(tmp_path):
    status_path = tmp_path / "daemon-pc.json"
    status_path.write_text(json.dumps({
        "host": "pc", "pid": 4242, "started": "2026-09-26T09:00:00+00:00",
        "last_tick": "2026-09-26T09:55:00+00:00", "tick_seconds": 10.0,
        "running": [], "queued": 0,
    }), encoding="utf-8")

    result = monitor.panel_daemons(now=NOW, status_path=status_path, pid_alive=lambda pid: True)

    pc_row = result["rows"][0]
    assert pc_row["state"] == "stale"
    assert pc_row["host"] == "pc"


def test_panel_daemons_pc_not_running_when_no_file(tmp_path):
    result = monitor.panel_daemons(now=NOW, status_path=tmp_path / "nope.json", pid_alive=lambda pid: True)
    assert result["rows"][0] == {"host": "pc", "pid": None, "state": "not running",
                                "last_tick_age_human": None, "running": 0, "queued": 0,
                                "fillers": "-", "fillers_ran_out": False,
                                "fillers_message_pending": None}


def test_panel_daemons_pc_not_running_when_pid_is_dead(tmp_path):
    status_path = tmp_path / "daemon-pc.json"
    status_path.write_text(json.dumps({
        "host": "pc", "pid": 4242, "last_tick": "2026-09-26T10:09:55+00:00", "tick_seconds": 10.0,
        "running": [], "queued": 0,
    }), encoding="utf-8")

    result = monitor.panel_daemons(now=NOW, status_path=status_path, pid_alive=lambda pid: False)
    assert result["rows"][0]["state"] == "not running"


def test_panel_daemons_laptop_row_comes_from_the_cache_reading_no_extra_ssh_call(tmp_path):
    cache = _FakeLaptopCache({
        "host": "laptop", "pid": 99, "last_tick": "2026-09-26T10:09:58+00:00", "tick_seconds": 10.0,
        "running": ["j-9"], "queued": 1,
    })
    result = monitor.panel_daemons(now=NOW, status_path=tmp_path / "nope.json", laptop_cache=cache)
    assert len(result["rows"]) == 2
    laptop_row = result["rows"][1]
    assert laptop_row == {"host": "laptop", "pid": 99, "state": "live", "last_tick_age_human": "2 s",
                          "running": 1, "queued": 1,
                          "fillers": "-", "fillers_ran_out": False, "fillers_message_pending": None}


def test_panel_daemons_laptop_not_running_when_the_cache_has_no_status(tmp_path):
    cache = _FakeLaptopCache(None)
    result = monitor.panel_daemons(now=NOW, status_path=tmp_path / "nope.json", laptop_cache=cache)
    assert result["rows"][1] == {"host": "laptop", "pid": None, "state": "not running",
                                 "last_tick_age_human": None, "running": 0, "queued": 0,
                                 "fillers": "-", "fillers_ran_out": False,
                                 "fillers_message_pending": None}


def test_panel_pob_runs_includes_daemons_key(tmp_path):
    store = Store(tmp_path / "jobs.jsonl")
    result = monitor.panel_pob_runs(store=store, now=NOW, daemon_status_path=tmp_path / "nope.json")
    assert result["daemons"] == [{"host": "pc", "pid": None, "state": "not running",
                                  "last_tick_age_human": None, "running": 0, "queued": 0,
                                  "fillers": "-", "fillers_ran_out": False,
                                  "fillers_message_pending": None}]


# --------------------------------------------------------------------------------- the server ----


def test_server_binds_localhost_and_serves_snapshot(prices, monkeypatch, tmp_path):
    def snapshot():
        return monitor.build_snapshot([_raw_session()], projects_dir=PROJECTS_DIR, prices=prices,
                                      repo_cwd=ROOT, now=NOW, issue_records=[],
                                      dashboard_kwargs=_no_network_dashboard_kwargs(monkeypatch),
                                      git_runner=_no_git_call, lane_state_file=tmp_path / "cloud_lane.json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), monitor.make_handler(snapshot))
    assert server.server_address[0] == "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["agents"][0]["session_id"] == "sessM"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "poe-junkroan agent monitor" in body
        assert 'data-tab="agents"' in body and 'data-tab="pob-runs"' in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ------------------------------------------------------------------ #60: held issues under ORCH ---


def test_60_the_orch_row_shows_its_held_issues_with_their_subagents(prices):
    sessions = [_raw_session(sessionId="sessM", name="orch #52 #60", cwd=str(ROOT))]
    state = {"session": "sessM", "session_uuid": "sessM", "held": [52, 60], "claimed_now": [60]}

    row = monitor.panel_agents(sessions, projects_dir=PROJECTS_DIR, prices=prices, repo_cwd=ROOT,
                               now=NOW, orch_state=state)["sessions"][0]

    assert [(h["number"], h["claimed"]) for h in row["held_issues"]] == [(52, False), (60, True)]
    assert [s["agent_id"] for s in row["held_issues"][0]["subagents"]] == ["r1", "r2"]  # both name #52
    assert row["held_issues"][1]["subagents"] == [] and row["subagents"] == []


def test_60_no_state_or_another_session_leaves_the_row_as_it_was(prices):
    sessions = [_raw_session(sessionId="sessM", name="orch #52", cwd=str(ROOT))]
    for state in (None, {"session": "other", "session_uuid": "other-uuid", "held": [52]}):
        row = monitor.panel_agents(sessions, projects_dir=PROJECTS_DIR, prices=prices, repo_cwd=ROOT,
                                   now=NOW, orch_state=state)["sessions"][0]
        assert "held_issues" not in row and len(row["subagents"]) == 2


def test_60_load_orch_state(tmp_path):
    path = tmp_path / "orch_session.json"
    assert monitor.load_orch_state(path) is None
    path.write_text(json.dumps({"session": None}), encoding="utf-8")
    assert monitor.load_orch_state(path) is None
    path.write_text(json.dumps({"session": "abc", "held": [1]}), encoding="utf-8")
    assert monitor.load_orch_state(path)["held"] == [1]


def test_60_completed_agent_ids_reads_queue_operation_lines(tmp_path):
    parent = tmp_path / "s.jsonl"
    text = "<task-notification>\n<task-id>q1</task-id>\n<status>completed</status>\n</task-notification>"
    parent.write_text(json.dumps({"type": "queue-operation", "operation": "enqueue", "content": text}) + "\n"
                      + json.dumps({"type": "attachment", "attachment": {"type": "queued_command",
                                    "prompt": text.replace("q1", "q2").replace("completed", "failed")}}) + "\n",
                      encoding="utf-8")
    assert monitor.completed_agent_ids(parent) == {"q1", "q2"}

# ------------------------------------------------------------------ the control strip (#54) ------


def _start_mode_server(*, token="secret-token", apply_mode_fn=None, read_modes_fn=None, revert_fn=None):
    def snapshot():
        return {"generated_at": "x", "agents": [], "pob_runs": {"jobs": [], "slots": {}}}

    handler = monitor.make_handler(
        snapshot, token=token, apply_mode_fn=apply_mode_fn, read_modes_fn=read_modes_fn, revert_fn=revert_fn,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post_mode(port, body, *, token="secret-token"):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Monitor-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/mode", data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_page_embeds_the_per_server_token_and_the_control_strip(prices):
    def snapshot():
        return {"generated_at": "x", "agents": [], "pob_runs": {"jobs": [], "slots": {}}}

    handler = monitor.make_handler(snapshot, token="tok-abc-123")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "tok-abc-123" in body
        assert "__MONITOR_TOKEN__" not in body
        assert 'onclick="setMode(\'pc\',\'play\')"' in body
        assert 'onclick="setMode(\'laptop\',\'browser\')"' in body
        assert "Back to normal" in body
        assert "no timer" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_post_mode_without_token_is_refused_and_nothing_applied():
    calls = []

    def apply_mode_fn(host, mode, minutes):
        calls.append((host, mode, minutes))
        return {"until": None}

    server, thread = _start_mode_server(apply_mode_fn=apply_mode_fn)
    try:
        port = server.server_address[1]
        status, payload = _post_mode(port, {"host": "pc", "mode": "play", "minutes": 60}, token=None)
        assert status == 403
        assert payload["ok"] is False
        assert calls == [], "a rejected token must never reach apply_mode_fn"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_post_mode_with_valid_token_applies_and_returns_until():
    calls = []

    def apply_mode_fn(host, mode, minutes):
        calls.append((host, mode, minutes))
        return {"until": "2026-09-26T13:00:00"}

    server, thread = _start_mode_server(apply_mode_fn=apply_mode_fn)
    try:
        port = server.server_address[1]
        status, payload = _post_mode(port, {"host": "pc", "mode": "play", "minutes": 60})
        assert status == 200
        assert payload == {"ok": True, "until": "2026-09-26T13:00:00"}
        assert calls == [("pc", "play", 60)]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_post_mode_failing_apply_reports_the_error_and_changes_nothing():
    def apply_mode_fn(host, mode, minutes):
        raise RuntimeError("ssh failed")

    server, thread = _start_mode_server(apply_mode_fn=apply_mode_fn)
    try:
        port = server.server_address[1]
        status, payload = _post_mode(port, {"host": "laptop", "mode": "browser", "minutes": 30})
        assert status == 400
        assert payload == {"ok": False, "error": "ssh failed"}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_api_modes_reports_mode_and_seconds_left():
    def read_modes_fn():
        return {"pc": {"mode": "play", "until": "2026-09-26T13:00:00"}}

    server, thread = _start_mode_server(read_modes_fn=read_modes_fn)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/modes", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["pc"]["mode"] == "play"
        assert data["laptop"]["mode"] == "normal"  # no entry recorded -> normal, no timer
        assert data["laptop"]["seconds_left"] is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_snapshot_path_calls_revert_expired_modes_once():
    calls = []

    def snapshot():
        return {"generated_at": "x", "agents": [], "pob_runs": {"jobs": [], "slots": {}}}

    handler = monitor.make_handler(snapshot, revert_fn=lambda: calls.append(1))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=5):
            pass
        assert calls == [1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
