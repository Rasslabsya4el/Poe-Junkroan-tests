"""#729 unit 2: a job held by the PC's spike hold (step >= 3) moves to the laptop without the 15 min wait."""

from __future__ import annotations

from pathlib import Path

from tests.test_runs_rebalance import CMD, _fill_pc, age, rig


def test_729_spike_step_3_moves_at_first_step(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = store.submit(host="pc", priority="P2", tag="held", cmd=CMD, workers=1)
    daemon.spike_step = 3
    age(daemon, job, 20 / 60)
    daemon.tick()
    assert calls["submit"] == 1 and len(laptop.jobs()) == 1
    assert store.get(job.id).state == "cancelled"


def test_729_below_step_3_keeps_15_minutes(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, workers=1)
    daemon.spike_step = 2
    age(daemon, job, 14)
    daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0
    age(daemon, job, 16)
    daemon.tick()
    assert calls["submit"] == 1 and store.get(job.id).state == "cancelled"
