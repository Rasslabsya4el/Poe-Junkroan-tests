"""Early warning (#749): `python scripts/early_warning.py --week YYYYmmdd [--core <run>] [--post]`.

Compares the base rows an empty machine made this week on current main (folders `artifacts/benchmark/*-warn-<Monday>`)
with the same references and seeds of the weekly core run, and prints only the references that dropped or failed.
Exit code 0 both ways; starts no PoB.
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
sys.path.insert(0, str(ROOT / "scripts"))

from compare_runs import _rows  # noqa: E402

MIN_THRESHOLD = 5.0
MIN_SEEDS = 2
BENCH = ROOT / "artifacts" / "benchmark"


def newest_core(root: Path | None = None) -> Path | None:
    """The newest finished weekly core run: a `*-gate-*` folder with results.json (folder names start with a sortable stamp)."""
    root = root or BENCH
    done = sorted(d for d in root.glob("*-gate-*") if d.is_dir() and (d / "results.json").is_file())
    return done[-1] if done else None


def week_rows(week: str, root: Path | None = None) -> list[dict]:
    """Newest row per (slug, seed) over the one folder level `*-warn-<week>`; variant rows are left out."""
    root = root or BENCH
    best: dict[tuple, tuple[float, dict]] = {}
    for folder in sorted(d for d in root.glob(f"*-warn-{week}") if d.is_dir()):
        for f in (folder / "rows").glob("*.json"):
            try:
                row = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(row, dict) or row.get("variant") or "slug" not in row or "seed" not in row:
                continue
            key, stamp = (row["slug"], row["seed"]), f.stat().st_mtime
            if key not in best or stamp >= best[key][0]:
                best[key] = (stamp, row)
    return [r for _, r in best.values()]


def _points(row: dict) -> float | None:
    v = row.get("ratio_lane")
    return 100.0 * float(v) if isinstance(v, (int, float)) else None


def _clean(row: dict) -> bool:
    return bool(row.get("ok")) and _points(row) is not None and not int(row.get("audit_errors") or 0)


def thresholds(core_rows: list[dict]) -> dict[str, dict]:
    """Per reference: seeds' points, spread (max - min over the core's rows with a number), threshold = max(5.0, spread)."""
    out: dict[str, dict] = {}
    for slug in sorted({r["slug"] for r in core_rows}):
        pts = {r["seed"]: _points(r) for r in core_rows if r["slug"] == slug and _points(r) is not None}
        spread = (max(pts.values()) - min(pts.values())) if pts else 0.0
        out[slug] = {"points": pts, "spread": spread, "threshold": max(MIN_THRESHOLD, spread)}
    return out


def find_drops(core_rows: list[dict], rows: list[dict]) -> list[dict]:
    th = thresholds(core_rows)
    core = {(r["slug"], r["seed"]): r for r in core_rows}
    found = []
    for slug in sorted({r["slug"] for r in rows} & set(th)):
        mine = [r for r in rows if r["slug"] == slug]
        commits = [r["commit"] for r in sorted(mine, key=lambda r: r["seed"]) if r.get("commit")]
        failed = [r for r in mine if not _clean(r) and (slug, r["seed"]) in core and _clean(core[(slug, r["seed"])])]
        if failed:
            found.append({"slug": slug, "kind": "failed", "seeds": sorted(r["seed"] for r in failed), "commits": commits,
                          "threshold": th[slug]["threshold"]})
            continue
        good = [r for r in mine if _clean(r) and (slug, r["seed"]) in core and _clean(core[(slug, r["seed"])])]
        if len(good) < MIN_SEEDS:
            continue
        mon = statistics.median(_points(core[(slug, r["seed"])]) for r in good)
        now = statistics.median(_points(r) for r in good)
        if now < mon - th[slug]["threshold"]:
            found.append({"slug": slug, "kind": "dropped", "seeds": sorted(r["seed"] for r in good), "monday": mon, "now": now,
                          "delta": now - mon, "threshold": th[slug]["threshold"], "commits": commits})
    return found


HEADER = ["| reference | seeds made | Monday's median | this week's median | delta | threshold | commits (first, last) |",
          "|---|---|---|---|---|---|---|"]


def row_line(d: dict) -> str:
    c = d["commits"]
    commits = "-" if not c else f"{c[0]}, {c[-1]}"
    seeds = ",".join(map(str, d["seeds"]))
    if d["kind"] == "failed":
        return f"| {d['slug']} | {seeds} | - | failed | - | {d['threshold']:.1f} | {commits} |"
    return (f"| {d['slug']} | {seeds} | {d['monday']:.1f} | {d['now']:.1f} | {d['delta']:+.1f} | "
            f"{d['threshold']:.1f} | {commits} |")


def render(drops: list[dict]) -> str:
    if not drops:
        return "no drop\n"
    return "\n".join(HEADER + [row_line(d) for d in drops]) + "\n"


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def _iso(week: str) -> str:
    return f"{week[:4]}-{week[4:6]}-{week[6:]}"


def ticket_body(week: str, core: Path, table_rows: list[str]) -> str:
    return (
        "## For the human\n"
        "- **What:** builds an empty machine made on current main this week came out lower than the same builds of Monday's weekly core run.\n"
        "- **Why:** the owner's word, 2026-10-10: an early warning between Monday and the cut, heard of only on a drop.\n"
        "- **Plan:** read the table below, find the commit range that moved the reference, and decide whether it is a regression.\n"
        "- **Result:** each reference below fell under Monday's median by more than its own seed spread (at least 5 points).\n"
        "- **Undo:** two-way door (one revert); touches only this ticket.\n\n"
        "## For the agent\n"
        f"Core run: `{core.name}`; week of {_iso(week)}. Rule: #749 (threshold = max(5.0, seed spread of the core run); "
        "at least 2 seeds made this week).\n\n" + "\n".join(HEADER + table_rows) + "\n\n"
        "Not in this ticket: fixing the drop; the table is a signal, PoB numbers decide.\n")


def post(week: str, core: Path, drops: list[dict], gh=_gh) -> str:
    """One ticket per week, one comment per further reference; a reference is written once. Returns what was done."""
    if not drops:
        return "nothing to post"
    title = f"Early warning, week of {_iso(week)}: builds that dropped on current main"
    found = json.loads(gh(["issue", "list", "--state", "all", "--search", f'"{title}" in:title',
                           "--json", "number,title,body,comments"]) or "[]")
    mine = [i for i in found if i.get("title") == title]
    written = ""
    number = None
    if mine:
        number = mine[0]["number"]
        written = mine[0].get("body", "") + "".join(c.get("body", "") for c in mine[0].get("comments", []))
    done = []
    for d in drops:
        if f"| {d['slug']} |" in written:
            continue
        if number is None:
            out = gh(["issue", "create", "--title", title, "--label", "needs-triage", "--label", "area:builds",
                      "--body", ticket_body(week, core, [row_line(d)])])
            number = out.strip().rsplit("/", 1)[-1]
            done.append(f"opened #{number}")
        else:
            gh(["issue", "comment", str(number), "--body", "\n".join(HEADER + [row_line(d)])])
            done.append(f"commented {d['slug']}")
    return "; ".join(done) or "already written"


def main(argv: list[str] | None = None, gh=_gh) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", required=True, help="the Monday as YYYYmmdd")
    ap.add_argument("--core", help="the weekly core run's folder (default: the newest finished *-gate-* run)")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--print-thresholds", action="store_true", help="print the threshold table of the core run and stop")
    args = ap.parse_args(argv)
    if args.core:
        core, how = Path(args.core), "given"
    else:
        core, how = newest_core(), "newest *-gate-* folder with results.json"
    if core is None or not core.is_dir():
        print("no core run found")
        return 0
    print(f"core run: {core.name} ({how})")
    core_rows = _rows(core)
    if args.print_thresholds:
        print("| reference | seeds' ratio_lane (points) | spread | threshold |\n|---|---|---|---|")
        for slug, v in thresholds(core_rows).items():
            pts = ", ".join(f"s{s} {p:.1f}" for s, p in sorted(v["points"].items()))
            print(f"| {slug} | {pts} | {v['spread']:.1f} | {v['threshold']:.1f} |")
        return 0
    drops = find_drops(core_rows, week_rows(args.week))
    print(render(drops))
    if args.post:
        print(post(args.week, core, drops, gh))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
