"""#724 unit 1: a slow PoB answer from a worker that is computing (or starved beside a suite) is waited for.

Stub worker process, stub CPU / priority probes: no PoB, no real minutes.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from junkroan.pob import headless_runtime_adapter as hra
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from timing_bound import bound

LIMIT = 0.05  # real seconds of one wait interval in these tests


class _Handle:
    """stdout of a stub worker: readline blocks until the reply is released."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def readline(self) -> str:
        self.release.wait(30)
        return '{"ok": true, "result": {"answer": 7}}\n'


class _Stdin:
    def write(self, _text: str) -> None:
        pass

    def flush(self) -> None:
        pass


class _Proc:
    pid = 4242

    def __init__(self) -> None:
        self.stdin = _Stdin()
        self.stdout = _Handle()
        self.terminated = 0

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated += 1
        self.stdout.release.set()

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.terminate()


def _adapter():
    adapter = hra.PinnedPoBHeadlessRuntimeAdapter.__new__(hra.PinnedPoBHeadlessRuntimeAdapter)
    adapter._flask_flags_changed = False
    proc = _Proc()
    adapter._dropped_workers = {}
    adapter._workers = {"p": hra._WorkerProcess(process=proc, request=None)}
    return adapter, SimpleNamespace(process_instance_id="p"), proc


def _call(adapter, handle):
    return adapter._call_worker(handle, {"action": "trial_stats", "trial_payload": {"trials": [1, 2]}}, timeout_seconds=LIMIT)


def _probes(monkeypatch, *, cpu, idle) -> None:
    """cpu(): tree CPU seconds at this probe; idle(): is the worker's priority class Idle."""
    monkeypatch.setattr(hra, "_tree_cpu_seconds", lambda process: cpu())
    monkeypatch.setattr(hra, "_is_idle_priority", lambda process: idle())


def _reply_after(proc, delay: float) -> threading.Thread:
    timer = threading.Timer(delay, proc.stdout.release.set)
    timer.start()
    return timer


def test_a_reply_after_two_limits_while_cpu_advances_is_returned(monkeypatch) -> None:
    adapter, handle, proc = _adapter()
    ticks = iter(range(1, 1000))
    _probes(monkeypatch, cpu=lambda: next(ticks) * 0.1, idle=lambda: False)
    timer = _reply_after(proc, 2.5 * LIMIT)
    response = _call(adapter, handle)
    timer.cancel()
    assert response["result"] == {"answer": 7}
    assert proc.terminated == 0 and "p" in adapter._workers


def test_b_sleeping_worker_is_ended_at_the_limit(monkeypatch) -> None:
    adapter, handle, proc = _adapter()
    _probes(monkeypatch, cpu=lambda: 1.0, idle=lambda: False)
    started = time.monotonic()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _call(adapter, handle)
    assert time.monotonic() - started < bound(5 * LIMIT, 10)
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert proc.terminated == 1 and "p" not in adapter._workers


def test_c_worker_computing_forever_is_raised_at_ten_limits(monkeypatch) -> None:
    adapter, handle, proc = _adapter()
    ticks = iter(range(1, 1000))
    _probes(monkeypatch, cpu=lambda: next(ticks) * 0.1, idle=lambda: False)
    started = time.monotonic()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _call(adapter, handle)
    waited = time.monotonic() - started
    assert 9.5 * LIMIT <= waited < bound(60 * LIMIT, 100)  # #844: 1.563 s was seen against the old 1.5 s floor
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert "Call trial_stats, trials 2" in str(info.value)
    assert proc.terminated == 1 and "p" not in adapter._workers


def test_d_idle_priority_worker_with_no_cpu_for_fifteen_minutes_then_answers(monkeypatch) -> None:
    adapter, handle, proc = _adapter()
    clock = SimpleNamespace(now=1000.0)
    intervals = []

    def idle() -> bool:
        intervals.append(clock.now)
        clock.now += 60.0  # one probe = one simulated minute starved
        if clock.now - 1000.0 >= 15 * 60:
            proc.stdout.release.set()
        return True

    _probes(monkeypatch, cpu=lambda: 1.0, idle=idle)
    response = _call(adapter, handle)
    assert response["result"] == {"answer": 7}
    assert proc.terminated == 0 and "p" in adapter._workers
    assert len(intervals) >= 15  # far past 10 x the limit of simulated wall time, and not ended


def test_e_no_cpu_at_normal_priority_past_the_limit_is_ended_naming_the_call(monkeypatch) -> None:
    adapter, handle, proc = _adapter()
    _probes(monkeypatch, cpu=lambda: 2.0, idle=lambda: False)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _call(adapter, handle)
    message = str(info.value)
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert message.startswith("Timed out waiting for the headless PoB worker protocol.")
    assert "Call trial_stats, trials 2, limit " in message and ", elapsed " in message
    assert proc.terminated == 1 and "p" not in adapter._workers


def test_unreadable_probes_fall_back_to_ending_at_the_limit(monkeypatch) -> None:
    adapter, handle, proc = _adapter()

    def gone():
        raise RuntimeError("process gone")

    _probes(monkeypatch, cpu=gone, idle=gone)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _call(adapter, handle)
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert proc.terminated == 1 and "p" not in adapter._workers
