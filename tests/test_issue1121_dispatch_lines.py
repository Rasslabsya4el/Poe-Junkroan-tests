"""The dispatcher's `start held` and rate-limit log lines end with ` [issues #N ...]` naming the issues they hold back."""

from __future__ import annotations

import re
import subprocess

from junkroan.pob.slot_budget import admission_now
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue
from tools.agentops.dispatch import GhCli

SUFFIX_RE = re.compile(r"\[issues((?: #\d+)+)\]")


def _busy_dispatcher(tmp_path, candidates):
    claude, clock = FakeClaude(), FakeClock()
    d = _dispatcher(tmp_path, claude=claude, gh=FakeGh(candidates=candidates), clock=clock)
    lines: list[str] = []
    d.log = lines.append
    d.admission = lambda prev: admission_now(
        now=1000.0, samples=[(1000.0 - 10 * i, 9.2) for i in range(8)],
        previous_wait=prev, cores=12, mode="day")
    return d, claude, clock, lines


def test_start_held_line_names_the_offered_issues(tmp_path):
    d, claude, clock, lines = _busy_dispatcher(tmp_path, [_issue(4), _issue(9)])
    d.run(ticks=1, sleep=lambda s: clock.advance(30))
    held = [l for l in lines if "start held" in l]
    assert not claude.started and len(held) == 1
    match = SUFFIX_RE.search(held[0])
    assert match is not None
    assert match.group(1).split() == ["#4", "#9"]
    assert held[0].endswith(" [issues #4 #9]")


def _failing_gh(stderr: str) -> GhCli:
    def runner(args, stdin):
        return subprocess.CompletedProcess(args, 1, "", stderr)
    return GhCli(runner=runner)


def test_rate_limit_failure_about_issue_names_it(capsys):
    gh = _failing_gh("gh: API rate limit exceeded, waiting until 12:00:00")
    assert gh.issue_title_and_last_comment(7) is None
    err = capsys.readouterr().err
    assert "rate limit" in err
    assert err.rstrip("\n").endswith(" [issues #7]")
    assert SUFFIX_RE.search(err).group(1) == " #7"


def test_rate_limit_failure_about_no_issue_has_no_suffix(capsys):
    gh = _failing_gh("You have exceeded a secondary rate limit")
    assert gh.claimed_issues() is None
    err = capsys.readouterr().err
    assert "secondary rate limit" in err
    assert SUFFIX_RE.search(err) is None


def test_plain_failure_about_issue_has_no_suffix(capsys):
    gh = _failing_gh("not found")
    assert gh.issue_title_and_last_comment(7) is None
    err = capsys.readouterr().err
    assert "not found" in err
    assert SUFFIX_RE.search(err) is None
