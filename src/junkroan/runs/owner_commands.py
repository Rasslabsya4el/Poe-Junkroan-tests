"""The owner's presets on a host (#958, unit 3b): `film`, `sleep`, `back`, `status`.

A preset is written as the host's owner record in ``modes.json`` (``hosts.set_owner_preset``); the host's own
daemon does the give-way from that record exactly as it does for a reserve (yield files, Idle priority, the
lapse), and at the lapse of a record with ``on_end: close-browsers`` it closes the browsers itself.
Everything that reads the machine goes through ``read_machine`` / the ``jobs_reader`` argument, so tests
bring their own readings; nothing here starts a process or opens ssh."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from junkroan.report_format import human_duration
from junkroan.runs import close_set
from junkroan.runs import hosts as runs_hosts
from junkroan.runs import owner_preset
from junkroan.runs import yield_plan

HostModeError = runs_hosts.HostModeError

PRESET_NAMES = ("film", "sleep")


@dataclass(frozen=True)
class Worker:
    cores: float
    ram_mb: float


@dataclass(frozen=True)
class Reading:
    """The machine now: idle cores, free RAM, and the live PoB worker processes."""

    idle_cores: float
    free_ram_mb: float
    workers: list[Worker] = field(default_factory=list)


def read_machine(interval: float = 1.0) -> Reading:
    """The real reading (psutil): idle cores = logical cores x (1 - CPU load over ``interval``), free RAM =
    available MB, one ``Worker`` per live PoB runtime worker (its CPU in cores over the same interval, RSS)."""

    import psutil

    procs = []
    for pid in runs_hosts.find_pob_pids():
        try:
            process = psutil.Process(pid)
            process.cpu_percent(None)
            procs.append(process)
        except Exception:
            continue
    load = psutil.cpu_percent(interval=interval)
    idle = (psutil.cpu_count(logical=True) or 1) * max(0.0, 1.0 - load / 100.0)
    workers: list[Worker] = []
    for process in procs:
        try:
            workers.append(Worker(cores=process.cpu_percent(None) / 100.0,
                                  ram_mb=process.memory_info().rss / 1048576.0))
        except Exception:
            continue
    return Reading(idle_cores=idle, free_ram_mb=psutil.virtual_memory().available / 1048576.0, workers=workers)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _readings_line(reading: Reading) -> str:
    return f"free RAM now: {reading.free_ram_mb:,.0f} MB, idle cores now: {reading.idle_cores:.1f}"


def _need_text(cpu: float | None, ram: float | None) -> str:
    return f"{cpu:g} cores and {ram:,.0f} MB"


def preset_spec(config: Mapping[str, Any], host: str, name: str) -> dict[str, Any]:
    presets = (config.get(host) or {}).get("owner_presets")
    if not isinstance(presets, Mapping) or not presets:
        raise HostModeError(f"{host} has no owner presets in config/hosts.json; the presets are the laptop's")
    spec = presets.get(name)
    if not isinstance(spec, Mapping):
        raise HostModeError(f"{host} has no preset {name!r} (it has: {', '.join(k for k in presets if k in PRESET_NAMES)})")
    return dict(spec)


def host_has_presets(config: Mapping[str, Any], host: str) -> bool:
    presets = (config.get(host) or {}).get("owner_presets")
    return isinstance(presets, Mapping) and any(k in presets for k in PRESET_NAMES)


def start_preset(
    host: str,
    name: str,
    *,
    config: Mapping[str, Any],
    duration_text: str | None = None,
    close: list[str] | None = None,
    reader: Callable[[], Reading] | None = None,
    jobs_reader: Callable[[], Mapping[str, int]] | None = None,
    modes_file: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Start preset ``name`` on ``host``: size the give-way, write the record, return the printed lines."""

    spec = preset_spec(config, host, name)
    text = duration_text or spec.get("for")
    if not text:
        raise HostModeError(f"{name} needs --for <duration>")
    minutes = runs_hosts.parse_duration(str(text)) / 60.0
    moment = now or datetime.now()

    need_cpu = spec.get("need_cpu_cores")
    need_ram = spec.get("need_ram_mb")
    has_need = need_cpu is not None or need_ram is not None
    need_cpu = float(need_cpu or 0.0)
    need_ram = float(need_ram or 0.0)

    reading: Reading | None
    try:
        reading = (reader or read_machine)()
    except Exception:
        if has_need:
            raise HostModeError("the machine could not be read, so the need cannot be sized") from None
        reading = None  # a slot-count preset sizes nothing from the machine
    running = len(reading.workers) if reading is not None else 0

    if has_need:
        assert reading is not None
        give = owner_preset.size_give_way(
            need_cpu_cores=need_cpu, need_ram_mb=need_ram,
            idle_cores=reading.idle_cores, free_ram_mb=reading.free_ram_mb, running_workers=running,
            worker_cores=_mean([w.cores for w in reading.workers]),
            worker_ram_mb=_mean([w.ram_mb for w in reading.workers]),
        )
    else:
        give = owner_preset.slots_give_way(int(spec.get("slots") or 1), running)
    n = give.workers

    on_end = spec.get("on_end") or None
    close_list = None
    close_mode = None
    keep_list: list[str] | None = None
    if on_end == runs_hosts.ON_END_CLOSE_BROWSERS:
        if not close and spec.get("close_mode") == runs_hosts.CLOSE_MODE_ALLOW_LIST:
            # #958 unit 4: the end closes every program of the user outside the allow-list (an explicit
            # `--close` list still means exactly those names)
            close_mode = runs_hosts.CLOSE_MODE_ALLOW_LIST
            keep_list = [str(n) for n in (spec.get("keep") or [])]
        else:
            close_list = list(close or spec.get("close") or runs_hosts.DEFAULT_CLOSE)
    until = runs_hosts.set_owner_preset(
        host, name, n, minutes,
        need_cpu_cores=need_cpu if has_need else None, need_ram_mb=need_ram if has_need else None,
        on_end=on_end, close=close_list, close_mode=close_mode, keep=keep_list, workers_before=running if reading is not None else None,
        modes_file=modes_file, now=moment,
    )

    lines = [f"{name} on {host} until {until:%H:%M} (for {human_duration(minutes * 60)})"]
    lines.append(f"workers giving way: {n} of {running} live PoB workers{_job_text(jobs_reader, n)}")
    if reading is not None:
        lines.append(_readings_line(reading))
    if has_need:
        lines.append(f"need: {_need_text(need_cpu, need_ram)}")
    else:
        lines.append(f"need: {int(spec.get('slots') or 1)} slot(s) (no measured need yet)")
    if has_need:
        lines += give.short_lines()
    if close_list:
        lines.append(f"at the end the {host} closes: {', '.join(close_list)}")
    if close_mode:
        lines.append(f"at the end the {host} closes every program of the user outside the allow-list "
                     f"(kept by name: {', '.join(keep_list) if keep_list else 'none'}); "
                     f"`owner {host} close-preview` shows the lists now")
    return lines


def close_preview_lines(host: str, config: Mapping[str, Any]) -> tuple[list[str], bool]:
    """``close-preview``: the KEPT and CLOSED lists of the allow-list close as they are now (name, pid, the rule
    that kept it); kills nothing. Returns ``(lines, ok)``; ``ok`` is False when the snapshot cannot be read."""

    keep = [str(n) for n in (preset_spec(config, host, "sleep").get("keep") or [])]
    plan = close_set.plan_close(host, keep)
    if plan is None:
        return [f"{host}: the process snapshot could not be read; nothing to preview"], False
    closed, kept = plan
    lines = [f"CLOSED ({len(closed)}): the end of sleep would close these, and nothing else"]
    lines += [f"  {proc.name} pid {proc.pid}" for proc in sorted(closed, key=lambda p: (p.name.lower(), p.pid))]
    lines.append(f"KEPT ({len(kept)}):")
    lines += [f"  {proc.name} pid {proc.pid}: {why}" for proc, why in sorted(kept, key=lambda k: (k[0].name.lower(), k[0].pid))]
    lines.append("nothing was closed")
    return lines, True


def _job_text(jobs_reader: Callable[[], Mapping[str, int]] | None, n: int) -> str:
    if n <= 0 or jobs_reader is None:
        return ""
    try:
        jobs = dict(jobs_reader())
    except Exception:
        return ""
    if not jobs:
        return ""
    in_use = sum(max(0, w) for w in jobs.values())
    plan = yield_plan.plan_yield(jobs, max(0, in_use - n))
    parts = [f"{job} {give} of {jobs[job]}" for job, give in sorted(plan.items()) if give > 0]
    return f" (from jobs: {', '.join(parts)})" if parts else ""


def end_preset(host: str, *, modes_file: Path | None = None) -> list[str]:
    """``back``: end whatever owner record the host holds, at once. A record with ``on_end`` is dropped
    here WITHOUT closing anything: only a lapse closes the browsers."""

    record = runs_hosts.owner_record_raw(host, modes_file=modes_file)
    if record is None:
        return [f"{host}: no owner preset or reservation is active"]
    runs_hosts.release_owner_reservation(host, modes_file=modes_file)
    what = record.get("preset") or "owner reservation"
    lines = [f"{host}: {what} ended at once; PoB takes the room back within a daemon tick"]
    if record.get("on_end"):
        lines.append("nothing is closed on back; the browsers stay open")
    return lines


def status_lines(
    host: str,
    *,
    reader: Callable[[], Reading] | None = None,
    modes_file: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """``status``: the active preset and its end, the live PoB workers, free RAM and idle cores now, and
    ``room: yes|no`` against the recorded need."""

    moment = now or datetime.now()
    record = runs_hosts.owner_record_raw(host, modes_file=modes_file)
    reading = (reader or read_machine)()
    lines: list[str] = []
    if record is None:
        lines.append(f"{host}: no owner preset or reservation is active")
    else:
        what = record.get("preset") or "owner reservation"
        try:
            until = datetime.fromisoformat(str(record["reserved_until"]))
            left = (until - moment).total_seconds()
            when = (f"until {until:%H:%M} (in {human_duration(left)})" if left > 0
                    else f"ended at {until:%H:%M}, waiting for the daemon's next tick")
        except (KeyError, ValueError):
            when = "with an unreadable end time"
        lines.append(f"{host}: {what} {when}; {int(record.get('reserved') or 0)} workers give way")
        if record.get("on_end"):
            if record.get("close_mode") == runs_hosts.CLOSE_MODE_ALLOW_LIST:
                lines.append(f"on end: {record['on_end']} (every program outside the allow-list; "
                             f"kept by name: {', '.join(record.get('keep') or []) or 'none'})")
            else:
                lines.append(f"on end: {record['on_end']} ({', '.join(record.get('close') or runs_hosts.DEFAULT_CLOSE)})")
    live = len(reading.workers)
    lines.append(f"live PoB workers: {live}")
    lines.append(_readings_line(reading))
    if record is not None:
        cpu, ram = record.get("need_cpu_cores"), record.get("need_ram_mb")
        if cpu is not None or ram is not None:
            lines.append(f"need: {_need_text(float(cpu or 0), float(ram or 0))}")
            room = reading.idle_cores >= float(cpu or 0) and reading.free_ram_mb >= float(ram or 0)
        else:
            allowed = max(0, int(record.get("workers_before") or 0) - int(record.get("reserved") or 0))
            room = live <= allowed
        lines.append(f"room: {'yes' if room else 'no'}")
    return lines
