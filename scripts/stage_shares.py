"""Median share of each build step / group in a benchmark folder's total stage seconds (#711).

    python scripts/stage_shares.py <benchmark dir> [--out FILE]

Reads rows/*.json (the per-build `stages` list), no PoB. A step's share is per build (its seconds over that build's
total stage seconds); the median is over the builds that ran the step. Unmapped names are counted in the total.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.stage_catalog import CONDITIONS, GROUPS, STEPS, group_of, step_of  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

UNMAPPED = "unmapped"


def shares(rows: list[list[dict]]) -> dict:
    step_shares: dict[str, list[float]] = {}
    group_shares: dict[str, list[float]] = {g: [] for g in GROUPS}
    step_secs: dict[str, list[float]] = {}
    unmapped: set[str] = set()
    used = 0
    for stages in rows:
        total = sum(float(s.get("seconds") or 0) for s in stages)
        if total <= 0:
            continue
        used += 1
        per_step: dict[str, float] = {}
        per_group: dict[str, float] = {g: 0.0 for g in GROUPS}
        for s in stages:
            name, sec = s.get("name", ""), float(s.get("seconds") or 0)
            step = step_of(name)
            if step is None:
                unmapped.add(name)
                per_step[UNMAPPED] = per_step.get(UNMAPPED, 0.0) + sec
                continue
            per_step[step.name] = per_step.get(step.name, 0.0) + sec
            per_group[group_of(name)] += sec
        for k, v in per_step.items():
            step_shares.setdefault(k, []).append(v / total)
            step_secs.setdefault(k, []).append(v)
        for g, v in per_group.items():
            group_shares[g].append(v / total)
    return {
        "builds": used,
        "groups": {g: statistics.median(v) if v else 0.0 for g, v in group_shares.items()},
        "steps": {k: {"median_share": statistics.median(v), "builds": len(v),
                      "median_seconds": statistics.median(step_secs[k])} for k, v in step_shares.items()},
        "unmapped": sorted(unmapped),
        # #720: one boolean per step, true = it runs only under a condition (stage_catalog.CONDITIONS)
        "conditional": {**{s.name: s.name in CONDITIONS for s in STEPS},
                        **{k: True for k in CONDITIONS if k.startswith("move: ")}},
    }


def load_rows(folder: Path) -> list[list[dict]]:
    out = []
    for p in sorted((folder / "rows").glob("*.json")):
        stages = json.loads(p.read_text(encoding="utf-8")).get("stages")
        if stages:
            out.append(stages)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res = {"source": a.folder, **shares(load_rows(Path(a.folder)))}
    print(f"{a.folder}: {res['builds']} builds")
    for g, v in res["groups"].items():
        print(f"  group {g:<18} {v * 100:5.1f} %")
    for k, v in res["steps"].items():
        print(f"  {k:<42} {v['median_share'] * 100:5.1f} %  median {human_duration(v['median_seconds']):>9}"
              f"  builds {v['builds']}")
    print("  unmapped:", ", ".join(res["unmapped"]) or "none")
    if a.out:
        res["steps"] = {k: {"median_share": v["median_share"], "builds": v["builds"]}
                        for k, v in res["steps"].items()}
        Path(a.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
