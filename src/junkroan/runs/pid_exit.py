"""Exit code of a process this one did not start (adopted by pid), Windows only.

A handle opened with OpenProcess while the pid is alive keeps the process object
after exit, so GetExitCodeProcess still returns the real code.
"""

from __future__ import annotations

import ctypes
import os

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258

_k32 = None
if os.name == "nt":
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    _k32.GetExitCodeProcess.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _k32.CloseHandle.restype = wintypes.BOOL


class ExitWatch:
    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle
        self._code: int | None = None

    def poll(self) -> int | None:
        if self._code is not None:
            return self._code
        if self._handle is None:
            return None
        r = _k32.WaitForSingleObject(self._handle, 0)
        if r == _WAIT_OBJECT_0:
            code = ctypes.wintypes.DWORD()
            if _k32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                self._code = int(code.value)
                return self._code
        return None

    def close(self) -> None:
        h, self._handle = self._handle, None
        if h is not None:
            _k32.CloseHandle(h)

    def __enter__(self) -> "ExitWatch":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def open_exit_watch(pid: int) -> ExitWatch | None:
    if _k32 is None:
        return None
    h = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
    if not h:
        return None
    return ExitWatch(h)
