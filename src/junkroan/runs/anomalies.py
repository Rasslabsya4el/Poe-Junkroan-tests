"""Anomaly detection and the on-demand keymaster launch (issue #57, part of the #36 redesign).

The keymaster no longer holds a standing chat: the runs daemon (``daemon.py``, #48) calls
:meth:`AnomalyGuard.check` once per tick and this module decides whether something is wrong, and
whether to start a ``claude.exe`` keymaster session about it. Nothing here starts real ``claude``,
``ssh`` or PoB in a test; every collaborator that touches the world (the launcher, the host probe,
the budget-file check) is injected.

Five anomaly kinds (requirement 1; the fifth added by issue #76):

    job_failed          a job ended with ``rc != 0`` (or lost its process, ``rc is None``).
    job_stuck           a running job's ``out`` file has not been written to for 45 min.
    host_unreachable    the laptop's ``run_on_host`` probe failed 3 ticks in a row.
    host_daemon_dead    the laptop answers ssh but its runs daemon is not live for 10 min (issue #1183):
                        one events/log line, no queue, no keymaster, no issue, no comment.
    budget_unreadable   ``var/machine_budget.json`` could not be read (the BOM case).
    lease_overrun       a slot held in the ``others`` share, or a reservation past its ``expires``,
                        for longer than ``LEASE_OVERRUN_SECONDS`` (issue #76). Detected from
                        ``slot_budget.busy_slots()`` rows and ``hosts.reserve_slots``'s own
                        reservation entries (both dicts, read through injected listers so no test
                        touches a real PoB slot lock or ``var/reservations.json``).
    job_wrong_host      a ``queued`` job in this host's own store whose ``host`` names some other
                        host (issue #120): the store is per-host, so `runs.py submit`'s ssh path
                        should never leave one behind -- only a hand-written line, or a submit run
                        directly against this store, can. Raised instead of leaving the job to sit
                        `queued` for ever (the #120 incident): one per job id, deduped like every
                        other anomaly.
    untracked_slots     a process tree holds PoB slots and no running job of the store owns it
                        (issue #365): raised once per host + pid + start time; nothing is stopped.

Each gets a stable key (``f"{kind}:{job_or_host}"``); once a key has been queued or started it is
recorded in ``var/anomalies.json`` and never queued again, even while the underlying condition
persists tick after tick (a job that stays ``failed`` must not spawn a second keymaster session).

At most one keymaster session runs at a time: ``check`` asks the launcher for sessions named
``keymaster: ...`` (the same ``claude agents --json --all`` the ORCH dispatcher polls,
``tools/agentops/dispatch.py``) and only starts the oldest queued anomaly when none is live; every state
but ``done`` / ``stopped`` counts as live, ``blocked`` and ``working`` included.
A live session that waits for input (``blocked`` or ``idle``) for ``KEYMASTER_WAIT_LIMIT_SECONDS`` is ended
through ``launcher.end``; its anomaly stays in ``handled`` (left to its issue), so the queue's head starts.
"""

from __future__ import annotations

import json
import os
import random
import re
import shlex
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from junkroan.report_format import human_duration
from junkroan.runs.bounded import run_bounded
from junkroan.runs.pass_guard import GUARD
from junkroan.runs.store import Job

PROJECT_ROOT = Path(__file__).resolve().parents[3]
KEYMASTER_DOC = "docs/agents/keymaster.md"

#: A running job's `out` file must have grown within this long, or it is "stuck" (requirement 1).
STUCK_OUTPUT_SECONDS = 45 * 60
#: A host must fail (probes, remote hand-backs) for this long, from the first failure of the streak,
#: before it counts as an anomaly (#382: the 2026-10-02 wifi blip of 8 min must not post one).
UNREACHABLE_SPAN_SECONDS = 10 * 60
#: The quiet time after a remote hand-back raise of `host_unreachable` (#308).
HANDBACK_COOLDOWN_SECONDS = 3600.0
#: The laptop probe runs at most this often (ORCH's call: an SSH round trip every 10 s tick is not
#: worth it); `AnomalyGuard` re-uses the last streak between probes rather than re-probing.
PROBE_INTERVAL_SECONDS = 60.0
#: A trivial remote command: proves the SSH transport (`hosts.run_on_host`) still answers, nothing
#: else. Kept out of `hosts.py` (#57: "do not edit hosts.py -- import from it only").
_PROBE_SCRIPT = "Write-Output ok"
#: The last N lines of a job's `out` file quoted in the keymaster's prompt.
OUT_TAIL_LINES = 20
#: A slot held in the `others` share, or a reservation past its `expires`, longer than this counts
#: as a `lease_overrun` anomaly (issue #76 requirement 1: "a config value"; seconds -- a machine
#: file's own unit, CLAUDE.md principle 7 -- human text renders it through `human_duration`).
LEASE_OVERRUN_SECONDS = 10 * 60
# an untracked tree of 1 slot is an agent's legal short PoB test up to this age (CLAUDE.md, #418;
# 30 min since 2026-10-02: every 1-slot holder of that day was reported 5-11 min into a legal test)
UNTRACKED_GRACE_SECONDS = 30 * 60

_BOM = b"\xef\xbb\xbf"

#: `--name "keymaster: ..."`; group 1/2 are the kind and the job-or-host (adoption, symmetry with
#: the ORCH dispatcher's own `_ORCH_NAME_RE`). `build_command` writes an optional origin host between
#: the two (`keymaster: job_stuck laptop j-...`, a laptop job's anomaly): without it such a session was
#: never `_is_keymaster` and so never ended (#877 row 7).
_KEYMASTER_NAME_RE = re.compile(r"^keymaster:\s*(\S+)\s+(?:\S+\s+)?(\S+)$")

#: States `claude agents --json --all` reports for a session still running (dispatch.py's own).
LIVE_STATES = frozenset({"working", None})
#: A keymaster session in any other state counts live (`blocked`, `working`, unknown, no state).
FINISHED_STATES = frozenset({"done", "stopped", "failed"})  # `failed` = the process exited (#862: f4dc7666, exit 4, blocked every start 17 h)
#: A live keymaster session waiting for input this long is ended (its anomaly is not re-queued).
KEYMASTER_WAIT_LIMIT_SECONDS = 10 * 60
#: Every ``claude.exe`` call of ``ClaudeKeymasterCli`` is bounded by this, whole process tree (#647).
END_WAIT_SECONDS = 0.5  # a tick waits at most this long for the end queue to drain (#761)
KEYMASTER_CALL_BOUND_SECONDS = 30.0
#: #1000: one `gh issue list` of the issue finder waits at most this long (the daemon's gh cap is 45 s too, #998).
GH_FINDER_TIMEOUT_SECONDS = 45.0
#: The tick waits at most this long for the session list; a slower call finishes in the background (#647).
SESSION_LIST_WAIT_SECONDS = 2.0
#: A cached session list older than this counts as not ready (#647).
SESSION_LIST_MAX_AGE_SECONDS = 10 * 60


def _log(message: str) -> None:
    import sys
    from datetime import datetime

    try:
        sys.stderr.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} anomalies: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


# -- an anomaly ------------------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class Anomaly:
    """One thing the daemon noticed. ``key`` is stable: the same anomaly never queues twice."""

    kind: str
    key: str
    job: str | None = None
    host: str | None = None
    detail: str = ""
    out: str | None = None
    #: `lease_overrun` only (issue #76): the holder's pid (a busy `others`-share slot), the issue a
    #: reservation was made for, and how long it has been held past its allowance, in seconds --
    #: captured once at detection time, never re-read from the queued entry afterwards.
    pid: int | None = None
    issue: int | None = None
    held_for: float | None = None
    #: The host whose daemon detected it, set only on an anomaly this daemon adopted from another
    #: host's queue (#467: the laptop never starts a keymaster, the PC starts it for the laptop).
    origin: str | None = None
    #: `job_failed` grouped by cause (#877 rule 3): every job id of the group, the first one is `job`;
    #: empty for a single job. `submit_ts` (epoch seconds) is the first job's submit time, the 5-minute window's start.
    jobs: tuple[str, ...] = ()
    submit_ts: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "job": self.job, "host": self.host,
                "detail": self.detail, "out": self.out, "pid": self.pid, "issue": self.issue,
                "held_for": self.held_for, "origin": self.origin,
                "jobs": list(self.jobs), "submit_ts": self.submit_ts}

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "Anomaly":
        return Anomaly(
            kind=str(data["kind"]), key=str(data["key"]), job=data.get("job"), host=data.get("host"),
            detail=str(data.get("detail") or ""), out=data.get("out"),
            pid=data.get("pid"), issue=data.get("issue"), held_for=data.get("held_for"),
            origin=data.get("origin"),
            jobs=tuple(str(j) for j in (data.get("jobs") or ())), submit_ts=data.get("submit_ts"),
        )

    @property
    def target(self) -> str:
        """The job id or host name in the anomaly's name/key -- whichever this anomaly carries."""

        if self.job or self.host:
            return self.job or self.host
        if self.pid is not None:
            return f"pid-{self.pid}"
        if self.issue is not None:
            return f"issue-{self.issue}"
        return "?"


# -- detection (pure functions; no I/O beyond reading a job's `out` file) -------------------------

_PYTEST_PROGRAMS = {"pytest", "pytest.exe", "py.test", "py.test.exe"}


def is_pytest_command(cmd: str) -> bool:
    """True when ``cmd`` runs pytest: ``-m pytest``, a pytest program, or ``python -c`` calling ``pytest.main``."""

    try:
        if not isinstance(cmd, str):
            return False
        tokens = shlex.split(cmd, posix=False)
        if not tokens:
            return False
        first = tokens[0].strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if first in _PYTEST_PROGRAMS:
            return True
        for i, tok in enumerate(tokens[:-1]):
            if tok == "-m" and tokens[i + 1].strip("\"'") == "pytest":
                return True
        return "pytest.main" in cmd and "-c" in tokens
    except Exception:
        return False


def detect_job_failed(job: Job) -> Anomaly | None:
    """A job that ended with ``rc != 0``, or whose process the daemon lost (``rc is None``)."""

    if job.state not in ("failed",):
        return None
    if (job.reason or "").startswith("stopped by "):
        return None  # a hand `stop` / `mode off` ended it on purpose (#412)
    if job.rc is not None:
        if getattr(job, "rc_is_reading", False):
            return None  # the job's rc is its reading, any value (#501)
        if job.rc == 1 and is_pytest_command(job.cmd):
            return None  # pytest rc 1 = tests ran and some failed: the reading (#501)
    from junkroan.runs.handback_gate import laptop_lacks_artifact  # local: handback_gate imports rebalance
    if laptop_lacks_artifact(job):
        return None  # the PC requeues it once (#642); a second failure is an ordinary one
    verdict = f"rc {job.rc}" if job.rc is not None else "rc null"
    detail = f"job {job.id} ended {verdict} ({job.reason or job.state}); cmd `{job.cmd}`"
    try:
        submit_ts = datetime.fromisoformat(job.submit_ts).timestamp()
    except Exception:
        submit_ts = None
    return Anomaly(kind="job_failed", key=f"job_failed:{job.id}", job=job.id, detail=detail, out=job.out,
                   issue=job.issue, submit_ts=submit_ts)


# -- one cause, one keymaster (#877 rule 3) ----------------------------------------------------------

GROUP_WINDOW_SECONDS = 5 * 60
_DETAIL_ERROR_RE = re.compile(r"ended (rc \S+) \((.*?)\); cmd ")


def _error_line(anomaly: Anomaly) -> str:
    """The error line of a failed job: the last non-empty line of its out file, else its rc.

    A laptop job's out file is not readable on the PC (an adopted anomaly has `origin`), so for it the
    error line is the `rc` plus the reason `detail` carries ("rc 1 (exit 1)"): same rc and reason = same error.
    """

    verdict = _DETAIL_ERROR_RE.search(anomaly.detail or "")
    rc = verdict.group(1) if verdict else (anomaly.detail or "")
    if anomaly.origin:
        return f"{rc} ({verdict.group(2)})" if verdict else rc
    for line in reversed(_out_tail(anomaly.out, 50)):
        if line.strip():
            return line.strip()
    return rc


def merge_into_queue(queue: list[Anomaly], anomaly: Anomaly) -> bool:
    """Fold a failed job into a queued `job_failed` of the same ticket, machine and error line submitted
    within 5 minutes of its first job: the queued entry then lists both ids. True when merged."""

    if anomaly.kind != "job_failed" or not anomaly.job or anomaly.submit_ts is None:
        return False
    sig = (anomaly.issue, anomaly.origin, _error_line(anomaly))
    for i, queued in enumerate(queue):
        if (queued.kind != "job_failed" or queued.submit_ts is None or not queued.job
                or (queued.issue, queued.origin, _error_line(queued)) != sig
                or abs(anomaly.submit_ts - queued.submit_ts) > GROUP_WINDOW_SECONDS):
            continue
        ids = queued.jobs or (queued.job,)
        if anomaly.job in ids:
            return True
        queue[i] = replace(queued, jobs=ids + (anomaly.job,))
        return True
    return False


LOOP_GRACE_SECONDS = 15 * 60
#: `replay_bench.py` writes nothing until every build is done (its report folder is created empty, `:906`), so
#: a live replay is quiet for as long as its longest build; the only per-build bound in its code is
#: `FIXED_POINT_MAX_SECONDS = 7200.0` (`scripts/replay_bench.py:247`); plus the same grace as a `--loop` run (#878).
REPLAY_STUCK_SECONDS = 7200 + LOOP_GRACE_SECONDS
_LOOP_SECONDS_RE = re.compile(r"(?<!\S)--loop-seconds(?:\s+|=)([0-9]+(?:\.[0-9]+)?)")


def stuck_line_seconds(cmd: str | None) -> float:
    """The no-output line of a job: 45 min, or for a command with `--loop-seconds N` (`--loop` itself is
    a no-op since D58) N s + 15 min, never below the 45 min line (#466). Without the flag the benchmark's
    40 min default stays under 45."""

    if "replay_bench.py" in (cmd or ""):
        return REPLAY_STUCK_SECONDS
    found = _LOOP_SECONDS_RE.search(cmd or "")
    if not found:
        return STUCK_OUTPUT_SECONDS
    return max(STUCK_OUTPUT_SECONDS, float(found.group(1)) + LOOP_GRACE_SECONDS)


_BENCH_TAG_RE = re.compile(r"(?<!\S)--tag(?:\s+|=)(\"[^\"]+\"|'[^']+'|\S+)")


def _bench_logs_mtime(command: str | None, bench_root: Path | None) -> float | None:
    """Newest mtime under `<bench_root>/<stamp>-<tag>*/logs/` for a `benchmark.py ... --tag T` command (#595)."""

    if not command or "benchmark.py" not in command:
        return None
    found = _BENCH_TAG_RE.search(command)
    if not found:
        return None
    tag = found.group(1).strip("\"'")
    root = bench_root if bench_root is not None else PROJECT_ROOT / "artifacts" / "benchmark"
    newest: float | None = None
    try:
        for run_dir in root.iterdir():
            # name = 13-char stamp + "-" + tag (+ "-no-<ablate>")
            rest = run_dir.name[13:]
            if rest != "-" + tag and not rest.startswith("-" + tag + "-no-"):
                continue
            try:
                for entry in (run_dir / "logs").iterdir():
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if newest is None or mtime > newest:
                        newest = mtime
            except OSError:
                continue
    except OSError:
        return None
    return newest


def _stood(start_epoch: float, end_epoch: float) -> float:
    """Seconds of [start, end] the machine stood in play (#779 rule 5); 0.0 when it cannot be told."""
    try:
        from tools.agentops.machine_mode import stood_between
    except ImportError:
        return 0.0
    return stood_between(start_epoch, end_epoch)


def detect_job_stuck(
    job_id: str, out: Path | str, *, now: float, stale_seconds: float = STUCK_OUTPUT_SECONDS,
    command: str | None = None, bench_root: Path | None = None,
) -> Anomaly | None:
    """A running job whose ``out`` file has not been written to in ``stale_seconds`` (45 min).
    A `benchmark.py --tag T` job also counts its run dir's `logs/` files as output (#595)."""

    path = Path(out)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    logs_mtime = _bench_logs_mtime(command, bench_root)
    if logs_mtime is not None and logs_mtime > mtime:
        mtime = logs_mtime
    age = now - mtime - _stood(mtime, now)
    if age < stale_seconds:
        return None
    detail = f"job {job_id} out file has not grown in {human_duration(age)}"
    return Anomaly(kind="job_stuck", key=f"job_stuck:{job_id}", job=job_id, detail=detail, out=str(path))


def detect_host_unreachable(
    host: str, failing_for: float | None, *, span: float = UNREACHABLE_SPAN_SECONDS,
) -> Anomaly | None:
    """``host`` (laptop only) once its probes have failed for ``span`` seconds, counted on the clock from
    the first failure of the streak (``failing_for``; `None` = the last probe succeeded)."""

    if failing_for is None or failing_for < span:
        return None
    detail = f"{host} unreachable for {human_duration(failing_for)} of failed probes"
    return Anomaly(kind="host_unreachable", key=f"host_unreachable:{host}", host=host, detail=detail)


def laptop_daemon_live(status: Mapping[str, Any], *, now: float) -> bool:
    """Whether a host daemon's ``status`` (read over ssh) still describes a live daemon (#1183).

    The pid cannot be checked from the PC, so only ``last_tick`` counts, judged like
    ``rebalance._remote_ram_bound``: its age, less the stood time, under ``stale_after`` of its own
    ``tick_seconds``. A status without a readable ``last_tick`` is not live.
    """

    from junkroan.runs.daemon import TICK_SECONDS, stale_after  # lazy: daemon.py imports the runs side

    try:
        last = datetime.fromisoformat(str(status.get("last_tick")))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    last_epoch = last.timestamp()
    age = max(0.0, now - last_epoch - _stood(last_epoch, now))
    return age < stale_after(status.get("tick_seconds", TICK_SECONDS))


def detect_host_daemon_dead(
    host: str, dead_for: float | None, *, span: float = UNREACHABLE_SPAN_SECONDS,
    fixed_jobs: Iterable[str] = (),
) -> Anomaly | None:
    """``host`` whose ssh answers but whose runs daemon is not live, once that has lasted ``span`` seconds
    (``dead_for``; `None` = the daemon is live or its status is unreadable). ``fixed_jobs``: the ids of
    this host's queued `--host <host>` jobs, which stay queued and are named in the line (#1183)."""

    if dead_for is None or dead_for < span:
        return None
    fixed = [str(job) for job in fixed_jobs]
    detail = f"{host} answers ssh but its runs daemon has not been live for {human_duration(dead_for)}"
    if fixed:
        detail += f"; jobs fixed to {host} wait there: {', '.join(fixed)}"
    return Anomaly(kind="host_daemon_dead", key=f"host_daemon_dead:{host}", host=host, detail=detail)


def detect_budget_unreadable(reason: str = "") -> Anomaly:
    """``var/machine_budget.json`` could not be read (the BOM case, or any other read failure)."""

    detail = "var/machine_budget.json unreadable" + (f" ({reason})" if reason else "")
    return Anomaly(kind="budget_unreadable", key="budget_unreadable:machine_budget", detail=detail)


def detect_held_by_failed_predecessor(job: Job, predecessor: Job | None) -> Anomaly | None:
    """A queued job whose ``--after`` predecessor did not end rc 0 (issue #82 requirement 2).

    The follower is never started: its input never arrived. One anomaly per (follower, predecessor)
    pair -- the key is stable, so the daemon may pass the same held job every tick and only the
    first one queues a keymaster, who decides whether to requeue the predecessor or cancel the
    follower.

    A predecessor stored ``stopped`` (a deliberate stop) or ``cancelled`` is not an anomaly (#422):
    the follower stays held and the stopped job's hand-back comment names how to release it.
    """

    if predecessor is not None and predecessor.state in ("stopped", "cancelled"):
        return None
    if predecessor is None:
        detail = f"job {job.id} waits on a job that is not in the store: {', '.join(job.after) or '?'}"
        return Anomaly(kind="held_by_failed_predecessor", key=f"held_by_failed_predecessor:{job.id}:?",
                       job=job.id, detail=detail, issue=job.issue)
    verdict = f"rc {predecessor.rc}" if predecessor.rc is not None else f"rc null ({predecessor.state})"
    detail = (f"job {job.id} (`{job.tag}`) is held: its `--after` predecessor {predecessor.id} "
              f"(`{predecessor.tag}`) ended {verdict} in state {predecessor.state}")
    return Anomaly(
        kind="held_by_failed_predecessor",
        key=f"held_by_failed_predecessor:{job.id}:{predecessor.id}",
        job=job.id, detail=detail, out=predecessor.out, issue=job.issue,
    )


def is_transient_gh_failure(tail: Iterable[str]) -> bool:
    """True when the out tail shows a flaky `gh` / GitHub call (#862 rule 3, `docs/agents/keymaster.md` "a flaky
    `gh` call"): the one transient failure a tail can prove. The marker list lives in
    ``tools/agentops/gh_call.py``, the one `gh` adapter (imported there, not copied; lazily, like this module's other
    ``tools.agentops`` imports). The keymaster list's other transient reason, "a snapshot race", leaves no fixed text
    to recognise: not mechanical here."""

    from tools.agentops.gh_call import is_transient_gh_failure as _is_transient

    return _is_transient(tail)


def _job_seconds(job: Job) -> float | None:
    if not job.start_ts or not job.end_ts:
        return None
    try:
        return (datetime.fromisoformat(job.end_ts) - datetime.fromisoformat(job.start_ts)).total_seconds()
    except Exception:
        return None


def chain_followers(jobs: Iterable[Job], root_id: str) -> list[Job]:
    """Every queued job that follows ``root_id`` through ``after``, followers of followers included."""

    pool = [j for j in jobs if j.state == "queued"]
    found: list[Job] = []
    seen = {root_id}
    frontier = {root_id}
    while frontier:
        step = [j for j in pool if j.id not in seen and frontier.intersection(j.after)]
        seen.update(j.id for j in step)
        found.extend(step)
        frontier = {j.id for j in step}
    return found


def detect_lease_overrun_slot(
    row: Mapping[str, Any], *, now: float, threshold: float = LEASE_OVERRUN_SECONDS,
) -> Anomaly | None:
    """A busy ``others``-share slot (one row of ``slot_budget.busy_slots()``) held past ``threshold``.

    ``row`` carries ``{"slot", "pid", "role", "cmd", "started", "age_seconds"}``; only ``role ==
    "other"`` counts (issue #76 requirement 1 -- the queue's own slots are not this anomaly).
    """

    from junkroan.pob import slot_budget  # lazy: this module must import with no PoB collaborator

    if str(row.get("role") or "").strip().lower() != slot_budget.ROLE_OTHER:
        return None
    try:
        held_for = float(row.get("age_seconds") or 0.0)
    except (TypeError, ValueError):
        return None
    held_for = max(0.0, held_for - _stood(now - held_for, now))
    if held_for < threshold:
        return None
    pid = row.get("pid")
    key = f"lease_overrun:slot:{pid}:{row.get('started') or ''}"
    detail = f"others-share slot #{row.get('slot')} held by pid {pid} for {human_duration(held_for)}: `{row.get('cmd', '')}`"
    return Anomaly(kind="lease_overrun", key=key, detail=detail, pid=pid, held_for=held_for)


def detect_follow_main_failed(host: str, streak: tuple[str, int, str] | None) -> Anomaly | None:
    """The follow-main step of a detached daemon checkout failed 3 times in a row (#861).

    ``streak``: (streak id, failures so far, git's error line) from `FollowMain.streak()`. One anomaly per
    streak -- the key carries the streak id, a success ends the streak and the next one gets a new id.
    """

    if streak is None:
        return None
    streak_id, count, error = streak
    return Anomaly(kind="follow_main_failed", key=f"follow_main_failed:{host}:{streak_id}", host=host,
                   detail=f"{host} could not follow origin/main: {count} failed `git checkout --detach origin/main` "
                          f"in a row, git says: {error}")


def detect_job_wrong_host(job: Job, host: str) -> Anomaly:
    """A ``queued`` job in ``host``'s own store addressed to a different host (issue #120).

    ``runs.py submit --host <other>`` now goes over ssh to that host's own store (#120), so this
    should never happen through it; it still catches a hand-written store line or a submit run
    directly against this store (bypassing the ssh path), instead of the job sitting `queued`
    silently for ever (the incident this issue is named for).
    """

    detail = f"job {job.id} (`{job.tag}`) is queued for host {job.host!r} in {host!r}'s own store"
    return Anomaly(kind="job_wrong_host", key=f"job_wrong_host:{job.id}", job=job.id, host=job.host, detail=detail)


def _untracked_within_rule(tree: Any, now: float) -> bool:
    """An untracked holder inside CLAUDE.md's rule (one slot, at most 30 min old: an agent's short PoB
    test after `machine_load.py`) raises nothing (issue #418). An unknown start time is not inside it."""

    started = tree.started
    return (tree.slots <= 1 and started is not None
            and now - started - _stood(started, now) <= UNTRACKED_GRACE_SECONDS)


def detect_untracked_slots(tree: Any, host: str) -> Anomaly:
    """A process tree that holds PoB slots and no running job owns (issue #365; ``tree`` is an
    ``untracked.UntrackedTree``). One anomaly per (host, pid, start time): a reused pid is a new one.
    Nothing is stopped: the owner's own PoB and hand runs hold slots the same way."""

    started = tree.started
    when = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") if started else "unknown"
    detail = (f"untracked slots on {host}: pid {tree.pid} holds {tree.slots} PoB slot(s) and no running "
              f"job of the store owns it; tag {tree.tag or 'none'}; started {when}; "
              f"command `{tree.cmd_head}`. Nothing is stopped automatically.")
    key = f"untracked_slots:{host}:{tree.pid}:{int(started) if started else 0}"
    return Anomaly(kind="untracked_slots", key=key, host=host, detail=detail, pid=tree.pid)


def detect_lease_overrun_reservation(
    entry: Mapping[str, Any], *, now: float, threshold: float = LEASE_OVERRUN_SECONDS,
) -> Anomaly | None:
    """A reservation (one entry of ``hosts.reserve_slots``'s own ``var/reservations.json``) whose
    ``expires`` passed more than ``threshold`` ago and is still on file (not yet released or pruned).
    """

    expires = entry.get("expires")
    if not expires:
        return None
    try:
        expires_epoch = datetime.fromisoformat(str(expires)).timestamp()
    except (ValueError, TypeError):
        return None
    held_for = now - expires_epoch
    held_for = max(0.0, held_for - _stood(expires_epoch, now))
    if held_for < threshold:
        return None
    reservation_id = entry.get("id")
    issue = entry.get("issue")
    key = f"lease_overrun:reservation:{reservation_id}"
    detail = (f"reservation {reservation_id} on {entry.get('host')} (issue {issue}) expired "
              f"{human_duration(held_for)} ago and is still held")
    return Anomaly(kind="lease_overrun", key=key, detail=detail, issue=issue, held_for=held_for)


# -- the real checkers (spec item 1: what `runs.py daemon` builds) --------------------------------

def budget_file_ok(path: Path | None = None) -> bool:
    """``True`` when the live ``machine_budget.json`` is readable as BOM-free UTF-8 JSON, or absent.

    ``slot_budget.load_budget`` tolerates a BOM (``utf-8-sig``) and falls back to the built-in
    defaults on ANY read error, silently -- exactly the 2026-09-24 incident (CLAUDE.md, this
    module's docstring). This is the strict check the daemon needs instead: a BOM or bad JSON here
    is the anomaly, even though `load_budget` itself would never raise over it.
    """

    from junkroan.pob import slot_budget

    target = path if path is not None else slot_budget.budget_path()
    if not target.is_file():
        return True  # no override file is not an anomaly; `load_budget` uses its defaults
    try:
        raw = target.read_bytes()
    except OSError:
        return False
    if raw[:3] == _BOM:
        return False
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(parsed, dict)


def make_budget_checker(path: Path | None = None) -> Callable[[], bool]:
    """``AnomalyGuard(budget_checker=...)``'s real collaborator: closes over the path once."""

    return lambda: budget_file_ok(path)


def make_host_prober(host_cfg: Mapping[str, Any], *, run_on_host: Callable[..., Any] | None = None) -> Callable[[], bool]:
    """``AnomalyGuard(host_prober=...)``'s real collaborator: a trivial PowerShell over SSH.

    ``run_on_host`` is ``hosts.run_on_host`` by default, imported lazily (never copied, #57's own
    rule) so this module still never touches ``hosts.py`` at import time. Any exception -- a
    timeout, a dead SSH alias -- counts as a failed probe, not a crash.
    """

    def probe() -> bool:
        transport = run_on_host
        if transport is None:
            from junkroan.runs import hosts as runs_hosts

            transport = runs_hosts.run_on_host
        try:
            result = transport(host_cfg, _PROBE_SCRIPT)
        except Exception:
            return False
        return getattr(result, "returncode", 1) == 0

    return probe


def make_slot_lister() -> Callable[[], list[dict[str, Any]]]:
    """``AnomalyGuard(slot_lister=...)``'s real collaborator: ``slot_budget.busy_slots()`` rows."""

    from junkroan.pob import slot_budget

    def lister() -> list[dict[str, Any]]:
        try:
            return slot_budget.busy_slots()
        except Exception:
            return []

    return lister


def make_reservation_lister(host: str) -> Callable[[], list[dict[str, Any]]]:
    """``AnomalyGuard(reservation_lister=...)``'s real collaborator: this host's own reservations.

    Filtered to ``host`` because ``var/reservations.json`` is shared across hosts (``hosts.py``'s
    own docstring) -- each host's daemon only reports the overruns it is responsible for.
    """

    from junkroan.pob import slot_budget

    host_key = str(host).strip().lower()

    def lister() -> list[dict[str, Any]]:
        try:
            entries = slot_budget.read_reservations()
        except Exception:
            return []
        return [e for e in entries if str(e.get("host") or "").strip().lower() == host_key]

    return lister


# -- var/anomalies.json: BOM-free, file-locked, stable keys ---------------------------------------

def default_anomalies_path() -> Path:
    override = os.environ.get("JUNKROAN_ANOMALIES_FILE")
    return Path(override) if override else PROJECT_ROOT / "var" / "anomalies.json"


class _FileLock:
    """One exclusive OS lock on ``path``; released by the OS if the holding process dies."""

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
                _lock_fd(fd)
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
            _unlock_fd(fd)
        finally:
            os.close(fd)


if os.name == "nt":
    import msvcrt

    def _lock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@dataclass(slots=True)
class AnomalyState:
    """The persisted content of ``var/anomalies.json``: what has been handled, what still waits."""

    handled: set[str] = field(default_factory=set)
    queue: list[Anomaly] = field(default_factory=list)
    #: keymaster session id -> epoch seconds the guard first saw it waiting for input.
    waiting: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"handled": sorted(self.handled), "queue": [a.as_dict() for a in self.queue],
                "waiting": dict(self.waiting)}

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "AnomalyState":
        handled = {str(k) for k in (data.get("handled") or [])}
        queue = [Anomaly.from_dict(d) for d in (data.get("queue") or [])]
        waiting = {str(k): float(v) for k, v in (data.get("waiting") or {}).items()}
        return AnomalyState(handled=handled, queue=queue, waiting=waiting)


def _read_state(path: Path) -> AnomalyState:
    try:
        raw = path.read_bytes()
    except OSError:
        return AnomalyState()
    if not raw.strip():
        return AnomalyState()
    text = raw[3:].decode("utf-8") if raw[:3] == _BOM else raw.decode("utf-8")
    try:
        return AnomalyState.from_dict(json.loads(text))
    except (ValueError, TypeError):
        return AnomalyState()


def _write_state(path: Path, state: AnomalyState) -> None:
    """Write BOM-free, with stable (sorted) keys, then read it back to prove the round trip."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.as_dict(), indent=1, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    raw = path.read_bytes()
    if raw[:3] == _BOM:
        raise RuntimeError(f"{path} was written with a BOM")


# -- the keymaster launcher (faked in tests; never a real claude.exe from a test) ------------------

class KeymasterLauncher(Protocol):
    def list_sessions(self) -> list[dict[str, Any]]: ...

    def start(self, anomaly: Anomaly) -> tuple[str, list[str]]: ...

    # Optional: `end(session_row) -> bool` ends a keymaster session (the guard logs once per tick
    # and treats the session as live when the launcher has none).


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


LAPTOP_DAEMON_CHECKOUT = r"C:\Coding\poe-junkroan-v2-daemon"


def build_prompt(anomaly: Anomaly) -> str:
    """The one-line "what happened" plus job id / out path / tail, requirement 2's prompt body."""

    lines = [anomaly.detail]
    if anomaly.origin:
        lines.append(
            f"host: {anomaly.origin} (this anomaly is the {anomaly.origin}'s, you run on the PC: read the "
            f"{anomaly.origin}'s files over `ssh {anomaly.origin}`; its daemon checkout is "
            f"{LAPTOP_DAEMON_CHECKOUT})")
    if anomaly.job:
        if len(anomaly.jobs) > 1:
            lines.append(f"jobs: {', '.join(anomaly.jobs)} ({len(anomaly.jobs)} failed jobs, one cause: "
                         f"same ticket, same machine, same error line, submitted within 5 minutes)")
        else:
            lines.append(f"job: {anomaly.job}")
        if anomaly.issue is not None and anomaly.kind != "lease_overrun":
            lines.append(f"issue: #{anomaly.issue} (the job's issue: write your finding there, "
                         f"{KEYMASTER_DOC} step 4)")
    if anomaly.out:
        lines.append(f"out: {anomaly.out}")
    tail = [] if anomaly.origin else _out_tail(anomaly.out)  # a remote path is not readable here
    if tail:
        lines += ["", f"last {OUT_TAIL_LINES} lines:", *tail]
    lines.append(
        "Ending: what you cannot fix mechanically goes as ONE comment on the job's ticket (what you found, "
        "what is left, file:line), then your last message states it and you end `done`. Never end `blocked`, "
        "never leave a `needs` or a question for a human: the ticket comment is mandatory.")
    lines.append(f"Follow {KEYMASTER_DOC}.")
    return "\n".join(lines)


def build_command(anomaly: Anomaly, exe: Path | str = "claude.exe") -> list[str]:
    """The exact command line requirement 2 names, as an argv list (no ``shell=True``)."""

    name = f"keymaster: {anomaly.kind} {anomaly.origin + ' ' if anomaly.origin else ''}{anomaly.target}"
    return _claude_bg().build_argv(exe, name=name, agent="keymaster", effort="medium",
                                   prompt=build_prompt(anomaly))


def _claude_bg() -> Any:
    """``tools/agentops/claude_bg.py``, the one module that builds, starts, lists and stops `--bg` sessions."""

    try:
        from tools.agentops import claude_bg
    except ImportError:
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        from tools.agentops import claude_bg
    return claude_bg


def _find_claude_exe() -> Path:
    """``tools/agentops/dispatch.py``'s own finder, imported rather than copied (requirement 2)."""

    try:
        from tools.agentops.dispatch import find_claude_exe
    except ImportError:
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        from tools.agentops.dispatch import find_claude_exe
    return find_claude_exe()


class ClaudeKeymasterCli:
    """The only ``claude.exe`` calls the anomaly guard makes for a keymaster session."""

    def __init__(self, exe: Path | str | None = None, cwd: Path = PROJECT_ROOT, timeout: float = KEYMASTER_CALL_BOUND_SECONDS) -> None:
        self.exe = exe if exe is not None else _find_claude_exe()
        self.cwd = Path(cwd)
        self.timeout = timeout

    def list_sessions(self) -> list[dict[str, Any]]:
        return _claude_bg().list_sessions(self.exe, cwd=self.cwd, timeout=self.timeout, log=_log,
                                          run=run_bounded)

    def start(self, anomaly: Anomaly) -> tuple[str, list[str]]:
        cmd = build_command(anomaly, self.exe)
        return _claude_bg().start_session(cmd, cwd=self.cwd, timeout=self.timeout, run=run_bounded,
                                          who=f" for {anomaly.key}"), cmd

    def end(self, session: Mapping[str, Any]) -> bool:
        """End a keymaster session for real (`claude stop` does not end the process, #86), as
        ``tools/agentops/dispatch.py``'s ``end_session`` does: stop, re-list, refuse unless the fresh
        row is a background keymaster, then ``taskkill`` its pid. False (logged) on a refusal/failure."""

        session_id = session.get("id")
        if not session_id:
            return False
        flags = _no_window_flags()
        _claude_bg().stop_session(self.exe, str(session_id), cwd=self.cwd, timeout=self.timeout, log=_log,
                                  run=run_bounded)
        fresh = next((s for s in self.list_sessions() if s.get("id") == session_id), None)
        if fresh is None:
            return True
        if fresh.get("kind") != "background" or not _is_keymaster(fresh):
            _log(f"refusing to end {session_id}: kind={fresh.get('kind')!r} name={fresh.get('name')!r}")
            return False
        pid = fresh.get("pid")
        if not pid:
            return True
        kill = run_bounded(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=self.timeout, creationflags=flags)
        if kill.returncode == 0:
            return True
        detail = (kill.stderr or kill.stdout or "").strip()
        if "not found" in detail.lower():
            return True
        _log(f"taskkill /PID {pid} failed: {detail[:200]}")
        return False


def _no_window_flags() -> int:
    import subprocess

    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def make_issue_finder(run: Callable[..., Any] | None = None) -> Callable[[str], int | None]:
    """The real `issue_finder`: the lowest number of an open issue whose body carries the key, else None."""

    import subprocess

    from junkroan.runs.bounded import run_bounded  # #521: a timeout kills the whole gh tree, not only gh

    runner = run if run is not None else run_bounded

    def find(key: str) -> int | None:
        if GUARD.down("gh"):  # #998: gh already failed to answer in this pass: a failed read, not a call
            return None
        args = ["gh", "issue", "list", "--state", "open", "--search", f'"{key}" in:body',
                "--json", "number", "--limit", "5"]
        try:
            result = runner(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=GH_FINDER_TIMEOUT_SECONDS, creationflags=_no_window_flags())
        except subprocess.TimeoutExpired as exc:
            # #998 row 3: gh did not answer in time: one log line, no open issue is read (the same as a
            # failed read above), and gh is skipped for the rest of the pass
            if GUARD.mark_down("gh", repr(exc)):
                _log(f"issue finder: gh did not answer within {GH_FINDER_TIMEOUT_SECONDS:g} s for {key}; "
                     "no open issue is read, the anomaly goes the old way (gh is skipped for the rest of the pass)")
            return None
        except Exception as exc:
            GUARD.mark_down("gh", repr(exc))
            raise
        if result.returncode != 0:
            return None
        try:
            numbers = [int(row["number"]) for row in json.loads(result.stdout or "[]")]
        except (ValueError, TypeError, KeyError):
            return None
        return min(numbers) if numbers else None

    return find


def make_issue_commenter() -> Callable[[int, str], bool]:
    """The real `issue_commenter`: `GhCli.comment` (imported here, `daemon` imports this module)."""

    from junkroan.runs.daemon import GhCli

    return GhCli(cwd=PROJECT_ROOT).comment


def _is_keymaster(session: Mapping[str, Any]) -> bool:
    return bool(_KEYMASTER_NAME_RE.match(str(session.get("name") or "")))


def _keymaster_live(session: Mapping[str, Any]) -> bool:
    return _is_keymaster(session) and session.get("state") not in FINISHED_STATES


def _keymaster_waiting(session: Mapping[str, Any]) -> bool:
    return session.get("state") == "blocked" or session.get("status") == "idle"


def _keymaster_sessions_live(sessions: Iterable[Mapping[str, Any]]) -> bool:
    return any(_keymaster_live(session) for session in sessions)


# -- the guard: what daemon.tick calls ------------------------------------------------------------

#: After a failed keymaster start, no new attempt for this long (10 min, #458).
KEYMASTER_START_RETRY_SECONDS = 600.0


class AnomalyGuard:
    """Detects anomalies, keeps ``var/anomalies.json``, starts/queues the keymaster.

    One call from ``daemon.tick`` (``self.anomalies.check(...)`` if the daemon was given one);
    everything else -- the file, the launcher, the laptop probe, the budget check -- lives here so
    that hunk in ``daemon.py`` stays small.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        launcher: KeymasterLauncher | None = None,
        host_prober: Callable[[], bool] | None = None,
        budget_checker: Callable[[], bool] | None = None,
        slot_lister: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
        reservation_lister: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
        issue_finder: Callable[[str], int | None] | None = None,
        issue_commenter: Callable[[int, str], bool] | None = None,
        lease_overrun_seconds: float = LEASE_OVERRUN_SECONDS,
        laptop_host: str = "laptop",
        probe_interval: float = PROBE_INTERVAL_SECONDS,
        daemon_status_reader: Callable[[], Mapping[str, Any] | None] | None = None,
        fixed_jobs_reader: Callable[[], Iterable[str]] | None = None,
        on_daemon_dead: Callable[[str], None] | None = None,
        host: str | None = None,
        start_keymasters: bool = True,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = _log,
        bench_root: Path | None = None,
        chain_store: Any | None = None,
        issue_labeler: Callable[[int], Any] | None = None,
        missing_script_line: Callable[[Job], str | None] | None = None,
    ) -> None:
        #: Where `benchmark.py` run dirs live (#595); `None` = the repo's `artifacts/benchmark`.
        self.bench_root = bench_root
        #: #862 rule 3: the job store the daemon owns (`Daemon.__init__` sets it), the label step
        #: (`runs.py relabel --issue N`, `None` = skipped) and unit 1's "script does not exist" line for a job.
        #: Without a store a failed job's chain is not closed in code and takes the keymaster path.
        self.chain_store = chain_store
        self.issue_labeler = issue_labeler
        self.missing_script_line = missing_script_line
        self.path = path if path is not None else default_anomalies_path()
        #: This daemon's own host name (issue #120's `job_wrong_host`); `None` in a test that never
        #: passes `wrong_host=` to `check`/`detect`.
        self.host = host
        #: False on the laptop (#467): it keeps detecting and queueing, never starts a keymaster (no
        #: `claude` login there); the PC's daemon takes its queue over ssh (`adopt_remote`).
        self.start_keymasters = start_keymasters
        self._launcher = launcher
        self.host_prober = host_prober
        self.budget_checker = budget_checker
        #: `None` (the default) means "do not check this" -- same convention as `host_prober` /
        #: `budget_checker` above; the real collaborators are `make_slot_lister()` /
        #: `make_reservation_lister(host)` (issue #76), never called from a test.
        self.slot_lister = slot_lister
        self.reservation_lister = reservation_lister
        #: A hand-back anomaly whose key an OPEN issue already carries becomes a comment on it (#395);
        #: `None` means "do not check", as above. Real ones: `make_issue_finder` / `make_issue_commenter`.
        self.issue_finder = issue_finder
        self.issue_commenter = issue_commenter
        self.lease_overrun_seconds = lease_overrun_seconds
        self.laptop_host = laptop_host
        #: The probe runs at most this often; a tick in between re-uses the last result (the SSH cost
        #: of probing every 10 s tick is not worth it, ORCH's call on #57's follow-up).
        self.probe_interval = probe_interval
        self.clock = clock
        self.log = log
        #: Clock time of the first failed probe of the current streak; `None` when the last one passed.
        self._laptop_fail_since: float | None = None
        #: #1183: the laptop daemon's status (read over ssh on each ok probe; `None` = feature off, a
        #: `None` or raising read never counts as dead) and the ids of its queued `--host laptop` jobs.
        self.daemon_status_reader = daemon_status_reader
        self.fixed_jobs_reader = fixed_jobs_reader
        #: #1183: called once with the host right after its `host_daemon_dead` event is written (the PC's
        #: reclaim of the dead host's movable jobs); an exception in it is logged and never stops the event.
        self.on_daemon_dead = on_daemon_dead
        #: Clock time the laptop's daemon was first seen not live on an ok probe; `None` when it was live or unseen.
        self._laptop_dead_since: float | None = None
        #: Clock time of the last `host_daemon_dead` event; a second one waits `HANDBACK_COOLDOWN_SECONDS`.
        self._daemon_dead_raised_at: float | None = None
        #: anomaly key -> clock time of its last failed keymaster start (in memory, #458).
        self._start_failed_at: dict[str, float] = {}
        #: ids of `done` keymaster sessions already ended (or tried once): never ended twice.
        #: Persisted next to ``var/anomalies.json`` (#877): a daemon restart must not re-queue the old ends.
        self._ended_path = self.path.with_name(self.path.name + ".ended")
        self._done_ended: set[str] = self._read_ended()
        #: Ends of keymaster sessions run on one daemon worker thread, never inside a tick (#761).
        self._end_cond = threading.Condition()
        self._end_queue: list[tuple[str, str, dict[str, Any], float, Callable[..., Any]]] = []
        self._end_thread: threading.Thread | None = None
        self._end_busy = False
        self._wait_pending: set[str] = set()
        self._wait_results: dict[str, bool] = {}
        self._list_lock = threading.Lock()
        self._list_thread: threading.Thread | None = None
        self._list_cache: tuple[list[dict[str, Any]], float] | None = None
        self._list_ready = True
        self._list_generation = 0
        self._last_probe_at: float | None = None
        #: The daemon's remote hand-back reads (#308): clock time of each host's first failure of the
        #: current streak, when each host's anomaly was last raised, and the raised ones `check` has not taken yet.
        self._handback_fail_since: dict[str, float] = {}
        self._handback_raised_at: dict[str, float] = {}
        self._handback_pending: list[Anomaly] = []

    def note_handback(self, host: str, ok: bool) -> None:
        """One remote hand-back read of ``host``: a success resets the streak; a failure streak spanning
        `UNREACHABLE_SPAN_SECONDS` from its first failure raises `host_unreachable:<host>`, then nothing
        more for an hour (`HANDBACK_COOLDOWN_SECONDS`)."""

        if ok:
            self._handback_fail_since.pop(host, None)
            return
        now = self.clock()
        since = self._handback_fail_since.setdefault(host, now)
        if now - since - _stood(since, now) < UNREACHABLE_SPAN_SECONDS:
            return
        raised = self._handback_raised_at.get(host)
        if raised is not None and now - raised < HANDBACK_COOLDOWN_SECONDS:
            return
        self._handback_raised_at[host] = now
        self._handback_pending.append(Anomaly(
            kind="host_unreachable", key=f"host_unreachable:{host}", host=host,
            detail=f"{host} unreachable for {human_duration(now - since)} of failed remote hand-backs"))

    @property
    def launcher(self) -> KeymasterLauncher:
        if self._launcher is None:
            self._launcher = ClaudeKeymasterCli()
        return self._launcher

    # -- detection --------------------------------------------------------------------------------

    def detect(
        self, *, ended_jobs: Iterable[Job] = (), running: Mapping[str, str] = {},
        held: Iterable[tuple[Job, Job | None]] = (), wrong_host: Iterable[Job] = (),
        untracked: Iterable[Any] = (), commands: Mapping[str, str] = {},
        follow_main: tuple[str, int, str] | None = None,
    ) -> list[Anomaly]:
        """``follow_main``: `FollowMain.streak()` of this host's daemon (#861). ``commands``: job id -> its command line (a `--loop` run has a longer stuck line, #466).
        ``ended_jobs``: jobs this tick ended. ``running``: job id -> its `out` file path.
        ``held``: (queued job, the ``--after`` predecessor that did not end rc 0) pairs (#82).
        ``wrong_host``: this host's own queued jobs addressed to some other host (#120).
        """

        now = self.clock()
        found: list[Anomaly] = []
        for job in ended_jobs:
            anomaly = detect_job_failed(job)
            if anomaly is not None:
                found.append(anomaly)
        for job, predecessor in held:
            anomaly = detect_held_by_failed_predecessor(job, predecessor)
            if anomaly is not None:
                found.append(anomaly)
        for job in wrong_host:
            found.append(detect_job_wrong_host(job, self.host or "?"))
        for job_id, out in running.items():
            anomaly = detect_job_stuck(job_id, out, now=now,
                                       stale_seconds=stuck_line_seconds(commands.get(str(job_id))),
                                       command=commands.get(str(job_id)), bench_root=self.bench_root)
            if anomaly is not None:
                found.append(anomaly)
        for tree in untracked:
            if _untracked_within_rule(tree, now):
                continue  # an agent's short 1-slot PoB test is legal (#418)
            found.append(detect_untracked_slots(tree, self.host or "?"))
        anomaly = detect_follow_main_failed(self.host or "?", follow_main)
        if anomaly is not None:
            found.append(anomaly)
        if self.host_prober is not None:
            if self._last_probe_at is None or now - self._last_probe_at >= self.probe_interval:
                self._last_probe_at = now
                if self.host_prober():
                    self._laptop_fail_since = None
                    self._note_laptop_daemon(now)
                else:
                    self._laptop_dead_since = None  # a failed probe resets the dead-daemon streak (#382 rule)
                    if self._laptop_fail_since is None:
                        self._laptop_fail_since = now
            failing_for = (None if self._laptop_fail_since is None else
                           now - self._laptop_fail_since - _stood(self._laptop_fail_since, now))
            anomaly = detect_host_unreachable(self.laptop_host, failing_for)
            if anomaly is not None:
                found.append(anomaly)
            anomaly = self._daemon_dead_anomaly(now)
            if anomaly is not None:
                found.append(anomaly)
        if self.budget_checker is not None and not self.budget_checker():
            found.append(detect_budget_unreadable())
        if self.slot_lister is not None:
            for row in self.slot_lister():
                anomaly = detect_lease_overrun_slot(row, now=now, threshold=self.lease_overrun_seconds)
                if anomaly is not None:
                    found.append(anomaly)
        if self.reservation_lister is not None:
            for entry in self.reservation_lister():
                anomaly = detect_lease_overrun_reservation(entry, now=now, threshold=self.lease_overrun_seconds)
                if anomaly is not None:
                    found.append(anomaly)
        return found

    # -- the file -----------------------------------------------------------------------------

    def _append_event(self, event: dict[str, Any]) -> None:
        try:
            from junkroan.runs import hosts as runs_hosts

            runs_hosts.append_event(event)
        except Exception as exc:
            self.log(f"could not append an event ({exc!r}): {event}")

    def _record_host_unreachable(self, anomaly: Anomaly) -> None:
        self.log(f"anomaly {anomaly.key}: {anomaly.detail} (recorded only, no keymaster)")
        self._append_event({"kind": "host_unreachable", "key": anomaly.key, "host": anomaly.host,
                            "detail": anomaly.detail})

    def _record_host_daemon_dead(self, anomaly: Anomaly) -> None:
        self.log(f"anomaly {anomaly.key}: {anomaly.detail} (recorded only, no keymaster)")
        self._append_event({"kind": "host_daemon_dead", "key": anomaly.key, "host": anomaly.host,
                            "detail": anomaly.detail})

    def _note_laptop_daemon(self, now: float) -> None:
        """#1183: one probe of the laptop answered ok. A live daemon, or no readable status, resets the
        dead-daemon streak; a status that is not live starts it (or keeps it running)."""

        status: Mapping[str, Any] | None = None
        if self.daemon_status_reader is not None:
            try:
                status = self.daemon_status_reader()
            except Exception:
                status = None
        if status and not laptop_daemon_live(status, now=now):
            if self._laptop_dead_since is None:
                self._laptop_dead_since = now
        else:
            self._laptop_dead_since = None

    def _daemon_dead_anomaly(self, now: float) -> Anomaly | None:
        """#1183: the `host_daemon_dead` anomaly once the streak has lasted `UNREACHABLE_SPAN_SECONDS`
        (stood time subtracted), at most once per `HANDBACK_COOLDOWN_SECONDS`. The fixed jobs are read
        only when the event is due."""

        since = self._laptop_dead_since
        if since is None:
            return None
        dead_for = now - since - _stood(since, now)
        if dead_for < UNREACHABLE_SPAN_SECONDS:
            return None
        raised = self._daemon_dead_raised_at
        if raised is not None and now - raised < HANDBACK_COOLDOWN_SECONDS:
            return None
        fixed: list[str] = []
        if self.fixed_jobs_reader is not None:
            try:
                fixed = [str(job) for job in self.fixed_jobs_reader()]
            except Exception:
                fixed = []
        anomaly = detect_host_daemon_dead(self.laptop_host, dead_for, fixed_jobs=fixed)
        if anomaly is not None:
            self._daemon_dead_raised_at = now
        return anomaly

    # -- #862: a failed job's chain ends in an outcome, in code ------------------------------------------

    def _chain_root(self, anomaly: Anomaly) -> str | None:
        """The failed job whose chain ``anomaly`` belongs to, or None: it takes the keymaster path.

        `job_failed` with queued followers, and `held_by_failed_predecessor` whose predecessor is a failed
        job of this store; a `job_failed` without followers and every other kind return None.
        """

        store = self.chain_store
        if store is None or anomaly.origin:
            return None
        try:
            if anomaly.kind == "job_failed" and anomaly.job:
                root = store.get(anomaly.job)
            elif anomaly.kind == "held_by_failed_predecessor":
                pred_id = anomaly.key.rsplit(":", 1)[-1]
                if pred_id in ("", "?"):
                    return None
                root = store.get(pred_id)
            else:
                return None
            if root.state != "failed" or not chain_followers(store.jobs(), root.id):
                return None
            return root.id
        except Exception as exc:
            self.log(f"chain root of {anomaly.key} unreadable ({exc!r}); the anomaly goes the old way")
            return None

    def _close_chain(self, root_id: str) -> tuple[str, bool]:
        """One failed job's chain: requeue it once if the failure is mechanical, else cancel every follower.

        Comments once on the failed job's ticket, then runs the label step once when the chain was
        cancelled. Returns ``(outcome, requeued)``; the outcome text is also the comment's second line.
        """

        store = self.chain_store
        job = store.get(root_id)
        followers = chain_followers(store.jobs(), root_id)
        tail = self._tail_of(job)
        missing = None
        if self.missing_script_line is not None:
            try:
                missing = self.missing_script_line(job)
            except Exception as exc:
                self.log(f"missing-script check of {job.id} failed ({exc!r})")
        # The once-rule: a requeue of the same id raises `attempts`; `requeued_from` marks a PC copy (#642).
        mechanical = (missing is None and not job.requeued_from and job.attempts <= 1
                      and is_transient_gh_failure(tail))
        names = ", ".join(f"`{f.id}`" for f in followers)
        outcome = ""
        requeued = False
        if mechanical:
            try:
                store.requeue(job.id)
                requeued = True
                outcome = (f"Requeued once as `{job.id}` (the same id; a gh / network failure in its out tail): "
                           f"{len(followers)} follower(s) follow it again: {names}.")
            except Exception as exc:
                self.log(f"requeue of {job.id} failed ({exc!r}); the chain is cancelled instead")
        if not requeued:
            cancelled: list[str] = []
            kept: list[str] = []
            for follower in followers:
                try:
                    store.cancel(follower.id, reason=f"predecessor {job.id} failed")
                    cancelled.append(f"`{follower.id}`")
                except Exception as exc:
                    self.log(f"cancel of {follower.id} failed ({exc!r})")
                    kept.append(f"`{follower.id}`")
            outcome = f"Cancelled {len(cancelled)} follower(s) of the chain: {', '.join(cancelled) or 'none'}."
            if kept:
                outcome += f" Could not cancel: {', '.join(kept)}."
        self._comment_chain(job, outcome, missing)
        if not requeued and job.issue is not None and not job.no_label and self.issue_labeler is not None:
            try:
                self.issue_labeler(int(job.issue))
            except Exception as exc:
                self.log(f"label step for #{job.issue} failed ({exc!r})")
        self._append_event({"kind": "chain_outcome", "job": job.id, "issue": job.issue,
                            "outcome": "requeued" if requeued else "cancelled",
                            "followers": [f.id for f in followers]})
        self.log(f"chain of {job.id}: {outcome}")
        return outcome, requeued

    @staticmethod
    def _tail_of(job: Job) -> list[str]:
        from junkroan.runs import handback_gate

        return handback_gate.out_tail_lines(job.out)

    def _comment_chain(self, job: Job, outcome: str, missing: str | None) -> None:
        """The one comment on the failed job's ticket (the daemon's `GhCli.comment` through ``issue_commenter``)."""

        if job.issue is None or self.issue_commenter is None:
            self.log(f"chain of {job.id}: no ticket to comment on")
            return
        seconds = _job_seconds(job)
        took = f" after {human_duration(seconds)}" if seconds is not None else ""
        rc = job.rc if job.rc is not None else "null"
        lines = [f"The runs daemon closed the failed chain of `{job.id}` (`{job.tag}`, host `{job.host}`): "
                 f"rc {rc}{took}.", ""]
        if missing:
            lines.append(f"- {missing}")
        lines.append(f"- {outcome}")
        try:
            ok = bool(self.issue_commenter(int(job.issue), "\n".join(lines) + "\n"))
        except Exception as exc:
            self.log(f"issue commenter failed for #{job.issue} ({exc!r})")
            ok = False
        if not ok:
            self.log(f"chain of {job.id}: comment on #{job.issue} NOT posted")

    def _close_chains(self, new: list[Anomaly], state: AnomalyState) -> list[Anomaly]:
        """Take the chain anomalies out of ``new`` and end each chain once (a root once per tick).

        Their keys go into ``state.handled`` -- except after a requeue: the requeued job may fail a
        second time, and that failure must be seen (and then cancels the chain).
        """

        rest: list[Anomaly] = []
        by_root: dict[str, list[Anomaly]] = {}
        for anomaly in new:
            root = self._chain_root(anomaly) if anomaly.kind in ("job_failed", "held_by_failed_predecessor") else None
            if root is None:
                rest.append(anomaly)
            else:
                by_root.setdefault(root, []).append(anomaly)
        for root, anomalies in by_root.items():
            try:
                _outcome, requeued = self._close_chain(root)
            except Exception as exc:
                self.log(f"chain of {root} could not be closed ({exc!r}); the anomaly goes the old way")
                rest.extend(anomalies)
                continue
            if not requeued:
                state.handled.update(a.key for a in anomalies)
        return rest

    def _to_open_issue(self, anomaly: Anomaly) -> bool:
        """A hand-back anomaly whose key an open issue carries: one comment there, no session (#395)."""

        if self.issue_finder is None:
            return False
        try:
            number = self.issue_finder(anomaly.key)
        except Exception as exc:
            self.log(f"issue finder failed for {anomaly.key} ({exc!r}); the anomaly goes the old way")
            return False
        if number is None:
            return False
        stamp = datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d %H:%M")
        text = (f"The runs daemon: {anomaly.detail} (anomaly {anomaly.key}, {stamp} local). "
                "No keymaster session started: this open issue carries the key. Next note at most in 1 h.")
        ok = False
        if self.issue_commenter is not None:
            try:
                ok = bool(self.issue_commenter(number, text))
            except Exception as exc:
                self.log(f"issue commenter failed for #{number} ({exc!r})")
        self.log(f"anomaly {anomaly.key}: open issue #{number} carries it; comment {'posted' if ok else 'NOT posted'}")
        self._append_event({"kind": "anomaly_to_issue", "key": anomaly.key, "issue": number, "ok": ok})
        return True

    def _cached_sessions(self) -> list[dict[str, Any]] | None:
        """The launcher's session list, never blocking the tick for long (#647).

        ``launcher.list_sessions`` runs in a daemon thread, one call in flight at most; the tick waits
        ``SESSION_LIST_WAIT_SECONDS`` for it and otherwise reads the last answer. None = no answer
        younger than ``SESSION_LIST_MAX_AGE_SECONDS``.
        """

        with self._list_lock:
            thread = self._list_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._refresh_sessions, args=(self._list_generation,), name="keymaster-list", daemon=True)
                self._list_thread = thread
                thread.start()
        thread.join(SESSION_LIST_WAIT_SECONDS)
        with self._list_lock:
            cache = self._list_cache
            ready = cache is not None and self.clock() - cache[1] <= SESSION_LIST_MAX_AGE_SECONDS
            if ready != self._list_ready:
                self._list_ready = ready
                if not ready:
                    self.log("anomalies: keymaster list not ready; starting none this tick")
            return list(cache[0]) if ready and cache is not None else None

    def _refresh_sessions(self, generation: int) -> None:
        try:
            rows = list(self.launcher.list_sessions())
        except Exception as exc:
            self.log(f"keymaster session list failed ({exc!r})")
            return
        with self._list_lock:
            if generation == self._list_generation:  # not overtaken by a keymaster start meanwhile
                self._list_cache = (rows, self.clock())

    def _keymasters_live(self, state: AnomalyState) -> bool:
        """Is a keymaster session live this tick? Tracks the waiting ones in ``state.waiting`` and
        ends one that waited past ``KEYMASTER_WAIT_LIMIT_SECONDS`` (counted not live from then on)."""

        now = self.clock()
        cached = self._cached_sessions()
        if cached is None:
            return True  # not ready: start no keymaster this tick, a duplicate is worse than a delay
        listed = list(cached)
        rows = [s for s in listed if _keymaster_live(s)]
        waiting_now = {str(s.get("id")): s for s in rows if _keymaster_waiting(s)}
        state.waiting = {sid: state.waiting.get(sid, now) for sid in waiting_now}
        end = getattr(self.launcher, "end", None)
        warned = False
        # A `--bg` session whose turn ended is `done` but stays listed and alive: end it at once, once.
        for row in listed:
            if not (_is_keymaster(row) and row.get("state") == "done"):
                continue
            sid = str(row.get("id"))
            if sid in self._done_ended:
                continue
            if end is None:
                continue
            self._done_ended.add(sid)
            self._write_ended()
            self._enqueue_end("done", sid, row, 0.0, end)
        waiting_results = self._take_wait_results()
        for sid, row in waiting_now.items():
            waited = now - state.waiting[sid] - _stood(state.waiting[sid], now)
            if waited < KEYMASTER_WAIT_LIMIT_SECONDS:
                continue
            if end is None:
                if not warned:
                    self.log("the launcher has no `end`: a keymaster session waiting too long stays live")
                    warned = True
                continue
            if sid not in waiting_results:
                self._enqueue_end("waiting", sid, row, waited, end)
        self._wait_for_ends()
        # An end finished by the worker (now or in an earlier tick) applies its bookkeeping here; a
        # failed one is retried next tick, one still in flight keeps the session live.
        waiting_results.update(self._take_wait_results())
        for sid, row in waiting_now.items():
            if waiting_results.get(sid) is True and sid in state.waiting:
                del state.waiting[sid]
                rows.remove(row)
        return bool(rows)

    def _read_ended(self) -> set[str]:
        try:
            data = json.loads(self._ended_path.read_text(encoding="utf-8-sig"))
            return {str(s) for s in data}
        except (OSError, ValueError, TypeError):
            return set()

    def _write_ended(self) -> None:
        try:
            self._ended_path.parent.mkdir(parents=True, exist_ok=True)
            self._ended_path.write_text(json.dumps(sorted(self._done_ended)) + "\n", encoding="utf-8")
        except OSError as exc:
            self.log(f"could not persist the ended-sessions list ({exc!r})")

    def _enqueue_end(self, kind: str, sid: str, row: dict[str, Any], waited: float, end: Callable[..., Any]) -> None:
        """Queue one `end` for the single worker thread (#761); a waiting end already queued is not queued twice."""

        with self._end_cond:
            if kind == "waiting":
                if sid in self._wait_pending:
                    return
                self._wait_pending.add(sid)
            entry = (kind, sid, row, waited, end)
            if kind == "waiting":  # a waiting end goes before every queued `done` end (#877)
                at = next((i for i, queued in enumerate(self._end_queue) if queued[0] == "done"), len(self._end_queue))
                self._end_queue.insert(at, entry)
            else:
                self._end_queue.append(entry)
            thread = self._end_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._end_worker, name="keymaster-end", daemon=True)
                self._end_thread = thread
                thread.start()

    def _end_worker(self) -> None:
        while True:
            with self._end_cond:
                if not self._end_queue:
                    self._end_busy = False
                    self._end_thread = None
                    self._end_cond.notify_all()
                    return
                kind, sid, row, waited, end = self._end_queue.pop(0)
                self._end_busy = True
            ok = self._do_end(kind, sid, row, waited, end)
            if kind == "waiting":
                with self._end_cond:
                    self._wait_pending.discard(sid)
                    self._wait_results[sid] = ok

    def _do_end(self, kind: str, sid: str, row: dict[str, Any], waited: float, end: Callable[..., Any]) -> bool:
        what = "finished keymaster session" if kind == "done" else "keymaster session"
        try:
            ended = bool(end(row))
        except Exception as exc:
            self.log(f"could not end {what} {sid} ({exc!r})")
            return False
        if not ended:
            if kind == "done":
                self.log(f"could not end {what} {sid}")
            return False
        if kind == "done":
            self.log(f"keymaster session {sid} ended: its turn is done")
            self._append_event({
                "kind": "keymaster_ended", "session": sid, "name": row.get("name"),
                "reason": "done",
            })
        else:
            self.log(f"keymaster session {sid} ended after waiting {human_duration(waited)} for input")
            self._append_event({
                "kind": "keymaster_ended", "session": sid, "name": row.get("name"),
                "waited": human_duration(waited), "waited_seconds": round(waited, 1),
                "reason": "waited for input past 10 min; its anomaly stays handled and is left to its issue",
            })
        return True

    def _wait_for_ends(self) -> None:
        """Wait at most ``END_WAIT_SECONDS`` for the end queue to drain."""

        with self._end_cond:
            self._end_cond.wait_for(lambda: not self._end_queue and not self._end_busy, END_WAIT_SECONDS)

    def _take_wait_results(self) -> dict[str, bool]:
        with self._end_cond:
            results, self._wait_results = self._wait_results, {}
        return results

    def drain_ends(self, timeout: float = 30.0) -> None:
        """Wait for every queued end to finish (tests, shutdown)."""

        with self._end_cond:
            self._end_cond.wait_for(lambda: not self._end_queue and not self._end_busy, timeout)

    def adopt_remote(
        self, host: str, entries: Iterable[Mapping[str, Any]], mark_taken: Callable[[str], bool],
        job_state: Callable[[str], str | None] | None = None,
    ) -> list[Anomaly]:
        """Take another host's queued anomalies into this queue, once each (#467).

        The key is prefixed with the host, `origin` names it; ``mark_taken(original key)`` removes the
        entry from that host's queue over ssh. An entry already adopted (its prefixed key is in
        ``handled``) is only marked again, never queued twice; a failed mark retries next pass. The
        normal start loop of :meth:`check` then starts the keymaster, back-off and one-at-a-time included.
        """

        adopted: list[Anomaly] = []
        with _FileLock(self.path.with_name(self.path.name + ".lock")):
            state = _read_state(self.path)
            changed = False
            for raw in entries:
                try:
                    remote = Anomaly.from_dict(raw)
                except Exception as exc:
                    self.log(f"remote anomaly from {host} unreadable ({exc!r}): {raw!r}")
                    continue
                key = f"{host}:{remote.key}"
                ended = None
                if job_state is not None and remote.kind == "job_stuck" and remote.job:
                    try:
                        ended = job_state(remote.job)
                    except Exception:
                        ended = None
                if ended in ("done", "failed"):
                    self.log(f"anomaly {key} not adopted: {host}'s job {remote.job} ended ({ended})")
                elif key not in state.handled:
                    local = Anomaly.from_dict({**remote.as_dict(), "key": key, "origin": host})
                    state.handled.add(key)
                    if merge_into_queue(state.queue, local):
                        self.log(f"anomaly {key} joins a queued {host} failure of the same cause")
                        changed = True
                        try:
                            ok = bool(mark_taken(remote.key))
                        except Exception:
                            ok = False
                        if not ok:
                            self.log(f"could not mark {remote.key} taken on {host}; retrying next pass")
                        continue
                    state.queue.append(local)
                    adopted.append(local)
                    changed = True
                    self.log(f"anomaly {key}: {local.detail}")
                try:
                    ok = bool(mark_taken(remote.key))
                except Exception as exc:
                    self.log(f"could not mark {remote.key} taken on {host} ({exc!r})")
                    ok = False
                if not ok:
                    self.log(f"could not mark {remote.key} taken on {host}; retrying next pass")
            if changed:
                _write_state(self.path, state)
        return adopted

    def check(
        self, *, ended_jobs: Iterable[Job] = (), running: Mapping[str, str] = {},
        held: Iterable[tuple[Job, Job | None]] = (), wrong_host: Iterable[Job] = (),
        untracked: Iterable[Any] = (), commands: Mapping[str, str] = {},
        job_state: Callable[[str], str | None] | None = None,
        origin_job_state: Callable[[str, str], str | None] | None = None,
        follow_main: tuple[str, int, str] | None = None,
    ) -> list[Anomaly]:
        """One tick: detect, dedupe into ``var/anomalies.json``, start what fits.

        Returns the anomalies started this call (empty when nothing new is queued and no session
        is free, or when everything new only joined the queue).
        ``job_state``: job id -> its store state; a queued `job_stuck` whose job is done / failed is
        dropped before a keymaster starts for it (#466).
        """

        detected = self.detect(ended_jobs=ended_jobs, running=running, held=held,
                               wrong_host=wrong_host,
                               untracked=untracked, commands=commands, follow_main=follow_main)
        dead_hosts: list[str] = []  # #1183: called after the lock is released (the reclaim makes ssh round trips)
        with _FileLock(self.path.with_name(self.path.name + ".lock")):
            state = _read_state(self.path)
            new = [a for a in detected if a.key not in state.handled
                   and a.kind not in ("host_unreachable", "host_daemon_dead")]
            for anomaly in detected:
                if anomaly.kind == "host_daemon_dead":  # #1183: one event line, no queue (cooldown is in detect)
                    self._record_host_daemon_dead(anomaly)
                    dead_hosts.append(anomaly.host)
            # A lost laptop link is only recorded (#674): one log line and one event each time it is raised,
            # no keymaster session, no issue, no comment. Routing reads the guard's own state, not this.
            for anomaly in detected:
                if anomaly.kind == "host_unreachable" and anomaly.key not in state.handled:
                    state.handled.add(anomaly.key)
                    self._record_host_unreachable(anomaly)
            for anomaly in self._handback_pending:
                self._record_host_unreachable(anomaly)
            self._handback_pending = []
            new = self._close_chains(new, state)
            for anomaly in new:
                state.handled.add(anomaly.key)
                if merge_into_queue(state.queue, anomaly):
                    self.log(f"anomaly {anomaly.key} joins a queued failure of the same cause: {anomaly.detail}")
                    continue
                state.queue.append(anomaly)
                self.log(f"anomaly {anomaly.key}: {anomaly.detail}")
                if anomaly.kind == "held_by_failed_predecessor":
                    # One event per held job, the first time it is seen (#82 requirement 2): `runs
                    # watch` shows the hold even when no keymaster session is free to take it.
                    self._append_event({
                        "kind": "held_by_failed_predecessor", "job": anomaly.job,
                        "detail": anomaly.detail,
                    })
                if anomaly.kind == "lease_overrun":
                    # Requirement 1's own event, one per holder, written the moment it is new --
                    # independent of whether a keymaster session ever starts for it (at most one
                    # runs at a time, so most queued anomalies never get their own session).
                    self._append_event({
                        "kind": "lease_overrun", "pid": anomaly.pid, "issue": anomaly.issue,
                        "held_for": anomaly.held_for,
                    })

            if job_state is not None or origin_job_state is not None:
                kept: list[Anomaly] = []
                for anomaly in state.queue:
                    ended = None
                    if anomaly.kind == "job_stuck" and anomaly.job:
                        try:
                            if anomaly.origin:  # another host's job: its own store, not ours (#467)
                                ended = origin_job_state(anomaly.origin, anomaly.job) if origin_job_state else None
                            else:
                                ended = job_state(anomaly.job) if job_state else None
                        except Exception:
                            ended = None
                    if ended in ("done", "failed"):
                        self._start_failed_at.pop(anomaly.key, None)
                        self.log(f"anomaly {anomaly.key} dropped from the queue: job {anomaly.job} ended ({ended})")
                        continue
                    kept.append(anomaly)
                state.queue = kept

            started: list[Anomaly] = []
            live = self._keymasters_live(state) if self.start_keymasters else True
            while not live and state.queue:
                head = state.queue[0]
                failed_at = self._start_failed_at.get(head.key)
                if failed_at is not None and self.clock() - failed_at < KEYMASTER_START_RETRY_SECONDS:
                    break  # a failed start waits out its back-off, the anomaly stays at the head (#458)
                anomaly = state.queue.pop(0)
                try:
                    session_id, _cmd = self.launcher.start(anomaly)
                except Exception as exc:
                    if anomaly.key not in self._start_failed_at:  # logged once per key (#458)
                        self.log(f"could not start a keymaster session for {anomaly.key} ({exc!r})")
                    self._start_failed_at[anomaly.key] = self.clock()
                    state.queue.insert(0, anomaly)  # retried after the back-off, at the head
                    break
                self._start_failed_at.pop(anomaly.key, None)
                with self._list_lock:
                    self._list_generation += 1
                    self._list_cache = None  # the cached list lacks the session just started
                self.log(f"keymaster session {session_id} started for {anomaly.key}")
                self._append_event({"kind": "keymaster_start", "anomaly": anomaly.as_dict(), "session": session_id})
                started.append(anomaly)
                live = True  # at most one at a time: the rest of the queue waits

            _write_state(self.path, state)
        for host in dead_hosts:  # #1183: once per event, outside the anomalies lock
            if self.on_daemon_dead is None:
                break
            try:
                self.on_daemon_dead(host)
            except Exception as exc:
                self.log(f"on_daemon_dead for host_daemon_dead:{host} failed ({exc!r})")
        return started


def take_queued(key: str, path: Path | None = None) -> bool:
    """Drop ``key`` from the queue of ``var/anomalies.json`` (it stays in ``handled``): another host's
    daemon started the keymaster for it (#467, ``runs.py anomaly-taken``). True when it was queued."""

    path = path if path is not None else default_anomalies_path()
    with _FileLock(path.with_name(path.name + ".lock")):
        state = _read_state(path)
        kept = [a for a in state.queue if a.key != key]
        if len(kept) == len(state.queue):
            return False
        state.queue = kept
        _write_state(path, state)
    return True


__all__ = [
    "take_queued",
    "Anomaly",
    "AnomalyGuard",
    "AnomalyState",
    "ClaudeKeymasterCli",
    "KeymasterLauncher",
    "FINISHED_STATES",
    "KEYMASTER_WAIT_LIMIT_SECONDS",
    "LEASE_OVERRUN_SECONDS",
    "LIVE_STATES",
    "OUT_TAIL_LINES",
    "PROBE_INTERVAL_SECONDS",
    "STUCK_OUTPUT_SECONDS",
    "UNREACHABLE_SPAN_SECONDS",
    "budget_file_ok",
    "build_command",
    "build_prompt",
    "default_anomalies_path",
    "detect_budget_unreadable",
    "detect_host_daemon_dead",
    "detect_host_unreachable",
    "detect_job_failed",
    "detect_job_stuck",
    "detect_job_wrong_host",
    "detect_lease_overrun_reservation",
    "detect_lease_overrun_slot",
    "make_budget_checker",
    "make_host_prober",
    "make_reservation_lister",
    "make_slot_lister",
]
