"""#872 unit 1c: reader. Per window one JSON line, cores by: D (NtQuerySystemInformation(8) busy), C2 (processes alive at
both ends, 60 s ends), CT (sum of THREAD times of the same processes, ends), C1 (1 s poll: every increment of every
process incl. those born and dead between window ends), plus Idle/System process facts. Starts no load; BELOW_NORMAL.
Unit 2b (#872): also names every process born AND dead inside a window (seen by the poll) by executable and by the
tree of its parent at first sight: pob_job / test_suite / orch_worker / other / unknown (a parent already dead);
last line `short_lived_table` = top 10 executables by CPU (cores over the run) + the share whose tree is named.
Usage: probe_busy_872c.py --minutes 10 --window 60 --out FILE [--poll 0.2]"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_busy_872 as pb  # noqa: E402

THREADS_OFF = 0x100
THREAD_SZ = 0x50


NAMED = ("pob_job", "test_suite", "orch_worker")
KIND_MAP = {"pob_jobs": "pob_job", "full_run": "pob_job", "workers_pytest": "test_suite", "merge_suite": "test_suite",
            "orch_and_subagents": "orch_worker"}


def kind_of(chain: list[dict], broken: bool, self_pid: int | None = None) -> str:
    """Class of a process from its chain (row first, root last; each {pid, ppid, name, cmdline}). `broken` = the
    walk ended at a parent that was already dead: an unnamed result then is `unknown`, not `other`."""
    import sample_kinds_838 as sk
    by_pid = {r["pid"]: r for r in chain}
    k = sk.classify(chain[0], by_pid, None, self_pid)
    if k in KIND_MAP:
        return KIND_MAP[k]
    if any(sk.lg._is_pytest(r) for r in chain):
        return "test_suite"
    return "unknown" if broken else "other"


def summarize(records: list[dict], elapsed_s: float, top: int = 10) -> dict:
    """records: {name, kind, cpu_s}. Top executables by CPU (cores over `elapsed_s`) and the named share."""
    total = sum(r["cpu_s"] for r in records)
    named = sum(r["cpu_s"] for r in records if r["kind"] in NAMED)
    exes: dict[str, dict] = {}
    for r in records:
        e = exes.setdefault(r["name"], {"cpu_s": 0.0, "n": 0, "by_kind": {}})
        e["cpu_s"] += r["cpu_s"]; e["n"] += 1
        e["by_kind"][r["kind"]] = e["by_kind"].get(r["kind"], 0.0) + r["cpu_s"]
    rows = [{"exe": n, "cores": round(e["cpu_s"] / elapsed_s, 4), "n": e["n"],
             "main_kind": max(e["by_kind"], key=e["by_kind"].get)}
            for n, e in sorted(exes.items(), key=lambda kv: -kv[1]["cpu_s"])[:top]]
    by_exe = sum(r["cpu_s"] for r in records if r.get("by_exe"))
    kinds: dict[str, float] = {}
    for r in records:
        kinds[r["kind"]] = kinds.get(r["kind"], 0.0) + r["cpu_s"]
    return {"short_lived_cores": round(total / elapsed_s, 3), "n_processes": len(records),
            "named_share": round(named / total, 3) if total else None,
            "named_by_exe_cores": round(by_exe / elapsed_s, 3),
            "kind_cores": {k: round(v / elapsed_s, 3) for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])},
            "top": rows}


def format_table(summ: dict) -> str:
    out = ["| # | executable | cores | processes | main tree |", "|---|---|---|---|---|"]
    for i, r in enumerate(summ["top"], 1):
        out.append(f"| {i} | {r['exe']} | {r['cores']:.3f} | {r['n']} | {r['main_kind']} |")
    share = summ["named_share"]
    out.append(f"named share (pob_job + test_suite + orch_worker): "
               f"{'n/a' if share is None else format(share * 100, '.1f') + ' %'} of {summ['short_lived_cores']} cores "
               f"({summ['n_processes']} processes); by kind: {summ['kind_cores']}; "
               f"named_by_exe_cores: {summ['named_by_exe_cores']}")
    return "\n".join(out)


def read_all() -> dict[tuple[int, float], tuple[float, float, str, int, int]]:
    """{(pid, create): (process cpu s, thread-sum cpu s, name, nthreads, ppid)}; pid 0 included."""
    nt = ctypes.windll.ntdll
    size = 1 << 21
    while True:
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong()
        st = nt.NtQuerySystemInformation(5, buf, size, ctypes.byref(need))
        if st & 0xFFFFFFFF == 0xC0000004:
            size = max(size * 2, need.value + (1 << 16)); continue
        if st != 0:
            raise OSError(hex(st & 0xFFFFFFFF))
        break
    raw = buf.raw
    out = {}
    off = 0
    while True:
        nxt, nth = struct.unpack_from("<II", raw, off)
        create, user, kern = struct.unpack_from("<qqq", raw, off + 32)
        nlen, _mx, nptr = struct.unpack_from("<HHxxxxQ", raw, off + 56)
        pid, ppid = struct.unpack_from("<QQ", raw, off + 80)
        tsum = 0
        for i in range(nth):
            k, u = struct.unpack_from("<qq", raw, off + THREADS_OFF + i * THREAD_SZ)
            tsum += k + u
        name = ctypes.string_at(nptr, nlen).decode("utf-16-le") if nlen and nptr else ""
        out[(int(pid), create / 1e7)] = ((user + kern) / 1e7, tsum / 1e7, name, nth, int(ppid))
        if not nxt:
            break
        off += nxt
    return out


def _psutil_cmdline(pid: int) -> tuple:
    import psutil
    return tuple(psutil.Process(pid).cmdline())


class Tracker:
    """Names a process at first sight: chain by snapshot ppid (parent must be older than the child), cmdlines by psutil.
    Kind and cmdline are remembered per (pid, create); a dead parent or an unreadable row falls back to that cache
    (kind the tree had while alive); still unresolvable -> `unresolved`, never `unknown`/`other` by poll timing."""

    def __init__(self, reader=_psutil_cmdline) -> None:
        self.reader = reader
        self.cmd: dict[tuple[int, float], tuple | None] = {}    # None = psutil could not read it
        self.kinds: dict[tuple[int, float], str] = {}
        self._by_pid: dict[int, list[float]] = {}
        self.parent_unknown = 0
        self.by_exe: set[tuple[int, float]] = set()             # named `orch_worker` by the exe's name alone (#872)

    def _row(self, k: tuple[int, float], v: tuple) -> dict:
        if k not in self.cmd:
            try:
                self.cmd[k] = tuple(self.reader(k[0]))
            except Exception:
                self.cmd[k] = None
        return {"pid": k[0], "ppid": v[4], "name": v[2], "cmdline": self.cmd[k] or ()}

    def _cached(self, pid: int, born_before: float) -> str | None:
        """Kind remembered for the newest process of `pid` created no later than `born_before`."""
        cs = [c for c in self._by_pid.get(pid, ()) if c <= born_before]
        return self.kinds[(pid, max(cs))] if cs else None

    def _remember(self, k: tuple[int, float], kind: str) -> None:
        if k not in self.kinds:
            self._by_pid.setdefault(k[0], []).append(k[1])
        self.kinds[k] = kind

    def name(self, k: tuple[int, float], cur: dict) -> tuple[str, str]:
        """(exe name, kind) of the new process k present in snapshot `cur`."""
        chain = [self._row(k, cur[k])]
        keys = [k]
        broken = False
        seen = {k[0]}
        child = k
        inherited = None
        while True:
            pp = cur[child][4]
            if pp in (0, 4) or pp in seen:
                break
            par = next((kk for kk in cur if kk[0] == pp and kk[1] <= child[1]), None)
            if par is None:
                broken = True
                if child == k:
                    self.parent_unknown += 1
                inherited = self._cached(pp, child[1])
                break
            seen.add(pp)
            chain.append(self._row(par, cur[par]))
            keys.append(par)
            child = par
        kind = kind_of(chain, broken, os.getpid())
        unreadable = any(self.cmd.get(kk) is None for kk in keys)
        if kind not in NAMED and (broken or unreadable):
            if inherited is None:               # an alive ancestor remembered from an earlier poll
                inherited = next((self.kinds[kk] for kk in keys[1:] if kk in self.kinds), None)
            if inherited is not None and inherited != "unresolved":
                kind = inherited
            elif cur[k][2].lower() == "claude.exe":
                # #872 fallback only: `claude.exe` is an agent session by what it is (no PoB job, test suite or other app
                # runs under that name); every other exe (gh, where, powershell) says nothing about whose it is
                kind = "orch_worker"
                self.by_exe.add(k)
            else:
                kind = "unresolved"
        self._remember(k, kind)
        return cur[k][2], kind


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--window", type=float, default=60.0)
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    end = time.time() + a.minutes * 60
    with open(a.out, "a", encoding="utf-8") as f:
        f.write(json.dumps({"owner": "probe_busy_872c", "pid": os.getpid(), "ticket": 872,
                            "ends": time.strftime("%H:%M:%S", time.localtime(end))}) + "\n"); f.flush()
        t0 = time.time(); p0 = pb.perf_info(); s0 = read_all(); last = s0; inc = 0.0; polls = 0; poll_cost = 0.0
        w_end = t0 + a.window
        seen = set(s0); tracked: dict = {}; records: list[dict] = []; tr = Tracker(); run_t0 = t0
        while time.time() + a.poll <= end + 1:
            time.sleep(a.poll)
            c0 = time.perf_counter(); cur = read_all(); poll_cost += time.perf_counter() - c0; polls += 1
            for k, v in cur.items():
                if k[0] == 0:
                    continue
                inc += max(0.0, v[0] - (last[k][0] if k in last else 0.0))
            last = cur
            for k in [k for k in tracked if k not in cur]:      # born and dead inside the window
                records.append(tracked.pop(k))
            for k, v in cur.items():
                if k not in seen:
                    seen.add(k)
                    if k[0]:
                        nm, kd = tr.name(k, cur)
                        tracked[k] = {"name": nm, "kind": kd, "cpu_s": v[0], "by_exe": k in tr.by_exe}
                elif k in tracked:
                    tracked[k]["cpu_s"] = cur[k][0]
            if time.time() >= w_end:
                t1 = time.time(); p1 = pb.perf_info(); w = t1 - t0
                pd = {k: p1[k] - p0[k] for k in p0}
                D = (pd["kernel"] + pd["user"] - pd["idle"]) / w
                C2 = sum(max(0.0, v[0] - s0[k][0]) for k, v in cur.items() if k in s0 and k[0]) / w
                CT = sum(max(0.0, v[1] - s0[k][1]) for k, v in cur.items() if k in s0 and k[0]) / w
                idle = sum(max(0.0, v[0] - s0[k][0]) for k, v in cur.items() if k in s0 and k[0] == 0) / w
                top = sorted(((v[0] - s0[k][0]) / w, v[2]) for k, v in cur.items() if k in s0 and k[0])[-3:]
                f.write(json.dumps({"window_s": round(w, 1), "D": round(D, 3), "C2_proc_ends": round(C2, 3),
                                    "CT_thread_ends": round(CT, 3), "C1_poll": round(inc / w, 3),
                                    "D-C2": round(D - C2, 3), "D-CT": round(D - CT, 3), "D-C1": round(D - inc / w, 3),
                                    "idle_proc_cores": round(idle, 2), "polls": polls,
                                    "poll_read_cores": round(poll_cost / w, 3), "nproc": len(cur),
                                    "top3": [[round(x, 2), n] for x, n in top]}) + "\n"); f.flush()
                tracked.clear()                                  # still alive at the window end: not short-lived
                t0, p0, s0, inc, polls, poll_cost = t1, p1, cur, 0.0, 0, 0.0
                w_end = t1 + a.window
        el = time.time() - run_t0
        summ = summarize(records, el)
        summ["parent_unknown_at_birth"] = tr.parent_unknown
        f.write(json.dumps({"short_lived_table": summ, "elapsed_s": round(el, 1)}) + "\n")
        text = format_table(summ) + f"\nparent already dead at first sight: {tr.parent_unknown}"
        f.write(text + "\n"); f.flush()
        print(text)


if __name__ == "__main__":
    main()
