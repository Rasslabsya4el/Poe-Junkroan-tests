"""#998 (unit 3): every `gh` call of a daemon pass is bounded at 45 s, and a dead `gh` costs one call per pass.

Fakes only: `run_bounded` is replaced, so no real gh, no ssh, no PoB, and nothing sleeps.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs.pass_guard import GUARD  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402


@pytest.fixture(autouse=True)
def _guard_starts_and_ends_clean():
    """GUARD is one module-level record: a test that leaves gh down must not leak into the next file."""
    GUARD.begin()
    yield
    GUARD.begin()


class GhRunner:
    """Stands in for `run_bounded` on gh argv: counts each gh call and its timeout.

    `hang=True`: every gh call raises TimeoutExpired. `hang=False`: every gh call answers
    `{"state": "OPEN"}` with return code 0 (a comment or label then goes through too).
    Non-gh argv answers 0 with no output.
    """

    def __init__(self, hang: bool) -> None:
        self.hang = hang
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, argv, **kwargs):
        if argv[0] != "gh":
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        self.calls.append(list(argv))
        self.timeouts.append(kwargs.get("timeout"))
        if self.hang:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"state": "OPEN", "comments": []}), stderr="")


def _five_queued(store):
    return [store.submit(host="pc", priority="P1", tag=f"t{n}", cmd="echo hi", issue=n) for n in range(1, 6)]


def _started_indices(store, jobs):
    return [i for i, job in enumerate(jobs) if store.get(job.id).state == "running"]


def test_hanging_gh_one_call_per_tick_and_no_job_touched_by_the_ticket_check(tmp_path, monkeypatch):
    hang = GhRunner(hang=True)
    monkeypatch.setattr(daemon_mod, "run_bounded", hang)
    daemon, store, _ = make_daemon(tmp_path, gh=daemon_mod.GhCli(cwd=tmp_path), launcher=FakeLauncher())
    logs: list[str] = []
    daemon.log = logs.append
    jobs = _five_queued(store)

    daemon.tick()

    assert len(hang.calls) == 1, hang.calls          # the ticket check's one read; the other four issues are not read
    assert all(t is not None and t <= 45.0 for t in hang.timeouts), hang.timeouts
    assert any("could not read #1" in line for line in logs), logs
    hung_states = [store.get(job.id).state for job in jobs]
    hung_started = _started_indices(store, jobs)

    # the same tick with gh answering 'open': the same jobs start, none is stopped or cancelled
    answer = GhRunner(hang=False)
    monkeypatch.setattr(daemon_mod, "run_bounded", answer)
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    daemon2, store2, _ = make_daemon(open_dir, gh=daemon_mod.GhCli(cwd=open_dir), launcher=FakeLauncher())
    daemon2.log = lambda line: None
    jobs2 = _five_queued(store2)
    daemon2.tick()

    assert [store2.get(job.id).state for job in jobs2] == hung_states
    assert _started_indices(store2, jobs2) == hung_started == [0, 1, 2, 3, 4]


def test_hanging_gh_one_call_per_pass_when_many_handbacks_are_due(tmp_path, monkeypatch):
    """Red before #998: five finished jobs each called `gh issue comment` and waited its own timeout."""

    hang = GhRunner(hang=True)
    monkeypatch.setattr(daemon_mod, "run_bounded", hang)
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, gh=daemon_mod.GhCli(cwd=tmp_path), launcher=launcher)
    daemon.log = lambda line: None
    jobs = _five_queued(store)
    daemon.tick()                                     # starts the five (the ticket check reads once here)
    assert _started_indices(store, jobs) == [0, 1, 2, 3, 4]
    for record in launcher.started:
        launcher.finish(record["pid"], 0)
    hang.calls.clear()
    hang.timeouts.clear()

    daemon.tick()                                     # the five end: each would post a hand-back comment

    assert len(hang.calls) == 1, hang.calls
    assert all(t is not None and t <= 45.0 for t in hang.timeouts), hang.timeouts
    assert [store.get(job.id).state for job in jobs] == ["done"] * 5
    assert all(store.get(job.id).posted is False for job in jobs)   # nothing got through: retried later


def test_gh_timeout_is_capped_at_45_seconds_whatever_the_constructor_says(tmp_path, monkeypatch):
    seen = []

    def fake(argv, **kwargs):
        seen.append(kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"state": "OPEN", "comments": []}), stderr="")

    monkeypatch.setattr(daemon_mod, "run_bounded", fake)
    GUARD.begin()
    gh = daemon_mod.GhCli(cwd=tmp_path)
    assert gh.timeout == 45.0
    gh.comment(7, "x")
    gh.issue_open(7)
    gh.existing_comments(7)
    gh.issue_state(7)
    assert seen == [45.0, 45.0, 45.0, 30.0]          # issue_state keeps its own 30 s
    seen.clear()
    GUARD.begin()
    big = daemon_mod.GhCli(cwd=tmp_path, timeout=120.0)
    big.add_label(7, "ready-for-agent")
    assert seen == [45.0]


def test_a_nonzero_return_code_is_read_by_the_caller_and_does_not_mark_gh_down(tmp_path, monkeypatch):
    def rc1(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not found")

    monkeypatch.setattr(daemon_mod, "run_bounded", rc1)
    GUARD.begin()
    gh = daemon_mod.GhCli(cwd=tmp_path)
    assert gh.comment(7, "x") is False
    assert not GUARD.down("gh")


def test_after_one_timeout_the_pass_makes_no_further_gh_call(tmp_path, monkeypatch):
    hang = GhRunner(hang=True)
    monkeypatch.setattr(daemon_mod, "run_bounded", hang)
    GUARD.begin()
    gh = daemon_mod.GhCli(cwd=tmp_path)
    assert gh.issue_state(7) is None                  # the one call of this pass
    assert gh.comment(7, "x") is False
    assert gh.add_label(7, "ready-for-agent") is False
    assert gh.issue_open(7) is None
    assert gh.existing_comments(7) is None
    assert gh.create_issue("t", "b", []) is None
    assert gh.add_sub_issue(404, 414) is False
    assert len(hang.calls) == 1
    assert GUARD.down("gh")
    GUARD.begin()                                     # the next pass tries again
    assert gh.issue_state(7) is None
    assert len(hang.calls) == 2
