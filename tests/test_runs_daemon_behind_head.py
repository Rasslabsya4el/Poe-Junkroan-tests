"""#834: a small job starts on free slots behind a room-blocked head when that cannot delay the head. PoB-free."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import slot_budget  # noqa: E402

from test_runs_daemon import FakeLauncher, FakeSlots, make_daemon  # noqa: E402,F401
from test_runs_daemon import _isolated_daemon_status  # noqa: E402,F401  (autouse fixture of that file)

OPEN_7 = slot_budget.Budget(period="day", hours=(0, 24), total=7, others=2, min_free_ram_gb=0.0, strict_reserve=False)


def _setup(tmp_path: Path, busy: int = 3):
    logs: list[str] = []
    slots = FakeSlots().foreign(busy)
    daemon, store, launcher = make_daemon(tmp_path, launcher=FakeLauncher(), budget=OPEN_7, slots=slots)
    daemon.log = logs.append
    return daemon, store, slots, logs


def _sub(store, tag: str, workers: int):
    return store.submit(host="pc", priority="P1", tag=tag, cmd=f"python x.py --workers {workers}", workers=workers)


def test_1_small_job_starts_behind_the_head(tmp_path: Path) -> None:
    daemon, store, _, logs = _setup(tmp_path)
    a, b = _sub(store, "a", 5), _sub(store, "b", 1)
    assert daemon.fill() == [b.id]
    assert store.get(a.id).state == "queued"
    assert any(f"gate {a.id}: room (used" in m and "need 5)" in m for m in logs)
    assert not any(f"{b.id}: room" in m for m in logs)          # row 5: B was never weighed against the room
    assert not any("room (used 3/7, need 1)" in m for m in logs)


def test_2_head_starts_when_the_running_job_ends(tmp_path: Path) -> None:
    daemon, store, slots, _ = _setup(tmp_path)
    a, b = _sub(store, "a", 5), _sub(store, "b", 1)
    assert daemon.fill() == [b.id]
    slots.rows[:] = []                                           # the 3 running slots end; B holds its own
    assert daemon.fill() == [a.id]                               # 5 + 1 <= 7
    assert store.get(b.id).state == "running"


def test_3_second_small_job_would_delay_the_head(tmp_path: Path) -> None:
    daemon, store, _, logs = _setup(tmp_path)
    a, b, c = _sub(store, "a", 5), _sub(store, "b", 1), _sub(store, "c", 2)
    assert daemon.fill() == [b.id]                               # 1 + 2 + 5 > 7
    assert store.get(c.id).state == "queued"
    assert any(f"gate {c.id}: behind {a.id} (needs 5, free" in m for m in logs)


def test_4_fits_the_room_but_not_the_sum(tmp_path: Path) -> None:
    daemon, store, _, logs = _setup(tmp_path)
    a, b = _sub(store, "a", 5), _sub(store, "b", 3)
    assert daemon.fill() == []                                   # 3 + 5 > 7 although room is 4
    assert any(f"gate {b.id}: behind {a.id}" in m for m in logs)


def test_5_a_later_submit_never_passes_when_the_sum_is_full(tmp_path: Path) -> None:
    daemon, store, _, _ = _setup(tmp_path)
    a, b, c = _sub(store, "a", 5), _sub(store, "b", 1), _sub(store, "c", 1)
    assert daemon.fill() == [b.id, c.id]                         # 1 + 1 + 5 <= 7
    d = _sub(store, "d", 1)
    assert daemon.fill() == []                                   # 1 + 1 + 1 + 5 > 7 is not asked: room is 0 too
    assert store.get(a.id).state == "queued" and store.get(d.id).state == "queued"
