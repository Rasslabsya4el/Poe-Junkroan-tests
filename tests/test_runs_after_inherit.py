"""#648 unit 1: `submit --after X` with no --host places the job in the store that holds X."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

CMD = "python scripts/benchmark.py --workers 1"


def _rig(tmp_path, monkeypatch, *, base_in: str, base_state: str = "queued"):
    """A PC store and a fake laptop store; the base job lives in `base_in`."""
    pc = Store(tmp_path / "pc.jsonl")
    laptop = Store(tmp_path / "laptop.jsonl")
    owner = pc if base_in == "pc" else laptop
    base = owner.submit(host=base_in, priority="P1", tag="base", cmd=CMD)
    if base_state in ("running", "done"):
        owner.start(base.id, pid=1)
    if base_state == "done":
        owner.end(base.id, rc=0)
    calls: list = []
    in_remote = {"on": False}

    def fake_remote(host, flag_argv, cmd_argv):
        calls.append((host, list(flag_argv)))
        in_remote["on"] = True  # the forwarded call runs on the laptop: its own host name
        try:
            return runs.main(["--store", str(laptop.path), "submit", *flag_argv, "--", *cmd_argv])
        finally:
            in_remote["on"] = False

    def boom(*a, **k):
        raise AssertionError("pick_host / gather_states must not be called")

    monkeypatch.setattr(runs.runs_placement, "pick_host", boom)
    monkeypatch.setattr(runs.runs_placement, "gather_states", boom)
    monkeypatch.setattr(runs, "_submit_remote", fake_remote)
    monkeypatch.setattr(runs, "_read_host_jobs", lambda cfg: laptop.jobs())
    monkeypatch.setattr(runs.runs_hosts, "load_hosts_config", lambda: {"pc": {}, "laptop": {"ssh": "laptop"}})
    monkeypatch.setattr(runs, "finished_run_dir", lambda t, root: None)
    monkeypatch.setattr(runs.slot_budget, "current_host", lambda: "laptop" if in_remote["on"] else "pc")
    return pc, laptop, base.id, calls


def _submit(pc, *extra):
    return runs.main(["--store", str(pc.path), "submit", "--priority", "P1", "--issue", "1", *extra,
                      "--", "python", "-c", "print('head')"])


def test_row1_base_on_laptop_head_goes_to_laptop(tmp_path, monkeypatch, capsys):
    pc, laptop, base, calls = _rig(tmp_path, monkeypatch, base_in="laptop", base_state="running")
    assert _submit(pc, "--after", base) == 0
    assert calls and calls[0][0] == "laptop" and "laptop" in calls[0][1]
    head = [j for j in laptop.jobs() if j.id != base][0]
    assert head.host == "laptop" and head.host_fixed is True and head.host_reason == f"after:{base}"
    assert head.after == (base,)
    assert pc.jobs() == []
    assert f"host laptop (after:{base})" in capsys.readouterr().err


def test_row2_base_on_pc_head_stays_on_pc(tmp_path, monkeypatch):
    pc, laptop, base, calls = _rig(tmp_path, monkeypatch, base_in="pc", base_state="done")
    assert _submit(pc, "--after", base) == 0
    head = [j for j in pc.jobs() if j.id != base][0]
    assert head.host == "pc" and head.host_fixed is True and head.host_reason == f"after:{base}"
    assert calls == [] and laptop.jobs() == []


def test_unknown_id_refused_nothing_written(tmp_path, monkeypatch):
    pc, laptop, base, calls = _rig(tmp_path, monkeypatch, base_in="pc")
    assert _submit(pc, "--after", "j-nope") == 1
    assert len(pc.jobs()) == 1 and laptop.jobs() == [] and calls == []


def test_split_across_hosts_refused(tmp_path, monkeypatch):
    pc, laptop, base, calls = _rig(tmp_path, monkeypatch, base_in="pc")
    other = laptop.submit(host="laptop", priority="P1", tag="other", cmd=CMD)
    assert _submit(pc, "--after", base, "--after", other.id) == 1
    assert len(pc.jobs()) == 1 and len(laptop.jobs()) == 1 and calls == []


def test_explicit_host_unchanged(tmp_path, monkeypatch):
    pc, laptop, base, calls = _rig(tmp_path, monkeypatch, base_in="pc")
    assert _submit(pc, "--host", "pc", "--after", base) == 0
    head = [j for j in pc.jobs() if j.id != base][0]
    assert head.host == "pc" and head.host_fixed is True and head.host_reason is None


def test_old_submit_line_folds_to_none(tmp_path):
    path = tmp_path / "j.jsonl"
    store = Store(path)
    job = store.submit(host="pc", priority="P1", tag="t", cmd=CMD)
    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "host_reason" not in rec and store.get(job.id).host_reason is None
