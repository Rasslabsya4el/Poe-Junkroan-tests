"""#575 review fix: the cached `read_state` is dropped exactly when a derivation changed a Flask flag.

A stats read, a fast trial, an active-skill read and the export derive the flags from PoB's uptime and may write
`slot.active` into the live build, while the session treats them as reads. The worker's reply carries
`flask_flags_changed` (the five flags compared around the call); the adapter keeps it until the session's
`_StateCacheAdapter` takes it after the call. A changed flag drops the cache (no `build_epoch` bump); an unchanged
one keeps it, so a stats read in a hot loop costs no extra `read_state`.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from junkroan.pob import headless_runtime_worker as worker
from junkroan.pob.headless_runtime_adapter import PinnedPoBHeadlessRuntimeAdapter
from junkroan.pob.session import PobSession, _StateCacheAdapter


class _Inner:
    """A fake adapter: its derivation flips Flask 2 when `flip_next` is set, and says so as the real one does."""

    def __init__(self) -> None:
        self.reads = 0
        self.flags = {"Flask 2": True}
        self.flip_next = False
        self._changed = False

    def _derive(self) -> None:
        if self.flip_next:
            self.flags = {"Flask 2": not self.flags["Flask 2"]}
            self.flip_next, self._changed = False, True

    def take_flask_flags_changed(self) -> bool:
        changed, self._changed = self._changed, False
        return changed

    def read_state(self, _handle):
        self.reads += 1
        return {"items_state": {"flasks_active": dict(self.flags)}}

    def read_stats(self, _handle, _keys=None, _parts=None):
        self._derive()
        return {"Life": 1.0}

    def read_stats_uncapped(self, _handle, _keys=None, _parts=None):
        self._derive()
        return {"changed": False}

    def read_active_skill_stats(self, _handle, _ids, _keys):
        self._derive()
        return {}

    def export_build_artifact(self, _handle):
        self._derive()
        return "<PathOfBuilding/>"

    def trial_stats(self, _handle, request):
        self._derive()
        return {"results": []}


def _session(inner: Any) -> PobSession:
    s = PobSession.__new__(PobSession)
    s._state_cache = None
    s._handle = object()
    s._adapter = _StateCacheAdapter(inner, s._drop_state_cache)
    return s


def _call(s: PobSession, call: str) -> None:
    adapter = s._adapter
    if call == "trial_stats":
        adapter.trial_stats(s._handle, {"mode": "fast", "trials": []})
    elif call == "read_stats":
        adapter.read_stats(s._handle, None, None)
    elif call == "read_stats_uncapped":
        adapter.read_stats_uncapped(s._handle, None, None)
    elif call == "read_active_skill_stats":
        adapter.read_active_skill_stats(s._handle, [], [])
    else:
        adapter.export_build_artifact(s._handle)


DERIVING = ["read_stats", "read_stats_uncapped", "read_active_skill_stats", "export_build_artifact", "trial_stats"]


@pytest.mark.parametrize("call", DERIVING)
def test_a_derivation_that_changed_a_flag_drops_the_cached_state(call: str) -> None:
    inner = _Inner(); s = _session(inner)
    assert s.read_state()["items_state"]["flasks_active"] == {"Flask 2": True}
    inner.flip_next = True
    _call(s, call)
    assert s.read_state()["items_state"]["flasks_active"] == {"Flask 2": False}, "no stale flags after the flip"
    assert inner.reads == 2


@pytest.mark.parametrize("call", DERIVING)
def test_a_derivation_that_changed_nothing_keeps_the_cached_state(call: str) -> None:
    inner = _Inner(); s = _session(inner)
    s.read_state()
    _call(s, call)
    _call(s, call)
    s.read_state()
    assert inner.reads == 1, "a stats read in a hot loop costs no extra read_state"


def test_the_flip_mark_is_taken_once_and_the_build_epoch_stays() -> None:
    inner = _Inner(); s = _session(inner)
    s.build_epoch = 7
    s.read_state()
    inner.flip_next = True
    s._adapter.read_stats(s._handle, None, None)
    assert s.build_epoch == 7, "a derived flag is no new build"
    s.read_state(); s._adapter.read_stats(s._handle, None, None); s.read_state()
    assert inner.reads == 2, "the mark was cleared by the call that took it"


def test_an_adapter_without_the_mark_never_drops_on_a_read() -> None:
    class Plain(_Inner):
        take_flask_flags_changed = None  # type: ignore[assignment]

    inner = Plain(); s = _session(inner)
    s.read_state(); s._adapter.read_stats(s._handle, None, None); s.read_state()
    assert inner.reads == 1


def test_flasks_active_reads_the_cache_and_sees_a_flip() -> None:
    inner = _Inner(); s = _session(inner)
    assert s.flasks_active() == {"Flask 2": True}
    inner.flip_next = True
    s._adapter.read_stats(s._handle, None, None)
    assert s.flasks_active() == {"Flask 2": False}
    s.flasks_active()
    assert inner.reads == 2, "no by-hand drop: the unchanged second read is the cached one"


def test_the_workers_reply_carries_the_flag_change_around_a_deriving_action(monkeypatch: pytest.MonkeyPatch) -> None:
    out = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", out)
    monkeypatch.setattr(worker, "_flask_flags_tracker", (lambda: "11101", "11111"))
    worker._success(result={})
    assert json.loads(out.getvalue())["flask_flags_changed"] is True
    monkeypatch.setattr(worker, "_flask_flags_tracker", (lambda: "11111", "11111"))
    out.seek(0); out.truncate()
    worker._success(result={})
    assert json.loads(out.getvalue())["flask_flags_changed"] is False
    monkeypatch.setattr(worker, "_flask_flags_tracker", None)
    out.seek(0); out.truncate()
    worker._success(result={})
    assert "flask_flags_changed" not in json.loads(out.getvalue())
    assert {"read_stats", "read_stats_uncapped", "read_active_skill_stats", "trial_stats", "export_build_xml"} == worker._FLASK_DERIVING_ACTIONS


def test_the_adapter_keeps_the_workers_mark_until_taken_failures_included() -> None:
    adapter = PinnedPoBHeadlessRuntimeAdapter.__new__(PinnedPoBHeadlessRuntimeAdapter)
    adapter._flask_flags_changed = False
    assert adapter.take_flask_flags_changed() is False
    adapter._flask_flags_changed = True
    assert adapter.take_flask_flags_changed() is True
    assert adapter.take_flask_flags_changed() is False
