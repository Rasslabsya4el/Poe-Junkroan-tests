"""#696: every op stamp in the run store is strictly after the newest earlier one, not only submits."""

from __future__ import annotations

from pathlib import Path

from junkroan.runs import store as store_mod
from junkroan.runs.store import Store


def test_frozen_clock_gives_strictly_increasing_stamps_for_every_op(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store_mod, "_now_iso", lambda: "2026-10-09T12:00:00.000000+00:00")
    store = Store(tmp_path / "jobs.jsonl")
    a = store.submit(host="pc", priority="P1", tag="a", cmd="echo")
    b = store.submit(host="pc", priority="P1", tag="b", cmd="echo")
    store.start(a.id)
    store.start(b.id)
    store.end(a.id, rc=0)
    store.end(b.id, rc=0)

    stamps = [rec["ts"] for rec in store._read_lines()]
    assert len(stamps) == 6
    # the two submits and the four later ops keep call order: submits strictly increasing among
    # themselves, every start/end strictly after the newest stamp before it
    assert stamps[:2] == sorted(set(stamps[:2]))
    assert stamps[2:] == sorted(set(stamps[2:]))
    assert stamps[2] > stamps[1]
    jobs = {j.id: j for j in store.jobs()}
    assert jobs[a.id].end_ts < jobs[b.id].end_ts
    assert jobs[a.id].start_ts < jobs[b.id].start_ts
