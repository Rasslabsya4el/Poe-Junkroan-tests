"""#751 unit 4a: the new filler pass at the daemon boundary (rows 1-3; no PoB, every reader stubbed)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from junkroan.runs import daemon as daemon_mod

from tests.test_runs_daemon import make_daemon

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # a Wednesday: no cut folder -> rule 4 commands


def rig(tmp_path: Path, *, cores: int = 12, mem_gb: float = 4 + 5 * 1.4, cpu: float = 0.0,
        per_worker: float | None = 1.4, switch: bool = True, mode: str = "normal"):
    cfg = {"pc": {"ram_per_worker_gb": per_worker} if per_worker else {}, "laptop": {}}
    d, store, _q = make_daemon(tmp_path, hosts_config=cfg)
    d.timestamp = lambda: NOW
    d._cut_repo = tmp_path / "repo"  # no artifacts/benchmark there: no cut in force
    d.fillers = object()
    d.filler_switch = lambda: switch
    d._mode_name = lambda: mode
    d._ram_reader = lambda: mem_gb
    d.filler_cpu_share = lambda: cpu
    d.filler_cores = lambda: cores
    d.filler_main_sha = lambda: "a" * 40
    d.filler_missing = lambda folder: []
    return d, store


def fillers_of(store):
    return [j for j in store.jobs() if j.is_filler]


def test_row1_three_free_slots_three_fillers(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 3  # 3 free slots of the mode
    out = d.filler_pass()
    jobs = fillers_of(store)
    assert len(out) == 3 and len(jobs) == 3
    assert {j.job_class for j in jobs} == {"filler"} and {j.workers for j in jobs} == {1}
    assert all(j.pin == "a" * 40 and j.note.startswith("filler-key:") for j in jobs)
    assert len({j.note for j in jobs}) == 3


def test_row2_other_job_mode_switch_give_zero(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 3
    store.submit(host="pc", priority="P2", tag="other", cmd="python scripts/benchmark.py --tag o")
    assert d.filler_pass() == []
    (tmp_path / "play").mkdir()
    d2, store2 = rig(tmp_path / "play", mode="play")
    d2.room = lambda b=None: 3
    assert d2.filler_pass() == [] and fillers_of(store2) == []
    (tmp_path / "off").mkdir()
    d3, store3 = rig(tmp_path / "off", switch=False)
    d3.room = lambda b=None: 3
    assert d3.filler_pass() == [] and fillers_of(store3) == []
    assert fillers_of(store) == []


def test_row2_a_job_of_the_other_host_does_not_stop_this_one(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 3
    store.submit(host="laptop", priority="P2", tag="other", cmd="python scripts/benchmark.py --tag o")
    assert len(d.filler_pass()) == 3


def test_row3_cpu_share_080_on_12_cores_gives_two(tmp_path: Path) -> None:
    d, store = rig(tmp_path, cpu=0.80)
    d.room = lambda b=None: 5
    assert len(d.filler_pass()) == 2 and len(fillers_of(store)) == 2


def test_no_ram_per_worker_number_starts_none(tmp_path: Path) -> None:
    d, store = rig(tmp_path, per_worker=None)
    d.room = lambda b=None: 5
    assert d.filler_pass() == [] and fillers_of(store) == []


def test_spike_step_one_starts_none(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 5
    d.spike_step = 1
    assert d.filler_pass() == [] and fillers_of(store) == []


def test_keys_of_the_other_host_are_not_made_twice(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 5
    first = d.filler_pass()
    assert len(first) == 5
    keys = {j.note for j in fillers_of(store)}
    # a second pass finds the first five queued as fillers (not "other" jobs) and picks 5 different ones
    d.room = lambda b=None: 5
    d.filler_pass()
    notes = [j.note for j in fillers_of(store)]
    assert len(notes) == len(set(notes)) == 10 and keys < set(notes)


# -- unit 4b: giving way (rule 5), restart adopts (rule 6), the early-warning tail (rule 4), 4a's two gaps ----

from junkroan.runs import weekly_fillers  # noqa: E402
from tests.test_runs_daemon import FakeLauncher  # noqa: E402


def live_rig(tmp_path: Path, n: int, *, cmd: str = "echo f"):
    launcher = FakeLauncher()
    d, store, _q = make_daemon(tmp_path, launcher=launcher)
    d.timestamp = lambda: NOW
    d._mode_name = lambda: "normal"
    d.killed = []
    d._spike_killer = lambda pid: d.killed.append(pid) or True
    ids = [store.submit(host="pc", priority="P2", tag=f"filler-{i}", cmd=f"{cmd} {i}", workers=1,
                        job_class="filler").id for i in range(n)]
    assert len(d.fill()) == n
    return d, store, launcher, ids


@pytest.mark.parametrize("priority", ["P1", "P2"])
def test_row6_three_fillers_killed_next_tick_job_started_after(tmp_path: Path, priority: str) -> None:
    d, store, _l, ids = live_rig(tmp_path, 3)
    job = store.submit(host="pc", priority=priority, tag="j", cmd="echo j", workers=1)
    d.tick()
    assert len(d.killed) == 3  # three process trees killed
    assert [store.get(i).state for i in ids] == ["stopped"] * 3
    assert all(store.get(i).rc is None for i in ids)  # no row file is written by a killed filler
    d.tick()
    assert store.get(job.id).state == "running"
    assert len(d.killed) == 3


def test_mode_away_from_normal_kills_fillers(tmp_path: Path) -> None:
    d, store, _l, ids = live_rig(tmp_path, 2)
    d.tick()
    assert [store.get(i).state for i in ids] == ["running"] * 2 and d.killed == []
    d._mode_name = lambda: "play"
    d.tick()
    assert [store.get(i).state for i in ids] == ["stopped"] * 2 and len(d.killed) == 2


def test_a_queued_filler_sibling_is_not_another_job(tmp_path: Path) -> None:
    d, store, _l, ids = live_rig(tmp_path, 1)
    store.submit(host="pc", priority="P2", tag="filler-q", cmd="echo q", workers=1, job_class="filler")
    assert d.preempt_fillers_pass() == [] and store.get(ids[0]).state == "running"


def test_row7_restart_adopts_two_fillers_stops_none(tmp_path: Path) -> None:
    d, store, launcher, ids = live_rig(tmp_path, 2)
    respawned: list[int] = []
    d._respawn = lambda: respawned.append(1)

    class Watch:
        def due(self):
            return ("a" * 40, "b" * 40)

    d._restart_watch = Watch()
    report = daemon_mod.TickReport()
    d._restart_gate(report)  # fillers do not hold the restart
    assert report.restarting and respawned == [1] and d.killed == []
    d2, store2, _q = make_daemon(tmp_path, launcher=launcher)
    d2.killed = []
    d2._spike_killer = lambda pid: d2.killed.append(pid) or True
    assert d2.recover() == []
    assert sorted(d2._active) == sorted(ids) and d2.killed == []
    assert [store2.get(i).state for i in ids] == ["running"] * 2


def finished_warn(store, launcher, d, tag: str, rc: int, week: str = "20261019"):
    job = store.submit(host="pc", priority="P2", tag=tag, workers=1, job_class="filler",
                       cmd=f"python scripts/benchmark.py x --seed 1 --tag warn-{week}")
    d.fill()
    launcher.finish(int(store.get(job.id).pid), rc)
    d.reap()
    return job


def test_early_warning_runs_once_with_week_after_warn_rc0_only(tmp_path: Path) -> None:
    d, store, launcher = live_rig(tmp_path, 0)[:3]
    calls: list[str] = []
    d.early_warning_runner = calls.append
    finished_warn(store, launcher, d, "filler-a", 1)
    assert calls == []
    cut = store.submit(host="pc", priority="P2", tag="filler-cut", cmd="python scripts/benchmark.py --resume f --row s1",
                       workers=1, job_class="filler")
    d.fill()
    launcher.finish(int(store.get(cut.id).pid), 0)
    d.reap()
    assert calls == []
    finished_warn(store, launcher, d, "filler-b", 0)
    assert calls == ["20261019"]


def test_warn_n_done_counts_finished_warn_jobs_of_this_week(tmp_path: Path) -> None:
    d, store = rig(tmp_path)
    d.room = lambda b=None: 1
    d.early_warning_runner = lambda week: None
    d.filler_cpu_share = lambda: 0.0
    launcher = d.launcher
    for i in range(3):
        finished_warn(store, launcher, d, f"filler-done{i}", 0)
    finished_warn(store, launcher, d, "filler-other-week", 0, week="20261012")
    out = d.filler_pass()
    assert len(out) == 1
    slug, seed = weekly_fillers.warn_rows(NOW.date(), 3)[0]
    assert store.get(out[0]).note == f"filler-key:{slug}:{seed}"


def test_missing_stems_cached_60s_and_dropped_by_a_finished_filler(tmp_path: Path) -> None:
    d, store, launcher, _ids = live_rig(tmp_path, 0)
    now = [1000.0]
    d.clock = lambda: now[0]
    reads: list[Path] = []
    d.filler_missing = lambda folder: reads.append(folder) or ["s1"]
    folder = tmp_path / "week"
    assert d._missing_cached(folder) == ["s1"] and d._missing_cached(folder) == ["s1"]
    assert len(reads) == 1
    now[0] += 61
    d._missing_cached(folder)
    assert len(reads) == 2
    d.early_warning_runner = lambda week: None
    finished_warn(store, launcher, d, "filler-x", 0)
    d._missing_cached(folder)
    assert len(reads) == 3
