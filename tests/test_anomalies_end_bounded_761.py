"""#761: a tick of the anomaly guard never waits on ending finished keymaster sessions."""

from __future__ import annotations

import sys
import threading
import time
from timing_bound import bound
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402


class SlowEndLauncher:
    def __init__(self, count: int, end_seconds: float) -> None:
        self.rows = [{"name": f"keymaster: job_failed j-{i}", "id": f"km-{i}", "state": "done"} for i in range(count)]
        self.end_seconds = end_seconds
        self.ended: list[str] = []
        self._lock = threading.Lock()
        self.cancelled = threading.Event()

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.rows]

    def end(self, row: dict) -> bool:
        if self.cancelled.wait(self.end_seconds):
            return False                        # test over: no event is appended (#827)
        with self._lock:
            self.ended.append(row["id"])
            self.rows = [r for r in self.rows if r["id"] != row["id"]]
        return True


def _guard(tmp_path: Path, launcher: SlowEndLauncher) -> an.AnomalyGuard:
    return an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=launcher,
                           log=lambda message: None, probe_interval=0.0)


def test_one_tick_with_many_slow_ends_returns_under_the_bound(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    launcher = SlowEndLauncher(80, 1.0)
    guard = _guard(tmp_path, launcher)
    started = time.monotonic()
    try:
        guard.check()
        took = time.monotonic() - started
    finally:
        # #827: the keymaster-end thread would go on ending the other ~79 sessions for ~80 s and append
        # a keymaster_ended event to whatever test's JUNKROAN_RUNS_EVENTS is current by then.
        launcher.cancelled.set()
        guard.drain_ends()
    # bound = max(floor, factor x a CPU spin timed here): load that slows the spin slows the call (#824)
    bound_s = bound(2.0, 13.0)
    assert took < bound_s, (took, bound_s)
    assert len(launcher.ended) < 80


def test_every_session_is_ended_exactly_once_over_many_ticks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JUNKROAN_RUNS_EVENTS", str(tmp_path / "events.jsonl"))
    launcher = SlowEndLauncher(80, 0.05)
    guard = _guard(tmp_path, launcher)
    for _ in range(40):
        guard.check()
    guard.drain_ends()
    assert sorted(launcher.ended) == sorted(f"km-{i}" for i in range(80))
    assert len(launcher.ended) == len(set(launcher.ended)) == 80
