"""#422: a deliberate stop (or a cancel) of an `--after` predecessor is not an anomaly for its followers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402


def _pair(store: Store, how: str):
    first = store.submit(host="pc", priority="P2", tag="pred", cmd="echo a", issue=422)
    second = store.submit(host="pc", priority="P2", tag="follower", cmd="echo b", after=[first.id])
    if how == "cancelled":
        store.cancel(first.id)
    else:
        store.start(first.id)
        if how == "stopped":
            store.stop(first.id, reason="stopped by brain")
        else:
            store.end(first.id, rc=3)
    return store.get(first.id), second


def test_stopped_predecessor_raises_nothing_and_comment_names_follower(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path)
    first, second = _pair(store, "stopped")
    assert an.detect_held_by_failed_predecessor(second, first) is None
    assert store.next_job("pc") is None                      # the hold is unchanged
    body = daemon.comment_body(first)
    assert second.id in body
    assert f"runs.py requeue {first.id}" in body and f"runs.py cancel {second.id}" in body
    print(body)


def test_failed_predecessor_still_raises_one_anomaly(tmp_path: Path) -> None:
    _, store, _ = make_daemon(tmp_path)
    first, second = _pair(store, "failed")
    anomaly = an.detect_held_by_failed_predecessor(second, first)
    assert anomaly is not None and anomaly.kind == "held_by_failed_predecessor"


def test_cancelled_predecessor_raises_nothing(tmp_path: Path) -> None:
    _, store, _ = make_daemon(tmp_path)
    first, second = _pair(store, "cancelled")
    assert an.detect_held_by_failed_predecessor(second, first) is None
