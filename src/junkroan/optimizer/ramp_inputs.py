"""Ramp-type config numbers are arithmetic (D62 amendment, 2026-09-18).

A stack / stage / "recently" count is never a ceiling typed into the config and
never a number somebody researched: it is

    value = min(cap, rate x budget)

the count the build's own rates reach inside the rails' ramp budget (2.5 s),
capped by the skill's own maximum. Every part comes from PoB:

- the **rate** from PoB's own stats of this build (`ManaCost` x `Speed` for mana
  spent per second, `HitSpeed` for hits, `PoisonStacks` / `PoisonDuration` for
  poisons applied per second);
- the **cap** from PoB's data (the bisection in `config_rules.judge_stack_options`
  for what PoB enforces on an input, `pob.skill_facts` for a skill's own maximum:
  Sigil of Power 4 stages, Perforate 7 spikes) or from the rails (Wither 15);
- the **per-unit cost** from the gem's own level data (Sigil of Power: 379 mana
  per stage at level 18, 400 at 20; Wither: a 0.28 s cast, one stack per pulse).

The two facts PoB does not hold -- Pride's 4 s ramp and how many Blood Stance
spikes overlap one target -- live in `mechanics/notes.json` with their source.

The conservative lane gets the derived value; the optimistic lane keeps the cap.
Nothing here judges strength: PoB does, once the number is in the config.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import floor
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from junkroan.pob.skill_facts import (
    cast_time_seconds,
    constant_stat,
    corpses_consumed_per_cast,
    corpses_created_per_cast,
    level_stat,
)

NOTES = Path(__file__).resolve().parents[1] / "mechanics" / "notes.json"
RECENTLY_SECONDS = 4.0  # PoB's "recently" window; the budget cuts it short when it is smaller
WITHER_MAX_STACKS = 15.0  # Wither's own maximum; the rails carry it as `withered_stacks_from_wither_skill` (BuildFacts.extra)
LONG_FIGHT = 3600.0  # the optimistic lane's budget: every ramp has all the time it wants, so each rule returns its cap


@dataclass(frozen=True, slots=True)
class Gem:
    """One gem of the build as the config rules see it."""

    name: str  # lower case
    effect_id: str  # PoB granted effect id ("Wither", "Pride"), "" when unknown
    level: int
    supports: tuple[str, ...] = ()  # lower-case support gems in the same socket group
    gem_id: str | None = None
    triggered: bool = False
    autoexerted: bool = False


@dataclass(frozen=True, slots=True)
class BuildFacts:
    """What the arithmetic needs about the build: PoB's numbers, its gems, the budget."""

    stats: Mapping[str, Any]
    budget: float
    gems: tuple[Gem, ...] = ()
    main_effect_id: str = ""
    text: str = ""
    triggered: bool = False  # the main skill is triggered: it does not share the player's casting time
    stance: str = ""  # bloodSandStance as the lane holds it
    extra: Mapping[str, float] = field(default_factory=dict)

    def num(self, key: str) -> float:
        raw = self.stats.get(key)
        return float(raw) if isinstance(raw, (int, float)) else 0.0

    def hits_per_second(self) -> float:
        return self.num("HitSpeed") or self.num("Speed")

    def gem(self, effect_id: str) -> Gem | None:
        return next((g for g in self.gems if g.effect_id == effect_id), None)


@lru_cache(maxsize=1)
def _notes() -> dict[str, dict[str, Any]]:
    recs = json.loads(NOTES.read_text(encoding="utf-8"))["notes"]
    return {str(r["id"]): r for r in recs if r.get("id")}


def note_param(note_id: str, key: str) -> float | None:
    """A numeric parameter of a hand-maintained mechanics note (the only facts here PoB has not got)."""

    rec = _notes().get(note_id) or {}
    value = (rec.get("params") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def reached(rate: float, seconds: float, cap: float | None = None) -> int:
    """Whole units the build reaches at `rate` per second inside `seconds`, never above `cap`."""

    if rate <= 0 or seconds <= 0:
        return 0
    n = floor(rate * seconds + 1e-9)
    return max(0, int(min(n, floor(cap)) if cap is not None else n))


# -- stack-type skill options (PoB caps them; `judge_stack_options` measures the cap) -------------


def sigil_of_power_stages(facts: BuildFacts, cap: float | None) -> tuple[int, str] | None:
    """Sigil of Power gains a stage per `base_circle_of_power_mana_spend_per_upgrade` mana the
    player spends in its area; the build spends `ManaCost` x `Speed` mana per second."""

    gem = facts.gem("SigilOfPower")
    level = gem.level if gem else 20
    per_stage = level_stat("SigilOfPower", "base_circle_of_power_mana_spend_per_upgrade", level)
    if not per_stage:
        return None
    limit = cap if cap is not None else constant_stat("SigilOfPower", "circle_of_power_max_stages")
    spend = facts.num("ManaCost") * facts.num("Speed")
    if spend <= 0:
        return 0, f"off: the build spends no mana per second (ManaCost {facts.num('ManaCost'):.0f} x Speed {facts.num('Speed'):.2f}), so Sigil of Power gains no stage"
    rate = spend / per_stage
    value = reached(rate, facts.budget, limit)
    why = (f"Sigil of Power: {facts.num('ManaCost'):.0f} mana x {facts.num('Speed'):.2f} casts/s = {spend:.0f} mana/s / {per_stage:.0f} per stage "
           f"(PoB gem data, level {level}) = {rate:.2f} stages/s x {facts.budget:g} s = {value} of {limit:.0f}")
    return value, why


def stack_option(var: str, label: str, cap: float | None, facts: BuildFacts) -> tuple[int, str] | None:
    """The conservative value of a stack-type skill option: what the build stacks inside the
    budget. Sigil of Power counts mana; every other such option is one stack per cast
    (intensity, stages), so the rate is PoB's own `Speed`."""

    if var == "sigilOfPowerStages":
        return sigil_of_power_stages(facts, cap)
    rate = facts.num("Speed")
    if rate <= 0 or cap is None:
        return None
    value = reached(rate, facts.budget, cap)
    return value, (f"{label}: one per cast x {rate:.2f} casts/s (PoB Speed) x {facts.budget:g} s = {value} of {cap:.0f} "
                   f"(the cap PoB enforces); the optimistic lane keeps the cap")


# -- numeric "recently" / stack inputs ------------------------------------------------------------


def withered_stacks(facts: BuildFacts) -> tuple[int, str] | None:
    """Withered stacks the build has on the boss inside the budget. Wither applies one stack per
    pulse at its own cast time (PoB gem data: 0.28 s), one pulse per caster (Spell Totem: one per
    totem); otherwise the stacks come from hits (Withering Touch, Withering Step): one per hit."""

    cap = float(facts.extra.get("withered_stacks_from_wither_skill") or WITHER_MAX_STACKS)
    gem = facts.gem("Wither")
    if gem is not None:
        cast = cast_time_seconds("Wither") or 0.28
        totems = facts.num("ActiveTotemLimit")
        casters = max(1.0, totems) if any("totem" in s for s in gem.supports) else 1.0
        rate = casters / cast
        value = reached(rate, facts.budget, cap)
        who = f"{casters:.0f} totems" if casters > 1 else "one caster"
        return value, (f"Wither ({who}): 1 stack per {cast:g} s pulse (PoB gem data) = {rate:.2f} stacks/s x {facts.budget:g} s "
                       f"= {value} of {cap:.0f}")
    hits = facts.hits_per_second()
    if hits <= 0:
        return None
    value = reached(hits, facts.budget, cap)
    return value, (f"hits wither (Withering Touch or similar): 1 stack per hit x {hits:.2f} hits/s x {facts.budget:g} s "
                   f"= {value} of {cap:.0f}")


def poisons_applied_recently(facts: BuildFacts) -> tuple[int, str] | None:
    """Poisons the build applies inside the window: PoB's own application rate (`PoisonStacks` over
    `PoisonDuration`) when it has one, else hits per second x poison chance. "Recently" is 4 s, cut
    to the ramp budget when that is shorter."""

    window = min(RECENTLY_SECONDS, facts.budget)
    stacks, duration = facts.num("PoisonStacks"), facts.num("PoisonDuration")
    if stacks > 0 and duration > 0:
        rate, how = stacks / duration, f"PoB: {stacks:.1f} poison stacks over a {duration:.2f} s poison"
    else:
        chance = facts.num("PoisonChance") / 100.0
        rate, how = facts.hits_per_second() * chance, f"{facts.hits_per_second():.2f} hits/s x {chance:.0%} poison chance"
    if rate <= 0:
        return None
    value = reached(rate, window)
    return value, f"{how} = {rate:.2f} poisons/s x {window:g} s ({'the ramp budget' if window < RECENTLY_SECONDS else 'recently'}) = {value}"


def corpses_consumed_recently(facts: BuildFacts) -> tuple[int, str] | None:
    """Corpses the build consumes inside the window: the consumer's cast rate x the corpses one
    cast eats (PoB skill data). Two hand-cast skills share the player's casting time, so a build
    that casts both its corpse creator and its consumer by hand gets half the rate; automation
    (Arcanist Brand, a trigger) lifts the halving."""

    eaten = corpses_consumed_per_cast(facts.main_effect_id)
    if not eaten:
        return None
    creators = [g for g in facts.gems if g.effect_id and corpses_created_per_cast(g.effect_id)]
    if not creators:
        return None
    window = min(RECENTLY_SECONDS, facts.budget)
    casts = facts.num("Speed")
    if casts <= 0:
        return None
    automated = facts.triggered or any(g.name == "arcanist brand" for g in facts.gems) or any("arcanist brand" in s or "trigger" in s for g in facts.gems for s in g.supports)
    share = 1.0 if automated else 0.5
    value = reached(casts * share * eaten, window)
    how = "automated (a trigger casts one of them)" if automated else f"{creators[0].name.title()} and the consumer are both hand cast: they share the casting time"
    return value, (f"{casts:.2f} casts/s x {eaten} corpses per cast x {share:g} ({how}) x {window:g} s = {value}")


PERFORATE_FACT = "perforate.max_overlap_on_boss"


def perforate_spike_overlap(facts: BuildFacts) -> tuple[int, str] | None:
    """Blood Stance spikes burst in sequence and can hit one target more than once; PoB's own
    multiplier is conditioned on Blood Stance and limited by the skill's spike count.

    The optimistic lane used to hold every spike the gem creates. Both research reports say that
    is not reachable on a boss-sized target -- one to two spikes usually, about three when
    positioning and area of effect are favourable -- so the pending fact
    `perforate.max_overlap_on_boss` caps that lane at 3 (`mechanics/pending_facts.json`, D62).
    The conservative lane keeps `mechanics/notes.json`'s 1 either way, so approving the fact
    cannot move the conservative number."""

    from junkroan.mechanics import pending_facts

    spikes = constant_stat("Perforate", "blood_spears_base_number_of_spears")
    if spikes is None:
        return None
    overlaps = note_param("perforate.overlapping_spikes_on_one_target", "overlaps_blood_stance")
    if overlaps is None:
        return None
    if str(facts.stance).upper() == "SAND":
        return 0, "off: Sand Stance thrusts the spikes outwards; PoB's overlap multiplier is conditioned on Blood Stance"
    if facts.budget >= LONG_FIGHT:  # the optimistic lane: every spike PoB allows, capped by what reaches one target
        rec = pending_facts.fact(PERFORATE_FACT)
        reachable = min(int(spikes), int(rec.value)) if rec is not None and rec.value else int(spikes)
        capped, why = pending_facts.lane_value(PERFORATE_FACT, "optimistic", int(spikes), reachable)
        return int(capped), (f"Blood Stance: {capped:.0f} of {spikes:.0f} spikes (PoB gem data) counted as overlapping"
                             + (f"; {why}" if why else ""))
    value = int(min(overlaps, spikes))
    return value, (f"Blood Stance: {value} of {spikes:.0f} spikes (PoB gem data) overlap one boss-sized target "
                   f"(mechanics/notes.json, the user's reading 2026-09-18)")


_RAGE_GAIN = re.compile(r"(?:(?P<chance>\d+)% chance to )?gain (?P<n>\d+) rage\b(?P<how>[^\n]*)")
_RAGE_ONCE_EVERY = re.compile(r"no more than once every (?P<s>\d+(?:\.\d+)?) seconds?")
_RAGE_PER_MANA = re.compile(r"spending a total of (?P<mana>\d+) mana")
RAGE_INPUT = "multiplierRage"  # the config var `rage_stacks` fills
RAGE_HIT_SECONDS = 0.5  # PoB's own reminder text on every rage-on-hit source: "(Only one Hit every 0.5 seconds can cause you to gain Rage)"


def _rage_source(how: str) -> str:
    """Which rate a "gain N rage <how>" line is counted by in `rage_stacks`: the first matching of
    kill, warcry power, warcry, hit taken, flask, retaliation, mana, crit, hit; "" for the rest."""

    if "kill" in how or "slain" in how:
        return "kill"
    if "warcry" in how:
        return "warcry power" if "power" in how else "warcry"
    if "when hit" in how or "hit by an enemy" in how:
        return "hit taken"
    if "flask" in how:
        return "flask"
    if "retaliation" in how:
        return "retaliation"
    if _RAGE_PER_MANA.search(how):
        return "mana"
    if "critical strike" in how or "crit" in how:
        return "crit"
    if "hit" in how:
        return "hit"
    return ""


def grants_rage_on_hit(text: str) -> bool:
    """Does this mod text hold a line `rage_stacks` counts by hits per second ("Gain 1 Rage on Melee
    Hit")? The one pattern, shared with `rage_stacks`, so a candidate node is recognised by what the
    ramp would derive from it."""

    return any(_rage_source(m.group("how")) == "hit" for m in _RAGE_GAIN.finditer(text.lower()))


def rage_stacks(facts: BuildFacts) -> tuple[int, str] | None:
    """Rage the build holds inside the budget: the sum of its own sources' rates x the budget,
    capped at PoB's `MaximumRage`. PoB only flags that rage can be gained (`Condition:CanGainRage`)
    and reads the count from the config, so the rates come from the build's own lines:

    - on hit ("on attack hit", "on melee hit", "on hit with axes", "on critical strike with
      attacks"): the amount x hits per second (PoB `HitSpeed` / `Speed`, x crit chance for the
      crit lines), never more than one hit per 0.5 s (PoB's reminder text on the sources) or
      than the line's own "no more than once every N seconds";
    - Rage Support on the main link: PoB's gem constant (3 per attack hit) x the same hit rate;
    - "after spending a total of N mana": the amount x mana spent per second / N;
    - "when you use a warcry": one use inside the budget when a warcry gem is in the build, then
      one per cooldown (PoB gem data);
    - PoB's `RageRegenRecovery` (Chainbreaker, "Lose 2 Rage per second") is a signed rate already;
    - rage spent by the skill (PoB `RageCost` x `Speed`) comes off the rate.

    On kill (the user's verdict: no kills on the boss lane), "when hit by an enemy" (the boss's
    hit rate is nowhere in PoB), a life flask, retaliation skills and warcry power ("N rage per M
    power") count for nothing in the conservative lane; on-kill lines reach the cap in the
    optimistic lane (a long fight with adds), the others stay off there too. PoB lifts the
    count to `MinimumRage` itself."""

    from junkroan.pob.skill_facts import cooldown_seconds, skill_types

    cap = facts.num("MaximumRage")
    if cap <= 0:
        return None
    hits = facts.hits_per_second()
    crit = facts.num("CritChance") / 100.0
    hit_rate = min(hits, 1.0 / RAGE_HIT_SECONDS)
    long_fight = facts.budget >= LONG_FIGHT
    warcry_cd = next((cooldown_seconds(g.effect_id) or 8.0 for g in facts.gems if g.effect_id and "warcry" in skill_types(g.effect_id)), None)
    rate, flat = 0.0, 0.0
    counted: list[str] = []
    ignored: list[str] = []
    for m in _RAGE_GAIN.finditer(facts.text):  # every occurrence is a source: two nodes with the same line both gain
        line = m.group(0).strip()
        n = int(m.group("n")) * (float(m.group("chance")) / 100.0 if m.group("chance") else 1.0)
        how = m.group("how")
        kind = _rage_source(how)
        if kind == "kill":
            if long_fight:
                rate += n
                counted.append(f"{line} (kills: the optimistic lane's long fight)")
            else:
                ignored.append(f"{line} (no kills on a boss)")
        elif kind == "warcry power":
            ignored.append(f"{line} (warcry power is not derived)")
        elif kind == "warcry":
            if warcry_cd:
                flat += n
                rate += n / warcry_cd
                counted.append(f"{line} x one warcry inside the budget (a {warcry_cd:g} s cooldown, PoB gem data)")
            else:
                ignored.append(f"{line} (no warcry gem in the build)")
        elif kind == "hit taken":
            ignored.append(f"{line} (the boss's hit rate is not in PoB)")
        elif kind == "flask":
            ignored.append(f"{line} (flasks are not in the lane)")
        elif kind == "retaliation":
            ignored.append(f"{line} (no retaliation rate)")
        elif kind == "mana":
            mm = _RAGE_PER_MANA.search(how)
            spend = facts.num("ManaCost") * facts.num("Speed")
            per_second = spend / float(mm.group("mana"))
            rate += n * per_second
            counted.append(f"{line} x {spend:.0f} mana/s (PoB ManaCost x Speed) / {mm.group('mana')}")
        elif kind == "crit":
            per_second = min(hits * crit, hit_rate)
            rate += n * per_second
            counted.append(f"{line} x {per_second:.2f} crits/s ({hits:.2f} hits/s x {crit:.0%} crit)")
        elif kind == "hit":
            every = _RAGE_ONCE_EVERY.search(how)
            per_second = min(hit_rate, 1.0 / float(every.group("s"))) if every else hit_rate
            rate += n * per_second
            counted.append(f"{line} x {per_second:.2f} hits/s" + (f" (of {hits:.2f}: one hit per {RAGE_HIT_SECONDS:g} s gains rage)" if per_second < hits else ""))
        else:
            ignored.append(f"{line} (unclassified rage source)")
    main = facts.gem(facts.main_effect_id) if facts.main_effect_id else None
    if main is not None and "rage" in main.supports:
        per_hit = constant_stat("SupportRage", "gain_x_rage_on_attack_hit") or 0.0
        rate += per_hit * hit_rate
        counted.append(f"Rage Support on the main link: {per_hit:g} rage per attack hit (PoB gem data) x {hit_rate:.2f} hits/s")
    regen = facts.num("RageRegenRecovery")
    if regen:
        rate += regen
        counted.append(f"rage {'regeneration' if regen > 0 else 'loss'} {regen:+.1f}/s (PoB)")
    spent = facts.num("RageCost") * facts.num("Speed")
    if spent > 0:
        rate -= spent
        counted.append(f"minus {facts.num('RageCost'):g} rage per use x {facts.num('Speed'):.2f} uses/s spent by the skill (PoB)")
    value = int(min(cap, floor(max(0.0, rate) * facts.budget + flat + 1e-9)))
    if not counted:
        return 0, "off: " + ("; ".join(ignored[:3]) if ignored else "no rage source in the build's text")
    why = f"rage: {'; '.join(counted[:3])} = {rate:.2f}/s x {facts.budget:g} s{f' + {flat:g}' if flat else ''} = {value} of {cap:.0f} (PoB MaximumRage)"
    if ignored:
        why += f"; ignored: {'; '.join(ignored[:2])}"
    return value, why


RULES = {
    "multiplierWitheredStackCount": withered_stacks,
    "multiplierPoisonAppliedRecently": poisons_applied_recently,
    "multiplierCorpseConsumedRecently": corpses_consumed_recently,
    RAGE_INPUT: rage_stacks,
    "perforateSpikeOverlap": perforate_spike_overlap,
}


def ramped_input(var: str, facts: BuildFacts, *, optimistic: bool = False) -> tuple[int | None, str] | None:
    """(value, reason) for a ramp-type numeric config input, (None, reason) when the build reaches
    nothing inside the budget (the input stays off), None when no rule covers the var.

    `optimistic=True` runs the same arithmetic with all the time in the world, which is what the
    optimistic lane holds: the cap (Wither 15 stacks), or the mechanic's own window where there is
    no cap ("recently" is 4 s)."""

    rule = RULES.get(var)
    if rule is None:
        return None
    out = rule(replace(facts, budget=LONG_FIGHT) if optimistic else facts)
    if out is None:
        return None
    value, why = out
    return (value if value > 0 else None), why


# -- list choices whose maximum is itself a ramp (Pride) -------------------------------------------


CRUELTY_EFFECT = re.compile(r"(\d+)% increased effect of cruelty")
CRUELTY_CLAMP = 40.0  # ConfigOptions.lua: overrideCruelty -> m_min(val, 40)
CRUELTY_TITLE = "junkroan: Cruelty effect above PoB's clamp"


def _more_lines_for(factor: float) -> tuple[list[int], float]:
    """The whole-percent "more" value nearest to `factor`. PoB's parser reads whole percents only
    ("8.57% more" parses as 8, flagged unsupported), and several such mods do not combine finer:
    measured on gladiator_lacerate, 41% more + 23% less (x1.0857) and 12% more + 3% less both read
    as x1.09 (one block or two), 7% + 1% more as x1.08: PoB rounds the Damage MORE total to whole
    percents. So one line is all there is; its error is up to half a percent of the damage."""

    value = max(1, round((factor - 1.0) * 100))
    return [value], 1 + value / 100.0


def cruelty_excess_mod(facts: BuildFacts, held: float | None = None) -> tuple[str, str, str] | None:
    """(custom mod lines, block title, reason) for the part of Cruelty's effect PoB's config cannot hold.

    PoB applies Cruelty as `Damage MORE 1 (ModFlag.Dot) x Multiplier:Cruelty` and clamps the config
    input `overrideCruelty` to 40, so "N% increased Effect of Cruelty" (Damage Over Time Mastery) takes
    40 -> 40 x (1 + N/100) only through a custom mod: Damage MORE, ModFlag.Dot, of
    (1 + v (1+N/100)/100) / (1 + v/100) - 1. `held` is the overrideCruelty value the lane holds
    (None: PoB's own 40). None when no enabled Cruelty Support sits in a skill group or no allocated
    line raises its effect."""

    if not any(g.name in ("cruelty", "cruelty support") for g in facts.gems):
        return None
    pct = sum(int(m) for m in CRUELTY_EFFECT.findall(facts.text))
    if pct <= 0:
        return None
    v = min(CRUELTY_CLAMP, float(CRUELTY_CLAMP if held is None else held))
    if v <= 0:
        return None
    effective = v * (1 + pct / 100.0)
    factor = (1 + effective / 100.0) / (1 + v / 100.0)
    values, product = _more_lines_for(factor)
    if not values:
        return None
    line = "\n".join(f"Deal {abs(x)}% {'more' if x > 0 else 'less'} Damage over Time" for x in values)
    why = (f"Damage Over Time Mastery: {pct}% increased Effect of Cruelty. PoB clamps overrideCruelty at {CRUELTY_CLAMP:g} so the config holds {v:g}%; "
           f"the effective Cruelty is {v:g} x (1 + {pct}/100) = {effective:g}%, Damage MORE x{factor:.4f} over PoB's {v:g}% "
           f"(1 + {effective:g}/100) / (1 + {v:g}/100); written as whole-percent lines, x{product:.4f}")
    return line, CRUELTY_TITLE, why


def pride_ramp_mod(facts: BuildFacts) -> tuple[str, str, str] | None:
    """(custom mod line, block title, reason) for Pride: PoB offers only the two ends of a ramp
    (`prideEffect` MIN / MAX), so the conservative lane takes MIN and adds, as a custom modifier,
    the part of the ramp the build reaches inside the budget. None when Pride is not in the build."""

    gem = facts.gem("Pride")
    if gem is None:
        return None
    key = "physical_damage_aura_nearby_enemies_physical_damage_taken_+%"
    initial = level_stat("Pride", key, gem.level)
    maximum = level_stat("Pride", key + "_max", gem.level)
    ramp = note_param("pride.ramp_seconds", "ramp_seconds")
    if initial is None or maximum is None or not ramp or maximum <= initial:
        return None
    share = min(1.0, facts.budget / ramp)
    value = initial + (maximum - initial) * share
    # PoB's mod parser takes whole percents on this line (a "9.98%" line parses as unsupported and is
    # silently ignored), so the conservative lane rounds its own bonus down
    extra = floor((100.0 + value) / (100.0 + initial) * 100.0 - 100.0)
    if extra < 1:
        return None
    line = f"Nearby Enemies take {extra:.0f}% more Physical Damage"
    title = f"junkroan: Pride at {facts.budget:g} s of a {ramp:g} s ramp"
    why = (f"conservative: PoB's MIN ({initial:.0f}% more physical damage taken, gem level {gem.level}) plus a custom mod of {extra:.0f}% more "
           f"(rounded down from the whole ramp), the {value:.1f}% the aura reaches in {facts.budget:g} s of its {ramp:g} s ramp to {maximum:.0f}% "
           f"(PoB gem data; mechanics/notes.json for the ramp); the optimistic lane keeps MAX")
    return line, title, why


BASELINE_SET = re.compile(r'(<ConfigSet [^>]*title="Baseline"[^>]*?)(/?)>')
OUR_BLOCK = re.compile(r'<CustomModifierBlock[^>]*title="junkroan[^"]*"[^>]*>.*?</CustomModifierBlock>', re.S)
AILMENT_STACK_INPUTS = frozenset(("multiplierBleedsOnEnemy", "overrideBleedStackPotential", "overrideIgniteStackPotential"))


def poison_stack_limit_mod(*, counted: int, steady: float, budget: float) -> tuple[str, str, str] | None:
    """The conservative poison-stack cap as PoB's native ``PoisonStackLimit`` mod."""

    if steady <= 0 or counted >= steady - 1e-9:
        return None
    line = f"Cannot Poison Enemies with at least {counted} Poisons on them"
    title = f"junkroan: poison stacks {counted} of {steady:.2f} inside {budget:g} s"
    why = (f"poison: {counted} of {steady:.2f} steady stacks inside {budget:g} s; "
           f"{line} parses to PoB's PoisonStackLimit")
    return line, title, why


def uncapped_ailment_stack_xml(xml: str) -> str:
    """Remove only D78's baseline caps for the report-only long-ramp projection."""

    root = ET.fromstring(xml)
    config = root.find("Config")
    if config is None:
        return xml
    baseline = next((s for s in config.findall("ConfigSet") if s.get("title") == "Baseline"), None)
    if baseline is None:
        return xml
    has_native_override = any(node.tag == "Input" and node.get("name") in {"overrideBleedStackPotential", "overrideIgniteStackPotential"}
                              for node in baseline)
    changed = has_native_override or any(node.tag == "CustomModifierBlock" and (node.get("title") or "").startswith("junkroan: poison stacks")
                                         for node in baseline)
    for node in list(baseline):
        if node.tag == "Input" and node.get("name") in {"overrideBleedStackPotential", "overrideIgniteStackPotential"} | ({"multiplierBleedsOnEnemy"} if has_native_override else set()):
            baseline.remove(node)
            changed = True
        elif node.tag == "CustomModifierBlock" and (node.get("title") or "").startswith("junkroan: poison stacks"):
            baseline.remove(node)
            changed = True
    if not changed:
        return xml
    return ET.tostring(root, encoding="unicode")


def apply_custom_mods(pob: Any, blocks: Sequence[tuple[str, str] | tuple[str, str, str]], *, replace_ailment_stacks: bool = False) -> None:
    """Write custom-modifier blocks into the conservative (Baseline) config set only.

    PoB keeps them in the build XML (`ConfigTab:Save` writes `<CustomModifierBlock>`), there is no
    config var for them, and `set_config` rebuilds the config sets and drops them -- so this runs
    after each apply, and only for builds with a partial ramp (Pride or poison stacks).
    """

    original = pob.export_xml()
    if not blocks:
        if not replace_ailment_stacks:
            return
        xml = OUR_BLOCK.sub("", original)
        if xml != original:
            pob.load_xml(xml)
        return
    xml = OUR_BLOCK.sub("", original)
    # PoB accepts comments inside a custom-modifier block. Keeping the reason on
    # its own line makes exports readable without changing the parsed mod line.
    text = "".join(
        f'<CustomModifierBlock title="{title}" enabled="true"># {why}\n{line}</CustomModifierBlock>'
        for line, title, why in (_custom_block_parts(block) for block in blocks)
    )
    new, n = BASELINE_SET.subn(lambda m: m.group(1) + ">" + text + ("</ConfigSet>" if m.group(2) else ""), xml, count=1)
    if not n:
        raise ValueError("no Baseline config set in the build XML: cannot write the ramp's custom modifiers")
    pob.load_xml(new)


MARKS_TITLE = "junkroan: red-line marks"
MARKS_BLOCK = re.compile(r'<CustomModifierBlock[^>]*title="' + re.escape(MARKS_TITLE) + r'"[^>]*>.*?</CustomModifierBlock>', re.S)
CONDITIONAL_SET = re.compile(r'(<ConfigSet [^>]*title="Conditional"[^>]*?)(/?)>')
_MARK_LANE_SETS = {"boss": BASELINE_SET, "optimistic": CONDITIONAL_SET}


def apply_mark_blocks(pob: Any, lines_by_lane: Mapping[str, Sequence[str]]) -> None:
    """Write the red-line marks block (#1124) into each lane's config set: `boss` into Baseline, `optimistic` into
    Conditional, one `junkroan: red-line marks` block per lane holding that lane's lines (comments included).

    Strip-and-rewrite like `apply_custom_mods`, but only its own block (the ramp's `junkroan` blocks stay): the old
    marks block goes first; a lane with no lines gets none, and no lines on either lane makes no PoB call at all.
    It has to run after `apply_custom_mods`, whose `OUR_BLOCK` strip takes every `junkroan` block, marks included."""

    wanted = {lane: [str(line) for line in lines] for lane, lines in lines_by_lane.items() if lines}
    unknown = set(wanted) - set(_MARK_LANE_SETS)
    if unknown:
        raise ValueError(f"lane must be 'boss' or 'optimistic', got {sorted(unknown)}")
    if not wanted:
        return
    xml = MARKS_BLOCK.sub("", pob.export_xml())
    for lane, lines in wanted.items():
        text = f'<CustomModifierBlock title="{MARKS_TITLE}" enabled="true">{escape(chr(10).join(lines))}</CustomModifierBlock>'
        xml, n = _MARK_LANE_SETS[lane].subn(lambda m, text=text: m.group(1) + ">" + text + ("</ConfigSet>" if m.group(2) else ""), xml, count=1)
        if not n:
            raise ValueError(f"no config set for the {lane} lane in the build XML: cannot write the red-line marks")
    pob.load_xml(xml)


def _custom_block_parts(block: tuple[str, str] | tuple[str, str, str]) -> tuple[str, str, str]:
    line, title = block[:2]
    if len(block) > 2:
        return str(line), str(title), str(block[2])
    label = str(title).removeprefix("junkroan:").strip()
    return str(line), str(title), f"conservative {label}"


def apply_ailment_stack_caps(pob: Any, inputs: Mapping[str, int | float]) -> None:
    """Write D78's native stack inputs into Baseline only.

    `PobSession.set_config` deliberately shares its base ``inputs`` across both
    lanes. These values must not leak into the optimistic lane, so they are
    patched into just the serialized Baseline config set like Pride's custom
    modifier. Repeated calls replace the old inputs rather than stacking them.
    """

    caps = {key: int(value) for key, value in inputs.items() if key in AILMENT_STACK_INPUTS and isinstance(value, (int, float))}
    original = pob.export_xml()
    root = ET.fromstring(original)
    config = root.find("Config")
    baseline = next((s for s in config.findall("ConfigSet") if s.get("title") == "Baseline"), None) if config is not None else None
    if baseline is None:
        raise ValueError("no Baseline config set in the build XML: cannot write ailment stack caps")
    native = {"overrideBleedStackPotential", "overrideIgniteStackPotential"}
    had_native = any(node.tag == "Input" and node.get("name") in native for node in baseline)
    if not caps and not had_native:
        return
    cap_bleed_count = bool(native & set(caps))
    for config_set in config.findall("ConfigSet"):
        for node in list(config_set):
            if node.tag != "Input":
                continue
            name = node.get("name")
            if name in native or (config_set is baseline and name == "multiplierBleedsOnEnemy" and (cap_bleed_count or had_native)):
                config_set.remove(node)
    for key, value in reversed(tuple(caps.items())):
        baseline.insert(0, ET.Element("Input", {"name": key, "number": str(value)}))
    xml = ET.tostring(root, encoding="unicode")
    if xml != original:
        pob.load_xml(xml)


__all__ = ["AILMENT_STACK_INPUTS", "BuildFacts", "Gem", "PERFORATE_FACT", "MARKS_TITLE", "apply_ailment_stack_caps", "apply_custom_mods", "apply_mark_blocks", "cruelty_excess_mod", "corpses_consumed_recently", "note_param", "perforate_spike_overlap",
            "poison_stack_limit_mod", "poisons_applied_recently", "pride_ramp_mod", "rage_stacks", "ramped_input", "reached", "sigil_of_power_stages",
            "stack_option", "uncapped_ailment_stack_xml", "withered_stacks"]
