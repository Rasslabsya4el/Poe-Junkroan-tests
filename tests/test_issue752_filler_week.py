"""#752: `runs.py fillers <host> --week <Monday>` prints the wait, the share made ahead, the time lost. No PoB."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONDAY = "20261005"
TAG = f"week-{MONDAY}"
BASE = datetime(2026, 10, 7, 12, 0).astimezone()  # Wednesday noon, local: inside the week in any zone
CORE = "python scripts/benchmark.py --set core14 --tag " + TAG


def _iso(offset_s: float) -> str:
    return (BASE + timedelta(seconds=offset_s)).isoformat()


def _job(jid, *, filler, sub, start, end=None, state="done", rc=0, cmd="python x.py", tag=TAG):
    sub_rec = {"op": "submit", "ts": _iso(sub), "job": jid, "host": "laptop", "priority": "P2", "issue": None,
               "submitter": "t", "tag": tag, "pin": None, "cmd": cmd, "resumable": False,
               "class": "filler" if filler else "run"}
    out = [sub_rec]
    if start is not None:
        out.append({"op": "start", "ts": _iso(start), "job": jid})
    if end is not None:
        out.append({"op": "end" if state != "stopped" else "stop", "ts": _iso(end), "job": jid, "rc": rc})
    return out


def _run(tmp_path, recs, rows=0):
    store = tmp_path / "jobs.jsonl"
    store.write_text("".join(json.dumps(r) + "\n" for group in recs for r in group), encoding="utf-8")
    folder = tmp_path / "artifacts" / "benchmark" / f"20261005-0900-week-{MONDAY}"
    (folder / "rows").mkdir(parents=True)
    for i in range(rows):
        (folder / "rows" / f"row{i}-s1.json").write_text("{}", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "runs.py"), "--store", str(store), "fillers", "laptop",
         "--week", MONDAY, "--root", str(tmp_path)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    return p


def _waits(third=58):
    # a filler runs for the first hour; three jobs submitted inside it, a fourth afterwards
    return [
        _job("f1", filler=True, sub=0, start=0, end=3600, cmd="python scripts/benchmark.py --resume F --row row0-s1"),
        _job("j1", filler=False, sub=100, start=112, end=200, tag="t"),
        _job("j2", filler=False, sub=300, start=341, end=400, tag="t"),
        _job("j3", filler=False, sub=500, start=500 + third, end=600, tag="t"),
        _job("j4", filler=False, sub=7200, start=7500, end=7600, tag="t"),
    ]


def test_row1_longest_wait_three_jobs(tmp_path):
    p = _run(tmp_path, _waits())
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines()[0] == "longest wait: 58 s (j3), 3 jobs"
    assert "over the limit" not in p.stdout


def test_row4_over_the_limit_names_job(tmp_path):
    p = _run(tmp_path, _waits(third=75))
    assert p.stdout.splitlines()[0] == "longest wait: 75 s (j3), 3 jobs"
    assert "over the limit: j3, 75 s" in p.stdout.splitlines()


def test_row2_made_ahead_40_of_61(tmp_path):
    recs = []
    for i in range(40):
        recs.append(_job(f"a{i}", filler=True, sub=i * 10, start=i * 10, end=i * 10 + 5,
                         cmd=f"python scripts/benchmark.py --resume F --row row{i}-s1"))
    # a filler of row 40 that ended after the Monday line started does not count
    recs.append(_job("late", filler=True, sub=9000, start=9000, end=9500,
                     cmd="python scripts/benchmark.py --resume F --row row40-s1"))
    recs.append(_job("mon", filler=False, sub=5000, start=5000, end=20000, cmd=CORE))
    p = _run(tmp_path, recs, rows=61)
    assert "made ahead: 40 of 61 (66 %)" in p.stdout.splitlines()


def test_row3_lost_time_15_percent(tmp_path):
    h = 3600
    recs = [_job("done1", filler=True, sub=0, start=0, end=17 * h),
            _job("kill1", filler=True, sub=17 * h, start=17 * h, end=20 * h, state="stopped", rc=1)]
    p = _run(tmp_path, recs)
    assert "lost time: 15 % (3 h 00 min of 20 h 00 min)" in p.stdout.splitlines()
    assert "lost time over 20 %" not in p.stdout


def test_lost_time_over_20_percent_line(tmp_path):
    h = 3600
    recs = [_job("done1", filler=True, sub=0, start=0, end=10 * h),
            _job("kill1", filler=True, sub=10 * h, start=10 * h, end=14 * h, state="stopped", rc=1)]
    p = _run(tmp_path, recs)
    assert "lost time over 20 %: open the ticket for a real pause" in p.stdout.splitlines()


def test_row5_no_fillers(tmp_path):
    p = _run(tmp_path, [_job("j1", filler=False, sub=0, start=10, end=20, tag="t")])
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert len(lines) == 3 and all("no fillers ran" in l for l in lines)
    assert lines[0].startswith("longest wait: 0 s, 0 jobs")
