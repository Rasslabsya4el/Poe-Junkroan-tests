"""Append one load snapshot (groups of processes, CPU, RAM) per interval to a jsonl file (issue #406)."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import load_groups  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--count", type=int, default=None, help="stop after N lines (default: forever)")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "runs" / "load_samples.jsonl"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prev = None
    n = 0
    while args.count is None or n < args.count:
        started = time.monotonic()
        try:
            snap = load_groups.snapshot(prev=prev)
            prev = snap
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(load_groups.public(snap)) + "\n")
                f.flush()
        except Exception as exc:  # a vanished process must not end the sampler
            print(f"sample failed: {exc!r}", file=sys.stderr)
        n += 1
        if args.count is None or n < args.count:
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
