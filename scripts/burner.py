"""Start N burners (CPU-only processes at BELOW_NORMAL) for S seconds and wait for them (#842).

    python scripts/burner.py --count 12 --seconds 60 [--host pc|laptop]

Exit 2, nothing started, on the PC by day with more than 1 burner. The period can be forced with
JUNKROAN_FORCE_PERIOD=day|night (tests).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.burner import BurnerRefused, start_burners  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--host", choices=["pc", "laptop"], default=None)
    args = ap.parse_args(argv)
    try:
        b = start_burners(args.count, args.seconds, host=args.host)
    except BurnerRefused as e:
        print(str(e), file=sys.stderr)
        return 2
    with b:
        b.wait(args.seconds + 5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
