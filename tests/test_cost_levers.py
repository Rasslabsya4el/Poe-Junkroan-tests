"""Tests for scripts/cost_levers.py: fixture transcripts only, no network, no gh call.

Fixture layout (tests/fixtures/cost_levers/):
  projects/orch1.jsonl                 ORCH session, titled "orch #10", not live at the
                                        test window's --until
  projects/orch2.jsonl                 ORCH session, titled "orch #11", live at --until
                                        (its second turn is timestamped after it)
  projects/orch1/subagents/agent-w1.jsonl(+.meta.json)  worker, issue #10, THREE TURNS WITH
                                        ONE EDIT (turn 1); first prompt holds the "Places to
                                        read" heading; last message starts with the
                                        "Context hand-back" heading
  projects/orch1/subagents/agent-w2.jsonl(+.meta.json)  worker, issue #10, A SPAWN WITH NO
                                        EDIT AT ALL (two Read turns); started 12 minutes
                                        after agent-w1's last turn
  projects/orch1/subagents/agent-w3.jsonl(+.meta.json)  worker-strong, issue #20, its FIRST
                                        TURN HOLDS TWO TOOL CALLS (Edit + Read, arriving on
                                        two separate jsonl lines sharing one message id)
  projects/orch1/subagents/agent-r1.jsonl(+.meta.json)  researcher-find, no issue named
  projects/orch2/subagents/agent-w4.jsonl(+.meta.json)  worker of the LIVE session: left out
                                        of every spawn indicator, counted apart
  prices.json                          every token kind priced at $1/million, so a turn's
                                        cost is just its token sum / 1e6
  sessions_both.txt                    "orch1\\norch2\\n", a --sessions file

Every dollar amount below was computed by hand from the fixture files; see the comment
above each assertion.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cost_levers as cl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cost_levers"
PROJECTS_DIR = FIXTURES / "projects"
PRICES_PATH = FIXTURES / "prices.json"
SESSIONS_BOTH = FIXTURES / "sessions_both.txt"

# #197: one ORCH session (a fixture cut from the real transcript bb1a7cb7, "the calls that
# matter" only) whose closing comment for #183 quotes 'gh issue close 84/81/93' as prose --
# the reproduction of the over-count bug.
FIXTURES_197 = Path(__file__).resolve().parent / "fixtures" / "cost_levers_197"
PROJECTS_DIR_197 = FIXTURES_197 / "projects"
PRICES_PATH_197 = FIXTURES_197 / "prices.json"
NO_DISPATCH_OUT = FIXTURES_197 / "no-such-dispatch.out"
NO_ORCH_SESSION_JSON = FIXTURES_197 / "no-such-orch_session.json"
SINCE_197 = datetime(2026, 9, 27, 14, 48, 0, tzinfo=timezone.utc)
UNTIL_197 = datetime(2026, 9, 27, 15, 36, 0, tzinfo=timezone.utc)

SINCE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def prices() -> dict:
    return cl.tm.load_prices(PRICES_PATH)


@pytest.fixture()
def spawns(prices) -> list[cl.Spawn]:
    """The three worker/worker-strong spawns of the non-live session, in file order."""

    w1 = cl.load_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w1.jsonl", {"agentType": "worker"}, prices
    )
    w2 = cl.load_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w2.jsonl", {"agentType": "worker"}, prices
    )
    w3 = cl.load_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w3.jsonl",
        {"agentType": "worker-strong"},
        prices,
    )
    return [w1, w2, w3]


# --------------------------------------------------------------------------- call_kind ----


def test_call_kind_edit_tools():
    for name in ("Edit", "Write", "NotebookEdit"):
        assert cl.call_kind(name, {}) == "edit"


def test_call_kind_read_tools():
    for name in ("Read", "Grep", "Glob"):
        assert cl.call_kind(name, {}) == "read"


def test_call_kind_shell_read():
    assert cl.call_kind("Bash", {"command": "cat scripts/foo.py"}) == "read"
    assert cl.call_kind("Bash", {"command": "rg pattern src/"}) == "read"


def test_call_kind_shell_write_is_not_read():
    assert cl.call_kind("Bash", {"command": "cat >> out.txt"}) == "other"


def test_call_kind_shell_git_gh_other_not_read():
    assert cl.call_kind("Bash", {"command": "git status"}) == "other"
    assert cl.call_kind("Bash", {"command": "gh issue view 1"}) == "other"


# --------------------------------------------------------------------------- parse_spawn ----


def test_three_turn_spawn_with_one_edit():
    issue, turns, first_prompt, last_message = cl.parse_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w1.jsonl"
    )
    assert issue == 10
    assert [t.message_id for t in turns] == ["w1_t0", "w1_t1", "w1_t2"]
    assert [t.context for t in turns] == [30000, 120000, 20000]
    first_edit = next(
        (t.turn_index for t in turns if any(n in cl.EDIT_TOOLS for n, _ in t.tool_calls)), None
    )
    assert first_edit == 1
    assert "Places to read" in first_prompt
    assert last_message == "Context hand-back: done reading, next edit tests."


def test_spawn_with_no_edit():
    issue, turns, _first_prompt, _last = cl.parse_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w2.jsonl"
    )
    assert issue == 10
    assert len(turns) == 2
    assert not any(any(n in cl.EDIT_TOOLS for n, _ in t.tool_calls) for t in turns)


def test_turn_with_two_tool_calls_merges_across_jsonl_lines():
    issue, turns, _first_prompt, _last = cl.parse_spawn(
        PROJECTS_DIR / "orch1" / "subagents" / "agent-w3.jsonl"
    )
    assert issue == 20
    assert len(turns) == 2
    first = turns[0]
    assert first.context == 160000  # usage came from the first of the two lines sharing its id
    assert [name for name, _ in first.tool_calls] == ["Edit", "Read"]


def test_usage_comes_from_last_line_carrying_it(tmp_path):
    """#262: one ``message.id`` on three lines, output tokens 12, 140, 911 -- the turn holds
    911 (the last line with usage), one turn total."""

    jsonl = tmp_path / "agent-w5.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                (
                    '{"type": "user", "message": {"role": "user", "content": "Work on #30."}, '
                    '"timestamp": "2026-01-01T01:59:00Z"}'
                ),
                (
                    '{"type": "assistant", "message": {"id": "w5_t0", "model": "claude-opus-5-5",'
                    ' "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 0,'
                    ' "cache_read_input_tokens": 0, "output_tokens": 12}, "content": []},'
                    ' "timestamp": "2026-01-01T02:00:00Z"}'
                ),
                (
                    '{"type": "assistant", "message": {"id": "w5_t0", "model": "claude-opus-5-5",'
                    ' "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 0,'
                    ' "cache_read_input_tokens": 0, "output_tokens": 140}, "content": []},'
                    ' "timestamp": "2026-01-01T02:00:01Z"}'
                ),
                (
                    '{"type": "assistant", "message": {"id": "w5_t0", "model": "claude-opus-5-5",'
                    ' "usage": {"input_tokens": 1000, "cache_creation_input_tokens": 0,'
                    ' "cache_read_input_tokens": 0, "output_tokens": 911}, "content": []},'
                    ' "timestamp": "2026-01-01T02:00:02Z"}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    issue, turns, _first_prompt, _last = cl.parse_spawn(jsonl)
    assert issue == 30
    assert len(turns) == 1
    assert turns[0].usage["output_tokens"] == 911


# --------------------------------------------------------------------------- load_spawn ----


def test_load_spawn_first_edit_and_cost(spawns):
    w1, w2, w3 = spawns
    assert w1.first_edit == 1
    assert w1.cost == pytest.approx((30000 + 120000 + 20000) / 1_000_000)
    assert w2.first_edit is None
    assert w2.cost == pytest.approx((10000 + 5000) / 1_000_000)
    assert w3.first_edit == 0
    assert w3.cost == pytest.approx((160000 + 50000) / 1_000_000)


# ------------------------------------------------------------------ per-type indicators ----


def test_median_context_at_first_edit(spawns):
    out = cl.median_context_at_first_edit(spawns)
    assert out["worker"] == (120000, 1, 1)  # w1 edited at 120k; w2 has no edit
    assert out["worker-strong"] == (160000, 1, 0)  # w3 edited at its first turn, 160k


def test_tool_calls_per_turn(spawns):
    ratio, counts = cl.tool_calls_per_turn(spawns)
    # w1: turn 1 (edit only) + turn 2 (read only) after its first edit.
    # w3: turn 0 (edit + read) + turn 1 (read only) after its first edit (turn 0 itself).
    assert counts == {
        "edit": {"calls": 2, "turns": 2},
        "read": {"calls": 3, "turns": 3},
    }
    assert ratio == pytest.approx(1.0)


def test_cost_share_above(spawns, prices):
    total = (30000 + 120000 + 20000 + 10000 + 5000 + 160000 + 50000) / 1_000_000
    above100 = (120000 + 160000) / 1_000_000  # w1's edit turn and w3's first turn
    above150 = 160000 / 1_000_000  # only w3's first turn
    assert cl.cost_share_above(spawns, 100_000, prices) == pytest.approx(above100 / total)
    assert cl.cost_share_above(spawns, 150_000, prices) == pytest.approx(above150 / total)


def test_places_to_read_count(spawns):
    assert cl.places_to_read_count(spawns) == 1  # only w1's first prompt holds the heading


def test_context_handback(spawns):
    n, gaps = cl.context_handback(spawns)
    assert n == 1  # only w1's last message opens with the heading
    assert gaps == pytest.approx([12.0])  # w1 ends 01:10, w2 (same issue #10) starts 01:22


# ------------------------------------------------------------------------- session scope ----


def test_session_is_live():
    assert cl.session_is_live(PROJECTS_DIR / "orch1.jsonl", UNTIL) is False
    assert cl.session_is_live(PROJECTS_DIR / "orch2.jsonl", UNTIL) is True


def test_discover_target_sessions_from_window():
    sessions = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, None)
    assert {sid for sid, _ in sessions} == {"orch1", "orch2"}


def test_discover_target_sessions_from_file():
    sessions = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    assert {sid for sid, _ in sessions} == {"orch1", "orch2"}


def test_gather_spawns_excludes_live_session(prices):
    target = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    found, live_excluded, live = cl.gather_spawns(PROJECTS_DIR, target, SINCE, UNTIL, prices)
    assert live == {"orch1": False, "orch2": True}
    assert live_excluded == 1  # agent-w4, under the live orch2
    assert {s.path.stem for s in found} == {"agent-w1", "agent-w2", "agent-w3"}


def test_apply_spawns_limit_orders_by_start_time(spawns):
    w1, w2, w3 = spawns  # started 01:00, 01:22, 02:00
    limited = cl.apply_spawns_limit([w3, w1, w2], 2)
    assert [s.path.stem for s in limited] == ["agent-w1", "agent-w2"]


# ------------------------------------------------------------------------ researcher-find ----


def test_researcher_find_ratio(prices):
    target = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    found, _live_excluded, live = cl.gather_spawns(PROJECTS_DIR, target, SINCE, UNTIL, prices)
    session_ids = {sid for sid, _ in target}
    n_rf, cost_rf, ratio = cl.researcher_find_ratio(
        PROJECTS_DIR, session_ids, live, prices, len(found)
    )
    assert n_rf == 1
    assert cost_rf == pytest.approx(2000 / 1_000_000)
    assert ratio == pytest.approx(1 / 3)


# -------------------------------------------------------------------------- whole cost ----


def test_session_gh_closes():
    # orch1's own thread: #10 succeeds before UNTIL, #99 fails (is_error) -- only #10 counts.
    closes = cl.session_gh_closes(PROJECTS_DIR / "orch1.jsonl", UNTIL)
    assert set(closes) == {10}


def test_session_gh_closes_cuts_at_until(tmp_path):
    # a successful close after --until never counts, even though the call itself succeeded.
    jsonl = tmp_path / "orch_late.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                '{"type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5", '
                '"usage": {"input_tokens": 1}, "content": [{"type": "tool_use", "id": "tu", '
                '"name": "Bash", "input": {"command": "gh issue close 77"}}]}, '
                '"timestamp": "2026-01-01T13:00:00Z"}',
                '{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", '
                '"tool_use_id": "tu", "content": [{"type": "text", "text": "Closed issue #77"}]}]}, '
                '"timestamp": "2026-01-01T13:00:01Z"}',
            ]
        ),
        encoding="utf-8",
    )
    closes = cl.session_gh_closes(jsonl, UNTIL)
    assert closes == {}


def test_gh_closed_issues_across_sessions():
    target = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    closes = cl.gh_closed_issues(target, UNTIL, None)
    assert set(closes) == {10}


def test_whole_cost_section(prices):
    target = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    whole = cl.whole_cost_section(PROJECTS_DIR, target, UNTIL, prices, None)
    # orch1's own thread up to UNTIL (1000 + 100 + 100, the tool-use turns of its two 'gh
    # issue close' attempts) + w1 (170000) + w2 (15000) + w3 (210000) + r1 (2000) + orch2's
    # own FIRST turn (500, before UNTIL -- only orch2's spawns and its later turn are cut,
    # its own thread up to UNTIL still counts).
    total_tokens = 1200 + 170000 + 15000 + 210000 + 2000 + 500
    assert whole.total_cost == pytest.approx(total_tokens / 1_000_000)
    # "the issues closed": only #10 (a successful 'gh issue close' before UNTIL, from
    # session_gh_closes above); #99 failed.
    assert whole.n_closed_issues == 1
    assert whole.mean_per_issue == pytest.approx(whole.total_cost / 1)
    # median per issue stays the token meter's own attribution: #10 gets orch1's own thread
    # (1200) + w1 (170000) + w2 (15000) (w3 is #20, r1 is unattributed).
    attributed_10 = (1200 + 170000 + 15000) / 1_000_000
    assert whole.median_per_issue == pytest.approx(attributed_10)
    assert whole.unattributed_share == pytest.approx(2000 / total_tokens)  # r1 only


# --------------------------------------------------------------------------- build_report ----



# ---------------------------------------------------------- #197: output-line-only counting ----


def test_closed_output_re_matches_gh_success_line():
    text = "1439a80\nlogged: ...\n✓ Closed issue Rasslabsya4el/Poe-Junkroan#166 (title here)\nclosed"
    assert [int(n) for n in cl.CLOSED_OUTPUT_RE.findall(text)] == [166]


def test_session_gh_closes_numbers_only_in_command_text_not_counted():
    # the #183 call: its --comment quotes 'gh issue close 84/81/93' as prose, but its own
    # output carries the success line for #183 only -- 84/81/93 must not be credited.
    closes = cl.session_gh_closes(PROJECTS_DIR_197 / "fixture01.jsonl", UNTIL_197)
    assert set(closes) == {166, 190, 153, 183}


def test_session_close_lists_orders_by_close_time():
    target = cl.discover_target_sessions(PROJECTS_DIR_197, SINCE_197, UNTIL_197, None)
    assert len(target) == 1
    lists = cl.session_close_lists(target, UNTIL_197)
    assert len(lists) == 1
    _sid, nums = lists[0]
    assert nums == [166, 190, 153, 183]  # closed in this order, 15:11 .. 15:22


def test_gh_closed_issues_197_fixture_gives_four():
    target = cl.discover_target_sessions(PROJECTS_DIR_197, SINCE_197, UNTIL_197, None)
    closes = cl.gh_closed_issues(target, UNTIL_197, None)
    assert set(closes) == {166, 190, 153, 183}
    assert len(closes) == 4


def test_build_report_197_fixture_lists_the_four_issues():
    prices = cl.tm.load_prices(PRICES_PATH_197)
    report = cl.build_report(
        projects_dir=PROJECTS_DIR_197,
        prices=prices,
        since=SINCE_197,
        until=UNTIL_197,
        sessions_file=None,
        spawns_limit=None,
        issues_limit=None,
        dispatch_out=NO_DISPATCH_OUT,
        orch_session_json=NO_ORCH_SESSION_JSON,
    )
    assert "4 closed issue(s)" in report
    assert "Closed issues counted, per ORCH session" in report
    assert "#166" in report and "#190" in report and "#153" in report and "#183" in report
    assert "#84" not in report and "#81" not in report and "#93" not in report


def test_build_report_smoke(prices):
    report = cl.build_report(
        projects_dir=PROJECTS_DIR,
        prices=prices,
        since=SINCE,
        until=UNTIL,
        sessions_file=SESSIONS_BOTH,
        spawns_limit=None,
        issues_limit=None,
    )
    assert "Spawns counted" in report
    assert "worker" in report
    assert "worker-strong" in report
    assert "Tool calls per turn" in report
    assert "The whole cost per closed issue, mean" in report
    assert "counted apart: 1" in report  # agent-w4, the live session's spawn


# ------------------------------------------------- #192: the further-ORCH indicators ----
#
# Fixtures of the records only (no transcript): merge-log lines, in #212's own line format
# (`"{now()} | {branch} | {reason} | suite {duration} | {n} failed | output {path}"`, as
# `tools.agentops.merge._append_merge_log` writes them -- one time per line, read as this
# line's own end) and dispatcher events ({ts, kind, ...}, as `tools.agentops.dispatch` writes
# them).

import json as _json  # noqa: E402


def _write_jsonl(path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(_json.dumps(r) for r in records) + ("\n" if records else ""), encoding="utf-8"
    )


def _write_merge_log(path, lines) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


#: #212's raw `MergeResult.reason` for a merge log line's own outcome column -- the value
#: `conflict_indicators` reads back out is `cl.MERGE_LOG_OUTCOME`'s mapping of this
#: (`"pushed"` -> `"merged"`, `"conflict"`/`"rebase-conflict"` -> `"conflict"`,
#: `"red-suite"` -> `"red_suite"`).
_REASON_FOR_OUTCOME = {"merged": "pushed", "conflict": "conflict", "red_suite": "red-suite"}


def _merge_line(branch: str, outcome: str, ts: str) -> str:
    """One #212-format merge-log line at time ``ts`` (``"YYYY-MM-DD HH:MM:SS"``, no timezone --
    ``now()``'s own format) for ``branch``, whose own reason maps back to ``outcome``."""
    reason = _REASON_FOR_OUTCOME[outcome]
    return f"{ts} | {branch} | {reason} | suite 1.0 s | 0 failed | output -"


def _merge_entry(branch: str, outcome: str, ts_start: str, ts_end: str) -> dict:
    """A parsed record in ``conflict_indicators``'s own shape, built the same way
    ``cl.parse_merge_log_line`` builds one from a real #212 line: both ends read ``ts_end``
    (#212's line carries a single time only), so ``ts_start`` here is accepted but ignored by
    every caller that only reads through ``cl.parse_merge_log_line``."""
    return {"ts_start": ts_start, "ts_end": ts_end, "branch": branch, "issue": None, "outcome": outcome}


CL_SINCE = datetime(2026, 9, 27, 0, 0, 0, tzinfo=timezone.utc)
CL_UNTIL = datetime(2026, 9, 27, 23, 59, 59, tzinfo=timezone.utc)


def test_conflict_indicators_3_over_49_prints_1_2(tmp_path):
    log_path = tmp_path / "merge.log"
    _write_merge_log(log_path, [
        _merge_line(f"origin/issue-{n}", "conflict", "2026-09-27 10:00:00")
        for n in (1, 2, 3)
    ])
    merge_log = cl.load_merge_log(log_path)
    result = cl.conflict_indicators(merge_log, CL_SINCE, CL_UNTIL, 49)
    assert result.n_conflicts == 3
    assert f"{result.per_20_closed:.1f}" == "1.2"
    assert cl.conflict_alerts(result) == []


def test_conflict_indicators_8_over_49_prints_3_3_and_marks(tmp_path):
    log_path = tmp_path / "merge.log"
    _write_merge_log(log_path, [
        _merge_line(f"origin/issue-{n}", "conflict", "2026-09-27 10:00:00")
        for n in range(1, 9)
    ])
    merge_log = cl.load_merge_log(log_path)
    result = cl.conflict_indicators(merge_log, CL_SINCE, CL_UNTIL, 49)
    assert result.n_conflicts == 8
    assert f"{result.per_20_closed:.1f}" == "3.3"
    alerts = cl.conflict_alerts(result)
    assert alerts and alerts[0].startswith("3.3 conflicts per 20 closed issues")


def test_conflict_indicators_one_conflict_ended_red_suite_marks_whatever_the_rate(tmp_path):
    # one conflict, over a large closed-issue count so the rate alone stays well under
    # CONFLICT_RATE_ALERT, yet the marked line must still appear.
    log_path = tmp_path / "merge.log"
    _write_merge_log(log_path, [
        _merge_line("origin/issue-1", "conflict", "2026-09-27 10:00:00"),
        _merge_line("origin/issue-1", "red_suite", "2026-09-27 10:06:00"),
    ])
    merge_log = cl.load_merge_log(log_path)
    result = cl.conflict_indicators(merge_log, CL_SINCE, CL_UNTIL, 1000)
    assert result.per_20_closed < cl.CONFLICT_RATE_ALERT
    assert result.any_without_green_suite is True
    alerts = cl.conflict_alerts(result)
    assert alerts == ["a conflict ended without a green suite"]
    # a red-suite next attempt is not a resolution: out of median/longest
    assert result.median_seconds is None
    assert result.longest_seconds is None


def test_conflict_indicators_median_and_longest_1_2_8_minutes(tmp_path):
    log_path = tmp_path / "merge.log"
    _write_merge_log(log_path, [
        _merge_line("origin/issue-1", "conflict", "2026-09-27 10:00:00"),
        _merge_line("origin/issue-1", "merged", "2026-09-27 10:01:00"),  # +1 min
        _merge_line("origin/issue-2", "conflict", "2026-09-27 11:00:00"),
        _merge_line("origin/issue-2", "merged", "2026-09-27 11:02:00"),  # +2 min
        _merge_line("origin/issue-3", "conflict", "2026-09-27 12:00:00"),
        _merge_line("origin/issue-3", "merged", "2026-09-27 12:08:00"),  # +8 min
    ])
    merge_log = cl.load_merge_log(log_path)
    result = cl.conflict_indicators(merge_log, CL_SINCE, CL_UNTIL, 100)
    assert result.n_conflicts == 3
    assert cl.human_duration(result.median_seconds) == cl.human_duration(120)
    assert cl.human_duration(result.longest_seconds) == cl.human_duration(480)


def test_parse_merge_log_line_maps_outcomes_and_uses_the_single_time_as_the_end(monkeypatch):
    # a fixed local offset (UTC+3, the owner's own machine): ``now()`` writes local time, so the
    # parsed record must land 3 h earlier in UTC (#192).
    monkeypatch.setattr(cl, "_local_tzinfo", lambda: timezone(timedelta(hours=3)))
    record = cl.parse_merge_log_line(
        "2026-09-27 10:00:00 | origin/issue-192 | conflict | suite 1.0 s | 0 failed | output -"
    )
    assert record == {
        "ts_start": "2026-09-27T07:00:00+00:00",
        "ts_end": "2026-09-27T07:00:00+00:00",
        "branch": "origin/issue-192",
        "outcome": "conflict",
    }
    merged = cl.parse_merge_log_line(
        "2026-09-27 10:01:00 | origin/issue-192 | pushed | suite 1.0 s | 0 failed | output -"
    )
    assert merged["outcome"] == "merged"
    red = cl.parse_merge_log_line(
        "2026-09-27 10:02:00 | origin/issue-192 | red-suite | suite 1.0 s | 3 failed | output x.out"
    )
    assert red["outcome"] == "red_suite"


def test_parse_merge_log_line_local_naive_one_minute_ago_is_inside_a_period_ending_now(monkeypatch):
    # #192: a line stamped with local naive time one minute ago must fall inside a period
    # ending "now" -- before the fix it was tagged +00:00 outright and could land in the future
    # of the (UTC) period filter, dropping it from `--until now` runs.
    fixed_offset = timezone(timedelta(hours=3))
    monkeypatch.setattr(cl, "_local_tzinfo", lambda: fixed_offset)
    now_utc = datetime(2026, 9, 28, 21, 40, 54, tzinfo=timezone.utc)
    one_minute_ago_local = (now_utc - timedelta(minutes=1)).astimezone(fixed_offset)
    line = _merge_line("origin/issue-192", "conflict", one_minute_ago_local.strftime("%Y-%m-%d %H:%M:%S"))
    record = cl.parse_merge_log_line(line)
    ts_end = datetime.fromisoformat(record["ts_end"])
    since = now_utc - timedelta(minutes=5)
    assert since <= ts_end <= now_utc


def test_load_merge_log_skips_unparsable_lines_and_missing_file(tmp_path):
    log_path = tmp_path / "merge.log"
    _write_merge_log(log_path, [
        "2026-09-27 10:00:00 | origin/issue-1 | conflict | suite 1.0 s | 0 failed | output -",
        "not a merge log line at all",
    ])
    records = cl.load_merge_log(log_path)
    assert len(records) == 1
    assert records[0]["branch"] == "origin/issue-1"
    assert cl.load_merge_log(tmp_path / "no-such-file.log") == []


def test_further_orch_waits_5_min_and_30_s_counts_only_the_long_one():
    events = [
        {"ts": "2026-09-27T09:00:00+00:00", "kind": "issue_ready_seen", "issue": 1},
        {"ts": "2026-09-27T09:05:00+00:00", "kind": "issue_taken", "issue": 1, "how": "claimed"},
        {"ts": "2026-09-27T10:00:00+00:00", "kind": "issue_ready_seen", "issue": 2},
        {"ts": "2026-09-27T10:00:30+00:00", "kind": "issue_taken", "issue": 2, "how": "offered"},
    ]
    result = cl.further_orch_waits(events, CL_SINCE, CL_UNTIL)
    assert result.n_waited == 1
    assert cl.human_duration(result.longest_seconds) == cl.human_duration(300)


def test_peak_orch_sessions_two_overlapping_and_one_all_day():
    events = [
        # one session live for the rest of the day, but not during the 15:00-15:20 overlap
        {"ts": "2026-09-27T00:00:00+00:00", "kind": "orch_start", "issues": [], "session": "s0a"},
        {"ts": "2026-09-27T15:00:00+00:00", "kind": "orch_session_end", "session": "s0a"},
        {"ts": "2026-09-27T15:20:00+00:00", "kind": "orch_start", "issues": [], "session": "s0b"},
        {"ts": "2026-09-27T23:59:59+00:00", "kind": "orch_session_end", "session": "s0b"},
        {"ts": "2026-09-27T15:00:00+00:00", "kind": "orch_start", "issues": [], "session": "s1"},
        {"ts": "2026-09-27T15:20:00+00:00", "kind": "orch_session_end", "session": "s1"},
        {"ts": "2026-09-27T15:05:00+00:00", "kind": "orch_start", "issues": [], "session": "s2"},
        {"ts": "2026-09-27T15:15:00+00:00", "kind": "orch_session_end", "session": "s2"},
    ]
    result = cl.peak_orch_sessions(events, CL_SINCE, CL_UNTIL)
    assert result.peak == 2
    assert result.n_excluded == 0


def test_peak_orch_sessions_fallback_to_orch_end_ts_when_no_session_end():
    # a real orch_end event (no orch_session_end for it) closes the session at its own ts.
    events = [
        {"ts": "2026-09-27T10:00:00+00:00", "kind": "orch_start", "issues": [1], "session": "s1"},
        {"ts": "2026-09-27T10:30:00+00:00", "kind": "orch_end", "issue": 1, "session": "s1",
         "outcome": "closed", "why": "done"},
    ]
    result = cl.peak_orch_sessions(events, CL_SINCE, CL_UNTIL)
    assert result.peak == 1
    assert result.n_excluded == 0
    # a second, later session overlapping only after s1's orch_end must not count as concurrent
    events_no_overlap = events + [
        {"ts": "2026-09-27T11:00:00+00:00", "kind": "orch_start", "issues": [2], "session": "s2"},
        {"ts": "2026-09-27T11:30:00+00:00", "kind": "orch_end", "issue": 2, "session": "s2",
         "outcome": "closed", "why": "done"},
    ]
    result2 = cl.peak_orch_sessions(events_no_overlap, CL_SINCE, CL_UNTIL)
    assert result2.peak == 1


def test_peak_orch_sessions_no_end_and_not_live_is_excluded():
    events = [
        {"ts": "2026-09-27T10:00:00+00:00", "kind": "orch_start", "issues": [], "session": "stale"},
    ]
    result = cl.peak_orch_sessions(events, CL_SINCE, CL_UNTIL)
    assert result.peak == 0
    assert result.n_excluded == 1
    # named live (as artifacts/runs/orch_session.json would report): counted, open to --until
    result_live = cl.peak_orch_sessions(events, CL_SINCE, CL_UNTIL, live_sessions={"stale"})
    assert result_live.peak == 1
    assert result_live.n_excluded == 0


def test_build_report_wires_merge_log_and_events_file(tmp_path, prices):
    merge_log_path = tmp_path / "merge.log"
    events_path = tmp_path / "events.jsonl"
    _write_merge_log(merge_log_path, [
        _merge_line("origin/issue-1", "conflict", "2026-01-01 05:00:00"),
    ])
    _write_jsonl(events_path, [
        {"ts": "2026-01-01T05:00:00+00:00", "kind": "orch_start", "issues": [], "session": "s1"},
        {"ts": "2026-01-01T05:10:00+00:00", "kind": "orch_session_end", "session": "s1"},
    ])
    report = cl.build_report(
        projects_dir=PROJECTS_DIR,
        prices=prices,
        since=SINCE,
        until=UNTIL,
        sessions_file=SESSIONS_BOTH,
        spawns_limit=None,
        issues_limit=None,
        merge_log=merge_log_path,
        events_file=events_path,
    )
    assert "Conflicts per 20 closed issues" in report
    assert "Time per conflict, median / longest" in report
    assert "Issues that waited for a further ORCH" in report
    assert "The day's peak of live ORCH sessions: 1" in report
    assert "1 conflict(s)" in report


# -------------------------------------------------------------------------------- units ----
# #254 unit 3 of 3: turns_by_agent_type / units_by_issue over hand-built Spawn objects (no
# fixture files needed -- these two functions only read fields Spawn already carries).


def _spawn(
    *, session: str, agent_type: str, issue: int, first_prompt: str,
    turn_timestamps: list[datetime],
) -> cl.Spawn:
    turns = [
        cl.SpawnTurn(
            turn_index=i, message_id=f"{session}_{i}", model="claude-sonnet-5",
            usage={"input_tokens": 100, "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0, "output_tokens": 0},
            timestamp=ts,
        )
        for i, ts in enumerate(turn_timestamps)
    ]
    return cl.Spawn(
        session=session, path=Path(f"{session}.jsonl"), agent_type=agent_type, issue=issue,
        turns=turns, first_edit=None, first_prompt=first_prompt, last_message="",
        cost=0.0, started=turn_timestamps[0] if turn_timestamps else None,
    )


def test_parse_unit_line():
    assert cl.parse_unit_line("## Places to read\nUnit: 2 of 3 (units)\n\nWork on #254.") == (2, 3)
    assert cl.parse_unit_line("Work on #254, no unit line here.") is None


def test_turns_by_agent_type():
    spawns = [
        _spawn(
            session="w1", agent_type="worker", issue=42, first_prompt="Unit: 1 of 3\n",
            turn_timestamps=[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)] * 2,
        ),
        _spawn(
            session="w2", agent_type="worker", issue=42, first_prompt="Unit: 2 of 3\n",
            turn_timestamps=[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)] * 4,
        ),
        _spawn(
            session="ws1", agent_type="worker-strong", issue=42, first_prompt="Unit: 3 of 3\n",
            turn_timestamps=[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)] * 5,
        ),
    ]
    out = cl.turns_by_agent_type(spawns)
    assert out["worker"] == {"n": 2, "total_turns": 6, "mean": 3.0, "median": 3.0}
    assert out["worker-strong"] == {"n": 1, "total_turns": 5, "mean": 5.0, "median": 5.0}


def test_units_by_issue_three_spawns_two_overlapping():
    """Row 2 of #254's acceptance: 3 spawns of one issue, two alive at once, the third after
    them; prompts carry Unit: 1 of 3 / 2 of 3 / 3 of 3."""

    a_start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    a_end = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    b_start = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)  # overlaps with A
    b_end = datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
    c_start = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)  # after A and B both end
    c_end = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    close_ts = datetime(2026, 1, 1, 0, 40, tzinfo=timezone.utc)

    spawns = [
        _spawn(session="a", agent_type="worker", issue=42, first_prompt="Unit: 1 of 3\n",
               turn_timestamps=[a_start, a_end]),
        _spawn(session="b", agent_type="worker", issue=42, first_prompt="Unit: 2 of 3\n",
               turn_timestamps=[b_start, b_end]),
        _spawn(session="c", agent_type="worker-strong", issue=42, first_prompt="Unit: 3 of 3\n",
               turn_timestamps=[c_start, c_end]),
    ]
    out = cl.units_by_issue(spawns, {42: close_ts})
    assert len(out) == 1
    iu = out[0]
    assert iu.issue == 42
    assert iu.n_spawns == 3
    assert iu.n_units == 3
    assert iu.peak_alive == 2
    assert iu.whole_issue_spawns == 0
    assert iu.wall_clock_seconds == pytest.approx((close_ts - a_start).total_seconds())


def test_units_by_issue_single_whole_issue_spawn():
    """Row 3 of #254's acceptance: one spawn with no Unit: line."""

    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    close_ts = datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)
    spawns = [
        _spawn(session="a", agent_type="worker", issue=55, first_prompt="Work on #55.\n",
               turn_timestamps=[start, end]),
    ]
    out = cl.units_by_issue(spawns, {55: close_ts})
    assert len(out) == 1
    iu = out[0]
    assert iu.issue == 55
    assert iu.n_spawns == 1
    assert iu.n_units == 1
    assert iu.peak_alive == 1
    assert iu.whole_issue_spawns == 1
    assert iu.wall_clock_seconds == pytest.approx((close_ts - start).total_seconds())


def test_build_report_includes_units_section(spawns, prices):
    report = cl.build_report(
        projects_dir=PROJECTS_DIR,
        prices=prices,
        since=SINCE,
        until=UNTIL,
        sessions_file=SESSIONS_BOTH,
        spawns_limit=None,
        issues_limit=None,
    )
    assert "Units: spawns, turns, turns per spawn" in report
    assert "Units per closed issue" in report


# ------------------------------------------------------------------- #249 gap and reopen ----


def _at(minute: int) -> datetime:
    return datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)


def _gh_thread(path: Path, calls: list[tuple[int, str, int]]) -> Path:
    """A main thread of Bash calls: (minute, 'close' | 'reopen', issue), each succeeding."""

    import json

    lines = []
    for i, (minute, kind, n) in enumerate(calls):
        verb = "Closed" if kind == "close" else "Reopened"
        stamp = f"2026-01-01T12:{minute:02d}:00Z"
        lines.append(json.dumps({
            "type": "assistant", "timestamp": stamp,
            "message": {"id": f"m{i}", "model": "claude-opus-5-5", "usage": {"input_tokens": 1},
                        "content": [{"type": "tool_use", "id": f"tu{i}", "name": "Bash",
                                     "input": {"command": f"gh issue {kind} {n}"}}]}}))
        lines.append(json.dumps({
            "type": "user", "timestamp": stamp,
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": f"tu{i}",
                "content": [{"type": "text", "text": f"✓ {verb} issue o/r#{n} (t)"}]}]}}))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_reopened_close_not_counted(tmp_path):
    a = _gh_thread(tmp_path / "a.jsonl", [(1, "close", 5), (2, "close", 6)])
    b = _gh_thread(tmp_path / "b.jsonl", [(3, "reopen", 5)])
    until = _at(30)
    target = [("a", a), ("b", b)]
    assert set(cl.gh_closed_issues(target, until, None)) == {6}
    assert cl.session_close_lists(target, until) == [("a", [6]), ("b", [])]


def test_reclosed_issue_counts_once_for_the_last_closer(tmp_path):
    a = _gh_thread(tmp_path / "a.jsonl", [(1, "close", 5)])
    b = _gh_thread(tmp_path / "b.jsonl", [(3, "reopen", 5), (4, "close", 5)])
    c = _gh_thread(tmp_path / "c.jsonl", [(5, "close", 7)])
    target = [("a", a), ("b", b), ("c", c)]
    assert cl.session_close_lists(target, _at(30)) == [("a", []), ("b", [5]), ("c", [7])]
    assert set(cl.gh_closed_issues(target, _at(30), None)) == {5, 7}
    # reopened and not closed again before --until: not counted
    assert cl.session_close_lists(target, _at(3)) == [("a", []), ("b", []), ("c", [])]


def test_handback_gap_never_negative_and_skips_overlapping_spawn():
    def mk(**kw):
        return _spawn(issue=9, first_prompt="", **kw)

    first = mk(session="s1", agent_type="worker", turn_timestamps=[_at(0), _at(30)])
    first.last_message = "Context hand-back\nbranch"
    overlap = mk(session="s2", agent_type="worker", turn_timestamps=[_at(5), _at(20)])
    later = mk(session="s3", agent_type="worker", turn_timestamps=[_at(40), _at(50)])
    n, gaps = cl.context_handback([first, overlap, later])
    assert n == 1
    assert gaps == [pytest.approx(10.0)]
    # no spawn started after the hand-back's last turn: no gap at all
    n, gaps = cl.context_handback([first, overlap])
    assert n == 1 and gaps == []


def test_reopen_only_in_non_set_transcript_drops_the_set_close(tmp_path):
    a = _gh_thread(tmp_path / "a.jsonl", [(1, "close", 5), (2, "close", 6)])
    other = _gh_thread(tmp_path / "other.jsonl", [(3, "reopen", 5)])
    since = _at(0)
    reopens = cl.scan_reopens(tmp_path, since, _at(30))
    assert [n for _t, n in reopens] == [5]
    target = [("a", a)]  # `other` is not a session of the set
    assert set(cl.gh_closed_issues(target, _at(30), None, reopens)) == {6}
    assert cl.session_close_lists(target, _at(30), reopens) == [("a", [6])]
    # a transcript last written before --since is not scanned
    assert cl.scan_reopens(tmp_path, datetime.now(timezone.utc) + timedelta(days=1), _at(30)) == []
    assert other.exists()


# ------------------------------------------------------------------ #300 cut-table units ----


def _cut_thread(path: Path, commands: list[str]) -> Path:
    import json

    lines = [
        json.dumps({
            "type": "assistant", "timestamp": f"2026-01-01T12:{i:02d}:00Z",
            "message": {"id": f"m{i}", "model": "claude-opus-5-5", "usage": {"input_tokens": 1},
                        "content": [{"type": "tool_use", "id": f"tu{i}", "name": "Bash",
                                     "input": {"command": cmd}}]}})
        for i, cmd in enumerate(commands)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _table(n: int) -> str:
    rows = "\n".join(f"| {k} of {n} (part {k}) | out | f.py | t | - |" for k in range(1, n + 1))
    return "| unit | outcome | files it edits | its test | needs |\n|---|---|---|---|---|\n" + rows


def _w_spawn(issue: int, k: int, n: int) -> cl.Spawn:
    return _spawn(session=f"w{issue}_{k}", agent_type="worker", issue=issue,
                  first_prompt=f"Unit: {k} of {n}\n", turn_timestamps=[_at(1), _at(2)])


def test_cut_table_three_units_two_by_spawn_one_by_orch(tmp_path):
    p = _cut_thread(tmp_path / "o.jsonl", [f'gh issue comment 283 --body "{_table(3)}"'])
    tables = cl.cut_tables_by_issue([("o", p)], _at(30))
    out = cl.units_by_issue([_w_spawn(283, 1, 3), _w_spawn(283, 2, 3)], {283: _at(20)}, tables)
    assert [(iu.issue, iu.n_units, iu.by_spawn, iu.by_orch) for iu in out] == [(283, 3, 2, 1)]


def test_cut_table_one_unit_no_spawn_issue_is_listed(tmp_path):
    p = _cut_thread(tmp_path / "o.jsonl", [f'gh issue comment 299 --body "{_table(1)}"'])
    tables = cl.cut_tables_by_issue([("o", p)], _at(30))
    out = cl.units_by_issue([], {299: _at(20)}, tables)
    assert [(iu.issue, iu.n_spawns, iu.n_units, iu.by_spawn, iu.by_orch) for iu in out] == [(299, 0, 1, 0, 1)]
    # not closed in the window: absent
    assert cl.units_by_issue([], {}, tables) == []


def test_cut_table_in_heredoc_to_file_then_body_file(tmp_path):
    cmd = f"cat > c.md <<'EOF'\nCheckpoint\n{_table(2)}\nEOF\ngh issue comment 77 --body-file c.md"
    p = _cut_thread(tmp_path / "o.jsonl", [cmd])
    assert cl.cut_tables_by_issue([("o", p)], _at(30)) == {77: ({1, 2}, 2)}


def test_latest_cut_table_wins_and_until_cuts(tmp_path):
    p = _cut_thread(tmp_path / "o.jsonl", [
        f'gh issue comment 5 --body "{_table(2)}"', f'gh issue comment 5 --body "{_table(4)}"'])
    assert cl.cut_tables_by_issue([("o", p)], _at(30))[5][1] == 4
    assert cl.cut_tables_by_issue([("o", p)], _at(0))[5][1] == 2


# ------------------------------------------ #300 unit 3: peak, headline, header ----


def _peak_events():
    return [
        {"ts": "2026-09-27T10:00:00+00:00", "kind": "orch_start", "issues": [], "session": "sA"},
        {"ts": "2026-09-27T10:10:00+00:00", "kind": "orch_start", "issues": [], "session": "sB"},
        {"ts": "2026-09-27T10:30:00+00:00", "kind": "orch_session_end", "session": "sB"},
    ]


def test_peak_no_end_event_ends_at_transcripts_last_turn():  # row 10
    last = {"sA": datetime(2026, 9, 27, 10, 20, tzinfo=timezone.utc)}
    result = cl.peak_orch_sessions(_peak_events(), CL_SINCE, CL_UNTIL, last_turns=last)
    assert result.peak == 2
    assert result.n_excluded == 0
    # A ended at 10:20 (its last turn): a session starting at 10:40 does not overlap it
    events = _peak_events() + [
        {"ts": "2026-09-27T10:40:00+00:00", "kind": "orch_start", "issues": [], "session": "sC"},
        {"ts": "2026-09-27T10:50:00+00:00", "kind": "orch_session_end", "session": "sC"},
    ]
    assert cl.peak_orch_sessions(events, CL_SINCE, CL_UNTIL, last_turns=last).peak == 2


def test_peak_no_end_event_no_transcript_left_out_and_named(tmp_path, prices):  # row 11
    result = cl.peak_orch_sessions(_peak_events(), CL_SINCE, CL_UNTIL, last_turns={})
    assert result.peak == 1
    assert result.n_excluded == 1
    assert result.excluded_ids == ["sA"]
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("\n".join(_json.dumps(e) for e in _peak_events()), encoding="utf-8")
    report = cl.build_report(
        projects_dir=tmp_path / "no-projects", prices=prices,
        since=CL_SINCE, until=CL_UNTIL, sessions_file=None, spawns_limit=None, issues_limit=None,
        dispatch_out=NO_DISPATCH_OUT, orch_session_json=NO_ORCH_SESSION_JSON,
        merge_log=tmp_path / "none.log", events_file=events_file,
    )
    assert "1 session(s) left out: no end event, not listed live, no transcript: sA" in report


def test_build_report_marks_headline_and_attribution_coverage():  # row 12
    prices = cl.tm.load_prices(PRICES_PATH_197)
    report = cl.build_report(
        projects_dir=PROJECTS_DIR_197, prices=prices, since=SINCE_197, until=UNTIL_197,
        sessions_file=None, spawns_limit=None, issues_limit=None,
        dispatch_out=NO_DISPATCH_OUT, orch_session_json=NO_ORCH_SESSION_JSON,
    )
    lines = report.splitlines()
    whole = [ln for ln in lines if "The whole cost per closed issue, mean" in ln]
    assert len(whole) == 1 and whole[0].startswith("Headline: ")
    attr = [ln for ln in lines if ln.startswith("The same, median per issue")]
    assert len(attr) == 1
    assert "covers 4 of 4 closed issue(s)" in attr[0]


def test_whole_cost_attribution_holds_turns_of_one_of_the_closes(prices):  # row 12
    target = cl.discover_target_sessions(PROJECTS_DIR, SINCE, UNTIL, SESSIONS_BOTH)
    whole = cl.whole_cost_section(PROJECTS_DIR, target, UNTIL, prices, None)
    assert whole.n_attributed_issues == 1 and whole.n_closed_issues == 1


def test_header_prints_window_in_local_clock_with_offset():  # row 1
    tz = timezone(timedelta(hours=2))
    since = cl.tm.parse_date_arg("2026-09-28T12:45", tz=tz)
    assert since == datetime(2026, 9, 28, 10, 45, tzinfo=timezone.utc)
    report = cl.build_report(
        projects_dir=PROJECTS_DIR_197, prices=cl.tm.load_prices(PRICES_PATH_197), since=since,
        until=since + timedelta(hours=1), sessions_file=None, spawns_limit=None, issues_limit=None,
        dispatch_out=NO_DISPATCH_OUT, orch_session_json=NO_ORCH_SESSION_JSON, tz=tz,
    )
    assert report.splitlines()[0].startswith(
        "Cost levers: 2026-09-28T12:45:00+02:00 .. 2026-09-28T13:45:00+02:00"
    )


def test_help_names_the_local_clock():  # row 4
    help_text = cl.build_arg_parser().format_help()
    assert "local clock unless it carries Z or an offset" in " ".join(help_text.split())


def test_attribution_line_prints_1_of_4(monkeypatch):  # row 12
    real = cl.whole_cost_section

    def fake(*a, **k):
        import dataclasses
        return dataclasses.replace(real(*a, **k), n_attributed_issues=1)

    monkeypatch.setattr(cl, "whole_cost_section", fake)
    report = cl.build_report(
        projects_dir=PROJECTS_DIR_197, prices=cl.tm.load_prices(PRICES_PATH_197),
        since=SINCE_197, until=UNTIL_197, sessions_file=None, spawns_limit=None, issues_limit=None,
        dispatch_out=NO_DISPATCH_OUT, orch_session_json=NO_ORCH_SESSION_JSON,
    )
    attr = [ln for ln in report.splitlines() if ln.startswith("The same, median per issue")]
    assert "covers 1 of 4 closed issue(s)" in attr[0]
