"""Where a ``submit --host auto`` job starts soonest (issue #403).

``room_now`` and ``pick_host`` are pure; ``gather_states`` is the one thin reader (local store +
budget for this host, ``read_remote_snapshot`` for the other). A filler yields, so its slots count
as free; an unreachable host is skipped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from junkroan.pob import slot_budget
from junkroan.runs import hosts as runs_hosts
from junkroan.runs.remote_store import RemoteStoreUnreachable, read_remote_snapshot


def _get(job: Any, name: str, default: Any = None) -> Any:
    if isinstance(job, Mapping):
        return job.get(name, default)
    return getattr(job, name, default)


def _need(job: Any) -> int:
    return max(1, int(_get(job, "need", None) or _get(job, "workers", None) or 1))


def _is_filler(job: Any) -> bool:
    value = _get(job, "is_filler", None)
    if value is None:
        value = _get(job, "job_class", "run") == "filler"
    return bool(value)


def room_now(total: int, running_jobs: Iterable[Any], queued_jobs_ahead: Iterable[Any]) -> int:
    """Slots free for a new job: ``total`` minus the need of running non-filler jobs minus the need
    of non-filler jobs queued ahead. Fillers (running or queued) count as free. May be negative."""

    used = sum(_need(j) for j in running_jobs if not _is_filler(j))
    ahead = sum(_need(j) for j in queued_jobs_ahead if not _is_filler(j))
    return int(total) - used - ahead


def pick_host(need: int, states: Mapping[str, int]) -> str:
    """``states`` maps each reachable host to its ``room_now``. Among the hosts where the job fits
    now (room >= ``need``) the larger room wins, ties go to ``pc``; where it fits nowhere, ``pc``
    (#403's spec: a 5-worker job goes to the laptop only when the laptop's room is >= 5)."""

    fits = {h: room for h, room in states.items() if room >= need}
    if not fits:
        return "pc"
    return max(fits, key=lambda h: (fits[h], h == "pc"))


def gate_filter(
    states: Mapping[str, int], cmd: Any, newest: str | None, present: Callable[[str], set[str]],
    *, needs_gate: Callable[[Any], bool] | None = None, dirs: list[str] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """(#642) A command that reads the weekly gate may only run where the newest gate dir is. (#642 unit 6b)
    A command that names artifacts folders (``dirs``: the ``replay_dirs`` of it) may run only where the host
    holds each of them (``present`` answers by ``runs_gates.dir_key``); the newest gate decides only for a
    command that names none. Returns ``(states without the hosts lacking it, the dropped host names)``;
    ``pc`` is never dropped. With no newest gate every other host is dropped. A command that needs no gate
    and names no folder: ``states`` unchanged."""

    from junkroan.runs import gates as runs_gates

    named = list(dirs or [])
    if not (named or (needs_gate or runs_gates.needs_gate)(cmd)):
        return dict(states), []
    kept: dict[str, int] = {}
    dropped: list[str] = []
    for host, room in states.items():
        if host == "pc":
            ok = True
        elif named:
            held = present(host)
            ok = all(runs_gates.dir_key(d) in held for d in named)
        else:
            ok = newest is not None and newest in present(host)
        if ok:
            kept[host] = room
        else:
            dropped.append(host)
    return kept, dropped


def _period_total(host_cfg: Mapping[str, Any], mode: str, now: datetime) -> int:
    entry = (host_cfg.get("modes") or {}).get(mode) or {}
    periods = {k: v for k, v in entry.items() if isinstance(v, Mapping) and "hours" in v}
    for spec in periods.values():
        start, end = (int(x) for x in spec["hours"])
        if start <= now.hour < end or start <= now.hour + 24 < end:
            return int(spec.get("total", 0))
    if periods:
        spec = periods.get("day") or next(iter(periods.values()))
        return int(spec.get("total", 0))
    return 0


#: Hosts whose unreadable budget was already logged (cleared when a later step reads a good one).
_unreadable_logged: set[str] = set()
#: (#709) Why a host's room is 0 right now because its budget did not read (host -> short cause);
#: absent while the budget reads fine. ``rebalance`` quotes it in the per-job stay line.
unreadable_cause: dict[str, str] = {}


def gather_states(
    *, local_host: str, local_store: Any, config: Mapping[str, Any] | None = None,
    now: datetime | None = None, remote_reader: Callable[..., Any] = read_remote_snapshot,
    local_total: Callable[[], int] | None = None, log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """``{host: room_now}`` for every host in the config that answers.

    A remote host is sized from the mode its snapshot's budget file matches (#471, no extra ssh
    call). No readable budget, or one matching no mode: room 0 for the step, one log line per host
    until a later step reads a good budget."""

    config = dict(config if config is not None else runs_hosts.load_hosts_config())
    moment = now or datetime.now()
    states: dict[str, int] = {}
    for host, host_cfg in config.items():
        try:
            if host == local_host:
                jobs = list(local_store.jobs())
                total = (local_total or (lambda: slot_budget.load_budget(now=moment).total))()
            else:
                snapshot = remote_reader(host_cfg, host=host)
                jobs = list(snapshot.jobs)
                budget = getattr(snapshot, "budget", None)
                mode = ("unknown" if budget is None
                        else runs_hosts.mode_from_budget(host, budget, config=config, placement_keys=True))
                if mode == "unknown":
                    total = 0
                    if budget is None:
                        cause = "file missing, empty or unparsable"
                    else:
                        closest, diff = runs_hosts.placement_diff(host_cfg, host, budget)
                        cause = (f"file differs from {closest!r} in {', '.join(diff) or 'nothing found'}"
                                 if closest else "host has no modes")
                    unreadable_cause[host] = cause
                    if host not in _unreadable_logged:
                        _unreadable_logged.add(host)
                        (log or (lambda _m: None))(
                            f"placement: {host} budget unreadable or matches no mode ({cause}); "
                            "room 0 until it reads again")
                else:
                    unreadable_cause.pop(host, None)
                    was_bad = host in _unreadable_logged
                    _unreadable_logged.discard(host)
                    total = _period_total(host_cfg, mode, moment)
        except RemoteStoreUnreachable:
            continue
        mine = [j for j in jobs if _get(j, "host") in (host, "any")]
        running = [j for j in mine if _get(j, "state") == "running"]
        queued = [j for j in mine if _get(j, "state") == "queued"]
        states[host] = room_now(total, running, queued)
        if host != local_host and mode != "unknown" and was_bad:
            (log or (lambda _m: None))(f"placement: {host} budget readable again; room {states[host]}")
    return states
