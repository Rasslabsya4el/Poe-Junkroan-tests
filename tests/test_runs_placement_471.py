"""#471: placement sizes a remote host from the budget in its snapshot (fakes only, no ssh, no PoB)."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs import placement, remote_store
from junkroan.runs.remote_store import RemoteStoreUnreachable

NOON = datetime(2026, 10, 1, 12, 0)
CONFIG = {
    "pc": {"ssh": None, "modes": {"normal": {"day": {"hours": [0, 24], "total": 7}}}},
    "laptop": {"ssh": "laptop", "modes": {
        "off": {"day": {"hours": [0, 24], "total": 0}},
        "browser": {"day": {"hours": [0, 24], "total": 2}},
        "normal": {"day": {"hours": [0, 24], "total": 3}},
    }},
}



def _gz64(text: str) -> str:
    import gzip
    return base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")

def job(state):
    return SimpleNamespace(host="laptop", state=state, workers=1, is_filler=False)


def snapshot(mode, jobs=()):
    budget = None if mode is None else runs_hosts.mode_budget(CONFIG["laptop"], "laptop", mode)
    return SimpleNamespace(jobs=list(jobs), daemon_status=None, budget=budget)


def gather(reader, *, log=None):
    extra = {"log": log} if log is not None else {}
    return placement.gather_states(
        local_host="pc", local_store=SimpleNamespace(jobs=lambda: []), config=CONFIG, now=NOON,
        remote_reader=reader, local_total=lambda: 7, **extra)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(runs_hosts, "read_modes", lambda *a, **k: {})
    getattr(placement, "_unreadable_logged", set()).clear()


@pytest.mark.parametrize("mode,total", [("off", 0), ("browser", 2), ("normal", 3)])
def test_471_row0_laptop_room_follows_its_real_mode(mode, total):
    jobs = [job("running"), job("queued")]
    st = gather(lambda cfg, host="laptop": snapshot(mode, jobs))
    assert st["laptop"] == total - 2


def test_471_row1_one_remote_call_per_host():
    calls = []
    budget = runs_hosts.mode_budget(CONFIG["laptop"], "laptop", "normal")
    reply = "\n".join([
        "", remote_store._SNAPSHOT_SPLIT, "", remote_store._SNAPSHOT_SPLIT,
        _gz64(json.dumps(budget))])

    def transport(cfg, script, *, timeout):
        calls.append(script)
        return SimpleNamespace(returncode=0, stdout=reply, stderr="")

    st = gather(lambda cfg, host="laptop": remote_store.read_remote_snapshot(cfg, host=host, transport=transport))
    assert len(calls) == 1
    assert st["laptop"] == 3


def test_471_row2_unreachable_host_is_skipped():
    def reader(cfg, host="laptop"):
        raise RemoteStoreUnreachable("down")

    assert "laptop" not in gather(reader)


def test_471_row2_unreadable_budget_room_zero_one_log_until_it_reads_again():
    logs = []

    def bad(cfg, host="laptop"):
        return snapshot(None)

    def good(cfg, host="laptop"):
        return snapshot("normal")

    assert gather(bad, log=logs.append)["laptop"] == 0
    assert gather(bad, log=logs.append)["laptop"] == 0
    assert len(logs) == 1 and "laptop" in logs[0]
    assert gather(good, log=logs.append)["laptop"] == 3
    assert len(logs) == 2 and logs[1] == "placement: laptop budget readable again; room 3"  # #709
    gather(bad, log=logs.append)
    assert len(logs) == 3


def test_471_budget_matching_no_mode_and_missing_attribute_give_room_zero():
    def odd(cfg, host="laptop"):
        return SimpleNamespace(jobs=[], daemon_status=None, budget={"day": {"total": 99}})

    def bare(cfg, host="laptop"):
        return SimpleNamespace(jobs=[], daemon_status=None)

    assert gather(odd)["laptop"] == 0
    assert gather(bare)["laptop"] == 0
