"""The runs daemon: start queued jobs by priority, hand finished runs back to their issue (#48).

The part of the keymaster that replaces ``scripts/run_queue.py``'s serial loop. Two differences
from that loop, and only two, are deliberate; everything else about starting a job (the child's
environment, the pinned-commit snapshot with its directory junctions, the ``.out`` naming, the
benchmark archival) is ``run_queue.py``'s own code, called by import through :class:`QueueBackend`
-- nothing here reimplements snapshots or junctions (CLAUDE.md "Worktrees hold junctions").

    1. Several jobs run at once. ``run_queue.py`` blocks in ``subprocess.run`` for one line at a
       time; the daemon starts a child per job and keeps as many running as the host's queue share
       has room for, counting each job's ``workers`` (PoB sessions) rather than jobs.
    2. A finished job is handed back to its GitHub issue (one comment + the ``ready-for-agent``
       label) so ORCH never waits on a 40-minute PoB run, and every end is announced on
       ``artifacts/runs/events.jsonl``, which ``runs watch`` tails.

Room is ``Budget.limit_for("queue")`` (``slot_budget``, so the strict reserve of #41 applies) minus
what is busy on the WHOLE host, not only what this daemon started (#82): every PoB slot the
semaphore reports busy counts -- a hand-run ``run_queue.py`` line, another daemon's job, a short
``others``-share call -- so the daemon starts at once beside a run it did not start and still never
puts 10 PoB workers on a 7-slot budget. See :meth:`Daemon.room` for the arithmetic (own jobs are
counted once, at ``max(declared workers, slots actually held)``). Graceful priority stays in
``slot_budget`` (#37): the daemon only lets a strictly higher-priority job START while
lower-priority work holds slots (up to the budget's ``total``, never beyond); which of them then
gets the next FREED slot, and the fact that nothing is ever killed, is the slot semaphore's business.

Fillers (issues #132, #751): on a wholly empty machine in the normal mode the daemon submits one filler job
per row the week still lacks (:meth:`Daemon.filler_pass`, ``junkroan.runs.weekly_fillers``); any job that is
not a filler, a mode change away from ``normal`` or spike step 2 kills every filler of the host
(:meth:`Daemon.preempt_fillers_pass`); a restart adopts them. :meth:`Daemon.sweep_filler_exports` keeps a
filler's PoB exports out of the folders the owner reads.

Every collaborator that touches the world -- the launcher, ``gh``, ``run_queue.py``, the clock --
is injected, so the tests run the whole loop with no PoB, no ``gh`` and no process launch.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol

from junkroan.pob import slot_budget
from junkroan.runs.bounded import run_bounded
from junkroan.runs.pass_guard import GUARD, SLOW_PASS_SECONDS, STEP_LINE_SECONDS
from junkroan.report_format import human_duration
from junkroan.runs import close_set as close_set_mod
from junkroan.runs import fillers as fillers_mod
from junkroan.runs import handback_gate as gate_mod
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import rebalance as rebalance_mod
from junkroan.runs import row_sync as row_sync_mod
from junkroan.runs import gate_pull as gate_pull_mod  # #1166
from junkroan.runs import load_groups as load_groups_mod
from junkroan.runs import load_record as load_record_mod
from junkroan.runs import merge_share
from junkroan.runs import remote_store as remote_store_mod
from junkroan.runs import run_issue as run_issue_mod
from junkroan.runs import spike as spike_mod
from junkroan.runs import stopper as stopper_mod
from junkroan.runs import ticket_closed as ticket_closed_mod
from junkroan.runs import store as store_mod
from junkroan.runs import untracked as untracked_mod
from junkroan.runs import weekly_cut
from junkroan.runs import weekly_fillers
from junkroan.runs import build_count
from junkroan.runs import yield_plan as yield_mod
from junkroan.runs.store import CLASS_FILLER, IllegalTransition, Job, Store

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Labels of a Run issue (#164): open = not reviewed; no label of its own.
RUN_ISSUE_LABELS = ("needs-triage", "area:builds")
RUN_QUEUE_SCRIPT = PROJECT_ROOT / "scripts" / "run_queue.py"

#: The label a finished job's issue gets back, so the lead's `ready-for-agent` list shows it.
HANDBACK_LABEL = "ready-for-agent"

#: A comment whose first line starts with this is the brain's pause of an issue (#654): while it is the
#: newest comment that is not a hand-back, a hand-back posts its result but leaves the label off.
PAUSE_PREFIX = "**PAUSED"
#: First line of every hand-back comment (issue #50): how a dispatcher recognizes one without
#: parsing its text -- an issue whose LATEST comment starts with this line just got its run back.
RUNS_DAEMON_MARKER = "<!-- runs-daemon result -->"
#: One tick of the loop, at most (requirement 1: "<= 10 s").
TICK_SECONDS = 10.0
#: #598: at the latest this long after a HEAD move was first seen the daemon restarts, jobs running or not.
RESTART_MAX_WAIT_SECONDS = 900
#: #406: one load snapshot takes ~7 s under load (measured 2026-10-01), so the spike ladder samples
#: at most once per this many seconds, not every tick.
SPIKE_SAMPLE_SECONDS = 30.0
#: #768: how often the load thread looks at its schedule at most.
LOAD_THREAD_POLL_SECONDS = 2.0
#: Why a job ends when the daemon comes back to a `running` job whose process is gone.
LOST_PROCESS_REASON = "lost pid"  # the reason is f"{LOST_PROCESS_REASON} {pid}"


def lost_pid_reason(pid: object) -> str:
    return f"{LOST_PROCESS_REASON} {pid}"
#: The last N lines of a job's `.out` file quoted in the issue comment.
OUT_TAIL_LINES = 20
MISSING_SCRIPT_SECONDS = 60.0
#: `Daemon(handback=...)` modes (issue #118): `local` posts through `gh` itself (unchanged
#: default); `remote` (the laptop, which has no `gh`) only stores the rendered body on the job.
HANDBACK_MODES = ("local", "remote")
#: How often a daemon reads every OTHER host's store to post its stored hand-backs (requirement 2):
#: "at most once a minute", never every 10 s tick.
REMOTE_HANDBACK_SECONDS = 60.0

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

#: A job of this many workers or more is a "heavy job" (`GLOSSARY.md`): two never run on one host
#: at once (#117), own or foreign, because every PoB job's numbers depend on wall clock and a
#: second heavy job changes both runs' results, not only their speed.
HEAVY_WORKERS = 5

#: #960: the commands that READ the job's yield file (`JUNKROAN_YIELD_FILE`) and so can be started at a
#: smaller count than they ask for and grown later. `scripts/benchmark.py` does (`run_pool` re-reads the file
#: before every build); #958: `scripts/replay_bench.py` and `scripts/search.py` do too (`limited_completions`
#: in `yield_plan.py` re-reads it before every submission; a build in flight runs to its end).
YIELD_READER_COMMANDS: tuple[str, ...] = ("scripts/benchmark.py", "scripts/replay_bench.py", "scripts/search.py")


def reads_yield_file(cmd: str) -> bool:
    """True when ``cmd`` runs a script that re-reads its yield file (:data:`YIELD_READER_COMMANDS`)."""

    text = str(cmd or "").replace(chr(92), "/")
    return any(pattern in text for pattern in YIELD_READER_COMMANDS)

#: #642: at most one gate-copy attempt start per this many seconds (10 min).
GATE_SYNC_SECONDS = 600.0
#: #1000: every outside call of a pass has a limit (the rule of `pass_guard`: a dead service costs one wait per pass).
#: The early warning's `scripts/early_warning.py --post` (one per warn row that ends rc 0).
EARLY_WARNING_SECONDS = 60.0
#: #1000 row 2: a gate copy (`scp -r`) still running after this long is killed (tree) and retried on a later tick.
GATE_COPY_LIMIT_SECONDS = 1800.0
#: #1000 row 2: the size of a gate dir (log line only) is walked at most this long and over this many files;
#: over either cap the size is shown as unknown and the copy goes on unchanged.
GATE_SIZE_WALK_SECONDS = 5.0
GATE_SIZE_WALK_MAX_ENTRIES = 20000
#: #1000 row 3: one `scp -r` of a replay/benchmark dir in `copy_dir_to_host` (called from `Rebalancer.step`).
COPY_DIR_SECONDS = 60.0
#: #1000 row 4: the weekly cut's `git fetch origin`; its own key, a dead origin is not a dead local git.
GIT_FETCH_SECONDS = 45.0
GIT_FETCH_KEY = "git-fetch"
#: #1000 row 4: the local git reads (`_host_behind`, `_origin_main`, `_host_head`) share one key, so a dead
#: git costs one `GIT_READ_SECONDS` wait per pass, not one per queued job.
GIT_READ_SECONDS = 30.0
GIT_READ_KEY = "git"
#: A filler is submitted at this priority and ordered UNDER it (`store.next_job`, class `filler`).
FILLER_PRIORITY = "P2"
#: The weekly cut is looked for on origin at most this often (one bounded `git fetch`), never on every tick.
FILLER_REFRESH_SECONDS = 300.0

#: A daemon's status file (below) is stale once its OWN last tick is older than this multiple of
#: its recorded ``tick_seconds`` -- or this floor, whichever is larger (requirement 2).
STALE_MULTIPLIER = 3.0
STALE_FLOOR_SECONDS = 180.0  # 3 min


def _log(message: str) -> None:
    try:
        sys.stderr.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} runs-daemon: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


@contextmanager
def _timed(name: str) -> Iterator[None]:
    """#998 row 1: time one step of `Daemon.tick` on the pass guard's clock, also when the step raises."""

    started = GUARD.now()
    try:
        yield
    finally:
        GUARD.step(name, started)


def _log_slow_pass() -> None:
    """#998 row 2: a pass longer than `SLOW_PASS_SECONDS` writes ONE line: its length, its slowest step, and
    every step over `STEP_LINE_SECONDS` in step order (so three ~21 s steps of a 64 s pass add up on the line)."""

    seconds = GUARD.pass_seconds()
    if seconds <= SLOW_PASS_SECONDS:
        return
    slowest = GUARD.slowest()
    if not slowest:
        _log(f"slow pass {human_duration(seconds)}")
        return
    over = ", ".join(f"{name} {human_duration(dur)}" for name, dur in GUARD.steps_over(STEP_LINE_SECONDS)) or "none"
    _log(f"slow pass {human_duration(seconds)} (slowest step: {slowest[0]} {human_duration(slowest[1])}; "
         f"steps over {human_duration(STEP_LINE_SECONDS)}: {over})")


# -- the daemon status file (issue #73) -----------------------------------------------------------
#
# `artifacts/runs/daemon-<host>.json`: written at start and after every tick (`Daemon.run`), and
# read once at start by `cmd_daemon` (`scripts/runs.py`) to decide whether a live daemon already
# owns this host before this one ticks at all -- the single-instance guard.

def _replace_retrying(tmp: Path, path: Path, *, attempts: int = 100, pause: float = 0.02) -> None:
    """``os.replace`` that survives a reader holding ``path`` open for a moment.

    On Windows, replacing a file another process (the monitor, a test) has open raises
    ``PermissionError``; the same fix ``scripts/benchmark.py``'s own ``_replace_retrying`` uses for
    ``results.json`` (commit 61ef9ad, issue #24) -- copied here rather than imported because
    ``scripts/`` is not an importable package (see ``run_queue()`` above).
    """

    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause)


def stale_after(tick_seconds: float) -> float:
    """How old a ``last_tick`` may be before a daemon counts as no longer live (requirement 2)."""

    try:
        seconds = float(tick_seconds)
    except (TypeError, ValueError):
        seconds = TICK_SECONDS
    return max(STALE_MULTIPLIER * seconds, STALE_FLOOR_SECONDS)


def daemon_status_path(host: str) -> Path:
    return runs_hosts.daemon_status_path(host)


def read_daemon_status(path: Path) -> dict[str, Any] | None:
    """The status dict at ``path``, or ``None`` when it is absent, empty, or not valid JSON."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_daemon_status(
    path: Path, status: Mapping[str, Any], *, log: Callable[[str], None] = _log,
) -> None:
    """Atomically write ``status`` (temp file + ``os.replace``, retried); never raises.

    A failing write is logged and swallowed -- requirement 1: "never kills the tick".
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(dict(status), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        _replace_retrying(tmp, path)
    except Exception as exc:
        log(f"could not write the daemon status file {path} ({exc!r})")


def _stood(start_epoch: float, end_epoch: float) -> float:
    """Seconds of [start, end] the machine stood in play (#779 rule 5); 0.0 when it cannot be told."""
    try:
        from tools.agentops.machine_mode import stood_between
    except ImportError:
        return 0.0
    return stood_between(start_epoch, end_epoch)


def status_liveness(
    status: Mapping[str, Any] | None, *, now: datetime, pid_alive: Callable[[int], bool],
) -> tuple[bool, float | None]:
    """Whether ``status`` (as :func:`read_daemon_status` returns it) describes a daemon still live.

    ``(live, age_seconds)`` -- live means the pid still runs AND the last tick is younger than
    :func:`stale_after` of the status's OWN recorded ``tick_seconds`` (requirement 2).
    ``age_seconds`` is ``None`` when there is nothing to measure (no status, no readable pid or
    ``last_tick``).
    """

    if not status:
        return False, None
    pid = status.get("pid")
    if not pid:
        return False, None
    try:
        alive = pid_alive(int(pid))
    except (TypeError, ValueError):
        return False, None
    if not alive:
        return False, None
    last_tick = status.get("last_tick")
    if not last_tick:
        return False, None
    try:
        last_dt = datetime.fromisoformat(str(last_tick))
    except ValueError:
        return False, None
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    age = (now - last_dt).total_seconds()
    age = max(0.0, age - _stood(last_dt.timestamp(), now.timestamp()))  # #779: play time is not a hung tick
    return age < stale_after(status.get("tick_seconds", TICK_SECONDS)), age


# -- scripts/run_queue.py, by import ------------------------------------------------------------

_run_queue_module: Any | None = None


def run_queue() -> Any:
    """``scripts/run_queue.py`` as a module.

    Loaded from its path because ``scripts/`` is not an importable package. Importing it has no
    side effects (its constants and functions only; ``signal.signal`` lives inside ``main``), and
    this is the ONLY way this module reaches snapshot and junction handling -- those functions are
    never copied here.
    """

    global _run_queue_module
    if _run_queue_module is None:
        spec = importlib.util.spec_from_file_location("junkroan_run_queue", RUN_QUEUE_SCRIPT)
        if spec is None or spec.loader is None:  # pragma: no cover - a checkout without scripts/
            raise RuntimeError(f"cannot load {RUN_QUEUE_SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _run_queue_module = module
    return _run_queue_module


class QueueBackend:
    """Everything the daemon borrows from ``run_queue.py``, in one seam the tests replace.

    ``wants_snapshot`` / ``make_snapshot`` / ``drop_snapshot`` / ``out_name`` /
    ``benchmark_run_dir`` / ``archive_benchmark_run`` / ``is_benchmark_command`` / ``pid_alive``
    are called, not copied: a job started by the daemon lands in the same snapshot, behind the same
    junctions, with the same ``.out`` name and the same archive as the same line in ``queue.txt``.
    """

    def runs_dir(self) -> Path:
        return run_queue().RUNS

    def out_name(self, cmd: str, now: datetime, runs_dir: Path) -> str:
        return run_queue().out_name(cmd, now, runs_dir)

    def wants_snapshot(self, cmd: str) -> bool:
        return run_queue().wants_snapshot(cmd)

    def make_snapshot(self, name: str, pin: str) -> tuple[Path, str] | None:
        return run_queue().make_snapshot(name, pin)

    def drop_pin_ref(self, pin: str) -> str:
        """Delete the pin's travelling ref from origin and this checkout (#756 rule 2); a log message."""
        from junkroan.runs import pin_ref
        return pin_ref.drop_pin(PROJECT_ROOT, pin)

    def sweep_pin_refs(self, held_pins: list[str], failed: set[str]) -> list[str]:
        """Delete pin refs on origin that no held pin names (#756 rule 2, the PC's sweep); log lines."""
        from junkroan.runs import pin_ref
        return pin_ref.sweep(PROJECT_ROOT, held_pins, failed)

    def snapshot_failure(self) -> str | None:
        """Why the last ``make_snapshot`` returned None (#756)."""
        return getattr(run_queue(), "LAST_SNAPSHOT_FAILURE", None)

    def drop_snapshot(self, snapshot: Path) -> None:
        run_queue().drop_snapshot(snapshot)

    def save_snapshot_diff(self, snapshot: Path, job_id: str) -> Path | None:
        return run_queue().save_snapshot_diff(snapshot, job_id)

    def pid_alive(self, pid: int) -> bool:
        return run_queue().pid_alive(pid)

    def find_run_dir(self, cmd: str, out: Path, started_at: float) -> Path | None:
        """The output directory the finished command wrote, when it is a benchmark."""

        module = run_queue()
        if not module.is_benchmark_command(cmd):
            return None
        return module.benchmark_run_dir(cmd, out, started_at)

    def archive(self, cmd: str, run_dir: Path | None, out: Path) -> int:
        if not run_queue().is_benchmark_command(cmd):
            return 0
        return run_queue().archive_benchmark_run(run_dir, out)


# -- launching a child ---------------------------------------------------------------------------

class Launched(Protocol):
    """A started child: its pid, whether it has exited, and the handles it holds."""

    pid: int

    def poll(self) -> int | None: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class _Child:
    pid: int
    _process: Any
    _out_handle: Any

    def poll(self) -> int | None:
        return self._process.poll()

    def close(self) -> None:
        try:
            self._out_handle.close()
        except Exception:
            pass


# CREATE_NO_WINDOW: a job never allocates a visible console of its own, whatever console (or none:
# a DETACHED_PROCESS parent) its daemon has (#490). Output goes to the job's file; a stop is taskkill.
_JOB_CREATIONFLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProcessLauncher:
    """The real launcher: one shell child per job, its own process group, output to the job's file.

    ``creationflags=CREATE_NEW_PROCESS_GROUP`` for the same reason ``run_queue.py`` uses it: a
    console Ctrl+C in a WMI-launched chain killed the runner, the benchmark and its workers at once
    (2026-09-18), and the daemon is launched detached in exactly that way.
    """

    def start(self, cmd: str | list[str], *, cwd: Path, out: Path, env: dict[str, str]) -> Launched:
        # a list is a job's own argv (#203): no shell, quotes survive; a str is a legacy `cmd` line
        out.parent.mkdir(parents=True, exist_ok=True)
        handle = out.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(  # noqa: S602 - a queue line is a shell command by design
                cmd,
                shell=isinstance(cmd, str),
                cwd=str(cwd),
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
                # by day in a BelowNormal mode (#839) the job and every descendant start BELOW_NORMAL
                creationflags=_JOB_CREATIONFLAGS | runs_hosts.day_priority_flag(),
            )
        except Exception:
            handle.close()
            raise
        return _Child(pid=process.pid, _process=process, _out_handle=handle)

    def alive(self, pid: int) -> bool:
        return QueueBackend().pid_alive(pid)

    def exit_watch(self, pid: int):
        """A handle on a live pid that later yields its exit code (#598); None where unsupported."""

        from junkroan.runs import pid_exit

        return pid_exit.open_exit_watch(pid)


# -- gh ------------------------------------------------------------------------------------------

def live_jobs_of_issue(jobs: Iterable[Job], issue: int | None, *, exclude_id: str | None = None) -> list[Job]:
    """The jobs of ``issue`` (own or refused-identical, #468) still ``queued`` (held ones included) or ``running``.

    The one check behind "the issue's last job gives the label" (#405) and ``runs.py relabel`` (#500).
    """

    if issue is None:
        return []
    return [j for j in jobs if j.id != exclude_id and int(issue) in j.all_issues
            and j.state in ("queued", "running")]


#: #998: one ``gh`` call waits at most this long; the pass guard (``pass_guard.GUARD``) keeps a
#: dead ``gh`` to one such wait per pass, whatever the number of issues or jobs.
GH_TIMEOUT_CAP_SECONDS = 45.0
GH_GUARD_KEY = "gh"


class GhCli:
    """``gh issue comment`` / ``gh issue edit --add-label``, each a bool: did it go through.

    A False is never fatal: the daemon leaves the job's ``posted`` flag unset and tries again on
    the next tick (requirement 3).
    """

    def __init__(self, cwd: Path | None = None, timeout: float = GH_TIMEOUT_CAP_SECONDS) -> None:
        self.cwd = Path(cwd) if cwd else PROJECT_ROOT
        self.timeout = timeout

    def _call(self, args: list[str], *, timeout: float | None = None, **kwargs: Any) -> subprocess.CompletedProcess | None:
        """One bounded ``gh <args>`` (#998). ``None`` when ``gh`` is down in this pass (not called) or did not answer.

        A nonzero return code is NOT a failure here: the caller reads it. A timeout or any other
        exception marks ``gh`` down for the rest of the pass (one log line).
        """

        if GUARD.down(GH_GUARD_KEY):
            return None
        cap = min(self.timeout, GH_TIMEOUT_CAP_SECONDS, timeout if timeout is not None else GH_TIMEOUT_CAP_SECONDS)
        try:
            return run_bounded(["gh", *args], cwd=str(self.cwd), timeout=cap, **kwargs)
        except Exception as exc:
            if GUARD.mark_down(GH_GUARD_KEY, repr(exc)):
                _log(f"gh {' '.join(args[:3])} did not answer ({exc!r}); gh is skipped for the rest of this pass")
            return None

    def _run(self, args: list[str], stdin: str | None = None) -> bool:
        result = self._call(args, input=stdin, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        if result is None:
            return False
        if result.returncode != 0:
            _log(f"gh {' '.join(args[:3])} rc {result.returncode}: {(result.stderr or '').strip()[:200]}")
            return False
        return True

    def comment(self, issue: int, body: str) -> bool:
        return self._run(["issue", "comment", str(issue), "--body-file", "-"], stdin=body)

    def add_label(self, issue: int, label: str) -> bool:
        return self._run(["issue", "edit", str(issue), "--add-label", label])

    def issue_open(self, issue: int) -> bool | None:
        """Whether ``issue`` is open (#803); ``None`` when ``gh`` could not answer."""

        result = self._call(["issue", "view", str(issue), "--json", "state"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result is None or result.returncode != 0:
            return None
        try:
            return str(json.loads(result.stdout).get("state") or "").upper() != "CLOSED"
        except Exception:
            return None

    def create_issue(self, title: str, body: str, labels: list[str]) -> int | None:
        """``gh issue create``; the new issue's number, ``None`` when it did not go through (#164)."""

        args = ["issue", "create", "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        result = self._call(args, input=body, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        if result is None:
            return None
        if result.returncode != 0:
            _log(f"gh issue create rc {result.returncode}: {(result.stderr or '').strip()[:200]}")
            return None
        match = re.search(r"/issues/(\d+)\s*$", (result.stdout or "").strip())
        return int(match.group(1)) if match else None

    def add_sub_issue(self, parent: int, child: int) -> bool:
        """Attach ``child`` as a native sub-issue of ``parent`` (the child's database id first)."""

        got = self._call(["api", "repos/{owner}/{repo}/issues/%d" % child, "--jq", ".id"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
        if got is None:
            return False
        child_id = (got.stdout or "").strip()
        if got.returncode != 0 or not child_id.isdigit():
            _log(f"gh api issue id rc {got.returncode}: {(got.stderr or '').strip()[:200]}")
            return False
        return self._run(["api", "-X", "POST", "repos/{owner}/{repo}/issues/%d/sub_issues" % parent,
                          "-F", f"sub_issue_id={child_id}"])

    def issue_state(self, issue: int) -> str | None:
        """``OPEN`` / ``CLOSED`` of ``issue`` (one bounded ``gh issue view``); ``None`` when ``gh`` could not answer (#686).

        Silent: the caller logs the one line for a failed pass.
        """

        result = self._call(["issue", "view", str(issue), "--json", "state"], timeout=30.0,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result is None or result.returncode != 0:
            return None
        try:
            return str(json.loads(result.stdout).get("state") or "").upper() or None
        except Exception:
            return None

    def existing_comments(self, issue: int) -> list[str] | None:
        """Every existing comment body on ``issue``; ``None`` when ``gh`` could not answer.

        Used only by the remote hand-back pass (#118 requirement 2) to check whether a comment
        already went out before a crash between the post and the mark -- a ``None`` here means
        "unknown", not "no comments", so the caller still tries to post rather than getting stuck.
        """

        result = self._call(["issue", "view", str(issue), "--json", "comments"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result is None:
            return None
        if result.returncode != 0:
            _log(f"gh issue view {issue} rc {result.returncode}: {(result.stderr or '').strip()[:200]}")
            return None
        try:
            data = json.loads(result.stdout)
        except Exception as exc:
            _log(f"gh issue view {issue}: could not parse its comments ({exc!r})")
            return None
        return [str(c.get("body") or "") for c in data.get("comments", [])]


def _remote_ticket_stop_over_ssh(host_cfg: Mapping[str, Any], host: str, job_id: str, action: str, reason: str) -> bool:
    """``runs.py stop|cancel <job> --local --reason ...`` ON the other host (its own store, #686)."""

    q = runs_hosts.quote_ps_arg
    parts = ["python", "scripts/runs.py", action, job_id, "--local", "--reason", reason]
    result = runs_hosts.write_over_ssh(dict(host_cfg), f"& {' '.join(q(p) for p in parts)}",
                                       repo_path=runs_hosts.daemon_repo_path(host_cfg), host=host)
    return getattr(result, "returncode", 1) == 0


# -- the daemon ----------------------------------------------------------------------------------

@dataclass(slots=True)
class _Active:
    """One job the daemon believes is running."""

    job_id: str
    workers: int
    priority: str
    cmd: str
    out: Path
    pid: int
    started_at: float
    child: Launched | None = None          # None for a job adopted from a dead daemon
    snapshot: Path | None = None
    watch: Any = None                      # ExitWatch on an adopted job's pid (#598)
    # #960: a job started at the RAM bound. `workers` is what it is ALLOWED now (what the budget counts),
    # `ram_give` the part of its `asked` count the yield file still withholds; `ram_grown_*` is the last
    # growth, whose workers have not grown into the free-RAM reading yet.
    asked: int = 0
    ram_give: int = 0
    ram_grown_at: float = 0.0
    ram_grown_n: int = 0


@dataclass(slots=True)
class TickReport:
    """What one tick did, for the log and for the tests."""

    started: list[str] = field(default_factory=list)
    ended: list[str] = field(default_factory=list)
    handed_back: list[str] = field(default_factory=list)
    #: Job ids from another host whose stored hand-back this tick posted (#118 requirement 2).
    remote_handed_back: list[str] = field(default_factory=list)
    #: Filler jobs this tick submitted (issues #132, #751).
    fillers: list[str] = field(default_factory=list)
    room: int = 0
    #: True when this tick started the replacement daemon (#489): the loop must end.
    restarting: bool = False


def _laptop_dir_paths(cfg: Mapping[str, Any], rel: str) -> tuple[str, str, str]:
    """(parent, final, partial) of ``artifacts/<rel>`` under the other host's daemon checkout (#642, #701)."""

    parts = rel.split("/")
    parent = "\\".join([str(runs_hosts.daemon_repo_path(cfg)), "artifacts", *parts[:-1]])
    return parent, parent + "\\" + parts[-1], parent + "\\" + parts[-1] + ".partial"


def _prep_script(parent: str, partial: str) -> str:
    return (f"New-Item -ItemType Directory -Force -Path '{parent}' | Out-Null; "
            f"if (Test-Path -LiteralPath '{partial}') {{ Remove-Item -LiteralPath '{partial}' -Recurse -Force }}")


def _rename_script(final: str, partial: str, name: str) -> str:
    return (f"if (Test-Path -LiteralPath '{final}') {{ Remove-Item -LiteralPath '{final}' -Recurse -Force }}; "
            f"Rename-Item -LiteralPath '{partial}' -NewName '{name}'")


FILLER_KEY_PREFIX = "filler-key:"


def _missing_stems(folder: Path) -> list[str]:
    """`benchmark.py --resume <folder> --missing`, one stem per line; any failure = [] (no cut filler)."""

    try:
        res = subprocess.run([sys.executable, "scripts/benchmark.py", "--resume", str(folder), "--missing"],
                             cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()] if res.returncode == 0 else []


MISSING_CACHE_SECONDS = 60.0


def _run_early_warning(week: str) -> None:
    """`python scripts/early_warning.py --week <Monday as YYYYmmdd> --post` (#749); no window."""

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run([sys.executable, "scripts/early_warning.py", "--week", week, "--post"],
                   cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=EARLY_WARNING_SECONDS,
                   creationflags=flags)


def _guarded_git(argv: list[str], *, key: str, timeout: float, **kwargs: Any) -> subprocess.CompletedProcess | None:
    """#1000: one local git call under the pass guard. ``None`` when ``key`` is down in this pass (not called)
    or the call raised (a timeout too). The first failure of a pass logs one line and marks ``key`` down; a
    nonzero return code is not a failure here (the caller reads it)."""

    if GUARD.down(key):
        return None
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kwargs)
    except Exception as exc:
        if GUARD.mark_down(key, repr(exc)):
            _log(f"git {argv[3] if len(argv) > 3 else ''} did not answer ({exc!r}); "
                 "git calls of this key are skipped for the rest of this pass")
        return None


def _tree_size(root: Path, *, seconds: float, max_entries: int, clock: Callable[[], float]) -> int | None:
    """#1000 row 2: total bytes of the files under ``root``; ``None`` when the walk runs over ``seconds`` or
    over ``max_entries`` files (the caller then shows the size as unknown; the copy is not affected)."""

    started = clock()
    total = 0
    seen = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            seen += 1
            if seen > max_entries or clock() - started > seconds:
                return None
            total += (Path(dirpath) / name).stat().st_size
    return total


def _origin_main(repo: Path) -> str:
    res = _guarded_git(["git", "-C", str(repo), "rev-parse", "origin/main"], key=GIT_READ_KEY,
                       timeout=GIT_READ_SECONDS)
    if res is None:
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


class Daemon:
    """The loop: reap finished jobs, retry unposted hand-backs, start what the host has room for."""

    def __init__(
        self,
        store: Store,
        host: str = "pc",
        *,
        launcher: Any | None = None,
        gh: Any | None = None,
        queue: QueueBackend | None = None,
        budget_loader: Callable[[], slot_budget.Budget] | None = None,
        slot_lister: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
        events_file: Path | None = None,
        runs_dir: Path | None = None,
        label: str = HANDBACK_LABEL,
        archive: bool = True,
        snapshots: bool = True,
        clock: Callable[[], float] = time.time,
        timestamp: Callable[[], datetime] = datetime.now,
        log: Callable[[str], None] = _log,
        anomaly_guard: Any | None = None,
        revert_modes: Callable[[], Any] | None = None,
        status_file: Path | None = None,
        utcnow: Callable[[], datetime] | None = None,
        parent_pid: Callable[[int], int | None] | None = None,
        handback: str = "local",
        hosts_config: Mapping[str, Any] | None = None,
        remote_store_reader: Callable[[Mapping[str, Any]], Iterable[Job]] | None = None,
        remote_mark_posted: Callable[[Mapping[str, Any], str, str], bool] | None = None,
        remote_pass_seconds: float = REMOTE_HANDBACK_SECONDS,
        remote_ticket_stop: Callable[[Mapping[str, Any], str, str, str, str], bool] | None = None,
        ticket_check_seconds: float = ticket_closed_mod.TICKET_CHECK_SECONDS,
        remote_status_reader: Callable[[Mapping[str, Any], str], Mapping[str, Any] | None] | None = None,
        remote_anomaly_reader: Callable[[Mapping[str, Any]], list[dict[str, Any]]] | None = None,
        remote_mark_anomaly_taken: Callable[[Mapping[str, Any], str, str], bool] | None = None,
        fillers: Any | None = None,
        pob_builds_dir: Path | None = None,
        untracked_collector: Callable[[], Iterable[Any]] | None = None,
        restart_watch: Any | None = None,
        respawn: Callable[[], Any] | None = None,
        follow_main: Any | None = None,
        rebalancer: Any | None = None,
        spike_reader: Callable[[dict[int, str], dict[str, Any] | None], dict[str, Any]] | None = None,
        spike_killer: Callable[[int], bool] | None = None,
        run_issue_parent: int | None = None,
        remote_mark_run_issue: Callable[[Mapping[str, Any], str, str, int], bool] | None = None,
        ram_reader: Callable[[], float] | None = None,
        modes_file: Path | None = None,
        yield_root: Path | None = None,
        pid_finder: Callable[[], list[int]] | None = None,
        priority_setter: Callable[[list[int], str], Any] | None = None,
        gate_popen: Callable[..., Any] | None = None,
        gate_run_on_host: Callable[[dict[str, Any], str], Any] | None = None,
        gate_artifacts: Path | None = None,
        gates_path: Path | None = None,
        gate_sync_seconds: float = GATE_SYNC_SECONDS,
        load_samples_path: Path | None = None,
        cut_repo: Path | None = None,
        cut_tz: tzinfo | None = None,
        machine_hold: bool = False,
        machine_mode_reader: Callable[[], str] | None = None,
        hold_pass: Callable[[str], Any] | None = None,
        hold_root: Path | None = None,
        process_killer: Callable[[list[str]], Any] | None = None,
        close_planner: Callable[[list[str]], Any] | None = None,
        pid_killer: Callable[[list[int]], Any] | None = None,
        gh_present: Callable[[], bool] | None = None,
    ) -> None:
        self.store = store
        #: #958: closes the processes named in a lapsed owner preset's `close` list (the end of "sleep");
        #: tests pass a recorder, the real one is `hosts.kill_processes_by_name`.
        self._process_killer = process_killer if process_killer is not None else runs_hosts.kill_processes_by_name
        #: #958 unit 4: a record with `close_mode: allow-list` closes every program of the user outside the
        #: allow-list: `close_planner(keep)` returns `(closed, kept)` or None (nothing read), `pid_killer(pids)`
        #: ends exactly those pids. Tests pass fakes; the real ones are `close_set.plan_close` / `kill_processes_by_pid`.
        self._close_planner = (close_planner if close_planner is not None
                               else (lambda keep: close_set_mod.plan_close(self.host, keep)))
        self._pid_killer = pid_killer if pid_killer is not None else runs_hosts.kill_processes_by_pid
        #: #779: with `machine_hold` the machine mode file (one per user, outside every repo) is read each tick:
        #: in `play` no job starts and the job trees are held; a read that raises starts nothing. Off by default
        #: so no test ever reads or freezes through the real file.
        self._machine_hold = machine_hold or machine_mode_reader is not None
        self._machine_mode_reader = machine_mode_reader
        self._hold_root = Path(hold_root) if hold_root is not None else PROJECT_ROOT
        self._hold_pass = hold_pass
        self._held = False
        #: #750: the checkout whose origin/main the weekly cut is read from (and whose artifacts/benchmark holds
        #: the week's folder); `None` (every test that is not about the cut) = no cut is ever taken.
        self._cut_repo = Path(cut_repo) if cut_repo is not None else None
        self._cut_tz = cut_tz
        self._cut_done: date | None = None  # the Monday whose folder this daemon has seen exist
        self._cut_fetch_at: float | None = None
        #: #621: the owner's reservation record lives in this host's modes file (`None` = the real one).
        self._modes_file = Path(modes_file) if modes_file is not None else None
        #: Where `artifacts/runs/yield/<job>.json` lives (`None` = the checkout this module is in).
        self._yield_root = Path(yield_root) if yield_root is not None else PROJECT_ROOT
        self._pid_finder = pid_finder if pid_finder is not None else runs_hosts.find_pob_pids
        self._priority_setter = priority_setter if priority_setter is not None else runs_hosts.set_priority_class
        self._last_period: str | None = None  # #839 unit 6: the period at the previous tick
        self._owner_idle = False  # True while this daemon holds the PoB workers at Idle for a record
        self._suite_idle = False  # #715: True while the workers are at Idle for a merge suite's test processes
        self._suite_seen = 0  # merge_suite_pytest of the latest spike snapshot
        #: #642 gate_sync: the copy of the weekly gate dir to the laptop (injectables for tests).
        self._dir_copy_run = subprocess.run
        self._gate_popen = gate_popen if gate_popen is not None else subprocess.Popen
        self._gate_run_on_host = gate_run_on_host
        self._gate_artifacts = gate_artifacts
        self._gates_path = gates_path
        self._gate_sync_seconds = gate_sync_seconds
        self._gate_copy: dict[str, Any] | None = None
        self._last_gate_attempt: float | None = None
        #: #1000 row 2: kills a gate copy past `GATE_COPY_LIMIT_SECONDS` (tree); a test replaces it.
        self._copy_killer: Callable[[int], Any] = stopper_mod.taskkill_tree
        self._row_sync: row_sync_mod.RowSync | None = None  # #753
        self._row_transport: row_sync_mod.Transport | None = None  # a test's stub of the laptop
        #: Free RAM in GiB, read when an `auto` job is sized at its start (#570).
        self._ram_reader = ram_reader if ram_reader is not None else slot_budget.available_ram_gb
        self._no_ram_figure_logged = False
        self._auto_settle: dict[str, tuple[float, int]] = {}  # #914: job id -> (first seen, last RAM bound)
        #: The spike ladder (#406): lines come from `config/hosts.json` `<host>.spike`, read on the
        #: first tick; absent or incomplete means the ladder is off. `spike_reader(job_pids, prev)`
        #: returns one machine snapshot (default `load_groups.snapshot`), `spike_killer(pid)` kills a tree.
        self._spike_reader = spike_reader if spike_reader is not None else (
            lambda job_pids, prev: load_groups_mod.snapshot(job_pids=job_pids, prev=prev))
        self._spike_killer = spike_killer if spike_killer is not None else stopper_mod.taskkill_tree
        self._spike_ladder: spike_mod.Ladder | None = None
        self._spike_loaded = False
        self._spike_prev: dict[str, Any] | None = None
        self._spike_last_sample: float | None = None
        #: #1118: the merge queue's CPU share per tick (`merge_share.merge_cores`, injectable for tests). Its state
        #: is carried tick to tick and never reset by a tick with no merge; `_merge_unreadable` makes the
        #: "merge share unreadable" log line once per run of unreadable ticks.
        self.merge_reader: Callable[[dict[str, Any] | None, float], tuple[float | None, dict[str, Any] | None]] = (
            merge_share.merge_cores)
        self._merge_prev: dict[str, Any] | None = None
        self._merge_unreadable = False
        self.spike_step = 0
        #: #760: the always-on load record; `None` path = `<runs dir>/load_samples.jsonl`.
        self._load_samples_path = Path(load_samples_path) if load_samples_path is not None else None
        self._load_last_sample: float | None = None
        #: #768: the next load sample is due on an anchored schedule (`_advance_load_due`), so the ticks'
        #: own granularity and a slow reading shift a line, never the whole cadence.
        self._load_due: float | None = None
        self._load_last_trim: float | None = None
        #: #768 unit 2: the load record's own thread (`start_load_thread`, started by `run(load_thread=True)`).
        #: While it runs it is the ONLY reader of `_spike_reader` and the only writer of `_spike_prev`,
        #: `_load_due`, `_load_last_sample` and the load file; the tick no longer calls `load_record_pass`,
        #: and the ladder's `spike_pass` observes `_load_latest` (the last reading, `(start, snapshot)`,
        #: published as one tuple) instead of reading itself. `_load_inflight` lets one reading be in flight.
        self._load_thread: threading.Thread | None = None
        self._load_stop = threading.Event()
        self._load_inflight = threading.Lock()
        self._load_latest: tuple[float, Mapping[str, Any]] | None = None
        self._load_observed: float | None = None
        #: The "Runs" parent issue (#164): `config/orchestration.json`'s `runs_parent_issue`, read
        #: lazily; every Run issue is attached to it as a native sub-issue.
        self._run_issue_parent = run_issue_parent
        #: Where a gone snapshot's run folder is looked for; `None` = the main checkout's `artifacts/benchmark`.
        self.benchmark_dir: Path | None = None
        self._remote_mark_run_issue = (
            remote_mark_run_issue if remote_mark_run_issue is not None
            else runs_hosts.mark_run_issue_on_host
        )
        #: Run issues created from another host's job whose receipt did not reach that host yet:
        #: `(host, job id) -> number`, so the next pass only retries the receipt, never the create.
        self._remote_run_issues: dict[tuple[str, str], int] = {}
        #: Run issues created but not yet attached under the parent (a failed attach retries).
        self._run_issue_attach: set[int] = set()
        #: Process trees holding PoB slots that no running job owns (#365); tests inject a fake.
        self._untracked_collector = (
            untracked_collector if untracked_collector is not None
            else (lambda: untracked_mod.collect_local(self.store))
        )
        #: Self-restart at a job boundary (#340): an object with `.due() -> (start, head) | None`
        #: and the function that starts the replacement. Both `None` (the default): no restart.
        self._restart_watch = restart_watch
        self._respawn = respawn
        #: #598: the clock reading when the HEAD move was first seen; the 900 s wait counts from it.
        self._move_first_seen: float | None = None
        #: #444: an object with `.step()`, called at the boundary before the restart watch is read.
        self._follow_main = follow_main
        #: #861 rule 3: the checkout a pin-less job's snapshot is cut from.
        self._host_checkout = PROJECT_ROOT
        self.host = str(host).strip().lower()
        #: #403 unit 4: moves a long-waiting queued job to a host with room; one call per tick.
        self._rebalancer = rebalancer if rebalancer is not None else rebalance_mod.Rebalancer(self)
        # #518: clock of each host's last failed remote read; ONE later success pops it
        self._remote_fail_at: dict[str, float] = {}
        self.queue = queue if queue is not None else QueueBackend()
        self.launcher = launcher if launcher is not None else ProcessLauncher()
        self.gh = gh if gh is not None else GhCli()
        self.label = label
        if handback not in HANDBACK_MODES:
            raise ValueError(f"unknown handback mode {handback!r} (one of {HANDBACK_MODES})")
        #: `local` (default): post through `gh` here, unchanged. `remote` (issue #118, the laptop,
        #: which has no `gh`): store the rendered body on the job and call no `gh` at all.
        self.handback = handback
        #: `config/hosts.json`, for the remote hand-back pass (requirement 2); `None` means the
        #: real file, loaded lazily on the first pass so a `local`-only daemon never touches it.
        self._hosts_config = hosts_config
        #: `None` means the default: ONE ssh round trip per host per pass that brings back both its
        #: job store AND its daemon status (`remote_store.read_remote_snapshot`, #73), because the
        #: pass needs both -- the stored hand-backs and a laptop's pending brain message (#132).
        #: A test that injects a jobs reader gets the status half from `remote_status_reader` only.
        self._remote_store_reader = remote_store_reader
        self._remote_status_reader = remote_status_reader
        self._remote_mark_posted = (
            remote_mark_posted if remote_mark_posted is not None else runs_hosts.mark_posted_on_host
        )
        self._remote_pass_seconds = remote_pass_seconds
        #: #686: `(host_cfg, host, job_id, 'stop'|'cancel', reason) -> ok`; `None` = `runs.py ... --local` over ssh.
        self._remote_ticket_stop = remote_ticket_stop if remote_ticket_stop is not None else _remote_ticket_stop_over_ssh
        self._ticket_check_seconds = ticket_check_seconds
        self._last_ticket_pass: float | None = None
        #: #989: whether this host has a `gh` executable, looked up ONCE here (`shutil.which`). Without one the
        #: closed-ticket pass is off here (it cannot read the tickets); the PC's daemon reads this host's jobs.
        #: An injected `gh` stands in for the host's own, so it counts as present unless `gh_present` says not.
        if gh_present is None:
            gh_present = (lambda: True) if gh is not None else (lambda: shutil.which("gh") is not None)
        self._gh_here = bool(gh_present())
        #: Another host's anomaly queue (#467); `None` = over ssh, unless a test injected a store reader
        #: and no anomaly reader (then that pass is skipped: a test never reaches a real ssh).
        self._remote_anomaly_reader = remote_anomaly_reader
        self._remote_mark_anomaly_taken = (
            remote_mark_anomaly_taken if remote_mark_anomaly_taken is not None
            else runs_hosts.mark_anomaly_taken_on_host
        )
        self._last_remote_anomaly_pass: float | None = None
        #: `clock()`-scale timestamp of the last remote hand-back pass; `None` means "never yet",
        #: so the very first tick always runs one.
        self._last_remote_pass: float | None = None
        self.archive = archive
        self.snapshots = snapshots
        self.events_file = Path(events_file) if events_file else None
        self._runs_dir = Path(runs_dir) if runs_dir else None
        self._budget_loader = budget_loader
        #: Every busy PoB slot on this host (#82). `None` means `slot_budget.busy_slots`, the live
        #: semaphore; tests inject a list so no test reads the machine's real slot directory.
        self._slot_lister = slot_lister
        self.clock = clock
        self.timestamp = timestamp
        self.log = log
        if not self._gh_here:
            self.log("ticket check off on this host (no gh here, #989): the PC's daemon reads this host's jobs "
                     "and stops the ones whose ticket closed")
        #: On-demand keymaster (#57): `None` (the default) means "no anomaly detection here" --
        #: an injectable `junkroan.runs.anomalies.AnomalyGuard`, called from `tick` only.
        self.anomaly_guard = anomaly_guard
        if anomaly_guard is not None and hasattr(anomaly_guard, "chain_store"):
            # #862: the guard closes a failed job's chain in code, on this daemon's own store.
            anomaly_guard.chain_store = self.store
            anomaly_guard.missing_script_line = self._missing_script_line
        #: Timed modes (#54): `hosts.revert_expired_modes` in production (`runs.py daemon`); `None`
        #: in tests, so a tick never touches the real `var/modes.json`.
        self.revert_modes = revert_modes
        self._active: dict[str, _Active] = {}
        self._ended_in_tick: list[str] = []  # #910: every job `_end` closed, whatever path (reap or launch)
        #: (job, issue) pairs whose comment is out but whose label call failed: label-only retries.
        self._label_retry: set[tuple[str, int]] = set()
        #: Each other host's jobs as its last successful read showed them (#405: the label waits for the issue's last job).
        self._remote_jobs_seen: dict[str, list[Job]] = {}
        #: Pin refs whose delete from origin failed once (read-only key): logged once, not retried (#756).
        self._pin_sweep_failed: set[str] = set()
        #: The single-instance guard's own file (issue #73); `None` means the real per-host path.
        self._status_file = Path(status_file) if status_file is not None else None
        self._utcnow = utcnow if utcnow is not None else (lambda: datetime.now(timezone.utc))
        self._started_at: datetime | None = None
        #: The owner-key resolver `slot_budget.owner_key` uses for a foreign slot's pid ("pid tree",
        #: #117); `None` means its own real psutil-backed default. Tests inject a fake pid->pid map.
        self._parent_pid = parent_pid
        #: Queued job ids for which the heavy-job hold's log line has already fired (#117
        #: requirement 2): one line per held job when the hold STARTS, not one per tick.
        self._heavy_held_logged: set[str] = set()
        self._spike_held_logged: set[str] = set()  # #729: jobs whose spike-hold line fired in this hold
        self._gate_status: dict[str, dict[str, str]] = {}  # queued held job id -> {gate, detail} (#549)
        self._last_gate: dict[str, str] = {}  # queued job id -> its last logged gate key (#403)
        self._over_limit_logged: dict[str, tuple[str, int]] = {}  # job id -> (mode, limit) its `held: ... queue limit` line named (#443)
        # -- fillers (issue #132) ---------------------------------------------------------------
        #: A `junkroan.runs.fillers.FillerSwitch` (`.enabled()` is the host's filler switch); `None` -- the
        #: default -- means this daemon submits no fillers at all, which is what every test that is not
        #: about fillers gets.
        self.fillers = fillers
        #: The owner's `Documents\Path of Building\Builds\Junkroan`: a filler's run folder is moved
        #: from here into its `fillers\` subfolder (requirement 5). `None` means the real folder.
        self._pob_builds_dir = Path(pob_builds_dir) if pob_builds_dir is not None else None
        # -- #751 filler pass: injectables for tests (None = the real reader) -------------------------
        self.filler_switch: Callable[[], bool] | None = None
        self.filler_cpu_share: Callable[[], float] | None = None   # share 0..1 over the last 60 s
        self.filler_cores: Callable[[], int] | None = None
        self.filler_missing: Callable[[Path], list[str]] | None = None
        self.filler_done_count: Callable[[], int] | None = None
        self.early_warning_runner: Callable[[str], Any] | None = None  # (week 'YYYYmmdd'); None = the real command
        self._missing_cache: dict[str, tuple[float, list[str]]] = {}
        self.filler_main_sha: Callable[[], str] | None = None
        self._cpu_samples: list[tuple[float, float]] = []

    # -- the numbers -----------------------------------------------------------------------------

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir if self._runs_dir is not None else self.queue.runs_dir()

    def _mode_name(self) -> str:
        """The mode this host is on, read as `runs.py mode <host> --current` reads it (#448)."""

        try:
            return runs_hosts.current_mode(self.host, config=self._hosts_config, local=True)
        except Exception:
            return "unknown"

    def owner_record(self) -> tuple[int, datetime] | None:
        """The owner's active reservation on this host (#621), judged at this daemon's clock."""

        return runs_hosts.owner_reservation(self.host, self.timestamp(), modes_file=self._modes_file)

    def budget(self) -> slot_budget.Budget:
        if self._budget_loader is not None:
            loaded = self._budget_loader()
        else:
            loaded = slot_budget.load_budget(
                now=self.timestamp(), host=self.host, modes_file=self._modes_file)
        record = self.owner_record()
        if record is not None and loaded.reserved != record[0]:
            # an injected loader that does not know the record: apply it here, once (never twice)
            loaded = replace(loaded, total=max(0, loaded.total - record[0]),
                             reserved=record[0], reserved_until=record[1])
        return loaded

    def yield_file(self, job_id: str) -> Path:
        return yield_mod.yield_path(job_id, self._yield_root)

    def _reserved_text(self, budget: slot_budget.Budget) -> str:
        until = budget.reserved_until
        return f"reserved {budget.reserved} until {until:%H:%M}" if budget.reserved and until else ""

    def owner_end_pass(self) -> None:
        """#958: on the tick where an owner preset with `on_end: close-browsers` lapses, close the processes
        of its `close` list, and only then drop the record. The close is this host's own; a killer that
        raises is logged once and the record is dropped anyway (the daemon never stops for it)."""

        try:
            record = runs_hosts.lapsed_close_record(self.host, self.timestamp(), modes_file=self._modes_file)
            if record is None:
                return
            preset = record.get("preset") or "owner preset"
            if record.get("close_mode") == runs_hosts.CLOSE_MODE_ALLOW_LIST:
                self._close_outside_allow_list(preset, [str(n) for n in (record.get("keep") or [])])
            else:
                names = [str(n) for n in (record.get("close") or runs_hosts.DEFAULT_CLOSE)]
                try:
                    result = self._process_killer(names)
                    self.log(f"{preset} ended: found {result.found}, killed {result.killed}, "
                             f"denied {result.denied} process(es) of {', '.join(names)}")
                except Exception as exc:  # noqa: BLE001
                    self.log(f"{preset} ended: closing {', '.join(names)} failed ({exc!r}); the record is dropped anyway")
            runs_hosts.release_owner_reservation(
                self.host, modes_file=self._modes_file, only_until=str(record.get("reserved_until")))
        except Exception as exc:  # noqa: BLE001
            self.log(f"owner preset end pass failed ({exc!r})")

    def _close_outside_allow_list(self, preset: str, keep: list[str]) -> None:
        """#958 unit 4: close the CLOSED set of ``close_set`` in one killer call; a snapshot that cannot be read
        (or a planner / killer that raises) closes nothing and logs one line."""

        try:
            plan = self._close_planner(keep)
            if plan is None:
                self.log(f"{preset} ended: the process snapshot could not be read; nothing closed")
                return
            closed = plan[0]
            if not closed:
                self.log(f"{preset} ended: nothing outside the allow-list to close")
                return
            names = ", ".join(sorted({proc.name for proc in closed}, key=str.lower))
            result = self._pid_killer([proc.pid for proc in closed])
            self.log(f"{preset} ended: found {result.found}, killed {result.killed}, "
                     f"denied {result.denied} process(es) outside the allow-list: {names}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"{preset} ended: closing outside the allow-list failed ({exc!r}); the record is dropped anyway")

    def owner_pass(self) -> None:
        """#621: yield files for every running job, and the PoB workers' priority, from the owner's record."""

        try:
            budget = self.budget()
            self._ram_grow(budget)
            record = (budget.reserved, budget.reserved_until) if budget.reserved else None
            workers = self.job_slot_counts()
            give = (yield_mod.plan_yield(workers, budget.limit_for(slot_budget.ROLE_QUEUE))
                    if record is not None else {})
            for job_id in workers:
                path = self.yield_file(job_id)
                active = self._active.get(job_id)
                ram = active.ram_give if active is not None else 0  # #960: a RAM yield is kept, not cleared
                owner = give.get(job_id, 0) if record is not None else 0
                if owner + ram > 0:
                    yield_mod.write_yield(path, owner + ram, record[0] if record else 0,
                                          record[1] if record else None, ram=ram)
                else:
                    yield_mod.clear_yield(path)
            suite = self._suite_seen >= 1
            if record is not None or suite:
                # one target from both conditions: Idle while either holds (#715)
                self._priority_setter(list(self._pid_finder()), "Idle")
                if record is not None and not self._owner_idle:
                    self.log(f"owner reservation: {record[0]} slots until {record[1]:%H:%M}; workers Idle")
                if suite and not self._suite_idle:
                    self.log(f"merge suite running ({self._suite_seen} test processes); workers Idle")
                self._owner_idle = record is not None
                self._suite_idle = suite
            elif self._owner_idle or self._suite_idle:
                was_owner = self._owner_idle
                self._owner_idle = False
                self._suite_idle = False
                self._priority_setter(list(self._pid_finder()), self._mode_priority_now())
                self.log("owner reservation ended; workers back at the mode's priority" if was_owner
                         else "merge suite ended; workers back at the mode's priority")
        except Exception as exc:
            self.log(f"owner reservation pass failed ({exc!r})")

    def _ram_grow(self, budget: slot_budget.Budget) -> None:
        """#960: lower the RAM yield of a job started at the RAM bound as free RAM and slots allow, until 0.

        No worker is stopped or restarted: the yield file only withholds builds, so a lower number lets
        the job's pool submit more of them. Growth is ``min(RAM bound, free slots, what is withheld)``.
        """

        pending = [a for a in self._active.values() if a.ram_give > 0]
        for active in pending:
            bound = self._ram_bound(budget)
            room = self.room(budget)
            step = active.ram_give if bound is None else min(active.ram_give, bound, room)
            if step <= 0:
                continue
            now = self.clock()
            carried = active.ram_grown_n if now - active.ram_grown_at < self._spike_window() else 0
            active.workers += step
            active.ram_give -= step
            active.ram_grown_at = now
            active.ram_grown_n = carried + step
            self.log(f"job {active.job_id}: RAM allows {step} more workers, now {active.workers} of "
                     f"{active.asked} ({active.ram_give} still withheld)")

    def job_slot_counts(self) -> dict[str, int]:
        """#710: per active job, the `queue`-role slot locks it holds, at least ``max(1, workers)``.

        A job submitted with 1 worker may hold more locks (widened); one just started holds none yet.
        """

        held: dict[str, int] = {}
        for row in self.busy_slots():
            job_id = row.get("job")
            if job_id and str(row.get("role") or "").strip().lower() == slot_budget.ROLE_QUEUE:
                held[str(job_id)] = held.get(str(job_id), 0) + 1
        return {job_id: max(self._declared_cost(a.cmd, a.workers), held.get(job_id, 0))
                for job_id, a in self._active.items()}

    @staticmethod
    def _declared_cost(cmd: str, workers: int) -> int:
        """#1053: what ``workers`` declared slots cost: no more than the builds the command runs, when it says.

        A pool of N workers over fewer builds never claims its last slots (083a: one build, 2 workers, 1 lock
        held for 4 h 13 min, counted 2). ``builds_in_command`` is ``None`` where the command does not fix its
        build list, and the charge is then the declared workers, as before.
        """

        declared = max(1, workers)
        builds = build_count.builds_in_command(cmd)
        return declared if builds is None else max(1, min(declared, builds))

    def period_boundary_pass(self) -> bool:
        """#839 unit 6: when the day/night period changed since the last tick, re-class the workers once.

        Same setter and target as the restore above; skipped while an owner reservation or a merge
        suite holds the workers Idle (their end restores the mode's priority for the then-current period).
        """

        try:
            period = runs_hosts.current_period()
            previous, self._last_period = self._last_period, period
            if previous is None or previous == period or self._owner_idle or self._suite_idle:
                return False
            self._priority_setter(list(self._pid_finder()), self._mode_priority_now())
            self.log(f"period {previous} -> {period}: workers re-classed to the mode's priority")
            return True
        except Exception as exc:
            self.log(f"period boundary pass failed ({exc!r})")
            return False

    def _mode_priority_now(self) -> str:
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            mode = str((runs_hosts.read_modes(self._modes_file).get(self.host) or {}).get("mode") or "normal")
            return runs_hosts.mode_priority(runs_hosts._host_entry(config, self.host), self.host, mode)
        except Exception:
            return "Normal"

    def _mine(self, job: Job) -> bool:
        """A job this host runs: its own, or an ``any`` job (what ``next_job(host)`` hands out)."""

        return job.host == self.host or job.host == "any"

    def running_jobs(self) -> list[Job]:
        return [job for job in self.store.jobs(state="running") if self._mine(job)]

    def blocked_jobs(self) -> list[tuple[Job, Job | None]]:
        """This host's queued jobs whose ``--after`` predecessor did not end rc 0 (#82).

        Only ``blocked`` pairs, never a job merely ``waiting`` for a predecessor that still runs:
        waiting is the normal state of a chain, being blocked is the anomaly.
        """

        return [
            (job, dep) for job, dep, status in self.store.held_jobs(self.host)
            if status == store_mod.DEP_BLOCKED
        ]

    def wrong_host_jobs(self) -> list[Job]:
        """This host's own store's ``queued`` jobs addressed to some other host (issue #120).

        The store is per-host, so ``runs.py submit --host <other>``'s ssh path should never leave
        one here; this only ever fires for a hand-written line, or a submit run directly against
        this store bypassing the ssh path -- the ``job_wrong_host`` anomaly, so it does not sit
        `queued` for ever silently (the #120 incident).
        """

        return [job for job in self.store.jobs(state="queued")
                if job.host != self.host and job.host != "any"]

    def busy_slots(self) -> list[dict[str, Any]]:
        """Every PoB slot held on this host right now, from the slot semaphore (never raises)."""

        lister = self._slot_lister
        if lister is None:
            lister = slot_budget.busy_slots
        try:
            return [dict(row) for row in lister()]
        except Exception as exc:
            self.log(f"could not read the busy PoB slots ({exc!r}); assuming none")
            return []

    def used_workers(self, rows: list[dict[str, Any]] | None = None) -> int:
        """What this daemon's own running jobs cost the host, counted once per job.

        A job's declared ``workers`` is a promise it will take that many PoB slots; its workers may
        not have taken them yet (a benchmark spends its first seconds loading), and a job may also
        hold MORE slots than it declared. So a job costs ``max(declared, slots it actually holds)``
        -- the declaration never double counts the slots the same job already took (#82).
        """

        rows = self.busy_slots() if rows is None else rows
        held: dict[str, int] = {}
        for row in rows:
            job_id = row.get("job")
            if job_id:
                held[str(job_id)] = held.get(str(job_id), 0) + 1
        total = 0
        for job in self.running_jobs():
            holding = held.get(job.id, 0)
            total += max(self._slot_cost(job), holding)
        return total

    def _slot_cost(self, job: Job) -> int:
        """What a running job costs the budget: its declared workers, or the workers the RAM bound allows it (#960)."""

        active = self._active.get(job.id)
        if active is not None and active.ram_give > 0:
            return self._declared_cost(job.cmd, active.workers)
        return self._declared_cost(job.cmd, job.workers)

    def foreign_slots(self, rows: list[dict[str, Any]] | None = None) -> tuple[int, int]:
        """``(queue-role, other-role)`` busy slots this daemon's own running jobs do not own."""

        rows = self.busy_slots() if rows is None else rows
        mine = {job.id for job in self.running_jobs()}
        queue_slots = other_slots = 0
        for row in rows:
            if str(row.get("job") or "") in mine:
                continue
            if str(row.get("role") or "").strip().lower() == slot_budget.ROLE_QUEUE:
                queue_slots += 1
            else:
                other_slots += 1
        return queue_slots, other_slots

    # -- the heavy-job rule (#117) -----------------------------------------------------------------

    def _owner_key(self, row: Mapping[str, Any]) -> str:
        kwargs = {} if self._parent_pid is None else {"parent_pid": self._parent_pid}
        return slot_budget.owner_key(row, **kwargs)

    def _descends_from(self, pid: Any, ancestors: set[int], *, depth: int = 8) -> bool:
        """True when ``pid`` is one of ``ancestors`` or has one among its parents (<= ``depth`` levels)."""

        resolve = self._parent_pid if self._parent_pid is not None else slot_budget._default_parent_pid
        try:
            current: int | None = int(pid) if pid else None
        except (TypeError, ValueError):
            return False
        seen: set[int] = set()
        for _ in range(depth):
            if not current or current in seen:
                return False
            if current in ancestors:
                return True
            seen.add(current)
            try:
                current = resolve(current)
            except Exception:
                return False
        return False

    def foreign_heavy_owner(self, rows: list[dict[str, Any]] | None = None) -> str | None:
        """A foreign owner (#117) holding >= :data:`HEAVY_WORKERS` busy slots on this host, if any.

        Groups every busy slot this daemon's own running jobs do not own by :func:`owner_key`
        (a `run_queue.py` line, another daemon's job, a hand-run benchmark's worker pool -- the
        most specific identity that row carries: its `job` id, else its process's parent pid).
        Every role counts (`queue` included): the rule is about wall-clock contention, not about
        which share a slot was taken from.
        """

        rows = self.busy_slots() if rows is None else rows
        running = self.running_jobs()
        mine = {job.id for job in running}
        own_pids = {int(job.pid) for job in running if job.pid}
        groups: dict[str, int] = {}
        for row in rows:
            job_id = row.get("job")
            if job_id and str(job_id) in mine:
                continue
            if own_pids and self._descends_from(row.get("pid"), own_pids):
                continue  # a worker of this daemon's own job (#403): never "foreign", even with no job env
            key = self._owner_key(row)
            groups[key] = groups.get(key, 0) + 1
        for key, count in groups.items():
            if count >= HEAVY_WORKERS:
                return key
        return None

    def heavy_holder(self, rows: list[dict[str, Any]] | None = None) -> str | None:
        """The id of a live heavy job holding the host, own or foreign; ``None`` when there is none.

        A FILLER is never a holder (#132 requirement 3): the heavy rule must not make a job an issue
        waits for sit out a 12 h filler; a filler is killed for any other job (:meth:`preempt_fillers_pass`),
        so the two never put ten PoB workers on a seven-slot host.
        """

        for other in self.running_jobs():
            if other.is_filler:
                continue
            if max(1, other.workers) >= HEAVY_WORKERS:
                return other.id
        return self.foreign_heavy_owner(rows)

    def _host_behind(self, job: Job) -> str | None:
        """#861 rule 3: why ``job`` must not start here, or None. A job with no pin snapshots this checkout's
        HEAD, so it waits until HEAD contains the commit it was submitted at (an unknown commit counts as
        behind). A pinned job, a row without `submit_commit` and an unreadable HEAD are never held."""

        sha = job.submit_commit
        if job.pin or not sha or job.is_filler:
            return None
        cwd = str(self._host_checkout)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # #1000: a read that did not answer (timeout, or skipped for the pass) is the same answer as a failed read: None.
        head = _guarded_git(["git", "-C", cwd, "rev-parse", "HEAD"], key=GIT_READ_KEY,
                            timeout=GIT_READ_SECONDS, creationflags=flags)
        if head is None or head.returncode != 0 or not head.stdout.strip():
            return None
        head_sha = head.stdout.strip()
        anc = _guarded_git(["git", "-C", cwd, "merge-base", "--is-ancestor", sha, head_sha],
                           key=GIT_READ_KEY, timeout=GIT_READ_SECONDS, creationflags=flags)
        if anc is None:
            return None
        if anc.returncode == 0:
            return None
        return f"job submitted at {sha[:12]}, host at {head_sha[:12]}"

    def _hold_for_heavy(self, job: Job) -> str | None:
        """``None`` when ``job`` may proceed; else the id/owner-key of the heavy job holding it.

        Only a queued job of >= :data:`HEAVY_WORKERS` workers can be held by this rule; a lighter
        job is never affected by it (requirement 1: light jobs behind it start as they do today).
        """

        if max(1, job.workers) < HEAVY_WORKERS:
            return None
        return self.heavy_holder()

    def _log_heavy_hold(self, job: Job, holder: str) -> None:
        """One log line per held job when its hold STARTS (#117 requirement 2), not per tick."""

        if job.id in self._heavy_held_logged:
            return
        self._heavy_held_logged.add(job.id)
        self.log(f"held: heavy job {holder} live on {self.host}")

    def _clear_heavy_hold(self, job_id: str) -> None:
        self._heavy_held_logged.discard(job_id)

    # -- fillers (issue #132) ----------------------------------------------------------------------

    def running_fillers(self) -> set[str]:
        return {job.id for job in self.running_jobs() if job.is_filler}

    # -- where a filler's builds go (requirement 5) -------------------------------------------------

    @property
    def pob_builds_dir(self) -> Path:
        if self._pob_builds_dir is not None:
            return self._pob_builds_dir
        return Path.home() / "Documents" / "Path of Building" / "Builds" / "Junkroan"

    def sweep_filler_exports(self, tags: Iterable[str] | None = None) -> list[Path]:
        """Move every filler run's PoB Builds folder into ``Junkroan\\fillers\\`` (requirement 5).

        The pinned ``benchmark.py`` writes ``Junkroan\\benchmark <date> <time>-<tag>`` and has no
        switch or environment variable for it, so the folder is moved from outside the run: every
        tick while a filler runs (the owner's folder holds it for at most one tick) and once more
        when the job ends, so nothing is left behind even if the daemon was down meanwhile. Files are
        moved one by one and overwrite their target, because the run rewrites its "current winner per
        reference and seed" XML as it goes and may write into the source folder again at any moment.
        """

        names = [job.tag for job in self.running_jobs() if job.is_filler] if tags is None else list(tags)
        if not names:
            return []
        builds = self.pob_builds_dir
        moved: list[Path] = []
        for tag in names:
            try:
                sources = sorted(builds.glob(fillers_mod.export_run_glob(str(tag))))
            except Exception as exc:
                self.log(f"could not look for the filler export folder of {tag} ({exc!r})")
                continue
            for source in sources:
                if not source.is_dir():
                    continue
                target = builds / fillers_mod.EXPORT_DIR_NAME / source.name
                if self._move_export(source, target):
                    moved.append(target)
        return moved

    def _move_export(self, source: Path, target: Path) -> bool:
        try:
            target.mkdir(parents=True, exist_ok=True)
            for item in sorted(source.iterdir()):
                destination = target / item.name
                try:
                    os.replace(item, destination)
                except OSError:
                    if item.is_dir() and not destination.exists():
                        item.rename(destination)
            try:
                source.rmdir()  # empty now; a file written between the move and this is kept
            except OSError:
                pass
        except Exception as exc:
            self.log(f"could not move the filler export folder {source} -> {target} ({exc!r})")
            return False
        self.log(f"filler export moved: {source.name} -> {fillers_mod.EXPORT_DIR_NAME}\\{source.name}")
        return True

    def filler_pass(self) -> list[str]:
        """#751 rules 1-4: submit fillers only on a wholly empty machine, as many as measured room allows."""

        if self.fillers is None:
            return []
        self._sample_cpu()
        try:
            return self._filler_pass()
        except Exception as exc:
            self.log(f"fillers: pass failed ({exc!r})")
            return []

    def _filler_on(self) -> bool:
        if self.filler_switch is not None:
            return bool(self.filler_switch())
        enabled = getattr(self.fillers, "enabled", None)
        return True if enabled is None else bool(enabled())

    def _other_job_here(self) -> bool:
        """Rule 1: a job that is not a filler, running or queued for this host (a blocked one counts too)."""

        return any(self._mine(j) and not j.is_filler
                   for state in ("running", "queued") for j in self.store.jobs(state=state))

    def _sample_cpu(self) -> None:
        if self.filler_cpu_share is not None:
            return
        try:
            import psutil  # noqa: PLC0415
            now = self.clock()
            self._cpu_samples.append((now, float(psutil.cpu_percent(interval=None)) / 100.0))
            self._cpu_samples = [(t, v) for t, v in self._cpu_samples if now - t <= 60.0]
        except Exception:
            pass

    def _cpu_share_60s(self) -> float:
        if self.filler_cpu_share is not None:
            return float(self.filler_cpu_share())
        if not self._cpu_samples:
            return 1.0  # no reading = no room
        return sum(v for _t, v in self._cpu_samples) / len(self._cpu_samples)

    @staticmethod
    def _warn_week_of(job: Job) -> str | None:
        m = re.search(r"--tag warn-(\d{8})\b", job.cmd or "")
        return m.group(1) if m else None

    def _filler_done_count(self) -> int:
        """Finished (state done) warn fillers of this week's Monday in this store: rule 4's row position."""

        if self.filler_done_count is not None:
            return int(self.filler_done_count())
        week = f"{weekly_cut.monday_of(self.timestamp()):%Y%m%d}"
        return sum(1 for j in self.store.jobs(state="done") if j.is_filler and self._warn_week_of(j) == week)

    def _missing_cached(self, folder: Path) -> list[str]:
        """`--missing` of a week folder, kept 60 s per folder; a finished filler drops the cache."""

        now = self.clock()
        hit = self._missing_cache.get(str(folder))
        if hit is not None and now - hit[0] < MISSING_CACHE_SECONDS:
            return list(hit[1])
        reader = self.filler_missing if self.filler_missing is not None else _missing_stems
        stems = list(reader(folder))
        self._missing_cache[str(folder)] = (now, stems)
        return stems

    def _early_warning_after(self, job: Job) -> None:
        """#751 rule 4 tail: after a warn row ends rc 0 run `scripts/early_warning.py --week <Monday> --post`."""

        week = self._warn_week_of(job)
        if week is None:
            return
        try:
            runner = self.early_warning_runner or _run_early_warning
            runner(week)
            self.log(f"early warning for week {week} run after {job.id}")
        except Exception as exc:
            self.log(f"early warning for week {week} failed ({exc!r})")

    def _filler_keys(self) -> list[str]:
        """The keys (`note` = `filler-key:<key>`) of fillers running or queued on either host; an unreachable
        other host counts as its last successful read, none yet = this host's only."""

        jobs = list(self.store.jobs(state="running")) + list(self.store.jobs(state="queued"))
        for other in self._remote_jobs_seen.values():
            jobs += [j for j in other if j.state in ("running", "queued")]
        seen: dict[str, None] = {}
        for j in jobs:
            if j.is_filler and j.note.startswith(FILLER_KEY_PREFIX):
                seen[j.note[len(FILLER_KEY_PREFIX):]] = None
        return list(seen)

    def _filler_pass(self) -> list[str]:
        if not self._filler_on() or self.spike_step >= 1 or self._mode_name() != "normal":
            return []
        if self._other_job_here():
            return []
        budget = self.budget()
        config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
        per_worker = (config.get(self.host) or {}).get("ram_per_worker_gb")
        cores = self.filler_cores() if self.filler_cores is not None else (os.cpu_count() or 1)
        n = weekly_fillers.filler_count(
            self.room(budget), float(self._ram_reader()), float(budget.min_free_ram_gb),
            float(per_worker) if per_worker else None, int(cores), self._cpu_share_60s())
        if n <= 0:
            return []
        monday = weekly_cut.monday_of(self.timestamp())
        repo = self._cut_repo if self._cut_repo is not None else PROJECT_ROOT
        folder = weekly_cut.find_week_folder(repo, monday)
        cut = None
        missing: list[str] = []
        rel = None
        if folder is not None:
            cut = str(json.loads((folder / "args.json").read_text(encoding="utf-8")).get("commit") or "") or None
            rel = f"artifacts/benchmark/{folder.name}"
            missing = self._missing_cached(folder)
        main_sha = (self.filler_main_sha() if self.filler_main_sha is not None else _origin_main(repo)) or ""
        if not (cut and missing) and not main_sha:
            self.log("fillers: no origin/main reading; no early-warning filler")
            return []
        # n_done (rule 4's position in the 42 rows): documented default 0 = start from the first row each
        # time; `filler_done_count` is the injectable counter for the warn-tag rows already made.
        n_done = self._filler_done_count()
        commands = weekly_fillers.choose(cut, rel, missing, self._filler_keys(), n, monday, n_done, main_sha)
        out: list[str] = []
        for fc in commands:
            tag = "filler-" + re.sub(r"[^A-Za-z0-9._-]", "-", fc.key)
            try:
                job = self.store.submit(
                    host=self.host, priority=FILLER_PRIORITY, tag=tag, cmd=fc.command, issue=None,
                    submitter=f"runs-daemon {self.host}", pin=fc.pin, workers=1, job_class=CLASS_FILLER,
                    note=FILLER_KEY_PREFIX + fc.key)
            except Exception as exc:
                self.log(f"fillers: could not submit {fc.key} ({exc!r})")
                continue
            self._append_event({"ts": self.timestamp().isoformat(timespec="seconds"), "kind": "filler_submit",
                                "job": job.id, "tag": job.tag, "host": job.host, "count": n})
            out.append(job.id)
        if out:
            self.log(f"fillers: {len(out)} submitted (room for {n})")
        return out

    def filler_status(self) -> dict[str, Any]:
        """The filler part of the status snapshot, for the monitor's row."""

        return {"fillers_running": sorted(self.running_fillers())}

    # -- the status file (issue #73) --------------------------------------------------------------

    @property
    def status_path(self) -> Path:
        return self._status_file if self._status_file is not None else daemon_status_path(self.host)

    def queued_count(self) -> int:
        """This host's own queued jobs (``any``-host jobs count too, same as :meth:`_mine`)."""

        return sum(1 for job in self.store.jobs(state="queued") if self._mine(job))

    def _ram_per_worker_gb(self) -> float | None:
        """#1144: this host's ``ram_per_worker_gb`` from config/hosts.json, or ``None`` when absent or unreadable."""

        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            per_worker = (config.get(self.host) or {}).get("ram_per_worker_gb")
            return float(per_worker) if per_worker else None
        except Exception:
            return None

    def waits(self) -> dict[str, dict[str, Any]]:
        """One reason per queued job of this host that did not start (#706), for the status file.

        Reads what ``fill`` already decided (``_gate_status``) plus the ``--after`` state and the RAM
        floor; it starts nothing and changes no gate. Order: after, ram, reserved / mode / slots.
        """

        try:
            queued = [j for j in self.store.jobs(state="queued") if self._mine(j)]
            if not queued:
                return {}
            all_jobs = {j.id: j for j in self.store.jobs()}
            budget = self.budget()
            try:
                free_ram: float | None = float(self._ram_reader())
            except Exception:
                free_ram = None
            floor = float(budget.min_free_ram_gb)
            out: dict[str, dict[str, Any]] = {}
            for job in queued:
                kind = text = ""
                if job.after:
                    status, dep = store_mod.dependency_status(job, all_jobs)
                    if status == store_mod.DEP_WAITING and dep is not None:
                        kind, text = "after", f"ждёт {dep.tag or dep.id}"
                gate = (self._gate_status.get(job.id) or {}).get("gate", "")
                if not kind and free_ram is not None and (free_ram < floor or gate in ("spike", "ram")):
                    # #1144: the RAM the job needs (floor + per-worker x its workers), not only the floor
                    per_worker = self._ram_per_worker_gb() or 0.0
                    need = 1 if job.workers_auto else self._declared_cost(job.cmd, job.workers)
                    needs_gb = floor + per_worker * need
                    kind, text = "ram", f"RAM: свободно {free_ram:.1f} GB, нужно {needs_gb:.1f} GB"
                if not kind and gate in ("room", "heavy", "limit", "behind"):
                    if budget.reserved and budget.reserved_until is not None:
                        kind, text = "reserved", f"резерв владельца до {budget.reserved_until:%H:%M}"
                    elif budget.total <= 0:
                        kind, text = "mode", "режим хоста off"
                    else:
                        kind, text = "slots", f"слоты: свободно {max(0, self.room(budget))} из {self._declared_cost(job.cmd, job.workers)}"
                if kind:
                    out[job.id] = {"kind": kind, "text": text, "host_fixed": bool(job.host_fixed)}
            return out
        except Exception as exc:
            self.log(f"waits status failed ({exc!r})")
            return {}

    def write_status(self, *, interval: float) -> None:
        """Write the status file: pid, when this daemon started, this tick, what it is running.

        Called from :meth:`run` at start and after every tick -- never from inside :meth:`tick`
        itself, so a test driving ``tick()`` directly is never surprised by a status file appearing.
        """

        now = self._utcnow()
        if self._started_at is None:
            self._started_at = now
        try:
            budget = self.budget()
            slots = {
                "slots_total": budget.total,
                "slots_in_use": sum(self.job_slot_counts().values()),
                "reserved": budget.reserved,
                "reserved_until": budget.reserved_until.isoformat(timespec="seconds") if budget.reserved_until else None,
            }
        except Exception as exc:
            self.log(f"slots status failed ({exc!r})")
            slots = {}
        try:  # #917: the RAM bound the rebalance of the OTHER host reads; None when unreadable
            ram_bound: int | None = self._ram_bound(self.budget())
        except Exception as exc:
            self.log(f"ram bound status failed ({exc!r})")
            ram_bound = None
        status = {
            "host": self.host,
            "ram_bound": ram_bound,
            "pid": os.getpid(),
            "started": self._started_at.isoformat(timespec="seconds"),
            "last_tick": now.isoformat(timespec="seconds"),
            "tick_seconds": interval,
            "running": sorted(self._active),
            "queued": self.queued_count(),
            "gates": dict(self._gate_status),
            "waits": self.waits(),
            **slots,
            **self.filler_status(),
        }
        write_daemon_status(self.status_path, status, log=self.log)

    def room(self, budget: slot_budget.Budget | None = None) -> int:
        """Free workers for a new job: the queue's share and the host's total, both respected.

        Two bounds, the smaller wins (#82 requirement 1):

        * the queue share -- ``limit_for("queue")`` minus this daemon's own jobs and minus every
          busy ``queue``-role slot it does not own (a live ``run_queue.py`` line, another daemon's
          job). Those compete for the same share, so they are subtracted from it.
        * the host total -- ``total`` minus every busy slot it does not own (``others``-share
          callers included) minus what its own jobs cost (declared workers, or more if they took
          more slots than they declared), so a slot is never counted twice. With
          ``strict_reserve`` off the queue's limit IS ``total``, so this is the bound that makes
          every role count; with it on, the ``others`` share is a separate range of slots the queue
          may not use anyway, and this bound stops the reserve from being subtracted twice.

        Can go negative (the host is over-subscribed by work the daemon did not start); ``fill``
        then simply starts nothing.
        """

        active = budget if budget is not None else self.budget()
        rows = self.busy_slots()
        own_usage = self.used_workers(rows)
        foreign_queue, foreign_other = self.foreign_slots(rows)
        queue_room = active.limit_for(slot_budget.ROLE_QUEUE) - own_usage - foreign_queue
        # `own_usage` already covers the slots its own jobs hold (max(declared, held)), so the host
        # bound subtracts each own job once and each foreign slot once -- never a slot twice.
        host_room = active.total - foreign_queue - foreign_other - own_usage
        return min(queue_room, host_room)

    # -- requirement 4: a daemon that died left `running` jobs behind -----------------------------

    def _open_watch(self, pid: int):
        opener = getattr(self.launcher, "exit_watch", None)
        if opener is None:
            return None
        try:
            return opener(pid)
        except Exception as exc:
            self.log(f"exit watch on pid {pid} failed ({exc!r}); falling back to the pid check")
            return None

    def recover(self) -> list[str]:
        """Adopt this host's live ``running`` jobs; end the ones whose process is gone.

        A job whose pid no longer exists becomes ``failed`` with ``rc`` null and the reason
        "lost pid <N>", and is handed back to its issue exactly like a normal end -- so
        a killed daemon can never leave a job ``running`` for ever.
        """

        lost: list[str] = []
        for job in self.running_jobs():
            if job.id in self._active:
                continue
            if job.pid and self.launcher.alive(int(job.pid)):
                asked = max(1, job.workers)
                ram_give = min(yield_mod.read_ram_give(self.yield_file(job.id)), asked - 1)  # #960
                started_at = self._epoch(job.start_ts)
                self._active[job.id] = _Active(
                    job_id=job.id, workers=asked - ram_give, priority=job.priority, cmd=job.cmd,
                    out=Path(job.out) if job.out else self.runs_dir / f"{job.tag}.out",
                    pid=int(job.pid), started_at=started_at, child=None,
                    watch=self._open_watch(int(job.pid)),
                    asked=asked, ram_give=ram_give, ram_grown_at=started_at,
                )
                self.log(f"adopted running job {job.id} (pid {job.pid}) from an earlier daemon")
                continue
            self.log(f"job {job.id}: pid {job.pid} is gone; ending it as failed")
            self._end(job.id, rc=None, reason=lost_pid_reason(job.pid), out=Path(job.out) if job.out else None)
            lost.append(job.id)
        return lost

    # -- one tick --------------------------------------------------------------------------------

    def tick(self) -> TickReport:
        """Retry the hand-backs that failed earlier, end what has exited, start what fits.

        The retry comes FIRST, so a comment that `gh` refused is posted on the NEXT tick rather than
        hammering the same failing call twice in a row.
        """

        GUARD.begin()  # #998: every outside service is tried again in this pass
        report = TickReport()
        self._gate_status = {}  # #549: rebuilt every tick by fill / the restart gate
        try:  # #998 row 2: the slow-pass line is written here, also when a gate returns early
            with _timed("retry_handbacks"):
                report.handed_back = self.retry_handbacks()
            with _timed("retry_run_issues"):
                self.retry_run_issues()
            with _timed("remote_handback_pass"):
                report.remote_handed_back = self.remote_handback_pass()
            with _timed("remote_anomaly_pass"):
                self.remote_anomaly_pass()
            with _timed("reap"):
                report.ended = self.reap()
            with _timed("preempt_fillers_pass"):  # #751 rule 5: before anything else that starts or syncs
                self.preempt_fillers_pass()
            with _timed("gate_sync_pass"):
                self.gate_sync_pass()
            with _timed("row_sync_pass"):
                self.row_sync_pass()
            with _timed("gate_pull_pass"):  # #1166: a finished laptop gate folder comes to the PC
                gate_pull_mod.gate_pull_pass(self)
            with _timed("ticket_closed_pass"):
                self.ticket_closed_pass()
            with _timed("take_cut_pass"):
                self.take_cut_pass()
            with _timed("restart_gate"):
                hold = self._restart_gate(report)
            if report.restarting:
                return report
            with _timed("machine_gate"):
                machine_hold = self._machine_gate()
            if machine_hold:
                hold = True
            with _timed("spike_pass"):
                self.spike_pass()
            if not self.load_thread_running:  # #768: with the load thread running, it takes the reading
                with _timed("load_record_pass"):
                    self.load_record_pass()
            with _timed("owner_end_pass"):  # #958: before the pass that reads the record, so a lapsed one is gone
                self.owner_end_pass()
            with _timed("owner_pass"):
                self.owner_pass()
            with _timed("period_boundary_pass"):
                self.period_boundary_pass()
            if not hold:
                with _timed("fill"):
                    report.started = self.fill()
            with _timed("rebalancer_step"):
                self._rebalancer.step()
            if not hold:
                with _timed("filler_pass"):
                    report.fillers = self.filler_pass()
            with _timed("sweep_filler_exports"):
                self.sweep_filler_exports()
            with _timed("room"):
                report.room = self.room()
            if self.revert_modes is not None:
                with _timed("revert_modes"):
                    try:
                        self.revert_modes()  # idempotent and file-locked: the monitor calls it too
                    except Exception as exc:
                        self.log(f"revert_expired_modes failed ({exc!r})")
            if self.anomaly_guard is not None:
                with _timed("anomalies_check"):
                    self._check_anomalies(report)
            return report
        finally:
            _log_slow_pass()

    def _machine_gate(self) -> bool:
        """#779: True when this tick must start nothing because of the machine mode (play, or unreadable).

        In play the job trees are suspended by `hold.keeper_pass` (only the daemon's own job pids, never the
        sessions: the dispatcher's keeper pass holds those); on `normal` what this daemon held is resumed.
        """

        if not self._machine_hold:
            return False
        from tools.agentops import machine_mode
        got = machine_mode.read_gate(self._machine_mode_reader)  # unreadable = start nothing this tick
        if got.mode is None:
            self.log(f"machine mode unreadable ({got.error!r}); no job starts this tick")
            return True
        mode = got.mode
        try:
            self._apply_hold(mode)
        except Exception as exc:  # noqa: BLE001
            self.log(f"machine hold pass failed ({exc!r})")
        return mode == "play"

    def _apply_hold(self, mode: str) -> None:
        from tools.agentops import hold
        from junkroan.runs import machine_hold
        if mode == "play":
            machine_hold.write_daemon_job_pids(self._hold_root, [int(j.pid) for j in self.running_jobs() if j.pid])
        elif not (self._held or hold.read_record(self._hold_root)):
            return
        run = self._hold_pass or (lambda m: hold.keeper_pass(m, self._hold_root, sessions=lambda: []))
        run(mode)
        self._held = mode == "play"
        if mode == "play":
            return
        machine_hold.write_daemon_job_pids(self._hold_root, [])

    # -- the weekly cut (#750) ---------------------------------------------------------------------

    def take_cut_pass(self) -> Path | None:
        """Friday 20:00 and after: record the coming Monday's cut and open its folder (no build, no queue).

        Only on the pc, only with a filler switch on (rule 6). A fetch at most every 5 min while waiting; a
        failed fetch or any error is one log line and a retry next tick. Never raises. Returns the new folder.
        """

        if self._cut_repo is None or self.host != "pc":
            return None
        now = self.timestamp()
        wd = now.weekday()  # Fri 4, Sat 5, Sun 6, Mon 0
        if not ((wd == 4 and now.hour >= weekly_cut.CUT_HOUR) or wd in (5, 6, 0)):
            return None
        monday = weekly_cut.monday_of(now)
        if self._cut_done == monday:
            return None
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            if self.fillers is None and not any(
                    isinstance(v, Mapping) and v.get("fillers") is True for v in config.values()):
                return None
            if weekly_cut.find_week_folder(self._cut_repo, monday) is not None:
                self._cut_done = monday
                return None
            at = self.clock()
            if self._cut_fetch_at is not None and at - self._cut_fetch_at < FILLER_REFRESH_SECONDS:
                return None
            self._cut_fetch_at = at
            fetched = _guarded_git(["git", "-C", str(self._cut_repo), "fetch", "--quiet", "origin"],
                                   key=GIT_FETCH_KEY, timeout=GIT_FETCH_SECONDS)
            if fetched is None:
                return None  # #1000: the fetch did not answer (one line already logged); retry after the refresh gap
            if fetched.returncode != 0:
                self.log(f"weekly cut: git fetch failed ({fetched.stderr.strip()[:200]}); retry later")
                return None
            sha = weekly_cut.cut_for_week(self._cut_repo, monday, self._cut_tz)
            folder = weekly_cut.open_week_folder(self._cut_repo, monday, sha, now)
            self._cut_done = monday
            self.log(f"weekly cut {sha[:7]} for {monday:%Y-%m-%d}")
            return folder
        except Exception as exc:
            self.log(f"weekly cut failed ({exc!r}); retry later")
            return None

    # -- closed tickets (#686) -----------------------------------------------------------------------

    def ticket_closed_pass(self) -> list[str]:
        """Every :data:`TICKET_CHECK_SECONDS`: stop / cancel the jobs (both hosts) whose ticket is closed.

        One ``gh`` call per distinct issue; a failed call means nothing is touched this pass and one log line.
        Returns the ids acted on. Never raises. Off on a host without a `gh` executable (#989): it reads nothing there.
        """

        if not self._gh_here:
            return []
        read = getattr(self.gh, "issue_state", None)
        if read is None:
            return []
        now = self.clock()
        if self._last_ticket_pass is not None and (now - self._last_ticket_pass) < self._ticket_check_seconds:
            return []
        self._last_ticket_pass = now
        try:
            local = self.running_jobs() + [j for j in self.store.jobs(state="queued") if self._mine(j)]
            remote = [(h, j) for h, jobs in self._remote_jobs_seen.items() for j in jobs
                      if j.state in ("running", "queued")]
            everything = local + [j for _, j in remote]
            states: dict[int, str | None] = {}
            for issue in ticket_closed_mod.issues_to_read(everything):
                states[issue] = read(issue)
                if states[issue] is None:
                    self.log(f"ticket check: gh could not read #{issue}; no job touched this pass")
                    return []
            host_of = {j.id: h for h, j in remote}
            done: list[str] = []
            for job, action, reason in ticket_closed_mod.closed_ticket_actions(everything, states):
                host = host_of.get(job.id)
                if host is None:
                    ok = self._stop_for_closed_ticket(job, action, reason)
                else:
                    ok = self._remote_stop_for_closed_ticket(host, job, action, reason)
                if ok:
                    done.append(job.id)
            return done
        except Exception as exc:
            self.log(f"ticket check failed ({exc!r}); no further job touched this pass")
            return []

    def _stop_for_closed_ticket(self, job: Job, action: str, reason: str) -> bool:
        if action == "cancel":
            try:
                self.store.cancel(job.id, reason=reason)
            except IllegalTransition as exc:
                self.log(f"ticket check: could not cancel {job.id}: {exc}")
                return False
            self.log(f"job {job.id} cancelled: {reason}")
            return True
        err = stopper_mod.kill_job(job, self._spike_killer)
        if err:
            self.log(f"ticket check: could not stop {job.id}: {err}")
            return False
        self._end(job.id, rc=None, reason=reason, stopped=True)
        self.log(f"job {job.id} stopped: {reason}")
        return True

    def _remote_stop_for_closed_ticket(self, host: str, job: Job, action: str, reason: str) -> bool:
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            ok = bool(self._remote_ticket_stop(config[host], host, job.id, action, reason))
        except Exception as exc:
            self.log(f"ticket check: {host} unreachable for {job.id} ({exc!r}); skipped")
            return False
        if ok:
            self.log(f"job {job.id} on {host}: {action} sent ({reason})")
        else:
            self.log(f"ticket check: {host} refused {action} of {job.id}; skipped")
        return ok

    # -- the spike ladder (#406) -------------------------------------------------------------------

    def _spike_ladder_or_none(self) -> "spike_mod.Ladder | None":
        if not self._spike_loaded:
            self._spike_loaded = True
            try:
                config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
                lines = spike_mod.Lines.from_config((config.get(self.host) or {}).get("spike"))
            except Exception as exc:
                self.log(f"spike ladder: could not read its lines ({exc!r}); ladder off")
                lines = None
            if lines is not None:
                self._spike_ladder = spike_mod.Ladder(lines)
        return self._spike_ladder

    def spike_pass(self) -> None:
        """One snapshot per tick into the ladder; step >= 2 stops this host's running fillers.
        Never touches a counted job. A failing reader leaves the step as it was."""

        ladder = self._spike_ladder_or_none()
        if ladder is None:
            return
        if self.load_thread_running:
            # #768: the load thread took the reading; the ladder observes the newest one, once.
            latest = self._load_latest
            if latest is None or latest[0] == self._load_observed:
                return
            now_s, snap = latest
            self._load_observed = now_s
            self._record_busy(snap, now_s)
            running = self.running_jobs()
            try:
                self._suite_seen = int(snap.get("merge_suite_pytest") or 0)
                decision = ladder.observe(snap, now_s)
            except Exception as exc:
                self.log(f"spike ladder: observe failed ({exc!r}); step stays {self.spike_step}")
                return
        else:
            now_s = self.clock()
            if self._spike_last_sample is not None and not self._load_sample_due(now_s):
                return
            self._spike_last_sample = now_s
            running = self.running_jobs()
            job_pids = self._job_pids(running)
            try:
                snap = self._spike_reader(job_pids, self._spike_prev)
                self._spike_prev = snap
                self._record_busy(snap, now_s)
                self._record_load(snap, now_s)  # the ladder's snapshot is the record's too (#760)
                self._suite_seen = int(snap.get("merge_suite_pytest") or 0)
                decision = ladder.observe(snap, now_s)
            except Exception as exc:
                self.log(f"spike ladder: snapshot failed ({exc!r}); step stays {self.spike_step}")
                self._advance_load_due(now_s)
                return
        self.spike_step = decision.step
        if decision.changed:
            self.log(f"spike ladder: step {decision.step}: {decision.reason}")
            self._append_event({
                "ts": self.timestamp().isoformat(timespec="seconds"),
                "kind": "spike_step", "step": decision.step, "cause": decision.cause,
                "reason": decision.reason, "free_ram_mb": snap.get("free_ram_mb"),
            })
        if decision.step >= 2:
            for job in running:
                if job.is_filler:
                    self._stop_filler_for_spike(job, decision.cause)

    def _record_busy(self, snap: Mapping[str, Any], now_s: float) -> None:
        """#898: one whole-PC busy-cores sample per tick from the reading the ladder already took.
        #1118: the row carries the merge queue's share (`merge_cores`) when it is read; when not, the row is the
        whole-PC value (no `merge_cores` key) and one log line says so per run of unreadable ticks."""

        try:
            busy = float(snap.get("cpu_pct")) / 100.0 * (os.cpu_count() or 1)
            slot_budget.append_busy_sample(now_s, busy, merge_cores=self._read_merge_share())
        except Exception as exc:
            self.log(f"busy samples: append failed ({exc!r})")

    def _read_merge_share(self) -> float | None:
        """#1118: one tick of the merge queue's share; None when unreadable (or no baseline yet). The reader is
        given the clock read right before its own call (its CPU delta is divided by that interval, not by the
        snapshot's time, which can be a tick old). A reader that raises counts as unreadable and drops the
        carried state, so the next tick starts over."""

        try:
            share, state = self.merge_reader(self._merge_prev, self.clock())
            why = "no reading this tick (no baseline yet, or the process table or a lock unreadable)"
        except Exception as exc:
            share, state = None, None
            why = f"reader raised {exc!r}"
        self._merge_prev = state
        if share is None:
            if not self._merge_unreadable:
                self.log(f"merge share: {why}; the busy sample is the whole-PC value")
            self._merge_unreadable = True
            return None
        self._merge_unreadable = False
        return float(share)

    @staticmethod
    def _job_pids(running: Iterable[Job]) -> dict[int, str]:
        job_pids: dict[int, str] = {}
        for job in running:
            try:
                job_pids[int(job.pid)] = "filler" if job.is_filler else "counted"
            except (TypeError, ValueError):
                continue
        return job_pids

    # -- the load record (#760) ----------------------------------------------------------------------

    @property
    def load_samples_path(self) -> Path:
        if self._load_samples_path is not None:
            return self._load_samples_path
        return self.runs_dir / "load_samples.jsonl"

    def _record_load(self, snap: Mapping[str, Any], now_s: float) -> None:
        """Append one snapshot; an error is one log line, never more."""

        try:
            load_record_mod.append_sample(self.load_samples_path, snap)
            self._load_last_sample = now_s
            self._advance_load_due(now_s)
        except Exception as exc:
            self.log(f"load record: append failed ({exc!r}); trying again next tick")

    def _load_sample_due(self, now_s: float) -> bool:
        return self._load_due is None or now_s >= self._load_due

    def _advance_load_due(self, now_s: float) -> None:
        """The sample taken at `now_s` (the reading's start) moves the due moment one period on from the
        old one, so a tick that came late costs that line a delay and not the next one; a daemon that
        fell more than a period behind starts a fresh period instead of catching up in a burst."""

        due = self._load_due
        if due is not None and now_s - due < SPIKE_SAMPLE_SECONDS:
            self._load_due = due + SPIKE_SAMPLE_SECONDS
        else:
            self._load_due = now_s + SPIKE_SAMPLE_SECONDS

    def seconds_to_load_sample(self) -> float | None:
        """Seconds until the next load sample is due (<= 0 when it is); `None` before the first one."""

        return None if self._load_due is None else self._load_due - self.clock()

    def load_record_pass(self) -> None:
        """Every SPIKE_SAMPLE_SECONDS one snapshot into `load_samples.jsonl`, whether the spike ladder is
        on or off; the day's trim to 14 days once a day. Never touches a job."""

        now_s = self.clock()
        if self._spike_last_sample == now_s:
            pass  # the ladder took (and recorded, or failed on) this tick's snapshot
        elif self._load_sample_due(now_s):
            try:
                snap = self._spike_reader(self._job_pids(self.running_jobs()), self._spike_prev)
                self._spike_prev = snap
                self._load_latest = (now_s, snap)
            except Exception as exc:
                self.log(f"load record: snapshot failed ({exc!r}); trying again next tick")
                self._load_due = now_s + TICK_SECONDS  # one retry per tick, never a spin
            else:
                self._record_load(snap, now_s)
        if self._load_last_trim is None or now_s - self._load_last_trim >= 86400.0:
            self._load_last_trim = now_s
            try:
                load_record_mod.trim(self.load_samples_path, self.timestamp())
            except Exception as exc:
                self.log(f"load record: trim failed ({exc!r})")

    @property
    def load_thread_running(self) -> bool:
        thread = self._load_thread
        return thread is not None and thread.is_alive()

    def load_record_step(self) -> bool:
        """One scheduler step of the load thread: take the reading (and the day's trim) if due, unless a
        reading is already in flight. `False` = another reading holds the guard, nothing was done.
        Never raises: the body logs its own failures."""

        if not self._load_inflight.acquire(blocking=False):
            return False
        try:
            self.load_record_pass()
        finally:
            self._load_inflight.release()
        return True

    def start_load_thread(self) -> None:
        """#768: the load record is taken by a daemon thread that never waits for the tick (a tick blocked
        by a slow ssh pass used to leave gaps of minutes). Idempotent; `stop_load_thread` ends it."""

        if self.load_thread_running:
            return
        self._load_stop.clear()
        self._load_thread = threading.Thread(target=self._load_loop, name="load-record", daemon=True)
        self._load_thread.start()

    def stop_load_thread(self, timeout: float = 30.0) -> None:
        self._load_stop.set()
        thread = self._load_thread
        if thread is not None:
            thread.join(timeout)

    def _load_loop(self) -> None:
        while not self._load_stop.is_set():
            try:
                self.load_record_step()
            except Exception as exc:  # the thread must outlive any one failure
                try:
                    self.log(f"load record: step failed ({exc!r})")
                except Exception:
                    pass
            to_sample = self.seconds_to_load_sample()
            wait = LOAD_THREAD_POLL_SECONDS if to_sample is None else min(LOAD_THREAD_POLL_SECONDS, max(to_sample, 0.5))
            self._load_stop.wait(wait)

    def _load_line(self, job: Job) -> str:
        try:
            end = datetime.fromisoformat(job.end_ts)  # type: ignore[arg-type]
            if end.tzinfo is not None:
                end = end.astimezone().replace(tzinfo=None)
            return load_record_mod.load_line(self.load_samples_path, end)
        except Exception:
            return "Load at its end: no load sample"

    def _stop_filler_for_spike(self, job: Job, cause: str | None) -> None:
        self._stop_filler(job, f"stopped by spike: {cause or 'unknown'}")

    def _stop_filler(self, job: Job, reason: str) -> bool:
        """Kill a filler's tree, then store it `stopped` with `reason`. False when the kill failed."""

        err = stopper_mod.kill_job(job, self._spike_killer)
        if err:
            self.log(f"fillers: could not stop {job.id}: {err}")
            return False
        self._end(job.id, rc=None, reason=reason, stopped=True)
        self.log(f"filler {job.id} stopped: {reason}")
        return True

    def _check_anomalies(self, report: TickReport) -> None:
        """One call into `junkroan.runs.anomalies` (#57); a bad detector must not kill the tick."""

        try:
            ids = list(report.ended)
            ids += [j for j in dict.fromkeys(self._ended_in_tick) if j not in ids]  # #910: ended in launch too
            self._ended_in_tick = []
            ended_jobs = [self.store.get(job_id) for job_id in ids]
            running = {job_id: str(active.out) for job_id, active in self._active.items()}
            try:
                untracked = list(self._untracked_collector())
            except Exception as exc:
                self.log(f"untracked-slot collection failed ({exc!r})")
                untracked = []
            self.anomaly_guard.check(ended_jobs=ended_jobs, running=running, held=self.blocked_jobs(),
                                      wrong_host=self.wrong_host_jobs(), untracked=untracked,
                                      commands={job_id: active.cmd for job_id, active in self._active.items()},
                                      job_state=lambda job_id: self.store.get(job_id).state,
                                      origin_job_state=self._origin_job_state,
                                      follow_main=self._follow_main.streak() if self._follow_main is not None else None)
        except Exception as exc:
            self.log(f"anomaly guard failed ({exc!r})")

    def reap(self) -> list[str]:
        """End every job whose child has exited (or whose adopted pid has gone)."""

        ended: list[str] = []
        for job_id, active in list(self._active.items()):
            if active.child is not None:
                rc = active.child.poll()
                if rc is None:
                    continue
                self._end(job_id, rc=int(rc), out=active.out, active=active)
            elif active.watch is not None:
                rc = active.watch.poll()
                if rc is None:
                    continue
                self._end(job_id, rc=int(rc), out=active.out, active=active)
                try:
                    active.watch.close()
                except Exception:
                    pass
                active.watch = None
            else:
                if self.launcher.alive(active.pid):
                    continue
                self._end(job_id, rc=None, reason=lost_pid_reason(active.pid), out=active.out, active=active)
            ended.append(job_id)
        # A running job of this host that this daemon did not start and did not adopt (an earlier
        # daemon's, or one written after `recover`) is checked by its pid too (#353).
        for job in self.running_jobs():
            if job.id in self._active or not job.pid:
                continue
            if self.launcher.alive(int(job.pid)):
                continue
            self.log(f"job {job.id}: pid {job.pid} is gone; ending it as failed")
            self._end(job.id, rc=None, reason=lost_pid_reason(job.pid), out=Path(job.out) if job.out else None)
            ended.append(job.id)
        return ended

    def fill(self) -> list[str]:
        """Start queued jobs while the host's share has room (priority, then oldest).

        A job HELD by the heavy-job rule (#117) keeps its place -- it is tried again first on the
        next tick -- but it does not block THIS tick: it is excluded from `store.next_job` for the
        rest of this call only, so a light job behind it (or another heavy job, held the same way)
        still gets its turn. A job that does not fit the room, in contrast, still ends the fill
        the head keeps its place, but (#834) a later job still starts when it fits the room now and the
        head would still fit once the jobs running now end (sum of passed needs + head need <= total).
        """

        started: list[str] = []
        if self.spike_step >= spike_mod.MAX_STEP:
            self._blanket_gate("spike", f"spike step {self.spike_step}: no new starts")
            self._log_spike_hold()
            return started
        self._spike_held_logged.clear()
        held: set[str] = set()
        gates: dict[str, tuple[str, str]] = {}  # job id -> (gate, holder), decided in this call
        room_blocked: Job | None = None
        passed: int | None = None  # #834: workers already running or started behind a room-blocked head
        budget = self.budget()
        try:
            while True:
                job = self.store.next_job(self.host, exclude=set(started) | held)
                if job is None:
                    return started
                # The heavy-job rule comes BEFORE `_may_exceed_room`, so no priority borrows past it:
                # two heavy jobs (5+ workers each) never hold slots on the same host at once.
                behind = self._host_behind(job)
                if behind is not None:
                    gates[job.id] = ("host behind main", behind)
                    self._gate_status[job.id] = {"gate": "host behind main", "detail": behind}
                    held.add(job.id)
                    continue
                holder = self._hold_for_heavy(job)
                if holder is not None:
                    self._log_heavy_hold(job, holder)
                    gates[job.id] = ("heavy", holder)
                    held.add(job.id)
                    continue
                workers = self._declared_cost(job.cmd, job.workers)
                limit = budget.limit_for(slot_budget.ROLE_QUEUE)
                if 0 < limit < workers:
                    # #443: wider than the mode's queue LIMIT (not the momentary room): it can never
                    # start in this mode, so it holds only itself and the jobs behind it go on.
                    # The line names the host's MODE (what `runs.py mode <host> --current` prints), not the
                    # budget file's period name (#448); it is written once per (mode, limit) change.
                    mode = self._mode_name()
                    key = (mode, limit)
                    if self._over_limit_logged.get(job.id) != key:
                        self._over_limit_logged[job.id] = key
                        self.log(f"held: {job.id} needs {workers} > queue limit {limit} (mode {mode})")
                    gates[job.id] = ("limit", "")
                    self._gate_status[job.id] = {
                        "gate": "limit", "detail": f"needs {workers} > queue limit {limit} (mode {mode})"}
                    held.add(job.id)
                    continue
                self._over_limit_logged.pop(job.id, None)
                room = self.room(budget)
                if room_blocked is not None:
                    # #834: the head waits for room only. A later job goes ahead of it only when it fits
                    # the room now AND the head would still fit once the jobs running now end:
                    # sum(passed) + need(head) <= the queue's total. Fillers stay off meanwhile.
                    cap = min(limit, budget.total) if limit > 0 else 0
                    if passed is None:  # jobs of this host that started behind the head earlier still run
                        key = (room_blocked.submit_ts, room_blocked.id)
                        passed = sum(self._slot_cost(j) for j in self.running_jobs()
                                     if not j.is_filler and (j.submit_ts, j.id) > key)
                    head_need = self._declared_cost(room_blocked.cmd, room_blocked.workers)
                    if job.is_filler or workers > room or passed + workers + head_need > cap:
                        gates[job.id] = ("behind", room_blocked.id)
                        self._gate_status[job.id] = {
                            "gate": "behind",
                            "detail": f"behind {room_blocked.id} (needs {head_need}, free {max(0, room)})"}
                        held.add(job.id)
                        continue
                    passed += workers
                elif workers > room and not self._may_exceed_room(job, budget):
                    if limit <= 0 or job.is_filler:
                        gates[job.id] = ("room", "")
                        room_blocked = job
                        return started
                    gates[job.id] = ("room", "")
                    room_blocked = job
                    held.add(job.id)
                    continue
                ram_hold = self._ram_hold(job, budget)
                ram_allowed: int | None = None
                if ram_hold is not None:  # #899: free RAM cannot hold its workers; retried every fill
                    ram_allowed = self._ram_partial(job, budget)  # #960: start at the bound, yield the rest
                    if ram_allowed is None:
                        gates[job.id] = ("ram", ram_hold)
                        self._gate_status[job.id] = {"gate": "ram", "detail": ram_hold}
                        held.add(job.id)
                        if room_blocked is None and not job.workers_auto and not job.is_filler:
                            room_blocked = job  # #960: a head held by RAM blocks later jobs as one held by room does
                        continue
                settle = self._auto_settle_hold(job, budget)
                if settle is not None:  # #914: RAM still moving after another job's end; retried every fill
                    gates[job.id] = ("ram", settle)
                    self._gate_status[job.id] = {"gate": "ram", "detail": settle}
                    held.add(job.id)
                    continue
                self._clear_heavy_hold(job.id)
                self._auto_settle.pop(job.id, None)
                self._start(job, ram_allowed=ram_allowed)
                started.append(job.id)
                gates[job.id] = ("start", "")
        finally:
            self._log_gates(gates, started, room_blocked, budget)

    def _log_spike_hold(self) -> None:
        """#729: one `gate <id>: spike step N (free RAM X GB under Y GB)` line per queued job per hold."""

        try:
            ladder = self._spike_ladder
            free_mb = (self._spike_prev or {}).get("free_ram_mb")
            for job in self.store.jobs(state="queued"):
                if not self._mine(job) or job.is_filler or job.id in self._spike_held_logged:
                    continue
                self._spike_held_logged.add(job.id)
                if ladder is not None and free_mb is not None:
                    tail = (f"free RAM {free_mb / 1024:.1f} GB under "
                            f"{ladder.lines.ram_free_mb_hard / 1024:.1f} GB")
                else:
                    tail = "free RAM unknown"
                self.log(f"gate {job.id}: spike step {self.spike_step} ({tail})")
        except Exception as exc:
            self.log(f"spike gate log failed ({exc!r})")

    def _blanket_gate(self, gate: str, detail: str) -> None:
        """Every queued non-filler job of this host is held by ``gate`` (spike / restart), for status (#549)."""

        try:
            for job in self.store.jobs(state="queued"):
                if self._mine(job) and not job.is_filler:
                    self._gate_status[job.id] = {"gate": gate, "detail": detail}
        except Exception as exc:
            self.log(f"gate status failed ({exc!r})")

    def preempt_fillers_pass(self) -> list[str]:
        """#751 rule 5: any job that is not a filler (any priority), running or queued here, or a mode other
        than `normal`: every running filler of this host is killed (whole tree) and stored `stopped`.

        Its row is simply missing again. The job that arrived starts on a later tick. A filler whose kill
        failed stays and is tried again next tick. Never raises.
        """

        try:
            fillers = [f for f in self.running_jobs() if f.is_filler]
            if not fillers:
                return []
            if self._other_job_here():
                reason = "a job that is not a filler is here"
            elif self._mode_name() != "normal":
                reason = f"mode {self._mode_name()} is not normal"
            else:
                return []
            return [f.id for f in fillers if self._stop_filler(f, f"stopped by daemon: {reason}")]
        except Exception as exc:
            self.log(f"fillers: preempt pass failed ({exc!r})")
            return []

    def _log_gates(self, gates: dict[str, tuple[str, str]], started: list[str],
                   room_blocked: Job | None, budget: slot_budget.Budget) -> None:
        """One ``gate <job>: <why> (...)`` line per queued non-filler job when its gate CHANGES (#403).

        The gate is what ``fill`` decided above (``heavy`` / ``room`` / ``start``); a queued job
        ``fill`` never reached is held either by ``--after`` (its predecessor not done) or sits
        behind the head-of-line ``room`` block. Nothing is re-derived: an unchanged gate logs
        nothing, and an entry of a job that is no longer queued is dropped.
        """

        try:
            queued = {j.id: j for j in self.store.jobs(state="queued") if self._mine(j)}
            for job_id in started:
                job = self.store.get(job_id)
                if job is not None and not job.is_filler:
                    queued.setdefault(job_id, job)
            all_jobs = None
            for job_id, job in queued.items():
                if job.is_filler:
                    continue
                gate = gates.get(job_id)
                if gate is not None and gate[0] == "limit":
                    continue  # its own `held: ... queue limit` line (#443) says it
                if gate is None:
                    if job.after:
                        all_jobs = all_jobs or {j.id: j for j in self.store.jobs()}
                        status, dep = store_mod.dependency_status(job, all_jobs)
                        if status == store_mod.DEP_WAITING:
                            gate = ("after", dep.id if dep else "")
                        elif status == store_mod.DEP_BLOCKED:
                            continue  # the held_by_failed_predecessor anomaly's business, not a gate
                    if gate is None and room_blocked is not None:
                        gate = ("room", "") if job.id == room_blocked.id else ("behind", room_blocked.id)
                    if gate is None:
                        # #825 row 4: every predecessor done, fill did not start it and no other gate
                        # holds it: the queue's own choice (`next_job`) passed it over. Say so.
                        gate = ("queue order", "")
                key = f"{gate[0]}:{gate[1]}"
                need = self._declared_cost(job.cmd, job.workers)
                if gate[0] == "heavy":
                    detail = f"holder {gate[1]}, need {need}"
                elif gate[0] == "after":
                    detail = f"predecessor {gate[1]} not done, need {need}"
                elif gate[0] in ("host behind main", "ram"):
                    detail = gate[1]
                elif gate[0] == "queue order":
                    detail = f"predecessors done, not chosen by the queue, need {need}"
                elif gate[0] == "behind":
                    head = self.store.get(gate[1])
                    detail = f"{gate[1]} (needs {self._declared_cost(head.cmd, head.workers)}, free {max(0, self.room(budget))})"
                elif gate[0] == "room":
                    rows = self.busy_slots()
                    fq, fo = self.foreign_slots(rows)
                    detail = f"used {self.used_workers(rows) + fq + fo}/{budget.total}, need {need}"
                    if budget.reserved:
                        detail += f", {self._reserved_text(budget)}"
                else:
                    detail = f"need {need}"
                if gate[0] in ("heavy", "room", "behind"):
                    self._gate_status[job_id] = {
                        "gate": gate[0], "detail": f"behind {detail}" if gate[0] == "behind" else detail}  # #549
                if self._last_gate.get(job_id) == key:
                    continue
                self._last_gate[job_id] = key
                if gate[0] == "behind":
                    self.log(f"gate {job_id}: behind {detail}")
                else:
                    self.log(f"gate {job_id}: {gate[0]} ({detail})")
            for job_id in list(self._last_gate):
                job = queued.get(job_id)
                if job is None or job.id in started or job.is_filler:
                    self._last_gate.pop(job_id, None)
        except Exception as exc:  # a log line must never stop a tick
            self.log(f"gate log failed ({exc!r})")

    def _may_exceed_room(self, job: Job, budget: slot_budget.Budget) -> bool:
        """Graceful priority: a job may start past the share while worse-priority work holds slots.

        Only while some running job of this host has a strictly worse priority, and never past the
        budget's ``total`` -- the slots it borrows are the ones the strict reserve holds back for
        everyone else, not slots that do not exist. Nothing is killed and nothing is preempted
        here: which waiter gets the next FREED slot is ``slot_budget``'s ordering (#37), and the
        started job carries its ``JUNKROAN_POB_PRIORITY`` so that ordering can see it.
        """

        if budget.limit_for(slot_budget.ROLE_QUEUE) <= 0:  # #413 pause: the queue's share is nothing, no borrowing
            return False
        own = _PRIORITY_RANK.get(job.priority, 2)
        running = self.running_jobs()
        if not any(_PRIORITY_RANK.get(other.priority, 2) > own for other in running):
            return False
        rows = self.busy_slots()
        foreign_queue, foreign_other = self.foreign_slots(rows)
        used = self.used_workers(rows) + foreign_queue + foreign_other
        return used + self._declared_cost(job.cmd, job.workers) <= budget.total

    # -- starting --------------------------------------------------------------------------------

    def _ram_bound(self, budget: slot_budget.Budget) -> int | None:
        """#899: how many more PoB workers free RAM holds, or ``None`` when the host has no ``ram_per_worker_gb``.

        ``floor_int((free - reserved - floor) / per)``; ``reserved`` is ``per`` times the workers of this
        daemon's jobs started less than the host's spike ``window_s`` (300 s when absent) ago: they have not
        grown into the free-RAM reading yet. A running job is never touched by this number.
        """

        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            host_cfg = config.get(self.host) or {}
            per_worker = host_cfg.get("ram_per_worker_gb")
            window = float((host_cfg.get("spike") or {}).get("window_s") or 300)
        except Exception as exc:
            self.log(f"ram bound: hosts config unreadable ({exc!r}); sized by slots alone")
            per_worker, window = None, 300.0
        if not per_worker:
            return None
        per = float(per_worker)
        now = self.clock()
        young = 0
        for a in self._active.values():
            if now - a.started_at < window:
                young += a.workers
            elif a.ram_grown_n and now - a.ram_grown_at < window:  # #960: workers added late are young too
                young += a.ram_grown_n
        free = float(self._ram_reader())
        return int(math.floor((free - per * young - budget.min_free_ram_gb) / per + 1e-9))

    def _spike_window(self) -> float:
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
            return float(((config.get(self.host) or {}).get("spike") or {}).get("window_s") or 300)
        except Exception:
            return 300.0

    def _ram_partial(self, job: Job, budget: slot_budget.Budget) -> int | None:
        """#960: the workers a RAM-held job may start with now, or ``None`` when it is held as before.

        Only a fixed-count, non-filler job whose command re-reads its yield file, with the RAM bound at least
        1 and below the count it asks for.
        """

        if job.workers_auto or job.is_filler or not reads_yield_file(job.cmd):
            return None
        bound = self._ram_bound(budget)
        need = self._declared_cost(job.cmd, job.workers)
        if bound is None or bound < 1 or bound >= need:
            return None
        return bound

    def _ram_hold(self, job: Job, budget: slot_budget.Budget) -> str | None:
        """#899: the gate text when free RAM cannot hold this job's workers, else ``None``."""

        bound = self._ram_bound(budget)
        if bound is None:
            return None
        need = 1 if job.workers_auto else self._declared_cost(job.cmd, job.workers)
        if bound >= need:
            return None
        return f"RAM: holds {max(0, bound)} workers, need {need}"

    AUTO_SETTLE_MAX_SECONDS = 180.0  # #914: the longest an auto job waits for its RAM reading to settle

    def _auto_settle_hold(self, job: Job, budget: slot_budget.Budget) -> str | None:
        """#914: hold an auto job whose RAM bound is below the host's free slots until two readings agree.

        Memory freed by a job that just ended is still rising for a minute or so; a count taken in that
        second stays for the whole run (#909's 17:42 start: 1 worker for 13 h 36 min on a 3-slot host).
        The first reading is remembered, a later fill whose bound equals the previous one lets the job
        start (with that bound), a differing one replaces it; after ``AUTO_SETTLE_MAX_SECONDS`` it starts
        with what it has. No number is fixed here: the bound is still the formula over measured RAM.
        """

        if not job.workers_auto:
            return None
        slots = self.room(budget)
        bound = self._ram_bound(budget)
        if bound is None or bound >= slots or bound < 1:
            self._auto_settle.pop(job.id, None)
            return None
        now = self.clock()
        first, last = self._auto_settle.get(job.id, (now, None))
        self._auto_settle[job.id] = (first, bound)
        if last == bound or now - first >= self.AUTO_SETTLE_MAX_SECONDS:
            return None
        return (f"RAM settling: holds {bound} of {slots} workers; waits for two agreeing readings "
                f"(up to {int(self.AUTO_SETTLE_MAX_SECONDS // 60)} min)")

    def _resolve_auto_workers(self, job: Job, budget: slot_budget.Budget) -> int:
        """The N an `auto` job starts with (#570): the free room on this host, bounded by free RAM.

        ``min(slots, ram_bound)`` (#899: below 1 the job is not started, :meth:`fill` holds it before this
        runs); ``slots`` is :meth:`room`, ``ram_bound`` is :meth:`_ram_bound` (no bound on a host whose
        ``config/hosts.json`` entry has no ``ram_per_worker_gb``). Capped at ``HEAVY_WORKERS - 1`` while
        another heavy job holds the host, so two heavy jobs never share it (#117).
        """

        slots = self.room(budget)
        ram_bound = self._ram_bound(budget)
        if ram_bound is None and not self._no_ram_figure_logged:
            self._no_ram_figure_logged = True
            self.log(f"auto workers: no ram_per_worker_gb for {self.host} in config/hosts.json; sized by slots alone")
        n = max(1, slots) if ram_bound is None else min(max(1, slots), ram_bound)
        capped = self.heavy_holder() is not None
        if capped:
            n = min(n, HEAVY_WORKERS - 1)
        builds = build_count.builds_in_command(job.cmd, job.argv)  # #1053: a pool never wider than its builds
        if builds is not None:
            n = max(1, min(n, builds))
        try:
            free_txt = f", free RAM {float(self._ram_reader()):.1f} GB"  # #914: the reading the count came from
        except Exception:
            free_txt = ""
        self.log(f"auto workers {job.id}: {n} (slots {slots}, ram {'-' if ram_bound is None else ram_bound}, "
                 f"heavy cap {'yes' if capped else 'no'}{free_txt})")
        return n

    def _start(self, job: Job, ram_allowed: int | None = None) -> None:
        resolved: dict[str, Any] = {}
        if job.workers_auto:
            n = self._resolve_auto_workers(job, self.budget())
            cmd, argv = rebalance_mod.set_workers(job.cmd, job.argv, n)
            job = replace(job, workers=n, cmd=cmd, argv=argv)
            resolved = {"workers": n, "cmd": cmd, "argv": argv}
        name = self.queue.out_name(job.cmd, self.timestamp(), self.runs_dir)
        out = self.runs_dir / f"{name}.out"
        snapshot: Path | None = None
        cwd = PROJECT_ROOT
        if self.snapshots and self.queue.wants_snapshot(job.cmd):
            made = self.queue.make_snapshot(name, job.pin or "HEAD")
            if made is not None:
                snapshot, commit = made
                cwd = snapshot
                self.log(f"job {job.id}: snapshot {name} @{commit}")
            elif job.pin:
                # A pinned run runs at its pin or not at all (#756): never on the daemon's own code.
                why = getattr(self.queue, "snapshot_failure", lambda: None)() or f"pin {job.pin}: no snapshot made"
                self.log(f"job {job.id}: {why}; not started")
                self.store.start(job.id, out=str(out), pid=None, **resolved)
                self._end(job.id, rc=None, reason=why, out=out)
                return
        # The same environment run_queue.py gives its children -- role `queue`, so the job may take
        # any slot of the queue's share -- plus the job's priority, which is what slot_budget's
        # graceful ordering reads (#37). Both are inherited by everything the job starts in turn.
        # `JUNKROAN_RUNS_JOB` tags every PoB slot this job's workers take with the job's id, so the
        # daemon's own slots are told apart from a foreign run's without process ancestry (#82).
        env = {
            **os.environ,
            "JUNKROAN_HOST": self.host,     # #778: a job's snapshot is never daemon_repo_path
            "JUNKROAN_POB_ROLE": "queue",
            "JUNKROAN_POB_PRIORITY": job.priority,
            slot_budget.JOB_ENV: job.id,
        }
        env[yield_mod.ENV_VAR] = str(self.yield_file(job.id).resolve())
        asked = max(1, job.workers)
        ram_give = 0
        if ram_allowed is not None and 1 <= ram_allowed < asked:
            # #960: the yield is on disk BEFORE the child exists, so no build runs above the RAM bound
            ram_give = asked - ram_allowed
            yield_mod.write_yield(self.yield_file(job.id), ram_give, 0, None, ram=ram_give)
        started_at = self.clock()
        try:
            child = self.launcher.start(list(job.argv) if job.argv else job.cmd, cwd=cwd, out=out, env=env)
        except Exception as exc:
            self.log(f"job {job.id}: launch failed ({exc!r})")
            if snapshot is not None:
                self.queue.drop_snapshot(snapshot)
            self.store.start(job.id, out=str(out), pid=None, **resolved)
            self._end(job.id, rc=None, reason=f"launch failed: {exc!r}", out=out)
            return
        self.store.start(job.id, out=str(out), pid=int(child.pid), **resolved)
        self._active[job.id] = _Active(
            job_id=job.id, workers=asked - ram_give, priority=job.priority, cmd=job.cmd,
            out=out, pid=int(child.pid), started_at=started_at, child=child, snapshot=snapshot,
            asked=asked, ram_give=ram_give, ram_grown_at=started_at,
        )
        if ram_give:
            self.log(f"gate {job.id}: started at {asked - ram_give} of {asked} workers, RAM")
        self.log(f"start {job.id} {job.priority} x{asked - ram_give} pid {child.pid}: {job.cmd}")

    # -- ending ----------------------------------------------------------------------------------

    def _end(
        self, job_id: str, *, rc: int | None, out: Path | None = None,
        reason: str | None = None, active: _Active | None = None, stopped: bool = False,
    ) -> None:
        active = active if active is not None else self._active.get(job_id)
        self._active.pop(job_id, None)
        yield_mod.clear_yield(self.yield_file(job_id))
        if active is not None and active.child is not None:
            active.child.close()
        started_at = active.started_at if active is not None else self.clock()
        cmd = active.cmd if active is not None else self.store.get(job_id).cmd
        out = out if out is not None else (active.out if active is not None else None)

        run_dir: Path | None = None
        if out is not None:
            try:
                run_dir = self.queue.find_run_dir(cmd, out, started_at)
            except Exception as exc:
                self.log(f"job {job_id}: could not locate the run directory ({exc!r})")
        snapshot_diff: Path | None = None
        keep_snapshot = False
        if active is not None and active.snapshot is not None:
            try:
                snapshot_diff = self.queue.save_snapshot_diff(active.snapshot, job_id)
            except Exception as exc:
                keep_snapshot = True
                self.log(f"job {job_id}: snapshot diff not saved ({exc}); worktree kept")
        try:
            if stopped:     # a deliberate stop is stored `stopped`, never `failed` (#421)
                job = self.store.stop(job_id, reason=reason,
                                      snapshot_diff=str(snapshot_diff) if snapshot_diff else None)
            else:
                job = self.store.end(job_id, rc=rc, out=str(out) if out else None,
                                     run_dir=str(run_dir) if run_dir else None, reason=reason,
                                     snapshot_diff=str(snapshot_diff) if snapshot_diff else None)
        except IllegalTransition as exc:
            # Someone else ended this job (a second daemon, a hand-written `stop`): the store's
            # word wins, and this tick must not die over it.
            self.log(f"job {job_id}: already not running ({exc}); leaving the store alone")
            return
        if self.anomaly_guard is not None:
            self._ended_in_tick.append(job_id)
        duration = self._duration(job)
        self.log(f"end {job_id}: rc {rc} in {human_duration(duration)}")
        if job.is_filler:
            # Its builds must not stay in the folder the owner reads even if this daemon never swept while it ran.
            self.sweep_filler_exports([job.tag])
            self._missing_cache.clear()  # #751: a finished filler changes what is missing
            if rc == 0 and not stopped:
                self._early_warning_after(job)
        if self.archive and out is not None:
            try:
                self.queue.archive(cmd, run_dir, out)
            except Exception as exc:
                self.log(f"job {job_id}: archival failed ({exc!r})")
        if active is not None and active.snapshot is not None and not keep_snapshot:
            self.queue.drop_snapshot(active.snapshot)
        self._drop_pin_ref(job)
        self._append_event({
            "ts": self.timestamp().isoformat(timespec="seconds"),
            "kind": "end", "job": job.id, "issue": job.issue, "rc": rc,
        })
        self._handback(job)
        job = self._keep_run_issue_body(job)
        if self.handback != "remote":
            self.create_run_issue(job)

    def _drop_pin_ref(self, job: Job) -> None:
        """#756 rule 2: the pin's ref on origin goes when no queued/running job holds the same pin."""

        drop = getattr(self.queue, "drop_pin_ref", None)
        if not job.pin or drop is None:
            return
        try:
            if any(j.pin == job.pin and j.id != job.id and j.state in ("queued", "running")
                   for j in self.store.jobs()):
                return
            msg = drop(job.pin)
            if msg:
                self.log(f"job {job.id}: {msg}")
        except Exception as exc:
            self.log(f"job {job.id}: pin ref not dropped ({exc!r})")

    # -- the Run issue of a whole-set benchmark job (#164) ---------------------------------------

    def _keep_run_issue_body(self, job: Job) -> Job:
        """Build the Run issue's title and body from the job's ``run_dir`` and keep them on the record."""

        if run_issue_mod.is_whole_set_job(job) is None or not job.run_dir or job.run_issue_body:
            return job
        try:
            title, body = self.run_issue_text(job)
            return self.store.record_run_issue_body(job.id, title, body)
        except Exception as exc:
            self.log(f"job {job.id}: could not build its Run issue ({exc!r})")
            return job

    def run_issue_text(self, job: Job) -> tuple[str, str]:
        """Title and body of the job's Run issue, built from its ``run_dir`` (raises when it cannot)."""

        return run_issue_mod.issue_text(job, self.store.jobs(), self.benchmark_dir)

    def backfill_run_issue(self, job: Job) -> int | None:
        """The same path as at a job's end, for a job that ended before the daemon made Run issues (#164)."""

        job = self._keep_run_issue_body(job)
        return self.create_run_issue(job)

    def _parent_issue(self) -> int | None:
        if self._run_issue_parent is None:
            try:
                cfg = json.loads((PROJECT_ROOT / "config" / "orchestration.json").read_text(encoding="utf-8"))
                self._run_issue_parent = int(cfg["runs_parent_issue"])
            except Exception as exc:
                self.log(f"run issue: no runs_parent_issue in config/orchestration.json ({exc!r})")
        return self._run_issue_parent

    def _make_run_issue(self, title: str, body: str) -> int | None:
        """Create the issue; its number, ``None`` when the create failed."""

        return self.gh.create_issue(title, body, list(RUN_ISSUE_LABELS))

    def _attach_run_issue(self, number: int) -> None:
        parent = self._parent_issue()
        if parent is None or not self.gh.add_sub_issue(parent, number):
            self.log(f"run issue #{number}: not attached under the parent yet; retrying next tick")
            self._run_issue_attach.add(number)
        else:
            self._run_issue_attach.discard(number)

    def create_run_issue(self, job: Job) -> int | None:
        """Create this host's own job's Run issue, once. ``None`` when nothing was (or could be) created."""

        if job.run_issue is not None or not job.run_issue_body or not job.run_issue_title:
            return None
        number = self._make_run_issue(job.run_issue_title, job.run_issue_body)
        if number is None:
            self.log(f"job {job.id}: the Run issue did not post; retrying next tick")
            return None
        # Recorded the moment the issue exists, before the attach: a retry must never create twice.
        self.store.record_run_issue(job.id, number)
        self._attach_run_issue(number)
        return number

    def retry_run_issues(self) -> None:
        if self.handback != "remote":
            for job in self.store.jobs():
                if (job.run_issue is None and job.run_issue_body and job.state in ("done", "failed", "stopped")
                        and run_issue_mod.is_whole_set_job(job)):
                    self.create_run_issue(job)
        for number in sorted(self._run_issue_attach):
            self._attach_run_issue(number)

    def _label_open_issue(self, job_id: str, issue: int, path: str) -> bool:
        """The one place the run queue adds the hand-back label (#803): only an open issue, one log line each.

        True = done (label added, or the issue is closed and skipped); False = retry later.
        """

        opener = getattr(self.gh, "issue_open", None)
        is_open = opener(issue) if opener is not None else True
        if is_open is None:
            self.log(f"job {job_id}: #{issue} state unreadable; '{self.label}' not added ({path}); retrying")
            return False
        if not is_open:
            self.log(f"job {job_id}: #{issue} is closed; '{self.label}' not added ({path})")
            return True
        if not self.gh.add_label(issue, self.label):
            return False
        self.log(f"job {job_id}: '{self.label}' added to #{issue} ({path})")
        return True

    def _handback(self, job: Job) -> bool:
        """One issue comment plus the ``ready-for-agent`` label. False when it must be retried.

        In ``handback="remote"`` mode (issue #118, the laptop) this never calls ``gh`` at all: the
        rendered body is written once to the job record (idempotent -- a later call with the body
        already stored does nothing) for another host's daemon to post on this one's behalf.
        """

        if not job.all_issues or not job.handback_pending:
            return True
        if self.handback == "remote":
            if not job.handback_body:
                try:
                    self.store.record_handback(job.id, self.comment_body(job))
                except Exception as exc:
                    self.log(f"job {job.id}: could not store its hand-back body ({exc!r})")
            return True
        ok = True
        body = self.comment_body(job)
        for issue in job.all_issues:     # the own issue, then the issues of refused identical submits (#468)
            own = job.issue is not None and issue == int(job.issue)
            if job.posted if own else issue in job.posted_extra:
                continue
            if not self.gh.comment(issue, body):
                self.log(f"job {job.id}: the issue #{issue} comment did not post; retrying next tick")
                ok = False
                continue
            # Recorded the moment the comment is out, before the label: a retry must never post twice.
            if own:
                self.store.mark_posted(job.id)
            else:
                self.store.mark_posted(job.id, issue)
            if job.state == "stopped" or job.no_label:
                continue    # no_label (#515): the comment only; a stop the brain made on purpose: the comment names the requeue, no ORCH starts (#421)
            if self._issue_has_other_live_job(job, issue=issue):
                continue    # the issue's last job gives the label, not this one (#405)
            paused = self._issue_paused(job.id, issue)
            if paused:
                continue    # the brain's pause stands (#654): the comment only
            if paused is None:
                self._label_retry.add((job.id, issue))   # comments unreadable: the retry asks again
                ok = False
                continue
            if not self._label_open_issue(job.id, issue, "handback"):
                self.log(f"job {job.id}: '{self.label}' not added to #{issue}; retrying next tick")
                self._label_retry.add((job.id, issue))
                ok = False
        return ok

    def _issue_paused(self, job_id: str, issue: int) -> bool | None:
        """Whether ``issue`` is paused (#654); ``None`` when its comments could not be read.

        Paused = the newest comment that is not a runs-daemon hand-back starts with
        :data:`PAUSE_PREFIX`. Hand-backs are skipped because this job's own result comment is
        posted just before the label step, and another job of the issue may have posted one too.
        """

        reader = getattr(self.gh, "existing_comments", None)
        comments = reader(issue) if reader is not None else []
        if comments is None:
            self.log(f"handback {job_id}: #{issue} comments unreadable, label held for the retry")
            return None
        if _newest_is_pause(comments):
            self.log(f"handback {job_id}: #{issue} paused, label left off")
            return True
        return False

    def _issue_has_other_live_job(
        self, job: Job, remote_jobs: Iterable[Job] = (), *, issue: int | None = None,
    ) -> bool:
        """Whether another job of ``job``'s issue is still ``queued`` (held ones included) or ``running``.

        Both hosts' stores count: this host's own, the jobs just read from another host
        (``remote_jobs``) and the other hosts' jobs as the last remote pass saw them (#405).
        """

        seen: dict[str, Job] = {j.id: j for jobs in self._remote_jobs_seen.values() for j in jobs}
        seen.update((j.id, j) for j in remote_jobs)
        seen.update((j.id, j) for j in self.store.jobs())
        target = job.issue if issue is None else issue
        return bool(live_jobs_of_issue(seen.values(), target, exclude_id=job.id))

    def retry_handbacks(self) -> list[str]:
        """Post the hand-backs that failed earlier: a comment is never lost and never duplicated."""

        done: list[str] = []
        for job in self.store.jobs():
            if not job.all_issues or not job.handback_pending or job.state not in ("done", "failed", "stopped"):
                continue
            if not job.end_ts:
                continue
            if self._handback(job):
                done.append(job.id)
        for job_id, issue in sorted(self._label_retry):
            paused = self._issue_paused(job_id, issue)
            if paused is None:
                continue
            if paused:
                self._label_retry.discard((job_id, issue))
                continue
            if self._label_open_issue(job_id, issue, "label retry"):
                self._label_retry.discard((job_id, issue))
                done.append(job_id)
        return done

    # -- the remote hand-back pass (issue #118 requirement 2) -----------------------------------

    def remote_handback_pass(self) -> list[str]:
        """Post another host's stored hand-backs, at most once every ``remote_pass_seconds``.

        For every host in ``config/hosts.json`` other than this one: read its own job store (over
        ssh, #81/#120); for every job that ended with an issue, a stored hand-back body and no
        ``posted`` mark, post the comment (unless the issue already carries one with
        :data:`RUNS_DAEMON_MARKER` and this job's id -- a crash between an earlier post and its
        mark), add the label, then mark the job posted IN THAT HOST'S OWN STORE (``runs.py
        mark-posted``, over ssh, #120). The same round trip brings back that host's daemon status, so
        a laptop's daemon status is read too. A host whose store cannot be read is skipped for this pass
        with no anomaly of its own (#119 already covers "laptop unreachable"); a post or mark that
        fails here is retried on the NEXT pass, never hammered every tick.
        """

        now = self.clock()
        if self._last_remote_pass is not None and (now - self._last_remote_pass) < self._remote_pass_seconds:
            return []
        self._last_remote_pass = now

        done: list[str] = []
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
        except Exception as exc:
            self.log(f"remote handback: could not load config/hosts.json ({exc!r})")
            return done

        all_read = True
        for host, host_cfg in config.items():
            if host == self.host or not host_cfg.get("ssh"):
                continue                # self, or a host with no ssh alias (local to its own daemon)
            started = time.monotonic()
            try:
                jobs, status = self._read_remote(host_cfg, host)
            except remote_store_mod.RemoteJobsLogMissing as exc:
                all_read = False        # #910: the host answers, its job log is not where hosts.json says
                self.log(f"remote handback: {host}'s job log is missing at {exc.path}; "
                         "fix jobs_log_path in config/hosts.json; skipping this pass")
                self._note_handback(host, True)
                self.note_remote_read(host, True)
                continue
            except Exception as exc:
                all_read = False
                why = (str(exc) if isinstance(exc, remote_store_mod.RemoteStoreUnreachable)
                       else runs_hosts.describe_ssh_failure(exc, time.monotonic() - started))
                self.log(f"remote handback: {host} unreachable ({why}); skipping this pass")
                self._note_handback(host, False)
                self.note_remote_read(host, False)
                continue
            self._note_handback(host, True)
            self.note_remote_read(host, True)
            self._remote_jobs_seen[host] = list(jobs)
            for job in jobs:
                self._remote_run_issue(host, host_cfg, job)
            for job in jobs:
                if not job.handback_pending or not job.handback_body:
                    continue
                if not job.all_issues or job.state not in ("done", "failed", "stopped"):
                    continue
                failed = False
                body = job.handback_body
                try:
                    body = self._requeue_on_pc(job, body)
                except Exception as exc:
                    self.log(f"remote handback: could not requeue job {job.id} on pc ({exc!r}); retrying next pass")
                    continue
                for issue in job.all_issues:     # the own issue and the refused-identical submits' issues (#468)
                    if _comment_has_marker(self.gh.existing_comments(issue), job.id):
                        continue
                    if not self.gh.comment(issue, body):
                        self.log(f"remote handback: job {job.id}'s comment on #{issue} "
                                 "did not post; retrying next pass")
                        failed = True
                        continue
                    if job.state == "stopped" or job.no_label or self._issue_has_other_live_job(job, jobs, issue=issue):
                        continue
                    paused = self._issue_paused(job.id, issue)
                    if paused is None:
                        self._label_retry.add((job.id, issue))   # comments unreadable: the retry asks again
                    elif not paused and not self._label_open_issue(job.id, issue, "remote handback"):
                        self.log(f"remote handback: '{self.label}' not added to #{issue}")
                if failed:
                    continue
                if not self._remote_mark_posted(host_cfg, host, job.id):
                    self.log(f"remote handback: could not mark job {job.id} posted on {host}; "
                             "retrying next pass")
                    continue
                done.append(job.id)
        if all_read:
            self._sweep_pin_refs()
        return done

    def _sweep_pin_refs(self) -> None:
        """#756 rule 2: a pin ref on origin that no queued/running job of any host holds is deleted from here.

        Only the host with write access to origin (hand-back not ``remote``) sweeps, and only on a pass that
        read every other host (an unread store could hold a live pin).
        """

        sweep = getattr(self.queue, "sweep_pin_refs", None)
        if self.handback == "remote" or sweep is None:
            return
        try:
            jobs = list(self.store.jobs()) + [j for js in self._remote_jobs_seen.values() for j in js]
            held = [j.pin for j in jobs if j.pin and j.state in ("queued", "running")]
            for j in self.store.jobs():   # #889: a moved job's copy not yet in the target host's view keeps the pin
                host, _, new_id = (j.moved_to or "").partition(":")
                if j.pin and new_id and new_id not in {r.id for r in self._remote_jobs_seen.get(host, ())}:
                    held.append(j.pin)
            for msg in sweep(held, self._pin_sweep_failed):
                self.log(f"pin sweep: {msg}")
        except Exception as exc:
            self.log(f"pin sweep failed ({exc!r})")

    def _requeue_on_pc(self, job: Job, body: str) -> str:
        """#642: a laptop job that lacked ``artifacts/...`` or only skipped its reading runs again on THIS host.

        Returns the comment body, with the ``requeued on pc as <id>`` line when it was requeued. Once: a job that
        ran here, that carries ``requeued_from`` or is not a laptop result is never requeued, and a PC job already
        written for this laptop job id is reused, so a second pass (or a crash between submit and the posted
        mark) never writes another.
        """

        if job.host == self.host or job.requeued_from or job.state not in ("done", "failed"):
            return body
        lines = body.splitlines()
        if job.state == "failed" and job.rc not in (None, 0):
            lacks = gate_mod.missing_artifact(lines)
            why = f"the laptop lacks {lacks}" if lacks else None
        elif job.state == "done" and job.rc == 0 and gate_mod.SKIPPED_VERDICT in body:
            path = gate_mod.skip_path(lines)
            why = f"the laptop lacks {path}" if path else "the laptop skipped the test (no reading)"
        else:
            why = None
        if why is None:
            return body
        known = next((j for j in self.store.jobs() if j.requeued_from == job.id), None)
        if known is None:
            try:
                known = self.store.submit(
                    host=self.host, priority=job.priority, tag=job.tag, cmd=job.cmd, issue=job.issue,
                    submitter=job.submitter, pin=job.pin, resumable=job.resumable, workers=job.workers,
                    job_class=job.job_class, argv=job.argv, rc_is_reading=job.rc_is_reading,
                    no_label=job.no_label, host_fixed=True, workers_auto=job.workers_auto,
                    note=f"requeued from {job.id}", requeued_from=job.id)
            except store_mod.DuplicateTag:
                return body     # the tag is live here already: an ordinary result
        line = f"- requeued on pc as {known.id}: {why}"
        at = next((i for i, text in enumerate(lines) if text.startswith("- job:")), None)
        if at is None:
            return body.rstrip("\n") + "\n" + line + "\n"
        lines.insert(at, line)
        return "\n".join(lines) + "\n"

    def _origin_job_state(self, host: str, job_id: str) -> str | None:
        """A job's state in another host's store, from the jobs this tick's remote pass already read."""

        for job in self._remote_jobs_seen.get(host, ()):
            if job.id == job_id:
                return job.state
        return None

    def remote_anomaly_pass(self) -> list[str]:
        """Start the keymasters of another host's anomalies HERE (#467).

        The laptop has no `claude` login: its guard only queues (`start_keymasters` off). For every
        other host with an ssh alias, read its `var/anomalies.json` over ssh and hand each queued entry to
        the guard (`adopt_remote`), which queues it under the host-prefixed key and marks it taken on the
        host; the guard's normal start loop (back-off, one session at a time) then starts the keymaster
        in this tick's `_check_anomalies`. Rate-limited like the hand-back pass; an unreachable host is
        skipped (its own `host_unreachable` anomaly exists already).
        """

        guard = self.anomaly_guard
        adopt = getattr(guard, "adopt_remote", None)
        if adopt is None or not getattr(guard, "start_keymasters", False):
            return []
        if self._remote_anomaly_reader is None and self._remote_store_reader is not None:
            return []
        now = self.clock()
        if (self._last_remote_anomaly_pass is not None
                and (now - self._last_remote_anomaly_pass) < self._remote_pass_seconds):
            return []
        self._last_remote_anomaly_pass = now
        try:
            config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
        except Exception as exc:
            self.log(f"remote anomalies: could not load config/hosts.json ({exc!r})")
            return []
        taken: list[str] = []
        for host, host_cfg in config.items():
            if host == self.host or not host_cfg.get("ssh"):
                continue
            try:
                reader = self._remote_anomaly_reader or remote_store_mod.read_remote_anomalies
                entries = list(reader(host_cfg))
            except Exception as exc:
                self.log(f"remote anomalies: {host} queue unreadable ({exc!r}); skipping this pass")
                self.note_remote_read(host, False)
                continue
            self.note_remote_read(host, True)
            if not entries:
                continue
            try:
                if host not in self._remote_jobs_seen and any(e.get("kind") == "job_stuck" for e in entries):
                    try:
                        self._remote_jobs_seen[host] = list(self._read_remote(host_cfg, host)[0])
                    except Exception as exc:
                        self.log(f"remote anomalies: {host}'s jobs unreadable ({exc!r})")
                adopted = adopt(host, entries, lambda key, h=host, c=host_cfg:
                                self._remote_mark_anomaly_taken(c, h, key),
                                lambda job_id, h=host: self._origin_job_state(h, job_id))
            except Exception as exc:
                self.log(f"remote anomalies: adopting {host}'s queue failed ({exc!r})")
                continue
            taken += [a.key for a in adopted]
        return taken

    # -- the gate copy to the laptop (#642 rule 1) ----------------------------------------------

    def gate_sync_pass(self) -> None:
        """Keep the laptop holding the PC's newest weekly gate dir (``artifacts/benchmark/<name>``).

        Only the PC daemon. One background ``scp -r`` into ``<name>.partial`` under the laptop daemon
        checkout's ``artifacts/benchmark`` (a snapshot's ``artifacts`` is a junction to that checkout, so that
        is where a laptop job reads it), polled on later ticks; on rc 0 a remote rename to ``<name>`` and
        ``record_gate``. At most one attempt start per ``gate_sync_seconds``; a laptop whose last remote read
        failed is not tried (the mkdir ssh call would block the tick). Never raises.
        """

        if self.host != "pc" or self._gate_artifacts is None:
            return                      # off unless `runs.py daemon` (or a test) names the artifacts root
        try:
            self._gate_sync()
        except Exception as exc:
            self.log(f"gate_sync: pass failed ({exc!r})")
            self._gate_copy = None

    def _gate_sync(self) -> None:
        from junkroan.runs import gates as gates_mod
        from junkroan.runs.ssh_transport import build_scp_argv

        copy = self._gate_copy
        if copy is not None:
            rc = copy["proc"].poll()
            if rc is None:
                if self.clock() - copy["started"] > GATE_COPY_LIMIT_SECONDS:
                    # #1000 row 2: a copy past its limit is killed; the next tick's cadence check starts it again
                    self._kill_copy(copy["proc"])
                    self._gate_copy = None
                    self.log(f"gate_sync: copy of {copy['name']} to laptop ran over "
                             f"{human_duration(GATE_COPY_LIMIT_SECONDS)}; killed, retried on a later tick")
                return
            self._gate_copy = None
            name = copy["name"]
            if rc != 0:
                self.log(f"gate_sync: copy of {name} to laptop failed rc {rc}")
                return
            run = self._gate_run_on_host or runs_hosts.run_on_host
            final, partial = copy["final"], copy["partial"]
            result = run(copy["cfg"], _rename_script(final, partial, name))
            if getattr(result, "returncode", 1) != 0:
                self.log(f"gate_sync: rename of {name} on laptop failed rc {getattr(result, 'returncode', 1)}")
                return
            gates_mod.record_gate("laptop", name, self._gates_path)
            self.log(f"gate_sync: laptop now holds {name} ({copy['size']} in "
                     f"{human_duration(self.clock() - copy['started'])})")
            return

        now = self.clock()
        if self._last_gate_attempt is not None and (now - self._last_gate_attempt) < self._gate_sync_seconds:
            return
        artifacts = self._gate_artifacts if self._gate_artifacts is not None else gates_mod.ROOT / "artifacts"
        name = gates_mod.newest_gate(artifacts)
        if name is None or name in gates_mod.gates_present("laptop", self._gates_path):
            return
        if "laptop" in self._remote_fail_at:
            return                      # unreachable at the last remote read: retry when it reads again
        config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
        cfg = config.get("laptop")
        if not cfg or not cfg.get("ssh"):
            return
        self._last_gate_attempt = now
        bench, final, partial = _laptop_dir_paths(cfg, f"benchmark/{name}")
        run = self._gate_run_on_host or runs_hosts.run_on_host
        prep = run(cfg, _prep_script(bench, partial))
        if getattr(prep, "returncode", 1) != 0:
            self.log(f"gate_sync: copy of {name} to laptop failed rc {getattr(prep, 'returncode', 1)}")
            return
        local = Path(artifacts) / "benchmark" / name
        total = _tree_size(local, seconds=GATE_SIZE_WALK_SECONDS, max_entries=GATE_SIZE_WALK_MAX_ENTRIES,
                           clock=self.clock)
        size = "size unknown" if total is None else f"{total / 1e6:.0f} MB"  # #1000: over the walk's cap = unknown
        argv = build_scp_argv(cfg, str(local), partial)
        proc = self._gate_popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=_JOB_CREATIONFLAGS)
        self._gate_copy = {"name": name, "proc": proc, "cfg": cfg, "final": final, "partial": partial,
                           "started": now, "size": size}
        self.log(f"gate_sync: copying {name} to laptop ({size})")

    def _kill_copy(self, proc: Any) -> None:
        """#1000 row 2: kill a copy's whole tree (`scp` runs `ssh`), then the process itself; never raises."""

        try:
            self._copy_killer(proc.pid)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def row_sync_pass(self) -> int:
        """#753: bring the laptop's finished week-folder rows to the PC (see ``row_sync``). Only the PC, only
        while the week's folder is open, at most every ``ROW_SYNC_SECONDS``; a lost link is a quiet skip."""

        if self.host != "pc" or self._cut_repo is None or "laptop" in self._remote_fail_at:
            return 0
        try:
            folder = weekly_cut.find_week_folder(self._cut_repo, weekly_cut.monday_of(self.timestamp()))
            if folder is None:
                return 0
            if self._row_sync is None:
                config = self._hosts_config if self._hosts_config is not None else runs_hosts.load_hosts_config()
                cfg = config.get("laptop")
                if not cfg or not cfg.get("ssh"):
                    return 0
                self._row_sync = row_sync_mod.RowSync(
                    self._row_transport or row_sync_mod.SshTransport(cfg), lambda m: self.log(m))
            return self._row_sync.run(folder, self.clock())
        except Exception as exc:
            self.log(f"row_sync: pass failed ({exc!r})")
            return 0

    def copy_dir_to_host(self, host: str, cfg: Mapping[str, Any], rel: str) -> bool:
        """#701: copy ``artifacts/<rel>`` (``replay/<dir>`` or ``benchmark/<dir>``) to ``host``'s daemon checkout
        with gate_sync's transport (scp into ``<dir>.partial``, remote rename, ``record_gate``); synchronous,
        bounded by ``COPY_DIR_SECONDS`` (#1000: a copy that does not finish in that is logged and skipped for the pass).
        True when the laptop holds it afterwards. Never raises."""

        from junkroan.runs import gates as gates_mod
        from junkroan.runs.ssh_transport import build_scp_argv

        try:
            artifacts = self._gate_artifacts if self._gate_artifacts is not None else gates_mod.ROOT / "artifacts"
            local = Path(artifacts) / rel
            name = rel.rsplit("/", 1)[-1]
            parent, final, partial = _laptop_dir_paths(cfg, rel)
            if not local.is_dir():
                self.log(f"copy_dir: {rel} is not a directory on this host")
                return False
            run = self._gate_run_on_host or runs_hosts.run_on_host
            prep = run(cfg, _prep_script(parent, partial))
            if getattr(prep, "returncode", 1) != 0:
                self.log(f"copy_dir: copy of {rel} to {host} failed rc {getattr(prep, 'returncode', 1)}")
                return False
            argv = build_scp_argv(cfg, str(local), partial)
            proc = self._dir_copy_run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=_JOB_CREATIONFLAGS,
                                      timeout=COPY_DIR_SECONDS)
            if getattr(proc, "returncode", 1) != 0:
                self.log(f"copy_dir: copy of {rel} to {host} failed rc {getattr(proc, 'returncode', 1)}")
                return False
            result = run(cfg, _rename_script(final, partial, name))
            if getattr(result, "returncode", 1) != 0:
                self.log(f"copy_dir: rename of {rel} on {host} failed rc {getattr(result, 'returncode', 1)}")
                return False
            gates_mod.record_gate(host, gates_mod.dir_key(rel), self._gates_path)
            self.log(f"copy_dir: {host} now holds {rel}")
            return True
        except Exception as exc:
            self.log(f"copy_dir: copy of {rel} to {host} failed ({exc!r})")
            return False

    def _remote_run_issue(self, host: str, host_cfg: Mapping[str, Any], job: Job) -> None:
        """Create another host's Run issue from the body its daemon kept (#164), once."""

        if job.run_issue is not None or not job.run_issue_body or not job.run_issue_title:
            return
        key = (host, job.id)
        number = self._remote_run_issues.get(key)
        if number is None:
            number = self._make_run_issue(job.run_issue_title, job.run_issue_body)
            if number is None:
                self.log(f"remote handback: job {job.id}'s Run issue did not post; retrying next pass")
                return
            self._remote_run_issues[key] = number
            self._attach_run_issue(number)
        if self._remote_mark_run_issue(host_cfg, host, job.id, number):
            self._remote_run_issues.pop(key, None)
        else:
            self.log(f"remote handback: could not record Run issue #{number} of job {job.id} on {host}; "
                     "retrying the receipt next pass")

    def note_remote_read(self, host: str, ok: bool) -> None:
        """#518: record a remote read of ``host``; a failure stamps the clock, ONE later success clears it."""

        if ok:
            self._remote_fail_at.pop(host, None)
        else:
            self._remote_fail_at[host] = self.clock()

    def remote_failed_ago(self, host: str) -> float | None:
        """Seconds since ``host``'s last failed remote read when no success came after it; else None."""

        at = self._remote_fail_at.get(host)
        return None if at is None else max(0.0, self.clock() - at)

    def _note_handback(self, host: str, ok: bool) -> None:
        """Feed the anomaly guard's hand-back streak (#308); a bad guard must not break the pass."""

        note = getattr(self.anomaly_guard, "note_handback", None)
        if note is None:
            return
        try:
            note(host, ok)
        except Exception as exc:
            self.log(f"anomaly guard note_handback failed ({exc!r})")

    def _read_remote_snapshot(self, host_cfg: Mapping[str, Any], host: str) -> Any:
        """The whole remote snapshot (jobs, daemon status, budget) -- ONE ssh round trip unless a test
        injects a reader (then ``budget`` is None)."""

        if self._remote_store_reader is not None:
            jobs = list(self._remote_store_reader(host_cfg))
            status = self._remote_status_reader(host_cfg, host) if self._remote_status_reader else None
            return remote_store_mod.RemoteSnapshot(jobs=jobs, daemon_status=status, budget=None)
        return remote_store_mod.read_remote_snapshot(host_cfg, host=host)

    def _read_remote(self, host_cfg: Mapping[str, Any], host: str) -> tuple[list[Job], Mapping[str, Any] | None]:
        """``(jobs, daemon status)`` of another host -- ONE ssh round trip unless a test injects."""

        snapshot = self._read_remote_snapshot(host_cfg, host)
        return list(snapshot.jobs), snapshot.daemon_status

    # -- the comment ------------------------------------------------------------------------------

    def comment_body(self, job: Job) -> str:
        """The hand-back comment: what ran, how it ended, how long it took, where to look.

        Starts with ``RUNS_DAEMON_MARKER`` (issue #50) so a dispatcher can tell "this is a
        runs-daemon result" from an issue's latest comment alone, without parsing its text.
        """

        duration = human_duration(self._duration(job))
        verdict = "rc 0 (done)" if job.rc == 0 else f"rc {job.rc if job.rc is not None else 'null'} ({job.state})"
        if job.rc_is_reading and job.rc is not None:
            verdict = f"rc {job.rc} (reading)"
        if job.rc == 0 and job.state == "done" and gate_mod.skipped_without_reading(
                job.cmd, job.rc, gate_mod.out_tail_lines(job.out)):
            verdict = gate_mod.SKIPPED_VERDICT      # a skip is no pass (#642)
        if (job.reason or "").startswith("stopped by "):
            headline = (f"Run `{job.tag}` was stopped on host `{job.host}` after {duration}; "
                        "it did not finish and needs a requeue.")
        else:
            headline = f"Run `{job.tag}` finished on host `{job.host}`: {verdict} in {duration}."
        lines = [
            RUNS_DAEMON_MARKER,
            headline,
            "",
            f"- job: `{job.id}` ({job.priority}, {max(1, job.workers)} worker(s))",
            f"- command: `{job.cmd}`",
        ]
        if job.pin:
            lines.append(f"- pinned commit: `{job.pin}`")
        if job.reason:
            lines.append(f"- reason: {job.reason}")
        if job.state in ("stopped", "failed"):
            lines += self._held_followers_lines(job)
        if job.state == "failed":
            lines.append(f"- {self._load_line(job)}")
            missing = self._missing_script_line(job)
            if missing:
                lines.append(f"- {missing}")
        if job.out:
            lines.append(f"- out file: `{job.out}`")
        if job.run_dir:
            lines.append(f"- run dir: `{job.run_dir}`")
            table = self._results_table(Path(job.run_dir))
            if table is not None:
                lines.append(f"- results table: `{table}`")
        tail = self._out_tail(job.out)
        if tail:
            lines += ["", f"Last {OUT_TAIL_LINES} lines of the out file:", "", "```", *tail, "```"]
        return "\n".join(lines) + "\n"

    def _held_followers_lines(self, job: Job) -> list[str]:
        """The queued ``--after`` followers a stopped job holds, each with its two release commands (#422)."""

        try:
            held = [(f, dep) for f, dep, _status in self.store.held_jobs() if dep is not None and dep.id == job.id]
        except Exception:
            return []
        if not held:
            return []
        if job.state == "failed":
            lines = ["", f"Held by this failure ({len(held)} follower(s), never started):"]
            for follower, _dep in held:
                lines.append(f"- `{follower.id}` (`{follower.tag}`): held, predecessor `{job.id}` failed "
                             f"(rc {job.rc if job.rc is not None else 'null'} after {human_duration(self._duration(job))}); "
                             f"release with `python scripts/runs.py requeue {job.id}` (run the predecessor again) "
                             f"or `python scripts/runs.py cancel {follower.id}` (drop the follower)")
            return lines
        lines = ["", "Held by this stop (never started, no anomaly raised):"]
        for follower, _dep in held:
            lines.append(f"- `{follower.id}` (`{follower.tag}`): release with "
                         f"`python scripts/runs.py requeue {job.id}` (run the predecessor again) "
                         f"or `python scripts/runs.py cancel {follower.id}` (drop the follower)")
        return lines

    def _missing_script_line(self, job: Job) -> str | None:
        """#862 rule 4: a non-zero rc within 60 s of the start whose out tail names a missing file."""

        duration = self._duration(job)
        if job.rc in (None, 0) or duration is None or duration > MISSING_SCRIPT_SECONDS:
            return None
        tail = " ".join(self._out_tail(job.out))
        if not re.search(r"can't open file|No such file or directory|cannot find the (?:file|path)", tail, re.I):
            return None
        head = self._host_head() or job.pin
        if not head:
            return "the script does not exist on this host (the host's commit is unreadable)"
        return f"the script does not exist on this host at {head[:12]}"

    def _host_head(self) -> str | None:
        """The commit this host's checkout is at (read like :meth:`_host_behind`), or None."""

        res = _guarded_git(["git", "-C", str(self._host_checkout), "rev-parse", "HEAD"], key=GIT_READ_KEY,
                           timeout=GIT_READ_SECONDS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if res is None:
            return None
        return res.stdout.strip() or None if res.returncode == 0 else None

    @staticmethod
    def _results_table(run_dir: Path) -> Path | None:
        for name in ("report.md", "results.json"):
            candidate = run_dir / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _out_tail(out: str | None, limit: int = OUT_TAIL_LINES) -> list[str]:
        if not out:
            return []
        path = Path(out)
        try:
            if not path.is_file():
                return []
            return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except Exception:
            return []

    # -- small helpers ----------------------------------------------------------------------------

    def _duration(self, job: Job) -> float | None:
        if not job.start_ts or not job.end_ts:
            return None
        try:
            return (datetime.fromisoformat(job.end_ts) - datetime.fromisoformat(job.start_ts)).total_seconds()
        except Exception:
            return None

    @staticmethod
    def _epoch(ts: str | None) -> float:
        if not ts:
            return time.time()
        try:
            return datetime.fromisoformat(ts).timestamp()
        except Exception:
            return time.time()

    def _append_event(self, event: dict[str, Any]) -> None:
        try:
            runs_hosts.append_event(event, path=self.events_file)
        except Exception as exc:
            self.log(f"could not append an event ({exc!r}): {event}")

    # -- the loop ---------------------------------------------------------------------------------

    def _restart_gate(self, report: TickReport) -> bool:
        """Self-restart (#340, #489, #598): never holds starts; ``report.restarting`` = replacement started.

        Runs right after `reap`, before `fill`. New starts go on as if HEAD had not moved. The daemon
        respawns at the first tick with no running job, or `RESTART_MAX_WAIT_SECONDS` after the move was
        first seen (a later move does not reset that wait), adopting the running jobs through
        `recover()`. A running filler is adopted too and holds nothing (#751 rule 6, #517).
        Returns True only when the tick must end (the replacement started).
        """

        if self._restart_watch is None or self._respawn is None:
            return False
        if self._follow_main is not None:
            try:
                self._follow_main.step()
            except Exception as exc:
                self.log(f"follow main failed ({exc!r}); continuing")
        try:
            due = self._restart_watch.due()
        except Exception as exc:
            self.log(f"restart watch failed ({exc!r}); continuing")
            return False
        if due is None:
            self._move_first_seen = None
            return False
        start, head = due
        now = self.clock()
        if self._move_first_seen is None:
            self._move_first_seen = now
        # #751 rule 6: a running filler is adopted like any other job; it is never stopped for a restart
        # and never holds one (the wait below counts only jobs that are not fillers).
        running = self.running_jobs()
        filler_ids = {job.id for job in running if job.is_filler}
        kept = [job for job in running if not job.is_filler]
        idle = not (kept or any(a_id not in filler_ids for a_id in self._active))
        if not idle and now - self._move_first_seen - _stood(self._move_first_seen, now) < RESTART_MAX_WAIT_SECONDS:
            return False
        line = f"restart at boundary: {start[:12]} -> {head[:12]}"
        if kept:
            line += f", adopting {len(kept)} running job(s)"
        self.log(line)
        try:
            self._respawn()
        except Exception as exc:
            self.log(f"restart at boundary failed ({exc!r}); continuing")
            return False
        self._move_first_seen = None
        report.restarting = True
        return True

    def run(
        self, *, ticks: int | None = None, interval: float = TICK_SECONDS,
        sleep: Callable[[float], None] = time.sleep, load_thread: bool = False,
    ) -> int:
        """Recover, then tick every ``interval`` seconds for ever (or ``ticks`` times, in tests).
        ``load_thread`` (the real daemon, #768) takes the load record on its own thread for the run."""

        if load_thread:
            self.start_load_thread()
        try:
            return self._run_loop(ticks=ticks, interval=interval, sleep=sleep)
        finally:
            if load_thread:
                self.stop_load_thread()

    def _run_loop(self, *, ticks: int | None, interval: float, sleep: Callable[[float], None]) -> int:
        self.recover()
        self.write_status(interval=interval)
        done = 0
        while ticks is None or done < ticks:
            restarting = False
            try:
                restarting = self.tick().restarting
            except Exception as exc:  # one bad tick must not end the daemon
                self.log(f"tick failed ({exc!r}); continuing")
            self.write_status(interval=interval)
            if restarting:
                return 0
            done += 1
            if ticks is not None and done >= ticks:
                break
            pause = min(interval, TICK_SECONDS)
            to_sample = self.seconds_to_load_sample()
            if to_sample is not None and not self.load_thread_running:  # #768: wake when the load sample is due, not a whole tick late
                pause = min(pause, max(to_sample, 0.5))
            sleep(max(0.0, pause))
        return 0


# -- requirement 5: `runs watch` ------------------------------------------------------------------

def _complete_event_lines(path: Path) -> list[str]:
    """Every finished line of the events log; a half-written last line is not an event yet."""

    try:
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    parts = text.split("\n")
    return [line for line in parts[:-1] if line.strip()]


def watch_next_event(
    path: Path | None = None,
    *,
    timeout: float | None = None,
    poll: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Block until one more line appears in the events log, return it. ``None`` on timeout.

    Lines already in the file when the call starts are the past: only the NEXT one returns.
    """

    target = Path(path) if path is not None else runs_hosts.events_path()
    seen = len(_complete_event_lines(target))
    deadline = None if timeout is None else clock() + timeout
    while True:
        lines = _complete_event_lines(target)
        if len(lines) > seen:
            return lines[seen]
        if deadline is not None and clock() >= deadline:
            return None
        sleep(poll)


_DECLARED_WORKERS_RE = re.compile(r"--workers(?:=|\s+)(\d+|auto)\b")


def declared_workers(cmd: str | None, argv: Iterable[str] | None = None) -> int | str | None:
    """The command's own ``--workers`` value (#570): an int, the word ``"auto"``, or None when it has none."""

    values: list[str] = []
    if argv:
        items = [str(a) for a in argv]
        for i, a in enumerate(items):
            if a == "--workers" and i + 1 < len(items):
                values.append(items[i + 1])
            elif a.startswith("--workers="):
                values.append(a[10:])
    elif cmd:
        values = [m.group(1) for m in _DECLARED_WORKERS_RE.finditer(cmd)]
    if not values:
        return None
    first = values[0].strip().lower()
    if first == "auto":
        return "auto"
    return max(1, int(first)) if first.isdigit() else None


_SCRIPT_RE = re.compile(r"""(?:^|[\s"'])((?:[\w.:\-]+[/\\])*scripts[/\\][\w.\-]+\.py)(?![\w.])""")
_WORKERS_OPTION_RE = re.compile(r"""add_argument\(\s*["']--workers["']""")


def script_has_workers_option(cmd: str | None, argv: Iterable[str] | None = None, root: Path | None = None) -> bool:
    """Whether the command runs a ``scripts/<x>.py`` whose own parser has a ``--workers`` option (#700).

    Read from the script's source, so a new script cannot drift from a hand-kept list."""

    base = root or PROJECT_ROOT
    text = " ".join(str(a) for a in argv) if argv else (cmd or "")
    for match in _SCRIPT_RE.finditer(text):
        path = Path(match.group(1).replace("\\", "/"))
        path = path if path.is_absolute() else base / path
        try:
            if _WORKERS_OPTION_RE.search(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def parse_workers(cmd: str, default: int = 1) -> int:
    """``--workers N`` / ``--workers=N`` in a command line (``import-queue`` reads it), else 1."""

    match = re.search(r"--workers[=\s]+(\d+)", cmd)
    if not match:
        return default
    return max(1, int(match.group(1)))


def _newest_is_pause(comments: list[str]) -> bool:
    """Whether the newest of ``comments`` that is not a runs-daemon hand-back is a pause (#654)."""

    for body in reversed(comments):
        if RUNS_DAEMON_MARKER in body:
            continue
        return body.lstrip().startswith(PAUSE_PREFIX)
    return False


def _comment_has_marker(comments: list[str] | None, job_id: str) -> bool:
    """Whether one of ``comments`` is already this job's hand-back (issue #118 requirement 2).

    ``None`` (``gh`` could not answer) is never treated as "yes" -- an unknown answer must not stop
    the daemon from trying to post, or a genuinely unposted job would wait for ever.
    """

    if not comments:
        return False
    needle = f"`{job_id}`"
    return any(RUNS_DAEMON_MARKER in body and needle in body for body in comments)


__all__ = [
    "Daemon",
    "FILLER_PRIORITY",
    "FILLER_REFRESH_SECONDS",
    "GhCli",
    "HANDBACK_LABEL",
    "HANDBACK_MODES",
    "HEAVY_WORKERS",
    "LOST_PROCESS_REASON",
    "lost_pid_reason",
    "ProcessLauncher",
    "QueueBackend",
    "REMOTE_HANDBACK_SECONDS",
    "RUNS_DAEMON_MARKER",
    "STALE_FLOOR_SECONDS",
    "STALE_MULTIPLIER",
    "TICK_SECONDS",
    "TickReport",
    "daemon_status_path",
    "parse_workers",
    "read_daemon_status",
    "run_queue",
    "stale_after",
    "status_liveness",
    "watch_next_event",
    "write_daemon_status",
]
