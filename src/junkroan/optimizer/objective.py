"""Objective: what "better" means, as a function of PoB stats.

A Score orders builds lexicographically: fewer constraint violations first,
then a higher value of the maximized stat. Violations are relative shortfalls
below floors (or excesses above ceilings), summed, so the optimizer can make
progress on constraints before chasing the objective.

Derived stats are numbers PoB does not output but its outputs determine
(time to full DPS, `optimizer/ramp.py`): computed in Python from the fetched
stats before floors and ceilings are checked, so every stage and every
what-if trial sees them for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace as _replace
from typing import Any, Callable, Literal, Mapping


@dataclass(frozen=True, slots=True)
class Score:
    """Ordered by `(value > 0, neg_violation, value)` (D88): every live score (value > 0) ranks above
    every dead one (value <= 0, a skill that stopped working never "satisfies" a floor); inside each
    class violation first, then value. A total order; equality and hash stay field-wise."""

    neg_violation: float  # -sum of relative shortfalls (0 when all floors met); larger is better
    value: float  # the maximized stat

    def _key(self) -> tuple[bool, float, float]:
        return (self.value > 0.0, self.neg_violation, self.value)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._key() < other._key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._key() <= other._key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._key() > other._key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Score):
            return NotImplemented
        return self._key() >= other._key()

    @property
    def violation(self) -> float:
        return -self.neg_violation

    @property
    def feasible(self) -> bool:
        return self.neg_violation >= 0.0


@dataclass(frozen=True, slots=True)
class DerivedStat:
    name: str  # the key it adds to the stats
    keys: tuple[str, ...]  # PoB stats it needs
    fn: Callable[[Mapping[str, object], "Objective"], float | None]  # None = not applicable (no constraint)
    context: Any = None  # whatever the stage needs to rebuild it (see ramp.with_ramp)


@dataclass(frozen=True, slots=True)
class Objective:
    maximize: str = "CombinedDPS"
    floors: Mapping[str, float] = field(default_factory=dict)  # stat -> minimum acceptable value
    # dynamic floors: stats[a] >= factor * stats[b]  (e.g. Str >= ReqStr, ManaUnreserved >= ManaCost); an optional
    # fourth element names the stat the shortfall is measured against when the floor is ~0 (ManaUnreserved vs "Mana")
    relations: tuple[tuple, ...] = ()
    ceilings: Mapping[str, float] = field(default_factory=dict)  # stat -> maximum acceptable value
    derived: tuple[DerivedStat, ...] = ()

    @property
    def stat_keys(self) -> tuple[str, ...]:
        """PoB stats to fetch: everything the floors, ceilings, relations and derived
        stats read; derived names themselves are computed, not fetched."""

        keys = [self.maximize]
        for expr in (*self.floors, *self.ceilings, *(k for rel in self.relations for k in rel[:2]), *(rel[3] for rel in self.relations if len(rel) > 3)):
            keys.extend(_parts(expr))
        for d in self.derived:
            keys.extend(d.keys)
        names = {d.name for d in self.derived}
        return tuple(k for k in dict.fromkeys(keys) if k not in names)

    def replace(self, **changes: object) -> "Objective":
        return _replace(self, **changes)  # type: ignore[arg-type]

    def without(self, *floor_keys: str) -> "Objective":
        """Same objective minus some floors (a stage that cannot deliver a floor
        efficiently, e.g. the tree and movement speed, optimizes without it)."""

        return self.replace(floors={k: v for k, v in self.floors.items() if k not in floor_keys})

    def without_sustain(self) -> "Objective":
        """Same objective minus the per-second sustain relations: a bare rig has no
        regen or leech gear yet, and with sustain enforced every support that adds
        mana cost loses (the first Fireball run picked a single support, Sacrifice)."""

        return self.replace(relations=tuple(r for r in self.relations if "PerSecond" not in r[1]))

    def derived_values(self, stats: Mapping[str, object]) -> dict[str, float | None]:
        return {d.name: d.fn(stats, self) for d in self.derived}

    def violations(self, stats: Mapping[str, object]) -> dict[str, float]:
        """Every missed floor, ceiling and relation with its relative shortfall: the
        parts of Score.violation, keyed by the constraint. Repairs are estimated per
        part (five +Str nodes each "fix" the same attribute shortfall; summed as one
        reduction they made a life repair look affordable that was not)."""

        if self.derived:
            stats = {**stats, **self.derived_values(stats)}
        out: dict[str, float] = {}
        for stat, floor in self.floors.items():
            raw = _value(stats, stat)
            observed = float(raw) if raw is not None else float("-inf")
            scale = max(1.0, abs(floor))
            if observed < floor - 1e-9 * scale:  # PoB's 1.19999 against a floor of 1.2 is not a shortfall (two Cold DoT seeds at 116% were "infeasible")
                out[stat] = (floor - observed) / scale
        for stat, ceiling in self.ceilings.items():
            raw = _value(stats, stat)
            if raw is not None and float(raw) > ceiling:
                out[f"{stat}<="] = (float(raw) - ceiling) / max(1.0, abs(ceiling))
        for rel in self.relations:
            stat, ref, factor = rel[0], rel[1], float(rel[2])
            raw_a, raw_b = _value(stats, stat), _value(stats, ref)
            if raw_a is None or raw_b is None:
                continue
            floor = factor * float(raw_b)
            a = float(raw_a)
            missed = a < floor - 1e-9 * max(1.0, abs(floor))
            if missed:
                pool = _value(stats, rel[3]) if len(rel) > 3 else None
                if pool is not None and a < 0:
                    # the pool is over-reserved: the whole floor is missing (1.0 when there is a cost) plus the
                    # excess relative to the pool, so auras over-reserving mana on a bare rig (ManaUnreserved
                    # -300 vs ManaCost 0) count 300 / Mana, not 300x a missing life node, and every mana node
                    # shrinks it (a gradient the greedy can follow)
                    out[f"{stat}>={ref}"] = (1.0 if floor > 0 else 0.0) + (-a) / max(1.0, abs(pool))
                else:
                    out[f"{stat}>={ref}"] = (floor - a) / max(1.0, abs(floor))
        return out

    def margins(self, stats: Mapping[str, object]) -> dict[str, float]:
        """The room every floor, ceiling and relation still has, relative the way `violations` measures a
        shortfall (negative = missed; keys as in `violations`; a constraint whose stat is absent is left out,
        a missing floor stat is -inf). The spare-point step (#865) ranks equal-value candidates by the smallest of
        these: the constraint nearest its limit gains first. No stat list or weight: only this objective's own."""

        if self.derived:
            stats = {**stats, **self.derived_values(stats)}
        out: dict[str, float] = {}
        for stat, floor in self.floors.items():
            raw = _value(stats, stat)
            out[stat] = (float(raw) - floor) / max(1.0, abs(floor)) if raw is not None else float("-inf")
        for stat, ceiling in self.ceilings.items():
            raw = _value(stats, stat)
            if raw is not None:
                out[f"{stat}<="] = (ceiling - float(raw)) / max(1.0, abs(ceiling))
        for rel in self.relations:
            stat, ref, factor = rel[0], rel[1], float(rel[2])
            raw_a, raw_b = _value(stats, stat), _value(stats, ref)
            if raw_a is None or raw_b is None:
                continue
            floor = factor * float(raw_b)
            out[f"{stat}>={ref}"] = (float(raw_a) - floor) / max(1.0, abs(floor))
        return out

    def score(self, stats: Mapping[str, object]) -> Score:
        violation = sum(self.violations(stats).values())
        if "MoMCastsAfterMaxHit" in self.floors:
            _trace_mom_casts(self, stats, violation)
        raw_value = stats.get(self.maximize)
        value = float(raw_value) if isinstance(raw_value, (int, float)) else float("-inf")
        return Score(neg_violation=-violation, value=value)

    def describe(self) -> str:
        parts = [f"{k} >= {v:g}" for k, v in self.floors.items()]
        parts += [f"{k} <= {v:g}" for k, v in self.ceilings.items()]
        parts += [f"{r[0]} >= {r[2]:g}*{r[1]}" if float(r[2]) != 1.0 else f"{r[0]} >= {r[1]}" for r in self.relations]
        return f"maximize {self.maximize}" + (" subject to " + ", ".join(parts) if parts else "")


def better_score(new: Score, cur: Score, *, min_gain: float = 0.0) -> bool:
    """The one acceptance rule every move of the improvement loop is judged by (D58): while a
    floor is missed any improvement of the Score ordering counts -- feasibility comes first, so a
    move that buys a floor wins even at a lower value -- and once the build is feasible the value
    must grow by `min_gain`. Written once here because the loop, the re-judged picks and the
    reserving-group drop must not drift apart.

    A floor that is met because the skill stopped working is not met: a build whose maximized stat
    has fallen to zero never beats one that still has a number, however many floors it now
    satisfies. Found on stormbrand-s1 of `core14-rules` (2026-09-20 replay bench, plan B): a region
    challenge on a build missing TotalEHP by 0.012 ended at FullDPS 0, violation 0, and was kept,
    because feasibility outranks value. It is the same shape as an empty weapon slot "satisfying"
    a sustain floor."""

    if new.value <= 0.0 < cur.value:
        return False
    # The old tuple order on purpose (#15): the type's live-over-dead order would also let a live
    # move with a larger violation replace a dead build; `better_score` keeps its own behaviour.
    if (new.neg_violation, new.value) <= (cur.neg_violation, cur.value):
        return False
    return not cur.feasible or new.value >= cur.value * (1.0 + min_gain)


def priced_value(s: Score) -> float:
    """The priced score (D116 / #553): value discounted by the relative floor violation, capped at 1.
    A hard violation-first order paid any DPS for a crumb of floor (impale_ballista cluster move:
    -74.53 % FullDPS for violation 0.0195 -> 0.0024). A dead or -inf value is never multiplied."""

    if s.value > 0.0:
        return s.value * (1.0 - min(max(s.violation, 0.0), 1.0))
    return s.value


def loop_key(s: Score) -> tuple:
    """Sort key for Scores inside the improvement loop (D116 / #553): the priced score first,
    today's `(value > 0, neg_violation, value)` order breaks a tie."""

    return (priced_value(s), *s._key())


def better_loop_score(new: Score, cur: Score, *, min_gain: float = 0.0) -> bool:
    """The improvement loop's acceptance (D116 / #553): a move is judged on floor violation and value
    together through `priced_value`. A tie of the priced values (every state at violation >= 1 prices
    at 0) is decided by `Score._key` (as in `loop_key`); a gain over a feasible build must clear `min_gain`."""

    if new.value <= 0.0 < cur.value:
        return False
    pn, pc = priced_value(new), priced_value(cur)
    if pn == pc:
        # The tie is broken by `Score._key`, the order `loop_key` sorts by, so sort and acceptance agree.
        if new._key() <= cur._key():
            return False
        return not cur.feasible or new.value >= cur.value * (1.0 + min_gain)
    if pn < pc:
        return False
    if cur.feasible:
        return pn >= pc * (1.0 + min_gain)
    return True


ScoreOrder = Literal["floors", "priced"]
"""Which order a move's candidate choice and acceptance use: "floors" is today's violation-first order
(construction and the tree optimizer), "priced" the improvement loop's (D116 / #553)."""


def score_key(order: ScoreOrder = "floors") -> Callable[[Score], tuple]:
    """Sort key of Scores under `order`, for `max(..., key=...)` / `sorted` / a `>` between two Scores.
    "floors" is `Score._key` (the order `Score`'s own comparisons use), "priced" is `loop_key`."""

    return loop_key if order == "priced" else Score._key


def accepts_under(order: ScoreOrder = "floors") -> Callable[..., bool]:
    """The acceptance rule of `order`: `better_score` or `better_loop_score` (same signature)."""

    return better_loop_score if order == "priced" else better_score


def _parts(expr: str) -> list[str]:
    return [p.strip() for p in expr.split("+") if p.strip()]


def _trace_mom_casts(objective: "Objective", stats: Mapping[str, object], violation: float) -> None:
    """#608 trace classes: a Mind over Matter evaluation checked, and a feasible one left below the floor's casts."""

    from junkroan.optimizer.keystone_floors import NOT_APPLICABLE, STAT_NAME
    from junkroan.optimizer.trace import TRACE

    values = objective.derived_values(stats)
    casts = values.get(STAT_NAME)
    if casts is None or casts >= NOT_APPLICABLE:
        return
    TRACE.add_evaluated(["mom-casts-rail-checked"])
    TRACE.add_evaluated(["mom-casts-below-n"], 1 if violation <= 0.0 and casts < objective.floors[STAT_NAME] else 0)


def _value(stats: Mapping[str, object], expr: str) -> float | None:
    """A stat key, or a "+"-joined sum of keys (missing parts count as 0; all missing = None)."""

    total, seen = 0.0, False
    for key in _parts(expr):
        raw = stats.get(key)
        if isinstance(raw, (int, float)):
            total += float(raw)
            seen = True
    return total if seen else None


# Sustain cost side (#808). A relation's cost is PoB's `<resource>PerSecondCost` -- except for a totem main skill
# (PoB sets `TotemPlacementTime` only under `skillFlags.totem`, CalcOffence.lua:1387), where PerSecondCost is
# `<resource>Cost x TotemPlacementSpeed`, the cost of re-placing totems at full speed forever, while a build pays
# for each placement only when a totem expires: `<resource>Cost x TotemsSummoned / TotemDuration`.
# A permanent minion's summon (#1015) is no cost paid without a pause either: PoB marks the main skill with
# `skillFlags.permanentMinion` (`baseFlags.permanentMinion` or the stat `infinite_minion_duration`, SkillStatMap.lua:25,
# CalcActiveSkill.lua:344: Raise Zombie, Raise Spectre, golems) and the worker hands it out as `MainSkillPermanentMinion`;
# such a skill's cost side is 0. A temporary minion (Summon Raging Spirit, Absolution, Summon Skeletons) carries no flag.
SUSTAIN_RESOURCES = ("Mana", "Life", "ES")
SUSTAIN_COST_SUFFIX = "SustainPerSecondCost"  # keeps "PerSecond" in the name: `without_sustain`, the channelling rule and the audit key on it
SUSTAIN_COST_KEYS = ("MainSkillPermanentMinion", "TotemPlacementTime", "TotemsSummoned", "TotemDuration", "ManaCost", "LifeCost", "ESCost", "EnergyShieldProtectsMana")


def sustain_cost_stat_name(resource: str) -> str:
    return f"{resource}{SUSTAIN_COST_SUFFIX}"


def _positive(stats: Mapping[str, object], key: str) -> float | None:
    raw = stats.get(key)
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0 else None


def sustain_cost(stats: Mapping[str, object], resource: str) -> float | None:
    """The per-second cost a sustain relation for `resource` ("Mana", "Life", "ES") holds the build to: PoB's
    `<resource>PerSecondCost`, 0 for the summon of a permanent minion (`MainSkillPermanentMinion`, #1015), or for a totem main skill `<resource>Cost x TotemsSummoned / TotemDuration`
    (Mana-paid cost goes to ES under EnergyShieldProtectsMana, as PoB books it, CalcOffence.lua:5793-5824).
    PoB's number stays when TotemDuration or TotemsSummoned is missing or 0, when the output is not a totem's,
    or when PoB booked no PerSecondCost for the resource (no relation is added that PoB did not have)."""

    raw = stats.get(f"{resource}PerSecondCost")
    per_second = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    if per_second is not None and _positive(stats, "MainSkillPermanentMinion"):
        return 0.0
    if per_second is None or not isinstance(stats.get("TotemPlacementTime"), (int, float)):
        return per_second
    summoned, duration = _positive(stats, "TotemsSummoned"), _positive(stats, "TotemDuration")
    if summoned is None or duration is None:
        return per_second
    shield_pays_mana = bool(_positive(stats, "EnergyShieldProtectsMana"))
    paid = {"Mana": () if shield_pays_mana else ("ManaCost",), "Life": ("LifeCost",), "ES": ("ESCost", "ManaCost") if shield_pays_mana else ("ESCost",)}[resource]
    cost = sum(_positive(stats, key) or 0.0 for key in paid)
    return cost * summoned / duration if cost > 0 else per_second


def sustain_cost_stat(resource: str) -> DerivedStat:
    """The derived stat the rails' sustain relation names as its cost side (`sustain_cost`)."""

    return DerivedStat(sustain_cost_stat_name(resource), (f"{resource}PerSecondCost", *SUSTAIN_COST_KEYS), lambda stats, _objective, r=resource: sustain_cost(stats, r))


MAX_HIT_KEYS = ("PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken")
ELEMENTAL_RESIST_MAX_KEYS = ("FireResistMax", "ColdResistMax", "LightningResistMax")
ELEMENTAL_RESIST_RELATIONS = tuple((stat, maximum, 1.0) for stat, maximum in zip(("FireResist", "ColdResist", "LightningResist"), ELEMENTAL_RESIST_MAX_KEYS))


def max_hit_floors(stats: Mapping[str, object], *, factor: float = 0.95) -> dict[str, float]:
    """Floors that keep the maximum hit taken of each damage type near where it is (D53):
    PoB's maximum hit carries no block, evasion or partial suppression (only suppression
    at 100% counts as mitigation), so it is the bossing defence; TotalEHP, which averages
    block in, is the mapping number and stays in the report."""

    out: dict[str, float] = {}
    for key in MAX_HIT_KEYS:
        raw = stats.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            out[key] = float(raw) * factor
    return out


def bossing_defence(stats: Mapping[str, object]) -> float:
    """The smallest maximum hit taken over the four damage types (0 when absent): the one
    number to break ties or rank defence on the boss lane."""

    vals = [float(stats[k]) for k in MAX_HIT_KEYS if isinstance(stats.get(k), (int, float))]
    return min(vals) if vals else 0.0


__all__ = ["DerivedStat", "ELEMENTAL_RESIST_MAX_KEYS", "ELEMENTAL_RESIST_RELATIONS", "MAX_HIT_KEYS", "Objective", "Score", "ScoreOrder", "accepts_under", "better_loop_score", "better_score", "loop_key", "priced_value", "score_key", "bossing_defence", "max_hit_floors"]
