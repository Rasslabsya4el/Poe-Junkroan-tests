"""Keymaster CLI front (issue #36 "keymaster" redesign).

`submit` / `status` / `cancel` / `import-queue` talk to the job store (`src/junkroan/runs/store.py`,
an append-only JSONL log under `artifacts/runs/jobs.jsonl`). `mode` / `reserve` (issue #41) apply a
host's named budget mode and manage `var/reservations.json` (`src/junkroan/runs/hosts.py`).
`daemon` / `watch` (issue #48) are the part that actually runs jobs and hands finished runs back to
their issue (`src/junkroan/runs/daemon.py`). A thin argparse front, one function per subcommand:

    python scripts/runs.py submit --priority P1 --issue 12|--no-issue [--no-label] [--note <text>] [--pin <commit>] [--resumable] [--workers N|auto] [--after <job id> ...] -- <command ...>
    python scripts/runs.py status [--json]
    python scripts/runs.py cancel <id>                                     # a queued job only
    python scripts/runs.py stop <id> [--who NAME]                          # kill a running job's process tree, end it (local host)
    python scripts/runs.py import-queue [--queue artifacts/runs/queue.txt]
    python scripts/runs.py mode <host> <mode>                              # "I play" / "browser on the laptop"
    python scripts/runs.py reserve --host pc --slots 2 --for 45m --issue 12
    python scripts/runs.py reserve --release <id>
    python scripts/runs.py owner laptop film --for 2h|sleep [--for 2h]|back|status  # the owner's presets (#958)
    python scripts/runs.py daemon --host pc                                # launched detached; starts queued jobs
    python scripts/runs.py daemon --host laptop --handback remote          # no gh on the laptop (#118)
    python scripts/runs.py daemon --ensure --host pc                       # start one only when none is alive (#353)
    python scripts/runs.py mark-posted <job id>                            # another host's daemon calls this over ssh
    python scripts/runs.py mark-run-issue <job id> <n>                     # ditto: the Run issue (#164) was created
    python scripts/runs.py anomaly-taken <key>                             # the PC started this anomaly's keymaster (#467)
    python scripts/runs.py watch                                           # blocks until the next event line
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(1, str(ROOT))  # tools.agentops (the machine mode, #779)

from junkroan.pob import slot_budget  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from junkroan.runs import anomalies as runs_anomalies  # noqa: E402
from junkroan.runs import daemon as runs_daemon  # noqa: E402
from junkroan.runs import fillers as runs_fillers  # noqa: E402
from junkroan.runs.untracked import UntrackedTree, collect_local  # noqa: E402
from junkroan.runs.dedupe import find_identical  # noqa: E402
from junkroan.runs.finished_tag import finished_run_dir  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import gates as runs_gates  # noqa: E402
from junkroan.runs import pin_ref as runs_pin_ref  # noqa: E402
from junkroan.runs import placement as runs_placement  # noqa: E402
from junkroan.runs import rebalance as runs_rebalance  # noqa: E402
from junkroan.runs import run_name  # noqa: E402
from junkroan.runs import weekly_cut  # noqa: E402
from junkroan.runs import filler_week  # noqa: E402
from junkroan.runs import self_restart  # noqa: E402
from junkroan.runs import stopper as runs_stopper  # noqa: E402
from junkroan.runs.store import (  # noqa: E402
    DEP_BLOCKED,
    DEP_READY,
    dependency_status,
    held_reason,
    DEFAULT_LOG,
    MAIN_ROOT,
    DuplicateTag,
    HOSTS,
    IllegalTransition,
    JobNotFound,
    PRIORITIES,
    Store,
    split_pin,
)

DEFAULT_QUEUE = MAIN_ROOT / "artifacts" / "runs" / "queue.txt"


def _store(args: argparse.Namespace) -> Store:
    return Store(Path(args.store) if getattr(args, "store", None) else DEFAULT_LOG)


def _age_seconds(ts: str | None) -> float | None:
    if not ts:
        return None
    then = datetime.fromisoformat(ts)
    now = datetime.now(then.tzinfo) if then.tzinfo else datetime.now()
    return (now - then).total_seconds()


# -- submit -----------------------------------------------------------------------------------

def encode_argv(argv: list[str]) -> str:
    return base64.b64encode(json.dumps(list(argv)).encode("utf-8")).decode("ascii")


def decode_argv(token: str) -> list[str]:
    return [str(x) for x in json.loads(base64.b64decode(token).decode("utf-8"))]


def _remote_submit_script(repo_path: str, host: str, flag_argv: list[str], cmd_argv: list[str]) -> str:
    """The exact ``runs.py submit`` line to run in ``repo_path``'s own checkout, over ssh (#120).

    Forwards ``flag_argv``/``cmd_argv`` unchanged (same split as this process's own ``argv``, ``--``
    included only when there was a command) so the remote store gets the identical job the caller
    asked for. Every argument is quoted for PowerShell (:func:`runs_hosts.quote_ps_arg`) -- the same hazard
    ``ssh_transport``'s own docstring names for a script crossing ssh, here for a literal argument
    rather than a whole script. Sets ``$env:JUNKROAN_HOST`` to ``host`` first: without it the remote
    side's own ``slot_budget.current_host()`` falls back to its default (``"pc"``), so the same
    "is this host mine" check that made THIS process go remote would send the laptop's own submit
    right back out over ssh to itself (a #120 follow-up bug: a real round trip against the laptop
    never actually landed a job on it).
    """

    parts = ["python", "scripts\\runs.py", "submit", *flag_argv]
    if cmd_argv:
        # PowerShell 5.1 mangles an embedded `"` and an empty arg to a native exe: one base64 token (#203)
        parts.extend(["--argv-b64", encode_argv(cmd_argv)])
    line = " ".join(runs_hosts.quote_ps_arg(part) for part in parts)
    return f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; cd '{repo_path}'; & {line}"


def _submit_remote(host: str, flag_argv: list[str], cmd_argv: list[str]) -> int:
    """Run ``submit`` on ``host`` over ssh, in its own daemon checkout (#120 decision, part 1).

    Exactly one remote call (:func:`junkroan.runs.hosts.run_on_host`); nothing is written to the
    local store either way. A failure to reach the host -- an unknown host, an exception from
    ssh, ssh's own exit code 255 (OpenSSH's connection-error code) -- is one
    ``submit: <host> unreachable: ...`` stderr line and a non-zero exit (part 2). Any other
    non-zero exit means the host answered: its own stderr/stdout text (usually its own
    ``submit: ...`` refusal) is printed as is, without the word "unreachable" (#462), exit 1.
    A reply with no job id is still ``unreachable``. On success the remote store's own job id is printed, unchanged. Runs in
    ``hosts.daemon_repo_path(host_cfg)`` -- the laptop's own runs daemon runs from a separate
    checkout (``C:\\Coding\\poe-junkroan-v2-daemon``, ``docs/STATE.md``), not `config/hosts.json`'s
    plain ``repo_path``, so this must land in the SAME store that host's daemon actually reads.
    """

    try:
        host_cfg = runs_hosts.load_hosts_config()[host]
    except Exception as exc:
        print(f"submit: {host} unreachable: could not load its config ({exc!r})", file=sys.stderr)
        return 1
    script = _remote_submit_script(runs_hosts.daemon_repo_path(host_cfg), host, flag_argv, cmd_argv)
    try:
        result = runs_hosts.run_on_host(host_cfg, script)
    except Exception as exc:
        print(f"submit: {host} unreachable: {exc!r}", file=sys.stderr)
        return 1
    if getattr(result, "returncode", 1) != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        if getattr(result, "returncode", 1) == 255:  # OpenSSH's own connection-error exit code
            print(f"submit: {host} unreachable: {detail or 'ssh exit 255'}", file=sys.stderr)
        else:
            print(detail or f"submit: {host} refused: non-zero exit", file=sys.stderr)
        return 1
    output = (getattr(result, "stdout", "") or "").strip()
    job_id = output.splitlines()[-1].strip() if output else ""
    if not job_id:
        print(f"submit: {host} unreachable: no job id in its reply ({output!r})", file=sys.stderr)
        return 1
    print(job_id)
    return 0


def _read_host_jobs(host_cfg: dict) -> list:
    """Another host's jobs, read over ssh the way `relabel` reads them (#648); the tests replace this seam."""
    from junkroan.runs import remote_store

    return remote_store.read_remote_jobs(host_cfg, timeout=remote_store.FOREGROUND_TIMEOUT_SECONDS)


def _host_of_predecessors(store: Store, local_host: str, after: list[str]) -> tuple[str | None, str]:
    """(host, error): the one host whose store holds every `--after` id (#648)."""
    ids = list(dict.fromkeys(str(x).strip() for x in after if str(x).strip()))
    local_ids = {j.id for j in store.jobs()}
    if all(i in local_ids for i in ids):
        return local_host, ""
    try:
        config = runs_hosts.load_hosts_config()
    except Exception as exc:
        return None, f"submit: --after names no such job here and the hosts config is unreadable ({exc!r})"
    problems = []
    for host, host_cfg in config.items():
        if host == local_host:
            continue
        try:
            remote_ids = {j.id for j in _read_host_jobs(host_cfg)}
        except Exception as exc:
            problems.append(f"{host} unreadable ({exc})")
            continue
        if all(i in remote_ids for i in ids):
            return host, ""
        if any(i in remote_ids or i in local_ids for i in ids):
            return None, f"submit: --after ids are split across hosts: {', '.join(ids)}; a follower lives in the store of its predecessors"
    detail = f" ({'; '.join(problems)})" if problems else ""
    return None, f"submit: --after names no such job: {', '.join(ids)}{detail}"


def _without_host(argv: list[str]) -> list[str]:
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
        elif a == "--host":
            skip = True
        elif not a.startswith("--host="):
            out.append(a)
    return out


def _src_tree_hash(pin: str) -> str | None:
    """`git rev-parse <pin>:src/junkroan` in the repo root; None when git cannot say."""
    res = subprocess.run(["git", "rev-parse", f"{pin}:src/junkroan"], cwd=ROOT,
                         capture_output=True, text=True)
    return (res.stdout.strip() or None) if res.returncode == 0 else None


def _today() -> date:
    """The local date a run name carries (#578); the tests pin it."""
    return date.today()


def _expanded_builds_glob(cmd_argv: list[str]) -> int:
    """#551: how many paths a shell-expanded `--builds` glob left in the command, 0 when it is fine.
    `--builds a b c` (value plus stray positionals) counts; `--builds=a b.pob.txt` counts only when
    the strays are .pob.txt/.xml paths."""
    for i, tok in enumerate(cmd_argv):
        if tok == "--builds":
            strays = []
            for t in cmd_argv[i + 1:]:
                if t.startswith("-"):
                    break
                strays.append(t)
            if len(strays) >= 2:
                return len(strays)
        elif tok.startswith("--builds="):
            strays = []
            for t in cmd_argv[i + 1:]:
                if t.startswith("-") or not t.lower().endswith((".pob.txt", ".xml")):
                    break
                strays.append(t)
            if strays:
                return 1 + len(strays)
    return 0


def _head_sha() -> str | None:
    """HEAD of the submitting checkout (#861 rule 3), or None when git cannot say."""

    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and len(sha) >= 40 else None
    except Exception:
        return None


def cmd_submit(store: Store, argv: list[str], *, again_hint: str = "--again") -> int:
    if "--" in argv:
        i = argv.index("--")
        flag_argv, cmd_argv = argv[:i], argv[i + 1:]
    else:
        flag_argv, cmd_argv = argv, []
    if not cmd_argv and "--argv-b64" in flag_argv:  # the remote form (#203)
        i = flag_argv.index("--argv-b64")
        cmd_argv = decode_argv(flag_argv[i + 1])
        flag_argv = flag_argv[:i] + flag_argv[i + 2:]
    if not cmd_argv:
        print("submit: a command is required after `--`", file=sys.stderr)
        return 2

    expanded = _expanded_builds_glob(cmd_argv)
    if expanded:  # #551: the shell expanded an unquoted --builds glob; replay_bench takes one string
        print(f"the --builds glob was expanded by your shell into {expanded} paths: quote it "
              "(\"--builds 'artifacts/x/*.pob.txt'\")", file=sys.stderr)
        return 2

    if any(a == "--tag" or a.startswith("--tag=") for a in flag_argv):
        print("runs submit: --tag is gone (#578): the name is derived as P<priority>-<#issue|core>, plus -<n> when that name exists; "
              "put free text in --note", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(prog="runs.py submit", add_help=False)
    parser.add_argument("--host", default="auto", choices=[*HOSTS, "auto"],
                        help="auto (default): the host where the job starts soonest (#403)")
    parser.add_argument("--priority", required=True, choices=PRIORITIES)
    parser.add_argument("--issue", type=int, default=None)
    parser.add_argument("--no-issue", action="store_true",
                        help="the result goes to no issue (a submit must say --issue N or --no-issue)")
    parser.add_argument("--no-label", action="store_true",
                        help="the hand-back comments on --issue but leaves its labels alone (#515)")
    parser.add_argument("--note", default="", help="free text shown as status's last column")
    parser.add_argument("--outlives-ticket", action="store_true",
                        help="the job keeps running after its --issue is closed (#686); say why in --note")
    parser.add_argument("--pin", default=None)
    parser.add_argument("--resumable", action="store_true")
    parser.add_argument("--submitter", default="")
    parser.add_argument("--workers", default=None, metavar="N|auto",
                        help="PoB workers this job wants at once: an int >= 1, or `auto` (the daemon sizes it "
                             "to the free room at start, #570). Default: the command's own --workers, else 1")
    parser.add_argument("--after", action="append", default=[], metavar="JOB_ID",
                        help="wait until this job has ended rc 0 (repeatable; unknown id = error)")
    parser.add_argument("--again", action="store_true",
                        help="queue the tag even though its results folder already holds a finished run (#365)")
    parser.add_argument("--rc-is-reading", action="store_true",
                        help="the job's exit code is its reading (bisect pin, probe): a non-zero rc raises no "
                             "job_failed anomaly; a lost process still does")
    parser.add_argument("--host-reason", default=None, help=argparse.SUPPRESS)  # #648: set on the forwarded argv of an after-inherit
    parser.add_argument("--host-auto-placed", action="store_true", help=argparse.SUPPRESS)  # #518: set on the forwarded argv of an auto placement
    args = parser.parse_args(flag_argv)
    if args.workers is not None:
        w = str(args.workers).strip().lower()
        if w != "auto" and not (w.isdigit() and int(w) >= 1):
            print("runs submit: --workers takes an integer >= 1 or `auto`", file=sys.stderr)
            return 2
        declared: int | str | None = "auto" if w == "auto" else int(w)
    else:  # the command's own --workers declares it; a command without one has no pool to size (#570)
        declared = runs_daemon.declared_workers(cmd_argv[0] if len(cmd_argv) == 1 else None,
                                                cmd_argv if len(cmd_argv) > 1 else None)
    if declared is None and runs_daemon.script_has_workers_option(
            cmd_argv[0] if len(cmd_argv) == 1 else None, cmd_argv if len(cmd_argv) > 1 else None):
        # #700: a PoB script with a --workers option and none on the line starts its own default (5); the queue
        # counts what it starts: `--workers auto` is sized at start from the free slots and written into the command
        declared = "auto"
        cmd_argv = [f"{cmd_argv[0]} --workers auto"] if len(cmd_argv) == 1 else [*cmd_argv, "--workers", "auto"]
    workers_auto = declared == "auto"
    args.workers = 1 if declared is None or workers_auto else int(declared)
    if args.issue is None and not args.no_issue:
        print("runs submit: name the issue the result goes to (--issue N), or say --no-issue", file=sys.stderr)
        return 2
    if args.issue is not None and args.no_issue:
        print("runs submit: --issue and --no-issue together; pick one", file=sys.stderr)
        return 2
    if args.no_issue and not run_name.is_core_command(cmd_argv[0] if len(cmd_argv) == 1 else cmd_argv):
        print("runs submit: a run without a ticket is only the weekly core run (core14 benchmark); "
              "name the issue with --issue N (#578)", file=sys.stderr)
        return 2
    if args.no_label and args.no_issue:
        print("runs submit: --no-label needs --issue N (it keeps that issue's labels)", file=sys.stderr)
        return 2

    # #120: a submit for a host that is not this one goes to THAT host's own store, over ssh --
    # never into this process's local store (`slot_budget.current_host()` is the same "which host
    # am I" the daemon already uses when `runs.py daemon` gets no explicit `--host`). `any` stays
    # local: it is picked up by whichever host's own daemon calls `next_job`, unchanged by #120.
    local_host = slot_budget.current_host()
    # #518: an explicit pc|laptop is fixed (the rebalancer never moves it); an auto placement is not,
    # and its forwarded argv says so with --host-auto-placed, so the far store records False too.
    host_fixed = args.host in HOSTS and args.host != "any" and not args.host_auto_placed
    host_reason = args.host_reason
    if args.host == "auto" and args.after:  # #648: the follower lives in the store of its predecessors
        found, err = _host_of_predecessors(store, local_host, args.after)
        if found is None:
            print(err, file=sys.stderr)
            return 1
        args.host = found
        host_fixed = True
        host_reason = "after:" + ",".join(dict.fromkeys(a.strip() for a in args.after if a.strip()))
        print(f"submit: host {found} ({host_reason})", file=sys.stderr)
        flag_argv = [*_without_host(flag_argv), "--host", found, "--host-reason", host_reason]
    elif args.host == "auto":
        all_states = runs_placement.gather_states(local_host=local_host, local_store=store)
        wanted = runs_placement.pick_host(args.workers, all_states)
        gate_cmd = cmd_argv[0] if len(cmd_argv) == 1 else subprocess.list2cmdline(cmd_argv)
        newest = runs_gates.newest_gate(runs_gates.ROOT / "artifacts")  # #642: a gate-reading job stays where the gate is
        # (#642 unit 6b) the artifacts folders the command names, read as the rebalancer reads them; no copy at submit
        try:
            named = runs_rebalance.replay_dirs(SimpleNamespace(cmd=gate_cmd, argv=None), runs_gates.ROOT / "artifacts") or []
        except Exception:  # a command line replay_dirs cannot read names no folder, as the rebalancer's _replay_dirs
            named = []
        states, dropped = runs_placement.gate_filter(all_states, gate_cmd, newest, runs_gates.gates_present, dirs=named)
        args.host = runs_placement.pick_host(args.workers, states)
        if wanted in dropped and named:
            missing = [d for d in named if runs_gates.dir_key(d) not in runs_gates.gates_present(wanted)]
            print(f"submit: placed on {args.host}; {wanted} lacks {', '.join(missing)}", file=sys.stderr)
        elif wanted in dropped:
            print(f"submit: placed on {args.host}; {wanted} lacks gate {newest or 'none'}", file=sys.stderr)
        else:
            print(f"submit: placed on {args.host}", file=sys.stderr)
        flag_argv = [*_without_host(flag_argv), "--host", args.host, "--host-auto-placed"]
    # #877 rule 4: a script that is not in the checkout at the pin is refused before anything is queued
    try:
        check_argv = shlex.split(cmd_argv[0], posix=False) if len(cmd_argv) == 1 else cmd_argv
    except ValueError:
        check_argv = []
    gone = runs_pin_ref.missing_script(ROOT, args.pin, check_argv)
    if gone is not None:
        print(f"runs submit: {gone[0]} does not exist at pin {gone[1][:12]}"
              f"{'' if args.pin else ' (HEAD)'}; 0 jobs queued", file=sys.stderr)
        return 2
    if args.pin and args.host != local_host:  # #756 rule 2: the pin travels through origin
        ok, msg = runs_pin_ref.push_pin(ROOT, args.pin)
        if not ok:  # #889: a pin that cannot reach the host never waits in its queue to fail at its start
            if host_fixed:
                print(f"runs submit: {msg}; not queued on {args.host}", file=sys.stderr)
                return 1
            print(f"submit: {msg}; staying on {local_host}", file=sys.stderr)
            args.host = local_host
            flag_argv = [*_without_host(flag_argv), "--host", local_host]
    if args.host not in (local_host, "any"):
        return _submit_remote(args.host, flag_argv, cmd_argv)  # the finished-tag check runs there, on its artifacts

    name = run_name.derive_name(args.priority, args.issue, args.no_issue,
                                [j.tag for j in store.jobs()])
    if not args.again:
        done = finished_run_dir(name, ROOT)
        if done is not None:
            print(f"runs submit: tag {name} already finished in {done}; pass {again_hint} to run it again",
                  file=sys.stderr)
            return 2
    cmd_argv = run_name.with_benchmark_tag(cmd_argv, name)

    # one argument after `--` is one shell line, started through the shell as before (a
    # `set X=... && python ...` line keeps working); two or more are an argv, no shell
    one_line = len(cmd_argv) == 1
    cmd = cmd_argv[0] if one_line else subprocess.list2cmdline(cmd_argv)
    if not args.again:  # #468: the same code and command already queued, running or done
        same = find_identical(
            store.jobs(), pin=args.pin,
            argv=shlex.split(cmd, posix=False) if one_line else cmd_argv, tree_hash=_src_tree_hash)
        if same is not None:
            recorded = ""
            if args.issue is not None and args.issue != same.issue and args.issue not in same.extra_issues:
                try:        # #468: its hand-back goes to this issue too
                    store.add_issue(same.id, args.issue)
                    recorded = f"; #{args.issue} recorded on it, its hand-back goes there too"
                except Exception as exc:
                    recorded = f"; #{args.issue} could not be recorded on it ({exc})"
            print(f"submit: identical to {same.id} ({same.state}): same src/junkroan tree "
                  f"{_src_tree_hash(same.pin)}, same command; pass {again_hint} to run it anyway{recorded}",
                  file=sys.stderr)
            return 1
    try:
        job = store.submit(
            host=args.host, priority=args.priority, tag=name, cmd=cmd, note=args.note,
            issue=args.issue, submitter=args.submitter, pin=args.pin, resumable=args.resumable,
            workers=args.workers, after=args.after, argv=None if one_line else cmd_argv,
            rc_is_reading=args.rc_is_reading, no_label=args.no_label, host_fixed=host_fixed,
            workers_auto=workers_auto, host_reason=host_reason,
            outlives_ticket=args.outlives_ticket, submit_commit=_head_sha(),
        )
    except DuplicateTag as exc:
        print(f"submit: {exc}", file=sys.stderr)
        return 1
    except JobNotFound as exc:
        print(f"submit: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 1
    print(job.id)
    return 0


# -- status -----------------------------------------------------------------------------------

def cmd_status(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py status", add_help=False)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--state", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--all", action="store_true")  # #1070: every job, not only live and recent ones
    parser.add_argument("--untracked-json", action="store_true", help=argparse.SUPPRESS)  # run on a remote host (#365)
    args = parser.parse_args(argv)

    if args.untracked_json:
        print(json.dumps([asdict(t) for t in collect_local(store)]))
        return 0

    jobs = store.jobs(state=args.state, host=args.host)
    if args.json:
        rows_json = [j.as_dict() for j in jobs]
        held = {job.id: held_reason(dep) for job, dep, status in store.held_jobs(args.host) if status == DEP_BLOCKED}
        for row in rows_json:
            if row["id"] in held:   # #862: a follower of a failed predecessor, never a slot reason
                row["reason"] = held[row["id"]]
                row["estimate"] = ""
        print(json.dumps(rows_json, indent=2, sort_keys=True))
        return 0

    # #1070: the table shows live jobs and those that ended in the last 24 h; `--state X` and `--all` show all.
    hidden = 0
    if args.state is None and not args.all:
        shown = [j for j in jobs if _in_status_window(j)]
        hidden = len(jobs) - len(shown)
        jobs = shown

    header = ("id", "host", "priority", "workers", "issue", "tag", "state", "age / duration", "note")
    rows = []
    for j in jobs:
        if j.state == "queued":
            duration = human_duration(_age_seconds(j.submit_ts))
        elif j.state == "running":
            duration = human_duration(_age_seconds(j.start_ts))
        elif j.start_ts and j.end_ts:
            span = (datetime.fromisoformat(j.end_ts) - datetime.fromisoformat(j.start_ts)).total_seconds()
            duration = human_duration(span)
        else:
            duration = "-"
        shown = "auto" if (j.workers_auto and j.state == "queued") else str(j.workers)
        state_col, note_col = ("moved", j.moved_to) if j.moved_to else (j.state, j.note)
        if j.state in ("stopped", "cancelled") and j.reason and not j.moved_to:  # #686: why it ended
            note_col = f"{j.reason} | {j.note}" if j.note else j.reason
        rows.append((j.id, j.host, j.priority, shown, str(j.issue if j.issue is not None else "-"), j.tag, state_col, duration, note_col))

    widths = [max(len(header[c]), *(len(r[c]) for r in rows)) if rows else len(header[c]) for c in range(len(header))]
    def fmt(row: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[c]) for c, cell in enumerate(row))
    print(fmt(header))
    print(fmt(tuple("-" * w for w in widths)))
    for row in rows:
        print(fmt(row))
    # The `--after` holds (#82), under the table: a queued job that is not starting because a
    # predecessor has not ended rc 0 yet, or never will.
    for job, dep, status in store.held_jobs(args.host):
        if args.state is not None and args.state != "queued":
            continue
        if status == DEP_BLOCKED:
            print(f"{job.id} {held_reason(dep)}")
            continue
        where = f"{dep.id} ({dep.state})" if dep is not None else ", ".join(job.after) or "?"
        print(f"{job.id} {status}: --after {where}")
    if args.state is None or args.state == "queued":
        all_jobs = {j.id: j for j in store.jobs()}  # #1144: a follower's predecessors decide whether its gate line shows
        for line in _gate_lines(jobs, all_jobs=all_jobs):
            print(line)
    for line in _untracked_lines(store, args.host):
        print(line)
    for line in _slot_lines(args.host):
        print(line)
    if hidden:
        print(f"{hidden} older jobs hidden (--all)")
    return 0


STATUS_WINDOW_SECONDS = 24 * 3600  # #1070: how long an ended job stays in the default status table


def _in_status_window(job, now: datetime | None = None) -> bool:
    """A queued or running job, or one that ended within `STATUS_WINDOW_SECONDS` (#1070)."""

    if job.state in ("queued", "running"):
        return True
    if not job.end_ts:
        return False
    now = now or datetime.now(timezone.utc)
    ended = datetime.fromisoformat(job.end_ts)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    return (now - ended).total_seconds() <= STATUS_WINDOW_SECONDS


GATE_STATUS_FRESH_SECONDS = 120.0


def _slot_lines(only_host: str | None = None, now: datetime | None = None,
                local_now: datetime | None = None) -> list[str]:
    """``<host>: <in_use> of <total> slots in use[, the owner reserved N until HH:MM (<m> left)]`` per host (#621).

    From each host's fresh daemon status file; a host without one (or a stale one) prints nothing.
    """

    now = now or datetime.now(timezone.utc)
    local_now = local_now or datetime.now()
    lines: list[str] = []
    for host in ([only_host] if only_host and only_host != "any" else ["pc", "laptop"]):
        status = runs_daemon.read_daemon_status(runs_hosts.daemon_status_path(host))
        if not status or "slots_total" not in status:
            continue
        try:
            age = (now - datetime.fromisoformat(str(status["last_tick"]))).total_seconds()
        except (KeyError, ValueError, TypeError):
            continue
        if age > GATE_STATUS_FRESH_SECONDS:
            continue
        line = f"{host}: {status.get('slots_in_use', 0)} of {status['slots_total']} slots in use"
        reserved = int(status.get("reserved") or 0)
        if reserved and status.get("reserved_until"):
            try:
                until = datetime.fromisoformat(str(status["reserved_until"]))
                left = human_duration(max(0.0, (until - local_now).total_seconds()))
                line += f", the owner reserved {reserved} until {until:%H:%M} ({left} left)"
            except ValueError:
                pass
        lines.append(line)
    return lines


def _gate_lines(jobs, now: datetime | None = None, all_jobs: dict | None = None) -> list[str]:
    """``<job> held: <gate> (<detail>)`` for each queued job whose `--after` predecessors are all done, from the daemon's status file (#549, #1144).

    A file older than 2 min (or without a ``last_tick``) -> ``held: unknown (daemon status <age> old)``;
    a missing file -> ``held: unknown (daemon status missing)``; a job the file does not list -> nothing.
    A follower with a live predecessor keeps its ``waiting:`` line and one with a failed predecessor its
    ``held: predecessor`` line, both printed by the ``--after`` loop; neither gets a gate line here.
    """

    now = now or datetime.now(timezone.utc)
    if all_jobs is None:
        all_jobs = {j.id: j for j in jobs}
    cache: dict[str, dict | None] = {}
    lines: list[str] = []
    for job in jobs:
        if job.state != "queued":
            continue
        if job.after and dependency_status(job, all_jobs)[0] != DEP_READY:
            continue
        host = job.host if job.host != "any" else "pc"
        if host not in cache:
            cache[host] = runs_daemon.read_daemon_status(runs_hosts.daemon_status_path(host))
        status = cache[host]
        if status is None:
            lines.append(f"{job.id} held: unknown (daemon status missing)")
            continue
        try:
            age = (now - datetime.fromisoformat(str(status["last_tick"]))).total_seconds()
        except (KeyError, ValueError, TypeError):
            age = None
        if age is None or age > GATE_STATUS_FRESH_SECONDS:
            shown = human_duration(age) if age is not None else "unknown age"
            lines.append(f"{job.id} held: unknown (daemon status {shown} old)")
            continue
        gate = (status.get("gates") or {}).get(job.id)
        if gate:
            lines.append(f"{job.id} held: {gate.get('gate')} ({gate.get('detail')})")
    return lines


def cmd_relabel(store: Store, argv: list[str], gh=None, remote_reader=None, hosts_config=None) -> int:
    """``runs.py relabel --issue N``: add ``ready-for-agent`` to #N only when none of its jobs is queued or running.

    Both hosts count: this host's store plus every other host's, read the way the daemon reads them (#500).
    A host that cannot be read is named and does not hold the label back. Exit 0 both ways; a closed issue (#803) is not labeled and exits 1.
    """

    from junkroan.runs import remote_store

    parser = argparse.ArgumentParser(prog="runs.py relabel", add_help=False)
    parser.add_argument("--issue", type=int, required=True)
    args = parser.parse_args(argv)

    jobs = list(store.jobs())
    try:
        config = hosts_config if hosts_config is not None else runs_hosts.load_hosts_config()
    except Exception as exc:
        print(f"relabel: could not load config/hosts.json ({exc!r}); only this host's store was read")
        config = {}
    reader = remote_reader or (lambda cfg: remote_store.read_remote_jobs(
        cfg, timeout=remote_store.FOREGROUND_TIMEOUT_SECONDS))  # a human waits here (#509)
    me = slot_budget.current_host()
    for host, host_cfg in config.items():
        if host == me:
            continue
        try:
            jobs.extend(reader(host_cfg))
        except Exception as exc:
            print(f"relabel: {host} unreadable ({exc}); its jobs are not counted")

    live = runs_daemon.live_jobs_of_issue(jobs, args.issue)
    if live:
        print(f"relabel: #{args.issue} not labeled, held back by: "
              + ", ".join(f"{j.id} ({j.host}, {j.state})" for j in live))
        return 0
    gh = gh or runs_daemon.GhCli()
    opener = getattr(gh, "issue_open", None)
    is_open = opener(args.issue) if opener is not None else True
    if is_open is not True:
        why = "is closed" if is_open is False else "state unreadable"
        print(f"relabel: #{args.issue} not labeled, it {why}", file=sys.stderr)
        runs_daemon._log(f"relabel: #{args.issue} not labeled, it {why} (runs relabel)")
        return 1
    if gh.add_label(args.issue, runs_daemon.HANDBACK_LABEL):
        runs_daemon._log(f"relabel: '{runs_daemon.HANDBACK_LABEL}' added to #{args.issue} (runs relabel)")
        print(f"relabel: #{args.issue} labeled {runs_daemon.HANDBACK_LABEL}")
    else:
        print(f"relabel: #{args.issue} label NOT added (gh failed)", file=sys.stderr)
    return 0


def _untracked_row(t: UntrackedTree) -> str:
    if t.started:
        when = datetime.fromtimestamp(t.started).strftime("%Y-%m-%d %H:%M")
        age = f" ({human_duration(max(0.0, time.time() - t.started))})"
    else:
        when, age = "?", ""
    pid = t.pid if t.pid is not None else "?"
    return f"untracked  pid {pid}  started {when}{age}  slots {t.slots}  tag {t.tag or '-'}  {t.cmd_head}"


def _untracked_lines(store: Store, host: str | None) -> list[str]:
    """Rows for PoB slots held by a process tree the store does not know (#365); the local host only when no --host."""

    local_host = slot_budget.current_host()
    if host is None or host == local_host:
        return [_untracked_row(t) for t in collect_local(store)]
    try:
        host_cfg = runs_hosts.load_hosts_config()[host]
        script = (f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; cd '{runs_hosts.daemon_repo_path(host_cfg)}'; "
                  "python scripts\\runs.py status --untracked-json")
        result = runs_hosts.run_on_host(host_cfg, script)
        if getattr(result, "returncode", 1) != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            raise RuntimeError(detail or "non-zero exit")
        out = (getattr(result, "stdout", "") or "").strip()
        trees = [UntrackedTree(**d) for d in json.loads(out.splitlines()[-1])]
    except Exception as exc:
        return [f"untracked: {host} unreachable ({exc})"]
    return [_untracked_row(t) for t in trees]


# -- cancel -----------------------------------------------------------------------------------

def cmd_mark_posted(store: Store, argv: list[str]) -> int:
    """Mark a job's hand-back posted in THIS process's own store (issue #118 requirement 2).

    A daemon that stored its hand-back with ``--handback remote`` never posts its own comment;
    another host's daemon posts it and then runs this over ssh, in this checkout, so the job
    never shows unposted for ever once its comment is actually out.
    """

    parser = argparse.ArgumentParser(prog="runs.py mark-posted", add_help=False)
    parser.add_argument("job_id")
    args = parser.parse_args(argv)

    try:
        job = store.mark_posted(args.job_id)
    except JobNotFound:
        print(f"mark-posted: no such job {args.job_id!r}", file=sys.stderr)
        return 1
    except IllegalTransition as exc:
        print(f"mark-posted: {exc}", file=sys.stderr)
        return 1
    print(f"{job.id} -> posted")
    return 0


def cmd_mark_run_issue(store: Store, argv: list[str]) -> int:
    """``runs.py mark-run-issue <job id> <n>``: another host's daemon created this job's Run issue (#164)."""

    parser = argparse.ArgumentParser(prog="runs.py mark-run-issue", add_help=False)
    parser.add_argument("job_id")
    parser.add_argument("number", type=int)
    args = parser.parse_args(argv)
    try:
        job = store.record_run_issue(args.job_id, args.number)
    except (JobNotFound, IllegalTransition) as exc:
        print(f"mark-run-issue: {exc}", file=sys.stderr)
        return 1
    print(f"{job.id} -> run issue #{job.run_issue}")
    return 0


def cmd_run_issues(store: Store, argv: list[str], daemon: "runs_daemon.Daemon | None" = None,
                   benchmark_dir: Path | None = None) -> int:
    """``runs.py run-issues --backfill [--since D] [--dry-run]``: Run issues for whole-set jobs that ended
    before the daemon opened them (#164). One line per job; a second run creates 0."""

    from junkroan.runs import run_issue as run_issue_mod

    parser = argparse.ArgumentParser(prog="runs.py run-issues", add_help=False)
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--since", default="2026-09-26")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.backfill:
        print("run-issues: only --backfill is supported", file=sys.stderr)
        return 2
    if daemon is None:
        daemon = runs_daemon.Daemon(store, snapshots=False, archive=False, log=lambda m: print(m, file=sys.stderr))
    created = 0
    if benchmark_dir is not None:
        daemon.benchmark_dir = benchmark_dir
    for job in store.jobs():
        if (run_issue_mod.is_whole_set_job(job) is None or job.run_issue is not None or not job.end_ts
                or job.end_ts[:10] < args.since or not job.run_dir):
            continue
        if run_issue_mod.resolve_run_dir(job.run_dir, benchmark_dir) is None:
            continue
        if args.dry_run:
            try:
                title, _ = daemon.run_issue_text(job)
            except Exception as exc:
                print(f"{job.id}  (cannot build: {exc!r})")
                continue
            print(f"{job.id}  {title}  would create")
            created += 1
            continue
        number = daemon.backfill_run_issue(job)
        title = store.get(job.id).run_issue_title or ""
        print(f"{job.id}  {title}  " + (f"#{number}" if number else "not created"))
        created += 1 if number else 0
    print(f"run-issues: {'would create' if args.dry_run else 'created'} {created}")
    return 0


def _forward_moved(store: Store, verb: str, past: str, job, extra: list[str]) -> int:
    """``cancel`` / ``stop`` of a moved row (#655): the same command on the target host's copy, never a local kill.

    One remote call (``runs_hosts.run_on_host``, faked in tests) in the host's ``daemon_repo_path`` with
    ``$env:JUNKROAN_HOST`` set. Any failure -> one line naming the host, exit 2, the PC row untouched.
    """

    host, _, new_id = job.moved_to.partition(":")
    try:
        host_cfg = runs_hosts.load_hosts_config()[host]
        parts = ["python", "scripts\\runs.py", verb, new_id, *extra]
        script = (f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; "
                  f"cd '{runs_hosts.daemon_repo_path(host_cfg)}'; & " + " ".join(p if p in (verb, new_id) else runs_hosts.quote_ps_arg(p) for p in parts))
        result = runs_hosts.run_on_host(host_cfg, script)
        out = (getattr(result, "stdout", "") or "").strip()
        err = (getattr(result, "stderr", "") or "").strip()
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(err or out or f"exit {getattr(result, 'returncode', '?')}")
    except Exception as exc:
        print(f"{verb}: {host} failed for {new_id}: {exc}", file=sys.stderr)
        return 2
    store.note_moved(job.id, f"{past} on {host} as {new_id}")
    print(f"{job.id} -> {job.moved_to}: {out or past}")
    return 0


def cmd_cancel(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py cancel", add_help=False)
    parser.add_argument("job_id")
    parser.add_argument("--reason", default=None)
    parser.add_argument("--local", action="store_true", help="this host's own store (the PC daemon runs it over ssh, #686)")
    args = parser.parse_args(argv)

    try:
        found = store.get(args.job_id)
    except JobNotFound:
        found = None
    if found is not None and found.moved_to:
        return _forward_moved(store, "cancel", "cancelled", found, ["--reason", args.reason] if args.reason else [])

    try:
        job = store.cancel(args.job_id, reason=args.reason)
    except JobNotFound:
        print(f"cancel: no such job {args.job_id!r}", file=sys.stderr)
        return 1
    except IllegalTransition as exc:
        try:
            state = store.get(args.job_id).state
        except JobNotFound:
            state = None
        if state == "running":
            print(f"cancel: job {args.job_id} is running; use 'runs.py stop {args.job_id}' to kill its tree and end it", file=sys.stderr)
        else:
            print(f"cancel: {exc} (only a queued job can be cancelled)", file=sys.stderr)
        return 1
    print(f"{job.id} -> {job.state}")
    return 0


def cmd_requeue(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py requeue", add_help=False)
    parser.add_argument("job_id")
    parser.add_argument("--reason", default=None)
    args = parser.parse_args(argv)

    try:
        job = store.requeue(args.job_id, reason=args.reason)
    except JobNotFound:
        print(f"requeue: no such job {args.job_id!r}", file=sys.stderr)
        return 1
    except IllegalTransition as exc:
        print(f"requeue: {exc} (only a stopped or failed job can be requeued)", file=sys.stderr)
        return 1
    print(f"{job.id} -> {job.state}")
    return 0


# -- stop ---------------------------------------------------------------------------------------

def taskkill_tree(pid: int) -> bool:
    """Kill `pid` and its whole tree (`taskkill /PID <pid> /T /F`). A pid already gone counts as
    done. Replaced by tests (`TREE_KILLER`)."""

    if sys.platform != "win32":
        import signal as _signal
        try:
            os.killpg(os.getpgid(pid), _signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return True
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        return True
    if "not found" in (result.stderr or result.stdout or "").lower():
        return True
    # taskkill can exit non-zero after the tree is dead (#412): the judge is the pid itself.
    return _pid_gone(pid)


def _pid_gone(pid: int, *, wait: float = 5.0) -> bool:
    """True when `pid` no longer exists, polled for up to `wait` seconds."""

    alive = runs_daemon.QueueBackend().pid_alive
    deadline = time.monotonic() + wait
    while True:
        if not alive(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


#: the one injectable killer of `stop` / `mode H off`.
TREE_KILLER = taskkill_tree


def _default_who() -> str:
    return os.environ.get("JUNKROAN_AGENT") or os.environ.get("USERNAME") or "hand"


def _stop_job(store: Store, job, who: str, reason: str | None = None) -> str | None:
    """Kill a running job's tree and store it as `stopped`, reason `stopped by <who>`. Returns an error
    line, or None on success. The job is ended only after the kill did not fail."""

    return runs_stopper.stop_job(store, job, who, TREE_KILLER, reason=reason)


def cmd_stop(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py stop", add_help=False)
    parser.add_argument("job_id")
    parser.add_argument("--who", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--local", action="store_true", help="this host's own store (the PC daemon runs it over ssh, #686)")
    args = parser.parse_args(argv)
    who = args.who or _default_who()

    try:
        job = store.get(args.job_id)
    except JobNotFound:
        print(f"stop: no such job {args.job_id!r}", file=sys.stderr)
        return 1
    if job.moved_to:
        return _forward_moved(store, "stop", "stopped", job, ["--who", who])
    if job.state != "running":
        print(f"stop: job {job.id} is {job.state}, not running", file=sys.stderr)
        return 1
    local = slot_budget.current_host()
    if job.host != local:
        print(f"stop: job {job.id} runs on host {job.host!r}, this is {local!r}; remote stop is not supported", file=sys.stderr)
        return 2
    err = _stop_job(store, job, who, args.reason)
    if err:
        print(err, file=sys.stderr)
        return 1
    print(f"{job.id} -> stopped ({args.reason or 'stopped by ' + who})")
    return 0


# -- import-queue -------------------------------------------------------------------------------

def _pending_queue_lines(queue_path: Path) -> list[str]:
    """Pending (not `done`, not blank, not `#` comment) lines of a `run_queue.py`-format queue file."""

    if not queue_path.is_file():
        return []
    out = []
    for raw in queue_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("done "):
            continue
        out.append(line)
    return out


def _import_tag(pin: str | None, cmd: str, existing: list[str]) -> str:
    return run_name.import_name(cmd, existing)


def cmd_import_queue(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py import-queue", add_help=False)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--host", default="pc", choices=HOSTS)
    parser.add_argument("--priority", default="P2", choices=PRIORITIES)
    args = parser.parse_args(argv)

    pending = _pending_queue_lines(Path(args.queue))
    already = {(j.pin, j.cmd) for j in store.jobs() if j.submitter == "import-queue"}

    imported = []
    for line in pending:
        pin, cmd = split_pin(line)
        if (pin, cmd) in already:
            continue
        auto = runs_daemon.declared_workers(cmd) == "auto"
        job = store.submit(
            host=args.host, priority=args.priority, tag=_import_tag(pin, cmd, [j.tag for j in store.jobs()]), cmd=cmd,
            submitter="import-queue", pin=pin, resumable=False,
            workers=runs_daemon.parse_workers(cmd),  # `--workers N` on the queue line, else 1
            workers_auto=auto,  # `--workers auto` on the line (#570)
        )
        already.add((pin, cmd))
        imported.append(job)

    for job in imported:
        print(f"{job.id}  {('@' + job.pin + ' ') if job.pin else ''}{job.cmd}")
    print(f"imported {len(imported)} of {len(pending)} pending line(s)")
    return 0


# -- mode (#41) ---------------------------------------------------------------------------------

def _mode_off_remote(host: str, who: str) -> int:
    """`mode <host> off` for ANOTHER host: run the stop ON that host over ssh (#73).

    That host's own job store holds its running jobs, this machine's never does. One
    :func:`run_on_host` call runs ``mode <host> off --local`` in the host's daemon checkout; on success
    its stdout is echoed and the mode recorded here, on any failure one stderr line and nothing recorded.
    """

    try:
        host_cfg = runs_hosts.load_hosts_config()[host]
        parts = ["python", "scripts\\runs.py", "mode", host, "off", "--local", "--who", who]
        line = " ".join(runs_hosts.quote_ps_arg(part) for part in parts)
        script = (f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; "
                  f"cd {runs_hosts.quote_ps_arg(runs_hosts.daemon_repo_path(host_cfg))}; & {line}")
        result = runs_hosts.run_on_host(host_cfg, script)
    except Exception as exc:
        print(f"mode: {host} unreachable: {exc!r}", file=sys.stderr)
        return 1
    if getattr(result, "returncode", 1) != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
        print(f"mode: {host} unreachable: {detail or 'non-zero exit'}", file=sys.stderr)
        return 1
    for out_line in (getattr(result, "stdout", "") or "").splitlines():
        print(out_line)
    runs_hosts.record_mode(host, "off")
    return 0


def cmd_fillers(store: Store, argv: list[str]) -> int:
    """`fillers <host> on|off` writes `<host>.fillers` in config/hosts.json (#751); `--current` reads."""

    parser = argparse.ArgumentParser(prog="runs.py fillers", add_help=False)
    parser.add_argument("host", nargs="?")
    parser.add_argument("state", nargs="?", choices=["on", "off"])
    parser.add_argument("--current", action="store_true", help="print the switch and change nothing")
    parser.add_argument("--week", help="the week's Monday as YYYYmmdd: print the three filler numbers (#752)")
    parser.add_argument("--root", default=None, help=argparse.SUPPRESS)  # where artifacts/benchmark lives (tests)
    args = parser.parse_args(argv)

    if args.week:
        if not args.host:
            print("fillers: --week needs <host>", file=sys.stderr)
            return 2
        monday = datetime.strptime(args.week, "%Y%m%d").date()
        folder = weekly_cut.find_week_folder(Path(args.root) if args.root else MAIN_ROOT, monday)
        lines, rc = filler_week.week_report(store.jobs(host=args.host), args.host, monday,
                                            folder / "rows" if folder else None)
        for line in lines:
            print(line)
        return rc

    try:
        config = runs_hosts.load_hosts_config()
        if args.current:
            names = [args.host] if args.host else list(config)
            for name in names:
                entry = config.get(name)
                if entry is None:
                    raise runs_hosts.HostModeError(f"unknown host {name!r} (known: {sorted(config)})")
                print(f"{name} fillers {'on' if runs_hosts.effective_fillers(name, config) else 'off'}")
            return 0
        if not args.host or not args.state:
            print("fillers: needs <host> on|off (or --current)", file=sys.stderr)
            return 2
        runs_hosts.set_fillers(args.host, args.state == "on")
    except runs_hosts.HostModeError as exc:
        print(f"fillers: {exc}", file=sys.stderr)
        return 1
    print(f"{args.host} fillers {args.state}")
    return 0


def cmd_mode(store: Store, argv: list[str]) -> int:
    """Apply a host's named budget mode (`config/hosts.json`). No job store involved."""

    parser = argparse.ArgumentParser(prog="runs.py mode", add_help=False)
    parser.add_argument("host")
    parser.add_argument("mode", nargs="?")
    parser.add_argument("--current", action="store_true",
                        help="print the mode HOST is on (its budget file when run on HOST or with --local; on another host it reads that host's budget file over ssh, `HOST unreachable` and rc 1 when ssh fails; unknown when nothing matches) and change nothing")
    parser.add_argument("--who", default=None, help="name recorded in the reason of jobs stopped by mode off")
    parser.add_argument("--local", action="store_true",
                        help="write this host's budget here instead of over ssh -- for a command "
                             "running ON that host, whose entry in config/hosts.json carries an ssh "
                             "alias meant for OTHER machines (issue #364)")
    args = parser.parse_args(argv)

    if args.current:
        try:
            print(runs_hosts.current_mode(args.host, local=args.local))
        except runs_hosts.HostModeError as exc:
            print(f"mode: {exc}", file=sys.stderr)
            return 1
        return 0
    if not args.mode:
        print("mode: a mode name is required (or --current)", file=sys.stderr)
        return 2

    here = args.local or args.host == slot_budget.current_host()
    if args.mode == "off" and not here:
        return _mode_off_remote(args.host, args.who or _default_who())
    try:
        result = runs_hosts.apply_mode(args.host, args.mode, local=args.local)
        runs_hosts.record_mode(args.host, args.mode)
    except runs_hosts.HostModeError as exc:
        print(f"mode: {exc}", file=sys.stderr)
        return 1
    if args.mode in ("play", "normal") and here and args.host == "pc":
        try:  # #779: the machine mode, one file for every repo on this PC (never for the laptop, pause, off)
            from tools.agentops import machine_mode
            machine_mode.set_mode(args.mode)
        except Exception as exc:  # noqa: BLE001
            print(f"mode: machine mode not written: {exc}", file=sys.stderr)
            return 1
    rc = 0
    print(f"{args.host}: mode '{args.mode}' applied (pob_priority={result['priority']}, transport={result['transport']})")
    if args.mode == "off":
        who = args.who or _default_who()
        stopped = 0
        for job in store.jobs(state="running", host=args.host):
            err = _stop_job(store, job, who)
            if err:
                print(err, file=sys.stderr)
                rc = 1
            else:
                stopped += 1
                print(f"{job.id} -> stopped (stopped by {who})")
        print(f"{args.host}: stopped {stopped} running job(s)")
        return rc
    return 0


# -- reserve (#41) ------------------------------------------------------------------------------

def _reserve_owner(args: argparse.Namespace, *, release: bool) -> int:
    """The owner record (#621): in this host's modes.json, or on another host over ssh via the same
    command with ``--local`` (as `mode` does), so that host's own daemon reads it."""

    host = args.host
    if not release:
        missing = [n for n, v in (("--host", host), ("--slots", args.slots), ("--for", args.for_)) if v is None]
        if missing:
            print(f"runs reserve --who owner needs {', '.join(missing)}", file=sys.stderr)
            return 2
    if not args.local and host != slot_budget.current_host():
        try:
            host_cfg = runs_hosts.load_hosts_config()[host]
            if not host_cfg.get("ssh"):
                raise runs_hosts.HostModeError(f"{host} has no ssh alias")
            parts = ["python", "scripts\\runs.py", "reserve", "--host", host, "--who", "owner", "--local"]
            if release:
                parts.append("--release")
            else:
                parts += ["--slots", str(args.slots), "--for", args.for_]
            line = " ".join(runs_hosts.quote_ps_arg(part) for part in parts)
            script = (f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; "
                      f"cd {runs_hosts.quote_ps_arg(runs_hosts.daemon_repo_path(host_cfg))}; & {line}")
            result = runs_hosts.run_on_host(host_cfg, script)
        except Exception as exc:
            print(f"reserve: {host} unreachable: {exc!r}", file=sys.stderr)
            return 1
        if getattr(result, "returncode", 1) != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            print(f"reserve: {host} unreachable: {detail or 'non-zero exit'}", file=sys.stderr)
            return 1
        for out_line in (getattr(result, "stdout", "") or "").splitlines():
            print(out_line)
        return 0
    try:
        if release:
            runs_hosts.release_owner_reservation(host)
            print(f"released the owner's reservation on {host}")
            return 0
        minutes = runs_hosts.parse_duration(args.for_) / 60.0
        until = runs_hosts.set_owner_reservation(host, args.slots, minutes)
    except runs_hosts.HostModeError as exc:
        print(f"reserve: {exc}", file=sys.stderr)
        return 1
    print(f"reserved {args.slots} slots on {host} until {until:%H:%M} (for {human_duration(minutes * 60)})")
    return 0


def cmd_reserve(store: Store, argv: list[str]) -> int:
    """Reserve, or release, PoB slots ahead of a run. Only takes effect when a host's mode has
    `strict_reserve` on (`var/machine_budget.json`'s own `strict_reserve` flag) -- without it the
    `others` share is not being held back from the queue in the first place, so a reservation on
    top of it would have nothing to add slots to."""

    parser = argparse.ArgumentParser(prog="runs.py reserve", add_help=False)
    parser.add_argument("--host")
    parser.add_argument("--slots", type=int)
    parser.add_argument("--for", dest="for_", help="duration like 45m or 2h")
    parser.add_argument("--issue", type=int, default=None)
    parser.add_argument("--release", type=int, nargs="?", const=-1, default=None, metavar="ID",
                        help="release an existing reservation by id; with no id and --host, the owner record")
    parser.add_argument("--who", default=None, help="`owner`: the owner record in modes.json (#621) instead of var/reservations.json")
    parser.add_argument("--local", action="store_true",
                        help="write this host's own modes.json here, never over ssh (a command running ON that host)")
    args = parser.parse_args(argv)

    owner_release = args.release == -1
    if owner_release and not args.host:
        print("runs reserve --release needs an id, or --host for the owner record", file=sys.stderr)
        return 2
    if args.who == "owner" or owner_release:
        return _reserve_owner(args, release=owner_release)
    if args.release is not None:
        found = runs_hosts.release_reservation(args.release)
        print(f"released reservation {args.release}" if found else f"no such reservation: {args.release}")
        return 0 if found else 1
    missing = [name for name, value in (("--host", args.host), ("--slots", args.slots), ("--for", args.for_)) if value is None]
    if missing:
        print(f"runs reserve needs {', '.join(missing)} (or --release <id>)", file=sys.stderr)
        return 2
    try:
        entry = runs_hosts.reserve_slots(args.host, args.slots, args.for_, args.issue)
    except runs_hosts.HostModeError as exc:
        print(f"reserve: {exc}", file=sys.stderr)
        return 1
    print(f"reservation {entry['id']}: {entry['slots']} slot(s) on {entry['host']} until {entry['expires']}")
    return 0


# -- owner presets (#958) -----------------------------------------------------------------------

OWNER_ACTIONS = ("film", "sleep", "back", "status", "close-preview")


def cmd_owner(store: Store, argv: list[str]) -> int:
    """`owner <host> film --for D | sleep [--for D] | back | status | close-preview`: the owner's presets on a host (#958).
    From another host it is exactly one ssh command carrying `--local` (as `reserve --who owner` does);
    the work happens on the host, whose own daemon gives way and, at the end of `sleep`, closes the browsers."""

    from junkroan.runs import owner_commands

    parser = argparse.ArgumentParser(prog="runs.py owner", add_help=False)
    parser.add_argument("host")
    parser.add_argument("action", choices=OWNER_ACTIONS)
    parser.add_argument("--for", dest="for_", default=None, help="duration like 90m or 2h")
    parser.add_argument("--close", default=None, help="comma-separated process names that replace the preset's `close` list")
    parser.add_argument("--local", action="store_true", help="work on this host's own files (a command running ON that host)")
    args = parser.parse_args(argv)

    host = args.host
    try:
        config = runs_hosts.load_hosts_config()
    except Exception as exc:
        print(f"owner: config/hosts.json unreadable: {exc!r}", file=sys.stderr)
        return 1
    if not owner_commands.host_has_presets(config, host):
        print(f"owner: {host} has no owner presets in config/hosts.json; the presets are the laptop's", file=sys.stderr)
        return 1
    if args.action == "film" and not args.for_:
        print("owner: film needs --for <duration>", file=sys.stderr)
        return 2

    if not args.local and host != slot_budget.current_host():
        host_cfg = config[host]
        try:
            if not host_cfg.get("ssh"):
                raise runs_hosts.HostModeError(f"{host} has no ssh alias")
            parts = ["python", "scripts\\runs.py", "owner", host, args.action, "--local"]
            if args.for_:
                parts += ["--for", args.for_]
            if args.close:
                parts += ["--close", args.close]
            line = " ".join(runs_hosts.quote_ps_arg(part) for part in parts)
            script = (f"$env:JUNKROAN_HOST = {runs_hosts.quote_ps_arg(host)}; "
                      f"cd {runs_hosts.quote_ps_arg(runs_hosts.daemon_repo_path(host_cfg))}; & {line}")
            result = runs_hosts.run_on_host(host_cfg, script)
        except Exception as exc:
            print(f"owner: the {host} did not take the command (unreachable: {exc!r})", file=sys.stderr)
            return 1
        out = (getattr(result, "stdout", "") or "")
        if getattr(result, "returncode", 1) != 0:
            detail = (getattr(result, "stderr", "") or out or "").strip()
            print(f"owner: the {host} did not take the command: {detail or 'non-zero exit'}", file=sys.stderr)
            return 1
        for out_line in out.splitlines():
            print(out_line)
        return 0

    def running_jobs() -> dict[str, int]:
        return {job.id: job.workers for job in store.jobs(state="running", host=host)}

    try:
        if args.action == "back":
            lines = owner_commands.end_preset(host)
        elif args.action == "status":
            lines = owner_commands.status_lines(host)
        elif args.action == "close-preview":
            lines, readable = owner_commands.close_preview_lines(host, config)
            if not readable:
                print(f"owner: {lines[0]}", file=sys.stderr)
                return 1
        else:
            close = [n.strip() for n in args.close.split(",") if n.strip()] if args.close else None
            lines = owner_commands.start_preset(
                host, args.action, config=config, duration_text=args.for_, close=close, jobs_reader=running_jobs)
    except runs_hosts.HostModeError as exc:
        print(f"owner: {exc}", file=sys.stderr)
        return 1
    for out_line in lines:
        print(out_line)
    return 0


# -- daemon (#48) / anomaly guard (#57) ----------------------------------------------------------

def _laptop_daemon_status(box: dict[str, Any], laptop_cfg: Mapping[str, Any]) -> dict[str, Any] | None:
    """#1183: the laptop daemon's status, read through the PC daemon's snapshot reader. Any failure, or no
    daemon yet, is `None` -- never "dead" (the guard reads `None` as not dead)."""

    daemon = box.get("daemon")
    if daemon is None:
        return None
    try:
        return daemon._read_remote_snapshot(dict(laptop_cfg), "laptop").daemon_status
    except Exception:
        return None


def _laptop_fixed_jobs(box: dict[str, Any], laptop_cfg: Mapping[str, Any]) -> list[str]:
    """#1183: the ids of the laptop's queued `--host laptop` jobs (they stay there and are named in the event)."""

    daemon = box.get("daemon")
    if daemon is None:
        return []
    try:
        snapshot = daemon._read_remote_snapshot(dict(laptop_cfg), "laptop")
    except Exception:
        return []
    return [job.id for job in snapshot.jobs if job.state == "queued" and job.host_fixed]


def _on_laptop_daemon_dead(box: dict[str, Any], host_name: str) -> None:
    """#1183: the PC daemon takes the dead host's movable queued jobs (`reclaim_from_dead_host`) and logs
    what it did in one line. No issue, comment or keymaster session."""

    daemon = box.get("daemon")
    if daemon is None:
        return
    result = runs_rebalance.reclaim_from_dead_host(daemon, host_name)
    failed = ", ".join(f"{job_id} ({reason})" for job_id, reason in result.failed) or "none"
    daemon.log(f"host_daemon_dead:{host_name}: reclaim moved {', '.join(result.moved) or 'none'}; "
               f"stayed fixed {', '.join(result.stayed_fixed) or 'none'}; failed {failed}")


def _build_anomaly_guard(host: str, store: Store | None = None,
                         daemon_box: dict[str, Any] | None = None) -> runs_anomalies.AnomalyGuard:
    """The real `AnomalyGuard` `daemon` builds: a BOM-aware budget check always, and a laptop probe
    only where an SSH route to the laptop actually exists -- this host's own `config/hosts.json`
    entry has no `ssh` value for itself, only the OTHER host's entry does (`config/hosts.json`:
    `pc.ssh` is null, `laptop.ssh` is `"laptop"`), so only the host that is NOT the laptop can probe
    it.

    #1183: the guard is built before the daemon that owns it, so the daemon reaches the guard's
    collaborators through `daemon_box["daemon"]`, which `cmd_daemon` sets right after it builds the
    daemon. On the PC (not the laptop) the guard reads the laptop daemon's status and queued fixed jobs
    through that daemon's snapshot reader, and reclaims the dead laptop's movable jobs on
    `host_daemon_dead`."""

    box: dict[str, Any] = daemon_box if daemon_box is not None else {}
    budget_checker = runs_anomalies.make_budget_checker()
    host_prober = None
    daemon_status_reader = None
    fixed_jobs_reader = None
    on_daemon_dead = None
    if host != "laptop":
        try:
            hosts_config = runs_hosts.load_hosts_config()
        except Exception:
            hosts_config = {}
        laptop_cfg = dict(hosts_config.get("laptop") or {})
        if laptop_cfg.get("ssh"):
            host_prober = runs_anomalies.make_host_prober(laptop_cfg)
        daemon_status_reader = lambda: _laptop_daemon_status(box, laptop_cfg)  # noqa: E731
        fixed_jobs_reader = lambda: _laptop_fixed_jobs(box, laptop_cfg)  # noqa: E731
        on_daemon_dead = lambda name: _on_laptop_daemon_dead(box, name)  # noqa: E731
    return runs_anomalies.AnomalyGuard(
        budget_checker=budget_checker, host_prober=host_prober,
        daemon_status_reader=daemon_status_reader, fixed_jobs_reader=fixed_jobs_reader,
        on_daemon_dead=on_daemon_dead,
        slot_lister=runs_anomalies.make_slot_lister(),
        reservation_lister=runs_anomalies.make_reservation_lister(host),
        issue_finder=runs_anomalies.make_issue_finder(),
        issue_commenter=runs_anomalies.make_issue_commenter(),
        host=host, start_keymasters=host != "laptop",
        # #862: the chain handler's label step is `relabel --issue N` itself (live jobs / closed issue refuse).
        issue_labeler=(lambda number: cmd_relabel(store, ["--issue", str(number)])) if store is not None else None,
    )


def cmd_anomaly_taken(store: Store, argv: list[str]) -> int:
    """Drop one anomaly from this checkout's queue (#467): the PC's daemon started its keymaster."""

    parser = argparse.ArgumentParser(prog="runs.py anomaly-taken", add_help=False)
    parser.add_argument("key")
    args = parser.parse_args(argv)
    taken = runs_anomalies.take_queued(args.key)
    print(f"anomaly {args.key} {'dropped from the queue' if taken else 'was not queued'}")
    return 0


def cmd_daemon(store: Store, argv: list[str]) -> int:
    """Start queued jobs while the host's queue share has room, and hand finished runs back.

    Meant to be launched detached and hidden (`scripts/launch_hidden.ps1`), like the queue runner it
    replaces. It ignores SIGINT for the same reason `run_queue.py` does: processes created through
    WMI share one console, and a console Ctrl+C there killed a runner, its benchmark and its workers
    at once (2026-09-18).
    """

    parser = argparse.ArgumentParser(prog="runs.py daemon", add_help=False)
    parser.add_argument("--host", default=None, help="this machine's name in config/hosts.json")
    parser.add_argument("--interval", type=float, default=runs_daemon.TICK_SECONDS)
    parser.add_argument("--ticks", type=int, default=None, help="stop after N ticks (tests, canaries)")
    parser.add_argument("--no-snapshot", action="store_true", help="run every job from the live checkout")
    parser.add_argument("--no-keymaster", action="store_true",
                        help="leave the anomaly guard off (issue #57): no on-demand keymaster session")
    parser.add_argument("--handback", default="local", choices=("local", "remote"),
                        help="'remote' (issue #118, the laptop: no gh) only stores the rendered "
                             "hand-back body on the job; another host's daemon posts it")
    parser.add_argument("--no-fillers", action="store_true",
                        help="issue #132: never submit a filler (the host then simply idles when nothing else can start)")
    parser.add_argument("--fillers", action="store_true",
                        help="#517: submit fillers (rule of #751); off by default (the owner's "
                             "word 2026-10-03); hosts.json '<host>.fillers: true' turns them on too")
    parser.add_argument("--ensure", action="store_true",
                        help="issue #353: start this host's daemon only when none is alive, then exit "
                             "(prints 'pid N' or 'alive pid N'); the Task Scheduler watchdog calls this")
    parser.add_argument("--no-self-restart", action="store_true",
                        help="issue #340: never restart at a boundary when the daemon's own code changes")
    args = parser.parse_args(argv)
    if args.ensure:
        from junkroan.runs import watchdog

        return watchdog.main(["--host", args.host] if args.host else [])

    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    host = args.host or slot_budget.current_host()

    # A replacement started by a daemon restarting itself (#340) waits for that daemon to exit first, so
    # the "already live" guard below finds it gone.
    replaced = self_restart.wait_for_predecessor(os.environ, runs_daemon.QueueBackend().pid_alive)
    if replaced is not None:
        print(f"runs daemon on host '{host}': replacing pid {replaced} (restart at boundary)", flush=True)

    status_path = runs_hosts.daemon_status_path(host)
    existing = runs_daemon.read_daemon_status(status_path)
    live, age = runs_daemon.status_liveness(
        existing, now=datetime.now(timezone.utc), pid_alive=runs_daemon.QueueBackend().pid_alive,
    )
    if live:
        age_text = human_duration(age) if age is not None else "an unknown time"
        print(f"runs daemon on host '{host}' is already live (pid {existing.get('pid')}, "
              f"last tick {age_text} ago); this one exits", flush=True)
        return 0

    daemon_box: dict[str, Any] = {}  # #1183: the guard's daemon collaborators read the daemon set below
    anomaly_guard = None if args.no_keymaster else _build_anomaly_guard(host, store, daemon_box)
    # Fillers (#751): the host's switch (`runs.py fillers <host> on|off`, or `--fillers` for this daemon only).
    filler_source = None if args.no_fillers else runs_fillers.FillerSwitch(
        enabled=runs_fillers.fillers_switch(host, flag=args.fillers))
    restart_watch = None
    respawn = None
    follow_main = None
    if not args.no_self_restart and args.ticks is None:
        try:
            restart_watch = self_restart.RestartWatch.from_repo(ROOT, log=runs_daemon._log)
            respawn = self_restart.respawn
            try:
                host_entry = runs_hosts.load_hosts_config().get(host) or {}
            except Exception:
                host_entry = {}
            follow_main = self_restart.FollowMain(
                ROOT, host_entry.get("daemon_repo_path"), self_restart.git_runner(ROOT), log=runs_daemon._log)
        except Exception as exc:
            print(f"self-restart off: git failed ({exc!r})", flush=True)
    daemon = runs_daemon.Daemon(store, host=host, snapshots=not args.no_snapshot, anomaly_guard=anomaly_guard,
                                revert_modes=runs_hosts.revert_expired_modes, handback=args.handback,
                                machine_hold=True,
                                fillers=filler_source,
                                restart_watch=restart_watch, respawn=respawn, follow_main=follow_main,
                                gate_artifacts=runs_gates.ROOT / "artifacts",
                                cut_repo=ROOT)  # #642; #750: the daemon takes the weekly cut from this checkout: keep the laptop holding the gate
    daemon_box["daemon"] = daemon
    budget = daemon.budget()
    print(f"runs daemon on host '{host}': queue share {budget.limit_for(slot_budget.ROLE_QUEUE)} "
          f"of {budget.total} slot(s) ({budget.period} {budget.window()}), tick {human_duration(args.interval)}, "
          + (f"self-restart on {restart_watch.start[:12]}" if restart_watch is not None else "self-restart off"),
          flush=True)
    return daemon.run(ticks=args.ticks, interval=args.interval, load_thread=True)  # #768


# -- watch (#48) --------------------------------------------------------------------------------

def cmd_watch(store: Store, argv: list[str]) -> int:
    """Block until the next line appears in `artifacts/runs/events.jsonl`, print it, exit."""

    parser = argparse.ArgumentParser(prog="runs.py watch", add_help=False)
    parser.add_argument("--events", default=None, help="override the events file (tests)")
    parser.add_argument("--timeout", type=float, default=None, help="give up after N seconds (exit 3)")
    parser.add_argument("--poll", type=float, default=0.5)
    args = parser.parse_args(argv)

    line = runs_daemon.watch_next_event(
        Path(args.events) if args.events else None, timeout=args.timeout, poll=args.poll,
    )
    if line is None:
        return 3
    print(line)
    return 0


# -- weekly / recut (#750) ----------------------------------------------------------------------

WEEKLY_CORE_LINE = ["python", "scripts/benchmark.py", *weekly_cut.WEEKLY_ARGV]
WEEKLY_NOTE = "laptop, comparable week to week: the same PoB calls as on the PC at one pin (#978, #1165)"
WEEKLY_FOLDER_NOTE = "PC only, comparable week to week (#594)"  # the folder line stays on the PC (#1165)


def _now() -> datetime:
    return datetime.now()


def _fetch_origin(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "fetch", "--quiet", "origin"], capture_output=True, text=True)


def _any_filler_switch() -> bool:
    """True when some host's filler switch (hosts.json ``<host>.fillers``) is on (#517)."""

    return any(runs_fillers.fillers_switch(h, flag=False)() for h in HOSTS if h != "any")


def commit_override_argv(monday: date, old_cut: str, new_cut: str) -> list[str]:
    msg = f"weekly cut: week {monday:%Y%m%d} re-cut {old_cut[:7]} -> {new_cut[:7]} (#750)"
    return [sys.executable, "-m", "tools.agentops", "commit", "-m", msg, "--detach", weekly_cut.OVERRIDE_PATH]


def _run_commit(argv: list[str]) -> int:
    return subprocess.run(argv, cwd=str(ROOT)).returncode


def _week_tag(monday: date) -> str:
    return f"week-{monday:%Y%m%d}"


def _folder_cut(folder: Path) -> str:
    return json.loads((folder / "args.json").read_text(encoding="utf-8")).get("commit", "")


def _submit_weekly(store: Store, monday: date, folder: Path | None, cut: str | None, again: bool = False) -> int:
    """The Monday line: with a folder = `--resume` of it pinned at the cut; without = today's line, pinned at main."""

    # #1165: the no-folder line runs on the laptop (host fixed); the folder line stays on the PC, where the folder lives
    flags = ["--host", "laptop" if folder is None else "pc", "--priority", "P2", "--no-issue",
             *(["--again"] if again else [])]
    hint = "`runs.py weekly --again`"  # #928: the refusal under `weekly` names the weekly form
    note = f"weekly core run {_week_tag(monday)}: {WEEKLY_NOTE if folder is None else WEEKLY_FOLDER_NOTE}"
    if folder is None:
        return cmd_submit(store, [*flags, "--note", note, "--", *WEEKLY_CORE_LINE], again_hint=hint)
    rel = folder.relative_to(ROOT).as_posix() if folder.is_relative_to(ROOT) else str(folder)
    # `--set core14` stays on the line so submit sees a core run (--no-issue needs it); resume checks it against args.json
    cmd = ["python", "scripts/benchmark.py", "--set", "core14", "--resume", rel, "--workers", "auto"]
    return cmd_submit(store, [*flags, "--pin", cut, "--note", f"{note}; resume at cut {cut[:7]}", "--", *cmd], again_hint=hint)


def cmd_weekly(store: Store, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="runs.py weekly", add_help=False)
    parser.add_argument("--again", action="store_true", help="run it even when the tree is identical to the last gate (#928)")
    again = parser.parse_args(argv).again
    monday = weekly_cut.monday_of(_now())
    if not _any_filler_switch():
        return _submit_weekly(store, monday, None, None, again)
    folder = weekly_cut.find_week_folder(ROOT, monday)
    if folder is None:
        _fetch_origin(ROOT)
        cut = weekly_cut.cut_for_week(ROOT, monday)
        folder = weekly_cut.open_week_folder(ROOT, monday, cut)
    return _submit_weekly(store, monday, folder, _folder_cut(folder), again)


def _quiet(fn, *a) -> int:
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        return fn(*a)


def cmd_recut(store: Store, argv: list[str]) -> int:
    argparse.ArgumentParser(prog="runs.py recut", add_help=False).parse_args(argv)
    monday = weekly_cut.monday_of(_now())
    tag = _week_tag(monday)
    _fetch_origin(ROOT)
    res = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "origin/main"], capture_output=True, text=True)
    new_cut = res.stdout.strip()
    if res.returncode != 0 or not new_cut:
        print(f"recut: no origin/main: {res.stderr.strip()}", file=sys.stderr)
        return 1
    folder = weekly_cut.find_week_folder(ROOT, monday)
    old_cut = _folder_cut(folder) if folder is not None else weekly_cut.cut_for_week(ROOT, monday)

    weekly_cut.record_override(ROOT, monday, new_cut)
    rc = _run_commit(commit_override_argv(monday, old_cut, new_cut))
    if rc != 0:
        print(f"recut: committing {weekly_cut.OVERRIDE_PATH} failed (rc {rc}); nothing cancelled, nothing renamed", file=sys.stderr)
        return 1

    resubmit = False
    for job in store.jobs():
        if job.state not in ("queued", "running"):
            continue
        monday_line = run_name.is_core_command(job.argv or job.cmd) and tag in (job.note or "")
        if not (job.is_filler or monday_line):
            continue
        reason = f"recut of {tag}: {old_cut[:7]} -> {new_cut[:7]}"
        step = cmd_stop if job.state == "running" else cmd_cancel
        if _quiet(step, store, [job.id, "--reason", reason]) != 0:
            print(f"recut: could not end {job.id} ({job.state})", file=sys.stderr)
        if monday_line:
            resubmit = True

    dropped = 0
    if folder is not None:
        dropped = len(list((folder / "rows").glob("*.json")))
        weekly_cut.drop_week_folder(folder, old_cut)
    new_folder = weekly_cut.open_week_folder(ROOT, monday, new_cut)
    if resubmit:
        _quiet(_submit_weekly, store, monday, *((new_folder, new_cut) if _any_filler_switch() else (None, None)))
    print(f"recut {tag}: old cut {old_cut[:7]}, new cut {new_cut[:7]}, builds dropped {dropped}")
    return 0


# -- dispatch -----------------------------------------------------------------------------------

SUBCOMMANDS = {
    "weekly": cmd_weekly,
    "recut": cmd_recut,
    "submit": cmd_submit,
    "status": cmd_status,
    "relabel": cmd_relabel,
    "cancel": cmd_cancel,
    "requeue": cmd_requeue,
    "stop": cmd_stop,
    "import-queue": cmd_import_queue,
    "mode": cmd_mode,
    "fillers": cmd_fillers,
    "reserve": cmd_reserve,
    "owner": cmd_owner,
    "mark-run-issue": cmd_mark_run_issue,
    "run-issues": cmd_run_issues,
    "daemon": cmd_daemon,
    "watch": cmd_watch,
    "mark-posted": cmd_mark_posted,
    "anomaly-taken": cmd_anomaly_taken,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="runs.py", add_help=True)
    parser.add_argument("subcommand", choices=sorted(SUBCOMMANDS))
    parser.add_argument("--store", default=None, help="override the job store path (tests)")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    store = _store(args)
    return SUBCOMMANDS[args.subcommand](store, args.rest)


if __name__ == "__main__":
    raise SystemExit(main())
