"""JUNKROAN_POB_CALL_LOG_ALL=1 logs every call, not only over half the limit (#724 unit 1b). Stub worker, no PoB."""

from __future__ import annotations

import json
from pathlib import Path

from test_pob_call_record import _adapter, _trial_call
from timing_bound import bound


def test_all_flag_logs_a_fast_call(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("JUNKROAN_POB_CALL_LOG", str(log))
    monkeypatch.setenv("JUNKROAN_POB_CALL_LOG_ALL", "1")
    adapter, handle, proc = _adapter(0.0)
    try:
        _trial_call(adapter, handle, 10.0)
    finally:
        proc.kill()
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["call"] == "trial_stats" and rec["limit"] == 10.0 and rec["elapsed"] < bound(floor=5.0, factor=30)


def test_without_the_flag_a_fast_call_is_not_logged(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("JUNKROAN_POB_CALL_LOG", str(log))
    monkeypatch.delenv("JUNKROAN_POB_CALL_LOG_ALL", raising=False)
    adapter, handle, proc = _adapter(0.0)
    try:
        _trial_call(adapter, handle, 10.0)
    finally:
        proc.kill()
    assert not log.exists()
