"""#403 unit 4: the PC daemon moves a long-waiting queued job to the laptop once (fake hosts, no PoB)."""

from __future__ import annotations

from pathlib import Path

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs.rebalance import Rebalancer
from junkroan.runs.remote_store import RemoteSnapshot
from junkroan.runs.store import Store
from tests.test_runs_daemon import BUDGET_NIGHT_10, make_daemon

CONFIG = {
    "pc": {"ssh": None, "modes": {"normal": {"day": {"hours": [0, 24], "total": 10}}}},
    "laptop": {"ssh": "laptop", "modes": {"normal": {"day": {"hours": [0, 24], "total": 3}}}},
}
CMD = "python scripts/benchmark.py --workers 1"


def host_status(daemon, ram_bound: int | None = 99) -> dict:
    """#917: the remote daemon's status as the rebalance reads it (RAM never the limit by default)."""

    return {"ram_bound": ram_bound, "last_tick": daemon._utcnow().isoformat(timespec="seconds")}


def rig(tmp_path: Path, monkeypatch, *, laptop_has_pin: bool = True):
    monkeypatch.setattr(runs_hosts, "current_mode", lambda host, **kw: "normal")
    laptop = Store(tmp_path / "laptop.jsonl")
    logged: list[str] = []
    calls = {"submit": 0}

    def submit_moved(cfg, host, job, origin):
        calls["submit"] += 1
        return laptop.submit(
            host=host, priority=job.priority, tag=job.tag, cmd=job.cmd, issue=job.issue,
            submitter=job.submitter, pin=job.pin, resumable=job.resumable, workers=job.workers,
            after=job.after, job_class=job.job_class, moved_from=origin).id

    daemon, store, _ = make_daemon(
        tmp_path, budget=BUDGET_NIGHT_10, hosts_config=CONFIG,
        remote_store_reader=lambda cfg: laptop.jobs())
    daemon.log = logged.append
    normal_budget = runs_hosts.mode_budget(CONFIG["laptop"], "laptop", "normal")  # #471: the snapshot carries it
    daemon._read_remote_snapshot = lambda cfg, host: RemoteSnapshot(
        jobs=laptop.jobs(), daemon_status=host_status(daemon), budget=normal_budget)
    daemon._rebalancer = Rebalancer(daemon, has_pin=lambda cfg, host, pin: laptop_has_pin,
                                    submit_moved=submit_moved,
                                    push_pin=lambda repo, pin: (laptop_has_pin, "ok" if laptop_has_pin else "push failed"))  # #889: no real push
    return daemon, store, laptop, logged, calls


def age(daemon, job, minutes: float) -> None:
    daemon.clock = lambda: daemon._epoch(job.submit_ts) + minutes * 60


def _fill_pc(daemon, store) -> None:
    """Ten running P0 jobs take every PC slot, so a later job waits in the queue."""

    for i in range(10):
        store.submit(host="pc", priority="P0", tag=f"busy{i}", cmd=CMD, workers=1)
    daemon.tick()


def test_403_moved_once_never_back(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, issue=77, pin="abc123",
                       workers=1, submitter="t")
    age(daemon, job, 16)
    daemon.tick()
    moved = laptop.jobs()
    assert len(moved) == 1
    copy = moved[0]
    assert (copy.pin, copy.tag, copy.issue, copy.priority, copy.after, copy.cmd) == \
        ("abc123", "waiter", 77, "P2", (), CMD)
    assert copy.moved_from == "pc" and copy.state == "queued"
    original = store.get(job.id)
    assert original.state == "cancelled" and original.moved_to == f"laptop:{copy.id}"
    assert [r["op"] for r in store._read_lines() if r["job"] == job.id][-1] == "moved"
    assert [r["op"] for r in laptop._read_lines() if r["job"] == copy.id] == ["submit", "moved"]
    daemon.tick()
    daemon.tick()
    assert calls["submit"] == 1 and len(laptop.jobs()) == 1
    # the copy is never a rebalance candidate, wherever the step runs
    assert Rebalancer(daemon)._candidates() == []
    assert not any(j.moved_from is None and j.host == "laptop" for j in laptop.jobs())


def test_403_not_moved_at_14_minutes(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, workers=1)
    age(daemon, job, 14)
    daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0


def test_403_laptop_missing_pin_logs_once(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch, laptop_has_pin=False)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, pin="deadbeef", workers=1)
    age(daemon, job, 20)
    for _ in range(3):
        daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0
    assert len([line for line in logged if line.startswith("rebalance: ")]) == 1


def test_403_filler_and_oversized_job_stay(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    filler = store.submit(host="pc", priority="P2", tag="fill", cmd=CMD, workers=1, job_class="filler")
    big = store.submit(host="pc", priority="P2", tag="big", cmd=CMD, workers=4)  # laptop room is 3
    daemon.clock = lambda: daemon._epoch(big.submit_ts) + 20 * 60
    daemon.tick()
    assert store.get(filler.id).state == "queued" and store.get(big.id).state == "queued"
    assert calls["submit"] == 0


def test_445_job_with_live_follower_stays(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    a = store.submit(host="pc", priority="P2", tag="a", cmd=CMD, workers=1)
    store.submit(host="pc", priority="P2", tag="b", cmd="python -m pytest tests -q", workers=1, after=[a.id])  # #484: a follower that cannot move holds the chain
    daemon.clock = lambda: daemon._epoch(a.submit_ts) + 20 * 60
    assert Rebalancer(daemon)._candidates() == []


def test_445_job_without_follower_is_a_candidate(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    a = store.submit(host="pc", priority="P2", tag="a", cmd=CMD, workers=1)
    daemon.clock = lambda: daemon._epoch(a.submit_ts) + 20 * 60
    assert [j.id for j in Rebalancer(daemon)._candidates()] == [a.id]


@pytest.mark.parametrize("ending", ["done", "cancelled", "stopped"])
def test_445_ended_follower_does_not_hold_the_job(tmp_path: Path, monkeypatch, ending: str) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    a = store.submit(host="pc", priority="P2", tag="a", cmd=CMD, workers=1)
    b = store.submit(host="pc", priority="P2", tag="b", cmd=CMD, workers=1, after=[a.id])
    if ending == "done":
        store.start(b.id, pid=1)
        store.end(b.id, rc=0)
    elif ending == "cancelled":
        store.cancel(b.id)
    else:
        store.start(b.id, pid=1)
        store.stop(b.id)
    assert store.get(b.id).state == ending
    daemon.clock = lambda: daemon._epoch(a.submit_ts) + 20 * 60
    assert [j.id for j in Rebalancer(daemon)._candidates()] == [a.id]


def test_444_failed_write_logs_once_per_job_and_remote_head(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    head = {"v": "abc1234"}

    def boom(cfg, host, job, origin):
        raise RuntimeError("TypeError: submit() got an unexpected keyword argument 'moved_from'\nTraceback")

    daemon._rebalancer = Rebalancer(daemon, has_pin=lambda cfg, host, pin: True, submit_moved=boom,
                                    remote_head=lambda cfg: head["v"])
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, workers=1)
    age(daemon, job, 20)

    def lines():
        return [x for x in logged if "could not write" in x]

    for _ in range(10):
        daemon.tick()
    assert len(lines()) == 1
    assert "abc1234" in lines()[0] and "unexpected keyword argument 'moved_from'" in lines()[0]
    assert "Traceback" not in lines()[0]
    head["v"] = "def5678"
    for _ in range(10):
        daemon.tick()
    assert len(lines()) == 2 and "def5678" in lines()[1]
    other = store.submit(host="pc", priority="P2", tag="waiter2", cmd=CMD, workers=1)
    age(daemon, other, 20)
    for _ in range(3):
        daemon.tick()
    assert len(lines()) == 3 and other.id in lines()[2] and job.id not in lines()[2]


def test_501_moved_job_keeps_rc_is_reading(tmp_path: Path, monkeypatch) -> None:
    import base64
    import json
    import re

    from junkroan.runs import rebalance

    store = Store(tmp_path / "pc.jsonl")
    marked = store.submit(host="pc", priority="P0", tag="pin", cmd="python -m pytest x", rc_is_reading=True)
    plain = store.submit(host="pc", priority="P0", tag="plain", cmd="python -m pytest x")
    sent: list[dict] = []

    class Done:
        returncode, stdout, stderr = 0, "j-new\n", ""

    def fake_run(cfg, script):
        blob = re.findall(r"'([A-Za-z0-9+/=]{20,})'", script)[-1]
        sent.append(json.loads(base64.b64decode(blob)))
        return Done()

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run)
    monkeypatch.setattr(runs_hosts, "daemon_repo_path", lambda cfg: "C:/repo")
    assert rebalance.submit_moved_on_host({}, "laptop", marked, "pc") == "j-new"
    assert rebalance.submit_moved_on_host({}, "laptop", plain, "pc") == "j-new"
    assert sent[0]["rc_is_reading"] is True
    assert "rc_is_reading" not in sent[1]  # an older store on the host still accepts the payload


def test_499_pytest_job_stays_other_job_moves(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    suite = store.submit(host="pc", priority="P2", tag="suite", workers=1,
                         cmd="python -m pytest tests -q -p no:faulthandler -m pob")
    wrapped = store.submit(host="pc", priority="P2", tag="wrapped", workers=1,
                           cmd="cmd /c py -m pytest tests -q")
    bench = store.submit(host="pc", priority="P2", tag="bench", workers=1,
                         cmd="python scripts/replay_bench.py --workers 1")
    daemon.clock = lambda: daemon._epoch(bench.submit_ts) + 20 * 60
    daemon.tick()
    assert store.get(suite.id).state == "queued" and store.get(wrapped.id).state == "queued"
    assert store.get(bench.id).state == "cancelled" and calls["submit"] == 1


BENCH5 = "python scripts/replay_bench.py --builds x --workers 5"


def test_484_chain_moves_as_one_cut_to_the_laptop_room(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    filler = laptop.submit(host="laptop", priority="P2", tag="fill", cmd=CMD, workers=1, job_class="filler")
    base = store.submit(host="pc", priority="P2", tag="b-base", cmd=BENCH5, workers=5, issue=9)
    head = store.submit(host="pc", priority="P2", tag="b-head", cmd=BENCH5 + " --head", workers=5, after=[base.id])
    age(daemon, base, 20)
    daemon.tick()
    on_laptop = {j.tag: j for j in laptop.jobs() if j.moved_from}
    assert set(on_laptop) == {"b-base", "b-head"} and calls["submit"] == 2
    nb, nh = on_laptop["b-base"], on_laptop["b-head"]
    assert (nb.workers, nh.workers) == (3, 3)
    assert nb.cmd.endswith("--workers 3") and nh.cmd == "python scripts/replay_bench.py --builds x --workers 3 --head"
    assert nh.after == (nb.id,) and nb.after == ()
    assert store.get(base.id).state == "cancelled" and store.get(head.id).state == "cancelled"
    assert laptop.next_job("laptop").id == nb.id and laptop.get(filler.id).state == "queued"
    assert any("workers 5 -> 3" in line for line in logged)


def test_484_single_job_cut(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    solo = store.submit(host="pc", priority="P2", tag="solo", cmd=BENCH5, workers=5)
    age(daemon, solo, 20)
    daemon.tick()
    copy = [j for j in laptop.jobs() if j.moved_from][0]
    assert (copy.workers, copy.cmd) == (3, "python scripts/replay_bench.py --builds x --workers 3")


def test_484_room_one_moves_nothing(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    busy = laptop.submit(host="laptop", priority="P0", tag="busy", cmd=CMD, workers=2)
    laptop.start(busy.id, pid=1)  # laptop room = 3 - 2 = 1
    _fill_pc(daemon, store)
    solo = store.submit(host="pc", priority="P2", tag="solo", cmd=BENCH5, workers=5)
    age(daemon, solo, 20)
    daemon.tick()
    assert calls["submit"] == 0 and store.get(solo.id).state == "queued"


def test_484_never_moved_kinds(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _fill_pc(daemon, store)
    filler = store.submit(host="pc", priority="P2", tag="f", cmd=BENCH5, workers=5, job_class="filler")
    suite = store.submit(host="pc", priority="P2", tag="s", cmd="python -m pytest tests --workers 5", workers=5)
    probe = store.submit(host="pc", priority="P2", tag="p", cmd=BENCH5, workers=5, rc_is_reading=True)
    copy = store.submit(host="pc", priority="P2", tag="c", cmd=BENCH5, workers=5, moved_from="laptop")
    running = store.submit(host="pc", priority="P2", tag="r", cmd=BENCH5, workers=5)
    store.start(running.id, pid=1)
    daemon.clock = lambda: daemon._epoch(running.submit_ts) + 20 * 60
    daemon.tick()
    assert calls["submit"] == 0
    for j in (filler, suite, probe, copy):
        assert store.get(j.id).state == "queued"
    assert store.get(running.id).state == "running"
