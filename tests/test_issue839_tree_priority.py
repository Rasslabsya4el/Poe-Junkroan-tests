"""#839 unit 1: by day every pytest tree is BELOW_NORMAL, by night Normal. Live class of a started child."""
import os
import subprocess
import sys
import textwrap

import pytest

from tools.agentops import full_run, merge

pytestmark = pytest.mark.skipif(os.name != "nt", reason="priority classes are read through the Windows API")

NORMAL, BELOW = 0x20, 0x4000

# a child that prints its own priority class
PROBE = ("import ctypes;k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p;"
         "k.GetPriorityClass.argtypes=[ctypes.c_void_p];print('CLASS=%d'%k.GetPriorityClass(k.GetCurrentProcess()))")
PROBE_CMD = f'"{sys.executable}" -c "{PROBE}"'


def _class_of(text: str) -> int:
    return int(text.split("CLASS=")[1].split()[0])


@pytest.mark.parametrize("period,expected", [("day", BELOW), ("night", None)])
def test_a_merge_suite_launch(monkeypatch, tmp_path, period, expected):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
    ok, out = merge._run_suite(PROBE_CMD, tmp_path)
    got = _class_of(out)
    if expected is None:
        assert got in (NORMAL, _parent_class())  # night adds no flag: the child keeps the parent's class
    else:
        assert got == expected


def _parent_class() -> int:
    import psutil
    return psutil.Process().nice()


@pytest.mark.parametrize("period,expected", [("day", BELOW), ("night", None)])
def test_b_full_run_suite_launch(monkeypatch, tmp_path, period, expected):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
    monkeypatch.setattr(full_run, "merge_suite_running", lambda: False)
    monkeypatch.setattr(full_run.TreePriorityWatcher, "__init__",
                        _fast_init(full_run.TreePriorityWatcher.__init__), raising=True)
    ok, out = full_run.run_suite_by_merge_state(PROBE_CMD, tmp_path)
    got = _class_of(out)
    if expected is None:
        assert got in (NORMAL, _parent_class())
    else:
        assert got == expected


def _fast_init(orig):
    def init(self, poll_s=None, **kw):
        orig(self, 0.05, **kw)
    return init


def test_b2_watcher_target_by_day_is_below_even_without_a_merge_suite(monkeypatch):
    import psutil

    class P:
        def __init__(self): self.c = psutil.NORMAL_PRIORITY_CLASS
        def nice(self, v=None):
            if v is None:
                return self.c
            self.c = v
    for period, want in (("day", psutil.BELOW_NORMAL_PRIORITY_CLASS), ("night", psutil.NORMAL_PRIORITY_CLASS)):
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
        tree = [P()]
        full_run.TreePriorityWatcher(signal=lambda: False, tree=lambda: tree).step()
        assert tree[0].c == want


# The child pytest is started through a launcher that exits at once, so the child is an orphan and no longer a
# descendant of this process (#855): the full run's TreePriorityWatcher (full_run.py, polls every 5 s) re-sets
# EVERY descendant of the full-run tree, and by day it lowered this test's own Normal child to BELOW_NORMAL
# before it read its class (red full run 60849c03, night-32 got 16384). The watcher walks ppid links only.
LAUNCHER = ("import os,subprocess,sys;"
            "p=subprocess.Popen(sys.argv[2:],stdout=open(sys.argv[1],'w'),stderr=subprocess.STDOUT,"
            f"creationflags={NORMAL}|getattr(subprocess,'CREATE_NO_WINDOW',0));"
            "print(p.pid,flush=True);os._exit(0)")  # _exit: no interpreter teardown, the child leaves the tree at once


def _child_pytest_output(tmp_path, period, while_alive=None) -> str:
    import psutil
    tiny = tmp_path / "test_tiny.py"
    tiny.write_text(textwrap.dedent("""
        import ctypes
        def test_class():
            k = ctypes.windll.kernel32
            k.GetCurrentProcess.restype = ctypes.c_void_p
            k.GetPriorityClass.argtypes = [ctypes.c_void_p]
            print("CLASS=%d" % k.GetPriorityClass(k.GetCurrentProcess()))
    """), encoding="utf-8")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # the tiny file sits outside the repo, so pytest does not find the root conftest by itself: load it as
    # a plugin (``-p conftest`` with the repo root on PYTHONPATH), the hook under test is the same one
    env = {**os.environ, "JUNKROAN_FORCE_PERIOD": period,
           "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}
    out = tmp_path / "child.out"
    # started Normal whatever this test process's own class is
    r = subprocess.run([sys.executable, "-c", LAUNCHER, str(out), sys.executable, "-m", "pytest", "-p", "conftest",
                        "-p", "no:cacheprovider", "-s", "-q", str(tiny)], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, timeout=120,
                       creationflags=NORMAL | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    pid = int(r.stdout.split()[0])
    try:
        child = psutil.Process(pid)
        while while_alive is not None and child.is_running():
            while_alive()  # the launcher has exited: only now does a watcher poll run, so there is no race
        child.wait(120)
    except psutil.NoSuchProcess:
        pass
    return out.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("period,expected", [("day", BELOW), ("night", NORMAL)])
def test_c_pytest_process_lowers_itself(tmp_path, period, expected):
    """A bare ``python -m pytest`` of a tiny file, rooted under this repo's conftest: its own class read
    inside the test."""
    out = _child_pytest_output(tmp_path, period)
    assert _class_of(out) == expected, out


def test_c2_night_child_stays_normal_beside_a_day_tree_watcher(tmp_path):
    """#855: a day TreePriorityWatcher on this process's tree (as in the full run) must not lower the night
    child: it is not in the tree. The watcher is stepped in a tight loop from the moment the launcher is gone
    until the child ends (the real one polls every 5 s)."""
    w = full_run.TreePriorityWatcher(signal=lambda: False, day=lambda: True)
    out = _child_pytest_output(tmp_path, "night", while_alive=w.step)
    assert _class_of(out) == NORMAL, out
