"""#490 unit 1: a job a runs daemon starts never gets a console window, whatever console its
parent has. The parent is a DETACHED_PROCESS (no console at all) on a private desktop object
(never `WinSta0\\Default`); windows are counted on that desktop while the job runs."""

from __future__ import annotations

import ctypes
import sys
import textwrap
import time
from pathlib import Path

import pytest
from conftest import pc_only

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_console_windows as probe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DETACHED_PROCESS = 0x00000008
CONSOLE_CLASSES = {"ConsoleWindowClass", "PseudoConsoleWindow"}

_PARENT = textwrap.dedent(
    """
    import os, sys, time
    from pathlib import Path
    sys.path.insert(0, {src!r})
    from junkroan.runs.daemon import ProcessLauncher
    work = Path({work!r})
    seconds = {seconds}
    child = ProcessLauncher().start(
        ["cmd", "/c", sys.executable, "-c", "import time; time.sleep(%d)" % seconds],
        cwd=work, out=work / "job.out", env=dict(os.environ),
    )
    (work / "pid.txt").write_text(str(child.pid))
    deadline = time.time() + 60
    while child.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    (work / "rc.txt").write_text(str(child.poll()))
    child.close()
    """
)


def _spawn_detached(script: Path, desktop_name: str) -> probe.PROCESS_INFORMATION:
    startup = probe.STARTUPINFOW()
    startup.cb = ctypes.sizeof(probe.STARTUPINFOW)
    startup.lpDesktop = f"WinSta0\\{desktop_name}"
    info = probe.PROCESS_INFORMATION()
    cmdline = f'"{sys.executable}" "{script}"'
    ok = probe.kernel32.CreateProcessW(
        None, cmdline, None, None, False, DETACHED_PROCESS | probe.CREATE_UNICODE_ENVIRONMENT,
        None, None, ctypes.byref(startup), ctypes.byref(info),
    )
    assert ok, f"CreateProcessW failed ({ctypes.get_last_error()})"
    return info


def _console_classes(handle) -> set[str]:
    return {c for c, _t in probe.count_windows_on_desktop(handle) if c in CONSOLE_CLASSES}


def _run_parent(tmp_path: Path, seconds: int, *, between=None) -> set[str]:
    """Run the parent on a private desktop; the console-window classes seen while it ran."""
    script = tmp_path / "parent.py"
    script.write_text(
        _PARENT.format(src=str(ROOT / "src"), work=str(tmp_path), seconds=seconds), encoding="utf-8"
    )
    handle, name = probe.create_isolated_desktop()
    seen: set[str] = set()
    try:
        info = _spawn_detached(script, name)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                seen |= _console_classes(handle)
                if between is not None and (tmp_path / "pid.txt").exists():
                    time.sleep(0.5)
                    seen |= _console_classes(handle)
                    between(int((tmp_path / "pid.txt").read_text()))
                    between = None
                if probe.kernel32.WaitForSingleObject(info.hProcess, 20) == 0:
                    break
            else:
                probe.kernel32.TerminateProcess(info.hProcess, 1)
                pytest.fail("parent did not finish in 60 s")
            time.sleep(0.05)
            seen |= _console_classes(handle)
        finally:
            probe.kernel32.CloseHandle(info.hThread)
            probe.kernel32.CloseHandle(info.hProcess)
    finally:
        probe.close_desktop(handle)
    return seen


@pc_only
def test_job_of_detached_parent_gets_no_window(tmp_path):
    seen = _run_parent(tmp_path, 4)
    print(f"console windows on the private desktop: {len(seen)} {sorted(seen)}")
    assert (tmp_path / "rc.txt").read_text() == "0"
    assert len(seen) == 0


def test_taskkill_tree_still_ends_a_started_job(tmp_path):
    import psutil

    from junkroan.runs.stopper import taskkill_tree

    killed: list[bool] = []
    seen = _run_parent(tmp_path, 40, between=lambda pid: killed.append(taskkill_tree(pid)))
    assert killed == [True]
    assert not psutil.pid_exists(int((tmp_path / "pid.txt").read_text()))
    assert len(seen) == 0
