"""#1118 unit 3: the daemon's busy sample carries the merge queue's share (`merge_cores`) when it is read."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from junkroan.pob import slot_budget  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402

CPUS = os.cpu_count() or 1


def _snap(busy_cores: float) -> dict[str, Any]:
    """A reading whose whole-PC busy cores come out to `busy_cores` on this host."""
    return {"cpu_pct": busy_cores / CPUS * 100.0, "free_ram_mb": 8000.0}


class FakeMergeReader:
    """Answers one scripted value per call; a value that is an Exception is raised."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[Any, float]] = []

    def __call__(self, prev: Any, now_s: float) -> tuple[float | None, dict]:
        self.calls.append((prev, now_s))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


@pytest.fixture
def busy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "busy_samples.jsonl"
    monkeypatch.setattr(slot_budget, "busy_samples_path", lambda: path)
    return path


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _daemon(tmp_path: Path, reader: Any) -> tuple[Any, list[str]]:
    daemon, _, _ = make_daemon(tmp_path)
    daemon.merge_reader = reader
    lines: list[str] = []
    daemon.log = lines.append
    return daemon, lines


def test_unreadable_merge_share_writes_whole_pc_value_and_one_log_line_per_run(
    tmp_path: Path, busy_path: Path
) -> None:
    """Acceptance row 2: no merge_cores key, busy = whole-PC value, one log line per unreadable run."""
    reader = FakeMergeReader((None, {}), (None, {}), (None, {}), (0.0, {"t": 0.0, "p": {}}), (None, {}))
    daemon, lines = _daemon(tmp_path, reader)
    t = 1_000_000.0
    for i in range(3):  # three consecutive unreadable ticks
        daemon._record_busy(_snap(9.6), t + 60.0 * i)
    assert len(lines) == 1
    rows = _rows(busy_path)
    assert len(rows) == 3
    assert all("merge_cores" not in row for row in rows)
    assert rows[-1]["busy_cores"] == pytest.approx(9.6)
    daemon._record_busy(_snap(9.6), t + 180.0)  # a good reading came in between
    assert len(lines) == 1
    daemon._record_busy(_snap(9.6), t + 240.0)  # unreadable again: a new run, a second line
    assert len(lines) == 2
    assert "merge_cores" not in _rows(busy_path)[-1]


def test_merge_share_is_subtracted_from_the_sample_the_admission_reads(
    tmp_path: Path, busy_path: Path
) -> None:
    """Acceptance row 1: PC 9.6 cores, merge trees 3.5 cores -> the row holds both, the admission reads 6.1."""
    reader = FakeMergeReader((None, {"t": 1_000_000.0, "p": {}}), (3.5, {"t": 1_000_060.0, "p": {}}))
    daemon, _ = _daemon(tmp_path, reader)
    t = 1_000_000.0
    daemon._record_busy(_snap(9.6), t)  # first tick of a merge: no baseline, the row is whole
    daemon._record_busy(_snap(9.6), t + 60.0)
    rows = _rows(busy_path)
    assert rows[-1]["busy_cores"] == pytest.approx(9.6)
    assert rows[-1]["merge_cores"] == pytest.approx(3.5)
    admitted = slot_budget.read_admission_samples(busy_path)
    assert admitted[-1] == (t + 60.0, pytest.approx(6.1))


def test_a_no_merge_tick_keeps_the_state_the_next_tick_needs(tmp_path: Path, busy_path: Path) -> None:
    """A tick with no merge (0.0) hands its state on: the next call receives the state the first one returned."""
    state_first = {"t": 1_000_000.0, "p": {1: [0.0, 1.0]}}
    reader = FakeMergeReader((0.0, state_first), (2.0, {"t": 1_000_060.0, "p": {}}))
    daemon, _ = _daemon(tmp_path, reader)
    daemon.clock = lambda: 1_000_000.0
    daemon._record_busy(_snap(5.0), 1_000_000.0)
    assert daemon._merge_prev is state_first
    daemon.clock = lambda: 1_000_060.0
    daemon._record_busy(_snap(5.0), 1_000_060.0)
    prev_second, now_second = reader.calls[1]
    assert prev_second is state_first
    assert now_second == 1_000_060.0
    assert _rows(busy_path)[-1]["merge_cores"] == pytest.approx(2.0)


def test_a_reader_that_raises_is_an_unreadable_tick(tmp_path: Path, busy_path: Path) -> None:
    reader = FakeMergeReader(RuntimeError("lock unreadable"), RuntimeError("lock unreadable"), (None, {}))
    daemon, lines = _daemon(tmp_path, reader)
    t = 1_000_000.0
    daemon._record_busy(_snap(4.0), t)
    daemon._record_busy(_snap(4.0), t + 60.0)
    rows = _rows(busy_path)
    assert len(rows) == 2 and all("merge_cores" not in row for row in rows)
    assert rows[-1]["busy_cores"] == pytest.approx(4.0)
    assert len(lines) == 1
    assert daemon._merge_prev is None


def test_merge_share_is_read_at_the_clock_of_its_own_read_not_the_snapshot_time(
    tmp_path: Path, busy_path: Path
) -> None:
    """Send-back: the load thread's snapshot time can be a tick old; merge_cores divides by the time it is given,
    so the reader gets the daemon's clock read right before its call, and the sample keeps the snapshot time."""
    reader = FakeMergeReader((None, {}))
    daemon, _ = _daemon(tmp_path, reader)
    daemon.clock = lambda: 1_000_005.0
    daemon._record_busy(_snap(9.6), 1_000_000.0)
    assert reader.calls[0][1] == 1_000_005.0
    assert _rows(busy_path)[-1]["t"] == 1_000_000.0
