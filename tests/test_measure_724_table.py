"""scripts/measure_724_table.py and the driver's dry plan (#724 unit 1b). No PoB."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_table_selftest() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/measure_724_table.py"), "--selftest"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "selftest ok" in r.stdout


def test_driver_dry_plan_busy_has_two_loaders() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/measure_724.py"), "--case", "kick-joint-busy", "--dry"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("loader:") == 2 and "--move kick-joint" in r.stdout and "winter_orb-s1" in r.stdout
    idle = subprocess.run([sys.executable, str(ROOT / "scripts/measure_724.py"), "--case", "jewel-idle", "--dry"],
                          capture_output=True, text=True)
    assert "loader:" not in idle.stdout and "--move jewel" in idle.stdout
