"""PoB slots held by a process tree the runs store knows nothing about (issue #365).

`untracked_trees` is pure: the caller passes the slot rows, the store's running jobs and a process
table. `collect_local` builds those three on this machine and calls it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from junkroan.runs import proc_bulk

#: Command-line needles of a PoB-run launcher, the same ones `scripts/machine_load.py` PROCESS_KINDS
#: uses for "queue runner" and "bench / benchmark / transplant", plus the `junkroan` console script.
LAUNCHER_NEEDLES: tuple[str, ...] = (
    "run_queue.py",
    "benchmark.py",
    "replay_bench.py",
    "gear_transplant.py",
    "search.py",
    "build_from_skeleton.py",
    "junkroan.exe",
)

CMD_HEAD_CHARS = 80
_TAG_RE = re.compile(r"--tag(?:=|\s+)(\"[^\"]*\"|'[^']*'|\S+)")

#: pid -> (ppid, create_time, cmdline)
ProcTable = Mapping[int, tuple["int | None", "float | None", "str | Sequence[str]"]]


@dataclass(frozen=True)
class UntrackedTree:
    pid: int | None
    started: float | None
    cmd_head: str
    tag: str | None
    slots: int


def _line(cmdline: "str | Sequence[str] | None") -> str:
    if not cmdline:
        return ""
    return cmdline if isinstance(cmdline, str) else " ".join(cmdline)


def parse_tag(cmdline: str) -> str | None:
    m = _TAG_RE.search(cmdline)
    return m.group(1).strip("\"'") if m else None


def _is_launcher(cmdline: str) -> bool:
    low = cmdline.lower()
    return any(n in low for n in LAUNCHER_NEEDLES)


def _chain(pid: int, procs: ProcTable) -> list[int]:
    """`pid` and its ancestors that the table knows, nearest first (cycle-safe)."""

    out: list[int] = []
    seen: set[int] = set()
    cur: int | None = pid
    while cur is not None and cur in procs and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = procs[cur][0]
    return out


def untracked_trees(
    slot_rows: Iterable[Mapping[str, Any]],
    jobs: Iterable[Any],
    procs: ProcTable,
) -> list[UntrackedTree]:
    # the store keeps a job's pid as a string ('20092'); compare as int (#365 live check)
    job_pids = set()
    for j in jobs:
        try:
            job_pids.add(int(getattr(j, "pid", None)))
        except (TypeError, ValueError):
            pass
    groups: dict[Any, list[Any]] = {}  # group key -> [root pid, slot count]
    for row in slot_rows:
        pid = row.get("pid")
        if not isinstance(pid, int) or pid not in procs:
            continue  # no evidence about this slot holder: never report a tree we know nothing of (#374)
        chain = _chain(pid, procs)
        if job_pids & (set(chain) | ({pid} if pid is not None else set())):
            continue
        root = pid
        for p in chain:  # the top-most launcher on the way up
            if _is_launcher(_line(procs[p][2])):
                root = p
        g = groups.setdefault(root, [root, 0])
        g[1] += 1
    trees: list[UntrackedTree] = []
    for root, count in groups.values():
        entry = procs.get(root)
        if entry is None:
            continue
        line = _line(entry[2])
        if entry[1] is None and not line:
            continue  # an unreadable process (no start, no command) is a failed observation, not a finding (#374)
        trees.append(
            UntrackedTree(
                pid=root,
                started=entry[1],
                cmd_head=line[:CMD_HEAD_CHARS],
                tag=parse_tag(line),
                slots=count,
            )
        )
    trees.sort(key=lambda t: (t.started or 0.0, t.pid or 0))
    return trees


#: #988: (pid, create_time) -> command line of a slot holder's chain member; a command line never changes during
#: a process's life, and reading one costs ~10 ms on Windows. Rebuilt each pass to the members seen in it.
_CMDLINES: dict[tuple[int, "float | None"], str] = {}


def collect_local(store: Any) -> list[UntrackedTree]:
    """The inputs of `untracked_trees` on this machine: psutil, `busy_slots`, the store's running jobs.

    #988: `untracked_trees` looks at a process only when it is a slot holder or one of its ancestors, so the
    table is read cheap (pid, ppid, start) and a command line is read only for those, and only once. With no
    slot holder at all the answer is empty and nothing of the process table is read.
    """

    global _CMDLINES
    import psutil

    from junkroan.pob import slot_budget

    # slots FIRST: a worker that takes its slot after the process table was built is absent from it (#374)
    slots = slot_budget.busy_slots()
    if not any(isinstance(row.get("pid"), int) for row in slots):
        return []
    live: dict[int, tuple[int | None, float | None]] = {}
    handles: dict[int, Any] = {}
    bulk = proc_bulk.snapshot()  # the whole list in one OS call where there is one (Windows)
    if bulk is not None:
        live = {pid: (r.ppid, r.create_time) for pid, r in bulk.items()}
    else:
        for p in psutil.process_iter(["pid", "ppid", "create_time"]):
            try:
                i = p.info
                live[i["pid"]] = (i.get("ppid"), i.get("create_time"))
                handles[i["pid"]] = p
            except Exception:
                continue
    wanted: set[int] = set()
    for row in slots:
        pid = row.get("pid")
        if isinstance(pid, int) and pid in live:
            wanted.update(_chain(pid, live))
    cmdlines: dict[tuple[int, "float | None"], str] = {}
    procs: dict[int, tuple[int | None, float | None, str]] = {}
    for pid, (ppid, started) in live.items():
        line = ""
        if pid in wanted:
            key = (pid, started)
            line = _CMDLINES.get(key)
            if line is None:
                try:
                    handle = handles.get(pid) or psutil.Process(pid)
                    line = " ".join(handle.cmdline() or ())
                except psutil.NoSuchProcess:
                    continue  # gone since the scan: absent from the table, as a process_iter would skip it
                except Exception:
                    line = ""
            if line:
                cmdlines[key] = line
        procs[pid] = (ppid, started, line)
    _CMDLINES = cmdlines
    return untracked_trees(slots, store.jobs(state="running"), procs)
