"""Owner preset sizing (#958 unit 3a): the ticket's rows 16-20, exact numbers."""

from junkroan.runs import owner_preset as op


def _size(**kw):
    base = dict(
        need_cpu_cores=1.5,
        need_ram_mb=2500,
        idle_cores=0.2,
        free_ram_mb=800,
        running_workers=3,
        worker_cores=1.0,
        worker_ram_mb=900,
    )
    base.update(kw)
    return op.size_give_way(**base)


def test_row16_cpu_and_ram_both_ask_two_no_short_line():
    r = _size()
    assert r.workers == 2
    assert r.short_lines() == []


def test_row17_idle_cores_and_ram_cover_need_nothing_gives_way():
    r = _size(idle_cores=2.0, free_ram_mb=4000)
    assert r.workers == 0
    assert r.short_lines() == []


def test_row18_ram_asks_four_capped_at_running_and_short_400_mb():
    r = _size(free_ram_mb=300, worker_cores=1.0, worker_ram_mb=600)
    assert r.workers == 3
    assert r.short_lines() == ["short by 400 MB"]


def test_row19_no_worker_n0_short_ram_and_cores():
    r = _size(free_ram_mb=800, running_workers=0, worker_cores=0.0, worker_ram_mb=0.0)
    assert r.workers == 0
    assert r.short_lines() == ["short by 1,700 MB", "short by 1.3 cores"]


def test_row20_slots_preset_no_need_gives_slots_and_reads_nothing():
    r = op.slots_give_way(slots=1, running_workers=3)
    assert r.workers == 1
    assert r.short_lines() == []


def test_slots_never_more_than_running_workers():
    assert op.slots_give_way(slots=2, running_workers=1).workers == 1
    assert op.slots_give_way(slots=2, running_workers=0).workers == 0


def test_float_noise_does_not_add_a_worker():
    # (0.4 - 0.1) / 0.1 is 3.0000000000000004 in floats: 3 workers, not 4
    assert (0.4 - 0.1) / 0.1 > 3
    r = _size(need_cpu_cores=0.4, idle_cores=0.1, worker_cores=0.1, free_ram_mb=4000, running_workers=5)
    assert r.workers == 3
    assert r.short_lines() == []


def test_zero_per_worker_cores_asks_all_running_and_shows_short():
    r = _size(worker_cores=0.0, idle_cores=0.2, free_ram_mb=800, running_workers=3)
    assert r.workers == 3
    assert r.short_lines() == ["short by 1.3 cores"]
