"""#759: the default launcher's real Claude program is refused under pytest unless the test is marked."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from junkroan.runs import anomalies as an


def _guard(tmp_path: Path) -> an.AnomalyGuard:
    return an.AnomalyGuard(path=tmp_path / "anomalies.json", clock=lambda: 0.0, log=lambda m: None)


def test_default_launcher_is_refused_with_the_test_name(tmp_path: Path, _no_real_claude_program) -> None:
    with pytest.raises(RuntimeError, match="test_default_launcher_is_refused_with_the_test_name"):
        an.ClaudeKeymasterCli()
    with pytest.raises(RuntimeError, match="test_default_launcher_is_refused_with_the_test_name"):
        _ = _guard(tmp_path).launcher
    assert len(_no_real_claude_program) == 2
    _no_real_claude_program.clear()                         # recorded and checked: let the teardown pass


def test_check_with_defaults_records_the_test_name(tmp_path: Path, _no_real_claude_program) -> None:
    """`check()` swallows the refusal in its list thread; the record is what fails the test at teardown."""

    _guard(tmp_path).check()
    assert _no_real_claude_program
    assert "test_check_with_defaults_records_the_test_name" in _no_real_claude_program[0]
    _no_real_claude_program.clear()


@pytest.mark.real_claude
def test_marked_test_reaches_the_launcher_with_a_fake_binary(tmp_path: Path, monkeypatch, _no_real_claude_program) -> None:
    marker = tmp_path / "called.txt"
    if sys.platform == "win32":
        exe = tmp_path / "fake_claude.cmd"
        exe.write_text(f'@echo off\r\necho %* > "{marker}"\r\necho []\r\n', encoding="utf-8")
    else:
        exe = tmp_path / "fake_claude"
        exe.write_text(f'#!/bin/sh\necho "$@" > "{marker}"\necho "[]"\n', encoding="utf-8")
        exe.chmod(0o755)
    monkeypatch.setattr(an, "_find_claude_exe", lambda: exe)
    guard = _guard(tmp_path)
    assert guard.launcher.list_sessions() == []
    assert "agents" in marker.read_text(encoding="utf-8")
    assert _no_real_claude_program == []
