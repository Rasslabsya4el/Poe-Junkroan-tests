"""Watchdog of a host's runs daemon (issue #353): start one when none is alive, else do nothing.

The daemon can die silently (2026-09-27: a console interrupt, 26 h with nothing running). A Task
Scheduler entry every 5 min calls ``ensure``; liveness is the same check ``runs submit`` uses
(``daemon.status_liveness`` over the host's status file). The start is the command written in
``docs/agents/runs.md`` "Starting and restarting a daemon", through ``scripts/launch_hidden.ps1``.

    python -m junkroan.runs.watchdog --host pc
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from junkroan.pob import slot_budget
from junkroan.runs import daemon as runs_daemon
from junkroan.report_format import human_duration
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import stopper

ROOT = Path(__file__).resolve().parents[3]
PC_PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe"


def daemon_command_line(host: str, python: str | None = None) -> str:
    """The daemon's start command (``docs/agents/runs.md`` "Starting and restarting a daemon")."""

    exe = python or (PC_PYTHON if Path(PC_PYTHON).is_file() else sys.executable)
    # The laptop has no gh: its daemon only stores hand-back bodies, the PC's posts them (#118).
    handback = "" if host == "pc" else "--handback remote "
    # `cmd /c` splits an unquoted path at its first space: the laptop's `C:\Program Files\...` (#73)
    if " " in exe and not exe.startswith('"'):
        exe = f'"{exe}"'
    return (f"{exe} scripts\\runs.py daemon --host {host} {handback}"
            f">> artifacts\\runs\\daemon-{host}.out 2>> artifacts\\runs\\daemon-{host}.err")


def hidden_launch(command_line: str, work_dir: Path) -> int:
    """Run ``scripts/launch_hidden.ps1`` (detached, no window); return the pid it prints."""

    script = ROOT / "scripts" / "launch_hidden.ps1"
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-CommandLine", command_line, "-WorkDir", str(work_dir)],
        capture_output=True, text=True, timeout=60,
    )
    match = re.search(r"rc=(\d+)\s+pid=(\d+)", proc.stdout or "")
    if not match:
        raise RuntimeError(f"launch_hidden.ps1 printed no rc/pid (exit {proc.returncode}): "
                           f"{(proc.stdout + proc.stderr).strip()[:200]}")
    if match.group(1) != "0":
        raise RuntimeError(f"launch_hidden.ps1 rc={match.group(1)}")
    return int(match.group(2))


def ensure(
    host: str,
    *,
    status_path: Path | None = None,
    pid_alive: Callable[[int], bool] | None = None,
    launch: Callable[[str, Path], int] | None = None,
    now: Callable[[], datetime] | None = None,
    out: Callable[[str], None] = print,
    kill: Callable[[int], bool] | None = None,
    err_path: Path | None = None,
) -> int:
    """0 = daemon alive (nothing started) or started; 1 = launch failed; 2 = not this host."""

    host = str(host).strip().lower()
    here = slot_budget.current_host()
    if host != here:
        out(f"refused: ensure acts only on this host ({here}), not {host}")
        return 2
    path = status_path if status_path is not None else runs_hosts.daemon_status_path(host)
    alive = pid_alive if pid_alive is not None else runs_daemon.QueueBackend().pid_alive
    clock = now if now is not None else (lambda: datetime.now(timezone.utc))
    status = runs_daemon.read_daemon_status(path)
    live, age = runs_daemon.status_liveness(status, now=clock(), pid_alive=alive)
    if live:
        out(f"alive pid {status['pid']}")
        return 0
    errfile = err_path if err_path is not None else ROOT / "artifacts" / "runs" / f"daemon-{host}.err"

    def takeover(reason: str) -> None:
        # #647: the reason is written before the kill and the launch, to the watchdog log and to the
        # daemon's own .err (same timestamp format as daemon._log)
        out(reason)
        try:
            errfile.parent.mkdir(parents=True, exist_ok=True)
            with open(errfile, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} watchdog: {reason}\n")
        except Exception:
            pass

    if not status:
        takeover("takeover: no status file")
    elif age is None:
        takeover(f"takeover: daemon pid {status.get('pid')} dead")
    if status and age is not None:
        # status_liveness gives an age only when the pid lives: a live pid with a stale tick is frozen
        # (#521: a hung `git fetch` held the laptop daemon 64 min); kill its tree before the new start.
        old_pid = int(status["pid"])
        stale = runs_daemon.stale_after(status.get("tick_seconds", runs_daemon.TICK_SECONDS))
        takeover(f"takeover: daemon pid {old_pid} tick age {int(age)} s > stale {int(stale)} s")
        out(f"stale: pid {old_pid} lives but last_tick {status.get('last_tick')} is {human_duration(age)} old; "
            "killing it and starting a new daemon")
        try:
            (kill or stopper.taskkill_pid)(old_pid)
        except Exception as exc:
            print(f"could not kill the stale pid {old_pid}: {exc!r}", file=sys.stderr)
            out("error: " + f"could not kill the stale pid {old_pid}: {exc!r}")  # #521: the task discards stderr; the log keeps it
    try:
        pid = (launch or hidden_launch)(daemon_command_line(host), ROOT)
    except Exception as exc:
        print(f"could not start the {host} daemon: {exc!r}", file=sys.stderr)
        out("error: " + f"could not start the {host} daemon: {exc!r}")  # #521: the task discards stderr; the log keeps it
        return 1
    out(f"pid {pid}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watchdog", description=__doc__)
    parser.add_argument("--host", default=None, help="this machine's name (default: current host)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    host = args.host or slot_budget.current_host()
    if str(host).strip().lower() == "laptop":
        from junkroan.runs import wifi

        wifi.check(log_path=ROOT / "artifacts" / "runs" / "wifi-laptop.log",
                   state_path=ROOT / "artifacts" / "runs" / "wifi-laptop.json")
    log_path = ROOT / "artifacts" / "runs" / f"watchdog-{str(host).strip().lower()}.log"

    def out(line: str) -> None:
        print(line)
        try:  # #521: the task's own output is discarded, so what ensure decided leaves a trace here
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
        except Exception:
            pass

    return ensure(host, out=out)


if __name__ == "__main__":
    raise SystemExit(main())
