"""#740: a core update's commit-and-push holds the merge lock, then the checkout lock of the same lock
path (the order a suite-needing `run_commit` uses), so it never writes into a checkout while a quick
commit does. Real git repos (a bare origin + a clone) under `tmp_path`; no PoB."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tests.test_agentops_merge import (
    _git, _origin_main_head, _protect_real_agentops_var, _green_default_commit_suite, _world,
)
from tools.agentops import core_update, merge as merge_mod
from tools.agentops.merge import CheckoutLock, MergeLock, _checkout_lock_path, run_commit

_ = (_protect_real_agentops_var, _green_default_commit_suite)  # autouse fixtures

WAIT = 1.0


def _lock_path(checkout: Path) -> Path:
    path = checkout / "var" / "locks" / "merge.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _head(repo: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _start_update(checkout: Path, errors: list) -> threading.Thread:
    (checkout / "core.txt").write_text("core\n", encoding="utf-8")

    def go() -> None:
        # the core's `_commit_and_push` never takes the lock itself (its caller does, #49): the update's
        # merge-then-checkout lock is `_target_lock`, the one `run_core_update` holds around the commit
        try:
            with core_update._target_lock(checkout, None):
                core_update._commit_and_push(checkout, {"core.txt"}, "abcdef1234567890", {"core.txt": None})
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            errors.append(exc)

    thread = threading.Thread(target=go)
    thread.start()
    return thread


def test_row1_core_update_makes_no_commit_while_the_checkout_lock_is_held(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = _lock_path(checkout)
    start = _head(checkout)
    holder = CheckoutLock(_checkout_lock_path(lock_path))
    holder.acquire(30)
    errors: list = []
    try:
        thread = _start_update(checkout, errors)
        time.sleep(WAIT)
        assert _head(checkout) == start, "the core update committed while the checkout lock was held"
    finally:
        holder.release()
    thread.join(60)
    assert not thread.is_alive() and not errors
    assert _head(checkout) != start
    assert _origin_main_head(bare) == _head(checkout)


def test_row2_quick_commit_waits_for_a_core_update_paused_between_commit_and_push(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    lock_path = _lock_path(checkout)
    at_push, go_on = threading.Event(), threading.Event()
    real = core_update._git

    def paused(root, *args, **kwargs):
        if args and args[0] == "push":
            at_push.set()
            assert go_on.wait(60)
        return real(root, *args, **kwargs)

    undone: list = []
    real_undo = core_update._undo_commit
    monkeypatch.setattr(core_update, "_git", paused)
    monkeypatch.setattr(core_update, "_undo_commit", lambda *a, **k: (undone.append(a), real_undo(*a, **k)))

    errors: list = []
    update = _start_update(checkout, errors)
    assert at_push.wait(60)

    (checkout / "docs").mkdir(exist_ok=True)
    (checkout / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    result: list = []
    quick = threading.Thread(target=lambda: result.append(
        run_commit(["docs/note.md"], "quick note", cwd=checkout, lock_path=lock_path, lock_timeout=60)))
    quick.start()
    quick.join(8)  # unlocked, run_commit finishes well inside this
    assert quick.is_alive(), "the quick commit did not wait for the core update's push"
    go_on.set()
    update.join(60)
    quick.join(60)
    assert not update.is_alive() and not quick.is_alive()
    assert not errors and not undone
    subjects = _git("log", "--format=%s", "main", cwd=bare).stdout.splitlines()
    assert "quick note" in subjects and any(s.startswith("Core update:") for s in subjects)


def test_row3_a_merge_lock_holder_alone_still_makes_the_core_update_wait(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = _lock_path(checkout)
    start = _head(checkout)
    holder = MergeLock(lock_path)
    holder.acquire(30)
    errors: list = []
    try:
        thread = _start_update(checkout, errors)
        time.sleep(WAIT)
        assert _head(checkout) == start
    finally:
        holder.release()
    thread.join(60)
    assert not errors and _head(checkout) != start


def test_row4_home_returns_the_home_message_and_takes_no_lock(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(core_update, "load_settings", lambda root: {"update_rule": core_update.HOME_RULE})

    def boom(*a, **k):
        raise AssertionError("a lock was taken at home")

    monkeypatch.setattr(core_update, "merge_then_checkout_locked", boom)
    monkeypatch.setattr(merge_mod.CheckoutLock, "acquire", boom)
    result = core_update.run_core_update(tmp_path)
    assert result.message == "this is the home: core update changes nothing"
