"""What is running on this machine right now, and whether a planned PoB launch fits the budget.

    python scripts/machine_load.py                     # the whole picture, under 3 s, no PoB
    python scripts/machine_load.py --need 2 --role other   # one verdict line; exit 0 = GO, 3 = WAIT

The budget itself lives in the SHARED `var/machine_budget.json` and is enforced inside
`PobSession` by `src/junkroan/pob/slot_budget.py`; this script only reads it. Run it BEFORE
launching anything that starts PoB sessions (a benchmark, a search, a whole pytest suite): the
owner works on this machine by day, and five jobs that do not know of each other put 13 worker
slots on 12 cores (incident 2026-09-20 07:10).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob import slot_budget  # noqa: E402

# One process family per line of the report, matched against the whole command line, lower-cased.
PROCESS_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("queue runner", ("run_queue.py",)),
    ("gpt worker / opencode", ("tools.agentops worker", "tools.agentops research", "opencode")),
    ("pytest", ("pytest",)),
    ("bench / benchmark / transplant", ("benchmark.py", "replay_bench.py", "gear_transplant.py", "search.py", "build_from_skeleton.py")),
    ("PoB runtime workers", ("headless_runtime_worker",)),
)


def _age(seconds: float) -> str:
    seconds = int(max(0.0, seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def cpu_percent() -> float | None:
    try:
        import psutil

        return float(psutil.cpu_percent(interval=1.0))
    except Exception:
        return None


def cpu_count() -> int | None:
    try:
        import psutil

        return int(psutil.cpu_count(logical=True) or 0) or None
    except Exception:
        return None


#: The `agentops full-run` tree's cpu % read in the same window as the last `cpu_shares()` call (#735);
#: None when no full run process exists or the grouping failed. A side channel so `cpu_shares` keeps its
#: 2-tuple for its other callers (`tools/agentops/suite_router.py`).
last_full_run_cpu: float | None = None


def cpu_shares() -> tuple[float | None, float | None]:
    """(total cpu %, cpu % of the runs daemon's PoB workers) from ONE per-process window, grouped by
    `junkroan.runs.load_groups` (#715); the share is None when the grouping fails. The same window also
    fills `last_full_run_cpu` (#735)."""

    global last_full_run_cpu
    last_full_run_cpu = None

    try:
        import psutil
        from junkroan.runs import load_groups

        psutil.cpu_percent(interval=None)  # prime: the reading below is the load since this call
        box: dict = {}
        pob = load_groups.pob_cpu_pct(full_run_out=box)  # #728: sleeps _PRIME_S inside, reads only the job and full-run trees
        last_full_run_cpu = box.get("cpu_pct")
        return round(float(psutil.cpu_percent(interval=None)), 1), pob
    except Exception:
        return cpu_percent(), None


#: Set by `agentops full-run` for its own probes (#775): the daemon steps PoB down only for a merge suite.
POB_NOT_STEPPED_DOWN_ENV = "JUNKROAN_POB_NOT_STEPPED_DOWN"


def suite_workers_line(budget: slot_budget.Budget) -> str:
    """The #684 probe line: the formula in `slot_budget` over one CPU and one RAM reading."""

    cores = cpu_count() or os.cpu_count() or 1
    try:
        free_ram: float | None = slot_budget.available_ram_gb()
    except Exception:
        free_ram = None
    total, pob = cpu_shares()
    _, line = slot_budget.suite_workers_from_readings(
        cores, total, free_ram, budget.merge_suite_reserve_gb, slot_budget.SUITE_PER_WORKER_GB,
        budget.limit_for(slot_budget.ROLE_MERGE_SUITE), pob, last_full_run_cpu,
        pob_stepped_down=not os.environ.get(POB_NOT_STEPPED_DOWN_ENV),
        floor_gb=budget.min_free_ram_gb)  # #966: the run queue's floor, the setting the runs daemon reads
    return line


def process_counts() -> dict[str, int] | None:
    """One count per process family, from the full command lines (psutil only)."""

    try:
        import psutil
    except Exception:
        return None
    counts = {label: 0 for label, _ in PROCESS_KINDS}
    for process in psutil.process_iter(["cmdline"]):
        try:
            line = " ".join(process.info.get("cmdline") or ()).lower()
        except Exception:
            continue
        if not line:
            continue
        for label, needles in PROCESS_KINDS:
            if any(needle in line for needle in needles):
                counts[label] += 1
    return counts


def report(budget: slot_budget.Budget, folder: Path) -> None:
    now = datetime.now()
    print(f"now      {now:%Y-%m-%d %H:%M:%S}  ({budget.period}, {budget.window()})")
    source = budget.source if budget.source is not None else "defaults"
    print(f"budget   total {budget.total}, others {budget.others}, min free RAM {budget.min_free_ram_gb:g} GB   ({source})")
    print(f"role     {slot_budget.current_role()}   (from {slot_budget.role_source()}: a run-queue ancestor makes a process 'queue')")
    cores, cpu = cpu_count(), cpu_percent()
    print(f"cpu      {'n/a' if cpu is None else f'{cpu:.1f}%'} over 1 s" + (f" ({cores} logical cores)" if cores else ""))
    free_ram, total_ram = slot_budget.available_ram_gb(), slot_budget.total_ram_gb()
    print(f"ram      {free_ram:.1f} GB free" + (f" of {total_ram:.1f} GB" if total_ram else ""))

    used = slot_budget.busy_slots(folder, budget=budget)
    reserved = max(0, budget.total - budget.limit_for(slot_budget.ROLE_OTHER))
    print(f"slots    {len(used)} of {budget.total} in use   (slots 1-{budget.limit_for(slot_budget.ROLE_OTHER)} open to everyone, {reserved} reserved for the queue)")
    print(f"         {folder}")
    for row in used:  # the role and priority are what the holder itself derived, written into its lock file
        print(
            f"  #{row['slot']:<3} pid {row['pid']:<8} {row['role']:<6} {row.get('priority', slot_budget.PRIORITY_DEFAULT):<3} "
            f"{_age(row['age_seconds']):>9}  {row['cmd']}"
        )
    if not used:
        print("  (none)")

    waiters = slot_budget.waiting(folder)
    print(f"waiting  {len(waiters)}")
    for row in waiters:
        print(
            f"  pid {row['pid']:<8} {row['role']:<6} {row.get('priority', slot_budget.PRIORITY_DEFAULT):<3} "
            f"{_age(row['age_seconds']):>9}  {row['reason']}"
        )

    counts = process_counts()
    print("processes")
    if counts is None:
        print("  (psutil not installed: no per-role process counts)")
    else:
        width = max(len(label) for label in counts)
        for label, count in counts.items():
            print(f"  {label:<{width}}  {count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--need", type=int, help="how many PoB sessions the planned launch will hold at once")
    parser.add_argument("--role", default=slot_budget.ROLE_OTHER, choices=[slot_budget.ROLE_QUEUE, slot_budget.ROLE_OTHER, slot_budget.ROLE_MERGE_SUITE],
                        help="the role that launch will run as (default: other)")
    parser.add_argument("--suite-workers", action="store_true",
                        help="print the merge suite's pytest worker count line (workers N: ...) from one cpu and one RAM reading")
    parser.add_argument("--quiet", action="store_true", help="with --need: print the verdict line only")
    args = parser.parse_args(argv)

    folder = slot_budget.slot_dir()
    budget = slot_budget.load_budget()
    if args.suite_workers:
        print(suite_workers_line(budget))
        return 0
    if args.need is None:
        report(budget, folder)
        return 0
    if not args.quiet:
        report(budget, folder)
        print()
    go, line = slot_budget.verdict(args.need, args.role, directory=folder, budget=budget)
    print(line)
    return 0 if go else 3


if __name__ == "__main__":
    raise SystemExit(main())
