"""#724 unit 1b: markdown table of PoB call-log files (JUNKROAN_POB_CALL_LOG lines).

    python scripts/measure_724_table.py artifacts/m724/jewel-idle-calls.jsonl ...

The case is the file name up to `-calls`. Columns: case, call, trials, limit, elapsed, share of limit.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def render(paths: list[Path]) -> str:
    rows = ["| case | call | trials | limit s | elapsed s | share of limit |", "|---|---|---|---|---|---|"]
    for path in paths:
        case = path.name.split("-calls")[0]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            share = r["elapsed"] / r["limit"] * 100 if r["limit"] else float("nan")
            trials = "-" if r.get("trials") is None else str(r["trials"])
            rows.append(f"| {case} | {r['call']} | {trials} | {r['limit']:g} | {r['elapsed']:.2f} | {share:.1f}% |")
    return "\n".join(rows)


def selftest() -> int:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "jewel-idle-calls.jsonl"
        f.write_text(
            json.dumps({"ts": 1.0, "call": "trial_stats", "trials": 3, "limit": 10.0, "elapsed": 2.5, "pid": 1}) + "\n"
            + json.dumps({"ts": 2.0, "call": "load", "trials": None, "limit": 60.0, "elapsed": 6.0, "pid": 1}) + "\n",
            encoding="utf-8")
        out = render([f])
    assert "| jewel-idle | trial_stats | 3 | 10 | 2.50 | 25.0% |" in out, out
    assert "| jewel-idle | load | - | 60 | 6.00 | 10.0% |" in out, out
    print(out)
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="*", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.logs:
        ap.error("give at least one call-log file")
    print(render(args.logs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
