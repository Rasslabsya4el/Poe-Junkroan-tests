"""#664 unit 1: `merge --issue N` plumbing, the `merge-stats:` last line, the detach record fields."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from tests.test_agentops_merge import _push_branch, _world, _git
from tools.agentops import detach, merge as merge_module
from tools.agentops.merge import MergeLock, add_commit_subparser, add_subparser, run_merge_command


@pytest.fixture(autouse=True)
def _protect(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_suite_out")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_merge.log")


def _parser():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    add_subparser(sub)
    add_commit_subparser(sub)
    return ap


def test_issue_flag_parsing():
    assert _parser().parse_args(["merge", "b", "--issue", "5", "--issue", "7"]).issue == [5, 7]
    assert _parser().parse_args(["merge", "b"]).issue == []
    with pytest.raises(SystemExit) as e:
        _parser().parse_args(["merge", "b", "--issue", "x"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        _parser().parse_args(["commit", "-m", "x", "--issue", "5", "f"])
    assert e.value.code != 0


def test_merge_ticket_carries_issues_and_last_line_is_stats(tmp_path, monkeypatch, capsys):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    seen = []
    real = MergeLock.acquire

    def spy(self, *a, ticket_info=None, **k):
        seen.append(ticket_info)
        return real(self, *a, ticket_info=ticket_info, **k)

    monkeypatch.setattr(MergeLock, "acquire", spy)
    monkeypatch.setattr(merge_module, "resolve_suite_env", lambda: {})
    args = _parser().parse_args(["merge", "feature-a", "--suite", f'"{sys.executable}" -c "pass"',
                                 "--cwd", str(checkout), "--lock", str(tmp_path / "m.lock"),
                                 "--issue", "1", "--issue", "2"])
    rc = run_merge_command(args)
    out = capsys.readouterr().out.rstrip("\n").splitlines()
    assert rc == 0
    assert seen[0]["issues"] == [1, 2]
    assert out[-1].startswith("merge-stats: in_line_s=")
    import re
    assert re.match(r"^merge-stats: in_line_s=\d", out[-1])


def test_run_and_record_reads_stats_and_issues(tmp_path):
    code = "print('ok'); print('merge-stats: in_line_s=1.5 suite_s=20.0 failed=0')"
    rec = _record(tmp_path, [sys.executable, "-c", code, "--issue", "3"])
    assert rec["issues"] == [3] and rec["in_line_s"] == 1.5 and rec["suite_s"] == 20.0 and rec["failed"] == 0
    rec = _record(tmp_path, [sys.executable, "-c", "print('hi')"])
    assert rec["in_line_s"] is None and rec["suite_s"] is None and rec["failed"] is None
    assert rec["issues"] == []
    rec = _record(tmp_path, [sys.executable, "-c", "print('merge-stats: in_line_s=2.0 suite_s=- failed=-')"])
    assert rec["in_line_s"] == 2.0 and rec["suite_s"] is None and rec["failed"] is None


import types


class _FakeGh:
    """No test reaches the real tracker (#712): every hand-back call is swallowed."""
    def issue_status(self, number):
        return types.SimpleNamespace(open=False)  # a closed issue: the hand-back posts nothing


def _record(tmp_path, argv):
    import json
    f = tmp_path / "r.json"
    detach.run_and_record(argv, f, "merge", "b", merge_log=tmp_path / "log", gh=_FakeGh())
    return json.loads(f.read_text(encoding="utf-8"))


def test_run_and_record_refuses_the_real_gh_under_pytest(tmp_path):
    import pytest
    with pytest.raises(detach.RealGhInTestError):
        detach.run_and_record([sys.executable, "-c", "print('ok')", "--issue", "3"], tmp_path / "r.json",
                              "merge", "b", merge_log=tmp_path / "log")
    assert not (tmp_path / "r.json").exists()
