"""#724 unit 1b: measure PoB call times of one replay, idle or beside two loader jobs. No behaviour change.

Cases: jewel-idle, kick-joint-idle, jewel-busy, kick-joint-busy. The `-busy` cases start two loader replays
(`--move loop`, 1 worker each), wait LOAD_WAIT seconds, run the measured replay (1 worker) in the foreground with
JUNKROAN_POB_CALL_LOG / JUNKROAN_POB_CALL_LOG_ALL set, then kill the loader process trees it started. Hard cap of
40 minutes on the whole driver. Prints the call-log path last.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDS = "artifacts/benchmark/20261009-1054-P1-#600"
OUT = "artifacts/m724"
CAP_SECONDS = 40 * 60
LOAD_WAIT = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# case -> (move, measured build, two loader builds)
CASES = {
    "jewel": ("jewel", "burning_arrow_snipe-s1", ("cold_dot-s1", "stormbrand-s1")),
    "kick-joint": ("kick-joint", "winter_orb-s1", ("cold_dot-s1", "stormbrand-s1")),
}


def _build(name: str) -> str:
    return f"{BUILDS}/{name}.pob.txt"


def plan(case: str) -> dict:
    base, _, mode = case.rpartition("-")
    if base not in CASES or mode not in ("idle", "busy"):
        raise SystemExit(f"unknown case {case!r}; one of " + ", ".join(f"{b}-{m}" for b in CASES for m in ("idle", "busy")))
    move, build, loaders = CASES[base]
    py = sys.executable
    measured = [py, "scripts/replay_bench.py", "--builds", glob.escape(_build(build)), "--move", move,
                "--workers", "1", "--seed", "1", "--tag", f"m724-{case}", "--record-calls", f"{OUT}/{case}-rec"]
    loader_cmds = []
    if mode == "busy":
        for i, name in enumerate(loaders, 1):
            loader_cmds.append([py, "scripts/replay_bench.py", "--builds", glob.escape(_build(name)), "--move", "loop",
                                "--passes", "5", "--workers", "1", "--seed", "1", "--tag", f"m724-load-{case}-{i}"])
    return {"case": case, "log": f"{OUT}/{case}-calls.jsonl", "measured": measured, "loaders": loader_cmds}


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)


def run(case: str) -> int:
    p = plan(case)
    start = time.monotonic()
    (ROOT / OUT).mkdir(parents=True, exist_ok=True)
    log = ROOT / p["log"]
    log.unlink(missing_ok=True)
    loaders: list[subprocess.Popen] = []
    rc = 1
    try:
        for cmd in p["loaders"]:
            loaders.append(subprocess.Popen(cmd, cwd=ROOT, creationflags=NO_WINDOW))
            print("loader started pid", loaders[-1].pid, flush=True)
        if loaders:
            time.sleep(LOAD_WAIT)
            alive = sum(1 for lp in loaders if lp.poll() is None)
            print(f"loaders alive after {LOAD_WAIT}s: {alive}/{len(loaders)}", flush=True)
        env = dict(os.environ, JUNKROAN_POB_CALL_LOG=str(log), JUNKROAN_POB_CALL_LOG_ALL="1")
        t0 = time.monotonic()
        meas = subprocess.Popen(p["measured"], cwd=ROOT, env=env, creationflags=NO_WINDOW)
        try:
            rc = meas.wait(timeout=max(1, CAP_SECONDS - (time.monotonic() - start)))
        except subprocess.TimeoutExpired:
            _kill_tree(meas)
            print("HARD CAP: measured replay killed at 40 min", flush=True)
            rc = 124
        print(f"measured replay rc {rc} wall {time.monotonic() - t0:.0f}s", flush=True)
        for lp in loaders:
            print(f"loader pid {lp.pid} still running at end: {lp.poll() is None}", flush=True)
    finally:
        for lp in loaders:
            _kill_tree(lp)
    print("call log:", log, flush=True)
    _summary(log)
    return rc


def _summary(log: Path) -> None:
    """The out file outlives the snapshot (its artifacts are removed with it), so the numbers are printed here."""
    import json
    rows = []
    try:
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except OSError as exc:
        print("no call log:", exc, flush=True)
        return
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["call"], []).append(r)
    print("| call | n | max trials | limit s | max elapsed s | n over 50% of limit |", flush=True)
    print("|---|---|---|---|---|---|", flush=True)
    for call, rs in sorted(by.items()):
        trials = max((r["trials"] or 0) for r in rs)
        limit = max(r["limit"] for r in rs)
        over = sum(1 for r in rs if r["limit"] and r["elapsed"] / r["limit"] > 0.5)
        print(f"| {call} | {len(rs)} | {trials} | {limit:g} | {max(r['elapsed'] for r in rs):.2f} | {over} |", flush=True)
    print("slowest 8:", flush=True)
    for r in sorted(rows, key=lambda r: -r["elapsed"])[:8]:
        print(f"  {r['call']} trials={r.get('trials')} limit={r['limit']:g} elapsed={r['elapsed']:.2f}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, help="jewel-idle | kick-joint-idle | jewel-busy | kick-joint-busy")
    ap.add_argument("--dry", action="store_true", help="print the plan, start nothing")
    args = ap.parse_args(argv)
    if args.dry:
        p = plan(args.case)
        print("log:", p["log"])
        for c in p["loaders"]:
            print("loader:", " ".join(c))
        print("measured:", " ".join(p["measured"]))
        return 0
    return run(args.case)


if __name__ == "__main__":
    sys.exit(main())
