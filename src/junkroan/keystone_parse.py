"""Keystone stat lines -> PoB's own parse -> one kind per line (#1030 unit 1).

    python -m junkroan.keystone_parse --out <json>      # one PobSession, writes the rows

Input: every keystone of ``TreeGraph.load()`` (node kind "keystone"). A ``TreeNode.stats`` entry
can hold several lines in one string, so each entry is split on "\\n"; blank pieces are dropped.
Each piece is sent to PoB unchanged (``PobSession.parse_mods``, via ``parse_mods_batch``).

Kind of one line, from its parse row (the parse is data here, no PoB needed to classify).
The first rule that matches wins:

1. ``unparsed``: ``ok`` is false, or ``unsupported`` is true, or ``extra`` holds non-blank
   text (PoB parsed only part of the line), or ``mods`` is empty. The text is kept.
2. ``zero``: a mod of type ``OVERRIDE`` (PoB sets the stat to a fixed value, e.g.
   "Maximum Chance to Dodge Spell Hits is 75%"); or a ``BASE``/``MORE``/``INC`` mod whose
   numeric value is -100 (a stat multiplied to 0: "Removes all mana", and "Maximum Life becomes
   1, Immune to Chaos Damage" carries ChaosDamageTaken MORE -100); or a ``FLAG`` whose name
   matches ``ZERO_FLAG_RE`` (PoB's "cannot" / "no bonus" / "never" / "disabled" flags: Cannot*,
   DealNo*, No<Capital>*, Never*, Disable*, *Immune, *OnlyFromCrit; a ``Condition:`` name is not
   matched unless it carries one of these words). A bool value is never a number here, so FLAG
   True is not -100.
3. ``redirect``: a mod whose name contains ``DamageTakenFrom`` or ``ConvertTo`` (any type), or a
   ``FLAG`` whose name matches ``REDIRECT_FLAG_RE`` (Cost, Reserv, Protects, AppliesTo:
   "Skills Cost Life instead of Mana" is CostLifeInsteadOfMana, "Skills Reserve Life instead of
   Mana" is BloodMagicReserved, "Energy Shield protects Mana instead of Life" is
   EnergyShieldProtectsMana, "Energy Shield Recharge instead applies to Life" is
   EnergyShieldRechargeAppliesToLife). A swap of a mechanic (Weeping Wounds instead of Mana Burn)
   is not a pool move, so it is ``add``. A numeric Cost/Reserv mod (the same resource, e.g. a
   cost increase) is not a redirect.
4. ``add``: everything else.

A keystone's ``kinds`` is the sorted set of its line kinds. The rules read PoB's mod names,
types, values and flags only; no keystone is named in this module.

Known limits of these rules (what the parse does not carry, found in the full run, not guessed):
a BASE value of 1 is not zero (it may add or set; PoB does not say). A flag whose name carries
none of the words above classifies as ``add``: GhostReaver (Ghost Reaver), ZealotsOath (Zealot's
Oath) and Condition:CreateFungalGround (Worship the Blightheart) are such cases. An OVERRIDE to a
fixed non-zero value (Acrobatics' 75% cap, "Multiplier:...=1") is ``zero`` by rule 2 as written.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from junkroan.optimizer.config_rules import parse_mods_batch
from junkroan.optimizer.tree_graph import TreeGraph

KINDS = ("unparsed", "zero", "redirect", "add")
ZERO_VALUE = -100
ZERO_FLAG_RE = re.compile(r"Cannot|DealNo|^No[A-Z]|Never|Disable|Immune|OnlyFromCrit")
REDIRECT_NAME_PARTS = ("DamageTakenFrom", "ConvertTo")
REDIRECT_FLAG_RE = re.compile(r"Cost|Reserv|Protects|AppliesTo")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_unparsed(parsed_line: Mapping[str, Any]) -> bool:
    mods = parsed_line.get("mods") or []
    return (
        not parsed_line.get("ok")
        or bool(parsed_line.get("unsupported"))
        or bool(str(parsed_line.get("extra") or "").strip())
        or not any(isinstance(mod, Mapping) for mod in mods)
    )


def _is_zero_mod(mod: Mapping[str, Any]) -> bool:
    mod_type = str(mod.get("type") or "")
    name = str(mod.get("name") or "")
    if mod_type == "OVERRIDE":
        return True
    if mod_type in {"BASE", "MORE", "INC"} and _is_number(mod.get("value")) and mod["value"] == ZERO_VALUE:
        return True
    return mod_type == "FLAG" and ZERO_FLAG_RE.search(name) is not None


def _is_redirect_mod(mod: Mapping[str, Any]) -> bool:
    mod_type = str(mod.get("type") or "")
    name = str(mod.get("name") or "")
    if any(part in name for part in REDIRECT_NAME_PARTS):
        return True
    return mod_type == "FLAG" and REDIRECT_FLAG_RE.search(name) is not None


def classify_line(parsed_line: Mapping[str, Any]) -> str:
    """Kind of one stat line from its PoB parse row. Pure and deterministic; see the module docstring."""

    if _is_unparsed(parsed_line):
        return "unparsed"
    mods = [mod for mod in parsed_line.get("mods") or [] if isinstance(mod, Mapping)]
    if any(_is_zero_mod(mod) for mod in mods):
        return "zero"
    if any(_is_redirect_mod(mod) for mod in mods):
        return "redirect"
    return "add"


def stat_lines(stats: Iterable[str]) -> list[str]:
    """Split ``TreeNode.stats`` entries on newlines; keep each piece exactly as PoB receives it."""

    out: list[str] = []
    for entry in stats:
        for piece in str(entry).split("\n"):
            if piece.strip():
                out.append(piece)
    return out


def classify_keystone(name: str, stats: Sequence[str], parsed_lines: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One keystone row: ``{"keystone", "lines": [{"text", "kind", "mods"}], "kinds": [sorted unique kinds]}``.

    ``parsed_lines`` are PoB parse rows (each with its exact "line" text). A stat line with no row
    is ``unparsed``: PoB did not answer for it, so nothing is assumed about it.
    """

    by_text: dict[str, Mapping[str, Any]] = {}
    for row in parsed_lines:
        by_text.setdefault(str(row.get("line", "")), row)
    lines: list[dict[str, Any]] = []
    for text in stat_lines(stats):
        parsed = by_text.get(text) or {"line": text, "ok": False, "unsupported": True, "mods": []}
        lines.append(
            {
                "text": text,
                "kind": classify_line(parsed),
                "mods": [dict(mod) for mod in parsed.get("mods") or [] if isinstance(mod, Mapping)],
            }
        )
    return {"keystone": name, "lines": lines, "kinds": sorted({line["kind"] for line in lines})}


def parse_all_keystones(pob: Any) -> list[dict[str, Any]]:
    """Every keystone of the tree, one PoB parse call for all its distinct lines."""

    keystones = sorted(
        (node for node in TreeGraph.load().nodes.values() if node.kind == "keystone"),
        key=lambda node: (node.name, node.node_id),
    )
    all_lines = list(dict.fromkeys(text for node in keystones for text in stat_lines(node.stats)))
    parsed_by_text = parse_mods_batch(pob, all_lines)
    parsed_lines = [dict(parsed_by_text[text], line=text) for text in all_lines if text in parsed_by_text]
    return [classify_keystone(node.name, node.stats, parsed_lines) for node in keystones]


def main(argv: Sequence[str] | None = None) -> int:
    from junkroan.pob.session import PobSession

    parser = argparse.ArgumentParser(description="Classify every keystone stat line through PoB's parser.")
    parser.add_argument("--out", type=Path, required=True, help="JSON file to write the keystone rows to")
    args = parser.parse_args(argv)
    with PobSession(run_id="keystone-parse") as pob:
        rows = parse_all_keystones(pob)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = Counter(line["kind"] for row in rows for line in row["lines"])
    print(f"{len(rows)} keystones -> {args.out}; line kinds " + ", ".join(f"{k} {counts.get(k, 0)}" for k in KINDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
