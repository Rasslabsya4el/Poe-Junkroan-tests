"""#838: one jsonl line per window with CPU in cores per KIND of work, over one window for all numbers.

Per kind: sum over processes alive at both ends of the window of (user+system cpu delta) / window.
`total_busy_cores` is the machine's busy time delta (psutil.cpu_times: user+system+interrupt+dpc) / window.
`short_lived_cores` = machine busy - the processes alive at both window ends (= sum of kinds): the CPU of
processes shorter than the read interval, which no per-pid delta can see (#872: not attributed per window).
One psutil walk per window (the end walk is the next window's start). Runs at BELOW_NORMAL.

    python scripts/sample_kinds_838.py --out samples.jsonl [--minutes N | --window S --count N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.runs import load_groups as lg  # noqa: E402

KINDS = ("orch_and_subagents", "workers_pytest", "merge_suite", "full_run", "pob_jobs",
         "desktop_and_mods", "daemons", "system", "sampler", "other")


def _line(row: Mapping[str, Any]) -> str:
    return lg._norm(" ".join(str(t) for t in row.get("cmdline") or ()))


def _is_daemon(row: Mapping[str, Any]) -> bool:
    line = _line(row)
    return ("agentops" in line and "dispatch" in line) or ("runs.py" in line and "daemon" in line)


def _is_merge(row: Mapping[str, Any]) -> bool:
    line = _line(row)
    return ("agentops" in line and " merge" in line) or lg._in_merge_suite(row)


def _claude_path(row: Mapping[str, Any]) -> str:
    cmd = row.get("cmdline") or ()
    return lg._norm(str(cmd[0])) if cmd else ""


def _is_cli_claude(row: Mapping[str, Any]) -> bool:
    """The `claude` CLI / background session: claude.exe from the claude-code folder (the desktop app's own
    claude.exe lives under WindowsApps, folder app, and is also named claude.exe)."""

    if lg._norm(row.get("name") or "") != "claude.exe":
        return False
    return "claude-code" in _claude_path(row) or not _is_desktop_claude(row)


def _is_desktop_claude(row: Mapping[str, Any]) -> bool:
    if (row.get("name") or "") == "Claude.exe":
        return True
    path = _claude_path(row)
    return lg._norm(row.get("name") or "") == "claude.exe" and ("windowsapps" in path or "/app/claude.exe" in path)


def classify(row: Mapping[str, Any], by_pid: Mapping[int, Mapping[str, Any]],
             job_pids: Mapping[int, str] | None = None, self_pid: int | None = None) -> str:
    """Kind of one process by its own record and its ancestor chain (row first, root last)."""

    if self_pid is not None and row["pid"] == self_pid:
        return "sampler"
    job_pids = job_pids or {}
    chain: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    cur: Any = row
    while cur is not None and cur["pid"] not in seen:
        seen.add(cur["pid"])
        chain.append(cur)
        cur = by_pid.get(cur.get("ppid"))
    if any(r["pid"] in job_pids for r in chain):
        return "pob_jobs"
    if any(lg._norm(r.get("name") or "") == "junkroan.exe" or lg._is_pob_runtime(r) for r in chain):
        return "pob_jobs"
    if any(_is_daemon(r) for r in chain):
        return "daemons"
    if any(_is_merge(r) for r in chain):
        return "merge_suite"
    if any(lg.is_full_run_cmdline(r.get("cmdline")) for r in chain):
        return "full_run"
    if any(_is_cli_claude(r) for r in chain):
        return "workers_pytest" if any(lg._is_pytest(r) for r in chain) else "orch_and_subagents"
    if any(_is_desktop_claude(r) for r in chain):
        return "desktop_and_mods"
    if lg._classify(row) == "system":
        return "system"
    return "other"


_STATIC: dict[tuple[int, float], dict[str, Any]] = {}  # (pid, born) -> cmdline / username / session, read once


def _sysinfo() -> list[tuple[int, int, str, float, float]]:
    """(pid, ppid, name, creation time, user+kernel cpu seconds) of EVERY process from one
    NtQuerySystemInformation(SystemProcessInformation) call (x64 layout). Unlike a handle per process it also
    reads the processes a non-elevated user may not open (System, svchost, MsMpEng, vmmem). pid 0 (idle) is dropped."""

    import ctypes
    import struct

    nt = ctypes.windll.ntdll
    size = 1 << 20
    while True:
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong()
        st = nt.NtQuerySystemInformation(5, buf, size, ctypes.byref(need))
        if st & 0xFFFFFFFF == 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
            size = max(size * 2, need.value + (1 << 16))
            continue
        if st != 0:
            raise OSError(f"NtQuerySystemInformation status {st & 0xFFFFFFFF:#x}")
        break
    raw = buf.raw
    out = []
    off = 0
    while True:
        nxt = struct.unpack_from("<I", raw, off)[0]
        create, user, kern = struct.unpack_from("<qqq", raw, off + 32)
        nlen, _mx, nptr = struct.unpack_from("<HHxxxxQ", raw, off + 56)
        pid, ppid = struct.unpack_from("<QQ", raw, off + 80)
        if pid:
            name = ctypes.string_at(nptr, nlen).decode("utf-16-le") if nlen and nptr else ""
            out.append((int(pid), int(ppid), name, create / 1e7, (user + kern) / 1e7))
        if not nxt:
            break
        off += nxt
    return out


def _static(pid: int, born: float) -> dict[str, Any]:
    key = (pid, born)
    if key not in _STATIC:
        import psutil

        d: dict[str, Any] = {"cmdline": [], "username": None, "session": None}
        try:
            p = psutil.Process(pid)
            d["cmdline"] = p.cmdline()
            d["username"] = p.username()
        except Exception:
            pass
        if d["username"] is None:
            d["session"] = lg._session_of(pid)
        _STATIC[key] = d
    return _STATIC[key]


def read_table() -> list[dict[str, Any]]:
    if sys.platform != "win32":
        import psutil

        return [{"pid": p.pid, "ppid": p.info["ppid"], "name": p.info["name"] or "", "cmdline": p.info["cmdline"] or [],
                 "username": p.info["username"], "session": None, "cwd": None,
                 "cpu_s": float(p.info["cpu_times"].user + p.info["cpu_times"].system) if p.info["cpu_times"] else 0.0,
                 "born": p.info["create_time"]}
                for p in psutil.process_iter(["ppid", "name", "cmdline", "username", "cpu_times", "create_time"])]
    rows = []
    live = set()
    for pid, ppid, name, born, cpu in _sysinfo():
        st = _static(pid, born)
        live.add((pid, born))
        rows.append({"pid": pid, "ppid": ppid, "name": name, "cwd": None, "cpu_s": cpu, "born": born, **st})
    for key in [k for k in _STATIC if k not in live]:
        del _STATIC[key]
    return rows


def busy_s() -> float:
    import psutil

    t = psutil.cpu_times()
    return float(t.user + t.system + getattr(t, "interrupt", 0.0) + getattr(t, "dpc", 0.0))


def intdpc_s() -> float:
    import psutil

    t = psutil.cpu_times()
    return float(getattr(t, "interrupt", 0.0) + getattr(t, "dpc", 0.0))


def born_cores(prev: list[dict[str, Any]], cur: list[dict[str, Any]], window: float) -> float:
    """Cores of processes born inside the window: their whole cpu time at the end is inside it (no pair to diff)."""

    before = {(r["pid"], r.get("born")) for r in prev}
    return sum(r["cpu_s"] for r in cur if (r["pid"], r.get("born")) not in before) / window


def died_seen_cores(tables: list[list[dict[str, Any]]], window: float) -> float:
    """Cores of processes (pid, born) that are in some sub-read of the window but NOT in its last table (died inside):
    the sum of their cpu deltas between consecutive sub-reads; a death between two reads loses only that last gap."""

    alive_end = {(r["pid"], r.get("born")) for r in tables[-1]}
    total = 0.0
    for a, b in zip(tables, tables[1:]):
        before = {(r["pid"], r.get("born")): r["cpu_s"] for r in a}
        for r in b:
            k = (r["pid"], r.get("born"))
            if k in before and k not in alive_end:
                total += max(0.0, r["cpu_s"] - before[k])
    return total / window


def kinds_delta(prev: list[dict[str, Any]], cur: list[dict[str, Any]], window: float,
                job_pids: Mapping[int, str] | None = None, self_pid: int | None = None) -> dict[str, float]:
    """Cores per kind over `window` for processes alive at both ends (same pid and creation time)."""

    before = {r["pid"]: r for r in prev}
    by_pid = {r["pid"]: r for r in cur}
    out = {k: 0.0 for k in KINDS}
    for r in cur:
        b = before.get(r["pid"])
        if b is None or b.get("born") != r.get("born"):
            continue
        out[classify(r, by_pid, job_pids, self_pid)] += max(0.0, r["cpu_s"] - b["cpu_s"]) / window
    return out


def sample_line(kinds: Mapping[str, float], total_busy: float, window: float, ts: str | None = None,
                born: float | None = None, intdpc: float | None = None,
                died_seen: float = 0.0) -> dict[str, Any]:
    row: dict[str, Any] = {"ts": ts or datetime.now().isoformat(timespec="seconds"), "window_s": round(window, 2),
                           "ncpu": os.cpu_count()}
    for k in KINDS:
        row[k] = round(kinds.get(k, 0.0), 3)
    row["total_busy_cores"] = round(total_busy, 3)
    unattr = total_busy - sum(kinds.values())
    row["short_lived_cores"] = round(unattr, 3)
    if born is not None and intdpc is not None:  # the residual by measured cause (#872)
        row["born_in_window_cores"] = round(born, 3)
        row["interrupt_dpc_cores"] = round(intdpc, 3)
        row["died_seen_cores"] = round(died_seen, 3)  # died inside, caught by a sub-read
        row["died_or_unread_cores"] = round(unattr - born - intdpc - died_seen, 3)  # remainder: lost last gap + unreadable
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--minutes", type=int, default=0, help="windows of 60 s; 0 = until killed")
    ap.add_argument("--window", type=float, default=60.0, help="window in seconds")
    ap.add_argument("--sub", type=float, default=5.0, help="sub-read step in seconds inside a window; 0 = off")
    ap.add_argument("--ticket", help="ticket number written to the owner record line")
    ap.add_argument("--count", type=int, default=0, help="number of windows (overrides --minutes)")
    a = ap.parse_args(argv)
    count = a.count or a.minutes
    import psutil

    me = psutil.Process()
    if sys.platform == "win32":
        me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    if out:
        end = datetime.now() + timedelta(seconds=a.window * count) if count else None
        out.write(json.dumps({"owner": {"pid": os.getpid(), "ticket": a.ticket,
                                        "end": end.isoformat(timespec="seconds") if end else None}}) + chr(10))
        out.flush()
    prev_idd = intdpc_s()
    prev, prev_busy, prev_t = read_table(), busy_s(), time.monotonic()  # cold start (cmdlines) not counted below
    t_start, cpu_start = time.monotonic(), sum(me.cpu_times()[:2])
    n = 0
    try:
        while not count or n < count:
            tables = [prev]
            t_end = prev_t + a.window
            while a.sub and time.monotonic() + a.sub < t_end:
                time.sleep(a.sub)
                tables.append(read_table())
            time.sleep(max(0.0, t_end - time.monotonic()))
            cur, busy, idd, now = read_table(), busy_s(), intdpc_s(), time.monotonic()
            win = now - prev_t
            kinds = kinds_delta(prev, cur, win, lg.live_job_pids(), os.getpid())
            tables.append(cur)
            row = sample_line(kinds, (busy - prev_busy) / win, win, born=born_cores(prev, cur, win),
                              intdpc=(idd - prev_idd) / win, died_seen=died_seen_cores(tables, win))
            text = json.dumps(row)
            print(text, flush=True)
            if out:
                out.write(text + "\n")
                out.flush()
            prev, prev_busy, prev_t, prev_idd = cur, busy, now, idd
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        if out:
            out.close()
        el = max(time.monotonic() - t_start, 1e-9)
        own = (sum(me.cpu_times()[:2]) - cpu_start) / el
        print(f"sampler own cost: {own * 100:.2f} % of one core over {el:.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
