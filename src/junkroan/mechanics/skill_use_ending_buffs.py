"""Buff sources which cannot persist while the character uses another skill."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


PATH = Path(__file__).resolve().with_suffix(".json")
ACTIVE_GEMS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "active_gems.json"


@dataclass(frozen=True, slots=True)
class SkillUseEndingBuff:
    effect_id: str
    name: str
    config_inputs: frozenset[str]
    disable_gem: bool
    conservative_reason: str
    quote: str
    source: str


@lru_cache(maxsize=1)
def load() -> dict[str, SkillUseEndingBuff]:
    """Facts keyed by the PoB granted-effect id from the active-gem corpus."""

    raw = json.loads(PATH.read_text(encoding="utf-8"))
    gems = {
        str(record.get("name") or "").lower(): str(record.get("granted_effect_id") or "")
        for record in json.loads(ACTIVE_GEMS.read_text(encoding="utf-8")).get("records") or ()
    }
    facts: dict[str, SkillUseEndingBuff] = {}
    for effect_id, record in (raw.get("effects") or {}).items():
        if not isinstance(record, dict):
            raise ValueError(f"{effect_id}: skill-use-ending buff fact must be an object")
        effect_id = str(effect_id)
        name = str(record.get("name") or "")
        corpus_effect_id = gems.get(name.lower(), "")
        inputs = frozenset(str(value) for value in (record.get("config_inputs") or ()) if str(value))
        reason = str(record.get("conservative_reason") or "")
        quote = str(record.get("quote") or "")
        source = str(record.get("source") or "")
        if not effect_id or not name or not inputs or not reason or not quote or not source:
            raise ValueError("every skill-use-ending buff fact needs a corpus effect id, name, inputs, reason, quote, and source")
        if corpus_effect_id != effect_id:
            raise ValueError(f"{name}: mechanics fact key {effect_id!r} does not match corpus granted-effect id {corpus_effect_id!r}")
        if effect_id in facts:
            raise ValueError(f"duplicate skill-use-ending buff fact for {effect_id}")
        facts[effect_id] = SkillUseEndingBuff(
            effect_id=effect_id,
            name=name,
            config_inputs=inputs,
            disable_gem=bool(record.get("disable_gem")),
            conservative_reason=reason,
            quote=quote,
            source=source,
        )
    return facts


def source(effect_id: str) -> SkillUseEndingBuff | None:
    return load().get(effect_id)


def sources_for_input(effect_ids: Iterable[str], config_input: str) -> tuple[SkillUseEndingBuff, ...]:
    return tuple(
        fact for effect_id in effect_ids
        if (fact := source(effect_id)) is not None and config_input in fact.config_inputs
    )


__all__ = ["ACTIVE_GEMS", "PATH", "SkillUseEndingBuff", "load", "source", "sources_for_input"]
