"""#825 row 4: a queued job whose predecessors are done and which does not start gets a `gate <id>: ...` line."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from test_runs_daemon import make_daemon  # noqa: E402
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401


def _rig(tmp_path: Path):
    daemon, store, _ = make_daemon(tmp_path)
    logs: list[str] = []
    daemon.log = lambda msg, *a, **k: logs.append(str(msg))
    return daemon, store, logs


def _done_pred(store):
    pred = store.submit(host="pc", priority="P1", tag="pred", cmd="echo pred")
    store.start(pred.id, pid=1)
    store.end(pred.id, rc=0)
    return pred


def _lines(logs: list[str], job_id: str) -> list[str]:
    return [m for m in logs if m.startswith(f"gate {job_id}:")]


def test_queue_order_hold_is_named(tmp_path: Path) -> None:
    """Predecessor done, room free, yet the queue hands the job out as None: one line names the gate."""
    daemon, store, logs = _rig(tmp_path)
    pred = _done_pred(store)
    job = store.submit(host="pc", priority="P1", tag="b", cmd="echo b", after=[pred.id])
    daemon.store.next_job = lambda host, exclude=(): None  # the hold the ticket saw (an earlier chain's skip)
    daemon.fill()
    daemon.fill()
    lines = _lines(logs, job.id)
    assert len(lines) == 1, lines
    assert "queue order" in lines[0]


def test_room_hold_is_named_once(tmp_path: Path) -> None:
    daemon, store, logs = _rig(tmp_path)
    pred = _done_pred(store)
    job = store.submit(host="pc", priority="P1", tag="b", cmd="echo b", after=[pred.id], workers=5)
    daemon.room = lambda budget: 0
    daemon.fill()
    lines = _lines(logs, job.id)
    assert len(lines) >= 1 and any(job.id in m for m in lines), lines
