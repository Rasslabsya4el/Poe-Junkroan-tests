"""Damage modes of a skill and which ascendancies serve them, measured in PoB.

A build's *idea* (Essence Drain as a DoT, Lightning Arrow as a poison delivery)
must be fixed before any rig or screen: a bare rig always favours the hit
because a hit is cheap to scale and a DoT needs the investment that only the
full pipeline makes. So the idea is read off PoB numbers, not guessed:

  1. composition: the skill alone at the rails' gem level on a neutral rig ->
     PoB's hit DPS, own DoT DPS, and, with one enabling support linked, ignite /
     poison / bleed DPS. A mode exists when its number is > 0.
  2. ascendancies per mode: for each ascendancy, its notables are picked
     greedily for the mode's stat alone (no floors); the gain over the bare
     start ranks ascendancies for that mode. Assassin gives a DoT nothing.

The report is text so the choice can be read before anything is built (D38).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from junkroan.report_format import human_duration
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.objective_select import maximized_stat
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.hypothesis import active_gems, ascendancies, normalize_ascendancy_ids
from junkroan.search.skeleton import Skeleton

# mode -> (PoB stat that is the mode's damage, support that enables it on a hit skill or None)
MODES = {
    "hit": ("TotalDPS", None),
    "dot": ("TotalDotDPS", None),
    "ignite": ("IgniteDPS", "Combustion"),
    "poison": ("TotalPoisonDPS", "Chance to Poison"),
    "bleed": ("BleedDPS", "Chance to Bleed"),
    "minion": ("FullDPS", None),  # FullDPS is the full number for any skill; it is the minion's only number
}


@dataclass(slots=True)
class ModeProbe:
    mode: str
    stat: str
    enabler: str | None
    rig_value: float  # the mode's DPS on the neutral rig (with the enabler if any)
    ascendancy_gains: dict[str, float] = field(default_factory=dict)  # ascendancy id -> mode DPS after its notables
    ascendancy_notables: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ModeReport:
    skill: str
    composition: dict[str, float]
    probes: list[ModeProbe]
    seconds: float = 0.0

    def text(self) -> str:
        lines = [f"# {self.skill}: damage modes by PoB ({human_duration(self.seconds)})", "",
                 "composition on a neutral rig (gem alone, rails gem level): " + ", ".join(f"{'full' if k == 'minion' else k} {v:,.0f}" for k, v in self.composition.items() if v),
                 ""]
        for p in self.probes:
            if p.rig_value <= 0:
                lines.append(f"- {p.mode}: 0 on the rig{' even with ' + p.enabler if p.enabler else ''}; not a mode for this skill")
                continue
            lines.append(f"- {p.mode} ({p.stat}{', enabler ' + p.enabler if p.enabler else ''}): rig {p.rig_value:,.0f}")
            ranked = sorted(p.ascendancy_gains.items(), key=lambda kv: kv[1], reverse=True)
            for asc, value in ranked:
                lines.append(f"    {asc:14s} {value:>10,.0f}  x{value / p.rig_value if p.rig_value else 0:.2f}  [{p.ascendancy_notables.get(asc, '')}]")
        return "\n".join(lines)


def _stat(pob: PobSession, key: str) -> float:
    v = pob.stats((key,)).get(key)
    return float(v) if isinstance(v, (int, float)) else 0.0


def probe_composition(pob: PobSession, skill: str, rails: Rails | None = None, *, rig_class: tuple[str, str] = ("Scion", "Ascendant")) -> dict[str, float]:
    """The skill's damage components on a neutral rig (gem alone, rails gem level), by PoB."""

    rails = rails or Rails.load()
    sk = Skeleton(class_name=rig_class[0], ascendancy=rig_class[1], level=rails.level, main_link=[skill])
    sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
    gen = SkeletonGenerator(pob, rails, objective=Objective(maximize="CombinedDPS"))
    gen.pick_skill_part(sk)
    gen.screen_bases(sk, n=20)
    return {m: _stat(pob, stat) for m, (stat, _e) in MODES.items()}


def probe_skill(pob: PobSession, skill: str, rails: Rails | None = None, *, ascendancy_ids: list[str] | None = None,
                rig_class: tuple[str, str] = ("Scion", "Ascendant"), log: Callable[[str], None] | None = None) -> ModeReport:
    rails = rails or Rails.load()
    ascendancy_ids = normalize_ascendancy_ids(ascendancy_ids)
    log = log or (lambda _m: None)
    t0 = time.perf_counter()
    tags = set(active_gems().get(skill.lower(), {}).get("tag_keys") or [])
    is_minion = "minion" in tags

    def rig(main_link: list[str], cls: tuple[str, str]) -> Skeleton:
        sk = Skeleton(class_name=cls[0], ascendancy=cls[1], level=rails.level, main_link=list(main_link))
        sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        gen = SkeletonGenerator(pob, rails, objective=Objective(maximize="CombinedDPS"))
        gen.pick_skill_part(sk)
        gen.screen_bases(sk, n=20)  # a weapon of the right type; the base screen's random rolls are enough for composition
        return sk

    # 1) composition
    base = rig([skill], rig_class)
    composition = {m: _stat(pob, stat) for m, (stat, _e) in MODES.items()}
    probes: list[ModeProbe] = []
    for mode, (stat, enabler) in MODES.items():
        if mode == "minion" and not is_minion:
            continue
        if mode in ("ignite", "poison", "bleed") and is_minion:
            continue
        link = [skill, enabler] if enabler else [skill]
        if enabler:
            try:
                rig(link, rig_class)
            except Exception as exc:  # the support cannot link (bleed on a spell)
                log(f"{mode}: {enabler} cannot support {skill} ({str(exc)[:60]})")
                probes.append(ModeProbe(mode=mode, stat=stat, enabler=enabler, rig_value=0.0))
                continue
        else:
            rig(link, rig_class)
        value = _stat(pob, stat)
        probe = ModeProbe(mode=mode, stat=stat, enabler=enabler, rig_value=value)
        probes.append(probe)
        if value <= 0:
            continue
        # 2) ascendancies for this mode: notables picked for the stat a build on this skill would
        # maximize (`maximized_stat`: the mode's own number, but FullDPS for an instance-counted
        # skill -- Hierophant's notables buy brands, which the per-instance number cannot see).
        # The report still shows the mode's own stat, so its columns are unchanged.
        objective = Objective(maximize=maximized_stat(skill, mode))
        for asc in ascendancies().values():
            if ascendancy_ids and asc["ascendancy_id"] not in ascendancy_ids:
                continue
            sk = Skeleton(class_name=asc["class_name"], ascendancy=asc["ascendancy_id"], level=rails.level, main_link=link, main_part=base.main_part, rare_bases=dict(base.rare_bases))
            sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
            gen = SkeletonGenerator(pob, rails, objective=objective)
            gen.screen_bases(sk, n=20)
            before = _stat(pob, stat)
            gen.pick_ascendancy_nodes(sk)
            after = _stat(pob, stat)
            probe.ascendancy_gains[asc["ascendancy_id"]] = after
            probe.ascendancy_notables[asc["ascendancy_id"]] = next((p.choice for p in gen.picks if p.what == "ascendancy"), "")
            log(f"{mode}/{asc['ascendancy_id']}: {before:,.0f} -> {after:,.0f}")
    return ModeReport(skill=skill, composition=composition, probes=probes, seconds=time.perf_counter() - t0)


__all__ = ["probe_skill", "probe_composition", "ModeReport", "ModeProbe", "MODES"]
