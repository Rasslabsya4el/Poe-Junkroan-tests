"""Read another host's job store over its SSH alias, cached (issue #81).

The runs job store (``junkroan.runs.store``) is per checkout: the laptop runs its own daemon
against its own ``artifacts/runs/jobs.jsonl``, so the PC monitor cannot see the laptop's jobs by
reading its own store. This module reads the laptop's ``jobs.jsonl`` over SSH (the same ``ssh
<alias>`` idea ``junkroan.runs.hosts.run_on_host`` and ``anomalies.make_host_prober`` use -- not
imported directly because both need a different timeout here, and #81's own follow-up found that
plain ``-Command "$p = '...'; ..."`` gets its ``$p`` eaten on the way through ssh (the remote shell
expands or re-tokenizes the argument before the inner powershell ever sees it: a real round trip
against the laptop failed with `` "= : The term '=' is not recognized..." ``). The fix is
``-EncodedCommand``: the script travels as base64 of UTF-16LE text, a form no shell layer can
touch (:mod:`junkroan.runs.ssh_transport`, shared with ``hosts.run_on_host`` since #87).

Nothing here opens a real SSH connection in a test: :func:`read_remote_jobs` takes an injected
``transport`` callable, and :class:`LaptopJobsCache` takes an injected ``reader`` (and, for the
background refresh, an injected ``executor``).

Caching and never blocking the snapshot (requirement 1, #81 follow-up): a real round trip to the
laptop takes about 1.3 s, so a short foreground timeout flaps constantly. :class:`LaptopJobsCache`
never runs the SSH call on the caller's thread: :meth:`read` always returns immediately with
whatever it already knows -- a fresh good reading (no I/O), a stale one while a refresh is already
in flight, or, before the very first reading ever completes, an explicit ``pending`` reading ("still
reading", not "no jobs" and not "unreachable"). At most one refresh runs at a time, at most once
per ``ttl`` seconds, in the background (a daemon thread by default; tests inject a synchronous
``executor`` to make the refresh deterministic). A refresh that fails never erases the last good
reading: it is still served, marked ``stale``, with its age -- ``ok=False`` only once an attempt
has actually failed, never merely because the TTL passed.
"""

from __future__ import annotations

import base64
import gzip
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import subprocess

from junkroan.runs.hosts import (
    SKIPPED_SSH_STDERR,
    SSH_TIMEOUT_SECONDS,
    daemon_repo_path,
    describe_ssh_failure,
    note_ssh_failure,
    note_ssh_result,
    ssh_key,
)
from junkroan.runs.pass_guard import GUARD
from junkroan.runs.ssh_transport import build_ssh_argv
from junkroan.runs.store import Job, fold

#: How long a good reading is served with no SSH round trip at all, and how often a failed host is
#: retried in the background.
DEFAULT_TTL_SECONDS = 60.0
#: The SSH round trip's own timeout for the daemon's background reads (#509): a read that answers at all
#: answers well under 30 s on this link (payload ~10 KB since 8744f76, `ssh laptop hostname` alone up to
#: 5.3 s); a read that does not is a link drop.
DEFAULT_TIMEOUT_SECONDS = 30.0
#: A foreground caller a human waits on (`runs.py relabel`) passes this explicitly.
FOREGROUND_TIMEOUT_SECONDS = 10.0


class RemoteStoreUnreachable(RuntimeError):
    """The remote host's job store could not be read (a dead SSH alias, a timeout, a bad reply)."""


class RemoteJobsLogMissing(RuntimeError):
    """The host answered, but its job log file does not exist at ``path`` (#910): a wrong path in
    ``config/hosts.json``, never "no jobs". Not an unreachable host: the link works."""

    def __init__(self, path: str) -> None:
        super().__init__(f"the job log {path} does not exist on the host")
        self.path = path


#: What the remote scripts print for a job log that is absent (not base64: ``-`` is outside its alphabet).
_MISSING_MARK = "JUNKROAN-JOBS-LOG-MISSING"


def remote_jobs_log_path(host_cfg: Mapping[str, Any]) -> str:
    """Where the daemon on that host WRITES ``jobs.jsonl`` (#910). ``jobs_log_path`` in the host's entry
    wins: a daemon in a linked git worktree (the laptop's ``...-daemon``) writes under the MAIN checkout
    (``store.main_root``), not under its own ``artifacts``. Default: ``<daemon_repo_path>/artifacts/runs/jobs.jsonl``."""

    explicit = host_cfg.get("jobs_log_path")
    if explicit:
        return str(explicit)
    return f"{daemon_repo_path(host_cfg)}\\artifacts\\runs\\jobs.jsonl"


def _runs_dir_of(jobs_path: str) -> str:
    return jobs_path.rsplit("\\", 1)[0]


# -- the transport (faked in tests; never a real SSH call from a test) -----------------------------

def default_remote_transport(host_cfg: Mapping[str, Any], script: str, *, timeout: float) -> Any:
    """One ``ssh <alias> powershell -EncodedCommand <...>`` call, bounded at :data:`SSH_TIMEOUT_SECONDS` (#998).

    Skipped (rc 255, :data:`SKIPPED_SSH_STDERR`) when the host already failed to answer in this pass; a
    timeout or an OS error marks the host down for the pass (:func:`hosts.note_ssh_failure`).
    """

    from junkroan.runs.bounded import run_bounded

    argv = build_ssh_argv(host_cfg, script)
    if GUARD.down(ssh_key(host_cfg)):
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr=SKIPPED_SSH_STDERR)
    try:
        result = run_bounded(argv, capture_output=True, text=True, timeout=min(timeout, SSH_TIMEOUT_SECONDS))
    except Exception as exc:
        note_ssh_failure(host_cfg, exc)
        raise
    note_ssh_result(host_cfg, result)     # #998: ssh could not reach the host (rc 255) -> down for the pass
    return result


def _raise_if_host_down(host_cfg: Mapping[str, Any]) -> None:
    """#998: a read of a host that already failed to answer in this pass is an unreadable read, no call made."""

    if GUARD.down(ssh_key(host_cfg)):
        raise RemoteStoreUnreachable(SKIPPED_SSH_STDERR)


#: PowerShell (5.1-compatible) function: file bytes -> GZip -> base64. The ssh stdout path from the laptop
#: moves only ~4-15 KB/s (#509), so a 118 KB jobs file must cross as ~20 KB.
_PS_GZ_FUNCTION = (
    "function G($p) { $b = [IO.File]::ReadAllBytes($p); $m = New-Object IO.MemoryStream; "
    "$z = New-Object IO.Compression.GZipStream($m, [IO.Compression.CompressionMode]::Compress); "
    "$z.Write($b, 0, $b.Length); $z.Close(); [Convert]::ToBase64String($m.ToArray()) }; "
)


def decode_remote_blob(encoded: str) -> bytes:
    """Inverse of the remote ``G`` function: base64 -> gunzip -> the file's bytes."""

    return gzip.decompress(base64.b64decode(encoded))


def _remote_jobs_script(repo_path: str, jobs_path: str | None = None) -> str:
    """GZip+base64 of the remote ``jobs.jsonl`` bytes (avoids every powershell quoting and encoding
    hazard for a file that can hold arbitrary JSON text, same idea as ``hosts._laptop_mode_script``'s
    own base64 round trip); the :data:`_MISSING_MARK` text when the file is absent (#910)."""

    path = jobs_path or f"{repo_path}\\artifacts\\runs\\jobs.jsonl"
    return f"{_PS_GZ_FUNCTION}$p = '{path}'; if (Test-Path $p) {{ G $p }} else {{ '{_MISSING_MARK}' }}"


#: PowerShell (5.1) function ``TrimJobs``: the jobs file as GZip+base64 with the bodies the PC daemon can no longer
#: use left out (#509 unit 3): a `handback` line is dropped when a LATER `posted` line without an `issue`
#: (the receipt of the job's own issue, `store.py` mark-posted) exists and the job has no `add_issue` line (so
#: no extra issue still waits for the body); a `runissue` line is dropped when a later `runissue_made` exists.
#: `fold` still ends in the same `posted` / `run_issue` and the daemon's `handback_pending and handback_body` /
#: `run_issue is None and run_issue_body` tests are False for exactly those jobs either way. Every other line
#: travels untouched (original text, not re-serialised).
_PS_TRIMMED_JOBS_FUNCTION = (
    "function TrimJobs($p) { $l = [IO.File]::ReadAllLines($p, [Text.Encoding]::UTF8); $r = @(); "
    "$lp = @{}; $lr = @{}; $ai = @{}; "
    "for ($i = 0; $i -lt $l.Length; $i++) { if ($l[$i].Trim()) { $o = $l[$i] | ConvertFrom-Json; $r += $o; "
    "if ($o.op -eq 'posted' -and -not $o.PSObject.Properties['issue']) { $lp[$o.job] = $i } "
    "elseif ($o.op -eq 'runissue_made') { $lr[$o.job] = $i } "
    "elseif ($o.op -eq 'add_issue') { $ai[$o.job] = 1 } } else { $r += $null } }; "
    "$k = New-Object System.Collections.Generic.List[string]; "
    "for ($i = 0; $i -lt $l.Length; $i++) { $o = $r[$i]; if ($o -eq $null) { continue }; "
    "if ($o.op -eq 'handback' -and $lp.ContainsKey($o.job) -and $lp[$o.job] -gt $i -and -not $ai.ContainsKey($o.job)) { continue }; "
    "if ($o.op -eq 'runissue' -and $lr.ContainsKey($o.job) -and $lr[$o.job] -gt $i) { continue }; "
    "$k.Add($l[$i]) }; "
    "$b = [Text.Encoding]::UTF8.GetBytes(($k -join \"`n\")); $m = New-Object IO.MemoryStream; "
    "$z = New-Object IO.Compression.GZipStream($m, [IO.Compression.CompressionMode]::Compress); "
    "$z.Write($b, 0, $b.Length); $z.Close(); [Convert]::ToBase64String($m.ToArray()) }; "
)


#: Separates the two base64 blobs `_remote_snapshot_script` prints on their own lines -- never
#: mistaken for base64 output (base64 uses only `A-Za-z0-9+/=`).
_SNAPSHOT_SPLIT = "---JUNKROAN-SNAPSHOT-SPLIT---"


def _remote_snapshot_script(repo_path: str, host: str, budget_repo_path: str | None = None,
                            jobs_path: str | None = None) -> str:
    """GZip+base64-encodes ``jobs.jsonl`` (without the hand-back / Run-issue bodies already delivered,
    :data:`_PS_TRIMMED_JOBS_FUNCTION`, #509), ``daemon-<host>.json`` AND ``var/machine_budget.json`` in one
    round trip (issues #73, #471): the monitor's laptop row must not cost the daemon-status read a
    second ``ssh`` call, and placement reads the host's real mode from the same reply.

    ``repo_path`` is the daemon checkout (jobs, status); the budget lives under ``budget_repo_path``
    (the host's plain ``repo_path``, where ``apply_mode`` writes it; default ``repo_path``)."""

    jobs_path = jobs_path or f"{repo_path}\\artifacts\\runs\\jobs.jsonl"
    status_path = f"{_runs_dir_of(jobs_path)}\\daemon-{host}.json"   # the daemon writes both into one runs dir
    budget_path = f"{budget_repo_path or repo_path}\\var\\machine_budget.json"
    return (
        f"{_PS_GZ_FUNCTION}{_PS_TRIMMED_JOBS_FUNCTION}$j = '{jobs_path}'; $s = '{status_path}'; $b = '{budget_path}'; "
        f"$jb = if (Test-Path $j) {{ TrimJobs $j }} else {{ '{_MISSING_MARK}' }}; "
        "$sb = if (Test-Path $s) { G $s } else { '' }; "
        "$bb = if (Test-Path $b) { G $b } else { '' }; "
        f"Write-Output $jb; Write-Output '{_SNAPSHOT_SPLIT}'; Write-Output $sb; "
        f"Write-Output '{_SNAPSHOT_SPLIT}'; Write-Output $bb"
    )


def read_remote_jobs(
    host_cfg: Mapping[str, Any], *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Callable[..., Any] | None = None,
) -> list[Job]:
    """Every job in ``host_cfg``'s own ``artifacts/runs/jobs.jsonl``, read over SSH.

    Raises :class:`RemoteStoreUnreachable` on any transport failure or bad reply, :class:`RemoteJobsLogMissing`
    when the log file is absent (#910) -- an empty list only ever means "the existing log has no jobs".
    """

    _raise_if_host_down(host_cfg)
    run = transport if transport is not None else default_remote_transport
    started = time.monotonic()
    try:
        result = run(host_cfg, _remote_jobs_script(daemon_repo_path(host_cfg), remote_jobs_log_path(host_cfg)),
                     timeout=timeout)
    except Exception as exc:
        raise RemoteStoreUnreachable(describe_ssh_failure(exc, time.monotonic() - started)) from exc

    if getattr(result, "returncode", 1) != 0:
        raise RemoteStoreUnreachable(describe_ssh_failure(result, time.monotonic() - started))

    encoded = (getattr(result, "stdout", "") or "").strip()
    if encoded == _MISSING_MARK:
        raise RemoteJobsLogMissing(remote_jobs_log_path(host_cfg))
    if not encoded:
        return []
    try:
        raw = decode_remote_blob(encoded).decode("utf-8")
    except Exception as exc:
        raise RemoteStoreUnreachable(f"could not decode the remote store: {exc!r}") from exc

    records = []
    for line in raw.split("\n"):
        line = line.strip()
        if line:
            records.append(json.loads(line))
    try:
        return list(fold(records).values())
    except Exception as exc:
        raise RemoteStoreUnreachable(f"could not fold the remote store: {exc!r}") from exc


def read_remote_anomalies(
    host_cfg: Mapping[str, Any], *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """The queued anomalies in ``host_cfg``'s own ``var/anomalies.json``, read over SSH (#467).

    Empty list = file absent or nothing queued; :class:`RemoteStoreUnreachable` on any failure.
    """

    _raise_if_host_down(host_cfg)
    path = f"{daemon_repo_path(host_cfg)}\\var\\anomalies.json"
    script = f"{_PS_GZ_FUNCTION}$p = '{path}'; if (Test-Path $p) {{ G $p }} else {{ '' }}"
    run = transport if transport is not None else default_remote_transport
    try:
        result = run(host_cfg, script, timeout=timeout)
    except Exception as exc:
        raise RemoteStoreUnreachable(str(exc)) from exc
    if getattr(result, "returncode", 1) != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        raise RemoteStoreUnreachable(detail or "non-zero exit")
    encoded = (getattr(result, "stdout", "") or "").strip()
    if not encoded:
        return []
    try:
        data = json.loads(decode_remote_blob(encoded).decode("utf-8-sig"))
    except Exception as exc:
        raise RemoteStoreUnreachable(f"could not decode the remote anomalies: {exc!r}") from exc
    queue = data.get("queue") if isinstance(data, dict) else None
    return [d for d in (queue or []) if isinstance(d, dict)]


@dataclass(frozen=True)
class RemoteSnapshot:
    """One combined round trip's answer: the remote host's jobs AND its daemon status file."""

    jobs: list[Job]
    daemon_status: dict[str, Any] | None
    #: ``var/machine_budget.json`` of the same host (#471); None when missing, empty or not JSON.
    budget: dict[str, Any] | None = None


def read_remote_snapshot(
    host_cfg: Mapping[str, Any], *,
    host: str = "laptop",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Callable[..., Any] | None = None,
) -> RemoteSnapshot:
    """``jobs.jsonl`` AND ``daemon-<host>.json`` in ONE ``ssh`` round trip (issue #73).

    Raises :class:`RemoteStoreUnreachable` exactly like :func:`read_remote_jobs`; the daemon status
    half is best-effort within that same reply -- an absent or unparsable status file is simply
    ``None``, never its own failure (the jobs half is the one thing this call must not silently
    lose).
    """

    _raise_if_host_down(host_cfg)
    run = transport if transport is not None else default_remote_transport
    started = time.monotonic()
    try:
        result = run(host_cfg, _remote_snapshot_script(
            daemon_repo_path(host_cfg), host, str(host_cfg.get("repo_path") or daemon_repo_path(host_cfg)),
            remote_jobs_log_path(host_cfg)), timeout=timeout)
    except Exception as exc:
        raise RemoteStoreUnreachable(describe_ssh_failure(exc, time.monotonic() - started)) from exc

    if getattr(result, "returncode", 1) != 0:
        raise RemoteStoreUnreachable(describe_ssh_failure(result, time.monotonic() - started))

    stdout = (getattr(result, "stdout", "") or "")
    parts = stdout.split(_SNAPSHOT_SPLIT)
    jobs_encoded = parts[0].strip()
    status_encoded = parts[1].strip() if len(parts) > 1 else ""
    budget_encoded = parts[2].strip() if len(parts) > 2 else ""

    if jobs_encoded == _MISSING_MARK:
        raise RemoteJobsLogMissing(remote_jobs_log_path(host_cfg))
    jobs: list[Job] = []
    if jobs_encoded:
        try:
            raw = decode_remote_blob(jobs_encoded).decode("utf-8")
        except Exception as exc:
            raise RemoteStoreUnreachable(f"could not decode the remote store: {exc!r}") from exc
        records = [json.loads(line) for line in raw.split("\n") if line.strip()]
        try:
            jobs = list(fold(records).values())
        except Exception as exc:
            raise RemoteStoreUnreachable(f"could not fold the remote store: {exc!r}") from exc

    status: dict[str, Any] | None = None
    if status_encoded:
        try:
            status_raw = json.loads(decode_remote_blob(status_encoded).decode("utf-8"))
            if isinstance(status_raw, dict):
                status = status_raw
        except Exception:
            status = None  # best-effort: a broken status half never fails the jobs read

    budget: dict[str, Any] | None = None
    if budget_encoded:
        try:
            budget_raw = json.loads(decode_remote_blob(budget_encoded).decode("utf-8-sig"))
            if isinstance(budget_raw, dict):
                budget = budget_raw
        except Exception:
            budget = None  # best-effort, like the status half

    return RemoteSnapshot(jobs=jobs, daemon_status=status, budget=budget)


# -- the reading + the cache ------------------------------------------------------------------------

@dataclass(frozen=True)
class RemoteJobsReading:
    """One answer to "what are the laptop's jobs right now" (requirement 1).

    Exactly one of three shapes: a good reading (``ok=True``), a stale one served while unreachable
    or mid-refresh (``stale=True``, ``jobs`` is the last good list, ``age_seconds`` its age), or --
    before the very first reading has ever completed -- ``pending=True`` ("still reading", never
    "no jobs" and never "unreachable"). ``daemon_status`` (issue #73) is the same host's
    ``daemon-<host>.json``, when the reader fetched one alongside the jobs (``None`` for a reader
    that only ever returns a bare job list, e.g. every pre-#73 test in this suite).
    """

    jobs: list[Job]
    ok: bool
    stale: bool
    age_seconds: float | None
    error: str | None = None
    pending: bool = False
    daemon_status: dict[str, Any] | None = None


@dataclass
class _CacheEntry:
    jobs: list[Job]
    fetched_at: float
    daemon_status: dict[str, Any] | None = None


def _spawn_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


class LaptopJobsCache:
    """Caches one host's job list; refreshes in the background at most once every ``ttl`` seconds.

    :meth:`read` never runs ``reader()`` itself and never blocks on it -- it only decides whether a
    background refresh is due and, if so, hands it to ``executor`` (a real background thread by
    default; tests inject a synchronous one, e.g. ``lambda fn: fn()``, to make the refresh
    deterministic). At most one refresh is in flight at a time. Thread-safe: the background
    refresher and the monitor's request thread may call into this object at once.
    """

    def __init__(
        self, reader: Callable[[], list[Job]], *,
        ttl: float = DEFAULT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic,
        executor: Callable[[Callable[[], None]], None] = _spawn_thread,
    ) -> None:
        self._reader = reader
        self._ttl = ttl
        self._clock = clock
        self._executor = executor
        self._lock = threading.Lock()
        self._entry: _CacheEntry | None = None
        self._error: str | None = None
        self._refreshing = False
        self._last_attempt_at: float | None = None

    def read(self) -> RemoteJobsReading:
        now = self._clock()
        need_refresh = False
        with self._lock:
            if self._entry is not None and (now - self._entry.fetched_at) < self._ttl:
                return RemoteJobsReading(
                    jobs=self._entry.jobs, ok=True, stale=False,
                    age_seconds=now - self._entry.fetched_at,
                    daemon_status=self._entry.daemon_status,
                )
            due = self._last_attempt_at is None or (now - self._last_attempt_at) >= self._ttl
            if due and not self._refreshing:
                need_refresh = True
                self._refreshing = True
                self._last_attempt_at = now
            if self._entry is not None:
                reading = RemoteJobsReading(
                    jobs=self._entry.jobs, ok=self._error is None, stale=True,
                    age_seconds=now - self._entry.fetched_at, error=self._error,
                    daemon_status=self._entry.daemon_status,
                )
            elif self._error is not None:
                reading = RemoteJobsReading(jobs=[], ok=False, stale=False, age_seconds=None, error=self._error)
            else:
                reading = RemoteJobsReading(jobs=[], ok=False, stale=False, age_seconds=None, pending=True)
        if need_refresh:
            self._executor(self._refresh)
        return reading

    def _refresh(self) -> None:
        try:
            result = self._reader()
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._refreshing = False
            return
        # A reader may return a bare job list (every reader before #73) or a `RemoteSnapshot`
        # (jobs + the same round trip's daemon status): either shape is cached the same way.
        if isinstance(result, RemoteSnapshot):
            jobs, daemon_status = result.jobs, result.daemon_status
        else:
            jobs, daemon_status = result, None
        fetched_at = self._clock()
        with self._lock:
            self._entry = _CacheEntry(jobs=jobs, fetched_at=fetched_at, daemon_status=daemon_status)
            self._error = None
            self._refreshing = False


# -- the default singleton (one per process; real hosts.json + real SSH) ---------------------------

_default_caches: dict[str, LaptopJobsCache] = {}
_default_caches_lock = threading.Lock()


def get_default_cache(host: str = "laptop") -> LaptopJobsCache:
    """The process-wide cache for ``host``'s store, built once, reused by every snapshot call.

    A fresh :class:`LaptopJobsCache` per call would defeat the TTL entirely (the monitor server
    calls :func:`tools.agentops.monitor.panel_pob_runs` on every ``/api/snapshot`` request), so
    this is the one real (non-test) entry point: it reads ``config/hosts.json`` lazily, on first
    use, so importing this module never touches the filesystem, and refreshes on a real background
    thread.
    """

    with _default_caches_lock:
        cache = _default_caches.get(host)
        if cache is None:
            def reader(host=host) -> RemoteSnapshot:
                from junkroan.runs import hosts as runs_hosts

                config = runs_hosts.load_hosts_config()
                host_cfg = config[host]
                return read_remote_snapshot(host_cfg, host=host)

            cache = LaptopJobsCache(reader)
            _default_caches[host] = cache
        return cache


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "FOREGROUND_TIMEOUT_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "LaptopJobsCache",
    "RemoteJobsLogMissing",
    "RemoteJobsReading",
    "RemoteSnapshot",
    "RemoteStoreUnreachable",
    "default_remote_transport",
    "get_default_cache",
    "read_remote_jobs",
    "remote_jobs_log_path",
    "read_remote_snapshot",
]
