"""#648 unit 2: the rebalancer never moves an inherited follower alone; it goes with its queued base."""

from __future__ import annotations

from pathlib import Path

from junkroan.runs.rebalance import Rebalancer
from tests.test_runs_rebalance import CMD, _fill_pc, age, rig


def _inherited(store, host, base, tag="head", **kw):
    return store.submit(host=host, priority="P2", tag=tag, cmd=CMD, workers=1, after=[base.id],
                        host_fixed=True, host_reason=f"after:{base.id}", **kw)


def test_row1_base_running_on_laptop_head_stays(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    base = laptop.submit(host="laptop", priority="P2", tag="base", cmd=CMD, workers=1)
    laptop.start(base.id, pid=1)
    head = _inherited(laptop, "laptop", base)
    age(daemon, head, 20)
    for _ in range(3):
        daemon.tick()
    assert calls["submit"] == 0 and Rebalancer(daemon)._candidates() == []
    laptop.end(base.id, rc=0)
    got = laptop.get(head.id)
    assert (got.host, got.host_fixed, got.host_reason) == ("laptop", True, f"after:{base.id}")
    assert got.state == "queued"


def test_row2_base_ended_on_pc_head_stays_logged_once(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    base = store.submit(host="pc", priority="P2", tag="base", cmd=CMD, workers=1)
    store.start(base.id, pid=1)
    store.end(base.id, rc=0)
    _fill_pc(daemon, store)
    head = _inherited(store, "pc", base)
    age(daemon, head, 20)
    for _ in range(3):
        daemon.tick()
    assert calls["submit"] == 0 and store.get(head.id).state == "queued"
    lines = [x for x in logged if "stays" in x and head.id in x]
    assert lines == [f"rebalance: job {head.id} stays; host inherited from after:{base.id}"]


def test_chain_queued_base_and_inherited_head_move_together(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)

    def submit_moved(cfg, host, job, origin):  # like the real payload: host_fixed and host_reason travel
        calls["submit"] += 1
        return laptop.submit(
            host=host, priority=job.priority, tag=job.tag, cmd=job.cmd, workers=job.workers, after=job.after,
            moved_from=origin, host_fixed=job.host_fixed, host_reason=job.host_reason).id

    daemon._rebalancer = Rebalancer(daemon, has_pin=lambda cfg, host, pin: True, submit_moved=submit_moved)
    _fill_pc(daemon, store)
    base = store.submit(host="pc", priority="P2", tag="base", cmd=CMD, workers=1)
    head = _inherited(store, "pc", base)
    age(daemon, base, 20)
    daemon.tick()
    copies = {j.tag: j for j in laptop.jobs() if j.moved_from}
    assert set(copies) == {"base", "head"} and calls["submit"] == 2
    nb, nh = copies["base"], copies["head"]
    assert nh.after == (nb.id,) and nh.host_fixed is True and nh.host_reason == f"after:{nb.id}"
    assert store.get(base.id).state == "cancelled" and store.get(head.id).state == "cancelled"


def test_plain_fixed_follower_still_blocks_the_chain(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    base = store.submit(host="pc", priority="P2", tag="base", cmd=CMD, workers=1)
    store.submit(host="pc", priority="P2", tag="fixed", cmd=CMD, workers=1, after=[base.id],
                 host_fixed=True, host_reason="host flag")
    age(daemon, base, 20)
    assert Rebalancer(daemon)._candidates() == []


def test_payload_carries_host_fixed_and_reason(tmp_path: Path, monkeypatch) -> None:
    import base64
    import json
    import re

    from junkroan.runs import hosts as runs_hosts
    from junkroan.runs import rebalance
    from junkroan.runs.store import Store

    store = Store(tmp_path / "pc.jsonl")
    base = store.submit(host="pc", priority="P2", tag="base", cmd=CMD)
    head = _inherited(store, "pc", base)
    plain = store.submit(host="pc", priority="P2", tag="plain", cmd=CMD)
    sent: list[dict] = []

    class Done:
        returncode, stdout, stderr = 0, "j-new", ""

    def fake_run(cfg, script):
        blob = re.findall(r"'([A-Za-z0-9+/=]{20,})'", script)[-1]
        sent.append(json.loads(base64.b64decode(blob)))
        return Done()

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run)
    monkeypatch.setattr(runs_hosts, "daemon_repo_path", lambda cfg: "C:/repo")
    rebalance.submit_moved_on_host({}, "laptop", head, "pc")
    rebalance.submit_moved_on_host({}, "laptop", plain, "pc")
    assert sent[0]["host_fixed"] is True and sent[0]["host_reason"] == f"after:{base.id}"
    assert "host_fixed" not in sent[1] and "host_reason" not in sent[1]
