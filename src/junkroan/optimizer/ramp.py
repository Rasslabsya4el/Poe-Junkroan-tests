"""Time to full DPS: a rail on how long the build's PoB number takes to arrive (D39).

PoB's DPS is a steady state: every bleed stack, blade and withered stack the
number relies on is already on the target. How many seconds of continuous
attacking that takes is not a PoB output, but every ingredient is one:

- bleed / ignite: `<Ailment>StackPotential` x `<Ailment>StacksMax` = stacks the
  build applies per duration; `<Ailment>Duration`; the steady state uses
  min(applied, max) stacks (Crimson Dance: 8, otherwise 1).
- poison: `PoisonStacks` (already capped) and `PoisonDuration`.
- rates: `Speed` (attacks / casts per second), `HitSpeed` (hits per second when
  it differs, e.g. Blade Vortex).

The floor changed on 2026-09-18 (D62 amendment). `RampBudget >= RampSeconds` was a
cliff: on bleed_perforate a Sand Stance worth 647,425 lost to a feasible Blood Stance
worth 189,005 because its ramp ran 13% over the budget. A ramp-type number is
arithmetic, not a pass/fail: every count the conservative lane controls -- charges,
stack-type skill options, withered stacks -- is written into the config at what the
build's own rates reach inside the budget (`ramp_inputs`), so it is inside by
construction, and ailment stacking is PoB's own steady state. What stays a floor is
the one binary state no config number can hold at a partial value: a stacked skill
part ("10 Blades"), `RampBudget >= RampStages`. `RampSeconds` is still computed and
reported (summaries, audit), it just no longer disqualifies a build.

Model: DPS(t) = M(t) * sum_i dps_i * min(1, t / ramp_i). Each ailment component
climbs linearly to its steady state over `stacks needed / stacks applied per
second`; hits and non-stacking DoTs are immediate. M(t) collects the stack
multipliers that scale the whole number: a stacked skill part ("10 Blades",
one per cast) and withered from hits (Withering Touch, one per hit, 6% per
stack). `RampSeconds` is the first t at which DPS(t) reaches `fraction` of the
steady state; the rails put a ceiling on it.

Not modelled yet, each a later rail once experience says it matters: charges,
rage, Trinity resonance, impale stacks, withered from a Wither totem, the
1-stack bleed roll average (PoB assumes the best of many bleeds).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from math import floor
from typing import Mapping

from junkroan.optimizer.objective import DerivedStat, Objective

RAMP_KEYS = (
    "CombinedDPS", "TotalDPS", "TotalDotDPS", "BleedDPS", "IgniteDPS", "TotalPoisonDPS",
    "BleedStackPotential", "BleedStacks", "BleedStacksMax", "BleedDuration",
    "IgniteStackPotential", "IgniteStacks", "IgniteStacksMax", "IgniteDuration",
    "PoisonStacks", "PoisonDuration", "Speed", "HitSpeed",
)
WITHERED_PER_STACK = 0.06
STAT_NAME = "RampSeconds"
BUDGET_NAME = "RampBudget"
STAGES_NAME = "RampStages"


@dataclass(frozen=True, slots=True)
class RampContext:
    fraction: float = 0.8  # share of the steady-state DPS that counts as "full"
    stages: int = 0  # stacked skill part ("10 Blades"): one stage per cast
    withered_stacks: int = 0  # stacks the conservative lane assumes
    withered_per_hit: bool = False  # Withering Touch in the main link: one stack per hit
    option_stacks: tuple[tuple, ...] = ()  # stack-type skill options held at PoB's cap (intensity ...): (cap, share of the number they carry[, stacks gained per second; default one per cast])
    seconds: float = 2.5  # the rail: seconds to `fraction` a component may take
    seconds_by_component: Mapping[str, float] = field(default_factory=dict)  # e.g. {"poison": 4.0}: the mechanic is the ramp
    ailment_stacks: Mapping[str, "AilmentStacks"] = field(default_factory=dict)  # conservative PoB caps written from the unmodified rate


@dataclass(frozen=True, slots=True)
class AilmentStacks:
    """One stacking ailment's PoB steady state and the whole stacks reached in a budget."""

    name: str
    steady: float
    rate: float
    duration: float
    counted: int
    budget_limited: bool

    @property
    def limited(self) -> bool:
        return self.budget_limited


def _num(stats: Mapping[str, object], key: str) -> float:
    raw = stats.get(key)
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _ailment(stats: Mapping[str, object], dps_key: str, potential_key: str, max_key: str, duration_key: str) -> tuple[float, float] | None:
    dps = _num(stats, dps_key)
    if dps <= 0:
        return None
    max_stacks = max(1.0, _num(stats, max_key))
    applied = _num(stats, potential_key) * max_stacks  # stacks applied per duration (uncapped)
    duration = _num(stats, duration_key)
    if applied <= 0 or duration <= 0:
        return dps, 0.0
    needed = max(1.0, min(applied, max_stacks))
    return dps, needed / (applied / duration)


def _poison(stats: Mapping[str, object]) -> tuple[float, float] | None:
    dps = _num(stats, "TotalPoisonDPS")
    if dps <= 0:
        return None
    stacks, duration = _num(stats, "PoisonStacks"), _num(stats, "PoisonDuration")
    if stacks <= 0 or duration <= 0:
        return dps, 0.0
    return dps, max(1.0, stacks) / (stacks / duration)


def ailment_stacks(stats: Mapping[str, object], budget: float) -> dict[str, AilmentStacks]:
    """Whole ailment stacks reached while attacking for ``budget`` seconds.

    PoB exposes bleed and ignite application as stack potential per maximum stack,
    while poison exposes its current steady-state stack count directly. The native
    bleed/ignite overrides only accept whole stack counts, so the conservative lane
    rounds down rather than claiming a fraction of the next application.
    """

    out: dict[str, AilmentStacks] = {}
    for name, dps_key, potential_key, max_key, duration_key in (
        ("bleed", "BleedDPS", "BleedStackPotential", "BleedStacksMax", "BleedDuration"),
        ("ignite", "IgniteDPS", "IgniteStackPotential", "IgniteStacksMax", "IgniteDuration"),
    ):
        dps = _num(stats, dps_key)
        maximum = _num(stats, max_key)
        duration = _num(stats, duration_key)
        applied = _num(stats, potential_key) * maximum
        steady = min(maximum, applied)
        # A one-bleed/ignite build has an immediate first hit, not a stacking state.
        if dps <= 0 or maximum <= 1 or duration <= 0 or applied <= 0 or steady <= 1:
            continue
        rate = applied / duration
        window = min(max(0.0, budget), duration)
        counted = int(min(steady, floor(rate * window + 1e-9)))
        out[name] = AilmentStacks(name=name, steady=steady, rate=rate, duration=duration, counted=counted,
                                  budget_limited=budget < duration and counted < steady - 1e-9)

    dps = _num(stats, "TotalPoisonDPS")
    steady, duration = _num(stats, "PoisonStacks"), _num(stats, "PoisonDuration")
    if dps > 0 and steady > 0 and duration > 0:
        rate = steady / duration
        window = min(max(0.0, budget), duration)
        counted = int(min(steady, floor(rate * window + 1e-9)))
        out["poison"] = AilmentStacks(name="poison", steady=steady, rate=rate, duration=duration, counted=counted,
                                       budget_limited=budget < duration and counted < steady - 1e-9)
    return out


def components(stats: Mapping[str, object], maximize: str, ctx: RampContext = RampContext()) -> list[tuple[float, float]]:
    """(dps, seconds to its steady state) for every part of the maximized stat."""

    return [(d, r) for _n, d, r in named_components(stats, maximize, ctx)]


def named_components(stats: Mapping[str, object], maximize: str, ctx: RampContext = RampContext()) -> list[tuple[str, float, float]]:
    """(name, dps, seconds to its steady state): "hit" (everything immediate), "bleed", "ignite", "poison"."""

    bleed = _ailment(stats, "BleedDPS", "BleedStackPotential", "BleedStacksMax", "BleedDuration")
    ignite = _ailment(stats, "IgniteDPS", "IgniteStackPotential", "IgniteStacksMax", "IgniteDuration")
    poison = _poison(stats)
    total = _num(stats, maximize)
    named = {"bleed": bleed, "ignite": ignite, "poison": poison}
    # PoB's override changes its displayed potential, which would make its normal
    # steady-state calculation say the capped bleed still takes a whole duration.
    # The original application rate captured during config derivation is the time
    # to the *delivered* count instead.
    for name, stack in ctx.ailment_stacks.items():
        current = named.get(name)
        if current is not None and stack.limited and stack.rate > 0:
            named[name] = (current[0], stack.counted / stack.rate)
    if maximize in ("CombinedDPS", "TotalDotDPS"):
        ailments = [(n, c[0], c[1]) for n, c in named.items() if c]
        immediate = total - sum(d for _n, d, _r in ailments)
        return ([("hit", immediate, 0.0)] if immediate > 0 else []) + ailments
    only = {"BleedDPS": "bleed", "IgniteDPS": "ignite", "TotalPoisonDPS": "poison"}.get(maximize)
    if only:
        c = named[only]
        return [(only, c[0], c[1])] if c else []
    return [("hit", total, 0.0)] if total > 0 else []


def ramp_budget(stats: Mapping[str, object], maximize: str, ctx: RampContext = RampContext()) -> float | None:
    """Seconds the build may take: each component's rail weighted by its share of
    the DPS (a 91%-poison Viper Strike with poison at 4 s and the rest at 2.5 s gets
    3.9 s; a hit build 2.5 s). None when the maximized stat is not positive."""

    comps = named_components(stats, maximize, ctx)
    total = sum(d for _n, d, _r in comps)
    if total <= 0:
        return None
    return sum(d / total * float(ctx.seconds_by_component.get(n, ctx.seconds)) for n, d, _r in comps)


def _multiplier(t: float, stats: Mapping[str, object], ctx: RampContext) -> float:
    m = 1.0
    cast_rate = _num(stats, "Speed")
    hit_rate = _num(stats, "HitSpeed") or cast_rate
    if ctx.stages > 0 and cast_rate > 0:
        m *= min(1.0, cast_rate * t / ctx.stages)
    if ctx.withered_stacks > 0 and ctx.withered_per_hit and hit_rate > 0:
        have = min(float(ctx.withered_stacks), hit_rate * t)
        m *= (1 + WITHERED_PER_STACK * have) / (1 + WITHERED_PER_STACK * ctx.withered_stacks)
    for entry in ctx.option_stacks:
        cap, share = entry[0], entry[1]
        rate = entry[2] if len(entry) > 2 and entry[2] else cast_rate
        if cap > 0 and share > 0 and rate > 0:
            m *= (1.0 - share) + share * min(1.0, rate * t / cap)  # only the share the stacks carry ramps
    return m


def ramp_seconds(stats: Mapping[str, object], maximize: str, ctx: RampContext = RampContext()) -> float | None:
    """Seconds of continuous attacking until DPS(t) reaches ctx.fraction of the
    steady state; None when the maximized stat is not positive."""

    comps = components(stats, maximize, ctx)
    total = sum(d for d, _r in comps)
    if total <= 0:
        return None
    cast_rate = _num(stats, "Speed")
    hit_rate = _num(stats, "HitSpeed") or cast_rate
    horizon = max([r for _d, r in comps] + [ctx.stages / cast_rate if ctx.stages and cast_rate > 0 else 0.0]
                  + [ctx.withered_stacks / hit_rate if ctx.withered_stacks and ctx.withered_per_hit and hit_rate > 0 else 0.0]
                  + [e[0] / (e[2] if len(e) > 2 and e[2] else cast_rate) for e in ctx.option_stacks if e[0] > 0 and e[1] > 0 and (e[2] if len(e) > 2 and e[2] else cast_rate) > 0])
    if horizon <= 0:
        return 0.0

    def share(t: float) -> float:
        return _multiplier(t, stats, ctx) * sum(d * (min(1.0, t / r) if r > 0 else 1.0) for d, r in comps) / total

    if share(horizon) < ctx.fraction:
        return horizon
    lo, hi = 0.0, horizon
    for _ in range(50):
        mid = (lo + hi) / 2
        if share(mid) >= ctx.fraction:
            hi = mid
        else:
            lo = mid
    return hi


def ramp_dps(stats: Mapping[str, object], maximize: str, seconds: float, ctx: RampContext = RampContext()) -> float | None:
    """The maximized PoB stat reached after ``seconds`` of continuous attacking."""

    comps = components(stats, maximize, ctx)
    if not comps:
        return None
    t = max(0.0, float(seconds))
    return _multiplier(t, stats, ctx) * sum(d * (min(1.0, t / ramp) if ramp > 0 else 1.0) for d, ramp in comps)


def stages_in_part(part_name: str | None) -> int:
    """A skill part named after a stack count ("10 Blades", "5 Stages") is a
    stacked state reached one cast at a time; anything else is not."""

    m = re.match(r"\s*(\d+)\b", part_name or "")
    return int(m.group(1)) if m else 0


def stage_seconds(stats: Mapping[str, object], ctx: RampContext = RampContext()) -> float | None:
    """Seconds until the one ramp the conservative lane cannot hold at a partial value is done:
    the stacked skill part ("10 Blades", one stage per cast, D42). None when there is no such part.

    Every other ramp is a *count* the lane writes into the config at what the build's own rates
    reach inside the budget (`ramp_inputs`, D62 amendment) -- charges, stack options, withered
    stacks -- so it is inside the budget by construction and cannot fail a floor; ailment stacking
    is PoB's own steady state, reported in `RampSeconds` but never a cliff. The floor kept
    exactly one job: a binary state (a skill part) the build cannot reach inside the budget.
    """

    rate = _num(stats, "Speed")
    if ctx.stages <= 0 or rate <= 0:
        return None
    return ctx.fraction * ctx.stages / rate


def ramp_stat(ctx: RampContext = RampContext()) -> DerivedStat:
    return DerivedStat(name=STAT_NAME, keys=RAMP_KEYS, fn=lambda stats, objective: ramp_seconds(stats, objective.maximize, ctx), context=ctx)


def ramp_budget_stat(ctx: RampContext = RampContext()) -> DerivedStat:
    return DerivedStat(name=BUDGET_NAME, keys=RAMP_KEYS, fn=lambda stats, objective: ramp_budget(stats, objective.maximize, ctx), context=ctx)


def ramp_stages_stat(ctx: RampContext = RampContext()) -> DerivedStat:
    return DerivedStat(name=STAGES_NAME, keys=RAMP_KEYS, fn=lambda stats, _objective: stage_seconds(stats, ctx), context=ctx)


RAMP_RELATION = (BUDGET_NAME, STAGES_NAME, 1.0)  # RampBudget >= RampStages: the one ramp no config number can hold (D62 amendment)


def ramp_context(objective: Objective) -> RampContext | None:
    for d in objective.derived:
        if d.name == STAT_NAME and isinstance(d.context, RampContext):
            return d.context
    return None


def with_ramp(objective: Objective, **changes: object) -> Objective:
    """The same objective with its ramp context updated (stages=, withered_stacks=,
    withered_per_hit=); an objective without the ramp rail is returned unchanged."""

    ctx = ramp_context(objective)
    if ctx is None:
        return objective
    new = replace(ctx, **changes)  # type: ignore[arg-type]
    rebuild = {STAT_NAME: ramp_stat, BUDGET_NAME: ramp_budget_stat, STAGES_NAME: ramp_stages_stat}
    return objective.replace(derived=tuple(rebuild[d.name](new) if d.name in rebuild else d for d in objective.derived))


def context_changes(main_link: list[str], part_name: str | None, config_inputs: Mapping[str, object], stack_caps: Mapping[str, tuple[int, float]] | None = None, ailment_stack_caps: Mapping[str, AilmentStacks] | None = None) -> dict[str, object]:
    """What the build says about its stack multipliers: the skill part's stage count, withered
    stacks from the conservative lane when the main link applies them per hit (Withering Touch),
    and stack-type skill options at the count the lane actually holds (D62 amendment: the value
    the build reaches inside the budget, not PoB's cap) with the share of the number they carry."""

    withered = config_inputs.get("multiplierWitheredStackCount")

    def held(var: str, cap: int) -> int:
        value = config_inputs.get(var)
        return int(min(cap, value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else int(cap)

    return {
        "stages": stages_in_part(part_name),
        "withered_stacks": int(withered) if isinstance(withered, (int, float)) else 0,
        "withered_per_hit": any(g.lower() == "withering touch" for g in main_link),
        "option_stacks": tuple((held(var, int(cap)), float(share)) for var, (cap, share) in (stack_caps or {}).items() if int(cap) > 0),
        "ailment_stacks": dict(ailment_stack_caps or {}),
    }


__all__ = ["AilmentStacks", "RAMP_KEYS", "RAMP_RELATION", "RampContext", "ailment_stacks", "components", "context_changes", "named_components", "ramp_budget", "ramp_budget_stat",
            "ramp_context", "ramp_dps", "ramp_seconds", "ramp_stages_stat", "ramp_stat", "stage_seconds", "stages_in_part", "with_ramp"]
