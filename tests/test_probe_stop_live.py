"""#258 row 5's parenthetical: a test of `scripts/probe_stop_live.py`'s own exit-code logic, no
real process touched -- `--force-mismatch` alone."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the probe is Windows-only")


def test_force_mismatch_exits_non_zero_without_touching_a_real_process():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "probe_stop_live.py"), "--force-mismatch"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0, result.stdout + result.stderr
