"""A machine-wide budget of live PoB sessions, enforced where a session is born.

One PoB session = one headless runtime process of ~1 GB that wants a whole core. Five PoB-backed
jobs launched by five people who did not know of each other put 13 worker slots on 12 cores
(incident 2026-09-20 07:10). This module is the counter they all share: ``PobSession.__enter__``
takes one slot before it starts its runtime and gives it back when the session closes.

The counter is a set of OS file locks under the SHARED ``var/locks/`` -- shared because every
worktree reaches ``var/`` through a junction, so the directory is resolved from the MAIN checkout
(``git rev-parse --git-common-dir``), never relative to the worktree the code happens to run from.
An OS lock dies with the process that holds it, so a killed worker frees its slot with no cleanup
and no stale-PID bookkeeping.

Two roles. ``JUNKROAN_POB_ROLE=queue`` (set by ``scripts/run_queue.py`` for what it starts, and
inherited by its children) may take only ``total`` slots -- exactly as before #41 -- UNLESS the
budget document opts in with a top-level ``"strict_reserve": true``, in which case it is held to
the top ``total - others`` slots (the strict reserve, issue #41: ``Budget.limit_for("queue") ==
total - others``, floor 1, and it never reaches down into the ``others`` range even when those
slots sit idle). The flag is opt-in, default off, because turning the reserve on unconditionally
would have stalled the laptop's own hand-written ``others: 3`` budget the moment this code reached
it (``total - others == 0``, every laptop run stuck); ``config/hosts.json`` renders
``strict_reserve: true`` for every mode that should actually reserve. Without the flag, everyone
else -- agents, GPT workers, pytest, scripts run by hand -- may still take only ``1..others``,
unchanged from before #41. A queue runner started BEFORE this code existed sets no variable, so
the role is also recognised from the process ancestry (``current_role``): the production queue
must never be the one that waits.

Within the ``queue`` role, three priorities: ``JUNKROAN_POB_PRIORITY=P0``/``P1``/``P2`` (also
``0``/``1``/``2``; unset or unknown is ``P2``), inherited like ``JUNKROAN_POB_ROLE``. A queue
waiter takes a freed slot only when no LIVE queue waiter of a strictly higher priority (lower
number) is also waiting; a dead waiter (its marker's lock is gone) never blocks. Equal priorities,
and the ``others`` role, are unaffected -- this is ordering among queue waiters only.

The budget is re-read from ``var/machine_budget.json`` on every attempt (the lead edits it while
jobs run), plus -- only when ``strict_reserve`` is on -- any active (not expired) reservations for
this host in ``var/reservations.json`` (``runs reserve``, issue #41), which are added to ``others``
-- capped so the queue always keeps at least one slot. Without the flag a reservation changes
nothing: the ``others`` share is not being held back from the queue in the first place, so there is
nothing for it to add slots to. ``JUNKROAN_POB_SLOTS=off`` disables the whole mechanism.

Nothing here may break a build: every failure of the slot machinery itself is one logged line and
a session that runs WITHOUT a slot, never a raise and never a hang.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ROLE_QUEUE = "queue"
ROLE_OTHER = "other"
#: The PoB-free merge test suite's pytest workers (#666): capped by ``merge_suite``, holds no PoB slot.
ROLE_MERGE_SUITE = "merge_suite"

#: The budget written on first use and used whenever the file is missing or unreadable.
#: "hours" [8, 25] = 08:00 to 01:00 the next day.
DEFAULT_BUDGET: dict[str, dict[str, Any]] = {
    "day": {"hours": [8, 25], "total": 7, "others": 2, "min_free_ram_gb": 8, "merge_suite": 6, "merge_suite_reserve_gb": 3},
    "night": {"hours": [1, 8], "total": 10, "others": 5, "min_free_ram_gb": 3, "merge_suite": 6, "merge_suite_reserve_gb": 3},
}

#: RAM one merge-suite pytest worker needs (#684): #666 measured the peak of 6 workers at 2.04 GB in
#: total; 2.04 / 6 = 0.34 rounded UP to 0.1 GB.
SUITE_PER_WORKER_GB = 0.4

#: CPU one merge-suite pytest worker costs, in cores (#744), measured 2026-10-10 (a whole-suite run on 5
#: workers, three 34 s windows 13:04-13:09): lower bound 1.64 cores / 5 = 0.33 a worker, with everything
#: doubtful counted 2.4 cores / 5 = 0.48 a worker; the upper bound rounded to 0.5.
SUITE_WORKER_CORES = 0.5


def suite_workers_from_readings(
    logical_cores: int,
    cpu_percent: float | None,
    free_ram_gb: float | None,
    reserve_gb: float,
    per_worker_gb: float,
    cap: int,
    pob_cpu_percent: float | None = None,
    full_run_cpu_percent: float | None = None,
    pob_stepped_down: bool = True,
    floor_gb: float | None = None,
) -> tuple[int, str]:
    """The merge suite's pytest worker count from ONE CPU and ONE RAM reading (#684):
    ``max(1, min(cap, by_cpu, free_ram_workers))``; ``by_cpu = floor(cores * (100 - cpu) / 100 / SUITE_WORKER_CORES)``,
    ``free_ram_workers = floor((free_ram - reserve) / per_worker)``. A reading that is ``None`` (its
    reader failed) drops out of the minimum; RAM unreadable -> 1 worker. Returns ``(n, line)``.
    #966: ``floor_gb`` = the run queue's free-RAM floor (the budget's ``min_free_ram_gb``); free RAM under it -> 1 worker."""

    import math

    cap = max(1, int(cap))
    if free_ram_gb is None:
        return 1, f"workers 1: RAM n/a -> 1 (reader failed), cap {cap}"
    if floor_gb is not None and free_ram_gb < floor_gb:
        _, line = suite_workers_from_readings(logical_cores, cpu_percent, free_ram_gb, reserve_gb, per_worker_gb,
                                              cap, pob_cpu_percent, full_run_cpu_percent, pob_stepped_down)
        return 1, f"workers 1: free RAM {free_ram_gb:.1f} GB under the floor {floor_gb:g} GB, " + line.split(": ", 1)[1]
    by_ram = max(0, math.floor((free_ram_gb - reserve_gb) / per_worker_gb + 1e-9))
    if cpu_percent is None:
        n = max(1, min(cap, by_ram))
        return n, f"workers {n}: cpu n/a, RAM free {free_ram_gb:.1f} GB -> {by_ram} by RAM, cap {cap}"
    # #715: the runs daemon's PoB workers step down to Idle priority while a suite runs, so the share
    # they burn counts as free: cpu of everything except them.
    # #735: the full run on main (the `agentops full-run` tree) yields to a merge suite the same way.
    other_cpu = cpu_percent
    # #775: the full run does not step PoB down, so PoB's share stays busy for it.
    if pob_cpu_percent is not None and pob_stepped_down:
        other_cpu = max(0.0, other_cpu - pob_cpu_percent)
    if full_run_cpu_percent is not None:
        other_cpu = max(0.0, other_cpu - full_run_cpu_percent)
    free_cores = max(0.0, logical_cores * (100 - other_cpu) / 100)
    by_cpu = math.floor(free_cores / SUITE_WORKER_CORES + 1e-9)
    n = max(1, min(cap, by_cpu, by_ram))
    shares = f"cpu {cpu_percent:.0f}%" if pob_cpu_percent is None else f"cpu {cpu_percent:.0f}%, PoB workers {pob_cpu_percent:.0f}%"
    if pob_cpu_percent is not None and not pob_stepped_down:
        shares += ", PoB not stepped down"
    if full_run_cpu_percent is not None:
        shares += f", full run {full_run_cpu_percent:.0f}%"
    return n, (f"workers {n}: cores free {free_cores:.1f} of {logical_cores} ({shares}), "
               f"{SUITE_WORKER_CORES:g} core a worker -> {by_cpu} by CPU, RAM free {free_ram_gb:.1f} GB -> {by_ram} by RAM, cap {cap}")


#: The runs daemon (``junkroan.runs.daemon``, #82) exports this with a job id for every child it
#: starts; everything that child starts in turn inherits it, so a PoB worker's slot carries the id
#: of the job that owns it. That is how the daemon tells ITS OWN slots (already paid for by the
#: job's declared ``workers``) from a foreign run's, without walking process ancestry.
JOB_ENV = "JUNKROAN_RUNS_JOB"

POLL_SECONDS = 2.0
SLOT_FILE_GLOB = "pob-slot-*.lock"
WAIT_FILE_GLOB = "pob-wait-*.lock"
_INFO_WIDTH = 512  # every info line is written padded to this many bytes, so the file never shrinks
_LOCK_OFFSET = 1_000_000  # the locked byte sits past the content, so readers can read it unlocked
_CMD_CHARS = 120


# -- logging -----------------------------------------------------------------------------------

def _log(message: str) -> None:
    """One line to stderr. Not `logging`: most entry points never configure it."""

    try:
        sys.stderr.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} pob-slot: {message}\n")
        sys.stderr.flush()
    except Exception:  # a closed stderr must not take a build down
        pass


# -- where the shared directory is -------------------------------------------------------------

_shared_var: Path | None = None


def shared_var_dir() -> Path:
    """The MAIN checkout's ``var/``: the one directory every worktree's junction points at.

    ``git rev-parse --git-common-dir`` is the main checkout's ``.git`` from anywhere inside any
    worktree; its parent is the main checkout. Falls back to this file's own project root when git
    is unavailable (a source tree unpacked without git).
    """

    global _shared_var
    if _shared_var is not None:
        return _shared_var
    root = PROJECT_ROOT
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:  # git < 2.31 has no --path-format
            result = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=str(Path(__file__).resolve().parent),
                capture_output=True,
                text=True,
                timeout=15,
            )
        common = (result.stdout or "").strip()
        if result.returncode == 0 and common:
            path = Path(common)
            if not path.is_absolute():
                path = (Path(__file__).resolve().parent / path).resolve()
            root = path.resolve().parent
    except Exception:
        pass
    _shared_var = root / "var"
    return _shared_var


def slot_dir() -> Path:
    """The directory holding the slot lock files (``JUNKROAN_POB_SLOT_DIR`` overrides; tests do)."""

    override = os.environ.get("JUNKROAN_POB_SLOT_DIR")
    return Path(override) if override else shared_var_dir() / "locks"


def budget_path() -> Path:
    """The live budget file (``JUNKROAN_POB_BUDGET`` overrides; tests do)."""

    override = os.environ.get("JUNKROAN_POB_BUDGET")
    return Path(override) if override else shared_var_dir() / "machine_budget.json"


def _checkout_root() -> Path:
    """The root of the checkout this code runs from (tests monkeypatch this)."""

    return Path(__file__).resolve().parents[3]


def _norm_path(value: str | Path) -> str:
    try:
        resolved = Path(str(value)).resolve()
    except (OSError, ValueError):
        resolved = Path(str(value))
    return os.path.normcase(str(resolved)).replace("\\", "/").rstrip("/").lower()


def current_host(root: Path | None = None) -> str:
    """This machine's name in ``config/hosts.json``.

    ``JUNKROAN_HOST`` wins. Without it, the checkout root equal to a host's ``daemon_repo_path``
    names that host (an ``ssh laptop`` shell inside the daemon checkout sets no variable); an
    unreadable hosts config or no match gives ``pc``.
    """

    env = (os.environ.get("JUNKROAN_HOST") or "").strip().lower()
    if env:
        return env
    try:
        from junkroan.runs.hosts import load_hosts_config  # lazy: runs.hosts imports this module

        here = _norm_path(root if root is not None else _checkout_root())
        for name, cfg in load_hosts_config().items():
            repo = cfg.get("daemon_repo_path") if isinstance(cfg, dict) else None
            if repo and _norm_path(repo) == here:
                return str(name).strip().lower()
    except Exception:
        pass
    return "pc"


def reservations_file() -> Path:
    """The live reservations file (``JUNKROAN_POB_RESERVATIONS`` overrides; tests do)."""

    override = os.environ.get("JUNKROAN_POB_RESERVATIONS")
    return Path(override) if override else shared_var_dir() / "reservations.json"


def read_reservations(path: Path | None = None) -> list[dict[str, Any]]:
    """Every reservation entry in the file, BOM-tolerant, ``[]`` when missing or unreadable.

    The same reader `runs reserve` / `runs mode` (``junkroan.runs.hosts``) use to list and prune
    entries, so a budget read and a CLI listing never disagree on what is active.
    """

    target = path if path is not None else reservations_file()
    try:
        if not target.is_file():
            return []
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        if isinstance(raw, list):
            return [dict(entry) for entry in raw if isinstance(entry, dict)]
    except Exception as exc:
        _log(f"cannot read {target} ({exc}); ignoring reservations")
    return []


def _active_reserved_slots(host: str, *, now: datetime, path: Path | None) -> int:
    """The sum of ``slots`` for this host's reservations that have not expired by ``now``."""

    total = 0
    for entry in read_reservations(path):
        if str(entry.get("host") or "").strip().lower() != host:
            continue
        expires = entry.get("expires")
        if expires:
            try:
                if datetime.fromisoformat(str(expires)) <= now:
                    continue  # expired: ignored here, pruned by the next `runs reserve` write
            except Exception:
                continue  # an unparsable expiry is treated as already gone, not as forever
        try:
            total += max(0, int(entry.get("slots", 0)))
        except Exception:
            continue
    return total


def enabled() -> bool:
    return os.environ.get("JUNKROAN_POB_SLOTS", "").strip().lower() != "off"


_role_cache: str | None = None
_QUEUE_MARKER = "run_queue.py"
_ANCESTOR_LEVELS = 10


def _ancestor_command_lines(max_levels: int = _ANCESTOR_LEVELS) -> list[str]:
    """This process's ancestors' command lines, nearest first; stops at any error or denial."""

    import psutil  # noqa: PLC0415 -- optional; without it there is no ancestry to read

    lines: list[str] = []
    process = psutil.Process()
    for _ in range(max_levels):
        try:
            process = process.parent()
            if process is None:
                break
            lines.append(" ".join(str(part) for part in (process.cmdline() or ())))
        except Exception:  # NoSuchProcess, AccessDenied, a parent that died mid-walk
            break
    return lines


def role_source() -> str:
    """Where ``current_role`` got its answer, for the report."""

    return "JUNKROAN_POB_ROLE" if os.environ.get("JUNKROAN_POB_ROLE", "").strip().lower() in {ROLE_QUEUE, ROLE_OTHER} else "process ancestry"


def current_role(*, ancestry: Callable[[], Iterable[str]] | None = None) -> str:
    """``queue`` when this process was started by the run queue, else ``other``.

    The environment variable decides when it is set -- that is what ``run_queue.py`` writes for
    everything it starts. It is not always there: a queue runner started BEFORE this code existed
    sets nothing, yet its children (which snapshot the code per run) import this module, and the
    production queue must never be the one that waits. So the fallback walks up the parent chain
    (at most ten levels, any error ends the walk) and takes ``queue`` from an ancestor whose
    command line names ``run_queue.py``. The answer is cached: a process's ancestry does not
    change, and the walk costs a psutil scan.

    ``ancestry`` is the injection point for tests and bypasses the cache.
    """

    global _role_cache
    declared = os.environ.get("JUNKROAN_POB_ROLE", "").strip().lower()
    if declared in {ROLE_QUEUE, ROLE_OTHER}:
        return declared
    if ancestry is None and _role_cache is not None:
        return _role_cache
    role = ROLE_OTHER
    try:
        for line in (ancestry or _ancestor_command_lines)():
            if _QUEUE_MARKER in str(line or "").lower():
                role = ROLE_QUEUE
                break
    except Exception:  # no psutil, or a chain that cannot be read at all
        pass
    if ancestry is None:
        _role_cache = role
    return role


# -- priority (queue role only) -----------------------------------------------------------------

PRIORITY_DEFAULT = "P2"
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
_PRIORITY_ALIASES = {"p0": "P0", "0": "P0", "p1": "P1", "1": "P1", "p2": "P2", "2": "P2"}


def _normalize_priority(value: str | None) -> str:
    return _PRIORITY_ALIASES.get(str(value or "").strip().lower(), PRIORITY_DEFAULT)


def current_priority() -> str:
    """This process's priority: ``JUNKROAN_POB_PRIORITY``, or ``P2`` when unset or unknown."""

    return _normalize_priority(os.environ.get("JUNKROAN_POB_PRIORITY"))


def current_job() -> str | None:
    """The runs job this process belongs to (``JUNKROAN_RUNS_JOB``), or ``None`` outside one."""

    value = os.environ.get(JOB_ENV, "").strip()
    return value or None


# -- owner grouping (#117) -----------------------------------------------------------------------
#
# "Under one owner": several PoB workers that belong to the SAME run. A run started by this
# daemon (or any daemon) tags every worker it starts with the same `job` id (`JOB_ENV`), which is
# the most specific grouping there is. A run started outside any daemon -- a hand-run
# ``run_queue.py`` line, a hand-run ``scripts/benchmark.py --workers N`` -- sets no `job`, so its
# workers are told apart by process ancestry instead: every one of a `ProcessPoolExecutor`'s
# worker processes is a direct child of the one process that started the run, so grouping by that
# parent pid finds the same run without any run-tag at all.


def _default_parent_pid(pid: int) -> int | None:
    """The OS parent pid of ``pid``, or ``None`` when it cannot be read (no psutil, gone, denied)."""

    try:
        import psutil  # noqa: PLC0415 -- optional, exactly like `_ancestor_command_lines`

        return psutil.Process(pid).ppid()
    except Exception:
        return None


def owner_key(row: Mapping[str, Any], *, parent_pid: Callable[[int], int | None] = _default_parent_pid) -> str:
    """A string that is equal for every slot ``busy_slots()`` row belonging to the same run.

    ``job`` (``JOB_ENV``) when the row carries one -- the most specific and exact identity there
    is. Otherwise the row's own parent pid (``pid tree``), so a hand-run benchmark's several worker
    processes still group together; a row whose pid or its parent cannot be read falls back to its
    own pid, which groups with nothing else (a lone worker is its own owner).
    """

    job = row.get("job")
    if job:
        return f"job:{job}"
    pid = row.get("pid")
    if pid:
        try:
            parent = parent_pid(int(pid))
        except Exception:
            parent = None
        if parent:
            return f"pid:{parent}"
        return f"pid:{pid}"
    return "pid:?"


def current_owner_key(*, parent_pid: Callable[[int], int | None] = _default_parent_pid) -> str:
    """This process's own owner key, on the same terms as :func:`owner_key` reads other rows'."""

    job = current_job()
    if job:
        return f"job:{job}"
    pid = os.getpid()
    try:
        parent = parent_pid(pid)
    except Exception:
        parent = None
    return f"pid:{parent}" if parent else f"pid:{pid}"


def _priority_blocks(directory: Path, priority: str, *, exclude_pid: int | None = None) -> bool:
    """True when a live ``queue`` waiter of strictly higher priority (lower number) is waiting."""

    own_rank = _PRIORITY_RANK.get(priority, _PRIORITY_RANK[PRIORITY_DEFAULT])
    pid = os.getpid() if exclude_pid is None else exclude_pid
    for row in waiting(directory):
        if row.get("role") != ROLE_QUEUE or row.get("pid") == pid:
            continue
        other_rank = _PRIORITY_RANK.get(row.get("priority") or PRIORITY_DEFAULT, _PRIORITY_RANK[PRIORITY_DEFAULT])
        if other_rank < own_rank:
            return True
    return False


# -- the budget --------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Budget:
    """The numbers in force at one moment."""

    period: str
    hours: tuple[int, int]
    total: int
    others: int
    min_free_ram_gb: float
    source: Path | None = None
    strict_reserve: bool = False
    queue_slots: int | None = None  # #413: the document's explicit cap on the queue's share (0 = pause)
    merge_suite: int = 6  # #666: cap on the merge test suite's pytest workers (no PoB slot)
    merge_suite_reserve_gb: float = 3.0  # #684: RAM kept free before counting suite workers
    reserved: int = 0  # #621: slots the owner holds right now; ``total`` is already reduced by it
    reserved_until: datetime | None = None

    def limit_for(self, role: str) -> int:
        """How many slots this role may hold at most.

        The queue's limit is ``total`` (today's behaviour) UNLESS the budget document's top-level
        ``"strict_reserve": true`` opts a host into the reserve (#41 fix, 2026-09-26): a host that
        has not turned it on keeps taking any free slot down to 1, exactly as before -- turning
        #41 on by itself would have stalled the laptop's *current*, hand-written
        ``others: 3`` budget the moment this code reached it (``total - others = 0``). With the
        flag on, the queue's limit is ``max(1, total - others)`` -- the ``others`` share is then
        never available to it even idle, and the queue always keeps at least one slot regardless of
        how large ``others`` (or a reservation added to it) grows. Everyone else is capped at
        ``others`` (never above ``total``), flag or no flag.
        """

        if role == ROLE_MERGE_SUITE:
            return max(0, self.merge_suite)
        if role == ROLE_QUEUE:
            if self.strict_reserve:
                computed = max(0 if self.reserved else 1, self.total - self.others)
            else:
                computed = max(0, self.total)
            if self.queue_slots is not None:
                return max(0, min(self.queue_slots, computed))
            return computed
        return max(0, min(self.others, self.total))

    def window(self) -> str:
        start, end = self.hours
        return f"{start % 24:02d}:00-{end % 24:02d}:00"


def _hour_in(hour: int, start: int, end: int) -> bool:
    """``[8, 25]`` contains 00:30 (hour 0) and not 01:30 (hour 1)."""

    return start <= hour < end or start <= hour + 24 < end


def _budget_document(path: Path | None) -> tuple[dict[str, Any], Path | None]:
    """The budget file's content, writing the defaults on first use. Never raises."""

    target = path if path is not None else budget_path()
    try:
        if target.is_file():
            # utf-8-sig: PowerShell's `Set-Content -Encoding utf8` writes a BOM, and plain utf-8 then failed the parse and
            # fell back to the defaults silently (the laptop's workers waited 1 h 30 min on the desktop's RAM floor, 2026-09-24)
            raw = json.loads(target.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict) and raw:
                merged = {}
                for name, defaults in DEFAULT_BUDGET.items():
                    merged[name] = {**defaults, **dict(raw.get(name) or {})}
                for name, spec in raw.items():  # a period the defaults do not know
                    if name not in merged and isinstance(spec, dict):
                        merged[name] = dict(spec)
                return merged, target
            _log(f"{target} is not a budget object; using the defaults")
            return json.loads(json.dumps(DEFAULT_BUDGET)), target
    except Exception as exc:
        _log(f"cannot read {target} ({exc}); using the defaults")
        return json.loads(json.dumps(DEFAULT_BUDGET)), target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(DEFAULT_BUDGET, indent=1) + "\n", encoding="utf-8", newline="\n")
    except Exception as exc:
        _log(f"cannot write {target} ({exc}); using the defaults in memory")
    return json.loads(json.dumps(DEFAULT_BUDGET)), target


def _read_strict_reserve(path: Path | None) -> bool:
    """This budget document's top-level ``"strict_reserve"`` flag. Default ``False`` on any absence
    or error (missing file, bad JSON, wrong type) -- this never raises, and an unreadable or legacy
    document behaves exactly as before #41 (no reserve)."""

    target = path if path is not None else budget_path()
    try:
        if not target.is_file():
            return False
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            return bool(raw.get("strict_reserve", False))
    except Exception:
        pass
    return False


def _read_queue_slots(path: Path | None) -> int | None:
    """The document's top-level ``"queue_slots"`` (#413), or None when absent or unreadable."""

    target = path if path is not None else budget_path()
    try:
        if not target.is_file():
            return None
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
        value = raw.get("queue_slots") if isinstance(raw, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    except Exception:
        pass
    return None


def _owner_record(host: str, now: datetime, modes_file: Path | None) -> tuple[int, datetime] | None:
    """The owner's active reservation on ``host`` (#621), or None. Never raises."""

    try:
        from junkroan.runs import hosts as runs_hosts
        return runs_hosts.owner_reservation(host, now, modes_file=modes_file)
    except Exception:
        return None


def load_budget(
    *,
    now: datetime | None = None,
    path: Path | None = None,
    host: str | None = None,
    reservations_path: Path | None = None,
    modes_file: Path | None = None,
) -> Budget:
    """The budget in force at ``now``, with this host's active reservations folded into ``others``.

    With no reservations file and today's ``machine_budget.json`` this returns exactly today's
    values (nothing here changes the document read, only what it does with it): a reservation adds
    to ``others``, capped so the queue (``total - others``) never drops below one slot -- but only
    when the document's ``"strict_reserve"`` flag is on (#41 fix, 2026-09-26); without it the queue's
    limit is ``total`` regardless of ``others`` or any reservation, so a reservation is a no-op.
    """

    document, source = _budget_document(path)
    strict = _read_strict_reserve(path)
    queue_slots = _read_queue_slots(path)
    moment = now or datetime.now()
    chosen = None
    try:
        from junkroan.runs import hosts as runs_hosts
        forced = runs_hosts.forced_period()  # #839: tests force the period
    except Exception:
        forced = None
    if forced and forced in document:
        chosen = (forced, document[forced])
    for name, spec in ([] if chosen else document.items()):
        hours = list((spec or {}).get("hours") or [])
        if len(hours) == 2 and _hour_in(moment.hour, int(hours[0]), int(hours[1])):
            chosen = (name, spec)
            break
    if chosen is None:  # a budget file whose windows leave a gap: take the strictest known period
        name = "day" if "day" in document else next(iter(document))
        chosen = (name, document[name])
        _log(f"no budget period covers {moment:%H:%M}; using '{name}'")
    name, spec = chosen
    hours = list(spec.get("hours") or [0, 24])
    defaults = DEFAULT_BUDGET.get(name, DEFAULT_BUDGET["day"])
    total = max(0, int(spec.get("total", defaults["total"])))
    others = max(0, int(spec.get("others", defaults["others"])))
    if strict:
        reserved = _active_reserved_slots(host or current_host(), now=moment, path=reservations_path)
        if reserved:
            others = min(total, max(others, min(total - 1, others + reserved)))
    owner = _owner_record(host or current_host(), moment, modes_file)
    owner_slots, owner_until = owner if owner else (0, None)
    total = max(0, total - owner_slots)  # #621: the owner's slots are not the queue's, strict or not
    return Budget(
        period=str(name),
        hours=(int(hours[0]), int(hours[1])),
        total=total,
        others=others,
        min_free_ram_gb=float(spec.get("min_free_ram_gb", defaults["min_free_ram_gb"])),
        source=source,
        strict_reserve=strict,
        queue_slots=queue_slots,
        merge_suite=max(0, int(spec.get("merge_suite", defaults["merge_suite"]))),
        merge_suite_reserve_gb=float(spec.get("merge_suite_reserve_gb", defaults["merge_suite_reserve_gb"])),
        reserved=owner_slots,
        reserved_until=owner_until,
    )


# -- free memory -------------------------------------------------------------------------------

def available_ram_gb() -> float:
    """Available physical memory in GiB (psutil when installed, else the OS call; no new dependency)."""

    try:
        import psutil  # noqa: PLC0415 -- optional, imported only when the guard runs

        return float(psutil.virtual_memory().available) / (1024 ** 3)
    except Exception:
        pass
    if os.name == "nt":
        import ctypes  # noqa: PLC0415

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return float(status.ullAvailPhys) / (1024 ** 3)
    return float(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / (1024 ** 3)


def total_ram_gb() -> float:
    try:
        import psutil  # noqa: PLC0415

        return float(psutil.virtual_memory().total) / (1024 ** 3)
    except Exception:
        return 0.0


# -- the OS lock -------------------------------------------------------------------------------

class _FileLock:
    """One exclusive OS lock on one file, released by the OS when this process dies.

    The locked byte sits at ``_LOCK_OFFSET``, far past the info line, so any reader can read the
    content of a held file (Windows byte-range locks deny reads of the locked bytes themselves).
    """

    __slots__ = ("path", "_fd")

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def try_acquire(self) -> bool:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(str(self.path), flags)
        try:
            _lock_byte(fd)
        except OSError:
            os.close(fd)
            return False
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        return True

    def write_info(self, payload: Mapping[str, Any]) -> None:
        if self._fd is None:
            return
        line = json.dumps(dict(payload), sort_keys=True).encode("ascii", "backslashreplace")
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, line[:_INFO_WIDTH].ljust(_INFO_WIDTH, b" "))

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock_byte(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass

    @property
    def held(self) -> bool:
        return self._fd is not None


if os.name == "nt":
    import msvcrt

    def _lock_byte(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_byte(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_byte(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_byte(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def read_info(path: Path) -> dict[str, Any]:
    """The info line of a lock file ({} when absent or unreadable)."""

    try:
        raw = path.read_bytes()[:_INFO_WIDTH].decode("ascii", "replace").strip()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _is_held(path: Path) -> bool:
    """True when some live process holds this file's lock. Probing IS the liveness test."""

    probe = _FileLock(path)
    try:
        if probe.try_acquire():
            probe.release()
            return False
    except Exception:
        return True  # cannot even open it: treat as busy rather than hand out a slot twice
    return True


def _command_line() -> str:
    try:
        import psutil  # noqa: PLC0415

        parts = psutil.Process().cmdline()
        if parts:
            return " ".join(str(p) for p in parts)[:_CMD_CHARS]
    except Exception:
        pass
    argv = list(sys.argv) or [sys.executable]
    return " ".join([Path(str(argv[0])).name, *[str(a) for a in argv[1:]]])[:_CMD_CHARS]


# -- the handle --------------------------------------------------------------------------------

@dataclass(slots=True)
class SlotHandle:
    """One held slot, or a no-op handle (``slot is None``) when the mechanism is off or broke."""

    slot: int | None = None
    role: str = ROLE_OTHER
    path: Path | None = None
    waited_seconds: float = 0.0
    reason: str = ""
    _lock: _FileLock | None = field(default=None, repr=False)

    @property
    def held(self) -> bool:
        return self.slot is not None

    def release(self) -> None:
        """Give the slot back. Idempotent; the OS would do it anyway if this process died."""

        lock, self._lock = self._lock, None
        self.slot = None
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass

    def __enter__(self) -> "SlotHandle":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _slot_path(directory: Path, number: int) -> Path:
    return directory / f"pob-slot-{number}.lock"


def _slot_order(budget: Budget, role: str) -> list[int]:
    """Which slots this role may try, in the order it tries them.

    The queue walks DOWN from ``total``, stopping at ``limit_for("queue")`` slots -- ``total``
    unless ``strict_reserve`` is on, in which case it is ``total - others`` (the strict reserve,
    #41) so it never reaches into the range reserved for everyone else, even when those slots are
    idle; everybody else walks UP from 1, capped at ``limit_for(role)``.
    """

    if role == ROLE_QUEUE:
        limit = budget.limit_for(role)
        return list(range(budget.total, budget.total - limit, -1))
    return list(range(1, budget.limit_for(role) + 1))


def busy_slots(directory: Path | None = None, *, budget: Budget | None = None) -> list[dict[str, Any]]:
    """Every slot a live process holds: {"slot", "pid", "role", "job", "cmd", "started", "age_seconds"}.

    Probes the lock, so a file left by a killed process reads as free. ``job`` is the runs job id
    that owns the slot (``JOB_ENV``), or ``None`` for anything the runs daemon did not start -- a
    hand-run ``run_queue.py`` line, another daemon's job, a short ``others``-share call (#82).
    """

    folder = Path(directory) if directory is not None else slot_dir()
    if not folder.is_dir():
        return []
    numbers: set[int] = set()
    if budget is not None:
        numbers.update(range(1, budget.total + 1))
    for path in folder.glob(SLOT_FILE_GLOB):
        try:
            numbers.add(int(path.stem.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    rows: list[dict[str, Any]] = []
    now = time.time()
    for number in sorted(numbers):
        path = _slot_path(folder, number)
        if not path.exists() or not _is_held(path):
            continue
        info = read_info(path)
        rows.append(
            {
                "slot": number,
                "pid": info.get("pid"),
                "role": info.get("role", "?"),
                "priority": info.get("priority", PRIORITY_DEFAULT),
                "job": info.get("job"),
                "cmd": info.get("cmd", ""),
                "started": info.get("started", ""),
                "age_seconds": max(0.0, now - float(info.get("started_epoch") or now)),
            }
        )
    return rows


def waiting(directory: Path | None = None) -> list[dict[str, Any]]:
    """Everyone currently blocked in ``acquire_slot``, read the same way (stale files read as gone)."""

    folder = Path(directory) if directory is not None else slot_dir()
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    now = time.time()
    for path in sorted(folder.glob(WAIT_FILE_GLOB)):
        if not _is_held(path):
            try:
                path.unlink(missing_ok=True)  # a killed waiter; fails harmlessly if still open
            except Exception:
                pass
            continue
        info = read_info(path)
        rows.append(
            {
                "pid": info.get("pid"),
                "role": info.get("role", "?"),
                "priority": info.get("priority", PRIORITY_DEFAULT),
                "cmd": info.get("cmd", ""),
                "reason": info.get("reason", ""),
                "age_seconds": max(0.0, now - float(info.get("started_epoch") or now)),
            }
        )
    return rows


# -- acquiring ---------------------------------------------------------------------------------

def _take(
    directory: Path, budget: Budget, role: str, priority: str = PRIORITY_DEFAULT
) -> tuple[SlotHandle | None, list[dict[str, Any]]]:
    """One pass over this role's slots. Returns (handle or None, the slots that blocked it)."""

    directory.mkdir(parents=True, exist_ok=True)
    blocked: list[dict[str, Any]] = []
    for number in _slot_order(budget, role):
        path = _slot_path(directory, number)
        lock = _FileLock(path)
        if lock.try_acquire():
            now = time.time()
            lock.write_info(
                {
                    "pid": os.getpid(),
                    "role": role,
                    "priority": priority,
                    "job": current_job(),  # the runs job that owns this slot, when there is one (#82)
                    "cmd": _command_line(),
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "started_epoch": now,
                }
            )
            return SlotHandle(slot=number, role=role, path=path, _lock=lock), []
        info = read_info(path)
        blocked.append({"slot": number, "pid": info.get("pid"), "role": info.get("role", "?")})
    return None, blocked


def _open_waiter(directory: Path, role: str, reason: str, priority: str = PRIORITY_DEFAULT) -> _FileLock | None:
    """A lock file that says this process is waiting, so ``machine_load.py`` can show it."""

    try:
        for attempt in range(64):
            path = directory / f"pob-wait-{os.getpid()}-{attempt}.lock"
            lock = _FileLock(path)
            if lock.try_acquire():
                lock.write_info(
                    {
                        "pid": os.getpid(),
                        "role": role,
                        "priority": priority,
                        "cmd": _command_line(),
                        "reason": reason[:_CMD_CHARS],
                        "started": datetime.now().isoformat(timespec="seconds"),
                        "started_epoch": time.time(),
                    }
                )
                return lock
    except Exception:
        pass
    return None


def try_acquire_slot(
    *,
    role: str | None = None,
    priority: str | None = None,
    directory: Path | None = None,
    budget: Budget | None = None,
    budget_file: Path | None = None,
    ram_reader: Callable[[], float] | None = None,
    now: datetime | None = None,
) -> SlotHandle | None:
    """One attempt, no waiting: a held ``SlotHandle`` or ``None``. Raises on a broken machine.

    ``acquire_slot`` is the caller-facing wrapper that never raises; this is the primitive the
    tests and ``machine_load.py`` use.
    """

    if not enabled():
        return SlotHandle(reason="JUNKROAN_POB_SLOTS=off")
    folder = Path(directory) if directory is not None else slot_dir()
    active = budget if budget is not None else load_budget(now=now, path=budget_file)
    chosen_role = (role or current_role()).strip().lower()
    chosen_priority = current_priority() if priority is None else _normalize_priority(priority)
    free_ram = (ram_reader or available_ram_gb)()
    if free_ram < active.min_free_ram_gb:
        return None
    if chosen_role == ROLE_QUEUE and _priority_blocks(folder, chosen_priority):
        return None
    handle, _blocked = _take(folder, active, chosen_role, chosen_priority)
    return handle


def acquire_slot(
    *,
    role: str | None = None,
    priority: str | None = None,
    directory: Path | None = None,
    budget_file: Path | None = None,
    ram_reader: Callable[[], float] | None = None,
    poll_seconds: float = POLL_SECONDS,
    timeout: float | None = None,
    log: Callable[[str], None] | None = None,
) -> SlotHandle:
    """Wait for one machine-wide PoB slot and return it. Always returns; never raises.

    Disabled (``JUNKROAN_POB_SLOTS=off``) or broken slot machinery returns a no-op handle: a
    40-minute build must never die, or block for ever, because of the counter that protects it.
    ``timeout`` is only ever a CALLER's timeout -- the mechanism itself never gives up.
    """

    say = log or _log
    if not enabled():
        return SlotHandle(reason="JUNKROAN_POB_SLOTS=off")
    try:
        folder = Path(directory) if directory is not None else slot_dir()
        folder.mkdir(parents=True, exist_ok=True)
        chosen_role = (role or current_role()).strip().lower()
        chosen_priority = current_priority() if priority is None else _normalize_priority(priority)
        read_ram = ram_reader or available_ram_gb
        started = time.monotonic()
        waiter: _FileLock | None = None
        announced = False
        try:
            while True:
                budget = load_budget(path=budget_file)
                free_ram = read_ram()
                if free_ram < budget.min_free_ram_gb:
                    reason = f"RAM free {free_ram:.1f} GB < {budget.min_free_ram_gb:g} GB"
                elif chosen_role == ROLE_QUEUE and _priority_blocks(folder, chosen_priority):
                    reason = f"a higher-priority '{ROLE_QUEUE}' waiter is ahead of this {chosen_priority}"
                else:
                    handle, blocked = _take(folder, budget, chosen_role, chosen_priority)
                    if handle is not None:
                        handle.waited_seconds = time.monotonic() - started
                        if announced:
                            say(f"got PoB slot {handle.slot} after {handle.waited_seconds:.1f} s")
                        return handle  # the `finally` drops the waiting marker: the wait is over
                    pids = [row["pid"] for row in blocked]
                    reason = f"{len(blocked)}/{budget.limit_for(chosen_role)} in use by pids {pids}"
                if not announced:
                    say(f"waiting for a PoB slot: {reason}")
                    announced = True
                    waiter = _open_waiter(folder, chosen_role, reason, chosen_priority)
                if timeout is not None and time.monotonic() - started >= timeout:
                    say(f"giving up on a PoB slot after {timeout:g} s ({reason}); running without one")
                    return SlotHandle(reason=f"timeout: {reason}")
                time.sleep(poll_seconds)
        finally:
            if waiter is not None:
                path = waiter.path
                waiter.release()
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception as exc:  # the counter must never be the thing that breaks a build
        _log(f"slot machinery failed ({exc!r}); continuing WITHOUT a slot")
        return SlotHandle(reason=f"error: {exc!r}")


def verdict(
    need: int,
    role: str,
    *,
    directory: Path | None = None,
    budget: Budget | None = None,
    ram_reader: Callable[[], float] | None = None,
) -> tuple[bool, str]:
    """"Can I start ``need`` PoB sessions as ``role`` right now?" -> (go, one-line reason)."""

    if role == ROLE_MERGE_SUITE:  # #666: no PoB slot, no lock files; only the cap and the RAM floor
        active = budget if budget is not None else load_budget()
        limit = active.limit_for(role)
        free_ram = (ram_reader or available_ram_gb)()
        problems = []
        if need > limit:
            problems.append(f"need {need} > {limit} '{role}' cap")
        if free_ram < active.min_free_ram_gb:
            problems.append(f"RAM free {free_ram:.1f} GB < {active.min_free_ram_gb:g} GB")
        if problems:
            return False, "WAIT: " + ", ".join(problems)
        return True, f"GO ({limit} of {limit} '{role}' slots free, RAM free {free_ram:.1f} GB)"
    folder = Path(directory) if directory is not None else slot_dir()
    active = budget if budget is not None else load_budget()
    limit = active.limit_for(role)
    used = [row for row in busy_slots(folder, budget=active) if row["slot"] in set(_slot_order(active, role))]
    free = max(0, limit - len(used))
    free_ram = (ram_reader or available_ram_gb)()
    problems: list[str] = []
    if free < need:
        pids = ", ".join(str(row["pid"]) for row in used) or "-"
        problems.append(f"{len(used)} of {limit} '{role}' slots in use (pids {pids})")
    if free_ram < active.min_free_ram_gb:
        problems.append(f"RAM free {free_ram:.1f} GB < {active.min_free_ram_gb:g} GB")
    if problems:
        return False, "WAIT: " + ", ".join(problems)
    return True, f"GO ({free} of {limit} '{role}' slots free, RAM free {free_ram:.1f} GB)"


# -- PC load admission (#898) ------------------------------------------------------------------------

ADMISSION_WINDOW_S = 600
ADMISSION_KEEP_S = 1200
ADMISSION_MIN_SAMPLES = 5
ADMISSION_MAX_AGE_S = 120
_BUSY_SAMPLES_NAME = "pc_busy_cores.jsonl"


def admission_caps(mode: str, cores: int) -> tuple[float, float]:
    """(wait_at, go_under) in busy cores: day 75 % / 8/12, night 11/12 / 10/12 of ``cores``; play always waits."""

    if mode == "night":
        return cores * 11 / 12, cores * 10 / 12
    if mode == "play":
        return 0.0, 0.0
    return cores * 0.75, cores * 8 / 12


def busy_samples_path() -> Path:
    return shared_var_dir() / _BUSY_SAMPLES_NAME


def _parse_busy_rows(target: Path) -> list[tuple[float, float, float | None]]:
    """(t, busy_cores, merge_cores or None) per readable line; a row without merge_cores has None (#1118)."""
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[tuple[float, float, float | None]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
            merge = row.get("merge_cores")
            rows.append((float(row["t"]), float(row["busy_cores"]), None if merge is None else float(merge)))
        except Exception:
            continue
    return rows


def read_busy_samples(path: Path | None = None) -> list[tuple[float, float]]:
    """Whole-PC (t, busy_cores) per sample; the admission reads ``read_admission_samples`` instead (#1118)."""
    target = Path(path) if path is not None else busy_samples_path()
    return [(t, b) for t, b, _ in _parse_busy_rows(target)]


def read_admission_samples(path: Path | None = None) -> list[tuple[float, float]]:
    """(t, effective busy cores) per sample: the whole-PC value minus the merge queue's share, never below 0;
    a row without merge_cores counts whole (#1118)."""
    target = Path(path) if path is not None else busy_samples_path()
    return [
        (t, b if m is None else max(0.0, b - m)) for t, b, m in _parse_busy_rows(target)
    ]


def append_busy_sample(
    now: float,
    busy_cores: float,
    path: Path | None = None,
    keep_s: float = ADMISSION_KEEP_S,
    *,
    merge_cores: float | None = None,
) -> None:
    """Append one whole-PC sample (with ``merge_cores`` when the merge queue's share is read, #1118), then rewrite
    the file without samples older than ``keep_s`` (atomic)."""

    target = Path(path) if path is not None else busy_samples_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _parse_busy_rows(target) if r[0] >= now - keep_s]
    rows.append((float(now), float(busy_cores), None if merge_cores is None else float(merge_cores)))
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    tmp.write_text("".join(_busy_line(t, b, m) for t, b, m in rows), encoding="utf-8")
    os.replace(tmp, target)


def _busy_line(t: float, busy: float, merge: float | None) -> str:
    row: dict[str, float] = {"t": t, "busy_cores": busy}
    if merge is not None:
        row["merge_cores"] = merge
    return json.dumps(row) + "\n"


@dataclass(frozen=True)
class Admission:
    go: bool
    reason: str
    mean: float | None
    cap: float
    mode: str
    samples: int
    waited_s: float = 0.0
    hold_cap_s: float | None = None

    def line(self) -> str:
        from junkroan.report_format import human_duration

        window = human_duration(ADMISSION_WINDOW_S)
        head = "go" if self.go else "wait"
        if self.reason == "hold cap" and self.mean is not None:
            return (f"go: hold cap, waited {human_duration(self.waited_s)} (cap {human_duration(self.hold_cap_s or 0)}), "
                    f"PC busy {self.mean:.1f} cores over the last {window} ({self.mode}, line {self.cap:.1f})")
        if self.mean is None:
            return f"{head}: {self.reason} ({self.mode})"
        return f"{head}: PC busy {self.mean:.1f} cores over the last {window} ({self.mode}, {self.reason}, line {self.cap:.1f})"


def load_admission(
    samples: Iterable[tuple[float, float]],
    now: float,
    mode: str,
    previous_wait: bool | None,
    cores: int,
    waited_s: float = 0.0,
    hold_cap_s: float | None = None,
) -> Admission:
    """``waited_s``: how long the caller has been answered wait without a break; once it reaches ``hold_cap_s``
    a wait of day or night becomes go, reason `hold cap` (#907). Play mode never caps."""
    adm = _load_admission(samples, now, mode, previous_wait, cores)
    if adm.go or mode == "play" or hold_cap_s is None or adm.mean is None or waited_s < hold_cap_s:
        return adm
    return Admission(True, "hold cap", adm.mean, adm.cap, mode, adm.samples, waited_s, hold_cap_s)


def _load_admission(
    samples: Iterable[tuple[float, float]],
    now: float,
    mode: str,
    previous_wait: bool | None,
    cores: int,
) -> Admission:
    wait_at, go_under = admission_caps(mode, cores)
    if mode == "play":
        return Admission(False, "play mode", None, wait_at, mode, 0)
    window = [(t, b) for t, b in samples if now - ADMISSION_WINDOW_S <= t <= now]
    if len(window) < ADMISSION_MIN_SAMPLES or now - max(t for t, _ in window) > ADMISSION_MAX_AGE_S:
        return Admission(True, "no reading", None, wait_at, mode, len(window))
    mean = sum(b for _, b in window) / len(window)
    n = len(window)
    if mean >= wait_at:
        return Admission(False, "busy", mean, wait_at, mode, n)
    if mean < go_under:
        return Admission(True, "back under", mean, wait_at, mode, n)
    if previous_wait:
        return Admission(False, "between lines (stays wait)", mean, wait_at, mode, n)
    return Admission(True, "between lines (stays go)", mean, wait_at, mode, n)


def _admission_mode() -> str:
    from junkroan.runs import hosts as runs_hosts

    forced = runs_hosts.forced_period()
    if forced:
        return forced
    try:
        if runs_hosts.current_mode(current_host(), local=True) == "play":
            return "play"
    except Exception:
        pass
    return load_budget().period


def admission_now(
    *,
    now: float | None = None,
    samples: Iterable[tuple[float, float]] | None = None,
    previous_wait: bool | None = None,
    cores: int | None = None,
    mode: str | None = None,
    waited_s: float = 0.0,
    hold_cap_s: float | None = None,
) -> Admission:
    return load_admission(
        read_admission_samples() if samples is None else samples,
        time.time() if now is None else now,
        mode if mode is not None else _admission_mode(),
        previous_wait,
        cores if cores is not None else (os.cpu_count() or 1),
        waited_s,
        hold_cap_s,
    )


__all__ = [
    "ADMISSION_KEEP_S",
    "ADMISSION_MAX_AGE_S",
    "ADMISSION_MIN_SAMPLES",
    "ADMISSION_WINDOW_S",
    "Admission",
    "admission_caps",
    "admission_now",
    "append_busy_sample",
    "busy_samples_path",
    "load_admission",
    "read_admission_samples",
    "read_busy_samples",
    "DEFAULT_BUDGET",
    "POLL_SECONDS",
    "PRIORITY_DEFAULT",
    "ROLE_MERGE_SUITE",
    "ROLE_OTHER",
    "ROLE_QUEUE",
    "Budget",
    "SlotHandle",
    "acquire_slot",
    "available_ram_gb",
    "budget_path",
    "busy_slots",
    "current_host",
    "current_job",
    "current_owner_key",
    "current_priority",
    "current_role",
    "enabled",
    "owner_key",
    "load_budget",
    "read_info",
    "read_reservations",
    "reservations_file",
    "role_source",
    "shared_var_dir",
    "slot_dir",
    "total_ram_gb",
    "try_acquire_slot",
    "verdict",
    "waiting",
]
