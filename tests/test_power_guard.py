"""tools/hosts/laptop/power-guard.ps1 (#367): battery -> mode off, mains -> the remembered mode back.

Runs the real script one tick at a time (-Tick) with a fake runs.py, a tmp repo root, a fake power state
and a fake clock. No real runs.py, no real machine.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "hosts" / "laptop" / "power-guard.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe is not on PATH (Windows-only script)")

FAKE_RUNS = r'''
import os
import sys
from pathlib import Path
here = Path(__file__).parent
args = sys.argv[1:]
with open(here / "calls.txt", "a") as f:
    f.write(" ".join(args) + chr(10))
with open(here / "hosts.txt", "a") as f:
    f.write(" ".join(args) + " | " + os.environ.get("JUNKROAN_HOST", "") + chr(10))
if (here / "fail_off.txt").exists() and args[:3] == ["mode", "laptop", "off"]:
    sys.stderr.write("cannot stop on laptop: this machine reads as pc; pass --local or set JUNKROAN_HOST" + chr(10))
    sys.exit(1)
if args == ["mode", "laptop", "--current"]:
    print((here / "mode.txt").read_text().strip())
elif args[:3] == ["mode", "laptop", "off"]:
    print("job-a -> failed (stopped by power-guard)")
    print("job-b -> failed (stopped by power-guard)")
    print("laptop: stopped 2 running job(s)")
'''


class Rig:
    def __init__(self, tmp: Path, mode: str):
        self.tmp = tmp
        self.runs = tmp / "artifacts" / "runs"
        self.runs.mkdir(parents=True)
        (tmp / "runs.py").write_text(FAKE_RUNS)
        (tmp / "mode.txt").write_text(mode)

    def tick(self, power: str, now: str) -> None:
        r = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Tick",
             "-Repo", str(self.tmp), "-Launcher", sys.executable, "-LauncherArg", "",
             "-RunsPy", str(self.tmp / "runs.py"), "-Power", power, "-Now", now],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, r.stdout + r.stderr

    def calls(self) -> list[str]:
        f = self.tmp / "calls.txt"
        lines = f.read_text().splitlines() if f.exists() else []
        return [c for c in lines if c != "mode laptop --current"]

    def log(self) -> list[str]:
        f = self.runs / "power-guard.log"
        return f.read_text(encoding="utf-8-sig").splitlines() if f.exists() else []

    @property
    def marker(self) -> Path:
        return self.runs / "power-guard.mode"

    def battery_2min(self) -> None:
        self.tick("battery", "2026-10-01 10:00:00")
        self.tick("battery", "2026-10-01 10:02:00")


def test_battery_two_minutes_sets_off_once_and_remembers_the_mode(tmp_path):
    rig = Rig(tmp_path, "normal")
    rig.tick("battery", "2026-10-01 10:00:00")
    assert rig.calls() == []
    rig.tick("battery", "2026-10-01 10:01:00")
    assert rig.calls() == []
    rig.tick("battery", "2026-10-01 10:02:00")
    assert rig.calls() == ["mode laptop off --local --who power-guard"]
    assert rig.marker.read_text().strip() == "normal"
    assert rig.log() == ["2026-10-01 10:02:00 on battery 2 min; mode normal -> off; stopped job-a, job-b"]
    rig.tick("battery", "2026-10-01 10:03:00")
    assert len(rig.calls()) == 1


def test_mains_restores_the_remembered_mode(tmp_path):
    rig = Rig(tmp_path, "night")
    rig.battery_2min()
    (tmp_path / "mode.txt").write_text("off")
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls() == ["mode laptop off --local --who power-guard", "mode laptop night --local"]
    assert not rig.marker.exists()
    assert rig.log()[-1] == "2026-10-01 10:30:00 mains back; mode off -> night"


def test_mains_with_a_mode_changed_by_hand_leaves_it(tmp_path):
    rig = Rig(tmp_path, "normal")
    rig.battery_2min()
    (tmp_path / "mode.txt").write_text("day")
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls() == ["mode laptop off --local --who power-guard"]
    assert not rig.marker.exists()
    assert rig.log()[-1] == "2026-10-01 10:30:00 mains back; mode changed by hand to day, left"


def test_mode_already_off_at_the_battery_event_does_nothing(tmp_path):
    rig = Rig(tmp_path, "off")
    rig.battery_2min()
    assert rig.calls() == []
    assert not rig.marker.exists()
    assert rig.log() == []
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls() == []
    assert rig.log() == ["2026-10-01 10:30:00 mains back; nothing to do"]


def test_mains_with_no_marker_says_nothing_to_do(tmp_path):
    rig = Rig(tmp_path, "normal")
    rig.tick("battery", "2026-10-01 10:00:00")
    rig.tick("mains", "2026-10-01 10:01:00")
    assert rig.calls() == []
    assert rig.log() == ["2026-10-01 10:01:00 mains back; nothing to do"]


def test_the_off_call_runs_with_the_laptop_host_env(tmp_path):
    rig = Rig(tmp_path, "normal")
    rig.battery_2min()
    hosts = (tmp_path / "hosts.txt").read_text().splitlines()
    assert "mode laptop off --local --who power-guard | laptop" in hosts


def test_a_failed_stop_is_logged_and_the_mode_is_still_restored_on_mains(tmp_path):
    rig = Rig(tmp_path, "night")
    (tmp_path / "fail_off.txt").write_text("1")
    rig.battery_2min()
    log = rig.log()
    assert len(log) == 1
    assert log[0].startswith("2026-10-01 10:02:00 on battery 2 min; mode night -> off; stop failed: cannot stop on laptop: ")
    assert "stopped none" not in log[0]
    assert rig.marker.read_text().strip() == "night"
    (tmp_path / "mode.txt").write_text("off")
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls()[-1] == "mode laptop night --local"
    assert not rig.marker.exists()


def test_mains_restores_browser_not_normal(tmp_path):
    rig = Rig(tmp_path, "browser")
    rig.battery_2min()
    assert rig.calls() == ["mode laptop off --local --who power-guard"]
    assert rig.marker.read_text().strip() == "browser"
    (tmp_path / "mode.txt").write_text("off")
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls() == ["mode laptop off --local --who power-guard", "mode laptop browser --local"]


@pytest.mark.parametrize("answer", ["unknown", ""])
def test_unknown_mode_goes_off_and_is_left_off_on_mains(tmp_path, answer):
    rig = Rig(tmp_path, answer)
    rig.battery_2min()
    assert rig.calls() == ["mode laptop off --local --who power-guard"]
    assert rig.marker.read_text().strip() == "unknown"
    (tmp_path / "mode.txt").write_text("off")
    rig.tick("mains", "2026-10-01 10:30:00")
    assert rig.calls() == ["mode laptop off --local --who power-guard"]
    assert rig.log()[-1] == "2026-10-01 10:30:00 mains back; mode before was unknown, left off"
    assert not rig.marker.exists()


def test_script_text_carries_none_of_the_retired_names():
    text = SCRIPT.read_text(encoding="utf-8")
    for word in ("queue.txt", "queue.log", "run_queue.py", "benchmark.py", "spawn_main"):
        assert word not in text, word
