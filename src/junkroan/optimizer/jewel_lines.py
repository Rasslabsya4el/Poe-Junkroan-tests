"""Line candidates of a day-1 rare jewel (#434, rulebook `j-regular`).

Read straight from PoB's data files (no PobSession): `Data/ModJewel.lua` (the Jewel mod pool) and
`Data/Bases/jewel.lua` (the three base tags). A mod spawns on a base by PoB's own rule
(`Classes/Item.lua` GetModSpawnWeight): the FIRST `weightKey` the base carries decides, and the mod
spawns when that weight is > 0. No candidate is filtered by tags or prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT
from junkroan.pob.lua_tables import parse_lua_assignment_table, parse_lua_return_value

JEWEL_BASES: tuple[str, ...] = ("Crimson Jewel", "Viridian Jewel", "Cobalt Jewel")
RANGE_VALUE = 0.5  # the way the wishlist rolls a line (`wishlist_gear._raw_for_modset`)
_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")


@dataclass(frozen=True, slots=True)
class JewelLine:
    group: str
    mod_id: str
    affix_type: str  # "Prefix" | "Suffix"
    lines: tuple[str, ...]  # the mod's line(s) rolled at 0.5 of every range
    bases: tuple[str, ...]  # the bases it spawns on, in JEWEL_BASES order
    base: str  # the first of JEWEL_BASES it spawns on
    template_lines: tuple[str, ...] = ()  # the lines as PoB writes them, ranges unresolved

    @property
    def id(self) -> str:
        """The candidate read as its line(s), rolled at 0.5: what the step's log line prints (a hybrid mod joins its lines)."""

        return " / ".join(self.lines)


def _roll(match: re.Match[str]) -> str:
    low, high = match.group(1), match.group(2)
    decimals = max((len(v.split(".")[1]) if "." in v else 0) for v in (low, high))
    value = float(low) + RANGE_VALUE * (float(high) - float(low))
    scale = 10 ** decimals
    value = int(value * scale + 0.5) / scale if value >= 0 else -int(-value * scale + 0.5) / scale
    return f"{value:.{decimals}f}" if decimals else str(int(value))


def roll_line(line: str) -> str:
    return _RANGE.sub(_roll, line)


def _spawns(mod: dict, tags: dict) -> bool:
    for key, weight in zip(mod.get("weightKey") or (), mod.get("weightVal") or ()):
        if tags.get(key):
            return weight > 0
    return False


@lru_cache(maxsize=4)
def _load(source_root: Path) -> tuple[JewelLine, ...]:
    data = source_root / "src" / "Data"
    mods = parse_lua_return_value((data / "ModJewel.lua").read_text(encoding="utf-8"))
    bases = parse_lua_assignment_table((data / "Bases" / "jewel.lua").read_text(encoding="utf-8"), "itemBases")
    out: list[JewelLine] = []
    seen: set[str] = set()
    for mod_id, mod in mods.items():
        if mod.get("type") not in ("Prefix", "Suffix"):
            continue  # Corrupted entries never
        spawn_on = tuple(b for b in JEWEL_BASES if _spawns(mod, bases[b]["tags"]))
        if not spawn_on:
            continue
        group = str(mod["group"])
        if group in seen:
            raise ValueError(f"jewel mod group {group!r} has more than one spawnable tier")
        seen.add(group)
        template = tuple(str(mod[i]) for i in range(1, 10) if i in mod)
        out.append(JewelLine(group, mod_id, str(mod["type"]), tuple(roll_line(t) for t in template), spawn_on, spawn_on[0], template))
    return tuple(out)


def jewel_line_candidates(source_root: Path = DEFAULT_SOURCE_ROOT) -> tuple[JewelLine, ...]:
    """Every spawnable group of the Jewel pool, one candidate each, in file order."""

    return _load(Path(source_root))


def rare_jewel_raw(candidate: JewelLine, *, ilvl: int = 72, name: str = "Junkroan Jewel", base: str | None = None) -> str:
    """Raw item text of a rare jewel with the candidate's one mod: every line of that mod, rolled at 0.5 (PoB `{range:}` form).

    A candidate is one MOD (the rulebook's "1 полезному моду"): a hybrid mod's several lines are one explicit
    mod. PoB parses this form to the same output as the `Prefix:` / `Suffix:` form `craft_rare` writes
    (all 156 one-line candidates, `tests/test_jewel_pipeline.py`)."""

    use_base = base or candidate.base
    if use_base not in candidate.bases:
        raise ValueError(f"{candidate.mod_id} cannot spawn on {use_base}")
    tag = f"{{range:{RANGE_VALUE}}}"
    explicit = [f"{tag if _RANGE.search(line) else ''}{line}" for line in candidate.template_lines]
    return "\n".join(["Rarity: RARE", name, use_base, f"Item Level: {ilvl}", "Implicits: 0", *explicit])
