"""#458: a failed keymaster start is logged once per key and retried at most every 10 min."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_anomalies import FakeKeymasterCli, make_job  # noqa: E402

DISCLAIMER = ("claude --bg for X failed: --bg with bypassPermissions requires accepting the "
              "disclaimer first. ...")


class FailingCli(FakeKeymasterCli):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0
        self.fail = True

    def start(self, anomaly):
        self.attempts += 1
        if self.fail:
            raise RuntimeError(DISCLAIMER)
        return super().start(anomaly)


def _guard(tmp_path, cli, now, logs):
    return an.AnomalyGuard(
        path=tmp_path / "anomalies.json", launcher=cli, clock=lambda: now[0],
        log=logs.append, probe_interval=0.0,
    )


def test_failed_start_logs_once_and_backs_off_ten_minutes(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1)
    cli, logs, now = FailingCli(), [], [0.0]
    guard = _guard(tmp_path, cli, now, logs)

    def tick(ended=()):
        guard.check(ended_jobs=ended)

    now[0] = 0.0
    tick([job])
    for t in range(12, 600, 12):  # 12 .. 588
        now[0] = float(t)
        tick()
    assert cli.attempts == 1
    assert sum("could not start" in line for line in logs) == 1

    now[0] = 600.0
    tick()
    assert cli.attempts == 2
    assert sum("could not start" in line for line in logs) == 1
    assert len(an._read_state(guard.path).queue) == 1  # still queued at the head

    # the next due attempt succeeds
    cli.fail = False
    now[0] = 1199.0
    tick()
    assert cli.attempts == 2  # not due yet
    now[0] = 1200.0
    tick()
    assert cli.attempts == 3
    assert any("keymaster session" in line and "started for" in line for line in logs)
    assert an._read_state(guard.path).queue == []
    assert guard._start_failed_at == {}

    # a new failure of the same key logs once again
    anomaly = an.detect_job_failed(job)
    state = an._read_state(guard.path)
    state.queue.append(anomaly)
    an._write_state(guard.path, state)
    cli.fail = True
    cli._sessions = []
    now[0] = 1300.0
    tick()
    assert sum("could not start" in line for line in logs) == 2
