"""#839 desktop-latency rig: do burners at BELOW_NORMAL hurt a Normal process's 10 ms sleeps less than at Normal?

Starts N burner processes at a chosen priority class, runs a probe at Normal priority (2000 x sleep 10 ms by
default) and prints one line:  RIG839 burners=<n> priority=<p> p99_ms=<x> median_ms=<y> max_ms=<z>
Refuses (exit 2) more than 1 burner on the PC between 08:00 and 01:00 local; there is no override.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0  # the tiny real run uses it
SLEEP_S = 0.010


def refuse_reason(host: str, hour: int, burners: int) -> str | None:
    """A reason not to start, or None; the rule is the shared one (junkroan.burner.refusal), hour 8..23 or 0 = day."""
    from junkroan.burner import refusal

    return refusal(host, "day" if (hour >= 8 or hour < 1) else "night", burners)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, q in 0..100."""
    if not values:
        raise ValueError("no values")
    s = sorted(values)
    rank = max(1, -(-len(s) * q // 100))  # ceil
    return s[int(rank) - 1]


def probe(samples: int, deadline: float) -> list[float]:
    over = []
    for _ in range(samples):
        if time.time() > deadline:
            break
        t = time.perf_counter()
        time.sleep(SLEEP_S)
        over.append((time.perf_counter() - t - SLEEP_S) * 1000.0)
    return over


def run_one(burners: int, priority: str, samples: int, deadline: float) -> str:
    from junkroan.burner import start_burners

    with start_burners(burners, seconds=max(5.0, deadline - time.time() + 5), priority=priority):
        time.sleep(1.0)  # let the burners spin up
        over = probe(samples, deadline)
    if not over:
        raise RuntimeError("no samples taken before --max-seconds")
    return (f"RIG839 burners={burners} priority={priority} p99_ms={percentile(over, 99):.2f} "
            f"median_ms={percentile(over, 50):.2f} max_ms={max(over):.2f}")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--burners", type=int, default=12)
    ap.add_argument("--burner-priority", choices=["below_normal", "normal"], default="below_normal")
    ap.add_argument("--both", action="store_true", help="below_normal then normal, two lines")
    ap.add_argument("--samples", type=int, default=2000)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    from junkroan.burner import BurnerRefused

    deadline = time.time() + args.max_seconds
    prios = ["below_normal", "normal"] if args.both else [args.burner_priority]
    try:
        for p in prios:
            print(run_one(args.burners, p, args.samples, deadline), flush=True)
    except BurnerRefused as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
