"""#877 rule 3: failed jobs of one ticket, machine and error line within 5 minutes are ONE anomaly."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_anomalies import make_guard  # noqa: E402

BASE = datetime(2026, 10, 11, 14, 0, 0, tzinfo=timezone.utc)


def _failed(store: Store, tmp_path: Path, n: int, *, minutes: float = 0.0, issue: int = 865,
            error: str = "error: unrecognized arguments: --no-label") -> object:
    job = store.submit(host="pc", priority="P1", tag=f"t{n}", cmd="python x.py", issue=issue)
    out = tmp_path / f"{job.id}.out"
    out.write_text(f"starting {n}\n{error}\n", encoding="utf-8")
    store.start(job.id, out=str(out), pid=1)
    ended = store.end(job.id, rc=2, out=str(out))
    return replace(ended, submit_ts=(BASE + timedelta(minutes=minutes)).isoformat())


def _run(tmp_path: Path, jobs: list) -> tuple[list, an.AnomalyGuard]:
    guard, cli = make_guard(tmp_path)
    guard.check(ended_jobs=jobs)
    cli.finish_all()
    guard.check()
    cli.finish_all()
    guard.check()
    return cli.started, guard


def test_five_jobs_one_cause_one_start_prompt_names_all(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    jobs = [_failed(store, tmp_path, n, minutes=n) for n in range(5)]
    started, _ = _run(tmp_path, jobs)
    assert len(started) == 1
    prompt = an.build_prompt(started[0][0])
    for job in jobs:
        assert job.id in prompt


def test_different_error_lines_two_starts(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    jobs = [_failed(store, tmp_path, 0), _failed(store, tmp_path, 1, error="ImportError: no module foo")]
    assert len(_run(tmp_path, jobs)[0]) == 2


def test_six_minutes_apart_two_starts(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    jobs = [_failed(store, tmp_path, 0), _failed(store, tmp_path, 1, minutes=6)]
    assert len(_run(tmp_path, jobs)[0]) == 2


def test_different_ticket_two_starts(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    jobs = [_failed(store, tmp_path, 0), _failed(store, tmp_path, 1, issue=866)]
    assert len(_run(tmp_path, jobs)[0]) == 2


def _remote(job) -> dict:
    return replace(an.detect_job_failed(job), out=None).as_dict()


def test_different_machine_two_starts(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    local, remote = _failed(store, tmp_path, 0), _failed(store, tmp_path, 1)
    guard, cli = make_guard(tmp_path)
    guard.adopt_remote("laptop", [_remote(remote)], lambda key: True)
    guard.check(ended_jobs=[local])
    cli.finish_all()
    guard.check()
    cli.finish_all()
    guard.check()
    assert len(cli.started) == 2


def test_laptop_group_one_start_all_ids(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    jobs = [_failed(store, tmp_path, n, minutes=n) for n in range(4)]
    guard, cli = make_guard(tmp_path)
    guard.adopt_remote("laptop", [_remote(j) for j in jobs[:2]], lambda key: True)
    guard.adopt_remote("laptop", [_remote(j) for j in jobs[2:]], lambda key: True)  # a later pass
    cli.finish_all()
    guard.check()
    cli.finish_all()
    guard.check()
    assert len(cli.started) == 1
    anomaly = cli.started[0][0]
    assert anomaly.origin == "laptop"
    prompt = an.build_prompt(anomaly)
    for job in jobs:
        assert job.id in prompt
    import re
    assert re.match(r"^keymaster:\s*(\S+)\s+(\S+)$", f"keymaster: {anomaly.kind} {anomaly.target}")
