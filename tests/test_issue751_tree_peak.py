"""#751 unit 2: scripts/tree_peak.py measures the peak of a whole process tree."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tree_peak.py"

STUB = """
import subprocess, sys, time
if len(sys.argv) > 1:
    b = bytearray(50 * 1024 * 1024)
    for i in range(0, len(b), 4096):
        b[i] = 1
    time.sleep(4)
else:
    kids = [subprocess.Popen([sys.executable, __file__, 'kid']) for _ in range(2)]
    for k in kids:
        k.wait()
"""


def _run(tmp_path, cmd):
    out = tmp_path / "o.json"
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--interval", "0.3", "--out", str(out), "--", *cmd],
        capture_output=True, text=True, timeout=60,
    )
    return p, json.loads(p.stdout.strip().splitlines()[-1]), json.loads(out.read_text())


def test_peak_counts_whole_tree(tmp_path):
    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    p, res, filed = _run(tmp_path, [sys.executable, str(stub)])
    assert p.returncode == 0 and res["rc"] == 0
    assert res == filed
    assert res["peak_tree_rss_gb"] >= 0.09
    assert res["peak_process_count"] >= 3
    assert res["samples"] >= 2
    assert res["peak_worker_count"] == 0


def test_failing_rc_propagates(tmp_path):
    p, res, _ = _run(tmp_path, [sys.executable, "-c", "import sys; sys.exit(7)"])
    assert p.returncode == 7 and res["rc"] == 7
