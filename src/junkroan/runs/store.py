"""Append-only JSONL job store for the keymaster (issue #40, part of the #36 scheduler design).

Nothing here executes a job (``junkroan.runs.daemon``, issue #48, does). This module only makes
jobs exist, fold to a current state, be listed and be cancelled, safely from many processes at once.

The log is ``artifacts/runs/jobs.jsonl`` (shared with worktrees and run snapshots through
directory junctions, like the rest of ``artifacts/runs``). Each line is one operation:
``{"ts": <iso8601>, "job": <id>, "op": "submit"|"start"|"end"|"stop"|"requeue"|"cancel"|"posted", ...}``.
A job's current state is the fold of its lines, in file order (:func:`fold`). Every write holds an
exclusive OS lock on a lock file next to the log (``jobs.jsonl.lock``); the OS releases the lock
when the holding process dies, so a killed writer never leaves the log stuck locked.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[3]


def main_root(root: Path) -> Path:
    """The main checkout for `root`: `root` itself, or, in a linked worktree (issue #180), the
    parent of the git common dir, read from the `.git` FILE (`gitdir: <main>/.git/worktrees/<wt>`)."""
    marker = Path(root) / ".git"
    if not marker.is_file():
        return Path(root)
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return Path(root)
    if not text.startswith("gitdir:"):
        return Path(root)
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = Path(root) / gitdir
    if gitdir.parent.name != "worktrees":
        return Path(root)  # a submodule or other gitdir file, not a linked worktree
    return gitdir.parent.parent.parent


MAIN_ROOT = main_root(ROOT)
DEFAULT_LOG = MAIN_ROOT / "artifacts" / "runs" / "jobs.jsonl"

HOSTS = ("pc", "laptop", "any")
PRIORITIES = ("P0", "P1", "P2")

#: A job's class. `run` is every job an issue (or a human) waits for -- the only class before #132.
#: `filler` is a Filler (`GLOSSARY.md`): a PoB job no issue waits for, submitted by a host's own
#: runs daemon (#751) when the machine is empty. It is ordered UNDER P2 (see `next_job`) and is killed
#: for every other job (`daemon.preempt_fillers_pass`).
CLASS_RUN = "run"
CLASS_FILLER = "filler"
CLASSES = (CLASS_RUN, CLASS_FILLER)
STATES = ("queued", "running", "done", "failed", "stopped", "cancelled")
OPS = ("submit", "start", "end", "stop", "requeue", "cancel", "posted", "handback", "moved", "runissue", "runissue_made", "add_issue", "moved_note")
LIVE_STATES = ("queued", "running")
TERMINAL_STATES = ("done", "failed", "stopped", "cancelled")

_PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITIES)}

# Which states an op may be applied from. `submit` is handled separately (it creates the job).
_ALLOWED_FROM: dict[str, tuple[str, ...]] = {
    "start": ("queued",),
    "end": ("running",),
    "stop": ("running",),
    "requeue": ("stopped", "failed"),
    "cancel": ("queued",),
    # `moved` (#403 unit 4): the PC daemon moved a long-waiting job to another host. With a `to` it
    # ends the job here (folds to `cancelled`, reason names the target); with a `from` it is only the
    # receipt on the target's copy and changes no state.
    "moved": ("queued",),
    # `moved_note` (#655): a cancel/stop sent on to the target host of a moved row; only appends to the reason.
    "moved_note": ("cancelled",),
    # `posted` is the daemon's hand-back receipt (issue #48): the issue comment for this job went
    # out, so a retry on a later tick must not post a second one. It changes no state, only the flag.
    "posted": TERMINAL_STATES,
    # `handback` is a `--handback remote` daemon's own receipt (issue #118): the rendered comment
    # body is stored on the job record instead of being posted through `gh` (the laptop has none).
    # It changes no state, only `handback_body`; the PC daemon reads it back over ssh and posts it.
    "handback": TERMINAL_STATES,
    # `runissue` keeps the title + body of the Run issue (#164) built at the end of a whole-set
    # benchmark job; `runissue_made` records the number of the issue created from it. Flags only.
    "runissue": TERMINAL_STATES,
    "runissue_made": TERMINAL_STATES,
    # `add_issue` (#468): a submit refused as identical to this job names another issue; its hand-back
    # goes there too. Flags only; allowed while the hand-back can still reach it (not `cancelled`).
    "add_issue": ("queued", "running", "done", "failed", "stopped"),
}


#: `dependency_status` verdicts (#82).
DEP_READY = "ready"        # no `--after`, or every predecessor ended rc 0
DEP_WAITING = "waiting"    # a predecessor is still queued or running
DEP_BLOCKED = "blocked"    # a predecessor ended rc != 0, was stopped or cancelled: held for ever


class IllegalTransition(RuntimeError):
    """An operation was applied to a job in a state that does not allow it."""


class JobNotFound(KeyError):
    """No job with this id has been submitted."""


class DuplicateJob(RuntimeError):
    """Two `submit` lines share a job id (should not happen; ids are checked before writing)."""


class DuplicateTag(ValueError):
    """`tag` is already used by a live (queued or running) job."""


def _now_iso() -> str:
    # microsecond precision: `next_job`'s age tie-break needs submits a lock apart to still order.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _strictly_after(ts: str, recs: Iterable[Mapping[str, Any]], *, only_submits: bool = True) -> str:
    """`ts`, or one microsecond past the newest earlier stamp when the clock has not moved on.

    A submit is compared with the earlier submits; every other op (`only_submits=False`, #696) with the
    newest stamp of any op, so two jobs that end back to back get ordered end stamps too.

    The Windows clock ticks coarser than a microsecond, so back-to-back submits read equal stamps
    (#688) and `next_job` fell back to the random job id. Called under the store lock, so the
    stamps of submits from different processes are strictly increasing in submission order.
    """

    last = max((r["ts"] for r in recs if not only_submits or r.get("op") == "submit"), default=None)
    if last is None or ts > last:
        return ts
    return (datetime.fromisoformat(last) + timedelta(microseconds=1)).isoformat(timespec="microseconds")


def new_job_id(now: datetime | None = None, rng: random.Random | None = None) -> str:
    """A sortable id: ``j-YYYYMMDD-HHMM-<4 hex>``."""

    now = now or datetime.now()
    rng = rng or random.SystemRandom()
    return f"j-{now:%Y%m%d-%H%M}-{rng.randrange(16 ** 4):04x}"


def split_pin(line: str) -> tuple[str | None, str]:
    """(pin, command) of a queue line: ``@<commit> <command>`` pins a commit, else (None, line).

    Mirrors ``run_queue.split_pin`` (``scripts/run_queue.py:74-78``); duplicated rather than
    imported because ``scripts/`` is not an importable package and this module must not depend on
    it.
    """

    m = re.match(r"@(\S+)\s+(.*)", line)
    return (m.group(1), m.group(2)) if m else (None, line)


@dataclass(frozen=True)
class Job:
    id: str
    host: str
    priority: str
    issue: int | None
    submitter: str
    tag: str
    pin: str | None
    cmd: str
    resumable: bool
    state: str
    submit_ts: str
    start_ts: str | None = None
    end_ts: str | None = None
    rc: int | None = None
    out: str | None = None
    run_dir: str | None = None
    attempts: int = 0
    #: How many PoB workers this job wants at once; the daemon's room arithmetic counts these,
    #: not jobs (issue #48). 1 unless `submit --workers N` said otherwise.
    workers: int = 1
    #: The pid of the process the daemon started for this job, from its `start` line.
    pid: int | None = None
    #: Whether the job's issue comment has been posted (the daemon's hand-back receipt).
    posted: bool = False
    #: The command as an argv list (#203): started without a shell, so quotes survive. None on a
    #: record that only has `cmd` (those start through the shell as before).
    argv: tuple[str, ...] | None = None
    #: The rendered hand-back comment body, when a `--handback remote` daemon stored one instead of
    #: posting it (issue #118) -- `None` until an `end` has been followed by a `handback` op.
    handback_body: str | None = None
    #: The Run issue (#164) of a whole-set benchmark job: title and body kept at `end`, then the
    #: number of the issue once created (`None` until then; no pass creates a second one).
    run_issue_title: str | None = None
    run_issue_body: str | None = None
    run_issue: int | None = None
    #: Why a job ended, stopped or was cancelled, when the writer gave a reason.
    reason: str | None = None
    #: Job ids this job waits for (`submit --after <id>`, repeatable, #82). It is only handed out by
    #: `next_job` once every one of them has ended `done` (rc 0); see `dependency_status`.
    after: tuple[str, ...] = ()
    #: `run` (every job before #132) or `filler` (issue #132): see `CLASS_FILLER`. A `submit` line
    #: written before this field existed folds to `run`, so nothing about an ordinary job changes.
    job_class: str = CLASS_RUN
    #: Set on the copy a rebalance wrote on another host (#403 unit 4): the host it came from. A job
    #: that carries it is never a rebalance candidate again, so a move happens once, never back.
    moved_from: str | None = None
    #: Set on the original a rebalance cancelled: the host (and job id) it was moved to.
    moved_to: str | None = None
    #: Other issues that get this job's hand-back comment too (#468): the issues of submits refused as
    #: identical to it. Deduplicated, never holds `issue`. `posted_extra` is the receipt per issue.
    extra_issues: tuple[int, ...] = ()
    posted_extra: tuple[int, ...] = ()
    #: The job's exit code is its reading (a bisect pin, a probe; `submit --rc-is-reading`, #501): a
    #: non-zero rc raises no job_failed anomaly. A row without the key folds to False.
    rc_is_reading: bool = False
    #: The hand-back posts its comment but adds no `ready-for-agent` label (#515; `submit --no-label`).
    #: A row without the key folds to False.
    no_label: bool = False
    #: The submit named `--host pc|laptop` itself (#518): the rebalancer never moves the job. A row
    #: without the key folds to False.
    host_fixed: bool = False
    #: The worker count is `auto` (#570): the daemon sizes it to the free room at START and writes the
    #: resolved N into `workers`, `cmd` and `argv`; stays true so a requeue is resolved again.
    workers_auto: bool = False
    #: Free text from `submit --note` (#578), shown as status's last column.
    note: str = ""
    #: The job is not stopped when its ticket closes (#686; `submit --outlives-ticket`, `--note` says why).
    outlives_ticket: bool = False
    #: Set on a job the PC daemon wrote because a laptop job lacked `artifacts/...` or only skipped its
    #: reading (#642): the id of the laptop job it replaces. A job that carries it is never requeued again.
    requeued_from: str | None = None
    #: Why the job sits on its host, when the submit said so (#648): `after:<id>[,<id>]` for a follower
    #: placed in the store that holds its predecessors. None on every other job and on old rows.
    host_reason: str | None = None
    #: The submitting checkout's HEAD sha (#861 rule 3). A job without a `pin` is not started on a host whose
    #: HEAD does not contain it. None on old rows and when the submitter could not read it: never held.
    submit_commit: str | None = None

    @property
    def all_issues(self) -> tuple[int, ...]:
        """The job's own issue (if any) followed by `extra_issues`: where its hand-back goes."""

        own = (int(self.issue),) if self.issue is not None else ()
        return own + tuple(n for n in self.extra_issues if n not in own)

    @property
    def handback_pending(self) -> bool:
        """Whether some issue of `all_issues` still lacks its hand-back comment."""

        return any((not self.posted) if (self.issue is not None and n == int(self.issue))
                   else n not in self.posted_extra for n in self.all_issues)

    @property
    def is_filler(self) -> bool:
        return self.job_class == CLASS_FILLER

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


# -- fold: many operation lines -> current job state ----------------------------------------------

def fold(lines: Iterable[Mapping[str, Any]]) -> dict[str, Job]:
    """The current state of every job named in `lines`, replayed in order.

    Raises `DuplicateJob` on two `submit`s of the same id, `JobNotFound` on an op for an id that
    was never submitted, and `IllegalTransition` on an op applied outside the states in
    `_ALLOWED_FROM` (e.g. `start` on a cancelled job).
    """

    jobs: dict[str, Job] = {}
    for rec in lines:
        op = rec["op"]
        jid = rec["job"]
        if op == "submit":
            if jid in jobs:
                raise DuplicateJob(jid)
            jobs[jid] = Job(
                id=jid,
                host=rec["host"],
                priority=rec["priority"],
                issue=rec.get("issue"),
                submitter=rec.get("submitter") or "",
                tag=rec["tag"],
                pin=rec.get("pin"),
                cmd=rec["cmd"],
                resumable=bool(rec.get("resumable", False)),
                state="queued",
                submit_ts=rec["ts"],
                workers=max(1, int(rec.get("workers") or 1)),
                after=tuple(str(x) for x in (rec.get("after") or ())),
                job_class=str(rec.get("class") or CLASS_RUN),
                moved_from=rec.get("moved_from"),
                rc_is_reading=bool(rec.get("rc_is_reading", False)),
                no_label=bool(rec.get("no_label", False)),
                host_fixed=bool(rec.get("host_fixed", False)),
                workers_auto=bool(rec.get("workers_auto", False)),
                note=str(rec.get("note") or ""),
                outlives_ticket=bool(rec.get("outlives_ticket", False)),
                requeued_from=rec.get("requeued_from") or None,
                host_reason=rec.get("host_reason") or None,
                submit_commit=rec.get("submit_commit") or None,
                argv=tuple(str(x) for x in rec["argv"]) if rec.get("argv") else None,
            )
            continue
        if op not in OPS:
            raise ValueError(f"unknown op {op!r}")
        job = jobs.get(jid)
        if job is None:
            raise JobNotFound(jid)
        allowed = _ALLOWED_FROM[op]
        if job.state not in allowed:
            raise IllegalTransition(f"{op} on job {jid} in state {job.state!r} (needs one of {allowed})")
        if op == "start":
            jobs[jid] = replace(
                job, state="running", start_ts=rec["ts"], end_ts=None, rc=None,
                out=rec.get("out", job.out), run_dir=rec.get("run_dir", job.run_dir),
                attempts=job.attempts + 1, pid=rec.get("pid", job.pid), posted=False, posted_extra=(), reason=None,
                handback_body=None, run_issue_title=None, run_issue_body=None, run_issue=None,
                workers=max(1, int(rec["workers"])) if rec.get("workers") else job.workers,
                cmd=rec.get("cmd") or job.cmd,
                argv=tuple(str(x) for x in rec["argv"]) if rec.get("argv") else job.argv,
            )
        elif op == "end":
            rc = rec.get("rc")
            jobs[jid] = replace(
                job, state=("done" if rc == 0 else "failed"), end_ts=rec["ts"], rc=rc,
                out=rec.get("out", job.out), run_dir=rec.get("run_dir", job.run_dir),
                reason=rec.get("reason", job.reason),
            )
        elif op == "stop":
            jobs[jid] = replace(job, state="stopped", end_ts=rec["ts"], reason=rec.get("reason", job.reason))
        elif op == "requeue":
            jobs[jid] = replace(job, state="queued", start_ts=None, end_ts=None, rc=None, posted=False,
                                posted_extra=())
        elif op == "cancel":
            jobs[jid] = replace(job, state="cancelled", end_ts=rec["ts"], reason=rec.get("reason", job.reason))
        elif op == "moved":
            if rec.get("to"):
                jobs[jid] = replace(job, state="cancelled", end_ts=rec["ts"], moved_to=str(rec["to"]),
                                    reason=rec.get("reason", job.reason))
            elif rec.get("from"):
                jobs[jid] = replace(job, moved_from=str(rec["from"]))
        elif op == "moved_note":
            jobs[jid] = replace(job, reason="; ".join(x for x in (job.reason, rec.get("note")) if x))
        elif op == "posted":
            if rec.get("issue") is not None and job.issue is not None and int(rec["issue"]) != int(job.issue):
                n = int(rec["issue"])
                jobs[jid] = replace(job, posted_extra=tuple(dict.fromkeys((*job.posted_extra, n))))
            elif rec.get("issue") is not None and job.issue is None:
                n = int(rec["issue"])
                jobs[jid] = replace(job, posted_extra=tuple(dict.fromkeys((*job.posted_extra, n))))
            else:
                jobs[jid] = replace(job, posted=True)
        elif op == "add_issue":
            n = int(rec["issue"])
            if n != job.issue and n not in job.extra_issues:
                jobs[jid] = replace(job, extra_issues=(*job.extra_issues, n))
        elif op == "handback":
            jobs[jid] = replace(job, handback_body=rec.get("body"))
        elif op == "runissue":
            jobs[jid] = replace(job, run_issue_title=rec.get("title"), run_issue_body=rec.get("body"))
        elif op == "runissue_made":
            jobs[jid] = replace(job, run_issue=rec.get("number"))
    return jobs


# -- dependencies: `submit --after <job id>` (#82) -------------------------------------------------

def _chain_ids(job: Job, jobs: Mapping[str, Job]) -> set[str]:
    """The job's own id and every id it reaches through `--after`, transitively (#825).

    Two jobs are in one chain when these sets meet; a job of another chain is none of their business.
    """

    seen: set[str] = {job.id}
    todo = list(job.after)
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        dep = jobs.get(cur)
        if dep is not None:
            todo.extend(dep.after)
    return seen


def dependency_status(job: Job, jobs: Mapping[str, Job]) -> tuple[str, Job | None]:
    """``(DEP_READY | DEP_WAITING | DEP_BLOCKED, the predecessor that explains it)``.

    A predecessor that ended ``done`` (rc 0) is satisfied. One still ``queued`` or ``running`` makes
    the job ``waiting``. One that ended ``failed`` (rc != 0, or a lost process), ``stopped`` or
    ``cancelled`` makes it ``blocked``: the follower is held for ever and a human (the keymaster,
    through the ``held_by_failed_predecessor`` anomaly) decides whether to requeue or cancel it --
    the daemon never runs a job whose input never arrived. A predecessor id that is not in ``jobs``
    (an id from a log the reader cannot see) counts as ``blocked`` too, never as satisfied; `submit`
    rejects unknown ids, so this only happens to a hand-edited log.
    """

    blocked: Job | None = None
    waiting: Job | None = None
    for dep_id in job.after:
        dep = jobs.get(dep_id)
        if dep is None:
            if job.moved_from:
                continue  # it ended rc 0 on the host the job was moved from (#403 unit 4)
            return DEP_BLOCKED, None
        if dep.state == "done":
            continue
        if dep.state in LIVE_STATES:
            waiting = waiting or dep
        else:  # failed / stopped / cancelled
            blocked = blocked or dep
    if blocked is not None:
        return DEP_BLOCKED, blocked
    if waiting is not None:
        return DEP_WAITING, waiting
    return DEP_READY, None


def held_reason(dep: Job | None) -> str:
    """The state reason of a follower whose predecessor will never end rc 0 (#862): ``held: predecessor <job> <state>``."""

    if dep is None:
        return "held: predecessor missing"
    return f"held: predecessor {dep.id} {dep.state}"


# -- the OS lock, mirroring the byte-lock idea in pob/slot_budget.py but scoped to this store -----

class _FileLock:
    """One exclusive OS lock on `path`, released by the OS if the holding process dies."""

    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        deadline = time.monotonic() + self.timeout
        rng = random.Random()
        while True:
            fd = os.open(str(self.path), flags)
            try:
                _lock_file(fd)
                self._fd = fd
                return self
            except OSError:
                os.close(fd)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"could not lock {self.path} within {self.timeout:.0f} s")
                time.sleep(0.01 + rng.random() * 0.03)

    def __exit__(self, *exc_info: object) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock_file(fd)
        finally:
            os.close(fd)


if os.name == "nt":
    import msvcrt

    def _lock_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


# -- the store --------------------------------------------------------------------------------

class Store:
    """One JSONL log of job operations, read and written under a cross-process lock."""

    def __init__(self, path: Path | str = DEFAULT_LOG) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        #: #988: the last fold and the (size, mtime_ns) of the file it was folded from. The log only ever
        #: grows by appended lines, so an unchanged stamp means an unchanged fold; the daemon reads the
        #: store ~25 times a tick and each read used to parse every line again.
        self._fold_stamp: tuple[int, int] | None = None
        self._fold_cache: dict[str, Job] = {}

    def _read_lines(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        recs = []
        # Reads take no lock: a writer's line may be half-written, so a last line without its
        # newline is not a record yet.
        lines = self.path.read_text(encoding="utf-8").split("\n")
        for line in lines[:-1]:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
        return recs

    def _write_line(self, rec: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dict(rec), sort_keys=True) + "\n")

    def _fold_all(self) -> dict[str, Job]:
        # The stamp is taken BEFORE the read: a line appended while we read leaves the cached stamp behind
        # the file, so the next call folds again (never the other way round).
        try:
            st = self.path.stat()
            stamp: tuple[int, int] | None = (st.st_size, st.st_mtime_ns)
        except OSError:
            stamp = None
        if stamp is not None and stamp == self._fold_stamp:
            return dict(self._fold_cache)
        jobs = fold(self._read_lines())
        if stamp is not None:
            self._fold_stamp, self._fold_cache = stamp, jobs
            return dict(jobs)
        self._fold_stamp, self._fold_cache = None, {}
        return jobs

    # -- reads --------------------------------------------------------------------------------

    def jobs(self, state: str | None = None, host: str | None = None) -> list[Job]:
        """Every job, oldest submitted first; optionally filtered by exact `state` or `host`."""

        js = list(self._fold_all().values())
        if state is not None:
            js = [j for j in js if j.state == state]
        if host is not None:
            js = [j for j in js if j.host == host]
        js.sort(key=lambda j: (j.submit_ts, j.id))
        return js

    def get(self, job_id: str) -> Job:
        jobs = self._fold_all()
        if job_id not in jobs:
            raise JobNotFound(job_id)
        return jobs[job_id]

    def next_job(self, host: str, *, exclude: Iterable[str] = ()) -> Job | None:
        """The queued job a `host` worker should take next: highest priority, then oldest submit.

        `host="any"` is picked by both `pc` and `laptop` workers.

        A `filler` (#132) sorts after every `run` of the same priority, however old it is: a filler
        is "ordered under P2", so a job an issue waits for never waits behind one. With no filler in
        the store the order is exactly what it was.

        `--after` (#82) only ever DELAYS a job, it never reorders the queue in its favour. Walking
        the sorted candidates, a job still WAITING for a predecessor is skipped, and every further
        candidate of the SAME chain (#825: its `--after` closure shares an id with the held job's,
        itself included) is skipped too: a dependent job never overtakes a dependent job of its own
        chain that was queued before it. A job of another chain is held only by its own
        predecessors (a better priority sorts ahead of the held one and is reached first, so this
        can never delay a P0 behind a held P2). A job with no `--after` at all is unrelated to the
        chains and starts as usual, so one waiting chain can never idle the host. The chain case of
        the spec -- A, B `--after A`, C: while B waits for A, C starts (it has no `--after`), and a
        later D `--after <something already done>` does not jump ahead of B.

        A BLOCKED job (its predecessor ended rc != 0, was stopped or cancelled) is the exception: it
        is out of the queue until a human requeues the predecessor or cancels it -- the daemon
        raises `held_by_failed_predecessor` for it -- so it holds nobody's place, and a healthy
        chain behind a dead one still runs.

        `exclude` (#117): job ids to leave out of THIS call only -- the caller's own within-tick
        holds (a heavy job it already decided to skip), never persisted. It only ever removes a
        candidate from contention; it never reorders the ones that remain, so a lighter job behind
        an excluded one is reached exactly as if the excluded one were not queued at all.
        """

        excluded = {str(x) for x in exclude}
        jobs = self._fold_all()
        candidates = [j for j in jobs.values()
                      if j.state == "queued" and (j.host == host or j.host == "any")
                      and j.id not in excluded]
        if not candidates:
            return None
        candidates.sort(key=lambda j: (_PRIORITY_RANK[j.priority], j.is_filler, j.submit_ts, j.id))
        held_chains: set[str] = set()  # ids of every WAITING job and of all its ancestors (#825)
        for job in candidates:
            if not job.after:
                return job
            if held_chains and not held_chains.isdisjoint(_chain_ids(job, jobs)):
                continue
            status, _dep = dependency_status(job, jobs)
            if status == DEP_READY:
                return job
            if status == DEP_WAITING:
                held_chains |= _chain_ids(job, jobs)
        return None

    def held_jobs(self, host: str | None = None) -> list[tuple[Job, Job | None, str]]:
        """Every queued job held by `--after`, with the predecessor and verdict that explain it."""

        jobs = self._fold_all()
        queued = sorted((j for j in jobs.values() if j.state == "queued"),
                        key=lambda j: (j.submit_ts, j.id))
        out: list[tuple[Job, Job | None, str]] = []
        for job in queued:
            if not job.after:
                continue
            if host is not None and job.host != host and job.host != "any":
                continue
            status, dep = dependency_status(job, jobs)
            if status != DEP_READY:
                out.append((job, dep, status))
        return out

    # -- writes ---------------------------------------------------------------------------------

    def submit(
        self, *, host: str, priority: str, tag: str, cmd: str,
        issue: int | None = None, submitter: str = "", pin: str | None = None,
        resumable: bool = False, workers: int = 1, after: Iterable[str] = (),
        job_class: str = CLASS_RUN, moved_from: str | None = None,
        argv: Iterable[str] | None = None, rc_is_reading: bool = False,
        no_label: bool = False, host_fixed: bool = False, workers_auto: bool = False,
        note: str = "", requeued_from: str | None = None,
        host_reason: str | None = None, outlives_ticket: bool = False,
        submit_commit: str | None = None,
    ) -> Job:
        if host not in HOSTS:
            raise ValueError(f"unknown host {host!r} (one of {HOSTS})")
        if priority not in PRIORITIES:
            raise ValueError(f"unknown priority {priority!r} (one of {PRIORITIES})")
        if job_class not in CLASSES:
            raise ValueError(f"unknown job class {job_class!r} (one of {CLASSES})")
        if not tag:
            raise ValueError("tag is required")
        if int(workers) < 1:
            raise ValueError(f"workers must be at least 1, got {workers!r}")
        predecessors = tuple(dict.fromkeys(str(x).strip() for x in after if str(x).strip()))
        with _FileLock(self.lock_path):
            lines = self._read_lines()
            state = fold(lines)
            live_tags = {j.tag for j in state.values() if j.state in LIVE_STATES}
            if tag in live_tags:
                raise DuplicateTag(f"tag {tag!r} is already live")
            # An unknown `--after` id is rejected here and not written (#82): a job that waits for a
            # job that does not exist would be held for ever with nothing to report it.
            # A job moved here by a rebalance names predecessors of the host it came from: kept as is.
            unknown = [] if moved_from else [dep for dep in predecessors if dep not in state]
            if unknown:
                raise JobNotFound(f"--after names no such job: {', '.join(unknown)}")
            ts = _strictly_after(_now_iso(), lines)
            job_id = new_job_id()
            while job_id in state:  # practically never, the lock already serializes submits
                job_id = new_job_id()
            rec = {
                "ts": ts, "job": job_id, "op": "submit",
                "host": host, "priority": priority, "issue": issue,
                "submitter": submitter, "tag": tag, "pin": pin, "cmd": cmd,
                "resumable": bool(resumable), "workers": int(workers),
                "after": list(predecessors), "class": job_class,
            }
            if moved_from:
                rec["moved_from"] = moved_from
            if rc_is_reading:
                rec["rc_is_reading"] = True
            if no_label:
                rec["no_label"] = True
            if host_fixed:
                rec["host_fixed"] = True
            if host_reason:
                rec["host_reason"] = str(host_reason)
            if submit_commit:
                rec["submit_commit"] = str(submit_commit)
            if workers_auto:
                rec["workers_auto"] = True
            if note:
                rec["note"] = note
            if outlives_ticket:
                rec["outlives_ticket"] = True
            if requeued_from:
                rec["requeued_from"] = str(requeued_from)
            if argv:
                rec["argv"] = [str(x) for x in argv]
            self._write_line(rec)
            if moved_from:  # the receipt of the move on this side (#403 unit 4)
                self._write_line({"ts": _now_iso(), "job": job_id, "op": "moved", "from": moved_from})
        return self.get(job_id)

    def _write_op(self, job_id: str, op: str, **fields: Any) -> Job:
        with _FileLock(self.lock_path):
            lines = self._read_lines()
            state = fold(lines)
            job = state.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            allowed = _ALLOWED_FROM[op]
            if job.state not in allowed:
                raise IllegalTransition(f"{op} on job {job_id} in state {job.state!r} (needs one of {allowed})")
            rec = {"ts": _strictly_after(_now_iso(), lines, only_submits=False), "job": job_id, "op": op, **fields}
            self._write_line(rec)
        return self.get(job_id)

    def start(
        self, job_id: str, *, out: str | None = None, run_dir: str | None = None,
        pid: int | None = None, workers: int | None = None, cmd: str | None = None,
        argv: Iterable[str] | None = None,
    ) -> Job:
        extra: dict[str, Any] = {}
        if workers is not None:  # an `auto` job's resolved count and rewritten command (#570)
            extra["workers"] = int(workers)
        if cmd is not None:
            extra["cmd"] = cmd
        if argv:
            extra["argv"] = [str(x) for x in argv]
        return self._write_op(job_id, "start", out=out, run_dir=run_dir, pid=pid, **extra)

    def end(
        self, job_id: str, *, rc: int | None, out: str | None = None, run_dir: str | None = None,
        reason: str | None = None, snapshot_diff: str | None = None,
    ) -> Job:
        """End a running job. ``rc=None`` means the runner never saw an exit code (the daemon lost
        the process, issue #48 requirement 4) and folds to ``failed`` like any non-zero rc."""

        extra = {"snapshot_diff": snapshot_diff} if snapshot_diff else {}
        return self._write_op(job_id, "end", rc=rc, out=out, run_dir=run_dir, reason=reason, **extra)

    def mark_posted(self, job_id: str, issue: int | None = None) -> Job:
        """Record that this job's issue comment went out, so a retry never posts a second one.

        ``issue`` names one of the job's ``extra_issues`` (#468); None is the job's own issue."""

        if issue is None:
            return self._write_op(job_id, "posted")
        return self._write_op(job_id, "posted", issue=int(issue))

    def add_issue(self, job_id: str, issue: int) -> Job:
        """Record another issue that gets this job's hand-back too (#468): a refused identical submit."""

        return self._write_op(job_id, "add_issue", issue=int(issue))

    def record_handback(self, job_id: str, body: str) -> Job:
        """Store a rendered hand-back comment on the job (a ``--handback remote`` daemon, #118),
        for another host's daemon to read over ssh and post through ``gh`` on its behalf."""

        return self._write_op(job_id, "handback", body=body)

    def record_run_issue_body(self, job_id: str, title: str, body: str) -> Job:
        """Keep the Run issue's title and body on the job (#164), for the PC daemon to create."""

        return self._write_op(job_id, "runissue", title=title, body=body)

    def record_run_issue(self, job_id: str, number: int) -> Job:
        """Record the number of the Run issue created for this job: no pass creates a second."""

        return self._write_op(job_id, "runissue_made", number=int(number))

    def stop(self, job_id: str, *, reason: str | None = None, snapshot_diff: str | None = None) -> Job:
        extra = {"snapshot_diff": snapshot_diff} if snapshot_diff else {}
        return self._write_op(job_id, "stop", reason=reason, **extra)

    def requeue(self, job_id: str, *, reason: str | None = None) -> Job:
        return self._write_op(job_id, "requeue", reason=reason)

    def move_away(self, job_id: str, *, to: str, new_id: str | None = None) -> Job:
        """End a queued job here because a rebalance moved it to host ``to`` (#403 unit 4)."""

        target = f"{to}:{new_id}" if new_id else to
        return self._write_op(job_id, "moved", to=target, reason=f"moved to {target}")

    def note_moved(self, job_id: str, note: str) -> Job:
        """Append ``note`` to the reason of a moved row (#655: a cancel/stop forwarded to the target host)."""

        return self._write_op(job_id, "moved_note", note=note)

    def cancel(self, job_id: str, *, reason: str | None = None) -> Job:
        return self._write_op(job_id, "cancel", reason=reason)
