"""Plan versus fact for the run queue: one table anyone can read without opening a log.

    python scripts/run_progress.py [--reset "2026-09-17 22:00"] [--build-seconds 5300]

Reads `artifacts/runs/queue.txt` (done / pending lines), `artifacts/runs/queue.log`
(start / end stamps) and the running run's `logs/*.log` (a build is finished when its log
carries "config (final lanes)"; the newest log write is the liveness signal: older than
--stall-minutes = STALLED?). Every run gets its build count from its command (`--set`
through scripts/benchmark.py's SETS, or the listed slugs, x --seeds), the ETA from
--build-seconds per build over --workers (88 min = smoke-frozen's pace on 5 workers), and the
plan's end is compared with the reset time (`--reset`, else artifacts/runs/reset_at.txt).
Numbers only; the limit-handover protocol (docs/ROADMAP.md) has the Opus session post this
every 2 hours and after every run.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts" / "runs"
BENCH = ROOT / "artifacts" / "benchmark"
sys.path.insert(0, str(ROOT / "src"))

from junkroan.report_format import human_duration


def _sets() -> dict[str, list[str]]:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from benchmark import SETS  # type: ignore

        return {k: list(v) for k, v in SETS.items()}
    except Exception:  # noqa: BLE001 - the count falls back to the logs
        return {}


def _builds(cmd: str, sets: dict[str, list[str]]) -> int | None:
    if "benchmark.py" not in cmd:
        return 0
    seeds = int(m.group(1)) if (m := re.search(r"--seeds (\d+)", cmd)) else 1
    if m := re.search(r"--set (\S+)", cmd):
        refs = sets.get(m.group(1))
        return len(refs) * seeds if refs else None
    slugs = [t for t in cmd.split("benchmark.py", 1)[1].split() if not t.startswith("-") and not t.isdigit() and t not in {"smoke", "core14", "new18", "ziz"}]
    # the tokens after a flag that takes a value are not slugs
    flagged = set()
    toks = cmd.split()
    for i, t in enumerate(toks):
        if t in {"--seeds", "--seed", "--workers", "--loop-seconds", "--tag", "--set", "--tree-depth", "--tree-trials", "--stat", "--ablate", "--reopt-rounds"} and i + 1 < len(toks):
            flagged.add(toks[i + 1])
    slugs = [s for s in slugs if s not in flagged]
    return len(slugs) * seeds


def _workers(cmd: str) -> int:
    return int(m.group(1)) if (m := re.search(r"--workers (\d+)", cmd)) else 5


def _tag(cmd: str) -> str:
    return m.group(1) if (m := re.search(r"--tag (\S+)", cmd)) else (cmd.split("scripts/", 1)[1].split()[0] if "scripts/" in cmd else cmd[:30])


def _log_events() -> dict[str, dict[str, str]]:
    events: dict[str, dict[str, str]] = {}
    path = RUNS / "queue.log"
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"(\S+ \S+) (start|end) (\S+): (.*)", line)
        if not m:
            continue
        when, kind, name, rest = m.groups()
        events.setdefault(name, {})[kind] = when
        if kind == "end" and (rc := re.search(r"rc (\d+)", rest)):
            events[name]["rc"] = rc.group(1)
    return events


def _running_state(name: str, stall_minutes: float) -> tuple[int, int, str, str]:
    """(builds finished, logs present, newest log write, liveness) of a running run."""

    logs = sorted((BENCH / name / "logs").glob("*.log")) if (BENCH / name / "logs").is_dir() else []
    done = sum(1 for f in logs if "config (final lanes)" in f.read_text(encoding="utf-8", errors="replace"))
    newest = max((f.stat().st_mtime for f in logs), default=0.0)
    if not logs:
        return 0, 0, "-", "starting"
    age = (time.time() - newest) / 60.0
    return done, len(logs), datetime.fromtimestamp(newest).strftime("%H:%M"), ("alive" if age < stall_minutes else f"STALLED? ({human_duration(age * 60)} silent)")


def render(args) -> str:
    reset_text = args.reset or ((RUNS / "reset_at.txt").read_text(encoding="utf-8").strip() if (RUNS / "reset_at.txt").is_file() else "")
    reset = datetime.strptime(reset_text, "%Y-%m-%d %H:%M") if reset_text else None
    now = datetime.now()
    sets = _sets()
    events = _log_events()
    lines = (RUNS / "queue.txt").read_text(encoding="utf-8").splitlines() if (RUNS / "queue.txt").is_file() else []
    rows: list[tuple] = []
    clock = now
    unfinished = [n for n, e in events.items() if "start" in e and "end" not in e]
    running_name = unfinished[-1] if unfinished else None  # the newest start without an end; older ones died with the app
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("done "):
            _, stamp, cmd = line.split(" ", 2)
            name = f"{stamp}-{_tag(cmd)}"
            ev = events.get(name, {})
            builds = _builds(cmd, sets)
            b = builds if builds is not None else "?"
            status = f"done rc {ev['rc']}" if "rc" in ev else ("running" if name == running_name else "aborted (no end in queue.log)")
            rows.append((name, f"{b}/{b}", status, ev.get("start", "")[11:16], ev.get("end", "")[11:16], ""))
            continue
        cmd = line
        builds = _builds(cmd, sets)
        planned_seconds = (builds or 0) * args.build_seconds / _workers(cmd) if builds else 0.0
        rows.append((_tag(cmd), f"0/{builds if builds is not None else '?'}", "queued", "", "", planned_seconds))
    # the running run: its queue line is already "done <stamp>" (the runner marks a line when it starts it)
    out: list[str] = []
    if reset:
        out.append(f"now {now:%a %H:%M}; reset {reset:%a %Y-%m-%d %H:%M} (in {human_duration((reset - now).total_seconds())})")
    else:
        out.append(f"now {now:%a %H:%M}; reset time not set (artifacts/runs/reset_at.txt or --reset)")
    out.append("| run | builds | status | started | ended / ETA | plan time |")
    out.append("|---|---|---|---|---|---|")
    for name, builds, status, started, ended, planned_seconds in rows:
        if running_name and name == running_name:
            done, present, newest, live = _running_state(name, args.stall_minutes)
            total = builds.split("/")[1]
            wk = _workers(next((l for l in lines if l.startswith("done ") and name.endswith("-" + _tag(l.split(" ", 2)[2]))), ""))
            start_dt = datetime.strptime(events[name]["start"], "%Y-%m-%d %H:%M:%S")
            total_n = int(total) if total.isdigit() else present
            eta = start_dt + timedelta(seconds=total_n * args.build_seconds / wk)
            clock = max(clock, eta)
            out.append(f"| {name} | {done}/{total} ({present} started) | RUNNING, {live}, last log {newest} | {started} | ETA ~{eta:%H:%M} | |")
        elif status == "queued":
            start_at = clock
            clock = clock + timedelta(seconds=planned_seconds)
            out.append(f"| {name} | {builds} | queued | ~{start_at:%a %H:%M} | ETA ~{clock:%a %H:%M} | {human_duration(planned_seconds)} |")
        else:
            out.append(f"| {name} | {builds} | {status} | {started} | {ended} | |")
    if reset:
        slack = (clock - reset).total_seconds()
        out.append(f"plan ends ~{clock:%a %H:%M}: {'covers the reset by ' + human_duration(slack) if slack >= 0 else 'SHORT of the reset by ' + human_duration(-slack) + ': queue more (handover rule 5)'}")
    else:
        out.append(f"plan ends ~{clock:%a %H:%M}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reset", help='when the main model\'s limit resets, "YYYY-MM-DD HH:MM" (default: artifacts/runs/reset_at.txt)')
    ap.add_argument("--build-seconds", type=float, default=5300.0, help="per-build duration for the ETA (the flag value is seconds)")
    ap.add_argument("--stall-minutes", type=float, default=20.0, help="a running run whose newest log is older than this is flagged")
    ap.add_argument("--every", type=float, default=0.0, help="seconds: keep rewriting --out with a fresh table (a detached heartbeat no chat session has to wake for)")
    ap.add_argument("--out", default=str(RUNS / "progress.md"), help="the file --every rewrites")
    args = ap.parse_args()
    if args.every <= 0:
        print(render(args))
        return 0
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # a console Ctrl+C killed the heartbeat twice (see run_queue.py)
    while True:
        try:
            Path(args.out).write_text(render(args) + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - a heartbeat never dies on one bad read
            Path(args.out).write_text(f"now {datetime.now():%a %H:%M}: progress table failed: {exc!r}\n", encoding="utf-8")
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
