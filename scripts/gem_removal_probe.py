"""#1204: what each utility gem of a build contributes, measured by PoB by removing it alone.

For a build's import code (`*.pob.txt`) the probe reads the base stats once, then for each gem name disables every
copy of that gem (the rest of the build unchanged), reads the same stats, and reloads the base before the next gem.
Every delta is `with gem - without gem` (base - removed), so its sign is what the gem contributes.

Only the active skill set is measured: a gem that occurs only in an inactive set is a row with `present=no` and no
run. A gem with no copy anywhere in the XML is a row with `present=no` and no run too.

    python scripts/gem_removal_probe.py <run folder>/<build>.pob.txt --out probe.json
    python scripts/gem_removal_probe.py build.pob.txt --gems "Dash,Leap Slam,Smite"

The PoB session opens only in `main()`; `probe_gems` takes any session with `load_xml(str)` and `stats(keys)`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_from_skeleton import xml_with_gems_disabled  # noqa: E402
from junkroan.optimizer.build_result import REPORT_KEYS  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

DEFAULT_GEMS: tuple[str, ...] = (
    "Dash", "Leap Slam", "Faster Attacks", "Momentum", "Flammability", "Malevolence", "Summon Chaos Golem",
    "Herald of Ice", "Pact of Ghorr", "Pyroclast Mine of Sabotage", "Smite", "Herald of Thunder", "Ancestral Cry",
)
# The keys a zero verdict is judged on (the objective and the floor PoB's own damage and EHP stats).
PROBE_KEYS: tuple[str, ...] = ("CombinedDPS", "TotalEHP", "EffectiveMovementSpeedMod")
# Every stat the probe reads on each load: the probe keys first, then the rest of PoB's report keys (the output
# a gem may exist for: Life, resistances, the damage of other kinds). One stats call per load reads all of them.
STAT_KEYS: tuple[str, ...] = PROBE_KEYS + tuple(k for k in REPORT_KEYS if k not in PROBE_KEYS)
# A removal delta counts as zero when |delta| <= ZERO_REL_TOLERANCE * |base value| of that key: relative to the
# build's own scale, so float noise on a big DPS number is still zero and 1e-3 on 1000 is not.
ZERO_REL_TOLERANCE = 1e-9


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read(session: Any) -> dict[str, float | None]:
    raw = session.stats(STAT_KEYS)
    return {key: _num(raw.get(key)) for key in STAT_KEYS}


def _is_zero(base_value: float | None, delta: float | None) -> bool:
    """True when the delta is readable and within ZERO_REL_TOLERANCE of the base value's own scale."""

    return delta is not None and base_value is not None and abs(delta) <= ZERO_REL_TOLERANCE * abs(base_value)


def _enabled_label(flags: list[bool]) -> str:
    if all(flags):
        return "yes"
    if not any(flags):
        return "no"
    return "mixed"


def _active_skill_groups(root: ET.Element) -> list[tuple[int, ET.Element]]:
    """(1-based index, Skill) of every socket group in the active skill set.

    The active set is `<Skills activeSkillSet=...>`; a missing attribute, or one naming no SkillSet, reads the first
    SkillSet. A Skills element with no SkillSet children (an old layout) is its own active set."""

    skills = root.find("Skills")
    if skills is None:
        return []
    skill_sets = skills.findall("SkillSet")
    if not skill_sets:
        return list(enumerate(skills.findall("Skill"), start=1))
    active = skills.get("activeSkillSet")
    chosen = next((s for s in skill_sets if s.get("id") == active), skill_sets[0])
    return list(enumerate(chosen.findall("Skill"), start=1))


def _inventory(xml: str) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """The gems of the active skill set by lowercased nameSpec, and the lowercased names of every gem in the XML.

    An entry holds each active copy's enabled flag, the socket groups it sits in, and each of those groups' enabled
    flag. A copy with no `enabled` attribute reads as enabled (the same rule as `xml_with_gems_disabled`)."""

    root = ET.fromstring(xml)
    active: dict[str, dict[str, Any]] = {}
    for index, skill in _active_skill_groups(root):
        gems = [child for child in skill if child.tag == "Gem"]
        if not gems:
            continue
        group_enabled = skill.get("enabled", "true") == "true"
        label = skill.get("label") or str(gems[0].get("nameSpec") or "").strip()
        group = f"{index}: {label}"
        for gem in gems:
            name = str(gem.get("nameSpec") or "").strip()
            if not name:
                continue
            entry = active.setdefault(name.lower(), {"name": name, "enabled": [], "groups": [], "group_enabled": []})
            entry["enabled"].append(gem.get("enabled", "true") == "true")
            entry["group_enabled"].append(group_enabled)
            if group not in entry["groups"]:
                entry["groups"].append(group)
    anywhere = {str(gem.get("nameSpec") or "").strip().lower() for gem in root.iter("Gem")} - {""}
    return active, anywhere


def _absent_row(name: str, note: str) -> dict[str, Any]:
    return {
        "gem": name, "present": "no", "enabled": "n/a", "group": "", "group_enabled": "n/a", "note": note,
        **{f"delta_{key}": None for key in PROBE_KEYS}, "moved_keys": [], "zero": None, "zero_all": None,
    }


def probe_gems(session: Any, xml: str, gems: Sequence[str]) -> dict[str, Any]:
    """The base stats of `xml` and one row per gem name, each delta being `with gem - without gem` (base - removed).

    Returns `{"base": {key: value}, "rows": [row, ...]}`. A row holds: gem, present (yes/no), enabled (yes/no/mixed,
    the Gem flags of its active copies; n/a when absent), group, group_enabled (yes/no/mixed, the flag of the
    `<Skill>` group holding it), note, delta_CombinedDPS, delta_TotalEHP, delta_EffectiveMovementSpeedMod,
    moved_keys (every other STAT_KEYS key whose delta is non-zero, as `{key, delta}`), zero and zero_all.

    `zero` is True when every PROBE_KEYS delta is zero (`_is_zero`: |delta| <= ZERO_REL_TOLERANCE * |base|).
    `zero_all` is True when `zero` holds and `moved_keys` is empty, i.e. no key at all moved. A delta that cannot
    be read (a non-numeric stat on either load) is None and is not zero. An absent gem has no delta and both
    zero flags None."""

    session.load_xml(xml)
    base = _read(session)
    active, anywhere = _inventory(xml)
    rows: list[dict[str, Any]] = []
    for gem in gems:
        name = str(gem).strip()
        key = name.lower()
        entry = active.get(key)
        if entry is None:
            note = "only in an inactive skill set" if key in anywhere else ""
            rows.append(_absent_row(name, note))
            continue
        session.load_xml(xml_with_gems_disabled(xml, [name]))
        try:
            removed = _read(session)
        finally:
            session.load_xml(xml)  # the base again, before the next gem
        deltas: dict[str, float | None] = {}
        for stat in STAT_KEYS:
            base_value, removed_value = base[stat], removed[stat]
            deltas[stat] = None if base_value is None or removed_value is None else base_value - removed_value
        zero = all(_is_zero(base[k], deltas[k]) for k in PROBE_KEYS)
        moved_keys = [
            {"key": stat, "delta": deltas[stat]}
            for stat in STAT_KEYS
            if stat not in PROBE_KEYS and deltas[stat] is not None and not _is_zero(base[stat], deltas[stat])
        ]
        rows.append({
            "gem": name,
            "present": "yes",
            "enabled": _enabled_label(entry["enabled"]),
            "group": "; ".join(entry["groups"]),
            "group_enabled": _enabled_label(entry["group_enabled"]),
            "note": "",
            **{f"delta_{k}": deltas[k] for k in PROBE_KEYS},
            "moved_keys": moved_keys,
            "zero": zero,
            "zero_all": zero and not moved_keys,
        })
    return {"base": base, "rows": rows}


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:,.1f}"
    return str(value)


def _moved_cell(moved: list[dict[str, Any]]) -> str:
    return "; ".join(f"{m['key']} {m['delta']:+,.1f}" for m in moved) or "-"


def markdown_table(result: dict[str, Any]) -> str:
    """The probe as a markdown table. Every delta is `with gem − without gem`; base values come first."""

    base = result["base"]
    head = ["gem", "present", "enabled", "group", "group_enabled",
            "delta CombinedDPS", "delta TotalEHP", "delta EffectiveMovementSpeedMod",
            "zero", "moved_keys", "zero_all", "note"]
    lines = [
        "delta = with gem − without gem (base − removed). Base: " + ", ".join(f"{k} {_cell(base[k])}" for k in PROBE_KEYS),
        "",
        "| " + " | ".join(head) + " |",
        "|" + "|".join("---" for _ in head) + "|",
    ]
    for row in result["rows"]:
        cells = [row["gem"], row["present"], row["enabled"], row["group"], row["group_enabled"],
                 *(_cell(row[f"delta_{k}"]) for k in PROBE_KEYS),
                 _cell(row["zero"]), _moved_cell(row["moved_keys"]), _cell(row["zero_all"]), row["note"] or "-"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _parse_gems(text: str | None) -> list[str]:
    if text is None:
        return list(DEFAULT_GEMS)
    return [part.strip() for part in text.split(",") if part.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    from junkroan.pob.session import PobSession, decode_import_code

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("build", type=Path, help="a PoB import code file (*.pob.txt)")
    parser.add_argument("--gems", default=None,
                        help=f"comma-separated gem names (default: the {len(DEFAULT_GEMS)} utility gems of #1204)")
    parser.add_argument("--out", type=Path, default=None, help="write the result as JSON to this file")
    args = parser.parse_args(argv)

    xml = decode_import_code(args.build.read_text(encoding="utf-8"))
    gems = _parse_gems(args.gems)
    started = time.perf_counter()
    with PobSession(run_id="gem-removal-probe") as session:
        result = probe_gems(session, xml, gems)
    elapsed = time.perf_counter() - started

    print(markdown_table(result))
    print(f"\n{len(gems)} gems probed in {human_duration(elapsed)}")
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"JSON written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
