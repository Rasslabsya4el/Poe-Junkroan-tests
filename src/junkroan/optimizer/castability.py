"""Costed player-skill resources observed from the active PoB skill state.

The player must have enough resource to use every enabled active skill PoB
checks, including triggered skills. This is deliberately based on PoB's
active-skill entries, parsed skill types, and per-active-skill costs rather than
gem names.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping

from junkroan.optimizer.objective import DerivedStat, Objective

MANA_COST_POOL_STAT = "ManaCostPool"
MANA_OVER_RESERVED_STAT = "ManaOverReserved"  # the floor of `ManaUnreserved >= 0` (#171), see mana_over_reserved_stat
MANA_COST_STAT = "CostedManaCost"
LIFE_COST_STAT = "CostedLifeCost"
_COST_RELATIONS = frozenset({
    (MANA_COST_POOL_STAT, MANA_COST_STAT),
    ("LifeUnreserved", LIFE_COST_STAT),
})


_COST_VIOLATION_KEYS = frozenset({
    f"{MANA_COST_POOL_STAT}>={MANA_COST_STAT}", f"{MANA_COST_POOL_STAT}>=ManaCost",
    f"LifeUnreserved>={LIFE_COST_STAT}", "LifeUnreserved>=LifeCost",
})


def castability_violations(objective: Objective, stats: Mapping[str, object]) -> dict[str, float]:
    """The missed cost relations of `objective.violations(stats)`: a costed skill (the frozen maximum of the others, or the live
    main skill PoB prices in the trial) that the pool cannot pay for once, the failure `audit_castability` reports as an error."""

    return {key: value for key, value in objective.violations(stats).items() if key in _COST_VIOLATION_KEYS}


@dataclass(frozen=True, slots=True)
class CostedSkill:
    """One enabled player active skill with known PoB costs."""

    name: str
    granted_effect_id: str
    active_skill_id: str
    mana_cost: float | None
    life_cost: float | None
    mana_reservation_percent: float | None
    life_reservation_percent: float | None
    triggered: bool


@dataclass(frozen=True, slots=True)
class CastabilityContext:
    """The frozen largest resource costs for one skills surface."""

    requirements: tuple[tuple[str, float | None, float | None], ...]
    mana_cost: float | None
    life_cost: float | None
    skills: tuple[CostedSkill, ...]
    live_active_skill_ids: frozenset[str] = frozenset()
    # Every costed skill, the live main skill included: the audit names them
    # all, while the frozen relations keep excluding the one PoB prices live
    # inside each trial. Only filled when the caller asked for it.
    all_skills: tuple[CostedSkill, ...] = ()


@dataclass(slots=True)
class CastabilityMetrics:
    """PoB work spent reading frozen active-skill costs for one build."""

    calls: int = 0
    seconds: float = 0.0


@lru_cache(maxsize=1)
def _trigger_support_ids() -> frozenset[str]:
    """Granted-effect ids of trigger supports, from the parsed PoB support corpus."""

    from junkroan.search.hypothesis import support_gems

    return frozenset(
        str(record.get("granted_effect_id"))
        for record in support_gems().values()
        if "trigger" in {str(tag).lower() for tag in (record.get("tag_keys") or ())}
        and record.get("granted_effect_id")
    )


def _groups(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    skills = state.get("skills_state") or {}
    return [group for group in (skills.get("socket_groups") or ()) if isinstance(group, Mapping)]


def _effect_id(entry: Mapping[str, Any], group: Mapping[str, Any]) -> str | None:
    """The active effect id, falling back to its observed source gem when available."""

    value = entry.get("granted_effect_id")
    if isinstance(value, str) and value:
        return value
    source = entry.get("source_gem_entry_id")
    for gem in group.get("gems") or ():
        if isinstance(gem, Mapping) and gem.get("gem_entry_id") == source:
            value = gem.get("skill_id")
            if isinstance(value, str) and value:
                return value
    return None


def _triggered(entry: Mapping[str, Any], group: Mapping[str, Any]) -> bool:
    """Whether PoB marks an entry as triggered, including linked trigger children."""

    if entry.get("triggered") is True:
        return True
    if entry.get("trigger_label") is None:
        return False
    gems = {
        str(gem.get("gem_entry_id")): str(gem.get("skill_id") or "")
        for gem in (group.get("gems") or ())
        if isinstance(gem, Mapping) and gem.get("gem_entry_id")
    }
    links = {
        str(link.get("skill_id") or "")
        for link in (entry.get("support_links") or ())
        if isinstance(link, Mapping)
    }
    links.update(
        gems.get(str(link.get("source_gem_entry_id")), "")
        for link in (entry.get("support_links") or ())
        if isinstance(link, Mapping) and link.get("source_gem_entry_id")
    )
    return bool(links & _trigger_support_ids())


def _cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0.0 else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _reservation(value: object) -> float | None:
    value = _number(value)
    return value if value is not None and value >= 0.0 else None


def _skill_entries(pob: Any) -> tuple[tuple[str, str, str, bool], ...]:
    """Enabled player active skills as PoB identifies them, without a calc."""

    if not callable(getattr(pob, "read_state", None)):
        return ()
    candidates: list[tuple[str, str, str, bool]] = []
    for group in _groups(pob.read_state()):
        if group.get("enabled") is False or group.get("slot_enabled") is False:
            continue
        for entry in group.get("active_skill_entries") or ():
            # A `minion_id` marks the entry that SUMMONS a minion -- the player
            # casts it and pays for it, and PoB's own ManaCostWarningList names
            # it (three Summon Golems at 52 against 33 unreserved on
            # vd_spellslinger s1, measured 2026-09-20). A minion's own attack
            # is never in the player's socket groups, so nothing here excludes
            # one. A gem the gem-count rule disabled stays out.
            if not isinstance(entry, Mapping) or entry.get("enabled") is False:
                continue
            effect_id = _effect_id(entry, group)
            if not effect_id:
                continue
            name = entry.get("name")
            active_id = entry.get("active_skill_id")
            if not isinstance(active_id, str) or not active_id:
                continue
            candidates.append((str(name) if isinstance(name, str) and name else effect_id, effect_id, active_id, _triggered(entry, group)))
    return tuple(candidates)


def _costed_skills(entries: Iterable[tuple[str, str, str, bool]], rows: Mapping[str, object]) -> tuple[CostedSkill, ...]:
    """Turn an active-skill stats read into costed player skills."""

    out: list[CostedSkill] = []
    for name, effect_id, active_id, triggered in entries:
        row = rows.get(active_id)
        if not isinstance(row, Mapping):
            continue
        mana_cost, life_cost = _cost(row.get("ManaCost")), _cost(row.get("LifeCost"))
        # A skill with no observed cost tells the objective nothing. A life-only
        # skill remains in `out` so its life requirement is still enforced.
        if not ((mana_cost or 0.0) > 0.0 or (life_cost or 0.0) > 0.0):
            continue
        out.append(CostedSkill(
            name,
            effect_id,
            active_id,
            mana_cost,
            life_cost,
            _reservation(row.get("ManaReservedPercent")),
            _reservation(row.get("LifeReservedPercent")),
            triggered,
        ))
    return tuple(out)


def _active_skill_stats(pob: Any, ids: Iterable[str], *, metrics: CastabilityMetrics | None = None) -> Mapping[str, object]:
    """Read one or more active skills and account for the expensive PoB calc."""

    ids = tuple(dict.fromkeys(ids))
    if not ids or not callable(getattr(pob, "active_skill_stats", None)):
        return {}
    import time

    started = time.perf_counter()
    rows = pob.active_skill_stats(ids, ("ManaCost", "LifeCost", "ManaReservedPercent", "LifeReservedPercent"))
    if metrics is not None:
        metrics.calls += 1
        metrics.seconds += time.perf_counter() - started
    return rows if isinstance(rows, Mapping) else {}


def costed_skills(pob: Any) -> tuple[CostedSkill, ...]:
    """PoB's enabled, costed player active skills.

    Reservation skills are the exception in PoB's affordability warning: their
    cost is checked against the pool before their own reservation. A summon
    skill is the player's own cost like any other. Triggered player skills
    remain because PoB charges them normally.
    """

    entries = _skill_entries(pob)
    return _costed_skills(entries, _active_skill_stats(pob, (entry[2] for entry in entries)))


def _cost_requirement(cost: float | None, reservation_percent: float | None, pool: object) -> float | None:
    if cost is None or cost <= 0.0:
        return None
    raw_pool = _number(pool)
    reservation = math.ceil(raw_pool * reservation_percent / 100.0) if raw_pool is not None and reservation_percent else 0.0
    return max(0.0, cost - reservation)


def costed_costs(pob: Any) -> tuple[float | None, float | None]:
    """Largest resource requirements after PoB's own reservation exception."""

    skills = costed_skills(pob)
    pools = pob.stats(("Mana", "Life")) if skills and callable(getattr(pob, "stats", None)) else {}
    mana = [
        value for skill in skills
        if (value := _cost_requirement(skill.mana_cost, skill.mana_reservation_percent, pools.get("Mana"))) is not None
    ]
    life = [
        value for skill in skills
        if (value := _cost_requirement(skill.life_cost, skill.life_reservation_percent, pools.get("Life"))) is not None
    ]
    return (max(mana) if mana else None, max(life) if life else None)


def _live_active_skill_ids(pob: Any) -> frozenset[str]:
    state = pob.read_state() if callable(getattr(pob, "read_state", None)) else {}
    skills = state.get("skills_state") or {}
    main_group_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    for group in skills.get("socket_groups") or ():
        if isinstance(group, Mapping) and group.get("socket_group_id") == main_group_id:
            entries = group.get("active_skill_entries") or ()
            index = int(group.get("main_active_skill_index") or 1)
            if 1 <= index <= len(entries) and isinstance(entries[index - 1], Mapping):
                active_id = entries[index - 1].get("active_skill_id")
                return frozenset({str(active_id)}) if active_id else frozenset()
    return frozenset()


def castability_context(pob: Any, *, metrics: CastabilityMetrics | None = None, include_live: bool = False) -> CastabilityContext:
    """Freeze every enabled player's largest cost once for the current skills surface.

    `include_live` prices the live main skill in the same read, for a caller
    that reports every uncastable skill by name (the final audit). The frozen
    requirements still leave it out: PoB prices it inside every trial.
    """

    live_ids = _live_active_skill_ids(pob)
    all_entries = _skill_entries(pob)
    entries = tuple(entry for entry in all_entries if entry[2] not in live_ids)
    rows = _active_skill_stats(pob, (entry[2] for entry in (all_entries if include_live else entries)), metrics=metrics)
    skills = _costed_skills(entries, rows)
    all_skills = _costed_skills(all_entries, rows) if include_live else skills
    pools = pob.stats(("Mana", "Life")) if (skills or all_skills) and callable(getattr(pob, "stats", None)) else {}
    requirements = tuple(
        (skill.active_skill_id,
         _cost_requirement(skill.mana_cost, skill.mana_reservation_percent, pools.get("Mana")),
         _cost_requirement(skill.life_cost, skill.life_reservation_percent, pools.get("Life")))
        for skill in skills
    )
    mana = [mana for _id, mana, _life in requirements if mana is not None]
    life = [life for _id, _mana, life in requirements if life is not None]
    return CastabilityContext(requirements, max(mana) if mana else None, max(life) if life else None, skills, live_ids, all_skills)


def replace_castability_skill(pob: Any, context: CastabilityContext, *, remove: Iterable[str] = (), active_skill_id: str | None = None,
                              metrics: CastabilityMetrics | None = None) -> CastabilityContext:
    """Replace one changed skill in a frozen context with one active-skill read.

    Candidate loops set every other socket group back to the frozen context and
    need only price the new main link or utility gem.  A removed skill needs no
    calc at all; the remaining frozen requirements still determine the maximum.
    """

    remove_ids = set(remove)
    if active_skill_id:
        remove_ids.add(active_skill_id)
    requirements = [row for row in context.requirements if row[0] not in remove_ids]
    skills = [skill for skill in context.skills if skill.active_skill_id not in remove_ids]
    live_ids = _live_active_skill_ids(pob)
    if active_skill_id:
        entry = next((entry for entry in _skill_entries(pob) if entry[2] == active_skill_id), None)
        if entry is not None and active_skill_id not in live_ids:
            skill = _costed_skills((entry,), _active_skill_stats(pob, (active_skill_id,), metrics=metrics))
            if skill:
                pools = pob.stats(("Mana", "Life")) if callable(getattr(pob, "stats", None)) else {}
                one = skill[0]
                requirements.append((one.active_skill_id,
                                     _cost_requirement(one.mana_cost, one.mana_reservation_percent, pools.get("Mana")),
                                     _cost_requirement(one.life_cost, one.life_reservation_percent, pools.get("Life"))))
                skills.append(one)
    mana = [mana for _id, mana, _life in requirements if mana is not None]
    life = [life for _id, _mana, life in requirements if life is not None]
    return CastabilityContext(tuple(requirements), max(mana) if mana else None, max(life) if life else None, tuple(skills), live_ids)


def mana_cost_pool_stat() -> DerivedStat:
    """PoB's mana-cost pool: unreserved mana plus ES under its own EB flag."""

    def pool(stats: Mapping[str, object], _objective: Objective) -> float | None:
        mana = _number(stats.get("ManaUnreserved"))
        if mana is None:
            return None
        energy_shield = _number(stats.get("EnergyShield")) or 0.0
        flag = _number(stats.get("EnergyShieldProtectsMana")) or 0.0
        return mana + energy_shield * (1.0 if flag else 0.0)

    return DerivedStat(MANA_COST_POOL_STAT, ("ManaUnreserved", "EnergyShield", "EnergyShieldProtectsMana"), pool)


def mana_over_reserved_stat() -> DerivedStat:
    """Mana reserved past the pool: 0 while the pool is whole, else what reservation took beyond it.

    PoB clamps `ManaReserved` to the pool and leaves `ManaUnreserved` negative
    (Modules/CalcPerform.lua:541-543), and warns on exactly that number: "Your unreserved Mana is
    negative" (Modules/BuildDisplayStats.lua:130). This stat is the floor of the relation
    `ManaUnreserved >= ManaOverReserved` (`rails.Rails.objective`), which is `ManaUnreserved >= 0`
    and nothing else: while the pool is whole the floor is 0 and the relation costs the build
    nothing; while it is over-reserved the floor is positive, so `objective.violations` charges the
    whole missed floor (1.0) plus the overflow relative to `Mana` -- a shortfall every mana or
    reservation move shrinks, visible inside each trial's own stats (#171, finding 1 of #155).
    """

    def over_reserved(stats: Mapping[str, object], _objective: Objective) -> float | None:
        unreserved = _number(stats.get("ManaUnreserved"))
        if unreserved is None:
            return None
        return max(0.0, -unreserved)

    return DerivedStat(MANA_OVER_RESERVED_STAT, ("ManaUnreserved",), over_reserved)


def with_castability_floors(pob: Any, objective: Objective, *, context: CastabilityContext | None = None) -> Objective:
    """Add floors for all costed player skills without replacing live main costs.

    The largest cost is fixed until the skills surface changes. Resource pools
    remain normal PoB trial stats, including the trial-local EB flag, so
    reservation, tree, and gear trials price the same relationship without
    re-selecting every active skill per candidate.
    """

    context = context or castability_context(pob)
    mana_cost, life_cost = context.mana_cost, context.life_cost
    relations = tuple(
        relation
        for relation in objective.relations
        if (str(relation[0]), str(relation[1])) not in _COST_RELATIONS
    )
    derived = tuple(stat for stat in objective.derived if stat.name not in {MANA_COST_STAT, LIFE_COST_STAT})
    if MANA_COST_POOL_STAT not in {stat.name for stat in derived}:
        derived += (mana_cost_pool_stat(),)
    if mana_cost is not None:
        derived += (DerivedStat(MANA_COST_STAT, (), lambda _stats, _objective, value=mana_cost: value, context=mana_cost),)
        relations += ((MANA_COST_POOL_STAT, MANA_COST_STAT, 1.0, "Mana"),)
    if life_cost is not None:
        derived += (DerivedStat(LIFE_COST_STAT, (), lambda _stats, _objective, value=life_cost: value, context=life_cost),)
        relations += (("LifeUnreserved", LIFE_COST_STAT, 1.0, "Life"),)
    return objective.replace(relations=relations, derived=derived)


__all__ = ["CastabilityContext", "CastabilityMetrics", "CostedSkill", "LIFE_COST_STAT", "MANA_COST_POOL_STAT", "MANA_COST_STAT", "MANA_OVER_RESERVED_STAT", "castability_context", "castability_violations", "costed_costs", "costed_skills", "mana_cost_pool_stat", "mana_over_reserved_stat", "replace_castability_skill", "with_castability_floors"]
