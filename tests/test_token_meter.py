"""Tests for scripts/token_meter.py (#47): dedupe, context arithmetic, attribution,
compaction count, price arithmetic, and a gh fake. No network; fixture transcripts only.

Fixture layout (tests/fixtures/token_meter/):
  projects/sessA.jsonl                        main chat, titled "poe-junkroan-v2 Orch"
  projects/sessB.jsonl                        main chat, no title (classified from its first message)
  projects/sessA/subagents/agent-x1.jsonl(+.meta.json)   first prompt names #47
  projects/sessA/subagents/agent-x2.jsonl(+.meta.json)   first prompt names #6 and #9 (ambiguous)
  projects/sessA/subagents/agent-x3.jsonl(+.meta.json)   first prompt names #9
  prices.json                                  fixture price table, "claude-unknown-model" absent on purpose

The exact numbers below were computed by hand from the fixture files; see the comment above
each assertion for the arithmetic.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import token_meter as tm  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "token_meter"
PROJECTS_DIR = FIXTURES / "projects"
PRICES_PATH = FIXTURES / "prices.json"

# fixtures/token_meter_multi/ (#64): a multi-issue ORCH session with two held issues (#54,
# #55) and two subagents, plus a brain session -- kept in a separate directory so they do not
# perturb fixtures/token_meter/'s hand-computed whole-fixture totals above.
MULTI_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "token_meter_multi"
MULTI_PROJECTS_DIR = MULTI_FIXTURES / "projects"

WINDOW_SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
WINDOW_UNTIL = datetime(2026, 9, 30, tzinfo=timezone.utc)


@pytest.fixture()
def prices() -> dict:
    return tm.load_prices(PRICES_PATH)


@pytest.fixture()
def scan() -> tm.ScanResult:
    return tm.scan_projects_dir(PROJECTS_DIR)


# ------------------------------------------------------------------------------ issue text ----


def test_single_issue_exactly_one():
    assert tm.single_issue("see #47") == 47


def test_single_issue_ambiguous_is_none():
    assert tm.single_issue("see #6 and #9") is None


def test_single_issue_none_mentioned():
    assert tm.single_issue("nothing here") is None


def test_single_issue_repeated_same_number_counts_once():
    # two mentions of the SAME issue are not ambiguous -- one distinct number.
    assert tm.single_issue("about #6, still #6") == 6


# ------------------------------------------------------------------------------- dedupe ----


def test_main_chat_dedupes_by_message_id():
    parsed = tm.parse_main_transcript(PROJECTS_DIR / "sessA.jsonl")
    # 5 distinct message ids in sessA.jsonl (msg_1..msg_5); msg_1's second line is a duplicate,
    # same input/cache as the first but a bigger output_tokens (45 vs 30, like a real streamed
    # message -- #259's finding: input/cache_write/cache_read stay equal, only output differs).
    assert [t.message_id for t in parsed.turns] == ["msg_1", "msg_2", "msg_3", "msg_4", "msg_5"]
    # #259: the LAST line of a message.id wins, every kind -- here that means the bigger output.
    msg_1 = parsed.turns[0]
    assert msg_1.input_tokens == 100
    assert msg_1.context == 100 + 50 + 200
    assert msg_1.output_tokens == 45


def test_subagent_dedupes_by_message_id():
    turns = tm.parse_subagent_transcript(
        PROJECTS_DIR / "sessA" / "subagents" / "agent-x1.jsonl",
        {"agentType": "effort-medium", "agentId": "x1"},
    )
    assert [t.message_id for t in turns] == ["msg_s1", "msg_s2"]
    # #259: the LAST line of msg_s1 wins -- same input/cache as the first line, but output
    # 350 (the whole turn), not 200 (the tokens written so far on the first streamed line).
    assert turns[0].context == 2000 + 1000 + 3000
    assert turns[0].output_tokens == 350


def test_dedupe_takes_output_tokens_from_the_last_line_of_a_message(tmp_path: Path):
    # #259 acceptance row 1: a message.id streamed over 3 lines, output tokens 5, 40, 120 --
    # the turn's output is the LAST line's (120), for both parsers.
    import json as _json

    lines = [
        {"type": "user", "message": {"role": "user", "content": "work on #259"},
         "timestamp": "2026-09-28T10:00:00Z"},
        {"type": "assistant", "timestamp": "2026-09-28T10:00:01Z",
         "message": {"id": "msg_stream", "model": "claude-sonnet-5",
                     "usage": {"input_tokens": 100, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0, "output_tokens": 5}}},
        {"type": "assistant", "timestamp": "2026-09-28T10:00:02Z",
         "message": {"id": "msg_stream", "model": "claude-sonnet-5",
                     "usage": {"input_tokens": 100, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0, "output_tokens": 40}}},
        {"type": "assistant", "timestamp": "2026-09-28T10:00:03Z",
         "message": {"id": "msg_stream", "model": "claude-sonnet-5",
                     "usage": {"input_tokens": 100, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0, "output_tokens": 120}}},
    ]

    main_path = tmp_path / "main.jsonl"
    main_path.write_text("\n".join(_json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    parsed = tm.parse_main_transcript(main_path)
    assert [t.message_id for t in parsed.turns] == ["msg_stream"]
    assert parsed.turns[0].output_tokens == 120

    sub_path = tmp_path / "agent-y.jsonl"
    sub_path.write_text("\n".join(_json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    sub_turns = tm.parse_subagent_transcript(sub_path, {"agentType": "worker", "agentId": "y"})
    assert [t.message_id for t in sub_turns] == ["msg_stream"]
    assert sub_turns[0].output_tokens == 120


# --------------------------------------------------------------------------- context math ----


def test_turn_context_is_input_plus_cache_read_plus_cache_creation():
    turn = tm.Turn(
        session_id="s",
        agent_id=None,
        agent_type=None,
        message_id="m",
        model="claude-sonnet-5",
        timestamp=None,
        input_tokens=10,
        cache_creation_input_tokens=5,
        cache_read_input_tokens=1000,
        output_tokens=15,
        issue=None,
        title=None,
        turn_index=0,
    )
    assert turn.context == 1015


# ---------------------------------------------------------------------------- attribution ----


def test_main_chat_attribution_tracks_latest_unambiguous_issue():
    parsed = tm.parse_main_transcript(PROJECTS_DIR / "sessA.jsonl")
    by_id = {t.message_id: t.issue for t in parsed.turns}
    assert by_id["msg_1"] == 47  # after "Please work on #47..."
    assert by_id["msg_2"] == 47  # "no issue mentioned here" does not change it
    assert by_id["msg_3"] == 47  # "#6 and #9" is ambiguous, ignored
    assert by_id["msg_4"] == 6  # "moving to #6" is unambiguous
    assert by_id["msg_5"] == 6


def test_subagent_attribution_from_first_prompt():
    x1 = tm.parse_subagent_transcript(
        PROJECTS_DIR / "sessA" / "subagents" / "agent-x1.jsonl",
        {"agentType": "effort-medium", "agentId": "x1"},
    )
    assert all(t.issue == 47 for t in x1)

    x2 = tm.parse_subagent_transcript(
        PROJECTS_DIR / "sessA" / "subagents" / "agent-x2.jsonl",
        {"agentType": "effort-medium", "agentId": "x2"},
    )
    assert all(t.issue is None for t in x2)  # first prompt names #6 and #9: ambiguous


def test_unattributed_share_over_the_whole_fixture(scan: tm.ScanResult):
    # unattributed context = sessB's msg_b1 (3500) + subagent x2's msg_s3 (3000) = 6500
    # total context = 14643 (see the module docstring's worked arithmetic in the PR)
    share, unattributed_ctx, total_ctx = tm.unattributed_share(
        scan.turns, since=WINDOW_SINCE, until=WINDOW_UNTIL
    )
    assert unattributed_ctx == 6500
    assert total_ctx == 14643
    assert share == pytest.approx(6500 / 14643)


# ----------------------------------------------------------------------------- compaction ----


def test_compaction_count():
    sess_a = tm.parse_main_transcript(PROJECTS_DIR / "sessA.jsonl")
    assert sess_a.compactions == 1
    sess_b = tm.parse_main_transcript(PROJECTS_DIR / "sessB.jsonl")
    assert sess_b.compactions == 0


# ------------------------------------------------------------------------------- pricing ----


def test_turn_cost_known_model(prices: dict):
    turn = tm.Turn(
        session_id="s", agent_id=None, agent_type=None, message_id="m",
        model="claude-haiku-4-5-20251001", timestamp=None,
        input_tokens=5, cache_creation_input_tokens=5, cache_read_input_tokens=5, output_tokens=5,
        issue=None, title=None, turn_index=0,
    )
    # (5*1 + 5*1.25 + 5*0.10 + 5*5) / 1e6 = 36.75 / 1e6
    assert tm.turn_cost(turn, prices) == pytest.approx(36.75 / 1_000_000)


def test_turn_cost_unpriced_model_is_none(prices: dict):
    turn = tm.Turn(
        session_id="s", agent_id=None, agent_type=None, message_id="m",
        model="claude-unknown-model", timestamp=None,
        input_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=50,
        issue=None, title=None, turn_index=0,
    )
    assert tm.turn_cost(turn, prices) is None


@pytest.fixture()
def real_prices() -> dict:
    """The shipped config/model_prices.json (the fixture prices.json has no 1h rates)."""
    return tm.load_prices(tm.DEFAULT_PRICES_PATH)


def _priced_turn(model: str, usage: dict) -> tm.Turn:
    """A turn built by the meter's own transcript parser from a usage dict (#637)."""

    obj = {"message": {"id": "m", "model": model, "usage": usage}}
    turn = tm._usage_turn(
        obj, session_id="s", agent_id=None, agent_type=None,
        issue=None, title=None, turn_index=0,
    )
    assert turn is not None
    return turn


def test_turn_cost_splits_the_cache_write_into_5m_and_1h(real_prices: dict):
    turn = _priced_turn("claude-opus-5-5", {
        "cache_creation_input_tokens": 15_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 5_000, "ephemeral_1h_input_tokens": 10_000},
    })
    # Opus 5.5: 10,000 * 8 / 1e6 = $0.08 (1h) + 5,000 * 5 / 1e6 = $0.025 (5m) = $0.105
    assert tm.turn_cost(turn, real_prices) == pytest.approx(0.105)


def test_turn_cost_without_cache_creation_object_bills_the_whole_write_as_5m(real_prices: dict):
    turn = _priced_turn("claude-opus-5-5", {"cache_creation_input_tokens": 15_000})
    # Opus 5.5: 15,000 * 5 / 1e6 = $0.075 (all 5m, today's behaviour)
    assert tm.turn_cost(turn, real_prices) == pytest.approx(0.075)


def test_turn_cost_haiku_5_5_above_100k_prices_every_kind_at_the_second_tier(real_prices: dict):
    turn = _priced_turn("claude-haiku-5-5", {
        "input_tokens": 10_000, "cache_read_input_tokens": 100_000,
        "cache_creation_input_tokens": 10_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 6_000, "ephemeral_1h_input_tokens": 4_000},
        "output_tokens": 2_000,
    })
    # prompt = 10k + 100k + 10k = 120k > 100k -> second tier, output included:
    # 10,000*0.50 + 6,000*0.625 + 4,000*1.00 + 100,000*0.05 + 2,000*2.50 = 5,000 + 3,750 + 4,000
    # + 5,000 + 5,000 = 22,750 / 1e6
    assert tm.turn_cost(turn, real_prices) == pytest.approx(0.02275)


def test_turn_cost_haiku_5_5_at_80k_prices_every_kind_at_the_first_tier(real_prices: dict):
    turn = _priced_turn("claude-haiku-5-5", {
        "input_tokens": 10_000, "cache_read_input_tokens": 60_000,
        "cache_creation_input_tokens": 10_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 6_000, "ephemeral_1h_input_tokens": 4_000},
        "output_tokens": 2_000,
    })
    # prompt = 80k <= 100k -> first tier:
    # 10,000*0.10 + 6,000*0.125 + 4,000*0.20 + 60,000*0.01 + 2,000*0.50 = 1,000 + 750 + 800
    # + 600 + 1,000 = 4,150 / 1e6
    assert tm.turn_cost(turn, real_prices) == pytest.approx(0.00415)


def test_turn_cost_sonnet_5_5_cache_read_is_ten_cents(real_prices: dict):
    turn = _priced_turn("claude-sonnet-5-5", {"cache_read_input_tokens": 1_000_000})
    assert tm.turn_cost(turn, real_prices) == pytest.approx(0.10)


def test_turn_cost_unknown_model_with_cache_creation_object_is_none(real_prices: dict):
    turn = _priced_turn("claude-nonexistent-9", {
        "cache_creation_input_tokens": 100,
        "cache_creation": {"ephemeral_1h_input_tokens": 100},
    })
    assert tm.turn_cost(turn, real_prices) is None


# --------------------------------------------------------------------- the four numbers ----


def test_subagent_first_turn_context_median_per_agent_type(scan: tm.ScanResult):
    # effort-medium: agent-x1 first turn = 2000+1000+3000 = 6000, agent-x2 first turn = 3000+0+0 = 3000
    # median(6000, 3000) = 4500
    # opus5-high: agent-x3 first turn = 500 -> median 500
    by_type = tm.subagent_first_turn_context_by_type(scan, since=WINDOW_SINCE, until=WINDOW_UNTIL)
    assert by_type["effort-medium"] == pytest.approx(4500)
    assert by_type["opus5-high"] == pytest.approx(500)


def test_classify_chat_by_title_and_by_fallback_first_message():
    assert tm.classify_chat("poe-junkroan-v2 Orch", brain_pattern="opus|fable", orch_pattern="orch") == "ORCH"
    assert tm.classify_chat("poe-junkroan-v2 opus 5.5", brain_pattern="opus|fable", orch_pattern="orch") == "brain"
    assert tm.classify_chat(None, brain_pattern="opus|fable", orch_pattern="orch") is None
    assert tm.classify_chat("Ничего не делай, жди", brain_pattern="opus|fable", orch_pattern="orch") is None


def test_weekly_median_context_brain_vs_orch(scan: tm.ScanResult):
    # ORCH = sessA (title "poe-junkroan-v2 Orch"):
    #   week 2026-W37: msg_1 (350), msg_2 (1015) -> median 682.5
    #   week 2026-W38: msg_3 (3), msg_4 (15), msg_5 (100) -> median 15
    # brain = sessB (untitled, classified from its first message "...opus 5.5 lead session..."):
    #   week 2026-W38: msg_b1 (3500) -> median 3500
    weekly = tm.weekly_median_context(
        scan.turns, since=WINDOW_SINCE, until=WINDOW_UNTIL, brain_pattern="opus|fable", orch_pattern="orch"
    )
    assert weekly[("ORCH", "2026-W37")] == pytest.approx(682.5)
    assert weekly[("ORCH", "2026-W38")] == pytest.approx(15)
    assert weekly[("brain", "2026-W38")] == pytest.approx(3500)


def test_cost_per_closed_issue(scan: tm.ScanResult, prices: dict):
    closed_issues = [
        {"number": 47, "closedAt": "2026-09-21T00:00:00Z"},
        {"number": 6, "closedAt": "2026-09-22T00:00:00Z"},
    ]
    costs = tm.cost_per_closed_issue(scan.turns, closed_issues, prices, since=WINDOW_SINCE, until=WINDOW_UNTIL)
    by_number = {ic.number: ic for ic in costs}

    # issue #47: main msg_1 (0.00159, output 45 per #259's last-line-wins dedupe)
    #          + msg_2 (0.0003825) + msg_3 (0.0000292)
    #          + subagent msg_s1 (0.0106, output 350) + msg_s2 (0.000345) = 0.0129467
    assert by_number[47].cost_usd == pytest.approx(0.0129467, rel=1e-6)
    assert by_number[47].turns == 5
    assert by_number[47].unpriced_turns == 0

    # issue #6: main msg_4 (0.00003675, priced) + msg_5 (unpriced model, 0 contribution, counted unpriced)
    assert by_number[6].cost_usd == pytest.approx(0.00003675, rel=1e-6)
    assert by_number[6].turns == 2
    assert by_number[6].unpriced_turns == 1

    # sorted by cost descending
    assert [ic.number for ic in costs] == [47, 6]


def test_claude_md_kb_reads_real_file_size():
    kb = tm.claude_md_kb(ROOT / "CLAUDE.md")
    assert kb is not None
    assert kb > 1  # CLAUDE.md is a real, non-trivial file
    assert kb == pytest.approx((ROOT / "CLAUDE.md").stat().st_size / 1024.0)


def test_claude_md_kb_missing_file_is_none(tmp_path: Path):
    assert tm.claude_md_kb(tmp_path / "does-not-exist.md") is None


# ------------------------------------------------------------------------------- gh fake ----


def test_fetch_closed_issues_uses_injected_runner():
    calls = []

    def fake_runner(args: list[str]) -> str:
        calls.append(args)
        return '[{"number": 47, "closedAt": "2026-09-21T00:00:00Z"}, {"number": 6, "closedAt": "2026-09-22T00:00:00Z"}]'

    result = tm.fetch_closed_issues("Rasslabsya4el/Poe-Junkroan", runner=fake_runner)
    assert result == [
        {"number": 47, "closedAt": "2026-09-21T00:00:00Z"},
        {"number": 6, "closedAt": "2026-09-22T00:00:00Z"},
    ]
    # the fake never shells out to a real `gh`; confirm the CLI shape it was asked to run.
    assert calls[0][:3] == ["issue", "list", "--repo"]
    assert "closed" in calls[0]


def test_fetch_closed_issues_bad_json_returns_empty_list():
    result = tm.fetch_closed_issues("x/y", runner=lambda args: "not json")
    assert result == []


# ---------------------------------------------------------------------------- discovery ----


def test_discover_main_and_subagent_transcripts():
    main_files = tm.discover_main_transcripts(PROJECTS_DIR)
    assert {p.name for p in main_files} == {"sessA.jsonl", "sessB.jsonl"}

    sub_files = tm.discover_subagent_transcripts(PROJECTS_DIR)
    assert {p.name for p, _meta in sub_files} == {"agent-x1.jsonl", "agent-x2.jsonl", "agent-x3.jsonl"}
    metas = {p.name: meta for p, meta in sub_files}
    assert metas["agent-x1.jsonl"]["agentType"] == "effort-medium"
    assert metas["agent-x3.jsonl"]["agentType"] == "opus5-high"


def test_scan_projects_dir_owning_session_for_subagents(scan: tm.ScanResult):
    subagent_turns = [t for t in scan.turns if t.is_subagent]
    assert subagent_turns  # non-empty
    assert all(t.session_id == "sessA" for t in subagent_turns)


def test_load_agentops_missing_file_is_empty_list(tmp_path: Path):
    assert tm.load_agentops(tmp_path / "agentops.jsonl") == []


def test_load_agentops_reads_rows(tmp_path: Path):
    path = tmp_path / "agentops.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    assert tm.load_agentops(path) == [{"a": 1}, {"b": 2}]


# -- ORCH context threshold (#60) ---------------------------------------------------------------

def _orch_transcript(path: Path, title: str, contexts: list[int], claims: list[int], start_hour: int,
                      failed_claims: list[int] | None = None) -> None:
    import json as _json
    failed_claims = failed_claims or []
    lines = [{"type": "custom-title", "customTitle": title}]
    for i, ctx in enumerate(contexts):
        content = []
        tool_id = f"tool-{path.stem}-{i}"
        claimed_here = i < len(claims)
        failed_here = i < len(failed_claims)
        if claimed_here:
            content.append({"type": "tool_use", "id": tool_id, "name": "Bash",
                            "input": {"command": f"gh issue edit {claims[i]} --add-assignee @me && echo ok"}})
        elif failed_here:
            content.append({"type": "tool_use", "id": tool_id, "name": "Bash",
                            "input": {"command": f"gh issue edit {failed_claims[i]} --add-assignee @me"}})
        lines.append({"type": "assistant", "timestamp": f"2026-09-20T{start_hour:02d}:{i:02d}:00Z",
                      "message": {"id": f"{path.stem}-{i}", "model": "claude-opus-5-5", "content": content,
                                  "usage": {"input_tokens": ctx, "cache_read_input_tokens": 0,
                                            "cache_creation_input_tokens": 0, "output_tokens": 1}}})
        if claimed_here:
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": "ok", "is_error": False}]}})
        elif failed_here:
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": "gh: not found",
                 "is_error": True}]}})
    path.write_text("\n".join(_json.dumps(l) for l in lines) + "\n", encoding="utf-8")


def test_orch_threshold_b_x_and_t(tmp_path: Path):
    _orch_transcript(tmp_path / "a.jsonl", "orch #1", [40_000, 60_000, 90_000], [1], 10)
    _orch_transcript(tmp_path / "b.jsonl", "orch #2 #3", [50_000, 70_000, 110_000], [2, 3], 11)
    _orch_transcript(tmp_path / "c.jsonl", "orch #4", [46_000, 76_000], [], 12)  # no claim seen: 1 issue
    _orch_transcript(tmp_path / "d.jsonl", "Orch", [10_000, 900_000], [], 13)  # the old chat, not ORCH

    profiles = [tm.orch_profile(p) for p in sorted(tmp_path.glob("*.jsonl"))]
    assert profiles[3] is None
    assert [(p.taken, p.per_issue) for p in profiles[:3]] == [(1, 50_000), (2, 30_000), (1, 30_000)]
    assert tm.orch_threshold(profiles[:3]) == (46_000, 30_000)

    since = datetime(2026, 9, 19, tzinfo=timezone.utc)
    until = datetime(2026, 9, 21, tzinfo=timezone.utc)
    now = datetime(2026, 9, 20, 12, 3, tzinfo=timezone.utc)  # c.jsonl's last turn was 2 min ago: live
    report = tm.render_orch_threshold(tmp_path, since=since, until=until, now=now)
    assert "2 finished ORCH contexts" in report
    assert "B (median context right after the start) = 45.0k" in report
    assert "X (median context one issue adds)        = 40.0k" in report
    assert "N=3 165.0k" in report
    assert "live ORCH c (orch #4): context 76.0k, 1 issue(s) taken, T(1) = 85.0k: under T" in report


def test_claimed_issues_real_orch_transcript_6db364a2():
    # #193: the real 6db364a2 transcript, cut to its three claim tool calls and their results
    # (`gh issue edit 147 --add-assignee`, the `for n in 156..163; do ...; done` loop, `gh issue
    # edit 167 --add-assignee`). Before the fix N was 2 (147, 167): the loop's `$n` never matched
    # the literal-digit CLAIM_RE.
    path = FIXTURES.parent / "token_meter_193" / "6db364a2_claims.jsonl"
    assert tm._claimed_issues(path) == {147, 156, 157, 158, 159, 160, 161, 162, 163, 167}


def test_claimed_issues_failed_claim_not_counted(tmp_path: Path):
    _orch_transcript(tmp_path / "e.jsonl", "orch #99", [40_000], [], 10, failed_claims=[99])
    assert tm._claimed_issues(tmp_path / "e.jsonl") == set()


def test_claimed_issues_number_quoted_in_another_command_not_counted(tmp_path: Path):
    import json as _json
    lines = [
        {"type": "custom-title", "customTitle": "orch #1"},
        {"type": "assistant", "timestamp": "2026-09-20T10:00:00Z",
         "message": {"id": "f-0", "model": "claude-opus-5-5", "content": [
             {"type": "tool_use", "id": "tool-f-0", "name": "Bash", "input": {
                 "command": 'gh issue comment 5 --body "note: gh issue edit 60 --add-assignee '
                            '@me was run by mistake"'}}],
             "usage": {"input_tokens": 40_000, "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "output_tokens": 1}}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-f-0", "content": "ok", "is_error": False}]}},
    ]
    path = tmp_path / "f.jsonl"
    path.write_text("\n".join(_json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    assert tm._claimed_issues(path) == set()


def test_claimed_issues_for_loop_over_shell_variable(tmp_path: Path):
    import json as _json
    lines = [
        {"type": "custom-title", "customTitle": "orch #1"},
        {"type": "assistant", "timestamp": "2026-09-20T10:00:00Z",
         "message": {"id": "g-0", "model": "claude-opus-5-5", "content": [
             {"type": "tool_use", "id": "tool-g-0", "name": "Bash", "input": {
                 "command": 'for n in 5 6 7; do gh issue edit $n --add-assignee @me '
                            '>/dev/null && echo "claimed $n"; done'}}],
             "usage": {"input_tokens": 40_000, "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "output_tokens": 1}}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-g-0",
             "content": "claimed 5\nclaimed 6\nclaimed 7", "is_error": False}]}},
    ]
    path = tmp_path / "g.jsonl"
    path.write_text("\n".join(_json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    assert tm._claimed_issues(path) == {5, 6, 7}


# ------------------------------------------------------------- multi-issue ORCH (#64) ----
#
# fixtures/token_meter_multi/projects/:
#   sessC.jsonl               titled "orch #54 #55"; first prompt names #54 and #55 (its held
#                             issues). msg_c1 (400 ctx, opus-5-5): no unambiguous single issue
#                             yet -- splits 50/50 over {54, 55}. msg_c2 (600 ctx, opus-5-5):
#                             the user line "orch sessC claimed #54" names #54 alone -- the
#                             better signal wins outright, all of it to #54.
#   sessC/subagents/agent-y1  first prompt "Issue #55 ... Also see #54" -- ambiguous under the
#                             plain single_issue rule (two distinct #N), but #55 is the first
#                             one that is also held -> attributed to #55.
#   sessC/subagents/agent-y2  first prompt "Issue #54 ... Also see #55" -> attributed to #54.
#   sessD.jsonl               titled "Настройка оркестрации" (the brain chat); one turn,
#                             4000 ctx, no issue mentioned anywhere.


@pytest.fixture()
def multi_scan() -> tm.ScanResult:
    return tm.scan_projects_dir(MULTI_PROJECTS_DIR)


def test_orch_session_splits_equally_absent_a_better_signal(multi_scan: tm.ScanResult):
    main_turns = {t.message_id: t for t in multi_scan.turns if t.session_id == "sessC" and not t.is_subagent}
    assert main_turns["msg_c1"].issue is None
    assert main_turns["msg_c1"].issue_shares == {54: 0.5, 55: 0.5}
    # msg_c2's latest user line names #54 alone: the better signal, no split.
    assert main_turns["msg_c2"].issue == 54
    assert main_turns["msg_c2"].issue_shares is None


def test_subagent_attribution_prefers_first_held_issue_in_prompt(multi_scan: tm.ScanResult):
    by_agent = {t.agent_id: t.issue for t in multi_scan.turns if t.is_subagent}
    assert by_agent["y1"] == 55  # "Issue #55 ... Also see #54" -- 55 is held and first
    assert by_agent["y2"] == 54  # "Issue #54 ... Also see #55" -- 54 is held and first


def test_multi_issue_orch_rows_sum_to_orch_plus_subagents(multi_scan: tm.ScanResult, prices: dict):
    rows = tm.grouped_table(multi_scan.turns, prices, by="issue", since=WINDOW_SINCE, until=WINDOW_UNTIL)
    by_key = {r.key: r for r in rows}

    # #54 = ORCH's msg_c2 (0.0024, all of it) + ORCH's msg_c1 share (0.0016 * 0.5 = 0.0008)
    #     + agent-y2 (2000*2.0 + 200*10.0, /1e6 = 0.006) = 0.0092
    assert by_key["#54"].cost_usd == pytest.approx(0.0092)
    assert by_key["#54"].context == 2800  # 600 + 200 + 2000

    # #55 = ORCH's msg_c1 share (0.0008) + agent-y1 (1000*2.0 + 100*10.0, /1e6 = 0.003) = 0.0038
    assert by_key["#55"].cost_usd == pytest.approx(0.0038)
    assert by_key["#55"].context == 1200  # 200 + 1000

    orch_turns = [t for t in multi_scan.turns if t.session_id == "sessC" and not t.is_subagent]
    subagent_turns = [t for t in multi_scan.turns if t.is_subagent]
    orch_cost = sum(tm.turn_cost(t, prices) for t in orch_turns)
    subagent_cost = sum(tm.turn_cost(t, prices) for t in subagent_turns)
    assert (by_key["#54"].cost_usd + by_key["#55"].cost_usd) == pytest.approx(orch_cost + subagent_cost, abs=0.01)


def test_brain_session_gets_its_own_row_not_unattributed(multi_scan: tm.ScanResult, prices: dict):
    rows = tm.grouped_table(multi_scan.turns, prices, by="issue", since=WINDOW_SINCE, until=WINDOW_UNTIL)
    by_key = {r.key: r for r in rows}
    assert "brain" in by_key
    assert by_key["brain"].context == 4000
    assert by_key["brain"].cost_usd == pytest.approx(0.024)
    assert "UNATTRIBUTED" not in by_key  # the only otherwise-unattributed turn was the brain one


def test_unattributed_share_excludes_brain_and_split_orch_turns(multi_scan: tm.ScanResult):
    share, unattributed_ctx, total_ctx = tm.unattributed_share(multi_scan.turns, since=WINDOW_SINCE, until=WINDOW_UNTIL)
    assert unattributed_ctx == 0
    assert total_ctx == 1000 + 1000 + 2000 + 4000  # sessC main + agent-y1 + agent-y2 + sessD
    assert share == 0.0


def test_is_brain_turn_by_agent_type_and_by_title():
    brain_by_agent = tm.Turn(
        session_id="s", agent_id="b1", agent_type="brain", message_id="m", model=None,
        timestamp=None, input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0,
        output_tokens=0, issue=None, title=None, turn_index=0,
    )
    brain_by_title = tm.Turn(
        session_id="s", agent_id=None, agent_type=None, message_id="m", model=None,
        timestamp=None, input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0,
        output_tokens=0, issue=None, title="Настройка оркестрации", turn_index=0,
    )
    not_brain = tm.Turn(
        session_id="s", agent_id=None, agent_type=None, message_id="m", model=None,
        timestamp=None, input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0,
        output_tokens=0, issue=None, title="poe-junkroan-v2 opus 5.5 lead session", turn_index=0,
    )
    assert tm.is_brain_turn(brain_by_agent)
    assert tm.is_brain_turn(brain_by_title)
    assert not tm.is_brain_turn(not_brain)


# ---------------------------------------------------------- dispatch.out / orch_session.json ----


def test_parse_dispatch_offers_multi_and_single_issue_lines():
    text = (
        "2026-09-26 20:16:04 orch-dispatch: started orch (43a8dba9) offered #54, #55, #56, #57: "
        "... Take every ready issue (ready now, in dispatch order: #54, #55, #56, #57). "
        "Follow docs/agents/orch.md.\n"
        "2026-09-26 19:19:32 orch-dispatch: started orch #6 (3a25b860): ... Your issue is #6. "
        "Follow docs/agents/orch.md.\n"
    )
    offers = tm.parse_dispatch_offers(text)
    assert offers["43a8dba9"] == [54, 55, 56, 57]
    assert offers["3a25b860"] == [6]


def test_parse_orch_session_held_shape():
    assert tm.parse_orch_session_held({"session": "bcca11d5", "held": [64, 65, 66]}) == {
        "bcca11d5": [64, 65, 66]
    }
    assert tm.parse_orch_session_held({"session": "x", "held": "not a list"}) == {}
    assert tm.parse_orch_session_held({}) == {}


def test_resolve_held_issues_priority_order():
    # orch_session.json beats dispatch.out beats title beats first message.
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #1 #2", "irrelevant",
        dispatch_offers={"abc12345": [8, 9]},
        orch_session_held={"abc12345": [1, 2, 3]},
    ) == [1, 2, 3]
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #1 #2", "irrelevant",
        dispatch_offers={"abc12345": [8, 9]},
        orch_session_held={},
    ) == [8, 9]
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #1 #2", "irrelevant",
        dispatch_offers={}, orch_session_held={},
    ) == [1, 2]
    # a single #N in the title/first message is the ordinary one-issue case, not a signal.
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #1", "irrelevant", dispatch_offers={}, orch_session_held={},
    ) == []


def test_resolve_held_issues_adds_claimed_issues_never_replaces():
    # #199: claimed issues are ADDED to whichever source wins, in claim order, never in place
    # of it, and never duplicated when a source already names one.
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #1", "irrelevant",
        dispatch_offers={}, orch_session_held={"abc12345": [1, 2]},
        claimed_issues={2, 3},
    ) == [1, 2, 3]
    # a single #N title gives no source signal ([]); claimed issues still populate held.
    assert tm.resolve_held_issues(
        "abc12345-x", "orch #198", "irrelevant",
        dispatch_offers={"abc12345": [198]}, orch_session_held={},
        claimed_issues={196, 193},
    ) == [198, 193, 196]


# --------------------------------------------------- claimed issues added to held (#199) ----
#
# fixtures/token_meter_199/: d0e08af0 cut to its two claim tool calls (#198 at 16:22:30Z, then
# #196 and #193 at 18:22:51Z) plus the first prompts of its three real workers -- each prompt
# is ambiguous under the plain single_issue rule (it names its own issue plus at least one
# other #N), so each worker is attributed correctly only once #198/#193/#196 are all held.
# orch_session.json is the real ended-session shape ({"session": null, "sessions": []});
# dispatch.out holds only the real "started orch (d0e08af0) offered #198" line -- neither
# names #193/#196, so only the claim-call fix (not the existing sources) can attribute them.

FIXTURES_199 = Path(__file__).resolve().parent / "fixtures" / "token_meter_199"


def test_ended_orch_session_claimed_issues_all_attributed():
    dispatch_offers = tm.load_dispatch_offers(FIXTURES_199 / "dispatch.out")
    orch_session_held = tm.load_orch_session_held(FIXTURES_199 / "orch_session.json")
    scan = tm.scan_projects_dir(
        FIXTURES_199 / "projects",
        dispatch_offers=dispatch_offers,
        orch_session_held=orch_session_held,
    )
    by_agent = {t.agent_id: t.issue for t in scan.turns if t.is_subagent}
    assert by_agent["a46261a849a7872d4"] == 198
    assert by_agent["a54a6c59262e04cf9"] == 193
    assert by_agent["ae750dbea16c48ad7"] == 196

    unattributed_turns = [t for t in scan.turns if t.is_subagent and t.issue is None]
    assert unattributed_turns == []


# ---- #300 unit 1: --since / --until are read on the local clock ----

_UTC2 = timezone(timedelta(hours=2))


def test_parse_date_arg_naive_datetime_is_in_tz():
    dt = tm.parse_date_arg("2026-09-28T12:45", tz=_UTC2)
    assert dt == datetime(2026, 9, 28, 10, 45, tzinfo=timezone.utc)
    assert dt.isoformat() == "2026-09-28T12:45:00+02:00"


@pytest.mark.parametrize("raw", ["2026-09-28T12:45Z", "2026-09-28T12:45+00:00"])
def test_parse_date_arg_keeps_z_and_offset(raw):
    dt = tm.parse_date_arg(raw, tz=_UTC2)
    assert dt == datetime(2026, 9, 28, 12, 45, tzinfo=timezone.utc)
    assert dt.utcoffset() == timedelta(0)


def test_parse_date_arg_bare_clock_is_today_in_tz():
    dt = tm.parse_date_arg("09:00", tz=_UTC2, today=date(2026, 9, 28))
    assert dt.isoformat() == "2026-09-28T09:00:00+02:00"


def test_parse_date_arg_date_is_midnight_in_tz():
    dt = tm.parse_date_arg("2026-09-28", tz=_UTC2)
    assert dt.isoformat() == "2026-09-28T00:00:00+02:00"


# ------------------------------------------------------------------ subagent share (#344) ----


def test_subagent_share_by_session_prefix(scan: tm.ScanResult, prices: dict):
    rows, own, sub = tm.subagent_share(scan.turns, prices, session_prefixes=["sessA"])
    # own: opus-5-5 1.59e-3 + sonnet 3.825e-4 + opus-5-5 2.92e-5 + haiku 3.675e-5 (unpriced model adds nothing)
    assert own == pytest.approx(0.00203845)
    # subagents: sonnet 0.0106 + 0.000345, opus-5-5 0.018, opus-5 0.00375
    assert sub == pytest.approx(0.032695)
    assert rows == [("sessA", pytest.approx(own), pytest.approx(sub))]
    assert "share 94.1 %" in tm.render_subagent_share(rows, own, sub)


def test_subagent_share_by_orch_title_takes_subagents_of_the_titled_session(scan: tm.ScanResult, prices: dict):
    rows, own, sub = tm.subagent_share(scan.turns, prices, orch_pattern="orch")
    assert [r[0] for r in rows] == ["sessA"]
    assert own == pytest.approx(0.00203845)
    assert sub == pytest.approx(0.032695)
