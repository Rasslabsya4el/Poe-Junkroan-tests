"""Token meter weights: `cost_per_closed_issue(session_issue_weights=...)` splits one ORCH session's cost by
the given per-issue shares instead of the equal split; `None` keeps the equal split as before.

The fixture is a synthetic main transcript written to tmp_path (the same JSONL shape as
tests/fixtures/token_meter/projects/sessA.jsonl), read through `scan_projects_dir` with the
session's held issues named by `orch_session_held`, so the turns carry the ORCH split exactly as
the real scan produces it. Prices are a fixture table, so every cost is a round number and the
asserted cents are exact.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import token_meter as tm  # noqa: E402

SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 9, 30, tzinfo=timezone.utc)

SESSION_ID = "orch0001full"  # the session key is its first 8 characters
HELD_A = 9001
HELD_B = 9002
UNHELD = 9003

PRICES = {
    "claude-sonnet-5": {"input": 2.0, "cache_write": 2.5, "cache_read": 0.2, "output": 10.0},
}

# one million input tokens = $2.00, 300,000 output = $3.00, one million cache reads = $0.20:
# the session costs $5.20; A's 25 % is $1.30, B's 75 % is $3.90.
USAGE = [
    {"input_tokens": 1_000_000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0},
    {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 300_000},
    {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1_000_000, "output_tokens": 0},
]


def _write_transcript(projects_dir: Path) -> None:
    lines = [{"type": "custom-title", "customTitle": "orch fixture", "sessionId": SESSION_ID}]
    lines.append({"type": "user", "message": {"role": "user", "content": "continue the batch"},
                  "timestamp": "2026-09-15T09:55:00Z"})
    for i, usage in enumerate(USAGE):
        lines.append({"type": "assistant",
                      "message": {"id": f"msg_{i}", "model": "claude-sonnet-5", "usage": usage},
                      "timestamp": f"2026-09-15T10:0{i}:00Z"})
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / f"{SESSION_ID}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _closed() -> list[dict]:
    return [{"number": HELD_A, "closedAt": "2026-09-20T00:00:00Z"},
            {"number": HELD_B, "closedAt": "2026-09-21T00:00:00Z"}]


@pytest.fixture()
def session_turns(tmp_path: Path) -> list[tm.Turn]:
    projects_dir = tmp_path / "projects"
    _write_transcript(projects_dir)
    scan = tm.scan_projects_dir(projects_dir, orch_session_held={SESSION_ID[:8]: [HELD_A, HELD_B]})
    turns = [t for t in scan.turns if t.session_id == SESSION_ID]
    assert len(turns) == len(USAGE)
    # the scan gives the equal split this unit must replace
    assert all(t.issue_shares == {HELD_A: 0.5, HELD_B: 0.5} for t in turns)
    return turns


def _by_number(costs: list[tm.IssueCost]) -> dict[int, tm.IssueCost]:
    return {ic.number: ic for ic in costs}


def test_mapped_shares_split_the_session_cost_25_75(session_turns: list[tm.Turn]):
    costs = tm.cost_per_closed_issue(
        session_turns, _closed(), PRICES, since=SINCE, until=UNTIL,
        session_issue_weights={SESSION_ID: {HELD_A: 0.25, HELD_B: 0.75}},
    )
    by_number = _by_number(costs)
    total = round(sum(tm.turn_cost(t, PRICES) for t in session_turns), 2)
    assert total == 5.20
    assert round(by_number[HELD_A].cost_usd, 2) == 1.30
    assert round(by_number[HELD_B].cost_usd, 2) == 3.90
    assert round(by_number[HELD_A].cost_usd + by_number[HELD_B].cost_usd, 2) == total


def test_no_weights_keeps_the_equal_split(session_turns: list[tm.Turn]):
    for costs in (
        tm.cost_per_closed_issue(session_turns, _closed(), PRICES, since=SINCE, until=UNTIL),
        tm.cost_per_closed_issue(session_turns, _closed(), PRICES, since=SINCE, until=UNTIL,
                                 session_issue_weights=None),
        # a mapping for some other session changes nothing for this one
        tm.cost_per_closed_issue(session_turns, _closed(), PRICES, since=SINCE, until=UNTIL,
                                 session_issue_weights={"someothersession": {HELD_A: 0.25, HELD_B: 0.75}}),
    ):
        by_number = _by_number(costs)
        assert round(by_number[HELD_A].cost_usd, 2) == 2.60
        assert round(by_number[HELD_B].cost_usd, 2) == 2.60


def test_missing_held_issue_renormalises_the_mapped_shares(session_turns: list[tm.Turn]):
    # the mapping has no entry for HELD_B: the turn's shares restricted to the mapping are
    # {HELD_A: 0.25}, renormalised to {HELD_A: 1.0}, so A carries the whole session cost
    costs = tm.cost_per_closed_issue(
        session_turns, _closed(), PRICES, since=SINCE, until=UNTIL,
        session_issue_weights={SESSION_ID: {HELD_A: 0.25, UNHELD: 0.75}},
    )
    by_number = _by_number(costs)
    assert round(by_number[HELD_A].cost_usd, 2) == 5.20
    assert HELD_B not in by_number
