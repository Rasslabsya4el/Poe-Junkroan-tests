"""Hypotheses: what an LLM (or a person) is allowed to propose, and nothing more.

A hypothesis names skeleton-level choices by their in-game names. It never
contains passive node ids, item affixes or config toggles: those are the
optimizer's. Every name is resolved against the corpora; unknown names are
errors, not guesses. `validate()` turns a hypothesis into a `Skeleton` the
pipeline can build, or returns the list of problems.

JSON shape (see docs/HYPOTHESES.md):

    {
      "name": "Fireball ignite Elementalist",
      "class": "Witch", "ascendancy": "Elementalist",
      "main_skill": "Fireball",
      "supports": ["Burning Damage", "Deadly Ailments"],        # optional; the generator fills the rest
      "extra_groups": [["Flammability"], ["Herald of Ash"]],    # optional utility links / auras
      "keystones": ["Elemental Overload"],                       # optional; forced like "nodes" (a request's keystones are never dropped)
  "nodes": ["Holy Dominion"],                               # optional; passive names (notable, keystone, mastery effect), forced
  "affixes": {"Wand": ["+1 to Level of all Fire Spell Skill Gems"]},  # optional; slot or item class -> mod lines the rare must carry
      "ascendancy_nodes": ["Shaper of Flames", "Mastermind of Discord"],  # optional; else chosen by PoB
      "uniques": {"Weapon 1": "Pledge of Hands"},               # optional; slot -> unique name
      "rare_bases": {"Body Armour": "Vaal Regalia"},            # optional; else chosen by PoB base screen
      "why": "one paragraph of reasoning, kept for the report"
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from junkroan.pob.spectres import resolve_spectre
from junkroan.search.forced import affix_template
from junkroan.search.skeleton import Skeleton, SocketGroup

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
RARE_SLOTS = ("Body Armour", "Helmet", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2", "Weapon 1", "Weapon 2")
UNIQUE_TYPE_SLOTS = {
    "Body Armour": ("Body Armour",), "Helmet": ("Helmet",), "Gloves": ("Gloves",), "Boots": ("Boots",), "Belt": ("Belt",),
    "Amulet": ("Amulet",), "Ring": ("Ring 1", "Ring 2"), "Shield": ("Weapon 2",), "Quiver": ("Weapon 2",),
    "Bow": ("Weapon 1",), "Wand": ("Weapon 1", "Weapon 2"), "Sceptre": ("Weapon 1", "Weapon 2"), "Dagger": ("Weapon 1", "Weapon 2"),
    "Claw": ("Weapon 1", "Weapon 2"), "One Handed Sword": ("Weapon 1", "Weapon 2"), "One Handed Axe": ("Weapon 1", "Weapon 2"),
    "One Handed Mace": ("Weapon 1", "Weapon 2"), "Staff": ("Weapon 1",), "Two Handed Sword": ("Weapon 1",), "Two Handed Axe": ("Weapon 1",),
    "Two Handed Mace": ("Weapon 1",), "Jewel": (), "Flask": ("Flask 1", "Flask 2", "Flask 3", "Flask 4", "Flask 5"),
}


@dataclass(slots=True)
class Hypothesis:
    name: str
    class_name: str
    ascendancy: str
    main_skill: str
    supports: list[str] = field(default_factory=list)
    extra_groups: list[list[str]] = field(default_factory=list)
    keystones: list[str] = field(default_factory=list)
    ascendancy_nodes: list[str] = field(default_factory=list)
    uniques: dict[str, str] = field(default_factory=dict)
    rare_bases: dict[str, str] = field(default_factory=dict)
    level: int = 77
    why: str = ""
    nodes: list[str] = field(default_factory=list)
    affixes: dict[str, list[str]] = field(default_factory=dict)
    weapon_types: list[str] = field(default_factory=list)
    spectres: list[str] = field(default_factory=list)  # ids or names of PoB spectres (Spectres.lua); only for Raise Spectre

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Hypothesis":
        return cls(
            name=str(raw.get("name") or raw.get("main_skill") or "hypothesis"),
            class_name=str(raw.get("class") or raw.get("class_name") or ""),
            ascendancy=str(raw.get("ascendancy") or ""),
            main_skill=str(raw.get("main_skill") or ""),
            supports=[str(x) for x in raw.get("supports") or []],
            extra_groups=[[str(g) for g in grp] for grp in raw.get("extra_groups") or []],
            keystones=[str(x) for x in raw.get("keystones") or []],
            ascendancy_nodes=[str(x) for x in raw.get("ascendancy_nodes") or []],
            uniques={str(k): str(v) for k, v in (raw.get("uniques") or {}).items()},
            rare_bases={str(k): str(v) for k, v in (raw.get("rare_bases") or {}).items()},
            level=int(raw.get("level") or 77),
            why=str(raw.get("why") or ""),
            nodes=[str(x) for x in raw.get("nodes") or []],
            affixes={str(k): [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])] for k, v in (raw.get("affixes") or {}).items()},
            weapon_types=[str(x) for x in raw.get("weapon_types") or []],
            spectres=[str(x) for x in raw.get("spectres") or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "class": self.class_name, "ascendancy": self.ascendancy, "main_skill": self.main_skill, "supports": self.supports,
                "extra_groups": self.extra_groups, "keystones": self.keystones, "ascendancy_nodes": self.ascendancy_nodes, "uniques": self.uniques,
                "rare_bases": self.rare_bases, "level": self.level, "why": self.why,
                "nodes": self.nodes, "affixes": self.affixes, "weapon_types": self.weapon_types, "spectres": self.spectres}


# -- corpora -----------------------------------------------------------------


def _records(name: str) -> list[dict]:
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))["records"]


@lru_cache(maxsize=1)
def active_gems() -> dict[str, dict]:
    return {r["name"].lower(): r for r in _records("active_gems.json")}


def is_limited_curse(name: str) -> bool:
    """Does this active gem take one of PoB's curse slots (`EnemyCurseLimit`)? The audit's own count
    (`audit_curse_limit`, #784): tagged curse and (hex or mark), not aura. A mark takes a slot like a hex
    (spark-s4: limit 1, PoB's CurseList held Sniper's Mark and dropped Conductivity); Hexblast and Bane
    carry "hex" without "curse" and take none."""

    tags = set((active_gems().get(str(name).strip().lower()) or {}).get("tag_keys") or [])
    return "curse" in tags and bool(tags & {"hex", "mark"}) and "aura" not in tags


@lru_cache(maxsize=1)
def support_gems() -> dict[str, dict]:
    return {r["name"].lower(): r for r in _records("support_gems.json") if r.get("is_support")}


@lru_cache(maxsize=1)
def keystones() -> dict[str, int]:
    return {r["name"].lower(): int(r["node_id"]) for r in _records("keystones.json")}


@lru_cache(maxsize=1)
def passive_nodes() -> dict[str, list[dict]]:
    """Lowercase name -> the passive nodes a request may name: notables (passives.json), keystones, and mastery
    effects (masteries.json, by the effect's stat text; `node_id` is the mastery node, `effect_id` is what a request forces)."""

    out: dict[str, list[dict]] = {}
    for r in _records("passives.json"):
        if r.get("is_notable") and not r.get("is_proxy"):
            out.setdefault(r["name"].lower(), []).append({"node_id": int(r["node_id"]), "kind": "notable", "ascendancy": r.get("ascendancy_name")})
    for r in _records("keystones.json"):
        out.setdefault(r["name"].lower(), []).append({"node_id": int(r["node_id"]), "kind": "keystone", "ascendancy": r.get("ascendancy_name")})
    for r in _records("masteries.json"):
        for eff in r.get("mastery_effects") or []:
            for line in eff.get("stats") or []:
                out.setdefault(str(line).lower(), []).append({"node_id": int(r["node_id"]), "kind": "mastery effect", "effect_id": eff.get("effect_id"), "ascendancy": None})
    return out


def _forced_id(rec: dict) -> int:
    """The id a request's name forces: a mastery effect's effect id, any other passive's node id."""

    return int(rec["effect_id"]) if rec["kind"] == "mastery effect" else int(rec["node_id"])


# Item classes a request's `affixes` key may name, and the one slot each fills (docs/REQUEST.md 6).
AFFIX_WEAPON_1_CLASSES = ("Bow", "Claw", "Dagger", "One Handed Sword", "One Handed Axe", "One Handed Mace", "Sceptre", "Staff", "Two Handed Sword", "Two Handed Axe", "Two Handed Mace", "Wand")
AFFIX_WEAPON_2_CLASSES = ("Shield", "Quiver")
AFFIX_ARMOUR_CLASSES = ("Body Armour", "Helmet", "Gloves", "Boots", "Belt", "Amulet")
AFFIX_ROLLABLE_SECTIONS = ("normal", "master", "essence", "delve")  # sections of the PoEDB affix catalog an item can roll or craft (not synthesis, scourge, eater/searing)
_RANGE = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)")


@lru_cache(maxsize=1)
def _affix_catalog() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(template -> item classes it rolls on, template -> item classes it appears on in any section) from the
    committed PoEDB affix catalog (src/junkroan/pob/mod_data/poedb_affix_catalog). A template is the mod text with numbers
    and ranges folded (`junkroan.search.forced.affix_template`); a hybrid mod's lines count one by one."""

    from junkroan.search.forced import affix_template

    data = json.loads((CORPUS.parent / "mod_data" / "poedb_affix_catalog" / "catalog.json").read_text(encoding="utf-8"))
    classes = {p["page_id"]: set(p.get("item_types") or []) for p in data["pages"]}
    rolls: dict[str, set[str]] = {}
    anywhere: dict[str, set[str]] = {}
    for a in data["affixes"]:
        text = _RANGE.sub("1", a.get("text") or "")
        for line in {text, *text.splitlines()}:
            key = affix_template(line)
            if not key:
                continue
            anywhere.setdefault(key, set()).update(classes.get(a["page_id"], ()))
            if a.get("section_kind") in AFFIX_ROLLABLE_SECTIONS:
                rolls.setdefault(key, set()).update(classes.get(a["page_id"], ()))
    return rolls, anywhere


def resolve_affix_key(key: str, weapon_types: Iterable[str] = ()) -> tuple[str | None, str | None, str | None]:
    """An `affixes` key -> (slot, item class, problem). A slot name needs its class: armour and jewellery slots have one,
    `Weapon 1` / `Weapon 2` take it from the request's weapon_types; an item class maps to its one slot."""

    k = key.strip().lower()
    classes = {c.lower(): c for c in (*AFFIX_WEAPON_1_CLASSES, *AFFIX_WEAPON_2_CLASSES, *AFFIX_ARMOUR_CLASSES)}
    if k in classes:
        c = classes[k]
        return ("Weapon 1" if c in AFFIX_WEAPON_1_CLASSES else "Weapon 2" if c in AFFIX_WEAPON_2_CLASSES else c), c, None
    if k == "ring":
        return None, None, f"affixes key {key!r} is a Ring: name Ring 1 or Ring 2"
    for slot in ("Ring 1", "Ring 2"):
        if k == slot.lower():
            return slot, "Ring", None
    for slot, group in (("Weapon 1", AFFIX_WEAPON_1_CLASSES), ("Weapon 2", AFFIX_WEAPON_2_CLASSES)):
        if k == slot.lower():
            have = [c for c in group if c.lower() in {w.lower() for w in weapon_types}]
            if len(have) != 1:
                return None, None, f"affixes key {slot!r} needs one item class: name it ({', '.join(group)}) as the key or in weapon_types"
            return slot, have[0], None
    return None, None, f"unknown affixes key {key!r}: name a slot (Weapon 1, Helmet, Ring 1...) or an item class (Wand, Shield...)"


# Trees PoB lists under a class that the search must not treat as a player ascendancy.
# Membership is decided by what PoB's numbers do, not by the tree's shape.
#
# Luminary (Scion, 3.29): its 18 nodes are the Mercenary system ("Your Mercenary can equip
# Unique Amulets", "Your Mercenary and their Minions deal 15% increased Damage"). PoB models no
# mercenary at all -- "Mercenary" appears zero times in ModParser.lua -- so the nodes are
# numerically dead, and a Luminary build is a build about a companion we cannot score. Excluded.
#
# Reliquarian (Scion, 3.29) is NOT excluded (2026-09-18). Its 36 nodes carry whole unique-item
# stat blocks and PoB scores them. Measured on the smoke rig (Scion, level 90, Fireball +
# Spell Echo + Controlled Destruction + Elemental Focus + Fire Penetration, smoke boots,
# Pinnacle boss), baseline Life 1208 / CombinedDPS 10,641 / TotalEHP 850:
#   Kaom's Roots (35448)        Life 1208 -> 1308 (+100), TotalEHP 850 -> 920
#   Elevore (48040)             SpellSuppressionChance 0 -> 25, TotalEHP 850 -> 894
#   Xirgil's Crank (17386)      CombinedDPS 10,641 -> 12,014 (+12.9%)
#   Presence of Chayula (54569) Life 1208 -> 966, EnergyShield 0 -> 246
# Its passives are replaced every league, so only the tree version of the build being scored
# means anything; a previous league's Reliquarian is not this league's Reliquarian.
NOT_PLAYER_ASCENDANCIES = {"luminary"}


@lru_cache(maxsize=1)
def ascendancies() -> dict[str, dict]:
    """One record per player ascendancy, keyed by PoB's internal id (lowercase).

    Iterate `.values()`; look a name up with `ascendancy()`, which also accepts the
    display name (they differ for renamed ascendancies: id "Raider" = "Warden").
    """

    return {r["ascendancy_id"].lower(): r for r in _records("ascendancies.json") if r.get("source_kind") == "class_ascendancy" and r["ascendancy_id"].lower() not in NOT_PLAYER_ASCENDANCIES}


LOADOUTS = ("day1", "t16", "endgame")
ASCENDANCY_RULE = "c-ascendancy"  # rulebook entry: day1 / t16 main ascendancies only, endgame adds the alternate ones


@lru_cache(maxsize=1)
def alternate_ascendancies() -> dict[str, dict]:
    """The ascendancies PoB's tree data marks `alternate_ascendancy`, keyed by lowercase id."""

    return {r["ascendancy_id"].lower(): r for r in _records("ascendancies.json") if r.get("source_kind") == "alternate_ascendancy" and r["ascendancy_id"].lower() not in NOT_PLAYER_ASCENDANCIES}


def search_ascendancies(loadout: str) -> list[str]:
    """PoB ids the search covers in a loadout: the main ones on day1 / t16, plus the alternate ones at endgame (rulebook c-ascendancy)."""

    if loadout not in LOADOUTS:
        raise ValueError(f"unknown loadout {loadout!r}; known: {', '.join(LOADOUTS)}")
    main = sorted(r["ascendancy_id"] for r in ascendancies().values())
    if loadout == "endgame":
        return main + sorted(r["ascendancy_id"] for r in alternate_ascendancies().values())
    return main


def check_ascendancy_for_loadout(name: str, loadout: str) -> None:
    """Raise ValueError when `name` is an alternate ascendancy asked for on day1 / t16. A name that is also a main
    ascendancy's display name ("Warden" = Raider) is the main one."""

    key = (name or "").strip().lower()
    if loadout != "endgame" and key in alternate_ascendancies() and key not in ascendancy_aliases():
        raise ValueError(f"ascendancy {name!r} is an alternate ascendancy; on loadout {loadout} only main ascendancies are searched (rulebook entry {ASCENDANCY_RULE})")


@lru_cache(maxsize=1)
def ascendancy_aliases() -> dict[str, str]:
    """Lowercase name -> PoB ascendancy id, for both the id and the display name."""

    out = {key: rec["ascendancy_id"] for key, rec in ascendancies().items()}
    for rec in ascendancies().values():
        out.setdefault(rec["display_name"].lower(), rec["ascendancy_id"])
    return out


def ascendancy(name: str) -> dict | None:
    """The record for an ascendancy named by PoB id or by display name ("Raider" / "Warden")."""

    key = ascendancy_aliases().get((name or "").strip().lower())
    return ascendancies().get(key.lower()) if key else None


def normalize_ascendancy_ids(names: Iterable[str] | None) -> list[str] | None:
    """A user's ascendancy list -> PoB ids, so a filter on `ascendancy_id` also accepts
    display names ("Warden" -> "Raider"). Unknown names pass through for the caller to reject."""

    if names is None:
        return None
    aliases = ascendancy_aliases()
    return [aliases.get(n.strip().lower(), n.strip()) for n in names]


@lru_cache(maxsize=1)
def uniques_by_name() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in _records("uniques.json"):
        # the corpus name is PoB's "Name, Base" key; PobSession.unique_item wants the plain name
        plain = r["name"][: -len(", " + r["base"])] if r["name"].endswith(", " + r["base"]) else r["name"]
        r = {**r, "plain_name": plain}
        out.setdefault(plain.lower(), []).append(r)
    return out


@lru_cache(maxsize=1)
def item_bases() -> dict[str, dict]:
    return {r["name"].lower(): r for r in _records("items.json")}


def canonical(name: str, table: Mapping[str, Any]) -> str | None:
    rec = table.get(name.strip().lower())
    if rec is None:
        return None
    return rec["name"] if isinstance(rec, dict) and "name" in rec else name.strip()


# -- validation ----------------------------------------------------------------


@dataclass(slots=True)
class Validation:
    skeleton: Skeleton | None
    problems: list[str]
    ascendancy_node_names: list[str] = field(default_factory=list)  # resolved later by the generator (PoB picks) if empty

    @property
    def ok(self) -> bool:
        return self.skeleton is not None and not self.problems


def validate(h: Hypothesis) -> Validation:
    problems: list[str] = []
    asc = ascendancy(h.ascendancy)
    if asc is None:
        problems.append(f"unknown ascendancy {h.ascendancy!r}")
    elif asc.get("class_name") and asc["class_name"].lower() != h.class_name.lower():
        problems.append(f"{asc['display_name']} belongs to {asc['class_name']}, not {h.class_name}")
    main = active_gems().get(h.main_skill.lower())
    if main is None:
        problems.append(f"unknown active skill gem {h.main_skill!r}")
    supports: list[str] = []
    for s in h.supports:
        rec = support_gems().get(s.lower())
        if rec is None:
            problems.append(f"unknown support gem {s!r}")
        elif rec["name"].startswith("Awakened") or rec["name"] in ("Enhance", "Empower", "Enlighten"):
            problems.append(f"{rec['name']} is not a day-1 gem")
        else:
            supports.append(rec["name"])
    groups: list[SocketGroup] = []
    utility_slots = ("Helmet", "Gloves", "Boots", "Weapon 1", "Weapon 2")
    for grp in h.extra_groups:
        names = []
        for g in grp:
            rec = active_gems().get(g.lower()) or support_gems().get(g.lower())
            if rec is None:
                problems.append(f"unknown gem {g!r} in extra group")
            else:
                names.append(rec["name"])
        if names:
            groups.append(SocketGroup(gems=names, slot=utility_slots[len(groups) % len(utility_slots)], include_in_full_dps=False, label=names[0]))
    key_ids: list[int] = []
    for k in h.keystones:
        nid = keystones().get(k.lower())
        if nid is None:
            problems.append(f"unknown keystone {k!r}")
        else:
            key_ids.append(nid)
    asc_ids: list[int] = []
    if asc is not None and h.ascendancy_nodes:
        by_name = {n["name"].lower(): n for n in asc.get("nodes") or []}
        for name in h.ascendancy_nodes:
            node = by_name.get(name.lower())
            if node is None:
                problems.append(f"{asc['display_name']} has no node {name!r}")
            else:
                asc_ids.append(int(node["node_id"]))
    uniques: dict[str, str] = {}
    for slot, name in h.uniques.items():
        recs = uniques_by_name().get(name.lower())
        if not recs:
            problems.append(f"unknown unique {name!r}")
            continue
        allowed = {s for r in recs for s in UNIQUE_TYPE_SLOTS.get(r["type"], ())}
        if all(r.get("availability") == "legacy" for r in recs):
            problems.append(f"{recs[0]['plain_name']} is no longer obtainable (PoB: {recs[0].get('source')})")
            continue
        if slot not in allowed:
            problems.append(f"{recs[0]['plain_name']} is a {recs[0]['type']}; it cannot go in {slot} (allowed: {sorted(allowed) or 'none'})")
        else:
            uniques[slot] = recs[0]["plain_name"]
    bases: dict[str, str] = {}
    for slot, base in h.rare_bases.items():
        rec = item_bases().get(base.lower())
        if rec is None:
            problems.append(f"unknown item base {base!r}")
        elif slot not in RARE_SLOTS:
            problems.append(f"{slot!r} is not a rare gear slot")
        elif slot in uniques:
            problems.append(f"{slot} has both a unique and a rare base")
        else:
            bases[slot] = rec["name"]
    node_ids: list[int] = []
    for name in h.nodes:
        if name.lower() in {k.lower() for k in h.keystones}:
            continue  # a request keystone is resolved (and reported) above
        found = passive_nodes().get(name.strip().lower())
        if not found:
            problems.append(f"unknown passive node {name!r}")
            continue
        mine = {asc["ascendancy_id"].lower(), asc["display_name"].lower()} if asc is not None else set()
        ok = [n for n in found if not n["ascendancy"] or asc is None or str(n["ascendancy"]).lower() in mine]
        if not ok:
            problems.append(f"passive node {name!r} belongs to ascendancy {found[0]['ascendancy']}, not {h.ascendancy}")
        elif len({_forced_id(n) for n in ok}) > 1:
            problems.append(f"passive node {name!r} is ambiguous: node ids {sorted({_forced_id(n) for n in ok})}")
        elif ok[0]["kind"] == "mastery effect":
            # a mastery is forced by its effect id (`TreeGraph.resolve_forced` finds the holder); the id space is
            # shared with the tree's nodes, and an effect id that is some node's id would read as that node
            from junkroan.optimizer.tree_graph import TreeGraph

            effect_id = _forced_id(ok[0])
            if effect_id in TreeGraph.load().nodes:
                problems.append(f"mastery effect {name!r} cannot be forced: its id {effect_id} collides with node {effect_id}")
            else:
                node_ids.append(effect_id)
        else:
            node_ids.append(ok[0]["node_id"])
            if ok[0]["kind"] == "keystone" and ok[0]["node_id"] not in key_ids:
                key_ids.append(ok[0]["node_id"])
    spectre_ids: list[str] = []
    is_raise_spectre = main is not None and main["name"].lower() == "raise spectre"
    for name in h.spectres:
        sid = resolve_spectre(name)
        if sid is None:
            problems.append(f"unknown spectre {name!r}")
        elif sid not in spectre_ids:
            spectre_ids.append(sid)
    if main is not None and is_raise_spectre and not h.spectres:
        problems.append("Raise Spectre needs --spectre <id or name> (the system never chooses the spectre)")
    elif main is not None and h.spectres and not is_raise_spectre:
        problems.append(f"--spectre is only for Raise Spectre, not {main['name']}")
    forced_classes: list[str] = []
    affixes: dict[str, list[str]] = {}
    for key, lines in h.affixes.items():
        slot, item_class, problem = resolve_affix_key(key, h.weapon_types)
        if problem:
            problems.append(problem)
            continue
        if slot in uniques:
            problems.append(f"affixes {key!r} names {slot}, which holds the unique {uniques[slot]}")
            continue
        if item_class in AFFIX_WEAPON_1_CLASSES and item_class not in h.weapon_types and item_class not in forced_classes:
            forced_classes.append(item_class)
        rolls, anywhere = _affix_catalog()
        for line in lines:
            t = affix_template(line)
            if t not in anywhere:
                problems.append(f"unknown mod line {line!r} (no such affix in the PoB-sourced catalog)")
            elif item_class not in rolls.get(t, ()):
                problems.append(f"mod line {line!r} cannot roll on {item_class}")
            else:
                affixes.setdefault(slot, []).append(line)
    if "Weapon 1" in uniques and "Weapon 2" in bases:
        recs = uniques_by_name().get(uniques["Weapon 1"].lower(), [])
        if any(r["type"] in ("Staff", "Two Handed Sword", "Two Handed Axe", "Two Handed Mace", "Bow") for r in recs):
            problems.append(f"{uniques['Weapon 1']} is two-handed; Weapon 2 cannot hold a rare base")
    if not h.class_name:
        problems.append("class is required")
    if problems:
        return Validation(skeleton=None, problems=problems)
    skeleton = Skeleton(
        class_name=h.class_name, ascendancy=asc["ascendancy_id"], level=h.level, ascendancy_nodes=asc_ids, forced_ascendancy_nodes=list(asc_ids), keystones=key_ids,
        main_link=[main["name"], *supports], main_slot="Body Armour", fixed_supports=list(supports), extra_groups=groups, uniques=uniques, rare_bases=bases, notes=h.why,
        weapon_types=[*h.weapon_types, *forced_classes], forced_uniques=dict(uniques), forced_bases=dict(bases),
        forced_nodes=list(dict.fromkeys([*key_ids, *node_ids])), forced_affixes=affixes,
        forced_spectres=spectre_ids,
    )
    skeleton.cap_links()
    return Validation(skeleton=skeleton, problems=[], ascendancy_node_names=list(h.ascendancy_nodes))


def load_hypotheses(path: Path) -> list[Hypothesis]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("hypotheses") if isinstance(raw, dict) else raw
    return [Hypothesis.from_dict(x) for x in items or []]


__all__ = ["Hypothesis", "Validation", "validate", "passive_nodes", "resolve_affix_key", "load_hypotheses", "RARE_SLOTS", "UNIQUE_TYPE_SLOTS"]
