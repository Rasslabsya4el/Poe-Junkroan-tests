"""Move a long-waiting queued job to the other host once (issue #403, unit 4).

``Rebalancer.step`` is called once per PC daemon tick. A queued NON-filler job of this host that has
waited ``MOVE_AFTER_SECONDS`` since its submit, whose need fits another host's ``room_now`` and whose
pin that host's daemon checkout holds, is written into that host's store (same pin, tag, issue,
priority, ``--after`` list, command) and ended here with a ``moved`` op. The copy carries
``moved_from``, and a job that carries it is never a candidate, so a job moves once and never back.

#484: a job whose need exceeds the other host's room but whose command carries ``--workers N`` (N > room)
moves with ``--workers`` cut to the room (never below 2). A job that others wait for (``--after``) moves
together with its whole chain of queued followers; the chain runs one job after another, so the room
must fit the largest need, not the sum.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from junkroan.runs import gates as runs_gates
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import pin_ref as runs_pin_ref
from junkroan.runs import placement
from junkroan.runs import spike as spike_mod
from junkroan.runs import store as store_mod
from junkroan.runs.store import Job

MOVE_AFTER_SECONDS = 15 * 60
# #518: no move to a host whose last remote read failed within this long, unless a read succeeded since
UNREACHABLE_MOVE_HOLD_SECONDS = 600


def _runs_pytest(cmd) -> bool:
    """True when the command (a string or argv, also inside a wrapper like `cmd /c`) invokes pytest."""

    text = cmd if isinstance(cmd, str) else " ".join(str(a) for a in cmd)
    return re.search(r"(?<![\w.-])(?:py\.test|pytest)(?![\w-])", text) is not None


def has_pin_on_host(host_cfg: Mapping[str, Any], host: str, pin: str) -> bool:
    """``git -C <daemon_repo_path> cat-file -e <pin>^{commit}`` on ``host``, over ssh."""

    repo = runs_hosts.daemon_repo_path(host_cfg)
    script = f"git -C {runs_hosts.quote_ps_arg(repo)} cat-file -e {runs_hosts.quote_ps_arg(pin + '^{commit}')}; exit $LASTEXITCODE"
    try:
        result = runs_hosts.run_on_host(dict(host_cfg), script)
    except Exception:
        return False
    return getattr(result, "returncode", 1) == 0


def head_on_host(host_cfg: Mapping[str, Any]) -> str:
    """Short HEAD of the host's daemon checkout, over ssh; ``unknown`` when it cannot be read."""

    script = f"git -C {runs_hosts.quote_ps_arg(runs_hosts.daemon_repo_path(host_cfg))} rev-parse --short HEAD; exit $LASTEXITCODE"
    try:
        result = runs_hosts.run_on_host(dict(host_cfg), script)
        lines = (getattr(result, "stdout", "") or "").strip().splitlines()
        if getattr(result, "returncode", 1) == 0 and lines:
            return lines[-1].strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def _first_line(text: Any) -> str:
    lines = str(text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def submit_moved_on_host(host_cfg: Mapping[str, Any], host: str, job: Job, origin: str) -> str | None:
    """Write ``job`` into ``host``'s own store (its daemon checkout) over ssh; its new job id.

    Raises on a failed write (the exception's first line is what the daemon log shows); None when the
    write ran but printed no id.
    """

    payload = {
        "host": host, "priority": job.priority, "tag": job.tag, "cmd": job.cmd, "issue": job.issue,
        "submitter": job.submitter, "pin": job.pin, "resumable": job.resumable, "workers": job.workers,
        "after": list(job.after), "job_class": job.job_class, "moved_from": origin,
    }
    if getattr(job, "rc_is_reading", False):  # a reading job stays one on the new host (#501); only when set, so an older store still loads it
        payload["rc_is_reading"] = True
    if getattr(job, "workers_auto", False):  # an auto job stays auto on the new host (#570)
        payload["workers_auto"] = True
    if getattr(job, "no_label", False):  # the moved copy hands back without the label too (#515)
        payload["no_label"] = True
    if getattr(job, "host_fixed", False):  # an inherited follower keeps its host and the reason (#648)
        payload["host_fixed"] = True
    if getattr(job, "host_reason", None):
        payload["host_reason"] = job.host_reason
    if getattr(job, "submit_commit", None):  # the moved copy was still submitted at that commit (#861)
        payload["submit_commit"] = job.submit_commit
    if job.argv:  # an argv job (#203) moves as one, never falling back to the shell form
        payload["argv"] = list(job.argv)
    blob = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    code = ("import base64,json,sys; from junkroan.runs.store import Store; "
            "d=json.loads(base64.b64decode(sys.argv[1])); print(Store().submit(**d).id)")
    result = runs_hosts.write_over_ssh(
        dict(host_cfg), f"python -c \"{code}\" {runs_hosts.quote_ps_arg(blob)}",
        repo_path=runs_hosts.daemon_repo_path(host_cfg), host=host, pythonpath="src")
    if getattr(result, "returncode", 1) != 0:
        raise RuntimeError(_first_line(getattr(result, "stderr", "")) or f"exit {getattr(result, 'returncode', 1)}")
    lines = (getattr(result, "stdout", "") or "").strip().splitlines()
    return lines[-1].strip() if lines else None


def remote_cancel_queued(host_cfg: Mapping[str, Any], job_id: str) -> bool:
    """Cancel the queued job ``job_id`` in the host's own store over ssh (#1183); True when it ended cancelled.

    The same ``runs.py cancel <job> --local`` the daemon runs on the other host (#686), in its daemon checkout
    (:func:`submit_moved_on_host`'s seam). The store refuses a job that is not queued (a running one is ``stop``'s):
    False, with the reason on stderr. Never raises: an ssh failure is False too.
    """

    q = runs_hosts.quote_ps_arg
    script = " ".join(q(p) for p in ("python", "scripts/runs.py", "cancel", job_id, "--local"))
    try:
        result = runs_hosts.write_over_ssh(dict(host_cfg), f"& {script}",
                                           repo_path=runs_hosts.daemon_repo_path(host_cfg))
    except Exception as exc:
        print(f"rebalance: cancel {job_id} over ssh failed ({_first_line(exc) or type(exc).__name__})", file=sys.stderr)
        return False
    if getattr(result, "returncode", 1) != 0:
        reason = _first_line(getattr(result, "stderr", "")) or f"exit {getattr(result, 'returncode', 1)}"
        print(f"rebalance: cancel {job_id} not done on the laptop: {reason}", file=sys.stderr)
        return False
    return True


_WORKERS_RE = re.compile(r"(--workers(?:\s+|=))(\d+)")


def _cmd_workers(job: Job) -> int | None:
    """The N of ``--workers N`` in the job's command (or argv); None when it carries none."""

    m = _WORKERS_RE.search(job.cmd if isinstance(job.cmd, str) else " ".join(str(a) for a in job.cmd))
    if m:
        return int(m.group(2))
    argv = [str(a) for a in (job.argv or ())]
    for i, a in enumerate(argv):
        if a == "--workers" and i + 1 < len(argv) and argv[i + 1].isdigit():
            return int(argv[i + 1])
        if a.startswith("--workers=") and a[10:].isdigit():
            return int(a[10:])
    return None


def _cmd_tokens(job: Job) -> list[str]:
    if job.argv:
        return [str(a) for a in job.argv]
    if isinstance(job.cmd, str):
        try:
            toks = shlex.split(job.cmd, posix=False)
        except ValueError:
            toks = job.cmd.split()
        return [t.strip("\"'") for t in toks]
    return [str(a) for a in job.cmd]


def cmd_option_values(job: Job, flag: str) -> list[str]:
    """The values of ``flag`` in the job's command or argv: ``--flag v [v ...]`` (up to the next ``-`` token) and
    ``--flag=v``; a string command and an argv list read alike (#701)."""

    toks = _cmd_tokens(job)
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == flag:
            i += 1
            while i < len(toks) and not toks[i].startswith("-"):
                out.append(toks[i])
                i += 1
            continue
        if t.startswith(flag + "="):
            out.append(t[len(flag) + 1:])
        i += 1
    return out


def replay_dirs(job: Job, artifacts: Path) -> list[str] | None:
    """The ``artifacts/``-relative dirs (``replay/<dir>``, ``benchmark/<dir>``) the job's ``--against`` and
    ``--builds`` read, ``--against`` resolved as ``scripts/replay_bench.py _against_rows`` resolves it on this host
    (a path that exists as is, else the newest ``replay/*-<tag>``); [] for a job that names none; None when an
    ``--against`` does not resolve here (#701)."""

    out: list[str] = []
    for arg in cmd_option_values(job, "--against"):
        path = Path(arg)
        if not path.exists():
            matches = sorted((artifacts / "replay").glob(f"*-{arg}"))
            if not matches:
                return None
            path = matches[-1]
        rel = _artifact_dir(path, artifacts)
        if rel is None:
            return None
        out.append(rel)
    for arg in cmd_option_values(job, "--builds"):
        m = re.search(r"artifacts[\\/]+(benchmark|replay)[\\/]+([^\\/*?\[]+)", arg)
        if m:
            out.append(f"{m.group(1)}/{m.group(2)}")
    return list(dict.fromkeys(out))


def _artifact_dir(path: Path, artifacts: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(Path(artifacts).resolve())
    except ValueError:
        return None
    parts = rel.parts
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 and parts[0] in ("replay", "benchmark") else None


_ANY_WORKERS_RE = re.compile(r"(--workers(?:\s+|=))(\S+)")


def set_workers(cmd: Any, argv: Any, n: int) -> tuple[Any, Any]:
    """``cmd`` and ``argv`` with every ``--workers <value>`` (a number or ``auto``) set to ``n`` (#570)."""

    new_cmd = _ANY_WORKERS_RE.sub(lambda m: f"{m.group(1)}{n}", cmd) if isinstance(cmd, str) else cmd
    new_argv = argv
    if argv:
        items = [str(a) for a in argv]
        out: list[str] = []
        i = 0
        while i < len(items):
            a = items[i]
            if a == "--workers" and i + 1 < len(items):
                out += [a, str(n)]
                i += 2
                continue
            out.append(_ANY_WORKERS_RE.sub(lambda m: f"{m.group(1)}{n}", a) if a.startswith("--workers=") else a)
            i += 1
        new_argv = tuple(out) if isinstance(argv, tuple) else out
    return new_cmd, new_argv


def _cut(job: Job, n: int) -> Job:
    """A copy of ``job`` at ``n`` workers: the field and every ``--workers N`` of its command and argv."""

    cmd = _WORKERS_RE.sub(lambda m: f"{m.group(1)}{n}", job.cmd) if isinstance(job.cmd, str) else job.cmd
    argv = job.argv
    if argv:
        out: list[str] = []
        items = [str(a) for a in argv]
        i = 0
        while i < len(items):
            a = items[i]
            if a == "--workers" and i + 1 < len(items) and items[i + 1].isdigit():
                out += [a, str(n)]
                i += 2
                continue
            out.append(_WORKERS_RE.sub(lambda m: f"{m.group(1)}{n}", a) if a.startswith("--workers=") else a)
            i += 1
        argv = tuple(out) if isinstance(argv, tuple) else out
    return replace(job, workers=n, cmd=cmd, argv=argv)


RAM_STATUS_MAX_AGE_SECONDS = 600.0  # #917: an older host status counts as "RAM not readable"


def _plan(members: list[Job], room: int) -> list[Job] | None:
    """The members as they would land on a host with ``room`` slots: unchanged when each fits, else the
    oversized ones cut to ``room`` (never below 2; only a job whose command carries ``--workers N`` with
    N > room); None when they cannot land there."""

    out: list[Job] = []
    for m in members:
        if max(1, int(m.workers)) <= room:
            out.append(m)
            continue
        n = _cmd_workers(m)
        if room < 2 or n is None or n <= room:
            return None
        out.append(_cut(m, room))
    return out


def _inherited(job: Job) -> bool:
    """A follower placed in its base's store by ``submit --after`` (#648): it goes only with its base."""

    return bool(job.host_fixed and (job.host_reason or "").startswith("after:"))


class Rebalancer:
    def __init__(
        self, daemon: Any, *,
        has_pin: Callable[[Mapping[str, Any], str, str], bool] = has_pin_on_host,
        submit_moved: Callable[[Mapping[str, Any], str, Job, str], str | None] = submit_moved_on_host,
        remote_head: Callable[[Mapping[str, Any]], str] = head_on_host,
        gates_present: Callable[[str], set[str]] = runs_gates.gates_present,
        newest_gate: Callable[[Any], str | None] = runs_gates.newest_gate,
        copy_dir: Callable[[str, Mapping[str, Any], str], bool] | None = None,
        push_pin: Callable[[Path, str], tuple[bool, str]] = runs_pin_ref.push_pin,
    ) -> None:
        self._push_pin = push_pin
        self._copy_dir = copy_dir
        self._copy_failed: set[tuple[str, str]] = set()
        self.daemon = daemon
        self._gates_present = gates_present
        self._newest_gate = newest_gate
        self._gate_logged: set[tuple[str, str]] = set()
        self._has_pin = has_pin
        self._submit_moved = submit_moved
        self._remote_head = remote_head
        self._pin_logged: set[tuple[str, str]] = set()
        self._write_logged: set[tuple[str, str]] = set()
        self._fixed_logged: set[str] = set()
        self._unreachable_logged: set[tuple[str, str]] = set()
        self._ram_logged: set[tuple[str, str]] = set()
        self._room_logged: set[tuple[str, str]] = set()

    def _candidates(self) -> list[Job]:
        d = self.daemon
        now = d.clock()
        queued = [j for j in d.store.jobs(state="queued") if j.host == d.host]
        queued.sort(key=lambda j: (store_mod._PRIORITY_RANK[j.priority], j.submit_ts, j.id))
        everything = None
        # a job some live job on this host waits for moves only together with its whole chain (#484)
        followed = {dep for j in d.store.jobs() if j.host == d.host and j.state in store_mod.LIVE_STATES
                    for dep in j.after}
        out: list[Job] = []
        for job in queued:
            if not self._movable(job):
                if (job.host_fixed and job.id not in self._fixed_logged
                        and now - d._epoch(job.submit_ts) >= MOVE_AFTER_SECONDS
                        and not (job.is_filler or job.moved_from or job.rc_is_reading
                                 or _runs_pytest(job.cmd))):
                    self._fixed_logged.add(job.id)
                    why = f"host inherited from {job.host_reason}" if _inherited(job) else "host fixed by its submit"
                    d.log(f"rebalance: job {job.id} stays; {why}")
                continue
            # #729: a job held by the PC's spike hold waits on a full PC from the first step: no 15 min wait
            held = getattr(d, "spike_step", 0) >= spike_mod.MAX_STEP
            if not held and now - d._epoch(job.submit_ts) < MOVE_AFTER_SECONDS:
                continue
            if job.after:
                everything = everything or {j.id: j for j in d.store.jobs()}
                if store_mod.dependency_status(job, everything)[0] != store_mod.DEP_READY:
                    continue
            if job.id in followed and self._chain(job) is None:
                continue
            out.append(job)
        return out

    @staticmethod
    def _movable(job: Job) -> bool:
        """Never a filler, a reading probe, a suite (it needs the submitting host's Python environment)
        or an already moved copy."""

        if job.is_filler or job.moved_from or getattr(job, "rc_is_reading", False) or job.host_fixed:
            return False
        return not _runs_pytest(job.cmd)

    def _chain(self, base: Job) -> list[Job] | None:
        """The live followers of ``base`` (transitively) in dependency order; [] for none; None when the
        chain cannot move as one (a follower that is started or unmovable, or waits for a job outside it)."""

        d = self.daemon
        live = [j for j in d.store.jobs() if j.host == d.host and j.state in store_mod.LIVE_STATES]
        ids = {base.id}
        found: list[Job] = []
        grew = True
        while grew:
            grew = False
            for j in live:
                if j.id in ids or not (set(j.after) & ids):
                    continue
                if j.state != "queued":
                    return None
                if _inherited(j) and not (j.is_filler or j.moved_from or getattr(j, "rc_is_reading", False)
                                          or _runs_pytest(j.cmd)):
                    if not set(j.after) <= ids:  # the follower waits for a job outside the chain
                        return None
                elif not self._movable(j):
                    return None
                ids.add(j.id)
                found.append(j)
                grew = True
        ordered: list[Job] = []
        placed = {base.id}
        while found:
            nxt = next((j for j in found if set(j.after) <= placed), None)
            if nxt is None:
                return None  # waits for a job outside the chain
            ordered.append(nxt)
            placed.add(nxt.id)
            found.remove(nxt)
        return ordered

    def _log_unreachable(self, job: Job, host: str, ago: float) -> None:
        if (job.id, host) in self._unreachable_logged:
            return
        self._unreachable_logged.add((job.id, host))
        self.daemon.log(f"rebalance: job {job.id} stays; {host} unreachable {max(1, int(ago // 60))} min ago")

    def _log_ram(self, job: Job, host: str, text: str) -> None:
        if (job.id, host) in self._ram_logged:
            return
        self._ram_logged.add((job.id, host))
        self.daemon.log(f"rebalance: job {job.id} stays; {host} RAM {text}")

    def _remote_ram_bound(self, snapshot: Any) -> int | None:
        """#917: the host daemon's own ``ram_bound`` from its status; None when missing, null or older than 10 min."""

        status = getattr(snapshot, "daemon_status", None) or {}
        bound = status.get("ram_bound")
        if isinstance(bound, bool) or not isinstance(bound, int):
            return None
        try:
            last = datetime.fromisoformat(str(status.get("last_tick")))
        except ValueError:
            return None
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (self.daemon._utcnow() - last).total_seconds() > RAM_STATUS_MAX_AGE_SECONDS:
            return None
        return bound

    def _log_gate(self, job: Job, host: str, newest: str | None) -> None:
        if (job.id, host) in self._gate_logged:
            return
        self._gate_logged.add((job.id, host))
        self.daemon.log(f"rebalance: job {job.id} stays; {host} lacks gate {newest or 'none'}")

    def _replay_dirs(self, plan: list[Job]) -> list[str]:
        d = self.daemon
        artifacts = d._gate_artifacts if getattr(d, "_gate_artifacts", None) is not None else runs_gates.ROOT / "artifacts"
        out: list[str] = []
        for m in plan:
            try:
                out += replay_dirs(m, Path(artifacts)) or []
            except Exception:
                continue
        return list(dict.fromkeys(out))

    def _copy_missing(self, job: Job, host: str, host_cfg: Mapping[str, Any], wanted: list[str]) -> bool:
        """#701: copy each wanted dir the host lacks, once; False (job stays, one log line) when a copy fails
        or failed earlier in this step."""

        d = self.daemon
        copy = self._copy_dir or d.copy_dir_to_host
        held = self._gates_present(host)
        for rel in wanted:
            if runs_gates.dir_key(rel) in held:
                continue
            if (host, rel) in self._copy_failed:
                return False
            ok = False
            try:
                ok = bool(copy(host, host_cfg, rel))
            except Exception:
                ok = False
            if not ok:
                self._copy_failed.add((host, rel))
                d.log(f"rebalance: job {job.id} stays; copy of {rel} to {host} failed")
                return False
        return True

    def step(self) -> list[str]:
        """Move what qualifies; the ids of the moved (original) jobs. Never raises."""

        d = self.daemon
        try:
            candidates = self._candidates()
            if not candidates:
                return []
            config = d._hosts_config if d._hosts_config is not None else runs_hosts.load_hosts_config()
            others = {h: c for h, c in config.items() if h != d.host and c.get("ssh")}
            if not others:
                return []
            held = {h: ago for h in others
                    if (ago := d.remote_failed_ago(h)) is not None and ago < UNREACHABLE_MOVE_HOLD_SECONDS}
            if len(held) == len(others):  # every other host is known dead: no ssh read, no move
                for job in candidates:
                    for h, ago in held.items():
                        self._log_unreachable(job, h, ago)
                return []

            snapshots: dict[str, Any] = {}

            def reader(host_cfg: Mapping[str, Any], host: str = "") -> Any:
                try:
                    snapshot = d._read_remote_snapshot(host_cfg, host)
                except Exception:
                    d.note_remote_read(host, False)
                    raise
                d.note_remote_read(host, True)
                snapshots[host] = snapshot
                return snapshot

            states = placement.gather_states(
                local_host=d.host, local_store=d.store, config=config, now=datetime.now(),
                remote_reader=reader, local_total=lambda: d.budget().total, log=d.log)
        except Exception as exc:
            d.log(f"rebalance: skipped ({exc!r})")
            return []
        moved: list[str] = []
        self._copy_failed = set()
        for job in candidates:
            if job.id in moved:
                continue
            members = [job] + (self._chain(job) or [])
            for host, host_cfg in others.items():
                if host in held:
                    self._log_unreachable(job, host, held[host])
                    continue
                if host not in states:
                    continue
                cause = placement.unreadable_cause.get(host)
                if cause and states[host] <= 0:  # (#709) room 0 because the budget did not read, not "full"
                    if (job.id, host) not in self._room_logged:
                        self._room_logged.add((job.id, host))
                        d.log(f"rebalance: job {job.id} stays; {host} room 0 ({cause})")
                    continue
                plan = _plan(members, states[host])
                if plan is None:
                    continue
                if host in snapshots:  # #917: the host's own gate holds on RAM too
                    bound = self._remote_ram_bound(snapshots[host])
                    if bound is None:
                        self._log_ram(job, host, "not readable")
                        continue
                    if bound < states[host]:
                        plan = _plan(members, bound)
                        if plan is None:
                            need = max(max(1, int(m.workers)) for m in members)
                            self._log_ram(job, host, f"holds {max(0, bound)} workers, need {need}")
                            continue
                wanted = self._replay_dirs(plan)
                if wanted and not self._copy_missing(job, host, host_cfg, wanted):
                    continue
                if not wanted and any(runs_gates.needs_gate(m.cmd) for m in plan):
                    try:
                        newest = self._newest_gate(runs_gates.ROOT / "artifacts")
                        has_gate = newest is not None and newest in self._gates_present(host)
                    except Exception:
                        newest, has_gate = None, False
                    if not has_gate:
                        self._log_gate(job, host, newest)
                        continue
                pins = sorted({m.pin for m in plan if m.pin})
                # #889: the pin travels through origin BEFORE the move (the host fetches it at its start);
                # a failed push keeps the job here, one log line per (job, host)
                push_failed = ""
                for pin in pins:
                    try:
                        ok, msg = self._push_pin(runs_gates.ROOT, pin)
                    except Exception as exc:
                        ok, msg = False, f"push of pin {pin} raised {exc!r}"
                    if not ok:
                        push_failed = msg
                        break
                if push_failed:
                    if (job.id, host) not in self._pin_logged:
                        self._pin_logged.add((job.id, host))
                        d.log(f"rebalance: job {job.id} stays; pin {', '.join(pins)} cannot reach {host}: {push_failed}")
                    continue
                room_was = states[host]
                need = max(max(1, int(m.workers)) for m in plan)
                new_ids: dict[str, str] = {}
                for orig, copy in zip(members, plan):
                    copy = replace(copy, after=tuple(new_ids.get(x, x) for x in copy.after))
                    if _inherited(copy):  # #648: the moved head still follows its base, now by the new id
                        copy = replace(copy, host_reason="after:" + ",".join(copy.after))
                    error = ""
                    try:
                        new_id = self._submit_moved(host_cfg, host, copy, d.host)
                    except Exception as exc:
                        new_id, error = None, _first_line(exc) or type(exc).__name__
                    if not new_id:
                        # one line per (job, remote HEAD): the HEAD is read only on a failure
                        try:
                            head = self._remote_head(host_cfg) or "unknown"
                        except Exception:
                            head = "unknown"
                        if (orig.id, head) not in self._write_logged:
                            self._write_logged.add((orig.id, head))
                            d.log(f"rebalance: could not write job {orig.id} into {host}'s store (its daemon HEAD {head}"
                                  f"{': ' + error if error else ''}); it stays")
                        break
                    new_ids[orig.id] = new_id
                    try:
                        d.store.move_away(orig.id, to=host, new_id=new_id)
                    except Exception as exc:
                        d.log(f"rebalance: job {orig.id} was written to {host} as {new_id} but not ended here ({exc!r})")
                        break
                    cut = f"; workers {orig.workers} -> {copy.workers}" if copy.workers != orig.workers else ""
                    d.log(f"rebalance: job {orig.id} waited {(d.clock() - d._epoch(orig.submit_ts)) / 60:.0f} min; "
                          f"moved to {host} as {new_id} (need {max(1, int(copy.workers))}, room was {room_was}{cut})")
                    d._append_event({
                        "ts": d.timestamp().isoformat(timespec="seconds"), "kind": "moved", "job": orig.id,
                        "tag": orig.tag, "issue": orig.issue, "from": d.host, "to": host, "new_job": new_id,
                    })
                    moved.append(orig.id)
                if new_ids:
                    states[host] -= need  # a chain runs one job after another: the largest need, not the sum
                    break
        return moved


@dataclass(frozen=True)
class ReclaimResult:
    """What :func:`reclaim_from_dead_host` did (#1183): ``moved`` the dead host's job ids now queued here,
    ``stayed_fixed`` the ids fixed to that host (still queued there), ``failed`` (job id, reason) pairs."""

    moved: list[str]
    stayed_fixed: list[str]
    failed: list[tuple[str, str]]


def _reclaimable(job: Job) -> bool:
    """Like :meth:`Rebalancer._movable` but a job that carries ``moved_from`` still qualifies: the rebalance sends
    a job to the laptop once and never back, and a dead laptop is exactly where that job sits stranded."""

    if job.is_filler or getattr(job, "rc_is_reading", False) or job.host_fixed:
        return False
    return not _runs_pytest(job.cmd)


def reclaim_from_dead_host(d: Any, host_name: str) -> ReclaimResult:
    """Queue the dead host's queued, movable jobs in this host's own store (#1183 unit 4).

    The dead host's queue is read as the rebalance reads a remote snapshot (``d._read_remote_snapshot``). A
    ``host_fixed`` job stays there; a filler, a suite or a reading is left as it is (:func:`_reclaimable`). A job
    the PC itself moved to the laptop (``moved_from`` set: the very case of #1183) comes back. Any other queued job is written here as a copy (``host_fixed=False``,
    ``moved_from=host_name``) and only then cancelled on the dead host; a refused cancel cancels the copy here
    again, so a job never queues on both hosts. A read that fails raises, with nothing moved. No issue, comment
    or keymaster session is touched.
    """

    config = d._hosts_config if d._hosts_config is not None else runs_hosts.load_hosts_config()
    host_cfg = dict(config.get(host_name) or {})
    snapshot = d._read_remote_snapshot(host_cfg, host_name)
    queued = [j for j in snapshot.jobs if j.state == "queued"]
    queued.sort(key=lambda j: (store_mod._PRIORITY_RANK[j.priority], j.submit_ts, j.id))
    moved: list[str] = []
    stayed: list[str] = []
    failed: list[tuple[str, str]] = []
    pending: list[Job] = []
    for job in queued:
        if job.host_fixed:
            stayed.append(job.id)
        elif _reclaimable(job):
            pending.append(job)
    new_ids: dict[str, str] = {}
    waiting = {j.id for j in pending}
    while pending:
        progressed = False
        for job in list(pending):
            if any(dep in waiting for dep in job.after):
                continue  # a predecessor still to be decided goes first
            pending.remove(job)
            waiting.discard(job.id)
            progressed = True
            _reclaim_one(d, host_cfg, host_name, job, new_ids, moved, failed)
        if not progressed:  # a cycle of --after ids: none of it moves
            failed.extend((j.id, "--after cycle") for j in pending)
            break
    return ReclaimResult(moved=moved, stayed_fixed=stayed, failed=failed)


def _reclaim_one(d: Any, host_cfg: Mapping[str, Any], host_name: str, job: Job,
                 new_ids: dict[str, str], moved: list[str], failed: list[tuple[str, str]]) -> None:
    """Write one queued job of the dead host into this store, then cancel the dead host's copy."""

    missing = [dep for dep in job.after if dep not in new_ids]
    if missing:  # a predecessor that stays on the dead host cannot follow the job here
        failed.append((job.id, f"waits for {', '.join(missing)} on {host_name}, which did not move"))
        return
    try:
        local = d.store.submit(
            host=d.host, priority=job.priority, tag=job.tag, cmd=job.cmd, issue=job.issue,
            submitter=job.submitter, pin=job.pin, resumable=job.resumable, workers=job.workers,
            after=[new_ids[x] for x in job.after], job_class=job.job_class, moved_from=host_name,
            argv=list(job.argv) if job.argv else None, no_label=job.no_label, host_fixed=False,
            workers_auto=job.workers_auto, note=job.note, submit_commit=job.submit_commit,
        )
    except Exception as exc:
        failed.append((job.id, _first_line(exc) or type(exc).__name__))
        return
    if not remote_cancel_queued(host_cfg, job.id):
        try:  # the dead host kept its copy: this copy goes, so the job never runs on both
            d.store.cancel(local.id, reason=f"{host_name} copy not cancelled; the job stays there")
        except Exception as exc:
            d.log(f"reclaim: copy {local.id} of job {job.id} not cancelled here ({exc!r})")
        failed.append((job.id, f"{host_name} did not cancel its copy"))
        return
    new_ids[job.id] = local.id
    moved.append(job.id)
    d.log(f"reclaim: job {job.id} taken from {host_name} (daemon dead) as {local.id}")
    d._append_event({
        "ts": d.timestamp().isoformat(timespec="seconds"), "kind": "moved", "job": job.id,
        "tag": job.tag, "issue": job.issue, "from": host_name, "to": d.host, "new_job": local.id,
        "reason": "daemon_dead",
    })
