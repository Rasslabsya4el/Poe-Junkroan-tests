"""#966 unit 4: the suite router's host choice reads the run queue's free-RAM floor (``min_free_ram_gb``).

A host whose free RAM is under its floor gets one worker (the suite still runs). The floors come from the
same ``config/hosts.json`` entries the runs daemon reads: the PC's normal-mode period entry and the laptop's
normal-mode day entry. No readings are taken from the live machine here.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.agentops.suite_host import _workers, caps_from_config, choose_suite_host

ROOT = Path(__file__).resolve().parents[1]
CAPS = dict(pc_cap=6, laptop_cap=4, pc_reserve_gb=3.0, laptop_reserve_gb=3.0, laptop_factor=1.18)


def r(cores, cpu, ram):
    """12 (or 8) logical cores at the given CPU share, the given free RAM: the readings ``pc_readings`` gives."""
    return {"logical_cores": cores, "cpu_percent": cpu, "free_ram_gb": ram}


def test_row2_pc_at_6_9_gb_under_the_8_gb_floor_is_one_worker():
    c = choose_suite_host(r(12, 10, 6.9), None, laptop_failure="no laptop in this test", pc_floor_gb=8.0, **CAPS)
    assert c.host == "pc" and c.pc_workers == 1
    assert "workers 1: free RAM 6.9 GB under the floor 8 GB" in c.line


def test_row2_the_laptop_still_wins_when_the_pc_is_under_the_floor():
    # 1 PC worker (under the floor) against a healthy laptop of 4 workers: 4 / 1.18 > 1, so the laptop runs it.
    c = choose_suite_host(r(12, 10, 6.9), r(8, 10, 20), laptop_failure=None, pc_floor_gb=8.0, **CAPS)
    assert (c.host, c.pc_workers, c.laptop_workers) == ("laptop", 1, 4)


def test_row3_laptop_at_0_8_gb_under_its_1_gb_floor_is_one_worker():
    # reserve 0 here: with the config's 3 GB reserve the count is 1 even without the floor, so the row would
    # not tell a floor from no floor; at reserve 0 the RAM alone gives 2 (0.8 / 0.4) and the floor cuts it to 1.
    caps = dict(CAPS, laptop_reserve_gb=0.0)
    c = choose_suite_host(r(12, 10, 20), r(8, 10, 0.8), laptop_failure=None, laptop_floor_gb=1.0, **caps)
    assert c.laptop_workers == 1
    assert c.line.endswith("; laptop: workers 1")  # 1 / 1.18 < 6: the PC keeps the suite, the laptop line is the short form


def test_row3_without_the_floor_the_laptop_count_is_the_ram_count():
    caps = dict(CAPS, laptop_reserve_gb=0.0)
    c = choose_suite_host(r(12, 10, 20), r(8, 10, 0.8), laptop_failure=None, **caps)
    assert c.laptop_workers == 2


def test_row4_pc_at_20_gb_over_the_floor_is_todays_count():
    # 6 = the count unchanged main gives for these inputs (12 cores at 10 %, cap 6, 20 GB free, 3 GB reserve).
    without = choose_suite_host(r(12, 10, 20), None, laptop_failure="x", **CAPS)
    with_floor = choose_suite_host(r(12, 10, 20), None, laptop_failure="x", pc_floor_gb=8.0, **CAPS)
    assert without.pc_workers == 6
    assert with_floor.pc_workers == 6
    assert with_floor.line == without.line


def test_row4_the_default_is_no_floor():
    assert _workers(r(12, 10, 6.9), 6, 3.0)[0] == 6  # no floor argument: the RAM count, cap 6


def test_caps_from_config_floors_are_the_config_entries(monkeypatch):
    config = json.loads((ROOT / "config" / "hosts.json").read_text(encoding="utf-8"))
    pc_normal = config["pc"]["modes"]["normal"]
    lap_day = config["laptop"]["modes"]["normal"]["day"]
    for period in ("day", "night"):
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
        caps = caps_from_config()
        assert caps["pc_floor_gb"] == pc_normal[period]["min_free_ram_gb"], period
        assert caps["laptop_floor_gb"] == lap_day["min_free_ram_gb"], period
