"""Host modes and slot reservations (issue #41, part of the #36 "keymaster" redesign).

Two owner commands, one call each:

    python scripts/runs.py mode <host> <mode>          # "I play" / "browser on the laptop"
    python scripts/runs.py reserve --host pc --slots 2 --for 45m --issue 12
    python scripts/runs.py reserve --release <id>

``apply_mode`` renders a host's named mode (``config/hosts.json``) into the budget-file format
``slot_budget.py`` reads, writes it WITHOUT a BOM, reads it back to prove that, and sets the
priority class of the host's PoB runtime processes. For the PC this happens in this process; for
the laptop the same steps run over SSH through ``run_on_host`` (the transport tests fake -- no
real SSH from a test).

``reserve_slots`` / ``release_reservation`` maintain ``var/reservations.json``, which
``slot_budget.load_budget`` reads (via ``slot_budget.read_reservations``, the same BOM-tolerant
reader) to add temporary slots to a host's ``others`` share -- but only on a host/mode whose
rendered budget turns on the top-level ``"strict_reserve"`` flag (default false, opt-in per mode
in ``config/hosts.json``): without it the queue's limit is ``total`` regardless of ``others``, so
a reservation has nothing to add slots to (#41 fix, 2026-09-26: an unconditional reserve would
have stalled the laptop's own hand-written ``others: 3`` budget at ``total - others == 0``).

``apply_timed_mode`` / ``revert_expired_modes`` (#54) are the monitor's "Free the PC" / "Free the
laptop" strip: an optional timer recorded in ``var/modes.json`` (BOM-free, file-locked) that the
runs daemon and the monitor's own snapshot both expire the same idempotent way.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from junkroan.pob import slot_budget
from junkroan.runs.bounded import run_bounded
from junkroan.runs.pass_guard import GUARD
from junkroan.runs.ssh_transport import build_ssh_argv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: A budget mode's own "which one applies right now" key never appears in it; only the priority
#: and the strict-reserve flag do (the flag is re-attached at the top level by ``mode_budget``).
_NON_PERIOD_KEYS = {"pob_priority", "pob_priority_day", "strict_reserve", "queue_slots"}

_BOM = b"\xef\xbb\xbf"

#: #998: the one timeout of every ssh / scp call (`run_on_host`, remote_store, row_sync). A call that does
#: not answer in this long marks its host down for the rest of the pass (`pass_guard.GUARD`).
SSH_TIMEOUT_SECONDS = 45
#: stderr of a call the pass guard skipped: the host already failed to answer in this pass (#998).
SKIPPED_SSH_STDERR = "skipped: ssh down this pass"

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.IGNORECASE)
_DURATION_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


class HostModeError(RuntimeError):
    """A host or mode the config does not know, or a mode application that failed to verify."""


class HostUnreachable(HostModeError):
    """ssh to a host failed (OpenSSH rc 255, a timeout, an OS error): its mode cannot be read."""


# -- config/hosts.json --------------------------------------------------------------------------

def hosts_config_path() -> Path:
    override = os.environ.get("JUNKROAN_HOSTS_CONFIG")
    return Path(override) if override else PROJECT_ROOT / "config" / "hosts.json"


def load_hosts_config(path: Path | None = None) -> dict[str, Any]:
    target = path if path is not None else hosts_config_path()
    return json.loads(target.read_text(encoding="utf-8"))


def host_switches_path() -> Path:
    """The untracked per-host switches file (#861): ``var/host_switches.json``, ``{host: {"fillers": bool}}``."""

    override = os.environ.get("JUNKROAN_HOST_SWITCHES_FILE")
    return Path(override) if override else slot_budget.shared_var_dir() / "host_switches.json"


def read_host_switches(path: Path | None = None) -> dict[str, Any]:
    """The switches file as a dict; ``{}`` when absent, empty or unreadable (same tolerance as ``read_modes``)."""

    target = path if path is not None else host_switches_path()
    try:
        raw = target.read_bytes()
    except OSError:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def effective_fillers(host: str, config: Mapping[str, Any] | None = None, switches: Mapping[str, Any] | None = None) -> bool:
    """The fillers switch of ``host``: the untracked file's own key wins; a tracked ``fillers`` is the carried-over fallback."""

    own = (read_host_switches() if switches is None else switches).get(host)
    if isinstance(own, dict) and isinstance(own.get("fillers"), bool):
        return own["fillers"]
    cfg = load_hosts_config() if config is None else config
    return (cfg.get(host) or {}).get("fillers") is True


def set_fillers(host: str, on: bool, path: Path | None = None) -> bool:
    """Set ``<host>.fillers`` in the untracked switches file (#861); the tracked hosts file is only read.

    An unknown host (not in the hosts config) raises :class:`HostModeError` and writes nothing.
    ``path`` is the switches file (default :func:`host_switches_path`).
    """

    _host_entry(load_hosts_config(), host)
    target = path if path is not None else host_switches_path()
    with _ModesLock(target):
        switches = read_host_switches(target)
        entry = dict(switches.get(host) or {})
        entry["fillers"] = bool(on)
        switches[host] = entry
        write_budget_bom_free(target, switches)
    return bool(on)


def daemon_repo_path(host_cfg: Mapping[str, Any]) -> str:
    """The checkout a host's own runs daemon actually runs from (issue #120).

    Usually the same as ``repo_path`` (the PC, and the laptop before #120's follow-up), but the
    laptop's daemon runs from a separate checkout (``docs/STATE.md``'s "Laptop" line:
    ``C:\\Coding\\poe-junkroan-v2-daemon``, not ``config/hosts.json``'s own ``repo_path``) --
    ``daemon_repo_path`` in a host's entry overrides ``repo_path`` for anything that must land in
    THAT daemon's own job store or read it back: ``runs.py submit``'s remote script and both
    ``remote_store.py`` readers. Deliberately NOT used by ``hosts._laptop_mode_script`` -- the mode
    switch writes ``var/machine_budget.json`` and sets PoB process priority, neither of which is
    the daemon's job store, so it keeps using plain ``repo_path`` (the brain's #120 decision).
    """

    return str(host_cfg.get("daemon_repo_path") or host_cfg.get("repo_path") or "")


def _host_entry(config: dict[str, Any], host: str) -> dict[str, Any]:
    try:
        return config[host]
    except KeyError:
        raise HostModeError(f"unknown host {host!r} (known: {sorted(config)})") from None


def _mode_entry(host_cfg: dict[str, Any], host: str, mode: str) -> dict[str, Any]:
    modes = host_cfg.get("modes") or {}
    try:
        return modes[mode]
    except KeyError:
        raise HostModeError(f"unknown mode {mode!r} for host {host!r} (known: {sorted(modes)})") from None


def mode_budget(host_cfg: dict[str, Any], host: str, mode: str) -> dict[str, Any]:
    """The mode's periods, plus its own top-level ``strict_reserve`` flag (default false), in
    exactly the shape ``slot_budget.py`` / ``machine_budget.json`` use -- this return value IS the
    whole document ``apply_mode`` writes (or sends over ssh), so ``strict_reserve`` has to sit
    beside the period keys here, not inside one of them."""

    entry = _mode_entry(host_cfg, host, mode)
    budget = {name: dict(spec) for name, spec in entry.items() if name not in _NON_PERIOD_KEYS}
    budget["strict_reserve"] = bool(entry.get("strict_reserve", False))
    if "queue_slots" in entry:  # #413: only a mode that names it carries it
        budget["queue_slots"] = int(entry["queue_slots"])
    return budget


def forced_period() -> str | None:
    """``JUNKROAN_FORCE_PERIOD=day|night`` (tests) or None; the one reader of that variable (#839)."""

    forced = os.environ.get("JUNKROAN_FORCE_PERIOD", "").strip().lower()
    return forced if forced in ("day", "night") else None


def current_period(entry: dict[str, Any] | None = None, now: datetime | None = None) -> str:
    """"day" or "night" by the mode's own day hours (default [8, 25] = 08:00-01:00).

    ``JUNKROAN_FORCE_PERIOD=day|night`` overrides it (tests); this is the only reader of that variable (#839).
    """

    forced = forced_period()
    if forced:
        return forced
    hours = ((entry or {}).get("day") or {}).get("hours") or [8, 25]
    moment = now or datetime.now()
    return "day" if slot_budget._hour_in(moment.hour, int(hours[0]), int(hours[1])) else "night"


def mode_priority(host_cfg: dict[str, Any], host: str, mode: str, now: datetime | None = None) -> str:
    """The mode's PoB priority; ``pob_priority_day`` (#839) replaces ``pob_priority`` in the day period."""

    entry = _mode_entry(host_cfg, host, mode)
    day = entry.get("pob_priority_day")
    if day and current_period(entry, now) == "day":
        return str(day)
    return str(entry.get("pob_priority") or "Normal")


def day_priority_flag() -> int:
    """#839: BELOW_NORMAL_PRIORITY_CLASS (0x4000) creation flag when this host's mode says BelowNormal now; else 0.

    The one day rule for a process this host starts (a runs-daemon job, a headless worker): children inherit the class.
    """

    if os.name != "nt":
        return 0
    try:
        host = slot_budget.current_host()
        config = load_hosts_config()
        mode = str((read_modes().get(host) or {}).get("mode") or "normal")
        priority = mode_priority(_host_entry(config, host), host, mode)
        return 0x00004000 if priority.strip().lower() == "belownormal" else 0
    except Exception:
        return 0


# -- writing the budget file, BOM-free, verified ------------------------------------------------

def write_budget_bom_free(path: Path, budget: dict[str, Any]) -> dict[str, Any]:
    """Write ``budget`` as UTF-8 with no BOM, then read it back and prove it.

    Mirrors PowerShell's ``[IO.File]::WriteAllText`` (no BOM by default) -- Python's plain
    ``encoding="utf-8"`` never writes one either, unlike ``"utf-8-sig"``. Raises
    :class:`HostModeError` if the file was written with a BOM or does not round-trip to the same
    JSON (the 2026-09-24 incident: a BOM written by ``Set-Content -Encoding utf8`` made the reader
    fall back to the desktop defaults on a 7.9 GB laptop for 1 h 30 min).
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(budget, indent=1, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    raw = path.read_bytes()
    if raw[:3] == _BOM:
        raise HostModeError(f"{path} was written with a BOM")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HostModeError(f"{path} did not read back as JSON: {exc!r}") from exc
    if parsed != budget:
        raise HostModeError(f"{path} did not round-trip: wrote {budget!r}, read back {parsed!r}")
    return parsed


# -- PoB runtime process priority (PC only; the laptop's own processes are set over SSH) --------

#: #988: (pid, create_time) -> command line, the same shape as ``load_groups._CMDLINES``. A command line never
#: changes during a process's life and reading it is the dearest part of this scan; it is rebuilt on every call to
#: the processes seen in it, so a process that left the list leaves nothing behind.
_CMDLINES: dict[tuple[int, "float | None"], list[str]] = {}
_EMPTY_CMDLINE_SETTLE_S = 10.0  # an empty line (denied, or a process just started) is kept only past this age


def find_pob_pids() -> list[int]:
    """PIDs of live PoB runtime worker processes, identified the way ``machine_load.py`` does.

    #988: the command line of a process is read only for a (pid, create_time) pair not seen before in this
    daemon process; the answer is the one the plain per-tick read gave.
    """

    global _CMDLINES
    try:
        import psutil
    except Exception:
        return []
    known = _CMDLINES
    fresh: dict[tuple[int, "float | None"], list[str]] = {}
    pids: list[int] = []
    for process in psutil.process_iter(["pid", "create_time"]):
        pid = process.pid
        key = (pid, process.info.get("create_time"))
        line = known.get(key)
        if line is None:
            try:
                line = list(process.cmdline() or [])
            except Exception:  # gone or denied: an empty line, as process_iter's ad_value=None gave before
                line = []
        if line or (key[1] is not None and time.time() - key[1] > _EMPTY_CMDLINE_SETTLE_S):
            fresh[key] = line
        if "headless_runtime_worker" in " ".join(line).lower():
            pids.append(pid)
    _CMDLINES = fresh
    return pids


def set_priority_class(pids: list[int], priority: str) -> list[int]:
    """Set each PID's process priority class; returns the PIDs it actually changed."""

    try:
        import psutil
    except Exception:
        return []
    name = str(priority).strip().lower().replace("_", "").replace(" ", "")
    if os.name == "nt":
        value = {
            "idle": psutil.IDLE_PRIORITY_CLASS,
            "belownormal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
        }.get(name, psutil.NORMAL_PRIORITY_CLASS)
    else:
        value = {"idle": 19, "belownormal": 10}.get(name, 0)
    changed: list[int] = []
    for pid in pids:
        try:
            psutil.Process(pid).nice(value)
            changed.append(pid)
        except Exception:
            continue
    return changed


# -- the laptop transport (faked in tests; never real SSH from a test) --------------------------

def describe_ssh_failure(failure: Any, elapsed_seconds: float | None = None) -> str:
    """One short phrase for a failed ssh call: the error class and how long it took (#382).

    ``failure`` is the exception the call raised or its ``CompletedProcess``. The class is one of
    ``timeout``, ``connection refused``, ``host unreachable / no route``, ``rc <N>`` (ssh exit code)
    or the exception's type name; never the argv (an encoded command), never base64.
    """

    from junkroan.report_format import human_duration

    if isinstance(failure, subprocess.TimeoutExpired):
        kind = "timeout"
        if failure.timeout is not None:
            elapsed_seconds = float(failure.timeout)
    elif isinstance(failure, BaseException):
        kind = type(failure).__name__
    else:
        rc = getattr(failure, "returncode", None)
        text = f"{getattr(failure, 'stderr', '') or ''}".lower()
        if "timed out" in text:
            kind = "timeout"
        elif "refused" in text:
            kind = "connection refused"
        elif "no route" in text or "unreachable" in text or "could not resolve" in text:
            kind = "host unreachable / no route"
        else:
            kind = f"rc {rc}"
    if elapsed_seconds is None:
        return kind
    return f"{kind} after {human_duration(elapsed_seconds)}"


def ssh_key(host_cfg: Mapping[str, Any]) -> str:
    """The pass guard's key of a host (#998): ``ssh:<alias>``, the same ``ssh`` value ``build_ssh_argv`` uses."""

    return f"ssh:{host_cfg.get('ssh')}"


def note_ssh_failure(host_cfg: Mapping[str, Any], exc: BaseException) -> None:
    """Mark the host down for this pass when its ssh call timed out or could not run at all (#998).

    Only a TimeoutExpired or an OSError counts as "the service did not answer"; any other exception is a
    programming error and is left to propagate untouched. Logs one line the first time per pass.
    """

    if not isinstance(exc, (subprocess.TimeoutExpired, OSError)):
        return
    _mark_host_down(host_cfg, repr(exc), describe_ssh_failure(exc))


#: #998: ssh's own exit code when it could not reach the host (connect timed out, refused, no route). ssh
#: returns it; it does not raise. A remote command's own exit code is another number.
SSH_UNREACHABLE_RC = 255


def note_ssh_result(host_cfg: Mapping[str, Any], result: Any) -> None:
    """Mark the host down for this pass when its ssh call returned :data:`SSH_UNREACHABLE_RC` (#998).

    A dead laptop costs one ssh connect timeout (~21 s) per call, and the call answers 255 instead of raising, so
    without this every later step of the same pass called ssh to it again. Any other exit code is the remote
    command's own answer and marks nothing. Logs one line the first time per pass.
    """

    if getattr(result, "returncode", None) != SSH_UNREACHABLE_RC:
        return
    _mark_host_down(host_cfg, repr(result), describe_ssh_failure(result))


def _mark_host_down(host_cfg: Mapping[str, Any], why: str, described: str) -> None:
    """The one mark every ssh failure makes (`ssh:<alias>` in `GUARD`); the caller's line is logged once per pass."""

    if GUARD.mark_down(ssh_key(host_cfg), why):
        _log(f"ssh {host_cfg.get('ssh')} did not answer ({described}); "
             "its calls are skipped until the next pass")


def _log(message: str) -> None:
    """One line on stderr in the daemon's own style (``daemon._log``); never raises."""
    try:
        sys.stderr.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} runs-daemon: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def run_on_host(host_cfg: dict[str, Any], powershell_script: str) -> subprocess.CompletedProcess:
    """Run ``powershell_script`` on a remote host over ``ssh <alias>``.

    The only transport for anything that is not the PC. Tests replace this function wholesale
    (``monkeypatch.setattr(hosts, "run_on_host", fake)``); nothing here is exercised for real by
    the test suite. Sends the script via ``-EncodedCommand`` (:func:`junkroan.runs.ssh_transport.
    build_ssh_argv`, shared with ``remote_store.default_remote_transport``) so no shell along the
    way gets a chance to eat a ``$variable`` in it -- the bug behind #87 (``_laptop_mode_script``'s
    own ``$path``/``$bytes``/``$check`` never survived the old ``-Command "<script>"`` form).

    #998: the call is bounded by :data:`SSH_TIMEOUT_SECONDS`; when the host already failed to answer in
    this pass it is not made at all and returns rc 255 (a failed call to every caller).
    """

    argv = build_ssh_argv(host_cfg, powershell_script)
    if GUARD.down(ssh_key(host_cfg)):
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr=SKIPPED_SSH_STDERR)
    try:
        result = run_bounded(argv, capture_output=True, text=True, timeout=SSH_TIMEOUT_SECONDS)
    except Exception as exc:
        note_ssh_failure(host_cfg, exc)
        raise
    note_ssh_result(host_cfg, result)     # #998: ssh could not reach the host (rc 255) -> down for the pass
    return result


def quote_ps_arg(arg: str) -> str:
    """One argv element as a single-quoted PowerShell literal (embedded ``'`` doubled).

    The one quote helper for every script that crosses ssh (``scripts/runs.py``, ``daemon.py`` and
    ``rebalance.py`` import it; #1037).
    """

    return "'" + str(arg).replace("'", "''") + "'"


def remote_write_script(command: str, *, repo_path: str | None = None, host: str | None = None,
                        pythonpath: str | None = None) -> str:
    """The PowerShell script :func:`write_over_ssh` sends: optional env, optional ``cd``, then ``command``.

    ``host`` sets ``$env:JUNKROAN_HOST`` (read by ``slot_budget.current_host``), ``pythonpath`` sets
    ``$env:PYTHONPATH``, ``repo_path`` is the checkout to ``cd`` into; an omitted one is not written.
    """

    steps: list[str] = []
    if host is not None:
        steps.append(f"$env:JUNKROAN_HOST = {quote_ps_arg(host)}")
    if pythonpath is not None:
        steps.append(f"$env:PYTHONPATH = {quote_ps_arg(pythonpath)}")
    if repo_path is not None:
        steps.append(f"cd {quote_ps_arg(repo_path)}")
    steps.append(command)
    return "; ".join(steps)


def write_over_ssh(host_cfg: Mapping[str, Any], command: str, *, repo_path: str | None = None,
                   host: str | None = None, pythonpath: str | None = None) -> subprocess.CompletedProcess:
    """A write into another host's job store (or its budget file) over ssh: the one function (#1037).

    ``command`` is the already-quoted PowerShell line (arguments through :func:`quote_ps_arg`); the
    optional ``host`` / ``pythonpath`` / ``repo_path`` are described at :func:`remote_write_script`.
    Returns :func:`run_on_host`'s result and raises what it raises: each caller keeps its own policy
    (the ``mark_*_on_host`` ones return False, the others let it propagate).
    """

    return run_on_host(host_cfg, remote_write_script(command, repo_path=repo_path, host=host, pythonpath=pythonpath))


def mark_posted_on_host(host_cfg: Mapping[str, Any], host: str, job_id: str) -> bool:
    """Mark ``job_id`` posted in ``host``'s own daemon checkout's store, over ssh (issue #118).

    Runs ``runs.py mark-posted <job id>`` inside :func:`daemon_repo_path` -- the SAME checkout
    that host's own daemon reads and writes, exactly like ``runs.py submit``'s own remote path
    (#120). Returns whether the remote call exited 0; a failure is the caller's to retry later,
    never raised here.
    """

    repo_path = daemon_repo_path(host_cfg)
    line = f"python scripts\\runs.py mark-posted {quote_ps_arg(job_id)}"
    try:
        result = write_over_ssh(host_cfg, line, repo_path=repo_path)
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0


def mark_anomaly_taken_on_host(host_cfg: Mapping[str, Any], host: str, key: str) -> bool:
    """Drop anomaly ``key`` from ``host``'s own queue over ssh (#467): the PC started its keymaster.

    ``runs.py anomaly-taken <key>`` inside :func:`daemon_repo_path`. Never raises; False = retry later.
    """

    line = f"python scripts\\runs.py anomaly-taken {quote_ps_arg(key)}"
    try:
        result = write_over_ssh(host_cfg, line, repo_path=daemon_repo_path(host_cfg))
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0


def mark_run_issue_on_host(host_cfg: Mapping[str, Any], host: str, job_id: str, number: int) -> bool:
    """Record ``number`` as ``job_id``'s Run issue in ``host``'s own store, over ssh (#164)."""

    line = f"python scripts\\runs.py mark-run-issue {quote_ps_arg(job_id)} {int(number)}"
    try:
        result = write_over_ssh(host_cfg, line, repo_path=daemon_repo_path(host_cfg))
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0


def _laptop_mode_script(repo_path: str, budget: dict[str, Any], priority: str) -> str:
    """One PowerShell script: write the budget BOM-free, verify it, set PoB process priority."""

    budget_json = json.dumps(budget, indent=1, sort_keys=True) + "\n"
    # `[Convert]::ToBase64String` avoids every quoting hazard of handing JSON through `ssh`'s own
    # command-line parsing (backticks, `$`, embedded quotes -- the laptop numbers doc's own warning).
    import base64

    encoded = base64.b64encode(budget_json.encode("utf-8")).decode("ascii")
    idle = "Idle" if str(priority).strip().lower() == "idle" else "Normal"
    return (
        f"$path = '{repo_path}\\var\\machine_budget.json'; "
        f"$bytes = [Convert]::FromBase64String('{encoded}'); "
        "[IO.File]::WriteAllBytes($path, $bytes); "
        "$check = [IO.File]::ReadAllBytes($path); "
        "if ($check[0] -eq 239 -and $check[1] -eq 187 -and $check[2] -eq 191) { "
        "Write-Error 'BOM written'; exit 1 }; "
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'headless_runtime_worker' } "
        f"| ForEach-Object {{ try {{ (Get-Process -Id $_.ProcessId).PriorityClass = '{idle}' }} catch {{}} }}; "
        "Write-Output 'OK'"
    )


# -- applying a mode -----------------------------------------------------------------------------

def events_path() -> Path:
    override = os.environ.get("JUNKROAN_RUNS_EVENTS")
    return Path(override) if override else slot_budget.shared_var_dir().parent / "artifacts" / "runs" / "events.jsonl"


def daemon_status_path(host: str) -> Path:
    """``artifacts/runs/daemon-<host>.json`` (issue #73): the single-instance guard's own file.

    ``events_path()``'s own override lets a test move the whole ``artifacts/runs`` directory;
    ``JUNKROAN_DAEMON_STATUS_DIR`` moves only this file, for a test that wants the events log left
    alone.
    """

    override = os.environ.get("JUNKROAN_DAEMON_STATUS_DIR")
    base = Path(override) if override else events_path().parent
    return base / f"daemon-{str(host).strip().lower()}.json"


def append_event(event: dict[str, Any], *, path: Path | None = None) -> None:
    """Append one JSON line to the shared events log, the file ``runs watch`` tails (issue #48)."""

    target = path if path is not None else events_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with events_feed_lock(target, timeout=_EVENTS_LOCK_WAIT):  # fail-open: never blocks or loses an event (#387)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


_EVENTS_LOCK_WAIT = 2.0  # seconds a writer waits for the cleaner's sidecar lock, then appends anyway


class events_feed_lock:
    """The sidecar lock ``<events file>.lock`` (issue #387) between ``append_event`` and
    ``scripts/clean_runs_events.py``: the cleaner holds it while it swaps the rewritten file in.

    ``timeout`` bounds the wait; on a timeout or any OS error the ``with`` body still runs, unlocked
    (``locked`` says which), so a writer never blocks for long and never loses an event.
    """

    def __init__(self, events_file: Path, timeout: float = _EVENTS_LOCK_WAIT) -> None:
        self._lock_path = events_file.with_name(events_file.name + ".lock")
        self._timeout = timeout
        self._fd: int | None = None
        self.locked = False

    def __enter__(self) -> "events_feed_lock":
        try:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            fd = os.open(str(self._lock_path), flags)
        except OSError:
            return self
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                _lock_whole_file(fd)
                self._fd = fd
                self.locked = True
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return self
                time.sleep(0.005)

    def __exit__(self, *exc_info: Any) -> None:
        fd, self._fd = self._fd, None
        self.locked = False
        if fd is None:
            return
        try:
            _unlock_whole_file(fd)
        except OSError:
            pass
        finally:
            os.close(fd)


def _append_event(path: Path | None, event: dict[str, Any]) -> None:
    append_event(event, path=path)


def apply_mode(
    host: str,
    mode: str,
    *,
    config: dict[str, Any] | None = None,
    budget_path: Path | None = None,
    events_file: Path | None = None,
    now: datetime | None = None,
    event_extra: dict[str, Any] | None = None,
    local: bool = False,
) -> dict[str, Any]:
    """Apply ``host``'s named ``mode``: write its budget, set PoB process priority, log one event.

    ``local=True`` writes the budget on THIS machine even when ``host``'s entry carries an ssh alias.
    The alias says how OTHER machines reach that host, not that the host is remote from here, so a
    command running on the host itself would otherwise ssh into itself: the nested session dies with
    no stdout, no stderr and no exit code, which is what the laptop's own restore-after-browser task
    would have done (issue #364, 2026-09-30).

    ``event_extra`` (the monitor's timer, #54) merges extra keys (``until``, ``by``) into that one
    event; omitted, the event is exactly ``{ts, kind, host, mode}`` as every existing caller of
    this function already expects.
    """

    config = config if config is not None else load_hosts_config()
    host_cfg = _host_entry(config, host)
    budget = mode_budget(host_cfg, host, mode)
    priority = mode_priority(host_cfg, host, mode)

    if host_cfg.get("ssh") and not local:
        script = _laptop_mode_script(host_cfg.get("repo_path") or str(PROJECT_ROOT), budget, priority)
        result = write_over_ssh(host_cfg, script)
        if result.returncode != 0:
            raise HostModeError(f"runs mode {host} {mode} failed over ssh: {result.stderr or result.stdout}")
        summary: dict[str, Any] = {"host": host, "mode": mode, "priority": priority, "transport": "ssh", "stdout": result.stdout}
    else:
        target = budget_path if budget_path is not None else slot_budget.budget_path()
        write_budget_bom_free(target, budget)
        pids = find_pob_pids()
        changed = set_priority_class(pids, priority)
        summary = {"host": host, "mode": mode, "priority": priority, "transport": "local", "budget_path": str(target), "pids": pids, "changed_pids": changed}

    event = {"ts": (now or datetime.now()).isoformat(timespec="seconds"), "kind": "mode", "host": host, "mode": mode}
    if event_extra:
        event.update(event_extra)
    _append_event(events_file, event)
    return summary


# -- var/modes.json: the monitor's optional timer (#54) ------------------------------------------
#
# ``apply_mode`` above stays exactly as every existing caller (``scripts/runs.py mode``, the
# runs daemon) already uses it. The monitor's "Free the PC" / "Free the laptop" strip goes through
# ``apply_timed_mode`` instead, which wraps one ``apply_mode`` call in the ``modes.json`` file lock
# so a concurrent ``revert_expired_modes`` (the daemon's tick, or another monitor snapshot) can
# never interleave with it -- exactly one of the two ever wins the write, the other's lock wait is
# bounded by ``_MODES_LOCK_TIMEOUT``.

_MODES_LOCK_TIMEOUT = 5.0  # seconds; a hung lock holder must not wedge the monitor's snapshot loop


def modes_path() -> Path:
    override = os.environ.get("JUNKROAN_MODES_FILE")
    return Path(override) if override else slot_budget.shared_var_dir() / "modes.json"


def read_modes(path: Path | None = None) -> dict[str, Any]:
    """``{host: {"mode": ..., "until": iso-string-or-None}}``; ``{}`` when the file is absent,
    empty, or unreadable (mirrors ``slot_budget.read_reservations``'s own tolerance)."""

    target = path if path is not None else modes_path()
    try:
        raw = target.read_bytes()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_modes(path: Path, modes: dict[str, Any]) -> None:
    write_budget_bom_free(path, modes)  # same BOM-free write + read-back proof, any JSON dict


class _ModesLock:
    """A bounded, blocking exclusive lock on ``modes.json``'s own sibling ``.lock`` file.

    Only one process (a monitor POST, the runs daemon's tick, another monitor's snapshot) may be
    inside the read-modify-write of ``modes.json`` at a time; a lock already held by a dead process
    is released by the OS the moment that process exits, same as ``slot_budget._FileLock``.
    """

    __slots__ = ("_lock_path", "_timeout", "_fd")

    def __init__(self, modes_file: Path, timeout: float = _MODES_LOCK_TIMEOUT) -> None:
        self._lock_path = modes_file.with_name(modes_file.name + ".lock")
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_ModesLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(str(self._lock_path), flags)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                _lock_whole_file(fd)
                self._fd = fd
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise HostModeError(f"timed out locking {self._lock_path}") from None
                time.sleep(0.02)

    def __exit__(self, *exc_info: Any) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock_whole_file(fd)
        finally:
            os.close(fd)


if os.name == "nt":
    import msvcrt

    def _lock_whole_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_whole_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_whole_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_whole_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


#: The owner record: ``reserved`` / ``reserved_until`` (#621) and the keys an owner preset adds (#958):
#: which preset, what happens when it lapses, the need it was sized for, the processes to close.
_OWNER_KEYS = ("reserved", "reserved_until", "preset", "on_end", "need_cpu_cores", "need_ram_mb",
               "close", "close_mode", "keep", "workers_before")

#: The `on_end` value of the laptop's "sleep" preset (#958).
ON_END_CLOSE_BROWSERS = "close-browsers"

#: The `close_mode` value of a preset record whose end closes every program of the user outside the
#: allow-list (#958 unit 4); a record without `close_mode` closes the `close` names as before.
CLOSE_MODE_ALLOW_LIST = "allow-list"

#: The five browser names of `tools/hosts/laptop/close-browsers.ps1` (#958's default `close` list).
DEFAULT_CLOSE = ("chrome", "msedge", "firefox", "opera", "brave")


def _set_host_mode(modes: dict[str, Any], host: str, mode: str | None, until: str | None) -> None:
    """Set (or, ``mode is None``, drop) ``host``'s mode/until in ``modes``, keeping the owner record
    (``reserved`` / ``reserved_until``, #621) the entry may carry."""

    old = modes.get(host)
    owner = {k: old[k] for k in _OWNER_KEYS if isinstance(old, dict) and k in old}
    if mode is None:
        if owner:
            modes[host] = owner
        else:
            modes.pop(host, None)
        return
    modes[host] = {"mode": mode, "until": until, **owner}


def apply_timed_mode(
    host: str,
    mode: str,
    minutes: float | None,
    *,
    config: dict[str, Any] | None = None,
    budget_path: Path | None = None,
    events_file: Path | None = None,
    modes_file: Path | None = None,
    now: datetime | None = None,
    by: str = "monitor",
) -> dict[str, Any]:
    """Apply ``mode`` on ``host`` (exactly as ``apply_mode`` does) and record it in ``modes.json``.

    ``minutes`` is ``None`` for "no timer". Records ``{host: {"mode", "until"}}`` in ``modes.json``
    (dropping the host entirely on ``mode == "normal"``, i.e. "Back to normal") and logs ONE event
    (``apply_mode``'s own, carrying ``until``/``by`` via ``event_extra``) -- never two. A failing
    ``apply_mode`` raises before anything is written to ``modes.json``.
    """

    moment = now or datetime.now()
    until = (moment + timedelta(minutes=float(minutes))).isoformat(timespec="seconds") if minutes else None
    target_modes = modes_file if modes_file is not None else modes_path()

    with _ModesLock(target_modes):
        summary = apply_mode(
            host, mode,
            config=config, budget_path=budget_path, events_file=events_file, now=moment,
            event_extra={"until": until, "by": by},
        )
        modes = read_modes(target_modes)
        _set_host_mode(modes, host, None if mode == "normal" else mode, until)
        _write_modes(target_modes, modes)

    summary["until"] = until
    return summary


def record_mode(host: str, mode: str, *, modes_file: Path | None = None) -> None:
    """Record ``mode`` as ``host``'s last applied mode in ``modes.json`` with no timer
    (``until: None``, which ``revert_expired_modes`` skips); ``normal`` drops the entry, as
    ``apply_timed_mode`` does. Called by ``runs.py mode`` after a successful ``apply_mode``."""

    target = modes_file if modes_file is not None else modes_path()
    with _ModesLock(target):
        modes = read_modes(target)
        _set_host_mode(modes, host, None if mode == "normal" else mode, None)
        _write_modes(target, modes)


def current_mode(
    host: str,
    *,
    config: dict[str, Any] | None = None,
    modes_file: Path | None = None,
    local: bool = False,
    budget_path: Path | None = None,
    read_remote: bool = True,
) -> str:
    """The mode ``host`` is on, or ``unknown``; never a guessed ``normal``. Raises ``HostModeError``
    for an unknown host. Reads only; writes nothing.

    On the host itself (``host == slot_budget.current_host()`` or ``local=True``) the budget file in
    force (``budget_path``, default ``slot_budget.budget_path()``) is the truth: it is compared with
    ``mode_budget`` of each of the host's modes. Two matching modes -> the one recorded in
    ``modes.json`` if it is among them, else ``unknown``. On another host with an ``ssh`` alias the same
    file is read over ssh (rc 255 or a transport exception raises ``HostUnreachable``); a host
    without ``ssh``, or ``read_remote=False`` (the daemon's placement, which makes no ssh call of its
    own for a mode, #469), returns its ``modes.json`` entry. No match, a missing or unreadable budget file, nothing recorded ->
    ``unknown``.
    """

    config = config if config is not None else load_hosts_config()
    host_cfg = _host_entry(config, host)
    entry = read_modes(modes_file).get(host)
    recorded = entry.get("mode") if isinstance(entry, dict) else None
    recorded = str(recorded) if recorded else None

    if not (local or host == slot_budget.current_host()):
        if not (read_remote and host_cfg.get("ssh")):
            return recorded or "unknown"
        return _match_mode(host_cfg, host, _read_remote_budget(host_cfg, host), recorded)

    target = budget_path if budget_path is not None else slot_budget.budget_path()
    try:
        in_force = json.loads(target.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    return _match_mode(host_cfg, host, in_force, recorded)


def _read_remote_budget(host_cfg: dict[str, Any], host: str) -> Any:
    """The parsed budget file on ``host`` (``<repo_path>\\var\\machine_budget.json``, where
    ``apply_mode`` writes it), or ``None`` when missing / unreadable / not JSON.
    Raises :class:`HostUnreachable` on ssh rc 255 or any exception from the transport."""

    script = f"Get-Content -Raw -Encoding UTF8 -LiteralPath '{host_cfg.get('repo_path')}\\var\\machine_budget.json'"
    try:
        result = run_on_host(host_cfg, script)
    except Exception as exc:
        raise HostUnreachable(f"{host} unreachable: {exc!r}") from exc
    code = getattr(result, "returncode", 1)
    if code == 255:
        detail = str(getattr(result, "stderr", "") or "").strip() or "ssh exit 255"
        raise HostUnreachable(f"{host} unreachable: {detail}")
    if code != 0:
        return None
    try:
        return json.loads(str(result.stdout).lstrip("﻿"))
    except (ValueError, TypeError):
        return None


def mode_from_budget(
    host: str, budget: Any, *, config: dict[str, Any] | None = None, placement_keys: bool = False,
) -> str:
    """The mode of ``host`` whose ``mode_budget`` equals ``budget`` (a parsed budget file), or
    ``unknown``; two matches -> the mode recorded in ``modes.json`` if among them (#471)."""

    config = config if config is not None else load_hosts_config()
    entry = read_modes().get(host)
    recorded = entry.get("mode") if isinstance(entry, dict) else None
    return _match_mode(_host_entry(config, host), host, budget, str(recorded) if recorded else None,
                       placement_keys=placement_keys)


_PLACEMENT_PERIOD_KEYS = ("hours", "total", "others", "min_free_ram_gb")


def _placement_view(doc: Any) -> dict[str, Any]:
    """(#709) Only what placement reads of a budget document: period entries cut to ``hours``/``total``/
    ``others``/``min_free_ram_gb`` plus the top-level ``strict_reserve``; every other key is dropped."""

    view: dict[str, Any] = {}
    if not isinstance(doc, dict):
        return view
    for name, spec in doc.items():
        if isinstance(spec, dict) and "hours" in spec:
            view[name] = {k: spec[k] for k in _PLACEMENT_PERIOD_KEYS if k in spec}
    view["strict_reserve"] = bool(doc.get("strict_reserve", False))
    return view


def placement_diff(host_cfg: dict[str, Any], host: str, budget: Any) -> tuple[str, list[str]]:
    """(#709) The mode of ``host`` closest to ``budget`` on the placement keys and the keys that differ
    from it (``day.total``); ``("", [])`` for a host with no modes."""

    got = _placement_view(budget)
    best: tuple[str, list[str]] | None = None
    for name in host_cfg.get("modes", {}):
        want = _placement_view(mode_budget(host_cfg, host, name))
        diff: list[str] = []
        for period in sorted(set(got) | set(want)):
            a, b = got.get(period), want.get(period)
            if isinstance(a, dict) or isinstance(b, dict):
                a, b = a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}
                diff += [f"{period}.{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
            elif a != b:
                diff.append(period)
        if best is None or len(diff) < len(best[1]):
            best = (name, diff)
    return best or ("", [])


def _match_mode(
    host_cfg: dict[str, Any], host: str, in_force: Any, recorded: str | None, *, placement_keys: bool = False,
) -> str:
    """The mode whose ``mode_budget`` equals ``in_force``; two matches -> ``recorded`` if among them."""

    matches = []
    for name in host_cfg.get("modes", {}):
        want = mode_budget(host_cfg, host, name)
        if placement_keys:  # #709: extra keys (merge_suite, queue_slots, ...) never break a match
            same = _placement_view(want) == _placement_view(in_force)
        else:
            same = want == in_force
        if same:
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    if recorded in matches:
        return str(recorded)
    return "unknown"


def _machine_back_to_normal() -> None:
    try:
        from tools.agentops import machine_mode
        machine_mode.set_mode("normal")
    except Exception:  # noqa: BLE001 -- the host's own revert goes on; the next tick of a loop reads the file
        pass


def revert_expired_modes(
    now: datetime | None = None,
    *,
    config: dict[str, Any] | None = None,
    budget_path: Path | None = None,
    events_file: Path | None = None,
    modes_file: Path | None = None,
) -> list[str]:
    """Switch every host whose recorded ``until`` has passed back to ``normal``.

    Idempotent: once a host is reverted its ``modes.json`` entry is gone, so a second call (the
    daemon's next tick, or the monitor's next snapshot -- whichever loses the file-lock race, the
    other's call is simply a no-op) finds nothing left to do. Returns the hosts it reverted.
    """

    moment = now or datetime.now()
    target_modes = modes_file if modes_file is not None else modes_path()
    reverted: list[str] = []

    with _ModesLock(target_modes):
        modes = read_modes(target_modes)
        expired: list[str] = []
        for host, entry in modes.items():
            until = entry.get("until") if isinstance(entry, dict) else None
            if not until:
                continue
            try:
                until_dt = datetime.fromisoformat(str(until))
            except ValueError:
                continue
            if until_dt <= moment:
                expired.append(host)

        for host in expired:
            if host == "pc" and modes_file is None and isinstance(modes.get(host), dict)                     and modes[host].get("mode") == "play":
                _machine_back_to_normal()  # #779: a timed play that lapses ends the machine play too
            apply_mode(
                host, "normal",
                config=config, budget_path=budget_path, events_file=events_file, now=moment,
                event_extra={"until": None, "by": "timer"},
            )
            _set_host_mode(modes, host, None, None)
            reverted.append(host)

        changed = bool(expired)
        for host in list(modes):
            entry = modes[host]
            if not isinstance(entry, dict) or "reserved_until" not in entry:
                continue
            try:
                lapsed = datetime.fromisoformat(str(entry["reserved_until"])) <= moment
            except ValueError:
                lapsed = True  # an unreadable owner record is dropped, never kept forever
            if lapsed and entry.get("on_end") == ON_END_CLOSE_BROWSERS:
                continue  # #958: only the host's own daemon drops it, after it closed the browsers
            if lapsed:
                for key in _OWNER_KEYS:
                    entry.pop(key, None)
                if not entry:
                    del modes[host]
                changed = True

        if changed:
            _write_modes(target_modes, modes)

    return reverted


def set_owner_reservation(
    host: str, slots: int, minutes: float, *, modes_file: Path | None = None, now: datetime | None = None
) -> datetime:
    """Write the owner record ``reserved`` / ``reserved_until`` into ``host``'s ``modes.json`` entry
    (one per host, a new call replaces it; ``mode`` / ``until`` untouched). Returns ``reserved_until``."""

    if int(slots) < 1 or float(minutes) <= 0:
        raise HostModeError("reserve needs slots >= 1 and a duration > 0")
    until = (now or datetime.now()) + timedelta(minutes=float(minutes))
    target = modes_file if modes_file is not None else modes_path()
    with _ModesLock(target):
        modes = read_modes(target)
        entry = modes.get(host)
        entry = dict(entry) if isinstance(entry, dict) else {}
        for key in _OWNER_KEYS:  # a new call replaces the whole record, a preset's keys too (#958)
            entry.pop(key, None)
        entry["reserved"] = int(slots)
        entry["reserved_until"] = until.isoformat(timespec="seconds")
        modes[host] = entry
        _write_modes(target, modes)
    return until


def set_owner_preset(
    host: str,
    preset: str,
    workers: int,
    minutes: float,
    *,
    need_cpu_cores: float | None = None,
    need_ram_mb: float | None = None,
    on_end: str | None = None,
    close: Iterable[str] | None = None,
    close_mode: str | None = None,
    keep: Iterable[str] | None = None,
    workers_before: int | None = None,
    modes_file: Path | None = None,
    now: datetime | None = None,
) -> datetime:
    """Write an owner preset (#958) as ``host``'s owner record: ``reserved`` = the PoB workers that give way
    (0 is a record too, so the end of "sleep" still finds it), ``reserved_until``, ``preset``, and the
    optional ``on_end`` / need / ``close`` / ``workers_before``. One record per host: it replaces any earlier
    one whole (a reserve, "film" before "sleep"). Returns ``reserved_until``."""

    if int(workers) < 0 or float(minutes) <= 0:
        raise HostModeError("an owner preset needs workers >= 0 and a duration > 0")
    until = (now or datetime.now()) + timedelta(minutes=float(minutes))
    target = modes_file if modes_file is not None else modes_path()
    with _ModesLock(target):
        modes = read_modes(target)
        entry = modes.get(host)
        entry = dict(entry) if isinstance(entry, dict) else {}
        for key in _OWNER_KEYS:
            entry.pop(key, None)
        entry["reserved"] = int(workers)
        entry["reserved_until"] = until.isoformat(timespec="seconds")
        entry["preset"] = str(preset)
        if on_end:
            entry["on_end"] = str(on_end)
        if need_cpu_cores is not None:
            entry["need_cpu_cores"] = float(need_cpu_cores)
        if need_ram_mb is not None:
            entry["need_ram_mb"] = float(need_ram_mb)
        if close is not None:
            entry["close"] = [str(name) for name in close]
        if close_mode:
            entry["close_mode"] = str(close_mode)
        if keep is not None:
            entry["keep"] = [str(name) for name in keep]
        if workers_before is not None:
            entry["workers_before"] = int(workers_before)
        modes[host] = entry
        _write_modes(target, modes)
    return until


def owner_record_raw(host: str, *, modes_file: Path | None = None) -> dict[str, Any] | None:
    """The owner keys of ``host``'s entry as they are on disk (an expired record too), or ``None``."""

    entry = read_modes(modes_file).get(host)
    if not isinstance(entry, dict):
        return None
    record = {k: entry[k] for k in _OWNER_KEYS if k in entry}
    return record or None


def lapsed_close_record(
    host: str, now: datetime | None = None, *, modes_file: Path | None = None
) -> dict[str, Any] | None:
    """The owner record of ``host`` when it carries ``on_end: close-browsers`` and has lapsed at ``now``
    (an unreadable ``reserved_until`` counts as lapsed); else ``None``. Reads only."""

    record = owner_record_raw(host, modes_file=modes_file)
    if not record or record.get("on_end") != ON_END_CLOSE_BROWSERS:
        return None
    try:
        lapsed = datetime.fromisoformat(str(record["reserved_until"])) <= (now or datetime.now())
    except (KeyError, ValueError):
        lapsed = True
    return record if lapsed else None


@dataclass(frozen=True)
class KillResult:
    """#958: what a name-kill did. ``found`` = processes whose name matched; ``killed`` = those ended;
    ``denied`` = those a kill raised on (AccessDenied or any other error). A process that vanished before
    its kill (NoSuchProcess) is found but neither killed nor denied. ``int(result)`` is ``killed``, so a
    caller that expected the old int still gets the number it asked for."""

    found: int = 0
    killed: int = 0
    denied: int = 0

    def __int__(self) -> int:
        return self.killed


def kill_processes_by_name(names: Iterable[str]) -> KillResult:
    """Kill every process whose executable name (case-blind, without ``.exe``) is in ``names``; returns the
    found / killed / denied counts (#958, see :class:`KillResult`). The laptop's "sleep" end (#958); tests
    pass their own killer, never this one."""

    import psutil

    wanted = {str(n).lower().removesuffix(".exe") for n in names}
    found = killed = denied = 0
    for process in psutil.process_iter(["name"]):
        if str(process.info.get("name") or "").lower().removesuffix(".exe") not in wanted:
            continue
        found += 1
        try:
            process.kill()
            killed += 1
        except psutil.NoSuchProcess:
            continue  # already gone: not a denial
        except Exception:  # AccessDenied and any other failure: the process is still alive, so count it
            denied += 1
    return KillResult(found=found, killed=killed, denied=denied)


def kill_processes_by_pid(pids: Iterable[int]) -> KillResult:
    """Kill exactly the processes of ``pids`` (#958 unit 4, the allow-list close); the same found / killed /
    denied counts as :func:`kill_processes_by_name`. A pid that is gone already is not found. Tests pass
    their own killer, never this one."""

    import psutil

    found = killed = denied = 0
    for pid in dict.fromkeys(int(p) for p in pids):
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            continue
        except Exception:
            found += 1
            denied += 1
            continue
        found += 1
        try:
            process.kill()
            killed += 1
        except psutil.NoSuchProcess:
            continue
        except Exception:
            denied += 1
    return KillResult(found=found, killed=killed, denied=denied)


def release_owner_reservation(
    host: str, *, modes_file: Path | None = None, only_until: str | None = None
) -> bool:
    """Drop ``host``'s owner record; the mode keys stay. Returns whether there was one.

    With ``only_until`` the record is dropped only while its ``reserved_until`` still reads that text: a
    record replaced meanwhile (a new "film", a ``back``) is left alone (#958's end pass)."""

    target = modes_file if modes_file is not None else modes_path()
    with _ModesLock(target):
        modes = read_modes(target)
        entry = modes.get(host)
        if not isinstance(entry, dict) or not any(k in entry for k in _OWNER_KEYS):
            return False
        if only_until is not None and entry.get("reserved_until") != only_until:
            return False
        for key in _OWNER_KEYS:
            entry.pop(key, None)
        if not entry:
            del modes[host]
        _write_modes(target, modes)
    return True


def owner_reservation(
    host: str, now: datetime | None = None, *, modes_file: Path | None = None
) -> tuple[int, datetime] | None:
    """``(slots, reserved_until)`` of the owner's reservation on ``host``, or ``None`` when absent,
    expired or malformed. Reads only; never raises."""

    try:
        entry = read_modes(modes_file).get(host)
        if not isinstance(entry, dict) or "reserved" not in entry:
            return None
        slots = int(entry["reserved"])
        until = datetime.fromisoformat(str(entry["reserved_until"]))
        if slots < 1 or until <= (now or datetime.now()):
            return None
        return slots, until
    except Exception:
        return None


# -- reservations ---------------------------------------------------------------------------------

def parse_duration(text: str) -> float:
    """``"45m"`` / ``"2h"`` / ``"90s"`` / ``"1d"`` -> seconds."""

    match = _DURATION_RE.match(text)
    if not match:
        raise HostModeError(f"cannot parse a duration from {text!r} (expected e.g. 45m, 2h, 90s, 1d)")
    value, unit = match.groups()
    return float(value) * _DURATION_UNITS[unit.lower()]


def _next_id(entries: list[dict[str, Any]]) -> int:
    highest = 0
    for entry in entries:
        try:
            highest = max(highest, int(entry.get("id", 0)))
        except Exception:
            continue
    return highest + 1


def _prune_expired(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for entry in entries:
        expires = entry.get("expires")
        if expires:
            try:
                if datetime.fromisoformat(str(expires)) <= now:
                    continue  # expired: dropped on this write, per the spec
            except Exception:
                pass
        kept.append(entry)
    return kept


def _write_reservations(path: Path | None, entries: list[dict[str, Any]]) -> None:
    target = path if path is not None else slot_budget.reservations_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(entries, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def reserve_slots(
    host: str,
    slots: int,
    duration: str,
    issue: int | None,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append a reservation of ``slots`` on ``host`` for ``duration`` (e.g. ``"45m"``, ``"2h"``)."""

    moment = now or datetime.now()
    seconds = parse_duration(duration)
    entries = slot_budget.read_reservations(path)
    entries = _prune_expired(entries, moment)
    entry = {
        "id": _next_id(entries),
        "host": str(host).strip().lower(),
        "slots": int(slots),
        "issue": issue,
        "created": moment.isoformat(timespec="seconds"),
        "expires": (moment + timedelta(seconds=seconds)).isoformat(timespec="seconds"),
    }
    entries.append(entry)
    _write_reservations(path, entries)
    return entry


def release_reservation(reservation_id: int, *, path: Path | None = None, now: datetime | None = None) -> bool:
    """Remove a reservation by id. Returns whether it was found."""

    entries = slot_budget.read_reservations(path)
    entries = _prune_expired(entries, now or datetime.now())
    kept = [entry for entry in entries if int(entry.get("id", -1)) != int(reservation_id)]
    found = len(kept) != len(entries)
    _write_reservations(path, kept)
    return found


__all__ = [
    "HostModeError",
    "append_event",
    "apply_mode",
    "apply_timed_mode",
    "owner_reservation",
    "release_owner_reservation",
    "set_owner_reservation",
    "daemon_repo_path",
    "daemon_status_path",
    "events_path",
    "find_pob_pids",
    "hosts_config_path",
    "load_hosts_config",
    "mark_posted_on_host",
    "mode_budget",
    "mode_priority",
    "modes_path",
    "parse_duration",
    "read_modes",
    "release_reservation",
    "reserve_slots",
    "revert_expired_modes",
    "run_on_host",
    "set_fillers",
    "effective_fillers",
    "read_host_switches",
    "host_switches_path",
    "set_priority_class",
    "write_budget_bom_free",
]
