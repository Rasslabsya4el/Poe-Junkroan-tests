"""#724 unit 2: the first error of a build is the one its row records.

A PoB call that times out ends its worker; the cleanup that follows (the trial's exit, the attempt's
restore) calls the dead handle. That second call must refuse with the TIMEOUT text first, not with a
bare "No live headless PoB worker" that hides what happened. Stub worker, no PoB.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.improvement_loop import Attempt, AttemptTools
from junkroan.optimizer.judging import _Trial
from junkroan.pob.host_runtime import PoBHeadlessHostContractError

from tests.test_issue724_cpu_wait import _adapter, _call, _probes


def _timed_out_adapter(monkeypatch):
    adapter, handle, _proc = _adapter()
    _probes(monkeypatch, cpu=lambda: 1.0, idle=lambda: False)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _call(adapter, handle)
    assert info.value.failure_state == "runtime_protocol_timeout"
    return adapter, handle, str(info.value)


def test_a_call_on_a_handle_ended_by_a_timeout_starts_with_that_timeout(monkeypatch) -> None:
    adapter, handle, timeout_text = _timed_out_adapter(monkeypatch)
    assert "Call trial_stats, trials 2, limit " in timeout_text and ", elapsed " in timeout_text
    with pytest.raises(PoBHeadlessHostContractError) as info:
        adapter.load_build_xml(handle, "<PathOfBuilding/>")
    message = str(info.value)
    assert info.value.failure_state == "unknown_session"
    assert message.startswith(timeout_text)
    assert "load_build_xml" in message and " p " in message
    assert not message.startswith("No live headless PoB worker")


def test_only_the_first_timeout_of_a_handle_is_remembered(monkeypatch) -> None:
    adapter, handle, timeout_text = _timed_out_adapter(monkeypatch)
    for _ in range(2):
        with pytest.raises(PoBHeadlessHostContractError) as info:
            adapter.read_state(handle)
        assert str(info.value).startswith(timeout_text)
    assert adapter._dropped_workers == {"p": timeout_text}


def test_a_handle_never_launched_keeps_the_plain_unknown_session_text() -> None:
    adapter, _handle, _proc = _adapter()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        adapter.read_state(SimpleNamespace(process_instance_id="nobody"))
    assert info.value.failure_state == "unknown_session"
    assert str(info.value) == "No live headless PoB worker exists for nobody."


class _PobOverAdapter:
    """What PobSession does for the restore: load_xml goes through the adapter's handle."""

    def __init__(self, adapter, handle) -> None:
        self.adapter, self.handle = adapter, handle

    def export_xml(self) -> str:
        return "<xml/>"

    def load_xml(self, xml: str) -> None:
        self.adapter.load_build_xml(self.handle, xml)


def test_a_trial_that_times_out_leaves_the_timeout_as_the_error_that_escapes(monkeypatch) -> None:
    adapter, handle, timeout_text = _timed_out_adapter(monkeypatch)
    pob = _PobOverAdapter(adapter, handle)
    lanes = SimpleNamespace(snapshot=pob.export_xml, restore=pob.load_xml)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        with _Trial(lanes):
            raise PoBHeadlessHostContractError("runtime_protocol_timeout", timeout_text)
    assert str(info.value).startswith(timeout_text)


def test_a_dropped_kick_draw_is_recorded_with_the_timeout_not_the_dead_worker(monkeypatch) -> None:
    adapter, handle, timeout_text = _timed_out_adapter(monkeypatch)
    pob = _PobOverAdapter(adapter, handle)
    tools = AttemptTools(
        st=SimpleNamespace(cur=1.0), snapshot=lambda: {}, restore=lambda _state, keep_rejections=False: pob.load_xml("<xml/>"),
        rejudge=lambda: None, restore_mark=lambda *_a: None, score=lambda: 1.0, record=lambda *a, **k: None,
        note_drop=lambda _row: None, log=lambda _m: None, min_gain=0.0,
    )
    with pytest.raises(PoBHeadlessHostContractError) as info:
        with Attempt(tools, "kick joint", ledger_name=None, started=0.0, before=None, armed=True):
            raise PoBHeadlessHostContractError("runtime_protocol_timeout", timeout_text)
    # the recovery failure escapes the attempt; its message is what the build's row ends up holding
    assert str(info.value).startswith(timeout_text)
    assert info.value.failure_state == "unknown_session"
