"""#862: a keymaster session whose row is `failed` is dead and never blocks the next start (no PoB, fakes only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_anomalies import make_guard, make_job  # noqa: E402


def test_failed_is_a_finished_state() -> None:
    assert "failed" in an.FINISHED_STATES


@pytest.mark.parametrize("state", ["failed", "done", "stopped"])
def test_a_dead_keymaster_row_does_not_block_the_next_start(tmp_path: Path, state: str) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=7)
    guard, launcher = make_guard(tmp_path)
    launcher.set_row(state, "idle")  # the 2026-10-10 19:35 row of session f4dc7666: failed, exit 4, idle

    assert len(guard.check(ended_jobs=[job])) == 1
    assert len(launcher.started) == 1
