"""#898 unit 2: the daemon appends one whole-PC busy-cores sample per tick, on both spike_pass paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from test_runs_daemon_spike import SPIKE, STEP, Rig, snap  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "daemon-status"))
    path = tmp_path / "busy_samples.jsonl"
    monkeypatch.setattr(slot_budget, "busy_samples_path", lambda: path)
    return path


def test_one_sample_per_tick_normal_path(tmp_path: Path, _isolated: Path) -> None:
    rig = Rig(tmp_path, SPIKE)
    rig.tick(3)
    rows = slot_budget.read_busy_samples(_isolated)
    assert len(rows) == 3
    assert rows[-1][0] == rig.t
    assert rows[-1][1] == pytest.approx(20.0 / 100.0 * (os.cpu_count() or 1))
    assert [b - a for (a, _), (b, _) in zip(rows, rows[1:])] == [STEP, STEP]


def test_one_sample_per_new_reading_thread_path(
    tmp_path: Path, _isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, SPIKE)
    monkeypatch.setattr(daemon_mod.Daemon, "load_thread_running", True)
    rig.daemon._load_latest = (5.0, snap(8000.0))
    rig.daemon.spike_pass()
    rig.daemon.spike_pass()  # the same reading again: not observed twice
    assert slot_budget.read_busy_samples(_isolated) == [(5.0, pytest.approx(0.2 * (os.cpu_count() or 1)))]
    rig.daemon._load_latest = (35.0, snap(8000.0))
    rig.daemon.spike_pass()
    assert [t for t, _ in slot_budget.read_busy_samples(_isolated)] == [5.0, 35.0]


def test_nothing_older_than_20_min_after_30_min_of_ticks(tmp_path: Path, _isolated: Path) -> None:
    rig = Rig(tmp_path, SPIKE)
    for _ in range(30):  # 30 minutes at one tick a minute
        rig.tick()
        rows = slot_budget.read_busy_samples(_isolated)
        assert rows and min(t for t, _ in rows) >= rig.t - 1200.0
    assert len(slot_budget.read_busy_samples(_isolated)) == 21


def test_append_failure_never_breaks_the_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, SPIKE)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(slot_budget, "append_busy_sample", boom)
    rig.tick(2)
    assert rig.readers == 2
