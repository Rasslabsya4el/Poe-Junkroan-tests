"""A skill whose element is random per hit is scored as the mean over its element parts.

PoB models Elemental Hit as six parts (Fire Attack, Fire AoE, Cold Attack, ...) and shows the
number of the one selected, as if every hit were that element; the skill chooses an element
per attack (PoB's own description: "will choose an element at random ... will avoid choosing
the same element twice in a row"), so a fire-only build's real number is nearer one third of
its fire part (the user's reading 2026-09-18, elemental_hit; research
`docs/research/2026-09-18-game-knowledge-2.md` 2: score (fire + cold + lightning) / 3, never a
scaled single part). `PobSession.mean_parts` makes every readback and what-if trial evaluate
each listed part and report the mean, so the optimizer prefers what raises all three. The
day-1 build carries no Combat Focus jewel, so no element is excluded; when one is, the group
shrinks to the elements left (not modelled yet: the jewel is not day-1 loot).

Which parts form a group comes from PoB's own part names: the names of one group are equal
once the element word is removed ("Fire Attack" / "Cold Attack" / "Lightning Attack" ->
"Attack"; Wild Strike's "Fire hit" / "Lightning hit" / "Cold hit" -> "hit"; its secondaries
"Fire explosion", "Lightning bolt", "Icy wave" stay single parts). The skill must carry the
corpus tag `random_element` (PoB's data), so a stacked-state skill with an element in a part
name is never averaged by accident.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from junkroan.pob.skill_facts import part_names

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
ELEMENTS = ("fire", "cold", "lightning")
_ELEMENT = re.compile(r"\b(fire|cold|lightning)\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def _gems() -> dict[str, dict[str, Any]]:
    recs = json.loads((CORPUS / "active_gems.json").read_text(encoding="utf-8"))["records"]
    return {str(r["name"]).lower(): r for r in recs}


def element_groups(names: tuple[str, ...] | list[str]) -> list[tuple[int, ...]]:
    """1-based part indices grouped by name with the element word removed; only complete groups
    (one part per element, all three) count, in the order the parts appear."""

    by_key: dict[str, list[tuple[str, int]]] = {}
    for index, name in enumerate(names, start=1):
        m = _ELEMENT.search(name)
        if not m:
            continue
        key = re.sub(r"\s+", " ", _ELEMENT.sub("", name)).strip().lower()
        by_key.setdefault(key, []).append((m.group(1).lower(), index))
    out: list[tuple[int, ...]] = []
    for members in by_key.values():
        if {e for e, _ in members} == set(ELEMENTS) and len(members) == len(ELEMENTS):
            out.append(tuple(i for _, i in members))
    return sorted(out)


def random_element_groups(main_skill: str) -> list[tuple[int, ...]]:
    """The element groups of a random-element skill (corpus tag `random_element`), [] otherwise."""

    rec = _gems().get(main_skill.lower())
    if not rec or "random_element" not in (rec.get("tag_keys") or []):
        return []
    return element_groups(part_names(str(rec.get("granted_effect_id") or "")))


def mean_parts_for(main_skill: str, part: int | None) -> tuple[int, ...] | None:
    """The parts a readback averages for this skill at this selected part: the group the part
    belongs to (PoB's default part 1 when none is selected), None when the skill is not a
    random-element skill or the part is a single one."""

    groups = random_element_groups(main_skill)
    if not groups:
        return None
    wanted = part or 1
    return next((g for g in groups if wanted in g), None)


def main_skill_of(state: Mapping[str, Any]) -> tuple[str, int | None]:
    """(main skill name, selected part) from a `read_state` snapshot, ("", None) when unknown."""

    skills = state.get("skills_state") or {}
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    groups = skills.get("socket_groups") or []
    for group in groups:
        if not isinstance(group, dict) or (main_id and group.get("socket_group_id") != main_id):
            continue
        for entry in group.get("active_skill_entries") or []:
            name = str(entry.get("name") or "")
            if name:
                part = entry.get("part_index")
                return name, (int(part) if isinstance(part, (int, float)) else None)
    return "", None


def apply_mean_parts(pob: Any) -> tuple[int, ...] | None:
    """Set `pob.mean_parts` for the build PoB holds (its main skill and selected part); returns it."""

    name, part = main_skill_of(pob.read_state())
    pob.mean_parts = mean_parts_for(name, part) if name else None
    return pob.mean_parts


__all__ = ["ELEMENTS", "apply_mean_parts", "element_groups", "main_skill_of", "mean_parts_for", "random_element_groups"]
