"""Refuse a submit that repeats a job already queued, running or done (#468).

Two jobs are the same run when the pin's `src/junkroan` tree hash and the command (ignoring
`--workers N` and `--tag X`, which change neither the number nor the code) are equal. The host is
ignored: a run on either host gives the same number. A job with no pin, or a pin git cannot
resolve, never matches: the check never refuses on a guess.
"""

from __future__ import annotations

import shlex
from typing import Callable, Iterable

from junkroan.runs.store import Job

DEDUPE_STATES = ("queued", "running", "done")
_VALUE_FLAGS = ("--workers", "--tag")


def normalized_argv(argv: Iterable[str]) -> tuple[str, ...]:
    """The command's argv without `--workers N` / `--workers=N` / `--tag X` / `--tag=X`."""
    out: list[str] = []
    skip = False
    for a in argv:
        if skip:
            skip = False
        elif a in _VALUE_FLAGS:
            skip = True
        elif not a.startswith(tuple(f"{f}=" for f in _VALUE_FLAGS)):
            out.append(a)
    return tuple(out)


def _job_argv(job: Job) -> list[str]:
    if job.argv:
        return list(job.argv)
    try:
        return shlex.split(job.cmd, posix=False)
    except ValueError:
        return [job.cmd]


def find_identical(
    jobs: Iterable[Job], *, pin: str | None, argv: Iterable[str],
    tree_hash: Callable[[str], str | None],
) -> Job | None:
    """The first job in queued/running/done with the same tree hash and command, else None.

    `pin` None is the new job's own start pin, HEAD; an existing job without a pin never matches.
    """
    wanted_cmd = normalized_argv(argv)
    cache: dict[str, str | None] = {}

    def tree(p: str) -> str | None:
        if p not in cache:
            try:
                cache[p] = tree_hash(p)
            except Exception:
                cache[p] = None
        return cache[p]

    mine = tree(pin or "HEAD")
    if not mine:
        return None
    for job in jobs:
        if job.state not in DEDUPE_STATES or not job.pin:
            continue
        if normalized_argv(_job_argv(job)) != wanted_cmd:
            continue
        if tree(job.pin) == mine:
            return job
    return None
