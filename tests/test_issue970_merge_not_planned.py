"""#970: a merge whose ticket was closed as "not planned" is dropped at the lock; nothing is pushed.

The issue's state is read through ``merge.read_issue_state`` (stubbed here; the real one never runs
under pytest). The read happens AFTER the merge lock is taken, so a ticket closed while the merge
waited in the line is dropped too (row 6). A real local bare repo stands in for GitHub."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.test_agentops_merge import (
    NO_LOAD_REACHES,
    _ThreadCapture,
    _clone,
    _git,
    _origin_main_head,
    _push_branch,
    _world,
    suite_cmd,
)
from tests.test_agentops_merge_batch import _Queue, _counter
from tools.agentops import merge as merge_module
from tools.agentops.merge import MergeLock, add_subparser, run_merge, run_merge_command

DROP_LINE = "issue #969 closed as not planned: merge dropped"


@pytest.fixture(autouse=True)
def _protect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_suite_out")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_merge.log")
    monkeypatch.setattr(merge_module, "resolve_suite_env", lambda: {})
    # the conftest sets AGENTOPS_MERGE_LOG for the whole session, and that env value wins over the constant
    monkeypatch.setenv(merge_module.ENV_MERGE_LOG, str(tmp_path / "_merge.log"))


def _stub_state(monkeypatch: pytest.MonkeyPatch, answer) -> None:
    """``answer`` is a ``(state, stateReason)`` pair, or an exception to raise. ``raising=False``:
    on the unchanged code the name does not exist yet, so the test fails, it does not error."""
    def read(number: int) -> tuple[str, str]:
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(merge_module, "read_issue_state", read, raising=False)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    add_subparser(sub)
    return ap


def _suite(tmp_path: Path) -> str:
    return f'"{sys.executable}" -c "pass"'


def _merge_log(tmp_path: Path) -> str:
    path = tmp_path / "_merge.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_row2_closed_not_planned_pushes_nothing_and_names_the_drop(tmp_path: Path, monkeypatch, capsys):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    _stub_state(monkeypatch, ("CLOSED", "NOT_PLANNED"))
    lock_path = tmp_path / "merge.lock"
    main_before = _origin_main_head(bare)
    branch_before = _git("rev-parse", "feature-a", cwd=bare).stdout.strip()
    local_before = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

    args = _parser().parse_args(["merge", "feature-a", "--suite", _suite(tmp_path), "--cwd", str(checkout),
                                 "--lock", str(lock_path), "--issue", "969"])
    rc = run_merge_command(args)
    out = capsys.readouterr().out

    assert rc != 0
    assert f"not merged (not-planned): {DROP_LINE}" in out
    assert _origin_main_head(bare) == main_before, "a dropped merge pushed to main"
    assert _git("rev-parse", "feature-a", cwd=bare).stdout.strip() == branch_before
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == local_before
    assert DROP_LINE in _merge_log(tmp_path)
    assert not Path(str(lock_path) + ".holding").exists(), "the lock was not released"


def test_row3_open_issue_merges_as_today(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    _stub_state(monkeypatch, ("OPEN", ""))

    result = run_merge("feature-a", _suite(tmp_path), cwd=checkout, lock_path=tmp_path / "merge.lock",
                       issues=(969,))

    assert result.ok, result.message
    assert result.pushed
    assert "a.py" in _git("ls-tree", "--name-only", "main", cwd=bare).stdout


def test_row4_closed_completed_merges_as_today(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    _stub_state(monkeypatch, ("CLOSED", "COMPLETED"))

    result = run_merge("feature-a", _suite(tmp_path), cwd=checkout, lock_path=tmp_path / "merge.lock",
                       issues=(969,))

    assert result.ok, result.message
    assert result.pushed
    assert "a.py" in _git("ls-tree", "--name-only", "main", cwd=bare).stdout


def test_row5_failed_state_read_merges_as_today_and_logs_it(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    _stub_state(monkeypatch, RuntimeError("gh: network unreachable"))

    result = run_merge("feature-a", _suite(tmp_path), cwd=checkout, lock_path=tmp_path / "merge.lock",
                       issues=(969,))

    assert result.ok, result.message
    assert result.pushed
    assert "a.py" in _git("ls-tree", "--name-only", "main", cwd=bare).stdout
    assert "issue state not read" in _merge_log(tmp_path)


def test_row6_closed_while_waiting_in_the_line_is_dropped_at_the_lock(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    answer = {"now": ("OPEN", "")}
    monkeypatch.setattr(merge_module, "read_issue_state", lambda n: answer["now"], raising=False)
    lock_path = tmp_path / "merge.lock"
    queue_dir = lock_path.with_name(lock_path.name + ".queue")
    main_before = _origin_main_head(bare)

    holder = MergeLock(lock_path)
    assert holder.acquire(None) is None  # this test holds the lock: the merge must wait behind it
    results: dict[str, object] = {}
    capture = _ThreadCapture(lambda: results.__setitem__("m", run_merge(
        "feature-a", _suite(tmp_path), cwd=checkout, lock_path=lock_path, lock_timeout=NO_LOAD_REACHES,
        issues=(969,))))
    thread = threading.Thread(target=capture)
    try:
        thread.start()
        deadline = time.monotonic() + 60.0  # bounded: the waiter's ticket must appear in the line
        while not (queue_dir.exists() and any(queue_dir.iterdir())):
            assert time.monotonic() < deadline, "the merge never queued behind the holder"
            assert thread.is_alive(), "the merge ended before the lock was released"
            time.sleep(0.05)
        answer["now"] = ("CLOSED", "NOT_PLANNED")  # the ticket is closed while the merge waits
    finally:
        holder.release()
    thread.join(timeout=NO_LOAD_REACHES)
    assert not thread.is_alive(), "the merge hung past its bound"
    capture.reraise()

    result = results["m"]
    assert not result.ok and result.reason == "not-planned", (result.reason, result.message)
    assert result.message == DROP_LINE
    assert not result.pushed
    assert _origin_main_head(bare) == main_before, "a merge dropped at the lock pushed to main"


def test_row8_a_batch_member_closed_not_planned_leaves_the_batch(tmp_path: Path, monkeypatch):
    """The holder (issue 968, open) batches the waiter (issue 969, closed as not planned): the waiter is
    dropped from the batch with its own result, the holder's branch goes alone (one suite run)."""
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "w0", "f1", "a.py", "f1 = 1\n")
    _push_branch(bare, tmp_path, "w1", "f2", "b.py", "f2 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    states = {968: ("OPEN", ""), 969: ("CLOSED", "NOT_PLANNED")}
    monkeypatch.setattr(merge_module, "read_issue_state", lambda n: states[n], raising=False)
    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    lock_path = tmp_path / "merge.lock"
    results: dict[str, object] = {}

    def job(branch: str, issue: int):
        results[branch] = run_merge(f"origin/{branch}", suite_cmd(counter, flag), cwd=checkout,
                                    lock_path=lock_path, lock_timeout=NO_LOAD_REACHES,
                                    suite_output_dir=tmp_path / "suite_out", issues=(issue,))

    queue = _Queue(lock_path)
    queue.add(lambda: job("f1", 968))  # first in line: the holder
    queue.add(lambda: job("f2", 969))  # waits in line, is claimed into the batch, then dropped
    queue.release_and_join()

    assert results["f1"].ok and results["f1"].pushed, results["f1"].message
    assert not results["f2"].ok and results["f2"].reason == "not-planned", results["f2"].message
    assert results["f2"].message == DROP_LINE
    assert _counter(counter) == 1, "the dropped member must not add a suite run"
    fresh = _clone(bare, tmp_path / "verify")
    assert (fresh / "a.py").exists() and not (fresh / "b.py").exists(), "the dropped member was pushed"
    assert f"not-planned | {DROP_LINE}" in _merge_log(tmp_path)
