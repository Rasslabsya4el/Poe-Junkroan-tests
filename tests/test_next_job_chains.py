"""#825: only a job's OWN unfinished predecessors hold it; another chain's waiting job never does."""

from __future__ import annotations

from pathlib import Path

from junkroan.runs.store import Store


def _chains(tmp_path: Path):
    """Chain A: a running job + a later job waiting on it. Chain B (submitted later): a job whose
    own predecessor is done (rc 0), queued, 1 worker."""

    store = Store(tmp_path / "jobs.jsonl")
    a1 = store.submit(host="pc", priority="P1", tag="a1", cmd="echo a1", workers=3)
    a2 = store.submit(host="pc", priority="P1", tag="a2", cmd="echo a2", workers=3, after=[a1.id])
    store.start(a1.id)
    b1 = store.submit(host="pc", priority="P1", tag="b1", cmd="echo b1")
    store.start(b1.id)
    store.end(b1.id, rc=0)
    b2 = store.submit(host="pc", priority="P1", tag="b2", cmd="echo b2", workers=1, after=[b1.id])
    return store, a1, a2, b1, b2


def test_825_row1_a_job_with_its_predecessor_done_is_not_held_by_another_chain(tmp_path: Path) -> None:
    store, _a1, _a2, _b1, b2 = _chains(tmp_path)
    job = store.next_job("pc")
    assert job is not None and job.id == b2.id


def test_825_order_inside_one_chain_is_kept(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    a1 = store.submit(host="pc", priority="P2", tag="a1", cmd="x")
    a2 = store.submit(host="pc", priority="P2", tag="a2", cmd="x", after=[a1.id])
    a3 = store.submit(host="pc", priority="P2", tag="a3", cmd="x", after=[a1.id])
    a4 = store.submit(host="pc", priority="P2", tag="a4", cmd="x", after=[a2.id])
    store.start(a1.id)
    assert store.next_job("pc") is None
    store.end(a1.id, rc=0)
    assert store.next_job("pc").id == a2.id
    store.start(a2.id)
    assert store.next_job("pc").id == a3.id   # sibling, ready
    store.start(a3.id)
    assert store.next_job("pc") is None        # a4 waits for the running a2
    store.end(a2.id, rc=0)
    assert store.next_job("pc").id == a4.id


def test_825_row3_failed_own_predecessor_is_not_returned(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    a1 = store.submit(host="pc", priority="P1", tag="a1", cmd="x")
    store.submit(host="pc", priority="P1", tag="a2", cmd="x", after=[a1.id])
    store.start(a1.id)
    b1 = store.submit(host="pc", priority="P1", tag="b1", cmd="x")
    store.start(b1.id)
    store.end(b1.id, rc=2)
    store.submit(host="pc", priority="P1", tag="b2", cmd="x", after=[b1.id])
    assert store.next_job("pc") is None


def _daemon_chains(tmp_path: Path, a_workers: int):
    from test_runs_daemon import make_daemon

    daemon, store, _ = make_daemon(tmp_path)
    a1 = store.submit(host="pc", priority="P1", tag="a1", cmd="echo a1", workers=a_workers)
    store.submit(host="pc", priority="P1", tag="a2", cmd="echo a2", workers=1, after=[a1.id])
    daemon.tick()
    assert store.get(a1.id).state == "running"
    b1 = store.submit(host="pc", priority="P1", tag="b1", cmd="echo b1")
    store.start(b1.id)
    store.end(b1.id, rc=0)
    b2 = store.submit(host="pc", priority="P1", tag="b2", cmd="echo b2", workers=1, after=[b1.id])
    return daemon, store, b2


def test_825_daemon_starts_b_when_room_is_free(tmp_path: Path) -> None:
    daemon, store, b2 = _daemon_chains(tmp_path, a_workers=2)
    assert daemon.tick().started == [b2.id]


def test_825_row3_no_start_when_room_is_0(tmp_path: Path) -> None:
    daemon, store, b2 = _daemon_chains(tmp_path, a_workers=5)   # queue share of budget 7/2 is 5
    assert daemon.room(daemon.budget()) <= 0
    assert daemon.fill() == []
    assert store.get(b2.id).state == "queued"


def test_825_row3_no_start_at_spike_max_step(tmp_path: Path) -> None:
    from junkroan.runs import spike as spike_mod

    daemon, store, b2 = _daemon_chains(tmp_path, a_workers=2)
    daemon.spike_step = spike_mod.MAX_STEP
    assert daemon.fill() == []
    assert store.get(b2.id).state == "queued"
