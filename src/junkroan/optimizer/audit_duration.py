"""#967 checks A, B and C of the build check: numbers PoB gives for the same skill, no constant in seconds.

A: an ailment (Ignite, Bleed) whose DPS is larger than the skill's hit TotalDPS while fewer than two applications
overlap (`<Ailment>StackPotential` under 2): the ailment barely holds. B: a skill whose `*Uptime` is under 100
(PoB's own uptime of a cooldown skill: it is down part of the time). Findings are warnings only; nothing here
moves a number, a rank or an audit error.

C: a skill FullDPS counts more than once whose copies end on a duration (a Brand attached more than once, a duration
minion with a count above 1): the share of time spent recasting, `copies x Time / duration`, always printed for such
a skill (the reader judges it). Copies of a Brand are PoB's own `AttachedBrandCount` (CalcPerform.lua:1323-1326, the
number PoB multiplies the brand's own DPS by, CalcOffence.lua:2423-2425; the gem's own count is 1 since #963, so
FullDPS multiplies by it once). Copies of a duration minion skill are the count FullDPS multiplies by (Calcs.lua:149-169: the
socket group's `groupCount` when set, else the gem's `count`), and only when one use of the skill makes one copy that
lives on its `Duration` (Summon Raging Spirit); a skill whose copy has its own secondary duration and is summoned by
another event (Absolution: a kill under the debuff) gets no C line (`is_cast_copy_duration_minion`). The duration of a Brand is its primary `Duration` (the
attached time PoB itself uses, `BrandTicks`, CalcOffence.lua:2407-2408) and, where the skill has none (Penance
Brand: `UnlimitedBrandDuration`), its `DurationSecondary`; the warning names the key used.

Only the entry `audit_duration` touches PoB: `read_state` (cached by the session) to find the skills included in
FullDPS and their counts, and one `active_skill_stats` call for those skills. The checks themselves are pure
functions of numbers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from junkroan.pob.skill_facts import is_cast_copy_duration_minion

AILMENTS = ("Ignite", "Bleed")
UPTIME_KEYS = ("DurationUptime", "DurationSecondaryUptime", "DurationTertiaryUptime", "AuraDurationUptime")
# The keys the one per-skill read asks for; A, B and C read from it.
DURATION_KEYS = (
    "TotalDPS",
    "Time",
    "Duration",
    "DurationSecondary",
    "AttachedBrandCount",
    *(f"{ailment}DPS" for ailment in AILMENTS),
    *(f"{ailment}StackPotential" for ailment in AILMENTS),
    *(f"{ailment}Duration" for ailment in AILMENTS),
    *UPTIME_KEYS,
)
# "fewer than two applications overlap": a count of applications, not a time.
STACK_BOUND = 2.0


def _number(values: Mapping[str, Any], key: str) -> float | None:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def ailment_findings(skill: str, values: Mapping[str, Any]) -> list[str]:
    """Check A for one skill's PoB numbers: the ailment's DPS beats the hit's TotalDPS and fewer than two of its
    applications overlap. Silent when a key is missing (the ailment is not this skill's damage)."""

    hit = _number(values, "TotalDPS")
    found: list[str] = []
    for ailment in AILMENTS:
        dps = _number(values, f"{ailment}DPS")
        stacks = _number(values, f"{ailment}StackPotential")
        duration = _number(values, f"{ailment}Duration")
        if hit is None or dps is None or stacks is None or duration is None:
            continue
        if dps > hit and stacks < STACK_BOUND:
            found.append(
                f"{skill}: {ailment} lasts {duration:.2f} s and is held by {stacks:.2f} applications at once "
                f"({ailment}Duration, {ailment}StackPotential)"
            )
    return found


def uptime_findings(skill: str, values: Mapping[str, Any]) -> list[str]:
    """Check B for one skill's PoB numbers: any of PoB's `*Uptime` keys under 100 percent."""

    found: list[str] = []
    for key in UPTIME_KEYS:
        value = _number(values, key)
        if value is not None and value < 100:
            found.append(f"{skill}: {key} {value:.1f}% (PoB's uptime of a cooldown skill: the skill is down part of the time)")
    return found


def recast_findings(skill: str, values: Mapping[str, Any], *, count: int = 1, duration_minion: bool = False) -> list[str]:
    """Check C for one skill's PoB numbers: copies kept up by recasting. A Brand (PoB wrote `AttachedBrandCount`) has
    that many copies; a duration minion skill has `count`, the number FullDPS multiplies it by. Silent for a single
    copy, a skill with no duration or no cast `Time`; otherwise always warns with the three numbers and the share."""

    time = _number(values, "Time")
    if time is None or time <= 0:
        return []
    attached = _number(values, "AttachedBrandCount")
    if attached is not None:
        copies = attached
        duration_key = next((key for key in ("Duration", "DurationSecondary") if (_number(values, key) or 0) > 0), None)
        copies_key = "AttachedBrandCount"
    elif duration_minion and count > 1 and (_number(values, "Duration") or 0) > 0:
        copies, duration_key, copies_key = float(count), "Duration", "count in FullDPS"
    else:
        return []
    if copies <= 1 or duration_key is None:
        return []
    duration = float(values[duration_key])
    share = copies * time / duration * 100
    return [
        f"{skill}: {copies:g} copies ({copies_key}) end on {duration_key} {duration:.2f} s and are recast every Time {time:.3f} s: "
        f"{share:.0f} % of the time is spent recasting ({copies:g} x {time:.3f} / {duration:.2f})"
    ]


def skill_counts(state: Mapping[str, Any]) -> dict[str, tuple[str, int]]:
    """active_skill_id -> (granted_effect_id, count FullDPS multiplies the skill by) for the active skill set.
    PoB's own rule (Calcs.lua:149-169): the socket group's `groupCount` when it is set, else the `count` of the
    gem that grants the skill; `read_state` shows an unset `groupCount` as 1, so a group count of 1 reads the gem."""

    skills = state.get("skills_state") or {}
    sets = [skill_set for skill_set in (skills.get("skill_sets") or []) if isinstance(skill_set, dict)]
    active = [skill_set for skill_set in sets if skill_set.get("skill_set_id") == skills.get("active_skill_set_id")] or sets
    counts: dict[str, tuple[str, int]] = {}
    for skill_set in active:
        for group in skill_set.get("socket_groups") or []:
            if not isinstance(group, dict):
                continue
            gems = {gem.get("gem_entry_id"): gem for gem in group.get("gems") or [] if isinstance(gem, dict)}
            group_count = group.get("group_count") or 1
            for entry in group.get("active_skill_entries") or []:
                if not isinstance(entry, dict) or not entry.get("active_skill_id"):
                    continue
                gem = gems.get(entry.get("source_gem_entry_id")) or {}
                count = int(group_count) if group_count != 1 else int(gem.get("count") or 1)
                counts[str(entry["active_skill_id"])] = (str(entry.get("granted_effect_id") or ""), count)
    return counts


def included_active_skills(state: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(name, active_skill_id) of every enabled active skill in an enabled socket group that PoB includes in FullDPS,
    in the active skill set (the set of `read_state`'s `skills_state`; every set when none is active)."""

    skills = state.get("skills_state") or {}
    sets = [skill_set for skill_set in (skills.get("skill_sets") or []) if isinstance(skill_set, dict)]
    active = [skill_set for skill_set in sets if skill_set.get("skill_set_id") == skills.get("active_skill_set_id")] or sets
    rows: list[tuple[str, str]] = []
    for skill_set in active:
        for group in skill_set.get("socket_groups") or []:
            if not isinstance(group, dict) or not group.get("include_in_full_dps") or not group.get("enabled", True):
                continue
            for entry in group.get("active_skill_entries") or []:
                if isinstance(entry, dict) and entry.get("enabled", True) and entry.get("active_skill_id"):
                    skill_id = str(entry["active_skill_id"])
                    rows.append((str(entry.get("name") or skill_id), skill_id))
    return rows


def audit_duration(pob: Any) -> list:
    """Checks A, B and C over every skill PoB includes in FullDPS: one `read_state` (cached) and, when any skill is
    included, one `active_skill_stats` call for those skills. Returns `Finding("warning", "duration", detail)`."""

    from junkroan.optimizer.audit import Finding  # audit.py imports this module at its top; the class is read at call time

    state = pob.read_state()
    included = included_active_skills(state)
    if not included:
        return []
    rows = pob.active_skill_stats([skill_id for _, skill_id in included], DURATION_KEYS)
    counts = skill_counts(state)
    findings = []
    for name, skill_id in included:
        values = rows.get(skill_id) or {}
        granted_effect_id, count = counts.get(skill_id, ("", 1))
        minion = bool(granted_effect_id) and is_cast_copy_duration_minion(granted_effect_id)
        for detail in ailment_findings(name, values) + uptime_findings(name, values) + recast_findings(name, values, count=count, duration_minion=minion):
            findings.append(Finding("warning", "duration", detail))
    return findings


__all__ = ["AILMENTS", "DURATION_KEYS", "UPTIME_KEYS", "ailment_findings", "audit_duration", "included_active_skills", "recast_findings", "skill_counts", "uptime_findings"]
