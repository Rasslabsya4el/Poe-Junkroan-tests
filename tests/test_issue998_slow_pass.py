"""#998 (unit 5): one daemon pass times its steps and writes one slow-pass line when it runs past 30 s.

Fake clock only: every outside call (gh, ssh) is a fake runner that advances the clock by the timeout it was
given when it "hangs". No real gh, no ssh, no PoB, no sleeping.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import bounded as bounded_mod  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import hosts, remote_store, row_sync  # noqa: E402
from junkroan.runs.pass_guard import PassGuard  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

HOST = {"name": "laptop", "ssh": "laptop", "repo_path": "C:/x"}


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    """One fake clock drives the module-level guard of every module that imports `GUARD`."""

    fake = FakeClock()
    guard = PassGuard(clock=fake)
    for module in (daemon_mod, hosts, row_sync, remote_store):
        monkeypatch.setattr(module, "GUARD", guard)
    return fake


@pytest.fixture
def lines(monkeypatch) -> list[str]:
    """The daemon's `_log` lines (the slow-pass line goes through it)."""

    collected: list[str] = []
    monkeypatch.setattr(daemon_mod, "_log", collected.append)
    return collected


# -- (a) the slow-pass line ------------------------------------------------------------------------

def test_a_31_second_pass_writes_exactly_one_line_naming_the_slowest_step(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(26.0)   # the slowest step: 26 s
    daemon.spike_pass = lambda: clock.advance(5.0)            # the rest of the 31 s
    daemon.tick()
    assert lines == ["slow pass 31 s (slowest step: ticket_closed_pass 26 s; steps over 5 s: ticket_closed_pass 26 s)"], lines


def test_a_5_second_pass_writes_no_line(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(5.0)
    daemon.tick()
    assert lines == []


def test_a_pass_of_exactly_30_seconds_writes_no_line(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(30.0)
    daemon.tick()
    assert lines == []


def test_an_early_return_after_the_restart_gate_is_timed_and_still_writes_its_line(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    reached: list[str] = []

    def restart_and_stop(report):
        clock.advance(40.0)
        report.restarting = True          # tick returns right here, before the machine gate and fill
        return True

    daemon._restart_gate = restart_and_stop
    daemon.fill = lambda: reached.append("fill") or []
    report = daemon.tick()
    assert report.restarting is True
    assert reached == []                  # the early return is unchanged: nothing after the gate ran
    assert lines == ["slow pass 40 s (slowest step: restart_gate 40 s; steps over 5 s: restart_gate 40 s)"], lines


# -- (b) the whole pass: gh and ssh both dead -----------------------------------------------------

class Services:
    """gh and ssh, both answering normally (`dead=False`) or both raising TimeoutExpired (`dead=True`).

    A raised call advances the fake clock by the timeout it was given, so the pass's fake-clock length is the
    sum of the waits the pass really asked for.
    """

    def __init__(self, clock: FakeClock, *, dead: bool) -> None:
        self.clock = clock
        self.dead = dead
        self.gh_timeouts: list[float] = []
        self.ssh_timeouts: list[float] = []

    def gh(self, argv, **kwargs):
        if argv[0] != "gh":
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        self.gh_timeouts.append(kwargs.get("timeout"))
        if self.dead:
            self.clock.advance(kwargs["timeout"])
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"state": "OPEN", "comments": []}), stderr="")

    def ssh(self, argv, **kwargs):
        self.ssh_timeouts.append(kwargs.get("timeout"))
        if self.dead:
            self.clock.advance(kwargs["timeout"])
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")   # a live laptop with no jobs


def _pass_two(tmp_path, monkeypatch, clock, lines, *, dead: bool) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    services = Services(clock, dead=dead)
    monkeypatch.setattr(daemon_mod, "run_bounded", services.gh)
    monkeypatch.setattr(hosts, "run_bounded", services.ssh)
    monkeypatch.setattr(bounded_mod, "run_bounded", services.ssh)   # remote_store imports it inside its call
    launcher = FakeLauncher()
    gh = daemon_mod.GhCli(cwd=tmp_path)
    daemon, store, _ = make_daemon(tmp_path, gh=gh, launcher=launcher,
                                   hosts_config={"laptop": HOST}, remote_pass_seconds=0.0)
    daemon._ticket_check_seconds = 0.0    # the ticket check runs on every pass of this test (private knob)
    daemon.log = lambda message: None
    jobs = [store.submit(host="pc", priority="P1", tag=f"t{n}", cmd="echo hi", issue=n) for n in range(1, 8)]

    daemon.tick()                          # pass 1 (not measured): five start, two wait for room
    for record in launcher.started:
        launcher.finish(record["pid"], 0)  # the five end
    services.gh_timeouts.clear()
    services.ssh_timeouts.clear()
    lines.clear()

    before = clock()
    daemon.tick()                          # pass 2 (measured): the five hand back, two start
    return {
        "elapsed": clock() - before,
        "gh": list(services.gh_timeouts),
        "ssh": list(services.ssh_timeouts),
        "states": [store.get(j.id).state for j in jobs],
        "started": [store.get(j.id).state == "running" for j in jobs],
        "posted": [bool(store.get(j.id).posted) for j in jobs],
        "remote_read": sorted(daemon._remote_jobs_seen),
        "lines": list(lines),
    }


def test_both_services_dead_one_pass_costs_one_call_each_and_touches_no_other_job(tmp_path, monkeypatch, clock, lines):
    dead = _pass_two(tmp_path / "dead", monkeypatch, clock, lines, dead=True)
    normal = _pass_two(tmp_path / "normal", monkeypatch, clock, lines, dead=False)

    # the dead pass: one gh call (45 s cap) and one ssh read (30 s), then everything else is skipped
    assert dead["gh"] == [45.0], dead
    assert dead["ssh"] == [30.0], dead
    assert dead["elapsed"] == 75.0 and dead["elapsed"] < 90.0, dead["elapsed"]
    assert dead["remote_read"] == []      # the laptop was not read in that pass (it failed to answer)
    assert normal["remote_read"] == ["laptop"]
    assert len(normal["ssh"]) == 1 and normal["elapsed"] == 0.0

    # the other jobs: the same states and the same starts with both services answering normally
    assert dead["states"] == normal["states"] == ["done"] * 5 + ["running"] * 2
    assert dead["started"] == normal["started"] == [False] * 5 + [True] * 2
    # the only difference is the hand-back mark of the five ended jobs: not posted, so the next pass retries it
    assert dead["posted"] == [False] * 5 + [False] * 2
    assert normal["posted"] == [True] * 5 + [False] * 2

    # one slow-pass line for the dead pass (the once-per-pass "did not answer" line is another line), none for the normal one
    slow = [line for line in dead["lines"] if "slow pass " in line]
    assert len(slow) == 1 and "(slowest step: reap 45 s; steps over 5 s: " in slow[0], dead["lines"]
    assert slow[0].endswith(", reap 45 s)"), dead["lines"]
    assert [line for line in normal["lines"] if "slow pass " in line] == []


# -- (c) the steps over 5 s: the sum a reader needs, not only the peak -----------------------------

def test_a_31_second_pass_of_three_steps_names_all_three_with_their_durations(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(10.0)
    daemon.spike_pass = lambda: clock.advance(10.0)
    daemon.fill = lambda: clock.advance(11.0) or []
    daemon.tick()
    assert lines == [
        "slow pass 31 s (slowest step: fill 11 s; steps over 5 s: ticket_closed_pass 10 s, spike_pass 10 s, fill 11 s)"
    ], lines


def test_a_5_second_pass_of_three_steps_writes_no_line(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(2.0)
    daemon.spike_pass = lambda: clock.advance(2.0)
    daemon.fill = lambda: clock.advance(1.0) or []
    daemon.tick()
    assert lines == []


def test_a_31_second_pass_with_one_26_second_step_names_only_that_step_in_the_over_five_list(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.ticket_closed_pass = lambda: clock.advance(26.0)
    daemon.spike_pass = lambda: clock.advance(1.0)
    daemon.fill = lambda: clock.advance(4.0) or []
    daemon.tick()
    assert lines == [
        "slow pass 31 s (slowest step: ticket_closed_pass 26 s; steps over 5 s: ticket_closed_pass 26 s)"
    ], lines


def test_a_31_second_pass_whose_steps_are_all_within_5_seconds_says_none(tmp_path, clock, lines):
    daemon, _, _ = make_daemon(tmp_path)
    daemon.retry_handbacks = lambda: clock.advance(5.0) or []
    daemon.ticket_closed_pass = lambda: clock.advance(5.0)
    daemon.spike_pass = lambda: clock.advance(5.0)
    daemon.fill = lambda: clock.advance(5.0) or []
    daemon.reap = lambda: clock.advance(5.0) or []
    daemon.row_sync_pass = lambda: clock.advance(5.0)
    daemon.take_cut_pass = lambda: clock.advance(5.0)
    daemon.tick()
    assert lines == ["slow pass 35 s (slowest step: retry_handbacks 5 s; steps over 5 s: none)"], lines
