"""#1053: how many builds a job's command can run at most, when the command itself says.

A pool of N workers over fewer than N builds never claims its last slots, so the run queue charges such a job
``min(declared workers, builds)`` (`Daemon._declared_cost`). Only a ``scripts/benchmark.py`` command whose build
list is fixed by its own words is read: explicit slugs, no ``--set`` / ``--resume`` / ``--rereport`` / ``--row`` /
``--missing`` / ``--pobbin-backfill``, and no keystone variants (those add builds after the base rows ran).
Everything else gives ``None`` and the charge stays the declared workers.

The flag lists mirror ``scripts/benchmark.py``'s parser; ``tests/test_issue1053_slot_overcount.py`` compares them
with the parser's source, so a new option cannot drift unnoticed (an unknown option gives ``None``).
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable

#: Options of ``scripts/benchmark.py`` that take one value (``--flag v`` or ``--flag=v``).
VALUE_FLAGS: frozenset[str] = frozenset({
    "--set", "--workers", "--gear", "--construction", "--reopt-rounds", "--seed", "--seeds", "--force-keystone",
    "--tree-depth", "--tree-trials", "--ablate", "--tag", "--stat", "--loop-seconds", "--record-calls",
    "--rereport", "--resume", "--row", "--pobbin-backfill",
})
#: Options of ``scripts/benchmark.py`` that take no value.
SWITCH_FLAGS: frozenset[str] = frozenset({
    "--construction-only", "--no-variants", "--loop", "--cluster-candidates", "--missing",
    "--skip-inert", "--no-skip-inert", "--fulldps-shortcut", "--no-fulldps-shortcut",
    "--fixed-point-check", "--no-fixed-point-check",
})
#: Options that make the build list something the command line does not fix.
_OPEN_LIST_FLAGS = ("--set", "--resume", "--rereport", "--row", "--missing", "--pobbin-backfill")


def _tokens(cmd: str | None, argv: Iterable[str] | None) -> list[str]:
    if argv:
        return [str(a) for a in argv]
    if not cmd:
        return []
    try:
        toks = shlex.split(cmd, posix=False)
    except ValueError:
        toks = cmd.split()
    return [t.strip("\"'") for t in toks]


def builds_in_command(cmd: str | None, argv: Iterable[str] | None = None) -> int | None:
    """The number of builds a ``scripts/benchmark.py`` command runs, or ``None`` when its words do not fix it."""

    toks = _tokens(cmd, argv)
    start = next((i for i, t in enumerate(toks) if t.replace("\\", "/").endswith("scripts/benchmark.py")), None)
    if start is None:
        return None
    slugs: list[str] = []
    seen: dict[str, str | None] = {}
    i = start + 1
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not tok.startswith("-") or tok == "-":
            slugs.append(tok)
            continue
        flag, eq, value = tok.partition("=")
        if flag in SWITCH_FLAGS and not eq:
            seen[flag] = None
        elif flag in VALUE_FLAGS:
            if not eq:
                if i >= len(toks):
                    return None
                value = toks[i]
                i += 1
            seen[flag] = value
        else:
            return None  # an option this reader does not know: the list is not derivable
    if not slugs or any(flag in seen for flag in _OPEN_LIST_FLAGS):
        return None
    if not any(flag in seen for flag in ("--no-variants", "--construction-only", "--force-keystone")):
        return None  # D40 variants add builds after the base rows: only a lower bound
    seeds = seen.get("--seeds", "1")
    if seeds is None or not seeds.isdigit() or int(seeds) < 1:
        return None
    return len(slugs) * int(seeds)
