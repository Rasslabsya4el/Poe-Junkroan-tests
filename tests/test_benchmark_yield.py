"""The benchmark pool honours the yield (#621): a fake build, a real ProcessPoolExecutor, a scaled clock; no PoB."""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark  # noqa: E402
import bench_yield_fakes as fakes  # noqa: E402

SCALE = 600.0  # 1 real second = 10 fake minutes: a 60-minute fake build takes 6 s
SOURCE = "20260101-0000-old's median of 1 {slug} builds"


@pytest.fixture
def scaled(monkeypatch):
    monkeypatch.setenv("JUNKROAN_BENCH_TIME_SCALE", str(SCALE))
    monkeypatch.delenv("JUNKROAN_YIELD_FILE", raising=False)


def _history(tmp_path: Path, slugs: list[str], seconds: float = 3600.0) -> Path:
    root = tmp_path / "bench_root" / "20260101-0000-old"
    (root / "rows").mkdir(parents=True)
    for slug in slugs:
        (root / "rows" / f"{slug}-s1.json").write_text(json.dumps({"slug": slug, "seconds": seconds, "ok": True}), encoding="utf-8")
    return tmp_path / "bench_root"


def _events(out_dir: Path) -> list[tuple[float, str, str]]:
    rows = [f.read_text(encoding="utf-8").split() for f in sorted((out_dir / "events").glob("*.ev"))]
    return [(float(t), kind, stem) for t, kind, stem in rows]


class Harness:
    def __init__(self, tmp_path: Path, jobs: list[tuple[benchmark.Job, int]], bench_root: Path, workers: int, schedule):
        self.out_dir = tmp_path / "run"
        (self.out_dir / "rows").mkdir(parents=True)
        (self.out_dir / "logs").mkdir()
        self.stages = {job.stem: n for job, n in jobs}
        self.jobs = [job for job, _ in jobs]
        self.bench_root = bench_root
        self.workers = workers
        self.schedule = schedule  # (harness, fake minutes since the pool started) -> how many workers to give up
        self.submitted: list[str] = []
        self.rows: list[dict] = []
        self.t_start = 0.0
        self.pool = None
        self.probes: dict = {}
        self.alive_at_end = False

    def fake_minutes(self) -> float:
        return (time.perf_counter() - self.t_start) * SCALE / 60

    def read_yield(self) -> int:
        return self.schedule(self, self.fake_minutes())

    def submit(self, job: benchmark.Job):
        self.submitted.append(job.stem)
        return self.pool.submit(fakes.fake_build, job.slug, log_path=str(self.out_dir / "logs" / f"{job.stem}.log"), seed=job.seed, n_stages=self.stages[job.stem], bench_root=str(self.bench_root), keystone=job.keystone)

    def handle(self, job: benchmark.Job, r: dict) -> list[benchmark.Job]:
        assert not r.get("deferred")
        self.rows.append(r)
        (self.out_dir / "rows" / f"{job.stem}.json").write_text(json.dumps(r), encoding="utf-8")
        return []

    def run(self) -> None:
        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            self.pool = pool
            for fut in [pool.submit(fakes.warm, i) for i in range(self.workers * 3)]:
                fut.result()  # the workers are spawned before the clock starts
            self.t_start = time.perf_counter()
            benchmark.run_pool(pool, list(self.jobs), submit=self.submit, handle=self.handle, workers=self.workers, out_dir=self.out_dir,
                               estimate_seconds=lambda slug: benchmark.estimate_build(slug, self.out_dir, None, self.bench_root)[0],
                               poll=0.02, read_yield=self.read_yield)
            self.alive_at_end = all(p.is_alive() for p in pool._processes.values())


def test_give_up_two_of_three_asks_the_nearly_done_build_then_the_youngest(tmp_path, scaled, capfd):
    old, mid, young = benchmark.Job("oldslug", 1), benchmark.Job("midslug", 1), benchmark.Job("youngslug", 1)

    def schedule(h: Harness, t: float) -> int:
        if t < 25:
            return 2  # only the old build runs
        if t < 51:
            return 1  # the mid build joins: about 30 fake minutes old when the young one is asked
        if "youngslug-s1" not in h.submitted:
            return 0  # the young build joins; held until it is really submitted, so a stalled poll loop cannot skip this step (#836)
        h.probes.setdefault("signal", time.time())
        return 2  # never released by the clock: the rerun waits for a free slot, not for a fake minute (#836)

    # mid is 70 fake minutes long and joins at 25: it ends ~35 fake minutes after old (60), so a loaded PC slowing every sleep cannot swap the two ends (#870)
    h = Harness(tmp_path, [(old, 120), (mid, 140), (young, 24)], _history(tmp_path, ["oldslug", "midslug", "youngslug"]), 3, schedule)
    h.run()
    out = capfd.readouterr().out
    assert re.search(r"deferred youngslug-s1 after .*\(about .* left; estimate: ", out)
    assert re.search(r"kept oldslug-s1 to its end \(about .* was left; estimate: ", out)
    assert "midslug" not in out  # the 30-minute build is never asked
    events = _events(h.out_dir)
    deferred_at = next(t for t, kind, stem in events if kind == "deferred" and stem == "youngslug-s1")
    assert deferred_at >= h.probes["signal"]  # the deferral answers the young build's submission; how long it took is machine speed, not asserted (#870)
    starts = [stem for _t, kind, stem in events if kind == "start"]
    assert starts == ["oldslug-s1", "midslug-s1", "youngslug-s1", "youngslug-s1"]
    old_end = next(t for t, kind, stem in events if kind == "end" and stem == "oldslug-s1")
    mid_end = next(t for t, kind, stem in events if kind == "end" and stem == "midslug-s1")
    rerun_at = [t for t, kind, stem in events if kind == "start" and stem == "youngslug-s1"][1]
    assert deferred_at < rerun_at  # the deferred build reruns only after it was deferred
    assert old_end < mid_end <= rerun_at  # slots in use: 1 once the kept build ended; the deferred build reruns after, never beside it
    assert h.submitted == starts
    assert sorted(r["slug"] for r in h.rows) == ["midslug", "oldslug", "youngslug"]  # rows = plan, the deferred attempt wrote none
    assert len(list((h.out_dir / "rows").glob("*.json"))) == 3


def test_give_up_one_of_two_asks_only_the_nearly_done_build(tmp_path, scaled, capfd):
    old, young = benchmark.Job("oldslug", 1), benchmark.Job("youngslug", 1)

    def schedule(h: Harness, t: float) -> int:
        if t < 51:
            return 1  # only the old build runs
        if "youngslug-s1" not in h.submitted:
            return 0  # the young one joins; held until it is really submitted, so a stalled poll loop cannot skip this step (#836)
        return 1 if t < 110 else 0  # asked the next poll: the old build (60 fake minutes long) has under 10 left

    h = Harness(tmp_path, [(old, 120), (young, 24)], _history(tmp_path, ["oldslug", "youngslug"]), 2, schedule)
    h.run()
    out = capfd.readouterr().out
    assert re.search(r"kept oldslug-s1 to its end \(about .* was left; estimate: ", out)
    assert "deferred" not in out and "youngslug" not in out  # the kept build frees the one slot; nothing is thrown away
    assert h.submitted == ["oldslug-s1", "youngslug-s1"]
    assert sorted(r["slug"] for r in h.rows) == ["oldslug", "youngslug"]


def test_give_up_all_idles_alive_then_refills(tmp_path, scaled, capfd):
    a, b = benchmark.Job("aslug", 1), benchmark.Job("bslug", 1)

    def schedule(h: Harness, t: float) -> int:
        if t < 4:
            return 0
        if t < 40:
            if t > 30 and "idle" not in h.probes:
                h.probes["idle"] = (len(list((h.out_dir / "rows").glob("*.json"))), all(p.is_alive() for p in h.pool._processes.values()), h.submitted[:])
            return 2
        return 0

    h = Harness(tmp_path, [(a, 40), (b, 40)], _history(tmp_path, ["aslug", "bslug"]), 2, schedule)
    h.run()
    out = capfd.readouterr().out
    assert out.count("deferred ") == 2 and "kept" not in out
    rows_while_idle, alive_while_idle, submitted_while_idle = h.probes["idle"]
    assert rows_while_idle == 0 and alive_while_idle  # alive and idle, no row, nothing killed
    assert submitted_while_idle == ["aslug-s1", "bslug-s1"]  # nothing refilled while everything was given up
    assert sorted(h.submitted) == ["aslug-s1", "aslug-s1", "bslug-s1", "bslug-s1"]  # then the pool refilled with the deferred builds
    assert sorted(r["slug"] for r in h.rows) == ["aslug", "bslug"] and h.alive_at_end


def test_no_yield_file_keeps_todays_order_and_in_flight_count(tmp_path, scaled):
    jobs = [benchmark.Job(f"s{i}", 1) for i in range(5)]
    h = Harness(tmp_path, [(job, 6) for job in jobs], _history(tmp_path, [job.slug for job in jobs]), 2, None)
    h.read_yield = benchmark.read_yield_from_env  # the real reader, no file
    h.run()
    assert h.submitted == [job.stem for job in jobs]
    events = _events(h.out_dir)
    starts = [t for t, kind, _ in events if kind == "start"]
    ends = sorted(t for t, kind, _ in events if kind == "end")
    in_flight = max(sum(1 for s in starts if s <= t) - sum(1 for e in ends if e <= t) for t in starts)  # <=: an end and the next start can share one Windows clock tick
    assert in_flight == 2
    assert not list((h.out_dir / "yield").glob("*.stop"))
    assert len(h.rows) == 5


def _signalled_build(tmp_path: Path, stage_names: list[str], est_seconds: float):
    out_dir = tmp_path / "run"
    (out_dir / "logs").mkdir(parents=True)
    (out_dir / "yield").mkdir()
    (out_dir / "yield" / "xslug-s1.stop").write_text("give up", encoding="utf-8")
    root = _history(tmp_path, ["xslug"], est_seconds)
    from junkroan.optimizer import yield_probe

    def body() -> dict:
        for name in stage_names:
            yield_probe.check(name)
        return {"ok": True}

    return benchmark.armed_build("xslug", log_path=str(out_dir / "logs" / "xslug-s1.log"), seed=1, variant="", loop_seconds=None, body=body, bench_root=root)


def test_a_build_in_the_fixed_point_check_keeps_whatever_the_estimate(tmp_path, scaled, capfd):
    r = _signalled_build(tmp_path, ["fixed point check"], 36000.0)
    out = capfd.readouterr().out
    assert r == {"ok": True}
    assert "kept xslug-s1 to its end" in out


def test_the_estimate_source_is_named_in_both_lines(tmp_path, scaled, capfd):
    r = _signalled_build(tmp_path, ["loop pass 1"], 36000.0)
    deferred = capfd.readouterr().out
    assert r["deferred"] and r["stage"] == "loop pass 1"
    assert "deferred xslug-s1 after" in deferred and "estimate: " + SOURCE.format(slug="xslug") in deferred
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    _signalled_build(tmp2, ["loop pass 1"], 60.0)  # nearly nothing left: kept
    kept = capfd.readouterr().out
    assert "kept xslug-s1 to its end" in kept and "estimate: " + SOURCE.format(slug="xslug") in kept
