"""#446: the remote submit line starts its command with the call operator. No PoB."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402

REPO = "C:\\repo"


def _line() -> str:
    return runs._remote_submit_script(REPO, "laptop", ["--slots", "1"], ["python", "-c", "print(1)"])


def _parse_errors(line: str) -> int:
    ps = (
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseInput($env:LINE_UNDER_TEST, [ref]$null, [ref]$errors); "
        "Write-Output $errors.Count"
    )
    env = {**os.environ, "LINE_UNDER_TEST": line}
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True, text=True, timeout=60)
    return int(out.stdout.strip())


def test_line_starts_with_call_operator() -> None:
    assert f"cd '{REPO}'; & 'python' 'scripts\\runs.py' 'submit'" in _line()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="no powershell")
def test_powershell_parser_accepts_line() -> None:
    line = _line()
    assert _parse_errors(line) == 0
    assert _parse_errors(line.replace("; & 'python'", "; 'python'")) >= 1


def _submit_with(monkeypatch, tmp_path, result_or_exc) -> int:
    from types import SimpleNamespace

    monkeypatch.setenv("JUNKROAN_HOST", "pc")

    def fake(host_cfg, script):
        if isinstance(result_or_exc, Exception):
            raise result_or_exc
        return SimpleNamespace(**result_or_exc)

    monkeypatch.setattr(runs.runs_hosts, "run_on_host", fake)
    monkeypatch.setattr(runs.runs_hosts, "load_hosts_config", lambda: {"laptop": {"ssh": "laptop", "repo_path": REPO}})
    return runs.main(["--store", str(tmp_path / "jobs.jsonl"), "submit", "--issue", "1", "--host", "laptop", "--priority", "P1", "--", "echo", "hi"])


def test_remote_refusal_text_printed_without_unreachable(tmp_path, capsys, monkeypatch) -> None:
    """#462: the laptop answered with its own refusal."""

    text = "submit: tag 'x' already finished; pass --again"
    rc = _submit_with(monkeypatch, tmp_path, {"returncode": 1, "stdout": "", "stderr": text + "\n"})
    err = capsys.readouterr().err
    assert rc == 1
    assert text in err and "unreachable" not in err


def test_ssh_connect_failure_still_unreachable(tmp_path, capsys, monkeypatch) -> None:
    rc = _submit_with(monkeypatch, tmp_path, {
        "returncode": 255, "stdout": "",
        "stderr": "ssh: connect to host laptop port 22: Connection timed out\n"})
    err = capsys.readouterr().err
    assert rc == 1
    assert "submit: laptop unreachable" in err and "Connection timed out" in err


def test_ssh_exception_still_unreachable(tmp_path, capsys, monkeypatch) -> None:
    rc = _submit_with(monkeypatch, tmp_path, TimeoutError("ssh timed out"))
    assert rc == 1
    assert "submit: laptop unreachable" in capsys.readouterr().err
