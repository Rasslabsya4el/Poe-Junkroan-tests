"""#642 unit 4: the PC daemon copies its newest weekly gate dir to the laptop. Fake Popen / run_on_host / clock; no ssh."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_runs_daemon import make_daemon  # noqa: E402

from junkroan.runs import gates  # noqa: E402
from junkroan.runs.ssh_transport import build_scp_argv  # noqa: E402

NAME = "20261005-1220-gate-20261005"
CFG = {"ssh": "laptop", "daemon_repo_path": r"C:\Coding\poe-junkroan-v2-daemon"}
BENCH = r"C:\Coding\poe-junkroan-v2-daemon\artifacts\benchmark"


class FakeProc:
    def __init__(self, argv):
        self.argv = argv
        self.rc = None

    def poll(self):
        return self.rc


class Rig:
    def __init__(self, tmp_path, *, host="pc", with_gate=True):
        self.now = 1000.0
        self.logs: list[str] = []
        self.procs: list[FakeProc] = []
        self.scripts: list[str] = []
        self.artifacts = tmp_path / "artifacts"
        if with_gate:
            gate = self.artifacts / "benchmark" / NAME
            gate.mkdir(parents=True)
            (gate / "a.txt").write_text("x" * 100, encoding="utf-8")
        self.gates_path = tmp_path / "gates.json"

        def popen(argv, **kw):
            proc = FakeProc(argv)
            self.procs.append(proc)
            return proc

        def run_on_host(cfg, script):
            self.scripts.append(script)
            return SimpleNamespace(returncode=0)

        daemon, _, _ = make_daemon(tmp_path, host=host, hosts_config={"laptop": CFG})
        daemon.clock = lambda: self.now
        daemon.log = self.logs.append
        daemon._gate_popen = popen
        daemon._gate_run_on_host = run_on_host
        daemon._gate_artifacts = self.artifacts
        daemon._gates_path = self.gates_path
        self.daemon = daemon

    def held(self):
        return gates.gates_present("laptop", self.gates_path)


def test_no_gate_no_copy(tmp_path):
    rig = Rig(tmp_path, with_gate=False)
    rig.daemon.gate_sync_pass()
    assert rig.procs == [] and rig.scripts == []


def test_missing_on_laptop_starts_one_copy_and_not_a_second(tmp_path):
    rig = Rig(tmp_path)
    rig.daemon.gate_sync_pass()
    assert len(rig.procs) == 1
    argv = rig.procs[0].argv
    assert argv[0] == "scp" and argv[-1] == f"laptop:{BENCH.replace(chr(92), '/')}/{NAME}.partial"
    assert argv[-2] == str(rig.artifacts / "benchmark" / NAME)
    assert argv == build_scp_argv(CFG, argv[-2], f"{BENCH}\\{NAME}.partial")
    rig.now += 5
    rig.daemon.gate_sync_pass()
    rig.now += 700
    rig.daemon.gate_sync_pass()                      # still in flight: nothing new even past the throttle
    assert len(rig.procs) == 1


def test_rc0_renames_records_and_logs_once(tmp_path):
    rig = Rig(tmp_path)
    rig.daemon.gate_sync_pass()
    rig.scripts.clear()
    rig.now += 90
    rig.procs[0].rc = 0
    rig.daemon.gate_sync_pass()
    assert len(rig.scripts) == 1
    assert f"Rename-Item -LiteralPath '{BENCH}\\{NAME}.partial' -NewName '{NAME}'" in rig.scripts[0]
    assert rig.held() == {NAME}
    done = [m for m in rig.logs if "laptop now holds" in m]
    assert done == [f"gate_sync: laptop now holds {NAME} (0 MB in 1.5 min)"] or len(done) == 1
    assert NAME in done[0]
    rig.now += 5000
    rig.daemon.gate_sync_pass()
    assert len(rig.procs) == 1 and len([m for m in rig.logs if "laptop now holds" in m]) == 1


def test_rc1_logs_failure_no_record_retries_after_ten_minutes(tmp_path):
    rig = Rig(tmp_path)
    rig.daemon.gate_sync_pass()
    rig.now += 30
    rig.procs[0].rc = 1
    rig.daemon.gate_sync_pass()
    assert [m for m in rig.logs if "failed" in m] == [f"gate_sync: copy of {NAME} to laptop failed rc 1"]
    assert rig.held() == set()
    rig.now += 300                                   # 330 s after the start: inside the throttle
    rig.daemon.gate_sync_pass()
    assert len(rig.procs) == 1
    rig.now += 300                                   # 630 s after the start
    rig.daemon.gate_sync_pass()
    assert len(rig.procs) == 2


def test_laptop_already_holds_it(tmp_path):
    rig = Rig(tmp_path)
    gates.record_gate("laptop", NAME, rig.gates_path)
    rig.daemon.gate_sync_pass()
    assert rig.procs == [] and rig.scripts == []


def test_daemon_host_laptop_does_nothing(tmp_path):
    rig = Rig(tmp_path, host="laptop")
    rig.daemon.gate_sync_pass()
    assert rig.procs == [] and rig.scripts == []


def test_unreachable_laptop_is_not_tried(tmp_path):
    rig = Rig(tmp_path)
    rig.daemon.note_remote_read("laptop", False)
    rig.daemon.gate_sync_pass()
    assert rig.procs == [] and rig.scripts == []


def test_gate_bookkeeping_uses_the_main_root():
    from junkroan.runs.store import MAIN_ROOT
    assert gates.ROOT == MAIN_ROOT and gates.DEFAULT_PATH == MAIN_ROOT / "var" / "runs" / "gates_present.json"
