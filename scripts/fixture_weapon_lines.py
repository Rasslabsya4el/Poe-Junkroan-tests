"""Census the value-bearing lines on reference and delivered-loot weapons.

Every line is removed from its item in one fast PoB item what-if.  The report
therefore records the line's measured share of the objective rather than
treating every line on a rare as equally useful.

Run: python scripts/fixture_weapon_lines.py
Out: artifacts/runs/gear-templates/weapon-lines-census.{json,md}
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import fixture_slugs, prepare_author, result_stem  # noqa: E402
from fixture_gear_tiers import META_PREFIXES, match_line  # noqa: E402
from gear_transplant import active_items, _base, _item_lines, _rarity  # noqa: E402
from junkroan.optimizer.item_bases import type_of  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.search.hypothesis import active_gems  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
DEFAULT_RUNS = (
    ROOT / "artifacts" / "benchmark" / "20260919-0941-core14-rules",
    ROOT / "artifacts" / "benchmark" / "20260919-0130-new18-rules",
)
DEFAULT_JSON = ROOT / "artifacts" / "runs" / "gear-templates" / "weapon-lines-census.json"
DEFAULT_REPORT = ROOT / "artifacts" / "runs" / "gear-templates" / "weapon-lines-census.md"
WEAPON_SLOTS = ("Weapon 1", "Weapon 2")
NON_WEAPON_TYPES = frozenset({"Shield", "Quiver"})


def explicit_lines(raw: str) -> list[tuple[int, str]]:
    """Return physical raw-line indexes for an item's explicit lines."""

    lines = raw.splitlines()
    implicit_at = next((index for index, line in enumerate(lines) if line.strip().startswith("Implicits:")), None)
    if implicit_at is None:
        return []
    try:
        implicit_count = int(lines[implicit_at].split(":", 1)[1])
    except (IndexError, ValueError):
        return []
    return [
        (index, line.strip())
        for index, line in enumerate(lines[implicit_at + 1 + implicit_count:], start=implicit_at + 1 + implicit_count)
        if line.strip() and not line.strip().startswith(META_PREFIXES)
    ]


def without_line(raw: str, index: int) -> str:
    """Remove one explicit raw line without otherwise changing the item's text."""

    lines = raw.splitlines()
    del lines[index]
    return "\n".join(lines)


def is_weapon(slot: str, raw: str) -> bool:
    """Weapons only: never count a shield or quiver occupying Weapon 2."""

    base = _base(raw)
    return slot in WEAPON_SLOTS and base is not None and type_of(base) not in NON_WEAPON_TYPES


def weapon_kind(main_skill: str) -> str:
    """Attack/caster comes from the main gem's corpus tags, not the weapon name."""

    tags = set((active_gems().get(main_skill.lower()) or {}).get("tag_keys") or ())
    return "attack" if "attack" in tags else "caster"


def ladders_for(pob: PobSession, base: str, cache: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, list[dict[str, Any]]]:
    if base not in cache:
        ladders: dict[str, list[dict[str, Any]]] = {}
        for mod in pob.list_item_mods(base, ilvl=100)["mods"]:
            ladders.setdefault(str(mod["group"]), []).append(dict(mod))
        cache[base] = ladders
    return cache[base]


def line_tier(line: str, ladders: Mapping[str, list[dict[str, Any]]]) -> dict[str, object]:
    hit = match_line(line, dict(ladders))
    return {
        "group": hit[0] if hit else None,
        "tier": hit[1] if hit else None,
        "of": hit[2] if hit else None,
        "crafted": line.startswith("{crafted}"),
    }


def measure_weapon(
    pob: PobSession,
    *,
    reference: str,
    source: str,
    slot: str,
    raw: str,
    stat: str,
    kind: str,
    ladder_cache: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, object]:
    """Measure every explicit line's objective share while the item is worn."""

    base = _base(raw) or ""
    entries = explicit_lines(raw)
    worn = float(pob.stats((stat,)).get(stat) or 0.0)
    trials = [{"item": {"slot": slot, "raw": without_line(raw, index)}} for index, _line in entries]
    outcomes = pob.trial_stats(trials, (stat,), mode="fast") if trials else []
    ladders = ladders_for(pob, base, ladder_cache)
    lines: list[dict[str, object]] = []
    for (_index, text), outcome in zip(entries, outcomes):
        without = outcome.get("stats", {}).get(stat) if outcome.get("ok") else None
        value_without = float(without) if isinstance(without, (int, float)) else None
        share = ((worn - value_without) / worn) if value_without is not None and worn else None
        lines.append({"line": text, "value_without": value_without, "share": share, **line_tier(text, ladders)})
    useful = [line for line in lines if isinstance(line.get("share"), float) and line["share"] >= 0.01]
    top = sorted(lines, key=lambda line: float(line.get("share") or float("-inf")), reverse=True)[:3]
    return {
        "reference": reference,
        "source": source,
        "slot": slot,
        "kind": kind,
        "stat": stat,
        "base": base,
        "value_worn": worn,
        "line_count": len(lines),
        "useful_lines": len(useful),
        "lines": lines,
        "top_lines": top,
    }


def load_rows(path: Path) -> list[dict[str, object]]:
    payload = json.loads((path / "results.json").read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{path / 'results.json'} does not contain benchmark rows")
    return [dict(row) for row in rows]


def best_loot_exports(runs: Iterable[Path]) -> dict[str, tuple[Path, dict[str, object]]]:
    """One delivered build per reference: highest persisted ratio_lane across runs."""

    best: dict[str, tuple[float, Path, dict[str, object]]] = {}
    for run in runs:
        for row in load_rows(run):
            if not row.get("ok") or not isinstance(row.get("slug"), str):
                continue
            ratio = row.get("ratio_lane")
            if not isinstance(ratio, (int, float)):
                continue
            slug = str(row["slug"])
            candidate = (float(ratio), run, row)
            if slug not in best or candidate[0] > best[slug][0]:
                best[slug] = candidate
    return {slug: (run, row) for slug, (_ratio, run, row) in best.items()}


def _number(value: object) -> str:
    return "-" if not isinstance(value, (int, float)) else f"{float(value):,.0f}"


def _share(value: object) -> str:
    return "-" if not isinstance(value, (int, float)) else f"{float(value):.1%}"


def _tier(line: Mapping[str, object]) -> str:
    tier, ladder = line.get("tier"), line.get("of")
    return f"T{tier}/{ladder}" if isinstance(tier, int) and isinstance(ladder, int) else "unmatched"


def _top(lines: Iterable[Mapping[str, object]]) -> str:
    return "<br>".join(f"{_tier(line)} {_share(line.get('share'))}: {line.get('line', '?')}" for line in lines) or "-"


def _median(values: Iterable[object]) -> float | None:
    usable = [float(value) for value in values if isinstance(value, (int, float))]
    return float(statistics.median(usable)) if usable else None


def summary_rows(weapons: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Summary exactly over useful lines; top-N requires that many useful lines."""

    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for weapon in weapons:
        grouped[(str(weapon["source"]), str(weapon["kind"]))].append(weapon)
        grouped[(str(weapon["source"]), "all")].append(weapon)
    rows: list[dict[str, object]] = []
    for (source, kind), group in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] == "all", item[0][1])):
        useful_by_weapon = [
            sorted(
                (line for line in weapon.get("lines", []) if isinstance(line, Mapping) and isinstance(line.get("share"), float) and line["share"] >= 0.01),
                key=lambda line: float(line["share"]), reverse=True,
            )
            for weapon in group
        ]
        row: dict[str, object] = {
            "source": source,
            "weapon_kind": kind,
            "weapons": len(group),
            "median_useful_lines": _median(len(lines) for lines in useful_by_weapon),
        }
        for label, values in [
            ("top_1", [lines[0] for lines in useful_by_weapon if len(lines) >= 1]),
            ("top_2", [lines[1] for lines in useful_by_weapon if len(lines) >= 2]),
            ("top_3", [lines[2] for lines in useful_by_weapon if len(lines) >= 3]),
            ("all_useful", [line for lines in useful_by_weapon for line in lines]),
        ]:
            matched = [line for line in values if isinstance(line.get("tier"), int) and isinstance(line.get("of"), int) and int(line["of"]) > 1]
            row[label] = {
                "lines": len(values),
                "matched": len(matched),
                "median_tier": _median(line["tier"] for line in matched),
                "median_relative_position": _median((int(line["tier"]) - 1) / (int(line["of"]) - 1) for line in matched),
            }
        rows.append(row)
    return rows


def render_report(weapons: list[dict[str, object]], summary: list[dict[str, object]], missing_loot: list[str]) -> str:
    lines = [
        "# Weapon Line Value Census",
        "",
        "Every share is `(value with weapon worn - value with one explicit line deleted) / value with weapon worn`, measured by a fast PoB item what-if. `USEFUL` means share >= 1%.",
        "",
        "| reference | source | slot | kind | stat | base | lines | useful | top three lines by share |",
        "|---|---|---|---|---|---|---:|---:|---|",
    ]
    for weapon in weapons:
        lines.append(
            f"| {weapon['reference']} | {weapon['source']} | {weapon['slot']} | {weapon['kind']} | {weapon['stat']} | {weapon['base']} | "
            f"{weapon['line_count']} | {weapon['useful_lines']} | {_top(weapon['top_lines'])} |"
        )
    lines += [
        "",
        "## Summary",
        "",
        "Each top-N cell is `median tier / median relative position` with the number of tier-matched useful lines. Relative position is `(tier - 1) / (of - 1)`; T1 is 0 and the worst tier is 1.",
        "",
        "| source | weapon kind | weapons | median useful lines | top-1 | top-2 | top-3 | all useful |",
        "|---|---|---:|---:|---|---|---|---|",
    ]
    for row in summary:
        def cell(name: str) -> str:
            value = row[name]
            return f"T{value['median_tier']:.1f} / {value['median_relative_position']:.2f} ({value['matched']}/{value['lines']})" if value["median_tier"] is not None and value["median_relative_position"] is not None else f"- (0/{value['lines']})"

        lines.append(
            f"| {row['source']} | {row['weapon_kind']} | {row['weapons']} | {row['median_useful_lines']:.1f} | "
            f"{cell('top_1')} | {cell('top_2')} | {cell('top_3')} | {cell('all_useful')} |"
        )
    if missing_loot:
        lines += ["", "## Missing Loot Exports", "", *[f"- {item}" for item in missing_loot]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, help="benchmark run directory; repeatable")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--render", action="store_true", help="render an existing census JSON without starting PoB")
    args = parser.parse_args()

    if args.render:
        payload = json.loads(args.json.read_text(encoding="utf-8"))
        weapons = list(payload.get("weapons") or [])
        report = render_report(
            weapons,
            summary_rows(weapons),
            list(payload.get("missing_loot_exports") or []),
        )
        print(report, end="")
        return 0

    loot = best_loot_exports(args.run or DEFAULT_RUNS)
    weapons: list[dict[str, object]] = []
    missing_loot: list[str] = []
    kinds: dict[str, str] = {}
    ladder_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with PobSession(run_id="weapon-lines-census") as pob:
        for slug in fixture_slugs(FIXTURES):
            prepared = prepare_author(pob, slug, log=lambda _line: None)
            kind = weapon_kind(prepared.skeleton.main_link[0])
            kinds[slug] = kind
            for slot, raw in active_items(prepared.state_xml).items():
                if _rarity(raw) == "RARE" and is_weapon(slot, raw):
                    weapons.append(measure_weapon(
                        pob, reference=slug, source="author", slot=slot, raw=raw,
                        stat=prepared.objective.maximize, kind=kind, ladder_cache=ladder_cache,
                    ))

        for slug, (run, row) in sorted(loot.items()):
            path = run / f"{result_stem(row)}.pob.txt"
            if not path.is_file():
                missing_loot.append(f"{slug}: {path}")
                continue
            pob.load_xml(decode_import_code(path.read_text(encoding="utf-8").strip()))
            stat = str(row.get("stat") or "CombinedDPS")
            for slot, raw in active_items(pob.export_xml()).items():
                if _rarity(raw) == "RARE" and is_weapon(slot, raw):
                    weapons.append(measure_weapon(
                        pob, reference=slug, source="loot", slot=slot, raw=raw, stat=stat,
                        kind=kinds.get(slug, "caster"), ladder_cache=ladder_cache,
                    ))

    summary = summary_rows(weapons)
    payload = {"weapons": weapons, "summary": summary, "missing_loot_exports": missing_loot}
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    args.report.write_text(render_report(weapons, summary, missing_loot), encoding="utf-8")
    print(f"json: {args.json}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
