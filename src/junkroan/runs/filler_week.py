"""The first week of fillers, measured (#752): wait, share made ahead, time lost.

Read from the job records (`artifacts/runs/jobs.jsonl`) and the week's folder; nothing is recorded while a build
runs. Pure over its inputs: the jobs, the rows directory and `now` come in as parameters.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from junkroan.report_format import human_duration
from junkroan.runs import run_name

WAIT_LIMIT_S = 60.0
LOST_LIMIT_PCT = 20.0


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _pct(part: float, whole: float) -> int:
    return int(round(100.0 * part / whole)) if whole > 0 else 0


def _row_stems(rows_dir: Path | None) -> list[str]:
    if rows_dir is None or not Path(rows_dir).is_dir():
        return []
    return sorted(p.stem for p in Path(rows_dir).glob("*.json"))


def _makes_row(cmd: str, stem: str) -> bool:
    return re.search(rf"--row\s+{re.escape(stem)}(\s|$)", cmd) is not None


def week_report(jobs: Iterable, host: str, monday: date, rows_dir: Path | None,
                now: datetime | None = None) -> tuple[list[str], int]:
    """The report lines for `host` and the week from `monday` (7 local days, by submit_ts) and the exit code."""

    now = now or datetime.now(timezone.utc)
    lo = datetime(monday.year, monday.month, monday.day).astimezone()
    hi = lo + timedelta(days=7)
    tag = f"week-{monday:%Y%m%d}"
    on_host = [j for j in jobs if j.host == host]

    def in_week(j) -> bool:
        s = _ts(j.submit_ts)
        return s is not None and lo <= s < hi

    fillers = [j for j in on_host if j.is_filler and in_week(j) and _ts(j.start_ts)]
    if not fillers:
        return ["longest wait: 0 s, 0 jobs, no fillers ran",
                "made ahead: 0 of 0 (0 %), no fillers ran",
                "lost time: 0 % (0 s of 0 s), no fillers ran"], 0

    def span(j) -> tuple[datetime, datetime]:
        return _ts(j.start_ts), (_ts(j.end_ts) or now)

    # 1. waits of non-filler jobs submitted while a filler ran on the host
    waits: list[tuple[float, str]] = []
    for j in on_host:
        if j.is_filler or not in_week(j):
            continue
        sub, start = _ts(j.submit_ts), _ts(j.start_ts)
        if start is None:
            continue
        if any(a <= sub < b for a, b in map(span, fillers)):
            waits.append(((start - sub).total_seconds(), j.id))
    lines = []
    if waits:
        worst, wid = max(waits)
        lines.append(f"longest wait: {human_duration(worst)} ({wid}), {len(waits)} jobs")
    else:
        lines.append("longest wait: 0 s, 0 jobs")

    # 2. rows made ahead of the Monday line
    stems = _row_stems(rows_dir)
    mondays = [_ts(j.start_ts) for j in on_host
               if j.tag == tag and not j.is_filler and _ts(j.start_ts)
               and run_name.is_core_command(j.argv or j.cmd)]
    cutoff = min(mondays) if mondays else None
    done = [j for j in fillers if j.tag == tag and j.rc == 0 and _ts(j.end_ts)
            and (cutoff is None or _ts(j.end_ts) < cutoff)]
    ahead = sum(1 for s in stems if any(_makes_row(j.cmd, s) for j in done))
    lines.append(f"made ahead: {ahead} of {len(stems)} ({_pct(ahead, len(stems))} %)")

    # 3. lost time
    total = sum((b - a).total_seconds() for a, b in map(span, fillers))
    lost = sum((b - a).total_seconds() for a, b in map(span, [j for j in fillers if j.state == "stopped"]))
    lost_pct = 100.0 * lost / total if total > 0 else 0.0
    lines.append(f"lost time: {_pct(lost, total)} % ({human_duration(lost)} of {human_duration(total)})")

    if waits and worst > WAIT_LIMIT_S:
        over = max(w for w in waits if w[0] > WAIT_LIMIT_S)
        lines.append(f"over the limit: {over[1]}, {human_duration(over[0])}")
    if lost_pct > LOST_LIMIT_PCT:
        lines.append("lost time over 20 %: open the ticket for a real pause")
    return lines, 0
