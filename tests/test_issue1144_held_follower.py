"""#1144: `runs.py status` shows the daemon's hold reason for a queued `--after` job whose predecessors are all done.

Row 1: a follower of a done job, held on RAM in the status file -> `held: ram (...)`.
Row 2: a follower of a running job -> no `held:` line, the `waiting:` line as today.
Row 3: the RAM wait text names the free RAM and the RAM the job needs (floor + per-worker x need).
Row 4: a follower of a failed job keeps today's text; a stale or missing status file -> `held: unknown (...)`.

Seams: the `status` command's output (a fake daemon status file read through `read_daemon_status`) and
the daemon's `waits()`. No PoB, no process table, no real status file.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from tests.test_runs_daemon import (  # noqa: F401,E402
    BUDGET_7_2, _isolated_daemon_status, make_daemon,
)

CMD = "python scripts/benchmark.py --workers 1"
RAM_GATE = {"gate": "ram", "detail": "RAM: holds 0 workers, need 1"}


def _chain(tmp_path: Path, *, state: str):
    """A first job and a queued follower `--after` it; the first job is `done`, `running` or `failed`."""
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    first = store.submit(host="pc", priority="P1", tag="first", cmd=CMD, workers=1)
    follower = store.submit(host="pc", priority="P1", tag="follow", cmd=CMD, workers=1, after=[first.id])
    store.start(first.id)
    if state == "done":
        store.end(first.id, rc=0)
    elif state == "failed":
        store.end(first.id, rc=2)
    return path, first, follower


def _status_file(*, age_s: float = 0.0, gates: dict | None = None) -> dict:
    tick = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return {"last_tick": tick.isoformat(), "gates": gates or {}}


def _status(path: Path, monkeypatch, capsys, status) -> str:
    monkeypatch.setattr(runs, "collect_local", lambda store: [])
    monkeypatch.setattr(runs, "_slot_lines", lambda *a, **k: [])
    monkeypatch.setattr(runs.runs_daemon, "read_daemon_status", lambda path: status)
    assert runs.main(["--store", str(path), "status"]) == 0
    return capsys.readouterr().out


def test_1144_row1_follower_of_a_done_job_shows_its_ram_hold(tmp_path, monkeypatch, capsys) -> None:
    path, first, follower = _chain(tmp_path, state="done")
    status = _status_file(gates={follower.id: RAM_GATE})
    text = _status(path, monkeypatch, capsys, status)
    assert f"{follower.id} held: ram (RAM: holds 0 workers, need 1)" in text


def test_1144_row2_follower_of_a_running_job_has_no_held_line(tmp_path, monkeypatch, capsys) -> None:
    path, first, follower = _chain(tmp_path, state="running")
    status = _status_file(gates={follower.id: RAM_GATE})
    text = _status(path, monkeypatch, capsys, status)
    assert f"{follower.id} waiting: --after {first.id} (running)" in text
    assert f"{follower.id} held:" not in text


def test_1144_row3_ram_wait_names_free_ram_and_the_ram_the_job_needs(tmp_path) -> None:
    budget = replace(BUDGET_7_2, min_free_ram_gb=8.0)
    daemon, store, _ = make_daemon(tmp_path, budget=budget, hosts_config={"pc": {"ram_per_worker_gb": 1.4}})
    daemon._ram_reader = lambda: 4.4
    job = store.submit(host="pc", priority="P1", tag="r", cmd=CMD, workers=1)
    wait = daemon.waits()[job.id]
    assert wait["kind"] == "ram"
    assert wait["text"] == "RAM: свободно 4.4 GB, нужно 9.4 GB"


def test_1144_row4_failed_predecessor_keeps_today_text_and_no_ram_line(tmp_path, monkeypatch, capsys) -> None:
    path, first, follower = _chain(tmp_path, state="failed")
    status = _status_file(gates={follower.id: RAM_GATE})
    text = _status(path, monkeypatch, capsys, status)
    assert f"{follower.id} held: predecessor {first.id} failed" in text
    assert f"{follower.id} held: ram" not in text


def test_1144_row4_stale_status_file_gives_unknown_for_a_done_predecessor(tmp_path, monkeypatch, capsys) -> None:
    path, first, follower = _chain(tmp_path, state="done")
    status = _status_file(age_s=600.0, gates={follower.id: RAM_GATE})
    text = _status(path, monkeypatch, capsys, status)
    assert f"{follower.id} held: unknown (daemon status " in text
    assert f"{follower.id} held: ram" not in text


def test_1144_row4_missing_status_file_gives_unknown_for_a_done_predecessor(tmp_path, monkeypatch, capsys) -> None:
    path, first, follower = _chain(tmp_path, state="done")
    text = _status(path, monkeypatch, capsys, None)
    assert f"{follower.id} held: unknown (daemon status missing)" in text
