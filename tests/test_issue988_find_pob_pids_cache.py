"""#988: find_pob_pids reads a process's command line only once per (pid, create_time).

A fake psutil and a fake process list stand in for the OS (no real process is started). Every
command-line read goes through one counter, whether psutil prefetched it (process_iter with
"cmdline" in attrs, the old way) or the caller asked the process for it (p.cmdline()).
"""

from __future__ import annotations

import sys
import types

import pytest

from junkroan.runs import hosts as runs_hosts

MARK = "headless_runtime_worker"


class FakeProcess:
    def __init__(self, reads: list[int], pid: int, create_time: float, cmdline: list[str]) -> None:
        self._reads = reads
        self.pid = pid
        self._create_time = create_time
        self._cmdline = cmdline
        self.info: dict = {}

    def cmdline(self) -> list[str]:
        self._reads.append(self.pid)
        return list(self._cmdline)


def make_psutil(table: list[dict], reads: list[int]) -> types.ModuleType:
    """`table` is a list of {"pid", "create_time", "cmdline"} dicts; the fake reads the live list each call."""

    module = types.ModuleType("psutil")

    def process_iter(attrs, ad_value=None):
        for row in table:
            proc = FakeProcess(reads, row["pid"], row["create_time"], row["cmdline"])
            for attr in attrs:
                if attr == "pid":
                    proc.info["pid"] = row["pid"]
                elif attr == "create_time":
                    proc.info["create_time"] = row["create_time"]
                elif attr == "cmdline":
                    proc.info["cmdline"] = proc.cmdline()
            yield proc

    module.process_iter = process_iter
    return module


def old_rule(table: list[dict]) -> list[int]:
    """The rule find_pob_pids applied before #988, on the same table."""
    return [row["pid"] for row in table if MARK in " ".join(row["cmdline"]).lower()]


@pytest.fixture
def world(monkeypatch):
    table: list[dict] = [
        {"pid": 100, "create_time": 1000.0, "cmdline": ["python.exe", "-m", "junkroan.runs.headless_runtime_worker", "--job", "a"]},
        {"pid": 200, "create_time": 2000.0, "cmdline": ["explorer.exe"]},
        {"pid": 300, "create_time": 3000.0, "cmdline": ["C:\\x\\HEADLESS_RUNTIME_WORKER.exe"]},
        {"pid": 400, "create_time": 4000.0, "cmdline": []},  # denied / empty line: never a match
    ]
    reads: list[int] = []
    monkeypatch.setitem(sys.modules, "psutil", make_psutil(table, reads))
    monkeypatch.setattr(runs_hosts, "_CMDLINES", {}, raising=False)  # a fresh daemon process
    return table, reads


def test_first_call_returns_the_old_rule_pids(world):
    table, reads = world
    assert runs_hosts.find_pob_pids() == old_rule(table) == [100, 300]


def test_second_call_on_the_same_list_reads_no_command_line(world):
    table, reads = world
    runs_hosts.find_pob_pids()
    reads.clear()
    assert runs_hosts.find_pob_pids() == old_rule(table)
    assert len(reads) == 0


def test_new_pid_is_read_once_and_reused_pid_is_read_again(world):
    table, reads = world
    runs_hosts.find_pob_pids()
    reads.clear()

    table.append({"pid": 500, "create_time": 5000.0, "cmdline": ["worker", MARK]})
    assert runs_hosts.find_pob_pids() == old_rule(table)
    assert reads == [500]

    # pid 200 is reused by a new process (new create_time) whose line is a PoB worker
    reads.clear()
    table[1] = {"pid": 200, "create_time": 2500.0, "cmdline": ["python.exe", MARK]}
    assert runs_hosts.find_pob_pids() == old_rule(table)
    assert reads == [200]


def test_pid_that_left_the_list_leaves_the_cache(world):
    table, reads = world
    runs_hosts.find_pob_pids()
    assert (100, 1000.0) in runs_hosts._CMDLINES

    gone = table.pop(0)  # pid 100 exits
    assert runs_hosts.find_pob_pids() == old_rule(table) == [300]
    assert (100, 1000.0) not in runs_hosts._CMDLINES

    # the same pid and create_time coming back is a new observation: read again
    table.insert(0, gone)
    reads.clear()
    assert runs_hosts.find_pob_pids() == old_rule(table)
    assert reads == [100]
