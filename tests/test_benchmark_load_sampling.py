"""#77: `_LoadSampler` records host mode / others-busy occupancy without touching PoB."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402


def test_sampler_records_the_modes_seen_and_the_others_busy_share(monkeypatch) -> None:
    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda: "pc")
    monkeypatch.setattr(benchmark.runs_hosts, "read_modes", lambda: {"pc": {"mode": "play"}})
    busy_results = iter([[], [{"role": "other"}], []])
    monkeypatch.setattr(benchmark.slot_budget, "busy_slots", lambda: next(busy_results))

    sampler = benchmark._LoadSampler(period=1000.0)  # long enough the timer thread never fires
    sampler.start()  # one immediate sample
    sampler._sample_once()
    sampler._sample_once()
    result = sampler.stop()

    assert result["load_modes_seen"] == ["play"]
    assert result["load_others_busy_share"] == 1 / 3


def test_sampler_never_raises_and_records_null_when_every_tick_fails(monkeypatch) -> None:
    def boom_modes():
        raise RuntimeError("modes file mid-write")

    def boom_busy():
        raise RuntimeError("lock probe failed")

    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda: "pc")
    monkeypatch.setattr(benchmark.runs_hosts, "read_modes", boom_modes)
    monkeypatch.setattr(benchmark.slot_budget, "busy_slots", boom_busy)

    sampler = benchmark._LoadSampler(period=1000.0)
    sampler.start()
    sampler._sample_once()
    result = sampler.stop()

    assert result == {"load_modes_seen": None, "load_others_busy_share": None}


def test_117_a_foreign_queue_role_slot_counts_as_busy_too(monkeypatch) -> None:
    """#117: a foreign run's `queue`-role slot is load, not only an `others`-role one.

    The row carries a `job` id that is not this build's own owner key, so it groups apart from
    self and counts as foreign regardless of its `role`.
    """

    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda: "pc")
    monkeypatch.setattr(benchmark.runs_hosts, "read_modes", lambda: {"pc": {"mode": "normal"}})
    monkeypatch.setattr(benchmark.slot_budget, "current_owner_key", lambda: "pid:1")
    busy_results = iter([
        [{"role": "queue", "job": "foreign-run", "pid": 900}],
        [],
    ])
    monkeypatch.setattr(benchmark.slot_budget, "busy_slots", lambda: next(busy_results))

    sampler = benchmark._LoadSampler(period=1000.0)
    sampler.start()
    sampler._sample_once()
    result = sampler.stop()

    assert result["load_others_busy_share"] == 1 / 2


def test_117_a_sibling_worker_of_the_same_run_is_never_counted_as_foreign(monkeypatch) -> None:
    """A slot carrying THIS build's own owner key is not load: it is this run's own worker."""

    monkeypatch.setattr(benchmark.slot_budget, "current_host", lambda: "pc")
    monkeypatch.setattr(benchmark.runs_hosts, "read_modes", lambda: {"pc": {"mode": "normal"}})
    monkeypatch.setattr(benchmark.slot_budget, "current_owner_key", lambda: "job:my-run")
    busy_results = iter([
        [{"role": "queue", "job": "my-run", "pid": 42}],
    ])
    monkeypatch.setattr(benchmark.slot_budget, "busy_slots", lambda: next(busy_results))

    sampler = benchmark._LoadSampler(period=1000.0)
    sampler.start()
    result = sampler.stop()

    assert result["load_others_busy_share"] == 0.0


def test_sampler_default_period_is_the_shared_constant() -> None:
    from junkroan.optimizer.benchmark_rows import LOAD_SAMPLE_PERIOD_SECONDS

    assert benchmark._LoadSampler()._period == LOAD_SAMPLE_PERIOD_SECONDS
