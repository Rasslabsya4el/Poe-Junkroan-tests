"""#998 unit 4: the daemon's local calls are bounded (pid_alive 15 s, every git call of make_snapshot 30 s,
run_issue._compare 60 s).

Fakes only: subprocess.run raises subprocess.TimeoutExpired; no sleep, no real process, no PoB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from junkroan.runs import daemon as daemon_mod
from junkroan.runs import run_issue

rq = daemon_mod.run_queue()


def _timeouts(calls: list):
    """A subprocess.run stand-in that records (argv, timeout) and always times out."""

    def fake_run(args, *a, **kw):
        calls.append((list(args), kw.get("timeout")))
        raise subprocess.TimeoutExpired(args, kw.get("timeout") or 0)

    return fake_run


def test_pid_alive_timeout_counts_as_alive(monkeypatch):
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _timeouts(calls))
    assert rq.pid_alive(4242) is True
    assert calls == [(["tasklist", "/FI", "PID eq 4242"], 15)]


def test_make_snapshot_git_timeout_is_a_failed_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "ROOT", tmp_path)
    monkeypatch.setattr(rq, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(rq, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _timeouts(calls))
    assert rq.make_snapshot("x") is None
    assert rq.LAST_SNAPSHOT_FAILURE and "timed out" in rq.LAST_SNAPSHOT_FAILURE
    assert calls and all(t == 30 for _, t in calls)


def test_make_snapshot_mklink_timeout_drops_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "ROOT", tmp_path)
    monkeypatch.setattr(rq, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(rq, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    for d in ("var", "artifacts", "vendor"):
        (tmp_path / d).mkdir()
    calls: list = []
    dropped: list = []

    def fake_run(args, *a, **kw):
        calls.append((list(args), kw.get("timeout")))
        if args[0] == "cmd":
            raise subprocess.TimeoutExpired(args, kw.get("timeout") or 0)
        if "worktree" in args and "add" in args:
            Path(args[5]).mkdir(parents=True)
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(rq, "drop_snapshot", lambda snap: dropped.append(snap))
    assert rq.make_snapshot("x") is None
    assert dropped == [tmp_path / "snapshots" / "x"]
    assert ("cmd" in [c[0][0] for c in calls]) and all(t == 30 for a, t in calls if a[0] in ("cmd", "git"))


def test_compare_timeout_omits_the_text(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _timeouts(calls))
    text, verdict = run_issue._compare(tmp_path / "control", tmp_path / "run")
    assert text == ""
    assert verdict.startswith("error")
    assert calls[0][1] == 60


def test_compare_failing_script_gives_the_same_shape(monkeypatch, tmp_path):
    """Baseline: a script that exits 3 with no output returns no text and an error verdict."""

    def fake_run(args, *a, **kw):
        return subprocess.CompletedProcess(args, 3, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_issue._compare(tmp_path / "control", tmp_path / "run") == ("", "error (rc 3)")
