"""#1118 unit 2: the merge queue's CPU share the start gate reads (`junkroan.runs.merge_share.merge_cores`).

Fake process tables and fake lock holders only: the real process table is never scanned here.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from junkroan.runs.merge_share import merge_cores

LOCK_STARTED = "2026-10-15 22:00:00"
STARTED = datetime(2026, 10, 15, 22, 0, 0).timestamp()  # the lock's `started`, as epoch seconds
T0 = STARTED + 100.0  # the first tick
T1 = T0 + 1.0  # the next tick, one second later


def _proc(ppid: int, name: str, cpu: float, created: float, cmdline: str | None = None) -> dict:
    p = {"ppid": ppid, "name": name, "cpu": cpu, "created": created}
    if cmdline is not None:
        p["cmdline"] = cmdline
    return p


def _holder(pid: int) -> list[dict]:
    return [{"pid": pid, "started": LOCK_STARTED}]


def _tree_at(merge_cpu: tuple[float, float, float], other_cpu: float) -> dict[int, dict]:
    """A merge tree (root 10 with children 11, 12) under the init-like pid 1, and an unrelated tree (20 -> 21)."""
    root, child_a, child_b = merge_cpu
    return {
        1: _proc(0, "init.exe", 0.0, STARTED - 9999),
        10: _proc(1, "python.exe", root, STARTED - 5),  # the merge process: the merge.lock holder
        11: _proc(10, "pytest.exe", child_a, STARTED + 1),
        12: _proc(10, "python.exe", child_b, STARTED + 1),
        20: _proc(1, "claude.exe", 7.0, STARTED - 3600),
        21: _proc(20, "python.exe", other_cpu, STARTED - 3600),
    }


def test_merge_tree_deltas_sum_to_cores():
    # Root + two children gain 1.5 + 1.0 + 1.0 CPU-seconds over one second: 3.5 cores.
    # The unrelated tree (21) burns 4.0 more over that second and must not count.
    locks = lambda: _holder(10)  # noqa: E731
    _, state = merge_cores(None, T0, processes=lambda: _tree_at((2.0, 1.0, 1.0), 1.0), lock_reader=locks)
    cores, _ = merge_cores(
        state, T1, processes=lambda: _tree_at((3.5, 2.0, 2.0), 5.0), lock_reader=locks,
    )
    assert cores == pytest.approx(3.5)


def test_no_lock_holder_is_zero_cores():
    procs = lambda: _tree_at((2.0, 1.0, 1.0), 1.0)  # noqa: E731
    cores, _ = merge_cores(None, T0, processes=procs, lock_reader=lambda: [])
    assert cores == 0.0
    cores, _ = merge_cores({"t": T0, "p": {}}, T1, processes=procs, lock_reader=lambda: [])
    assert cores == 0.0


def test_process_table_raising_is_none():
    def boom():
        raise OSError("process table unreadable")

    cores, state = merge_cores(None, T0, processes=boom, lock_reader=lambda: _holder(10))
    assert cores is None
    assert state == {}


def test_lock_unreadable_is_none():
    def boom():
        raise ValueError("lock file half written")

    cores, _ = merge_cores(None, T0, processes=lambda: _tree_at((2.0, 1.0, 1.0), 1.0), lock_reader=boom)
    assert cores is None


def test_lock_holder_created_after_started_plus_two_seconds_is_not_accepted():
    # Pid 10 was created 5 s after the lock says it started: a reused pid, not the merge.
    procs = {
        10: _proc(1, "python.exe", 2.0, STARTED + 5),
        11: _proc(10, "pytest.exe", 1.0, STARTED + 5),
    }
    cores, _ = merge_cores(None, T0, processes=lambda: procs, lock_reader=lambda: _holder(10))
    assert cores == 0.0
    procs_next = {
        10: _proc(1, "python.exe", 4.0, STARTED + 5),
        11: _proc(10, "pytest.exe", 3.0, STARTED + 5),
    }
    cores, _ = merge_cores({"t": T0, "p": {10: [STARTED + 5, 2.0], 11: [STARTED + 5, 1.0]}}, T1,
                           processes=lambda: procs_next, lock_reader=lambda: _holder(10))
    assert cores == 0.0


def test_child_of_a_non_merge_process_is_not_counted():
    # Only the merge tree's CPU counts: pid 21 (child of the unrelated 20) burns 9 s and is left out.
    first = _tree_at((2.0, 1.0, 1.0), 1.0)
    second = _tree_at((2.0, 1.0, 1.0), 10.0)
    locks = lambda: _holder(10)  # noqa: E731
    _, state = merge_cores(None, T0, processes=lambda: first, lock_reader=locks)
    cores, _ = merge_cores(state, T1, processes=lambda: second, lock_reader=locks)
    assert cores == 0.0


def test_first_tick_with_a_merge_tree_has_no_delta_so_none():
    cores, state = merge_cores(None, T0, processes=lambda: _tree_at((2.0, 1.0, 1.0), 1.0),
                               lock_reader=lambda: _holder(10))
    assert cores is None
    assert state["t"] == T0


def test_suite_wrapper_under_wscript_is_a_merge_root():
    # A merge's suite on this host: powershell run by wscript whose command line names `-suite-<sha8>.out.ps1`.
    procs = {
        1: _proc(0, "init.exe", 0.0, STARTED - 9999),
        30: _proc(1, "wscript.exe", 0.0, STARTED - 50),
        31: _proc(30, "powershell.exe", 1.0, STARTED - 50,
                  cmdline="powershell -File C:/x/poe-junkroan-suite-0a1b2c3d.out.ps1"),
        32: _proc(31, "python.exe", 2.0, STARTED - 40),
    }
    later = {k: dict(v, cpu=v["cpu"] + d) for (k, v), d in zip(procs.items(), (0.0, 0.0, 0.5, 1.0))}
    _, state = merge_cores(None, T0, processes=lambda: procs, lock_reader=lambda: [])
    cores, _ = merge_cores(state, T1, processes=lambda: later, lock_reader=lambda: [])
    assert cores == pytest.approx(1.5)
