"""#1119 unit 4 (report): the day-1 red lines as tables, generated from the rows (file reads only, no PoB).

A red line is a day-1 row whose outcome is `partial` or `none`: PoB reads part of it or none of it. The rows come
from unit 1 (`day1_lines.day1_rows`, the rails and the parse outcomes), the group of each line from unit 2
(`day1_groups.group_of`). Tables:
- (a) surface x outcome, with the total row;
- (b) group x surface, line counts, with the total row;
- (c) per group: lines by surface, distinct sources (surface, source id), red lines, partial share, and the first
  three distinct line texts in sorted order as examples (a group with no lines shows none).

Run: `python scripts/day1_red_lines_report.py` (writes docs/research/2026-10-15-day1-red-lines.md).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from day1_groups import GROUPS, group_of  # noqa: E402
from day1_lines import OUTCOMES, SURFACES, UNIQUE_JEWEL_FORM, day1_rows, load_corpus  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402

RED = ("partial", "none")
DOC = ROOT / "docs" / "research" / "2026-10-15-day1-red-lines.md"
EXAMPLES = 3


def _line(row: dict) -> str:
    return " ".join(str(row["line"]).split())


def surface_outcome_table(rows) -> dict[str, dict[str, int]]:
    table = {s: {o: 0 for o in OUTCOMES} for s in SURFACES}
    for r in rows:
        table[r["surface"]][r["outcome"]] += 1
    return table


def group_surface_table(rows) -> dict[str, dict[str, int]]:
    """group -> {surface: line count}, only the surfaces that hold a line; every group of GROUPS is a key."""
    table: dict[str, dict[str, int]] = {g: {} for g in GROUPS}
    for r in rows:
        cells = table[group_of(r["line"])]
        cells[r["surface"]] = cells.get(r["surface"], 0) + 1
    return table


def _examples(found: list[dict]) -> list[str]:
    """Red lines first, sorted by text; non-red texts fill the rest. Each is `[outcome] text`, one per text."""
    red = sorted({(_line(r), r["outcome"]) for r in found if r["outcome"] in RED})
    rest = sorted({(_line(r), r["outcome"]) for r in found if r["outcome"] not in RED})
    picked: list[str] = []
    seen: set[str] = set()
    for text, outcome in red + rest:
        if text in seen:
            continue
        seen.add(text)
        picked.append(f"[{outcome}] {text}")
        if len(picked) == EXAMPLES:
            break
    return picked


def group_summaries(rows) -> list[dict]:
    members: dict[str, list[dict]] = {g: [] for g in GROUPS}
    for r in rows:
        members[group_of(r["line"])].append(r)
    out = []
    for group in GROUPS:
        found = members[group]
        counts = Counter(r["surface"] for r in found)
        partial = sum(1 for r in found if r["outcome"] == "partial")
        red = sum(1 for r in found if r["outcome"] in RED)
        out.append({
            "group": group,
            "lines": len(found),
            "by_surface": {s: counts[s] for s in SURFACES if counts[s]},
            "sources": len({(r["surface"], r["source"]) for r in found}),
            "red": red,
            "partial_share": partial / len(found) if found else None,
            "partial_of_red": partial / red if red else None,
            "examples": _examples(found),
        })
    return out


def _md_table(header: list[str], body: list[list[str]], align: list[str] | None = None) -> list[str]:
    sep = align or ["---"] + ["---:"] * (len(header) - 1)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return lines


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _share(share: float | None) -> str:
    return "-" if share is None else f"{share * 100:.1f}%"


def render(rows) -> str:
    rows = list(rows)
    total = len(rows)
    outcomes = Counter(r["outcome"] for r in rows)
    red = sum(outcomes[o] for o in RED)
    out = ["# Day-1 red lines (#1119, unit 4)", ""]

    out.append(
        f"A red line is a line on a day-1 item, unique, flask or passive node that PoB reads only in part, or not at all. "
        f"In this report a line is red when its outcome is `partial` (PoB reads part of it) or `none` (PoB reads none of it); "
        f"`full` lines are read whole. {red} of {total} day-1 lines are red ({outcomes['partial']} partial, {outcomes['none']} none), "
        f"so the tables below show where PoB stops understanding what the day-1 rails allow."
    )
    if outcomes["missing"]:
        out.append(f"{outcomes['missing']} lines are `missing` (no parse outcome yet) and are not counted as red.")
    out.append("")

    surfaces = surface_outcome_table(rows)
    out += ["## (a) Surface x outcome", ""]
    body = [[s] + [str(surfaces[s][o]) for o in OUTCOMES] + [str(sum(surfaces[s].values()))] for s in SURFACES]
    body.append(["total"] + [str(outcomes[o]) for o in OUTCOMES] + [str(total)])
    out += _md_table(["surface", *OUTCOMES, "total"], body)
    out.append("")

    groups = group_surface_table(rows)
    out += ["## (b) Group x surface (line counts)", ""]
    body = []
    for g in GROUPS:
        cells = [str(groups[g].get(s, 0)) for s in SURFACES]
        body.append([g] + cells + [str(sum(groups[g].values()))])
    surface_totals = [str(sum(groups[g].get(s, 0) for g in GROUPS)) for s in SURFACES]
    body.append(["total"] + surface_totals + [str(total)])
    out += _md_table(["group", *SURFACES, "total"], body)
    out.append("")

    out += ["## (c) Per group", ""]
    summaries = group_summaries(rows)
    body = []
    for summary in summaries:
        by_surface = ", ".join(f"{s} {n}" for s, n in summary["by_surface"].items()) or "-"
        examples = "; ".join(_cell(e) for e in summary["examples"]) or "-"
        body.append([
            summary["group"], str(summary["lines"]), _cell(by_surface), str(summary["sources"]),
            str(summary["red"]), _share(summary["partial_share"]), _share(summary["partial_of_red"]), examples,
        ])
    out += _md_table(
        ["group", "lines", "by surface", "distinct sources (node id / unique name / mod id)", "red",
         "partial share (partial / all lines of the group)", "partial of red (partial / red lines)", "examples"],
        body,
        align=["---", "---:", "---", "---:", "---:", "---:", "---:", "---"],
    )
    out.append("")

    distinct_texts = len({_line(r) for r in rows})
    out += ["## Notes", ""]
    out.append(
        f"- Distinct sources can be fewer than lines in a group: one line text sits on several sources (node ids, unique "
        f"names, mod ids), and {total - distinct_texts} of the {total} rows repeat a text another row already has "
        f"({distinct_texts} distinct texts in all)."
    )
    for summary in summaries:
        if summary["lines"] == 0:
            if summary["group"] == "jewel_conditional":
                out.append(
                    "- jewel_conditional: 0 lines. Its lines are jewel lines (a radius or a socketed jewel), which only the "
                    "unique_jewel surface would carry; that surface is empty, so the group is empty too."
                )
            else:
                out.append(f"- {summary['group']}: 0 lines in the day-1 rows.")
    if sum(surfaces["unique_jewel"].values()) == 0:
        out.append(
            f"- unique_jewel: 0 rows. Only a unique jewel whose entry in the owner's form (`{UNIQUE_JEWEL_FORM.relative_to(ROOT).as_posix()}`) "
            f"has the `day1` loadout reaches this surface, and the form has none yet (rails, not the reader)."
        )
    out.append("")

    out += ["## (d) How to regenerate", ""]
    out.append(
        "Script `scripts/day1_red_lines_report.py` (file reads only, no PoB session). Command, from the repo root: "
        "`python scripts/day1_red_lines_report.py`; it writes this file."
    )
    out.append("")
    return "\n".join(out)


def main() -> int:
    rails = Rails.load()
    rows = list(day1_rows(rails, load_corpus(rails)))
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(render(rows), encoding="utf-8", newline="\n")
    print(f"wrote {DOC.relative_to(ROOT).as_posix()} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
