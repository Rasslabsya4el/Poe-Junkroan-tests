"""#1000: the daemon's own outside calls inside one pass are bounded (early warning 60 s, gate copy start
deadline + size walk cap, copy_dir_to_host 60 s, the weekly cut's git fetch 45 s, the local git reads one
shared 30 s limit per pass).

Fakes only: subprocess.run / Popen stand-ins; a fake clock that a hanging call spends its whole timeout on.
No sleep, no real process, no ssh, no git, no PoB.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_issue701_replay_copy import BASE, _setup  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402
from test_runs_gate_copy import NAME, Rig  # noqa: E402

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import gates  # noqa: E402
from junkroan.runs.pass_guard import PassGuard  # noqa: E402
from junkroan.runs.rebalance import Rebalancer  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> FakeClock:
    """A fresh pass guard on a fake clock for every test (the daemon's GUARD is module-global)."""

    c = FakeClock()
    monkeypatch.setattr(daemon_mod, "GUARD", PassGuard(clock=c))
    return c


def _hang(clock: FakeClock, calls: list):
    """A subprocess.run / runner stand-in that never answers: it spends its whole timeout on the fake clock,
    records (argv, timeout), then raises TimeoutExpired."""

    def fake_run(args, *a, **kw):
        timeout = kw.get("timeout") or 0
        calls.append((list(args), kw.get("timeout")))
        clock.now += timeout
        raise subprocess.TimeoutExpired(args, timeout)

    return fake_run


def _timeouts(calls: list) -> list:
    return [t for _, t in calls]


# -- row 1: the early warning -------------------------------------------------------------------

def test_early_warning_hang_is_cut_at_one_minute_and_logged(tmp_path, monkeypatch, clock):
    d = make_daemon(tmp_path)[0]
    logs: list[str] = []
    d.log = logs.append
    d._warn_week_of = lambda job: "20261012"
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _hang(clock, calls))
    assert d._early_warning_after(SimpleNamespace(id="j1")) is None
    assert _timeouts(calls) == [60]
    assert clock.now <= 60
    failed = [m for m in logs if "early warning for week 20261012 failed" in m]
    assert len(failed) == 1 and len(logs) == 1


def test_early_warning_answering_run_gives_the_same_end_handling(tmp_path, monkeypatch):
    d = make_daemon(tmp_path)[0]
    logs: list[str] = []
    d.log = logs.append
    d._warn_week_of = lambda job: "20261012"
    monkeypatch.setattr(subprocess, "run",
                        lambda args, *a, **kw: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))
    assert d._early_warning_after(SimpleNamespace(id="j1")) is None
    assert logs == ["early warning for week 20261012 run after j1"]


# -- row 3: copy_dir_to_host (Rebalancer move) ---------------------------------------------------

def _copy_rig(tmp_path, dir_run):
    d = make_daemon(tmp_path)[0]
    logs: list[str] = []
    d.log = logs.append
    art = tmp_path / "artifacts"
    (art / "replay" / BASE).mkdir(parents=True)
    (art / "replay" / BASE / "r.json").write_text("[]", encoding="utf-8")
    d._gate_artifacts = art
    d._gates_path = tmp_path / "gates.json"
    scripts: list[str] = []
    d._gate_run_on_host = lambda cfg, script: scripts.append(script) or SimpleNamespace(returncode=0)
    d._dir_copy_run = dir_run
    return d, logs, scripts


CFG = {"ssh": "laptop", "daemon_repo_path": r"C:\Coding\d"}


def test_copy_dir_hang_is_cut_at_one_minute_and_skipped(tmp_path, clock):
    calls: list = []
    d, logs, scripts = _copy_rig(tmp_path, _hang(clock, calls))
    assert d.copy_dir_to_host("laptop", CFG, f"replay/{BASE}") is False
    assert _timeouts(calls) == [60]
    assert clock.now <= 60
    assert [m for m in logs if "copy of" in m and "failed" in m] and len(logs) == 1
    assert gates.gates_present("laptop", d._gates_path) == set()
    assert not any("Rename-Item" in s for s in scripts)


def test_copy_dir_failing_answer_gives_the_same_decision(tmp_path):
    d, logs, scripts = _copy_rig(tmp_path, lambda argv, **kw: SimpleNamespace(returncode=1))
    assert d.copy_dir_to_host("laptop", CFG, f"replay/{BASE}") is False
    assert gates.gates_present("laptop", d._gates_path) == set()
    assert not any("Rename-Item" in s for s in scripts)


def test_copy_dir_hang_leaves_the_job_queued_like_a_failed_copy(tmp_path, monkeypatch, clock):
    """Through the Rebalancer: the job stays queued, nothing is submitted, the same as a failed copy."""

    def outcome(sub: str, dir_run):
        base = tmp_path / sub
        base.mkdir(parents=True)
        daemon, store, laptop, logged, calls, held, copies, job = _setup(base, monkeypatch, copy_ok=True)
        daemon._rebalancer = Rebalancer(
            daemon, has_pin=lambda cfg, host, pin: True, submit_moved=daemon._rebalancer._submit_moved,
            gates_present=lambda host: held[host], newest_gate=lambda root: None)
        daemon._gate_run_on_host = lambda cfg, script: SimpleNamespace(returncode=0)
        daemon._dir_copy_run = dir_run
        daemon._gates_path = base / "gates.json"
        daemon.tick()
        return store.get(job.id).state, calls["submit"], [m for m in logged if "stays" in m][:1]

    calls: list = []
    hung = outcome("hung", _hang(clock, calls))
    failed = outcome("failed", lambda argv, **kw: SimpleNamespace(returncode=1))
    assert _timeouts(calls) and all(t == 60 for t in _timeouts(calls))
    assert hung[0] == failed[0] == "queued" and hung[1] == failed[1] == 0


# -- the weekly cut's git fetch (take_cut_pass) --------------------------------------------------

def test_cut_fetch_hang_is_cut_at_45_seconds_and_retried_later(tmp_path, monkeypatch, clock):
    d = make_daemon(tmp_path, hosts_config={"pc": {"fillers": True}})[0]
    repo = tmp_path / "repo"
    repo.mkdir()
    d._cut_repo = repo
    d.timestamp = lambda: datetime(2026, 10, 17, 12, 0)  # a Saturday: the cut is open
    d.clock = clock
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _hang(clock, calls))
    assert d.take_cut_pass() is None
    assert _timeouts(calls) == [45]
    assert clock.now <= 45
    assert d._cut_done is None


def test_cut_fetch_failing_answer_gives_the_same_decision(tmp_path, monkeypatch):
    d = make_daemon(tmp_path, hosts_config={"pc": {"fillers": True}})[0]
    repo = tmp_path / "repo"
    repo.mkdir()
    d._cut_repo = repo
    d.timestamp = lambda: datetime(2026, 10, 17, 12, 0)
    d.clock = lambda: 0.0
    monkeypatch.setattr(subprocess, "run",
                        lambda args, *a, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr="no"))
    assert d.take_cut_pass() is None
    assert d._cut_done is None


# -- the local git reads (_host_behind, _origin_main, _host_head) ------------------------------

def test_host_behind_hang_costs_one_timeout_per_pass(tmp_path, monkeypatch, clock, capsys):
    d = make_daemon(tmp_path)[0]
    d._host_checkout = tmp_path
    job = SimpleNamespace(pin=None, submit_commit="a" * 40, is_filler=False)
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _hang(clock, calls))
    assert [d._host_behind(job) for _ in range(3)] == [None, None, None]
    assert _timeouts(calls) == [30]
    assert clock.now <= 30
    assert capsys.readouterr().err.count("did not answer") == 1


def test_host_behind_failed_read_gives_the_same_answer(tmp_path, monkeypatch):
    d = make_daemon(tmp_path)[0]
    d._host_checkout = tmp_path
    job = SimpleNamespace(pin=None, submit_commit="a" * 40, is_filler=False)
    monkeypatch.setattr(subprocess, "run",
                        lambda args, *a, **kw: subprocess.CompletedProcess(args, 128, stdout="", stderr=""))
    assert d._host_behind(job) is None


def test_origin_main_and_host_head_share_the_pass_limit(tmp_path, monkeypatch, clock, capsys):
    d = make_daemon(tmp_path)[0]
    d._host_checkout = tmp_path
    job = SimpleNamespace(pin=None, submit_commit="a" * 40, is_filler=False)
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _hang(clock, calls))
    assert daemon_mod._origin_main(tmp_path) == ""
    assert d._host_head() is None
    assert d._host_behind(job) is None
    assert _timeouts(calls) == [30]
    assert clock.now <= 30
    assert capsys.readouterr().err.count("did not answer") == 1


def test_origin_main_and_host_head_failed_answers(tmp_path, monkeypatch):
    d = make_daemon(tmp_path)[0]
    d._host_checkout = tmp_path
    monkeypatch.setattr(subprocess, "run",
                        lambda args, *a, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr=""))
    assert daemon_mod._origin_main(tmp_path) == ""
    assert d._host_head() is None


# -- row 2: the gate copy to the laptop ----------------------------------------------------------

class KillableProc:
    pid = 4242

    def __init__(self, argv) -> None:
        self.argv = argv
        self.rc = None
        self.killed = False

    def poll(self):
        return self.rc

    def kill(self) -> None:
        self.killed = True


def _gate_rig(tmp_path):
    rig = Rig(tmp_path)
    procs: list[KillableProc] = []

    def popen(argv, **kw):
        p = KillableProc(argv)
        procs.append(p)
        return p

    killed: list[int] = []
    rig.daemon._gate_popen = popen
    rig.daemon._copy_killer = killed.append
    return rig, procs, killed


def test_gate_copy_past_its_limit_is_killed_and_retried_later(tmp_path):
    limit = daemon_mod.GATE_COPY_LIMIT_SECONDS
    rig, procs, killed = _gate_rig(tmp_path / "a")
    rig.daemon.gate_sync_pass()
    assert len(procs) == 1
    rig.now += limit + 1
    rig.daemon.gate_sync_pass()
    assert killed == [4242] and procs[0].killed
    assert rig.daemon._gate_copy is None
    assert len([m for m in rig.logs if "ran over" in m]) == 1
    assert rig.held() == set()
    rig.daemon.gate_sync_pass()
    assert len(procs) == 2

    # the decision equals a copy that answered rc 1 at the same moment
    rig2, procs2, _ = _gate_rig(tmp_path / "b")
    rig2.daemon.gate_sync_pass()
    rig2.now += limit + 1
    procs2[0].rc = 1
    rig2.daemon.gate_sync_pass()
    rig2.daemon.gate_sync_pass()
    assert len(procs2) == 2 and rig2.held() == set()


def test_gate_copy_under_its_limit_is_left_running(tmp_path):
    limit = daemon_mod.GATE_COPY_LIMIT_SECONDS
    rig, procs, killed = _gate_rig(tmp_path)
    rig.daemon.gate_sync_pass()
    rig.now += limit - 60
    rig.daemon.gate_sync_pass()
    assert killed == [] and not procs[0].killed and rig.daemon._gate_copy is not None
    rig.now += 60
    procs[0].rc = 0
    rig.daemon.gate_sync_pass()
    assert rig.held() == {NAME}


def test_gate_size_walk_over_its_entry_cap_skips_the_size(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "GATE_SIZE_WALK_MAX_ENTRIES", 0)
    rig, procs, killed = _gate_rig(tmp_path)
    rig.daemon.gate_sync_pass()
    assert len(procs) == 1                                   # the copy starts anyway
    assert [m for m in rig.logs if "copying" in m] == [f"gate_sync: copying {NAME} to laptop (size unknown)"]
    procs[0].rc = 0
    rig.now += 90
    rig.daemon.gate_sync_pass()
    assert rig.held() == {NAME}


def test_tree_size_gives_up_past_its_time_or_entry_cap(tmp_path):
    (tmp_path / "a").mkdir()
    for i in range(5):
        (tmp_path / "a" / f"{i}.txt").write_text("xx", encoding="utf-8")
    assert daemon_mod._tree_size(tmp_path, seconds=5, max_entries=100, clock=lambda: 0.0) == 10
    assert daemon_mod._tree_size(tmp_path, seconds=5, max_entries=2, clock=lambda: 0.0) is None
    ticks = iter(range(1000))  # a clock that moves one second per read
    assert daemon_mod._tree_size(tmp_path, seconds=3, max_entries=100, clock=lambda: float(next(ticks))) is None
