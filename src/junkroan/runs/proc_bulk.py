"""The whole Windows process list in ONE call (#988).

psutil reads a process's memory and CPU time one handle at a time, and for every process the OS refuses
(services, other users) it falls back to a full system scan PER process: ~1.3 s of CPU for one reading of
400 processes. `NtQuerySystemInformation(SystemProcessInformation)` returns the same figures for all of them in
one buffer (~10 ms). `snapshot()` is that call; anything but Windows, or any failure, returns ``None`` and the
caller keeps its psutil path.
"""

from __future__ import annotations

import ctypes
import sys
from typing import NamedTuple

_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_FILETIME_UNIX_EPOCH = 116444736000000000  # 100 ns ticks between 1601-01-01 and 1970-01-01

# Offsets in SYSTEM_PROCESS_INFORMATION (x64): the fields the load record reads.
_OFF_NEXT, _OFF_CREATE, _OFF_USER, _OFF_KERNEL = 0, 32, 40, 48
_OFF_NAME_LEN, _OFF_NAME_PTR = 56, 64
_OFF_PID, _OFF_PPID, _OFF_SESSION, _OFF_WORKING_SET = 80, 88, 100, 144
_MIN_ENTRY = _OFF_WORKING_SET + 8


class ProcInfo(NamedTuple):
    pid: int
    ppid: int
    name: str
    create_time: float  # epoch seconds, as psutil's create_time
    cpu_s: float  # user + kernel
    rss: int  # bytes (the working set, what psutil calls rss)
    session: int


def snapshot() -> dict[int, ProcInfo] | None:
    """Every process at this moment, or ``None`` where this reader does not apply."""

    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    try:
        return _read()
    except Exception:
        return None


def _read() -> dict[int, ProcInfo]:
    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    query.restype = ctypes.c_ulong
    size = 1 << 20
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong(0)
        status = query(_SYSTEM_PROCESS_INFORMATION, buf, size, ctypes.byref(need))
        if status == _STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, need.value + (1 << 16))
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation 0x{status:08x}")
        break
    else:
        raise OSError("NtQuerySystemInformation: buffer never fit")
    raw = bytes(buf.raw[:need.value or size])
    out: dict[int, ProcInfo] = {}
    off = 0
    u64 = lambda at: int.from_bytes(raw[at:at + 8], "little")  # noqa: E731
    u32 = lambda at: int.from_bytes(raw[at:at + 4], "little")  # noqa: E731
    while off + _MIN_ENTRY <= len(raw):
        pid = u64(off + _OFF_PID)
        name_len, name_ptr = int.from_bytes(raw[off + _OFF_NAME_LEN:off + _OFF_NAME_LEN + 2], "little"), u64(off + _OFF_NAME_PTR)
        name = ""
        if name_len and name_ptr:
            name = ctypes.wstring_at(name_ptr, name_len // 2)  # the name lives inside the same buffer
        elif pid == 0:
            name = "System Idle Process"
        out[pid] = ProcInfo(
            pid=pid, ppid=u64(off + _OFF_PPID), name=name,
            create_time=(u64(off + _OFF_CREATE) - _FILETIME_UNIX_EPOCH) / 1e7,
            cpu_s=(u64(off + _OFF_USER) + u64(off + _OFF_KERNEL)) / 1e7,
            rss=u64(off + _OFF_WORKING_SET), session=u32(off + _OFF_SESSION))
        nxt = u32(off + _OFF_NEXT)
        if nxt == 0:
            break
        off += nxt
    return out
