"""#595: a benchmark.py job's logs/ files count as its output for the stuck check."""

from __future__ import annotations

import os
from pathlib import Path

from junkroan.runs.anomalies import AnomalyGuard, detect_job_stuck

NOW = 1_000_000_000.0
BENCH = "python scripts/benchmark.py smite --tag T"


def _touch(path: Path, age_min: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    t = NOW - age_min * 60
    os.utime(path, (t, t))


def _setup(tmp_path: Path, out_age: float, log_age: float) -> tuple[Path, Path]:
    out = tmp_path / "job.out"
    _touch(out, out_age)
    root = tmp_path / "bench"
    _touch(root / "20261006-1847-T" / "logs" / "x.log", log_age)
    return out, root


def test_fresh_log_means_not_stuck(tmp_path):
    out, root = _setup(tmp_path, 50, 1)
    assert detect_job_stuck("j1", out, now=NOW, command=BENCH, bench_root=root) is None


def test_ablation_dir_counts(tmp_path):
    out = tmp_path / "job.out"
    _touch(out, 50)
    root = tmp_path / "bench"
    _touch(root / "20261006-1847-T-no-foo" / "logs" / "x.log", 1)
    assert detect_job_stuck("j1", out, now=NOW, command="python scripts/benchmark.py a --tag=T", bench_root=root) is None


def test_both_old_is_stuck(tmp_path):
    out, root = _setup(tmp_path, 50, 50)
    anomaly = detect_job_stuck("j1", out, now=NOW, command=BENCH, bench_root=root)
    assert anomaly is not None and anomaly.kind == "job_stuck"


def test_other_tag_does_not_count(tmp_path):
    out, root = _setup(tmp_path, 50, 1)
    anomaly = detect_job_stuck("j1", out, now=NOW, command="python scripts/benchmark.py a --tag U", bench_root=root)
    assert anomaly is not None


def test_non_benchmark_command_unchanged(tmp_path):
    out, root = _setup(tmp_path, 50, 1)
    anomaly = detect_job_stuck("j1", out, now=NOW, command="python scripts/replay_bench.py --tag T", bench_root=root)
    assert anomaly is not None and anomaly.kind == "job_stuck"


def test_missing_root_never_raises(tmp_path):
    out = tmp_path / "job.out"
    _touch(out, 50)
    anomaly = detect_job_stuck("j1", out, now=NOW, command=BENCH, bench_root=tmp_path / "nope")
    assert anomaly is not None


def test_detect_method_path(tmp_path):
    out, root = _setup(tmp_path, 50, 1)
    guard = AnomalyGuard(path=tmp_path / "anomalies.json", clock=lambda: NOW, bench_root=root)
    found = guard.detect(running={"j1": str(out)}, commands={"j1": BENCH})
    assert not [a for a in found if a.kind == "job_stuck"]
    found = guard.detect(running={"j1": str(out)}, commands={"j1": "python scripts/other_job.py --tag T"})
    assert [a for a in found if a.kind == "job_stuck"]


def test_a_longer_tag_sharing_the_prefix_does_not_count(tmp_path: Path) -> None:
    """Tag `T` must not read the logs of a live run tagged `T2` (exact tag or `-no-<ablate>` only)."""
    import os

    from junkroan.runs.anomalies import detect_job_stuck

    now = 1_000_000.0
    out = tmp_path / "job.out"
    out.write_text("")
    os.utime(out, (now - 50 * 60, now - 50 * 60))
    log = tmp_path / "bench" / "20261006-1847-T2" / "logs" / "x.log"
    log.parent.mkdir(parents=True)
    log.write_text("x")
    os.utime(log, (now - 60, now - 60))
    found = detect_job_stuck("j1", out, now=now, command="python scripts/benchmark.py smite --tag T",
                             bench_root=tmp_path / "bench")
    assert found is not None and found.kind == "job_stuck"
