"""tools/agentops/detach.py (issue #399): a `--detach`ed merge survives the death of the process
tree that started it. Temp bare remote, temp lock, temp result dir and merge.log; never the real
`var/`, never `origin`. Nothing here starts PoB."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from tools.agentops import detach
from tests.test_agentops_merge import _git, _origin_main_head, _push_branch, _world

ROOT = Path(__file__).resolve().parents[1]
BOUND = 120.0  # a ceiling no load reaches; the waits below poll for an event


def _wait(predicate, what: str, bound: float = BOUND):
    deadline = time.time() + bound
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def test_runner_records_rc_and_reason_for_a_failing_command(tmp_path: Path):
    result = tmp_path / "r.json"
    log = tmp_path / "merge.log"
    cmd = [sys.executable, "-c", "print('not merged (red-suite): the suite failed (the output: X.txt)'); raise SystemExit(1)"]
    rc = detach.run_and_record(cmd, result, "merge", "feature-x", merge_log=log)
    assert rc == 1
    rec = json.loads(result.read_text(encoding="utf-8"))
    assert rec["rc"] == 1 and rec["reason"] == "red-suite" and rec["pushed_sha"] is None
    assert rec["suite_output"] == "X.txt" and rec["kind"] == "merge"
    assert f"| feature-x | detached result rc 1 | {result}" in log.read_text(encoding="utf-8")


def test_detached_merge_survives_a_tree_kill_of_its_starter(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    lock_path = tmp_path / "merge.lock"
    release = tmp_path / "release.flag"
    held = tmp_path / "held.flag"
    holder_code = (
        "import sys, time, pathlib\n"
        "from pathlib import Path\n"
        "from tools.agentops.merge import MergeLock\n"
        f"lock = MergeLock(Path(r'{lock_path}')); lock.acquire()\n"
        f"Path(r'{held}').write_text('1')\n"
        f"end = time.time() + {BOUND}\n"
        f"while time.time() < end and not Path(r'{release}').exists(): time.sleep(0.1)\n"
        "lock.release()\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", holder_code], cwd=str(ROOT))
    results = tmp_path / "results"
    env = {**os.environ, detach.ENV_RESULTS_DIR: str(results),
           detach.ENV_MERGE_LOG: str(tmp_path / "merge.log")}
    starter = None
    from tools.agentops import merge as merge_mod
    live = merge_mod.MERGE_LOG_PATH
    live_before = live.stat().st_size if live.exists() else None
    try:
        _wait(held.exists, "the holder's lock")
        starter = subprocess.Popen(
            [sys.executable, "-m", "tools.agentops", "merge", "origin/feature-a",
             "--suite", f'"{sys.executable}" -c "pass"', "--cwd", str(checkout),
             "--lock", str(lock_path), "--timeout", str(BOUND), "--detach"],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, text=True)
        out, _ = starter.communicate(timeout=60)
        assert starter.returncode == 0 and out.startswith("detached: result "), out
        # kill the starter's whole tree (it has already exited; kill whatever is left of it)
        try:
            for child in psutil.Process(starter.pid).children(recursive=True):
                child.kill()
        except psutil.NoSuchProcess:
            pass
        assert not list(results.glob("*.json")), "the merge cannot have finished behind the lock"
        release.write_text("go")
        holder.wait(timeout=60)
        found = _wait(lambda: list(results.glob("*-merge-origin_feature-a.json")), "the result file")
        rec = json.loads(found[0].read_text(encoding="utf-8"))
        assert rec["rc"] == 0, rec
        assert rec["pushed_sha"] == _origin_main_head(bare)
        assert rec["reason"] == "pushed" and rec["kind"] == "merge"
        mlog = tmp_path / "merge.log"
        _wait(lambda: mlog.exists() and "detached result rc 0" in mlog.read_text(encoding="utf-8"),
              "the merge.log line", bound=30)
        text = mlog.read_text(encoding="utf-8")
        assert "| origin/feature-a | pushed |" in text, text  # the inner merge's own line
        assert str(tmp_path) in text  # its suite output went under tmp_path too
        live_after = live.stat().st_size if live.exists() else None
        assert live_after == live_before, "the test wrote the live merge.log"
    finally:
        release.write_text("go")
        if holder.poll() is None:
            holder.kill()
