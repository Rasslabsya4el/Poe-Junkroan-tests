"""tools/agentops/runs_marker.py (issue #50; a local module since #150, ADR 0109 point 4): a ready
issue whose latest comment is a runs-daemon result is offered before older plain ones.

The test moved here from `test_agentops_dispatch.py` unchanged, with the ORCH fakes and the one-tick
helper imported from that file rather than copied: the rule is measured on the real dispatcher loop,
and this file needs this repo's `local_modules` (the core alone has no such rule).
"""

from __future__ import annotations

from pathlib import Path

from test_agentops_dispatch import _events, _start

from tools.agentops.dispatch import IssueSummary
from tools.agentops.runs_marker import RUNS_DAEMON_MARKER


def _issue(number: int, day: int = 1, *, result: bool = False) -> IssueSummary:
    """`test_agentops_dispatch.py`'s own helper, with the latest comment the marker rule reads."""

    return IssueSummary(number=number, created_at=f"2026-09-{day:02d}T00:00:00Z",
                        latest_comment=f"{RUNS_DAEMON_MARKER}\nrun 42 finished" if result else "")


def test_a_runs_daemon_result_issue_is_offered_before_an_older_plain_one(tmp_path: Path):
    claude, _, _, live_id = _start(tmp_path, [_issue(10, 1), _issue(20, 20, result=True)])

    assert claude.started[0][0] == [20, 10]
    events = _events(tmp_path)
    assert events[0]["kind"] == "orch_start" and events[0]["issues"] == [20, 10] and events[0]["session"] == live_id
