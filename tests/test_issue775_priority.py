"""#775 unit 3: the full run's pytest tree runs at Normal, and at BELOW_NORMAL only while a merge suite runs.

No PoB, no real long run: a fake process tree (psutil-shaped stubs) and one real two-process stub."""
import os
import sys
import threading
import time

import psutil
import pytest

from junkroan.runs import load_groups
from tools.agentops import full_run

NORMAL = psutil.NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
BELOW = psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10
IDLE = psutil.IDLE_PRIORITY_CLASS if os.name == "nt" else 19


@pytest.fixture(autouse=True)
def _night(monkeypatch):
    # #839: by day the full run's tree is BELOW_NORMAL always; these tests state the night rule.
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")


class FakeProc:
    def __init__(self, cls):
        self.cls = cls

    def nice(self, value=None):
        if value is None:
            return self.cls
        self.cls = value


def _watcher(tree, state):
    return full_run.TreePriorityWatcher(0.02, signal=lambda: state["suite"], tree=lambda: list(tree))


def test_a_no_merge_suite_the_tree_is_normal():
    tree = [FakeProc(BELOW), FakeProc(BELOW), FakeProc(NORMAL)]  # spawned below (inherited) or normal
    _watcher(tree, {"suite": False}).step()
    assert [p.cls for p in tree] == [NORMAL] * 3


def test_a_real_tree_is_normal_with_no_merge_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(full_run, "merge_suite_running", lambda: False)
    monkeypatch.setattr(full_run, "WATCH_POLL_S", 0.05)
    seen = tmp_path / "seen.txt"
    script = tmp_path / "stub.py"
    script.write_text(
        "import subprocess, sys, time, os\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        f"open(r'{seen}', 'w').write(f'{{os.getpid()}} {{c.pid}}')\n"
        "time.sleep(20)\n")
    me = psutil.Process()
    before = me.nice()
    result = {}
    t = threading.Thread(target=lambda: result.update(r=full_run.run_suite_by_merge_state(
        f'"{sys.executable}" "{script}"', tmp_path, {}, tmp_path / "o.out", "")), daemon=True)
    t.start()
    pids = []
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not seen.exists():
            time.sleep(0.1)
        assert seen.exists()
        pids = [int(x) for x in seen.read_text().split()]
        time.sleep(0.5)  # a few polls
        root = psutil.Process(pids[0])
        procs = [root] + root.children(recursive=True) + [psutil.Process(pids[1])]
        classes = {p.pid: p.nice() for p in procs}
        assert all(v == NORMAL for v in classes.values()), classes
        assert me.nice() == before  # the full run's own process is never touched
    finally:
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass
        t.join(10)


def test_b_while_a_merge_suite_runs_below_normal_then_back_to_normal():
    tree = [FakeProc(NORMAL), FakeProc(NORMAL)]
    state = {"suite": True}
    w = _watcher(tree, state)
    w.step()
    assert [p.cls for p in tree] == [BELOW, BELOW]
    tree.append(FakeProc(NORMAL))  # an xdist worker started later, inherits Normal
    w.step()
    assert [p.cls for p in tree] == [BELOW] * 3
    state["suite"] = False
    w.step()
    assert [p.cls for p in tree] == [NORMAL] * 3


def test_b_idle_process_is_left_alone_and_a_failed_signal_keeps_the_target():
    tree = [FakeProc(IDLE), FakeProc(NORMAL)]
    state = {"suite": True}
    w = _watcher(tree, state)
    w.step()
    assert [p.cls for p in tree] == [IDLE, BELOW]
    w.signal = lambda: (_ for _ in ()).throw(RuntimeError("cannot read"))
    tree.append(FakeProc(NORMAL))
    w.step()
    assert [p.cls for p in tree] == [IDLE, BELOW, BELOW]  # the last target stays


def test_b_watcher_follows_the_signal_over_time():
    tree = [FakeProc(NORMAL)]
    state = {"suite": True}
    with full_run.tree_priority_watch(poll_s=0.02, signal=lambda: state["suite"], tree=lambda: list(tree)):
        deadline = time.time() + 5
        while time.time() < deadline and tree[0].cls != BELOW:
            time.sleep(0.01)
        assert tree[0].cls == BELOW
        state["suite"] = False
        while time.time() < deadline and tree[0].cls != NORMAL:
            time.sleep(0.01)
        assert tree[0].cls == NORMAL


def test_c_the_watcher_thread_stops_with_the_suite():
    tree = [FakeProc(BELOW)]
    with full_run.tree_priority_watch(poll_s=0.02, signal=lambda: False, tree=lambda: list(tree)) as w:
        assert w._thread.is_alive()
    assert not w._thread.is_alive()
    assert not [t for t in threading.enumerate() if t.name == "full-run-priority"]


def test_c_the_watcher_stops_when_the_suite_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(full_run._merge, "_run_suite", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        full_run.run_suite_by_merge_state("x", tmp_path, {}, None, "")
    assert not [t for t in threading.enumerate() if t.name == "full-run-priority"]


def _row(pid, ppid, cmdline, cwd=None):
    return {"pid": pid, "ppid": ppid, "name": "python.exe", "cmdline": cmdline, "username": "u", "session": 1,
            "cpu_s": 0.0, "rss_mb": 1.0, "cwd": cwd}


def test_signal_is_the_daemons_merge_suite_pytest(monkeypatch):
    full = _row(10, 1, ["python", "-m", "pytest", "tests"], "C:/r/.claude/worktrees/full-run")
    merge = _row(20, 1, ["python", "-m", "pytest", "tests/test_x.py"], "C:/r/.claude/worktrees/merge-suite")
    monkeypatch.setattr(load_groups, "read_proc_table", lambda: [full])
    assert full_run.merge_suite_running() is False
    monkeypatch.setattr(load_groups, "read_proc_table", lambda: [full, merge])
    assert full_run.merge_suite_running() is True
    assert load_groups.snapshot([full, merge], {})["merge_suite_pytest"] == 1  # the number the daemon reads
