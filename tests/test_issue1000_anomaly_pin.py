"""#1000 (unit 2): every outside call of the anomaly guard and of the pin ref is bounded, and a hit is one log line.

One case per call site: each uses a fake runner that raises `TimeoutExpired`. Fakes only: no real gh, no ssh,
no git, no claude.exe, no PoB, and nothing sleeps.

Red on the unchanged source (before this unit): the issue finder (raises instead of answering None), the pin
ref git call (two calls in one pass, no log line) and the snapshot git call (the plain `subprocess.run` raises).
Green on the unchanged source: the keymaster `claude` calls and the laptop probe, which were already bounded
(30 s and 45 s, `hosts.py` #998); they are kept under this test so the call sites stay covered.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import bounded  # noqa: E402
from junkroan.runs import hosts as hosts_mod  # noqa: E402
from junkroan.runs import pin_ref  # noqa: E402
from junkroan.runs.pass_guard import GUARD  # noqa: E402
import run_queue  # noqa: E402


@pytest.fixture(autouse=True)
def _guard_starts_and_ends_clean():
    """GUARD is one module-level record: a key left down here must not leak into another test file."""
    GUARD.begin()
    yield
    GUARD.begin()


def _plain_run_hangs(argv, **kwargs):
    """What the unchanged source reaches for: a plain `subprocess.run` that times out (no real process)."""
    raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))


def _lines_with(text: str, needle: str) -> int:
    return sum(1 for line in text.splitlines() if needle in line)


# -- ssh: the laptop probe of the anomaly guard (`make_host_prober` -> `hosts.run_on_host`) --------

def test_laptop_probe_ssh_timeout_is_one_line_and_the_pass_makes_no_second_call(monkeypatch, capsys):
    calls = []

    def hang(argv, **kwargs):
        calls.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(hosts_mod, "run_bounded", hang)
    probe = an.make_host_prober({"name": "laptop", "ssh": "laptop-test"})

    assert probe() is False                       # a failed probe, the decision the guard already takes
    assert probe() is False                       # the next tick in the same pass: ssh is skipped
    assert calls == [hosts_mod.SSH_TIMEOUT_SECONDS] and hosts_mod.SSH_TIMEOUT_SECONDS <= 45.0
    assert _lines_with(capsys.readouterr().err, "did not answer") == 1
    assert GUARD.down("ssh:laptop-test")


# -- gh: the issue finder of an anomaly ------------------------------------------------------------

def test_issue_finder_gh_timeout_returns_no_issue_within_the_limit_and_logs_once(monkeypatch, capsys):
    calls = []

    def hang(argv, **kwargs):
        calls.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    find = an.make_issue_finder(hang)
    assert find("host_unreachable:laptop") is None   # the same answer as "no open issue": the anomaly goes the old way
    assert find("host_unreachable:laptop") is None   # the next anomaly of the pass: gh is skipped, no call
    assert calls == [an.GH_FINDER_TIMEOUT_SECONDS] and an.GH_FINDER_TIMEOUT_SECONDS <= 45.0
    assert _lines_with(capsys.readouterr().err, "did not answer") == 1
    assert GUARD.down("gh")


def test_issue_finder_default_runner_is_the_tree_killing_one(monkeypatch, capsys):
    """Red before #1000: the default was the plain `subprocess.run`, which kills only the gh child (#521)."""
    seen = []

    def hang_tree(argv, **kwargs):
        seen.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(bounded, "run_bounded", hang_tree)
    monkeypatch.setattr(subprocess, "run", _plain_run_hangs)
    assert an.make_issue_finder()("host_unreachable:laptop") is None
    assert seen == [an.GH_FINDER_TIMEOUT_SECONDS]


# -- git: the pin ref fetch (`pin_ref.fetch_pin`, the snapshot's own pin fetch) --------------------

def test_fetch_pin_git_timeout_is_a_failed_read_one_line_and_origin_skipped_for_the_pass(monkeypatch, tmp_path, capsys):
    calls = []

    def hang(argv, **kwargs):
        calls.append((list(argv), kwargs["timeout"]))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(pin_ref, "run_bounded", hang)
    assert pin_ref.fetch_pin(tmp_path, "abcdef1") is False      # the failed read: nothing fetched
    assert pin_ref.fetch_pin(tmp_path, "abcdef1") is False      # the same pass: origin is not asked again
    assert len(calls) == 1, calls
    assert all(timeout <= 60.0 for _, timeout in calls), calls
    assert _lines_with(capsys.readouterr().err, "did not answer") == 1
    assert GUARD.down(pin_ref.GIT_GUARD_KEY)


# -- git: the snapshot's own git calls (`run_queue._snap_git`) -------------------------------------

def test_snapshot_git_timeout_is_a_failed_git_call_that_keeps_the_snapshot(monkeypatch, tmp_path):
    lines: list[str] = []
    calls: list[object] = []

    def hang(argv, **kwargs):
        calls.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(run_queue, "log", lines.append)
    monkeypatch.setattr(bounded, "run_bounded", hang)
    monkeypatch.setattr(run_queue.subprocess, "run", _plain_run_hangs)

    res = run_queue._snap_git(tmp_path / "snap", "status", "--porcelain")
    assert res.returncode == 1
    assert calls == [60], calls
    assert len(lines) == 1, lines
    # the caller reads it as any failed git call: RuntimeError, the snapshot is kept, not dropped
    with pytest.raises(RuntimeError, match="git status failed"):
        run_queue.save_snapshot_diff(tmp_path / "snap", "job-1000")


# -- keymaster `claude` calls (`ClaudeKeymasterCli`): already bounded, callers already skip ------

@pytest.mark.parametrize("call", ["list", "start", "end"])
def test_keymaster_claude_calls_are_bounded_and_a_timeout_reaches_the_callers_skip_path(monkeypatch, tmp_path, call):
    seen: list[float] = []

    def hang(argv, **kwargs):
        seen.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(an, "run_bounded", hang)
    cli = an.ClaudeKeymasterCli(exe="claude.exe", cwd=tmp_path)
    anomaly = an.Anomaly(kind="host_unreachable", key="host_unreachable:laptop", host="laptop", detail="x")
    with pytest.raises(subprocess.TimeoutExpired):
        if call == "list":
            cli.list_sessions()
        elif call == "start":
            cli.start(anomaly)
        else:
            cli.end({"id": "s1"})
    assert seen and max(seen) <= 45.0, seen
