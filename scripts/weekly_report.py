"""The weekly core run report (#538, condition 5 of #2; `--core` since #578): `python scripts/weekly_report.py --core <run name or folder> [--previous <run name or folder>]`.

Writes `report-weekly.md` into the gate's folder and prints it. Per reference: median of `ratio_lane`
over the clean seeds (compare_runs.py rule: counted_row, which is progress.py clean with a fixed-point-only audit error tolerated), spread, audit errors, fixed-point gain, the previous gate's
median and the delta. It gates nothing: exit 0 always, no PASS / FAIL word (D113).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from compare_runs import _rows, resolve  # noqa: E402
from junkroan.optimizer.benchmark_rows import counted_row  # noqa: E402

from junkroan.report_format import human_duration  # noqa: E402

MIN_CLEAN = 3
STABLE_SPREAD_POINTS = 10.0


def summarize(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for slug in sorted({r["slug"] for r in rows}):
        mine = [r for r in rows if r["slug"] == slug]
        clean = [r for r in mine if r.get("ok") and isinstance(r.get("ratio_lane"), (int, float)) and counted_row(r)]
        points = sorted(round(100.0 * float(r["ratio_lane"]), 1) for r in clean)
        gains = [float(r["fixed_point_gain"]) for r in mine if isinstance(r.get("fixed_point_gain"), (int, float))]
        entry = {"seeds": len(mine), "clean": len(points), "median": None, "spread": None,
                 "audit_errors": sum(int(r.get("audit_errors") or 0) for r in mine),
                 "gain": 100.0 * max(gains) if gains else None, "status": "infeasible"}
        if len(points) >= MIN_CLEAN:
            entry["median"] = statistics.median(points)
            entry["spread"] = points[-1] - points[0]
            if entry["median"] >= 100.0:
                entry["status"] = "stable" if entry["spread"] <= STABLE_SPREAD_POINTS else "covered"
            else:
                entry["status"] = "below author"
        out[slug] = entry
    return out


def totals(summary: dict[str, dict]) -> dict:
    medians = [v["median"] for v in summary.values() if v["median"] is not None]
    return {"total": len(summary),
            "covered": sum(1 for v in summary.values() if v["status"] in ("covered", "stable")),
            "stable": sum(1 for v in summary.values() if v["status"] == "stable"),
            "median": statistics.median(medians) if medians else None}


def wall_clock(folder: Path, rows: list[dict]) -> str:
    started, finished = folder / "args.json", folder / "results.json"
    if started.is_file() and finished.is_file():
        return human_duration(finished.stat().st_mtime - started.stat().st_mtime)
    return f"{human_duration(sum(float(r.get('seconds') or 0.0) for r in rows))} of build time summed over rows (no args.json)"


def _f(v, digits=1, suffix="") -> str:
    return "-" if v is None else f"{v:.{digits}f}{suffix}"


def _d(v) -> str:
    return "-" if v is None else f"{v:+.1f}"


def render(gate: Path, rows: list[dict], previous: Path | None = None, prev_rows: list[dict] | None = None) -> str:
    cur = summarize(rows)
    prev = summarize(prev_rows) if prev_rows is not None else None
    lines = [f"# Weekly core report: {gate.name}", "",
             f"Previous run: {previous.name if previous else 'none (first weekly core run)'}. Medians and spread are in % of the author under our lane (points for spread and delta); this report decides nothing.", "",
             "| reference | seeds | median | spread | audit errors | fixed-point gain | previous median | delta | status |",
             "|---|---|---|---|---|---|---|---|---|"]
    for slug, v in cur.items():
        pm = prev.get(slug, {}).get("median") if prev is not None else None
        prev_cell = "first run" if prev is None else _f(pm, 1, " %")
        delta = (v["median"] - pm) if (v["median"] is not None and pm is not None) else None
        delta_cell = "first run" if prev is None else _d(delta)
        status = v["status"] if v["median"] is not None else f"infeasible (clean {v['clean']})"
        lines.append(f"| {slug} | {v['seeds']} | {_f(v['median'], 1, ' %')} | {_f(v['spread'], 1)} | {v['audit_errors']} | {_f(v['gain'], 2, ' %')} | {prev_cell} | {delta_cell} | {status} |")
    t = totals(cur)
    lines += ["", f"Covered {t['covered']} of {t['total']}, stable {t['stable']} of {t['total']}, median of medians {_f(t['median'], 1, ' %')}."]
    if prev is None:
        lines.append("Previous run: none (first weekly core run).")
    else:
        p = totals(prev)
        dm = (t["median"] - p["median"]) if (t["median"] is not None and p["median"] is not None) else None
        lines.append(f"Previous run: covered {p['covered']} of {p['total']} ({t['covered'] - p['covered']:+d}), stable {p['stable']} of {p['total']} ({t['stable'] - p['stable']:+d}), "
                     f"median of medians {_f(p['median'], 1, ' %')} ({_d(dm)} points).")
    lines.append(f"Wall clock: {wall_clock(gate, rows)}.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--core", required=True, help="the weekly core run's folder or name (P2-core or P2-core-<n>)")
    ap.add_argument("--previous", help="the previous core run's folder or name")
    args = ap.parse_args(argv)
    gate = resolve(args.core)
    rows = _rows(gate)
    if not rows:
        print(f"no rows in {gate / 'results.json'}")
        return 0
    previous = resolve(args.previous) if args.previous else None
    prev_rows = _rows(previous) if previous else None
    text = render(gate, rows, previous, prev_rows)
    (gate / "report-weekly.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
