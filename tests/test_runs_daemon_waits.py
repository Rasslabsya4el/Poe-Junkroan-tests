"""#706: the daemon writes one reason per queued job into its status file (`waits`). No PoB, no process table."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_runs_daemon import (  # noqa: F401
    BUDGET_7_2, FakeLauncher, _isolated_daemon_status, make_daemon,
)

CMD = "python scripts/benchmark.py --workers 1"


def _waits(daemon) -> dict:
    daemon.write_status(interval=5)
    return json.loads(daemon.status_path.read_text(encoding="utf-8"))["waits"]


def test_row1_low_ram_is_the_reason(tmp_path: Path) -> None:
    budget = replace(BUDGET_7_2, min_free_ram_gb=8.0)
    daemon, store, _ = make_daemon(tmp_path, budget=budget)
    daemon._ram_reader = lambda: 4.4
    job = store.submit(host="pc", priority="P1", tag="r", cmd=CMD, workers=1)
    wait = _waits(daemon)[job.id]
    assert wait["kind"] == "ram"
    assert "4.4" in wait["text"] and "8" in wait["text"]
    assert wait["host_fixed"] is False


def test_row2_after_a_running_job_names_the_predecessor_tag(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path)
    daemon._ram_reader = lambda: 64.0
    first = store.submit(host="pc", priority="P1", tag="first-tag", cmd=CMD, workers=1)
    daemon.tick()
    assert store.get(first.id).state == "running"
    follower = store.submit(host="pc", priority="P1", tag="f", cmd=CMD, workers=1, after=[first.id])
    daemon.tick()
    wait = _waits(daemon)[follower.id]
    assert wait["kind"] == "after" and "first-tag" in wait["text"]


def test_row3_full_slots_and_row4_flags_and_drop_out(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path)
    daemon._ram_reader = lambda: 64.0
    big = store.submit(host="pc", priority="P1", tag="big", cmd=CMD, workers=5)
    daemon.tick()
    assert store.get(big.id).state == "running"
    fixed = store.submit(host="pc", priority="P1", tag="fx", cmd=CMD, workers=1, host_fixed=True)
    daemon.tick()
    assert store.get(fixed.id).state == "queued"
    waits = _waits(daemon)
    assert waits[fixed.id]["kind"] == "slots" and waits[fixed.id]["host_fixed"] is True
    assert waits[fixed.id]["text"] == "слоты: свободно 0 из 1"
    assert big.id not in waits  # a running job has no entry
    # a job with no reason has no entry; once started it drops out
    daemon._end(big.id, rc=0, reason="done", out=None)
    daemon.tick()
    assert store.get(fixed.id).state == "running"
    assert fixed.id not in _waits(daemon)
