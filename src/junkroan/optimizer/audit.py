"""Build audit: the logical checks a person would do by eye on a finished PoB,
run by machine on every build the pipeline emits.

Findings are facts with numbers, never advice. Severity "error" = the build
is not legal or not playable (duplicate mastery effect, legacy unique, a
resource it cannot sustain); "warning" = outside the rails or worth a look.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from xml.etree import ElementTree as ET

from junkroan.optimizer.objective import Objective, _value
from junkroan.optimizer.audit_duration import audit_duration
from junkroan.optimizer.castability import CastabilityMetrics, CostedSkill, LIFE_COST_STAT, MANA_COST_POOL_STAT, MANA_COST_STAT, MANA_OVER_RESERVED_STAT, castability_context, costed_skills, with_castability_floors
from junkroan.optimizer.rails import Rails
from junkroan.pob.bench_mod_ids import crafted_text_families, crafted_text_mods
from junkroan.pob.mod_families import conflicting, families_of
from junkroan.pob.session import PobSession

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
_AFFIX_LINE = re.compile(r"^(?:Prefix|Suffix): (?:\{[^}]*\})*(?P<mod_id>\S+)\s*$")
_DECORATED_LINE = re.compile(r"^(?P<tags>(?:\{[^}]*\})*)(?P<text>.*)$")


@dataclass(slots=True)
class Finding:
    severity: str  # "error" | "warning"
    check: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}: {self.detail}"


@lru_cache(maxsize=1)
def _unique_availability() -> dict[str, dict]:
    recs = json.loads((CORPUS / "uniques.json").read_text(encoding="utf-8"))["records"]
    out: dict[str, dict] = {}
    for r in recs:
        plain = r["name"][: -len(", " + r["base"])] if r["name"].endswith(", " + r["base"]) else r["name"]
        out.setdefault(plain.lower(), r)
    return out


@lru_cache(maxsize=1)
def _ascendancy_node_ids() -> dict[int, bool]:
    """ascendancy node id -> is_start"""

    recs = json.loads((CORPUS / "ascendancies.json").read_text(encoding="utf-8"))["records"]
    return {int(n["node_id"]): bool(n.get("is_ascendancy_start")) for r in recs for n in (r.get("nodes") or [])}


def _allocated_nodes(root: ET.Element) -> set[int]:
    tree = root.find("Tree")
    spec = tree.find("Spec") if tree is not None else None
    if spec is None or not spec.get("nodes"):
        return set()
    return {int(x) for x in spec.get("nodes").split(",") if x.strip().isdigit()}


def _items(xml: str) -> list[tuple[str, list[str]]]:
    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return []
    by_id = {i.get("id"): i for i in items.findall("Item")}
    iset = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
    out = []
    for slot in (iset.findall("Slot") if iset is not None else items.findall("Slot")):
        item = by_id.get(slot.get("itemId") or "")
        if item is not None and "Swap" not in (slot.get("name") or ""):
            out.append((slot.get("name") or "", [line.strip() for line in (item.text or "").splitlines() if line.strip()]))
    return out


def crafted_families(lines: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    """[(craft text, its game mod families)] for the ``{crafted}`` lines of one item's text.

    One bench craft is one mod, so all crafted lines are tried as one mod first (the hybrid
    "+31 to maximum Life / Regenerate 2 Mana per second" is two lines); an item whose lines
    fit no single mod (a multi-modded author's item) has each line resolved alone. A line
    no crafted mod fits has no family and is not judged.
    """

    texts = []
    for line in lines:
        m = _DECORATED_LINE.match(line)
        if m and "{crafted}" in m.group("tags") and m.group("text").strip():
            texts.append(m.group("text").strip())
    if not texts:
        return []
    groups = [texts] if crafted_text_mods(texts) else [[t] for t in texts]
    out = []
    for group in groups:
        families = crafted_text_families(group)
        if families:
            out.append((" / ".join(group), families))
    return out


def crafted_mod_count(lines: list[str]) -> int:
    """Bench crafts on one item (an anoint enchant is not one), a hybrid craft (two lines of one ModMaster entry) counted once."""

    texts = []
    for line in lines:
        m = _DECORATED_LINE.match(line)
        if m and "{crafted}" in m.group("tags") and "{enchant}" not in m.group("tags") and m.group("text").strip():
            texts.append(m.group("text").strip())
    left = list(range(len(texts)))
    count = 0
    while left:
        i = left.pop(0)
        for j in left:
            if crafted_text_mods([texts[i], texts[j]]):
                left.remove(j)
                break
        count += 1
    return count


def audit_flask_slots(xml: str, rails: Rails) -> list[Finding]:
    """#705: one error per empty slot of Flask 1..N while the rails allow flasks (`rails.gear.flasks.slots` > 0).
    #1162: with `flask_utility_crafting` false (day 1) only Flask 1 is crafted, so Flask 2..N are not flagged."""

    worn = {slot for slot, _lines in _items(xml)}
    last = rails.gear.flasks.slots if rails.gear.flasks.flask_utility_crafting else min(1, rails.gear.flasks.slots)
    return [Finding("error", "flask-slot-empty", f"Flask {n} is empty; the rails allow {rails.gear.flasks.slots} flask slots")
            for n in range(1, last + 1) if f"Flask {n}" not in worn]


def _worn_flasks(xml: str) -> list[tuple[str, str, bool, Any]]:
    """[(slot, item name, is unique, flask base)] of the Flask slots that hold a Flask or Tincture base."""

    from junkroan.optimizer.flask_lines import flask_base_of

    out = []
    for slot, lines in _items(xml):
        base = flask_base_of(lines) if slot.startswith("Flask ") else None
        if base is not None:
            out.append((slot, lines[1] if len(lines) > 1 else base.name, bool(lines) and lines[0].endswith("UNIQUE"), base))
    return out


def audit_flask_bases(xml: str, rails: Rails) -> list[Finding]:
    """#1169: a crafted flask or tincture the rails do not allow (`flask_base_allowed`, the flask step's own pool test; #1162 on day 1:
    no utility flask is crafted, only Life, Mana or Hybrid). A unique is not crafted and is judged elsewhere."""

    from junkroan.optimizer.flask_lines import flask_base_allowed

    flasks = rails.gear.flasks
    out = []
    for slot, name, unique, base in _worn_flasks(xml):
        if unique or flask_base_allowed(base, flasks):
            continue
        why = ("the rails allow no tinctures (gear.flasks.tinctures is off)" if base.kind == "tincture" and not flasks.tinctures
               else "the rails craft only Life, Mana or Hybrid flasks (gear.flasks.flask_utility_crafting is off)")
        out.append(Finding("error", "flask-utility-crafted", f"{slot}: {name} ({base.name}, a {base.kind} flask) is crafted; {why}"))
    return out


def audit_weapon_all_gems(xml: str, rails: Rails, forced: Mapping[str, Iterable[str]] | None = None) -> list[Finding]:
    """#1169 (#1152): a day-1 Weapon 1 / Weapon 2 rare with a line the rails forbid on a weapon (`gear.weapon_forbidden_lines`),
    judged by the rail's own `weapon_all_gems_raw`. Day 1 only. A line the request itself forces on that slot (`forced`, the skeleton's forced_affixes) is the rail's only exemption (`unforced_forbidden`); a caller without a skeleton passes none."""

    from junkroan.optimizer.loot_gear import rare_mod_lines, unforced_forbidden, weapon_all_gems_raw, weapon_line_forbidden

    forbidden = tuple(rails.gear.weapon_forbidden_lines)
    if rails.loadout != "day1" or not forbidden:
        return []
    out = []
    for slot, lines in _items(xml):
        if slot not in ("Weapon 1", "Weapon 2"):
            continue
        slot_forbidden = unforced_forbidden(forbidden, (forced or {}).get(slot))
        if not weapon_all_gems_raw(slot, "\n".join(lines), slot_forbidden):
            continue
        line = next(ln for ln in rare_mod_lines(lines) if weapon_line_forbidden(ln, slot_forbidden))
        out.append(Finding("error", "weapon-all-gems-level", f"{slot}: {lines[2]} carries '{line}'; the rails forbid it on a day-1 weapon (gear.weapon_forbidden_lines)"))
    return out


def audit_excluded_bases(xml: str, rails: Rails) -> list[Finding]:
    """#1169 (#1154): a worn item whose base is one the loaded loadout never offers (`excluded_of`, `gear.bases_excluded_by_loadout`:
    Prismatic Ring before endgame). The base is the item's third line (rare, unique) or its second (a name-less base line); nothing is
    excluded on the endgame loadout, so nothing is flagged there."""

    from junkroan.optimizer.item_bases import excluded_of

    excluded = excluded_of(rails)
    if not excluded:
        return []
    out = []
    for slot, lines in _items(xml):
        base = next((ln for ln in lines[1:3] if ln.strip().casefold() in excluded), None)
        if base is not None:
            out.append(Finding("error", "base-excluded-by-loadout", f"{base} in {slot}: excluded before endgame (gear.bases_excluded_by_loadout, loadout {rails.loadout})"))
    return out


def audit_shield_gem_level(xml: str) -> list[Finding]:
    """#1169 (#601): a rare Weapon 2 Shield with a gem-level line AND another mod, judged by the rail's `is_shield_gem_level_with_other`
    (the gem line takes the whole shield)."""

    from junkroan.optimizer.loot_gear import rare_mod_lines
    from junkroan.optimizer.wishlist_gear import is_shield_gem_level_with_other

    out = []
    for slot, lines in _items(xml):
        if is_shield_gem_level_with_other(slot, "\n".join(lines)):
            mods = "; ".join(f"'{ln}'" for ln in rare_mod_lines(lines))
            out.append(Finding("error", "shield-gem-level-with-other", f"{slot}: {lines[2]} is a Shield with a gem-level line and other mods ({mods}); the gem line takes the whole shield (#601)"))
    return out


def audit_flask_uptime(pob: Any, xml: str) -> list[Finding]:
    """#1169, D115: a utility flask whose "Flask uptime" in PoB is not 100 % is inactive and PoB counts none of its effect.

    A Life, Mana or Hybrid flask is not judged: PoB prints no uptime line for an instant recovery and never makes it active."""

    worn = [(slot, name, base) for slot, name, _unique, base in _worn_flasks(xml) if base.kind == "utility"]
    if not worn:
        return []
    uptimes = pob.flask_uptimes()
    out = []
    for slot, name, _base in worn:
        info = uptimes.get(slot) or {}
        if not info.get("full"):
            line = info.get("line")
            out.append(Finding("error", "flask-uptime", f"{slot}: {name} is inactive: PoB prints '{line}'" if line else f"{slot}: {name} is inactive: PoB prints no 'Flask uptime' line for it"))
    return out


def audit_movement(root: ET.Element, rails: Rails, weapon1_type: str = "") -> list[Finding]:
    """#1169: the rails' movement pair (#1153) read off the build's enabled socket groups, by the generator's own predicates.

    `movement-pair-missing`: no gem of the movement spell slot and/or of the movement skill slot (`movement_kinds_missing`); a build
    with `movement_skill_skip_weapon` in Weapon 1 may skip the skill (the rail decides that on Leap Slam's PoB Attack Time, which
    XML does not hold), so only its missing spell is named. `movement-gem-refused`: a gem the rails refuse in both slots
    (`refused_movement_gems`: Smoke Mine, Lightning Warp). Nothing when the rails require no pair."""

    from junkroan.search.generator import movement_kinds_missing, movement_rails, refused_movement_gems
    from junkroan.search.skeleton import SocketGroup

    movement = movement_rails(rails)
    skills = root.find("Skills")
    if movement is None or skills is None:
        return []
    active = skills.find(f"SkillSet[@id='{skills.get('activeSkillSet') or '1'}']")
    groups = []
    for group in (active if active is not None else skills).findall("Skill"):
        if group.get("enabled", "true") != "true" or group.get("source"):
            continue
        gems = [str(g.get("nameSpec") or "") for g in group.findall("Gem") if g.get("enabled", "true") == "true"]
        groups.append(SocketGroup(gems=gems, slot=group.get("slot") or ""))
    out = []
    missing = movement_kinds_missing(groups, [], rails)
    if "skill" in missing and movement.skill_skip_weapon and weapon1_type == movement.skill_skip_weapon:
        missing.remove("skill")
    if missing:
        parts = [f"no movement {kind}: none of {', '.join(movement.spell if kind == 'spell' else movement.skill)} in an enabled socket group" for kind in missing]
        out.append(Finding("error", "movement-pair-missing", "; ".join(parts)))
    for group in groups:
        for gem in refused_movement_gems(group.gems, rails):
            out.append(Finding("error", "movement-gem-refused", f"{group.slot}: {gem} is socketed; the rails refuse {', '.join(movement.forbidden)} as the movement spell or skill"))
    return out


def _weapon1_type(xml: str) -> str:
    """The item type of the Weapon 1 base (a rare's or unique's third text line is its base), "" when unknown."""

    from junkroan.search.hypothesis import item_bases

    for slot, lines in _items(xml):
        if slot == "Weapon 1":
            return next((str(item_bases()[line.lower()].get("type") or "") for line in lines[:3] if line.lower() in item_bases()), "")
    return ""


def audit_xml(xml: str, rails: Rails | None = None, forced: Mapping[str, Iterable[str]] | None = None) -> list[Finding]:
    """Checks that need only the build XML."""

    rails = rails or Rails.load()
    findings: list[Finding] = []
    root = ET.fromstring(xml)
    tree = root.find("Tree")
    spec = tree.find("Spec") if tree is not None else None
    if spec is not None and spec.get("masteryEffects"):
        pairs = [tuple(int(x) for x in m.strip("{}").split(",")) for m in spec.get("masteryEffects").strip("{}").split("},{") if m]
        dupes = {e: n for e, n in Counter(e for _node, e in pairs).items() if n > 1}
        for effect, n in dupes.items():
            findings.append(Finding("error", "duplicate mastery effect", f"effect {effect} selected on {n} mastery nodes; the game allows each effect once"))
    asc_ids = _ascendancy_node_ids()
    asc_taken = [n for n in _allocated_nodes(root) if n in asc_ids and not asc_ids[n]]
    if len(asc_taken) > rails.ascendancy_points:
        findings.append(Finding("error", "ascendancy points", f"{len(asc_taken)} ascendancy nodes allocated; the rails allow {rails.ascendancy_points} (4 labs)"))
    findings.extend(audit_flask_slots(xml, rails))
    findings.extend(audit_flask_bases(xml, rails))
    findings.extend(audit_weapon_all_gems(xml, rails, forced))
    findings.extend(audit_excluded_bases(xml, rails))
    findings.extend(audit_shield_gem_level(xml))
    avail = _unique_availability()
    for slot, lines in _items(xml):
        # our loot / crafted rares keep their "Prefix: {range:x}<mod id>" lines: two mods of one
        # game mod family is an item the game cannot make, whatever PoB's own group field says
        ids = [m.group("mod_id") for m in (_AFFIX_LINE.match(line) for line in lines) if m and m.group("mod_id") != "None"]
        for mod_a, mod_b, family in conflicting(ids):
            findings.append(Finding("error", "mod family", f"{slot}: {mod_a} and {mod_b} are both family {family}; an item can carry only one mod of a family"))
        # the bench craft is text with its numbers rolled ("{crafted}+31 to maximum Life"), no id:
        # recognised by the crafted mods whose lines it fits, then judged on the same families
        for text, families in crafted_families(lines):
            for mod_id in ids:
                shared = sorted(set(families) & set(families_of(mod_id)))
                if shared:
                    findings.append(Finding("error", "mod family", f"{slot}: the bench craft '{text}' and {mod_id} are both family {shared[0]}; an item can carry only one mod of a family"))
        limit = 3 if any("can have up to 3 crafted modifiers" in line.lower() for line in lines) else 1
        n_crafts = crafted_mod_count(lines)
        if n_crafts > limit:
            findings.append(Finding("error", "crafted mod count", f"{slot}: {n_crafts} bench crafts; an item carries {limit} unless it has 'Can have up to 3 Crafted Modifiers'"))
        if not lines or not lines[0].endswith("UNIQUE"):
            continue
        name = lines[1]
        rec = avail.get(name.lower())
        if rec is None:
            findings.append(Finding("warning", "unknown unique", f"{slot}: {name} is not in the uniques corpus"))
            continue
        cls, source, tier = rec.get("availability", "core"), rec.get("source"), rec.get("tier")
        if cls == "legacy":
            findings.append(Finding("error", "legacy unique", f"{slot}: {name} is no longer obtainable ({source or 'wiki: drop disabled'})"))
        elif not rails.unique_allowed(rec):
            findings.append(Finding("warning", "unique outside the rails", f"{slot}: {name} is {cls}, tier {'T' + str(tier) if tier is not None else 'unknown'} ({source or 'world drop'})"))
    skills = root.find("Skills")
    if skills is not None:
        for group in skills.iter("Skill"):
            if group.get("source"):
                continue  # granted by the tree / an item (Guardian relics), not a socketed gem
            for gem in group.findall("Gem"):
                if gem.get("enabled", "true") == "true" and (int(gem.get("level") or 0) > rails.gems.level or int(gem.get("quality") or 0) > max(rails.gems.quality, rails.gems.main_quality)):
                    findings.append(Finding("warning", "gem above the rails", f"{gem.get('nameSpec')} L{gem.get('level')} Q{gem.get('quality')} (rails {rails.gems.level}/{rails.gems.quality})"))
                if gem.get("enabled", "true") == "true":
                    findings.extend(audit_buff_uptime(str(gem.get("nameSpec") or "")))
        findings.extend(audit_movement(root, rails, _weapon1_type(xml)))
        findings.extend(audit_corpse_source(skills))
        findings.extend(audit_dead_support_groups(skills))
    return findings


def worn_unique_names(xml: str) -> set[str]:
    """The names of the UNIQUE items worn in the active item set (any slot, swaps included)."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return set()
    by_id = {i.get("id"): (i.text or "") for i in items.findall("Item")}
    active = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
    worn = set()
    for slot in (active.findall("Slot") if active is not None else items.findall("Slot")):
        iid = slot.get("itemId") or ""
        text = by_id.get(iid)
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 2 and lines[0].endswith("UNIQUE"):
            worn.add(lines[1])
    return worn


def audit_skeleton_uniques(xml: str, uniques: Mapping[str, str]) -> list[Finding]:
    """A unique the skeleton asked for that is not on the build (pure XML, no PoB).

    PoB's ``ItemSlotClass:Populate()`` (``vendor/pob/source/src/Classes/ItemSlotControl.lua:94``)
    clears a slot whose item is not valid for it without a word, at the end of every equip; a
    gear pass that empties Weapon 1 takes a unique quiver in Weapon 2 with it, and the fill that
    follows never puts it back. The item stays in the list, unworn, so the build is judged without
    it. ``uniques`` is the skeleton's ``{slot: name}``, the same mapping the pipeline equips.
    """

    worn = worn_unique_names(xml)
    return [Finding("error", "skeleton unique not equipped", f"{slot}: {name}")
            for slot, name in uniques.items() if name and name not in worn]


def dead_support_group(names: Sequence[str]) -> bool:
    """Every gem in the group is a support: it supports nothing. The one definition, used by the
    audit below and by the skeleton derivation, which does not carry such a group in at all."""

    from junkroan.search.hypothesis import active_gems, support_gems

    supports, actives = support_gems(), active_gems()
    live = [str(n) for n in names if n]
    return bool(live) and all(n.lower() in supports and n.lower() not in actives for n in live)


def audit_dead_support_groups(skills: ET.Element) -> list[Finding]:
    """An enabled socket group with nothing but support gems in it: a support with no active gem
    beside it supports nothing, so the group is dead weight in sockets the build could use
    (the author's weapon-swap "Arcane Surge + Elemental Focus" carried in as a live group)."""

    findings: list[Finding] = []
    for group in skills.iter("Skill"):
        if group.get("enabled", "true") != "true":
            continue
        names = [str(gem.get("nameSpec") or "") for gem in group.findall("Gem") if gem.get("enabled", "true") == "true" and gem.get("nameSpec")]
        if not names:
            continue
        if dead_support_group(names):
            findings.append(Finding("warning", "dead support group", f"{', '.join(names)}: {'a support' if len(names) == 1 else 'supports'} with no active gem to support"))
    return findings


def audit_corpse_source(skills: ET.Element) -> list[Finding]:
    """A corpse-fed skill with nothing to feed it: Volatile Dead eats 3 corpses per cast, and
    without a creator (Desecrate, Unearth) in the build it fires on whatever the map left lying
    around. PoB counts the instances anyway, so the number is a fiction (D57 rule 2)."""

    from junkroan.pob.skill_facts import corpses_consumed_per_cast, corpses_created_per_cast

    consumers: list[tuple[str, int]] = []
    creates = False
    for group in skills.iter("Skill"):
        if group.get("enabled", "true") != "true":
            continue
        for gem in group.findall("Gem"):
            skill_id = str(gem.get("skillId") or "")
            if not skill_id or gem.get("enabled", "true") != "true":
                continue
            eaten = corpses_consumed_per_cast(skill_id)
            if eaten:
                consumers.append((str(gem.get("nameSpec") or skill_id), eaten))
            if corpses_created_per_cast(skill_id) is not None:
                creates = True
    if creates:
        return []
    return [Finding("error", "corpse source", f"{name} consumes {eaten} corpses per cast and nothing in the build creates corpses") for name, eaten in consumers]


def audit_buff_uptime(gem_name: str) -> list[Finding]:
    """A self-buff skill with a cooldown longer than its buff: PoB applies the buff all
    the time; the number is optimistic by the uptime (Ambush: 1.5 s per 5 s, D46)."""

    from junkroan.pob.skill_facts import buff_uptime
    from junkroan.search.hypothesis import active_gems

    rec = active_gems().get(gem_name.lower())
    if not rec:
        return []
    uptime = buff_uptime(str(rec.get("granted_effect_id") or ""))
    if uptime is not None and uptime < 0.9:
        return [Finding("warning", "buff uptime", f"{gem_name}: PoB keeps its buff on all the time, real uptime ~{uptime:.0%} (cooldown vs duration)")]
    return []


def audit_stats(stats: dict[str, Any], objective: Objective) -> list[Finding]:
    """Every objective floor/relation the build misses, with the numbers."""

    from junkroan.optimizer.pipeline import FEASIBILITY_TOLERANCE  # pipeline imports this module

    findings: list[Finding] = []
    if objective.derived:
        stats = {**stats, **objective.derived_values(stats)}
    for stat, floor in objective.floors.items():
        v = _value(stats, stat)
        if v is None or v < floor - FEASIBILITY_TOLERANCE:  # the loop's own slack (1.19999 vs 1.2 is no miss); every missed floor is an error (#553)
            shown = "missing" if v is None else (f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}")  # 1.19 against a floor of 1.2 must not print as "1.2 < 1.2"
            findings.append(Finding("error", "floor", f"{stat} = {shown} < {floor:g}"))
    for stat, ceiling in objective.ceilings.items():
        v = _value(stats, stat)
        if v is not None and v > ceiling:
            findings.append(Finding("error", "ceiling", f"{stat} = {v:.1f} > {ceiling:g}"))
    for rel in objective.relations:
        a, b, f = rel[0], rel[1], float(rel[2])
        if b in {MANA_COST_STAT, LIFE_COST_STAT}:
            # `audit_castability` names the affected manual skill and its exact
            # cost, which is more useful than the aggregate derived floor.
            continue
        va, vb = _value(stats, a), _value(stats, b)
        if va is None or vb is None:
            continue
        floor = f * vb
        missed = va < floor - 1e-9 * max(1.0, abs(floor))
        if missed:
            if b == MANA_OVER_RESERVED_STAT:
                # the floor is `ManaUnreserved >= 0` (#171): print the number PoB warns about,
                # not the derived floor that only repeats it
                mana = _value(stats, "Mana")
                pool = f" of Mana = {mana:.1f}" if mana is not None else ""
                findings.append(Finding("error", "relation", f"ManaUnreserved = {va:.1f} < 0: reservation takes {vb:.1f} mana past the pool{pool}"))
                continue
            sev = "error" if "PerSecond" in b or "Unreserved" in a or a == MANA_COST_POOL_STAT or b.startswith("Req") or a == "RampBudget" or a.startswith("NetLifeRegen") else "warning"  # a degen while idle is not playable (2026-09-18)
            findings.append(Finding(sev, "relation", f"{a} = {va:.1f} < {f:g} x {b} = {vb:.1f}"))
    # Ailment stacks are written into the delivered baseline at the budget cap
    # (D78). A remaining over-budget ramp is therefore only reportable when a
    # non-configurable state such as a skill part caused it.
    ramp, budget = _value(stats, "RampSeconds"), _value(stats, "RampBudget")
    if ramp is not None and budget is not None and ramp > budget:
        findings.append(Finding("error", "ramp", f"RampSeconds = {ramp:.1f} > RampBudget = {budget:.1f}: the delivered build still counts a ramp beyond its budget"))
    return findings


def _shown_number(v: float) -> str:
    return f"{v:.3f}" if abs(v) < 10 else f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.1f}"


def missed_constraints(stats: dict[str, Any], objective: Objective) -> list[str]:
    """Every floor, ceiling and relation of the objective the stats miss, worst first, as
    `<stat> <observed> < <floor>` (relations `<lhs> <observed> < <rhs> <value>`); read from
    `Objective.violations`, the judgement the optimizer itself used (#704)."""

    if objective.derived:
        stats = {**stats, **objective.derived_values(stats)}
    out: list[tuple[float, str]] = []
    for key, viol in objective.violations(stats).items():
        text = key
        if key in objective.floors:
            v = _value(stats, key)
            text = f"{key} {'missing' if v is None else _shown_number(v)} < {_shown_number(objective.floors[key])}"
        elif key.endswith("<=") and key[:-2] in objective.ceilings:
            v = _value(stats, key[:-2])
            text = f"{key[:-2]} {_shown_number(v or 0.0)} > {_shown_number(objective.ceilings[key[:-2]])}"
        else:
            for rel in objective.relations:
                if key == f"{rel[0]}>={rel[1]}":
                    va, vb = _value(stats, rel[0]), _value(stats, rel[1])
                    if va is not None and vb is not None:
                        text = f"{rel[0]} {_shown_number(va)} < {rel[1]} {_shown_number(float(rel[2]) * vb)}"
                    break
        out.append((viol, text))
    out.sort(key=lambda t: -t[0])
    return [t for _, t in out]


def floors_cell(missed: list[str] | None) -> str:
    """The report's floors cell: "ok", or the three worst misses and "+N more"."""

    if missed is None:
        return "-"
    if not missed:
        return "ok"
    return "; ".join(missed[:3]) + (f"; +{len(missed) - 3} more" if len(missed) > 3 else "")


def _shown_cost(value: float) -> str:
    return f"{value:g}"


def audit_castability(pob: PobSession, *, skills: tuple[CostedSkill, ...] | None = None) -> list[Finding]:
    """Every active player skill PoB prices has enough resource for one use."""

    skills = costed_skills(pob) if skills is None else skills
    if not skills:
        return []
    stats = pob.stats(("Mana", "ManaUnreserved", "EnergyShield", "EnergyShieldProtectsMana", "Life", "LifeUnreserved"))
    mana = stats.get("ManaUnreserved")
    energy_shield = stats.get("EnergyShield")
    eb = stats.get("EnergyShieldProtectsMana")
    life = stats.get("LifeUnreserved")
    findings: list[Finding] = []
    for skill in skills:
        triggered = " (triggered)" if skill.triggered else ""
        mana_reservation = math.ceil(float(stats.get("Mana") or 0.0) * (skill.mana_reservation_percent or 0.0) / 100.0)
        life_reservation = math.ceil(float(stats.get("Life") or 0.0) * (skill.life_reservation_percent or 0.0) / 100.0)
        if skill.mana_cost is not None and skill.mana_cost > 0 and isinstance(mana, (int, float)):
            pool = float(mana)
            detail = f"{skill.name}{triggered} costs {_shown_cost(skill.mana_cost)} mana, {_shown_cost(pool)} unreserved"
            if bool(eb) and isinstance(energy_shield, (int, float)):
                pool += float(energy_shield)
                detail += f" mana + {_shown_cost(float(energy_shield))} energy shield"
            if skill.mana_cost > pool + mana_reservation:
                findings.append(Finding("error", "skill cannot be used", detail))
        if skill.life_cost is not None and skill.life_cost > 0 and isinstance(life, (int, float)) and skill.life_cost >= float(life) + life_reservation:
            findings.append(Finding("error", "skill cannot be used", f"{skill.name}{triggered} costs {_shown_cost(skill.life_cost)} life, {_shown_cost(float(life))} unreserved"))
    return findings


def audit_ailment_stack_caps(xml: str, stats: dict[str, Any], objective: Objective, *, uncapped_stats: dict[str, Any] | None = None) -> list[Finding]:
    """A D78 cap must not claim stacks the budget cannot apply.

    PoB keeps `<Ailment>Stacks` at the calculated steady-state count when a
    native potential override is on, so the original application rate remains
    available for this delivered-build audit.
    """

    from junkroan.optimizer.ramp import ailment_stacks, ramp_context

    ctx = ramp_context(objective)
    if ctx is None:
        return []
    caps = ailment_stacks(uncapped_stats or stats, ctx.seconds)
    baseline = baseline_config_inputs(xml) or {}
    findings: list[Finding] = []
    for name, var in (("bleed", "overrideBleedStackPotential"), ("ignite", "overrideIgniteStackPotential")):
        value, cap = baseline.get(var), caps.get(name)
        if isinstance(value, (int, float)) and cap is not None and int(value) > cap.counted:
            findings.append(Finding("error", "ailment stacks", f"{name}: Baseline counts {int(value)} stacks but only {cap.counted} fit inside the {ctx.seconds:g} s ramp budget"))
    bleed = caps.get("bleed")
    value = baseline.get("multiplierBleedsOnEnemy")
    if isinstance(value, (int, float)) and bleed is not None and int(value) > bleed.counted:
        findings.append(Finding("error", "ailment stacks", f"bleed: Baseline effective DPS counts {int(value)} stacks but only {bleed.counted} fit inside the {ctx.seconds:g} s ramp budget"))
    match = re.search(r'<CustomModifierBlock[^>]*title="junkroan: poison stacks (?P<count>\d+) of [^\"]+ inside [^\"]+"[^>]*>(?P<line>.*?)</CustomModifierBlock>', xml, re.S)
    poison = caps.get("poison")
    if match and poison is not None and int(match.group("count")) > poison.counted:
        findings.append(Finding("error", "ailment stacks", f"poison: Baseline counts {match.group('count')} stacks but only {poison.counted} fit inside the {ctx.seconds:g} s ramp budget"))
    if match:
        expected = f"Cannot Poison Enemies with at least {match.group('count')} Poisons on them"
        line = "\n".join(part for part in match.group("line").splitlines() if not part.lstrip().startswith("#")).strip()
        if line != expected:
            findings.append(Finding("error", "ailment stacks", f"poison: Baseline must use PoB's PoisonStackLimit ({expected!r}), not {line!r}"))
    value = baseline.get("multiplierPoisonOnEnemy")
    if isinstance(value, (int, float)) and poison is not None and int(value) > poison.counted:
        findings.append(Finding("error", "ailment stacks", f"poison: Baseline effective DPS counts {int(value)} stacks but only {poison.counted} fit inside the {ctx.seconds:g} s ramp budget"))
    return findings


def audit_average_damage(stats: dict[str, Any]) -> list[Finding]:
    """Skills PoB flags show-average (Blade Trap, some traps/mines): CombinedDPS is
    the average damage of one hit, not damage per second, so attack, throw and
    rotation rates are not in the number. The optimizer still ranks candidates of
    the same skill consistently; the number is not comparable across skills."""

    combined, average, total = stats.get("CombinedDPS"), stats.get("AverageDamage"), stats.get("TotalDPS")
    if isinstance(combined, (int, float)) and isinstance(average, (int, float)) and combined > 0 and abs(combined - average) <= 1e-6 * max(1.0, combined) and not total:
        return [Finding("warning", "average damage", f"PoB shows average damage for the main skill: {combined:,.0f} is one hit, not per second (attack / throw rate not counted); comparable only within this skill")]
    return []


def audit_unsupported_gems(pob: PobSession) -> list[Finding]:
    """A support gem PoB's own calc applies to no active skill of its group (the skills
    tab's red "Cannot apply to any of the active skills"), or one a stronger copy in the
    group supersedes: a socket spent on nothing. PoB's verdict, read back after the main
    calc (`PobSession.unsupported_gems`), not a corpus guess. A group with no active gem
    at all is "dead support group"; a support that applies but adds nothing (Efficacy on
    Shield Charge) is legal here and stays a reading remark."""

    findings: list[Finding] = []
    for row in pob.unsupported_gems():
        where = row.get("label") or row.get("slot") or f"group {row.get('group')}"
        findings.append(Finding("warning", "support fits no active gem", f"{where}: {row.get('gem')} {row.get('reason')}"))
    return findings


def held_mod_entries(state: dict[str, Any], graph: Any = None) -> list[tuple[str, str]]:
    """Every mod line the build carries as (line, source): item affixes (source = slot name), allocated notable /
    keystone / ascendancy nodes and taken mastery effects (source = node name). The line is as the data holds it
    (a node's stat line may carry a newline); `audit_unsupported_mods` splits it, and the red-line marks (#1124) look
    it up whole. `state` is `PobSession.read_state()`; `graph` defaults to `TreeGraph.load()`."""

    from junkroan.optimizer.tree_graph import TreeGraph

    held: list[tuple[str, str]] = []
    slots = (state.get("items_state") or {}).get("slots") or {}
    if isinstance(slots, dict):
        for slot, entry in slots.items():
            item = (entry or {}).get("item") or {}
            for line in list(item.get("implicit_affixes") or []) + list(item.get("explicit_affixes") or []):
                # a mod written on two lines (The Wasp Nest's "... against\nEnemies affected by at least 5 Poisons")
                # is one mod to PoB's parser; "Corrupted" is an item flag, not a mod
                text = " ".join(part.strip() for part in str(line).split("\n") if part.strip())
                if text and text.lower() != "corrupted":
                    held.append((text, f"{slot}"))
    graph = graph if graph is not None else TreeGraph.load()
    tree_state = state.get("tree_state") or {}
    allocated = {int(n) for n in tree_state.get("user_allocated_node_ids") or []}
    for nid in allocated:
        node = graph.node(nid)
        if node is None or node.kind not in ("notable", "keystone", "ascendancy"):
            continue
        for line in node.stats or []:
            held.append((str(line), node.name))
    taken = {}
    for entry in tree_state.get("mastery_effect_ids") or []:
        try:
            nid, eff = str(entry).split(":")
            taken[int(nid)] = int(eff)
        except ValueError:
            continue
    for nid, eff in taken.items():
        node = graph.node(nid)
        for effect_id, stats in (node.mastery_effects if node else []):
            if effect_id == eff:
                for line in stats or []:
                    held.append((str(line), node.name))
    return held


def audit_unsupported_mods(pob: PobSession) -> list[Finding]:
    """Every mod line the build carries (item affixes, allocated notables, keystones,
    ascendancy nodes, mastery effects) through PoB's own parser: lines PoB cannot
    model are worth zero in every number here and are named, so the reader knows
    what the build has that the numbers do not (Jagged Technique's aggravation
    line was the first case; the config rule D40 covers that one by text)."""

    where: dict[str, list[str]] = {}
    for line, source in held_mod_entries(pob.read_state()):
        for part in line.split("\n"):
            where.setdefault(part.strip(), []).append(source)
    lines = [ln for ln in where if ln]
    if not lines:
        return []
    findings: list[Finding] = []
    # the custom mod of #400 carries "N% increased Effect of Cruelty" above PoB's clamp: not a zero then
    carried = ("increased effect of cruelty",) if "junkroan: Cruelty effect" in pob.export_xml() else ()
    for r in pob.parse_mods(lines):
        if not r.get("ok") or r.get("unsupported"):
            if any(c in str(r.get("line")).lower() for c in carried):
                continue
            srcs = ", ".join(dict.fromkeys(where.get(str(r.get("line")), [])))
            findings.append(Finding("warning", "not modelled by PoB", f"{r.get('line')} ({srcs}): worth zero in every number here"))
    return findings


def audit_elemental_overload(xml: str, stats: dict[str, Any]) -> list[Finding]:
    """Elemental Overload with no uptime behind it.

    PoB gives the keystone's 40% more elemental damage whenever the skill's crit chance is
    not zero (`CalcOffence`: `if output.CritChance ~= 0 then skillModList.conditions
    ["CritInPast8Sec"] = true`). There is no config input for it, so no lane can switch it
    off: 7% effective crit on a slow channelled Burning Arrow got the whole 40% (the user's
    reading 2026-09-18). The keystone's own window is 8 seconds, so its real uptime is the
    same rule the ailments use, 1 - (1 - c)^(8 r), with c the effective crit per hit and r
    the hits per second (`config_rules._crit_recently`, which also decides the crit-recently
    config inputs). Minions crit for themselves: the keystone is per skill."""

    from junkroan.optimizer.config_rules import CRIT_RECENTLY_MIN_UPTIME, _crit_recently
    from junkroan.search.hypothesis import active_gems, keystones

    node_id = keystones().get("elemental overload")
    root = ET.fromstring(xml)
    allocated = node_id is not None and node_id in _allocated_nodes(root)
    if not allocated:
        for _slot, lines in _items(xml):
            if any(line.strip().lower() == "elemental overload" for line in lines):
                allocated = True
                break
    if not allocated:
        return []
    build = root.find("Build")
    main = str((build.get("mainSocketGroup") if build is not None else None) or "")
    skills = root.find("Skills")
    main_tags: frozenset[str] = frozenset()
    if skills is not None and main.isdigit():
        groups = list(skills.iter("Skill"))
        if 1 <= int(main) <= len(groups):
            for gem in groups[int(main) - 1].findall("Gem"):
                rec = active_gems().get(str(gem.get("nameSpec") or "").lower())
                if rec and rec.get("grants_active_skill") and gem.get("enabled", "true") == "true":
                    main_tags = frozenset(rec.get("tag_keys") or [])
                    break
    ok, why = _crit_recently(stats, main_tags)
    if ok:
        return []
    return [Finding("warning", "elemental overload uptime", f"{why}; below {CRIT_RECENTLY_MIN_UPTIME:.0%}, and PoB grants the keystone's 40% more elemental damage at any crit chance above zero (no config input gates it)")]


def audit_curse_limit(xml: str, stats: dict[str, Any]) -> list[Finding]:
    """Curses and marks share PoB's curse slots (CalcPerform: a mark takes a slot like a
    hex; beyond EnemyCurseLimit only the highest-priority ones apply): a build carrying
    more curse skills than its limit has dead gems in it, and the number already ignores
    them. The Spark reference runs Conductivity and Sniper's Mark on a limit of 1."""

    from junkroan.search.hypothesis import is_limited_curse

    limit = stats.get("EnemyCurseLimit")
    if not isinstance(limit, (int, float)):
        return []
    root = ET.fromstring(xml)
    skills = root.find("Skills")
    if skills is None:
        return []
    names: list[str] = []
    for group in skills.iter("Skill"):
        if group.get("enabled", "true") != "true":
            continue
        for gem in group.findall("Gem"):
            if gem.get("enabled", "true") != "true":
                continue
            if is_limited_curse(str(gem.get("nameSpec") or "")):
                names.append(str(gem.get("nameSpec")))
    names = list(dict.fromkeys(names))
    if len(names) > int(limit):
        return [Finding("warning", "curse limit", f"{len(names)} curse skills ({', '.join(names)}) for a curse limit of {int(limit)}: PoB applies only the highest-priority {int(limit)}; the rest add nothing to the number")]
    return []


def audit_golem_limit(xml: str, stats: dict[str, Any]) -> list[Finding]:
    """More golem gems than the build can summon: PoB applies every enabled golem's buff whatever
    ActiveGolemLimit says (measured on the Cold DoT reference 2026-09-16: four golem gems, limit 4,
    each gem's buff moved the number on its own), so a build over the limit is scored on buffs it
    cannot have. The reference builds carry their golems at the limit; ours inherit those groups."""

    from junkroan.search.hypothesis import active_gems

    limit = stats.get("ActiveGolemLimit")
    if not isinstance(limit, (int, float)):
        return []
    root = ET.fromstring(xml)
    skills = root.find("Skills")
    if skills is None:
        return []
    names: list[str] = []
    for group in skills.iter("Skill"):
        if group.get("enabled", "true") != "true":
            continue
        for gem in group.findall("Gem"):
            if gem.get("enabled", "true") != "true":
                continue
            rec = active_gems().get(str(gem.get("nameSpec") or "").lower())
            if "golem" in set((rec or {}).get("tag_keys") or []):
                names.append(str(gem.get("nameSpec")))
    names = list(dict.fromkeys(names))
    if len(names) > int(limit):
        return [Finding("warning", "golem limit", f"{len(names)} golem gems ({', '.join(names)}) for a golem limit of {int(limit)}: PoB applies every enabled golem's buff; the game summons {int(limit)}")]
    return []


def audit_forbidden_lines(pob: PobSession, rails: Rails) -> list[Finding]:
    """Allocated notables, keystones and mastery effects whose text the rails forbid (tree.forbidden_text):
    accuracy conditional on the enemy being unique or marked caps the boss number while maps are hit at 70%."""

    import re

    from junkroan.optimizer.tree_graph import TreeGraph

    regs = [re.compile(p, re.IGNORECASE) for p in rails.forbidden_node_text]
    if not regs:
        return []
    graph = TreeGraph.load()
    tree_state = (pob.read_state().get("tree_state") or {})
    findings: list[Finding] = []
    for nid in tree_state.get("user_allocated_node_ids") or []:
        node = graph.node(int(nid))
        if node and node.kind in ("notable", "keystone"):
            for s in node.stats or []:
                if any(r.search(s) for r in regs):
                    findings.append(Finding("warning", "forbidden line", f"{node.name}: {s} (rails: hit chance is capped by universal means only)"))
    for entry in tree_state.get("mastery_effect_ids") or []:
        try:
            nid, eff = (int(x) for x in str(entry).split(":"))
        except ValueError:
            continue
        node = graph.node(nid)
        for effect_id, stats in (node.mastery_effects if node else []):
            if effect_id == eff:
                for s in stats or []:
                    if any(r.search(s) for r in regs):
                        findings.append(Finding("warning", "forbidden line", f"{node.name}: {s} (rails: hit chance is capped by universal means only)"))
    return findings


def _config_inputs(config_set: ET.Element) -> dict[str, Any]:
    """The explicit input values in one exported config set."""

    out: dict[str, Any] = {}
    for inp in config_set.findall("Input"):
        name = inp.get("name")
        if not name:
            continue
        if inp.get("boolean") is not None:
            out[name] = inp.get("boolean") == "true"
        elif inp.get("number") is not None:
            raw = str(inp.get("number"))
            out[name] = float(raw) if "." in raw else int(raw)
        elif inp.get("string") is not None:
            out[name] = inp.get("string")
    return out


def baseline_config_inputs(xml: str) -> dict[str, Any] | None:
    """Explicit inputs of the generated conservative lane, or None when absent."""

    config = ET.fromstring(xml).find("Config")
    if config is None:
        return None
    baseline = next((s for s in config.findall("ConfigSet") if (s.get("title") or "").strip().lower() == "baseline"), None)
    return _config_inputs(baseline) if baseline is not None else None


def audit_conservative_generator_inputs(inputs: dict[str, Any], stats: dict[str, Any], text: str, gem_tags: frozenset[str], main_tags: frozenset[str],
                                          warcry_sources=(), *, parsed=None, options=None, gem_names=(), source_contexts=None, ramp_seconds: float | None = None) -> list[Finding]:
    """Flag an enabled conservative generator whose every source lacks proof. ramp_seconds None: the rails' default budget (the audit holds no assumptions)."""

    from junkroan.optimizer.config_rules import BUFF_VARS, CHARGE_VARS, DEFAULT_RAMP_BUDGET_S, _skill_use_ending_buff_sources, conservative_generator_issue

    ramp = DEFAULT_RAMP_BUDGET_S if ramp_seconds is None else ramp_seconds

    findings: list[Finding] = []
    options_by_var = {str(option.get("var")): option for option in (options or ()) if isinstance(option, dict)}
    for var in (*CHARGE_VARS, *BUFF_VARS):
        if inputs.get(var) is not True:
            continue
        issue = conservative_generator_issue(
            var,
            stats,
            text,
            gem_tags,
            main_tags,
            warcry_sources,
            parsed=parsed or {},
            option=options_by_var.get(var),
            gem_names=gem_names,
            source_contexts=source_contexts,
            ramp_seconds=ramp,
        )
        if issue:
            check = "buff ended by skill use" if var in BUFF_VARS and _skill_use_ending_buff_sources(var, gem_names) else "conservative generator proof"
            findings.append(Finding("error", check, f"{var} is on in Baseline but {issue}"))
    return findings


def audit_conservative_generator_proofs(pob: PobSession, xml: str, stats: dict[str, Any]) -> list[Finding]:
    """Audit the explicit Baseline lane using the same charge and buff proof rules."""

    inputs = baseline_config_inputs(xml)
    if inputs is None:
        return []
    from junkroan.optimizer.config_rules import BUFF_VARS, DEFAULT_RAMP_BUDGET_S, _gem_names, _gem_tags, _main_skill_name, _main_skill_tags, buff_candidate_lines, build_facts, build_text, generator_source_contexts, parse_mods_batch, warcry_charge_effect_ids, warcry_charge_sources, warcry_usage_proof

    gem_names = _gem_names(pob)
    gem_tags = _gem_tags(gem_names)
    main_tags = _main_skill_tags(pob, _main_skill_name(pob))
    source_contexts = generator_source_contexts(pob, main_tags)
    text = build_text(pob)
    parsed = parse_mods_batch(pob, buff_candidate_lines(text)) if callable(getattr(pob, "parse_mods", None)) else {}
    try:
        options = pob.config_options(condition_flag_vars=tuple(BUFF_VARS))
    except (AttributeError, TypeError):
        options = []
    warcry_sources = ()
    if hasattr(pob, "config_inputs") and hasattr(pob, "active_skill_stats"):
        facts = build_facts(pob, stats, DEFAULT_RAMP_BUDGET_S, pob.config_inputs(), text)
        effects = warcry_charge_effect_ids(facts.gems)
        skill_stats = pob.active_skill_stats(effects, ("Cooldown", "WarcryPower")) if effects else {}
        proven, _proof = warcry_usage_proof(facts.gems)
        warcry_sources = warcry_charge_sources(facts.gems, skill_stats, usage_proven=proven)
    return audit_conservative_generator_inputs(
        inputs,
        stats,
        text,
        gem_tags,
        main_tags,
        warcry_sources,
        parsed=parsed,
        options=options,
        gem_names=gem_names,
        source_contexts=source_contexts,
        ramp_seconds=DEFAULT_RAMP_BUDGET_S,
    )


def audit_dead_tree_nodes(pob: PobSession, objective: Objective | None = None, *, rows=None, points_budget: int) -> list[Finding]:
    """Leaves whose PoB removal buys nothing, or very little, and ascendancy nodes that buy nothing (#1157).

    The first pass is one frozen-config trial batch. Tentative leftovers are
    then removed for real and their conservative lane is re-derived, so a node
    that proves (for example) power charges is reported as a proof holder rather
    than a false dead-node error. Ascendancy nodes are checked only once the build
    has spent `points_budget` (the caller's rails.ascendancy_points), and each
    dead one is a **warning**, not an error: an error drops the row from the
    benchmark medians (benchmark_rows.py counted_row) until the ascendancy swap
    move exists to repair it.
    """

    from junkroan.optimizer.tree_hygiene import DEAD_ASCENDANCY_SHARE, analyze_tree_leaves, audit_findings, dead_ascendancy_nodes

    rows = analyze_tree_leaves(pob, objective=objective) if rows is None else rows
    findings = [Finding(severity, "dead tree node", detail) for severity, detail in audit_findings(rows, objective=objective)]
    for row in dead_ascendancy_nodes(pob, objective=objective, points_budget=points_budget):
        findings.append(Finding(
            "warning", "dead ascendancy node",
            f"{row.name} (node {row.node_id}) moves {row.judged_stat} {row.judged_change:+.2%} and TotalEHP {row.ehp_change:+.2%} when removed (under {DEAD_ASCENDANCY_SHARE:.1%} on both)",
        ))
    return findings


def audit_dead_implicits(pob: PobSession, objective: Objective | None = None) -> list[Finding]:
    """An equipped gear item whose implicit, removed in PoB, moves neither the objective nor TotalEHP by 0.1 % (#1158).

    One full trial per gear item that carries an implicit (dead_implicit.implicit_removals). A **warning**: the build
    is legal and playable, the implicit just buys nothing (a base swap would).
    """

    from junkroan.optimizer.dead_implicit import DEAD_IMPLICIT_SHARE, dead_implicits

    return [
        Finding(
            "warning", "dead implicit",
            f"{row.slot} {row.base}: implicit \"{row.implicit}\" moves {row.judged_stat} {row.judged_change:+.2%} and TotalEHP {row.ehp_change:+.2%} when removed (under {DEAD_IMPLICIT_SHARE:.1%} on both)",
        )
        for row in dead_implicits(pob, objective=objective)
    ]


def skeleton_beside(build_path: Any, explicit: Any = None) -> Any:
    """The skeleton a stored build was made from, for the checks that need one (`audit_empty_sockets`): the file ``explicit``
    names, else the search build's sidecar next to it (``<name>.pob.txt`` / ``<name>.xml`` -> ``<name>.json``, key
    ``skeleton``). None when neither exists or the file has no skeleton: a replayed build has no sidecar, and a skeleton is never guessed."""

    from junkroan.search.skeleton import Skeleton

    path = Path(build_path)
    if explicit is not None:
        sidecar = Path(explicit)
    else:
        stem = path.name[:-len(".pob.txt")] if path.name.endswith(".pob.txt") else path.stem
        sidecar = path.with_name(f"{stem}.json")
    if not sidecar.is_file():
        return None
    stored = json.loads(sidecar.read_text(encoding="utf-8")).get("skeleton")
    return Skeleton.from_json(stored) if stored else None


def audit_empty_sockets(pob: PobSession, skeleton: Any, rails: Rails, objective: Objective) -> list[Finding]:
    """A free socket of the delivered build that a candidate fits, when the fill step's keep rule would keep that candidate (#1156).

    One first-round trial per candidate that fits a free socket (empty_socket.measure_fill_round); the build is loaded back
    from its own XML afterwards. A **warning**: the build is legal, the socket just stays empty while PoB counts a gem for it.
    Needs the skeleton (the candidates' present gems and forbidden utilities); without one the check does nothing. Under
    the rail `fill_step` off the fill step never runs, so the check does nothing either (the same gate as pipeline.py:685).
    """

    if skeleton is None or not getattr(rails, "fill_step", False):
        return []
    from junkroan.optimizer.empty_socket import EMPTY_SOCKET_CHECK, empty_socket_detail, kept_fill_candidate, measure_fill_round

    round_ = measure_fill_round(pob, skeleton, rails, objective)
    if round_ is None:
        return []
    base, measures = round_
    best = kept_fill_candidate(base, measures, gain=float(rails.fill_min_gain), max_loss=float(rails.fill_max_objective_loss))
    return [] if best is None else [Finding("warning", EMPTY_SOCKET_CHECK, empty_socket_detail(base, best))]


def audit_build(pob: PobSession, *, rails: Rails | None = None, objective: Objective | None = None, tree_leaves=None,
                castability_metrics: CastabilityMetrics | None = None, skeleton=None) -> list[Finding]:
    rails = rails or Rails.load()
    supplied_objective = objective
    castability = castability_context(pob, metrics=castability_metrics, include_live=True)  # the audit names every uncastable skill, the main one included
    objective = with_castability_floors(pob, objective or rails.objective(), context=castability)
    xml = pob.export_xml()
    from junkroan.optimizer.random_parts import apply_mean_parts

    apply_mean_parts(pob)  # a random-element main skill is judged as the mean over its element parts, here as in the pipeline
    stats = pob.stats((*objective.stat_keys, "CombinedDPS", "FullDPS", "AverageDamage", "TotalDPS", "EnemyCurseLimit", "ActiveGolemLimit", "CritChance", "HitChance", "HitSpeed", "Speed", "ManaPerSecondCost", "LifeLeechGainRate", "ManaLeechGainRate", "EnergyShieldLeechGainRate", "TotemPlacementTime", "TotemDuration", "PowerChargesMax", "PowerChargesDuration", "FrenzyChargesMax", "FrenzyChargesDuration", "EnduranceChargesMax", "EnduranceChargesDuration"))
    baseline = baseline_config_inputs(xml) or {}
    has_ailment_cap = bool({"overrideBleedStackPotential", "overrideIgniteStackPotential"} & set(baseline)) or "junkroan: poison stacks" in xml
    uncapped_stats = None
    if has_ailment_cap:
        from junkroan.optimizer.ramp import ailment_stacks, ramp_context, with_ramp
        from junkroan.optimizer.ramp_inputs import uncapped_ailment_stack_xml

        ctx = ramp_context(objective)
        if ctx is not None:
            uncapped = uncapped_ailment_stack_xml(xml)
            if uncapped != xml:
                pob.load_xml(uncapped)
                uncapped_stats = pob.stats((*objective.stat_keys, "BleedStacks", "BleedStackPotential", "BleedStacksMax", "BleedDuration", "IgniteStacks", "IgniteStackPotential", "IgniteStacksMax", "IgniteDuration", "PoisonStacks", "PoisonDuration"))
                pob.load_xml(xml)
            objective = with_ramp(objective, ailment_stacks=ailment_stacks(uncapped_stats or stats, ctx.seconds))
    # A caller that did not supply the build's own objective has only the
    # generic Rails objective. Use the reference measurement surface instead:
    # it includes every floor stat but does not mistake a default sustain
    # relation for this build's chosen objective.
    leaf_objective = objective if supplied_objective is not None else None
    uniques = getattr(skeleton, "uniques", None) or {}
    forced = getattr(skeleton, "forced_affixes", None) or {}
    return audit_xml(xml, rails, forced) + audit_skeleton_uniques(xml, uniques) + audit_stats(stats, objective) + audit_castability(pob, skills=castability.all_skills or castability.skills) + audit_ailment_stack_caps(xml, stats, objective, uncapped_stats=uncapped_stats) + audit_average_damage(stats) + audit_unsupported_mods(pob) + audit_unsupported_gems(pob) + audit_curse_limit(xml, stats) + audit_golem_limit(xml, stats) + audit_elemental_overload(xml, stats) + audit_forbidden_lines(pob, rails) + audit_conservative_generator_proofs(pob, xml, stats) + audit_dead_tree_nodes(pob, leaf_objective, rows=tree_leaves, points_budget=rails.ascendancy_points) + audit_dead_implicits(pob, leaf_objective) + audit_duration(pob) + audit_flask_uptime(pob, xml) + audit_empty_sockets(pob, skeleton, rails, objective)


__all__ = ["Finding", "floors_cell", "missed_constraints", "audit_ailment_stack_caps", "audit_build", "audit_castability", "audit_conservative_generator_inputs", "audit_conservative_generator_proofs", "audit_dead_implicits", "audit_dead_tree_nodes", "audit_empty_sockets", "skeleton_beside", "audit_elemental_overload", "audit_excluded_bases", "audit_flask_bases", "audit_flask_uptime", "audit_movement", "audit_shield_gem_level", "audit_weapon_all_gems", "audit_skeleton_uniques", "audit_xml", "audit_stats", "baseline_config_inputs", "dead_support_group", "worn_unique_names"]
