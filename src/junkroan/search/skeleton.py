"""Skeleton: the archetype-level choices the search layer makes. Everything
below it (tree fill, rare gear, config lanes) is the optimizer's job.

A skeleton is serializable and can be applied to a fresh PoB session.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from junkroan.optimizer.buff_gems import disable_unreliable_buff_gems
from junkroan.pob.session import PobSession


@dataclass(slots=True)
class SocketGroup:
    gems: list[str]  # first entry is the active skill (or a support-only utility group)
    slot: str = "Body Armour"
    include_in_full_dps: bool = False
    enabled: bool = True
    label: str = ""
    picked: bool = False  # chosen by the utility picker, not by the request: a variant of the build picks again (D40)
    source_index: int = 0  # the group's index in the export it was derived from (PoB's socketGroupList), so a PoB readback about group N finds it; 0 = not from an export
    instance_counts: list[int] = field(default_factory=list)  # per-gem live PoB instance counts; indexes handle repeated gems
    disabled_gem_indices: list[int] = field(default_factory=list)  # zero-fielded gems, by index so repeated names remain distinct


# the one mod text PoB's parser maps to BrandsAttachedLimit (ModParser.lua); the skill's own base is in its stats
_BRAND_ATTACHED_LINE = re.compile(r"you can have an additional brand attached to an enemy", re.I)


def _granted_effect_id(name: str) -> str:
    """The PoB block id behind a gem name, active or support ("Spell Cascade" -> SupportSpellCascade)."""

    from junkroan.search.hypothesis import active_gems, support_gems

    rec = active_gems().get(name.lower()) or support_gems().get(name.lower())
    return str((rec or {}).get("granted_effect_id") or "")


@lru_cache(maxsize=1)
def _corpse_pool_cap_bonus_nodes() -> dict[int, tuple[frozenset[str], int]]:
    """Passive node ids with a PoB-corpus corpse-pool bonus, keyed by creator effect id.

    The corpus is the source for both the bonus and the affected skills. This deliberately does
    not know that a particular node is called Undertaker or that it has a particular id.
    """

    from junkroan.search.hypothesis import active_gems

    path = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "passives.json"
    records = json.loads(path.read_text(encoding="utf-8")).get("records") or []
    gems = active_gems()
    bonuses: dict[int, tuple[frozenset[str], int]] = {}
    for record in records:
        node_id = record.get("node_id")
        if not isinstance(node_id, int):
            continue
        for line in record.get("stats") or []:
            match = re.fullmatch(r"(.+?) have \+(\d+) to Maximum number of corpses allowed", str(line))
            if not match:
                continue
            effect_ids = frozenset(
                str((gems.get(name.strip().lower()) or {}).get("granted_effect_id") or "")
                for name in match.group(1).split(" and ")
            ) - {""}
            if effect_ids:
                bonuses[node_id] = (effect_ids, int(match.group(2)))
    return bonuses


def _corpse_pool_cap_bonus(pob: PobSession, creator_effect_id: str) -> int:
    """The live tree's bonus to this creator's corpse pool, or zero for a test double."""

    tree_light = getattr(pob, "tree_light", None)
    if not callable(tree_light):
        return 0
    state = tree_light()
    allocated = {int(node) for node in state.get("user_allocated_node_ids") or []}
    return sum(
        bonus for node_id, (effect_ids, bonus) in _corpse_pool_cap_bonus_nodes().items()
        if node_id in allocated and creator_effect_id in effect_ids
    )


def brand_attach_extra(pob: PobSession, names: Sequence[str], links: Sequence[Sequence[str]] | None = None) -> int:
    """How many "you can have an additional Brand Attached to an Enemy" lines the build owns.

    Remembered per session until it can have changed. `config_rules.build_text` reads exactly three
    surfaces -- the equipped items, the allocated passives (masteries and ascendancy included) and
    the gems of the enabled socket groups -- so the count is a function of those three and of
    nothing else.

    * items and passives: `PobSession.build_epoch` moves on every call that can touch either of
      them (and on a whole-build load), so it stands for both.
    * gems: a gem reaches `build_text` as its own name and, when its corpus record grants an active
      skill, as that skill's lines. A gem that grants no active skill therefore contributes its
      name alone, and a support gem's name cannot be the sentence this counts -- so the key only
      has to carry the gems that grant an active skill (plus, for form's sake, any name that does
      match). Which of them is enabled, and which group counts at all, follows from the names
      (`buff_gems.disable_unreliable_buff_gems`); gem counts, levels and the skill part never reach
      `build_text` at all.

    So swapping a support in the main link cannot move this number, which is what the re-judge of
    the picks does ~250 times per run while paying a full `read_state` export (105 ms) plus the text
    rebuild (40 ms) for each of them: 145 of the 260 ms a support candidate cost on stormbrand.
    Swapping a utility gem can move it, and still pays.

    A `pob` without the counter (a test double) is never memoized.
    """

    from junkroan.optimizer.config_rules import _active_gem_records, build_text

    epoch = getattr(pob, "build_epoch", None)
    if epoch is None:
        return len(_BRAND_ATTACHED_LINE.findall(build_text(pob)))
    records = _active_gem_records()
    groups = [list(link) for link in links] if links is not None else [[name] for name in names]
    speaking = tuple(sorted(
        name
        for group in groups
        for name in group
        if (records.get(str(name).strip().lower()) or {}).get("grants_active_skill") or _BRAND_ATTACHED_LINE.search(str(name))
    ))
    key = (epoch, speaking)
    memo = getattr(pob, "_brand_attach_memo", None)
    if memo is not None and memo[0] == key:
        return int(memo[1])
    extra = len(_BRAND_ATTACHED_LINE.findall(build_text(pob)))
    pob._brand_attach_memo = (key, extra)  # type: ignore[attr-defined]
    return extra


def _derived_count_occurrences(pob: PobSession, names: Sequence[str], links: Sequence[Sequence[str]] | None = None) -> dict[int, int]:
    """The per-occurrence form of :func:`derived_counts`.

    A gem name is not an identity: two copies of the same golem can have different allocations
    under one shared limit.  Public callers retain the historical name-keyed result, while the
    skills writer uses these indexes to disable only the zero-fielded occurrence.
    """

    groups = [list(link) for link in links] if links is not None else [[name] for name in names]
    source_names = [name for group in groups for name in group]
    candidate_sources: list[int] = []
    if source_names == list(names):
        candidate_sources = list(range(len(names)))
    else:
        # Public callers may ask for one skill while passing the whole build's links so corpse
        # creators and supports still affect it. Match requested occurrences left-to-right; the
        # skeleton refresh path above keeps exact source order and therefore preserves duplicates.
        start = 0
        for name in names:
            index = next((i for i in range(start, len(source_names)) if source_names[i] == name), None)
            if index is None:
                continue
            candidate_sources.append(index)
            start = index + 1
    group_indexes: list[list[int]] = []
    next_index = 0
    for group in groups:
        indexes = list(range(next_index, next_index + len(group)))
        group_indexes.append(indexes)
        next_index += len(group)

    from junkroan.pob.skill_facts import brand_attach_base, cascade_areas, corpses_consumed_per_cast, corpses_created_per_cast, is_duration_minion, minion_limit_stat, minions_per_cast
    from junkroan.search.hypothesis import active_gems

    limits: dict[int, str] = {}
    brands: dict[int, int] = {}
    for index, name in enumerate(source_names):
        rec = active_gems().get(name.lower())
        gid = str((rec or {}).get("granted_effect_id") or "") if rec else ""
        stat = minion_limit_stat(gid) if gid else None
        if stat:
            limits[index] = stat
            continue
        base = brand_attach_base(gid) if gid else None
        if base:
            brands[index] = base
    # Speed and Duration are the main skill's own numbers, so the cast-rate cap applies only to a
    # duration minion that IS the main skill (the first gem of the first link).
    main_index = group_indexes[0][0] if group_indexes and group_indexes[0] else None
    duration_main = main_index if main_index in limits and is_duration_minion(_granted_effect_id(source_names[main_index])) else None
    counts: dict[int, int] = {}
    if limits or brands:
        keys = tuple(dict.fromkeys([*limits.values(), *(["ActiveBrandLimit"] if brands else []), *(["Speed", "Duration"] if duration_main is not None else [])]))
        stats = pob.stats(keys)
        counts = {
            index: max(0, int(round(float(stats.get(stat) or 0))))
            for index, stat in limits.items()
            if isinstance(stats.get(stat), (int, float)) and stats.get(stat) >= 0
        }
        golems = [
            index for index in limits
            if "golem" in set((active_gems().get(source_names[index].lower()) or {}).get("tag_keys") or [])
        ]
        if golems:
            golem_limit = stats.get("ActiveGolemLimit")
            if isinstance(golem_limit, (int, float)) and golem_limit >= 0:
                base, remainder = divmod(int(round(golem_limit)), len(golems))
                counts.update({index: base + int(order < remainder) for order, index in enumerate(golems)})
        if duration_main is not None and duration_main in counts:
            speed, duration = stats.get("Speed"), stats.get("Duration")
            if isinstance(speed, (int, float)) and isinstance(duration, (int, float)) and speed > 0 and duration > 0:
                alive = int(float(speed) * float(duration) * minions_per_cast(_granted_effect_id(source_names[duration_main])))
                counts[duration_main] = max(1, min(counts[duration_main], alive)) if counts[duration_main] > 0 else 0
        if brands:
            extra = brand_attach_extra(pob, source_names, groups)
            cap = stats.get("ActiveBrandLimit")
            cap = int(cap) if isinstance(cap, (int, float)) and cap > 0 else None
            for index, base in brands.items():
                counts[index] = max(1, min(base + extra, cap) if cap else base + extra)
    consumers: dict[int, int] = {}
    created: int | None = None
    pool_cap: int | None = None
    for group, indexes in zip(groups, group_indexes):
        areas = max([cascade_areas(_granted_effect_id(name)) for name in group] or [1])
        for index, name in zip(indexes, group):
            gid = _granted_effect_id(name)
            if not gid:
                continue
            made = corpses_created_per_cast(gid)
            if made is not None and created is None:
                per_cast, cap = made
                created = per_cast * areas
                if cap is not None:
                    cap += _corpse_pool_cap_bonus(pob, gid)
                    pool_cap = cap
            eaten = corpses_consumed_per_cast(gid)
            if eaten:
                consumers[index] = max(consumers.get(index, 0), eaten * areas)
    # Creator and consumer casts are paired 1:1 today, both for a trigger pair and hand-cast
    # alternation. TODO: model a proven two-creators-per-consumer cast ratio when the skeleton can
    # express it. Until then the first creator is the one paired with the consumer.
    supplied = min(created, pool_cap) if created is not None and pool_cap is not None else (created or 0)
    for index, consumed in consumers.items():
        counts[index] = max(1, min(consumed, supplied)) if supplied > 0 else 1
    return {
        candidate_index: counts[source_index]
        for candidate_index, source_index in enumerate(candidate_sources)
        if source_index in counts
    }


def derived_counts(pob: PobSession, names: Sequence[str], links: Sequence[Sequence[str]] | None = None) -> dict[str, int]:
    """Instances PoB counts in FullDPS for each of `names`, derived from PoB's own numbers and never
    from an author's typed-in `count` (D57): minions and totems at their limit stat (D49); brands
    at the skill's attach base plus every "additional Brand Attached to an Enemy" the build owns,
    capped by ActiveBrandLimit, which is what PoB caps BrandsAttachedToEnemy by (CalcPerform.lua),
    REPORTED only: PoB multiplies a brand's TotalDPS by that number itself, so `PobSession` writes
    count 1 on every brand gem (#963, `pob/brand_instances.py`);
    a corpse-fed skill (Volatile Dead) at the corpses it eats per cast, held down by what the build
    actually creates (D57 rule 2); a duration minion that is the main skill by what the caster keeps
    alive, casts per second x duration x minions per cast, never above the limit (D57 rule 6: PoB
    Speed 2.8 x Duration 8.2 x 1 = 23 raging spirits against a limit of 20).

    `links` are the socket groups as they stand, the main link first: corpse supply is a property of
    the whole build (Desecrate sits in its own group) and Spell Cascade multiplies the areas of its
    own link on both sides of the trade. None = every name is its own one-gem link.
    Skills counted once are absent from the result."""

    occurrences = _derived_count_occurrences(pob, names, links)
    counts: dict[str, int] = {}
    for index, count in occurrences.items():
        name = names[index]
        # A name-keyed view cannot represent two copies of the same gem. Keep the positive
        # occurrence's count for the payload; indexed disabled state retains any zero occurrence.
        counts[name] = max(counts.get(name, count), count)
    return counts


@dataclass(slots=True)
class Skeleton:
    class_name: str
    ascendancy: str
    level: int = 77
    ascendancy_nodes: list[int] = field(default_factory=list)
    forced_ascendancy_nodes: list[int] = field(default_factory=list)  # ascendancy node ids the request named (#1157): no loop move drops them
    keystones: list[int] = field(default_factory=list)
    main_link: list[str] = field(default_factory=list)
    main_slot: str = "Body Armour"
    main_part: int | None = None  # PoB skill part of the main gem (Blade Vortex "10 Blades"); chosen by PoB, D36
    mode: str | None = None  # damage mode the build is optimized for (hit/dot/ignite/poison/bleed/minion); None = CombinedDPS
    scaling: dict | None = None  # {"stat": "Dex", "seed_points": 0.4}: the tree climbs the stat first (docs/REQUEST.md 5)
    weapon_types: list[str] = field(default_factory=list)  # weapon item classes the base screen may choose from; [] = any
    forbid_supports: list[str] = field(default_factory=list)
    forbid_utilities: list[str] = field(default_factory=list)
    forbid_keystones: list[str] = field(default_factory=list)
    user_config: dict = field(default_factory=dict)  # numeric config inputs the user vouches for
    tuned_choices: dict = field(default_factory=dict)  # list-type config inputs PoB judged best (stance, exposure type); re-applied by every reconfigure until re-judged (D60)
    utility_groups: int | None = None
    unique_slots: str = "auto"
    fixed_supports: list[str] = field(default_factory=list)  # hypothesis-given supports: kept when PoB re-picks the link
    aura_levels: dict[str, int] = field(default_factory=dict)  # non-rail levels of PoB-derived flat-reservation auras
    gem_counts: dict[str, int] = field(default_factory=dict)  # gem name -> instances PoB counts in FullDPS (minions at their limit, D49)
    gem_minion_skills: dict[str, int] = field(default_factory=dict)  # gem name -> which of the minion's skills PoB calculates (chosen by PoB, D49)
    main_instance_counts: list[int] = field(default_factory=list)  # per-gem live PoB counts; indexes distinguish repeated main-link gems
    disabled_main_gem_indices: list[int] = field(default_factory=list)  # zero-fielded main-link gems, by index so repeated names remain distinct
    extra_groups: list[SocketGroup] = field(default_factory=list)
    uniques: dict[str, str] = field(default_factory=dict)  # slot -> unique name (raw text resolved from PoB)
    rare_bases: dict[str, str] = field(default_factory=dict)  # slot -> base name
    # forced directions of the request (#510): every build of the search carries them, no move drops them
    forced_uniques: dict[str, str] = field(default_factory=dict)  # slot -> unique name the request named
    forced_bases: dict[str, str] = field(default_factory=dict)  # slot -> rare base the request named
    forced_nodes: list[int] = field(default_factory=list)  # passive node ids the request named (notables, keystones, masteries)
    forced_affixes: dict[str, list[str]] = field(default_factory=dict)  # slot -> mod lines (PoB text) its rare must carry
    forced_spectres: list[str] = field(default_factory=list)  # spectre ids (`Metadata/Monsters/...`) the request named (#173)
    weapon_alternatives: list[dict[str, str]] = field(default_factory=list)  # runner-up weapon setups from the base screen ({"Weapon 1": base[, "Weapon 2": base]}), rebuilt as whole builds (D41)
    sockets: dict[str, str] = field(default_factory=dict)  # slot -> "R-R-B-B"
    flasks: dict[str, str] = field(default_factory=dict)  # slot -> raw item text (carried as-is)
    jewels: dict[str, str] = field(default_factory=dict)  # slot name -> raw item text (carried as-is)
    bandit: str = "None"
    pantheon_major: str = "None"
    pantheon_minor: str = "None"
    pure_es: bool = False  # author classification for the D79 gear template, retained after rare gear is stripped
    notes: str = ""
    source_label: str = ""  # request echo or hypothesis id for durable search evaluation rows

    def __post_init__(self) -> None:
        # #802 rule 3: a Vaal version is a delivery form of the plain gem, never a search option. A main link that names
        # one (a hypothesis may) is searched, and counted by PoB, as the plain gem; delivery writes the Vaal form back.
        # PoB lists a Vaal skill beside its plain skill (most Vaal gems: ['Vaal Spark', 'Spark']), so the Vaal name
        # as the main skill would be the Vaal skill's own numbers.
        from junkroan.search.vaal_twin import plain_of_vaal

        self.main_link = [plain_of_vaal(name) or name for name in self.main_link]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def drop_picked_utilities(self) -> None:
        """Forget the utility groups the pipeline picked, keeping the request's own;
        a variant of the build (a keystone forbidden, a unique added) picks again
        because what fits (auras vs Blood Magic, mana vs reservation) changed."""

        self.extra_groups = [g for g in self.extra_groups if not g.picked]

    def cap_links(self, rails: Any = None) -> list[str]:
        """gm-links (#426): the main link keeps at most `rails.gems.main_link_max` gems, every extra group at most
        `other_link_max`. Over-cap groups lose gems from the end; the active gem (index 0) is never dropped and a
        `fixed_supports` gem goes last. Index lists follow the kept gems. Returns one line per dropped gem."""

        if rails is None:
            from junkroan.optimizer.rails import Rails

            rails = Rails.load()
        dropped: list[str] = []

        def trim(gems: list[str], cap: int, protected: Sequence[str]) -> list[int]:
            """Indices kept, in order."""
            if len(gems) <= cap:
                return list(range(len(gems)))
            tail = list(range(len(gems) - 1, 0, -1))
            order = [i for i in tail if gems[i] not in protected] + [i for i in tail if gems[i] in protected]
            gone = set(order[: len(gems) - cap])
            return [i for i in range(len(gems)) if i not in gone]

        def remap(indices: Sequence[int], kept: list[int]) -> list[int]:
            return [kept.index(i) for i in indices if i in kept]

        kept = trim(self.main_link, rails.gems.main_link_max, self.fixed_supports)
        if len(kept) != len(self.main_link):
            dropped += [f"main link: dropped {g}" for i, g in enumerate(self.main_link) if i not in kept]
            self.disabled_main_gem_indices = remap(self.disabled_main_gem_indices, kept)
            self.main_instance_counts = [self.main_instance_counts[i] for i in kept if i < len(self.main_instance_counts)]
            self.main_link = [self.main_link[i] for i in kept]
        for g in self.extra_groups:
            kept = trim(g.gems, rails.gems.other_link_max, ())
            if len(kept) != len(g.gems):
                dropped += [f"group {g.label or g.gems[0]}: dropped {n}" for i, n in enumerate(g.gems) if i not in kept]
                g.disabled_gem_indices = remap(g.disabled_gem_indices, kept)
                g.instance_counts = [g.instance_counts[i] for i in kept if i < len(g.instance_counts)]
                g.gems = [g.gems[i] for i in kept]
        return dropped

    @classmethod
    def from_json(cls, text: str) -> "Skeleton":
        raw = json.loads(text)
        raw["extra_groups"] = [SocketGroup(**g) for g in raw.get("extra_groups", [])]
        return cls(**raw)

    # -- apply ---------------------------------------------------------------

    def enablers(self) -> list[str]:
        """Active gems in the main link after the main skill (Snipe with Burning Arrow, Spellslinger
        with Volatile Dead, General's Cry with Sunder): they deliver the skill and are never a
        support slot (7.1d); PoB re-picks and re-judges only the supports around them."""

        from junkroan.search.hypothesis import active_gems, support_gems

        return [g for g in self.main_link[1:] if g.lower() in active_gems() and g.lower() not in support_gems()]

    def flat_reservation_auras(self) -> list[str]:
        """Enabled active gems whose PoB data makes their level a reservation decision."""

        from junkroan.pob.skill_facts import flat_reservation_aura_effect_ids
        from junkroan.search.hypothesis import active_gems
        from junkroan.search.vaal_twin import plain_of_vaal

        effects = flat_reservation_aura_effect_ids()
        carried = [*self.main_link, *(name for group in self.extra_groups if group.enabled for name in group.gems)]
        # #1023: a Vaal version of a reservation aura (Vaal Clarity) counts as the aura of its plain name, but is listed
        # under the gem's own name: `aura_levels` is read by gem name when the groups are written.
        return list(dict.fromkeys(
            name for name in carried
            if str((active_gems().get((plain_of_vaal(name) or name).lower()) or {}).get("granted_effect_id") or "") in effects
        ))

    def skill_payload(self, *, gem_level: int = 18, gem_quality: int = 0, main_quality: int = 0,
                      main_link: Sequence[str] | None = None, probe_unfielded: bool = False,
                      main_disabled_indices: Sequence[int] | None = None,
                      main_instance_counts: Sequence[int] | None = None) -> dict[str, Any]:
        """The one serialized skills representation used by ordinary writes and raw trials.

        A derived zero is represented only by an indexed disabled gem. PoB's worker correctly
        rejects non-positive numeric fields, so every payload count is clamped independently of
        the reporting count retained in ``gem_counts``.
        """

        active_main_link = list(main_link) if main_link is not None else self.main_link

        def gem(name: str, index: int, disabled: set[int], counts: Sequence[int] = ()) -> dict[str, Any]:
            return {
                "gem_name": name,
                "level": self.aura_levels.get(name, gem_level),
                "quality": gem_quality,
                "enabled": probe_unfielded or index not in disabled,
                "count": max(1, int(counts[index] if index < len(counts) else self.gem_counts.get(name, 1))),
                **({"skill_minion_skill_index": int(self.gem_minion_skills[name])} if self.gem_minion_skills.get(name) else {}),
            }

        groups = [
            {
                "label": g.label or (g.gems[0] if g.gems else "group"),
                "slot": g.slot,
                "enabled": g.enabled,
                "include_in_full_dps": g.include_in_full_dps,
                "group_count": 1,
                "main_active_skill_index": 1,
                "gems": [gem(name, index, set(g.disabled_gem_indices), g.instance_counts) for index, name in enumerate(g.gems)],
            }
            for g in self.extra_groups
        ]
        disable_unreliable_buff_gems(groups)  # guard skills and cooldown-limited buffs stay in the build, disabled
        payload = {
            "main_link": active_main_link,
            "slot": self.main_slot,
            "level": gem_level,
            "quality": gem_quality,
            "main_quality": main_quality,
            "main_part": self.main_part,
            "extra_groups": groups,
            "main_counts": self.gem_counts,
            "main_instance_counts": list(main_instance_counts) if main_instance_counts is not None else (
                list(self.main_instance_counts) if active_main_link == self.main_link else []
            ),
            "main_minion_skills": self.gem_minion_skills,
        }
        if self.aura_levels:
            payload["gem_levels"] = self.aura_levels
        disabled_main = list(main_disabled_indices) if main_disabled_indices is not None else (
            self.disabled_main_gem_indices if active_main_link == self.main_link else []
        )
        if disabled_main and not probe_unfielded:
            payload["main_disabled_indices"] = disabled_main
        if self.forced_spectres:  # #173: the spectre list and the Raise Spectre gem's skillMinion, written with every skills write
            payload["spectres"] = list(self.forced_spectres)
            payload["main_skill_minion"] = {"Raise Spectre": self.forced_spectres[0]}
        return payload

    def apply_skills(self, pob: PobSession, *, gem_level: int = 18, gem_quality: int = 0, main_quality: int = 0,
                     main_link: Sequence[str] | None = None, probe_unfielded: bool = False,
                     main_disabled_indices: Sequence[int] | None = None,
                     main_instance_counts: Sequence[int] | None = None) -> None:
        """The skills surface alone: main link, extra groups, skill part, gem counts.
        `main_link` writes a link the caller is trying instead of the skeleton's own (the skeleton
        keeps its link until the trial is accepted); a re-apply must not put the old link back."""

        pob.set_skills(**self.skill_payload(
            gem_level=gem_level,
            gem_quality=gem_quality,
            main_quality=main_quality,
            main_link=main_link,
            probe_unfielded=probe_unfielded,
            main_disabled_indices=main_disabled_indices,
            main_instance_counts=main_instance_counts,
        ))

    def refresh_minion_counts(self, pob: PobSession, *, gem_level: int = 18, gem_quality: int = 0, main_quality: int = 0,
                              main_link: Sequence[str] | None = None, log=None) -> dict[str, int]:
        """Instance counts PoB's FullDPS multiplies by, derived for the build as it stands (D49, D57):
        a Raise Zombie gem counts ActiveZombieLimit zombies, Absolution its sentinels, a brand the
        brands one enemy can carry, Volatile Dead the corpses it eats and the build supplies.
        `main_link` overrides the skeleton's own link for a trial link the caller has just applied
        (a Spell Cascade swapped out cuts the corpses eaten from 9 to 3). Re-applies the skills when a count
        changed. Returns the counts in force."""

        active_main_link = list(main_link or self.main_link)
        has_unfielded = bool(self.disabled_main_gem_indices or any(g.disabled_gem_indices for g in self.extra_groups))
        if has_unfielded:
            # Count limits against every intended candidate, including one that was not fielded for
            # the previous score. This write is only a derivation probe; no objective read occurs here.
            self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality,
                              main_link=active_main_link, probe_unfielded=True)
        links = [active_main_link] + [list(g.gems) for g in self.extra_groups if g.enabled]
        names = [*active_main_link, *(name for group in self.extra_groups if group.enabled for name in group.gems)]
        occurrence_counts = _derived_count_occurrences(pob, names, links=links)
        if not occurrence_counts:
            if has_unfielded:
                self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality, main_link=active_main_link)
            return {}
        counts: dict[str, int] = {}
        for index, count in occurrence_counts.items():
            name = names[index]
            counts[name] = max(counts.get(name, count), count)
        old_main = set(self.disabled_main_gem_indices)
        old_groups = [set(group.disabled_gem_indices) for group in self.extra_groups]
        old_main_counts = list(self.main_instance_counts)
        old_group_counts = [list(group.instance_counts) for group in self.extra_groups]
        next_index = 0
        new_main = {index for index, _name in enumerate(active_main_link) if occurrence_counts.get(index) == 0}
        next_index += len(active_main_link)
        new_groups: list[set[int]] = []
        for group in self.extra_groups:
            if not group.enabled:
                new_groups.append(set())
                continue
            disabled = {
                index for index, _name in enumerate(group.gems)
                if occurrence_counts.get(next_index + index) == 0
            }
            new_groups.append(disabled)
            next_index += len(group.gems)
        new_main_counts = [occurrence_counts.get(index, self.gem_counts.get(name, 1)) for index, name in enumerate(active_main_link)]
        new_group_counts: list[list[int]] = []
        next_index = len(active_main_link)
        for group in self.extra_groups:
            if group.enabled:
                new_group_counts.append([
                    occurrence_counts.get(next_index + index, self.gem_counts.get(name, 1))
                    for index, name in enumerate(group.gems)
                ])
                next_index += len(group.gems)
            else:
                new_group_counts.append(list(group.instance_counts))
        changed = (any(self.gem_counts.get(n, 1) != c for n, c in counts.items())
                   or old_main != new_main or old_groups != new_groups
                   or old_main_counts != new_main_counts or old_group_counts != new_group_counts)
        self.gem_counts.update(counts)
        self.disabled_main_gem_indices = sorted(new_main)
        self.main_instance_counts = new_main_counts
        for group, disabled, instance_counts in zip(self.extra_groups, new_groups, new_group_counts):
            group.disabled_gem_indices = sorted(disabled)
            group.instance_counts = instance_counts

        if log is not None:
            for index, name in enumerate(active_main_link):
                if index in new_main - old_main:
                    log(f"minion count: {name} fields 0 instances by PoB; disabled for scoring (payload count remains 1)")
                elif index in old_main - new_main:
                    log(f"minion count: {name} fields {occurrence_counts.get(index, 1)} instances by PoB; re-enabled for scoring")
            next_index = len(active_main_link)
            for group, was, now in zip(self.extra_groups, old_groups, new_groups):
                for index, name in enumerate(group.gems):
                    if index in now - was:
                        log(f"minion count: {name} fields 0 instances by PoB; disabled for scoring (payload count remains 1)")
                    elif index in was - now:
                        log(f"minion count: {name} fields {occurrence_counts.get(next_index + index, 1)} instances by PoB; re-enabled for scoring")
                if group.enabled:
                    next_index += len(group.gems)
        if changed or has_unfielded:
            self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality,
                              main_link=active_main_link, main_disabled_indices=sorted(new_main),
                              main_instance_counts=self.main_instance_counts)
        return counts

    def tune_minion_skills(self, pob: PobSession, score, *, gem_level: int = 18, gem_quality: int = 0, main_quality: int = 0, max_index: int = 4) -> dict[str, int]:
        """Which of a minion's skills PoB calculates is a choice, judged like stance or exposure
        type (D24): every minion gem tries skill 1..max_index, the best score stays. `score()`
        returns the current objective score. Absolution's sentinels: skill 2 is 2.2x skill 1."""

        from junkroan.pob.skill_facts import minion_limit_stat
        from junkroan.search.hypothesis import active_gems

        names = []
        for n in list(self.main_link) + [g for grp in self.extra_groups for g in grp.gems]:
            rec = active_gems().get(n.lower())
            if rec and minion_limit_stat(str(rec.get("granted_effect_id") or "")):
                names.append(n)
        chosen: dict[str, int] = {}
        for name in names:
            best = None
            for idx in range(1, max_index + 1):
                self.gem_minion_skills[name] = idx
                self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality)
                s = score()
                if best is not None and s == best[0] and idx > 1:
                    break  # PoB clamped the index: no more skills
                if best is None or s > best[0]:
                    best = (s, idx)
            self.gem_minion_skills[name] = best[1] if best else 1
            chosen[name] = self.gem_minion_skills[name]
        if names:
            self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality)
        return chosen

    def apply_forced_nodes(self, pob: PobSession) -> None:
        """Public: put the request's forced nodes back after a `set_tree` (a regrow starts from a fresh tree)."""

        if self.forced_nodes:
            self._apply_forced_nodes(pob)

    def _apply_forced_nodes(self, pob: PobSession) -> None:
        """Allocate the request's forced passive nodes (#510) like the keystones: PoB paths a notable or
        keystone itself. A mastery effect is reached through the cheapest notable of its cluster, then
        allocated with its effect (a mastery is never a path). Already allocated ids are skipped."""

        from junkroan.optimizer.tree_graph import TreeGraph, ascendancy_node_owners

        graph = TreeGraph.load()
        owners = ascendancy_node_owners()  # #1147: an ascendancy node is no passive node; PoB allocates it from the ascendancy start
        ascendancy = [int(n) for n in self.forced_nodes if int(n) in owners]
        plain, masteries = graph.resolve_forced([n for n in self.forced_nodes if int(n) not in owners], class_name=self.class_name)
        state = pob.tree_light()
        allocated = {int(n) for n in state.get("user_allocated_node_ids") or ()}
        todo = [n for n in plain if n not in allocated]
        if todo:
            allocated |= {int(n) for n in pob.add_nodes(todo).get("allocated_node_ids") or ()}
        start = graph.class_starts.get(self.class_name)
        for node_id, effect in masteries.items():
            if node_id in allocated:
                continue
            roots = allocated | ({start} if start is not None else set())
            _cost, path = graph.bfs_costs(roots, max_depth=80)[node_id]
            if len(path) > 1:
                allocated |= {int(n) for n in pob.add_nodes(list(path[:-1])).get("allocated_node_ids") or ()}
            allocated |= {int(n) for n in pob.add_nodes([node_id], mastery_effects={node_id: effect}).get("allocated_node_ids") or ()}
        if ascendancy:  # the worker raises for a node it cannot reach (another ascendancy) or does not know, so none is silently missing
            pob.add_nodes(ascendancy)
        # `allocated` is the whole allocated tree: tree_light's read plus each add_nodes return (mutate_tree_nodes
        # returns every allocated ordinary node), and nothing here removes a node. A forced node missing from it is
        # a run that would continue without the request's node, so it raises (#1044) instead of going on.
        missing = [n for n in (*plain, *masteries) if n not in allocated]
        if missing:
            names = ", ".join(f"{graph.nodes[n].name} (id {n})" for n in missing)
            raise RuntimeError(f"forced passive node(s) not allocated on the {self.class_name} tree after PoB added them: {names}")

    def apply(self, pob: PobSession, *, unique_raw: Mapping[str, str] | None = None, gem_level: int = 18, gem_quality: int = 0, main_quality: int = 0) -> None:
        """Put the skeleton into a blank session: identity, class/ascendancy/keystones,
        gems, uniques, flasks and jewels. Rares and the passive tree are left to the optimizer.
        Gem level/quality come from the rails (day-1: 18/0, D23), never 20/20."""

        pob.set_identity(level=self.level)
        pob.set_tree(class_id=self.class_name, ascendancy_id=self.ascendancy, ascendancy_nodes=self.ascendancy_nodes)
        if self.keystones:
            pob.add_nodes(self.keystones)
        if self.forced_nodes:
            self._apply_forced_nodes(pob)
        self.apply_skills(pob, gem_level=gem_level, gem_quality=gem_quality, main_quality=main_quality)
        items: dict[str, str] = {}
        for slot, name in self.uniques.items():
            raw = (unique_raw or {}).get(name)
            if raw is None:
                raw = pob.unique_item(name)["raw"]
            items[slot] = raw
        items.update(self.flasks)
        items.update(self.jewels)
        if items:
            pob.equip(items)
        pob.set_config(bandit=self.bandit, pantheon_major=self.pantheon_major, pantheon_minor=self.pantheon_minor, enemy_state={"is_boss": "Pinnacle"}, preserve="none")


__all__ = ["Skeleton", "SocketGroup"]
