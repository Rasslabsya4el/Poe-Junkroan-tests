"""#292: an open issue carrying `needs-info` is offered to nobody (ORCH's ready list, the cloud
lane), whatever else it carries. Fakes only, no real `gh` or `claude`."""

from __future__ import annotations

from pathlib import Path

from tests.test_agentops_cloud_lane import (
    FakeClaudeRunner, FakeGhRunner, LANE_ISSUE, _lane, _open_comment,
)
from tests.test_agentops_dispatch import FakeClaude, FakeGh, _dispatcher, _issue
from tools.agentops import cloud_lane as cl
from tools.agentops.dispatch import IssueSummary, NEEDS_INFO_LABEL, READY_LABEL


def _parked(number: int = 290) -> IssueSummary:
    return IssueSummary(number=number, created_at="2026-09-28T00:00:00Z",
                        labels=(READY_LABEL, NEEDS_INFO_LABEL))


def test_row1_ready_and_needs_info_is_offered_zero_times_over_three_ticks(tmp_path: Path):
    claude, gh, messages = FakeClaude(), FakeGh(candidates=[_parked()]), []
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.log = messages.append
    for _ in range(3):
        d.tick()
    assert claude.started == []
    assert sum("skipped as needs-info: #290" in m for m in messages) == 1  # logged once


def test_row2_once_needs_info_is_removed_it_is_offered_at_the_next_tick(tmp_path: Path):
    claude, gh = FakeClaude(), FakeGh(candidates=[_parked()])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.tick()
    assert claude.started == []
    gh._candidates = [IssueSummary(number=290, created_at="2026-09-28T00:00:00Z", labels=(READY_LABEL,))]
    d.tick()
    assert [offered for offered, _ in claude.started] == [[290]]


def test_row3_ready_for_agent_alone_is_offered_as_today(tmp_path: Path):
    claude, gh = FakeClaude(), FakeGh(candidates=[_issue(5, 5)])
    _dispatcher(tmp_path, claude=claude, gh=gh).tick()
    assert [offered for offered, _ in claude.started] == [[5]]


def test_row4_the_cloud_lane_does_not_offer_a_needs_info_issue(tmp_path: Path):
    gh, claude, messages = FakeGhRunner(), FakeClaudeRunner(), []
    gh.add(LANE_ISSUE, labels=(cl.LANE_LABEL,), comments=[_open_comment()])
    gh.add(290, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL, NEEDS_INFO_LABEL))
    gh.add(291, labels=(cl.READY_LABEL, cl.POB_FREE_LABEL))
    lane = _lane(tmp_path, gh, claude, messages=messages)
    assert lane._candidates({}) == [291]
    assert any("#290 (needs-info)" in m for m in messages)
