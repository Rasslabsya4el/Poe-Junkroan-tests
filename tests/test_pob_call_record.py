"""Timeout error names its call; slow calls leave a line in JUNKROAN_POB_CALL_LOG (#724 unit 1a). Stub worker, no PoB."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.pob import headless_runtime_adapter as hra
from junkroan.pob.host_runtime import PoBHeadlessHostContractError

_STUB = (
    "import sys,time,json\n"
    "line=sys.stdin.readline()\n"
    "time.sleep(float(sys.argv[1]))\n"
    "print(json.dumps({'ok':True,'result':{'results':[]}}),flush=True)\n"
    "time.sleep(30)\n"
)


def _wait_until_warm(proc, quiet: float = 0.3) -> None:
    """Interpreter start-up burns CPU; the real workers are warm, so wait until the stub's CPU is flat (#724)."""
    import time

    import psutil

    ps = psutil.Process(proc.pid)
    last, since = ps.cpu_times(), time.monotonic()
    while time.monotonic() - since < quiet:
        time.sleep(0.05)
        now = ps.cpu_times()
        if now != last:
            last, since = now, time.monotonic()


def _adapter(sleep: float):
    adapter = hra.PinnedPoBHeadlessRuntimeAdapter.__new__(hra.PinnedPoBHeadlessRuntimeAdapter)
    adapter._flask_flags_changed = False
    proc = subprocess.Popen(
        [sys.executable, "-c", _STUB, str(sleep)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _wait_until_warm(proc)
    adapter._dropped_workers = {}
    adapter._workers = {"p": hra._WorkerProcess(process=proc, request=None)}
    return adapter, SimpleNamespace(process_instance_id="p"), proc


def _trial_call(adapter, handle, limit):
    return adapter._call_worker(handle, {"action": "trial_stats", "trial_payload": {"trials": [1, 2, 3]}}, timeout_seconds=limit)


def test_timeout_message_names_call_trials_limit_elapsed(monkeypatch) -> None:
    monkeypatch.delenv("JUNKROAN_POB_CALL_LOG", raising=False)
    adapter, handle, proc = _adapter(10)
    try:
        with pytest.raises(PoBHeadlessHostContractError) as info:
            _trial_call(adapter, handle, 0.5)
    finally:
        proc.kill()
    assert info.value.failure_state == "runtime_protocol_timeout"
    msg = str(info.value)
    assert msg.startswith("Timed out waiting for the headless PoB worker protocol.")
    assert "trial_stats" in msg and "trials 3" in msg and "limit 0.5 s" in msg and "elapsed 0." in msg


def test_slow_call_writes_one_line(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("JUNKROAN_POB_CALL_LOG", str(log))
    adapter, handle, proc = _adapter(0.6)
    try:
        _trial_call(adapter, handle, 1.0)
    finally:
        proc.kill()
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert set(rec) == {"ts", "call", "trials", "limit", "elapsed", "pid"}
    assert rec["call"] == "trial_stats" and rec["trials"] == 3 and rec["limit"] == 1.0 and rec["pid"] == proc.pid
    assert 0.5 < rec["elapsed"] < 1.0


def test_fast_call_or_unset_env_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("JUNKROAN_POB_CALL_LOG", str(log))
    adapter, handle, proc = _adapter(0.0)
    try:
        _trial_call(adapter, handle, 10.0)
    finally:
        proc.kill()
    assert not log.exists()
    monkeypatch.delenv("JUNKROAN_POB_CALL_LOG")
    adapter, handle, proc = _adapter(0.6)
    try:
        _trial_call(adapter, handle, 1.0)
    finally:
        proc.kill()
    assert not log.exists()
