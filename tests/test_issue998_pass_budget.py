"""#998 (unit 2 of 3, kill-bound): a call that times out returns within its timeout + 10 s, and a pass
that has used 45 s starts no further outside call.

Fake clock only: the child process, the taskkill, the pid wait and every gh/ssh runner are fakes that advance
the clock by the time they were given. No real process, no ssh, no gh, no PoB, nothing sleeps.
"""

from __future__ import annotations

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
from junkroan.runs import hosts, remote_store, row_sync, stopper  # noqa: E402
from junkroan.runs.pass_guard import PassGuard  # noqa: E402
from test_issue998_slow_pass import HOST, FakeClock, Services  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

#: the whole pass budget of #998: once a pass has used this much, no further outside call is started.
BUDGET_SECONDS = 45.0
#: the slack a single call may take on top of its own timeout (the kill and the drain included).
SLACK_SECONDS = 10.0


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    """One fake clock drives the module-level guard of every module that imports `GUARD`."""

    fake = FakeClock()
    guard = PassGuard(clock=fake)
    for module in (daemon_mod, hosts, row_sync, remote_store):
        monkeypatch.setattr(module, "GUARD", guard)
    return fake


class HangingChild:
    """A child whose pipes never drain: `communicate` waits the whole timeout it is given, then raises."""

    pid = 4242

    def __init__(self, argv, clock: FakeClock) -> None:
        self.args = argv
        self.clock = clock
        self.returncode = None
        self.stdout = None
        self.stderr = None
        self.stdin = None
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self.clock.advance(timeout)
        raise subprocess.TimeoutExpired(self.args, timeout)

    def kill(self) -> None:
        self.killed = True


# -- (1) a call that hangs through the kill returns within its timeout + 10 s ----------------------

def test_a_hanging_call_with_a_hanging_taskkill_returns_within_timeout_plus_10(monkeypatch, clock):
    children: list[HangingChild] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: children.append(HangingChild(argv, clock)) or children[-1])

    def taskkill_hangs(argv, *args, timeout=None, **kwargs):
        clock.advance(timeout)                      # taskkill runs until its own timeout
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(subprocess, "run", taskkill_hangs)
    monkeypatch.setattr(stopper, "_pid_gone", lambda pid, *, wait=5.0: clock.advance(wait) or False)

    start = clock()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_mod.run_bounded(["slow-tool"], capture_output=True, timeout=20.0)
    elapsed = clock() - start

    assert children and children[0].killed is True
    assert 20.0 <= elapsed <= 20.0 + SLACK_SECONDS, elapsed


def test_a_hanging_call_with_a_taskkill_that_says_no_returns_within_timeout_plus_10(monkeypatch, clock):
    children: list[HangingChild] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: children.append(HangingChild(argv, clock)) or children[-1])

    def taskkill_refuses(argv, *args, timeout=None, **kwargs):
        clock.advance(0.5)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="access is denied")

    monkeypatch.setattr(subprocess, "run", taskkill_refuses)
    monkeypatch.setattr(stopper, "_pid_gone", lambda pid, *, wait=5.0: clock.advance(wait) or False)

    start = clock()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_mod.run_bounded(["slow-tool"], capture_output=True, timeout=20.0)
    elapsed = clock() - start

    assert 20.0 <= elapsed <= 20.0 + SLACK_SECONDS, elapsed


# -- (2) the pass budget: a pass that used 45 s starts no further outside call ----------------------

def _pass_whose_first_step_takes(tmp_path, monkeypatch, clock, first_step_seconds: float) -> Services:
    """One real `Daemon.tick`: `retry_handbacks` (the first step) advances the clock, then every later step
    that makes an outside call runs. gh and ssh both answer normally; the Services count each call."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    services = Services(clock, dead=False)
    monkeypatch.setattr(daemon_mod, "run_bounded", services.gh)
    monkeypatch.setattr(hosts, "run_bounded", services.ssh)
    monkeypatch.setattr(bounded_mod, "run_bounded", services.ssh)   # remote_store imports it inside its call
    daemon, store, _ = make_daemon(tmp_path, gh=daemon_mod.GhCli(cwd=tmp_path), launcher=FakeLauncher(),
                                   hosts_config={"laptop": HOST}, remote_pass_seconds=0.0)
    daemon._ticket_check_seconds = 0.0   # the ticket check runs on every pass of this test (private knob)
    daemon.log = lambda message: None
    for n in range(1, 8):
        store.submit(host="pc", priority="P1", tag=f"t{n}", cmd="echo hi", issue=n)
    daemon.retry_handbacks = lambda: clock.advance(first_step_seconds) or []
    daemon.tick()
    return services


def test_a_pass_that_used_45_seconds_starts_no_further_outside_call(tmp_path, monkeypatch, clock):
    services = _pass_whose_first_step_takes(tmp_path, monkeypatch, clock, BUDGET_SECONDS)

    assert services.gh_timeouts == [], services.gh_timeouts     # the ticket check's gh read is skipped
    assert services.ssh_timeouts == [], services.ssh_timeouts   # the laptop read is skipped


def test_a_pass_that_used_20_seconds_still_starts_its_outside_calls(tmp_path, monkeypatch, clock):
    services = _pass_whose_first_step_takes(tmp_path, monkeypatch, clock, 20.0)

    assert len(services.ssh_timeouts) == 1, services.ssh_timeouts   # the laptop is read, as before


def test_the_budget_is_spent_at_45_seconds_and_not_before(clock):
    guard = PassGuard(clock=clock)
    guard.begin()
    clock.advance(BUDGET_SECONDS - 0.1)
    assert guard.down("gh") is False
    clock.advance(0.1)
    assert guard.down("gh") is True
    assert guard.mark_down("gh") is False        # a skipped call is no new "did not answer" line


def test_a_guard_that_never_began_a_pass_has_no_budget(clock):
    guard = PassGuard(clock=clock)               # a CLI or the monitor's refresh: no begin() ever
    clock.advance(500.0)
    assert guard.down("gh") is False
