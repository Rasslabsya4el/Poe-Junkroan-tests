"""#684 rows 1-4: the merge suite's worker count on fixed CPU and RAM readings."""
from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings as f


def _w(cores, cpu, ram, cap=6):
    return f(cores, cpu, ram, 3.0, SUITE_PER_WORKER_GB, cap)


def test_per_worker_constant():
    assert SUITE_PER_WORKER_GB == 0.4


def test_row1_idle_cpu_7_3_gb_gives_the_cap():
    n, line = _w(12, 10, 7.3)
    assert n == 6
    assert line == "workers 6: cores free 10.8 of 12 (cpu 10%), 0.5 core a worker -> 21 by CPU, RAM free 7.3 GB -> 10 by RAM, cap 6"


def test_row2_busy_cpu_limits_to_free_cores():
    n, line = _w(12, 75, 20)
    assert n == 6 and "cores free 3.0 of 12" in line and "6 by CPU" in line


def test_row3_ram_limits_and_line_names_ram():
    n, line = _w(12, 5, 3.5)
    assert n == 1 and "1 by RAM" in line


def test_below_reserve_still_one_worker():
    assert _w(12, 5, 2.0)[0] == 1


def test_row4_cpu_reader_fails_ram_only():
    n, line = _w(12, None, 7.3)
    assert n == 6 and "cpu n/a" in line
    assert _w(12, None, 3.9)[0] == 2


def test_row4_ram_reader_fails_one_worker():
    n, line = _w(12, 5, None)
    assert n == 1 and "RAM n/a" in line
