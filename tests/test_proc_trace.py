"""#396: scripts/proc_trace.py with a fake process table: no real processes, no sleep."""

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("proc_trace", Path(__file__).resolve().parents[1] / "scripts" / "proc_trace.py")
pt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pt)

SVC = r"C:\Windows\system32\svchost.exe -k netsvcs -p -s Schedule"


def row(pid, ppid, name, cmd="", ct=1000.0):
    return {"pid": pid, "ppid": ppid, "name": name, "cmdline": cmd or name, "create_time": ct}


def run(tmp_path, snapshots):
    it = iter(snapshots)
    last = [snapshots[0]]

    def table():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    t = [0.0]

    def sleep(s):
        t[0] += 1.0

    out = tmp_path / "o.jsonl"
    pt.record(0.1, out, table=table, clock=lambda: t[0], sleep=sleep)
    return [json.loads(x) for x in out.read_text().splitlines()]


def test_new_powershell_with_svchost_parent(tmp_path):
    base = [row(1, 0, "System"), row(50, 999, "svchost.exe", SVC), row(7, 1, "powershell.exe", "old")]
    new = base + [row(60, 50, "powershell.exe", "powershell -File x.ps1", ct=2000.0)]
    lines = run(tmp_path, [base, new])
    assert len(lines) == 1
    assert lines[0]["pid"] == 60
    assert [e["name"] for e in lines[0]["chain"]] == ["powershell.exe", "svchost.exe"]
    assert "Schedule" in lines[0]["chain"][1]["cmdline"]


def test_parent_dead_chain_from_cache(tmp_path):
    base = [row(1, 0, "System")]
    s2 = base + [row(70, 1, "launcher.exe", "launcher --go", ct=1500.0)]
    s3 = base + [row(71, 70, "powershell.exe", "ps", ct=1600.0)]
    lines = run(tmp_path, [base, s2, s3])
    assert [e["name"] for e in lines[0]["chain"]] == ["powershell.exe", "launcher.exe", "System"]


def test_notepad_not_written(tmp_path):
    base = [row(1, 0, "System")]
    assert run(tmp_path, [base, base + [row(80, 1, "notepad.exe")]]) == []


def test_summarize(tmp_path):
    p = tmp_path / "s.jsonl"

    def line(ts, starter, cmd):
        return json.dumps({"ts": ts, "pid": 1, "name": "powershell.exe", "cmdline": cmd,
                           "chain": [{"pid": 1, "name": "powershell.exe", "cmdline": cmd},
                                     {"pid": 2, "name": starter, "cmdline": "x"}]})

    ls = [line(f"2026-10-01T10:{m:02d}:00", "a.exe", "ps a") for m in (0, 15, 30)]
    ls.append(line("2026-10-01T11:00:00", "a.exe", "ps a"))
    ls += [line("2026-10-01T10:10:00", "b.exe", "ps b"), line("2026-10-01T10:40:00", "b.exe", "ps b")]
    p.write_text("\n".join(ls) + "\n")
    rows = pt.summarize(p)
    assert [r["count"] for r in rows] == [4, 2]
    assert [r["per_hour"] for r in rows] == [4.0, 2.0]
