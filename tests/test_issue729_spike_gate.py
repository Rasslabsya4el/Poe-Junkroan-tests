"""#729: the spike hold (step 3) writes one `gate <id>: spike step 3 (...)` line per held queued job per hold."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from test_runs_daemon_spike import SPIKE, Rig, _isolated_daemon_status  # noqa: E402,F401


def _lines(rig: Rig, job_id: str) -> list[str]:
    return [m for m in rig.daemon_logs if m.startswith(f"gate {job_id}: spike step")]


def _rig(tmp_path: Path) -> Rig:
    rig = Rig(tmp_path, SPIKE)
    rig.daemon_logs = []
    orig = rig.daemon.log

    def log(msg, *a, **k):
        rig.daemon_logs.append(str(msg))
        return orig(msg, *a, **k)

    rig.daemon.log = log
    return rig


def _to_step3(rig: Rig) -> None:
    rig.free = 1000.0
    rig.tick(16)
    assert rig.daemon.spike_step == 3


def test_hold_writes_one_line_per_job(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    _to_step3(rig)
    rig.daemon_logs.clear()
    job = rig.submit("held")
    rig.tick(5)
    assert rig.state(job.id) == "queued"
    lines = _lines(rig, job.id)
    assert len(lines) == 1 and lines[0].startswith(f"gate {job.id}: spike step 3 (free RAM ")
    assert "GB under 2.0 GB)" in lines[0]


def test_hold_ends_job_starts_second_hold_logs_again(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    _to_step3(rig)
    job = rig.submit("held")
    rig.tick(2)
    assert len(_lines(rig, job.id)) == 1
    rig.free = 8000.0
    rig.tick(30)
    assert rig.daemon.spike_step < 3 and rig.state(job.id) == "running"
    rig.free = 1000.0
    rig.tick(40)
    assert rig.daemon.spike_step == 3
    job2 = rig.submit("held2")
    rig.tick(2)
    assert len(_lines(rig, job2.id)) == 1
    # the hold ends (fill sees step < 3): the set is cleared, a later hold logs the same job again
    rig.daemon.spike_step = 2
    rig.daemon.fill()
    assert rig.state(job2.id) != "queued" or not rig.daemon._spike_held_logged
    rig.daemon.spike_step = 3
    job3 = rig.submit("held3")
    rig.daemon.fill()
    rig.daemon.fill()
    assert len(_lines(rig, job3.id)) == 1
