"""#686: a job whose ticket is closed is stopped (running) or cancelled (queued).

The rule is pure; the daemon reads the issue states (one bounded ``gh`` call per distinct issue) and
applies the actions. A job is exempt when it was submitted ``--outlives-ticket``, names no issue
(``--no-issue``), or is the weekly core run.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from junkroan.runs import run_name
from junkroan.runs.store import Job

#: The PC daemon looks at the tickets this often (not every 10 s tick).
TICKET_CHECK_SECONDS = 300.0


def watched(job: Job) -> bool:
    """Whether the rule applies to ``job`` at all."""

    if job.state not in ("running", "queued") or job.outlives_ticket or not job.all_issues:
        return False
    return not run_name.is_core_command(job.argv if getattr(job, "argv", None) else job.cmd)


def issues_to_read(jobs: Iterable[Job]) -> list[int]:
    """Distinct issues of the watched jobs, in first-seen order."""

    seen: dict[int, None] = {}
    for job in jobs:
        if watched(job):
            for n in job.all_issues:
                seen.setdefault(n, None)
    return list(seen)


def closed_ticket_actions(jobs: Iterable[Job], states: Mapping[int, str | None]) -> list[tuple[Job, str, str]]:
    """``(job, 'stop'|'cancel', reason)`` for every watched job whose issues are ALL closed."""

    out: list[tuple[Job, str, str]] = []
    for job in jobs:
        if not watched(job):
            continue
        if not all(str(states.get(n) or "").upper() == "CLOSED" for n in job.all_issues):
            continue
        out.append((job, "stop" if job.state == "running" else "cancel", f"ticket #{job.all_issues[0]} closed"))
    return out
