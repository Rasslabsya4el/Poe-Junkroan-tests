"""#870 row 1: each of four tests, N repeats, while 12 CPU burners run (`scripts/burner.py`).

    python scripts/repeat_under_load_870.py --repeats 30 --host laptop

By day the burners run only on the laptop (`burner.py` refuses 12 on the PC by day); the job is submitted through
`runs submit` with `--rc-is-reading`. Prints one line per test (passes of N, failures, slowest run) and
exits 0 only when every test passed every repeat."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from junkroan.report_format import human_duration  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

TESTS = [
    "tests/test_runs_anomalies_tick_bound.py::test_hanging_list_does_not_stall_last_tick_or_trigger_takeover",
    "tests/test_benchmark_yield.py::test_give_up_two_of_three_asks_the_nearly_done_build_then_the_youngest",
    "tests/test_brain_reset_nudge.py::test_311_row2_live_subagents",
    "tests/test_worker_process_guard.py::test_all_22_forms_refused",
]


def temp_root(pid: int) -> Path:
    """This job's own pytest `--basetemp`; its parent is made here because pytest makes the folder itself only when
    the parent exists (a fresh snapshot has no `var/repeat_870`: 0 of 30 green on the laptop, #870)."""
    base = ROOT / "var" / "repeat_870" / str(pid)
    base.parent.mkdir(parents=True, exist_ok=True)
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=30)
    ap.add_argument("--burners", type=int, default=12)
    ap.add_argument("--host", default="laptop", choices=["pc", "laptop"])
    ap.add_argument("--max-minutes", type=int, default=150)
    a = ap.parse_args()
    seconds = a.max_minutes * 60
    burner = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "burner.py"), "--count", str(a.burners),
         "--seconds", str(seconds), "--host", a.host],
        cwd=ROOT, creationflags=NO_WINDOW)
    time.sleep(5)
    if burner.poll() is not None:
        print(f"burner refused or died, rc {burner.returncode}: nothing measured")
        return 2
    t0 = time.time()
    ok_all = True
    try:
        for t in TESTS:
            passes, fails, slowest = 0, 0, 0.0
            for _ in range(a.repeats):
                if time.time() - t0 > seconds - 60:
                    break
                s = time.time()
                # Its own temp root inside the project, one per job (#864): the shared pytest-of-<user> folder of the
                # laptop made every run end rc 1 after "[100%]" (the 0 of 30 of 2026-10-11); pytest itself empties
                # a --basetemp it is given at the start of each run, so this script deletes nothing.
                base = temp_root(os.getpid())
                r = subprocess.run([sys.executable, "-m", "pytest", t, "-q", "-p", "no:faulthandler",
                                    "-p", "no:cacheprovider", "--basetemp", str(base)], cwd=ROOT,
                                   capture_output=True, text=True, creationflags=NO_WINDOW)
                slowest = max(slowest, time.time() - s)
                if r.returncode == 0:
                    passes += 1
                else:
                    fails += 1
                    print(f"FAILED run of {t} (rc {r.returncode}):\n{(r.stdout or '')[-1500:]}\n"
                          f"stderr: {(r.stderr or '')[-1000:]}")
            ok_all &= passes == a.repeats
            print(f"{t.split('::')[1]}: {passes} of {a.repeats} green, {fails} red, "
                  f"slowest run {human_duration(slowest)}")
    finally:
        burner.terminate()
    print(f"all four tests {a.repeats} of {a.repeats} under {a.burners} burners: {ok_all}; "
          f"took {human_duration(time.time() - t0)}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
