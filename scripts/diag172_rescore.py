"""#172 item 2: for every slug item 1 found affected, re-score the author the way `main` does it
(`flag_main_group_for_full_dps(xml, count, main=...)`, the derived count on the main skill's
gem) and compare with the recorded `author_lane` / `ratio_lane` of the finished runs.

Read-only against `results.json` for the recorded side; one `prepare_author` call per (run,
slug) for the corrected side -- `author_cache=None` so the stale memo (written at @42565a9,
before 10c1e84) is never replayed, and the fresh call goes through the current
`flag_main_group_for_full_dps`, which is the same fix `main`'s benchmark run gets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

# (short run name, run dir, [affected slugs]) -- from diag172_author_count.py's item 1 output
JOBS = [
    ("ziz-tpl", "20260927-0322-ziz-tpl-main3-s4", ["z327_necromancer_raise_spectre", "z328_hierophant_shock_nova_archmage"]),
    ("ziz", "20260926-0200-ziz-main3-s4", ["z327_necromancer_raise_spectre", "z328_hierophant_shock_nova_archmage"]),
]


def load_results(run: str) -> list[dict]:
    path = ROOT / "artifacts" / "benchmark" / run / "results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    from junkroan.pob.session import PobSession

    rows_out = []
    with PobSession(run_id="diag172-rescore") as pob:
        for short, run, slugs in JOBS:
            results = load_results(run)
            for slug in slugs:
                log_lines: list[str] = []
                prepared = prepare_author_fresh(pob, slug, log_lines)
                corrected_author_lane = prepared.author_lane[prepared.stat]
                slug_rows = [r for r in results if r.get("slug") == slug]
                for row in sorted(slug_rows, key=lambda r: r.get("seed")):
                    ours = row.get("ours")
                    recorded_author_lane = row.get("author_lane")
                    recorded_ratio = row.get("ratio_lane")
                    corrected_ratio = (ours or 0) / max(1.0, corrected_author_lane)
                    rows_out.append({
                        "run": short, "slug": slug, "seed": row.get("seed"),
                        "ours": ours,
                        "recorded_author_lane": recorded_author_lane,
                        "corrected_author_lane": corrected_author_lane,
                        "recorded_ratio_lane": recorded_ratio,
                        "corrected_ratio_lane": corrected_ratio,
                    })

    print(f"{'run':10s} {'slug':38s} {'seed':>4s} {'ours':>12s} {'author_lane rec':>16s} {'author_lane corr':>17s} {'ratio rec':>9s} {'ratio corr':>10s}")
    for r in rows_out:
        print(f"{r['run']:10s} {r['slug']:38s} {r['seed']:>4} {r['ours']:>12,.0f} {r['recorded_author_lane']:>16,.0f} {r['corrected_author_lane']:>17,.0f} {r['recorded_ratio_lane']:>9.3f} {r['corrected_ratio_lane']:>10.3f}")

    out_path = ROOT / "artifacts" / "runs" / "diag172_rescore_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows_out, indent=2), encoding="utf-8")
    print(f"\nwritten {out_path}")


def prepare_author_fresh(pob, slug: str, log_lines: list[str]):
    from benchmark import prepare_author

    def log(msg: str) -> None:
        log_lines.append(msg)

    return prepare_author(pob, slug, log=log, author_cache=None)


if __name__ == "__main__":
    main()
