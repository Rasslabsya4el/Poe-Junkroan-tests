"""Self-cost on use: "Lose X% of Life and Energy Shield when you use a Chaos Skill" (Chaos Mastery),
a line PoB does not parse, counted as degen in the self-degen rail (D34; mechanics/unsupported_lines.json).

Loss per second = X% x pool x uses per second of the skills the player uses themselves: the main
skill when it carries the tag, at PoB's `Speed`. A triggered skill is not "used" (PoB's own
triggered flag on the active skill decides, whatever the trigger: Spellslinger, Cast when Damage
Taken, trigger crafts ...); the skill doing the triggering is the one used, and it carries its own
tags. Utility skills the player casts by hand have no rate PoB knows; they are not counted.

A support gem that pays a pool per use is the same thing wearing another hat: Sacrifice sacrifices
20% of current life on every use and PoB turns that life into added chaos damage and into no cost
at all (`mechanics/self_cost_gems.json`). The main link's gems are read from the build PoB holds,
so a support a pick is trying is judged with its cost, not after it is kept.

A third kind is a self-*hit*: Trauma deals the player `per stack x stacks` physical damage on every
attack hit that gains a stack, and PoB, which has the per-stack number in the gem's level data,
maps it to no modifier at all (`mechanics/pending_facts.json`, D62). It is the same arithmetic --
a cost per use x uses per second -- with a flat number instead of a share of a pool, and it is
charged only once the user approves the fact; while it is pending, `trauma_lane_note` reports what
approving it would do and the conservative number is untouched.

The derived stat `SelfCostPerSecond` is negative and enters the rails' idle-recovery relation by
name ("NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond >= 0 x Life"), so a Chaos Mastery on a
4-casts-per-second chaos skill (-40% life per second) disqualifies itself exactly as Righteous
Fire's degen does. The context is re-derived on every reconfigure, so a line taken later counts:
computed once from the empty build it never saw the Chaos Mastery the tree went on to take seven
times (soulrend s1, +17% each). What the optimizer must not even try -- a passive or mastery whose
text is such a line for the main skill -- is excluded from the tree by `tree_patterns`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

from junkroan.optimizer.objective import DerivedStat, Objective

STAT_NAME = "SelfCostPerSecond"
KEYS = ("Life", "EnergyShield", "Mana", "LifeUnreserved", "Speed", "HitSpeed")
TRAUMA_FACT = "trauma.self_hit_per_stack_gained"
TRAUMA_STAT = "trauma_strike_self_damage_per_trauma"
_LINE = re.compile(r"lose (\d+)% of (life and energy shield|energy shield|life|mana) when you use a (\w+) skill", re.IGNORECASE)
_POOLS = {"life": ("Life",), "energy shield": ("EnergyShield",), "life and energy shield": ("Life", "EnergyShield"), "mana": ("Mana",)}
_GEMS_PATH = Path(__file__).resolve().parents[1] / "mechanics" / "self_cost_gems.json"


@lru_cache(maxsize=1)
def gem_self_costs() -> dict[str, tuple[str, float]]:
    """gem name -> (pool stat, fraction of it paid per use), from `mechanics/self_cost_gems.json`:
    costs PoB has the number for and counts as no cost."""

    raw = json.loads(_GEMS_PATH.read_text(encoding="utf-8"))
    return {str(g["name"]).lower(): (str(g["pool"]), float(g["fraction_per_use"])) for g in raw.get("gems", [])}


@dataclass(frozen=True, slots=True)
class SelfCostContext:
    fractions: tuple[tuple[str, float], ...] = ()  # (pool stat, fraction lost per use) for the main skill
    rate_key: str = "Speed"
    per_hit: float = 0.0  # flat damage the player takes on every attack hit of the main skill (Trauma)
    per_hit_why: str = ""  # where that number comes from, for the explanation


def self_cost_lines(text: str) -> list[tuple[str, float, str]]:
    """(pool, fraction, skill tag) for every "lose X% of <pool> when you use a <tag> skill" line."""

    out: list[tuple[str, float, str]] = []
    for m in _LINE.finditer(text):
        out.append((m.group(2).lower(), float(m.group(1)) / 100.0, m.group(3).lower()))
    return out


def trauma_self_hit(gem_levels: Iterable[tuple[str, int]], stacks: float) -> tuple[float, str] | None:
    """(physical damage the player takes on every attack hit of the main skill, why) for a link
    that applies Trauma -- the Trauma Support, or a skill with Trauma of its own (Boneshatter,
    PoB `SkillType.InnateTrauma`). None when nothing in the link applies Trauma or no stacks are
    held.

    The mechanic is the researched fact (`mechanics/pending_facts.json`
    `trauma.self_hit_per_stack_gained`): the hit lands once per attack hit that gains a stack and
    is `per stack x stacks now held`. The per-stack number is PoB's own
    (`trauma_strike_self_damage_per_trauma` at the gem's level, effectiveness-interpolated), which
    PoB parses and then maps to no modifier -- so it is in no PoB stat at all. Nothing here judges
    whether the build survives it: the rails' idle-recovery relation does, once the number is in
    `SelfCostPerSecond`."""

    from junkroan.pob.skill_facts import effectiveness_stat

    if stacks <= 0:
        return None
    best: tuple[float, str, int] | None = None
    for gid, level in gem_levels:
        per_stack = effectiveness_stat(str(gid), TRAUMA_STAT, int(level)) if gid else None
        if per_stack and (best is None or per_stack > best[0]):
            best = (float(per_stack), str(gid), int(level))
    if best is None:
        return None
    per_stack, gid, level = best
    damage = per_stack * float(stacks)
    why = (f"Trauma ({gid} level {level}): {per_stack:.0f} physical damage per stack (PoB gem data "
           f"{TRAUMA_STAT}) x {stacks:g} stacks = {damage:,.0f} taken on every attack hit")
    return damage, why


def context_for(text: str, main_tags: frozenset[str], main_triggered: bool, main_gems: Iterable[str] = (),
                gem_levels: Iterable[tuple[str, int]] = (), trauma_stacks: float = 0.0) -> SelfCostContext:
    """The main skill's self-costs: the lines of the build's text whose tag the main skill carries,
    plus the gems of its own link that pay a pool per use (`main_gems`, the main socket group as
    PoB holds it, so a support being tried counts), plus the Trauma self-hit when the researched
    fact is approved (`gem_levels` are the link's PoB skill ids with their levels). All of it only
    while the player uses the skill themselves (not triggered)."""

    from junkroan.mechanics import pending_facts

    fractions: dict[str, float] = {}
    per_hit, per_hit_why = 0.0, ""
    if not main_triggered:
        for pool, frac, tag in self_cost_lines(text):
            if tag in main_tags:
                for stat in _POOLS.get(pool, ()):
                    fractions[stat] = fractions.get(stat, 0.0) + frac
        costs = gem_self_costs()
        for gem in main_gems:
            entry = costs.get(str(gem).lower())
            if entry:
                fractions[entry[0]] = fractions.get(entry[0], 0.0) + entry[1]
        rec = pending_facts.fact(TRAUMA_FACT)
        hit = trauma_self_hit(gem_levels, trauma_stacks) if rec is not None else None
        # a cost has no optimistic lane to live in (the optimistic lane is the generous one), so a
        # pending fact is computed and reported, never charged: `trauma_lane_note` is the report
        if hit is not None and rec is not None and rec.binding:
            per_hit, per_hit_why = hit[0], rec.reason(hit[1])
    return SelfCostContext(fractions=tuple(sorted(fractions.items())), per_hit=per_hit, per_hit_why=per_hit_why)


def trauma_lane_note(stats: Mapping[str, object], gem_levels: Iterable[tuple[str, int]], trauma_stacks: float) -> str:
    """The pending fact's note for this build: what approving the Trauma self-hit would do to the
    conservative number. "" when the build applies no Trauma or the fact is already binding (then
    the cost is simply in `SelfCostPerSecond`) or disputed."""

    from junkroan.mechanics import pending_facts

    rec = pending_facts.fact(TRAUMA_FACT)
    if rec is None or not rec.pending:
        return ""
    hit = trauma_self_hit(gem_levels, trauma_stacks)
    if hit is None:
        return ""
    damage, why = hit
    rate = _rate(stats, "HitSpeed") or _rate(stats, "Speed")
    recovery = sum(_rate(stats, key) for key in ("NetLifeRegen", "NetEnergyShieldRegen"))
    return pending_facts.would_move(TRAUMA_FACT, recovery, recovery - damage * rate, "idle recovery per second") + f"; {why} at {rate:.2f} hits/s"


def tree_patterns(graph, main_tags: frozenset[str]) -> tuple[str, ...]:
    """Patterns for `TreeOptimizer.forbid_text`: every passive or mastery line of the graph that is
    a self-cost for the main skill's tags. The floor prices a self-cost the build already has; this
    keeps the optimizer from buying one, which is the user's verdict on the Chaos Mastery ("you
    cannot take this unless something else triggers your chaos skills"). Nothing when the main
    skill is triggered -- then the line costs nothing -- which is the caller's `main_tags`."""

    lines: dict[str, None] = {}
    for node in graph.nodes.values():
        texts = list(node.stats or ())
        for _effect_id, stats in node.mastery_effects or ():
            texts.extend(stats or ())
        for text in texts:
            if any(tag in main_tags for _pool, _frac, tag in self_cost_lines(text)):
                lines[re.escape(text.strip())] = None
    return tuple(lines)


def _rate(stats: Mapping[str, object], key: str) -> float:
    raw = stats.get(key)
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0


def self_cost_per_second(stats: Mapping[str, object], ctx: SelfCostContext) -> float:
    if not ctx.fractions and not ctx.per_hit:
        return 0.0
    loss = 0.0
    if ctx.fractions:
        rate = _rate(stats, ctx.rate_key)
        pools = 0.0
        for stat, frac in ctx.fractions:
            pools += frac * _rate(stats, stat)
        loss += pools * rate
    if ctx.per_hit:  # a flat hit per attack: its rate is the hit rate, not the cast rate
        loss += ctx.per_hit * (_rate(stats, "HitSpeed") or _rate(stats, ctx.rate_key))
    return -loss


def self_cost_stat(ctx: SelfCostContext = SelfCostContext()) -> DerivedStat:
    return DerivedStat(name=STAT_NAME, keys=KEYS, fn=lambda stats, objective: self_cost_per_second(stats, ctx), context=ctx)


def with_self_cost(objective: Objective, ctx: SelfCostContext) -> Objective:
    """The same objective with its self-cost context replaced (or added when a floor or a
    relation names the stat: the rails put it in the idle-recovery relation)."""

    derived = tuple(d for d in objective.derived if d.name != STAT_NAME)
    named = (*objective.floors, *(part for rel in objective.relations for part in rel[:2]))
    if any(STAT_NAME in key for key in named):
        derived = (*derived, self_cost_stat(ctx))
    return objective.replace(derived=derived)


__all__ = ["STAT_NAME", "TRAUMA_FACT", "TRAUMA_STAT", "SelfCostContext", "context_for", "gem_self_costs", "self_cost_lines",
           "self_cost_per_second", "self_cost_stat", "trauma_lane_note", "trauma_self_hit", "tree_patterns", "with_self_cost"]
