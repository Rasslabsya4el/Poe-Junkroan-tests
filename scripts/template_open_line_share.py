"""Measure D89 template armour/jewellery open-line opportunity cost.

``fix3`` contains the smoke six; ``fix4`` replaces its two corrected controls.
Each non-fixed armour/jewellery line is removed from the delivered template item
in one fast what-if, then the median value share becomes the weapon-base price.

Run: python scripts/template_open_line_share.py
Out: artifacts/runs/gear-templates/open-line-share.{json,md}
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from fixture_gear_tiers import match_line  # noqa: E402
from fixture_weapon_lines import explicit_lines, without_line  # noqa: E402
from gear_transplant import _base, _rarity, active_items  # noqa: E402
from junkroan.optimizer.wishlist_gear import _is_elemental_resistance_group  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

RUNS = (
    ROOT / "artifacts" / "runs" / "gear-templates" / "fix3-results.json",
    ROOT / "artifacts" / "runs" / "gear-templates" / "fix4-results.json",
)
DEFAULT_JSON = ROOT / "artifacts" / "runs" / "gear-templates" / "open-line-share.json"
DEFAULT_REPORT = ROOT / "artifacts" / "runs" / "gear-templates" / "open-line-share.md"
FIXED_GROUPS = {"IncreasedLife", "LocalIncreasedLife", "IncreasedEnergyShield", "LocalIncreasedEnergyShield", "MovementVelocity"}


def rows_from(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["slug"]): dict(row) for row in payload["rows"] if row.get("ok")}


def prefix(path: Path) -> str:
    return path.stem[: -len("-results")]


def is_open_group(group: object) -> bool:
    return isinstance(group, str) and group not in FIXED_GROUPS and not _is_elemental_resistance_group(group)


def ladders(pob: PobSession, base: str, cache: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, list[dict[str, Any]]]:
    if base not in cache:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for mod in pob.list_item_mods(base, ilvl=100)["mods"]:
            grouped.setdefault(str(mod["group"]), []).append(dict(mod))
        cache[base] = grouped
    return cache[base]


def main() -> int:
    rows = rows_from(RUNS[0])
    # Fix4 is the corrected version of its two fix3 controls, not two extra
    # observations in the D89 smoke-six median.
    rows.update(rows_from(RUNS[1]))
    sources = {slug: (RUNS[1] if slug in rows_from(RUNS[1]) else RUNS[0]) for slug in rows}
    detail: list[dict[str, object]] = []
    cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with PobSession(run_id="template-open-line-share") as pob:
        for slug, row in sorted(rows.items()):
            code_path = sources[slug].parent / f"{prefix(sources[slug])}-{slug}.pob.txt"
            pob.load_xml(decode_import_code(code_path.read_text(encoding="utf-8").strip()))
            stat = str(row["stat"])
            worn = float(pob.stats((stat,)).get(stat) or 0.0)
            for slot, raw in active_items(pob.export_xml()).items():
                if slot.startswith("Weapon") or _rarity(raw) != "RARE":
                    continue
                base = _base(raw)
                if not base:
                    continue
                ladder = ladders(pob, base, cache)
                open_lines = []
                for index, line in explicit_lines(raw):
                    hit = match_line(line, ladder)
                    group = hit[0] if hit else None
                    if is_open_group(group) or line.startswith("{crafted}"):
                        open_lines.append((index, line, group))
                trials = [{"item": {"slot": slot, "raw": without_line(raw, index)}} for index, _line, _group in open_lines]
                outcomes = pob.trial_stats(trials, (stat,), mode="fast") if trials else []
                for (_index, line, group), outcome in zip(open_lines, outcomes):
                    value = outcome.get("stats", {}).get(stat) if outcome.get("ok") else None
                    without = float(value) if isinstance(value, (int, float)) else None
                    detail.append({
                        "reference": slug,
                        "slot": slot,
                        "base": base,
                        "stat": stat,
                        "line": line,
                        "group": group,
                        "share": (worn - without) / worn if without is not None and worn else None,
                    })
    shares = [float(row["share"]) for row in detail if isinstance(row.get("share"), float)]
    value_shares = [share for share in shares if share > 1e-9]
    payload = {
        "lines": detail,
        "median_share_all_lines": statistics.median(shares),
        "median_share_value_lines": statistics.median(value_shares),
        "value_line_count": len(value_shares),
        "count": len(shares),
    }
    DEFAULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report = [
        "# D89 Template Open-Line Value Share",
        "",
        "`fix4` replaces the two corrected controls in `fix3`; each armour/jewellery open-or-craft line is measured by deleting it from the delivered template item in a fast PoB what-if.",
        "",
        f"All-line median: **{payload['median_share_all_lines']:.2%}** across {payload['count']} flexible lines. "
        f"The weapon-base price uses the **{payload['median_share_value_lines']:.2%}** median across {payload['value_line_count']} value-bearing lines; floor-only repairs have a 0% DPS share and are not a forgone value line.",
        "",
        "| reference | slot | base | stat | group | value share | line |",
        "|---|---|---|---|---|---:|---|",
    ]
    report.extend(
        f"| {row['reference']} | {row['slot']} | {row['base']} | {row['stat']} | {row['group'] or 'crafted/unmatched'} | {float(row['share']):.2%} | {row['line']} |"
        for row in detail if isinstance(row.get("share"), float)
    )
    DEFAULT_REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"median value-bearing open-line share: {payload['median_share_value_lines']:.2%} ({payload['value_line_count']}/{payload['count']} lines)")
    print(f"json: {DEFAULT_JSON}")
    print(f"report: {DEFAULT_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
