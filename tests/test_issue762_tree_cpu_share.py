"""#762: the tree share counts processes born and ended inside the window (real processes, no PoB)."""

import json
import os
import subprocess
import sys
import time
from timing_bound import bound
from pathlib import Path

import psutil
import pytest

from junkroan.runs import load_groups

NCPU = os.cpu_count() or 1
CHILD = (
    "import sys,time,json\n"
    "t0=time.time()\n"
    "while time.process_time()<0.2: pass\n"
    "import os\n"
    "mine=sys.argv[1]+'.'+sys.argv[2]\n"  # #769: one file per child, named by its number (a pid is recycled within seconds; a shared append file loses lines on Windows)
    "open(mine+'.tmp','w').write(json.dumps([t0,time.time(),time.process_time()]))\n"
    "os.replace(mine+'.tmp',mine)\n"
)
# the root: keeps 4 children alive for `secs` seconds; its argv carries `agentops full-run` (a full-run root)
ROOT = (
    "import subprocess,sys,time\n"
    "out,secs,mode=sys.argv[1],float(sys.argv[2]),sys.argv[3]\n"
    "end=time.time()+secs\nalive=[]\nstarted=0\n"
    "while time.time()<end:\n"
    "    alive=[p for p in alive if p.poll() is None]\n"
    "    while len(alive)<(4 if mode=='short' else 1) and time.time()<end:\n"
    "        code=%r if mode=='short' else 'while True: pass'\n"
    "        alive.append(subprocess.Popen([sys.executable,'-c',code,out,str(started)])); started+=1\n"
    "    time.sleep(0.01)\n"
    "for p in alive:\n"
    "    if mode=='short': p.wait()\n"  # a short child is let finish: every started child leaves its file
    "    else: p.kill()\n"
    "open(out+'.started','w').write(str(started))\n"
) % CHILD


def _root(tmp_path, mode, secs, tag="agentops full-run"):
    out = tmp_path / f"{mode}{tag[:2]}.jsonl"
    child = tmp_path / f"child_{mode}.py"
    child.write_text(CHILD if mode == "short" else "import psutil; psutil.Process().nice(psutil.HIGH_PRIORITY_CLASS)"+chr(10)+"while True: pass")
    argv = [sys.executable, "-c", ROOT, str(out), str(secs), mode, str(child)] + tag.split()
    return subprocess.Popen(argv), out


def _end_tree(root):
    """#853: end a root and its children; a process already gone (psutil.NoSuchProcess, also from Process(pid) and
    children()) counts as ended, any other error raises."""
    try:
        kids = psutil.Process(root.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        kids = []
    for c in kids:
        try:
            c.kill()
        except psutil.NoSuchProcess:
            pass
    root.kill()


def _cmds(*roots):
    """a cheap `cmdline_reader`: the full process table costs ~5 s on a loaded PC (old cost, not this ticket's)."""
    return lambda: {r.pid: psutil.Process(r.pid).cmdline() for r in roots}


def _truth_pct(out, w0, w1):
    """child cpu spread uniformly over each child's life, clipped to the window [w0, w1]. #769: one result file
    per child (`out.<n>`); the count of files must equal the count of children the root started."""
    started = int(Path(str(out) + ".started").read_text())
    files = sorted(out.parent.glob(out.name + ".[0-9]*"))
    assert len(files) == started, f"{len(files)} result files for {started} children started"
    lives = [json.loads(f.read_text()) for f in files]
    total = 0.0
    for a, b, cpu in lives:
        lo, hi = max(a, w0), min(b, w1)
        if hi > lo and b > a:
            total += cpu * (hi - lo) / (b - a)
    print(f"children {len(lives)}, mean wall {sum(b - a for a, b, _ in lives) / len(lives):.2f}s")
    return total / (w1 - w0) / NCPU * 100.0


def test_row1_short_lived_children_counted(tmp_path):
    root, out = _root(tmp_path, "short", 4)
    try:
        time.sleep(1.0)
        w0 = time.time()
        _, full = load_groups.pob_and_full_run_cpu_pct({}, cmdline_reader=_cmds(root))
        w1 = time.time()
        root.wait(timeout=60)
    finally:
        root.kill()
    truth = _truth_pct(out, w0, w1)
    print(f"row1 reading {full} truth {truth:.2f}")
    assert truth > 0 and abs(full - truth) <= 0.2 * truth


class _FakeHandles:
    """processes of a fake table: `born` pid -> creation time; every read adds `rate` cpu seconds."""

    born: dict = {}
    rate: dict = {}

    def __init__(self):
        self.h, self.last, self.n = {}, {}, {}

    def open(self, pid):
        self.h[pid] = True
        return True

    def created(self, pid):
        return self.born.get(pid)

    def read(self, pid):
        self.n[pid] = self.n.get(pid, 0) + 1
        self.last[pid] = self.rate[pid] * self.n[pid]
        return self.last[pid]

    def close(self):
        pass


def _fake_window(ppids, born):
    class H(_FakeHandles):
        pass

    H.born = born
    H.rate = {pid: 0.1 for pid in ppids}
    now = [0.0]
    clock = lambda: now[0]
    sleep = lambda s: now.__setitem__(0, now[0] + s)
    return load_groups._exact_tree_window({}, {100}, 4, ppids, load_groups._chain, clock, sleep,
                                          ppids_reader=lambda: ppids, handles=H)[2]


def test_769_stale_ppid_member_created_before_its_ancestor_not_counted():
    """root 100 (born 10), its child 200 (born 11) and 400 (born 12, child of 200); pid 300 names 200 as its ppid
    but was created at 5, before 200: 200 is a recycled pid, 300 is not its child (OneDrive.Sync.Service.exe)."""
    clean = {100: 1, 200: 100, 400: 200}
    born = {100: 10.0, 200: 11.0, 400: 12.0, 300: 5.0}
    without = _fake_window(clean, born)
    stale = _fake_window({**clean, 300: 200}, born)
    child_of_200 = _fake_window({**clean, 300: 200}, {**born, 300: 13.0})  # control: a real later child IS counted
    print(f"tree without 300 {without:.2f}, 300 born before its ppid {stale:.2f}, 300 born after {child_of_200:.2f}")
    assert without > 0 and child_of_200 > without
    assert stale == without


def _old_tidy_up(root):
    for c in psutil.Process(root.pid).children(recursive=True):
        c.kill()
    root.kill()


def test_853_end_tree_tolerates_processes_already_gone(monkeypatch):
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    child = subprocess.Popen(sleeper)
    handle = psutil.Process(child.pid)
    child.kill()
    child.wait()  # a child listed by children() that ended before its kill()
    root = subprocess.Popen(sleeper)
    with monkeypatch.context() as m:
        m.setattr(psutil.Process, "children", lambda self, recursive=False: [handle])
        with pytest.raises(psutil.NoSuchProcess):  # control: the old loop raises on it
            _old_tidy_up(root)
        _end_tree(root)  # no raise
    root.wait(timeout=30)
    with pytest.raises(psutil.NoSuchProcess):  # a root already gone: the old loop raises at Process(pid)
        _old_tidy_up(root)
    _end_tree(root)  # no raise


def test_row2_steady_child_is_one_core(tmp_path):
    root, _ = _root(tmp_path, "steady", 8)
    try:
        time.sleep(1.5)
        child = psutil.Process(root.pid).children()[0]
        c0, t0 = sum(child.cpu_times()[:2]), time.perf_counter()
        _, full = load_groups.pob_and_full_run_cpu_pct({}, cmdline_reader=_cmds(root))
        got = (sum(child.cpu_times()[:2]) - c0) / (time.perf_counter() - t0) / NCPU * 100.0  # the child's own
    finally:
        _end_tree(root)
    one_core = 100.0 / NCPU
    line = f"row2 reading {full} child's own {got:.2f} one core {one_core:.2f}"
    print(line)
    if got < 0.5 * one_core:  # #777: the machine starved the child; a reading against so little proves nothing
        pytest.skip(f"child got {got:.2f} % of the machine, under half a core: {line}")
    _assert_reader_matches_child(full, got, one_core)


def _assert_reader_matches_child(full, got, one_core):
    """#777 clause (a): the reader's value equals the child's own measured share within 0.1 of one core."""
    assert abs(full - got) <= 0.1 * one_core, f"reader {full} vs child's own {got:.2f}"


def test_777_a_wrong_reader_is_caught():
    one_core = 100.0 / NCPU
    got = one_core
    _assert_reader_matches_child(got, got, one_core)  # control: the right reader passes
    with pytest.raises(AssertionError):
        _assert_reader_matches_child(2 * got, got, one_core)


def test_row3_outside_process_not_counted(tmp_path):
    inside, _ = _root(tmp_path, "steady", 5)
    outside, out = _root(tmp_path, "short", 5, tag="plain")
    try:
        time.sleep(1.0)
        _, full = load_groups.pob_and_full_run_cpu_pct({}, cmdline_reader=_cmds(inside, outside))
    finally:
        for r in (inside, outside):
            _end_tree(r)
    one_core = 100.0 / NCPU
    print(f"row3 reading {full} one core {one_core:.2f}")
    assert full <= 1.1 * one_core  # only the steady child, none of the outside process's children


def test_row4_reading_cost(tmp_path):
    root, _ = _root(tmp_path, "short", 5)
    try:
        time.sleep(1.0)
        me = psutil.Process()
        spent = []

        def cmdlines():  # the old cost, not this ticket's: timed apart (4.8 s on a loaded PC)
            a, c = time.perf_counter(), sum(me.cpu_times()[:2])
            r = load_groups.read_cmdlines()
            spent.append((time.perf_counter() - a, sum(me.cpu_times()[:2]) - c))
            return r

        c0, t0 = sum(me.cpu_times()[:2]), time.perf_counter()
        load_groups.pob_and_full_run_cpu_pct({}, cmdline_reader=cmdlines)
        cpu = sum(me.cpu_times()[:2]) - c0 - spent[0][1]
        wall = time.perf_counter() - t0 - spent[0][0]
    finally:
        root.kill()
    print(f"row4 own cpu {cpu:.3f}s over {wall:.2f}s = {cpu / wall:.3f} core")
    # bound = max(floor, factor x a CPU spin timed here): load that slows the spin slows the call (#824)
    wall_bound = bound(0.5 + 2.0, 17.0)
    assert wall <= wall_bound and cpu / wall < 0.3, (wall, wall_bound)
