"""#889: a pinned job placed on or moved to another host has its pin pushed first (fakes, no ssh, no real push)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from junkroan.runs import pin_ref
from junkroan.runs import placement as runs_placement
from junkroan.runs.rebalance import Rebalancer
from tests.test_runs_rebalance import CMD, _fill_pc, age, rig

ROOT = Path(__file__).resolve().parents[1]


def _rig_with_push(tmp_path, monkeypatch, push):
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch, laptop_has_pin=False)
    order: list[str] = []
    old_submit = daemon._rebalancer._submit_moved

    def submit_moved(cfg, host, job, origin):
        order.append("move")
        return old_submit(cfg, host, job, origin)

    def push_pin(repo, pin):
        order.append("push")
        return push(pin)

    daemon._rebalancer = Rebalancer(daemon, has_pin=lambda c, h, p: False, submit_moved=submit_moved,
                                    push_pin=push_pin)
    return daemon, store, laptop, logged, calls, order


def test_row1_pin_pushed_before_the_move(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, order = _rig_with_push(tmp_path, monkeypatch, lambda pin: (True, "ok"))
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="w", cmd=CMD, pin="59923532", workers=1)
    age(daemon, job, 20)
    daemon.tick()
    assert order == ["push", "move"]
    assert store.get(job.id).state != "queued" and calls["submit"] == 1


def test_row2_push_fails_job_stays_one_log_line(tmp_path, monkeypatch):
    daemon, store, laptop, logged, calls, order = _rig_with_push(
        tmp_path, monkeypatch, lambda pin: (False, "push of pin 59923532 to origin failed: denied"))
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="w", cmd=CMD, pin="59923532", workers=1)
    age(daemon, job, 20)
    for _ in range(3):
        daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0 and "move" not in order
    lines = [x for x in logged if x.startswith("rebalance: ")]
    assert len(lines) == 1 and "59923532" in lines[0] and "denied" in lines[0]


def _load_runs():
    spec = importlib.util.spec_from_file_location("runs_script_889", ROOT / "scripts" / "runs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runs_script_889"] = mod
    spec.loader.exec_module(mod)
    return mod


def _submit(tmp_path, monkeypatch, host_args, push_ok):
    runs = _load_runs()
    pushed, remote = [], []
    monkeypatch.setattr(runs.slot_budget, "current_host", lambda: "pc")
    monkeypatch.setattr(runs.runs_pin_ref, "missing_script", lambda *a, **k: None)
    monkeypatch.setattr(runs.runs_pin_ref, "push_pin",
                        lambda repo, pin: (pushed.append(pin), (push_ok, "boom" if not push_ok else "ok"))[1])
    monkeypatch.setattr(runs, "_submit_remote", lambda host, flags, cmd: (remote.append(host), 0)[1])
    monkeypatch.setattr(runs.runs_placement, "gather_states", lambda **k: {"pc": 0, "laptop": 5})
    monkeypatch.setattr(runs.runs_placement, "pick_host", lambda w, s: "laptop")
    monkeypatch.setattr(runs.runs_placement, "gate_filter", lambda st, *a, **k: (st, []))
    from junkroan.runs.store import Store
    store = Store(tmp_path / "s.jsonl")
    rc = runs.cmd_submit(store, ["--priority", "P2", "--issue", "1", "--pin", "59923532", *host_args,
                                 "--", "python", "-c", "pass"])
    return rc, pushed, remote, store


def test_row3_explicit_and_auto_submit_still_push(tmp_path, monkeypatch):
    for host_args in (["--host", "laptop"], ["--host", "auto"]):
        rc, pushed, remote, _ = _submit(tmp_path, monkeypatch, host_args, True)
        assert rc == 0 and pushed == ["59923532"] and remote == ["laptop"]


def test_submit_push_failure_never_queues_remote(tmp_path, monkeypatch):
    rc, pushed, remote, _ = _submit(tmp_path, monkeypatch, ["--host", "laptop"], False)
    assert rc == 1 and remote == []
    rc, pushed, remote, store = _submit(tmp_path, monkeypatch, ["--host", "auto"], False)
    assert remote == [] and len(store.jobs()) == 1
