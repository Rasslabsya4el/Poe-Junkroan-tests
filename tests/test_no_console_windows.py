"""#490 unit 4: a test for every launcher form -- does it ever show a console window?

Cases 1-3 run on a desktop object the test creates for itself (`CreateDesktopW`, the recipe of
`scripts/probe_console_windows.py`), never `WinSta0\\Default`: a python parent is started with
`DETACHED_PROCESS` (no console of its own, like a worker's ad-hoc driver) and `lpDesktop` pointing at
the private desktop, and starts the stand-in `cmd /c python -c "import time; time.sleep(5)"` in the
form under test. Console-class windows (`ConsoleWindowClass`, `CASCADIA_HOSTING_WINDOW_CLASS`,
`PseudoConsoleWindow`) are polled on that desktop while the parent lives.

  1. positive control: plain `Popen` from a DETACHED parent -> exactly 1 window (the test can see one)
  2. `self_restart.respawn` (`CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`) -> 0
  3. `tools/agentops/detach.py`'s child form (`no_window_flags()`) -> 0

Cases 4-5 (`scripts/launch_hidden.ps1`, `tools/hosts/run-hidden.vbs`) run as in production: WMI and
wscript land on the DEFAULT desktop whatever desktop is asked for, so they snapshot the visible
console windows of the default desktop, poll while the stand-in runs and assert 0 new ones."""

from __future__ import annotations

import ctypes
import os
import importlib.util
import re
import subprocess
import sys
import textwrap
import time
from ctypes import wintypes
from pathlib import Path

import pytest
from conftest import pc_only

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timing_bound import bound  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows console windows")

CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow"}
DETACHED_PROCESS = 0x00000008
STAND_IN_SECONDS = 5
STAND_IN_CODE = f"import time; time.sleep({STAND_IN_SECONDS})"


def _probe():
    spec = importlib.util.spec_from_file_location(
        "probe_console_windows", ROOT / "scripts" / "probe_console_windows.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_console_windows", mod)
    spec.loader.exec_module(mod)
    return mod


def _class_of(user32, hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _console_windows_on_desktop(probe, handle) -> dict[int, bool]:
    """{hwnd: visible} of every console-class window on the desktop `handle`."""
    user32 = probe.user32
    found: dict[int, bool] = {}

    def _cb(hwnd, _lparam):
        if _class_of(user32, hwnd) in CONSOLE_CLASSES:
            found[int(hwnd or 0)] = bool(user32.IsWindowVisible(hwnd))
        return True

    user32.EnumDesktopWindows(handle, probe.WNDENUMPROC(_cb), 0)
    return found


# what each form does inside the DETACHED parent; {py} is the interpreter, STAND_IN the stand-in argv
_PARENT_SCRIPT = textwrap.dedent(
    """
    import subprocess, sys, time
    sys.path.insert(0, {root!r})
    sys.path.insert(0, {src!r})
    form = sys.argv[1]
    stand_in = ["cmd", "/c", sys.executable, "-c", {code!r}]
    if form == "plain":
        p = subprocess.Popen(stand_in)
        p.wait()
    elif form == "self_restart":
        from junkroan.runs.self_restart import respawn
        respawn(stand_in[1:], executable="cmd")
        time.sleep({wait})  # respawn returns only the pid: outlive the stand-in
    elif form == "detach":
        from tools.agentops.util import no_window_flags
        p = subprocess.Popen(stand_in, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=no_window_flags())
        p.wait()
    """
)


def _run_form_on_private_desktop(form: str, tmp_path: Path) -> dict[int, bool]:
    """Starts a DETACHED python parent on a private desktop that runs `form`; returns every
    console-class window ever seen on that desktop ({hwnd: visible})."""
    probe = _probe()
    handle, name = probe.create_isolated_desktop()
    script = tmp_path / f"parent_{form}.py"
    script.write_text(
        _PARENT_SCRIPT.format(root=str(ROOT), src=str(ROOT / "src"), code=STAND_IN_CODE,
                              wait=STAND_IN_SECONDS + 2),
        encoding="utf-8",
    )
    seen: dict[int, bool] = {}
    proc_info = probe.PROCESS_INFORMATION()
    try:
        startup = probe.STARTUPINFOW()
        startup.cb = ctypes.sizeof(probe.STARTUPINFOW)
        startup.lpDesktop = f"WinSta0\\{name}"
        cmdline = f'"{sys.executable}" "{script}" {form}'
        ok = probe.kernel32.CreateProcessW(
            None, cmdline, None, None, False,
            DETACHED_PROCESS | probe.CREATE_UNICODE_ENVIRONMENT,
            None, str(ROOT), ctypes.byref(startup), ctypes.byref(proc_info),
        )
        assert ok, f"CreateProcessW failed (error {ctypes.get_last_error()})"
        try:
            deadline = time.monotonic() + STAND_IN_SECONDS + bound(15, 100)  # #826: slack follows the machine
            while True:
                seen.update(_console_windows_on_desktop(probe, handle))
                if probe.kernel32.WaitForSingleObject(proc_info.hProcess, 20) == 0:
                    break
                assert time.monotonic() < deadline, "the parent did not end"
            time.sleep(0.1)
            seen.update(_console_windows_on_desktop(probe, handle))
        finally:
            probe.kernel32.CloseHandle(proc_info.hThread)
            probe.kernel32.CloseHandle(proc_info.hProcess)
    finally:
        probe.close_desktop(handle)
    return seen


@pc_only
def test_positive_control_detached_parent_with_plain_popen_shows_one_window(tmp_path):
    seen = _run_form_on_private_desktop("plain", tmp_path)
    assert len(seen) == 1, f"the test must see exactly 1 console window, saw {seen}"


def test_self_restart_respawn_form_shows_no_window(tmp_path):
    seen = _run_form_on_private_desktop("self_restart", tmp_path)
    assert len(seen) == 0, f"self_restart.respawn showed console windows: {seen}"


def test_detach_child_form_shows_no_window(tmp_path):
    seen = _run_form_on_private_desktop("detach", tmp_path)
    assert len(seen) == 0, f"detach.py's child form showed console windows: {seen}"


# ---- cases 4-5: the production hidden launchers, on the default desktop (snapshot / poll / diff) --

def _visible_console_windows() -> dict[int, str]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: dict[int, str] = {}

    def _cb(hwnd, _lparam):
        cls = _class_of(user32, hwnd)
        if cls in CONSOLE_CLASSES and user32.IsWindowVisible(hwnd):
            found[int(hwnd or 0)] = cls
        return True

    user32.EnumWindows(enum_proc(_cb), 0)
    return found


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def _poll_new_windows(before: dict[int, str], seconds: float) -> dict[int, str]:
    new: dict[int, str] = {}
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for hwnd, cls in _visible_console_windows().items():
            if hwnd not in before:
                new[hwnd] = cls
        time.sleep(0.05)
    return new


# Cases 4-5 start a process through WMI / wscript, which lands on the owner's real desktop whatever
# desktop is asked for: opt-in only (#490; the worker process guard refuses such a start from an agent).
live_desktop = pytest.mark.skipif(
    os.environ.get("JUNKROAN_LIVE_DESKTOP") != "1",
    reason="starts a process on the owner's desktop; set JUNKROAN_LIVE_DESKTOP=1 with the owner away",
)


@live_desktop
def test_launch_hidden_ps1_shows_no_new_console_window():
    before = _visible_console_windows()
    pid = None
    try:
        py = sys.executable
        out = subprocess.run(
            ["powershell", "-NoProfile", "-File", str(ROOT / "scripts" / "launch_hidden.ps1"),
             "-CommandLine", f'"{py}" -c "{STAND_IN_CODE}"'],
            capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        m = re.search(r"rc=0 pid=(\d+)", out)
        assert m, f"launch_hidden.ps1 did not start the stand-in: {out!r}"
        pid = int(m.group(1))
        new = _poll_new_windows(before, 3)
    finally:
        if pid:
            _kill_tree(pid)
    assert not new, f"launch_hidden.ps1 showed new console windows: {new}"


@live_desktop
def test_run_hidden_vbs_shows_no_new_console_window(tmp_path):
    ps1 = tmp_path / "stand_in.ps1"
    ps1.write_text(f'& "{sys.executable}" -c "{STAND_IN_CODE}"\n', encoding="utf-8")
    before = _visible_console_windows()
    proc = subprocess.Popen(
        ["wscript.exe", "//B", "//Nologo", str(ROOT / "tools" / "hosts" / "run-hidden.vbs"), str(ps1)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        new = _poll_new_windows(before, 3)
    finally:
        _kill_tree(proc.pid)
    assert not new, f"run-hidden.vbs showed new console windows: {new}"
