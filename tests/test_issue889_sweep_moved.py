"""#889 unit 2: the pin sweep keeps the pin of a job moved to another host until the moved copy is seen there."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_issue756_pin_ref_sweep import _setup, count  # noqa: E402


def _moved_pc_job(store, pin: str, new_id: str) -> None:
    job = store.submit(host="pc", priority="P1", tag="m", cmd="echo x", pin=pin[:7])
    store.move_away(job.id, to="laptop", new_id=new_id)


def test_moved_copy_not_seen_yet_keeps_the_ref(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    _moved_pc_job(store, pin, "j-X")
    daemon.remote_handback_pass()
    assert count(origin) == 1


def test_moved_copy_seen_queued_keeps_the_ref(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    copy = remote.store.submit(host="laptop", priority="P1", tag="m", cmd="echo x", pin=pin[:7])
    _moved_pc_job(store, pin, copy.id)
    daemon.remote_handback_pass()
    assert count(origin) == 1


def test_moved_copy_seen_ended_releases_the_ref(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    copy = remote.store.submit(host="laptop", priority="P1", tag="m", cmd="echo x", pin=pin[:7])
    remote.store.start(copy.id, out="o", pid=None)
    remote.store.end(copy.id, rc=0)
    _moved_pc_job(store, pin, copy.id)
    daemon.remote_handback_pass()
    assert count(origin) == 0
