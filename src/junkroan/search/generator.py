"""Skeleton generator: everything below the hypothesis line is chosen by PoB.

Given a main skill (and optionally an LLM hypothesis), produce skeleton
candidates whose remaining blanks are filled by measurement, not by prose:

  - rare bases per slot: best-of-N loot rolls per candidate base, PoB scores
  - ascendancy nodes: greedy by objective gain per point, PoB scores
  - support gems: greedy over the supports PoB accepts on the skill
  - uniques: every unique of the slot's type is tried as an item trial

No game knowledge lives here beyond corpus lookups and slot geometry.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Collection, Iterable, Mapping, Sequence

from junkroan.optimizer.gear_filler import GearFiller
from junkroan.report_format import human_duration
from junkroan.optimizer.item_bases import bases_by_type, bases_of_type, excluded_of, without_excluded
from junkroan.optimizer.loot_gear import drop_weapon_all_gems, forced_mod_choices, ordered_slots, raw_carries  # one definition of the slot order, shared with the fillers
from junkroan.optimizer.castability import CastabilityContext, CastabilityMetrics, castability_context, replace_castability_skill, with_castability_floors
from junkroan.optimizer.objective import Objective, Score, ScoreOrder, accepts_under, score_key
from junkroan.optimizer.ramp import stages_in_part, with_ramp
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_gems import count_evaluated, count_generated, gem_classes
from junkroan.optimizer.self_cost import STAT_NAME as SELF_COST_STAT, context_for as self_cost_context, with_self_cost
from junkroan.pob.game_corpus import DEFAULT_SOURCE_LOCK_PATH
from junkroan.pob.calc_snapshot import PoBHeadlessCalcSnapshotContractError
from junkroan.pob.headless_runtime_worker import WorkerContractError
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from junkroan.pob.session import PobSession
from junkroan.pob.skill_facts import buff_uptime, reservation_pools, skill_types
from junkroan.pob.skill_requirements import PoBSkillRequirementsContractError
from junkroan.pob.support_legality_readback import PoBSupportLegalityReadbackContractError
from junkroan.search.hypothesis import RARE_SLOTS, UNIQUE_TYPE_SLOTS, active_gems, ascendancies, ascendancy, is_limited_curse, item_bases, normalize_ascendancy_ids, support_gems, uniques_by_name
from junkroan.search.skeleton import Skeleton, SocketGroup
from junkroan.search.sockets import gem_colour

if TYPE_CHECKING:
    from junkroan.optimizer.judging import Rejudge

# a dead or contract-breaking PoB worker is never a rejected support trial (#556 R4): these propagate out of `_try_score`
POB_CONTRACT_ERRORS = (WorkerContractError, PoBHeadlessHostContractError, PoBHeadlessCalcSnapshotContractError, PoBSkillRequirementsContractError, PoBSupportLegalityReadbackContractError)
CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
SAVED_LISTS: dict[str, str] = {}  # #978: saved list file name -> sha256 of it as this run first found it, or "absent"


def note_saved_list(path: Path) -> None:
    """#978: record the state of a saved list before this run reads or writes it; the first look wins."""
    if path.name not in SAVED_LISTS:
        SAVED_LISTS[path.name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"


def write_saved_lists(path: Path) -> None:
    """#978: the sidecar of a recorded run, next to its transcript: the saved lists it started with."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(SAVED_LISTS.items())), indent=1), encoding="utf-8")
ARMOUR_SLOT_TYPES = {"Body Armour": "Body Armour", "Helmet": "Helmet", "Gloves": "Gloves", "Boots": "Boots", "Belt": "Belt", "Amulet": "Amulet", "Ring 1": "Ring", "Ring 2": "Ring"}
ONE_HAND_TYPES = ("Wand", "Sceptre", "Dagger", "Claw", "One Handed Sword", "One Handed Axe", "One Handed Mace")
TWO_HAND_TYPES = ("Staff", "Two Handed Sword", "Two Handed Axe", "Two Handed Mace", "Bow")


LEGAL_SUPPORTS_CACHE_DIR = CORPUS.parents[2].parent / "artifacts" / "cache"  # tests and scratch point this at a tmp folder


def legal_supports_cache_path(skill: str) -> Path:
    return LEGAL_SUPPORTS_CACHE_DIR / f"legal_supports-{skill.lower().replace(' ', '_')}.json"


def legal_support_candidates(skill: str, forbid_supports: Iterable[str]) -> list[str]:
    """The day-1 supports the readback tries on `skill`, minus the forbidden ones (the one filter the loop and the cache key share)."""

    forbidden = {s.lower() for s in forbid_supports}
    main_tags = set(active_gems().get(skill.lower(), {}).get("tag_keys") or [])
    blocked_delivery = DELIVERY_TAGS - main_tags  # a trap skill may take trap supports; a spell may not become a mine by a greedy pick
    return [r["name"] for r in support_gems().values() if _day1_support(r) and not (set(r.get("tag_keys") or []) & blocked_delivery) and r["name"].lower() not in forbidden]


def legal_supports_key(skill: str, candidate_names: Iterable[str]) -> str:
    """sha256 over the pinned PoB commit, the skill and the sorted candidate names: a saved legal list is valid only for these."""

    commit = json.loads(DEFAULT_SOURCE_LOCK_PATH.read_text(encoding="utf-8"))["pinned_commit"]
    return hashlib.sha256(json.dumps([commit, skill, sorted(candidate_names)]).encode("utf-8")).hexdigest()


def forced_slots(skeleton: Skeleton) -> set[str]:
    """Every slot the request fixed (#510): a forced unique, a forced rare base or a forced affix slot.
    No search step may change what stands in them."""

    return set(skeleton.forced_uniques) | set(skeleton.forced_bases) | set(skeleton.forced_affixes)
NOT_DAY1_SUPPORTS = ("Enhance", "Empower", "Enlighten")
UPTIME_MIN = 0.9  # a self-buff PoB applies unconditionally must really be up this share of the time (D46)
DELIVERY_TAGS = {"trigger", "mine", "trap", "totem"}
# utility gems: one per socket group, judged by PoB under reservation + sustain (D35)
UTILITY_FAMILIES = {
    "aura": ({"aura"}, {"attack", "melee", "mine", "trap", "totem", "vaal", "minion", "spell_damage"}),
    "herald": ({"herald"}, set()),
    "curse": ({"curse", "mark"}, set()),
    "guard": ({"guard"}, set()),
    "golem": ({"golem"}, set()),
    "banner": ({"banner"}, set()),
    "warcry": ({"warcry"}, {"retaliation"}),
    "movement": ({"movement", "travel", "blink"}, {"attack_main"}),
}
UTILITY_SLOTS = ("Helmet", "Gloves", "Boots", "Weapon 1", "Weapon 2")
FILL_TAGS = frozenset({"aura", "guard", "herald"})  # gem tags the fill step takes; PoB's skill type "buff" takes the rest (Tempest Shield, Withering Step)
FILL_CLASS = "fill-candidate"  # a gem the fill step wrote into PoB (#1156): generated before the call, evaluated after the score read
FILL_SLOTS = (*UTILITY_SLOTS, "Body Armour")
MOVEMENT_FORBIDDEN_CLASS = "movement-forbidden"  # a refused movement gem written into PoB: generated and evaluated stay 0 (#1153)


def _gem_family(name: str) -> str:
    """A gem and its transfigured variants share the game id (rulebook gm-transfigured: they stand next to the base gem)."""

    rec = active_gems().get(name.lower())
    return str((rec or {}).get("game_id") or name)


def in_gem_list(name: str, listed: Iterable[str]) -> bool:
    """Is `name` one of `listed` or a transfigured variant of one."""

    family = _gem_family(name)
    return any(family == _gem_family(n) for n in listed)


@functools.cache
def _fill_pool() -> frozenset[str]:
    """Every gem the fill step may measure, from the corpus tags and PoB's own skill types (no hand list, no Vaal variant,
    the uptime rule of the utility picker): an aura, guard or herald tag, or the skill type `buff`."""

    out: set[str] = set()
    for r in active_gems().values():
        effect = str(r.get("granted_effect_id") or "")
        if not (set(r.get("tag_keys") or []) & FILL_TAGS or "buff" in skill_types(effect)):
            continue
        if r.get("is_vaal_gem") or r["name"].startswith("Vaal "):
            continue
        uptime = buff_uptime(effect)
        if uptime is not None and uptime < UPTIME_MIN:
            continue
        out.add(r["name"])
    return frozenset(out)


def fill_candidate_names() -> frozenset[str]:
    """The names the fill step can offer; the trace output counts the delivered groups whose first gem is one of them."""

    return _fill_pool()


@functools.cache
def _own_choice_map() -> dict[str, dict[str, list[str]]]:
    from junkroan.optimizer.config_rules import config_surfaces  # lazy: config_rules imports this package

    out: dict[str, dict[str, list[str]]] = {}
    for var, rec in config_surfaces().items():
        if rec.get("type") != "list" or rec.get("section") != "Skill Options":
            continue
        skills = (rec.get("predicates") or {}).get("ifSkill")
        values = [str(v["value"]) for v in rec.get("list_values") or [] if isinstance(v, dict) and "value" in v]
        for skill in ([skills] if isinstance(skills, str) else skills or []):
            if values:
                out.setdefault(str(skill), {})[var] = values
    return out


def own_choices(name: str) -> dict[str, list[str]]:
    """The list-type config vars a gem owns (config surface of the section "Skill Options" whose `ifSkill` names it):
    Flesh and Stone -> {"bloodSandStance": ["BLOOD", "SAND"]}; {} for a gem with none."""

    return {var: list(values) for var, values in _own_choice_map().get(name, {}).items()}


def movement_rails(rails):
    """The rails' movement pair (#1153) when the rails require one, else None."""

    return getattr(rails, "movement", None) if getattr(rails, "movement_skill_required", False) else None


def movement_kind(name: str, movement) -> str | None:
    """`spell` / `skill` for a gem of the rails' movement pair (#1153), else None."""

    if movement is None:
        return None
    if in_gem_list(name, movement.spell):
        return "spell"
    return "skill" if in_gem_list(name, movement.skill) else None


def utility_groups_used(groups: Iterable[SocketGroup], rails) -> int:
    """The groups that count against `utilities.max_groups`: the movement pair does not (#1153)."""

    movement = movement_rails(rails)
    return sum(1 for grp in groups if not (grp.gems and movement_kind(grp.gems[0], movement)))


def movement_kinds_missing(groups: Iterable[SocketGroup], main_link: Iterable[str], rails) -> list[str]:
    """The slots of the movement pair (`spell`, `skill`) in which the build carries no gem; [] when the rails require no pair."""

    movement = movement_rails(rails)
    if movement is None:
        return []
    kinds = {movement_kind(g, movement) for grp in groups for g in grp.gems} | {movement_kind(g, movement) for g in main_link}
    return [kind for kind in ("spell", "skill") if kind not in kinds]


def movement_pair_missing(groups: Iterable[SocketGroup], main_link: Iterable[str], rails) -> bool:
    """Does the build still lack a gem of either movement slot (the utility picker has work even at max_groups)."""

    return bool(movement_kinds_missing(groups, main_link, rails))


def refused_movement_gems(names: Iterable[str], rails) -> list[str]:
    """The gems among `names` that the rails refuse in both movement slots (Smoke Mine, Lightning Warp; #1153); [] when the rails require no pair."""

    movement = movement_rails(rails)
    return [] if movement is None else [n for n in names if in_gem_list(n, movement.forbidden)]


# PoB's own witnesses that a socket group reserves: the pools it leaves free (D72). Never a list of
# gem names or an "aura" tag -- a Herald on a Blood Magic build reserves no mana, and PoB says so.
RESERVATION_KEYS = ("ManaUnreserved", "LifeUnreserved")
RESERVATION_EPS = 1e-6


def _frees_reservation(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    """Did PoB hand reservation back when this socket group was disabled? The only witness that the
    group reserves anything: `ManaUnreserved` / `LifeUnreserved` rose. A group whose gems reserve
    nothing (a movement skill, a curse on hit, a herald the build pays for with life it does not
    have) leaves both where they were and is not a candidate for the drop."""

    return any(_num(after.get(k)) > _num(before.get(k)) + RESERVATION_EPS for k in RESERVATION_KEYS)


def _num(raw: object) -> float:
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _day1_support(r: Mapping) -> bool:
    """Regular supports only: no Awakened, no exceptional low-max-level gems (Enhance family, Invert the Rules...)."""

    return not r["name"].startswith("Awakened") and r["name"] not in NOT_DAY1_SUPPORTS and int(r.get("natural_max_level") or 0) >= 20


def _is_transfigured(gem: Mapping) -> bool:
    """Transfigured gems share the base gem's game_id and carry an AltX/AltY variant id (the picker offers them; the trace classifies them, #498)."""

    variant = str(gem.get("variant_id") or "")
    return variant.endswith(("AltX", "AltY", "AltZ")) or "Alt" in variant[-5:]


def _attr_profile(req: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(sorted(k for k in ("str", "dex", "int") if int(req.get(k) or 0) > 0))


def _ascendancy_picks(nodes: Mapping[int, Mapping], adjacency: Mapping[int, set[int]]) -> set[int]:
    """Where the ascendancy greedy is allowed to stop: the nodes that are a choice.

    Normally those are the notables. PoB also builds "choose one of these" groups, and there it
    puts the stats on the options, not on the notable: the notable is an empty hub. The Scion's
    Reliquarian is made entirely of them -- its only four notables are the empty "Caster Weapon
    Display", "Martial Weapon Display", "Jewellery Display" and "Armour Display", and the 24
    unique-item nodes that carry the stats (Kaom's Roots +100 life, Elevore +25% suppression)
    hang off them -- and so are the Ascendant's six class hubs, Assassin's "Assassination Style",
    Warlock's "Warlock Power", Aul's "Legacy of the King" and five more. On notables alone the
    greedy can only stop on an empty hub and score nothing.

    So: every notable, plus every stat-carrying neighbour of a notable that has no stats of its
    own. Measured over the 3_29 corpus (2026-09-18): 27 of the 37 ascendancies keep exactly the
    notables they had, and of the 20 the search may pick only Ascendant (+30), Assassin (+4) and
    Reliquarian (+30) gain anything. Which of the options exclude each other is not decided here
    -- PoB refuses a set that holds two of them, and the greedy reads that refusal.
    """

    hubs = {nid for nid, n in nodes.items() if n.get("is_notable") and not n.get("stats")}
    out = {nid for nid, n in nodes.items() if n.get("is_notable")}
    out |= {nid for nid, n in nodes.items() if n.get("stats") and (adjacency.get(nid) or set()) & hubs}
    return out - {nid for nid, n in nodes.items() if n.get("is_ascendancy_start")}


def candidate_bases(item_type: str, *, max_level: int, excluded: Collection[str] = ()) -> list[str]:
    """Highest-level base per attribute profile of a type (Body Armour: one per
    str / dex / int / str+dex / str+int / dex+int), all droppable at the rails ilvl.
    Rings/amulets/belts have no attribute profile: every base at or under the level.

    The bases themselves come from the shared day-1 catalogue (`optimizer.item_bases`):
    Sanctum / experimental / demigod bases, talismans and PoB's "not_for_sale" (atlas,
    Necropolis, Cryonic-style rings, Bone Helmet) are out; a hypothesis may still name any
    base explicitly. The screen keeps one filter of its own, a level requirement above zero:
    it drops the skill-made weapons and the level-1 bases, which no loot roll ever wanted, and
    it stays here rather than in the catalogue so that this screen's answer does not move
    until a benchmark says it should (the wishlist filler does want them: a Rustic Sash's
    implicit is free damage, D73).

    ``excluded`` is the loadout's case-folded base names (`Rails.gear.excluded_bases`, #1154); they are never offered.
    """

    rows = [r for r in bases_by_type().get(item_type, ())
            if int((r.get("requirements") or {}).get("level") or 0) <= max_level and (r.get("requirements") or {}).get("level")
            and str(r["name"]).strip().casefold() not in excluded]
    if item_type in ("Ring", "Amulet", "Belt"):
        return sorted({r["name"] for r in rows})
    best: dict[tuple[str, ...], dict] = {}
    for r in rows:
        prof = _attr_profile(r.get("requirements") or {})
        lvl = int((r.get("requirements") or {}).get("level") or 0)
        if prof not in best or lvl > int((best[prof].get("requirements") or {}).get("level") or 0):
            best[prof] = r
    return [r["name"] for r in best.values()]


def part_is_assumption(part_name: str) -> bool:
    """PoB skill parts of two kinds: a state the player builds and holds ("10 Blades",
    "5 Stages"; the ramp rail judges the time) and an assumption about the fight
    ("Maximum Hits": every Spark projectile hits, 4x on the author's '1 Hit'; D42).
    The picker never takes the second kind for the conservative number."""

    return bool(re.search(r"\bmax(imum)?\b", part_name or "", re.IGNORECASE))


def current_part_name(pob: PobSession, skill_name: str) -> str:
    """The part PoB currently has selected for the named skill ("10 Blades"), "" if none."""

    for group in (pob.read_state().get("skills_state") or {}).get("socket_groups") or []:
        for e in group.get("active_skill_entries") or []:
            if e.get("name") == skill_name:
                return str(e.get("part_name") or "")
    return ""


@dataclass(slots=True)
class Pick:
    what: str
    choice: str
    score: Score
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    seconds: float = 0.0


def fill_keeps(now: tuple, then: tuple, *, gain: float, max_loss: float) -> bool:
    """The fill step's keep rule (#1156) on two (Score, TotalEHP) pairs: no floor gets worse, the objective falls by at most
    `max_loss`, and the objective or TotalEHP rises by at least `gain`. Shared by `pick_fill` and the audit (#1156 unit 2)."""

    if then[0].neg_violation < now[0].neg_violation - 1e-9:
        return False  # a floor that holds now would not hold (or a miss would be deeper)
    before, after = now[0].value, then[0].value
    if before > 0 and after < before * (1 - max_loss):
        return False
    return after >= before * (1 + gain) or then[1] >= now[1] * (1 + gain)


class SkeletonGenerator:
    def __init__(self, pob: PobSession, rails: Rails | None = None, *, objective: Objective | None = None, log: Callable[[str], None] | None = None,
                 gear_mode: str = "loot", castability_context: CastabilityContext | None = None,
                 castability_metrics: CastabilityMetrics | None = None) -> None:
        self.pob = pob
        self.rails = rails or Rails.load()
        self.objective = objective or self.rails.objective()
        self.log = log or (lambda _m: None)
        self.picks: list[Pick] = []
        self.gear_mode = gear_mode  # "wishlist": the filler chooses the base of every slot itself (D73), so the screen only names the class
        self.castability_context = castability_context
        self.castability_metrics = castability_metrics or CastabilityMetrics()

    # -- helpers -------------------------------------------------------------

    def _score(self) -> Score:
        return self.objective.score(self.pob.stats(self.objective.stat_keys))

    def refresh_castability(self) -> Objective:
        """Install all observed manual-skill costs after a caller applies skills."""

        self.castability_context = castability_context(self.pob, metrics=self.castability_metrics)
        self.objective = with_castability_floors(self.pob, self.objective, context=self.castability_context)
        return self.objective

    def _apply_castability_context(self) -> None:
        if self.castability_context is not None:
            self.objective = with_castability_floors(self.pob, self.objective, context=self.castability_context)

    def _restore_castability(self, context: CastabilityContext | None) -> None:
        """Put back a trial's frozen costs without another active-skill calc."""

        self.castability_context = context
        self._apply_castability_context()

    def _active_skill_ids(self, name: str) -> tuple[str, ...]:
        if not callable(getattr(self.pob, "read_state", None)):
            return ()
        state = self.pob.read_state()
        return tuple(
            str(entry.get("active_skill_id"))
            for group in (state.get("skills_state") or {}).get("socket_groups") or ()
            for entry in group.get("active_skill_entries") or ()
            if isinstance(entry, Mapping) and entry.get("name") == name and entry.get("active_skill_id")
        )

    def _all_active_skill_ids(self) -> tuple[str, ...]:
        if not callable(getattr(self.pob, "read_state", None)):
            return ()
        state = self.pob.read_state()
        return tuple(
            str(entry.get("active_skill_id"))
            for group in (state.get("skills_state") or {}).get("socket_groups") or ()
            for entry in group.get("active_skill_entries") or ()
            if isinstance(entry, Mapping) and entry.get("active_skill_id")
        )

    def _refresh_self_cost(self, skeleton: Skeleton) -> None:
        """Replace the self-cost context for the main link PoB currently holds."""

        named = (*self.objective.floors, *(part for rel in self.objective.relations for part in rel[:2]))
        if not any(SELF_COST_STAT in name for name in named):
            return
        state = self.pob.read_state()
        skills = state.get("skills_state") or {}
        main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
        groups = [g for g in skills.get("socket_groups") or [] if isinstance(g, dict)]
        main = next((g for g in groups if g.get("socket_group_id") == main_id), None) if main_id else (groups[0] if groups else None)
        gems = [str(g.get("gem_name") or g.get("name") or "") for g in (main or {}).get("gems") or [] if isinstance(g, dict)]
        triggered = any(isinstance(entry, dict) and entry.get("triggered") is True for entry in (main or {}).get("active_skill_entries") or [])
        from junkroan.optimizer.config_rules import build_text
        from junkroan.optimizer.judging import trauma_stacks

        entries = [g for g in (main or {}).get("gems") or [] if isinstance(g, dict)]
        gem_levels = tuple((str(g.get("skill_id") or ""), int(g["level"]) if isinstance(g.get("level"), (int, float)) else 20) for g in entries if g.get("skill_id"))
        tags = frozenset(active_gems().get(skeleton.main_link[0].lower(), {}).get("tag_keys") or [])
        self.objective = with_self_cost(
            self.objective,
            self_cost_context(build_text(self.pob), tags, triggered, gems, gem_levels=gem_levels, trauma_stacks=trauma_stacks(self.pob)),
        )

    def _reconfigure(self, callback: "Rejudge | None", skeleton: Skeleton, *, full: bool = False) -> None:
        """Refresh the objective after a discrete candidate changed the build.

        Some objective terms are derived from the build rather than returned by PoB. In
        particular, `SelfCostPerSecond` has to be rebuilt after changing a main-link
        support. The pipeline owns that derivation and returns its current Objective;
        keeping it here makes every accepted pick compare the same complete objective.
        The callback is the pipeline's `Rejudge` port and is always called with both
        keywords (`full`, `castability_context`).
        """

        if callback is not None:
            refreshed = callback(full=full, castability_context=self.castability_context)
            if refreshed is not None:
                self.objective = refreshed
            return
        self._refresh_self_cost(skeleton)
        if self.castability_context is None:
            self.refresh_castability()
        else:
            self._apply_castability_context()

    def _best_roll(self, slot: str, base: str, n: int, seed: int, forced: list[str] | None = None) -> tuple[Score, str] | None:
        kw: dict = {}
        if forced:  # a forced line rides every roll, and nothing lacking it is counted or sent (#523)
            try:
                kw["forced"] = forced_mod_choices(self.pob, base, forced, self.rails.gear.item_level)
            except ValueError:
                return None  # the base cannot roll a forced line: it is not screened
        rolls = self.pob.random_rares(base, n=n, ilvl=self.rails.gear.item_level, quality=self.rails.gear.quality, seed=seed, **kw)
        if forced:
            rolls = [r for r in rolls if all(raw_carries(r["raw"], line) for line in forced)]
        rolls = drop_weapon_all_gems(rolls, slot, self.rails, forced)  # #1152
        best = None
        roll_trials = [{"item": {"slot": slot, "raw": r["raw"]}} for r in rolls]
        TRACE.count_candidates(roll_trials)
        for r, o in zip(rolls, self.pob.trial_stats(roll_trials, self.objective.stat_keys, mode="fast")):
            if o.get("ok") and o.get("stats"):
                s = self.objective.score(o["stats"])
                if best is None or s > best[0]:
                    best = (s, r["raw"])
        return best

    # -- bases -----------------------------------------------------------------

    def _ceiling(self, slot: str, base: str, forced: list[str] | None = None) -> tuple[Score, str] | None:
        """The base's affix ceiling under the rails' tier caps, scored on damage alone
        (D41): a deterministic greedy craft, so weapon types are compared by what
        their affix pool and base can do for the skill, not by which of 40 random
        rolls happened to carry life while the bare rig was still below every floor."""

        filler = GearFiller(self.pob, self.objective.replace(floors={}, relations=()), self.rails, log=lambda _m: None)
        self.pob.equip({slot: None})
        if forced:  # a forced mod line rides the ceiling; a base that cannot roll it is not screened (#510)
            try:
                res = filler.fill_slot(slot, base, forced=forced)
            except ValueError:
                return None
        else:
            res = filler.fill_slot(slot, base)
        if not res.raw or res.after is None:
            return None
        return res.after, res.raw

    def _screen_weapons(self, skeleton: Skeleton) -> dict[str, str]:
        """The weapon the build fights with, and the shield or quiver that goes with it, by
        affix ceiling (`_ceiling`, D41): every one-hand type (+ the best shield) and every
        two-hand type; incompatible weapons score 0 DPS and lose. Nothing here reads the
        armour slots, and it runs before them."""

        chosen: dict[str, str] = {}
        if "Weapon 1" in skeleton.uniques or "Weapon 1" in skeleton.rare_bases:
            return chosen
        w2_fixed = "Weapon 2" in skeleton.uniques or "Weapon 2" in forced_slots(skeleton)
        max_level = self.rails.gear.wishlist.base_level_max
        fa = getattr(skeleton, "forced_affixes", {}) or {}
        kw1 = {"forced": list(fa["Weapon 1"])} if fa.get("Weapon 1") else {}
        kw2 = {"forced": list(fa["Weapon 2"])} if fa.get("Weapon 2") else {}
        self.pob.equip({"Weapon 1": None, "Weapon 2": None})  # a bow left from an earlier screen makes a shield invalid
        best = None
        shield = None
        for base in self._candidate_bases("Shield", max_level):
            roll = self._ceiling("Weapon 2", base, **kw2)
            if roll and (shield is None or roll[0] > shield[0]):
                shield = (roll[0], base, roll[1])
        allowed_types = [t for t in ONE_HAND_TYPES + TWO_HAND_TYPES if not skeleton.weapon_types or t in skeleton.weapon_types]
        ceilings: dict[str, float] = {}
        ranked: list[tuple[Score, str, str, str]] = []  # every usable weapon type's best base: (score, base, raw, type)
        for wtype in allowed_types:
            for base in self._candidate_bases(wtype, max_level):
                if shield and wtype in ONE_HAND_TYPES:
                    self.pob.equip({"Weapon 2": shield[2]})
                else:
                    self.pob.equip({"Weapon 2": None})
                roll = self._ceiling("Weapon 1", base, **kw1)
                if roll:
                    ceilings[base] = roll[0].value
                if roll and roll[0].value <= 0:
                    continue  # the skill cannot be used with this weapon type (Lightning Arrow with a claw scored 0 DPS but won on life)
                if roll:
                    ranked.append((roll[0], base, roll[1], wtype))
                if roll and (best is None or roll[0] > best[0]):
                    best = (roll[0], base, roll[1], wtype)
        if ceilings:
            self.log("weapon ceilings: " + ", ".join(f"{b} {v:,.0f}" for b, v in sorted(ceilings.items(), key=lambda kv: -kv[1])))
        if best and len(ranked) > 1:
            # the bare rig cannot rank weapon types (Blade Trap: sword 224 > claw 192 here, claw 65k > sword 50k as builds):
            # the runner-ups are kept and rebuilt as whole builds by the search's mutation round (D41)
            skeleton.weapon_alternatives = []
            for score, base, _raw, wtype in sorted(ranked, key=lambda r: r[0], reverse=True):
                if base == best[1] or score.value < 0.5 * best[0].value or len(skeleton.weapon_alternatives) >= 2:
                    continue
                alt = {"Weapon 1": base}
                if wtype in ONE_HAND_TYPES and shield and not w2_fixed:
                    alt["Weapon 2"] = shield[1]
                elif wtype == "Bow" and not w2_fixed:
                    quivers = self._candidate_bases("Quiver", max_level)
                    if quivers:
                        alt["Weapon 2"] = quivers[0]
                skeleton.weapon_alternatives.append(alt)
        if best:
            chosen["Weapon 1"] = best[1]
            self.pob.equip({"Weapon 1": best[2]})
            if best[3] in ONE_HAND_TYPES and shield and not w2_fixed:
                chosen["Weapon 2"] = shield[1]
                self.pob.equip({"Weapon 2": shield[2]})
            elif best[3] == "Bow" and not w2_fixed:
                quiver = None
                for base in self._candidate_bases("Quiver", max_level):
                    roll = self._ceiling("Weapon 2", base, **kw2)
                    if roll and (quiver is None or roll[0] > quiver[0]):
                        quiver = (roll[0], base, roll[1])
                if quiver:
                    chosen["Weapon 2"] = quiver[1]
                    self.pob.equip({"Weapon 2": quiver[2]})
            else:
                self.pob.equip({"Weapon 2": None})
        return chosen

    def _screen_armour(self, skeleton: Skeleton, *, n: int, seed: int, wishlist: bool) -> dict[str, str]:
        """The armour and jewellery bases: the best of n loot rolls per candidate base on the
        current build -- which, because `screen_bases` screens the weapon first, is a build
        with a weapon in hand. The slots are taken in the fillers' own order
        (`loot_gear.ordered_slots`, weapons first and then these eight).

        In wishlist mode (D73) they are not screened at all: the filler chooses them itself, on
        the bare base's own implicit and defence, from every base of the class the day-1 area
        level allows -- a screen that ranks 6 bases by 40 random rolls each would only name one
        of them, and then be overruled. The slot still has to name its class, so it gets the
        class's top day-1 base as a placeholder, and PoB is not touched."""

        chosen: dict[str, str] = {}
        max_level = self.rails.gear.wishlist.base_level_max
        fa = getattr(skeleton, "forced_affixes", {}) or {}
        for slot in ordered_slots(ARMOUR_SLOT_TYPES):
            if slot in skeleton.uniques or slot in skeleton.rare_bases:
                continue
            if wishlist:
                names = without_excluded(bases_of_type(ARMOUR_SLOT_TYPES[slot], max_level=self.rails.gear.wishlist.base_level_max), self.rails)
                if names:
                    chosen[slot] = names[0]  # the class, not the base: the wishlist filler chooses inside it
                continue
            best = None
            for base in self._candidate_bases(ARMOUR_SLOT_TYPES[slot], max_level):
                roll = self._best_roll(slot, base, n, seed, **({"forced": list(fa[slot])} if fa.get(slot) else {}))
                if roll and (best is None or roll[0] > best[0]):
                    best = (roll[0], base, roll[1])
            if best:
                chosen[slot] = best[1]
                self.pob.equip({slot: best[2]})
        return chosen

    def _candidate_bases(self, item_type: str, max_level: int) -> list[str]:
        """The screen's candidate bases of a class, minus the ones the loadout excludes (#1154)."""

        return candidate_bases(item_type, max_level=max_level, excluded=excluded_of(self.rails))

    def screen_bases(self, skeleton: Skeleton, *, n: int = 40, seed: int = 1, gear_mode: str | None = None) -> dict[str, str]:
        """Choose a rare base per slot by PoB: the weapon first (`_screen_weapons`), then the
        armour and jewellery slots (`_screen_armour`) in the fillers' own order.

        The weapon goes first for the reason `loot_gear.RARE_SLOT_ORDER` puts it first
        (measured on bleed_bow, 2026-09-18): an attack build with an empty main hand deals no
        damage at all, so while the armour and jewellery bases were screened before the weapon
        every candidate scored 0 CombinedDPS under the same infinite violation, and only the
        floors could tell one base from another -- the choice was blind to damage. A spell is
        unaffected (PoB scores it without a weapon), so the order is unconditional.

        In wishlist mode (D73) only the weapon screen runs: which weapon type the build fights
        with is a decision about the build, and the filler keeps the class it is given, while
        the armour and jewellery bases are the filler's own choice."""

        t0 = time.perf_counter()
        wishlist = (gear_mode or self.gear_mode) == "wishlist"
        chosen: dict[str, str] = dict(self._screen_weapons(skeleton))
        chosen.update(self._screen_armour(skeleton, n=n, seed=seed, wishlist=wishlist))
        chosen = {slot: base for slot, base in chosen.items() if slot not in skeleton.forced_bases}  # a forced base is never overwritten
        skeleton.rare_bases.update(chosen)
        self.log(f"bases by PoB ({human_duration(time.perf_counter() - t0)}): {chosen}" + (" [armour and jewellery: the class only, the wishlist filler chooses the base]" if wishlist else ""))
        return chosen

    # -- ascendancy --------------------------------------------------------------

    def pick_ascendancy_nodes(self, skeleton: Skeleton, *, points: int = 8,
                              reconfigure: "Rejudge | None" = None) -> list[int]:
        """Greedy: each step tries every unallocated ascendancy pick with its path
        and keeps the best objective gain per point. Applied through set_tree with
        the skeleton's keystones only (call before the passive tree exists)."""

        t0 = time.perf_counter()
        asc = ascendancy(skeleton.ascendancy)
        if asc is None:
            return list(skeleton.ascendancy_nodes)
        nodes = {int(n["node_id"]): n for n in asc.get("nodes") or []}
        starts = {int(s) for s in asc.get("start_node_ids") or []}
        adjacency: dict[int, set[int]] = defaultdict(set)
        for nid, n in nodes.items():
            for other in (*(n.get("incoming_node_ids") or []), *(n.get("outgoing_node_ids") or [])):
                if int(other) in nodes:
                    adjacency[nid].add(int(other))
                    adjacency[int(other)].add(nid)
        picks = _ascendancy_picks(nodes, adjacency)
        allocated: set[int] = set(int(n) for n in skeleton.ascendancy_nodes) | starts
        refused: set[int] = set()  # PoB will not hold this pick together with what is already allocated

        def apply(alloc: Iterable[int]) -> None:
            self.pob.set_tree(class_id=skeleton.class_name, ascendancy_id=skeleton.ascendancy, ascendancy_nodes=sorted(set(alloc) - starts), keystones=skeleton.keystones)

        def points_spent() -> int:
            # PoB's own count: a fixed notable brings its path with it, our set does not know that
            state = self.pob.read_state().get("tree_state") or {}
            ids = state.get("allocated_ascendancy_node_ids") or []
            return int(state.get("allocated_ascendancy_points") or len(ids))

        apply(allocated)
        allocated |= {int(n) for n in ((self.pob.read_state().get("tree_state") or {}).get("allocated_ascendancy_node_ids") or [])}
        spent = points_spent()
        score = self._score()
        while spent < points:
            # shortest path from the allocated set to every unallocated notable
            frontier = list(allocated)
            parent: dict[int, int | None] = {n: None for n in allocated}
            order = list(frontier)
            while order:
                cur = order.pop(0)
                for nb in adjacency.get(cur, ()):
                    if nb not in parent:
                        parent[nb] = cur
                        order.append(nb)
            candidates: list[tuple[int, list[int]]] = []
            for nid, n in nodes.items():
                if nid in allocated or nid in refused or nid not in picks or nid not in parent:
                    continue
                path = []
                cur: int | None = nid
                while cur is not None and cur not in allocated:
                    path.append(cur)
                    cur = parent[cur]
                if spent + len(path) <= points:
                    candidates.append((nid, path))
            if not candidates:
                break
            best = None
            for nid, path in candidates:
                try:
                    apply(allocated | set(path))
                    self._reconfigure(reconfigure, skeleton, full=True)
                except PoBHeadlessHostContractError as exc:
                    # PoB drops the sibling of a "choose one of these" option, so the set it was
                    # handed does not materialize. Which options exclude each other is PoB's
                    # answer, not ours: take the refusal as "not available on top of what is
                    # allocated", and put the build back where it was.
                    if "did not materialize" not in str(exc):
                        raise
                    refused.add(nid)
                    self.log(f"ascendancy {nodes[nid]['name']}: PoB will not hold it with the current picks")
                    apply(allocated)
                    self._reconfigure(reconfigure, skeleton, full=True)
                    continue
                s = self._score()
                ehp = float(self.pob.stats(("TotalEHP",)).get("TotalEHP") or 0)
                gain_pp = (s.value - score.value) / len(path)
                # objective gain per point first; a notable that adds nothing (Measured Retaliation on a bow) loses to one that adds EHP
                key = (s.neg_violation > score.neg_violation, gain_pp if s.feasible or not score.feasible else -1e18, ehp)
                if best is None or key > best[0]:
                    best = (key, nid, path, s)
            if best is None:  # every candidate this round was refused
                break
            _k, nid, path, s = best
            allocated |= set(path)
            apply(allocated)
            spent = points_spent()
            self.log(f"ascendancy +{len(path)} {nodes[nid]['name']}: {score.value:,.0f} -> {s.value:,.0f} (viol {s.violation:.3f}); {spent}/{points} points")
            score = s
        apply(allocated)
        self._reconfigure(reconfigure, skeleton, full=True)
        skeleton.ascendancy_nodes = sorted(allocated - starts)
        self.picks.append(Pick(what="ascendancy", choice=", ".join(nodes[n]["name"] for n in skeleton.ascendancy_nodes if n in picks), score=score, seconds=time.perf_counter() - t0))
        return skeleton.ascendancy_nodes

    # -- skill part ----------------------------------------------------------------

    def pick_skill_part(self, skeleton: Skeleton, *, max_parts: int = 8) -> tuple[int | None, str]:
        """PoB models stacked states of a skill as parts ("0 / 5 / 10 Blades", stages).
        Try every part, keep the best objective score. The part is a sustained state a
        player holds on a boss (D36); the report names it so it can be questioned."""

        from junkroan.optimizer.random_parts import random_element_groups

        # a random-element skill (Elemental Hit) is scored as the mean over an element group of
        # parts; the group's first part stands for it here and every readback averages the group
        groups = {g[0]: g for g in random_element_groups(skeleton.main_link[0])}
        grouped = {i for g in groups.values() for i in g}
        names: dict[int, str] = {}
        scores: dict[int, Score] = {}
        for part in range(1, max_parts + 1):
            skeleton.main_part = part
            self._set_main_link(skeleton, skeleton.main_link)
            entry = None
            for group in (self.pob.read_state().get("skills_state") or {}).get("socket_groups") or []:
                for e in group.get("active_skill_entries") or []:
                    if e.get("name") == skeleton.main_link[0]:
                        entry = e
                        break
                if entry:
                    break
            index = int((entry or {}).get("part_index") or 1)
            if index in names:
                break  # PoB clamped: no more parts
            names[index] = str((entry or {}).get("part_name") or "")
            if part_is_assumption(names[index]):
                continue  # "Maximum Hits" is an assumption, not a state (D42)
            if index in grouped and index not in groups:
                continue  # an element part of a group already scored through its first part
            self.pob.mean_parts = groups.get(index)
            part_obj = with_ramp(self.objective, stages=stages_in_part(names[index]))  # "10 Blades" takes 10 casts (D39)
            scores[index] = part_obj.score(self.pob.stats(part_obj.stat_keys))
            if index in groups:
                names[index] = re.sub(r"\b(fire|cold|lightning)\b\s*", "", names[index], flags=re.IGNORECASE).strip() + " (mean of fire / cold / lightning)"
        if len(scores) <= 1:
            skeleton.main_part = min(scores) if scores and len(names) > 1 else None  # the one allowed part, or PoB's default
            self._set_main_link(skeleton, skeleton.main_link)
            self.pob.mean_parts = groups.get(skeleton.main_part or 1)
            return skeleton.main_part, (names.get(skeleton.main_part, "") if skeleton.main_part else "")
        best = max(scores, key=lambda i: scores[i])
        skeleton.main_part = best
        self._set_main_link(skeleton, skeleton.main_link)
        self.pob.mean_parts = groups.get(best)
        self.log(f"skill part: {names[best]!r} ({', '.join(f'{names[i]} {scores[i].value:,.0f}' for i in sorted(scores))})")
        self.picks.append(Pick(what="skill part", choice=names[best], score=scores[best]))
        return best, names[best]

    # -- supports ----------------------------------------------------------------

    def legal_supports(self, skeleton: Skeleton) -> list[str]:
        """Supports PoB actually links to the main skill (its own readback), day-1 only.
        Legality depends on the skill's tags, not on the build, so it is cached per skill; the saved file is
        valid only for the PoB commit, the skill and the candidate list it was built from (#980)."""

        cache = legal_supports_cache_path(skeleton.main_link[0])
        if not skeleton.forbid_supports:
            note_saved_list(cache)  # #978: the state this run starts from, before the read or the write below
        key = "" if skeleton.forbid_supports else legal_supports_key(skeleton.main_link[0], legal_support_candidates(skeleton.main_link[0], ()))
        if cache.is_file() and not skeleton.forbid_supports:
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                if isinstance(saved, dict) and saved.get("key") == key:
                    return list(saved["legal"])
            except (ValueError, KeyError, TypeError):
                pass
        legal = []
        # supports that change the delivery (mines, traps, totems, triggers) are a hypothesis-level
        # choice, never a greedy pick: PoB scores them under mine/trap/totem count assumptions
        names = legal_support_candidates(skeleton.main_link[0], skeleton.forbid_supports)
        for name in names:
            self._set_main_link(skeleton, [skeleton.main_link[0], name], refresh_castability=False)
            state = self.pob.read_state().get("skills_state") or {}
            linked = False
            for group in state.get("socket_groups") or []:
                for entry in group.get("active_skill_entries") or []:
                    if entry.get("name") == skeleton.main_link[0] and any(l.get("name") == name for l in entry.get("support_links") or []):
                        linked = True
            if linked:
                legal.append(name)
        # the readback wrote [main, candidate] links into PoB; the skeleton's own link comes back before anyone
        # measures: the re-judge of every new-skill reference in the 2026-09-15 intake opened on a one-support
        # link (Arc Archmage 373,571 -> 64,531) and accepted its first swap against that number, unjudged
        self._set_main_link(skeleton, skeleton.main_link, refresh_castability=False)
        if not skeleton.forbid_supports:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"key": key, "legal": legal}, indent=0), encoding="utf-8")
        return legal

    def _set_main_link(self, skeleton: Skeleton, link: Sequence[str], *, changed_skill: str | None = None,
                       refresh_castability: bool = True) -> None:
        self._set_main_link_raw(skeleton, link, changed_skill=changed_skill, refresh_castability=refresh_castability)
        # the trial link, not the skeleton's own: a Spell Cascade swapped out of a Volatile Dead link
        # cuts the corpses eaten from 9 to 3, and the count PoB multiplies FullDPS by has to follow it (D57 rule 2)
        counts_before = dict(skeleton.gem_counts)
        counts = skeleton.refresh_minion_counts(self.pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality,
                                                main_quality=self.rails.gems.main_quality, main_link=list(link), log=self.log)
        if counts and counts_before != skeleton.gem_counts:
            # The count setter reapplies the complete skills surface; it can
            # change more than the candidate active skill.
            self.refresh_castability()

    def _set_main_link_raw(self, skeleton: Skeleton, link: Sequence[str], *, changed_skill: str | None = None,
                           refresh_castability: bool = True) -> None:
        """The skills surface with `link` in place of the skeleton's main link, and no lanes
        re-derived. The skeleton's minion counts and minion-skill choices (D49) are written
        as they stand: a setter that wrote count 1 left Summon Raging Spirits at 8% of the
        author through two benchmark runs, because `refresh_minion_counts` re-applies only
        when PoB's limit differs from the count the skeleton remembers."""

        changed_skill = changed_skill or skeleton.main_link[0]
        previous_ids = self._active_skill_ids(changed_skill)
        self.pob.set_skills(**skeleton.skill_payload(
            gem_level=self.rails.gems.level,
            gem_quality=self.rails.gems.quality,
            main_quality=self.rails.gems.main_quality,
            main_link=link,
        ))
        if not refresh_castability:
            return
        current_ids = self._active_skill_ids(changed_skill)
        if self.castability_context is None:
            self.refresh_castability()
        else:
            # A candidate changes only one active skill. Keep every other frozen
            # requirement and ask PoB for this skill alone.
            self.castability_context = replace_castability_skill(
                self.pob,
                self.castability_context,
                remove=(*previous_ids, *(skill_id for skill_id, _mana, _life in self.castability_context.requirements if skill_id not in self._all_active_skill_ids())),
                active_skill_id=current_ids[0] if current_ids else None,
                metrics=self.castability_metrics,
            )
            self._apply_castability_context()

    def _try_score(self, skeleton: Skeleton, link: Sequence[str], reconfigure: "Rejudge | None", *, full: bool = False) -> Score | None:
        """The score of `link` written into PoB, or None when the write or the score raises (#550 R2: a trial that
        raises is a rejected trial, never the end of the pass). A PoB contract error propagates at once (#556 R4); any
        other RuntimeError is counted `support-trial:raised`, kept in `self._trial_error` for the round (#556 R5)."""

        self._trial_error = None
        try:
            self._set_main_link(skeleton, link)
            self._reconfigure(reconfigure, skeleton, full=full)
            return self._score()
        except POB_CONTRACT_ERRORS:
            raise
        except RuntimeError as exc:
            self._trial_error = exc
            TRACE.add_generated({"support-trial:raised"})
            TRACE.add_evaluated({"support-trial:raised"})
            self.log(f"support trial {list(link[1:])} raised {type(exc).__name__}: {exc}; rejected")
            return None

    def pick_supports(self, skeleton: Skeleton, *, n_supports: int | None = None, legal: Sequence[str] | None = None, reconfigure: "Rejudge | None" = None, shortlist: int = 30) -> list[str]:
        """Greedy: add the support with the best objective score until the link is full.
        Mana cost is part of the objective (unreserved mana >= cost), so PoB, not a
        rule, decides when a cheaper support beats a stronger one.

        `reconfigure` re-derives the config lanes after each pick: a support that
        only wins under an assumption it removes (Elemental Focus with "enemy
        ignited" still on) is rejected once the lanes are honest again."""

        cap = self.rails.gems.main_link_max - 1  # the main link is at most main_link_max gems (gm-links rail)
        n_supports = cap if n_supports is None else min(n_supports, cap)
        t0 = time.perf_counter()
        legal = list(legal) if legal is not None else self.legal_supports(skeleton)
        link = list(skeleton.main_link[:1])
        enablers = set(skeleton.enablers())
        legal_set = set(legal)
        fixed = [s for s in skeleton.main_link[1:] if s in enablers]  # enablers stay in place, never a slot (7.1d)
        fixed += [s for s in skeleton.fixed_supports if s in legal and s not in link and s not in fixed]
        link.extend(fixed)
        # the incumbent (#550 R1/R2, #557 R1'/R1''): the link the skeleton holds now. When it differs from the bare start
        # link it is scored once here (through the trial's error rule), unless it holds a support outside the legal list
        # (then it is never written into PoB and counted `support:illegal` generated) or misses a gem of the start link
        # (a fixed support or enabler a kept incumbent would drop). The re-pick replaces it only at a strictly greater
        # score; an incumbent whose score is not above 0 (or that raised) is no incumbent
        incumbent = list(skeleton.main_link)
        incumbent_score = None
        if incumbent != link:
            if any(g not in enablers and g not in legal_set for g in incumbent[1:]):
                TRACE.add_generated({"support:illegal"})
                self.log(f"support incumbent {incumbent[1:]} holds a support outside the legal list: no incumbent")
            elif not set(link) <= set(incumbent):
                self.log(f"support incumbent {incumbent[1:]} misses a gem of the start link {link[1:]}: no incumbent")
            else:
                incumbent_score = self._try_score(skeleton, incumbent, reconfigure, full=True)
                if incumbent_score is not None and not incumbent_score.value > 0:
                    incumbent_score = None
        self._set_main_link(skeleton, link)
        self._reconfigure(reconfigure, skeleton, full=True)
        score = self._score()
        score_context = self.castability_context
        rejected: set[str] = set()
        pool = list(legal)
        attempted, raised, last_error = 0, 0, None  # the whole greedy phase is one round (#556 R5)
        while len(link) - 1 < n_supports:
            best = None
            ranked: list[tuple[Score, str]] = []
            count_generated(legal, role="support", link_size=len(link) + 1)
            for name in pool:
                if name in link or name in rejected:
                    continue
                s = self._try_score(skeleton, [*link, name], reconfigure)
                attempted += 1
                if s is None:
                    raised, last_error = raised + 1, self._trial_error
                    rejected.add(name)
                    continue
                count_evaluated(name, role="support", link_size=len(link) + 1)
                ranked.append((s, name))
                if best is None or s > best[0]:
                    best = (s, name)
            if len(link) == 1 + len(fixed) and shortlist and len(ranked) > shortlist:
                # after the first full round only the top candidates stay in the running
                ranked.sort(key=lambda x: (x[0].neg_violation, x[0].value), reverse=True)
                pool = [n for _s, n in ranked[:shortlist]]
            if best is None or not best[0] > score:
                self._set_main_link(skeleton, link, refresh_castability=False)
                self._restore_castability(score_context)
                break
            if reconfigure:
                honest = self._try_score(skeleton, [*link, best[1]], reconfigure, full=True)
                if honest is None or not honest > score:
                    rejected.add(best[1])
                    self.log(f"support {best[1]} rejected: {best[0].value:,.0f} under stale config, "
                             + (f"{honest.value:,.0f} under re-derived lanes" if honest is not None else "its re-derived lanes raised")
                             + f" (vs {score.value:,.0f})")
                    self._set_main_link(skeleton, link, refresh_castability=False)
                    self._restore_castability(score_context)
                    self._reconfigure(reconfigure, skeleton, full=True)
                    continue
                best = (honest, best[1])
            link.append(best[1])
            self.log(f"support +{best[1]}: {score.value:,.0f} -> {best[0].value:,.0f} (viol {best[0].violation:.3f})")
            score = best[0]
            score_context = self.castability_context
        if attempted and raised == attempted:
            raise last_error  # every trial of the greedy phase raised: not a finished pick (#556 R5)
        # 1-for-1 swap pass: the greedy is a local optimum (Blade Trap kept Increased Critical
        # Damage while Swift Assembly in that slot was +15%); try every legal support in every
        # non-fixed slot until no swap helps
        improved = True
        rounds = 0
        while improved and rounds < 3:
            improved, rounds = False, rounds + 1
            attempted, raised, last_error = 0, 0, None  # one swap round = all its slots
            for i in range(1, len(link)):
                if link[i] in fixed:
                    continue
                score_context = self.castability_context
                best_swap = None
                count_generated(legal, role="support", link_size=len(link))
                for name in legal:
                    if name in link or name in rejected:
                        continue
                    trial = [*link[:i], name, *link[i + 1:]]
                    s = self._try_score(skeleton, trial, reconfigure)
                    attempted += 1
                    if s is None:
                        raised, last_error = raised + 1, self._trial_error
                        rejected.add(name)
                        continue
                    count_evaluated(name, role="support", link_size=len(trial))
                    if s > score and (best_swap is None or s > best_swap[0]):
                        best_swap = (s, name)
                if best_swap:
                    if reconfigure:
                        honest = self._try_score(skeleton, [*link[:i], best_swap[1], *link[i + 1:]], reconfigure, full=True)
                        if honest is None or not honest > score:
                            rejected.add(best_swap[1])
                            self._set_main_link(skeleton, link, refresh_castability=False)
                            self._restore_castability(score_context)
                            self._reconfigure(reconfigure, skeleton, full=True)
                            continue
                        best_swap = (honest, best_swap[1])
                    self.log(f"support swap {link[i]} -> {best_swap[1]}: {score.value:,.0f} -> {best_swap[0].value:,.0f}")
                    link[i] = best_swap[1]
                    score = best_swap[0]
                    score_context = self.castability_context
                    improved = True
                else:
                    self._set_main_link(skeleton, link, refresh_castability=False)
                    self._restore_castability(score_context)
            if attempted and raised == attempted:
                raise last_error  # every trial of this swap round raised (#556 R5)
        same = link[0] == incumbent[0] and sorted(link[1:]) == sorted(incumbent[1:])  # the same supports in another order
        if incumbent_score is not None and not same and not score > incumbent_score:
            # the re-pick is monotone (#557 R1'): its result replaces the incumbent only at a strictly greater score.
            # `generated` counts the result that was not kept, `evaluated` only one that was kept (stays 0)
            TRACE.add_generated({"support-repick:fewer-at-equal" if len(link) < len(incumbent) else "support-repick:below-incumbent"})
            self.log(f"support re-pick {link[1:]} ({score.value:,.0f}) is not above the incumbent {incumbent[1:]} ({incumbent_score.value:,.0f}): incumbent kept")
            link, score = incumbent, incumbent_score
        self._set_main_link(skeleton, link)
        self._reconfigure(reconfigure, skeleton, full=True)
        skeleton.main_link = link
        if any(g not in enablers and g not in legal_set for g in link[1:]):
            TRACE.add_evaluated({"support:illegal"})  # the delivered link holds a support outside the legal list: must stay 0
        self.picks.append(Pick(what="supports", choice=", ".join(link[1:]), score=score, seconds=time.perf_counter() - t0))
        return link

    # -- utility links -------------------------------------------------------------

    def utility_candidates(self, skeleton: Skeleton) -> dict[str, list[str]]:
        """Utility gems by family from the corpus tags (no Vaal variants; transfigured variants
        stand next to their base gem, rulebook gm-transfigured; no gem already in the build, movement skills that are not attacks the main
        weapon cannot use are left to PoB to score)."""

        present = {g.lower() for grp in skeleton.extra_groups for g in grp.gems} | {g.lower() for g in skeleton.main_link} | {g.lower() for g in skeleton.forbid_utilities}
        out: dict[str, list[str]] = {}
        for family, (want, avoid) in UTILITY_FAMILIES.items():
            names = []
            for r in active_gems().values():
                tags = set(r.get("tag_keys") or [])
                if not (tags & want) or (tags & avoid) or r.get("is_vaal_gem") or r["name"].startswith("Vaal "):
                    continue
                if family == "movement" and "movement" in tags and not (tags & {"travel", "blink"}):
                    continue  # Cyclone, Charged Dash... are main skills, not travel
                if r["name"].lower() in present:
                    continue
                uptime = buff_uptime(str(r.get("granted_effect_id") or ""))
                if uptime is not None and uptime < UPTIME_MIN:
                    continue  # PoB keeps the buff on all the time; Ambush (1.5 s per 5 s) tripled a Smite build (D46)
                names.append(r["name"])
            names = sorted(set(names))
            if family == "movement":
                # PoB is indifferent between travel skills; on a tie the instant blink family comes first
                names.sort(key=lambda n: 0 if "blink" in (active_gems().get(n.lower(), {}).get("tag_keys") or []) else 1)
            out[family] = names
        return out

    def _curse_limit(self) -> int | None:
        """PoB's `EnemyCurseLimit` for the build as it stands (None when PoB gives no number): the curses
        beyond it are dropped by PoB (spark-s4: limit 1, Conductivity + Sniper's Mark, only the Mark
        applied, #784), so a candidate that links one more is a socket spent on nothing."""

        value = self.pob.stats(("EnemyCurseLimit",)).get("EnemyCurseLimit")
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @staticmethod
    def _curses_linked(names: Iterable[str]) -> set[str]:
        """The distinct gems among `names` that take a curse slot (the audit's own count)."""

        return {n for n in names if is_limited_curse(n)}

    @staticmethod
    def _offer_within_curse_limit(pool: Sequence[str], linked: int, limit: int | None) -> list[str]:
        """The candidates of `pool` that keep the curses linked within `limit`: a curse (or mark) only when
        `linked` curses leave a slot free; every other gem always (#784)."""

        if limit is None or linked < limit:
            return list(pool)
        return [n for n in pool if not is_limited_curse(n)]

    @staticmethod
    def _trace_curses(names: Iterable[str], linked: int, limit: int | None, *, evaluated: bool) -> None:
        """The curse classes of the trace (#784): `curse:linked=<n>` is a candidate that makes n curses linked,
        `curse:over-limit` one that makes more than PoB applies (must stay 0 evaluated). Under the caller's move."""

        add = TRACE.add_evaluated if evaluated else TRACE.add_generated
        add(["curse:over-limit"], 0)
        for name in names:
            if is_limited_curse(name):
                add({f"curse:linked={linked + 1}"} | ({"curse:over-limit"} if limit is not None and linked + 1 > limit else set()))

    def _weapon2_is_shield(self) -> bool:
        """Is a Shield equipped in Weapon 2 (the build's own readback)."""

        slots = (self.pob.read_state().get("items_state") or {}).get("slots") or {}
        item = (slots.get("Weapon 2") or {}).get("item") if isinstance(slots, dict) else None
        if not item:
            return False
        label = str(item.get("type_label") or (item_bases().get(str(item.get("base_type") or "").lower()) or {}).get("type") or "")
        return label == "Shield"

    def _skill_attack_time(self, name: str) -> float | None:
        """PoB's "Attack Time" (output `Time`, seconds) of the active skill `name` as the build holds it; None when PoB gives none."""

        ids = self._active_skill_ids(name) or (str((active_gems().get(name.lower()) or {}).get("granted_effect_id") or name),)
        rows = self.pob.active_skill_stats(ids, ("Time",))
        for row in rows.values():
            value = row.get("Time") if isinstance(row, Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    def _linked_slot(self, skeleton: Skeleton, n: int) -> str | None:
        """The utility slot whose item still has `n` linked sockets free (PoB's `links` of the item minus the gems already
        socketed in that slot), None when no slot has them."""

        from junkroan.optimizer.socket_step import slot_groups

        slots = (self.pob.read_state().get("items_state") or {}).get("slots") or {}
        socketed = slot_groups(self.pob)
        for slot in UTILITY_SLOTS:
            item = (slots.get(slot) or {}).get("item") if isinstance(slots, dict) else None
            if int((item or {}).get("links") or 0) - len(socketed.get(slot, [])) >= n:
                return slot
        return None

    def _slot_names(self, kind: str, pool: Sequence[str], mv) -> list[str]:
        """The pool's members of the rails' list for one movement slot: never a refused gem, Shield Charge only with a shield in Weapon 2."""

        listed = mv.spell if kind == "spell" else mv.skill
        names = [n for n in pool if in_gem_list(n, listed) and not in_gem_list(n, mv.forbidden)]
        if kind == "skill" and not self._weapon2_is_shield():
            names = [n for n in names if not in_gem_list(n, mv.shield_only)]
        return names

    def _movement_options(self, skeleton: Skeleton, kind: str, pool: Sequence[str], mv) -> list[tuple[list[str], str]]:
        """The (gems, slot) options for one slot of the movement pair (#1153): the pool's members of the rails' list for `kind`
        (never a refused one; Shield Charge only with a shield in Weapon 2); the skill slot links the rails' supports when an item
        has the linked sockets, else stands alone. A `skill_skip_weapon` build whose Leap Slam "Attack Time" in PoB is at least the
        rails' value gets no skill option."""

        names = self._slot_names(kind, pool, mv)
        if kind == "skill":
            if names and mv.skill_skip_attack_time_s is not None and mv.skill_skip_weapon and self._weapon1_type() == mv.skill_skip_weapon:
                slow = self._leap_slam_too_slow(skeleton, mv)
                if slow:
                    self.log(f"movement skill skipped: {mv.skill_skip_weapon} build, Leap Slam Attack Time {slow:.2f} s >= {mv.skill_skip_attack_time_s} s")
                    return []
        default_slot = UTILITY_SLOTS[len(skeleton.extra_groups) % len(UTILITY_SLOTS)]
        out: list[tuple[list[str], str]] = []
        for name in names:
            linked = self._linked_slot(skeleton, mv.skill_link_sockets) if kind == "skill" and mv.skill_links and in_gem_list(name, mv.skill_links_for) else None
            out.append(([name, *mv.skill_links], linked) if linked else ([name], default_slot))
        return out

    def _leap_slam_too_slow(self, skeleton: Skeleton, mv) -> float | None:
        """Leap Slam's "Attack Time" in seconds when it is at least the rails' skip value, else None. Leap Slam is written into
        PoB alone for the read and taken out again."""

        name = "Leap Slam"
        before = list(skeleton.extra_groups)
        context = self.castability_context
        skeleton.extra_groups = [*before, SocketGroup(gems=[name], slot=UTILITY_SLOTS[len(before) % len(UTILITY_SLOTS)], label=name)]
        try:  # a read of PoB, no option of the slot: nothing is counted here (the options loop counts what it writes)
            self._set_main_link(skeleton, skeleton.main_link, changed_skill=name)
            time_s = self._skill_attack_time(name)
        finally:
            skeleton.extra_groups = before
            self._set_main_link(skeleton, skeleton.main_link)
            self._restore_castability(context)
        return time_s if time_s is not None and time_s >= (mv.skill_skip_attack_time_s or 0.0) else None

    def pick_utilities(self, skeleton: Skeleton, *, max_groups: int | None = None, reconfigure: "Rejudge | None" = None, shortlist: int = 25) -> list[SocketGroup]:
        """Add utility socket groups (one gem each) greedily: every candidate is a real
        group in PoB, the objective (mana reservation, sustain, floors) decides. The
        movement pair (a spell and a skill from the rails' lists, #1153) is added first
        when the rails require it, outside `max_groups`; inside each slot PoB's
        best-scoring (then most EHP) member is taken."""

        t0 = time.perf_counter()
        max_groups = max_groups if max_groups is not None else self.rails.utility_max_groups
        cands = self.utility_candidates(skeleton)
        added: list[SocketGroup] = []
        mv = movement_rails(self.rails)  # the movement pair (#1153)
        authored = {id(grp) for grp in skeleton.extra_groups}

        def with_groups(groups: Sequence[SocketGroup], *, changed_skill: str | None = None) -> None:
            if mv is not None:
                for grp in groups:  # the PoB boundary: a refused movement gem written into the build counts evaluated (must stay 0)
                    if id(grp) not in authored and refused_movement_gems(grp.gems, self.rails):
                        TRACE.add_evaluated([MOVEMENT_FORBIDDEN_CLASS])
            skeleton.extra_groups = list(groups)
            self._set_main_link(skeleton, skeleton.main_link, changed_skill=changed_skill,
                                refresh_castability=changed_skill is not None)

        def score_now(*, full: bool = False) -> tuple[Score, float]:
            self._reconfigure(reconfigure, skeleton, full=full)
            stats = self.pob.stats((*self.objective.stat_keys, "TotalEHP"))
            return self.objective.score(stats), float(stats.get("TotalEHP") or 0)

        base_groups = list(skeleton.extra_groups)
        with_groups(base_groups)
        current = score_now(full=True)
        current_context = self.castability_context
        curse_limit = self._curse_limit()  # a candidate curse is offered only while the build has a curse slot PoB applies
        if mv is not None and cands.get("movement"):
            TRACE.add_generated([MOVEMENT_FORBIDDEN_CLASS], 0)
            TRACE.add_evaluated([MOVEMENT_FORBIDDEN_CLASS], 0)
            carried = {movement_kind(g, mv) for grp in base_groups for g in grp.gems} | {movement_kind(g, mv) for g in skeleton.main_link}
            for kind in ("spell", "skill"):
                if kind in carried:
                    continue
                best = None
                for gems, slot in self._movement_options(skeleton, kind, cands["movement"], mv):
                    classes = {f"movement-{kind}", *gem_classes(gems[0], role="gem", link_size=len(gems))}
                    TRACE.add_generated(classes)
                    with_groups([*base_groups, *added, SocketGroup(gems=list(gems), slot=slot, label=gems[0])], changed_skill=gems[0])
                    s = score_now()
                    TRACE.add_evaluated(classes)
                    if s[0].neg_violation >= current[0].neg_violation - 1e-9 and (best is None or s > best[0]):
                        best = (s, gems, slot)
                if best:
                    added.append(SocketGroup(gems=list(best[1]), slot=best[2], label=best[1][0], picked=True))
                    with_groups([*base_groups, *added], changed_skill=best[1][0])
                    current = score_now(full=True)
                    current_context = self.castability_context
                    self.log(f"utility +{', '.join(best[1])} (movement {kind}): {current[0].value:,.0f} (viol {current[0].violation:.3f})")
                else:
                    with_groups([*base_groups, *added])
                    self._restore_castability(current_context)
        cands.pop("movement", None)
        pool = [n for fam, names in cands.items() if fam != "movement" for n in names]
        rejected: set[str] = set()
        while utility_groups_used([*base_groups, *added], self.rails) < max_groups and pool:
            best = None
            ranked: list[tuple[tuple[Score, float], str]] = []
            linked_now = len(self._curses_linked([*skeleton.main_link, *(g for grp in (*base_groups, *added) if grp.enabled for g in grp.gems)]))
            offered = self._offer_within_curse_limit(pool, linked_now, curse_limit)
            if not offered:
                break  # only curses are left and the build has no curse slot PoB would apply
            count_generated(offered, role="gem", link_size=1)
            self._trace_curses(offered, linked_now, curse_limit, evaluated=False)
            for name in offered:
                if name in rejected or any(name in g.gems for g in added):
                    continue
                with_groups([*base_groups, *added, SocketGroup(gems=[name], slot=UTILITY_SLOTS[len(base_groups + added) % len(UTILITY_SLOTS)], label=name)], changed_skill=name)
                s = score_now()
                count_evaluated(name, role="gem", link_size=1)
                self._trace_curses([name], linked_now, curse_limit, evaluated=True)
                ranked.append((s, name))
                if best is None or s > best[0]:
                    best = (s, name)
            if best is None or not best[0][0] > current[0]:
                with_groups([*base_groups, *added])
                self._restore_castability(current_context)
                break
            if shortlist and len(ranked) > shortlist:
                ranked.sort(key=lambda x: x[0], reverse=True)
                pool = [n for _s, n in ranked[:shortlist]]
            candidate = SocketGroup(gems=[best[1]], slot=UTILITY_SLOTS[len(base_groups + added) % len(UTILITY_SLOTS)], label=best[1], picked=True)
            with_groups([*base_groups, *added, candidate], changed_skill=best[1])
            honest = score_now(full=True)
            if not honest[0] > current[0]:
                rejected.add(best[1])  # only won under the previous lanes (an assumption the gem itself removed)
                with_groups([*base_groups, *added])
                self._restore_castability(current_context)
                current = score_now(full=True)
                self.log(f"utility {best[1]} rejected under re-derived lanes ({honest[0].value:,.0f} vs {current[0].value:,.0f})")
                continue
            added.append(candidate)
            current = honest
            current_context = self.castability_context
            self.log(f"utility +{best[1]}: -> {current[0].value:,.0f} (viol {current[0].violation:.3f})")
        with_groups([*base_groups, *added])
        self._restore_castability(current_context)
        current = score_now(full=True)
        self.picks.append(Pick(what="utilities", choice=", ".join(g.gems[0] for g in added), score=current[0], seconds=time.perf_counter() - t0))
        return added

    # -- the fill step (#1156) ------------------------------------------------------------

    def fill_candidates(self, skeleton: Skeleton) -> list[str]:
        """The gems the fill step may measure: `fill_candidate_names()` without a gem the build carries, a gem the request
        forbids and a gem the rails refuse as movement (Smoke Mine, Lightning Warp)."""

        present = {g.lower() for grp in skeleton.extra_groups for g in grp.gems} | {g.lower() for g in skeleton.main_link} | {g.lower() for g in skeleton.forbid_utilities}
        mv = movement_rails(self.rails)
        return sorted(n for n in fill_candidate_names() if n.lower() not in present and not (mv is not None and in_gem_list(n, mv.forbidden)))

    def _free_sockets(self) -> dict[str, list[str]]:
        """Per candidate slot, the colours (R/G/B/W/A) of the sockets of its item that no gem holds yet; only slots with one,
        in `FILL_SLOTS` order. PoB's readback: the item's `sockets` (the `color` of each) minus the gems socketed in the slot,
        which take the first sockets (`socket_step.slot_groups` counts them the same way)."""

        from junkroan.optimizer.socket_step import slot_groups

        slots = (self.pob.read_state().get("items_state") or {}).get("slots") or {}
        socketed = slot_groups(self.pob)
        out: dict[str, list[str]] = {}
        for slot in FILL_SLOTS:
            item = (slots.get(slot) or {}).get("item") if isinstance(slots, dict) else None
            colours = [(str((sock.get("color") if isinstance(sock, dict) else sock) or "").upper() or "W") for sock in (item or {}).get("sockets") or []]
            free = colours[len(socketed.get(slot, [])):]
            if free:
                out[slot] = free
        return out

    @staticmethod
    def _socket_for(colour: str | None, free: Mapping[str, Sequence[str]]) -> tuple[str, int] | None:
        """The (slot, index) of the free socket a gem of ``colour`` takes: the first slot that has a socket the gem fits, in
        that slot a socket of its own colour before a white one. A white socket fits any gem, an abyss socket (A) none, and a
        gem with no colour in the corpus fits any socket but an abyss one."""

        for slot, sockets in free.items():
            fitting = [i for i, c in enumerate(sockets) if c != "A" and (colour is None or c == colour or c not in ("R", "G", "B"))]
            if fitting:
                return slot, next((i for i in fitting if sockets[i] == colour), fitting[0])
        return None

    @staticmethod
    def _reserve_pools(name: str) -> frozenset[str]:
        """The pools the gem reserves from, read off PoB's level data (`lifeReservation*` -> Life, `manaReservation*` -> Mana);
        a gem PoB types `hasreservation` whose level data names no pool is Mana (the data does not say more)."""

        effect = str((active_gems().get(name.lower()) or {}).get("granted_effect_id") or "")
        pools = reservation_pools(effect)
        return pools or (frozenset({"Mana"}) if "hasreservation" in skill_types(effect) else frozenset())

    def pick_fill(self, skeleton: Skeleton, *, reconfigure: "Rejudge | None" = None,
                  tune: "Callable[[Skeleton, dict[str, list[str]]], object] | None" = None,
                  hold_config: "Callable[[], Callable[[], None]] | None" = None) -> list[SocketGroup]:
        """Fill the free sockets with the gems PoB counts (#1156), after the utility pick and not capped by `max_groups`.

        Every candidate stands alone in the first slot that has a free socket its colour fits (`_socket_for`; a candidate with
        none is never measured) and is measured by PoB, with each of its own config choices tried (`tune`, the pipeline's
        `tune_given_choices`: Flesh and Stone under Blood and Sand stance). A candidate passes when no floor gets worse than
        now, the objective falls by at most `fill_max_objective_loss` and TotalEHP or the objective rises by `fill_min_gain`;
        one that fails is dropped for good. The best passing one by (Score, TotalEHP) is confirmed under re-derived lanes and
        kept, greedily, until no socket or no candidate is left; a kept gem uses up its socket. Once the pool a candidate
        reserves from (`_reserve_pools`: Mana or Life) has nothing unreserved (`ManaUnreserved` / `LifeUnreserved` <= 0) it is
        not measured any more. The trace counts under the caller's `TRACE.move`.

        `hold_config` takes the config PoB holds after a full re-judge and returns the closure that writes it back: a
        candidate's own choices are tuned into PoB's config, which the next lane write would carry on (`plan_config`
        preserves every non-bool input), so after each such candidate the build goes back to what it was and the held
        config is written under it (#1156)."""

        t0 = time.perf_counter()
        added: list[SocketGroup] = []
        free = {slot: list(colours) for slot, colours in self._free_sockets().items() if colours}
        pool = [n for n in self.fill_candidates(skeleton) if self._socket_for(gem_colour(n), free) is not None]
        if not pool:
            return added
        base_groups = list(skeleton.extra_groups)
        gain, max_loss = float(self.rails.fill_min_gain), float(self.rails.fill_max_objective_loss)

        def with_groups(groups: Sequence[SocketGroup], *, changed_skill: str | None = None) -> None:
            skeleton.extra_groups = list(groups)
            self._set_main_link(skeleton, skeleton.main_link, changed_skill=changed_skill,
                                refresh_castability=changed_skill is not None)

        def number(value: object) -> float | None:
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        def score_now(*, full: bool = False) -> tuple[Score, float, float | None, float | None]:
            """(score, TotalEHP, ManaUnreserved, LifeUnreserved)"""

            self._reconfigure(reconfigure, skeleton, full=full)
            keys = tuple(dict.fromkeys((*self.objective.stat_keys, "TotalEHP", "ManaUnreserved", "LifeUnreserved")))
            stats = self.pob.stats(keys)
            return self.objective.score(stats), float(stats.get("TotalEHP") or 0), number(stats.get("ManaUnreserved")), number(stats.get("LifeUnreserved"))

        def keeps(now: tuple, then: tuple) -> bool:
            return fill_keeps(now, then, gain=gain, max_loss=max_loss)

        def restore_choices(saved: dict) -> None:
            skeleton.tuned_choices.clear()  # in place: the lanes and the judging hold this dict
            skeleton.tuned_choices.update(saved)

        def hold() -> Callable[[], None]:
            return hold_config() if hold_config is not None else (lambda: None)

        with_groups(base_groups)
        current = score_now(full=True)
        restore_config = hold()
        current_context = self.castability_context
        while pool:
            unreserved = {"Mana": current[2], "Life": current[3]}
            pool = [n for n in pool if self._socket_for(gem_colour(n), free) is not None]  # the free sockets only get fewer
            offered = [n for n in pool if all(unreserved[p] is None or unreserved[p] > 0 for p in self._reserve_pools(n))]
            if not offered:
                break
            round_choices = dict(skeleton.tuned_choices)
            passing: list[tuple[tuple[Score, float], str, dict, tuple[str, int]]] = []
            for name in offered:
                place = self._socket_for(gem_colour(name), free)
                slot = place[0]
                classes = {FILL_CLASS, *gem_classes(name, role="gem", link_size=1)}
                TRACE.add_generated(classes)
                with_groups([*base_groups, *added, SocketGroup(gems=[name], slot=slot, label=name)], changed_skill=name)
                own = own_choices(name) if tune is not None else {}
                if own:
                    tune(skeleton, own)
                seen = score_now()
                TRACE.add_evaluated(classes)
                if keeps(current, seen):
                    passing.append(((seen[0], seen[1]), name, dict(skeleton.tuned_choices), place))
                else:
                    pool.remove(name)
                    self.log(f"fill {name}: {seen[0].value:,.0f} / EHP {seen[1]:,.0f} vs {current[0].value:,.0f} / {current[1]:,.0f}: not kept")
                if own:
                    restore_choices(round_choices)
                    with_groups([*base_groups, *added])  # the build as it was: the config comes back under it
                    restore_config()
            if not passing:
                with_groups([*base_groups, *added])
                self._restore_castability(current_context)
                break
            _key, name, chosen, (slot, index) = max(passing, key=lambda p: p[0])
            restore_choices(chosen)
            candidate = SocketGroup(gems=[name], slot=slot, label=name, picked=True)
            with_groups([*base_groups, *added, candidate], changed_skill=name)
            honest = score_now(full=True)
            pool.remove(name)
            if not keeps(current, honest):
                restore_choices(round_choices)  # only won under the previous lanes (an assumption the gem itself removed)
                with_groups([*base_groups, *added])
                self._restore_castability(current_context)
                restore_config()  # the winner's re-judge wrote its lane into PoB: the plan held before it goes back, then the re-score carries nothing of the winner
                current = score_now(full=True)
                restore_config = hold()
                self.log(f"fill {name} rejected under re-derived lanes ({honest[0].value:,.0f} vs {current[0].value:,.0f})")
                continue
            added.append(candidate)
            del free[slot][index]  # the gem sits in that socket now: the next candidate sees one socket fewer
            if not free[slot]:
                del free[slot]
            current = honest
            restore_config = hold()
            current_context = self.castability_context
            self.log(f"fill +{name} ({slot}): {current[0].value:,.0f} / EHP {current[1]:,.0f} / ManaUnreserved {current[2]} / LifeUnreserved {current[3]}")
        with_groups([*base_groups, *added])
        self._restore_castability(current_context)
        current = score_now(full=True)
        self.picks.append(Pick(what="fill", choice=", ".join(g.gems[0] for g in added), score=current[0], seconds=time.perf_counter() - t0))
        return added

    # -- giving reservation back when the build misses a floor ----------------------

    def _relief_note(self, before: Mapping[str, object], after: Mapping[str, object]) -> str:
        """The constraint a move relieved most, in PoB's own numbers: "MoMUnreservedShare 0.324 ->
        0.612", or "ManaUnreserved>=ManaCost viol 0.264 -> 0.000" for a relation, which has no
        single observed value to quote."""

        was, now = self.objective.violations(before), self.objective.violations(after)
        key, relief = "", 0.0
        for k, v in was.items():
            if v - now.get(k, 0.0) > relief:
                key, relief = k, v - now.get(k, 0.0)
        if not key:
            return "no constraint relieved"
        if key in self.objective.floors:
            full_before = {**before, **self.objective.derived_values(before)}
            full_after = {**after, **self.objective.derived_values(after)}
            if isinstance(full_before.get(key), (int, float)) and isinstance(full_after.get(key), (int, float)):
                return f"{key} {float(full_before[key]):.3f} -> {float(full_after[key]):.3f}"
        return f"{key} viol {was[key]:.3f} -> {now.get(key, 0.0):.3f}"

    def drop_reserving_group(self, skeleton: Skeleton, *, reconfigure: "Rejudge | None" = None,
                             min_gain: float = 0.005, current: Score | None = None, order: ScoreOrder = "floors") -> dict | None:
        """The one move of the improvement loop that can lower reservation (D72).

        While the build misses a floor or a relation, every enabled socket group PoB reports as
        reserving mana or life is a candidate for removal, and the drop with the best Score is kept
        when `better_score` accepts it -- feasibility first, so a drop that buys the floor wins at a
        lower value. Nothing else in the loop can do this: the tree moves allocate and deallocate
        nodes, the gear moves roll items, and the picks swap one utility gem for another of the same
        family. On the rules-smoke run (20260918-0723) stormbrand s3 took Mind over Matter in pass 1,
        landed at `MoMUnreservedShare` 0.324 against a floor of 0.40, and stayed infeasible for nine
        more passes with no move able to give the mana back.

        Which groups reserve is PoB's answer and not a gem-name list: each group is disabled, the
        build recalculated, and the group reserved exactly when `ManaUnreserved` or `LifeUnreserved`
        rose (`_frees_reservation`). A feasible build tries nothing at all -- the move is inert, and
        reservation is only ever paid back to buy a floor, never to buy damage.

        A dropped group stays in the skeleton with `enabled=False`, the way `optimizer/buff_gems.py`
        disables a guard skill: nothing is removed from the build, so a later construction or a
        variant of it picks the gem again. Returns the change (as `rejudge_picks` reports one) or
        None when nothing was dropped.

        `order` is the Score order of the choice among the drops and of the acceptance ("floors" is
        `better_score`, the default; the improvement loop passes "priced", D116 / #553)."""

        key, better = score_key(order), accepts_under(order)
        self._reconfigure(reconfigure, skeleton, full=True)
        if self._score().feasible:
            return None  # inert: the build misses nothing, so there is no floor to buy and no trial to run
        candidates = [g for g in skeleton.extra_groups if g.enabled and g.gems]
        if not candidates:
            return None
        base_context = self.castability_context
        # an instance-counted main skill (minions, totems, brands: D49, D57) carries its count in the
        # skill payload, and the raw setter writes 1 -- which judges every trial at half the FullDPS
        # of the build it is compared with (measured on stormbrand s3: a trial at 590,854 against an
        # incumbent at 1,869,566, two brands). The same witness `rejudge_picks` uses, read before the
        # baseline because it can re-apply the skills itself.
        set_trial = self._set_main_link if skeleton.refresh_minion_counts(self.pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality, main_quality=self.rails.gems.main_quality) else self._set_main_link_raw
        keys = (*self.objective.stat_keys, *RESERVATION_KEYS)
        before = self.pob.stats(keys)
        cur = self.objective.score(before)  # the baseline the trials are compared with, read after the counts
        if cur.feasible:
            return None
        best: tuple[Score, SocketGroup, dict] | None = None
        for group in candidates:
            group.enabled = False
            set_trial(skeleton, skeleton.main_link, changed_skill=group.gems[0])
            reserved = self.pob.stats(keys)
            self._reconfigure(reconfigure, skeleton, full=True)
            stats = self.pob.stats(keys)
            group.enabled = True
            if not _frees_reservation(before, reserved):
                continue  # PoB gave nothing back: this group reserves nothing
            s = self.objective.score(stats)
            if best is None or key(s) > key(best[0]):
                best = (s, group, stats)
        self._set_main_link(skeleton, skeleton.main_link, refresh_castability=False)  # the build back exactly as the move found it
        self._restore_castability(base_context)
        self._reconfigure(reconfigure, skeleton, full=True)
        if best is None or not better(best[0], cur, min_gain=min_gain):
            if reconfigure and best is not None:
                self.log(f"picks: dropping {' + '.join(best[1].gems)} rejected under re-derived lanes ({best[0].value:,.0f} viol {best[0].violation:.3f} vs {cur.value:,.0f} viol {cur.violation:.3f})")
            return None
        group = best[1]
        name = " + ".join(group.gems)  # the whole group goes off, so the whole group is named
        group.enabled = False
        self._set_main_link(skeleton, skeleton.main_link, changed_skill=group.gems[0])
        if reconfigure:
            self._reconfigure(reconfigure, skeleton, full=True)  # judged under the lanes the drop itself earns (D45), as every other move
        after = self.pob.stats(keys)
        verified = self.objective.score(after)
        if not better(verified, cur, min_gain=min_gain):
            group.enabled = True
            self._set_main_link(skeleton, skeleton.main_link, refresh_castability=False)
            self._restore_castability(base_context)
            if reconfigure:
                self._reconfigure(reconfigure, skeleton, full=True)
            self.log(f"picks: dropping {name} rejected under re-derived lanes ({verified.value:,.0f} viol {verified.violation:.3f} vs {cur.value:,.0f} viol {cur.violation:.3f})")
            return None
        gain = f"{verified.value / cur.value - 1:+.1%}" if cur.value > 0 else f"{verified.value:,.0f}"
        text = f"dropped {name} ({self._relief_note(before, after)}, {gain})"
        self.log(f"picks: {text}")
        return {"what": "dropped", "was": name, "now": "off", "before": cur.value, "after": verified.value, "text": text}

    # -- re-judging picks on the finished build ------------------------------------

    def rejudge_picks(self, skeleton: Skeleton, *, reconfigure: "Rejudge | None" = None, min_gain: float = 0.005, max_sweeps: int = 3, order: ScoreOrder = "floors") -> list[dict]:
        """Every discrete pick judged again with the tree, gear and lanes in place: each
        support of the main link (not the request's fixed ones) and each utility group
        the picker chose, one at a time against every alternative; a swap is kept only
        when the objective under re-derived lanes improves by `min_gain`. Sweeps repeat
        until one changes nothing. Supports and utilities are picked early (a bare rig,
        then once after gear pass 2) and the build they were right for is gone by the
        end: a Smite Slayer kept Immolate over Trinity (no fire or cold in its hits when
        supports were judged; Anger and Herald of Ice came later) and Flammability over
        Elemental Weakness (Anger was in, Herald of Ice not yet).

        `order` is the Score order of every choice and acceptance here ("floors" is today's
        violation-first one, the default; the improvement loop passes "priced", D116 / #553)."""

        key, accept = score_key(order), accepts_under(order)
        t_all = time.perf_counter()
        changes: list[dict] = []
        opening = self._score()  # the build as the caller measured it

        def honest() -> Score:
            self._reconfigure(reconfigure, skeleton, full=True)
            return self._score()

        def trial_score() -> Score:
            self._reconfigure(reconfigure, skeleton)
            return self._score()

        def better(new: Score, cur: Score) -> bool:
            return accept(new, cur, min_gain=min_gain)

        legal = self.legal_supports(skeleton)
        shortlists: dict[int, list[str]] = {}  # per support slot: the alternatives worth a second sweep
        movement_tags = {"travel", "blink"}
        mv = movement_rails(self.rails)  # the movement pair (#1153)
        # a minion build's counts (Raise Zombie x limit, D49) live in the skill payload: the raw setter writes count 1 and
        # collapsed Summon Raging Spirits to 8% of the author in run D; such builds use the full setter for every trial
        has_minions = bool(skeleton.refresh_minion_counts(self.pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality, main_quality=self.rails.gems.main_quality))
        set_trial = self._set_main_link if has_minions else self._set_main_link_raw

        def is_movement(name: str) -> bool:
            return bool(set(active_gems().get(name.lower(), {}).get("tag_keys") or []) & movement_tags)

        current = honest()
        if opening.value > 0 and current.value < opening.value * 0.9:
            # a swap judged against a broken baseline is no judgment: the first alternative wins whatever it is worth
            raise RuntimeError(f"the re-judge opened at {current.value:,.0f} on a build measured at {opening.value:,.0f} before it: a readback or setter left the build changed")
        for sweep in range(max_sweeps):
            changed = False
            # first, the only move that can give reservation back: while a floor is missed, one
            # reserving group may be dropped (D72). On a feasible build it does nothing at all.
            dropped = self.drop_reserving_group(skeleton, reconfigure=reconfigure, min_gain=min_gain, current=current, order=order)
            if dropped:
                changes.append(dropped)
                current = honest()  # the drop already left the lanes derived for what it kept
                changed = True
            # supports: one slot at a time against every legal alternative (the first sweep ranks them; later sweeps keep the top 12)
            enablers = skeleton.enablers()
            for i in range(1, len(skeleton.main_link)):
                if skeleton.main_link[i] in skeleton.fixed_supports or skeleton.main_link[i] in enablers:
                    continue
                original = list(skeleton.main_link)
                ranked: list[tuple[Score, str]] = []
                count_generated(legal, role="support", link_size=len(original))
                for name in shortlists.get(i, legal):
                    if name in original:
                        continue
                    trial = list(original)
                    trial[i] = name
                    set_trial(skeleton, trial)
                    ranked.append((trial_score(), name))
                    count_evaluated(name, role="support", link_size=len(original))
                ranked.sort(key=lambda x: key(x[0]), reverse=True)
                shortlists[i] = [n for _s, n in ranked[:12]]
                if ranked and better(ranked[0][0], current):
                    trial = list(original)
                    trial[i] = ranked[0][1]
                    self._set_main_link(skeleton, trial)
                    verified = honest()
                    if better(verified, current):
                        skeleton.main_link = trial
                        changes.append({"what": "support", "was": original[i], "now": ranked[0][1], "before": current.value, "after": verified.value})
                        self.log(f"re-judged support {original[i]} -> {ranked[0][1]}: {current.value:,.0f} -> {verified.value:,.0f}")
                        current = verified
                        changed = True
                        continue
                    self._set_main_link(skeleton, original)
                    current = honest()
                else:
                    self._set_main_link(skeleton, original)  # the full setter: minion counts come back
                    current = honest()
            # utilities: each picked group against every candidate gem of its own kind (a movement skill stays a movement skill: the rails require one)
            cands = self.utility_candidates(skeleton)
            pool_all = [n for fam, names in cands.items() if fam != "movement" for n in names]
            curse_limit = self._curse_limit()
            for group in [g for g in skeleton.extra_groups if g.picked and g.enabled]:  # a dropped group (D72) is off: swapping its gem changes nothing
                original_gem = group.gems[0]
                original_gems = list(group.gems)  # a swap keeps the group's supports (a linked movement skill)
                slot_kind = movement_kind(original_gem, mv) if mv is not None else None
                if slot_kind:  # a movement group stays inside its own slot's list (#1153)
                    pool = self._slot_names(slot_kind, cands.get("movement", []), mv)
                elif mv is None and is_movement(original_gem):
                    pool = cands.get("movement", [])
                else:
                    pool = pool_all
                best = None
                # the curses the build links without this group: a swap to a curse needs a slot left among them (#784)
                others = len(self._curses_linked([*skeleton.main_link, *(g for grp in skeleton.extra_groups if grp is not group and grp.enabled for g in grp.gems)]))
                pool = self._offer_within_curse_limit(pool, others, curse_limit)
                count_generated(pool, role="gem", link_size=1)
                self._trace_curses(pool, others, curse_limit, evaluated=False)
                for name in pool:
                    if any(name in g.gems for g in skeleton.extra_groups) or name in skeleton.main_link:
                        continue
                    group.gems, group.label = [name, *original_gems[1:]], name
                    set_trial(skeleton, skeleton.main_link, changed_skill=name)
                    s = trial_score()
                    count_evaluated(name, role="gem", link_size=1)
                    self._trace_curses([name], others, curse_limit, evaluated=True)
                    if best is None or key(s) > key(best[0]):
                        best = (s, name)
                if best is not None and better(best[0], current):
                    group.gems, group.label = [best[1], *original_gems[1:]], best[1]
                    self._set_main_link(skeleton, skeleton.main_link, changed_skill=best[1])
                    verified = honest()
                    if better(verified, current):
                        changes.append({"what": "utility", "was": original_gem, "now": best[1], "before": current.value, "after": verified.value})
                        self.log(f"re-judged utility {original_gem} -> {best[1]}: {current.value:,.0f} -> {verified.value:,.0f}")
                        current = verified
                        changed = True
                        continue
                    group.gems, group.label = list(original_gems), original_gem
                    self._set_main_link(skeleton, skeleton.main_link, changed_skill=original_gem)
                    current = honest()
                else:
                    group.gems, group.label = list(original_gems), original_gem
                    self._set_main_link(skeleton, skeleton.main_link, changed_skill=original_gem)
                    current = honest()
            if not changed:
                break
        final = honest()
        self.picks.append(Pick(what="re-judged picks", choice="; ".join(f"{c['what']} {c['was']} -> {c['now']}" for c in changes) or "no change", score=final, seconds=time.perf_counter() - t_all))
        return changes

    # -- uniques -------------------------------------------------------------------

    def _weapon1_type(self) -> str:
        """The equipped main-hand weapon's type by the build's own readback ("" when Weapon 1 is empty)."""

        slots = (self.pob.read_state().get("items_state") or {}).get("slots") or {}
        item = (slots.get("Weapon 1") or {}).get("item") if isinstance(slots, dict) else None
        if not item:
            return ""
        if item.get("type_label"):
            return str(item["type_label"])
        rec = item_bases().get(str(item.get("base_type") or "").lower())
        return str((rec or {}).get("type") or "")

    def _weapon1_is_bow(self) -> bool:
        """Is the currently equipped main-hand weapon a bow (by the build's own readback)?"""

        return self._weapon1_type() == "Bow"

    def _weapon1_is_two_hander(self) -> bool:
        """Is the main-hand weapon a two-hander other than a bow (it allows nothing in Weapon 2, ItemsTab.lua:2475-2481)?"""

        t = self._weapon1_type()
        return t in TWO_HAND_TYPES and t != "Bow"

    def screen_uniques(self, *, slots: Sequence[str] = RARE_SLOTS, max_level: int | None = None, top: int = 5, min_gain: float = 0.03,
                       availability: Sequence[str] | None = None, fixed: Sequence[str] | None = None) -> list[tuple[str, str, Score, float]]:
        """Try every unique whose type fits the slot as an item trial on the current
        build; return (slot, name, score, gain) for those beating the current item by
        min_gain. Only uniques the rails allow (PoB "Source:" availability class and
        level requirement, D31); the caller decides how many uniques the rails allow.
        `fixed` are the slots the request fixed (`forced_slots`): no unique is tried in them (#510)."""

        max_level = max_level or self.rails.unique_max_req_level
        slots = [s for s in slots if s not in (fixed or ())]
        allowed = set(availability if availability is not None else self.rails.unique_availability)
        current = self._score()
        out: list[tuple[str, str, Score, float]] = []
        by_slot: dict[str, list[dict]] = defaultdict(list)
        w1 = self._weapon1_type() if "Weapon 2" in slots else ""  # one PoB read per call, not per record
        for recs in uniques_by_name().values():
            for r in recs:
                if availability is None:
                    if not self.rails.unique_allowed(r):
                        continue
                elif int(r.get("req_level") or 0) > max_level or r.get("availability", "core") not in allowed:
                    continue
                for slot in UNIQUE_TYPE_SLOTS.get(r["type"], ()):
                    if slot in slots and not (slot == "Weapon 2" and r["type"] not in ("Shield", "Quiver")):
                        if slot == "Weapon 2" and ((r["type"] == "Quiver") != (w1 == "Bow") or (w1 in TWO_HAND_TYPES and w1 != "Bow")):
                            continue  # a quiver needs a bow, a shield needs a one-hander (an empty Weapon 1 keeps a shield): PoB's what-if accepts either, the real equip does not
                        by_slot[slot].append(r)
        for slot, recs in by_slot.items():
            trials, names = [], []
            for r in recs:
                try:
                    raw = self.pob.unique_item(r["plain_name"])["raw"]
                except Exception:
                    continue
                trials.append({"item": {"slot": slot, "raw": raw}})
                names.append(r["plain_name"])
            TRACE.count_candidates(trials)
            for name, o in zip(names, self.pob.trial_stats(trials, self.objective.stat_keys, mode="fast")):
                if o.get("ok") and o.get("stats"):
                    s = self.objective.score(o["stats"])
                    gain = (s.value - current.value) / max(1.0, current.value)
                    if s > current and gain >= min_gain:
                        out.append((slot, name, s, gain))
        out.sort(key=lambda x: (x[2].neg_violation, x[2].value), reverse=True)
        return out[:top]

    # -- candidates -----------------------------------------------------------------

    def candidates(self, main_skill: str, *, ascendancy_ids: Sequence[str] | None = None, level: int | None = None, supports: Sequence[str] | None = None,
                   extra_groups: Sequence = (), n_supports: int = 5, points: int = 8) -> list[Skeleton]:
        """One skeleton per ascendancy: bases, ascendancy nodes and (once, shared)
        supports all chosen by PoB on a quick rig. Screening and full optimization
        are the search script's job."""

        level = level or self.rails.level
        ascendancy_ids = normalize_ascendancy_ids(ascendancy_ids)
        out: list[Skeleton] = []
        shared_supports: list[str] | None = list(supports) if supports else None
        for asc in ascendancies().values():
            if ascendancy_ids and asc["ascendancy_id"] not in ascendancy_ids:
                continue
            t0 = time.perf_counter()
            sk = Skeleton(class_name=asc["class_name"], ascendancy=asc["ascendancy_id"], level=level, main_link=[main_skill, *(shared_supports or [])], extra_groups=list(extra_groups))
            sk.cap_links(self.rails)
            sk.apply(self.pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality, main_quality=self.rails.gems.main_quality)
            self.refresh_castability()
            self.screen_bases(sk)
            self.pick_ascendancy_nodes(sk, points=points)
            if shared_supports is None:
                self.pick_supports(sk, n_supports=n_supports)
                shared_supports = list(sk.main_link[1:])
            else:
                sk.main_link = [main_skill, *shared_supports]
                sk.cap_links(self.rails)
            self.log(f"candidate {sk.class_name}/{sk.ascendancy}: {sk.main_link} bases {len(sk.rare_bases)} asc {len(sk.ascendancy_nodes)} ({human_duration(time.perf_counter() - t0)})")
            out.append(sk)
        return out


__all__ = ["SkeletonGenerator", "candidate_bases", "Pick"]
