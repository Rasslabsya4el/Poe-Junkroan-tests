"""#878: a live `replay_bench.py` job (quiet until its builds end) is not `job_stuck` at 46 min."""

from __future__ import annotations

import os
from pathlib import Path

from junkroan.runs import anomalies as an
from junkroan.runs.anomalies import AnomalyGuard

NOW = 1_000_000_000.0
REPLAY = "python scripts/replay_bench.py --move loop --seed 1 --workers 3 --tag b814-loop-head"
BENCH = "python scripts/benchmark.py smite --tag T"


def _out(tmp_path: Path, age_min: float) -> Path:
    out = tmp_path / "job.out"
    out.write_text("x")
    os.utime(out, (NOW - age_min * 60, NOW - age_min * 60))
    return out


def _guard(tmp_path: Path) -> AnomalyGuard:
    return AnomalyGuard(clock=lambda: NOW, bench_root=tmp_path / "bench")


def _stuck(found) -> list:
    return [a for a in found if a.kind == "job_stuck"]


def test_live_replay_at_46_min_is_not_stuck(tmp_path):
    out = _out(tmp_path, 46)
    assert _stuck(_guard(tmp_path).detect(running={"j1": str(out)}, commands={"j1": REPLAY})) == []


def test_replay_older_than_its_longest_build_is_stuck(tmp_path):
    out = _out(tmp_path, 7200 / 60 + 16)
    assert len(_stuck(_guard(tmp_path).detect(running={"j1": str(out)}, commands={"j1": REPLAY}))) == 1


def test_replay_job_whose_process_is_gone_is_not_running_and_stuck_unchanged(tmp_path):
    out = _out(tmp_path, 46)
    # a gone pid leaves the daemon's active set: no `running` entry, so no stuck row from the same call
    assert _stuck(_guard(tmp_path).detect(running={}, commands={"j1": REPLAY})) == []
    assert len(_stuck(_guard(tmp_path).detect(running={"j1": str(out)}, commands={"j1": "echo x"}))) == 1


def test_benchmark_line_unchanged(tmp_path):
    out = _out(tmp_path, 46)
    assert an.stuck_line_seconds(BENCH) == an.STUCK_OUTPUT_SECONDS
    assert len(_stuck(_guard(tmp_path).detect(running={"j1": str(out)}, commands={"j1": BENCH}))) == 1
