"""#403 unit 1: `submit --host auto` placement (fake hosts, no PoB, no SSH)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs import placement
from junkroan.runs.remote_store import RemoteStoreUnreachable

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("runs_cli_403", ROOT / "scripts" / "runs.py")
runs = importlib.util.module_from_spec(_spec)
sys.modules["runs_cli_403"] = runs
_spec.loader.exec_module(runs)

CONFIG = {
    "pc": {"ssh": None, "modes": {"normal": {"day": {"hours": [0, 24], "total": 7}}}},
    "laptop": {"ssh": "laptop", "modes": {
        "normal": {"day": {"hours": [0, 24], "total": 3}},
        "browser": {"day": {"hours": [0, 24], "total": 2}},
    }},
}
NOON = datetime(2026, 10, 1, 12, 0)


def job(host, state, workers=1, filler=False):
    return SimpleNamespace(host=host, state=state, workers=workers, is_filler=filler)


def states(pc_jobs, laptop_jobs, *, laptop_up=True, monkeypatch):
    monkeypatch.setattr(runs_hosts, "read_modes", lambda *a, **k: {})

    def reader(cfg, host="laptop"):
        if not laptop_up:
            raise RemoteStoreUnreachable("down")
        return SimpleNamespace(jobs=laptop_jobs, daemon_status=None,
                               budget=runs_hosts.mode_budget(CONFIG["laptop"], "laptop", "browser"))

    return placement.gather_states(
        local_host="pc", local_store=SimpleNamespace(jobs=lambda: pc_jobs), config=CONFIG, now=NOON,
        remote_reader=reader, local_total=lambda: 7)


def test_room_now_fillers_are_free():
    assert placement.room_now(7, [{"workers": 3}, {"workers": 4, "is_filler": True}], [{"need": 2}]) == 2


@pytest.mark.parametrize("need,expected", [(1, "laptop"), (2, "laptop"), (5, "pc")])  # 5: fits nowhere -> pc (spec test a)
def test_pc_full_laptop_filler(monkeypatch, need, expected):
    pc = [job("pc", "running", 7)]
    laptop = [job("laptop", "running", 2, filler=True)]
    st = states(pc, laptop, monkeypatch=monkeypatch)
    assert st == {"pc": 0, "laptop": 2}  # browser total 2, the filler is free
    assert placement.pick_host(need, st) == expected


def test_tie_goes_to_pc():
    assert placement.pick_host(1, {"pc": 3, "laptop": 3}) == "pc"


def test_laptop_unreachable_goes_to_pc(monkeypatch):
    st = states([job("pc", "running", 7)], [], laptop_up=False, monkeypatch=monkeypatch)
    assert st == {"pc": 0}
    assert placement.pick_host(1, st) == "pc"


def _submit(tmp_path, monkeypatch, host_args):
    calls = []
    monkeypatch.setattr(runs.runs_placement, "gather_states", lambda **kw: {"pc": 0, "laptop": 2})
    monkeypatch.setattr(runs, "_submit_remote", lambda host, f, c: calls.append((host, f)) or 0)
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    rc = runs.main(["--store", str(tmp_path / "jobs.jsonl"), "submit", "--issue", "1", *host_args, "--priority", "P1",
                    "--again", "--", "echo", "x"])
    return rc, calls


@pytest.mark.parametrize("host_args", [[], ["--host", "auto"]])
def test_cli_auto_places_on_laptop(tmp_path, monkeypatch, host_args):
    rc, calls = _submit(tmp_path, monkeypatch, host_args)
    assert rc == 0 and calls and calls[0][0] == "laptop"
    assert calls[0][1].count("--host") == 1 and "laptop" in calls[0][1]


def test_cli_host_pc_forces_pc(tmp_path, monkeypatch):
    rc, calls = _submit(tmp_path, monkeypatch, ["--host", "pc"])
    assert rc == 0 and calls == []


def test_five_workers_go_to_the_laptop_when_its_room_holds_them():
    assert placement.pick_host(5, {"pc": 0, "laptop": 5}) == "laptop"
