"""#521: a timeout bounds the call, grandchildren holding the pipes included."""

from __future__ import annotations

import subprocess
import sys
import time
import uuid

import pytest

from junkroan.runs import bounded, self_restart


def _marked_sleepers(marker: str) -> list[int]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{marker}*' "
         f"-and $_.CommandLine -notlike '*Get-CimInstance*' }} | ForEach-Object {{ $_.ProcessId }}"],
        capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    return [int(x) for x in out.split()]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process tree")
def test_timeout_kills_the_grandchild_holding_the_pipe():
    marker = "bounded_" + uuid.uuid4().hex
    grand = f"import time; time.sleep(600)  # {marker}"
    child = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grand!r}])\n"
        f"time.sleep(600)  # {marker}\n"
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded.run_bounded([sys.executable, "-c", child], capture_output=True, timeout=2)
        took = time.monotonic() - started
        assert took < 7, took
        deadline = time.monotonic() + 10
        left = _marked_sleepers(marker)
        while left and time.monotonic() < deadline:
            time.sleep(0.5)
            left = _marked_sleepers(marker)
        assert left == []
    finally:
        for pid in _marked_sleepers(marker):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    print(f"timeout test returned in {took:.2f}s")


def test_quick_child_behaves_like_subprocess_run():
    res = bounded.run_bounded(
        [sys.executable, "-c", "import sys; print('hi'); sys.stderr.write('e'); sys.exit(3)"],
        capture_output=True, text=True, timeout=30,
    )
    assert (res.returncode, res.stdout.strip(), res.stderr) == (3, "hi", "e")
    with pytest.raises(subprocess.CalledProcessError):
        bounded.run_bounded([sys.executable, "-c", "raise SystemExit(1)"], timeout=30, check=True)


def test_input_is_fed():
    res = bounded.run_bounded(
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
        capture_output=True, text=True, input="abc", timeout=30,
    )
    assert res.stdout.strip() == "ABC"


def test_killer_is_injectable(monkeypatch):
    killed = []
    monkeypatch.setattr(bounded, "TREE_KILLER", lambda pid: killed.append(pid))
    with pytest.raises(subprocess.TimeoutExpired):
        bounded.run_bounded([sys.executable, "-c", "import time; time.sleep(60)"],
                            capture_output=True, timeout=1)
    assert len(killed) == 1


def test_git_runner_carries_git_ssh_command(monkeypatch, tmp_path):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, "out", "")

    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setattr(self_restart, "run_bounded", fake)
    assert self_restart.git_runner(tmp_path)(["fetch"]) == "out"
    assert seen["env"]["GIT_SSH_COMMAND"] == self_restart.GIT_SSH_COMMAND
    assert "BatchMode=yes" in seen["env"]["GIT_SSH_COMMAND"] and "ConnectTimeout=10" in seen["env"]["GIT_SSH_COMMAND"]


def test_git_env_carries_git_ssh_command_and_keeps_an_existing_one(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    assert self_restart.git_env()["GIT_SSH_COMMAND"] == self_restart.GIT_SSH_COMMAND
    monkeypatch.setenv("GIT_SSH_COMMAND", "mine")
    assert self_restart.git_env()["GIT_SSH_COMMAND"] == "mine"
