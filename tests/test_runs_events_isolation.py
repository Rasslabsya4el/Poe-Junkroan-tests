"""#138: the runs tests never append to the live artifacts/runs/events.jsonl.

Runs them in a child pytest with JUNKROAN_RUNS_EVENTS removed from its env, so the conftest autouse
fixture is what protects the live feed; the live file's prefix that existed before must be byte-identical
after (live daemons may append meanwhile, so only that prefix is compared).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from junkroan.runs import hosts

ROOT = Path(__file__).resolve().parents[1]
FILES = ["tests/test_runs_stop.py", "tests/test_runs_hosts.py", "tests/test_runs_anomalies.py",
         "tests/test_power_guard.py"]


def test_runs_tests_leave_the_live_feed_untouched(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JUNKROAN_RUNS_EVENTS", raising=False)
    live = hosts.events_path()
    before = live.read_bytes() if live.exists() else b""
    env = {k: v for k, v in os.environ.items() if k != "JUNKROAN_RUNS_EVENTS"}
    env["JUNKROAN_NO_POB"] = "1"
    child = subprocess.run([sys.executable, "-m", "pytest", *FILES, "-q", "-p", "no:faulthandler",
                            f"--basetemp={tmp_path / 'child_tmp'}"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert child.returncode == 0, child.stdout[-3000:] + child.stderr[-1000:]
    after = live.read_bytes() if live.exists() else b""
    assert after[:len(before)] == before
    assert hashlib.sha256(after[:len(before)]).hexdigest() == hashlib.sha256(before).hexdigest()
    new_lines = after[len(before):].decode("utf-8", "replace")
    for marker in ("echo x", "pytest-of-user", "wrong-host"):
        assert marker not in new_lines
