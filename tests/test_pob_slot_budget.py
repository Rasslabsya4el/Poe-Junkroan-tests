"""The machine-wide PoB slot budget (`src/junkroan/pob/slot_budget.py`).

Fast: no PoB, no real `var/` (every test gets its own lock directory and its own budget file), a
fake clock for the day / night windows and a fake memory reader for the RAM guard. The one thing
that cannot be faked is the OS lock itself, so the tests that prove "a killed holder frees its
slot" and "the second acquirer waits" run real child processes against the real lock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from junkroan.pob import slot_budget
from tests.timing_bound import bound

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

PLENTY_OF_RAM = 999.0

# A child that takes one slot, prints its number, and then sits there until it is killed.
HOLDER_SOURCE = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, {str(SRC)!r})
from junkroan.pob import slot_budget

handle = slot_budget.acquire_slot(
    role=sys.argv[2],
    directory=Path(sys.argv[1]),
    budget_file=Path(sys.argv[3]),
    ram_reader=lambda: {PLENTY_OF_RAM},
    poll_seconds=0.1,
)
print(handle.slot, flush=True)
time.sleep(600)
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No stray JUNKROAN_POB_* from the shell the suite was started in."""

    for name in (
        "JUNKROAN_POB_SLOTS",
        "JUNKROAN_POB_ROLE",
        "JUNKROAN_POB_PRIORITY",
        "JUNKROAN_POB_SLOT_DIR",
        "JUNKROAN_POB_BUDGET",
    ):
        monkeypatch.delenv(name, raising=False)
    # #847: the budget tests expect the DAY budget (7 / 2); pinned so the clock does not decide
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    monkeypatch.setattr(slot_budget, "_role_cache", None)


@pytest.fixture
def slots(tmp_path):
    folder = tmp_path / "locks"
    folder.mkdir()
    return folder


def write_budget(
    path: Path, *, total: int, others: int, min_free_ram_gb: float = 0.0, strict_reserve: bool = False
) -> Path:
    """One period covering every hour, so the tests never depend on the wall clock.

    ``strict_reserve`` defaults to ``False`` (today's/legacy behaviour, #41 send-back): a test that
    means to exercise the opt-in reserve (the queue capped at ``total - others``, or a reservation
    moving that cap) must pass ``strict_reserve=True`` explicitly.
    """

    path.write_text(
        json.dumps(
            {
                "day": {"hours": [0, 24], "total": total, "others": others, "min_free_ram_gb": min_free_ram_gb},
                "strict_reserve": strict_reserve,
            }
        ),
        encoding="utf-8",
    )
    return path


def holder(slots: Path, budget_file: Path, role: str, tmp_path: Path) -> tuple[subprocess.Popen, int]:
    """Start a child that holds one slot; returns (process, the slot number it took)."""

    script = tmp_path / "hold_slot.py"
    script.write_text(HOLDER_SOURCE, encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(script), str(slots), role, str(budget_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    line = process.stdout.readline().strip()
    assert line.isdigit(), f"holder did not take a slot (said {line!r})"
    return process, int(line)


# A child that opens a queue waiter marker at the given priority and sits there until killed --
# the priority gate only ever sees a LIVE waiter, so testing it needs a real held lock.
WAITER_SOURCE = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, {str(SRC)!r})
from junkroan.pob import slot_budget

lock = slot_budget._open_waiter(Path(sys.argv[1]), slot_budget.ROLE_QUEUE, "test", sys.argv[2])
print(lock.path.name if lock else "", flush=True)
time.sleep(600)
"""


def priority_waiter(slots: Path, priority: str, tmp_path: Path) -> subprocess.Popen:
    """Start a child holding a live 'queue' waiter marker at ``priority``."""

    script = tmp_path / f"wait_{priority}.py"
    script.write_text(WAITER_SOURCE, encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(script), str(slots), priority],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    line = process.stdout.readline().strip()
    assert line, "priority waiter did not open its marker"
    return process


def take(slots: Path, budget_file: Path, role: str, ram: float = PLENTY_OF_RAM):
    return slot_budget.try_acquire_slot(
        role=role, directory=slots, budget_file=budget_file, ram_reader=lambda: ram
    )


# -- the budget document -----------------------------------------------------------------------

def test_defaults_are_written_on_first_use(tmp_path):
    path = tmp_path / "machine_budget.json"
    budget = slot_budget.load_budget(now=datetime(2026, 9, 20, 12, 0), path=path)
    assert json.loads(path.read_text(encoding="utf-8")) == slot_budget.DEFAULT_BUDGET
    assert (budget.period, budget.total, budget.others, budget.min_free_ram_gb) == ("day", 7, 2, 8)


@pytest.mark.parametrize(
    "moment, period, total, others",
    [
        (datetime(2026, 9, 20, 8, 0), "day", 7, 2),      # the day window opens at 08:00
        (datetime(2026, 9, 20, 12, 30), "day", 7, 2),
        (datetime(2026, 9, 20, 0, 30), "day", 7, 2),     # [8, 25] reaches past midnight
        (datetime(2026, 9, 20, 0, 59), "day", 7, 2),
        (datetime(2026, 9, 20, 1, 30), "night", 10, 5),  # ... but not to 01:30
        (datetime(2026, 9, 20, 7, 59), "night", 10, 5),
    ],
)
def test_day_night_windows(tmp_path, monkeypatch, moment, period, total, others):
    monkeypatch.delenv("JUNKROAN_FORCE_PERIOD", raising=False)  # #847: an explicit `now` decides
    budget = slot_budget.load_budget(now=moment, path=tmp_path / "budget.json")
    assert (budget.period, budget.total, budget.others) == (period, total, others)


# -- the strict reserve (#41, opt-in send-back): a host must set the top-level "strict_reserve"
# flag before the queue is held to total - others; without it the queue's limit is the full total,
# exactly as before #41 (a laptop with others == total would otherwise stall at limit 0) -----------

def test_limit_for_is_the_full_total_without_the_flag(tmp_path):
    """No `strict_reserve` (the default): the queue's limit is `total`, others == total or not."""

    budget_file = write_budget(tmp_path / "budget.json", total=3, others=3)
    budget = slot_budget.load_budget(path=budget_file)
    assert budget.strict_reserve is False
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 3
    assert budget.limit_for(slot_budget.ROLE_OTHER) == 3


def test_limit_for_is_total_minus_others_with_the_flag_on(tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2, strict_reserve=True)
    budget = slot_budget.load_budget(path=budget_file)
    assert budget.strict_reserve is True
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 5
    assert budget.limit_for(slot_budget.ROLE_OTHER) == 2


def test_limit_for_never_drops_below_one_with_the_flag_on(tmp_path):
    """The guard/floor: total == others still leaves the queue one slot, never zero."""

    budget_file = write_budget(tmp_path / "budget.json", total=3, others=3, strict_reserve=True)
    budget = slot_budget.load_budget(path=budget_file)
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 1
    assert budget.limit_for(slot_budget.ROLE_OTHER) == 3


def test_queue_never_takes_an_others_slot_even_when_idle(slots, tmp_path):
    """With the flag on the queue stops at total - others, even though nobody holds those slots."""

    budget_file = write_budget(tmp_path / "budget.json", total=5, others=2, strict_reserve=True)
    # nobody holds slots 1-2 (the 'others' share) -- the queue must still never reach them.
    held = [take(slots, budget_file, slot_budget.ROLE_QUEUE) for _ in range(3)]
    assert sorted(handle.slot for handle in held) == [3, 4, 5]
    assert take(slots, budget_file, slot_budget.ROLE_QUEUE) is None, "the queue's 4th attempt must not reach slot 1 or 2"
    other = take(slots, budget_file, slot_budget.ROLE_OTHER)
    assert other is not None and other.slot == 1, "the reserved 'others' slots are still free"
    for handle in (*held, other):
        handle.release()


def test_budget_file_is_reread_between_attempts(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=1)
    first = take(slots, budget_file, slot_budget.ROLE_OTHER)
    assert first is not None and first.slot == 1
    assert take(slots, budget_file, slot_budget.ROLE_OTHER) is None  # others = 1, and it is taken

    write_budget(budget_file, total=4, others=2)  # the lead widens the budget while jobs run
    second = take(slots, budget_file, slot_budget.ROLE_OTHER)
    assert second is not None and second.slot == 2
    first.release()
    second.release()


def test_unreadable_budget_falls_back_to_the_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("JUNKROAN_FORCE_PERIOD", raising=False)  # #847: an explicit `now` decides
    path = tmp_path / "budget.json"
    path.write_text("{not json", encoding="utf-8")
    budget = slot_budget.load_budget(now=datetime(2026, 9, 20, 3, 0), path=path)
    assert (budget.period, budget.total, budget.others) == ("night", 10, 5)


# -- roles -------------------------------------------------------------------------------------

def test_others_are_confined_to_the_first_slots(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=5, others=2)
    held = [take(slots, budget_file, slot_budget.ROLE_OTHER) for _ in range(2)]
    assert [handle.slot for handle in held] == [1, 2]
    assert take(slots, budget_file, slot_budget.ROLE_OTHER) is None
    for handle in held:
        handle.release()


def test_queue_gets_a_slot_above_others(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=5, others=2)
    held = [take(slots, budget_file, slot_budget.ROLE_OTHER) for _ in range(2)]
    assert [handle.slot for handle in held] == [1, 2]

    queue = take(slots, budget_file, slot_budget.ROLE_QUEUE)
    assert queue is not None and queue.slot > 2, "the queue must find a slot no agent can hold"
    assert queue.slot == 5, "the queue walks down from the top so it never squats on an open slot"
    for handle in (*held, queue):
        handle.release()


def test_role_comes_from_the_environment(monkeypatch, slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=3, others=1)
    monkeypatch.setenv("JUNKROAN_POB_ROLE", "queue")
    assert slot_budget.current_role() == slot_budget.ROLE_QUEUE
    handle = slot_budget.try_acquire_slot(directory=slots, budget_file=budget_file, ram_reader=lambda: PLENTY_OF_RAM)
    assert handle is not None and handle.slot == 3
    handle.release()

    monkeypatch.setenv("JUNKROAN_POB_ROLE", "")
    assert slot_budget.current_role(ancestry=lambda: []) == slot_budget.ROLE_OTHER


# -- the role of a process the queue started before this code existed --------------------------

QUEUE_ANCESTOR = r"C:\Python312\python.exe C:\Coding\poe-junkroan-v2\scripts\run_queue.py --queue artifacts/runs/queue.txt"


def test_a_run_queue_ancestor_makes_the_process_queue():
    """The running queue runner predates this code and sets no variable; its children still count."""

    chain = ["python benchmark.py --tag x", "cmd /c python benchmark.py --tag x", QUEUE_ANCESTOR]
    assert slot_budget.current_role(ancestry=lambda: chain) == slot_budget.ROLE_QUEUE
    assert slot_budget.current_role(ancestry=lambda: chain[:2]) == slot_budget.ROLE_OTHER
    assert slot_budget.current_role(ancestry=lambda: []) == slot_budget.ROLE_OTHER


def test_the_environment_wins_over_the_ancestry(monkeypatch):
    queue_chain = [QUEUE_ANCESTOR]
    monkeypatch.setenv("JUNKROAN_POB_ROLE", "other")
    assert slot_budget.current_role(ancestry=lambda: queue_chain) == slot_budget.ROLE_OTHER
    monkeypatch.setenv("JUNKROAN_POB_ROLE", "queue")
    assert slot_budget.current_role(ancestry=lambda: ["python scripts/benchmark.py"]) == slot_budget.ROLE_QUEUE


def test_an_ancestry_reader_that_raises_is_other():
    def denied() -> list[str]:
        raise RuntimeError("access is denied")

    assert slot_budget.current_role(ancestry=denied) == slot_budget.ROLE_OTHER


def test_the_derived_role_is_read_once_per_process(monkeypatch):
    calls = {"n": 0}

    def chain() -> list[str]:
        calls["n"] += 1
        return [QUEUE_ANCESTOR]

    monkeypatch.setattr(slot_budget, "_ancestor_command_lines", chain)
    assert slot_budget.current_role() == slot_budget.ROLE_QUEUE
    assert slot_budget.current_role() == slot_budget.ROLE_QUEUE
    assert calls["n"] == 1, "a process's ancestry does not change; the psutil walk runs once"
    assert slot_budget.role_source() == "process ancestry"


def test_a_slot_taken_by_a_queue_descendant_is_recorded_as_queue(monkeypatch, slots, tmp_path):
    """What machine_load.py prints per holder is the role the holder itself derived."""

    budget_file = write_budget(tmp_path / "budget.json", total=4, others=1)
    monkeypatch.setattr(slot_budget, "_ancestor_command_lines", lambda: [QUEUE_ANCESTOR])
    handle = slot_budget.try_acquire_slot(directory=slots, budget_file=budget_file, ram_reader=lambda: PLENTY_OF_RAM)
    assert handle is not None and handle.slot == 4, "it took a queue slot, not the single 'other' one"
    rows = slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))
    assert [(row["slot"], row["role"]) for row in rows] == [(4, "queue")]
    handle.release()


def test_82_a_slot_carries_the_runs_job_that_owns_it(monkeypatch, slots, tmp_path):
    """`JUNKROAN_RUNS_JOB` on a job's children tags their slots, so the runs daemon can tell its
    own PoB workers' slots from a foreign run's (#82)."""

    budget_file = write_budget(tmp_path / "budget.json", total=4, others=1)
    monkeypatch.setenv(slot_budget.JOB_ENV, "j-20260926-2300-abcd")
    handle = slot_budget.try_acquire_slot(directory=slots, budget_file=budget_file, ram_reader=lambda: PLENTY_OF_RAM)
    assert handle is not None
    rows = slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))
    assert [row["job"] for row in rows] == ["j-20260926-2300-abcd"]
    handle.release()

    monkeypatch.delenv(slot_budget.JOB_ENV)
    other = slot_budget.try_acquire_slot(directory=slots, budget_file=budget_file, ram_reader=lambda: PLENTY_OF_RAM)
    assert other is not None
    rows = slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))
    assert [row["job"] for row in rows] == [None], "anything the daemon did not start carries no job"
    other.release()


# -- priority (P0/P1/P2, queue role only; #37) --------------------------------------------------

def test_priority_defaults_to_p2_when_unset():
    assert slot_budget.current_priority() == "P2"


@pytest.mark.parametrize(
    "raw, expected",
    [("0", "P0"), ("1", "P1"), ("2", "P2"), ("p0", "P0"), ("P1", "P1"), ("weird", "P2"), ("", "P2")],
)
def test_priority_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("JUNKROAN_POB_PRIORITY", raw)
    assert slot_budget.current_priority() == expected


def test_p0_waiter_takes_the_slot_ahead_of_a_live_p2_waiter(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=1, others=0)
    low = priority_waiter(slots, "P2", tmp_path)
    high = priority_waiter(slots, "P0", tmp_path)
    try:
        assert take(slots, budget_file, slot_budget.ROLE_QUEUE) is None, "P2 tries; a live P0 waiter is ahead of it"
        handle = slot_budget.try_acquire_slot(
            role=slot_budget.ROLE_QUEUE, priority="P0", directory=slots, budget_file=budget_file,
            ram_reader=lambda: PLENTY_OF_RAM,
        )
        assert handle is not None and handle.slot == 1, "the P0 waiter is not blocked by anyone"
        handle.release()
    finally:
        for process in (low, high):
            process.kill()
            process.wait(timeout=30)


def test_a_dead_priority_marker_never_blocks(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=1, others=0)
    dead = priority_waiter(slots, "P0", tmp_path)
    dead.kill()
    dead.wait(timeout=30)
    handle = slot_budget.try_acquire_slot(
        role=slot_budget.ROLE_QUEUE, priority="P2", directory=slots, budget_file=budget_file,
        ram_reader=lambda: PLENTY_OF_RAM,
    )
    assert handle is not None and handle.slot == 1, "a dead P0 marker must not block a live P2"
    handle.release()


def test_p1_is_blocked_by_a_live_p0_but_not_by_a_live_p2(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=1, others=0)
    low = priority_waiter(slots, "P2", tmp_path)
    try:
        handle = slot_budget.try_acquire_slot(
            role=slot_budget.ROLE_QUEUE, priority="P1", directory=slots, budget_file=budget_file,
            ram_reader=lambda: PLENTY_OF_RAM,
        )
        assert handle is not None, "a live P2 waiter must not block P1"
        handle.release()
    finally:
        low.kill()
        low.wait(timeout=30)

    high = priority_waiter(slots, "P0", tmp_path)
    try:
        blocked = slot_budget.try_acquire_slot(
            role=slot_budget.ROLE_QUEUE, priority="P1", directory=slots, budget_file=budget_file,
            ram_reader=lambda: PLENTY_OF_RAM,
        )
        assert blocked is None, "a live P0 waiter must block P1"
    finally:
        high.kill()
        high.wait(timeout=30)


def test_an_others_waiter_ignores_a_live_p0_queue_waiter(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=2, others=1)
    high = priority_waiter(slots, "P0", tmp_path)
    try:
        handle = slot_budget.try_acquire_slot(
            role=slot_budget.ROLE_OTHER, priority="P2", directory=slots, budget_file=budget_file,
            ram_reader=lambda: PLENTY_OF_RAM,
        )
        assert handle is not None and handle.slot == 1, "the 'others' role is not gated by queue priority at all"
        handle.release()
    finally:
        high.kill()
        high.wait(timeout=30)


def test_equal_priority_waiters_behave_as_today(slots, tmp_path):
    """Unset everywhere -> everyone is P2 -> the gate never fires: today's FIFO-by-luck behaviour."""

    budget_file = write_budget(tmp_path / "budget.json", total=1, others=0)
    other = priority_waiter(slots, "P2", tmp_path)
    try:
        handle = take(slots, budget_file, slot_budget.ROLE_QUEUE)
        assert handle is not None and handle.slot == 1
        handle.release()
    finally:
        other.kill()
        other.wait(timeout=30)


def test_waiter_and_holder_lock_files_carry_priority(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=1, others=0)
    monkeypatch_priority = priority_waiter(slots, "P0", tmp_path)
    try:
        rows = slot_budget.waiting(slots)
        assert [(row["role"], row["priority"]) for row in rows] == [(slot_budget.ROLE_QUEUE, "P0")]
    finally:
        monkeypatch_priority.kill()
        monkeypatch_priority.wait(timeout=30)

    handle = slot_budget.try_acquire_slot(
        role=slot_budget.ROLE_QUEUE, priority="P1", directory=slots, budget_file=budget_file,
        ram_reader=lambda: PLENTY_OF_RAM,
    )
    assert handle is not None
    rows = slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))
    assert [(row["role"], row["priority"]) for row in rows] == [(slot_budget.ROLE_QUEUE, "P1")]
    handle.release()


# -- waiting -----------------------------------------------------------------------------------

def test_the_second_other_waits_until_the_first_releases(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=1)
    first = take(slots, budget_file, slot_budget.ROLE_OTHER)
    assert first is not None and first.slot == 1

    messages: list[str] = []
    result: dict[str, slot_budget.SlotHandle] = {}

    def waiter() -> None:
        result["handle"] = slot_budget.acquire_slot(
            role=slot_budget.ROLE_OTHER,
            directory=slots,
            budget_file=budget_file,
            ram_reader=lambda: PLENTY_OF_RAM,
            poll_seconds=0.05,
            log=messages.append,
        )

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.5)
    assert "handle" not in result, "the only 'other' slot is held; the second acquirer must wait"
    assert messages and messages[0].startswith("waiting for a PoB slot: 1/1 in use by pids ["), messages
    assert [row["pid"] for row in slot_budget.waiting(slots)] == [os.getpid()]

    first.release()
    thread.join(timeout=10)
    assert not thread.is_alive()
    handle = result["handle"]
    assert handle.slot == 1
    assert handle.waited_seconds > 0
    assert messages[-1].startswith("got PoB slot 1 after ")
    assert slot_budget.waiting(slots) == [], "the marker goes the moment the wait ends, not at close"
    assert [row["slot"] for row in slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))] == [1]
    handle.release()


def test_a_callers_timeout_gives_a_slotless_handle(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=2, others=1)
    first = take(slots, budget_file, slot_budget.ROLE_OTHER)
    handle = slot_budget.acquire_slot(
        role=slot_budget.ROLE_OTHER, directory=slots, budget_file=budget_file,
        ram_reader=lambda: PLENTY_OF_RAM, poll_seconds=0.05, timeout=0.3, log=lambda _m: None,
    )
    assert handle.held is False and handle.slot is None and "timeout" in handle.reason
    first.release()


# -- the lock dies with the process ------------------------------------------------------------

def test_a_killed_holder_frees_its_slot(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=3, others=1)
    process, slot = holder(slots, budget_file, slot_budget.ROLE_OTHER, tmp_path)
    try:
        assert slot == 1
        rows = slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file))
        assert [(row["slot"], row["pid"], row["role"]) for row in rows] == [(1, process.pid, "other")]
        assert take(slots, budget_file, slot_budget.ROLE_OTHER) is None
    finally:
        process.kill()
        process.wait(timeout=30)

    deadline = time.monotonic() + 10
    handle = None
    while handle is None and time.monotonic() < deadline:
        handle = take(slots, budget_file, slot_budget.ROLE_OTHER)
        if handle is None:
            time.sleep(0.1)
    assert handle is not None, "a killed holder must free its slot with no cleanup"
    assert handle.slot == 1
    handle.release()


def test_a_released_slot_file_is_not_counted_as_in_use(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=3, others=2)
    handle = take(slots, budget_file, slot_budget.ROLE_OTHER)
    path = handle.path
    handle.release()
    assert path.is_file(), "the lock file stays; only the lock is gone"
    assert slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file)) == []


# -- the RAM guard -----------------------------------------------------------------------------

def test_ram_guard_blocks_and_then_lets_through(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=2, min_free_ram_gb=8)
    assert take(slots, budget_file, slot_budget.ROLE_OTHER, ram=5.1) is None
    handle = take(slots, budget_file, slot_budget.ROLE_OTHER, ram=8.0)
    assert handle is not None and handle.slot == 1
    handle.release()


def test_ram_guard_wait_line_names_the_numbers(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=2, min_free_ram_gb=8)
    messages: list[str] = []
    handle = slot_budget.acquire_slot(
        role=slot_budget.ROLE_OTHER, directory=slots, budget_file=budget_file,
        ram_reader=lambda: 5.1, poll_seconds=0.05, timeout=0.2, log=messages.append,
    )
    assert handle.held is False
    assert messages[0] == "waiting for a PoB slot: RAM free 5.1 GB < 8 GB"


# -- the off switch ----------------------------------------------------------------------------

def test_slots_off_takes_no_lock(monkeypatch, slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=1, others=1)
    monkeypatch.setenv("JUNKROAN_POB_SLOTS", "off")
    assert slot_budget.enabled() is False
    handle = slot_budget.acquire_slot(role=slot_budget.ROLE_OTHER, directory=slots, budget_file=budget_file)
    assert handle.held is False and handle.slot is None and handle.reason == "JUNKROAN_POB_SLOTS=off"
    handle.release()
    assert list(slots.glob("*.lock")) == []


def test_a_broken_slot_directory_never_raises(monkeypatch, tmp_path):
    """The counter protects builds; it must never be the thing that kills one."""

    monkeypatch.setattr(slot_budget, "load_budget", lambda **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    handle = slot_budget.acquire_slot(role=slot_budget.ROLE_OTHER, directory=tmp_path / "locks", log=lambda _m: None)
    assert handle.held is False and handle.reason.startswith("error: RuntimeError")


# -- the lock file's own line ------------------------------------------------------------------

def test_the_lock_file_names_pid_role_command_and_start(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=2, others=2)
    handle = take(slots, budget_file, slot_budget.ROLE_OTHER)
    info = slot_budget.read_info(handle.path)
    assert info["pid"] == os.getpid()
    assert info["role"] == "other"
    assert 0 < len(info["cmd"]) <= 120
    assert datetime.fromisoformat(info["started"]).year >= 2024
    assert handle.path.stat().st_size == 512, "one padded line, so the file never shrinks under a lock"
    handle.release()


# -- the verdict and scripts/machine_load.py ---------------------------------------------------

def test_verdict_counts_only_this_roles_slots(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=5, others=2, min_free_ram_gb=8)
    budget = slot_budget.load_budget(path=budget_file)
    queue = take(slots, budget_file, slot_budget.ROLE_QUEUE)
    go, line = slot_budget.verdict(2, slot_budget.ROLE_OTHER, directory=slots, budget=budget, ram_reader=lambda: 20.0)
    assert go is True, line  # the queue's slot 5 is not an 'other' slot

    held = [take(slots, budget_file, slot_budget.ROLE_OTHER) for _ in range(2)]
    go, line = slot_budget.verdict(1, slot_budget.ROLE_OTHER, directory=slots, budget=budget, ram_reader=lambda: 5.1)
    assert go is False
    assert line.startswith("WAIT: 2 of 2 'other' slots in use (pids ")
    assert line.endswith("RAM free 5.1 GB < 8 GB"), line  # the spec's verdict line, both reasons
    for handle in (queue, *held):
        handle.release()


def run_machine_load(slots: Path, budget_file: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "JUNKROAN_POB_SLOT_DIR": str(slots), "JUNKROAN_POB_BUDGET": str(budget_file)}
    env.pop("JUNKROAN_POB_ROLE", None)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "machine_load.py"), *args],
        capture_output=True, text=True, env=env, timeout=120,
    )


def test_machine_load_need_exit_codes(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=1, min_free_ram_gb=0)

    free = run_machine_load(slots, budget_file, "--need", "1", "--role", "other", "--quiet")
    assert free.returncode == 0, free.stdout + free.stderr
    assert free.stdout.startswith("GO ")

    process, _slot = holder(slots, budget_file, slot_budget.ROLE_OTHER, tmp_path)
    try:
        busy = run_machine_load(slots, budget_file, "--need", "1", "--role", "other", "--quiet")
        assert busy.returncode == 3, busy.stdout + busy.stderr
        assert busy.stdout.startswith("WAIT: 1 of 1 'other' slots in use (pids ")
        assert str(process.pid) in busy.stdout

        queue_ok = run_machine_load(slots, budget_file, "--need", "1", "--role", "queue", "--quiet")
        assert queue_ok.returncode == 0, queue_ok.stdout + queue_ok.stderr
    finally:
        process.kill()
        process.wait(timeout=30)


def test_machine_load_ram_guard_exit_code(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=2, min_free_ram_gb=100000)
    result = run_machine_load(slots, budget_file, "--need", "1", "--role", "other", "--quiet")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "RAM free" in result.stdout and "100000 GB" in result.stdout


def test_machine_load_report_runs_and_lists_the_holder(slots, tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=4, others=2, min_free_ram_gb=0)
    process, _slot = holder(slots, budget_file, slot_budget.ROLE_OTHER, tmp_path)
    try:
        started = time.monotonic()
        result = run_machine_load(slots, budget_file)
        elapsed = time.monotonic() - started
    finally:
        process.kill()
        process.wait(timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in ("now ", "budget ", "cpu ", "ram ", "slots ", "waiting ", "processes"):
        assert marker in result.stdout, result.stdout
    assert f"pid {process.pid}" in result.stdout
    assert "total 4, others 2" in result.stdout
    # What dominates: python start + psutil/junkroan imports, the 1 s cpu_percent sample (machine_load.py:44) and
    # the cmdline read of every process (:113); all CPU work, so the bound follows the machine (a sleep/poll
    # crawl would still exceed 200 x the spin).
    assert elapsed < bound(20.0, 200.0), "the report samples the CPU for one second; it must not crawl"


# -- PobSession's use of it (no PoB: the runtime launch is stubbed) ----------------------------

class _RunThatCannotStart:
    """Stands in for the headless proof run so `__enter__` fails after the slot is taken."""

    def bootstrap_session(self, *_args, **_kwargs):
        raise RuntimeError("no runtime")


def test_pob_session_takes_a_slot_and_gives_it_back_when_the_launch_fails(monkeypatch, slots, tmp_path):
    from junkroan.pob.session import PobSession

    budget_file = write_budget(tmp_path / "budget.json", total=3, others=2)
    monkeypatch.setenv("JUNKROAN_POB_SLOT_DIR", str(slots))
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(budget_file))

    session = PobSession.__new__(PobSession)  # no runtime, no download: only the lifecycle matters
    session._run = _RunThatCannotStart()
    session._live = False
    with pytest.raises(RuntimeError):
        session.__enter__()
    assert session._slot is None
    assert slot_budget.busy_slots(slots, budget=slot_budget.load_budget(path=budget_file)) == [], (
        "a session that never started must not keep the slot it reserved"
    )


# -- the shared directory ----------------------------------------------------------------------

def test_the_shared_var_is_the_main_checkouts(monkeypatch):
    """A worktree has no `var/` of its own: the slot directory must resolve to the main checkout."""

    monkeypatch.setattr(slot_budget, "_shared_var", None)
    shared = slot_budget.shared_var_dir()
    assert shared.name == "var"
    assert (shared.parent / ".git").exists(), f"{shared} does not sit next to a .git"
    monkeypatch.setattr(slot_budget, "_shared_var", None)
    assert slot_budget.slot_dir() == shared / "locks"


def test_slot_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JUNKROAN_POB_SLOT_DIR", str(tmp_path / "elsewhere"))
    assert slot_budget.slot_dir() == tmp_path / "elsewhere"
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(tmp_path / "b.json"))
    assert slot_budget.budget_path() == tmp_path / "b.json"


def test_budget_file_with_a_bom_is_read_not_replaced_by_defaults(tmp_path) -> None:
    """PowerShell's `Set-Content -Encoding utf8` writes a BOM; the file must still be read (2026-09-24)."""
    import json as _json
    from junkroan.pob import slot_budget as _sb

    target = tmp_path / "machine_budget.json"
    target.write_bytes("﻿".encode("utf-8") + _json.dumps({"day": {"total": 3, "others": 0}}).encode("utf-8"))
    document, _ = _sb._budget_document(target)
    assert document["day"]["total"] == 3 and document["day"]["others"] == 0


# -- reservations (#41): load_budget adds active reservations of this host to `others` ---------

def _write_reservations(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_no_reservations_file_leaves_load_budget_exactly_as_today(tmp_path):
    """Requirement 5: with no reservations file, `load_budget` returns today's values unchanged."""

    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2, strict_reserve=True)
    reservations_file = tmp_path / "reservations.json"  # deliberately never written
    budget = slot_budget.load_budget(
        now=datetime(2026, 9, 20, 12, 0), path=budget_file, host="pc", reservations_path=reservations_file,
    )
    assert (budget.total, budget.others) == (7, 2)
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 5


def test_a_reservation_without_the_flag_changes_nothing(tmp_path):
    """#41 send-back: a reservation only ever takes effect on a host whose mode has `strict_reserve`
    on. Without it the queue's limit is `total` regardless of `others`, so a reservation added to
    `others` has nothing to add slots to."""

    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2)  # strict_reserve defaults False
    reservations_file = tmp_path / "reservations.json"
    now = datetime(2026, 9, 20, 12, 0)
    _write_reservations(
        reservations_file,
        [{"id": 1, "host": "pc", "slots": 2, "issue": 12, "created": now.isoformat(),
          "expires": (now + timedelta(hours=1)).isoformat()}],
    )
    budget = slot_budget.load_budget(now=now, path=budget_file, host="pc", reservations_path=reservations_file)
    assert budget.others == 2, "no strict_reserve -- the reservation is not applied"
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 7, "the queue's limit stays the full total"


def test_a_reservation_raises_others_and_lowers_the_queue_limit(tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2, strict_reserve=True)
    reservations_file = tmp_path / "reservations.json"
    now = datetime(2026, 9, 20, 12, 0)
    _write_reservations(
        reservations_file,
        [{"id": 1, "host": "pc", "slots": 2, "issue": 12, "created": now.isoformat(),
          "expires": (now + timedelta(hours=1)).isoformat()}],
    )
    budget = slot_budget.load_budget(now=now, path=budget_file, host="pc", reservations_path=reservations_file)
    assert budget.others == 4, "others: 2 -> 4"
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 3, "queue limit: 5 -> 3"

    # after expiry (a later "now"), the reservation no longer applies
    later = now + timedelta(hours=2)
    budget_after = slot_budget.load_budget(now=later, path=budget_file, host="pc", reservations_path=reservations_file)
    assert budget_after.others == 2
    assert budget_after.limit_for(slot_budget.ROLE_QUEUE) == 5


def test_an_oversized_reservation_leaves_the_queue_one_slot(tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2, strict_reserve=True)
    reservations_file = tmp_path / "reservations.json"
    now = datetime(2026, 9, 20, 12, 0)
    _write_reservations(
        reservations_file,
        [{"id": 1, "host": "pc", "slots": 50, "issue": None, "created": now.isoformat(),
          "expires": (now + timedelta(hours=1)).isoformat()}],
    )
    budget = slot_budget.load_budget(now=now, path=budget_file, host="pc", reservations_path=reservations_file)
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 1, "the queue always keeps at least one slot"


def test_a_reservation_of_a_different_host_is_ignored(tmp_path):
    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2)
    reservations_file = tmp_path / "reservations.json"
    now = datetime(2026, 9, 20, 12, 0)
    _write_reservations(
        reservations_file,
        [{"id": 1, "host": "laptop", "slots": 2, "issue": 12, "created": now.isoformat(),
          "expires": (now + timedelta(hours=1)).isoformat()}],
    )
    budget = slot_budget.load_budget(now=now, path=budget_file, host="pc", reservations_path=reservations_file)
    assert budget.others == 2


def test_read_reservations_is_bom_tolerant(tmp_path):
    target = tmp_path / "reservations.json"
    target.write_bytes("﻿".encode("utf-8") + json.dumps([{"id": 1, "host": "pc", "slots": 1}]).encode("utf-8"))
    entries = slot_budget.read_reservations(target)
    assert entries == [{"id": 1, "host": "pc", "slots": 1}]


def test_reservations_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("JUNKROAN_POB_RESERVATIONS", str(tmp_path / "elsewhere.json"))
    assert slot_budget.reservations_file() == tmp_path / "elsewhere.json"


def test_current_host_env_override(monkeypatch):
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    assert slot_budget.current_host() == "pc"
    monkeypatch.setenv("JUNKROAN_HOST", "Laptop")
    assert slot_budget.current_host() == "laptop"


def test_413_machine_load_under_pause_other_gets_2_slots_and_a_third_waits(slots, tmp_path):
    """#413 row 3: the committed `pause` mode, rendered by `mode_budget`, with the RAM floor zeroed."""

    from junkroan.runs import hosts as runs_hosts

    config = runs_hosts.load_hosts_config()
    document = runs_hosts.mode_budget(config["pc"], "pc", "pause")
    document["day"]["min_free_ram_gb"] = 0
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(json.dumps(document), encoding="utf-8")

    two = run_machine_load(slots, budget_file, "--need", "2", "--role", "other", "--quiet")
    assert two.returncode == 0, two.stdout + two.stderr
    three = run_machine_load(slots, budget_file, "--need", "3", "--role", "other", "--quiet")
    assert three.returncode == 3, three.stdout + three.stderr
    assert three.stdout.startswith("WAIT")


def test_411_a_live_reservation_at_the_fallback_path_never_reaches_a_test(monkeypatch, tmp_path):
    """The fallback root is faked as a populated `var/`: with the env var cleared it WOULD change
    `others` (so the simulation is live); with the suite's own env var (conftest) it does not."""

    fake_var = tmp_path / "fake_main_var"
    fake_var.mkdir()
    now = datetime(2026, 9, 20, 12, 0)
    _write_reservations(
        fake_var / "reservations.json",
        [{"id": 1, "host": "pc", "slots": 2, "issue": 398, "created": now.isoformat(),
          "expires": (now + timedelta(hours=2)).isoformat()}],
    )
    monkeypatch.setattr(slot_budget, "shared_var_dir", lambda: fake_var)
    budget_file = write_budget(tmp_path / "budget.json", total=7, others=2, strict_reserve=True)

    # what the suite sees: the conftest env var wins over the populated fallback file
    assert slot_budget.reservations_file() != fake_var / "reservations.json"
    assert slot_budget.load_budget(now=now, path=budget_file, host="pc").others == 2

    # control: without the env var the fallback is read and the live reservation is added
    monkeypatch.delenv("JUNKROAN_POB_RESERVATIONS")
    assert slot_budget.reservations_file() == fake_var / "reservations.json"
    assert slot_budget.load_budget(now=now, path=budget_file, host="pc").others == 4
