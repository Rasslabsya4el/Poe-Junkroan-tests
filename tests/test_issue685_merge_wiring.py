"""#685 unit 4: the merge suite's host choice wired into merge.py; fakes only, never the live laptop."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tools.agentops import merge, suite_host, suite_router

HEAD = "workers 1: pc busy"
LAPTOP_OK = {"logical_cores": 8, "cpu_percent": 0.0, "free_ram_gb": 20.0}
PC_BUSY = {"logical_cores": 12, "cpu_percent": 95.0, "free_ram_gb": 3.0}
PC_IDLE = {"logical_cores": 12, "cpu_percent": 0.0, "free_ram_gb": 30.0}


class Rig:
    def __init__(self, tmp_path, monkeypatch):
        self.out = tmp_path / "suite.out"
        self.read_laptop_calls = 0
        self.laptop_runs = []
        self.pc_runs = []
        self.rechecks = []
        self.laptop_rc = 0
        self.laptop_text = ""
        self.recheck_still: list[str] = []
        self.laptop_reading = (LAPTOP_OK, None)
        self.pc = PC_BUSY
        monkeypatch.delenv("JUNKROAN_NO_LAPTOP_SUITE", raising=False)
        # these tests state the night (cap 6) host rule; the day cap 3 is #839's own test
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
        monkeypatch.setattr(suite_router, "route_enabled", lambda: True)
        monkeypatch.setattr(suite_router, "pc_readings", lambda: self.pc)
        monkeypatch.setattr(merge, "_git", lambda *a, **k: SimpleNamespace(stdout="abc123\n", returncode=0))
        monkeypatch.setattr(merge, "_default_restart", lambda *a, **k: None)
        monkeypatch.setattr(suite_host, "read_laptop", self._read_laptop)
        monkeypatch.setattr(merge, "_run_suite", self._run_suite)
        monkeypatch.setattr(merge, "_recheck_failed", self._recheck)
        sys.path.insert(0, str(suite_host._ROOT / "scripts"))
        import suite_on_host
        monkeypatch.setattr(suite_on_host, "run_suite", self._laptop)

    def _read_laptop(self, *a, **k):
        self.read_laptop_calls += 1
        return self.laptop_reading

    def _laptop(self, host, commit, workers, out, *a, **k):
        self.laptop_runs.append((host, commit, workers))
        if isinstance(self.laptop_rc, Exception):
            raise self.laptop_rc
        out.write_text(self.laptop_text, encoding="utf-8")
        return self.laptop_rc

    def _run_suite(self, cmd, cwd, env=None, output_path=None, head_line="", append=False, restart=None, stall=None):
        self.pc_runs.append((cmd, head_line, append))
        return True, "pc full suite\n"

    def _recheck(self, suite_cmd, ids, suite_dir, env, output_path):
        self.rechecks.append(list(ids))
        return list(self.recheck_still), "recheck out\n"

    def run(self, tmp_path):
        return merge._run_merge_suite("pytest -n 1", "pytest", 1, HEAD, tmp_path, None, self.out)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch)


MIXED = ("FAILED tests/a.py::t1 - x\nFAILED tests/a.py::t2 - x\nERROR tests/b.py::t3 - y\n"
         "________ ERROR collecting tests/c.py ________\n2 failed, 1 error\n")


def test_laptop_candidates_go_to_the_pc_recheck_and_all_pass_is_green(rig, tmp_path):
    rig.laptop_rc, rig.laptop_text = 1, MIXED
    run = rig.run(tmp_path)
    assert rig.rechecks == [["tests/a.py::t1", "tests/a.py::t2", "tests/b.py::t3", "tests/c.py"]]
    assert run.ok and run.host == "laptop" and run.rechecked_done and not rig.pc_runs
    result = merge.MergeResult(ok=True, reason="pushed", suite_workers=run.workers, suite_host=run.host,
                               rechecked=run.red_ids, recheck_note=run.recheck_note)
    log = tmp_path / "m.log"
    merge._append_merge_log("b", result, log_path=log)
    line = log.read_text(encoding="utf-8")
    assert "0 failed after re-check of 4 (laptop)" in line and "host laptop" in line
    assert rig.out.read_text(encoding="utf-8").startswith("host laptop: workers")


def test_one_candidate_still_failing_on_the_pc_is_red(rig, tmp_path):
    rig.laptop_rc, rig.laptop_text = 1, MIXED
    rig.recheck_still = ["tests/b.py::t3"]
    run = rig.run(tmp_path)
    assert not run.ok and run.still == ["tests/b.py::t3"] and len(run.red_ids) == 4 and not rig.pc_runs


def test_41_candidates_run_the_full_suite_on_the_pc(rig, tmp_path):
    rig.laptop_rc = 1
    rig.laptop_text = "".join(f"FAILED tests/x.py::t{i} - x\n" for i in range(41))
    run = rig.run(tmp_path)
    assert rig.rechecks == [] and len(rig.pc_runs) == 1 and run.host == "pc" and run.ok
    assert "41 candidates > 40" in rig.out.read_text(encoding="utf-8")


def test_transport_failure_rc_75_falls_back_to_the_pc(rig, tmp_path):
    rig.laptop_rc = 75
    run = rig.run(tmp_path)
    assert len(rig.pc_runs) == 1 and rig.pc_runs[0][2] is True and run.host == "pc"
    assert "laptop unreachable (rc 75), full suite on the PC" in rig.out.read_text(encoding="utf-8")


def test_exception_falls_back_to_the_pc(rig, tmp_path):
    rig.laptop_rc = RuntimeError("ssh boom")
    run = rig.run(tmp_path)
    assert len(rig.pc_runs) == 1 and "ssh boom" in rig.out.read_text(encoding="utf-8") and run.ok


def test_laptop_green_does_not_run_the_pc_suite(rig, tmp_path):
    rig.laptop_rc, rig.laptop_text = 0, "4000 passed\n"
    run = rig.run(tmp_path)
    assert run.ok and run.host == "laptop" and not rig.pc_runs and not rig.rechecks
    assert rig.laptop_runs[0][0] == "laptop" and rig.laptop_runs[0][1] == "abc123"


def test_host_pc_runs_the_pc_suite_with_the_choice_line(rig, tmp_path):
    rig.pc = PC_IDLE
    run = rig.run(tmp_path)
    assert rig.laptop_runs == [] and run.host == "pc" and len(rig.pc_runs) == 1
    head = rig.pc_runs[0][1]
    last = head.splitlines()[-1]
    # the workers line stays LAST (the #687 restart watcher reads the last line), the host line before it
    assert last == HEAD and "host pc:" in head.splitlines()[-2] and merge._WORKERS_LINE_RE.match(last)


def test_route_off_never_reads_the_laptop(rig, tmp_path, monkeypatch):
    monkeypatch.undo()  # drop all patches, then re-install what the check needs
    monkeypatch.setenv("JUNKROAN_NO_LAPTOP_SUITE", "1")
    calls = []
    monkeypatch.setattr(suite_host, "read_laptop", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(merge, "_run_suite", lambda *a, **k: (True, "pc\n"))
    run = merge._run_merge_suite("pytest", "pytest", 1, HEAD, tmp_path, None, tmp_path / "o")
    assert run.ok and run.host == "" and calls == []


def test_route_off_by_settings_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JUNKROAN_NO_LAPTOP_SUITE", raising=False)
    import tools.agentops.core_settings as cs
    monkeypatch.setattr(cs, "load", lambda *a, **k: {"merge_suite_laptop": False})
    assert suite_router.route_enabled() is False
    monkeypatch.setattr(cs, "load", lambda *a, **k: {"merge_suite_laptop": True})
    assert suite_router.route_enabled() is True
    monkeypatch.setenv("JUNKROAN_NO_LAPTOP_SUITE", "1")
    assert suite_router.route_enabled() is False


def test_a_selected_subset_is_never_routed_to_the_laptop(rig, tmp_path):
    run = merge._run_merge_suite("cmd", "suite", 1, "selected 3 of 4000 (map abc12345)\n" + HEAD,
                                 tmp_path, {}, rig.out, routed_ok=False)
    assert rig.read_laptop_calls == 0 and rig.laptop_runs == [] and run.host == ""
