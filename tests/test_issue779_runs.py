"""#779 unit 5, row 11: runs.py mode pc play|normal writes the machine mode; the daemon obeys a machine play
written from another clone within one tick. AGENTOPS_MACHINE_DIR = tmp_path; nothing is suspended, no PoB."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import runs as runs_cli  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from tests.test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402
from tools.agentops import hold, machine_mode  # noqa: E402
from junkroan.runs import machine_hold  # noqa: E402


@pytest.fixture()
def mdir(tmp_path, monkeypatch):
    d = tmp_path / "machine"
    monkeypatch.setenv("AGENTOPS_MACHINE_DIR", str(d))
    return d


def _fake_apply(monkeypatch):
    monkeypatch.setattr(runs_hosts, "apply_mode", lambda host, mode, local=False: {"priority": "Normal", "transport": "local"})
    monkeypatch.setattr(runs_hosts, "record_mode", lambda host, mode: None)


def test_mode_command_writes_machine_mode(tmp_path, mdir, monkeypatch):
    _fake_apply(monkeypatch)
    store = make_daemon(tmp_path)[1]
    assert runs_cli.cmd_mode(store, ["pc", "play", "--local"]) == 0
    assert machine_mode.current_mode() == "play"
    assert runs_cli.cmd_mode(store, ["pc", "normal", "--local"]) == 0
    assert machine_mode.current_mode() == "normal"
    assert runs_cli.cmd_mode(store, ["pc", "play", "--local"]) == 0
    for other in ("pause", "off"):  # never touched by pause / off
        runs_cli.cmd_mode(store, ["pc", other, "--local"])
        assert machine_mode.current_mode() == "play"
    machine_mode.set_mode("normal")
    runs_cli.cmd_mode(store, ["laptop", "play", "--local"])  # the laptop's modes never write it
    assert machine_mode.current_mode() == "normal"


def test_expired_timed_play_sets_machine_normal(tmp_path, mdir, monkeypatch):
    from junkroan.runs import hosts
    monkeypatch.setattr(hosts, "modes_path", lambda: tmp_path / "modes.json")
    monkeypatch.setattr(hosts, "apply_mode", lambda *a, **k: {})
    now = datetime(2026, 10, 11, 12, 0)
    (tmp_path / "modes.json").write_text(json.dumps(
        {"pc": {"mode": "play", "until": (now - timedelta(minutes=1)).isoformat()}}), encoding="utf-8")
    machine_mode.set_mode("play")
    assert hosts.revert_expired_modes(now) == ["pc"]
    assert machine_mode.current_mode() == "normal"


def _rig(tmp_path, holds):
    daemon, store, _ = make_daemon(tmp_path, launcher=FakeLauncher())
    daemon._machine_hold = True
    daemon._hold_root = tmp_path / "root"
    daemon._hold_pass = lambda mode: holds.append(mode)
    store.submit(host="pc", priority="P1", tag="a", cmd="python scripts/x.py", workers=1)
    return daemon, store


def test_machine_play_from_another_clone_holds_daemon(tmp_path, mdir):
    holds: list[str] = []
    daemon, store = _rig(tmp_path, holds)
    mdir.mkdir(parents=True)
    # written directly, as another clone would
    (mdir / "machine_mode.json").write_text(
        json.dumps({"mode": "play", "since": datetime(2026, 10, 11).isoformat()}), encoding="utf-8")
    started = [daemon.tick().started for _ in range(5)]
    assert started == [[]] * 5
    assert holds == ["play"] * 5
    (mdir / "machine_mode.json").write_text(
        json.dumps({"mode": "normal", "since": datetime(2026, 10, 11).isoformat()}), encoding="utf-8")
    assert len(daemon.tick().started) == 1
    assert holds[-1] == "normal"


def test_unreadable_machine_mode_starts_nothing(tmp_path, mdir):
    daemon, store = _rig(tmp_path, [])
    mdir.mkdir(parents=True)
    (mdir / "machine_mode.json").write_text("{not json", encoding="utf-8")
    assert daemon.tick().started == []


def test_daemon_job_pids_are_hold_targets(tmp_path):
    class Table:
        def create_time(self, pid): return 1.0
        def children(self, pid): return {500: [501]}.get(pid, [])
        def parent(self, pid): return None
        def cmdline(self, pid): return ""
        def all_pids(self): return []
    machine_hold.write_daemon_job_pids(tmp_path, [500])
    got = hold.targets(tmp_path, table=Table(), sessions=[], caller=1)
    assert sorted(p for p, _ in got) == [500, 501]
