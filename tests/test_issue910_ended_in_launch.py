"""#910: a job that ends INSIDE the launch code (pin failure) reaches the anomaly guard that tick (PoB-free)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import anomalies as an  # noqa: E402
from test_runs_anomalies import make_guard  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

PIN = "59923532"
WHY = f"pin {PIN} is not on this host"


def _daemon(tmp_path: Path):
    launcher = FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher)
    queue.make_snapshot = lambda name, pin: None
    queue.snapshot_failure = lambda: WHY
    guard, cli = make_guard(tmp_path)
    daemon.anomaly_guard = guard
    return daemon, store, cli, launcher


def test_five_pin_failures_in_one_tick_one_keymaster_naming_all(tmp_path: Path) -> None:
    daemon, store, cli, launcher = _daemon(tmp_path)
    jobs = [store.submit(host="pc", priority="P1", tag=f"t{n}", cmd="python scripts/benchmark.py --tag x",
                         pin=PIN, issue=865) for n in range(5)]
    daemon.tick()
    assert launcher.started == []
    assert all(store.get(j.id).state == "failed" and store.get(j.id).rc is None for j in jobs)
    assert len(cli.started) == 1
    prompt = an.build_prompt(cli.started[0][0])
    for job in jobs:
        assert job.id in prompt


def test_single_pin_failure_one_job_failed_anomaly(tmp_path: Path) -> None:
    daemon, store, cli, _ = _daemon(tmp_path)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python scripts/benchmark.py --tag x",
                       pin=PIN, issue=865)
    daemon.tick()
    assert [a.key for a, _cmd in cli.started] == [f"job_failed:{job.id}"]


def test_pytest_rc1_ended_in_launch_path_raises_none(tmp_path: Path) -> None:
    daemon, store, cli, _ = _daemon(tmp_path)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python -m pytest tests/x.py -q", issue=865)
    store.start(job.id, out=str(tmp_path / "o.out"), pid=1)
    daemon._end(job.id, rc=1, out=tmp_path / "o.out")
    daemon.tick()
    assert cli.started == []
