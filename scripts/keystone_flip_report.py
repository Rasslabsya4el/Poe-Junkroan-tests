"""Issue #1030, unit 3: the keystone flip table as markdown, joined from the parse JSON and the flip JSONs.

    python scripts/keystone_flip_report.py --parse <parse.json> --flip spark=<flip.json> cold_dot=<flip.json> smite=<flip.json> --out docs/research/2026-10-14-keystone-flip-table.md
    python scripts/keystone_flip_report.py --parse <parse.json> --flip spark=<flip.json> smite=<flip.json> --sanity

No PoB runs here. The parse JSON is the list `python -m junkroan.keystone_parse --out <json>` writes; each flip JSON
is the one `scripts/keystone_flip.py` writes (`artifacts/keystone_flip/<build>.json`). Every number in the output is
copied from those files; nothing is judged and no class line is written. `--sanity` prints two rows read straight
off the JSON (Chaos Inoculation on spark, Blood Magic on smite) instead of the table.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # the package lives in src/

from junkroan.report_format import human_duration  # noqa: E402

REPORT_DATE = "2026-10-14"
PARSE_KINDS = ("zero", "redirect", "add", "unparsed")
STATS = ("CombinedDPS", "Life", "EnergyShield", "Mana", "ManaUnreserved", "TotalEHP", "PhysicalMaximumHitTaken", "ChaosResist")
DELTA_COLUMNS = ("CombinedDPS", "Life", "EnergyShield", "TotalEHP", "ManaUnreserved", "objective")
TABLE_HEAD = (
    "keystone",
    "parsed kinds",
    "flip",
    "status",
    "CombinedDPS, %",
    "Life, %",
    "EnergyShield, %",
    "TotalEHP, %",
    "ManaUnreserved, %",
    "objective, %",
    "collapsed nodes v, count",
    "collapsed nodes v, value",
    "collapsed nodes p, count",
    "collapsed nodes p, value",
    "collapsed lines v, count",
    "collapsed lines v, value",
    "collapsed lines p, count",
    "collapsed lines p, value",
    "time",
)
SANITY = (("Chaos Inoculation", "spark", "Life"), ("Blood Magic", "smite", "ManaUnreserved"))
NOTES = (
    "- `parsed kinds`: the kinds of the keystone's stat lines from PoB's parse (`zero`, `redirect`, `add`, `unparsed`); `-` when the parse JSON has no such keystone.",
    "- `flip`: `add` = the keystone allocated in state 2 by `mutate_nodes(add=...)`; `remove` = the build already held it and state 2 removes it.",
    "- `status`: `ok`, or the status PoB gave with its reason (`pob_refused`, `skill_dead`, `not_flipped`).",
    "- `CombinedDPS, %` ... `objective, %`: change from state 1 to state 2 in percent of the absolute state 1 value; `-` where no percentage exists.",
    "- `collapsed nodes v` / `p`: share of the allocated passive nodes worth something in state 1 (value != 0) that fell by more than half or changed sign in state 2; `v` on the maximized stat, `p` on the priced score; `-` where there is no such reading (`p` None).",
    "- `collapsed lines v` / `p`: the same share over the rare-gear affix lines (`line` marginals of the baseline, lines state 2 no longer holds count as 0).",
    "- `time`: wall time of the row.",
)


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def seconds_of(value: Any) -> float:
    return float(value) if _is_number(value) else 0.0


def cell(value: Any) -> str:
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool) or isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.1f}"
    return str(value)


def fmt_pct(value: Any) -> str:
    return f"{value:+.1f}%" if _is_number(value) else "-"


def fmt_share(value: Any) -> str:
    return f"{value * 100:.1f}%" if _is_number(value) else "-"


def fmt_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def baseline_seconds(payload: Mapping[str, Any]) -> float:
    """The baseline run time, read from the cache file the flip run recorded (0 when that file is gone)."""

    cache = (payload.get("baseline") or {}).get("cache")
    if not cache or not Path(cache).is_file():
        return 0.0
    return seconds_of(load_json(Path(cache)).get("seconds"))


def build_seconds(payload: Mapping[str, Any]) -> float:
    return sum(seconds_of(row.get("seconds")) for row in payload.get("rows") or []) + baseline_seconds(payload)


def parse_index(parse_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    return {str(row.get("keystone")): list(row.get("kinds") or []) for row in parse_rows}


def kinds_text(kinds: Sequence[str]) -> str:
    ordered = [k for k in PARSE_KINDS if k in kinds] + sorted(k for k in kinds if k not in PARSE_KINDS)
    return ", ".join(ordered) if ordered else "-"


def status_text(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or "-")
    if status == "ok":
        return status
    reason = row.get("reason")
    return f"{status}: {reason}" if reason else status


def _collapsed(row: Mapping[str, Any], reading: str, scope: str) -> Mapping[str, Any]:
    """The `collapsed` block of one reading ("value" = v, "priced" = p) for one scope ("nodes" | "lines");
    empty when PoB gave no such reading."""

    collapsed = row.get("collapsed") or {}
    return (collapsed.get(reading) or {}).get(scope) or {}


def table_lines(payload: Mapping[str, Any], kinds_by_name: Mapping[str, Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(TABLE_HEAD) + " |", "| " + " | ".join("---" for _ in TABLE_HEAD) + " |"]
    for row in payload.get("rows") or []:
        name = str(row.get("keystone"))
        delta = row.get("delta_pct") or {}
        shares = []
        for scope in ("nodes", "lines"):
            for reading in ("value", "priced"):
                block = _collapsed(row, reading, scope)
                shares += [fmt_share(block.get("share_count")), fmt_share(block.get("share_value"))]
        cells = [
            cell(name),
            cell(kinds_text(kinds_by_name.get(name, []))),
            cell(row.get("flip")),
            cell(status_text(row)),
            *(fmt_pct(delta.get(k)) for k in DELTA_COLUMNS),
            *shares,
            human_duration(row.get("seconds")),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def build_section(label: str, payload: Mapping[str, Any], kinds_by_name: Mapping[str, Sequence[str]]) -> list[str]:
    base = payload.get("baseline") or {}
    numbers = base.get("numbers") or {}
    rows = payload.get("rows") or []
    stats = ", ".join(f"{k} {fmt_num(numbers.get(k))}" for k in STATS)
    return [
        f"## {label}",
        "",
        f"- main skill: {fmt_text(payload.get('main_skill'))}; mode: {fmt_text(payload.get('mode'))}; objective: {fmt_text(payload.get('objective'))}",
        f"- baseline (state 1): {stats}; objective ({fmt_text(numbers.get('objective_stat'))}) {fmt_num(numbers.get('objective'))}",
        f"- baseline nodes {fmt_text(base.get('n_nodes'))}; baseline rare-gear lines {fmt_text(base.get('n_lines'))}; keystones {len(rows)}",
        f"- run time: {human_duration(build_seconds(payload))}",
        "",
        *table_lines(payload, kinds_by_name),
        "",
    ]


def refused_section(label: str, payload: Mapping[str, Any]) -> list[str]:
    rows = [row for row in payload.get("rows") or [] if str(row.get("status") or "ok") != "ok"]
    lines = [f"### {label}", ""]
    if not rows:
        return [*lines, "none", ""]
    lines += ["| keystone | flip | status | reason |", "| --- | --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {cell(row.get('keystone'))} | {cell(row.get('flip'))} | {cell(row.get('status'))} | {cell(row.get('reason'))} |")
    return [*lines, ""]


def render(parse_rows: Sequence[Mapping[str, Any]], builds: Sequence[tuple[str, Mapping[str, Any], Path]], parse_path: Path) -> str:
    kinds_by_name = parse_index(parse_rows)
    total = sum(build_seconds(payload) for _label, payload, _path in builds)
    out: list[str] = [
        "# Keystone flip table (#1030)",
        "",
        f"- date: {REPORT_DATE}",
        "- parent: #1028; this table: #1030 (unit 3, report)",
        f"- parse JSON: `{parse_path}`",
        *(f"- flip JSON {label}: `{path}`" for label, _payload, path in builds),
        f"- Total wall time: {human_duration(total)} (the recorded run seconds of the flip rows and of each baseline; the parse run is not recorded in its JSON)",
        "",
        "## Columns",
        "",
        *NOTES,
        "",
    ]
    for label, payload, _path in builds:
        out += build_section(label, payload, kinds_by_name)
    out += ["## Keystones PoB could not flip on this tree", ""]
    for label, payload, _path in builds:
        out += refused_section(label, payload)
    return "\n".join(out) + "\n"


def sanity_line(by_label: Mapping[str, Mapping[str, Any]], keystone: str, label: str, stat: str) -> str:
    payload = by_label.get(label)
    if payload is None:
        return f"{keystone} on {label}: build not given"
    row = next((r for r in payload.get("rows") or [] if r.get("keystone") == keystone), None)
    if row is None:
        return f"{keystone} on {label}: no row"
    if row.get("status") != "ok":
        return f"{keystone} on {label}: status {status_text(row)}"
    base = (row.get("state1") or {}).get(stat)
    flipped = (row.get("state2") or {}).get(stat)
    delta = (row.get("delta_pct") or {}).get(stat)
    return (
        f"{keystone} on {label} (flip {row.get('flip')}): {stat} {fmt_num(base)} -> {fmt_num(flipped)} ({fmt_pct(delta)}); "
        f"{_share_text(row, 'nodes')}; {_share_text(row, 'lines')}"
    )


def _share_text(row: Mapping[str, Any], scope: str) -> str:
    block = _collapsed(row, "value", scope)
    return (
        f"collapsed {scope} {fmt_text(block.get('n_collapsed'))} of {fmt_text(block.get('n'))}, "
        f"by count {fmt_share(block.get('share_count'))}, by value {fmt_share(block.get('share_value'))}"
    )


def sanity_lines(builds: Sequence[tuple[str, Mapping[str, Any], Path]]) -> list[str]:
    by_label = {label: payload for label, payload, _path in builds}
    return [sanity_line(by_label, keystone, label, stat) for keystone, label, stat in SANITY]


def flip_arg(text: str) -> tuple[str, Path]:
    label, sep, path = text.partition("=")
    if not sep or not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=JSON, got {text!r}")
    return label.strip(), Path(path.strip())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Keystone flip table (markdown) from the parse JSON and the flip JSONs.")
    ap.add_argument("--parse", type=Path, help="keystone_parse JSON (the rows of junkroan.keystone_parse)")
    ap.add_argument("--flip", type=flip_arg, nargs="+", required=True, metavar="NAME=JSON", help="one keystone_flip JSON per build")
    ap.add_argument("--out", type=Path, help="markdown file to write")
    ap.add_argument("--sanity", action="store_true", help="print the two sanity rows (Chaos Inoculation on spark, Blood Magic on smite)")
    args = ap.parse_args(argv)
    if not args.out and not args.sanity:
        ap.error("give --out <md> or --sanity")
    if args.out and args.parse is None:
        ap.error("--out needs --parse")

    builds = [(label, load_json(path), path) for label, path in args.flip]
    if args.sanity:
        for line in sanity_lines(builds):
            print(line)
    if args.out:
        parse_rows = load_json(args.parse)
        text = render(parse_rows, builds, args.parse)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: {len(builds)} builds, {sum(len(p.get('rows') or []) for _l, p, _x in builds)} flip rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
