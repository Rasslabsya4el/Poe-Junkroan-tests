"""#760 unit 2: the runs daemon records the machine's load every 30 s and shows it on a failed job (PoB-free)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.test_runs_daemon import (  # noqa: F401  (the autouse fixture must be in this module too)
    FakeGh, FakeLauncher, _isolated_daemon_status, make_daemon,
)


def snap(ts: datetime, cpu: float = 50.0, free: float = 12288.0, claude: int = 4) -> dict:
    return {
        "ts": ts.isoformat(timespec="seconds"), "free_ram_mb": free, "total_ram_mb": 32000.0, "cpu_pct": cpu,
        "groups": {"pob_counted": {"count": 2}, "pob_filler": {"count": 1}, "claude": {"count": claude}},
        "whole_suite_pytest": 3, "merge_suite_pytest": 1, "whole_suite_list": [],
    }


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def wire(tmp_path: Path, reader, **kw):
    clock = Clock()
    logs: list[str] = []
    gh = kw.pop("gh", FakeGh())
    daemon, store, _ = make_daemon(tmp_path, gh=gh, **kw)
    daemon.clock = clock
    daemon.log = logs.append
    daemon._spike_reader = reader
    daemon._load_samples_path = tmp_path / "load_samples.jsonl"
    daemon._rebalancer = type("R", (), {"step": lambda self: None})()
    return daemon, store, clock, logs


def lines(tmp_path: Path) -> list[dict]:
    p = tmp_path / "load_samples.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_row1_five_minutes_of_ticks_append_a_sample_every_30_s(tmp_path: Path) -> None:
    calls: list[float] = []
    daemon, _, clock, _ = wire(tmp_path, lambda pids, prev: (calls.append(clock.t), snap(datetime.now()))[1])
    for _ in range(31):  # ticks every 10 s for 5 min
        daemon.tick()
        clock.t += 10
    assert len(lines(tmp_path)) >= 9
    gaps = [b - a for a, b in zip(calls, calls[1:])]
    assert gaps and max(gaps) <= 30


def test_row2_one_snapshot_error_is_one_log_line_and_the_next_tick_appends(tmp_path: Path) -> None:
    state = {"n": 0}

    def reader(pids, prev):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("psutil gone")
        return snap(datetime.now())

    daemon, store, clock, logs = wire(tmp_path, reader)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="echo x", issue=None)
    before = store.get(job.id)
    daemon.load_record_pass()
    assert len([m for m in logs if "load record" in m]) == 1 and not lines(tmp_path)
    clock.t += 10
    daemon.load_record_pass()
    assert len(lines(tmp_path)) == 1
    assert store.get(job.id) == before


def test_the_ladder_snapshot_is_shared_not_taken_twice(tmp_path: Path) -> None:
    daemon, _, clock, _ = wire(tmp_path, lambda pids, prev: snap(datetime.now()))
    taken = []
    daemon._spike_reader = lambda pids, prev: (taken.append(1), snap(datetime.now()))[1]
    daemon._spike_loaded = True
    from junkroan.runs import spike as spike_mod
    daemon._spike_ladder = spike_mod.Ladder(spike_mod.Lines.from_config(
        {"ram_free_mb_hard": 1000, "cpu_pct_soft": 99, "window_s": 300}))
    daemon.spike_pass()
    daemon.load_record_pass()
    assert len(taken) == 1 and len(lines(tmp_path)) == 1


def _fail_a_job(tmp_path: Path, daemon, store, launcher: FakeLauncher, gh: FakeGh):
    job = store.submit(host="pc", priority="P1", tag="t", cmd="echo x", issue=760)
    daemon.tick()
    launcher.finish(launcher.started[-1]["pid"], 1)
    daemon.tick()
    return store.get(job.id)


def _end_local(job) -> datetime:
    return datetime.fromisoformat(job.end_ts).astimezone().replace(tzinfo=None)


def test_row4_failed_job_comment_has_the_load_line_or_no_sample(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, clock, _ = wire(tmp_path, lambda p, q: snap(datetime.now()), launcher=launcher, gh=gh)
    daemon._load_samples_path = tmp_path / "far.jsonl"  # keep the sampler's own lines out of this test
    daemon.load_record_pass = lambda: None
    job = _fail_a_job(tmp_path, daemon, store, launcher, gh)
    assert job.state == "failed"
    from junkroan.runs import load_record
    # a sample 20 s before the end
    load_record.append_sample(daemon._load_samples_path, snap(_end_local(job) - timedelta(seconds=20), cpu=91.0, free=5120, claude=9))
    body = daemon.comment_body(job)
    assert "CPU 91%, free RAM 5.0 GB, PoB 3, pytest 4, claude 9" in body
    # newest sample 5 min old
    daemon._load_samples_path = tmp_path / "old.jsonl"
    load_record.append_sample(daemon._load_samples_path, snap(_end_local(job) - timedelta(minutes=5)))
    assert "Load at its end: no load sample" in daemon.comment_body(job)
    # unreadable file never raises
    daemon._load_samples_path = tmp_path  # a directory
    assert "no load sample" in daemon.comment_body(job)


def test_row4_a_done_job_comment_has_no_load_line(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, clock, _ = wire(tmp_path, lambda p, q: snap(datetime.now()), launcher=launcher, gh=gh)
    daemon.load_record_pass = lambda: None
    job = store.submit(host="pc", priority="P1", tag="t", cmd="echo x", issue=760)
    daemon.tick()
    launcher.finish(launcher.started[-1]["pid"], 0)
    daemon.tick()
    done = store.get(job.id)
    assert done.state == "done"
    assert "Load at its end" not in daemon.comment_body(done)


def test_trim_runs_once_a_day_by_the_injected_clock(tmp_path: Path) -> None:
    daemon, _, clock, _ = wire(tmp_path, lambda p, q: snap(datetime.now()))
    now = datetime(2026, 10, 10, 12, 0, 0)
    daemon.timestamp = lambda: now
    from junkroan.runs import load_record
    for d in (20, 1):
        load_record.append_sample(daemon._load_samples_path, snap(now - timedelta(days=d)))
    daemon.load_record_pass()  # first pass trims
    assert [r["ts"][:10] for r in lines(tmp_path)][0] == "2026-10-09"
    load_record.append_sample(daemon._load_samples_path, snap(now - timedelta(days=30)))
    clock.t += 3600
    daemon.load_record_pass()  # same day: no trim, the old line stays
    assert any(r["ts"].startswith("2026-09-10") for r in lines(tmp_path))
    clock.t += 86400
    daemon.load_record_pass()
    assert not any(r["ts"].startswith("2026-09-10") for r in lines(tmp_path))


def test_768_row1_a_slow_reading_keeps_a_line_every_30_s(tmp_path: Path) -> None:
    """#768: the reading takes 15 s, the other work of a tick 12 s, `run` sleeps 10 s: 10 min of the loop
    still give >= 18 lines and no gap over 45 s (before: a line every 37 s, 17 lines)."""

    stamps: list[float] = []

    def reader(pids, prev):
        stamps.append(clock.t)
        clock.t += 15
        return snap(datetime.now())

    daemon, _, clock, _ = wire(tmp_path, reader)
    start = clock.t
    daemon.reap = lambda: (setattr(clock, "t", clock.t + 12), [])[1]  # the tick's other work
    daemon.write_status = lambda **kw: None
    daemon.recover = lambda: None

    def sleep(seconds: float) -> None:
        clock.t += seconds
        if clock.t - start >= 600:
            raise SystemExit  # ten minutes are up

    with pytest.raises(SystemExit):
        daemon.run(sleep=sleep)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) >= 18 and max(gaps) <= 45, (len(stamps), gaps)


def test_768_a_failed_reading_is_retried_next_tick_not_spun(tmp_path: Path) -> None:
    def reader(pids, prev):
        raise RuntimeError("psutil gone")

    daemon, _, clock, logs = wire(tmp_path, reader)
    daemon.load_record_pass()
    assert daemon.seconds_to_load_sample() == 10.0
    assert len([m for m in logs if "load record" in m]) == 1


# -- #768 unit 2: the load record on its own thread --------------------------------------------------------

class _Alive:
    """Stands for a running load thread: `tick` and `spike_pass` see it, nothing really runs."""

    def is_alive(self) -> bool:
        return True


def test_768b_a_blocked_tick_does_not_stop_the_load_thread_lines(tmp_path: Path) -> None:
    """#768 unit 2: the reading takes 15 s, the tick is blocked 60 s at a time by a slow remote pass; the
    load thread (driven here as `load_record_step` on the fake clock, never waiting for the tick) still
    gives >= 18 lines in 10 min with no gap over 45 s (before: the tick's own call, a line per 60 s)."""

    stamps: list[float] = []
    busy = {"thread_until": 0.0, "tick_until": 0.0}

    def reader(pids, prev):
        stamps.append(clock.t)
        busy["thread_until"] = clock.t + 15  # the reading itself takes 15 s
        return snap(datetime.now())

    daemon, _, clock, _ = wire(tmp_path, reader)
    daemon._load_thread = _Alive()  # the tick leaves the reading to the thread

    def slow_remote() -> list:
        busy["tick_until"] = clock.t + 60
        return []

    daemon.remote_handback_pass = slow_remote
    start = clock.t
    ticks = 0
    for second in range(600):
        clock.t = start + second
        if clock.t >= busy["tick_until"]:
            daemon.tick()
            ticks += 1
        if clock.t >= busy["thread_until"]:
            daemon.load_record_step()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert ticks <= 10  # the tick really was blocked
    assert len(lines(tmp_path)) >= 18 and max(gaps) <= 45, (len(lines(tmp_path)), gaps)
    assert len(lines(tmp_path)) == len(stamps)  # one reading, one line; the tick read nothing


def test_768b_only_one_reading_is_in_flight(tmp_path: Path) -> None:
    taken = {"n": 0, "nested": []}

    def reader(pids, prev):
        taken["n"] += 1
        taken["nested"].append(daemon.load_record_step())  # another caller while this reading runs
        return snap(datetime.now())

    daemon, _, clock, _ = wire(tmp_path, reader)
    assert daemon.load_record_step() is True
    assert taken == {"n": 1, "nested": [False]} and len(lines(tmp_path)) == 1
    assert daemon.load_record_step() is True  # the guard is released; not due yet, so no second reading
    assert taken["n"] == 1


def test_768b_a_failing_reader_still_writes_one_log_line_and_the_thread_survives(tmp_path: Path) -> None:
    def reader(pids, prev):
        raise RuntimeError("psutil gone")

    daemon, store, clock, logs = wire(tmp_path, reader)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="echo x", issue=None)
    before = store.get(job.id)
    daemon.load_record_step()
    assert len([m for m in logs if "load record" in m]) == 1 and not lines(tmp_path)
    clock.t += 10  # the retry is one per tick, never a spin
    daemon.load_record_step()
    assert len([m for m in logs if "load record" in m]) == 2
    assert store.get(job.id) == before


def test_768b_the_ladder_observes_the_threads_reading_and_reads_nothing_itself(tmp_path: Path) -> None:
    from junkroan.runs import spike as spike_mod
    taken: list[float] = []
    daemon, _, clock, _ = wire(tmp_path, lambda pids, prev: (taken.append(clock.t), snap(datetime.now()))[1])
    daemon._spike_loaded = True
    daemon._spike_ladder = spike_mod.Ladder(spike_mod.Lines.from_config(
        {"ram_free_mb_hard": 1000, "cpu_pct_soft": 99, "window_s": 300}))
    observed: list[float] = []
    real = daemon._spike_ladder.observe
    daemon._spike_ladder.observe = lambda s, now: (observed.append(now), real(s, now))[1]
    daemon._load_thread = _Alive()
    daemon.spike_pass()
    assert not taken and not observed  # no reading yet: the ladder waits
    daemon.load_record_step()
    daemon.spike_pass()
    daemon.spike_pass()  # the same reading is observed once
    assert len(taken) == 1 and observed == [clock.t] and len(lines(tmp_path)) == 1


def test_768b_the_real_thread_starts_takes_a_line_and_stops(tmp_path: Path) -> None:
    daemon, _, clock, _ = wire(tmp_path, lambda pids, prev: snap(datetime.now()))
    daemon.start_load_thread()
    try:
        assert daemon.load_thread_running
        deadline = time.monotonic() + 5
        while not lines(tmp_path) and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        daemon.stop_load_thread(timeout=5)
    assert len(lines(tmp_path)) == 1 and not daemon.load_thread_running
