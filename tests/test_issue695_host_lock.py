"""#695: two suites sent to the laptop never share its suite worktree; FAKE transport only (never the live laptop, #457)."""

from __future__ import annotations

import base64
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("suite_on_host", ROOT / "scripts" / "suite_on_host.py")
soh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soh)

from tools.agentops import merge, suite_host, suite_router  # noqa: E402

SHA = "a" * 40
CONFIG = {"laptop": {"ssh": "laptop", "repo_path": "C:\\Coding\\repo", "daemon_repo_path": "C:\\Coding\\repo-daemon"}}


def done(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, out, err)


def decode(argv):
    return base64.b64decode(argv[-1]).decode("utf-16-le")


class Laptop:
    """The laptop's lock file as the remote scripts treat it: created only if absent, released only by its writer."""

    def __init__(self):
        self.lock = None          # {"info": "pc_pid=.. commit=..", "since": "T", "age_min": n}
        self.suites_started = []  # one entry per start script that got past the lock
        self.on_poll = None       # called once from inside the first poll (a second run starting meanwhile)
        self.start_raises = None
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if argv[0] == "git" and argv[1] == "rev-parse":
            return done(argv, 0, SHA + "\n")
        if argv[0] == "git":
            return done(argv, 0)
        if argv[0] == "scp":
            Path(argv[-1]).write_text("== 3 passed in 1.00s ==\n", encoding="utf-8")
            return done(argv)
        script = decode(argv)
        if "schtasks /Create" in script:
            info = re.search(r"\$info = '([^']*)'", script).group(1)
            lock_min = float(re.search(r"TotalMinutes -gt ([\d.]+)", script).group(1))
            out = ""
            if self.lock is not None:
                if self.lock["age_min"] > lock_min:
                    out = f"SUITE_LOCK=stale {self.lock['info']} start={self.lock['since']}\n"
                    self.lock = None
                else:
                    return done(argv, 76, f"SUITE_BUSY={self.lock['info']} start={self.lock['since']}\n")
            self.lock = {"info": info, "since": "2026-10-09T12:00:00", "age_min": 0}
            self.suites_started.append(info)
            if self.start_raises:
                raise self.start_raises
            return done(argv, 0, out + "SUITE_STARTED=1\n")
        if "SUITE_DONE" in script:
            hook, self.on_poll = self.on_poll, None
            if hook:
                hook()
            return done(argv, 0, "SUITE_DONE=0 60\n")
        mine = re.search(r"-like \('([^']*)' \+", script)  # cleanup
        if mine and self.lock and self.lock["info"] == mine.group(1):
            self.lock = None
        return done(argv)


@pytest.fixture
def laptop(monkeypatch):
    monkeypatch.setattr(soh, "POLL_EVERY_S", 0)
    lap = Laptop()
    monkeypatch.setattr(soh, "_run", lap)
    monkeypatch.setattr(soh, "load_hosts_config", lambda: CONFIG)
    return lap


def run(tmp_path, name, timeout="40"):
    return soh.main(["run", "--host", "laptop", "--commit", "HEAD", "--workers", "2", "--out", str(tmp_path / name),
                     "--timeout-min", timeout])


def test_start_script_takes_the_lock_before_touching_the_worktree(laptop, tmp_path):
    assert run(tmp_path, "o.txt") == 0
    script = next(decode(c) for c in laptop.calls if c[0] == "ssh" and "schtasks /Create" in decode(c))
    assert "'CreateNew'" in script and "C:\\Coding\\repo-suite.lock" in script
    assert script.index("CreateNew") < script.index("worktree add") < script.index("schtasks /Create")
    assert laptop.lock is None


def test_second_manual_run_is_refused_while_the_first_holds_the_lock(laptop, tmp_path, monkeypatch, capsys):
    second = {}

    def start_second():
        with monkeypatch.context() as mp:
            mp.setattr(soh.os, "getpid", lambda: 4242)
            second["rc"] = run(tmp_path, "second.txt")
    laptop.on_poll = start_second
    assert run(tmp_path, "first.txt") == 0
    assert second["rc"] == soh.EXIT_BUSY != soh.EXIT_UNREACHABLE
    out = capsys.readouterr().out
    assert "laptop busy (suite aaaaaaaa since 2026-10-09T12:00:00)" in out
    assert len(laptop.suites_started) == 1                   # one suite on the laptop
    assert (tmp_path / "first.txt").exists() and not (tmp_path / "second.txt").exists()
    assert laptop.lock is None                               # the refused run did not free the first's lock


def test_stale_lock_is_taken_over_and_the_line_says_so(laptop, tmp_path, capsys):
    laptop.lock = {"info": "pc_pid=1 commit=bbbbbbbb", "since": "2026-10-08T01:00:00", "age_min": 90}
    assert run(tmp_path, "o.txt", timeout="40") == 0
    out = capsys.readouterr().out
    assert "stale" in out and "bbbbbbbb" in out and "taken over" in out
    assert len(laptop.suites_started) == 1 and laptop.lock is None


def test_lock_is_gone_after_a_run_that_raises(laptop, tmp_path, capsys):
    laptop.start_raises = subprocess.TimeoutExpired(["ssh"], 180)
    assert run(tmp_path, "o.txt") == soh.EXIT_UNREACHABLE
    assert len(laptop.suites_started) == 1
    assert laptop.lock is None


# --- the merge router: busy laptop -> the suite runs on the PC, first line says why ---

class Rig:
    def __init__(self, tmp_path, monkeypatch):
        self.out = tmp_path / "suite.out"
        self.pc_runs = []
        self.laptop_runs = []
        monkeypatch.delenv("JUNKROAN_NO_LAPTOP_SUITE", raising=False)
        monkeypatch.setattr(suite_router, "route_enabled", lambda: True)
        monkeypatch.setattr(suite_router, "pc_readings",
                            lambda: {"logical_cores": 12, "cpu_percent": 95.0, "free_ram_gb": 3.0})
        monkeypatch.setattr(merge, "_git", lambda *a, **k: SimpleNamespace(stdout="abc123\n", returncode=0))
        monkeypatch.setattr(merge, "_default_restart", lambda *a, **k: None)
        monkeypatch.setattr(suite_host, "read_laptop",
                            lambda *a, **k: ({"logical_cores": 16, "cpu_percent": 5.0, "free_ram_gb": 20.0}, None))
        monkeypatch.setattr(merge, "_run_suite", self._pc)
        sys.path.insert(0, str(suite_host._ROOT / "scripts"))
        import suite_on_host
        self.soh = suite_on_host
        monkeypatch.setattr(suite_on_host, "run_suite", self._laptop)

    def _laptop(self, host, commit, workers, out, *a, **k):
        self.laptop_runs.append(commit)
        raise self.soh.HostBusy("suite 1234abcd since 2026-10-09T12:00:00")

    def _pc(self, cmd, cwd, env=None, output_path=None, head_line="", append=False, restart=None):
        self.pc_runs.append(head_line)
        return True, "pc full suite\n"


def test_router_runs_on_the_pc_with_the_busy_line_first(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    res = merge._run_merge_suite("pytest -n 1", "pytest", 1, "workers 1: pc busy", tmp_path, None, rig.out)
    lines = rig.out.read_text(encoding="utf-8").splitlines()
    assert any(ln == "host pc: laptop busy (suite 1234abcd since 2026-10-09T12:00:00)" for ln in lines)
    assert not any("laptop unreachable" in ln for ln in lines)
    assert len(rig.laptop_runs) == 1 and len(rig.pc_runs) == 1     # no second laptop suite
    assert res.ok and res.host == "pc"
