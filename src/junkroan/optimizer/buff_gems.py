"""Buffs PoB keeps up all the time but a player cannot: guard skills and other
cooldown-limited self-buffs.

PoB applies a skill's self-buff for as long as its gem is enabled, with no uptime, and
no config input can switch it off: Steelskin (1.5 s of buff per 3 s of cooldown, and
only while something is hitting you) counted for its whole armour and damage-taken
value in EHP and in every maximum-hit floor of shockwave_cyclone (the user's reading,
2026-09-18: "гард скиллы и прочие подобные штуки которые не постоянные должны быть
выключены"). So the rule cannot live in a config lane; it lives in the skills surface:
the gem stays in the build and is written `enabled=false`.

What counts is PoB's own view of the skill (`skill_facts.skill_types`), never a list of
gem names:

- a **guard** skill (Steelskin, Immortal Call, Molten Shell, Arcane Cloak, the Vaal
  versions): always off, whatever its duration -- guard skills share a cooldown and are
  reactive by design;
- any other **buff** skill whose `buff_uptime` (base duration / cooldown) is below 1
  (Phase Run 45%, Convocation 67%, Vaal Immortal Call 0.7%).

Skills PoB flags as **damage** (Bear Trap, Frost Bomb, Seismic Trap, Void Sphere) are
left alone even though the audit's uptime table names them: their duration / cooldown is
a throw rate, not a buff that PoB holds up for free. **Aura** and **banner** skills
(War Banner, Dread Banner) are left alone for the same reason -- a planted banner is
permanent; its "duration" is the aura's, and its cooldown only limits re-placing it.
"""

from __future__ import annotations

from typing import Any, MutableMapping, Sequence

_LEFT_ALONE = frozenset({"damage", "aura", "banner", "hasreservation"})


def unreliable_reason(gem_name: str) -> str | None:
    """Why this gem's buff must not count, or None when it may stay enabled."""

    from junkroan.pob.skill_facts import buff_uptime, skill_types
    from junkroan.search.hypothesis import active_gems

    rec = active_gems().get(str(gem_name).strip().lower())
    if not rec:
        return None
    gid = str(rec.get("granted_effect_id") or "")
    from junkroan.mechanics.skill_use_ending_buffs import source as ending_buff_source

    if (ending := ending_buff_source(gid)) is not None and ending.disable_gem:
        return f"{gem_name}: {ending.conservative_reason}; PoB would hold its buff up all the time"
    types = skill_types(gid)
    uptime = buff_uptime(gid)
    if "guard" in types:
        return f"{gem_name}: a guard skill (reactive, shares a Guard cooldown); PoB would hold its buff up all the time"
    if "buff" in types and not (types & _LEFT_ALONE) and uptime is not None and uptime < 1.0:
        return f"{gem_name}: a self-buff up {uptime:.0%} of the time (its duration against its cooldown); PoB would hold it up all the time"
    return None


def disable_unreliable_buff_gems(groups: Sequence[MutableMapping[str, Any]]) -> list[str]:
    """Write `enabled=false` on every guard / cooldown-limited buff gem in `set_skills`
    socket groups, in place. A group left with no enabled active gem is disabled with it,
    so the supports around it do not read as a live group. Nothing is ever removed.
    Returns the reasons, one per disabled gem."""

    from junkroan.search.hypothesis import active_gems

    actives = active_gems()
    reasons: list[str] = []
    for group in groups:
        gems = group.get("gems") or []
        touched = False
        for gem in gems:
            name = str(gem.get("gem_name") or gem.get("name") or "")
            if gem.get("enabled") is False:
                continue
            why = unreliable_reason(name)
            if why:
                gem["enabled"] = False
                reasons.append(why)
                touched = True
        if touched and not any(
            g.get("enabled", True) and str(g.get("gem_name") or g.get("name") or "").strip().lower() in actives
            for g in gems
        ):
            group["enabled"] = False
    return reasons


def disable_unreliable_buff_gems_xml(xml: str) -> tuple[str, list[str]]:
    """The same rule on a PoB build XML (the benchmark's author row: like with like, the
    author's Steelskin must not inflate their EHP and maximum-hit floors either).
    Returns the XML and the reasons."""

    from xml.etree import ElementTree as ET

    from junkroan.search.hypothesis import active_gems

    actives = active_gems()
    root = ET.fromstring(xml)
    skills = root.find("Skills")
    if skills is None:
        return xml, []
    reasons: list[str] = []
    for group in skills.iter("Skill"):
        gems = group.findall("Gem")
        touched = False
        for gem in gems:
            if gem.get("enabled", "true") != "true":
                continue
            why = unreliable_reason(str(gem.get("nameSpec") or ""))
            if why:
                gem.set("enabled", "false")
                reasons.append(why)
                touched = True
        if touched and not any(
            g.get("enabled", "true") == "true" and str(g.get("nameSpec") or "").strip().lower() in actives
            for g in gems
        ):
            group.set("enabled", "false")
    return (ET.tostring(root, encoding="unicode"), reasons) if reasons else (xml, [])


__all__ = ["disable_unreliable_buff_gems", "disable_unreliable_buff_gems_xml", "unreliable_reason"]
