"""#443: a job wider than the mode's queue LIMIT is held alone; it never blocks the jobs behind it."""

from __future__ import annotations

from pathlib import Path

from junkroan.pob import slot_budget

from tests.test_runs_daemon import make_daemon


def _budget(total: int, period: str = "period-x") -> slot_budget.Budget:
    return slot_budget.Budget(period=period, hours=(0, 24), total=total, others=0,
                              min_free_ram_gb=0.0, strict_reserve=False)


def _on_mode(daemon, mode: str) -> None:
    daemon._mode_name = lambda: mode


def _submit(store, tag: str, workers: int):
    return store.submit(host="pc", priority="P2", tag=tag, cmd=f"python scripts/benchmark.py --tag {tag}",
                        workers=workers)


def test_row1_wider_than_limit_is_held_alone_and_logged_once(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3))
    daemon.log = logged.append
    _on_mode(daemon, "play")
    a, b, c = _submit(store, "a", 5), _submit(store, "b", 3), _submit(store, "c", 2)

    assert daemon.fill() == [b.id]
    assert daemon.fill() == []
    assert store.get(a.id).state == "queued"
    assert store.get(c.id).state == "queued"  # fits the limit, waits for room
    held = [line for line in logged if line.startswith("held: ")]
    assert held == [f"held: {a.id} needs 5 > queue limit 3 (mode play)"]
    assert "period-x" not in held[0]


def test_448_row1_line_names_the_mode_not_the_period(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3, "day"))
    daemon.log = logged.append
    _on_mode(daemon, "play")
    a = _submit(store, "a", 5)
    daemon.fill()
    assert logged == [f"held: {a.id} needs 5 > queue limit 3 (mode play)"]
    assert "day" not in logged[0]


def test_448_row2_same_period_new_mode_and_limit_writes_a_second_line(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3, "day"))
    daemon.log = logged.append
    _on_mode(daemon, "play")
    a = _submit(store, "a", 6)
    daemon.fill()
    daemon.fill()
    daemon._budget_loader = lambda: _budget(5, "day")
    _on_mode(daemon, "normal")
    daemon.fill()
    daemon.fill()
    held = [line for line in logged if line.startswith("held: ")]
    assert held == [f"held: {a.id} needs 6 > queue limit 3 (mode play)",
                    f"held: {a.id} needs 6 > queue limit 5 (mode normal)"]


def test_row2_job_that_fits_the_limit_keeps_the_head_of_line_wait(tmp_path: Path) -> None:
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3))
    _submit(store, "run", 1)
    assert len(daemon.fill()) == 1
    a, b = _submit(store, "a", 3), _submit(store, "b", 2)
    assert daemon.fill() == []
    assert store.get(a.id).state == "queued"
    assert store.get(b.id).state == "queued"


def test_row3_mode_with_a_wider_limit_starts_the_wide_job_first(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3))
    daemon.log = logged.append
    _on_mode(daemon, "play")
    a, b = _submit(store, "a", 5), _submit(store, "b", 3)
    daemon._budget_loader = lambda: _budget(5, "night")
    assert daemon.fill() == [a.id]
    assert not [line for line in logged if line.startswith("held: ")]
    assert store.get(b.id).state == "queued"


def test_line_is_written_again_when_the_mode_changes(tmp_path: Path) -> None:
    logged: list[str] = []
    daemon, store, _ = make_daemon(tmp_path, budget=_budget(3))
    daemon.log = logged.append
    _on_mode(daemon, "play")
    a = _submit(store, "a", 5)
    daemon.fill()
    daemon._budget_loader = lambda: _budget(4, "day")
    _on_mode(daemon, "day")
    daemon.fill()
    daemon.fill()
    held = [line for line in logged if line.startswith("held: ")]
    assert held == [f"held: {a.id} needs 5 > queue limit 3 (mode play)",
                    f"held: {a.id} needs 5 > queue limit 4 (mode day)"]
