from __future__ import annotations

from pathlib import Path

from junkroan.runs.run_issue import gear_of, is_whole_set_job, pick_control, run_body, run_title
from junkroan.runs.store import Job

FIX = Path(__file__).parent / "fixtures" / "run_issue"
NEW = FIX / "20261001-0100-filler-smoke-loot-s7"
OLD = FIX / "20260930-0100-filler-smoke-loot-s7"
BENCH = "py -3.12 scripts/benchmark.py --set {s} --seed 7 --seeds 3 --gear {g} --tag x"


def job(jid="j-1", cmd=None, rc=0, end="2026-10-01T10:00:00+00:00", run_dir="r", set_="smoke", gear="loot"):
    return Job(id=jid, host="pc", priority="normal", issue=None, submitter="t", tag="filler-smoke-loot-s7", pin=None,
               cmd=cmd if cmd is not None else BENCH.format(s=set_, g=gear), resumable=False, state="done",
               submit_ts="2026-10-01T08:00:00+00:00", start_ts="2026-10-01T08:30:00+00:00", end_ts=end, rc=rc, run_dir=run_dir)


def test_title_and_table_rows():
    j = job(run_dir=str(NEW))
    assert run_title(j, NEW) == "Run 20261001-0100-filler-smoke-loot-s7 (smoke, pc)"
    body = run_body(j, NEW)
    rows = [l for l in body.splitlines() if l.startswith("| ") and not l.startswith("| reference")]
    assert len(rows) == 6
    assert "6 references at or above the author" in body or "of 6 references at or above the author" in body
    assert "no earlier run of smoke loot" in body
    assert "duration: 1 h 30 min" in body


def test_is_whole_set_job():
    assert is_whole_set_job(job()) == "smoke"
    assert is_whole_set_job(job(rc=1)) is None
    assert is_whole_set_job(job(rc=None)) is None
    assert is_whole_set_job(job(cmd="py scripts/benchmark.py --slugs a b --gear loot")) is None
    assert is_whole_set_job(job(cmd="py -m pytest tests -q")) is None
    assert gear_of(job()) == "loot"
    assert gear_of(job(cmd="py scripts/benchmark.py --set smoke")) is None


def test_pick_control():
    me = job("j-me", set_="new18")
    a = job("j-a", set_="new18", end="2026-09-29T10:00:00+00:00")
    b = job("j-b", set_="new18", end="2026-09-30T10:00:00+00:00")
    w = job("j-w", set_="new18", gear="wishlist", end="2026-09-30T20:00:00+00:00")
    later = job("j-l", set_="new18", end="2026-10-02T10:00:00+00:00")
    assert pick_control(me, [a, b, w, later, me]).id == "j-b"
    assert pick_control(me, [w, later]) is None
    assert "no earlier run of new18 loot" in run_body(me, NEW, None)


def test_compare_verdict():
    j = job(run_dir=str(NEW))
    assert "**PASS**" in run_body(j, NEW, OLD)
    assert "| reference |" in run_body(j, NEW, OLD)
    assert "**FAIL**" in run_body(j, FIX / "20260929-0100-filler-smoke-loot-s7", NEW)
    assert "**incomplete**" in run_body(j, NEW, FIX / "missing")


def test_issue_text_passes_the_ticket_shape():
    from tools.agentops.ticket_shape import check

    j = job(run_dir=str(NEW))
    for control in (None, OLD):  # no earlier run -> "not compared"; with a control -> PASS
        title, body = run_title(j, NEW), run_body(j, NEW, control)
        assert check(title, body) == []
        assert body.startswith("## For the human") and "\n## For the agent\n- job:" in body
    failed = run_body(j, FIX / "20260929-0100-filler-smoke-loot-s7", NEW)  # compare verdict FAIL
    assert "**FAIL**" in failed and check(run_title(j, NEW), failed) == []
    long = Path("x") / ("a-" * 60 + "#7")
    assert len(run_title(j, long)) <= 80 and check(run_title(j, long), None) == []
