"""Floors that bind only while a keystone is allocated.

The optimizer judges thousands of what-if trials that never touch the build, so "only when Mind
over Matter is allocated" cannot be a Python branch on the build PoB currently holds: the
condition has to be visible in the stats of the trial itself. PoB's own `sharedMindOverMatter`
(CalcDefence.lua: the share of a hit taken from mana before life) is that witness -- 0 without
the keystone, 40 with it -- and it comes back in every readback, real or what-if.

`MoMCastsAfterMaxHit` (#608, note docs/research/2026-10-06-mom-pool-balance.md) is the derived stat for
Mind over Matter: how many casts of the main skill the unreserved mana (plus ES under Eldritch Battery) still pays
for after a hit of `f` x `PhysicalMaximumHitTaken` has been taken through the keystone's share `p`. It replaces the
hand rule "40% of the mana unreserved" (the owner, 2026-10-06: the split is judged by PoB's own EHP numbers). The
stat is not applicable while nothing takes damage from mana, and while the skill costs no mana; it then returns
`NOT_APPLICABLE`, a number far above any floor, because a floored stat that is missing counts as failed.

`ElementalOverloadUptime` works the same way. PoB grants the keystone's 40% more elemental
damage whenever the skill's crit chance is not zero (CalcOffence: `CritInPast8Sec` is set at
any crit chance above 0; no config input gates it), so a 7% effective crit on a slow channelled
Burning Arrow got the whole 40% (the user's reading 2026-09-18). The witness is
`HaveElementalOverload`, published by the headless wrapper from PoB's own `env.keystonesAdded`
after every `calcs.perform` (the tree keystone leaves no other output). The stat is 1.0 without
the keystone and the 8 s window's uptime with it, 1 - (1 - c)^(8 r) from PoB's effective crit
chance (accuracy already in) and hits per second; a minion main skill keeps it at 0 (the
minions' critical strikes are theirs, the keystone is per skill: research 2026-09-18). The floor
is `CRIT_RECENTLY_MIN_UPTIME` (0.9), the same rule the crit-recently config inputs use.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Mapping

from junkroan.optimizer.objective import DerivedStat

STAT_NAME = "MoMCastsAfterMaxHit"
HIT_FRACTION_KEY = "MoMHitFraction"  # rails_default.json floors: f, the share of the maximum hit the rail takes (0.8)
DEFAULT_HIT_FRACTION = 0.8
NOT_APPLICABLE = 1.0e6  # casts of a build the rail does not bind (no Mind over Matter, or a free skill)
KEYS = ("sharedMindOverMatter", "ManaUnreserved", "EnergyShield", "EnergyShieldProtectsMana", "ManaCost", "PhysicalMaximumHitTaken")

ES_RECHARGE_FOR_COSTS_STAT = "EnergyShieldRechargeForCosts"
ES_RECHARGE_FOR_COSTS_KEYS = (
    "EnergyShieldRecharge",
    "EnergyShieldProtectsMana",
    "sharedMindOverMatter",
    "PhysicalMindOverMatter",
    "LightningMindOverMatter",
    "ColdMindOverMatter",
    "FireMindOverMatter",
    "ChaosMindOverMatter",
)

EO_STAT_NAME = "ElementalOverloadUptime"
EO_WITNESS = "HaveElementalOverload"  # headless_wrapper.lua: 1 while PoB merged the keystone, else 0
EO_KEYS = (EO_WITNESS, "CritChance", "HitSpeed", "Speed")
CRIT_RECENTLY_WINDOW_SECONDS = 8.0  # the keystone's own window ("dealt a Critical Strike in the past 8 seconds")
CRIT_RECENTLY_MIN_UPTIME = 0.9  # the ailment rule's threshold (config_rules: 1 - (1 - p)^(hits x duration) >= 0.9)


def mom_casts_after_max_hit(stats: Mapping[str, object], hit_fraction: float = DEFAULT_HIT_FRACTION) -> float | None:
    """Casts of the main skill left after a hit of `hit_fraction` x PhysicalMaximumHitTaken.

    p = sharedMindOverMatter / 100, D = f x hit. Mana drained by the keystone's share: without Eldritch Battery
    p x max(0, D - ES) (ES takes the whole hit first), with it max(0, p x D - ES) (ES pays the p share first;
    CalcDefence.lua:330-345). Casts = (ManaUnreserved - drained) / ManaCost. NOT_APPLICABLE when p = 0 or the skill
    costs no mana; None when the hit size is not in the stats."""

    p = _num(stats, "sharedMindOverMatter") / 100.0
    if p <= 0.0 or _num(stats, "ManaCost") <= 0.0:
        return NOT_APPLICABLE
    hit = stats.get("PhysicalMaximumHitTaken")
    if not isinstance(hit, (int, float)):
        return None
    p = min(p, 1.0)
    es, d = max(0.0, _num(stats, "EnergyShield")), hit_fraction * float(hit)
    drained = max(0.0, p * d - es) if _num(stats, "EnergyShieldProtectsMana") > 0 else p * max(0.0, d - es)
    left = max(0.0, _num(stats, "ManaUnreserved") - drained)
    return left / _num(stats, "ManaCost")


@lru_cache(maxsize=8)
def mom_casts_stat(hit_fraction: float = DEFAULT_HIT_FRACTION) -> DerivedStat:
    return DerivedStat(name=STAT_NAME, keys=KEYS, fn=lambda stats, _objective: mom_casts_after_max_hit(stats, hit_fraction), context={"hit_fraction": hit_fraction})


def energy_shield_recharge_for_costs(stats: Mapping[str, object]) -> float:
    """Recharge sustains EB costs only when no damage can drain the ES pool.

    The typed Mind over Matter outputs are each independent witnesses from PoB's
    calculator, so an absent output remains unproven rather than assuming it is
    zero.
    """

    if _num(stats, "EnergyShieldProtectsMana") <= 0:
        return 0.0
    for key in ES_RECHARGE_FOR_COSTS_KEYS[2:]:
        if not isinstance(stats.get(key), (int, float)) or _num(stats, key) != 0.0:
            return 0.0
    return max(0.0, _num(stats, "EnergyShieldRecharge"))


def energy_shield_recharge_for_costs_stat() -> DerivedStat:
    return DerivedStat(
        name=ES_RECHARGE_FOR_COSTS_STAT,
        keys=ES_RECHARGE_FOR_COSTS_KEYS,
        fn=lambda stats, _objective: energy_shield_recharge_for_costs(stats),
    )


def crit_recently_uptime(stats: Mapping[str, object]) -> tuple[float, str]:
    """(uptime, detail) of "dealt a critical strike in the past 8 seconds" from PoB's own effective
    crit chance (`CritChance`, which in the effective mode already carries the accuracy roll:
    CalcOffence multiplies it by `AccuracyHitChance`) and hits per second."""

    hits = _num(stats, "HitSpeed") or _num(stats, "Speed")
    crit_pct = _num(stats, "CritChance")
    c = max(0.0, min(1.0, crit_pct / 100.0))
    if c <= 0.0 or hits <= 0.0:
        return 0.0, f"no critical strikes to keep it up ({crit_pct:.4g}% effective crit at {hits:.2f} hits/s)"
    uptime = 1.0 - (1.0 - c) ** (CRIT_RECENTLY_WINDOW_SECONDS * hits)
    return uptime, (f"{c:.1%} effective crit (PoB CritChance, accuracy in) at {hits:.2f} hits/s: "
                    f"1 - (1 - c)^({CRIT_RECENTLY_WINDOW_SECONDS:g} x r) = {uptime:.0%} of the time")


def elemental_overload_uptime(stats: Mapping[str, object], *, minion_main: bool = False) -> float:
    """1.0 without the keystone (the floor cannot bind); with it, the crit-recently uptime of the
    main skill, 0.0 when the main skill is a minion's."""

    if _num(stats, EO_WITNESS) <= 0:
        return 1.0
    if minion_main:
        return 0.0
    return crit_recently_uptime(stats)[0]


@lru_cache(maxsize=2)
def eo_uptime_stat(*, minion_main: bool = False) -> DerivedStat:
    """One instance per case, so an objective that already carries it is equal to itself after
    `with_skill_floors` runs again (the pipeline applies the skill floors more than once)."""

    return DerivedStat(name=EO_STAT_NAME, keys=EO_KEYS, fn=lambda stats, _objective: elemental_overload_uptime(stats, minion_main=minion_main), context={"minion_main": minion_main})


def _num(stats: Mapping[str, object], key: str) -> float:
    raw = stats.get(key)
    return float(raw) if isinstance(raw, (int, float)) else 0.0


__all__ = ["CRIT_RECENTLY_MIN_UPTIME", "CRIT_RECENTLY_WINDOW_SECONDS", "EO_KEYS", "EO_STAT_NAME", "EO_WITNESS", "ES_RECHARGE_FOR_COSTS_KEYS",
           "ES_RECHARGE_FOR_COSTS_STAT", "HIT_FRACTION_KEY", "KEYS", "NOT_APPLICABLE", "STAT_NAME", "crit_recently_uptime", "elemental_overload_uptime",
           "energy_shield_recharge_for_costs", "energy_shield_recharge_for_costs_stat", "eo_uptime_stat", "mom_casts_after_max_hit", "mom_casts_stat"]
