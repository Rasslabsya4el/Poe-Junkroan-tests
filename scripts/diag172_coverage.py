"""#172 item 4: per-run coverage (rows with `ratio_lane` >= 1.0), recorded vs corrected -- only the
rows of the slugs item 1 found affected can move; every other row keeps its recorded ratio.

Reads `results.json` of each of the five runs, `counted_row`-filtered exactly like
`render_report` scores coverage, and swaps in the corrected `ratio_lane` (from
`diag172_rescore.py`'s output) for the affected slugs' rows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.benchmark_rows import counted_row  # noqa: E402

RUNS = {
    "ziz-tpl": "20260927-0322-ziz-tpl-main3-s4",
    "ziz": "20260926-0200-ziz-main3-s4",
    "new18-tpl": "20260926-0920-new18-tpl-main3-s4-lap",
    "core14-tpl": "20260926-1759-core14-tpl-main3-s4",
    "core14": "20260925-1943-core14-main3-s4",
}

RESCORE = json.loads((ROOT / "artifacts" / "runs" / "diag172_rescore_result.json").read_text(encoding="utf-8"))


def corrected_ratio(run_short: str, slug: str, seed) -> float | None:
    for r in RESCORE:
        if r["run"] == run_short and r["slug"] == slug and r["seed"] == seed:
            return r["corrected_ratio_lane"]
    return None


def best_of_slug(results: list[dict]) -> dict[str, dict]:
    """The report's own "best of" pick: the row with the higher `ratio_lane` per (slug, seed) --
    here every slug has exactly one row per seed, so best-of collapses to that row."""
    return {(str(r.get("slug")), r.get("seed")): r for r in results}


def main() -> None:
    for short, run in RUNS.items():
        results = json.loads((ROOT / "artifacts" / "benchmark" / run / "results.json").read_text(encoding="utf-8"))
        rows = [r for r in results if counted_row(r)]
        recorded_covered = sum(1 for r in rows if isinstance(r.get("ratio_lane"), (int, float)) and r["ratio_lane"] >= 1.0)
        corrected_covered = 0
        moved = []
        for r in rows:
            ratio = r.get("ratio_lane")
            corr = corrected_ratio(short, str(r.get("slug")), r.get("seed"))
            if corr is not None:
                ratio = corr
            if isinstance(ratio, (int, float)) and ratio >= 1.0:
                corrected_covered += 1
            if corr is not None and (r.get("ratio_lane") is None or (r.get("ratio_lane") >= 1.0) != (ratio >= 1.0)):
                moved.append((r.get("slug"), r.get("seed"), r.get("ratio_lane"), ratio))
        print(f"{short:10s} ({run}): rows counted {len(rows)}, coverage recorded {recorded_covered}, corrected {corrected_covered}"
              + (f", moved: {moved}" if moved else ""))


if __name__ == "__main__":
    main()
