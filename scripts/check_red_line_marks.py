"""#1123 unit 1 (b): check the red-line marks (the marks rule of the issue) against the red set, the schema, the zero rule and PoB's parse.

Input: a marks file (a JSON list of records, or {"records": [...]}) or a folder of such part files (read in name order).
A record is {line, surfaces[], sources[], group, kind, boss_lane[], optimistic_lane[], zero_reason, why, partial_part, formula?,
type?, vars?, stand_blind?}; `stand_blind` = {reason_kind (one of STAND_BLIND_KINDS), why} marks a record that moves no PoB
output on any stand (#1123), checked by scripts/red_line_stand_check.py.

Checks (exit 1 on any failure):
- schema: the keys, their types, kind in snake_case, group in GROUPS, no unknown key, why and line not blank, no blank lane line;
- group: a record's group is the group rule's answer for its line (scripts/day1_groups.py);
- missing / extra / duplicates against the distinct red set (scripts/red_line_slices.red_records over the day-1 rows);
  with --slice FILE the expected set is the slice file's lines and marks for other lines are ignored;
- zero rule: a record with both lanes empty has a zero_reason that names a verdict or a kind of
  src/junkroan/mechanics/unsupported_lines.json;
- boss lane: a new kind (not in unsupported_lines.json) has an empty boss lane, except the BOSS_LANE_KINDS
  (ramp_window, proxy_delivery), whose boss lane must equal their optimistic lane (lane_equality_errors);
- parse (row 2): every distinct non-empty lane line goes through PobSession.parse_mods in batches of 100 and must give
  ok true, unsupported empty, extra empty. --no-parse skips this check (PoB-free).

Run: `python scripts/check_red_line_marks.py <marks.json | folder> [--slice FILE] [--no-parse]`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_groups import GROUPS, group_of  # noqa: E402

UNSUPPORTED_KINDS = ROOT / "src" / "junkroan" / "mechanics" / "unsupported_lines.json"
# The owner's standing verdicts the marks apply (issue #1123), by the words a zero_reason uses (matched case-insensitively).
VERDICT_TOKENS: dict[str, str] = {
    "ramp_window": "a ramp (Rage, stacks, Pride, Sigil stages) counts at the loadout's ramp window (2.5 s on day 1), never at the cap",
    "guard_skill": "a guard skill (Steelskin, Immortal Call, Molten Shell) counts 0 on every lane",
    "cooldown": "a cooldown-limited buff counts 0 on every lane",
    "on_kill": "an on-kill effect counts 0 on the boss lane (the JSON enablers aside), counted on the optimistic lane",
    "first_seconds": "an effect on the enemy at full life, or in its first seconds only, counts 0 on the boss lane",
    "steal": "stealing charges or resources counts 0 on every lane",
    "mana_sustain": "mana on kill and a mana flask below 100 % uptime never count as sustain",
    "uptime_dependent": "a duration's uptime decides the worth: optimistic lane at full uptime, empty boss lane (parked #965)",
    "proxy_delivery": "on-hit, on-kill and leech of a proxy (totem, trap, mine) go to the proxy, not the player",
}
# The two kinds whose boss lane is not empty: the owner's verdict counts them on both lanes, so the boss lane must
# equal the optimistic lane (list equality, in order). Any other new kind keeps an empty boss lane.
BOSS_LANE_KINDS = ("ramp_window", "proxy_delivery")
BATCH_SIZE = 100
LANES = ("boss_lane", "optimistic_lane")
REQUIRED: dict[str, type] = {
    "line": str, "surfaces": list, "sources": list, "group": str, "kind": str,
    "boss_lane": list, "optimistic_lane": list, "zero_reason": str, "why": str, "partial_part": str,
}
OPTIONAL: dict[str, type] = {"formula": str, "type": str, "vars": dict, "stand_blind": dict}
STAND_TYPES = ("spell", "attack", "minion", "any")
# #1123 (brain's rule A): why a red-line mark moves no PoB output on any stand, though its lanes are not zero.
STAND_BLIND_KINDS = ("trap", "totem", "shield", "minion", "flag-only", "charge-without-consumer", "uptime-saturated",
                     "mechanic-absent")
_KIND = re.compile(r"^[a-z][a-z0-9_]*$")

ParseMods = Callable[[list[str]], Sequence[Mapping[str, Any]]]


def line_text(line: Any) -> str:
    return " ".join(str(line).split())


def json_kind_ids() -> tuple[str, ...]:
    """The kind ids of src/junkroan/mechanics/unsupported_lines.json (the eight known kinds)."""

    return tuple(k["id"] for k in json.loads(UNSUPPORTED_KINDS.read_text(encoding="utf-8"))["kinds"])


def zero_tokens() -> tuple[str, ...]:
    """The words a zero_reason may name: the verdict tokens and the kind ids of unsupported_lines.json."""

    return tuple(VERDICT_TOKENS) + json_kind_ids()


def _words(text: str) -> str:
    return re.sub(r"[\s\-]+", "_", text.lower())


def names_a_verdict(zero_reason: str, tokens: Sequence[str]) -> bool:
    text = _words(zero_reason)
    return any(token in text for token in tokens)


def check_schema(record: Any) -> list[str]:
    """Every break of the marks schema in one record, as text; [] when the record is well formed."""

    if not isinstance(record, Mapping):
        return ["record is not an object"]
    errors: list[str] = []
    for key, kind in REQUIRED.items():
        if key not in record:
            errors.append(f"missing {key}")
        elif not isinstance(record[key], kind):
            errors.append(f"{key} is not {kind.__name__}")
    for key, kind in OPTIONAL.items():
        if key in record and not isinstance(record[key], kind):
            errors.append(f"{key} is not {kind.__name__}")
    if isinstance(record.get("type"), str) and record["type"] not in STAND_TYPES:
        errors.append(f"type {record['type']} is not one of {STAND_TYPES}")
    for key in record:
        if key not in REQUIRED and key not in OPTIONAL:
            errors.append(f"unknown key {key}")
    for key in ("surfaces", "sources", *LANES):
        value = record.get(key)
        if isinstance(value, list) and any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"{key} has a blank or non-text item")
    if isinstance(record.get("line"), str) and not record["line"].strip():
        errors.append("line is blank")
    if isinstance(record.get("group"), str) and record["group"] not in GROUPS:
        errors.append(f"unknown group {record['group']}")
    if isinstance(record.get("kind"), str) and not _KIND.match(record["kind"]):
        errors.append(f"kind {record['kind']!r} is not snake_case")
    if isinstance(record.get("why"), str) and not record["why"].strip():
        errors.append("why is empty")
    stand_blind = record.get("stand_blind")
    if isinstance(stand_blind, Mapping):
        if stand_blind.get("reason_kind") not in STAND_BLIND_KINDS:
            errors.append(f"stand_blind reason_kind {stand_blind.get('reason_kind')!r} is not one of {STAND_BLIND_KINDS}")
        if not isinstance(stand_blind.get("why"), str) or not stand_blind["why"].strip():
            errors.append("stand_blind why is blank or missing")
    return errors


def _records_of(payload: Any, source: Path) -> list[Any]:
    if isinstance(payload, Mapping):
        payload = payload.get("records")
    if not isinstance(payload, list):
        raise ValueError(f"{source}: no list of records")
    return payload


def load_marks(path: Path) -> list[Any]:
    """The records of a marks file, or of every *.json part file of a folder (name order)."""

    if path.is_dir():
        out: list[Any] = []
        for part in sorted(path.glob("*.json")):
            out += _records_of(json.loads(part.read_text(encoding="utf-8")), part)
        return out
    return _records_of(json.loads(path.read_text(encoding="utf-8")), path)


def load_slice(path: Path) -> dict[str, str | None]:
    """The distinct line texts of a slice file with their outcome (scripts/red_line_slices.py); None when a record has none."""

    return {line_text(r["line"]): r.get("outcome") for r in _records_of(json.loads(path.read_text(encoding="utf-8")), path)}


def _parse_problem(result: Mapping[str, Any]) -> str:
    problems = []
    if result.get("ok") is not True:
        problems.append("ok is not true")
    if result.get("unsupported"):
        problems.append(f"unsupported: {result.get('unsupported')}")
    if str(result.get("extra") or "").strip():
        problems.append(f"extra: {result.get('extra')}")
    return "; ".join(problems)


def _parse_lane_lines(lines: Sequence[str], parse_mods: ParseMods, batch_size: int) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for start in range(0, len(lines), batch_size):
        batch = list(lines[start:start + batch_size])
        results = {str(result.get("line")): result for result in parse_mods(batch)}
        for line in batch:
            if line not in results:
                failures.append({"line": line, "reason": "no result from PoB"})
                continue
            problem = _parse_problem(results[line])
            if problem:
                failures.append({"line": line, "reason": problem})
    return failures


def check_marks(
    records: Iterable[Any],
    expected: Iterable[str] | Mapping[str, str | None],
    *,
    parse_mods: ParseMods | None = None,
    batch_size: int = BATCH_SIZE,
    scoped: bool = False,
    tokens: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Checks the records against the expected red lines.

    `expected` is the set of line texts, or a mapping line -> outcome (`partial` / `none`), which also enables the
    partial_part rule. `scoped`: records of other lines are ignored, not extra. `parse_mods` None skips the parse
    check. `tokens` (default: zero_tokens()) are the words a zero_reason may name.
    """

    outcomes: dict[str, str | None] = {}
    if isinstance(expected, Mapping):
        outcomes = {line_text(line): outcome for line, outcome in expected.items()}
        expected = set(outcomes)
    else:
        expected = set(expected)
    tokens = zero_tokens() if tokens is None else tokens
    kinds = set(json_kind_ids())
    seen: Counter[str] = Counter()
    schema_errors: list[dict[str, Any]] = []
    group_errors: list[str] = []
    zero_errors: list[str] = []
    partial_part_errors: list[str] = []
    kind_errors: list[str] = []
    lane_equality_errors: list[str] = []
    boss_kind_total = 0
    boss_kind_with_boss = 0
    new_kind_lines: dict[str, set[str]] = {}
    kept: list[Mapping[str, Any]] = []
    ignored = 0
    for index, record in enumerate(records):
        line = line_text(record["line"]) if isinstance(record, Mapping) and isinstance(record.get("line"), str) else None
        if line is None:
            schema_errors.append({"index": index, "line": None, "errors": check_schema(record)})
            continue
        if scoped and line not in expected:
            ignored += 1
            continue
        seen[line] += 1
        errors = check_schema(record)
        if errors:
            schema_errors.append({"index": index, "line": line, "errors": errors})
            continue
        if record["group"] != group_of(line):
            group_errors.append(line)
        if not record["boss_lane"] and not record["optimistic_lane"] and not names_a_verdict(record["zero_reason"], tokens):
            zero_errors.append(line)
        outcome = outcomes.get(line)
        if outcome == "partial" and not record["partial_part"].strip():
            partial_part_errors.append(line)
        if outcome == "none" and record["partial_part"].strip():
            partial_part_errors.append(line)
        if record["kind"] not in kinds:
            new_kind_lines.setdefault(record["kind"], set()).add(line)
            if record["boss_lane"] and record["kind"] not in BOSS_LANE_KINDS:
                kind_errors.append(line)
        if record["kind"] in BOSS_LANE_KINDS:
            boss_kind_total += 1
            if record["boss_lane"]:
                boss_kind_with_boss += 1
            if record["boss_lane"] != record["optimistic_lane"]:
                lane_equality_errors.append(line)
        kept.append(record)

    lane_lines = sorted({
        line.replace("{formula}", "10").strip() for record in kept for lane in LANES for line in record[lane] if line.strip()
    })
    parse_failures = [] if parse_mods is None else _parse_lane_lines(lane_lines, parse_mods, batch_size)
    missing = sorted(expected - set(seen))
    extra = [] if scoped else sorted(set(seen) - expected)
    duplicates = {line: n for line, n in sorted(seen.items()) if n > 1}
    new_kinds = {
        kind: {"lines": len(lines), "examples": sorted(lines)[:3]} for kind, lines in sorted(new_kind_lines.items())
    }
    report = {
        "records": sum(seen.values()),
        "expected": len(expected),
        "distinct_lines": len(seen),
        "ignored": ignored,
        "missing": missing,
        "extra": extra,
        "duplicates": duplicates,
        "schema_errors": schema_errors,
        "group_errors": group_errors,
        "zero_errors": zero_errors,
        "partial_part_errors": partial_part_errors,
        "kind_errors": kind_errors,
        "lane_equality_errors": lane_equality_errors,
        "boss_lane_kinds": {"with_boss_lane": boss_kind_with_boss, "total": boss_kind_total},
        "new_kinds": new_kinds,
        "lane_lines": len(lane_lines),
        "parse_checked": parse_mods is not None,
        "parse_failures": parse_failures,
    }
    report["ok"] = not (missing or extra or duplicates or schema_errors or group_errors or zero_errors
                        or partial_part_errors or kind_errors or lane_equality_errors or parse_failures)
    return report


def print_report(report: Mapping[str, Any]) -> None:
    print(f"records: {report['records']} (distinct lines {report['distinct_lines']}, expected {report['expected']}"
          f"{', ignored ' + str(report['ignored']) if report['ignored'] else ''})")
    print(f"missing: {len(report['missing'])}" + "".join(f"\n  {line}" for line in report["missing"][:20]))
    print(f"extra: {len(report['extra'])}; duplicates: {len(report['duplicates'])} lines")
    for line, n in report["duplicates"].items():
        print(f"  {n}x {line}")
    print(f"schema errors: {len(report['schema_errors'])}")
    for item in report["schema_errors"][:20]:
        print(f"  record {item['index']} ({item['line']}): {'; '.join(item['errors'])}")
    print(f"group errors: {len(report['group_errors'])}; zero errors: {len(report['zero_errors'])}; "
          f"partial_part errors: {len(report['partial_part_errors'])}; kind errors: {len(report['kind_errors'])}")
    for line in report["zero_errors"][:20]:
        print(f"  zero without a named verdict or kind: {line}")
    for line in report["partial_part_errors"][:20]:
        print(f"  partial_part does not follow the outcome: {line}")
    for line in report["kind_errors"][:20]:
        print(f"  new kind with a boss lane (must be empty, but ramp_window / proxy_delivery): {line}")
    print(f"lane equality errors: {len(report['lane_equality_errors'])}")
    for line in report["lane_equality_errors"][:20]:
        print(f"  boss lane != optimistic lane: {line}")
    boss_kinds = report["boss_lane_kinds"]
    print(f"ramp_window/proxy_delivery records with a boss lane = {boss_kinds['with_boss_lane']} of {boss_kinds['total']}")
    print(f"new kinds (not in unsupported_lines.json): {len(report['new_kinds'])}")
    for kind, info in report["new_kinds"].items():
        print(f"  {kind}: {info['lines']} lines")
        for example in info["examples"]:
            print(f"    e.g. {example}")
    if report["parse_checked"]:
        print(f"parse: {report['lane_lines']} lane lines, failures {len(report['parse_failures'])}")
        for item in report["parse_failures"]:
            print(f"  {item['line']!r}: {item['reason']}")
    else:
        print(f"parse: skipped (--no-parse), {report['lane_lines']} lane lines")
    print("ok" if report["ok"] else "FAILED")


def _red_lines() -> dict[str, str]:
    """The distinct red lines of the day-1 rows, line -> outcome (file reads only)."""

    from red_line_slices import red_records
    from day1_lines import day1_rows, load_corpus
    from junkroan.optimizer.rails import Rails

    rails = Rails.load()
    return {r["line"]: r["outcome"] for r in red_records(day1_rows(rails, load_corpus(rails)))}


def verdict_help() -> str:
    """The help epilog: the verdict tokens with their meaning, and the JSON kind ids (what a zero_reason may name)."""

    lines = [
        "zero_reason must name one of these verdict tokens (matched case-insensitively), or a kind id of",
        f"src/junkroan/mechanics/unsupported_lines.json ({', '.join(json_kind_ids())}):",
        "",
    ]
    lines += [f"  {token:<18} {meaning}" for token, meaning in VERDICT_TOKENS.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog=verdict_help(), formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("marks", type=Path, help="a marks JSON file, or a folder of part files")
    parser.add_argument("--slice", type=Path, default=None, help="check only this slice file's lines")
    parser.add_argument("--no-parse", action="store_true", help="skip the PoB parse check (schema, counts, zero rule only)")
    args = parser.parse_args(argv)
    records = load_marks(args.marks)
    if args.slice is not None:
        expected, scoped = load_slice(args.slice), True
    else:
        expected, scoped = _red_lines(), False
    if args.no_parse:
        report = check_marks(records, expected, scoped=scoped)
    else:
        from junkroan.pob.session import PobSession

        with PobSession(run_id="red-line-marks-check") as pob:
            report = check_marks(records, expected, parse_mods=pob.parse_mods, scoped=scoped)
    print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
