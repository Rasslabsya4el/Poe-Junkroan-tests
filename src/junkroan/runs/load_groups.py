"""Who uses the machine (issue #406): one snapshot of CPU and RAM split into process groups.

Groups go by process tree, first match wins: ``pob_counted`` / ``pob_filler`` (a running job's pid and
its descendants), ``claude`` (claude.exe and descendants), ``system`` (session 0, SYSTEM / LOCAL SERVICE
/ NETWORK SERVICE, pid 0 and 4), ``owner`` (every other process of the interactive user), ``other``
(what could not be read). ``cpu_pct`` of a group is a share of the WHOLE machine (all cores = 100).

Keys starting with ``_`` in the snapshot are private (the per-pid cpu times the next call diffs
against); the jsonl writer drops them.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Mapping, NamedTuple

from junkroan.runs import proc_bulk

GROUPS = ("pob_counted", "pob_filler", "claude", "owner", "system", "other")
SYSTEM_USERS = ("system", "local service", "network service")
POB_RUNTIME_MARKS = ("headless_runtime_worker",)  # the same mark scripts/machine_load.py counts
MERGE_SUITE_MARKS = (".claude/worktrees/merge-suite", "var/agentops/merge_suite")
_PRIME_S = 0.5  # a first snapshot has no previous one: it waits this long for a cpu delta
_TREE_WINDOW_S = 1.0  # #762: the exact tree reading's window (members are followed, so a longer one is cheap)
_TREE_STEP_S = 0.06  # #762: pause between two process snapshots of the window


def _session_of(pid: int) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        sid = ctypes.c_ulong()
        if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
            return int(sid.value)
    except Exception:
        pass
    return None


#: #988: (pid, create_time) -> command line. It never changes during a process's life, and reading it is the
#: dearest call of the whole table (~7 ms a process on Windows, more when the OS refuses it). Rebuilt on every
#: read to the processes seen in it, so a dead process leaves nothing behind.
_CMDLINES: dict[tuple[int, "float | None"], list[str]] = {}


_EMPTY_CMDLINE_SETTLE_S = 10.0


class _Mem(NamedTuple):
    rss: int


class _Cpu(NamedTuple):
    user: float
    system: float


def _bulk_figures(p: Any, got: "proc_bulk.ProcInfo | None") -> tuple[Any, Any]:
    """(memory, cpu times) of one process out of the bulk list; a process the list missed (born after it was
    taken) is asked directly, and a denied one is None, as `ad_value=None` made it."""

    if got is not None:
        return _Mem(got.rss), _Cpu(got.cpu_s, 0.0)
    try:
        return p.memory_info(), p.cpu_times()
    except Exception:
        return None, None


def _older_than(created: "float | None", seconds: float) -> bool:
    return created is not None and time.time() - created > seconds


def read_proc_table() -> list[dict[str, Any]]:
    """The live process table through psutil (one oneshot read per process, the cheap way on Windows);
    a process that vanishes is skipped, a denied field is None / 0. A command line is read once per process."""

    global _CMDLINES
    import psutil

    # #988: where the OS gives the whole list in one call, memory and CPU time come from it; psutil would read
    # them one handle at a time (and scan the whole system again for every process it is refused).
    bulk = proc_bulk.snapshot()
    attrs = ["pid", "ppid", "name", "create_time", "username"] + ([] if bulk is not None else ["memory_info", "cpu_times"])
    known = _CMDLINES
    fresh: dict[tuple[int, "float | None"], list[str]] = {}
    rows = []
    for p in psutil.process_iter(attrs, ad_value=None):
        info = p.info
        key = (p.pid, info.get("create_time"))
        cmdline = known.get(key)
        if cmdline is None:
            try:
                cmdline = list(p.cmdline() or [])
            except psutil.NoSuchProcess:
                continue
            except Exception:  # denied: what process_iter's ad_value gave before
                cmdline = []
        if cmdline or _older_than(key[1], _EMPTY_CMDLINE_SETTLE_S):
            fresh[key] = cmdline  # an empty line (a denied process, the System ones) sticks only past the first seconds
        if bulk is not None:
            mem, t = _bulk_figures(p, bulk.get(p.pid))
        else:
            mem, t = info.get("memory_info"), info.get("cpu_times")
        row: dict[str, Any] = {
            "pid": p.pid, "ppid": info.get("ppid"), "name": info.get("name") or "",
            "cmdline": cmdline, "username": info.get("username"),
            "session": None, "cpu_s": float(t.user + t.system) if t else 0.0,
            "rss_mb": mem.rss / (1024 * 1024) if mem else 0.0, "cwd": None}
        if row["username"] is None:  # the OS refuses what is not ours: ask the session instead
            row["session"] = _session_of(p.pid)
        if _is_pytest(row):
            try:
                row["cwd"] = p.cwd()
            except Exception:
                pass
        rows.append(row)
    _CMDLINES = fresh
    return rows


def live_job_pids() -> dict[int, str]:
    from junkroan.runs.store import Store

    out: dict[int, str] = {}
    try:
        for job in Store().jobs(state="running"):
            if job.pid:
                out[int(job.pid)] = "filler" if job.is_filler else "counted"
    except Exception:
        pass
    return out


def _norm(s: str) -> str:
    return s.replace("\\", "/").lower()


def _is_pytest(row: Mapping[str, Any]) -> bool:
    for tok in row.get("cmdline") or ():
        if _norm(str(tok)).rsplit("/", 1)[-1] in ("pytest", "pytest.exe"):
            return True
    return False


def _pytest_args(row: Mapping[str, Any]) -> list[str]:
    cmd = [_norm(str(t)) for t in row.get("cmdline") or ()]
    for i, tok in enumerate(cmd):
        if tok.rsplit("/", 1)[-1] in ("pytest", "pytest.exe"):
            return cmd[i + 1:]
    return []


def _runs_whole_suite(row: Mapping[str, Any]) -> bool:
    for tok in _pytest_args(row):
        if re.search(r"\.py(::|$)", tok) or re.match(r"(\./)?tests/.+", tok):
            return False
    return True


def _is_pob_runtime(row: Mapping[str, Any]) -> bool:
    return any(mark in _norm(" ".join(str(t) for t in row.get("cmdline") or ())) for mark in POB_RUNTIME_MARKS)


def _in_merge_suite(row: Mapping[str, Any]) -> bool:
    hay = _norm(" ".join(str(t) for t in row.get("cmdline") or ()) + " " + str(row.get("cwd") or ""))
    return any(mark in hay for mark in MERGE_SUITE_MARKS)


def _classify(row: Mapping[str, Any]) -> str:
    if row["pid"] in (0, 4):
        return "system"
    user = (row.get("username") or "").lower().rsplit("\\", 1)[-1]
    if row.get("session") == 0 or user in SYSTEM_USERS:
        return "system"
    if not row.get("username"):
        # denied username: the OS only refuses other users' processes, so session 0 / unknown is
        # a service; a denied process inside the user's own session is "could not be read"
        return "system" if row.get("session") in (0, None) and row.get("name") else "other"
    return "owner"


def snapshot(proc_table: list[dict[str, Any]] | None = None, job_pids: Mapping[int, str] | None = None,
             prev: Mapping[str, Any] | None = None, *, wall: float | None = None,
             ncpu: int | None = None) -> dict[str, Any]:
    """One reading of the machine split into groups (shape in issue #406). `prev` is an earlier
    snapshot (its private `_cpu_s` / `_wall` are the baseline for cpu shares); with none, a live
    table is read twice `_PRIME_S` apart. `wall` (monotonic seconds) and `ncpu` are for tests."""

    live = proc_table is None
    psutil = None
    if live:
        import psutil  # noqa: PLC0415

        psutil.cpu_percent(interval=None)  # prime: the reading below is the load since this call
    table = read_proc_table() if live else proc_table
    now_wall = time.monotonic() if wall is None else wall
    if prev is None and live:
        time.sleep(_PRIME_S)
        prev = {"_cpu_s": {r["pid"]: r["cpu_s"] for r in table}, "_wall": now_wall}
        table = read_proc_table()
        now_wall = time.monotonic()
    cpu_total = free_mb = total_mb = 0.0
    if live:
        cpu_total = float(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        free_mb, total_mb = vm.available / (1024 * 1024), vm.total / (1024 * 1024)
    if ncpu is None:
        ncpu = os.cpu_count() or 1
    if job_pids is None:
        job_pids = live_job_pids() if live else {}

    by_pid = {r["pid"]: r for r in table}
    prev_cpu = (prev or {}).get("_cpu_s") or {}
    dt = (now_wall - prev["_wall"]) if prev and "_wall" in prev else 0.0

    def cpu_share(row: Mapping[str, Any]) -> float:
        before = prev_cpu.get(row["pid"])
        if before is None or dt <= 0:
            return 0.0
        return max(0.0, (row["cpu_s"] - before) / dt / ncpu * 100.0)

    def chain(pid: Any) -> list[int]:
        out: list[int] = []
        while pid in by_pid and pid not in out:
            out.append(pid)
            pid = by_pid[pid].get("ppid")
        return out

    groups = {g: {"cpu_pct": 0.0, "rss_mb": 0.0, "count": 0} for g in GROUPS}
    pob_runtime = {g: 0 for g in GROUPS}
    pytests: dict[int, Mapping[str, Any]] = {}
    for row in table:
        pids = chain(row["pid"])
        group = None
        for p in pids:  # nearest job pid wins
            if p in job_pids:
                group = "pob_filler" if job_pids[p] == "filler" else "pob_counted"
                break
        if group is None and any(_norm(by_pid[p].get("name") or "") in ("claude.exe", "claude") for p in pids):
            group = "claude"
        if group is None:
            group = _classify(row)
        g = groups[group]
        g["cpu_pct"] += cpu_share(row)
        g["rss_mb"] += float(row.get("rss_mb") or 0.0)
        g["count"] += 1
        if _is_pytest(row):
            pytests[row["pid"]] = row
        if _is_pob_runtime(row):
            pob_runtime[group] += 1

    whole = merge = 0
    whole_list: list[dict[str, Any]] = []
    for row in pytests.values():
        if any(p in pytests for p in chain(row["pid"])[1:]):  # a pytest under any pytest is not top-level
            continue
        merge += _in_merge_suite(row)
        if _runs_whole_suite(row):
            whole += 1
            whole_list.append({"pid": row["pid"], "cwd": row.get("cwd"), "merge_suite": _in_merge_suite(row)})

    for g in groups.values():
        g["cpu_pct"] = round(g["cpu_pct"], 2)
        g["rss_mb"] = round(g["rss_mb"], 1)
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "free_ram_mb": round(free_mb, 1), "total_ram_mb": round(total_mb, 1),
        "cpu_pct": round(cpu_total, 1), "groups": groups,
        "whole_suite_pytest": int(whole), "merge_suite_pytest": int(merge),
        "whole_suite_list": whole_list, "pob_runtime_by_group": pob_runtime,
        "_cpu_s": {r["pid"]: r["cpu_s"] for r in table}, "_wall": now_wall,
    }


def read_ppids() -> dict[int, int | None]:
    """pid -> ppid of every process: the one cheap read (no cmdline, memory, username)."""

    import psutil

    try:  # one Toolhelp snapshot on Windows (10 ms); process_iter builds a Process per pid (5 s cold)
        return dict(psutil._psplatform.ppid_map())
    except Exception:
        return {p.pid: p.info.get("ppid") for p in psutil.process_iter(["pid", "ppid"], ad_value=None)}


def read_cpu_s(pid: int) -> float | None:
    """user + system cpu seconds of one process; None when it vanished or is denied."""

    import psutil

    try:
        t = psutil.Process(pid).cpu_times()
        return float(t.user + t.system)
    except Exception:
        return None


def pob_cpu_pct(job_pids: Mapping[int, str] | None = None, *, ppids_reader=read_ppids, cpu_reader=read_cpu_s,
                ncpu: int | None = None, clock=time.monotonic, sleep=time.sleep,
                full_run_out: dict | None = None) -> float:
    """`groups["pob_counted"].cpu_pct + groups["pob_filler"].cpu_pct` of `snapshot()` (same formula, same
    rounding per group) without reading the whole table (#728): only pid / ppid for everyone, cpu times
    only for the processes inside a job-pid chain, twice `_PRIME_S` apart. With `full_run_out` (a dict) the
    same window also reads the `agentops full-run` tree (#735) and stores it as `full_run_out["cpu_pct"]`."""

    if full_run_out is not None:
        pob, full = pob_and_full_run_cpu_pct(job_pids, ppids_reader=ppids_reader, cpu_reader=cpu_reader,
                                             ncpu=ncpu, clock=clock, sleep=sleep)
        full_run_out["cpu_pct"] = full
        return pob

    if job_pids is None:
        job_pids = live_job_pids()
    if ncpu is None:
        ncpu = os.cpu_count() or 1
    ppids = ppids_reader()

    def nearest_job(pid: Any) -> int | None:
        seen: list[int] = []
        while pid in ppids and pid not in seen:
            if pid in job_pids:
                return pid
            seen.append(pid)
            pid = ppids[pid]
        return None

    members = {pid: j for pid in ppids if (j := nearest_job(pid)) is not None}
    t0 = clock()
    before = {pid: s for pid in members if (s := cpu_reader(pid)) is not None}
    sleep(_PRIME_S)
    after = {pid: s for pid in before if (s := cpu_reader(pid)) is not None}
    dt = clock() - t0
    sums = {"pob_counted": 0.0, "pob_filler": 0.0}
    if dt > 0:
        for pid, s in after.items():
            group = "pob_filler" if job_pids[members[pid]] == "filler" else "pob_counted"
            sums[group] += max(0.0, (s - before[pid]) / dt / ncpu * 100.0)
    return round(sums["pob_counted"], 2) + round(sums["pob_filler"], 2)


def read_cmdlines() -> dict[int, list[str]]:
    """pid -> command line of every process (psutil; a denied or vanished one is skipped)."""

    import psutil

    return {p.pid: list(p.info.get("cmdline") or ()) for p in psutil.process_iter(["pid", "cmdline"], ad_value=None)}


def is_full_run_cmdline(cmdline: Any) -> bool:
    """The `agentops full-run` process (#735): `agentops` and `full-run` both in its command line."""

    line = _norm(" ".join(str(t) for t in cmdline or ()))
    return "agentops" in line and "full-run" in line


class _Handles:
    """#762: a held handle per tree member, so the cpu of a process that ended inside the window stays readable
    (`GetProcessTimes` works on an exited process while its handle is open). Off Windows: psutil, last good read."""

    def __init__(self) -> None:
        self.h: dict[int, Any] = {}
        self.last: dict[int, float] = {}
        self.born: dict[int, float | None] = {}

    def open(self, pid: int) -> bool:
        if sys.platform != "win32":
            return read_cpu_s(pid) is not None
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        self.h[pid] = h
        return True

    def read(self, pid: int) -> float | None:
        if sys.platform != "win32":
            v = read_cpu_s(pid)
            if v is not None:
                self.last[pid] = v
            return self.last.get(pid)
        import ctypes
        from ctypes import wintypes

        ft = [wintypes.FILETIME() for _ in range(4)]
        if ctypes.windll.kernel32.GetProcessTimes(self.h[pid], *[ctypes.byref(f) for f in ft]):
            self.last[pid] = sum(((f.dwHighDateTime << 32) | f.dwLowDateTime) for f in ft[2:]) / 1e7
        return self.last.get(pid)

    def created(self, pid: int) -> float | None:
        """#769: when the process was created (seconds, one clock for every pid); None when unreadable. Cached."""

        if pid in self.born:
            return self.born[pid]
        v: float | None = None
        try:
            if sys.platform != "win32":
                import psutil

                v = float(psutil.Process(pid).create_time())
            else:
                import ctypes
                from ctypes import wintypes

                k = ctypes.windll.kernel32
                h = self.h.get(pid) or k.OpenProcess(0x1000, False, pid)
                if h:
                    ft = [wintypes.FILETIME() for _ in range(4)]
                    if k.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                        v = ((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime) / 1e7
                    if pid not in self.h:
                        k.CloseHandle(h)
        except Exception:
            v = None
        self.born[pid] = v
        return v

    def close(self) -> None:
        if sys.platform == "win32":
            import ctypes

            for h in self.h.values():
                ctypes.windll.kernel32.CloseHandle(h)
        self.h.clear()


def _chain(pid: Any, ppids: Mapping[int, Any]) -> list[int]:
    seen: list[int] = []
    while pid in ppids and pid not in seen:
        seen.append(pid)
        pid = ppids[pid]
    return seen


def _exact_tree_window(job_pids, roots, ncpu, ppids, up, clock, sleep, *, ppids_reader=read_ppids, handles=_Handles):
    """#762: one window in which every process of the pob job trees and the full-run tree, born or ended inside
    it, is counted: a fast ppid snapshot loop adds each new pid whose ancestor chain hits a job / root pid and
    holds its handle; cpu is read after every loop, so the last read of an ended process stands. Returns
    `(pob_counted, pob_filler, full)` in percent of the machine."""

    hs = handles()
    members: dict[int, tuple[str, int | None]] = {}
    base: dict[int, float] = {}

    def classify(pid: int, chain: list[int]):
        job = next((p for p in chain if p in job_pids), None)
        if job is not None:
            return ("pob", job), chain[:chain.index(job) + 1]
        i = next((i for i, p in enumerate(chain) if p in roots), None) if roots else None
        return (("full", None), chain[:i + 1]) if i is not None else (None, chain)

    def born_after_ancestors(path: list[int]) -> bool:
        """#769: a ppid goes stale when its parent ends and the pid is recycled; a process created before the
        process its ppid names is not that process's child, so it is no member of the tree."""
        for child, parent in zip(path, path[1:]):
            a, b = hs.created(child), hs.created(parent)
            if a is not None and b is not None and a < b:
                return False
        return True

    def scan(ppids, born):
        for pid in ppids:
            if pid in members or pid in rejected:
                continue
            kind, path = classify(pid, up(pid, ppids))
            if kind is None or not born_after_ancestors(path):
                rejected.add(pid)
            elif hs.open(pid):
                members[pid] = kind
                base[pid] = (hs.read(pid) or 0.0) if not born else 0.0
            else:
                rejected.add(pid)

    rejected: set[int] = set()
    try:
        t0 = clock()
        scan(ppids, False)
        while clock() - t0 < _TREE_WINDOW_S:
            sleep(_TREE_STEP_S)
            for pid in members:
                hs.read(pid)
            scan(ppids_reader(), True)
        for pid in members:
            hs.read(pid)
        dt = clock() - t0
    finally:
        hs.close()
    sums = {"pob_counted": 0.0, "pob_filler": 0.0, "full": 0.0}
    for pid, (kind, job) in members.items():
        share = max(0.0, (hs.last.get(pid, 0.0) - base[pid]) / dt / ncpu * 100.0) if dt > 0 else 0.0
        sums["full" if kind == "full" else ("pob_filler" if job_pids[job] == "filler" else "pob_counted")] += share
    return sums["pob_counted"], sums["pob_filler"], sums["full"]


def pob_and_full_run_cpu_pct(job_pids: Mapping[int, str] | None = None, *, ppids_reader=read_ppids,
                             cpu_reader=read_cpu_s, cmdline_reader=read_cmdlines, ncpu: int | None = None,
                             clock=time.monotonic, sleep=time.sleep,
                             self_pid: int | None = None) -> tuple[float, float | None]:
    """`(pob_cpu_pct(...), full run's cpu %)` from ONE per-process window (#735). The full run is the
    `agentops full-run` process plus all its descendants (pytest, xdist children); its share is None when
    no such process exists, or when the caller itself is inside that tree (the full run's own probe:
    its own tree is not free for itself)."""

    if job_pids is None:
        job_pids = live_job_pids()
    if ncpu is None:
        ncpu = os.cpu_count() or 1
    if self_pid is None:
        self_pid = os.getpid()
    ppids = ppids_reader()

    def up(pid: Any) -> list[int]:
        seen: list[int] = []
        while pid in ppids and pid not in seen:
            seen.append(pid)
            pid = ppids[pid]
        return seen

    roots = {pid for pid, cmd in cmdline_reader().items() if pid != self_pid and is_full_run_cmdline(cmd)}
    roots -= set(up(self_pid))
    if ppids_reader is read_ppids and cpu_reader is read_cpu_s and sleep is time.sleep:  # real readers: #762
        counted, filler, full_pct = _exact_tree_window(job_pids, roots, ncpu, ppids, lambda p, tbl: _chain(p, tbl),
                                                       clock, sleep)
        return round(counted, 2) + round(filler, 2), (round(full_pct, 2) if roots else None)
    members: dict[int, tuple[str, int | None]] = {}
    for pid in ppids:
        chain = up(pid)
        job = next((p for p in chain if p in job_pids), None)
        if job is not None:
            members[pid] = ("pob", job)
        elif roots and any(p in roots for p in chain):
            members[pid] = ("full", None)
    t0 = clock()
    before = {pid: s for pid in members if (s := cpu_reader(pid)) is not None}
    sleep(_PRIME_S)
    after = {pid: s for pid in before if (s := cpu_reader(pid)) is not None}
    dt = clock() - t0
    sums = {"pob_counted": 0.0, "pob_filler": 0.0}
    full = 0.0
    if dt > 0:
        for pid, s in after.items():
            share = max(0.0, (s - before[pid]) / dt / ncpu * 100.0)
            kind, job = members[pid]
            if kind == "full":
                full += share
            else:
                sums["pob_filler" if job_pids[job] == "filler" else "pob_counted"] += share
    pob = round(sums["pob_counted"], 2) + round(sums["pob_filler"], 2)
    return pob, (round(full, 2) if roots else None)


def public(snap: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in snap.items() if not k.startswith("_")}
