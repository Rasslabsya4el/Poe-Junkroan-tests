"""#939: a PoB worker that is slow to START is waited for like a computing one (#724's CPU rule on the ready wait).

Fake worker process (stub stdout, stub CPU / priority probes) through the real `launch_session`: no PoB starts, the
limit is shrunk by patching `_WORKER_READY_TIMEOUT_SECONDS`, nothing sleeps 30 s.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.pob import headless_runtime_adapter as hra
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from timing_bound import bound

LIMIT = 0.05  # real seconds of one ready-wait interval in these tests
READY = '{"status": "ready"}\n'
TIMEOUT_TEXT = "Timed out waiting for the headless PoB worker protocol."


class _Handle:
    """stdout of a stub worker: the ready line comes after `ready_after` seconds, or never (until the worker is ended)."""

    def __init__(self, ready_after: float | None) -> None:
        self.ready_after = ready_after
        self.released = threading.Event()

    def readline(self) -> str:
        if self.ready_after is None:
            self.released.wait(30)
            return ""
        if self.released.wait(self.ready_after):
            return ""
        return READY


class _Stdin:
    def write(self, _text: str) -> None:
        pass

    def flush(self) -> None:
        pass


class _Proc:
    pid = 4242

    def __init__(self, ready_after: float | None) -> None:
        self.stdin = _Stdin()
        self.stdout = _Handle(ready_after)
        self.stderr = None
        self.terminated = 0

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated += 1
        self.stdout.released.set()

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None) -> int:
        return 0


def _probes(monkeypatch, *, cpu) -> None:
    """cpu(): tree CPU seconds at this probe; the worker is never Idle-priority here."""
    monkeypatch.setattr(hra, "_tree_cpu_seconds", lambda process: cpu())
    monkeypatch.setattr(hra, "_is_idle_priority", lambda process: False)


def _launch(monkeypatch, tmp_path: Path, proc: _Proc):
    """A real `PinnedPoBHeadlessRuntimeAdapter.launch_session` whose path checks, Popen and hashes are stubs."""
    monkeypatch.setattr(hra, "_WORKER_READY_TIMEOUT_SECONDS", LIMIT)
    monkeypatch.setattr(hra, "guard_pob_launch", lambda: None)  # the worker is a fake: the merge suite sets JUNKROAN_NO_POB
    monkeypatch.setattr(hra.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(hra.PinnedPoBHeadlessRuntimeAdapter, "_resolve_runtime_root", lambda self, request: tmp_path)
    monkeypatch.setattr(hra.PinnedPoBHeadlessRuntimeAdapter, "_resolve_wrapper_path", lambda self, ref: tmp_path / "w.lua")
    monkeypatch.setattr(hra.PinnedPoBHeadlessRuntimeAdapter, "_validate_wrapper_path", lambda self, path: None)
    monkeypatch.setattr(hra, "validate_headless_worker_launch_paths", lambda **kwargs: {"offending_paths": []})
    monkeypatch.setattr(hra, "sha256_file", lambda path: "sha")
    adapter = hra.PinnedPoBHeadlessRuntimeAdapter.__new__(hra.PinnedPoBHeadlessRuntimeAdapter)
    adapter._release_manager = None
    adapter._python_executable = "python"
    adapter._workers = {}
    adapter._dropped_workers = {}
    adapter._flask_flags_changed = False
    request = SimpleNamespace(
        session_root=tmp_path, temp_root=tmp_path, export_locator=tmp_path / "export.json",
        session_role="build", reopen_source_locator=None, wrapper_entrypoint_ref="w.lua", process_instance_id="p",
    )
    return adapter, request


def test_1_ready_line_after_one_and_a_half_limits_while_cpu_advances_opens_the_session(monkeypatch, tmp_path) -> None:
    proc = _Proc(ready_after=1.5 * LIMIT)
    ticks = iter(range(1, 10_000))
    _probes(monkeypatch, cpu=lambda: next(ticks) * 0.1)
    adapter, request = _launch(monkeypatch, tmp_path, proc)
    result = adapter.launch_session(request)
    assert result.os_pid == 4242
    assert proc.terminated == 0 and "p" in adapter._workers


def test_2_no_ready_line_and_no_cpu_is_ended_at_the_first_limit_with_the_text_unchanged(monkeypatch, tmp_path) -> None:
    proc = _Proc(ready_after=None)
    _probes(monkeypatch, cpu=lambda: 1.0)
    adapter, request = _launch(monkeypatch, tmp_path, proc)
    started = time.monotonic()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        adapter.launch_session(request)
    waited = time.monotonic() - started
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert str(info.value) == TIMEOUT_TEXT
    assert waited < bound(5 * LIMIT, 10)  # the first limit, not the cap (10 limits = 0.5 s here)
    assert proc.terminated == 1 and "p" not in adapter._workers


def test_3_worker_computing_for_ever_is_raised_after_the_cap_and_the_process_has_exited(monkeypatch, tmp_path) -> None:
    proc = _Proc(ready_after=None)
    ticks = iter(range(1, 10_000))
    probes: list[float] = []

    def cpu() -> float:
        value = next(ticks) * 0.1
        probes.append(value)
        return value

    _probes(monkeypatch, cpu=cpu)
    adapter, request = _launch(monkeypatch, tmp_path, proc)
    started = time.monotonic()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        adapter.launch_session(request)
    waited = time.monotonic() - started
    assert info.value.failure_state == "runtime_protocol_timeout"
    assert str(info.value) == TIMEOUT_TEXT
    assert len(probes) == 1 + hra._CPU_WAIT_CAP_INTERVALS  # one start probe, then one per interval
    assert 9.5 * LIMIT <= waited < bound(60 * LIMIT, 100)
    assert proc.poll() is not None and proc.terminated == 1 and "p" not in adapter._workers
