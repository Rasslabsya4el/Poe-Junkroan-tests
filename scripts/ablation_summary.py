"""Summarize the stage ablation: every variant's per-seed ratio and median per reference, from the
benchmark reports (artifacts/benchmark/<stamp>-ablation[-no-<stage>]/report.md). Builds that only miss
the movement floor by the loot's 1% (the audit's "EffectiveMovementSpeedMod = 1.190 < 1.2") count.

    python scripts/ablation_summary.py [--since 20260914-2133]
"""

from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| (?P<slug>[a-z_]+) s(?P<seed>\d)(?P<flag> \(infeasible, not counted\))? \| [^|]*\| [^|]*\| (?P<ours>[\d,]+) \| (?P<ratio>\d+)% \|")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20260914-2133")
    args = ap.parse_args()
    runs = sorted(p for p in (ROOT / "artifacts" / "benchmark").glob("*-ablation*") if p.name >= args.since and "aborted" not in p.name and (p / "report.md").is_file())
    table: dict[str, dict[str, dict[int, tuple[int, float, bool]]]] = {}  # variant -> slug -> seed -> (ours, ratio, counted)
    for run in runs:
        variant = run.name.split("-ablation", 1)[1].lstrip("-") or "baseline"
        variant = variant.replace("no-", "no ") if variant else "baseline"
        for line in (run / "report.md").read_text(encoding="utf-8").splitlines():
            m = ROW.match(line)
            if m:
                table.setdefault(variant, {}).setdefault(m["slug"], {})[int(m["seed"])] = (int(m["ours"].replace(",", "")), float(m["ratio"]), not m["flag"])
    slugs = sorted({s for v in table.values() for s in v})
    variants = ["baseline"] + [v for v in table if v != "baseline"]
    print("| variant | " + " | ".join(f"{s} s1/s2/s3 -> median" for s in slugs) + " | median of medians |")
    print("|---|" + "---|" * (len(slugs) + 1))
    base_med: dict[str, float] = {}
    for v in variants:
        if v not in table:
            continue
        cells = []
        meds = []
        for s in slugs:
            seeds = table[v].get(s, {})
            vals = [seeds[k][1] for k in sorted(seeds)]
            med = statistics.median(vals) if vals else float("nan")
            meds.append(med)
            if v == "baseline":
                base_med[s] = med
            delta = f" ({med - base_med[s]:+.0f})" if v != "baseline" and s in base_med else ""
            cells.append("/".join(f"{seeds[k][1]:.0f}{'' if seeds[k][2] else '*'}" for k in sorted(seeds)) + f" -> {med:.0f}%{delta}")
        mm = statistics.median(meds) if meds else float("nan")
        print(f"| {v} | " + " | ".join(cells) + f" | {mm:.0f}% |")
    print("\n* = not counted by the benchmark (a floor missed; here the loot's 1% on movement speed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
