"""Plain-python check of the laptop's run in the monitor's data (#984): python test_addon_laptop_run.py

1. A RECORDED laptop run (`fixtures/laptop_run/`: what the laptop held for the weekly core run `j-20261013-2220-1c28`
   at 00:55 on 14.10, its benchmark folder trimmed and the job record) gives the same build fields as a PC run of the
   same folder. Before the fix its `progress` was None (the laptop's daemon works in `poe-junkroan-v2-daemon`, not in the
   REPO the collector looked at) and, once found, `--workers auto` raised ValueError and made the whole `host` reading an error.
2. The laptop read is bounded: a host that never answers adds at most LAPTOP_WAIT (+ process start) to a pull and the
   last good reading comes back with its age; a host slower than the bound is picked up by a later pull; a host that
   fails at once is held off for LAPTOP_BACKOFF.
"""
import json
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file
FX = Path(__file__).resolve().parent / "fixtures" / "laptop_run"
BOUND = addon.LAPTOP_WAIT + 1.0  # the wait plus starting a process and reading the cache


def _job(out: Path):
    rec = json.loads((FX / "job.json").read_text(encoding="utf-8"))
    rec["out"] = str(out)
    return SimpleNamespace(**rec)


def test_laptop_run_has_the_build_fields_of_a_pc_run():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        old = addon.BENCH
        try:
            # the PC: the folder under this checkout's artifacts/benchmark, the job's out in this checkout
            pc_bench = root / "pc" / "artifacts" / "benchmark"
            shutil.copytree(FX / "bench", pc_bench)
            addon.BENCH = pc_bench
            pc = addon.run_cells(_job(root / "pc" / "artifacts" / "runs" / "x.out"))
            # the laptop: the folder in the daemon's own checkout; the collector's REPO holds no folder of that tag
            lap_bench = root / "daemon" / "artifacts" / "benchmark"
            shutil.copytree(FX / "bench", lap_bench)
            addon.BENCH = root / "main" / "artifacts" / "benchmark"
            lap = addon.run_cells(_job(root / "daemon" / "artifacts" / "runs" / "x.out"))
        finally:
            addon.BENCH = old
        assert pc is not None and lap is not None, (pc, lap)
        assert (lap["done"], lap["total"], lap["total_open"]) == (1, 43, True), lap  # 14 builds x 3 seeds + 1 planned variant
        assert sorted(lap) == sorted(pc), (sorted(lap), sorted(pc))
        assert [sorted(c) for c in lap["cells"]] == [sorted(c) for c in pc["cells"]]
        got = [(c["ref"], c["seed"], c["state"]) for c in lap["cells"][:4]]
        assert got == [("absolution_minions", 4, "done"), ("absolution_minions", 5, "waiting"),
                       ("absolution_minions", 6, "waiting"), ("bleed_bow", 4, "running")], got
        assert sum(c["state"] == "running" for c in lap["cells"]) == 2
        assert "·" in lap["cells"][-1]["name"], lap["cells"][-1]  # the variant row that broke the cp1252 pipe
        # `--workers auto` (the daemon has not rewritten it): no crash. The eta is no longer set here (#985: runs()
        # sets `progress["eta"]` from the pool estimate), so both hosts return None from run_cells alike.
        assert lap["eta"] is None and pc["eta"] is None, (lap["eta"], pc["eta"])
        _laptop_cells_have_status(lap)


def _laptop_cells_have_status(lap: dict):
    """#985 (autopilot send-back): every cell of the laptop's run carries its `status` word, every word is one of
    STATUS_WORDS, and a running cell whose log names a catalog step carries `stage_index` / `stage_count`. The three logs
    of the recorded run hold: bleed_bow-s4 2 `step start:` lines, absolution_minions-s4 0, cold_dot-s4 0."""
    cat = addon._catalog()
    words = set(addon.STATUS_WORDS.values())
    no_status = [c for c in lap["cells"] if "status" not in c]
    assert not no_status, (len(no_status), [(c["ref"], c["seed"], c["state"]) for c in no_status[:5]])
    bad = [(c["ref"], c["status"]) for c in lap["cells"] if c["status"] not in words]
    assert not bad, bad[:5]
    running = [c for c in lap["cells"] if c["state"] == "running"]
    # the rule: a running cell has stage_index / stage_count exactly when its step is a catalog step. bleed_bow-s4's log holds
    # 2 `step start:` lines, but its second is cut at the end of the file (`step start: confi`, no newline, a write caught
    # half-way): not a catalog step, so no scale and no guessed step. cold_dot-s4 holds 0 step lines.
    named = [c for c in running if c.get("step") and cat is not None and cat.step_of(c["step"]) is not None]
    scaled = [c for c in running if "stage_index" in c and "stage_count" in c]
    assert [(c["ref"], c["seed"]) for c in named] == [(c["ref"], c["seed"]) for c in scaled], (
        [(c["ref"], c.get("step")) for c in running], [(c["ref"], c["seed"]) for c in scaled])
    print(f"laptop run: {len(lap['cells'])} cells, {len(no_status)} without status; running {len(running)}, "
          f"running with a catalog step {len(named)}, with stage_index {len(scaled)}; "
          f"steps read: {[c.get('step') for c in running]}")


def test_the_laptop_reading_is_ascii_json():
    # the laptop's pipe is cp1252: a variant row's `·` made the PC's utf-8 read fail (#984); `host` takes `here`
    assert addon.LAPTOP_SSH[-2:] == ["host", "here"], addon.LAPTOP_SSH
    assert addon.MODES["host"].__code__.co_flags & 0x04, "host(*flags) accepts the `here` argument"


def _cache_dir():
    d = Path(tempfile.mkdtemp())
    addon.LAPTOP_CACHE = d / "laptop.json"
    return d


def _good_cache(age_s: float) -> dict:
    at = (addon.NOW - addon.timedelta(seconds=age_s)).isoformat()
    row = {"id": "j-1", "tag": "P2-core", "host": "laptop", "progress": {"done": 1, "total": 43, "cells": []}}
    return {"at": at, "data": {"runs": {"running": [row], "queued": []}, "machine": {"cores": 8}}}


def _kill_pending(cache_file: Path):
    try:
        pid = json.loads(cache_file.read_text(encoding="utf-8")).get("pending", {}).get("pid")
        if pid:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass


def test_a_dead_host_costs_the_wait_and_keeps_the_last_data():
    old = addon.LAPTOP_CACHE, addon.LAPTOP_SSH
    d = _cache_dir()
    try:
        addon.LAPTOP_CACHE.write_text(json.dumps(_good_cache(300)), encoding="utf-8")
        addon.LAPTOP_SSH = [sys.executable, "-c", "import time; time.sleep(20)"]  # never answers
        t0 = time.time()
        r = addon.laptop()
        first = time.time() - t0
        t0 = time.time()
        r2 = addon.laptop()  # the ssh is still pending: no second process, no wait
        second = time.time() - t0
        print(f"dead host: first pull {first:.1f} s, next pull {second:.2f} s, age {r['age']} ({r['age_s']} s)")
        assert first <= BOUND, first
        assert second <= 0.5, second
        for x in (r, r2):
            assert "error" not in x and x["runs"]["running"][0]["progress"]["total"] == 43, x
            assert 300 <= x["age_s"] <= 330 and x["age"], x
        _kill_pending(addon.LAPTOP_CACHE)
        # never read before and dead: an error with `offline`, no rows, and still bounded
        addon.LAPTOP_CACHE.unlink()
        t0 = time.time()
        r3 = addon.laptop()
        took = time.time() - t0
        print(f"dead host, never read: {took:.1f} s")
        assert took <= BOUND and r3["error"] and r3["age_s"] is None and r3["last"] == {"running": [], "queued": []}, r3
    finally:
        _kill_pending(addon.LAPTOP_CACHE)
        addon.LAPTOP_CACHE, addon.LAPTOP_SSH = old
        shutil.rmtree(d, ignore_errors=True)


def test_a_slow_host_is_picked_up_by_the_next_pull():
    old = addon.LAPTOP_CACHE, addon.LAPTOP_SSH
    d = _cache_dir()
    try:
        addon.LAPTOP_CACHE.write_text(json.dumps(_good_cache(300)), encoding="utf-8")
        answer = json.dumps({"runs": {"running": [{"id": "j-2", "tag": "new", "host": "laptop"}], "queued": []}})
        addon.LAPTOP_SSH = [sys.executable, "-c", f"import time; time.sleep(3.5); print({answer!r})"]
        t0 = time.time()
        r = addon.laptop()
        first = time.time() - t0
        assert first <= BOUND and r["runs"]["running"][0]["id"] == "j-1" and r["age_s"] >= 300, (first, r)
        time.sleep(2.5)
        r2 = addon.laptop()
        print(f"slow host: first pull {first:.1f} s (old data, age {r['age']}), later pull has the new data, age {r2['age_s']} s")
        assert r2["runs"]["running"][0]["id"] == "j-2" and r2["age_s"] <= 1, r2
        assert "pending" not in json.loads(addon.LAPTOP_CACHE.read_text(encoding="utf-8"))
    finally:
        addon.LAPTOP_CACHE, addon.LAPTOP_SSH = old
        shutil.rmtree(d, ignore_errors=True)


def test_a_failing_host_is_held_off():
    old = addon.LAPTOP_CACHE, addon.LAPTOP_SSH
    d = _cache_dir()
    try:
        addon.LAPTOP_CACHE.write_text(json.dumps(_good_cache(300)), encoding="utf-8")
        addon.LAPTOP_SSH = [sys.executable, "-c", "import sys; sys.stderr.write('ssh: connection refused\\n'); sys.exit(255)"]
        t0 = time.time()
        r = addon.laptop()
        took = time.time() - t0
        assert took <= BOUND and r["error"] == "ssh: connection refused", (took, r)
        assert r["last"]["running"][0]["progress"]["total"] == 43 and r["age_s"] >= 300, r
        addon.LAPTOP_SSH = [sys.executable, "-c", "raise SystemExit('must not start: backoff')"]
        r2 = addon.laptop()
        assert r2["error"] == "ssh: connection refused", r2
    finally:
        addon.LAPTOP_CACHE, addon.LAPTOP_SSH = old
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    test_laptop_run_has_the_build_fields_of_a_pc_run()
    test_the_laptop_reading_is_ascii_json()
    test_a_dead_host_costs_the_wait_and_keeps_the_last_data()
    test_a_slow_host_is_picked_up_by_the_next_pull()
    test_a_failing_host_is_held_off()
    print("ok")
