"""#246 acceptance rows 2-4: prove or refute the row-1 cause hypothesis with a probe that never
touches the owner's real desktop.

    python scripts/probe_console_windows.py --code-root <path to a checkout>

Every window this probe could ever produce is counted on a desktop object the probe creates for
itself (`CreateDesktopW`), never `WinSta0\\Default` (the owner's desktop): the probe asserts the
desktop handle is valid before starting anything, and the root child it launches is started with
`STARTUPINFO.lpDesktop` pointing at that desktop's name -- every descendant it spawns inherits the
same desktop by default (Windows associates a desktop with a thread at creation time, not by
walking up a process tree each time). If `CreateDesktopW` fails, this aborts outright: it never
falls back to the default desktop.

The probe starts a `pythonw.exe` parent (a GUI-subsystem exe: no console of its own, matching how
`schtasks` starts `--ensure` under the keepalive task, `keepalive.py`) which runs a small stand-in
script. That script never runs a real dispatcher tick and opens no PoB: it only calls `gh
--version` three times, through the exact seams the real dispatcher/local-module code uses --
`tools.agentops.dispatch.GhCli._run`, `tools.agentops.cloud_lane.LaneGh._run` (the module
`config/orchestration.json`'s `local_modules` loads into the home dispatcher) and
`tools.agentops.provisional.GhCli._run` -- imported from whichever checkout `--code-root` names,
so the same probe proves row 3 (this checkout, fixed) and row 4 (a checkout of a7fba46, before the
fix) with nothing else different. Each `gh --version` child's console window lives only as long
as that one child process does, which is gone long before the whole stand-in script (three
sequential calls) exits, so the probe polls the desktop every few ms while the stand-in runs
(bounded by `--wait-seconds`), keeping every distinct window (any class, `EnumDesktopWindows`) it
ever saw, then closes the desktop. `EnumDesktopWindows` returning FALSE with `GetLastError()==0`
means the desktop had 0 windows at that instant, not a failure (verified by creating one window on
the same desktop and back).
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from ctypes import wintypes
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("probe_console_windows.py: Windows only")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

GENERIC_ALL = 0x10000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class ProbeError(RuntimeError):
    """The probe could not set up its own isolated desktop or process: abort, never fall back to
    the owner's real desktop."""


def create_isolated_desktop() -> tuple[int, str]:
    """A brand-new desktop with a unique name; `(handle, name)`. Raises `ProbeError` and creates
    nothing further if this fails -- this probe never runs anything on `WinSta0\\Default`."""
    name = f"junkroan-probe-{uuid.uuid4().hex}"
    handle = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not handle:
        raise ProbeError(
            f"CreateDesktopW failed (error {ctypes.get_last_error()}): aborting, "
            f"never falling back to the default desktop"
        )
    return handle, name


def close_desktop(handle: int) -> None:
    user32.CloseDesktop(handle)


def count_windows_on_desktop(handle: int) -> list[tuple[str, str]]:
    """`[(class, title)]` for every window `EnumDesktopWindows` reports on `handle` -- every
    class, not console-shaped windows alone (#246 row 5's own lesson)."""
    found: list[tuple[str, str]] = []

    def _callback(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        title_len = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if title_len:
            title_buf = ctypes.create_unicode_buffer(title_len + 1)
            user32.GetWindowTextW(hwnd, title_buf, title_len + 1)
            title = title_buf.value
        found.append((buf.value, title))
        return True

    ctypes.set_last_error(0)
    ok = user32.EnumDesktopWindows(handle, WNDENUMPROC(_callback), 0)
    if not ok:
        # A fresh, empty desktop makes EnumDesktopWindows return FALSE with GetLastError()==0:
        # the callback is simply never invoked (no window to pass it), which is a valid "0
        # windows", not a failure. Confirmed by repro: creating one window on this same desktop
        # (via SetThreadDesktop from a thread, then CreateWindowExW) makes the very next call
        # return TRUE with that window counted; destroying it goes back to FALSE/err==0. Any
        # other error code is a real failure.
        err = ctypes.get_last_error()
        if err != 0:
            raise ProbeError(f"EnumDesktopWindows failed (error {err})")
        return found
    return found


_STAND_IN_SCRIPT = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {code_root!r})
    from tools.agentops.dispatch import GhCli
    from tools.agentops.cloud_lane import LaneGh
    from tools.agentops.provisional import GhCli as ProvisionalGhCli

    # The exact three seams #246's row 1 names: the core dispatcher's own `gh` runner, the
    # `.cloud_lane` local module's runner (loaded into the home dispatcher by
    # config/orchestration.json's `local_modules`), and `provisional`'s. `--version` only: no
    # network write, no PoB, nothing that touches a real issue.
    GhCli()._run(["--version"])
    LaneGh()._run(["--version"])
    ProvisionalGhCli()._run(["--version"])
    """
)


def _pythonw(python_exe: str | None = None) -> str:
    exe = Path(python_exe or sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else str(exe)


def run_probe(code_root: Path, *, python_exe: str | None = None,
             wait_seconds: float = 20.0) -> tuple[int, list[tuple[str, str]]]:
    """Runs the stand-in dispatcher (importing from `code_root`) as a `pythonw.exe` child of a
    fresh isolated desktop, waits for it to finish (bounded by `wait_seconds`), counts every
    window left on that desktop, and closes it. Returns `(count, windows)`."""
    handle, name = create_isolated_desktop()
    if not handle:
        raise ProbeError("no valid desktop handle: refusing to start anything")
    try:
        script_path = Path(tempfile.mktemp(suffix=".py", prefix="junkroan_probe_standin_"))
        script_path.write_text(
            _STAND_IN_SCRIPT.format(code_root=str(code_root)), encoding="utf-8"
        )
        try:
            exe = _pythonw(python_exe)
            cmdline = f'"{exe}" "{script_path}"'
            startup = STARTUPINFOW()
            startup.cb = ctypes.sizeof(STARTUPINFOW)
            startup.lpDesktop = f"WinSta0\\{name}"
            proc_info = PROCESS_INFORMATION()
            ok = kernel32.CreateProcessW(
                None, cmdline, None, None, False, CREATE_UNICODE_ENVIRONMENT,
                None, None, ctypes.byref(startup), ctypes.byref(proc_info),
            )
            if not ok:
                raise ProbeError(f"CreateProcessW failed (error {ctypes.get_last_error()})")
            # A `gh --version` child's console window lives only as long as that one child
            # process does (tens to low hundreds of ms) -- it is gone long before the whole
            # stand-in script (three sequential calls) exits. Waiting for the stand-in to finish
            # and enumerating only then sees nothing even when every call opened a window. Poll
            # the desktop every few ms while the stand-in runs instead, and keep every distinct
            # (class, title) window ever seen across the whole run.
            WAIT_OBJECT_0 = 0
            poll_interval_ms = 5
            deadline = time.monotonic() + wait_seconds
            seen: dict[tuple[str, str], None] = {}
            try:
                while True:
                    for w in count_windows_on_desktop(handle):
                        seen.setdefault(w, None)
                    wait_result = kernel32.WaitForSingleObject(proc_info.hProcess, poll_interval_ms)
                    if wait_result == WAIT_OBJECT_0 or time.monotonic() >= deadline:
                        break
                # a short settle so a window that pops just as the child exits is still seen
                time.sleep(0.05)
                for w in count_windows_on_desktop(handle):
                    seen.setdefault(w, None)
            finally:
                kernel32.CloseHandle(proc_info.hThread)
                kernel32.CloseHandle(proc_info.hProcess)
        finally:
            try:
                script_path.unlink()
            except OSError:
                pass
        windows = list(seen.keys())
        return len(windows), windows
    finally:
        close_desktop(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", required=True, type=Path,
                        help="a checkout to import tools.agentops from (this worktree, or a temp "
                             "worktree of an older commit)")
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    args = parser.parse_args()

    count, windows = run_probe(args.code_root, wait_seconds=args.wait_seconds)
    for cls, title in windows:
        print(f"WINDOW class={cls} title={title!r}")
    print(f"windows on the isolated desktop: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
