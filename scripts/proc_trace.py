"""Catch who starts a short-lived console process (#396). Opens no window itself: psutil only, no subprocess.

    pythonw.exe scripts/proc_trace.py --minutes 30 --out artifacts/proc_trace/run.jsonl
    python scripts/proc_trace.py --summary artifacts/proc_trace/run.jsonl

Every pid that is NOT in the first snapshot and whose exe name is in `names` is written once as a JSON
line with its parent chain. The chain is read from the same snapshot plus a cache of rows seen earlier
(a parent may already be gone). Under pythonw.exe there is no stdout: nothing is printed, errors go to
`<out>.err`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.report_format import human_duration  # noqa: E402

DEFAULT_NAMES = ("powershell.exe", "pwsh.exe", "cmd.exe", "conhost.exe", "wscript.exe", "cscript.exe")
MAX_CHAIN = 12


def _iso(epoch: float | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch).isoformat(timespec="milliseconds")


def psutil_table() -> list[dict]:
    import psutil

    rows = []
    for p in psutil.process_iter():
        try:
            with p.oneshot():
                row = {"pid": p.pid, "ppid": p.ppid(), "name": p.name(), "cmdline": None, "create_time": None}
                for key, getter in (("cmdline", p.cmdline), ("create_time", p.create_time)):
                    try:
                        row[key] = getter()
                    except Exception:
                        pass
        except Exception:
            continue
        rows.append(row)
    return rows


def _cmd(row: dict) -> str:
    c = row.get("cmdline")
    return " ".join(c) if isinstance(c, (list, tuple)) else (c or "")


def _chain(row: dict, by_pid: dict[int, dict], cache: dict[int, dict]) -> list[dict]:
    chain = []
    cur = row
    seen = set()
    while cur is not None and len(chain) < MAX_CHAIN:
        chain.append({"pid": cur["pid"], "name": cur.get("name"), "cmdline": _cmd(cur)[:200]})
        seen.add(cur["pid"])
        ppid = cur.get("ppid")
        if ppid in (None, 0, 4) or ppid in seen:
            break
        parent = by_pid.get(ppid) or cache.get(ppid)
        # a reused pid: the parent must be older than the child
        ct = cur.get("create_time")
        pct = parent.get("create_time") if parent else None
        if parent is not None and ct is not None and pct is not None and pct > ct:
            parent = None
        cur = parent
    return chain


def record(minutes, out_path, names=DEFAULT_NAMES, interval=0.25, table=psutil_table, clock=time.time, sleep=time.sleep) -> int:
    """Poll for `minutes`; return the number of lines written."""
    wanted = {n.lower() for n in names}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    first = {r["pid"] for r in table()}
    cache: OrderedDict[int, dict] = OrderedDict()
    written: set[int] = set()
    count = 0
    end = clock() + minutes * 60
    with open(out_path, "a", encoding="utf-8") as fh:
        while clock() < end:
            sleep(interval)
            now = clock()
            rows = table()
            by_pid = {r["pid"]: r for r in rows}
            for r in rows:
                pid = r["pid"]
                if pid in first or pid in written or (r.get("name") or "").lower() not in wanted:
                    continue
                written.add(pid)
                line = {
                    "ts": _iso(now), "pid": pid, "name": r.get("name"), "create_time": _iso(r.get("create_time")),
                    "cmdline": _cmd(r), "chain": _chain(r, by_pid, cache),
                }
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()
                count += 1
            for r in rows:
                cache[r["pid"]] = r
                cache.move_to_end(r["pid"])
            while len(cache) > 20000:
                cache.popitem(last=False)
    return count


def summarize(jsonl_path, names=DEFAULT_NAMES) -> list[dict]:
    wanted = {n.lower() for n in names}
    recs = [json.loads(l) for l in Path(jsonl_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not recs:
        return []
    stamps = [datetime.fromisoformat(r["ts"]) for r in recs]
    hours = max((max(stamps) - min(stamps)).total_seconds(), 60.0) / 3600
    groups: dict[tuple[str, str], dict] = {}
    for r, ts in zip(recs, stamps):
        starter = "(unknown)"
        for e in r.get("chain", []):
            if (e.get("name") or "").lower() not in wanted:
                starter = f"{e.get('name')} {(e.get('cmdline') or '')[:120]}"
                break
        own = (r.get("cmdline") or "")[:160]
        g = groups.setdefault((starter, own), {"starter": starter, "own": own, "count": 0, "first": ts, "last": ts})
        g["count"] += 1
        g["first"], g["last"] = min(g["first"], ts), max(g["last"], ts)
    rows = [
        {"starter": g["starter"], "own": g["own"], "count": g["count"], "first_ts": g["first"].isoformat(timespec="seconds"),
         "last_ts": g["last"].isoformat(timespec="seconds"), "per_hour": round(g["count"] / hours, 1)}
        for g in groups.values()
    ]
    return sorted(rows, key=lambda x: -x["count"])


def format_table(rows: list[dict]) -> str:
    out = ["| starter | own command | count | first | last | per hour |", "|---|---|---|---|---|---|"]
    for r in rows:
        starter, own = r["starter"].replace("|", "\\|"), r["own"].replace("|", "\\|")
        out.append(f"| {starter} | {own} | {r['count']} | {r['first_ts']} | {r['last_ts']} | {r['per_hour']:.1f} |")
    return "\n".join(out)


def _say(text: str) -> None:
    if sys.stdout is not None:
        print(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--out")
    ap.add_argument("--summary")
    ap.add_argument("--interval", type=float, default=0.25)
    a = ap.parse_args(argv)
    if a.summary:
        _say(format_table(summarize(a.summary)))
        return 0
    if not a.out:
        ap.error("--out is required")
    out = Path(a.out)
    try:
        _say(f"recording for {human_duration(a.minutes * 60)} into {out}")
        n = record(a.minutes, out, interval=a.interval)
        _say(f"done: {n} lines")
    except Exception:
        out.parent.mkdir(parents=True, exist_ok=True)
        Path(str(out) + ".err").write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
