"""Run the merge test suite on another host (the laptop) for one commit, or read that host's load (#685).

    python scripts/suite_on_host.py run --host laptop --commit <sha> --workers N --out <path> [--timeout-min M]
    python scripts/suite_on_host.py readings --host laptop

``run``: this machine pushes a temporary ref of the commit to ``origin`` (never a branch), one bounded
ssh call fetches it on the host into a worktree of its own (``<repo_path>-suite``, neither the host's repo
nor the runs daemon's checkout), checks the commit out detached, runs ``merge_suite`` from
``config/orchestration.json`` with ``-n N`` and ``merge_suite_env``, writes the output to a file there;
a bounded scp copies it to ``--out``. Exit code = the suite's rc. The ref is deleted from origin in a
``finally``. ``readings`` prints ``{"host", "logical_cores", "cpu_percent", "free_ram_gb"}``.

Any ssh/scp/push failure or timeout: exit 75 and ONE line saying why. No PoB is started.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.report_format import human_duration  # noqa: E402
from junkroan.runs.bounded import run_bounded  # noqa: E402
from junkroan.runs.hosts import describe_ssh_failure, load_hosts_config  # noqa: E402
from junkroan.runs.ssh_transport import build_scp_argv, build_ssh_argv  # noqa: E402

EXIT_UNREACHABLE = 75
EXIT_BUSY = 76
READINGS_TIMEOUT_S = 10
GIT_TIMEOUT_S = 120
COPY_TIMEOUT_S = 120
START_TIMEOUT_S = 180
POLL_TIMEOUT_S = 25
POLL_EVERY_S = 10
POLL_MISSES = 4
IDLE_POLLS = 4
CLEANUP_TIMEOUT_S = 30

_SUMMARY = re.compile(r"\d+ (?:passed|failed|error)")


class HostFailure(Exception):
    """A transport step failed; the message is the one line printed."""


class HostBusy(HostFailure):
    """Another suite holds the host's lock (#695); the message is ``suite <commit> since <time>``."""


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    """The one place a subprocess starts (tests replace it): hidden console, whole tree killed on timeout."""

    return run_bounded(list(argv), capture_output=True, text=True, timeout=timeout, cwd=str(ROOT),
                       stdin=subprocess.DEVNULL)


def _step(what: str, argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    started = time.monotonic()
    try:
        done = _run(argv, timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise HostFailure(f"{what}: {describe_ssh_failure(exc, time.monotonic() - started)}") from exc
    return done


def ssh_argv(host_cfg: dict[str, Any], script: str) -> list[str]:
    """``build_ssh_argv`` plus keepalives: a wifi drop mid-suite ends the call (~2 min) instead of hanging it."""

    argv = build_ssh_argv(host_cfg, script)
    return argv[:1] + ["-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"] + argv[1:]


def _ps(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def host_config(name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if config is not None else load_hosts_config()
    entry = config.get(name)
    if not isinstance(entry, dict) or not entry.get("ssh"):
        raise SystemExit(f"host {name!r} has no ssh alias in config/hosts.json")
    return {**entry, "name": name}


def suite_settings() -> tuple[str, dict[str, str]]:
    cfg = json.loads((ROOT / "config" / "orchestration.json").read_text(encoding="utf-8"))
    return str(cfg["merge_suite"]), {str(k): str(v) for k, v in (cfg.get("merge_suite_env") or {}).items()}


def suite_worktree(host_cfg: dict[str, Any]) -> str:
    return str(host_cfg["repo_path"]).rstrip("\\/") + "-suite"


def suite_lock_path(host_cfg: dict[str, Any]) -> str:
    return suite_worktree(host_cfg) + ".lock"


def lock_info(commit: str) -> str:
    return f"pc_pid={os.getpid()} commit={commit[:8]}"


def remote_start_script(host_cfg: dict[str, Any], ref: str, commit: str, suite_cmd: str,
                        env: dict[str, str], remote_out: str, task: str, lock_min: float = 40) -> str:
    """Session 0 (ssh): fetch + checkout + junctions, write the runner, create and start a one-shot task.

    The suite itself runs in the logged-in user's INTERACTIVE session (the task, started through
    ``tools/hosts/run-hidden.vbs`` like the daemon's watchdog, no console window): a Session 0 suite
    cannot see a desktop, so the window/WMI tests fail there. rc and seconds go to ``<out>.rc``.
    """

    repo, wt = str(host_cfg["repo_path"]), suite_worktree(host_cfg)
    daemon = str(host_cfg.get("daemon_repo_path") or repo)
    env = {**env, "JUNKROAN_HOST": str(host_cfg.get("name") or "laptop")}  # tests marked pc_only skip on any host but the PC
    env_lines = "\n".join(f"$env:{k} = {_ps(v)}" for k, v in env.items())
    runner = f"""$ErrorActionPreference = 'Continue'
Set-Location {_ps(wt)}
{env_lines}
$sw = [Diagnostics.Stopwatch]::StartNew()
cmd /c ({_ps(remote_out + ".cmd")})
$rc = $LASTEXITCODE
Set-Content -Path {_ps(remote_out + ".rc")} -Encoding ASCII -Value ("" + $rc + " " + [int]$sw.Elapsed.TotalSeconds)
"""
    return f"""$ErrorActionPreference = 'Continue'
$repo = {_ps(repo)}; $wt = {_ps(wt)}; $out = {_ps(remote_out)}; $ref = {_ps(ref)}; $daemon = {_ps(daemon)}
$tn = {_ps(task)}
$gui = Get-Process explorer -ErrorAction SilentlyContinue | Where-Object {{ $_.SessionId -gt 0 }} | Select-Object -First 1
if (-not $gui) {{ Write-Output 'SUITE_STEP_FAILED=no interactive session logged in'; exit 72 }}
$lock = {_ps(suite_lock_path(host_cfg))}; $info = {_ps(lock_info(commit))} + ' start=' + (Get-Date).ToString('s')
function Take-Lock {{ try {{ $fs = [IO.File]::Open($lock, 'CreateNew', 'Write', 'None'); $b = [Text.Encoding]::ASCII.GetBytes($info); $fs.Write($b, 0, $b.Length); $fs.Close(); return $true }} catch {{ return $false }} }}
if (-not (Take-Lock)) {{
  $item = Get-Item $lock -ErrorAction SilentlyContinue
  if ($item -and (((Get-Date) - $item.LastWriteTime).TotalMinutes -gt {float(lock_min)})) {{
    Write-Output ('SUITE_LOCK=stale ' + (Get-Content $lock -Raw).Trim())
    Remove-Item -Force -ErrorAction SilentlyContinue $lock
  }}
  if (-not (Take-Lock)) {{
    $held = (Get-Content $lock -Raw -ErrorAction SilentlyContinue)
    Write-Output ('SUITE_BUSY=' + ("" + $held).Trim()); exit 76 }}
}}
git -C $repo fetch origin ("+" + $ref + ":" + $ref) 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Write-Output 'SUITE_STEP_FAILED=fetch'; exit 70 }}
if (-not (Test-Path $wt)) {{ git -C $repo worktree add --detach $wt {_ps(commit)} 2>&1 | Out-Null }}
else {{ git -C $wt checkout --detach -f {_ps(commit)} 2>&1 | Out-Null; git -C $wt clean -fd 2>&1 | Out-Null }}
if ($LASTEXITCODE -ne 0) {{ Write-Output 'SUITE_STEP_FAILED=checkout'; exit 71 }}
git -C $repo update-ref -d $ref 2>&1 | Out-Null
foreach ($src in @($daemon, $repo)) {{
  if ((-not (Test-Path (Join-Path $wt 'vendor'))) -and (Test-Path (Join-Path $src 'vendor/pob'))) {{
    New-Item -ItemType Junction -Path (Join-Path $wt 'vendor') -Target (Join-Path $src 'vendor') | Out-Null }}
  if ((-not (Test-Path (Join-Path $wt 'var/cache/pob'))) -and (Test-Path (Join-Path $src 'var/cache/pob'))) {{
    New-Item -ItemType Directory -Force -Path (Join-Path $wt 'var/cache') | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $wt 'var/cache/pob') -Target (Join-Path $src 'var/cache/pob') | Out-Null }}
}}
Remove-Item -Force -ErrorAction SilentlyContinue ($out + '.rc'), $out
Set-Content -Path ($out + '.cmd') -Encoding ASCII -Value ({_ps(suite_cmd)} + ' > "' + $out + '" 2>&1')
$ps1 = $out + '.ps1'
Set-Content -Path $ps1 -Encoding ASCII -Value {_ps(runner)}
$vbs = Join-Path $wt 'tools/hosts/run-hidden.vbs'
$action = 'wscript.exe //B //Nologo "' + $vbs + '" "' + $ps1 + '"'
schtasks /Create /F /TN $tn /TR $action /SC ONCE /ST 23:59 /SD (Get-Date).ToString('MM/dd/yyyy') /RU $env:USERNAME /RL LIMITED 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Write-Output 'SUITE_STEP_FAILED=schtasks create'; exit 73 }}
schtasks /Run /TN $tn 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {{ Write-Output 'SUITE_STEP_FAILED=schtasks run'; exit 74 }}
Write-Output 'SUITE_STARTED=1'
exit 0
"""


def poll_script(remote_out: str, task: str) -> str:
    return f"""$rcf = {_ps(remote_out + ".rc")}
if (Test-Path $rcf) {{ Write-Output ('SUITE_DONE=' + (Get-Content $rcf -Raw).Trim()); exit 0 }}
$st = (schtasks /Query /TN {_ps(task)} /FO LIST 2>&1 | Select-String 'Status').ToString()
Write-Output ('SUITE_TASK=' + $st.Trim())
"""


def cleanup_script(remote_out: str, task: str, lock: str | None = None, info: str | None = None) -> str:
    release = ""
    if lock and info:  # only a lock this run wrote (its pc pid + commit) is released
        release = ("\n$l = " + _ps(lock) + "\nif ((Test-Path $l) -and ((Get-Content $l -Raw) -like (" + _ps(info)
                   + " + ' *'))) { Remove-Item -Force -ErrorAction SilentlyContinue $l }")
    return f"""schtasks /End /TN {_ps(task)} 2>&1 | Out-Null
schtasks /Delete /F /TN {_ps(task)} 2>&1 | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue {_ps(remote_out + ".ps1")}, {_ps(remote_out + ".cmd")}, {_ps(remote_out + ".rc")}{release}
"""


def readings_script() -> str:
    return """$ErrorActionPreference = 'Stop'
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$os = Get-CimInstance Win32_OperatingSystem
[ordered]@{ logical_cores = [int]$cs.NumberOfLogicalProcessors; cpu_percent = [double]$cpu;
  free_ram_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2) } | ConvertTo-Json -Compress
"""


def last_summary(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if _SUMMARY.search(ln)]
    return lines[-1] if lines else ""


def _marker(stdout: str, key: str) -> str | None:
    found = re.findall(rf"^{key}=(.*)$", stdout or "", flags=re.M)
    return found[-1].strip() if found else None


def _busy_words(info: str) -> str:
    commit = re.search(r"commit=(\S+)", info)
    since = re.search(r"start=(\S+)", info)
    return f"suite {commit.group(1) if commit else '?'} since {since.group(1) if since else '?'}"


def run_suite(host: str, commit: str, workers: int, out: Path, timeout_min: float = 40,
              config: dict[str, Any] | None = None, pytest_args: str | None = None) -> int:
    """Returns the suite's rc; raises :class:`HostFailure` for any transport problem."""

    host_cfg = host_config(host, config)
    suite_cmd, env = suite_settings()
    if pytest_args:
        suite_cmd = f"python -m pytest {pytest_args} -q -p no:faulthandler"
    else:
        suite_cmd = f"{suite_cmd} -n {int(workers)}"
    # a basetemp of its own, NEXT TO the worktree (inside any repo it breaks the tests that look at git state): the shared pytest-of-<user> dir holds symlinks a Session 0 run made, which an
    # interactive-session run cannot clean up (PermissionError at exit)
    suite_cmd += f' --basetemp="{suite_worktree(host_cfg)}-tmp"'
    sha = _step("rev-parse", ["git", "rev-parse", commit], 30)
    if sha.returncode != 0:
        raise HostFailure(f"commit {commit} unknown here")
    full = sha.stdout.strip()
    ref = f"refs/merge-suite/{full[:8]}-{os.getpid()}"
    remote_out = suite_worktree(host_cfg) + f"-{full[:8]}.out"
    task = f"junkroan-suite-{full[:8]}-{os.getpid()}"
    task_made = False
    try:
        push = _step("push ref", ["git", "push", "origin", f"{full}:{ref}"], GIT_TIMEOUT_S)
        if push.returncode != 0:
            raise HostFailure(f"push ref: rc {push.returncode} {(push.stderr or '').strip()[-120:]}")
        task_made = True
        script = remote_start_script(host_cfg, ref, full, suite_cmd, env, remote_out, task, timeout_min)
        started = time.monotonic()
        call = _step("ssh start", ssh_argv(host_cfg, script), START_TIMEOUT_S)
        busy = _marker(call.stdout, "SUITE_BUSY")
        if busy is not None:
            raise HostBusy(_busy_words(busy))
        stale = _marker(call.stdout, "SUITE_LOCK")
        if stale:
            print(f"host lock on {host} was stale ({_busy_words(stale.removeprefix('stale').strip())}), taken over")
        step_failed = _marker(call.stdout, "SUITE_STEP_FAILED")
        if step_failed:
            raise HostFailure(f"on {host}: {step_failed}")
        if call.returncode != 0 or _marker(call.stdout, "SUITE_STARTED") != "1":
            raise HostFailure(f"ssh start: {describe_ssh_failure(call, time.monotonic() - started)}")
        done_text = _wait_done(host_cfg, remote_out, task, timeout_min * 60)
        rc_text, _, seconds = done_text.partition(" ")
        if not rc_text.lstrip("-").isdigit():
            raise HostFailure(f"unreadable result file on {host}: {done_text!r}")
        out.parent.mkdir(parents=True, exist_ok=True)
        remote = remote_out.replace("\\", "/")
        copy = _step("copy out", ["scp", "-q", "-o", "BatchMode=yes", f"{host_cfg['ssh']}:{remote}", str(out)],
                     COPY_TIMEOUT_S)
        if copy.returncode != 0:
            raise HostFailure(f"copy out: {describe_ssh_failure(copy)}")
        print(f"suite on {host} at {full[:8]} with -n {workers}: rc {rc_text}"
              + (f" in {human_duration(float(seconds))}" if seconds.strip().isdigit() else ""))
        print(last_summary(out.read_text(encoding="utf-8-sig", errors="replace")) or "(no pytest summary line)")
        return int(rc_text)
    finally:
        if task_made:
            try:
                _run(ssh_argv(host_cfg, cleanup_script(remote_out, task, suite_lock_path(host_cfg), lock_info(full))), CLEANUP_TIMEOUT_S)
            except Exception:
                pass
        try:
            _run(["git", "push", "origin", f":{ref}"], GIT_TIMEOUT_S)
        except Exception:
            pass


def _wait_done(host_cfg: dict[str, Any], remote_out: str, task: str, budget_s: float) -> str:
    """Poll the host in short bounded ssh calls until the result file appears; one line of failure otherwise."""

    deadline = time.monotonic() + budget_s
    misses = 0
    idle = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        try:
            call = _run(ssh_argv(host_cfg, poll_script(remote_out, task)), POLL_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError) as exc:
            call, why = None, describe_ssh_failure(exc, time.monotonic() - started)
        else:
            why = describe_ssh_failure(call, time.monotonic() - started) if call.returncode != 0 else ""
        if call is None or call.returncode != 0:
            misses += 1
            if misses >= POLL_MISSES:
                raise HostFailure(f"polling the suite: {why} ({misses} calls in a row)")
        else:
            misses = 0
            done = _marker(call.stdout, "SUITE_DONE")
            if done is not None:
                return done
            status = _marker(call.stdout, "SUITE_TASK") or ""
            idle = idle + 1 if "running" not in status.lower() else 0
            if idle >= IDLE_POLLS:
                raise HostFailure(f"the suite task ended without a result file ({status})")
        time.sleep(POLL_EVERY_S)
    raise HostFailure(f"suite still running after {human_duration(budget_s)} (timeout)")

def read_readings(host: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    host_cfg = host_config(host, config)
    started = time.monotonic()
    call = _step("readings", ssh_argv(host_cfg, readings_script()), READINGS_TIMEOUT_S)
    if call.returncode != 0:
        raise HostFailure(f"readings: {describe_ssh_failure(call, time.monotonic() - started)}")
    try:
        data = json.loads((call.stdout or "").strip().splitlines()[-1])
        return {"host": host, "logical_cores": int(data["logical_cores"]),
                "cpu_percent": float(data["cpu_percent"]), "free_ram_gb": float(data["free_ram_gb"])}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HostFailure(f"readings: unreadable answer ({type(exc).__name__})") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--host", required=True)
    run.add_argument("--commit", required=True)
    run.add_argument("--workers", type=int, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--timeout-min", type=float, default=40)
    run.add_argument("--pytest-args", default=None, help="run these pytest args instead of the merge suite")
    rd = sub.add_parser("readings")
    rd.add_argument("--host", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "run":
            return run_suite(args.host, args.commit, args.workers, args.out, args.timeout_min, pytest_args=args.pytest_args)
        print(json.dumps(read_readings(args.host)))
        return 0
    except HostBusy as exc:
        print(f"laptop busy ({exc})")
        return EXIT_BUSY
    except HostFailure as exc:
        print(f"host unreachable or failed: {exc}")
        return EXIT_UNREACHABLE


if __name__ == "__main__":
    raise SystemExit(main())
