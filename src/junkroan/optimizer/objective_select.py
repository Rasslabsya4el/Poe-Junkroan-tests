"""Which PoB number a build maximizes: the player's CombinedDPS, the requested damage mode's own
number, or FullDPS when the main skill is counted by instance: a minion skill (PoB puts minion
damage there and the player's own number stays 0; Summon Raging Spirit screened
at 0 everywhere), a totem skill (CombinedDPS is one ballista, FullDPS is the
gem count of them at PoB's ActiveTotemLimit: Tuadh's Shrapnel Ballista 95,177
vs 557,631, 2026-09-15), a brand or a corpse-fed skill.

The instance count wins over the mode: it is a PoB number that the tree and the ascendancy move
(D37, D56, D57), so `--mode hit` on Storm Brand still maximizes FullDPS and not the single
brand's TotalDPS. `maximized_stat` is that rule in one place; the mode probe uses it too.

The floors and relations are the rails' in every case (D37), plus the ones the main skill's own
kind imposes (`with_skill_floors`: hit chance on attacks, full sustain on channelled skills)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails, pool_floor_for

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"


@lru_cache(maxsize=1)
def _gem_tags() -> dict[str, set[str]]:
    recs = json.loads((CORPUS / "active_gems.json").read_text(encoding="utf-8"))["records"]
    return {r["name"].lower(): set(r.get("tag_keys") or []) for r in recs}


def is_minion_skill(name: str) -> bool:
    return bool(_gem_tags().get(name.lower(), set()) & {"minion"})


def counts_instances(name: str) -> bool:
    """Is this skill's damage counted per instance in PoB's FullDPS (minions, totems, brands, and
    the corpse-fed skills that fire once per corpse consumed: the families whose count is derived
    from a PoB number, D57)?"""

    from junkroan.pob.skill_facts import corpses_consumed_per_cast
    from junkroan.search.hypothesis import active_gems

    if _gem_tags().get(name.lower(), set()) & {"minion", "totem", "brand"}:
        return True
    rec = active_gems().get(name.lower())
    return bool(rec and corpses_consumed_per_cast(str(rec.get("granted_effect_id") or "")))


MODE_STATS = {"hit": "TotalDPS", "dot": "TotalDotDPS", "ignite": "IgniteDPS", "poison": "TotalPoisonDPS", "bleed": "BleedDPS", "minion": "FullDPS"}


def maximized_stat(main_skill: str, mode: str | None = None) -> str:
    """The PoB stat a build on this main skill maximizes (the one rule, used by `objective_for`
    and by the mode probe so a request and the benchmark cannot disagree):

    * an **instance-counted** main skill (`counts_instances`: minions, totems, brands, corpse-fed
      skills) maximizes `FullDPS` whatever the mode -- the instance count is itself a PoB number
      that moves with the tree and the ascendancy (Hierophant buys brands), so an objective on the
      per-instance number optimizes the wrong build (D37, D56, D57). `mode="minion"` already means
      FullDPS, so it is unchanged;
    * otherwise the **mode's** own PoB number (docs/REQUEST.md 2) so supports, ascendancy nodes,
      tree and gear are built for it;
    * with no mode, `CombinedDPS`.
    """

    if counts_instances(main_skill):
        return "FullDPS"
    if mode and mode in MODE_STATS:
        return MODE_STATS[mode]
    return "CombinedDPS"

HIT_CHANCE_FLOOR = 95.0  # the user's rail, 2026-09-18: below it an attack build "just feels bad" (kinetic_bolt_wander at 83%)


def with_skill_floors(main_skill: str, obj: Objective) -> Objective:
    """The floors the main skill's own kind imposes, from its gem tags (the user's rails,
    2026-09-18 reading):

    * an **attack** keeps PoB's HitChance at 95 or better -- accuracy is a gate on whether the
      damage happens at all, and the objective judges it against a unique boss, so 95 on the
      boss is a lower bound for maps (D54 keeps that number honest by forbidding conditional
      accuracy);
    * a **channelling** main skill sustains 100% of its per-second cost instead of the rails'
      85%: the channel stops the moment the resource runs out, and a flask sip does not cover
      it the way it covers a cast (Cyclone at 39.3 mana/s regen against 43.84/s cost);
    * **Elemental Overload** is allocated only where the main skill keeps "crit recently" up
      90% of the time (`keystone_floors.ElementalOverloadUptime`: 1.0 without the keystone, so
      the floor binds on the very trial that takes it; 0 for a minion main skill, whose crits
      are the minions'). PoB itself grants the 40% at any crit chance above zero.

    Idempotent: applying it twice changes nothing, so it can sit on every path that builds the
    objective."""

    from junkroan.optimizer.keystone_floors import CRIT_RECENTLY_MIN_UPTIME, EO_STAT_NAME, eo_uptime_stat

    tags = _gem_tags().get(main_skill.lower(), set())
    if "attack" in tags:
        obj = obj.replace(floors={**obj.floors, "HitChance": HIT_CHANCE_FLOOR})
    if "channelling" in tags:
        obj = obj.replace(relations=tuple((r[0], r[1], 1.0, *r[3:]) if "PerSecond" in r[1] else r for r in obj.relations))
    derived = tuple(d for d in obj.derived if d.name != EO_STAT_NAME) + (eo_uptime_stat(minion_main="minion" in tags),)
    return obj.replace(derived=derived, floors={**obj.floors, EO_STAT_NAME: CRIT_RECENTLY_MIN_UPTIME})


def forced_keystones_of(skeleton) -> tuple[str, ...]:
    """The names of the keystones a request forces (`skeleton.forced_nodes` are node ids, #1029): the
    input `objective_for` needs for the defence-pool floor (#1044). A skeleton with none gives ()."""

    ids = [int(n) for n in (getattr(skeleton, "forced_nodes", None) or ())]
    if not ids:
        return ()
    from junkroan.optimizer.tree_graph import TreeGraph

    nodes = TreeGraph.load().nodes
    return tuple(nodes[i].name for i in ids if i in nodes and nodes[i].kind == "keystone")


def objective_for(rails: Rails, main_skill: str, base: Objective | None = None, *, mode: str | None = None,
                  forced_keystones: tuple[str, ...] | list[str] = ()) -> Objective:
    """The rails objective with the maximized stat from `maximized_stat`: FullDPS for an
    instance-counted main skill whatever the mode, else the mode's own PoB number
    (docs/REQUEST.md 2), else CombinedDPS. The final ranking across modes uses CombinedDPS
    regardless.

    The instance count outranks the mode (2026-09-18, found by the CLI smoke): `junkroan build
    --skill "Storm Brand" --mode hit` maximized TotalDPS, one brand, while the benchmark's
    `objective_for(rails, "Storm Brand")` maximized FullDPS, all of them -- the same skeleton
    optimized for two different numbers depending on which path built it.

    The skill's own floors (hit chance, sustain) are applied whatever the stat."""

    obj = base if base is not None else rails.objective(forced_keystones=forced_keystones)
    if forced_keystones:  # #1044: a forced Chaos Inoculation moves the Life floor to EnergyShield, also on a base built without it
        obj = obj.replace(floors=pool_floor_for(obj.floors, forced_keystones))
    obj = with_skill_floors(main_skill, obj)
    if obj.maximize != "CombinedDPS":
        return obj
    stat = maximized_stat(main_skill, mode)
    return obj if stat == obj.maximize else obj.replace(maximize=stat)


__all__ = ["HIT_CHANCE_FLOOR", "objective_for", "forced_keystones_of", "maximized_stat", "is_minion_skill", "counts_instances", "with_skill_floors"]
