"""Describe a build the way a person reads a PoB: identity, ascendancy notables,
keystones, notables and mastery effects, gem links, items with their mods,
config inputs that are on, and the headline stats. For looking at a build with
your own eyes (CLAUDE.md: audit AND read the top builds).

    python scripts/describe_build.py "artifacts/search-fireball/01 *.pob.txt"
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.optimizer.tree_hygiene import analyze_tree_leaves, render_tree_leaf_table  # noqa: E402
from junkroan.optimizer.move_ledger import render_move_table, render_pob_calls  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.pob.skill_facts import flat_reservation_aura_effect_ids  # noqa: E402
from junkroan.search.hypothesis import ascendancies  # noqa: E402
from junkroan.search.hypothesis import active_gems  # noqa: E402

STATS = ("CombinedDPS", "FullDPS", "Life", "EnergyShield", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist", "EffectiveMovementSpeedMod",
         "Str", "Dex", "Int", "ManaUnreserved", "ManaCost", "ManaPerSecondCost", "ManaRegenRecovery", "ManaLeechGainRate", "LifeCost", "LifePerSecondCost",
         "LifeRegenRecovery", "LifeLeechGainRate", "CritChance", "CritMultiplier", "HitChance", "Speed", "AverageDamage", "IgniteChance", "ShockChance")


def _ledger_row(path: Path) -> dict:
    """Read the persisted search or benchmark row for a delivered build."""

    stem = path.name.removesuffix(".pob.txt")
    # Search writes one JSON payload beside each delivered import code. Prefer it
    # over an ancestor's unrelated benchmark results file.
    adjacent = path.with_name(f"{stem}.json")
    if adjacent.is_file():
        try:
            row = json.loads(adjacent.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            row = None
        if isinstance(row, dict) and row.get("ok"):
            return row
    for parent in (path.parent, *path.parents):
        results = parent / "results.json"
        if not results.is_file():
            continue
        try:
            payload = json.loads(results.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = payload.get("rows", []) if isinstance(payload, dict) else payload
        for row in rows if isinstance(rows, list) else ():
            if isinstance(row, dict) and row.get("ok") and f"{row.get('slug')}-s{row.get('seed')}" == stem:
                return row
    return {}


def describe(xml: str, pob: PobSession) -> str:
    root = ET.fromstring(xml)
    build = root.find("Build")
    graph = TreeGraph.load()
    out = [f"{build.get('className')}/{build.get('ascendClassName')} level {build.get('level')}  bandit {build.get('bandit')}  pantheon {build.get('pantheonMajorGod')}/{build.get('pantheonMinorGod')}"]
    spec = root.find("Tree").find("Spec")
    asc_names = {int(n["node_id"]): n["name"] for a in ascendancies().values() for n in a.get("nodes") or []}
    nodes = parse_allocated_from_xml(xml)
    out.append("ascendancy: " + ", ".join(asc_names[n] for n in nodes if n in asc_names and graph.node(n) is None))
    kinds: dict[str, list[str]] = {"keystone": [], "notable": []}
    for n in nodes:
        node = graph.node(n)
        if node and node.kind in kinds:
            kinds[node.kind].append(node.name)
    out.append(f"keystones: {', '.join(kinds['keystone']) or '-'}")
    out.append(f"notables ({len(kinds['notable'])}): {', '.join(sorted(kinds['notable']))}")
    if spec.get("masteryEffects"):
        effects = []
        for m in spec.get("masteryEffects").strip("{}").split("},{"):
            node_id, effect_id = (int(x) for x in m.strip("{}").split(","))
            node = graph.node(node_id)
            text = next((" / ".join(s) for e, s in (node.mastery_effects if node else ()) if e == effect_id), str(effect_id))
            effects.append(f"{node.name if node else node_id}: {text}")
        out.append("masteries: " + " | ".join(effects))
    out.append(f"tree: {len([n for n in nodes if graph.node(n)])} allocated")
    skills = root.find("Skills")
    rail_level = Rails.load().gems.level
    flat_effects = flat_reservation_aura_effect_ids()
    effects_by_name = {name: str(rec.get("granted_effect_id") or "") for name, rec in active_gems().items()}
    sets = skills.findall("SkillSet")
    groups = sets[0].findall("Skill") if sets else skills.findall("Skill")
    for i, g in enumerate(groups, 1):
        gems = []
        for x in g.findall("Gem"):
            if x.get("enabled", "true") != "true":
                continue
            name, level = x.get("nameSpec"), int(x.get("level") or rail_level)
            suffix = f" (flat-reservation aura, rail {rail_level})" if effects_by_name.get(str(name).lower()) in flat_effects and level != rail_level else ""
            gems.append(f"{name} {level}/{x.get('quality')}{suffix}")
        if gems:
            out.append(f"  link {i} [{g.get('slot') or '?'}]{' (granted)' if g.get('source') else ''}{' MAIN' if str(i) == (build.get('mainSocketGroup') or '1') else ''}: {', '.join(gems)}")
    items = root.find("Items")
    by_id = {i.get("id"): i for i in items.findall("Item")}
    iset = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
    for slot in (iset.findall("Slot") if iset is not None else items.findall("Slot")):
        item = by_id.get(slot.get("itemId") or "")
        if item is None or "Swap" in (slot.get("name") or ""):
            continue
        lines = [l.strip() for l in (item.text or "").splitlines() if l.strip()]
        rarity = lines[0].split(":")[-1].strip()
        mods = [l for l in lines[3:] if not l.startswith(("Unique ID", "Item Level", "Quality", "Sockets", "LevelReq", "Implicits", "Crafted", "Prefix: None", "Suffix: None", "Armour:", "Evasion:", "Energy Shield:", "Ward:", "ArmourBase", "EvasionBase", "EnergyShieldBase", "League:", "Source:", "Variant", "Selected", "Radius", "Limited", "Has Alt", "Talisman", "Catalyst"))]
        out.append(f"  {slot.get('name'):12s} {rarity:6s} {lines[1]}{' / ' + lines[2] if rarity in ('RARE', 'UNIQUE') and len(lines) > 2 and not lines[2].startswith('Unique ID') else ''}: {' | '.join(mods)[:220]}")
    cfg = root.find("Config")
    on = []
    for cs in cfg.findall("ConfigSet") if cfg is not None else []:
        if cs.get("id") == "1":
            on = [f"{i.get('name')}={i.get('boolean') or i.get('number') or i.get('string')}" for i in cs.findall("Input") if i.get("boolean") != "false"]
    out.append("config: " + ", ".join(on))
    pob.load_xml(xml)
    s = pob.stats(STATS)
    out.append("stats: " + ", ".join(f"{k}={v:,.1f}" if isinstance(v, float) else f"{k}={v}" for k, v in s.items()))
    objective = Rails.load().objective(maximize="FullDPS" if float(s.get("FullDPS") or 0.0) > float(s.get("CombinedDPS") or 0.0) else "CombinedDPS")
    out.append(render_tree_leaf_table(analyze_tree_leaves(pob, objective=objective, mastery_context=True), objective=objective))
    return "\n".join(out)


def main() -> int:
    paths = [Path(p) for arg in sys.argv[1:] for p in (glob.glob(arg) or [arg])]
    with PobSession(run_id="describe") as pob:
        for path in paths:
            text = path.read_text(encoding="utf-8").strip()
            xml = text if text.startswith("<") else decode_import_code(text)
            text = describe(xml, pob)
            row = _ledger_row(path)
            if row.get("moves") or row.get("move_rows"):
                text += "\n" + "\n".join(render_move_table(row.get("moves") or row.get("move_rows") or (), heading="loop moves"))
            if row.get("pob_calls"):
                text += "\n" + "\n".join(render_pob_calls(row["pob_calls"], heading="PoB calls"))
            if row.get("tree_churn"):
                text += "\ntree churn: " + ", ".join(f"{key}={value:.4f}" for key, value in sorted(row["tree_churn"].items()))
            print(f"== {path.name}\n{text}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
