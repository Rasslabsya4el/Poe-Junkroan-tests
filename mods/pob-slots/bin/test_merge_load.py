"""#986: a merge's CPU and RAM on a host, apart from work / agents / you (`collect.machine` -> `machine.merge`).

    python -m pytest -q mods/pob-slots/bin/test_merge_load.py     (from the repo root, like the other bin tests)

A recorded process table (no real process is read): on the PC a merge (the holder of `var/locks/merge.lock` with its
`gh` and pytest tree) and the full run it spawned (the holder of `var/agentops/full_run.lock`, a tree of its own); on the
laptop the one-shot suite task (wscript -> powershell `...-suite-<sha8>.out.ps1` -> cmd -> pytest workers). With the merge
its share is `machine.merge` and the three classes do not carry it; without it `merge` is 0 and the same processes fall
into the classes by command line (an agent needs a session command line, collect.py `is_session`).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402

T0 = 1_800_000_000.0   # "now" of every case
DT = 10.0              # seconds since the previous pull
CORES = 10             # one CPU second of a process in DT = 1 % of the machine
BORN = T0 - 3600       # every process is older than the previous pull

# pid: (ppid, name, CPU seconds spent in DT, RAM GB)
PC = {
    1: (0, "explorer.exe", 0, 0.1),
    100: (1, "python.exe", 0, 0.1),         # the merge process: the holder of merge.lock
    110: (100, "gh.exe", 1, 0.05),          # its `gh` call: outside a session it falls to `you`
    120: (100, "python.exe", 2, 0.2),       # its pytest
    121: (120, "python.exe", 10, 0.5),      # xdist workers
    122: (120, "python.exe", 10, 0.5),
    500: (1, "python.exe", 1, 0.1),         # the full run (own tree: WMI parent): the holder of full_run.lock
    510: (500, "python.exe", 13, 0.9),
    200: (1, "claude.exe", 5, 0.5),         # a live agent session
    300: (1, "chrome.exe", 3, 1.5),         # the owner's browser
    400: (1, "junkroan.exe", 4, 1.0),       # a PoB slot
}
MERGE_TREE = (100, 110, 120, 121, 122, 500, 510)
LAPTOP = {
    1: (0, "explorer.exe", 0, 0.1),
    600: (1, "wscript.exe", 0, 0.01),       # the suite task's launcher
    610: (600, "powershell.exe", 1, 0.1),   # `-File <repo>-suite-1234abcd.out.ps1`
    620: (610, "cmd.exe", 0, 0.01),
    630: (620, "python.exe", 2, 0.2),
    631: (630, "python.exe", 12, 0.5),
    632: (630, "python.exe", 12, 0.5),
    700: (1, "wscript.exe", 0, 0.01),       # the daemon's watchdog, the same launcher
    710: (700, "powershell.exe", 2, 0.1),   # `-File watchdog.ps1`
    200: (1, "claude.exe", 5, 0.5),
}
CMDLINES = {
    200: r"C:\Users\user\.local\bin\claude.exe",            # a live CLI session: `is_session` needs a command line (collect.py:709)
    610: r"powershell.exe -NoProfile -File C:\poe-suite-1234abcd.out.ps1",
    710: r"powershell.exe -File C:\poe\tools\hosts\watchdog.ps1",
}


def stamp(created: float, fmt: str) -> str:
    return datetime.fromtimestamp(created).strftime(fmt)


def world(mp: pytest.MonkeyPatch, tmp: Path, table: dict) -> None:
    """The scan, the CPU clock, the previous pull and the memory counters of `table`."""
    procs = {pid: {"ppid": pp, "name": name, "cpu": 100.0 + cpu, "rss": int(gb * 2**30), "created": BORN}
             for pid, (pp, name, cpu, gb) in table.items()}
    known = sum(cpu for _, _, cpu, _ in table.values())     # the busy share equals what the processes spent: no rescaling
    used_gb = sum(gb for *_, gb in table.values())
    mp.setattr(collect, "REPO", tmp)
    mp.setattr(collect, "SNAP", tmp / "snap.json")
    mp.setattr(collect, "_scan", lambda: {k: dict(v) for k, v in procs.items()})
    mp.setattr(collect, "_cpu_clock", lambda: (1000.0 + known, 2100.0))   # busy grew by `known` of 100 machine-seconds
    mp.setattr(collect, "_cmdline", lambda pid: CMDLINES.get(pid, ""))
    mp.setattr(collect, "time", SimpleNamespace(time=lambda: T0, sleep=lambda s: None))
    (tmp / "snap.json").write_text(json.dumps({
        "t": T0 - DT, "busy": 1000.0, "total": 2000.0,
        "p": {str(pid): [BORN, 100.0] for pid in table}}), encoding="utf-8")
    import psutil
    mp.setattr(psutil, "cpu_count", lambda *a, **k: CORES)
    mp.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * 2**30, available=(32 - used_gb) * 2**30))


def locks(tmp: Path, merge_pid: int | None = 100, full_pid: int | None = 500, started_after: float = 1.0) -> None:
    """The two lock files of the repo; `started_after` = seconds between the holder's creation and the lock's `started`."""
    for pid, parts, fmt in ((merge_pid, collect.MERGE_LOCKS[0], "%Y-%m-%d %H:%M:%S"),
                            (full_pid, collect.MERGE_LOCKS[1], "%Y-%m-%dT%H:%M:%S")):
        if pid is None:
            continue
        path = tmp.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid, "started": stamp(BORN + started_after, fmt)}), encoding="utf-8")


def read(table: dict) -> dict:
    return collect.machine(set(), None, work_key="pob", work_prefix="junkroan")


def test_pc_merge_leaves_the_classes_and_shows_in_its_own_field(monkeypatch, tmp_path):
    world(monkeypatch, tmp_path, PC)
    locks(tmp_path)
    m = read(PC)
    spent = sum(PC[p][2] for p in MERGE_TREE)                # 37 CPU seconds in 10 s on 10 cores = 37 %
    ram_gb = sum(PC[p][3] for p in MERGE_TREE)
    assert m["merge"]["cpu"] == pytest.approx(spent, abs=0.1) == pytest.approx(37.0, abs=0.1)
    assert m["merge"]["ram_mb"] == pytest.approx(ram_gb * 1024, abs=2)
    # not double counted: the claude session is the only agent, the browser the only `you`, the slot-named process the only PoB
    assert m["cpu"]["agents"] == pytest.approx(5.0, abs=0.1)
    assert m["cpu"]["you"] == pytest.approx(3.0, abs=0.1)
    assert m["cpu"]["pob"] == pytest.approx(4.0, abs=0.1)
    assert m["ram"]["agents"] == pytest.approx(0.5, abs=0.06) and m["ram"]["you"] == pytest.approx(1.6, abs=0.06)
    # the four parts add up to what the processes spent (the busy share) and to the used RAM
    assert sum(m["cpu"].values()) + m["merge"]["cpu"] == pytest.approx(m["cpu_total"], abs=0.2)


def test_pc_without_a_merge_the_field_is_zero_and_the_processes_fall_into_the_classes(monkeypatch, tmp_path):
    world(monkeypatch, tmp_path, PC)         # no lock file in the repo
    m = read(PC)
    assert m["merge"] == {"cpu": 0.0, "cpu_raw": 0.0, "ram_mb": 0}
    # a name alone makes nothing agents (collect.py:699): the merge's python.exe and gh.exe outside a session fall to `you`
    # with the browser's 3 %: 3 + 37 = 40 %; the claude session alone stays `agents` (5 %)
    assert m["cpu"]["agents"] == pytest.approx(5.0, abs=0.1)
    assert m["cpu"]["you"] == pytest.approx(40.0, abs=0.1)
    # the classes load_split returns (collect.py:801-810): the four roles, the two extra roles and the gap
    assert set(m["cpu"]) == {"pob", "agents", "app", "tests", "you", "unmeasured"}
    assert set(m["ram"]) == {"pob", "agents", "app", "tests", "you", "unmeasured"}


def test_a_lock_of_a_dead_holder_or_a_reused_pid_is_no_merge(monkeypatch, tmp_path):
    world(monkeypatch, tmp_path, PC)
    locks(tmp_path, merge_pid=9999, full_pid=500, started_after=-30.0)   # 9999 is not running; 500 was created after `started`
    assert read(PC)["merge"] == {"cpu": 0.0, "cpu_raw": 0.0, "ram_mb": 0}
    world(monkeypatch, tmp_path, PC)                                     # a pull rewrites the previous-pull file: start it again
    locks(tmp_path, merge_pid=100, full_pid=9998)                        # only the merge line holds a live lock: the full run is not counted
    assert read(PC)["merge"]["cpu"] == pytest.approx(23.0, abs=0.1)


def test_laptop_suite_task_is_the_merge_and_the_watchdog_is_not(monkeypatch, tmp_path):
    world(monkeypatch, tmp_path, LAPTOP)     # the laptop has no merge lock at all
    m = read(LAPTOP)
    spent = sum(LAPTOP[p][2] for p in (610, 620, 630, 631, 632))
    assert m["merge"]["cpu"] == pytest.approx(spent, abs=0.1) == pytest.approx(27.0, abs=0.1)
    assert m["merge"]["ram_mb"] == pytest.approx(sum(LAPTOP[p][3] for p in (610, 620, 630, 631, 632)) * 1024, abs=2)
    assert m["cpu"]["agents"] == pytest.approx(5.0, abs=0.1)             # the claude session alone
    assert m["cpu"]["you"] == pytest.approx(2.0, abs=0.1)                # the watchdog's powershell stays where it was
    world(monkeypatch, tmp_path, LAPTOP)
    monkeypatch.setattr(collect, "_cmdline", lambda pid: "")             # no suite runner on the command lines: nothing is a merge
    assert read(LAPTOP)["merge"] == {"cpu": 0.0, "cpu_raw": 0.0, "ram_mb": 0}


def test_unscaled_classes_leave_the_gap_in_unmeasured_and_the_merge_cpu_is_the_live_sum(monkeypatch, tmp_path):
    """#986 rows 3a / 3b, unscaled (collect.py:781-783, 810): the machine was busier than its live processes (children that
    ended inside the interval, kernel time). No share is rescaled: each role and the merge is the raw sum over its own
    processes, `merge.cpu_raw` equals `merge.cpu`, and the gap between `cpu_total` and every known share is `unmeasured`."""
    world(monkeypatch, tmp_path, PC)
    locks(tmp_path)
    known = sum(cpu for _, _, cpu, _ in PC.values())                      # 49 CPU seconds in 10 s on 10 cores = 49 %
    monkeypatch.setattr(collect, "_cpu_clock", lambda: (1000.0 + known * 1.5, 2100.0))   # busy 73.5 %: the gap is 73.5 - 49 = 24.5
    m = read(PC)
    assert m["cpu_total"] == pytest.approx(known * 1.5, abs=0.1)                       # 73.5
    assert sum(m["cpu"].values()) + m["merge"]["cpu"] == pytest.approx(m["cpu_total"], abs=1.0)
    assert m["merge"]["cpu_raw"] == pytest.approx(37.0, abs=0.1)                       # the merge's live processes, 23 + 14
    assert m["merge"]["cpu"] == pytest.approx(37.0, abs=0.1)                           # no 1.5 factor
    assert m["merge"]["cpu"] == m["merge"]["cpu_raw"]
    assert m["cpu"]["unmeasured"] == pytest.approx(known * 1.5 - known, abs=0.2)       # 24.5: the gap, not spread over the classes
    assert m["cpu"]["agents"] == pytest.approx(5.0, abs=0.1)                           # the classes stay their raw sums


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
