"""#963: a brand gem reaches PoB with instance count 1, whoever built the PoB.

PoB multiplies a Brand-type skill's own DPS by the brands attached, `AttachedBrandCount`
(`CalcOffence.lua:2423-2425`: `dpsMultiplier * AttachedBrandCount` for every Brand skill without
`countsAttachedBrandsInDamage`; Wintertide Brand part 1, the one skill with the flag, puts the same number into
its own Damage MORE, `Data/Skills/act_int.lua:21108-21134`), and FullDPS multiplies once more by the gem's
instance count (`Calcs.lua:289`, count from `gemData.count` `Calcs.lua:167`). So the gem count of every brand
stays 1 and the attached brands are counted once, by PoB. `PobSession.load_xml` (a whole build: our generator's
export, the author's file, a delivered build of an older run) and `PobSession.set_skills` (our skills payload)
are the only two doors a gem count passes through into PoB; both call this module.

The trace counts at that door (#498, the PoB boundary): `brand-gem` is every brand gem that reached PoB,
`brand-gem:count>1` is generated for each one that came with a count above 1 and evaluated for each one PoB was
actually handed with a count above 1, which is 0 by construction.
"""

from __future__ import annotations

import re
from typing import Sequence

from junkroan.optimizer.trace import TRACE
from junkroan.pob.skill_facts import brand_skill_ids, brand_skill_names

_GEM_TAG = re.compile(r"<Gem\b[^>]*>")
_COUNT = re.compile(r'(\bcount=")(\d+)(")')
_NAME = re.compile(r'\bnameSpec="([^"]*)"')
_SKILL_ID = re.compile(r'\bskillId="([^"]*)"')
BRAND_CLASS = "brand-gem"
ABOVE_ONE_CLASS = "brand-gem:count>1"


def is_brand_gem(name: str | None, skill_id: str | None = None) -> bool:
    """A Brand-type gem by its granted effect id (`skillId` of a PoB XML gem) or, without one, by its name."""

    if skill_id and skill_id in brand_skill_ids():
        return True
    return bool(name) and str(name).strip().lower() in brand_skill_names()


def note_brand_gems(incoming_counts: Sequence[int]) -> None:
    """Trace the brand gems of one write into PoB: `incoming_counts` is the count each came with (PoB is
    handed 1 for every one of them)."""

    if not incoming_counts:
        return
    above = sum(1 for count in incoming_counts if count > 1)
    TRACE.add_generated([BRAND_CLASS], len(incoming_counts))
    TRACE.add_generated([ABOVE_ONE_CLASS], above)
    TRACE.add_evaluated([BRAND_CLASS], len(incoming_counts))
    TRACE.add_evaluated([ABOVE_ONE_CLASS], 0)


def brand_gems_at_count_one_xml(xml_text: str) -> str:
    """The build XML with `count="1"` on every brand gem; any other byte stays, a build with no brand gem above 1
    comes back as it was."""

    seen: list[int] = []

    def fix(match: re.Match) -> str:
        tag = match.group(0)
        name, skill_id, count = _NAME.search(tag), _SKILL_ID.search(tag), _COUNT.search(tag)
        if not is_brand_gem(name.group(1) if name else None, skill_id.group(1) if skill_id else None):
            return tag
        seen.append(int(count.group(2)) if count else 1)
        return _COUNT.sub(r"\g<1>1\g<3>", tag, count=1) if count and int(count.group(2)) != 1 else tag

    out = _GEM_TAG.sub(fix, xml_text)
    note_brand_gems(seen)
    return out
