"""Job store fold, transitions and concurrency (issue #40)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from junkroan.runs.store import (
    DuplicateTag,
    IllegalTransition,
    JobNotFound,
    Store,
    split_pin,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"


def test_fold_submit_start_end_gives_done(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t1", cmd="echo hi")
    assert job.state == "queued"

    started = store.start(job.id)
    assert started.state == "running"
    assert started.attempts == 1

    ended = store.end(job.id, rc=0)
    assert ended.state == "done"
    assert ended.rc == 0


def test_fold_nonzero_rc_gives_failed(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P2", tag="t1", cmd="echo hi")
    store.start(job.id)
    ended = store.end(job.id, rc=1)
    assert ended.state == "failed"


# -- issue #118: `record_handback` stores a `--handback remote` daemon's own comment body --------

def test_118_record_handback_stores_the_body_on_the_job(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="laptop", priority="P1", tag="lap1", cmd="echo hi", issue=118)
    store.start(job.id)
    store.end(job.id, rc=0)

    updated = store.record_handback(job.id, "the body")
    assert updated.handback_body == "the body"
    assert updated.posted is False    # `record_handback` never sets `posted`: only the PC does


def test_118_record_handback_before_the_job_ends_raises(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="laptop", priority="P1", tag="lap2", cmd="echo hi")
    store.start(job.id)
    with pytest.raises(IllegalTransition):
        store.record_handback(job.id, "too early")


def test_118_a_requeue_clears_the_stored_handback_body(tmp_path: Path) -> None:
    """A resumed run must not hand back its earlier attempt's stale body (mirrors `posted`)."""

    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="laptop", priority="P1", tag="lap3", cmd="echo hi")
    store.start(job.id)
    store.end(job.id, rc=1)
    store.record_handback(job.id, "first attempt")
    store.requeue(job.id)
    restarted = store.start(job.id)
    assert restarted.handback_body is None


def test_cancel_of_a_running_job_raises(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t1", cmd="echo hi")
    store.start(job.id)
    with pytest.raises(IllegalTransition):
        store.cancel(job.id)


def test_start_on_a_cancelled_job_raises(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t1", cmd="echo hi")
    store.cancel(job.id)
    with pytest.raises(IllegalTransition):
        store.start(job.id)


def test_start_on_unknown_job_raises_not_found(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    with pytest.raises(JobNotFound):
        store.start("j-does-not-exist")


def test_cancel_a_queued_job_ok(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t1", cmd="echo hi")
    cancelled = store.cancel(job.id)
    assert cancelled.state == "cancelled"


def test_duplicate_live_tag_raises(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P1", tag="same", cmd="echo 1")
    with pytest.raises(DuplicateTag):
        store.submit(host="pc", priority="P1", tag="same", cmd="echo 2")


def test_tag_reusable_once_the_first_job_is_terminal(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    first = store.submit(host="pc", priority="P1", tag="same", cmd="echo 1")
    store.cancel(first.id)
    second = store.submit(host="pc", priority="P1", tag="same", cmd="echo 2")
    assert second.id != first.id


def test_requeue_stopped_job_goes_back_to_queued(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="t1", cmd="echo hi")
    store.start(job.id)
    store.stop(job.id, reason="power guard")
    requeued = store.requeue(job.id)
    assert requeued.state == "queued"


# -- next_job ordering --------------------------------------------------------------------------

def test_next_job_priority_then_age(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    p2 = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    p1_older = store.submit(host="pc", priority="P1", tag="b", cmd="echo b")
    p1_newer = store.submit(host="pc", priority="P1", tag="c", cmd="echo c")
    p0 = store.submit(host="pc", priority="P0", tag="d", cmd="echo d")

    assert store.next_job("pc").id == p0.id
    store.cancel(p0.id)
    assert store.next_job("pc").id == p1_older.id  # oldest P1 before the newer P1
    store.cancel(p1_older.id)
    assert store.next_job("pc").id == p1_newer.id
    store.cancel(p1_newer.id)
    assert store.next_job("pc").id == p2.id


def test_next_job_any_host_is_picked_by_both(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="any", priority="P1", tag="a", cmd="echo a")
    assert store.next_job("pc").id == job.id
    assert store.next_job("laptop").id == job.id


def test_next_job_host_specific_not_picked_by_other_host(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    store.submit(host="pc", priority="P0", tag="a", cmd="echo a")
    assert store.next_job("laptop") is None


def test_next_job_none_when_no_queued(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    assert store.next_job("pc") is None


# -- split_pin ------------------------------------------------------------------------------------

def test_split_pin_with_pin() -> None:
    assert split_pin("@abc123 python scripts/benchmark.py --seeds 3") == ("abc123", "python scripts/benchmark.py --seeds 3")


def test_split_pin_without_pin() -> None:
    assert split_pin("python scripts/search.py Fireball") == (None, "python scripts/search.py Fireball")


# -- concurrency: many processes submitting at once -----------------------------------------------

# A real `multiprocessing.Pool`, but bootstrapped inside its own freshly spawned interpreter
# (this whole script run via `subprocess.run`, not `multiprocessing.Pool` called directly from the
# pytest process) -- issue #114. Deep in a long pytest run (~100 subprocess-heavy tests earlier in
# the same suite), Windows' multiprocessing "spawn" can hang forever in the child's own bootstrap:
# `CreateProcess(bInheritHandles=True)` duplicates every still-inheritable handle from the parent,
# including stale pipe handles an unrelated, much earlier test's `subprocess.Popen` never closed
# (`subprocess.run`, used everywhere else in this suite, always closes its own; a kept-open
# `Popen` does not). A short-lived interpreter that has done nothing else has no such handle
# table, so its own `Pool` spawns cleanly -- reproduced hanging past 4 min in the pytest process
# after the rest of this suite ran first; instant (this form) either way.
_CONCURRENT_SUBMIT_SCRIPT = """
import json, multiprocessing, sys
from pathlib import Path

sys.path.insert(0, __SRC__)
from junkroan.runs.store import Store


def _submit_batch(store_path, worker, n):
    store = Store(Path(store_path))
    return [store.submit(host="pc", priority="P2", tag=f"w{worker}-{i}", cmd=f"echo {worker}-{i}").id
            for i in range(n)]


def main():
    store_path, n_workers, n_each = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with multiprocessing.Pool(n_workers) as pool:
        results = pool.starmap(_submit_batch, [(store_path, w, n_each) for w in range(n_workers)])
    print(json.dumps([jid for batch in results for jid in batch]))


if __name__ == "__main__":
    main()
""".replace("__SRC__", repr(str(SRC)))


def test_concurrent_submits_from_many_processes(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.jsonl"
    n_workers, n_each = 8, 25
    script_path = tmp_path / "_concurrent_submit.py"
    script_path.write_text(_CONCURRENT_SUBMIT_SCRIPT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script_path), str(store_path), str(n_workers), str(n_each)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr

    all_ids = json.loads(result.stdout)
    assert len(all_ids) == n_workers * n_each == 200
    assert len(set(all_ids)) == 200  # every id distinct

    lines = [ln for ln in store_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 200  # every line well-formed (json.loads succeeds) and one per submit

    store = Store(store_path)
    jobs = store.jobs()
    assert len(jobs) == 200
    assert all(j.state == "queued" for j in jobs)


# -- #82: `submit --after <job id>` ---------------------------------------------------------------

def test_82_a_follower_waits_until_its_predecessor_ends_rc_0(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    assert store.get(second.id).after == (first.id,)

    assert store.next_job("pc").id == first.id
    store.start(first.id)
    assert store.next_job("pc") is None            # `b` waits while `a` runs
    store.end(first.id, rc=0)
    assert store.next_job("pc").id == second.id


def test_82_a_job_with_no_after_starts_while_a_chain_waits_but_a_dependent_one_does_not(tmp_path: Path) -> None:
    """The chain rule: A, B --after A, C (plain), D --after A-done-sibling.

    C may overtake the held B (no dependency at all); since #825 D may too (its own predecessor is
    done and it shares no chain with B).
    """

    store = Store(tmp_path / "jobs.jsonl")
    done = store.submit(host="pc", priority="P2", tag="done", cmd="echo done")
    store.start(done.id)
    store.end(done.id, rc=0)
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    third = store.submit(host="pc", priority="P2", tag="c", cmd="echo c")
    fourth = store.submit(host="pc", priority="P2", tag="d", cmd="echo d", after=[done.id])

    assert store.next_job("pc").id == first.id
    store.start(first.id)
    assert store.next_job("pc").id == third.id     # C overtakes the held B: it has no --after
    store.start(third.id)
    # #825: D is another chain (its only predecessor is done, no id shared with B's), so the
    # waiting B no longer holds it; order inside ONE chain is tests/test_next_job_chains.py.
    assert store.next_job("pc").id == fourth.id
    store.start(fourth.id)
    assert store.next_job("pc") is None
    store.end(first.id, rc=0)
    assert store.next_job("pc").id == second.id


def test_82_a_failed_predecessor_holds_its_follower_for_ever(tmp_path: Path) -> None:
    from junkroan.runs.store import DEP_BLOCKED

    store = Store(tmp_path / "jobs.jsonl")
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    store.start(first.id)
    store.end(first.id, rc=3)

    assert store.next_job("pc") is None
    held = store.held_jobs("pc")
    assert [(job.id, dep.id, status) for job, dep, status in held] == [(second.id, first.id, DEP_BLOCKED)]


def test_82_a_cancelled_predecessor_blocks_too(tmp_path: Path) -> None:
    from junkroan.runs.store import DEP_BLOCKED

    store = Store(tmp_path / "jobs.jsonl")
    first = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    second = store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=[first.id])
    store.cancel(first.id)
    assert store.next_job("pc") is None
    assert store.held_jobs("pc")[0][2] == DEP_BLOCKED
    assert second.state == "queued"


def test_82_a_blocked_chain_does_not_hold_up_a_healthy_one(tmp_path: Path) -> None:
    """A follower whose predecessor failed is out of the queue (a human's problem), not a gate."""

    store = Store(tmp_path / "jobs.jsonl")
    dead = store.submit(host="pc", priority="P2", tag="dead", cmd="echo dead")
    store.submit(host="pc", priority="P2", tag="orphan", cmd="echo orphan", after=[dead.id])
    good = store.submit(host="pc", priority="P2", tag="good", cmd="echo good")
    follower = store.submit(host="pc", priority="P2", tag="follower", cmd="echo follower", after=[good.id])
    store.start(dead.id)
    store.end(dead.id, rc=1)

    assert store.next_job("pc").id == good.id      # the orphan is skipped, not a gate
    store.start(good.id)
    assert store.next_job("pc") is None            # now the follower waits for its own predecessor
    store.end(good.id, rc=0)
    assert store.next_job("pc").id == follower.id


def test_82_an_unknown_after_id_is_rejected_at_submit(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    with pytest.raises(JobNotFound):
        store.submit(host="pc", priority="P2", tag="b", cmd="echo b", after=["j-20260101-0000-dead"])
    assert store.jobs() == []                      # nothing was written


def test_82_a_two_step_chain_needs_both_predecessors(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    a = store.submit(host="pc", priority="P2", tag="a", cmd="echo a")
    b = store.submit(host="pc", priority="P2", tag="b", cmd="echo b")
    c = store.submit(host="pc", priority="P2", tag="c", cmd="echo c", after=[a.id, b.id])
    for job in (a, b):
        store.start(job.id)
    store.end(a.id, rc=0)
    assert store.next_job("pc") is None
    store.end(b.id, rc=0)
    assert store.next_job("pc").id == c.id


def test_equal_clock_stamps_still_order_by_submission(tmp_path: Path, monkeypatch) -> None:
    """#688: a clock that returns one stamp for every submit must not leave order to the random id."""

    from junkroan.runs import store as store_mod

    monkeypatch.setattr(store_mod, "_now_iso", lambda: "2026-10-09T12:00:00.000000+00:00")
    store = Store(tmp_path / "jobs.jsonl")
    ids = [store.submit(host="pc", priority="P1", tag=f"t{i}", cmd="echo").id for i in range(8)]
    # a second Store on the same file stands for the other process (CLI vs daemon)
    ids.append(Store(tmp_path / "jobs.jsonl").submit(host="pc", priority="P1", tag="t8", cmd="echo").id)

    assert [j.id for j in store.jobs()] == ids
    order = []
    while (job := store.next_job("pc")) is not None:
        order.append(job.id)
        store.cancel(job.id)
    assert order == ids
