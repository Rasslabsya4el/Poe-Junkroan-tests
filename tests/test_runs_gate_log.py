"""The daemon logs one `gate` line per queued job when its gate changes (issue #403). No PoB."""

from __future__ import annotations

from pathlib import Path

from tests.test_runs_daemon import (  # noqa: F401
    BUDGET_NIGHT_10, FakeLauncher, FakeSlots, _isolated_daemon_status, make_daemon,
)


def _gate_lines(logged: list[str]) -> list[str]:
    return [line for line in logged if line.startswith("gate ")]


def test_403_e_gate_logged_once_per_change(tmp_path: Path) -> None:
    logged: list[str] = []
    launcher = FakeLauncher()
    slots = FakeSlots().foreign(10)  # every slot taken by something else
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, slots=slots, budget=BUDGET_NIGHT_10)
    daemon.log = logged.append

    job = store.submit(host="pc", priority="P1", tag="w", cmd="python scripts/benchmark.py --workers 1", workers=1)

    # room: one line with used/total/need, none on an unchanged tick
    daemon.tick()
    daemon.tick()
    assert _gate_lines(logged) == [f"gate {job.id}: room (used 10/10, need 1)"]

    # room freed: the job starts, one line
    slots.rows.clear()
    daemon.tick()
    assert store.get(job.id).state == "running"
    assert _gate_lines(logged)[-1] == f"gate {job.id}: start (need 1)"

    # heavy: a live heavy job of ours holds a queued heavy job
    holder = store.submit(host="pc", priority="P0", tag="h", cmd="python scripts/benchmark.py --workers 5", workers=5)
    heavy = store.submit(host="pc", priority="P1", tag="h2", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    daemon.tick()
    lines = _gate_lines(logged)
    assert f"gate {heavy.id}: heavy (holder {holder.id}, need 5)" in lines
    assert sum(1 for line in lines if line.startswith(f"gate {heavy.id}")) == 1

    # start: logged once when the held job finally starts
    launcher.exit_codes[store.get(holder.id).pid] = 0
    daemon.tick()
    daemon.tick()
    assert store.get(heavy.id).state == "running"
    mine = [line for line in _gate_lines(logged) if line.startswith(f"gate {heavy.id}")]
    assert mine == [f"gate {heavy.id}: heavy (holder {holder.id}, need 5)", f"gate {heavy.id}: start (need 5)"]
    assert daemon._last_gate == {}


def test_403_after_gate_names_the_predecessor(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_NIGHT_10)
    daemon.log = logged.append
    first = store.submit(host="pc", priority="P1", tag="a", cmd="python scripts/benchmark.py --workers 1", workers=1)
    second = store.submit(host="pc", priority="P1", tag="b", cmd="python scripts/benchmark.py --workers 1",
                          workers=1, after=[first.id])
    daemon.tick()
    daemon.tick()
    assert sorted(_gate_lines(logged)) == sorted([
        f"gate {first.id}: start (need 1)",
        f"gate {second.id}: after (predecessor {first.id} not done, need 1)",
    ])


# -- #549: the last gate per held job lands in the status file; `runs.py status` prints it -----------

def _mk(path: Path) -> Path:
    path.mkdir()
    return path


def _gates(daemon) -> dict:
    import json
    daemon.write_status(interval=10.0)
    return json.loads(daemon.status_path.read_text(encoding="utf-8"))["gates"]


def test_549_heavy_and_room_gates_in_status_file(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_NIGHT_10)
    holder = store.submit(host="pc", priority="P0", tag="h", cmd="python scripts/benchmark.py --workers 5", workers=5)
    heavy = store.submit(host="pc", priority="P1", tag="h2", cmd="python scripts/benchmark.py --workers 5", workers=5)
    daemon.tick()
    assert _gates(daemon) == {
        heavy.id: {"gate": "heavy", "detail": f"holder {holder.id}, need 5"}}
    # the holder ends: the heavy job starts and drops out of the map
    daemon.launcher.exit_codes[store.get(holder.id).pid] = 0
    daemon.tick()
    daemon.tick()
    assert store.get(heavy.id).state == "running"
    assert _gates(daemon) == {}

    daemon2, store2, _ = make_daemon(_mk(tmp_path / "b"), slots=FakeSlots().foreign(10), budget=BUDGET_NIGHT_10)
    job = store2.submit(host="pc", priority="P1", tag="w", cmd="python scripts/benchmark.py --workers 1", workers=1)
    daemon2.tick()
    assert _gates(daemon2) == {job.id: {"gate": "room", "detail": "used 10/10, need 1"}}


def test_598_no_restart_gate_in_status_file(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_NIGHT_10)
    store.submit(host="pc", priority="P1", tag="run", cmd="python scripts/benchmark.py --workers 1", workers=1)
    daemon.tick()  # a running job keeps the boundary from restarting yet
    daemon._restart_watch = type("W", (), {"due": lambda self: ("a" * 40, "b" * 40)})()
    daemon._respawn = lambda: None
    job = store.submit(host="pc", priority="P1", tag="w", cmd="python scripts/benchmark.py --workers 1", workers=1)
    daemon.tick()
    assert all(g["gate"] != "restart" for g in _gates(daemon).values())  # #598: starts are never held
    assert store.get(job.id).state == "running"


def test_549_status_prints_held_line_and_unknown_when_stale(tmp_path: Path, capsys, monkeypatch) -> None:
    import json
    from datetime import datetime, timedelta, timezone
    import runs
    from junkroan.runs.store import Store

    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "st"))
    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)
    job = store.submit(host="pc", priority="P1", tag="a", cmd="echo a", workers=5)
    quiet = store.submit(host="pc", priority="P1", tag="b", cmd="echo b")
    status_file = tmp_path / "st" / "daemon-pc.json"
    status_file.parent.mkdir()

    def write(age_seconds: float) -> None:
        tick = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        status_file.write_text(json.dumps({
            "last_tick": tick.isoformat(timespec="seconds"),
            "gates": {job.id: {"gate": "heavy", "detail": "holder j-x, need 5"}}}), encoding="utf-8")

    write(10)
    assert runs.main(["--store", str(store_path), "status"]) == 0
    out = capsys.readouterr().out
    assert f"{job.id} held: heavy (holder j-x, need 5)" in out
    assert f"{quiet.id} held" not in out

    write(600)
    assert runs.main(["--store", str(store_path), "status"]) == 0
    out = capsys.readouterr().out
    assert f"{job.id} held: unknown (daemon status 10 min old)" in out
