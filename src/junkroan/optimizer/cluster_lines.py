"""Candidates of a day-1 rare cluster jewel (#433), read straight from PoB's data files (no PobSession).

`Data/ClusterJewels.lua` gives the enchants per size; `Data/ModJewelCluster.lua` the Notable pool. A notable
spawns on an enchant when the enchant's tag is in its `weightKey` with `weightVal > 0`, the size's
`expansion_jewel_<size>` is in `weightMultiplierKey` with `weightMultiplierVal > 0`, and `level <= item level`.
The enchant lines are written as `ItemsTab.lua` CraftClusterJewel writes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT
from junkroan.pob.lua_tables import parse_lua_return_value

SIZES: tuple[str, ...] = ("large", "medium", "small")
DAY1_PASSIVES: dict[str, int] = {"large": 12, "medium": 6}
_SOCKET_LINES = {
    "large": "2 Added Passive Skills are Jewel Sockets",
    "medium": "1 Added Passive Skill is a Jewel Socket",
    "small": None,
}
_NOTABLE_PREFIX = "1 Added Passive Skill is "


@dataclass(frozen=True, slots=True)
class ClusterEnchant:
    size: str
    id: str
    tag: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClusterNotable:
    name: str
    level: int
    mod_id: str = ""
    affix_type: str = ""
    line: str = ""


@dataclass(frozen=True, slots=True)
class ClusterCandidate:
    size: str
    enchant: ClusterEnchant
    notables: tuple[str, ...]
    passives: int

    @property
    def id(self) -> str:
        return f"{self.size}:{self.enchant.id}:{self.passives}:" + "+".join(self.notables)

    def raw(self, item_level: int, name: str = "Day-1 Large Cluster") -> str:
        socket = _SOCKET_LINES[self.size]
        enchant = [f"{{crafted}}Adds {self.passives} Passive Skills"]
        if socket:
            enchant.append(f"{{crafted}}{socket}")
        enchant += [f"{{crafted}}{line}" for line in self.enchant.lines]
        out = [
            "Rarity: RARE",
            name,
            f"{self.size.capitalize()} Cluster Jewel",
            f"Item Level: {item_level}",
            f"Cluster Jewel Skill: {self.enchant.id}",
            f"Cluster Jewel Node Count: {self.passives}",
            f"Implicits: {len(enchant)}",
            *enchant,
            *(f"{_NOTABLE_PREFIX}{n}" for n in self.notables),
        ]
        return "\n".join(out)


@lru_cache(maxsize=4)
def _load(source_root: Path) -> tuple[dict, tuple[dict, ...]]:
    data = source_root / "src" / "Data"
    jewels = parse_lua_return_value((data / "ClusterJewels.lua").read_text(encoding="utf-8"))["jewels"]
    mods = parse_lua_return_value((data / "ModJewelCluster.lua").read_text(encoding="utf-8"))
    notables = tuple({"mod_id": k, **v} for k, v in mods.items() if v.get("affix") == "Notable")
    return jewels, notables


def cluster_enchants(size: str, source_root: Path = DEFAULT_SOURCE_ROOT) -> tuple[ClusterEnchant, ...]:
    if size not in SIZES:
        raise ValueError(f"cluster size {size!r} is not one of {SIZES}")
    jewels, _ = _load(Path(source_root))
    skills = jewels[f"{size.capitalize()} Cluster Jewel"]["skills"]
    return tuple(
        ClusterEnchant(size, str(sid), str(s["tag"]), tuple(str(x) for x in s["enchant"])) for sid, s in skills.items()
    )


def _weight(mod: dict, keys: str, vals: str, key: str) -> int:
    for k, v in zip(mod.get(keys) or (), mod.get(vals) or ()):
        if k == key:
            return v
    return 0


def cluster_notables(
    enchant: ClusterEnchant, item_level: int, source_root: Path = DEFAULT_SOURCE_ROOT
) -> tuple[ClusterNotable, ...]:
    _, notables = _load(Path(source_root))
    expansion = f"expansion_jewel_{enchant.size}"
    out: list[ClusterNotable] = []
    for mod in notables:
        if (
            _weight(mod, "weightKey", "weightVal", enchant.tag) > 0
            and _weight(mod, "weightMultiplierKey", "weightMultiplierVal", expansion) > 0
            and int(mod["level"]) <= item_level
        ):
            line = str(mod[1])
            name = line[len(_NOTABLE_PREFIX):] if line.startswith(_NOTABLE_PREFIX) else line
            out.append(ClusterNotable(name, int(mod["level"]), mod["mod_id"], str(mod["type"]), line))
    return tuple(out)


def cluster_candidates(
    size: str, item_level: int, source_root: Path = DEFAULT_SOURCE_ROOT
) -> tuple[ClusterEnchant, ...]:
    return cluster_enchants(size, source_root)


def cluster_jewel_raw(candidate: ClusterCandidate, item_level: int, name: str = "Day-1 Large Cluster") -> str:
    return candidate.raw(item_level, name)
