"""#574: on a fast run the end pass waits out pobb.in's HTTP 429; the write-time path never sleeps. No network, no PoB."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import benchmark  # noqa: E402
from junkroan import pobbin  # noqa: E402
from test_benchmark_pobbin import Fake, _persist, _read, _row, _setup  # noqa: E402


class Phased:
    """A fake pobb.in whose answer depends on the phase (`write`, `pass`, `backfill`) and the call's number in it."""

    def __init__(self):
        self.phase = "write"
        self.n = {"write": 0, "pass": 0, "backfill": 0}
        self.rules = {}

    def __call__(self, code, _total):
        self.n[self.phase] += 1
        rule = self.rules.get(self.phase)
        status = rule(self.n[self.phase]) if rule else None
        if status:
            raise pobbin.HttpStatusError(status)
        return f"id-{code}"


def _run(monkeypatch, tmp_path, slugs, write_rule):
    phased = Phased()
    phased.rules["write"] = write_rule
    fake = Fake(phased)
    out, run, results = _setup(monkeypatch, tmp_path, fake)
    sleeps: list[float] = []
    real_sleep, own = benchmark.time.sleep, threading.get_ident()

    def record(seconds):
        # time.sleep is process-wide: only this test's thread is recorded (#826), others really sleep
        if threading.get_ident() == own:
            sleeps.append(seconds)
        else:
            real_sleep(seconds)

    monkeypatch.setattr(benchmark.time, "sleep", record)
    for slug in slugs:
        _persist(out, run, results, _row(slug))
    return phased, fake, out, run, results, sleeps


SLUGS20 = [f"b{i:02d}" for i in range(1, 21)]


def test_row1_the_write_time_path_never_sleeps(tmp_path, monkeypatch):
    phased, fake, out, run, results, sleeps = _run(monkeypatch, tmp_path, SLUGS20, lambda n: 429 if n >= 16 else None)
    rows = [_read(out, f"{s}-s1") for s in SLUGS20]
    assert sum(1 for r in rows if r.get("pobbin_id")) == 15
    assert [r.get("pobbin_error") for r in rows[15:]] == ["HTTP 429"] * 5
    assert all(r["ok"] for r in rows)
    assert (len(fake.calls), len(sleeps)) == (20, 0)


def test_row2_the_end_pass_waits_out_a_429_and_fixes_all_five(tmp_path, monkeypatch, capsys):
    phased, fake, out, run, results, sleeps = _run(monkeypatch, tmp_path, SLUGS20, lambda n: 429 if n >= 16 else None)
    phased.phase = "pass"
    phased.rules["pass"] = lambda n: 429 if n == 1 else None
    before = len(fake.calls)
    fixed = benchmark.pobbin_retry_pass(out, results, run)
    assert fixed == 5
    assert (len(fake.calls) - before, len(sleeps)) == (6, 1)
    assert sleeps == [benchmark.BACKFILL_429_WAIT_S]
    for s in SLUGS20[15:]:
        data = _read(out, f"{s}-s1")
        assert data["pobbin_id"] == f"id-import {s}" and "pobbin_error" not in data
    n_up = sum(1 for r in results if r.get("pobbin_id"))
    n_err = sum(1 for r in results if r.get("pobbin_error"))
    line = f"pobbin: {n_up} uploaded, {n_err} errors, {fixed} fixed at the end"
    assert line == "pobbin: 20 uploaded, 0 errors, 5 fixed at the end"


SLUGS5 = ["c1", "c2", "c3", "c4", "c5"]


def _row3(monkeypatch, tmp_path):
    phased, fake, out, run, results, sleeps = _run(monkeypatch, tmp_path, SLUGS5, lambda n: 429)
    phased.phase = "pass"
    phased.rules["pass"] = lambda n: 500 if n == 2 else None
    before = len(fake.calls)
    fixed = benchmark.pobbin_retry_pass(out, results, run)
    return phased, fake, out, sleeps, fixed, len(fake.calls) - before


def test_row3_a_non_429_failure_stops_the_end_pass(tmp_path, monkeypatch):
    phased, fake, out, sleeps, fixed, calls = _row3(monkeypatch, tmp_path)
    assert fixed == 1
    assert (calls, len(sleeps)) == (2, 0)
    assert "pobbin_id" in _read(out, "c1-s1") and "pobbin_error" not in _read(out, "c1-s1")
    assert all(_read(out, f"{s}-s1").get("pobbin_error") == "HTTP 429" for s in SLUGS5[1:])


def test_row4_a_backfill_afterwards_links_the_four_and_leaves_the_one(tmp_path, monkeypatch):
    phased, fake, out, sleeps, fixed, _calls = _row3(monkeypatch, tmp_path)
    first = _read(out, "c1-s1")
    phased.phase = "backfill"
    before = len(fake.calls)
    line = benchmark.pobbin_backfill(out)
    assert (len(fake.calls) - before, len(sleeps)) == (4, 0)
    assert _read(out, "c1-s1") == first
    for s in SLUGS5[1:]:
        data = _read(out, f"{s}-s1")
        assert data["pobbin_id"] == f"id-import {s}" and "pobbin_error" not in data
    assert "4 uploaded, 1 already linked, 0 errors" in line
