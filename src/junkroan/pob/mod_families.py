"""The game's mod families: which two mods can never sit on the same item.

PoB's own `group` field is not the family (it splits 185 of the 512 families
into several groups and 10 of its groups span two families), so rolling loot
or crafting on the group alone produces items the game cannot drop. The
families come from RePoE, keyed by the same mod ids PoB uses:
`corpus_data/mod_families.json`, built by `scripts/build_mod_families.py`.

A mod occupies ALL of its families. A mod the corpus does not know has no
family and never conflicts (the caller falls back to PoB's group).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

CORPUS = Path(__file__).resolve().parent / "corpus_data" / "mod_families.json"


def corpus_path() -> Path:
    """Where the family index lives."""

    return CORPUS


@lru_cache(maxsize=1)
def _index() -> dict[str, tuple[str, ...]]:
    raw = json.loads(CORPUS.read_text(encoding="utf-8"))
    return {mod_id: tuple(fams) for mod_id, fams in (raw.get("families") or {}).items()}


@lru_cache(maxsize=None)
def families_of(mod_id: str) -> tuple[str, ...]:
    """The families a mod occupies; empty when the corpus does not know the mod."""

    return _index().get(mod_id, ())


def conflicting(mod_ids: Iterable[str]) -> list[tuple[str, str, str]]:
    """Pairs of mod ids that cannot share an item: (mod a, mod b, the family they share)."""

    ids = list(mod_ids)
    out: list[tuple[str, str, str]] = []
    for i, a in enumerate(ids):
        fams_a = set(families_of(a))
        if not fams_a:
            continue
        for b in ids[i + 1 :]:
            shared = sorted(fams_a & set(families_of(b)))
            if shared:
                out.append((a, b, shared[0]))
    return out
