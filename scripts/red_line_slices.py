"""#1123 unit 1 (a): the distinct day-1 red lines, sliced for the marks workers (file reads only, no PoB).

A red line is a day-1 row whose outcome is `partial` or `none` (scripts/day1_red_lines_report.py). Rows that share a
line text make one record, its surfaces and sources the sorted distinct values over those rows; the group of a text
is scripts/day1_groups.group_of. Slices hold at most CAP distinct lines each, in GROUPS order, sorted by text; a group
over CAP is split into numbered parts (`<NN>-<group>-p<k>.json`), a smaller group is one file (`<NN>-<group>.json`).

Slice file: {"group", "part" (null when unsplit), "parts", "records"}; a record is
{line, surfaces[], sources[], group, outcome}.

Run: `python scripts/red_line_slices.py [--out-dir DIR]` (default artifacts/1123/slices).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_groups import GROUPS, group_of  # noqa: E402
from day1_lines import day1_rows, load_corpus  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402

RED = ("partial", "none")
CAP = 120
DEFAULT_OUT = ROOT / "artifacts" / "1123" / "slices"
_SLICE_FILE = re.compile(r"^\d{2}-.+\.json$")


def line_text(line: Any) -> str:
    return " ".join(str(line).split())


def red_records(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One record per distinct red line text, sorted by text. Rows that are not red are left out."""

    by_text: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["outcome"] not in RED:
            continue
        text = line_text(row["line"])
        entry = by_text.setdefault(text, {"surfaces": set(), "sources": set(), "outcomes": set()})
        entry["surfaces"].add(str(row["surface"]))
        entry["sources"].add(str(row["source"]))
        entry["outcomes"].add(row["outcome"])
    out = []
    for text in sorted(by_text):
        entry = by_text[text]
        # one text can be partial on one row and none on another: partial wins (PoB reads part of it), sources keep all rows
        out.append({
            "line": text,
            "surfaces": sorted(entry["surfaces"]),
            "sources": sorted(entry["sources"]),
            "group": group_of(text),
            "outcome": "partial" if "partial" in entry["outcomes"] else "none",
        })
    return out


def slice_records(records: Iterable[Mapping[str, Any]], cap: int = CAP) -> list[dict[str, Any]]:
    """The slices of the records: GROUPS order, then text order; a group over `cap` lines is split in parts."""

    records = list(records)
    unknown = sorted({r["group"] for r in records} - set(GROUPS))
    if unknown:
        raise ValueError(f"records in no known group: {unknown}")
    found: list[dict[str, Any]] = []
    for group in GROUPS:
        members = [dict(r) for r in records if r["group"] == group]
        if not members:
            continue
        chunks = [members[i:i + cap] for i in range(0, len(members), cap)]
        for number, chunk in enumerate(chunks, start=1):
            index = len(found) + 1
            if len(chunks) == 1:
                part, name = None, f"{index:02d}-{group}.json"
            else:
                part, name = number, f"{index:02d}-{group}-p{number}.json"
            found.append({"index": index, "name": name, "group": group, "part": part,
                          "parts": len(chunks), "records": chunk})
    return found


def write_slices(found: Iterable[Mapping[str, Any]], out_dir: Path) -> None:
    """Writes the slice files; slice files of an earlier run that this run does not make are removed (own output only)."""

    found = list(found)
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = {s["name"] for s in found}
    for old in out_dir.iterdir():
        if _SLICE_FILE.match(old.name) and old.name not in keep:
            old.unlink()
    for s in found:
        body = {"group": s["group"], "part": s["part"], "parts": s["parts"], "records": s["records"]}
        text = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (out_dir / s["name"]).write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    rails = Rails.load()
    rows = list(day1_rows(rails, load_corpus(rails)))
    red_rows = sum(1 for r in rows if r["outcome"] in RED)
    records = red_records(rows)
    found = slice_records(records)
    write_slices(found, args.out_dir)
    print(f"day-1 rows: {len(rows)}; red rows: {red_rows}; distinct red lines: {len(records)}")
    print(f"slices: {len(found)} (at most {CAP} lines each) in {args.out_dir}")
    for s in found:
        print(f"  {s['name']}: {len(s['records'])} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
