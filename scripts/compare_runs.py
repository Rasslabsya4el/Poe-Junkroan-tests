"""Compare two benchmark runs by 3-seed medians and decide mechanically (D60's gate).

    python scripts/compare_runs.py artifacts/benchmark/<A> artifacts/benchmark/<B> [--min-delta -5] [--revert-commit <hash>]

A is the control, B the candidate. Per reference: the median over seeds of the ratio to the
author under our lane (points = percent), the seed spread (max - min), audit errors; then the
median of the per-reference medians, over the references counted on BOTH sides (a reference the
audit drops on one side would otherwise move that side's median alone: 2026-09-26, ziz-main3 26
references vs ziz-main3-s4 25 read +12.0 where the common 25 give -1.0); the references counted on
one side only are listed, and the median over each side's own set is printed for reference.
Verdict PASS when B's median of medians (common set) is at least A's
plus --min-delta (points; the default -5 tolerates one seed's noise, CLAUDE.md: a seed moves
a reference by up to 35 points, a median by less), FAIL otherwise. With --revert-commit the
FAIL branch runs `git revert --no-edit <hash>` so the runs queued after this line use the code
without the change: a decision written before the numbers, executed without a person.

Exit codes: 0 PASS, 1 FAIL, 2 incomplete (a results.json is missing or B has no finished row).
Only numbers are printed; reading them is the main session's job.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.benchmark_rows import audit_errors, counted_row, time_under_load
from junkroan.report_format import human_duration


def resolve(arg: str) -> Path:
    """A run folder, or a tag: the newest `artifacts/benchmark/*-<tag>` (the stamp is unknown when the queue is written)."""

    path = Path(arg)
    if path.is_dir():
        return path
    root = Path(__file__).resolve().parents[1] / "artifacts" / "benchmark"
    matches = sorted(d for d in root.glob(f"*-{arg}") if d.is_dir())
    return matches[-1] if matches else path


def _rows(run: Path) -> list[dict]:
    path = run / "results.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
    return [r for r in rows if isinstance(r, dict) and not r.get("variant")]


def summarize(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for slug in sorted({r["slug"] for r in rows}):
        mine = [r for r in rows if r["slug"] == slug]
        finished = [r for r in mine if r.get("ok") and isinstance(r.get("ratio_lane"), (int, float))]
        counted = [r for r in finished if counted_row(r)]
        points = sorted(round(100.0 * float(r["ratio_lane"]), 1) for r in counted)
        out[slug] = {
            "seeds": len(counted),
            "failed": len(mine) - len(finished),
            "not_counted": len(finished) - len(counted),
            "median": statistics.median(points) if points else None,
            "spread": (points[-1] - points[0]) if len(points) > 1 else None,
            "audit_errors": sum(len(audit_errors(r)) for r in finished),
            "points": points,
            "error": next((str(r["error"]).splitlines()[0] for r in mine if not r.get("ok") and r.get("error")), None),
        }
    return out


def _max_pass(row: dict) -> int:
    passes = [m["pass"] for m in row.get("move_rows") or [] if isinstance(m, dict) and isinstance(m.get("pass"), int)]
    return max(passes) if passes else 0


def _pob_seconds(row: dict) -> float:
    total = 0.0
    for entry in (row.get("pob_calls") or {}).values():
        seconds = entry.get("seconds") if isinstance(entry, dict) else entry
        if isinstance(seconds, (int, float)):
            total += float(seconds)
    return total


def _delta_pct(a_value, b_value):
    if not isinstance(a_value, (int, float)) or not isinstance(b_value, (int, float)) or a_value == 0:
        return None
    return round(100.0 * (b_value - a_value) / a_value, 1)


def per_build_rows(a_rows: list[dict], b_rows: list[dict]) -> list[dict]:
    """One row per (slug, seed) present in both runs, sorted by slug then seed."""

    a_by_key = {(r.get("slug"), r.get("seed")): r for r in a_rows}
    b_by_key = {(r.get("slug"), r.get("seed")): r for r in b_rows}
    out: list[dict] = []
    for key in sorted(set(a_by_key) & set(b_by_key)):
        ra, rb = a_by_key[key], b_by_key[key]
        a_value, b_value = ra.get("ours"), rb.get("ours")
        out.append({
            "slug": key[0],
            "seed": key[1],
            "a_value": a_value,
            "b_value": b_value,
            "delta_pct": _delta_pct(a_value, b_value),
            "a_passes": _max_pass(ra),
            "b_passes": _max_pass(rb),
            "a_pob_seconds": _pob_seconds(ra),
            "b_pob_seconds": _pob_seconds(rb),
            "a_build_seconds": ra.get("seconds"),
            "b_build_seconds": rb.get("seconds"),
            "a_time_under_load": time_under_load(ra),  # #77
            "b_time_under_load": time_under_load(rb),
        })
    return out


def _fmt_value(value) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{value:.1f}"


def per_build_table(rows: list[dict]) -> str:
    """Render `per_build_rows` as a markdown table with human durations.

    A build time carries a trailing ``*`` when its loop stopped on time while the host was under
    load (#77); the caller prints the one-line legend only when at least one row has it.
    """

    lines = [
        "| slug | seed | A value | B value | delta % | A passes | B passes | A PoB | B PoB | A build | B build |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        delta = "n/a" if r["delta_pct"] is None else f"{r['delta_pct']:+.1f}"
        a_build = human_duration(r["a_build_seconds"]) + ("*" if r.get("a_time_under_load") else "")
        b_build = human_duration(r["b_build_seconds"]) + ("*" if r.get("b_time_under_load") else "")
        lines.append(
            f"| {r['slug']} | {r['seed']} | {_fmt_value(r['a_value'])} | {_fmt_value(r['b_value'])} | {delta} | "
            f"{r['a_passes']} | {r['b_passes']} | {human_duration(r['a_pob_seconds'])} | {human_duration(r['b_pob_seconds'])} | "
            f"{a_build} | {b_build} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("control")
    ap.add_argument("candidate")
    ap.add_argument("--min-delta", type=float, default=-5.0, help="PASS when candidate median of medians >= control's + this (points)")
    ap.add_argument("--revert-commit", help="on FAIL run `git revert --no-edit <hash>` in the repo root")
    ap.add_argument("--per-build", action="store_true", help="also print a per-(slug, seed) table over builds present in both runs")
    args = ap.parse_args()
    a, b = resolve(args.control), resolve(args.candidate)
    rows_a, rows_b = _rows(a), _rows(b)
    sa, sb = summarize(rows_a), summarize(rows_b)
    if not sa or not sb:
        print(f"incomplete: control rows {sum(v['seeds'] for v in sa.values())}, candidate rows {sum(v['seeds'] for v in sb.values())}")
        return 2
    print(f"| reference | {a.name} seeds | median | spread | {b.name} seeds | median | spread | delta | audit errors A/B | not counted A/B |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    deltas = []
    for slug in sorted(set(sa) | set(sb)):
        ra, rb = sa.get(slug, {}), sb.get(slug, {})
        ma, mb = ra.get("median"), rb.get("median")
        delta = (mb - ma) if (ma is not None and mb is not None) else None
        if delta is not None:
            deltas.append(delta)
        fmt = lambda v: "n/a" if v is None else f"{v:.1f}"
        print(f"| {slug} | {ra.get('seeds', 0)}{'+' + str(ra['failed']) + ' failed' if ra.get('failed') else ''} | {fmt(ma)} | {fmt(ra.get('spread'))} | "
              f"{rb.get('seeds', 0)}{'+' + str(rb['failed']) + ' failed' if rb.get('failed') else ''} | {fmt(mb)} | {fmt(rb.get('spread'))} | {fmt(delta)} | {ra.get('audit_errors', 0)}/{rb.get('audit_errors', 0)} | {ra.get('not_counted', 0)}/{rb.get('not_counted', 0)} |")
    counted_a = {k for k, v in sa.items() if v["median"] is not None}
    counted_b = {k for k, v in sb.items() if v["median"] is not None}
    common = sorted(counted_a & counted_b)
    if not common:
        print("incomplete: no reference counted in both control and candidate")
        return 2
    for side, only in ((a.name, counted_a - counted_b), (b.name, counted_b - counted_a)):
        if only:
            print(f"counted in {side} only (left out of the verdict): {', '.join(sorted(only))}")
    own_a = statistics.median(sa[k]["median"] for k in counted_a)
    own_b = statistics.median(sb[k]["median"] for k in counted_b)
    mm_a = statistics.median(sa[k]["median"] for k in common)
    mm_b = statistics.median(sb[k]["median"] for k in common)
    delta_verdict = "PASS" if mm_b >= mm_a + args.min_delta else "FAIL"  # the delta's own reading, printed on its line
    verdict = delta_verdict
    lost = sorted(counted_a - counted_b)  # built in the control, no median in the candidate: decides alone
    if lost:
        verdict = "FAIL"
    if counted_a != counted_b:
        print(f"median of medians over each side's own set: {a.name} {own_a:.1f} ({len(counted_a)}), {b.name} {own_b:.1f} ({len(counted_b)})")
    print(f"median of medians over the {len(common)} common references: {a.name} {mm_a:.1f}, {b.name} {mm_b:.1f}, delta {mm_b - mm_a:+.1f} (min {args.min_delta:+.1f}): {delta_verdict}")
    if lost:
        parts = [f"{k} ({sb[k]['error']})" if k in sb and sb[k].get("error") else f"{k} (absent)" if k not in sb else f"{k} (no counted seed)" for k in lost]
        print(f"FAIL: built in {a.name}, lost in {b.name}: {', '.join(parts)}")
    moved = [(k, sa[k]["median"], sb[k]["median"]) for k in common if sa[k]["median"] and abs(sb[k]["median"] - sa[k]["median"]) > 0.15 * abs(sa[k]["median"])]
    if moved:
        print("moved more than 15 %:")
        for k, x, y in moved:
            print(f"- {k}: {x:.1f} -> {y:.1f} ({100.0 * (y - x) / x:+.1f} %)")
    if args.per_build:
        print()
        per_build = per_build_rows(rows_a, rows_b)
        print(per_build_table(per_build))
        if any(r.get("a_time_under_load") or r.get("b_time_under_load") for r in per_build):
            print("`*` after a build time: loop stopped on time while the host was under load (#77).")
    if verdict == "FAIL" and args.revert_commit:
        root = Path(__file__).resolve().parents[1]
        res = subprocess.run(["git", "revert", "--no-edit", args.revert_commit], cwd=root, capture_output=True, text=True)
        print(f"git revert {args.revert_commit}: rc {res.returncode}\n{(res.stdout + res.stderr).strip()[-600:]}")
        if res.returncode != 0:
            return 1
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
