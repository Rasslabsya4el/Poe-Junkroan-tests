"""#258 rows 5-6: `agentops stop` live, on stand-ins only, on a desktop object of its own.

    python scripts/probe_stop_live.py
    python scripts/probe_stop_live.py --force-mismatch   # exit-code logic only, no real process

Adapted by hand from `ab-mini-c`'s `scripts/probe_stop_live.py` (commit 4997e41) and
`scripts/probe_job_breakaway.py` of the same branch (the isolated-desktop object and the owner's-
desktop window watch) -- neither file exists on `main`, so this script is self-contained rather
than importing them; that branch's own "always exits 0" is NOT taken here -- #258 wants a real
exit code, non-zero when a count is off.

Two stand-ins, each a plain `python -c` process that writes its own pid to a file then sleeps:

- A: started by a Git Bash shell that waits for it (the shell stays alive the whole run) -- A's
  chain reaches this probe's own process tree and, through it (this script must be run from a
  live Claude session's shell, exactly like the probe it is adapted from), a live `claude.exe`:
  `agentops stop` must refuse it.
- B: started by a Git Bash shell that backgrounds it (`... &`) and exits at once -- B's chain
  reaches no live session: `agentops stop` must stop it.

Everything of this trial (both stand-ins, both shells, the `stop` command itself) runs on one
`CreateDesktopW` desktop object of the probe's own -- never the desktop this script itself
started on (measured live, #257: a process `CreateProcessW` starts with `STARTUPINFOW.lpDesktop`
set lands on that desktop, not the caller's). A background thread lists every top-level window
(any class, visible or hidden) that lands on the CALLER's own desktop -- the real one, where the
owner would see it -- belonging to any process of this trial, for the whole run: expected 0.

`--force-mismatch` never starts a real process: it feeds `_verdict_exit_code` a count that does
not match what was expected, proving "a count off -> exit != 0" without live process handling.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("probe_stop_live.py: Windows only")

ROOT = Path(__file__).resolve().parents[1]

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
user32.CreateDesktopW.restype = wintypes.HANDLE

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GENERIC_ALL = 0x10000000
CREATE_NEW_CONSOLE = 0x00000010
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESHOWWINDOW = 0x00000001
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

GIT_BASH_CANDIDATES = (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe")

STANDIN = textwrap.dedent(
    """
    import os, sys, time
    open(sys.argv[1], "w").write(str(os.getpid()))
    time.sleep(600)
    """
)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class ProbeError(RuntimeError):
    pass


def _git_bash() -> str:
    for candidate in GIT_BASH_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    raise ProbeError("no Git Bash found")


def create_isolated_desktop() -> tuple[int, str]:
    name = f"junkroan-258-{uuid.uuid4().hex}"
    handle = user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not handle:
        raise ProbeError(f"CreateDesktopW failed (error {ctypes.get_last_error()})")
    return handle, name


def close_desktop(handle: int) -> None:
    user32.CloseDesktop(handle)


def start_on_desktop(command_line: str, desktop: str, cwd: Path) -> tuple[int, int]:
    startup = STARTUPINFOW()
    startup.cb = ctypes.sizeof(STARTUPINFOW)
    startup.lpDesktop = desktop
    startup.dwFlags = STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    info = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, command_line, None, None, False,
                                 CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT, None,
                                 str(cwd), ctypes.byref(startup), ctypes.byref(info))
    if not ok:
        raise ProbeError(f"CreateProcessW failed ({ctypes.get_last_error()}): {command_line}")
    kernel32.CloseHandle(info.hThread)
    return info.dwProcessId, info.hProcess


def pid_alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def stop_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)


def _wait_file(path: Path, seconds: float) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    raise ProbeError(f"nothing in {path} within {seconds:.0f} s")


def _process_table() -> dict[int, int]:
    """`{pid: ppid}` from one Toolhelp snapshot."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return {}
    out: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def _descendants(roots: set[int], table: dict[int, int]) -> set[int]:
    found = set(roots)
    grew = True
    while grew:
        grew = False
        for pid, ppid in table.items():
            if ppid in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def _all_top_level_windows() -> dict[int, tuple[str, int, bool]]:
    """`{hwnd: (class, owner pid, visible)}` of every top-level window on THIS thread's desktop --
    the caller's real one, never the isolated one (this thread never calls `SetThreadDesktop`)."""
    found: dict[int, tuple[str, int, bool]] = {}

    def _cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found[hwnd] = (buf.value, pid.value, bool(user32.IsWindowVisible(hwnd)))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found


@dataclass
class OwnerDesktopWatch:
    """Samples the CALLER's own desktop (this thread's -- pytest/this script never switches to
    the isolated one) every `interval` s, keeping every top-level window new since `start()` that
    is owned by a pid descended from `roots`."""
    interval: float = 0.05
    roots: set[int] = field(default_factory=set)
    windows: dict[int, tuple[str, int, bool]] = field(default_factory=dict)
    _baseline: set[int] = field(default_factory=set)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._baseline = set(_all_top_level_windows())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.interval)
        self._tick()

    def _tick(self) -> None:
        table = _process_table()
        trial_pids = _descendants(set(self.roots), table)
        for hwnd, info in _all_top_level_windows().items():
            if hwnd not in self._baseline and info[1] in trial_pids:
                self.windows.setdefault(hwnd, info)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


def _verdict_exit_code(*, refused: int, refused_of: int, stopped: int, stopped_of: int) -> int:
    """0 only when every expected count was met exactly (`refused == refused_of` and `stopped ==
    stopped_of`) -- a count off (fewer, more, or the wrong pid counted) is a probe failure, never
    silently 0 (#258: the ab-mini-c original always returned 0, not taken here)."""

    return 0 if (refused == refused_of and stopped == stopped_of) else 1


def run_probe(*, code_root: Path = ROOT) -> dict:
    python = sys.executable.replace("\\", "/")
    bash = _git_bash()
    desk_handle, desk_name = create_isolated_desktop()
    desktop = f"WinSta0\\{desk_name}"
    workdir = Path(tempfile.mkdtemp(prefix="junkroan_258_"))
    standin = workdir / "standin.py"
    standin.write_text(STANDIN, encoding="utf-8")
    s = str(standin).replace("\\", "/")
    pid_a_file, pid_b_file, out_file = workdir / "a.pid", workdir / "b.pid", workdir / "stop.out"
    a_file = str(pid_a_file).replace("\\", "/")
    b_file = str(pid_b_file).replace("\\", "/")
    watch = OwnerDesktopWatch()
    watch.roots.add(os.getpid())
    shell_a = pid_a = pid_b = None
    handles: list[int] = []
    try:
        watch.start()
        # A: the shell waits for it (a live shell) -- reaches this probe's own session
        shell_a, h = start_on_desktop(f'"{bash}" -c "\'{python}\' \'{s}\' \'{a_file}\'"',
                                      desktop, workdir)
        handles.append(h)
        # B: the shell backgrounds it and exits at once
        shell_b, h_b = start_on_desktop(
            f'"{bash}" -c "\'{python}\' \'{s}\' \'{b_file}\' > /dev/null 2>&1 &"', desktop, workdir)
        handles.append(h_b)
        pid_a = int(_wait_file(pid_a_file, 60))
        pid_b = int(_wait_file(pid_b_file, 60))
        watch.roots |= {pid_a, pid_b}
        if kernel32.WaitForSingleObject(h_b, 30_000) != 0:
            raise ProbeError("B's shell did not end within 30 s")
        time.sleep(1.0)
        b_shell_gone = not pid_alive(shell_b)

        stop_pid, h_stop = start_on_desktop(
            f'cmd /c ""{sys.executable}" -m tools.agentops stop {pid_a} {pid_b} > "{out_file}" 2>&1"',
            desktop, code_root)
        handles.append(h_stop)
        if kernel32.WaitForSingleObject(h_stop, 180_000) != 0:
            raise ProbeError("stop did not finish within 3 min")
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(h_stop, ctypes.byref(code))
        time.sleep(1.0)
        lines = out_file.read_text(encoding="utf-8", errors="replace").splitlines()
        result = {
            "pid_a": pid_a, "pid_b": pid_b, "b_shell_gone_before_stop": b_shell_gone,
            "stop_exit_code": code.value, "stop_output": lines,
            "a_alive_after": pid_alive(pid_a), "b_alive_after": pid_alive(pid_b),
        }
    finally:
        watch.stop()
        for pid in (shell_a, pid_a, pid_b):
            if pid and pid_alive(pid):
                stop_tree(pid)
        for h in handles:
            kernel32.CloseHandle(h)
        close_desktop(desk_handle)
        shutil.rmtree(workdir, ignore_errors=True)
    result["owner_desktop_windows"] = list(watch.windows.values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force-mismatch", action="store_true",
                        help="exercise the exit-code logic alone, no real process")
    args = parser.parse_args()

    if args.force_mismatch:
        # a count that does not match what was expected (2 refused when 1 was expected) -- no real
        # process is touched; this exercises `_verdict_exit_code` alone (#258 row 5's parenthetical)
        code = _verdict_exit_code(refused=2, refused_of=1, stopped=1, stopped_of=1)
        print(f"forced mismatch: exit code {code}")
        return code

    r = run_probe()
    for line in r["stop_output"]:
        print(f"stop> {line}")
    refused = sum(1 for line in r["stop_output"]
                 if f"pid {r['pid_a']}:" in line and "refused --" in line)
    stopped = sum(1 for line in r["stop_output"]
                 if f"pid {r['pid_b']}:" in line and line.rstrip().endswith("-- stopped"))
    print(f"B's shell gone before the stop: {r['b_shell_gone_before_stop']}")
    print(f"stop exit code: {r['stop_exit_code']}")
    print(f"A (child of a live shell): refused {refused} of 1, alive after: {r['a_alive_after']}")
    print(f"B (its shell ended): stopped {stopped} of 1, alive after: {r['b_alive_after']}")
    print(f"windows of the probe on the caller's own desktop: {len(r['owner_desktop_windows'])} "
          f"{r['owner_desktop_windows']}")

    code = _verdict_exit_code(refused=refused, refused_of=1, stopped=stopped, stopped_of=1)
    if r["stop_exit_code"] == 0:
        code = 1  # `stop` itself must have exited non-zero (a refusal happened)
    if r["a_alive_after"] is not True or r["b_alive_after"] is not False:
        code = 1
    if r["owner_desktop_windows"]:
        code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
