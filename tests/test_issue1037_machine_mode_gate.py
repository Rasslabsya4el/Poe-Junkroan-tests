"""The machine-mode gate has one definition, `machine_mode.read_gate`; the four readers call it (fakes only)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools.agentops import machine_mode  # noqa: E402
from tools.agentops.machine_mode import MachineModeUnreadable, ModeRead, read_gate  # noqa: E402

# the old inline decision of each reader, per file
OLD_FORMS = {
    "tools/agentops/dispatch.py": [r"machine_mode\.current_mode\(\)"],
    "tools/agentops/merge.py": [r"current_mode\(\)\s*==", r"except MachineModeUnreadable"],
    "tools/agentops/hold.py": [r"mode = read\(\)"],
    "src/junkroan/runs/daemon.py": [r"machine_mode\.current_mode\(\)", r"self\._machine_mode_reader\(\)"],
}


@pytest.mark.parametrize("rel", sorted(OLD_FORMS))
def test_old_inline_form_is_gone(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for pattern in OLD_FORMS[rel]:
        assert len(re.findall(pattern, text)) == 0, (rel, pattern)
    assert "read_gate" in text


def _raising(exc):
    def reader():
        raise exc
    return reader


def test_dispatch_form_any_exception_is_unreadable_with_error():
    """dispatch: default reader, every exception caught, the error kept for the log."""
    boom = RuntimeError("x")
    got = read_gate(_raising(boom))
    assert got == ModeRead(None, boom) and got.mode is None and got.error is boom
    assert read_gate(lambda: "play").mode == "play"
    assert read_gate(lambda: "normal").mode == "normal"


def test_merge_form_play_and_unreadable_hold_other_errors_propagate():
    """merge: holds in play and on MachineModeUnreadable; any other exception is not swallowed."""
    assert read_gate(lambda: "play", MachineModeUnreadable).holds is True
    assert read_gate(lambda: "normal", MachineModeUnreadable).holds is False
    assert read_gate(_raising(MachineModeUnreadable("bad")), MachineModeUnreadable).holds is True
    with pytest.raises(ValueError):
        read_gate(_raising(ValueError("other")), MachineModeUnreadable)


def test_hold_form_injected_reader_is_used_and_error_returned():
    """hold: the keeper's injected reader; a raise gives no mode (no pass) and the error for one log line."""
    seen = []
    got = read_gate(lambda: seen.append(1) or "normal")
    assert got.mode == "normal" and seen == [1]
    err = OSError("gone")
    assert read_gate(_raising(err)).error is err


def test_daemon_form_none_reader_falls_back_to_current_mode(tmp_path, monkeypatch):
    """daemon: reader None reads the mode file; unreadable holds; `play` holds, `normal` does not."""
    monkeypatch.setenv("AGENTOPS_MACHINE_DIR", str(tmp_path))
    assert read_gate(None).mode == "normal"  # absent file
    machine_mode.set_mode("play")
    got = read_gate(None)
    assert got.mode == "play" and got.holds is True
    (tmp_path / machine_mode.MODE_FILE).write_text("{not json", encoding="utf-8")
    got = read_gate(None)
    assert got.mode is None and isinstance(got.error, MachineModeUnreadable) and got.holds is True
