"""#665 rules 2-4: a red batch is triaged with only the failed tests; at most 2 full suites."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests.test_agentops_merge import NO_LOAD_REACHES, _git, _push_branch, _world
from tests.test_agentops_merge_batch import _Queue, _log_lines, _merge_jobs
from tools.agentops import merge as merge_module

STUB = """\
import pathlib, sys
counter = pathlib.Path(sys.argv[1]); mode = sys.argv[2]; ids = sys.argv[3:]
calls = counter.read_text().splitlines() if counter.exists() else []
calls.append(" ".join(ids) or "FULL")
counter.write_text(chr(10).join(calls))
fulls = calls.count("FULL")
failing = []
if mode == "base" or list(pathlib.Path(".").glob("marker-*")):
    failing.append("tests/t.py::m")
if mode == "second" and fulls >= 2:
    failing.append("tests/t.py::o")
shown = [i for i in failing if not ids or i in ids]
for i in shown:
    print("FAILED " + i + " - boom")
print(str(len(shown)) + " failed in 0.1s" if shown else "all passed")
sys.exit(1 if shown else 0)
"""


@pytest.fixture(autouse=True)
def _protect(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_auto_out")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_auto.log")
    monkeypatch.setattr(merge_module, "_PYTEST_RE", re.compile(r"-m pytest"))


def _run(tmp_path: Path, mode: str, files: list[tuple[str, str]]):
    bare, checkout = _world(tmp_path)
    for i, (b, f) in enumerate(files):
        _push_branch(bare, tmp_path, f"w{i}", b, f, f"{b}\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    counter, log, lock_path = tmp_path / "calls.txt", tmp_path / "merge.log", tmp_path / "merge.lock"
    suite = f'"{sys.executable}" "{stub}" "{counter}" {mode}'
    results: dict = {}
    q = _Queue(lock_path)
    for job in _merge_jobs(tmp_path, checkout, lock_path, [b for b, _f in files], suite, results, log):
        q.add(job)
    q.release_and_join()
    calls = counter.read_text().splitlines() if counter.exists() else []
    return results, calls, _log_lines(log), bare


def _phase(calls: list[str], fulls: int) -> list[str]:
    """The calls up to (not including) the full suite number ``fulls`` + 1: the first holder's own work."""
    seen = 0
    for n, c in enumerate(calls):
        if c == "FULL":
            seen += 1
            if seen == fulls + 1:
                return calls[:n]
    return calls


PLAIN = [("b1", "a.py"), ("b2", "b.py"), ("b3", "c.py")]


def test_row2_culprit_member_is_ejected_the_rest_land_in_two_full_suites(tmp_path):
    results, calls, log, _bare = _run(tmp_path, "m", [("b1", "a.py"), ("b2", "marker-b2"), ("b3", "c.py")])
    assert calls.count("FULL") == 2, calls
    assert results["b2"].reason == "red-suite" and results["b2"].message == "red-suite: tests/t.py::m"
    assert results["b1"].ok and results["b3"].ok and results["b1"].head_after == results["b3"].head_after
    assert not any("red-suite" in r.message for k, r in results.items() if k != "b2")
    assert any("origin/b2" in l and "ejected: red-suite tests/t.py::m" in l for l in log), log
    assert any("batch of 3" in l and "red-suite" in l and "failed | output" in l for l in log), log


def test_row3_red_on_base_ejects_nobody_and_runs_one_full_suite(tmp_path):
    results, calls, log, _bare = _run(tmp_path, "base", PLAIN)
    assert _phase(calls, 1) == ["FULL", "tests/t.py::m", "tests/t.py::m"], calls
    assert results["b1"].reason == "red-on-base"
    assert any("red-on-base: tests/t.py::m" in l for l in log), log
    assert not any("ejected" in l for l in log)
    assert not any(r.batched and r.reason == "red-suite" for r in results.values())


def test_row4_holder_culprit_exits_red_and_oldest_member_holds_next(tmp_path):
    results, calls, log, _bare = _run(tmp_path, "m", [("b1", "marker-b1"), ("b2", "b.py"), ("b3", "c.py")])
    assert results["b1"].reason == "red-suite" and results["b1"].failed_tests == ["tests/t.py::m"]
    assert _phase(calls, 1)[:3] == ["FULL", "tests/t.py::m", "tests/t.py::m"], calls
    assert len(_phase(calls, 1)) == 6, calls  # FULL, re-check, base, b1, b2, b3: one full suite only
    assert calls.count("FULL") == 2  # the red one, then b2 + b3 as the next batch
    assert results["b2"].ok and not results["b2"].batched
    assert results["b3"].ok and results["b3"].batched
    assert sum("re-queued after red batch" in l for l in log) == 2, log


def test_row5_second_red_after_triage_is_final_with_two_full_suites(tmp_path):
    results, calls, log, _bare = _run(tmp_path, "second", [("b1", "a.py"), ("b2", "marker-b2"), ("b3", "c.py")])
    assert results["b1"].reason == "red-suite" and results["b1"].failed_tests == ["tests/t.py::o"]
    assert results["b2"].reason == "red-suite" and results["b2"].message == "red-suite: tests/t.py::m"
    assert results["b1"].suite_runs == 2 and calls[:1] == ["FULL"], calls
    full_idx = [n for n, c in enumerate(calls) if c == "FULL"]
    assert calls[full_idx[1] + 1] == "tests/t.py::o"  # the retry's own re-check, then nothing more for b1
    assert sum("re-queued after red batch" in l for l in log) >= 1, log
