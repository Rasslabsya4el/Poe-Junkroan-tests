"""#735 row 4: the full run's pytest and its children run below normal priority."""
import os
import sys
import time

import psutil

from tools.agentops import full_run

BELOW = psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10


def test_suite_and_children_below_normal(tmp_path):
    before = psutil.Process().nice()
    seen = tmp_path / "seen.txt"
    script = tmp_path / "stub.py"
    script.write_text(
        "import subprocess, sys, time, os\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        f"open(r'{seen}', 'w').write(f'{{os.getpid()}} {{c.pid}}')\n"
        "time.sleep(20)\n")
    import threading
    result = {}

    def run():
        result["r"] = full_run.run_suite_below_normal(
            f'"{sys.executable}" "{script}"', tmp_path, {}, tmp_path / "o.out", "")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    pids = []
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not seen.exists():
            time.sleep(0.1)
        time.sleep(0.3)
        assert seen.exists()
        pids = [int(x) for x in seen.read_text().split()]
        # shell=True: the wrapper cmd.exe may sit above; all of the tree must be below normal
        root = psutil.Process(pids[0])
        procs = [root] + root.children(recursive=True) + [psutil.Process(pids[1])]
        classes = {p.pid: p.nice() for p in procs}
        assert all(v == BELOW for v in classes.values()), classes
    finally:
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass
        t.join(10)
    assert psutil.Process().nice() == before  # the full run's own class is restored
