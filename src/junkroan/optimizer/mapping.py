"""Mapping notes: what a build has that only pays on maps, and what it lacks. Text, never a score.

The objective measures bossing (a Pinnacle boss, the conservative lane, maximum hit taken as the
defence rail, D53). Mapping comfort is not a number PoB gives (the user, 2026-09-14: a life build
with life on kill maps a hundred times better than one without; block is near-immortal for mapping
and weak for bossing; on-kill effects are a mapping mechanic). Each line below carries the PoB
number or the source text it comes from; nothing is weighed.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

from junkroan.optimizer.config_rules import charge_sources

KEYS = ("LifeOnKill", "ManaOnKill", "EnergyShieldOnKill", "LifeOnHit", "BlockChance", "SpellBlockChance", "TotalEHP", "EffectiveMovementSpeedMod",
        "AreaOfEffectMod", "ProjectileCount", "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken")
_ON_KILL = re.compile(r"^(?!.*charge)(.*\b(on kill|when you kill|per enemy killed|killed recently)\b.*)$", re.IGNORECASE | re.MULTILINE)
_MOVEMENT_TAGS = {"travel", "blink"}


def _num(stats: Mapping[str, object], key: str) -> float | None:
    v = stats.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def mapping_lines(stats: Mapping[str, object], text: str, gem_names: Iterable[str], gem_tags: Mapping[str, Iterable[str]]) -> list[str]:
    """One line per mapping-only trait the build has, then one line for what it lacks."""

    has: list[str] = []
    lacks: list[str] = []

    # recovery on kill: the difference between comfortable and miserable mapping for a life build
    on_kill = [(k, _num(stats, k)) for k in ("LifeOnKill", "ManaOnKill", "EnergyShieldOnKill")]
    on_kill = [(k, v) for k, v in on_kill if v]
    if on_kill:
        has.append("recovery on kill: " + ", ".join(f"{k.replace('OnKill', '').lower()} {v:,.0f}" for k, v in on_kill) + " (PoB)")
    else:
        lacks.append("no life, mana or energy shield on kill")

    # on-kill effects PoB counts nowhere on a boss
    kill_lines: list[str] = []
    for kind in ("Frenzy", "Power", "Endurance"):
        kill_lines.extend(s["line"] for s in charge_sources(kind, text) if s["trigger"] == "kill")
    kill_lines.extend(m.group(1).strip() for m in _ON_KILL.finditer(text) if "charge" not in m.group(1).lower())
    kill_lines = list(dict.fromkeys(l for l in kill_lines if l))
    if kill_lines:
        has.append("on-kill effects (maps only, off on the boss lane): " + "; ".join(kill_lines[:4]) + (f"; and {len(kill_lines) - 4} more" if len(kill_lines) > 4 else ""))

    # block: strong on maps, weak on bosses; the EHP PoB averages it into is the mapping number
    block, sblock = _num(stats, "BlockChance") or 0.0, _num(stats, "SpellBlockChance") or 0.0
    ehp = _num(stats, "TotalEHP")
    max_hits = [v for k in ("PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken") if (v := _num(stats, k)) is not None]
    if block >= 30 or sblock >= 30:
        has.append(f"block {block:.0f}% / spell block {sblock:.0f}% (maps: near-immortal at the caps; bosses: many abilities are not blockable); EHP with block averaged in {ehp:,.0f}" + (f", smallest maximum hit {min(max_hits):,.0f} (the bossing rail)" if max_hits else ""))
    elif ehp is not None:
        has.append(f"EHP {ehp:,.0f} (mapping, block averaged in)" + (f"; smallest maximum hit {min(max_hits):,.0f} (bossing)" if max_hits else ""))

    # movement
    ms = _num(stats, "EffectiveMovementSpeedMod")
    movement = [g for g in gem_names if set(gem_tags.get(g.lower(), ()) or ()) & _MOVEMENT_TAGS]
    if ms is not None:
        has.append(f"movement {ms:.2f}x" + (f" with {', '.join(movement)}" if movement else ""))
    if not movement:
        lacks.append("no travel skill")

    # area and projectiles: clear, not single target
    aoe = _num(stats, "AreaOfEffectMod")
    proj = _num(stats, "ProjectileCount")
    clear = []
    if aoe is not None and aoe != 1.0:
        clear.append(f"area of effect x{aoe:.2f}")
    if proj is not None and proj > 1:
        clear.append(f"{proj:.0f} projectiles")
    if clear:
        has.append("clear: " + ", ".join(clear) + " (PoB)")

    out = [f"has: {h}" for h in has]
    if lacks:
        out.append("lacks: " + ", ".join(lacks))
    return out


__all__ = ["KEYS", "mapping_lines"]
