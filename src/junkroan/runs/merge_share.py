"""The merge queue's CPU share of the PC, in cores, for the start gate (#1118).

The gate (`junkroan.pob.slot_budget.load_admission`) reads the whole PC's busy cores. The merge queue's own test runs
(a merge's suite, its line checks, a full run on main) are the operator's own queue, not work a new ORCH should be held
for, so the gate subtracts their share. The same share is what the monitor shows as "мердж" (#986,
`mods/pob-slots/bin/collect.py:merge_roots`); this is a compact reimplementation, since `mods/` is not importable
from `src/`.

`merge_cores` is one tick: it reads the process table and the lock holders, finds the merge roots, and returns the
CPU cores their trees burned since the previous tick, plus the state the next tick needs. Nothing here raises.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from junkroan.runs import proc_bulk

ROOT = Path(__file__).resolve().parents[3]
#: The two lock files whose holder pid is a merge process: the merge line and the full run it spawns after a landing.
LOCKS = (("var", "locks", "merge.lock"), ("var", "agentops", "full_run.lock"))
#: A merge's suite on this host: a powershell run by wscript whose command line names `...-suite-<sha8>.out.ps1`.
SUITE_RUNNER = re.compile(r"-suite-[0-9a-f]{8}\.out\.ps1", re.IGNORECASE)
#: A lock holder counts only when its process was created no later than the lock's `started` + this (a reused pid).
LOCK_SLACK_S = 2.0

Processes = dict[int, dict[str, Any]]  # pid -> {"ppid", "name", "cpu" (CPU seconds so far), "created" (epoch s), "cmdline"?}


def _cmdline(pid: int) -> str:
    import psutil

    try:
        return " ".join(psutil.Process(pid).cmdline())
    except psutil.Error:
        return ""


def _default_processes() -> Processes:
    """The process table in one read: proc_bulk on Windows, psutil elsewhere or when that read fails.
    The command line is read only for a powershell under wscript, the one shape a merge suite takes."""
    snap = proc_bulk.snapshot()
    if snap is not None:
        out: Processes = {pid: {"ppid": p.ppid, "name": p.name, "cpu": p.cpu_s, "created": p.create_time}
                          for pid, p in snap.items()}
    else:
        import psutil

        out = {}
        for p in psutil.process_iter(["pid", "ppid", "name", "cpu_times", "create_time"]):
            i = p.info
            ct = i.get("cpu_times")
            if ct is None:
                continue
            out[i["pid"]] = {"ppid": i.get("ppid") or 0, "name": i.get("name") or "", "cpu": ct.user + ct.system,
                             "created": i.get("create_time") or 0}
    for pid, p in out.items():
        if _is_suite_host(p["name"]) and out.get(p["ppid"], {}).get("name", "").lower() == "wscript.exe":
            p["cmdline"] = _cmdline(pid)
    return out


def _is_suite_host(name: str) -> bool:
    return name.lower() in ("powershell.exe", "pwsh.exe")


def _default_locks() -> list[dict[str, Any]]:
    """The holder record of each merge-side lock file that exists. A missing file holds nothing; a present one that
    cannot be read or parsed raises (the caller answers None)."""
    out: list[dict[str, Any]] = []
    for parts in LOCKS:
        try:
            text = ROOT.joinpath(*parts).read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        out.append(json.loads(text))
    return out


def _merge_roots(procs: Processes, holders: Iterable[dict[str, Any]]) -> set[int]:
    roots: set[int] = set()
    for holder in holders:
        try:
            pid = int(holder["pid"])
        except (KeyError, TypeError, ValueError):
            continue
        p = procs.get(pid)
        if p is None:
            continue
        try:
            started = datetime.fromisoformat(str(holder.get("started"))).timestamp()  # local naive, ' ' or 'T'
            if p["created"] > started + LOCK_SLACK_S:
                continue
        except (ValueError, TypeError):
            pass  # no readable start: the pid alone, the safe side
        roots.add(pid)
    for pid, p in procs.items():
        if _is_suite_host(p["name"]) and procs.get(p["ppid"], {}).get("name", "").lower() == "wscript.exe" \
                and SUITE_RUNNER.search(p.get("cmdline") or ""):
            roots.add(pid)
    return roots


def _tree(roots: set[int], procs: Processes) -> set[int]:
    """The roots and every process below them (each pid once: a cycle in the ppid links cannot loop)."""
    children: dict[int, list[int]] = {}
    for pid, p in procs.items():
        children.setdefault(p["ppid"], []).append(pid)
    seen: set[int] = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in seen or pid not in procs:
            continue
        seen.add(pid)
        stack.extend(children.get(pid, []))
    return seen


def merge_cores(prev: dict | None, now_s: float, *, processes: Callable[[], Processes] | None = None,
                lock_reader: Callable[[], list[dict[str, Any]]] | None = None) -> tuple[float | None, dict]:
    """The CPU cores the merge queue's process trees burned since `prev`, and the state for the next tick.

    * no merge root (no live merge lock holder, no suite wrapper): 0.0.
    * the first tick of a merge (no `prev`, or a `prev` without `t`): no delta exists, so None.
    * the process table or a lock cannot be read: None, with an empty state (the next tick starts over).
    The state is `{"t": now_s, "p": {pid: [created, cpu_seconds]}}` for every process this tick saw. A pid already
    recorded whose creation time differs (a reused pid) counts none of its CPU; a pid born inside the interval
    (created no earlier than the previous tick less 1 s) counts all of its CPU.
    """
    try:
        procs = (processes or _default_processes)()
        roots = _merge_roots(procs, (lock_reader or _default_locks)())
        tree = _tree(roots, procs) if roots else set()
        state = {"t": now_s, "p": {pid: [p["created"], p["cpu"]] for pid, p in procs.items()}}
        if not roots:
            return 0.0, state
        if not prev or "t" not in prev:
            return None, state
        dt = max(0.1, now_s - prev["t"])
        was_p = prev.get("p", {})
        spent = 0.0
        for pid in tree:
            p = procs[pid]
            was = was_p.get(pid)
            if was and abs(was[0] - p["created"]) < 1:
                spent += max(0.0, p["cpu"] - was[1])
            elif p["created"] >= prev["t"] - 1:
                spent += max(0.0, p["cpu"])  # born inside the interval: all of its CPU falls in it
        return spent / dt, state
    except Exception:
        return None, {}
