"""Candidates of a day-1 MAGIC flask or tincture (#436).

Read straight from PoB's data files (no PobSession): `Data/Bases/flask.lua`, `Data/Bases/tincture.lua`
(the bases, their tags and drop level) and `Data/ModFlask.lua`, `Data/ModTincture.lua` (the mod pools). A mod
spawns on a base by PoB's own rule (`Classes/Item.lua` GetModSpawnWeight, same as `jewel_lines`): the FIRST
`weightKey` the base carries decides, and the mod spawns when that weight is > 0.

PoB has no tincture-specific affix limit: a MAGIC item (flask or tincture alike) holds at most one prefix and
one suffix (`Item.lua` affixLimit 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from junkroan.optimizer.jewel_lines import roll_line
from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT
from junkroan.pob.lua_tables import parse_lua_assignment_table, parse_lua_return_value

# PoB's own tags for a base a character cannot get (#589): Iron Flask is `expedition_flask` (league-locked). On a flask
# `not_for_sale` only means no vendor sells it (Divine/Eternal/Hallowed Hybrid drop), so it is NOT screened here
UNOBTAINABLE_TAGS = frozenset({"expedition_flask", "experimental_base", "demigods"})
_KIND_TAGS = (("life_flask", "life"), ("mana_flask", "mana"), ("hybrid_flask", "hybrid"), ("utility_flask", "utility"), ("tincture", "tincture"))


@dataclass(frozen=True, slots=True)
class FlaskBase:
    name: str
    kind: str  # "life" | "mana" | "hybrid" | "utility" | "tincture"
    drop_level: int
    item_class: str  # "Flask" | "Tincture"


DAY1_FLASK_KINDS = ("life", "mana", "hybrid")  # #1162: the only kinds crafted while `gear.flasks.flask_utility_crafting` is false


def flask_base_allowed(base: FlaskBase, flask_rails) -> bool:
    """Does `gear.flasks` (tinctures, flask_utility_crafting) allow a flask of this base: the one test the flask step builds its
    pool by (#436, #1162) and the audit judges a worn flask by (#1169)."""

    return (flask_rails.tinctures or base.kind != "tincture") and (flask_rails.flask_utility_crafting or base.kind in DAY1_FLASK_KINDS)


def flask_base_of(lines: list[str]) -> FlaskBase | None:
    """The Flask or Tincture base a worn item is, read off its text: a magic item's name line holds the base inside its affixes
    ("Abecedarian's Sulphur Flask of the Ibex"), a rare's or unique's base is its own line; the longest base name found wins.
    None for an item of no flask base (every base counts here, the unobtainable ones too)."""

    found = [b for b, _tags in _bases_load(Path(DEFAULT_SOURCE_ROOT)) if any(b.name in line for line in lines[:3])]
    return max(found, key=lambda b: len(b.name), default=None)


@dataclass(frozen=True, slots=True)
class FlaskMod:
    id: str
    affix: str  # "prefix" | "suffix"
    level: int
    lines: tuple[str, ...]  # rolled at 0.5 of every range (`jewel_lines.roll_line`)
    name: str = ""  # PoB's affix name ("Scholar's", "of Sealing"), part of a magic item's name line


@dataclass(frozen=True, slots=True)
class FlaskCandidate:
    base: FlaskBase
    prefix: FlaskMod | None
    suffix: FlaskMod | None

    @property
    def id(self) -> str:
        return " | ".join((self.base.name, self.prefix.id if self.prefix else "-", self.suffix.id if self.suffix else "-"))

    def raw(self, item_level: int) -> str:
        """MAGIC item text in the shape PoB exports a magic flask: name line, `Item Level`, `Quality: 0`, `LevelReq`, `Implicits: 0`, mod lines."""

        parts = [p for p in (self.prefix.name if self.prefix else "", self.base.name, self.suffix.name if self.suffix else "") if p]
        lines = ["Rarity: MAGIC", " ".join(parts), f"Item Level: {item_level}", "Quality: 0", f"LevelReq: {self.base.drop_level}", "Implicits: 0"]
        for mod in (self.prefix, self.suffix):
            if mod:
                lines.extend(mod.lines)
        return "\n".join(lines)


def _spawns(mod: dict, tags: dict) -> bool:
    for key, weight in zip(mod.get("weightKey") or (), mod.get("weightVal") or ()):
        if tags.get(key):
            return weight > 0
    return False


@lru_cache(maxsize=4)
def _bases_load(source_root: Path) -> tuple[tuple[FlaskBase, dict], ...]:
    data = source_root / "src" / "Data" / "Bases"
    out: list[tuple[FlaskBase, dict]] = []
    for fname, item_class in (("flask.lua", "Flask"), ("tincture.lua", "Tincture")):
        bases = parse_lua_assignment_table((data / fname).read_text(encoding="utf-8"), "itemBases")
        for name, b in bases.items():
            tags = b["tags"]
            kind = next((k for t, k in _KIND_TAGS if tags.get(t)), None)
            if kind is None:
                continue
            out.append((FlaskBase(name, kind, int((b.get("req") or {}).get("level") or 0), item_class), tags))
    return tuple(out)


def _screened(tags: dict) -> bool:
    return not any(tags.get(t) for t in UNOBTAINABLE_TAGS)


@lru_cache(maxsize=4)
def _mods_load(source_root: Path, item_class: str) -> dict:
    fname = "ModFlask.lua" if item_class == "Flask" else "ModTincture.lua"
    return parse_lua_return_value((source_root / "src" / "Data" / fname).read_text(encoding="utf-8"))


def flask_bases(base_level_max: int, source_root: Path = DEFAULT_SOURCE_ROOT) -> tuple[FlaskBase, ...]:
    """Every obtainable Flask and Tincture base whose drop level is <= base_level_max, in file order."""

    return tuple(b for b, t in _bases_load(Path(source_root)) if _screened(t) and b.drop_level <= base_level_max)


def flask_base(name: str, source_root: Path = DEFAULT_SOURCE_ROOT) -> FlaskBase:
    """The Flask or Tincture base named `name`, whatever its tags: used for the fixed Divine Life Flask slot (#589 rule 1)."""

    for b, _ in _bases_load(Path(source_root)):
        if b.name == name:
            return b
    raise KeyError(f"no flask base {name!r} in PoB's data")


def flask_mods(base: FlaskBase, item_level: int, source_root: Path = DEFAULT_SOURCE_ROOT) -> tuple[FlaskMod, ...]:
    """The mods that spawn on `base` by its tags with level <= item_level (every tier of every group)."""

    root = Path(source_root)
    tags = next(t for b, t in _bases_load(root) if b.name == base.name)
    out: list[FlaskMod] = []
    for mod_id, mod in _mods_load(root, base.item_class).items():
        if mod.get("type") not in ("Prefix", "Suffix") or int(mod["level"]) > item_level or not _spawns(mod, tags):
            continue
        template = tuple(str(mod[i]) for i in range(1, 10) if i in mod)
        out.append(FlaskMod(mod_id, str(mod["type"]).lower(), int(mod["level"]), tuple(roll_line(t) for t in template), str(mod.get("affix") or "")))
    return tuple(out)
