"""#872 unit 1b: reader. Every window prints one JSON line with the machine's busy cores by four definitions.

A = psutil cpu_times user+system+interrupt+dpc (what sample_kinds_838.busy_s uses)
A0 = psutil user+system only (to see whether interrupt/dpc are already inside `system`)
B = GetSystemTimes: kernel + user - idle
C = sum of cpu deltas of every process alive at both ends (pid + creation time), no kinds
D = NtQuerySystemInformation(8) per CPU: kernel + user - idle (kernel includes idle, dpc, interrupt); Dx = dpc+interrupt
Starts no load; BELOW_NORMAL priority. Usage: probe_busy_872.py --minutes 12 --window 60 --out FILE
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_kinds_838 as sk  # noqa: E402


def system_times() -> tuple[float, float, float]:
    i, k, u = (wintypes.FILETIME() for _ in range(3))
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    f = lambda t: ((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7  # noqa: E731
    return f(i), f(k), f(u)


def perf_info() -> dict[str, float]:
    import psutil

    n = psutil.cpu_count(logical=True)
    size = 48 * n
    buf = ctypes.create_string_buffer(size)
    ret = ctypes.c_ulong()
    st = ctypes.windll.ntdll.NtQuerySystemInformation(8, buf, size, ctypes.byref(ret))
    if st != 0:
        raise OSError(f"NtQuerySystemInformation(8) status {st & 0xFFFFFFFF:#x}")
    tot = dict(idle=0, kernel=0, user=0, dpc=0, interrupt=0)
    for c in range(ret.value // 48):
        idle, kern, user, dpc, intr = struct.unpack_from("<qqqqq", buf.raw, c * 48)
        tot["idle"] += idle; tot["kernel"] += kern; tot["user"] += user; tot["dpc"] += dpc; tot["interrupt"] += intr
    return {k: v / 1e7 for k, v in tot.items()}


def snap() -> dict:
    import psutil

    t = psutil.cpu_times()
    return {"t": time.time(), "ps": t, "sys": system_times(), "perf": perf_info(),
            "proc": {(r["pid"], r["born"]): r["cpu_s"] for r in sk.read_table()}}


def delta(a: dict, b: dict) -> dict:
    w = b["t"] - a["t"]
    pa, pb = a["ps"], b["ps"]
    d = lambda f: (getattr(pb, f, 0.0) - getattr(pa, f, 0.0))  # noqa: E731
    A0 = d("user") + d("system")
    A = A0 + d("interrupt") + d("dpc")
    si, sk_, su = (y - x for x, y in zip(a["sys"], b["sys"]))
    B = sk_ + su - si
    C = sum(max(0.0, cpu - a["proc"][k]) for k, cpu in b["proc"].items() if k in a["proc"])
    p = {k: b["perf"][k] - a["perf"][k] for k in a["perf"]}
    D = p["kernel"] + p["user"] - p["idle"]
    r = lambda x: round(x / w, 3)  # noqa: E731
    return {"window_s": round(w, 1), "A_psutil_busy": r(A), "A0_user_system": r(A0), "B_GetSystemTimes": r(B),
            "C_all_process": r(C), "D_perf_info": r(D), "D_dpc_int": r(p["dpc"] + p["interrupt"]),
            "A-B": r(A - B), "A-C": r(A - C), "B-C": r(B - C), "D-C": r(D - C), "A-D": r(A - D)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--window", type=float, default=60.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    end = time.time() + a.minutes * 60
    with open(a.out, "a", encoding="utf-8") as f:
        f.write(json.dumps({"owner": "probe_busy_872", "pid": os.getpid(), "ticket": 872,
                            "ends": time.strftime("%H:%M:%S", time.localtime(end))}) + "\n"); f.flush()
        prev = snap()
        while time.time() + a.window <= end + 1:
            time.sleep(a.window)
            cur = snap()
            f.write(json.dumps(delta(prev, cur)) + "\n"); f.flush()
            prev = cur


if __name__ == "__main__":
    main()
