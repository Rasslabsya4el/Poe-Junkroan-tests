"""#685 rows 2-4: host choice on fixed readings; the live laptop is never touched."""
from tools.agentops.suite_host import caps_from_config, choose_suite_host, read_laptop

CAPS = dict(pc_cap=6, laptop_cap=4, pc_reserve_gb=3.0, laptop_reserve_gb=3.0, laptop_factor=1.18)


def r(cores, cpu, ram):
    return {"logical_cores": cores, "cpu_percent": cpu, "free_ram_gb": ram}


def pc_n(n):  # RAM-limited: (3 + 0.4 n) GB free -> n workers
    return r(32, 0, 3 + 0.4 * n + 0.05)


def test_row2_pc_one_laptop_four_goes_laptop():
    c = choose_suite_host(pc_n(1), pc_n(4), laptop_failure=None, **CAPS)
    assert (c.host, c.pc_workers, c.laptop_workers) == ("laptop", 1, 4)
    assert c.line.startswith("host laptop: workers 4 (workers 4:") and c.line.endswith("; pc would give 1")


def test_row3_pc_six_laptop_four_stays_pc():
    c = choose_suite_host(pc_n(6), pc_n(4), laptop_failure=None, **CAPS)
    assert (c.host, c.pc_workers, c.laptop_workers) == ("pc", 6, 4)
    assert c.line.startswith("host pc: workers 6 (workers 6:") and c.line.endswith("; laptop: workers 4")


def test_strict_greater_edge():
    assert choose_suite_host(pc_n(3), pc_n(4), laptop_failure=None, **CAPS).host == "laptop"  # 3.39 > 3
    assert choose_suite_host(pc_n(4), pc_n(4), laptop_failure=None, **CAPS).host == "pc"  # 3.39 < 4


def test_row4_reader_failures_give_none_and_reason():
    from scripts.suite_on_host import HostFailure  # noqa: F401
    import time

    def boom(host):
        raise HostFailure("readings: ssh timed out after 10 s")

    assert read_laptop(reader=boom) == (None, "readings: ssh timed out after 10 s")
    data, why = read_laptop(0.1, reader=lambda h: time.sleep(2))
    assert data is None and "timed out after 0.1 s" in why
    assert read_laptop(reader=lambda h: "junk")[0] is None
    assert read_laptop(reader=lambda h: r(8, 1, 9))[0] == r(8, 1, 9)


def test_row4_failure_chooses_pc_with_reason_in_line():
    c = choose_suite_host(pc_n(1), None, laptop_failure="ssh timed out after 10 s", **CAPS)
    assert c.host == "pc" and c.laptop_workers is None
    assert c.line.endswith("; laptop: ssh timed out after 10 s")
    c2 = choose_suite_host(pc_n(1), pc_n(4), laptop_failure="boom", **CAPS)
    assert c2.host == "pc" and "laptop: boom" in c2.line


def test_caps_from_config_reads_hosts_json(monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    caps = caps_from_config()
    # #966: the two run-queue floors (normal mode: PC day 8, laptop day 1) are the same config entries
    assert caps == dict(pc_cap=3, laptop_cap=4, pc_reserve_gb=3.0, laptop_reserve_gb=3.0, laptop_factor=1.18,
                        pc_floor_gb=8.0, laptop_floor_gb=1.0)


def test_caps_from_config_night_pc_cap_is_6(monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
    assert caps_from_config()["pc_cap"] == 6
