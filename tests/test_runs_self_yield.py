"""#403 (d): a filler never yields to its own benchmark process (fakes only, no PoB, no processes)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_runs_fillers as tf  # noqa: E402


def _setup(tmp_path):
    launcher = tf.FakeLauncher()
    daemon, store = tf.make_daemon(tmp_path, slots=tf.FakeSlots(), launcher=launcher)
    job_id = tf.running_filler(store, launcher, daemon)
    return daemon, int(store.get(job_id).pid)


def test_d_own_filler_benchmark_pid_is_never_foreign(tmp_path):
    daemon, pid = _setup(tmp_path)
    tree = {1000 + i: pid for i in range(5)}  # five workers, no job env, parent = the filler's pid
    daemon._parent_pid = lambda p: tree.get(p)
    rows = [{"pid": 1000 + i, "role": "queue"} for i in range(5)]
    assert daemon.foreign_heavy_owner(rows) is None


def test_d_real_foreign_heavy_process_still_is(tmp_path):
    daemon, pid = _setup(tmp_path)
    tree = {2000 + i: 7777 for i in range(5)}
    tree[1000] = pid
    daemon._parent_pid = lambda p: tree.get(p)
    rows = [{"pid": 2000 + i, "role": "other"} for i in range(5)] + [{"pid": 1000, "role": "queue"}]
    assert daemon.foreign_heavy_owner(rows) == "pid:7777"
