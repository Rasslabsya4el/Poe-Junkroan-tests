"""#958: a denied kill is visible. `kill_processes_by_name` returns found / killed / denied; a process that
vanishes before its kill (NoSuchProcess) is not denied; the daemon's end-of-sleep line carries all three
counts. The process list is faked through `psutil.process_iter`, so no real process is read or killed and
no PoB runs."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import owner_commands as oc  # noqa: E402
from tests.test_runs_daemon import BUDGET_NIGHT_10, FakeLauncher, make_daemon  # noqa: E402

T0 = datetime(2026, 10, 13, 22, 0, 0)
DUMMY = "pob958dummy"
HOSTS = {"pc": {"modes": {"night": {"pob_priority": "BelowNormal"}}}}
SLEEP_CONFIG = {"owner_presets": {"sleep": {
    "need_cpu_cores": 1.5, "need_ram_mb": 2500, "for": "2h", "on_end": "close-browsers", "close": [DUMMY]}}}


class FakeProcess:
    def __init__(self, name, error=None):
        self.info = {"name": name}
        self._error = error
        self.kill_calls = 0

    def kill(self):
        self.kill_calls += 1
        if self._error is not None:
            raise self._error


def _processes(monkeypatch, processes):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(processes))


def _three_matches_one_denied():
    return [
        FakeProcess(f"{DUMMY}.exe"),
        FakeProcess(f"{DUMMY.upper()}.EXE"),
        FakeProcess(f"{DUMMY}.exe", error=psutil.AccessDenied(pid=3, name=f"{DUMMY}.exe")),
        FakeProcess("explorer.exe"),  # not in the list: never counted
    ]


def _reading():
    return oc.Reading(idle_cores=0.2, free_ram_mb=800, workers=[oc.Worker(1.0, 900)] * 3)


def test_three_matches_two_killed_one_denied(monkeypatch):
    processes = _three_matches_one_denied()
    _processes(monkeypatch, processes)

    result = runs_hosts.kill_processes_by_name([DUMMY])

    assert (result.found, result.killed, result.denied) == (3, 2, 1)
    assert int(result) == 2  # an old caller that expected the int still gets the killed count
    assert processes[3].kill_calls == 0


def test_a_process_that_vanishes_before_its_kill_is_found_but_not_denied(monkeypatch):
    _processes(monkeypatch, [
        FakeProcess(f"{DUMMY}.exe"),
        FakeProcess(f"{DUMMY}.exe", error=psutil.NoSuchProcess(pid=4, name=f"{DUMMY}.exe")),
    ])

    result = runs_hosts.kill_processes_by_name([DUMMY])

    assert (result.found, result.killed, result.denied) == (2, 1, 0)


def test_any_other_kill_error_is_counted_as_denied(monkeypatch):
    _processes(monkeypatch, [FakeProcess(f"{DUMMY}.exe", error=RuntimeError("boom"))])

    result = runs_hosts.kill_processes_by_name([DUMMY])

    assert (result.found, result.killed, result.denied) == (1, 0, 1)


def test_no_match_is_all_zero(monkeypatch):
    _processes(monkeypatch, [FakeProcess("explorer.exe")])

    assert runs_hosts.kill_processes_by_name([DUMMY]) == runs_hosts.KillResult(found=0, killed=0, denied=0)


def test_the_daemon_end_line_carries_found_killed_and_denied(tmp_path, monkeypatch):
    _processes(monkeypatch, _three_matches_one_denied())
    modes = tmp_path / "modes.json"
    (tmp_path / "d1").mkdir()
    daemon, _, _ = make_daemon(tmp_path / "d1", launcher=FakeLauncher(), budget=BUDGET_NIGHT_10,
                               hosts_config=HOSTS)
    logs: list = []
    daemon.log = logs.append
    daemon._modes_file = modes
    daemon._process_killer = runs_hosts.kill_processes_by_name
    oc.start_preset("pc", "sleep", config={"pc": SLEEP_CONFIG}, modes_file=modes, reader=_reading, now=T0)

    daemon.timestamp = lambda: T0 + timedelta(minutes=121)
    daemon.owner_end_pass()

    assert f"sleep ended: found 3, killed 2, denied 1 process(es) of {DUMMY}" in logs
    assert runs_hosts.owner_record_raw("pc", modes_file=modes) is None
