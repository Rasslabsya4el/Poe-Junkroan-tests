"""The runs daemon's result marker (#50) -- a local module of this installation (ADR 0109,
extension point 4). The core's dispatcher orders its ready queue oldest first and knows nothing
else; this module puts the issues whose latest comment is a run's result in front of it, so a
finished run is picked up before older work.

The marker string is `junkroan.runs.daemon.RUNS_DAEMON_MARKER`, copied rather than imported
(`tools/agentops` imports no `junkroan`: `worktree.py`'s own note).
"""

from __future__ import annotations

from typing import Any

from .extensions import Registry

#: `daemon.RUNS_DAEMON_MARKER`: the first line of every comment the runs daemon posts with a result.
RUNS_DAEMON_MARKER = "<!-- runs-daemon result -->"


def is_daemon_result(candidate: Any) -> bool:
    """`True` when this candidate's latest comment is a run's result (`IssueSummary.latest_comment`
    holds the body; `""` when the issue has no comment at all)."""

    return str(getattr(candidate, "latest_comment", "") or "").startswith(RUNS_DAEMON_MARKER)


def order(candidates: list) -> list:
    """The dispatcher's own order: results first, then oldest. One function, so whoever shows the
    queue outside the dispatcher orders it the same way instead of copying the rule."""

    return sorted(candidates, key=lambda c: (not is_daemon_result(c), c.created_at))


def _candidates(dispatcher: Any, candidates: list, *, offering: bool) -> list:
    """Only the call that is about to start a session orders the queue; the wake (#137) is left in
    the order the core read it, exactly as before."""

    return order(candidates) if offering else candidates


def register(core: Registry) -> None:
    core.candidates(_candidates)


__all__ = ["RUNS_DAEMON_MARKER", "is_daemon_result", "order", "register"]
