"""Peak memory of a command's whole process tree (#751 rule 2: laptop RAM per worker).

Usage: python scripts/tree_peak.py [--interval 2] [--out file.json] -- <command...>

Runs the command as a child (no console window on Windows), samples the child and all its
descendants every --interval seconds, sums RSS (the Windows working set), and prints one JSON
line when the command ends. Exit code = the command's exit code.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import psutil

WORKER_MARK = "headless_runtime_worker"


def sample_tree(root: psutil.Process) -> tuple[int, int, int]:
    """(sum RSS bytes, process count, count of PoB workers) over root and its descendants."""
    try:
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return 0, 0, 0
    total = count = workers = 0
    for p in procs:
        try:
            rss = p.memory_info().rss
            cmd = " ".join(p.cmdline())
        except psutil.Error:
            continue
        total += rss
        count += 1
        if WORKER_MARK in cmd:
            workers += 1
    return total, count, workers


def run(command: list[str], interval: float = 2.0) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    t0 = time.monotonic()
    child = subprocess.Popen(command, creationflags=flags)
    root = psutil.Process(child.pid)
    samples = 0
    peak = (0, 0, 0)
    peak_t = 0.0
    max_workers = 0
    while True:
        done = child.poll() is not None
        s = sample_tree(root) if not done else (0, 0, 0)
        if s[1]:
            samples += 1
            max_workers = max(max_workers, s[2])
            if s[0] > peak[0]:
                peak, peak_t = s, time.monotonic() - t0
        if done:
            break
        time.sleep(interval)
    return {
        "command": command,
        "rc": child.returncode,
        "samples": samples,
        "peak_tree_rss_gb": round(peak[0] / 1024**3, 2),
        "peak_at_min": round(peak_t / 60, 2),
        "peak_process_count": peak[1],
        "peak_worker_count": max_workers,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--out")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        ap.error("no command given (python scripts/tree_peak.py [opts] -- <command...>)")
    result = run(cmd, args.interval)
    line = json.dumps(result)
    print(line)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(line + "\n")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
