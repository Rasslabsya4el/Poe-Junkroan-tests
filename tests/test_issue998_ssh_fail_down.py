"""#998 (ssh fail down): an ssh call that could not reach the laptop (rc 255) marks the host down for the pass.

Cause: `ssh` exits 255 after ~21 s when the laptop is dead ("Connection timed out"). That exit is returned,
not raised, so before the fix nothing marked `ssh:laptop` down and each of the three remote steps of one daemon
pass called ssh again: 3 x 21 s = 63 s. Fake clock only: no real ssh, no PoB, no sleeping.
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

from junkroan.runs import anomalies as an_mod  # noqa: E402
from junkroan.runs import bounded as bounded_mod  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import hosts, remote_store  # noqa: E402
from junkroan.runs.pass_guard import GUARD  # noqa: E402
from test_issue998_slow_pass import FakeClock, clock, lines  # noqa: E402,F401  (the #998 pass fixtures)
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

HOST = {"name": "laptop", "ssh": "laptop", "repo_path": "C:/x"}
KEY = "ssh:laptop"
DEAD_SECONDS = 21.0
UNREACHABLE_STDERR = "ssh: connect to host laptop port 22: Connection timed out"


@pytest.fixture(autouse=True)
def fresh_pass():
    GUARD.begin()
    yield
    GUARD.begin()


class DeadLaptop:
    """gh answers normally; every ssh call answers rc 255 "Connection timed out" after 21 s of fake clock."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.ssh_calls: list = []

    def gh(self, argv, **kwargs):
        if argv[0] != "gh":
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"state": "OPEN", "comments": []}), stderr="")

    def ssh(self, argv, **kwargs):
        self.ssh_calls.append(kwargs.get("timeout"))
        self.clock.advance(DEAD_SECONDS)
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr=UNREACHABLE_STDERR)


class _NoSessions:                        # no real Claude program (#759)
    def list_sessions(self) -> list:
        return []


def _dead_laptop_pass(tmp_path, monkeypatch, clock, lines) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    laptop = DeadLaptop(clock)
    monkeypatch.setattr(daemon_mod, "run_bounded", laptop.gh)
    monkeypatch.setattr(hosts, "run_bounded", laptop.ssh)
    monkeypatch.setattr(bounded_mod, "run_bounded", laptop.ssh)   # remote_store imports it inside its call
    gh = daemon_mod.GhCli(cwd=tmp_path)
    daemon, _, _ = make_daemon(tmp_path, gh=gh, launcher=FakeLauncher(),
                               hosts_config={"laptop": HOST}, remote_pass_seconds=0.0)
    # the PC daemon's own anomaly guard (`scripts/runs.py _build_anomaly_guard`): its laptop probe is the third ssh step
    daemon.anomaly_guard = an_mod.AnomalyGuard(path=tmp_path / "anomalies.json", host="pc",
                                               host_prober=an_mod.make_host_prober(HOST), launcher=_NoSessions(),
                                               clock=clock, log=lambda message: None)
    daemon._ticket_check_seconds = 0.0    # the ticket check runs on every pass of this test (private knob)
    daemon.log = lambda message: None
    before = clock()
    daemon.tick()                          # one whole pass with the laptop dead
    return {"elapsed": clock() - before, "ssh": list(laptop.ssh_calls), "lines": list(lines)}


# -- the whole pass: one ssh call, under a minute ------------------------------------------------------

def test_a_dead_laptop_costs_one_ssh_call_and_21_seconds_in_the_whole_pass(tmp_path, monkeypatch, clock, lines):
    dead = _dead_laptop_pass(tmp_path, monkeypatch, clock, lines)
    assert len(dead["ssh"]) == 1, dead
    assert dead["elapsed"] == DEAD_SECONDS and dead["elapsed"] < 60.0, dead["elapsed"]


# -- one call: the rc 255 mark, and the rc of a remote command that is not 255 --------------------------

def test_an_unreachable_exit_marks_the_host_down_for_the_rest_of_the_pass(monkeypatch):
    calls: list = []

    def dead_ssh(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr=UNREACHABLE_STDERR)

    monkeypatch.setattr(hosts, "run_bounded", dead_ssh)
    first = hosts.run_on_host(HOST, "first")
    assert first.returncode == 255 and GUARD.down(KEY)
    second = hosts.run_on_host(HOST, "second")
    assert second.returncode == 255 and second.stderr == hosts.SKIPPED_SSH_STDERR
    assert len(calls) == 1


def test_a_remote_nonzero_exit_other_than_255_does_not_mark_the_host_down(monkeypatch):
    calls: list = []

    def remote_fails(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="remote script failed")

    monkeypatch.setattr(hosts, "run_bounded", remote_fails)
    monkeypatch.setattr(bounded_mod, "run_bounded", remote_fails)
    assert hosts.run_on_host(HOST, "first").returncode == 1
    assert not GUARD.down(KEY)
    with pytest.raises(remote_store.RemoteStoreUnreachable):
        remote_store.read_remote_anomalies(HOST)
    assert not GUARD.down(KEY)
    assert hosts.run_on_host(HOST, "second").returncode == 1
    assert len(calls) == 3              # every call was made: a remote rc 1 never skips the host
