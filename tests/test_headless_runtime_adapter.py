from __future__ import annotations

import sys
from pathlib import Path

import pytest

from junkroan.pob.headless_runtime_adapter import validate_headless_worker_launch_paths
from junkroan.pob.host_runtime import PoBHeadlessHostContractError


def test_headless_worker_launch_path_validation_reports_exact_invalid_cwd(tmp_path: Path) -> None:
    missing_cwd = tmp_path / "missing-cwd"
    temp_root = tmp_path / "temp"
    output_dir = tmp_path / "output"
    temp_root.mkdir()
    output_dir.mkdir()

    with pytest.raises(PoBHeadlessHostContractError) as exc_info:
        validate_headless_worker_launch_paths(
            python_executable=sys.executable,
            cwd=missing_cwd,
            session_root=missing_cwd,
            temp_root=temp_root,
            output_dir=output_dir,
        )

    message = str(exc_info.value)
    assert exc_info.value.failure_state == "runtime_launch_path_invalid"
    assert str(missing_cwd) in message
    assert "worker_executable" in message
    assert "worker_script" in message
    assert "cwd" in message
    assert "session_root" in message
    assert "temp_root" in message
    assert "output_dir" in message
    assert "expected_existing_directory" in message


def test_headless_worker_launch_path_validation_reports_windows_cwd_length(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    temp_root = session_root / "temp"
    output_dir = tmp_path / "output"
    temp_root.mkdir(parents=True)
    output_dir.mkdir()

    with pytest.raises(PoBHeadlessHostContractError) as exc_info:
        validate_headless_worker_launch_paths(
            python_executable=sys.executable,
            cwd=session_root,
            session_root=session_root,
            temp_root=temp_root,
            output_dir=output_dir,
            windows_cwd_limit=1,
        )

    message = str(exc_info.value)
    assert exc_info.value.failure_state == "runtime_launch_path_invalid"
    assert str(session_root) in message
    assert "windows_createprocess_cwd_path_too_long" in message
    assert '"limit": 1' in message
