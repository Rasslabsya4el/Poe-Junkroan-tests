import json
from datetime import datetime, timedelta

from junkroan.runs import load_record as lr

NOW = datetime(2026, 10, 10, 14, 0, 0)


def snap(ts, cpu=53.0, free=12362.5, pob=2, filler=1, claude=46, whole=3, merge=1):
    return {
        "ts": ts.isoformat(timespec="seconds"), "free_ram_mb": free, "total_ram_mb": 32000.0, "cpu_pct": cpu,
        "groups": {"pob_counted": {"count": pob}, "pob_filler": {"count": filler}, "claude": {"count": claude}},
        "whole_suite_pytest": whole, "merge_suite_pytest": merge, "whole_suite_list": [], "_wall": 1,
    }


def test_trim_drops_old(tmp_path):
    p = tmp_path / "d" / "s.jsonl"
    for d in (20, 19):
        lr.append_sample(p, snap(NOW - timedelta(days=d)))
    for d in (2, 0):
        lr.append_sample(p, snap(NOW - timedelta(days=d)))
    assert lr.trim(p, NOW) == 2
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert all(datetime.fromisoformat(json.loads(x)["ts"]) >= NOW - timedelta(days=14) for x in lines)
    assert "_wall" not in lines[0]
    assert not list(p.parent.glob("*.tmp"))


def test_trim_missing_file_noop(tmp_path):
    assert lr.trim(tmp_path / "none.jsonl", NOW) == 0


def test_load_line_near_sample(tmp_path):
    p = tmp_path / "s.jsonl"
    lr.append_sample(p, snap(NOW - timedelta(minutes=5), cpu=1.0))
    lr.append_sample(p, snap(NOW - timedelta(seconds=20), cpu=88.5, free=10240, pob=2, filler=1, claude=7, whole=3, merge=1))
    lr.append_sample(p, snap(NOW - timedelta(seconds=100), cpu=5.0))
    p.write_text("".join(sorted(p.read_text().splitlines(True), key=lambda s: json.loads(s)["ts"])))
    out = lr.load_line(p, NOW)
    assert out == f"Load at its end ({(NOW - timedelta(seconds=20)).isoformat(timespec='seconds')}): CPU 88.5%, free RAM 10.0 GB, PoB 3, pytest 4, claude 7"


def test_load_line_stale_or_missing(tmp_path):
    p = tmp_path / "s.jsonl"
    assert lr.load_line(p, NOW) == "Load at its end: no load sample"
    p.write_text("")
    assert lr.load_line(p, NOW) == "Load at its end: no load sample"
    lr.append_sample(p, snap(NOW - timedelta(minutes=5)))
    assert lr.load_line(p, NOW) == "Load at its end: no load sample"


def test_load_line_reads_from_end_large(tmp_path):
    p = tmp_path / "s.jsonl"
    for i in range(3000):
        lr.append_sample(p, snap(NOW - timedelta(seconds=30 * (3000 - i))))
    assert "CPU 53%" in lr.load_line(p, NOW - timedelta(seconds=25))
