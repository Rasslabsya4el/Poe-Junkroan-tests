"""#376, #388: the mode-touching tests never write the "real" var/modes.json.

The child pytest runs the mode test files with JUNKROAN_MODES_FILE removed from its env, so the conftest
autouse fixture is what protects the store. The "real" store the child resolves (`shared_var_dir()`) is
moved, by a `-p` plugin in the child only, to a private stand-in directory made by this test. The test
hashes the stand-in, never the owner's live var/modes.json: a live writer (the runs daemon, a
`runs.py mode` command) rewrites that file at any moment, and under the old whole-file hash of the live
path it turned this test red without any mode test writing anything. Nothing but the child can reach the
stand-in, so a change of it means a mode test wrote through the path the live store uses.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["tests/test_runs_mode_cli.py", "tests/test_runs_stop.py", "tests/test_runs_hosts.py",
         "tests/test_power_guard.py", "tests/test_hosts_install.py"]

_PLUGIN = '''\
import os
from pathlib import Path


def pytest_configure(config):
    from junkroan.pob import slot_budget
    slot_budget._shared_var = Path(os.environ["JUNKROAN_STANDIN_VAR"])
'''


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def run_children(tmp_path: Path, files: list[str] = FILES) -> tuple[subprocess.CompletedProcess, str, str]:
    """Run `files` in a child pytest whose shared var dir is a stand-in; return (child, before, after)."""

    standin = tmp_path / "standin_var"
    standin.mkdir(exist_ok=True)
    plug = tmp_path / "plug"
    plug.mkdir(exist_ok=True)
    (plug / "standin_plugin.py").write_text(_PLUGIN, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "JUNKROAN_MODES_FILE"}
    env["JUNKROAN_NO_POB"] = "1"
    env["JUNKROAN_STANDIN_VAR"] = str(standin)
    env["PYTHONPATH"] = os.pathsep.join([str(plug), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    before = _digest(standin / "modes.json")
    child = subprocess.run([sys.executable, "-m", "pytest", *files, "-q", "-p", "no:faulthandler",
                            "-p", "standin_plugin",
                            f"--basetemp={tmp_path / 'child_tmp'}"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    return child, before, _digest(standin / "modes.json")


def test_mode_tests_leave_the_real_store_untouched(tmp_path) -> None:
    child, before, after = run_children(tmp_path)
    assert child.returncode == 0, child.stdout[-3000:] + child.stderr[-1000:]
    assert after == before


def test_a_live_writer_does_not_turn_the_isolation_red(tmp_path) -> None:
    """A stand-in daemon rewrites a "live" store for the whole child run; the verdict does not move."""

    live = tmp_path / "live_modes.json"
    stop = threading.Event()

    def writer() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            live.write_text('{"host": {"mode": "x", "until": null, "n": %d}}' % n, encoding="utf-8")
            stop.wait(0.01)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        child, before, after = run_children(tmp_path, ["tests/test_runs_mode_cli.py"])
    finally:
        stop.set()
        thread.join(timeout=5)
    assert live.exists() and "n" in live.read_text(encoding="utf-8")
    assert child.returncode == 0, child.stdout[-3000:] + child.stderr[-1000:]
    assert after == before
