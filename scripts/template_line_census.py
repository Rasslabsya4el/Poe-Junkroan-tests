"""Census the +0 open lines of template gear per benchmark run.

Every template build log `artifacts/benchmark/<run>/logs/<slug>-s<seed>.log` ends
with a gear summary, one line per slot, e.g.

    Helmet: Royal Burgonet: life T3 T3/10 +(100-114) to maximum Life; resistance_fixed T4 T4/8 +(30-35)% to Cold Resistance; attribute {crafted} +18 to Strength and Dexterity, delta 39,941.

A flexible line is an `objective_line` or `attribute` part; its value is the
number after `delta`, and the census counts how many of them add +0 to the
objective (the next template change is measured against that number). Weapon
slots whose body carries no `life T` are a weapon shape and are skipped: their
lines buy value by rule. When a slot is printed several times (kicks) the last
occurrence is the delivered item.

Run: python scripts/template_line_census.py <run dir or name> [<run> ...] [--top 15]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SLOTS = ("Weapon 1", "Weapon 2", "Body Armour", "Helmet", "Gloves", "Boots", "Amulet", "Ring 1", "Ring 2", "Belt")
SUMMARY_TOKENS = ("life T", "objective_line", "resistance_fixed", "attribute")
FLEXIBLE = ("objective_line", "attribute")

_SUMMARY = re.compile(r"^  (" + "|".join(re.escape(s) for s in SLOTS) + r"): (.*)$")
_TIER = re.compile(r"^(?:T\d+\s+T\d+/\d+|\{crafted\})\s+")
_DELTA = re.compile(r",\s*delta\s+([\d,]+)\.?\s*$")
_RANGE = re.compile(r"\([^()]*\)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Line:
    """One flexible gear line: its kind, its objective delta and normalised mod text."""

    kind: str
    value: int
    text: str

    @property
    def zero(self) -> bool:
        return self.value == 0


def resolve(arg: str) -> Path:
    """A run folder, a full run name, or a tag: the newest `artifacts/benchmark/*<tag>`."""

    path = Path(arg)
    if path.is_dir():
        return path
    root = ROOT / "artifacts" / "benchmark"
    direct = root / arg
    if direct.is_dir():
        return direct
    matches = sorted(d for d in root.glob(f"*{arg}") if d.is_dir())
    return matches[-1] if matches else direct


def summary_bodies(text: str) -> dict[str, str]:
    """The LAST summary body per slot (kicks print a slot several times)."""

    bodies: dict[str, str] = {}
    for raw in text.splitlines():
        match = _SUMMARY.match(raw)
        if not match:
            continue
        slot, body = match.group(1), match.group(2)
        if not any(token in body for token in SUMMARY_TOKENS):
            continue
        bodies[slot] = body
    return bodies


def _delta_value(part: str) -> int | None:
    match = _DELTA.search(part)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def mod_text(part: str) -> str:
    """The part without its first word, tier token and `, delta`, numbers normalised to `#`."""

    body = part.split(" ", 1)[1] if " " in part else ""
    body = _TIER.sub("", body.strip())
    body = _DELTA.sub("", body)
    body = _RANGE.sub("#", body)
    body = _NUMBER.sub("#", body)
    return body.strip()


def parse_log(text: str) -> list[Line]:
    """Flexible lines of one build log: last summary per slot, weapon shapes skipped."""

    lines: list[Line] = []
    for slot, body in summary_bodies(text).items():
        if slot.startswith("Weapon") and "life T" not in body:
            continue
        for part in body.split("; "):
            kind = part.split(" ", 1)[0]
            if kind not in FLEXIBLE:
                continue
            value = _delta_value(part)
            if value is None:
                continue
            lines.append(Line(kind, value, mod_text(part)))
    return lines


def run_lines(run: Path) -> dict[str, list[Line]]:
    """Per build (log stem) the flexible lines of a run directory."""

    logs = sorted((run / "logs").glob("*.log"))
    return {path.stem: parse_log(path.read_text(encoding="utf-8", errors="replace")) for path in logs}


def _share(part: int, total: int) -> str:
    return "n/a" if total == 0 else f"{100.0 * part / total:.0f}%"


def per_run_table(runs: dict[str, dict[str, list[Line]]]) -> list[str]:
    rows = [
        "| run | builds | flexible lines | objective_line | attribute | +0 lines | +0 share | +0 objective_line | +0 attribute |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, builds_by_log in runs.items():
        all_lines = [line for build_lines in builds_by_log.values() for line in build_lines]
        flexible = len(all_lines)
        objective = sum(1 for line in all_lines if line.kind == "objective_line")
        attribute = sum(1 for line in all_lines if line.kind == "attribute")
        zero = [line for line in all_lines if line.zero]
        zero_objective = sum(1 for line in zero if line.kind == "objective_line")
        zero_attribute = sum(1 for line in zero if line.kind == "attribute")
        rows.append(
            f"| {name} | {len(builds_by_log)} | {flexible} | {objective} | {attribute} | {len(zero)} | "
            f"{_share(len(zero), flexible)} | {zero_objective} | {zero_attribute} |"
        )
    return rows


def top_table(all_lines: list[Line], top: int) -> list[str]:
    counts = Counter(line.text for line in all_lines if line.zero)
    lines = ["", "| +0 mod text | count |", "|---|---:|"]
    for text, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:top]:
        lines.append(f"| {text} | {count} |")
    return lines


def per_build_table(builds: list[tuple[str, list[Line]]], top: int = 12) -> list[str]:
    rows = []
    for name, lines_ in builds:
        flexible = len(lines_)
        zero = sum(1 for line in lines_ if line.zero)
        rows.append((name, flexible, zero))
    rows.sort(key=lambda row: (-row[2], row[0]))
    lines = ["", "| build | flexible | +0 |", "|---|---:|---:|"]
    for name, flexible, zero in rows[:top]:
        lines.append(f"| {name} | {flexible} | {zero} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", help="run directory, full run name, or tag")
    parser.add_argument("--top", type=int, default=15, help="most common +0 mod texts to print")
    args = parser.parse_args()

    runs: dict[str, dict[str, list[Line]]] = {}
    builds: list[tuple[str, list[Line]]] = []
    for arg in args.runs:
        run = resolve(arg)
        if not run.is_dir():
            print(f"no such run: {arg} -> {run}")
            return 1
        builds_by_name = run_lines(run)
        runs[run.name] = builds_by_name
        builds.extend(builds_by_name.items())

    for row in per_run_table(runs):
        print(row)
    for row in top_table([line for _, lines_ in builds for line in lines_], args.top):
        print(row)
    for row in per_build_table(builds):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())