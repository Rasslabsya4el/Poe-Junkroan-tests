"""#665 rule 1: a red suite re-runs only its failed tests once; all pass -> green."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests.test_agentops_merge import _git, _push_branch, _world
from tools.agentops import merge as merge_module
from tools.agentops.merge import run_merge

STUB = """\
import pathlib, sys
counter = pathlib.Path(sys.argv[1]); mode = sys.argv[2]; ids = sys.argv[3:]
calls = counter.read_text().splitlines() if counter.exists() else []
calls.append(" ".join(ids) or "FULL")
counter.write_text(chr(10).join(calls))
if mode == "silent":
    print("boom"); sys.exit(1)
if mode == "flaky" and len(calls) > 1:
    print("1 passed"); sys.exit(0)
print("FAILED tests/t.py::flaky - boom")
print("1 failed, 2 passed in 0.1s")
sys.exit(1)
"""


@pytest.fixture(autouse=True)
def _protect(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_auto_out")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_auto.log")
    # tmp_path itself contains "pytest-of-<user>": only `-m pytest` marks a pytest command here
    monkeypatch.setattr(merge_module, "_PYTEST_RE", re.compile(r"-m pytest"))


def _run(tmp_path: Path, mode: str):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "w", "feature-r", "r.py", "r = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    counter = tmp_path / "calls.txt"
    log = tmp_path / "merge.log"
    result = run_merge("origin/feature-r", f'"{sys.executable}" "{stub}" "{counter}" {mode}',
                       cwd=checkout, lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=tmp_path / "out", merge_log_path=log)
    return result, counter.read_text().splitlines(), log.read_text(encoding="utf-8")


def test_flaky_test_passes_the_recheck_and_the_merge_lands(tmp_path):
    result, calls, log = _run(tmp_path, "flaky")
    assert result.ok and result.reason == "pushed", result.message
    assert calls == ["FULL", "tests/t.py::flaky"]
    assert "0 failed after re-check of 1: tests/t.py::flaky" in log


def test_test_failing_every_time_stays_red_with_both_outputs(tmp_path):
    result, calls, log = _run(tmp_path, "always")
    assert not result.ok and result.reason == "red-suite"
    assert result.failed_tests == ["tests/t.py::flaky"]
    assert calls == ["FULL", "tests/t.py::flaky"]
    assert Path(result.suite_output_path).read_text(encoding="utf-8").count("FAILED tests/t.py::flaky") == 2


def test_red_suite_without_failed_lines_makes_no_recheck(tmp_path):
    result, calls, log = _run(tmp_path, "silent")
    assert not result.ok and result.reason == "red-suite"
    assert calls == ["FULL"]
