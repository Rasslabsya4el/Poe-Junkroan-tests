"""Anoint candidates: the passives whose 3-oil recipe stays within an oil ceiling (#432).

The oil order is PoB's own (vendor/pob/source/src/Data/CurrencyNames.lua:418-430). A passive is a
candidate when every oil of its `recipe` is at or below `oil_max` in that order. Recipes come from the
committed passives corpus (notables) and keystones corpus (Worship the Blightheart, 3x Prismatic Oil:
the one keystone PoB's tree gives a recipe), so the endgame count is the 472 of tree.lua 3_29.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from junkroan.optimizer.trace import register_class
from junkroan.pob.game_corpus import load_game_corpus_bundle, load_game_corpus_manifest

OIL_ORDER: tuple[str, ...] = (
    "Clear", "Sepia", "Amber", "Verdant", "Teal", "Azure", "Indigo",
    "Violet", "Crimson", "Black", "Opalescent", "Silver", "Golden", "Prismatic",
)


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    node_id: int
    recipe: tuple[str, ...]  # oil names without the "Oil" suffix, as in OIL_ORDER
    highest_oil: str


def _oil(raw: str) -> str:
    name = raw[:-3] if raw.endswith("Oil") else raw
    if name not in OIL_ORDER:
        raise ValueError(f"Unknown oil in a passive recipe: {raw!r}")
    return name


def anoint_candidates(oil_max: str, tree_version: str | None = None) -> list[Candidate]:
    """Passives anointable with oils up to `oil_max`, ordered by node id.

    `tree_version` defaults to the committed corpus's (manifest source_lane.tree_version); another
    value raises, the corpus holds one tree.
    """

    if oil_max not in OIL_ORDER:
        raise ValueError(f"Unknown oil {oil_max!r}; expected one of {OIL_ORDER}")
    corpus_version = load_game_corpus_manifest()["source_lane"]["tree_version"]
    if tree_version is not None and tree_version != corpus_version:
        raise ValueError(f"The committed corpus is tree {corpus_version}, not {tree_version}")
    limit = OIL_ORDER.index(oil_max)
    out: list[Candidate] = []
    for family in ("passives", "keystones"):
        for record in load_game_corpus_bundle(family)["records"]:
            if not record.get("recipe"):
                continue
            oils = tuple(_oil(raw) for raw in record["recipe"])
            highest = max(oils, key=OIL_ORDER.index)
            if OIL_ORDER.index(highest) <= limit:
                out.append(Candidate(record["name"], int(record["node_id"]), oils, highest))
    return sorted(out, key=lambda c: c.node_id)


@lru_cache(maxsize=1)
def _highest_by_name() -> dict[str, str]:
    return {c.name: c.highest_oil for c in anoint_candidates(OIL_ORDER[-1])}


def _anoint_output_class(item: dict) -> list[str]:
    """Trace class of an item wearing an anoint: `oil:<highest oil>` of the notable (#432), so the output counts name it."""

    from junkroan.optimizer.anoint_line import anoint_of

    raw = item.get("item", {}).get("raw") if isinstance(item.get("item"), dict) else None
    notable = anoint_of(raw) if isinstance(raw, str) else None
    if not notable:
        return []
    by_name = _highest_by_name()
    return [f"oil:{by_name[notable]}"] if notable in by_name else []


register_class(_anoint_output_class)

__all__ = ["OIL_ORDER", "Candidate", "anoint_candidates"]
