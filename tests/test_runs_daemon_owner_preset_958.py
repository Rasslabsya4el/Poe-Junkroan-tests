"""#958 unit 3b: the daemon side of the owner presets. The end of "sleep" closes the browsers exactly 1 time,
"film" 0 times, `back` 0 times. Fake clock, fake launcher, a fake process killer that records its calls."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import owner_commands as oc  # noqa: E402
from tests.test_runs_daemon import (  # noqa: E402,F401
    BUDGET_NIGHT_10, FakeLauncher, _isolated_daemon_status, make_daemon,
)

T0 = datetime(2026, 10, 13, 22, 0, 0)
FIVE = ["chrome", "msedge", "firefox", "opera", "brave"]
HOSTS = {"pc": {"modes": {"night": {"pob_priority": "BelowNormal"}}}}
CONFIG = {"laptop": {"owner_presets": {
    "film": {"need_cpu_cores": 1.5, "need_ram_mb": 2500},
    "sleep": {"need_cpu_cores": 1.5, "need_ram_mb": 2500, "for": "2h", "on_end": "close-browsers", "close": FIVE},
}}}


def _reading():
    return oc.Reading(idle_cores=0.2, free_ram_mb=800, workers=[oc.Worker(1.0, 900)] * 3)


def _wire(daemon, modes, clock, killed, logs):
    daemon.timestamp = lambda: clock["now"]
    daemon._modes_file = modes
    daemon._yield_root = modes.parent / "root"
    daemon._pid_finder = lambda: []
    daemon._priority_setter = lambda pids, prio: None
    daemon._process_killer = lambda names: killed.append(list(names)) or runs_hosts.KillResult(
        found=len(names), killed=len(names))
    daemon.log = logs.append
    # the production wiring: `scripts/runs.py daemon` passes revert_expired_modes (it drops a lapsed film record)
    daemon.revert_modes = lambda: runs_hosts.revert_expired_modes(
        clock["now"], modes_file=modes, events_file=modes.parent / "ev.jsonl")
    return daemon


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    modes = tmp_path / "modes.json"
    ssh_calls: list = []
    monkeypatch.setattr(runs_hosts, "run_on_host", lambda *a, **k: ssh_calls.append(a))
    (tmp_path / "d1").mkdir()
    daemon, store, _ = make_daemon(tmp_path / "d1", launcher=FakeLauncher(), budget=BUDGET_NIGHT_10,
                                   hosts_config=HOSTS)
    clock = {"now": T0}
    killed: list = []
    logs: list = []
    _wire(daemon, modes, clock, killed, logs)
    return SimpleRig(daemon, modes, clock, killed, logs, ssh_calls, tmp_path)


class SimpleRig:
    def __init__(self, daemon, modes, clock, killed, logs, ssh_calls, tmp_path):
        self.daemon, self.modes, self.clock = daemon, modes, clock
        self.killed, self.logs, self.ssh_calls, self.tmp_path = killed, logs, ssh_calls, tmp_path

    def start(self, name, duration_text=None):
        # the daemon's own host is "pc" in this rig; the preset is written for it
        return oc.start_preset("pc", name, config={"pc": CONFIG["laptop"]}, modes_file=self.modes,
                               reader=_reading, now=self.clock["now"], duration_text=duration_text)

    def at(self, minutes):
        self.clock["now"] = T0 + timedelta(minutes=minutes)

    def ticks(self, n=1):
        for _ in range(n):
            self.daemon.tick()

    @property
    def total(self):
        return self.daemon.budget().total


def test_row22_film_lapses_total_back_and_the_killer_is_never_called(rig):
    rig.start("film", "120m")
    rig.ticks()
    assert rig.total == 8  # 10 - the 2 that give way
    rig.at(121)
    rig.ticks()
    assert rig.total == 10
    assert rig.killed == []
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None


def test_row24_sleep_lapses_closes_exactly_once_with_the_five_names_and_asks_no_ssh(rig):
    rig.start("sleep")
    rig.ticks()
    assert rig.total == 8 and rig.killed == []
    rig.at(121)
    rig.ticks(3)
    assert rig.killed == [FIVE]
    assert rig.total == 10
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None
    assert rig.ssh_calls == []


def test_sleep_does_not_close_before_its_end(rig):
    rig.start("sleep")
    for minute in (0, 30, 60, 119):
        rig.at(minute)
        rig.ticks()
    assert rig.killed == []


def test_row25_back_then_the_clock_runs_past_the_end_closes_nothing(rig):
    rig.start("sleep")
    rig.at(0)
    rig.ticks()
    rig.at(30)
    oc.end_preset("pc", modes_file=rig.modes)
    rig.ticks()
    assert rig.total == 10  # from the tick after back
    rig.at(121)
    rig.ticks(3)
    assert rig.killed == []


def test_row27_a_daemon_rebuilt_from_disk_still_closes_exactly_once(rig):
    rig.start("sleep")
    rig.ticks()
    rig.at(60)
    second_dir = rig.tmp_path / "d2"
    second_dir.mkdir()
    second, _, _ = make_daemon(second_dir, launcher=FakeLauncher(), budget=BUDGET_NIGHT_10, hosts_config=HOSTS)
    killed2: list = []
    _wire(second, rig.modes, rig.clock, killed2, [])
    second.tick()
    assert killed2 == []
    rig.at(121)
    second.tick()
    second.tick()
    assert killed2 == [FIVE] and rig.killed == []


def test_row28_a_killer_that_raises_still_drops_the_record_logs_once_and_the_daemon_goes_on(rig):
    def boom(names):
        raise PermissionError("access denied")

    rig.daemon._process_killer = boom
    rig.start("sleep")
    rig.ticks()
    rig.at(121)
    rig.ticks(3)
    assert rig.total == 10
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is None
    failures = [line for line in rig.logs if "failed" in line and "access denied" in line]
    assert len(failures) == 1


def test_a_close_override_reaches_the_killer(rig):
    oc.start_preset("pc", "sleep", config={"pc": CONFIG["laptop"]}, modes_file=rig.modes, reader=_reading,
                    now=T0, close=["dummy_probe"])
    rig.at(121)
    rig.ticks()
    assert rig.killed == [["dummy_probe"]]


def test_a_new_record_written_between_the_read_and_the_drop_is_not_dropped(rig):
    rig.start("sleep")
    record = runs_hosts.owner_record_raw("pc", modes_file=rig.modes)
    rig.at(121)
    rig.start("film", "120m")  # replaces the lapsed record before the end pass drops the old one
    assert runs_hosts.release_owner_reservation(
        "pc", modes_file=rig.modes, only_until=record["reserved_until"]) is False
    assert json.loads(rig.modes.read_text(encoding="utf-8"))["pc"]["preset"] == "film"


def test_the_monitors_revert_does_not_drop_a_lapsed_close_record_before_the_daemon_closes(rig):
    rig.start("sleep")
    runs_hosts.revert_expired_modes(T0 + timedelta(minutes=121), modes_file=rig.modes,
                                    events_file=rig.tmp_path / "ev.jsonl")
    assert runs_hosts.owner_record_raw("pc", modes_file=rig.modes) is not None
    rig.at(121)
    rig.ticks()
    assert rig.killed == [FIVE]
