"""Template-driven deterministic day-1 rare gear (D79).

The template data fixes the shape of every rare. PoB chooses only the open and
bench lines; fixed life, resistance, and movement lines are not allowed to
disappear just because the current objective values another line more highly.
"""

from __future__ import annotations

from junkroan.optimizer.seeds import PURPOSE_TEMPLATE_TIES, PURPOSE_WISHLIST_FILL_SLOT, derive_seed, tie_rank

import itertools
import json
import re
import statistics
import time
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from junkroan.optimizer.anoint_line import apply_anoint
from junkroan.optimizer.gear_interface import GearInterface
from junkroan.optimizer.item_bases import base_record, bases_of_type, drop_level, implicit_of, type_of, without_excluded
from junkroan.optimizer.loot_gear import RARE_SLOT_ORDER, WEAPON_SLOTS, _affix_counts, _mod_families, _rank, ordered_slots, rare_mod_lines, restore_weapon_partner, unforced_forbidden, weapon_all_gems_raw, weapon_line_forbidden
from junkroan.optimizer.objective import Objective, Score, ScoreOrder, accepts_under, better_score, loop_key, score_key
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.red_line_gate import red_lines_blocking
from junkroan.optimizer.trace import TRACE, register_class
from junkroan.pob.mod_families import families_of
from junkroan.pob.session import PobSession
from junkroan.search.forced import affix_template, raw_has_affix, raw_header_ids

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "mechanics" / "day1_gear_templates.json"
RESISTANCE_STATS = ("FireResist", "ColdResist", "LightningResist", "FireResistOverCap", "ColdResistOverCap", "LightningResistOverCap")
RESISTANCE_GROUPS = {"fire": "FireResistance", "cold": "ColdResistance", "lightning": "LightningResistance"}
_RESISTANCE_STAT = {"fire": "FireResist", "cold": "ColdResist", "lightning": "LightningResist"}
_RESISTANCE_OVERCAP = {"fire": "FireResistOverCap", "cold": "ColdResistOverCap", "lightning": "LightningResistOverCap"}
ATTRIBUTE_REQUIREMENTS = {"Str": "ReqStr", "Dex": "ReqDex", "Int": "ReqInt"}
BASE_ATTRIBUTE_REQUIREMENTS = {
    "Str": ("str", "strength"),
    "Dex": ("dex", "dexterity"),
    "Int": ("int", "intelligence"),
}
JEWELLERY_SLOTS = ("Amulet", "Ring 1", "Ring 2", "Belt")
_NUMBER = re.compile(r"\+?\(?(-?\d+(?:\.\d+)?)(?:-(-?\d+(?:\.\d+)?))?\)?%?")
_RANGE = re.compile(r"([+-]?)\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")


def _count_items(slot: str, raws) -> None:
    """Count the item trials this module is about to send as generated (#498); no PoB call."""

    TRACE.count_candidates({"item": {"slot": slot, "raw": raw}} for raw in raws)


def _share_band(share: float, never_below: float, two_lines_below: float) -> str:
    """Share band of an open mod, cut exactly where the filter and the two-line price cut it (#428)."""

    if share < never_below:
        return "mod-share:<0.2%"
    return "mod-share:0.2-1%" if share < two_lines_below else "mod-share:>=1%"


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    kind: str
    group: str | None = None
    tier: int | None = None
    affix_type: str = "either"


@dataclass(frozen=True, slots=True)
class BaseChoice:
    base: str
    payment: BasePayment | None = None


@dataclass(frozen=True, slots=True)
class BasePayment:
    """One attribute line that the base screen has already charged to the item."""

    mod: WishlistMod | None = None
    bench: Mapping[str, object] | None = None

    @property
    def families(self) -> frozenset[str]:
        if self.mod is not None:
            return self.mod.families
        if self.bench is not None:
            return _mod_families(self.bench.get("mod_id"), self.bench.get("group"), self.bench.get("families"))
        return frozenset()


@dataclass(frozen=True, slots=True)
class ResistancePlan:
    assignments: Mapping[str, str]
    totals: Mapping[str, float]
    overcap: Mapping[str, float]
    shortfall: Mapping[str, float]
    extra_assignments: Mapping[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WishlistMod:
    mod_id: str
    affix_type: str
    group: str
    tier: int
    ladder: int
    line: str
    lines: tuple[str, ...] = ()
    families: frozenset[str] = frozenset()
    attribute: bool = False
    share: float = 1.0
    line_cost: int = 1
    gem_level: bool = False

    @property
    def text(self) -> str:
        """Every line of the mod, so a hybrid never reads as a pure one (rule 7).

        "(25-30)% increased Spell Damage / +(x-y) to maximum Mana" printed as
        its first line alone reads like a second pure spell-damage mod.
        """

        return " / ".join(self.lines or (self.line,))

    @property
    def label(self) -> str:
        return f"T{self.tier}/{self.ladder} {self.text}"


@dataclass(slots=True)
class WishlistSlotResult:
    slot: str
    base: str
    ilvl: int
    sockets: str | None = None
    implicit: str = ""
    raw: str = ""
    mod_ids: list[str] = field(default_factory=list)
    affixes: list[WishlistMod] = field(default_factory=list)
    bench_line: str | None = None
    before: Score | None = None
    after: Score | None = None
    rolled: int = 0
    seconds: float = 0.0
    steps: list[str] = field(default_factory=list)
    bases_screened: int = 0
    bases_filled: tuple[str, ...] = ()
    kept_incumbent: bool = False
    shopping: list[dict[str, object]] = field(default_factory=list)
    extra_resistance: str | None = None
    gem_level_trials: list[dict[str, object]] = field(default_factory=list)
    candidate_log: list[dict[str, object]] = field(default_factory=list)  # per flexible line: every candidate PoB judged
    base_log: list[dict[str, object]] = field(default_factory=list)  # the base screen: every base PoB was offered
    bench: Mapping[str, object] | None = None
    bench_attribute: bool = False
    resistance_repair_backup: tuple[str, list[WishlistMod], Mapping[str, object] | None, bool, str | None, list[dict[str, object]], int] | None = None

    @property
    def after_loot(self) -> Score | None:
        return self.after

    @property
    def after_bench(self) -> Score | None:
        return self.after if self.bench_line else None

    @property
    def mod_lines(self) -> str:
        lines = [mod.label for mod in self.affixes]
        if self.bench_line:
            lines.append("{crafted} " + self.bench_line)
        return " / ".join(lines)


@dataclass(slots=True)
class _GearSetSnapshot:
    """One whole gear set the fill held, with the ``Score`` PoB gave it at that moment (#188).

    A fill may change the item of every slot it fills (and, through
    ``restore_weapon_partner``, the paired weapon slot), and it rewrites the
    per-slot record each of those items is shopped from. A set is therefore only
    restorable together with its records and its resistance assignments: after
    ``WishlistGear._restore_gear_set`` both ``current_raw`` and
    ``_results_by_raw`` must describe what is equipped. The records are copied
    because the late repair passes mutate them in place
    (``_replace_with_resistance_crafts``, ``_remove_unneeded_resistance``).
    """

    label: str
    score: Score
    raw_by_slot: dict[str, str]
    results_by_raw: dict[tuple[str, str], WishlistSlotResult]
    resistance_assignments: dict[str, str]
    extra_resistance_assignments: dict[str, str]

    @property
    def log_line(self) -> str:
        return f"{self.label} viol {self.score.violation:.4f} value {self.score.value:,.1f}"


def median_index(ladder_length: int) -> int:
    """The median rank of a whole best-first tier ladder."""

    return max(0, (int(ladder_length) - 1) // 2)


def rolled_line(line: str, range_: float = 0.5) -> str:
    """Render a range at the deterministic 50% roll used by ``craft_rare``."""

    def replace(match: re.Match[str]) -> str:
        low, high = float(match.group(2)), float(match.group(3))
        return f"{match.group(1)}{low + (high - low) * range_:g}"

    return _RANGE.sub(replace, line)


def attribute_grants(lines: Sequence[str], range_: float = 0.5) -> dict[str, float]:
    """Read attribute payments from PoB's own text, for open attribute lines."""

    names = {"strength": ("Str",), "dexterity": ("Dex",), "intelligence": ("Int",), "all attributes": ("Str", "Dex", "Int")}
    out: dict[str, float] = {}
    for line in lines:
        match = re.match(r"^\+?\(?(-?\d+(?:\.\d+)?)(?:-(-?\d+(?:\.\d+)?))?\)?\s+to\s+(.+?)\s*$", str(line).strip(), re.I)
        if not match:
            continue
        low = float(match.group(1))
        high = float(match.group(2)) if match.group(2) is not None else low
        attributes: list[str] = []
        for part in match.group(3).lower().split(" and "):
            values = names.get(part.strip())
            if values is None:
                attributes = []
                break
            attributes.extend(values)
        for stat in attributes:
            out[stat] = out.get(stat, 0.0) + low + (high - low) * range_
    return out


def is_pure_es(stats: Mapping[str, object]) -> bool:
    """CI or an ES pool at least twice the life pool uses the ES template variant."""

    ci = stats.get("ChaosInoculation")
    life = float(stats.get("Life") or 0.0)
    energy_shield = float(stats.get("EnergyShield") or 0.0)
    return bool(ci) or energy_shield >= 2.0 * max(life, 1.0)


def solve_resistances(
    baseline: Mapping[str, object],
    slots: Sequence[tuple[str, Mapping[str, float]]],
    *,
    floor: float | Mapping[str, float] = 75.0,
    extra_slots: Sequence[tuple[str, Mapping[str, float]]] = (),
    max_extra: int = 0,
) -> ResistancePlan:
    """Assign every resistance template line globally, minimizing shortfall then overcap.

    ``slots`` contains the fire/cold/lightning values its fixed tier supplies. The
    exact search has at most three choices per rare slot, so a full nine-rare set
    is only 19,683 combinations and needs no PoB trials.
    """

    elements = tuple(RESISTANCE_GROUPS)
    floors = {
        element: float(floor.get(element, floor.get(_RESISTANCE_STAT[element], floor.get(_RESISTANCE_STAT[element] + "Max", 75.0))))
        if isinstance(floor, Mapping) else float(floor)
        for element in elements
    }
    base = {element: float(baseline.get(_RESISTANCE_STAT[element]) or 0.0) for element in elements}
    if not slots:
        shortfall = {element: max(0.0, floors[element] - base[element]) for element in elements}
        return ResistancePlan({}, base, {element: max(0.0, base[element] - floors[element]) for element in elements}, shortfall)

    choices = [
        tuple(element for element in elements if float(values.get(element) or 0.0) > 0.0) or elements
        for _slot, values in slots
    ]
    best: tuple[tuple[float, float, tuple[str, ...]], tuple[str, ...], dict[str, float]] | None = None
    for assigned in itertools.product(*choices):
        totals = dict(base)
        for element, (_slot, values) in zip(assigned, slots):
            totals[element] += float(values.get(element) or 0.0)
        shortfall = sum(max(0.0, floors[element] - totals[element]) for element in elements)
        overcap = sum(max(0.0, totals[element] - floors[element]) for element in elements)
        candidate = ((shortfall, overcap, assigned), assigned, totals)
        if best is None or candidate[0] < best[0]:
            best = candidate

    assert best is not None
    _key, assigned, totals = best
    # ``floor`` may be a mapping (the build's own elemental maxima, D85); every
    # comparison below reads the per-element value resolved in ``floors``.
    fixed_shortfall = {element: max(0.0, floors[element] - totals[element]) for element in elements}
    extra_assigned: tuple[tuple[str, str], ...] = ()
    if any(fixed_shortfall.values()) and extra_slots and max_extra > 0:
        extra_candidates: list[tuple[str, tuple[str, ...], Mapping[str, float]]] = []
        fixed_by_slot = {slot: element for element, (slot, _values) in zip(assigned, slots)}
        for slot, values in extra_slots:
            choices = tuple(element for element in elements if element != fixed_by_slot.get(slot) and float(values.get(element) or 0.0) > 0.0)
            if choices:
                extra_candidates.append((slot, choices, values))
        best_extra: tuple[tuple[float, int, float, tuple[tuple[str, str], ...]], tuple[tuple[str, str], ...], dict[str, float]] | None = None
        for count in range(1, min(int(max_extra), len(extra_candidates)) + 1):
            for chosen in itertools.combinations(extra_candidates, count):
                for extra_elements in itertools.product(*(choices for _slot, choices, _values in chosen)):
                    candidate_totals = dict(totals)
                    pairs = tuple((slot, element) for (slot, _choices, _values), element in zip(chosen, extra_elements))
                    for (_slot, element), (_name, _choices, values) in zip(pairs, chosen):
                        candidate_totals[element] += float(values.get(element) or 0.0)
                    remaining = sum(max(0.0, floors[element] - candidate_totals[element]) for element in elements)
                    overcap = sum(max(0.0, candidate_totals[element] - floors[element]) for element in elements)
                    key = (remaining, count, overcap, pairs)
                    if best_extra is None or key < best_extra[0]:
                        best_extra = (key, pairs, candidate_totals)
        if best_extra is not None:
            _key, extra_assigned, totals = best_extra
    return ResistancePlan(
        assignments={slot: element for element, (slot, _values) in zip(assigned, slots)},
        totals=totals,
        overcap={element: max(0.0, totals[element] - floors[element]) for element in elements},
        shortfall={element: max(0.0, floors[element] - totals[element]) for element in elements},
        extra_assignments=dict(extra_assigned),
    )


@lru_cache(maxsize=1)
def _templates() -> tuple[dict[str, tuple[TemplateSlot, ...]], dict[str, str]]:
    raw = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    templates = {
        str(name): tuple(
            TemplateSlot(
                kind=str(slot["kind"]),
                group=(str(slot["group"]) if slot.get("group") is not None else None),
                tier=(int(slot["tier"]) if slot.get("tier") is not None else None),
                affix_type=str(slot.get("affix_type") or "either"),
            )
            for slot in slots
        )
        for name, slots in (raw.get("templates") or {}).items()
    }
    return templates, {str(k): str(v) for k, v in (raw.get("by_type") or {}).items()}


def template_for(base: str, slot: str, *, weapon_open_lines: int = 2, quiver_weapon_shape: bool = False) -> tuple[TemplateSlot, ...]:
    """The JSON template for a corpus base, falling back to its equipment slot.

    ``quiver_weapon_shape`` (template v4 requirement 1): a quiver follows the
    weapon rule -- ``weapon_open_lines`` open lines by value plus one craft --
    instead of the armour shape (life + resistance + one open-or-craft line).
    """

    templates, aliases = _templates()
    item_type = type_of(base)
    key = aliases.get(item_type, item_type)
    if quiver_weapon_shape and key == "Quiver":
        key = "weapon"
    if key not in templates:
        slot_types = {
            "Ring 1": "Ring",
            "Ring 2": "Ring",
            "Weapon 1": "weapon",
            "Weapon 2": "Shield",
        }
        key = slot_types.get(slot, slot)
    if key not in templates:
        raise ValueError(f"no day-1 gear template for {base!r} ({item_type or slot})")
    template = templates[key]
    if key == "weapon":
        return (*(TemplateSlot("open") for _ in range(max(0, int(weapon_open_lines)))), TemplateSlot("craft"))
    return template


def _elemental_value(lines: Iterable[str], element: str) -> float:
    """The deterministic 50% roll granted to one elemental resistance."""

    needle = element.lower()
    for line in lines:
        if needle not in str(line).lower():
            continue
        match = _NUMBER.search(str(line))
        if match:
            low = float(match.group(1))
            high = float(match.group(2)) if match.group(2) is not None else low
            return low + (high - low) * 0.5
    return 0.0


def _is_attribute_mod(mod: Mapping[str, object]) -> bool:
    return "attribute" in {str(tag).lower() for tag in (mod.get("mod_tags") or ())}


def _is_gem_level_mod(mod: Mapping[str, object]) -> bool:
    """A gem-level property, read from PoB's own parse rather than from words (D79 rule 5).

    PoB tags every one of them ``gem`` and writes the level in the line itself:
    "+1 to Level of all Spell Skill Gems", "+1 to Level of all Cold Spell Skill
    Gems", "+1 to Level of all Minion Skill Gems", "+2 to Level of Socketed
    Melee Gems". The other ``gem``-tagged mods say nothing about a level
    ("+7% to Quality of Socketed Gems", "Trigger a Socketed Spell ...") and are
    ordinary lines. Checked against PoB's tables on 15 bases: 40 level mods
    match, the 4 other gem-tagged mods do not, and nothing untagged does.
    """

    tags = {str(tag).lower() for tag in (mod.get("mod_tags") or ())}
    text = " ".join(str(line) for line in (mod.get("lines") or mod.get("rolled_lines") or ()))
    return "gem" in tags and bool(re.search(r"\blevel of\b.*\bgems?\b", text, re.IGNORECASE))


_GEM_LEVEL_LINE = re.compile(r"\blevel of\b.*\bgems?\b", re.IGNORECASE)


def _shield_gem_level_class(trial: dict) -> Iterable[str]:
    """`shield-gem-level` for a rare Shield trial carrying a gem-level line (#601; trace counter class)."""

    item = trial.get("item") if isinstance(trial, dict) else None
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, str) or item.get("slot") != "Weapon 2":
        return ()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0].lower() != "rarity: rare" or type_of(lines[2]) != "Shield":
        return ()
    return ("shield-gem-level",) if any(_GEM_LEVEL_LINE.search(ln) for ln in lines[3:]) else ()


register_class(_shield_gem_level_class)

def _shield_gem_level_with_other_class(trial: dict) -> Iterable[str]:
    """`shield-gem-level-with-other` for a rare Shield whose raw carries a gem-level line AND any other mod line (#601: stays 0 by construction)."""

    item = trial.get("item") if isinstance(trial, dict) else None
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, str) or item.get("slot") != "Weapon 2":
        return ()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0].lower() != "rarity: rare" or type_of(lines[2]) != "Shield":
        return ()
    mods = rare_mod_lines(lines)
    if not any(_GEM_LEVEL_LINE.search(ln) for ln in mods):
        return ()
    return ("shield-gem-level-with-other",) if any(not _GEM_LEVEL_LINE.search(ln) for ln in mods) else ()


register_class(_shield_gem_level_with_other_class)


def is_shield_gem_level_with_other(slot: str, raw: str) -> bool:
    """True for a rare Shield raw that carries a gem-level line AND another mod line: the item #601's rule forbids at the PoB boundary."""

    return bool(tuple(_shield_gem_level_with_other_class({"item": {"slot": slot, "raw": raw}})))


_RESISTANCE_NOT_GRANTED = ("penetrat", "enem")  # penetration and enemy reduction are damage, not defence
_RESISTANCE_ELEMENTS = ("fire", "cold", "lightning", "allresist", "elementalresist")


def _is_elemental_resistance_group(group: object) -> bool:
    """A PoB mod group that grants the player fire, cold or lightning resistance.

    Such a group belongs to the global resistance solver and is never an open
    line. Pure chaos resistance stays open, and so does every damage mod that
    merely names an element: the old substring test swallowed
    ``LocalLightningDamage``, ``SpellAddedLightningDamage``,
    ``IncreasedWeaponElementalDamagePercent`` and the damage-over-time
    multipliers, which is why elemental damage was never offered on any item.

    Checked against every mod group PoB offers on 15 bases (explicit and bench):
    the eight granting groups match (Fire/Cold/LightningResistance, the three
    two-element pairs, AllResistances, AllResistancesMinionResistances, the
    three ...AndChaosDamageResistance groups) and
    ``LocalAttackReduceEnemyElementalResistance`` -- penetration -- does not.
    """

    text = str(group).lower().replace("_", "")
    if "resistance" not in text or any(word in text for word in _RESISTANCE_NOT_GRANTED):
        return False
    return any(word in text for word in _RESISTANCE_ELEMENTS)


def _candidate_label(mod: object, craft: Mapping[str, object] | None) -> str:
    """How one offered line reads in the per-line candidate table."""

    if isinstance(mod, WishlistMod):
        return mod.label
    if craft is not None:
        return "{crafted} " + " / ".join(str(line) for line in (craft.get("rolled_lines") or ()))
    return "(nothing)"


def _picked_is_gem_level(entry: Sequence[object]) -> bool:
    """A chosen or offered (mod, craft) pair whose line is a gem-level property."""

    mod, craft = entry[0], entry[1]
    return bool((isinstance(mod, WishlistMod) and mod.gem_level) or (craft is not None and _is_gem_level_mod(craft)))


def _picked_is_two_line(entry: Sequence[object]) -> bool:
    """A chosen or offered (mod, craft) pair whose mod is priced at two template lines."""

    mod = entry[0]
    return isinstance(mod, WishlistMod) and not mod.gem_level and mod.line_cost > 1


_comparable = _rank


def pick_attempt(attempts: Sequence[tuple[Score, Any]], order: ScoreOrder = "floors", tie: Callable[[str], int] | None = None) -> tuple[Score, Any]:
    """The finished item a slot's fill ends on, among its base candidates' `(Score, result)` attempts.

    "floors" (construction, the default) is violation first, then value, then the base name -- the
    rule `fill_slot` always had. "priced" (the improvement loop, D116 / #553) is `objective.loop_key`
    of the Score, then the base name: a candidate that keeps most of its value after the floors it
    misses are charged wins, so a crumb of violation no longer outranks a large loss of value.

    ``tie`` (#619) replaces the base name as the last key by a seeded rank of it, so the seed only
    separates attempts PoB scored the same; None keeps the first listed by name."""

    last = (lambda entry: entry[1].base) if tie is None else (lambda entry: tie(entry[1].base))
    if order == "priced":
        return max(attempts, key=lambda entry: (*loop_key(entry[0]), last(entry)))
    return max(attempts, key=lambda entry: (entry[0].neg_violation, entry[0].value, last(entry)))


RESISTANCE_PLAN_ATTRS = ("_resistance_assignments", "_extra_resistance_assignments", "resistance_plan")  # what a gear move can rewrite (#33)


class WishlistGear(GearInterface):
    """Craft the fixed template shape for every rare slot and retain a later-pass incumbent."""

    tie_seed: int | None = None  # #619: class default, so a bare object.__new__(WishlistGear) in a test reads "no seed"

    def __init__(self, pob: PobSession, objective: Objective, rails: Rails | None = None, *, log: Callable[[str], None] | None = None,
                 pure_es: bool | None = None, uniques: Mapping[str, str] | None = None) -> None:
        self.pob = pob
        self.objective = objective
        self.rails = rails or Rails.load()
        self.log = log or (lambda _line: None)
        self.pure_es = pure_es
        self.uniques = dict(uniques or {})  # slot -> raw, the skeleton's unique gear; its weapon pair is restored after a refill
        self.current_raw: dict[str, str] = {}
        self._whole_ladder_cache: dict[tuple[str, int], dict[tuple[str, str], list[dict]]] = {}
        self._legal_ladder_cache: dict[tuple[str, int], dict[tuple[str, str], list[dict]]] = {}
        self._bench_cache: dict[tuple[str, int], list[dict]] = {}
        self._raw_cache: dict[tuple[object, ...], str | None] = {}
        self.anoint: str | None = None  # the notable an Amulet raw carries as its enchant (#432); set by the pipeline
        self._resistance_assignments: dict[str, str] = {}
        self._extra_resistance_assignments: dict[str, str] = {}
        self._results_by_raw: dict[tuple[str, str], WishlistSlotResult] = {}
        self._last_choice_rows: list[dict[str, object]] = []  # every candidate the last _choose_trial judged
        self.base_screen: dict[str, list[dict[str, object]]] = {}  # slot -> every base the last screen judged
        self.resistance_plan: ResistancePlan | None = None
        self._fill_bases_by_slot: dict[str, str] = {}
        self._filling_slots: frozenset[str] = frozenset()
        self._attribute_capacity_cache: dict[tuple[str, str], tuple[float, float, int, float]] = {}
        self._weapon_base_choices: dict[str, list[BaseChoice]] = {}
        self.weapon_requirement_refills: list[dict[str, object]] = []
        self.tie_seed: int | None = None  # #619: the seed of the slot being filled; None = an exact tie keeps the first listed (and the later base name)
        self.flexible_by_value = False  # set only by the loop's gear move (spec 2026-09-26), never by construction
        self.forced_lines: dict[str, list[str]] = {}  # slot -> mod lines the request forces; each is one of the item's template lines, no pass removes it
        self.flexible_report: dict[str, object] = {}  # template v4: moves tried/kept per kind, seconds (empty when both switches are off)

    def _template_for(self, base: str, slot: str) -> tuple[TemplateSlot, ...]:
        return template_for(
            base, slot,
            weapon_open_lines=self.rails.gear.wishlist.weapon_open_lines,
            quiver_weapon_shape=self.rails.gear.wishlist.quiver_weapon_shape,
        )

    def _whole_ladders(self, base: str, ilvl: int) -> dict[tuple[str, str], list[dict]]:
        key = (base, ilvl)
        if key not in self._whole_ladder_cache:
            rows = self.pob.list_item_mods(base, ilvl=100)["mods"]
            grouped: dict[tuple[str, str], list[dict]] = {}
            for mod in rows:
                grouped.setdefault((str(mod["type"]), str(mod["group"])), []).append(dict(mod))
            self._whole_ladder_cache[key] = {
                group: sorted(ladder, key=lambda mod: (-int(mod.get("level") or 0), str(mod.get("mod_id") or "")))
                for group, ladder in grouped.items()
            }
        return self._whole_ladder_cache[key]

    def ladders(self, base: str, ilvl: int) -> dict[tuple[str, str], list[dict]]:
        key = (base, ilvl)
        if key not in self._legal_ladder_cache:
            legal = self.pob.list_item_mods(base, ilvl=ilvl)["mods"]
            grouped: dict[tuple[str, str], list[dict]] = {}
            for mod in legal:
                grouped.setdefault((str(mod["type"]), str(mod["group"])), []).append(dict(mod))
            self._legal_ladder_cache[key] = {
                group: sorted(ladder, key=lambda mod: (-int(mod.get("level") or 0), str(mod.get("mod_id") or "")))
                for group, ladder in grouped.items()
            }
        return self._legal_ladder_cache[key]

    def bench_rows(self, base: str, ilvl: int) -> list[dict]:
        key = (base, ilvl)
        if key not in self._bench_cache:
            best: dict[tuple[str, str, tuple[str, ...]], dict] = {}
            for row in self.pob.list_bench_mods(base, ilvl=ilvl)["mods"]:
                if not self.rails.bench_allowed(row):  # the recipe's unlock stage (rails gear.bench); before the best-rank pick, so a legal lower rank survives
                    continue
                identity = (str(row.get("type")), str(row.get("group")), tuple(row.get("families") or ()))
                if identity not in best or int(row.get("level") or 0) > int(best[identity].get("level") or 0):
                    best[identity] = dict(row)
            self._bench_cache[key] = sorted(best.values(), key=lambda row: (str(row.get("type")), str(row.get("group")), -int(row.get("level") or 0)))
        return self._bench_cache[key]

    def _mod_at_tier(self, base: str, ilvl: int, group: str, tier: int, *, affix_type: str | None = None) -> WishlistMod | None:
        whole = self._whole_ladders(base, ilvl)
        legal = self.ladders(base, ilvl)
        candidates: list[tuple[int, WishlistMod]] = []
        for (kind, name), full in whole.items():
            if name != group or (affix_type not in (None, "either") and kind != affix_type):
                continue
            legal_ids = {str(mod["mod_id"]) for mod in legal.get((kind, name), ())}
            available = [(rank, mod) for rank, mod in enumerate(full, start=1) if str(mod["mod_id"]) in legal_ids]
            if not available:
                continue
            # Requested whole-ladder rank, clamped to the best rank the current ilvl can roll.
            rank, mod = next((entry for entry in available if entry[0] >= tier), available[0])
            families = _mod_families(mod.get("mod_id"), mod.get("group"))
            lines = tuple(str(line) for line in (mod.get("lines") or ()))
            candidates.append((rank, WishlistMod(
                str(mod["mod_id"]), kind, name, rank, len(full), lines[0] if lines else "",
                lines=lines, families=families, attribute=_is_attribute_mod(mod),
            )))
        return min(candidates, key=lambda entry: (entry[0], entry[1].mod_id))[1] if candidates else None

    def _refuses(self, slot: str | None, lines: Iterable[object]) -> bool:
        """#1152: whether ``slot`` is a weapon slot and any of ``lines`` is a line it never carries (rails ``gear.weapon_forbidden_lines``); only the text a forced line of the slot is itself is exempt."""

        forbidden = unforced_forbidden(self.rails.gear.weapon_forbidden_lines, self.forced_lines.get(slot, ()))
        if slot not in WEAPON_SLOTS or not forbidden:
            return False
        return any(weapon_line_forbidden(str(line), forbidden) for line in lines)

    def _forbids_item(self, slot: str, raw: str) -> bool:
        """#1152: whether ``raw`` is a rare weapon of ``slot`` that already carries a line the slot never carries (a forced line's own text excepted)."""

        return weapon_all_gems_raw(slot, raw, unforced_forbidden(self.rails.gear.weapon_forbidden_lines, self.forced_lines.get(slot, ())))

    def _median_mods(self, base: str, ilvl: int, *, affix_type: str = "either", tier_position: float | None = None, slot: str | None = None) -> list[WishlistMod]:
        whole = self._whole_ladders(base, ilvl)
        legal = self.ladders(base, ilvl)
        total_weight = {
            kind: sum(max(0, int(mod.get("weight") or 0)) for ladder in legal.values() for mod in ladder if str(mod.get("type")) == kind)
            for kind in ("Prefix", "Suffix")
        }
        out: list[WishlistMod] = []
        for (kind, group), full in whole.items():
            if affix_type not in ("either", kind):
                continue
            legal_ids = {str(mod["mod_id"]) for mod in legal.get((kind, group), ())}
            available = [(rank, mod) for rank, mod in enumerate(full, start=1) if str(mod["mod_id"]) in legal_ids]
            if not available:
                continue
            # ``0.40`` names the legacy lower-middle policy in the rails. Keep it
            # exact for every ladder (including a two-tier group); any measurement
            # override uses the relative-position rule below.
            if tier_position is None or len(full) == 1 or abs(float(tier_position) - 0.40) < 1e-12:
                desired = median_index(len(full)) + 1
                rank, mod = next((entry for entry in available if entry[0] >= desired), available[0])
            else:
                position = min(1.0, max(0.0, float(tier_position)))
                rank, mod = min(
                    available,
                    key=lambda entry: (
                        round(abs((entry[0] - 1) / (len(full) - 1) - position), 9),
                        entry[0],
                    ),
                )
            # A template accepts this whole-ladder tier and every better tier legal
            # at the requested item level. Price that group, not one chosen tier.
            share = sum(max(0, int(candidate.get("weight") or 0)) for candidate_rank, candidate in available if candidate_rank <= rank) / max(1, total_weight[kind])
            wl = self.rails.gear.wishlist
            if share < wl.open_mod_never_below_share:
                TRACE.add_generated([_share_band(share, wl.open_mod_never_below_share, wl.open_mod_two_lines_below_share)])
                self.log(
                    f"open candidate blocked: {str((mod.get('lines') or [''])[0])} group share {share:.2%} "
                    f"< {self.rails.gear.wishlist.open_mod_never_below_share:.2%}"
                )
                continue
            families = _mod_families(mod.get("mod_id"), mod.get("group"))
            lines = tuple(str(line) for line in (mod.get("lines") or ()))
            if self._refuses(slot, lines):
                continue
            # Rule 5 (rulebook g-rarity): an open mod whose group share is in
            # [open_mod_never_below_share, open_mod_two_lines_below_share) occupies
            # TWO template lines; everything above costs one. A gem-level property
            # is priced by measurement instead (it takes the item's whole open budget).
            gem_level = _is_gem_level_mod(mod)
            line_cost = 2 if (not gem_level and share < self.rails.gear.wishlist.open_mod_two_lines_below_share) else 1
            out.append(WishlistMod(
                str(mod["mod_id"]), kind, group, rank, len(full), lines[0] if lines else "",
                lines=lines, families=families, attribute=_is_attribute_mod(mod), share=share,
                line_cost=line_cost, gem_level=gem_level,
            ))
        return sorted(out, key=lambda mod: (mod.group, mod.affix_type, mod.tier, mod.mod_id))

    def _attribute_mods(self, base: str, ilvl: int) -> list[WishlistMod]:
        """All legal attribute lines, ordered by the smallest whole-ladder tier."""

        out: list[WishlistMod] = []
        for (kind, group), ladder in self._whole_ladders(base, ilvl).items():
            if kind not in {"Prefix", "Suffix"}:
                continue
            legal_ids = {str(mod["mod_id"]) for mod in self.ladders(base, ilvl).get((kind, group), ())}
            for rank, mod in enumerate(ladder, start=1):
                if str(mod.get("mod_id")) not in legal_ids or not _is_attribute_mod(mod):
                    continue
                lines = tuple(str(line) for line in (mod.get("lines") or ()))
                out.append(WishlistMod(
                    str(mod["mod_id"]), kind, group, rank, len(ladder),
                    lines[0] if lines else "", lines=lines,
                    families=_mod_families(mod.get("mod_id"), mod.get("group")), attribute=True,
                ))
        return sorted(out, key=lambda mod: (mod.tier, mod.group, mod.mod_id))

    @staticmethod
    def _affix_room(affixes: Sequence[WishlistMod], bench: Mapping[str, object] | None) -> tuple[int, int]:
        prefixes = sum(mod.affix_type == "Prefix" for mod in affixes) + int(bench is not None and bench.get("type") == "Prefix")
        suffixes = sum(mod.affix_type == "Suffix" for mod in affixes) + int(bench is not None and bench.get("type") == "Suffix")
        return prefixes, suffixes

    @staticmethod
    def _used_families(affixes: Sequence[WishlistMod], bench: Mapping[str, object] | None) -> set[str]:
        used = {family for mod in affixes for family in mod.families}
        if bench is not None:
            used |= set(_mod_families(bench.get("mod_id"), bench.get("group"), bench.get("families")))
        return used

    def _raw(self, base: str, ilvl: int, affixes: Sequence[WishlistMod], bench: Mapping[str, object] | None, sockets: str | None) -> str | None:
        key = (base, ilvl, sockets, tuple(mod.mod_id for mod in affixes), tuple(bench.get("rolled_lines") or ()) if bench else ())
        if key not in self._raw_cache:
            crafted = self.pob.craft_rare(
                base,
                prefixes=[{"mod_id": mod.mod_id, "range": 0.5} for mod in affixes if mod.affix_type == "Prefix"],
                suffixes=[{"mod_id": mod.mod_id, "range": 0.5} for mod in affixes if mod.affix_type == "Suffix"],
                ilvl=ilvl,
                quality=self.rails.gear.quality,
                sockets=sockets,
            )
            # a marked red line no longer drops the item (#1124); no lane is known here: marked on either lane passes
            raw = None if crafted.get("problems") or red_lines_blocking(crafted.get("unsupported_lines") or ()) else str(crafted["raw"])
            if raw and bench is not None:
                raw += "\n" + "\n".join("{crafted}" + str(line) for line in (bench.get("rolled_lines") or ()))
            self._raw_cache[key] = raw
        raw = self._raw_cache[key]
        return apply_anoint(raw, self.anoint) if raw else raw  # only an anointable amulet base changes

    def _bench_candidates(self, base: str, ilvl: int, affixes: Sequence[WishlistMod], *, affix_type: str = "either", reserve: str | None = None,
                            allow_resistance: bool = True, attribute_slots_used: int = 0,
                            allow_gem_level: bool = False, allow_attributes: bool = True, slot: str | None = None) -> list[dict]:
        prefixes, suffixes = self._affix_room(affixes, None)
        used = self._used_families(affixes, None)
        attributes = sum(mod.attribute for mod in affixes)
        out = []
        for row in self.bench_rows(base, ilvl):
            kind = str(row.get("type"))
            if affix_type not in ("either", kind) or (kind == "Prefix" and prefixes >= self.rails.gear.max_prefixes) or (kind == "Suffix" and suffixes >= self.rails.gear.max_suffixes):
                continue
            if self._refuses(slot, [*(row.get("lines") or ()), *(row.get("rolled_lines") or ())]):
                continue
            if _is_gem_level_mod(row) and not allow_gem_level:
                # Rule 5: a gem-level craft takes the item's WHOLE open budget, so
                # it is only a candidate while no open line has been spent yet.
                continue
            if not allow_resistance and _is_elemental_resistance_group(row.get("group")):
                continue
            if _mod_families(row.get("mod_id"), row.get("group"), row.get("families")) & used:
                continue
            if _is_attribute_mod(row) and (not allow_attributes or attributes >= 1 or attributes + attribute_slots_used >= self.rails.gear.wishlist.attribute_affixes_max):
                continue
            if reserve is not None:
                projected = [*affixes]
                projected_families = used | set(_mod_families(row.get("mod_id"), row.get("group"), row.get("families")))
                if not any(
                    mod.affix_type == reserve
                    and not (mod.families & projected_families)
                    and (mod.affix_type != "Prefix" or prefixes + int(kind == "Prefix") < self.rails.gear.max_prefixes)
                    and (mod.affix_type != "Suffix" or suffixes + int(kind == "Suffix") < self.rails.gear.max_suffixes)
                    for mod in self._median_mods(base, ilvl, affix_type=reserve, slot=slot)
                ):
                    continue
            out.append(row)
        return out

    @staticmethod
    def _flexible(line: TemplateSlot) -> bool:
        return line.kind in {"open", "open_or_craft", "craft"}

    def _buys_value(self, base: str, slot: str) -> bool:
        """A weapon's lines buy the objective's value (rule 2); every other slot buys floors.

        The discriminator is the template the base actually has, not the slot
        name: a shield sits in ``Weapon 2`` and is an armour piece with a fixed
        life line, a fixed resistance and one open-or-craft line. Reads
        ``self._template_for`` (not the bare module function) so a quiver under
        ``quiver_weapon_shape`` is recognised as a value-buying weapon shape too.
        """

        return any(line.kind == "open" for line in self._template_for(base, slot))

    def _gem_takes_whole_item(self, base: str, slot: str) -> bool:
        """#601: on a shield (``Weapon 2`` with an armour-shaped template) a gem-level line takes the whole item.

        A weapon's template is all open lines, so its gem line already leaves no
        room (Rule 5); a shield's template also carries a fixed Life and a fixed
        resistance line, which the gem line displaces too.
        """

        return slot == "Weapon 2" and not self._buys_value(base, slot)

    @staticmethod
    def _violation_removed(current: Mapping[str, float], trial: Mapping[str, float]) -> float:
        """How much relative violation a candidate removes, over the union of both keys.

        ``Objective.violations`` only names constraints that are still missed, so
        a floor a candidate repairs outright disappears from ``trial`` and would
        otherwise count as nothing removed.
        """

        return sum(
            float(current.get(key, 0.0)) - float(trial.get(key, 0.0))
            for key in set(current) | set(trial)
        )

    def _tie(self, label: str) -> int:
        """The seeded priority of one candidate that PoB scored like another (0 for all while no seed is set)."""

        return 0 if self.tie_seed is None else tie_rank(self.tie_seed, PURPOSE_TEMPLATE_TIES, label)

    def _choose_trial(
        self,
        slot: str,
        base: str,
        ilvl: int,
        affixes: Sequence[WishlistMod],
        bench: Mapping[str, object] | None,
        candidates: Sequence[tuple[WishlistMod | None, Mapping[str, object] | None]],
        *,
        sockets: str | None,
        buys_value: bool | None = None,
        order: ScoreOrder = "floors",
        baseline_stats: Mapping[str, object] | None = None,
    ) -> tuple[WishlistMod | None, Mapping[str, object] | None, str, Score] | None:
        """The best candidate by PoB's trial; ``baseline_stats`` stands in for the equipped item as "the item as it stands" (#601: a whole-item gem shield is judged against the bare shield)."""

        self._last_choice_rows = []
        trials: list[tuple[WishlistMod | None, Mapping[str, object] | None, str]] = []
        for mod, craft in candidates:
            if self._refuses(slot, [*(mod.lines if mod is not None else ()), *((craft or {}).get("lines") or ()), *((craft or {}).get("rolled_lines") or ())]):
                self._last_choice_rows.append({"candidate": _candidate_label(mod, craft), "taken": False,
                                               "reason": "refused: a weapon never carries the all-gems line (#1152)"})
                continue
            trial_affixes = [*affixes, *([mod] if mod is not None else [])]
            trial_bench = craft if craft is not None else bench
            raw = self._raw(base, ilvl, trial_affixes, trial_bench, sockets)
            if self._unsendable(slot, base, raw):
                self._last_choice_rows.append({"candidate": _candidate_label(mod, craft), "taken": False,
                                               "reason": "refused: drops a line the request forces"})
            elif raw is not None:
                trials.append((mod, craft, raw))
            else:
                self._last_choice_rows.append({"candidate": _candidate_label(mod, craft), "taken": False,
                                               "reason": "PoB cannot craft this line beside the others"})
        if not trials:
            return None
        _count_items(slot, [raw for _mod, _craft, raw in trials])
        wl = self.rails.gear.wishlist
        bands = [_share_band(m.share, wl.open_mod_never_below_share, wl.open_mod_two_lines_below_share) for m, _c, _r in trials if m is not None]
        TRACE.add_generated(bands)
        TRACE.add_evaluated(bands)
        outcomes = self.pob.trial_stats([{"item": {"slot": slot, "raw": raw}} for _mod, _craft, raw in trials], self.objective.stat_keys, mode="fast")
        best: tuple[tuple[float, float, int], WishlistMod | None, Mapping[str, object] | None, str, Score] | None = None
        best_row: dict[str, object] = {}
        current_stats = baseline_stats if baseline_stats is not None else self.pob.stats(self.objective.stat_keys)
        current = self.objective.score(current_stats)
        current_violations = self.objective.violations(current_stats)
        value_first = (self._buys_value(base, slot) or self.flexible_by_value) if buys_value is None else buys_value
        for (mod, craft, raw), outcome in zip(trials, outcomes):
            row: dict[str, object] = {"candidate": _candidate_label(mod, craft), "before": current.value,
                                      "before_violation": current.violation, "taken": False}
            self._last_choice_rows.append(row)
            if not outcome.get("ok") or not outcome.get("stats"):
                row["reason"] = "PoB returned no stats"
                continue
            score = self.objective.score(outcome["stats"])
            violations = self.objective.violations(outcome["stats"])
            row.update({"after": score.value, "after_violation": score.violation})
            if value_first:
                # Rule 2: a weapon line buys DPS. A candidate that makes any floor
                # worse is refused outright; among the rest the best value wins and
                # violation only breaks a tie. A line PoB measures at +0 is never a
                # purchase here -- an attribute requirement is paid under rule 4.
                worse = [key for key, value in violations.items() if value > current_violations.get(key, 0.0) + 1e-9]
                if worse:
                    row["reason"] = "refused: worsens " + ", ".join(sorted(worse))
                    continue
                if score.value <= current.value + 1e-9:
                    row["reason"] = "refused: +0 value on a weapon line"
                    continue
                row["reason"] = "value candidate"
                candidate = ((score.value, score.neg_violation, self._tie(_candidate_label(mod, craft))), mod, craft, raw, score)
            else:
                # Rule 3: armour and jewellery open-or-craft lines buy floors first,
                # but a line that removes almost no violation and adds no value is
                # not a purchase -- leave it free rather than buy 0.0016. The 0.01
                # is there against noise, and a line that ends the build's WHOLE
                # violation is not noise (#174): it is bought whatever its size.
                removed = self._violation_removed(current_violations, violations)
                row["violation_removed"] = removed
                if not accepts_under(order)(score, current):
                    row["reason"] = "refused: not better than the item as it stands"
                    continue
                if score.value <= current.value + 1e-9 and removed < 0.01 and not score.feasible:
                    row["reason"] = f"refused: removes only {removed:.4f} of violation at +0 value"
                    continue
                row["reason"] = "violation-first candidate"
                candidate = ((*_rank(current, score, order=order), self._tie(_candidate_label(mod, craft))), mod, craft, raw, score)
            if best is None or candidate[0] > best[0]:
                best = candidate
                best_row = row
        if best is None:
            return None
        best_row["taken"] = True
        best_row["reason"] = "TAKEN (" + str(best_row["reason"]) + ")"
        return best[1:]

    def _choose_gem_shield(
        self,
        slot: str,
        base: str,
        ilvl: int,
        candidates: Sequence[tuple[WishlistMod | None, Mapping[str, object] | None]],
        *,
        sockets: str | None,
        order: ScoreOrder = "floors",
    ) -> tuple[WishlistMod | None, Mapping[str, object] | None, str, Score] | None:
        """#601: the best gem-level line for a shield, each tried ALONE on the shield (never beside Life or a resistance line).

        Judged against the bare shield, the same baseline the gem-only side of
        ``_gem_beats_ordinary_fill`` is built on.
        """

        bare = self._raw(base, ilvl, [], None, sockets)
        if bare is None:
            return None
        outcome = self.pob.trial_stats([{"item": {"slot": slot, "raw": bare}}], self.objective.stat_keys, mode="fast")[0]
        if not outcome.get("ok") or not outcome.get("stats"):
            return None
        return self._choose_trial(slot, base, ilvl, [], None, candidates, sockets=sockets, buys_value=False, order=order,
                                  baseline_stats=outcome["stats"])

    def _open_candidates(
        self,
        base: str,
        ilvl: int,
        line: TemplateSlot,
        affixes: Sequence[WishlistMod],
        bench: Mapping[str, object] | None,
        *,
        reserve: str | None,
        pure_es: bool,
        bench_allowed: bool,
        payment_budget_used: int,
        allow_gem_level: bool,
        allow_attributes: bool = True,
        tier_position: float | None = None,
        flexible_left: int | None = None,
        slot: str | None = None,
    ) -> list[tuple[WishlistMod | None, Mapping[str, object] | None]]:
        """Every ordinary open mod and bench craft one flexible line may take.

        One definition, used by the template pass and by the gem-level
        comparison, so "the best filling of the same lines with ordinary mods"
        really is the filling the template would have produced.
        """

        candidates: list[tuple[WishlistMod | None, Mapping[str, object] | None]] = []
        prefixes, suffixes = self._affix_room(affixes, bench)
        used = self._used_families(affixes, bench)
        attributes = sum(mod.attribute for mod in affixes) + int(bench is not None and _is_attribute_mod(bench))
        if line.kind != "craft":
            for mod in self._median_mods(
                base,
                ilvl,
                affix_type=line.affix_type,
                tier_position=tier_position,
                slot=slot,
            ):
                if mod.gem_level and not allow_gem_level:
                    continue
                if flexible_left is not None and not mod.gem_level and mod.line_cost > flexible_left:
                    continue
                if pure_es and mod.group == "IncreasedLife":
                    continue
                if _is_elemental_resistance_group(mod.group):
                    continue
                if mod.families & used or (mod.affix_type == "Prefix" and prefixes >= self.rails.gear.max_prefixes) or (mod.affix_type == "Suffix" and suffixes >= self.rails.gear.max_suffixes):
                    continue
                # Rule 4: one attribute affix per ITEM, and at most
                # attribute_affixes_max items across the set carry one.
                if mod.attribute and (not allow_attributes or attributes >= 1 or payment_budget_used >= self.rails.gear.wishlist.attribute_affixes_max):
                    continue
                candidates.append((mod, None))
        if bench_allowed and self.rails.gear.wishlist.bench_crafts and line.kind in {"craft", "open_or_craft"} and bench is None:
            candidates.extend((None, row) for row in self._bench_candidates(
                base, ilvl, affixes, affix_type=line.affix_type, reserve=reserve,
                # Elemental repair happens after every fixed line and extra
                # resistance is installed, so an early item cannot waste its
                # lone flexible line on a deficit later fixed lines would solve.
                allow_resistance=False,
                attribute_slots_used=payment_budget_used,
                allow_gem_level=allow_gem_level,
                allow_attributes=allow_attributes,
                slot=slot,
            ))
        return candidates

    def _weapon_open_tier_position(self, template: Sequence[TemplateSlot], index: int) -> float:
        """The census position for this weapon's first, second, or later open line."""

        positions = self.rails.gear.wishlist.weapon_open_tier_positions
        if not positions:
            return 0.0
        rank = sum(line.kind == "open" for line in template[:index])
        return positions[min(rank, len(positions) - 1)]

    @staticmethod
    def _reserve_for(template: Sequence[TemplateSlot], index: int) -> str | None:
        """The affix type a following craft line still needs kept free."""

        following = template[index + 1] if index + 1 < len(template) else None
        return following.affix_type if following is not None and following.kind == "craft" else None

    def _gem_beats_ordinary_fill(
        self,
        slot: str,
        base: str,
        ilvl: int,
        affixes: Sequence[WishlistMod],
        bench: Mapping[str, object] | None,
        selected: WishlistMod | Mapping[str, object],
        template: Sequence[TemplateSlot],
        index: int,
        *,
        sockets: str | None,
        pure_es: bool,
        bench_allowed: bool,
        payment_budget_used: int,
        allow_attributes: bool,
        span: int | None = None,
        order: ScoreOrder = "floors",
        whole_item: bool = False,
    ) -> tuple[bool, list[dict[str, object]]]:
        """Rule 5: a gem-level property is kept only when it beats ordinary filling.

        It takes the item's whole open budget, so it is measured against the
        best the template could do with ordinary mods on exactly the same lines
        -- filled line by line, the way the template fills them. Returns the
        verdict and the rows the reports print. ``whole_item`` (a rare Shield, #601):
        the gem line takes the WHOLE item, so the gem side is the shield with that
        one line and none of ``affixes``, while the ordinary side keeps them (the
        whole ordinary shield, fixed lines included). ``span`` limits the compared
        ordinary filling to that many flexible lines (a two-line mod is measured
        against the best ordinary pair, not the whole item); ordinary filling is
        always one-line mods.
        """

        gem_mod = selected if isinstance(selected, WishlistMod) else None
        gem_raw = self._raw(base, ilvl, [*([] if whole_item else affixes), *([gem_mod] if gem_mod is not None else [])],
                            selected if gem_mod is None else (None if whole_item else bench), sockets)
        if gem_raw is None or self._unsendable(slot, base, gem_raw):
            return False, []
        _count_items(slot, [gem_raw])
        outcome = self.pob.trial_stats([{"item": {"slot": slot, "raw": gem_raw}}], self.objective.stat_keys, mode="fast")[0]
        if not outcome.get("ok") or not outcome.get("stats"):
            return False, []
        gem_score = self.objective.score(outcome["stats"])
        trial_affixes = list(affixes)
        trial_bench = bench
        ordinary: Score | None = None
        rows: list[dict[str, object]] = []
        filled = 0
        for offset in range(index, len(template)):
            if not self._flexible(template[offset]):
                continue
            if span is not None and filled >= span:
                break
            filled += 1
            pool = self._open_candidates(
                base, ilvl, template[offset], trial_affixes, trial_bench,
                reserve=self._reserve_for(template, offset), pure_es=pure_es,
                bench_allowed=bench_allowed, payment_budget_used=payment_budget_used,
                allow_gem_level=False,
                allow_attributes=allow_attributes,
                tier_position=(self._weapon_open_tier_position(template, offset) if template[offset].kind == "open" else None),
                flexible_left=1,
                slot=slot,
            )
            picked = self._choose_trial(slot, base, ilvl, trial_affixes, trial_bench, pool, sockets=sockets, order=order)
            if picked is None:
                break
            mod, craft, _raw, score = picked
            if mod is not None:
                trial_affixes.append(mod)
            if craft is not None:
                trial_bench = craft
            ordinary = score
            rows.append({"line": mod.label if mod is not None else "{crafted} " + " / ".join(str(v) for v in (craft or {}).get("rolled_lines") or ()),
                         "value": score.value})
        keep = ordinary is None or accepts_under(order)(gem_score, ordinary)
        rows.insert(0, {"line": gem_mod.label if gem_mod is not None else "{crafted} " + " / ".join(str(v) for v in (selected or {}).get("rolled_lines") or ()),
                        "value": gem_score.value, "gem_level": span is None, "kept": keep})
        return keep, rows

    def _fixed_es_mod(self, base: str, ilvl: int, tier: int) -> WishlistMod | None:
        groups = sorted({group for (_kind, group), ladder in self._whole_ladders(base, ilvl).items() if any("energy shield" in " ".join(str(line).lower() for line in mod.get("lines") or ()) for mod in ladder)})
        ranked = sorted(groups, key=lambda group: (group not in {"IncreasedEnergyShield", "LocalIncreasedEnergyShield"}, group))
        return next((self._mod_at_tier(base, ilvl, group, tier) for group in ranked if self._mod_at_tier(base, ilvl, group, tier) is not None), None)

    def _resistance_mod(self, base: str, ilvl: int, element: str, tier: int) -> WishlistMod | None:
        return self._mod_at_tier(base, ilvl, RESISTANCE_GROUPS[element], tier)

    def _resistance_values(self, base: str, ilvl: int, tier: int) -> dict[str, float]:
        return {
            element: _elemental_value((mod.line,), element) if (mod := self._resistance_mod(base, ilvl, element, tier)) is not None else 0.0
            for element in RESISTANCE_GROUPS
        }

    def _all_resistance_values(self, base: str, ilvl: int) -> dict[str, float]:
        """The extra line is always the amended template's T3 resistance."""

        return self._resistance_values(base, ilvl, 3)

    @staticmethod
    def _implicit_resistances(base: str) -> dict[str, float]:
        implicit = implicit_of(base)
        all_elemental = _elemental_value((implicit,), "all elemental") if "all elemental resistances" in implicit.lower() else 0.0
        return {element: _elemental_value((implicit,), element) or all_elemental for element in RESISTANCE_GROUPS}

    def _resistance_baseline(self) -> dict[str, float]:
        """PoB's uncapped elemental totals for a solver decision.

        ``FireResist`` and peers are display values capped at the maximum. The
        matching ``*ResistOverCap`` readback carries the surplus the solver must
        retain when it minimizes overcap.
        """

        readback = self.pob.stats(RESISTANCE_STATS)
        return {
            _RESISTANCE_STAT[element]: float(readback.get(_RESISTANCE_STAT[element]) or 0.0)
            + max(0.0, float(readback.get(_RESISTANCE_OVERCAP[element]) or 0.0))
            for element in RESISTANCE_GROUPS
        }

    def _resistance_floors(self) -> dict[str, float]:
        maxima = self.pob.stats(("FireResistMax", "ColdResistMax", "LightningResistMax"))
        return {
            element: float(value) if isinstance(value := maxima.get(_RESISTANCE_STAT[element] + "Max"), (int, float))
            else self.rails.elemental_resist_floor
            for element in RESISTANCE_GROUPS
        }

    def _attribute_lines_used(self, *, excluding: str | None = None) -> int:
        """How many ITEMS of the set already carry an attribute affix (D79 rule 4).

        The budget is a count of items, not of affixes: one item may carry at
        most one attribute affix or craft anyway (D73), and the rail is the 32
        authors' median number of rares that pay an attribute. Results are
        retained by their raw item text, so a second template pass counts the
        item it will replace only until that slot is excluded.
        """

        total = 0
        for slot, raw in self.current_raw.items():
            if slot == excluding:
                continue
            prior = self._results_by_raw.get((slot, raw))
            if prior is None:
                continue
            total += int(any(mod.attribute for mod in prior.affixes) or prior.bench_attribute)
        return total

    def _resistance_for_slot(self, slot: str, base: str, baseline: Mapping[str, float]) -> str | None:
        resistance = next((line for line in self._template_for(base, slot) if line.kind == "resistance"), None)
        if resistance is None:
            return None
        totals = dict(baseline)
        for element, value in self._implicit_resistances(base).items():
            totals[_RESISTANCE_STAT[element]] += value
        plan = solve_resistances(
            totals,
            [(slot, self._resistance_values(base, self.rails.gear.wishlist.item_level_for(slot), int(resistance.tier or 1)))],
            floor=self._resistance_floors(),
        )
        return plan.assignments.get(slot)

    def _rank_bases(self, slot: str, base: str, ilvl: int, sockets: str | None, *, bench_allowed: bool = True) -> list[BaseChoice]:
        """Rank bare bases, paying only an attribute requirement a later open line can carry.

        A heavy base is not discarded just because its bare requirement breaks
        ``Str/Dex/Int >= Req*``. It is re-trialled with one median, legal
        attribute line, exactly the D73 base screen. That line is not an extra
        affix: the finished template must choose it in its own open/craft line.
        """

        if self._buys_value(base, slot):
            return self._rank_weapon_bases(slot, base, ilvl, sockets)

        candidates = self.base_candidates(base)
        pins = {name: self._forced_pins(slot, name, ilvl) for name in candidates}
        raws = [(name, self._raw(name, ilvl, pins[name], None, sockets)) for name in candidates if pins[name] is not None]
        craftable = [(name, raw) for name, raw in raws if raw and not self._forced_lacking(slot, raw)]
        if not craftable:
            return [BaseChoice(base)]
        _count_items(slot, [raw for _name, raw in craftable])
        outcomes = self.pob.trial_stats([{"item": {"slot": slot, "raw": raw}} for _name, raw in craftable], self.objective.stat_keys, mode="fast")
        empty_violations = self.objective.violations(self.pob.stats(self.objective.stat_keys))
        attribute_violations = {f"{stat}>={requirement}" for stat, requirement in ATTRIBUTE_REQUIREMENTS.items()}
        scored: list[tuple[str, Score, BasePayment | None]] = []
        payments: list[tuple[str, BasePayment, frozenset[str]]] = []
        unpaid_values: list[float] = []  # bases that owe no attribute payment at all (rule 4)
        attribute_room = self._attribute_lines_used(excluding=slot) < self.rails.gear.wishlist.attribute_affixes_max
        for (name, _raw), outcome in zip(craftable, outcomes):
            if outcome.get("ok") and outcome.get("stats"):
                score = self.objective.score(outcome["stats"])
                scored.append((name, score, None))
                # The payment may only occupy an open/craft template line. Boots
                # have no such line, so an attribute-affordable base is not a
                # candidate there unless its implicit already pays the cost.
                if not any(line.kind in {"open", "open_or_craft", "craft"} for line in self._template_for(name, slot)):
                    continue
                violated = self.objective.violations(outcome["stats"])
                worsened = {key for key, value in violated.items() if value > empty_violations.get(key, 0.0) + 1e-9}
                if worsened - attribute_violations:
                    continue
                required = frozenset(worsened & attribute_violations)
                if not required:
                    unpaid_values.append(score.value)
                if required and attribute_room:
                    if any(line.kind in {"open", "open_or_craft"} for line in self._template_for(name, slot)):
                        payments.extend((name, BasePayment(mod=mod), required) for mod in self._attribute_mods(name, ilvl))
                    if bench_allowed and self.rails.gear.wishlist.bench_crafts and any(line.kind in {"open_or_craft", "craft"} for line in self._template_for(name, slot)):
                        payments.extend((name, BasePayment(bench=row), required) for row in self.bench_rows(name, ilvl) if _is_attribute_mod(row))
        if payments:
            payment_trials = []
            for name, payment, required in payments:
                raw = self._raw(name, ilvl, [*(pins[name] or []), *([payment.mod] if payment.mod is not None else [])], payment.bench, sockets)
                if raw is not None and not self._forced_lacking(slot, raw):
                    payment_trials.append((name, payment, required, raw))
            _count_items(slot, [raw for _name, _payment, _required, raw in payment_trials])
            payment_outcomes = self.pob.trial_stats([{"item": {"slot": slot, "raw": raw}} for _name, _payment, _required, raw in payment_trials], self.objective.stat_keys, mode="fast")
            for (name, payment, required, _raw), outcome in zip(payment_trials, payment_outcomes):
                if outcome.get("ok") and outcome.get("stats"):
                    remaining = self.objective.violations(outcome["stats"])
                    if any(remaining.get(key, 0.0) > empty_violations.get(key, 0.0) + 1e-9 for key in required):
                        continue
                    score = self.objective.score(outcome["stats"])
                    scored.append((name, score, payment))
        offered = list(scored)
        scored = self._drop_weapon_payments_with_a_free_alternative(slot, base, scored, unpaid_values)
        ranked = sorted(
            scored,
            key=lambda entry: (-entry[1].neg_violation, -entry[1].value, int(entry[2] is not None), 0 if entry[0] == base else 1, entry[0]),
        )
        limit = max(1, self.rails.gear.wishlist.base_candidates)
        chosen = ranked[:limit]
        # Attribute budgets are set-wide. A paid base must therefore compete with
        # an uncharged finished item even if the bare base screen ranked the paid
        # version in every initial position.
        uncharged = next((entry for entry in ranked if entry[2] is None), None)
        if uncharged is not None and all((entry[0], entry[2]) != (uncharged[0], uncharged[2]) for entry in chosen):
            chosen[-1] = uncharged
        self.base_screen[slot] = self._base_screen_rows(candidates, craftable, offered, scored, chosen)
        return [BaseChoice(name, payment) for name, _score, payment in chosen] or [BaseChoice(base)]

    @staticmethod
    def _base_attribute_requirements(base: str) -> dict[str, float]:
        requirements = dict((base_record(base) or {}).get("requirements") or {})
        return {
            stat: float(next((requirements[key] for key in names if isinstance(requirements.get(key), (int, float))), 0.0))
            for stat, names in BASE_ATTRIBUTE_REQUIREMENTS.items()
        }

    def _score_without_own_base_requirements(self, stats: Mapping[str, object], base: str, baseline: Mapping[str, object]) -> Score:
        """Score a bare weapon without charging the requirement it alone introduces.

        PoB combines a base and gem requirement in one ``Req*`` readback. The
        empty-slot readback is the requirement from every other source, which
        remains a real violation; only the candidate base's increase is ignored.
        """

        violations = self.objective.violations(stats)
        for stat, requirement in self._base_attribute_requirements(base).items():
            req_stat = ATTRIBUTE_REQUIREMENTS[stat]
            observed_requirement, observed_stat = stats.get(req_stat), stats.get(stat)
            baseline_requirement = baseline.get(req_stat)
            key = f"{stat}>={req_stat}"
            if not requirement or not isinstance(observed_requirement, (int, float)) or not isinstance(observed_stat, (int, float)) or not isinstance(baseline_requirement, (int, float)):
                continue
            remaining = float(baseline_requirement)
            if float(observed_stat) >= remaining - 1e-9 * max(1.0, remaining):
                violations.pop(key, None)
            else:
                violations[key] = (remaining - float(observed_stat)) / max(1.0, remaining)
        score = self.objective.score(stats)
        return Score(-sum(violations.values()), score.value)

    def _payment_slots(self, weapon_slot: str) -> list[tuple[str, str]]:
        """Armour/jewellery template slots that can still buy one attribute line."""

        bases = dict(self._fill_bases_by_slot)
        if not bases:
            bases = {"Amulet": "Amber Amulet", "Ring 1": "Coral Ring", "Ring 2": "Coral Ring", "Belt": "Leather Belt"}
        return [
            (slot, base)
            for slot, base in bases.items()
            if slot != weapon_slot
            and not self._buys_value(base, slot)
            and any(line.kind in {"open", "open_or_craft", "craft"} for line in self._template_for(base, slot))
        ]

    def _attribute_capacity(self, weapon_slot: str, stat: str) -> tuple[float, float, int, float]:
        """(total, template-line roll, available line count, jewellery implicit total)."""

        key = (weapon_slot, stat)
        if key in self._attribute_capacity_cache:
            return self._attribute_capacity_cache[key]
        payment_slots = self._payment_slots(weapon_slot)
        rolls: list[float] = []
        for slot, base in payment_slots:
            ilvl = self.rails.gear.wishlist.item_level_for(slot)
            for candidate in without_excluded(bases_of_type(type_of(base), max_level=self.rails.gear.wishlist.base_level_max), self.rails):
                rolls.extend(
                    float(grant)
                    for mod in self._median_mods(candidate, ilvl)
                    if (grant := attribute_grants(mod.lines).get(stat, 0.0)) > 0
                )
        roll = float(statistics.median(rolls)) if rolls else 0.0
        retained_attributes = sum(
            int(any(mod.attribute for mod in result.affixes) or result.bench_attribute)
            for (slot, _raw), result in self._results_by_raw.items()
            if slot not in self._filling_slots and slot != weapon_slot
        )
        slots = min(len(payment_slots), max(0, self.rails.gear.wishlist.attribute_affixes_max - retained_attributes))
        implicit = 0.0
        for slot in JEWELLERY_SLOTS:
            if slot not in self._fill_bases_by_slot or slot == weapon_slot or (slot not in self._filling_slots and slot in self.current_raw):
                continue
            base = self._fill_bases_by_slot.get(slot)
            item_type = type_of(base) if base else {"Amulet": "Amulet", "Ring 1": "Ring", "Ring 2": "Ring", "Belt": "Belt"}[slot]
            implicit += max(
                (attribute_grants((implicit_of(candidate),)).get(stat, 0.0)
                 for candidate in without_excluded(bases_of_type(item_type, max_level=self.rails.gear.wishlist.base_level_max), self.rails)),
                default=0.0,
            )
        self._attribute_capacity_cache[key] = (roll * slots + implicit, roll, slots, implicit)
        return self._attribute_capacity_cache[key]

    def _rank_weapon_bases(self, slot: str, base: str, ilvl: int, sockets: str | None) -> list[BaseChoice]:
        """Rank weapon bases by PoB value after proving their requirements payable.

        A weapon line is never reserved for an attribute payment. Its base earns
        the right to consume armour/jewellery capacity only when its effective
        value remains best after the measured per-line opportunity cost.
        """

        candidates = self.base_candidates(base)
        pins = {name: self._forced_pins(slot, name, ilvl) for name in candidates}
        raws = [(name, self._raw(name, ilvl, pins[name], None, sockets)) for name in candidates if pins[name] is not None]
        craftable = [(name, raw) for name, raw in raws if raw and not self._forced_lacking(slot, raw)]
        if not craftable and self.forced_lines.get(slot):
            # No base of the type can hold the forced line: stay loud as `_build_on_base` is (never a bare weapon).
            self._forced_mod(base, ilvl, self.forced_lines[slot][0], self._template_for(base, slot))
        baseline = self.pob.stats(self.objective.stat_keys)
        _count_items(slot, [raw for _name, raw in craftable])
        outcomes = self.pob.trial_stats(
            [{"item": {"slot": slot, "raw": raw}} for _name, raw in craftable],
            self.objective.stat_keys,
            mode="fast",
        ) if craftable else []
        rows_by_base: dict[str, dict[str, object]] = {}
        offered: list[tuple[str, Score, int, dict[str, object]]] = []
        for name in candidates:
            record = base_record(name) or {}
            rows_by_base[name] = {
                "base": name,
                "implicit": implicit_of(name),
                "requirements": self._base_requirements(name),
                "drop_level": drop_level(record) if record else None,
                "value": None,
                "effective_value": None,
                "violation": None,
                "shortfall": {},
                "payable": False,
                "lines_needed": None,
                "payment": None,
                "requested": name == base,
                "verdict": "not legal",
            }
        for (name, _raw), outcome in zip(craftable, outcomes):
            row = rows_by_base[name]
            record = base_record(name) or {}
            if drop_level(record) > self.rails.gear.wishlist.base_level_max:
                row["verdict"] = "level requirement above rail"
                continue
            stats = outcome.get("stats") if outcome.get("ok") else None
            if not isinstance(stats, Mapping):
                row["verdict"] = "PoB returned no stats"
                continue
            score = self._score_without_own_base_requirements(stats, name, baseline)
            requirements = self._base_attribute_requirements(name)
            shortfall = {
                stat: max(0.0, requirement - float(stats.get(stat) or 0.0))
                for stat, requirement in requirements.items()
                if requirement > 0
            }
            capacity: dict[str, float] = {}
            lines: dict[str, int] = {}
            payable = True
            for stat, missing in shortfall.items():
                total, roll, _slots, implicit = self._attribute_capacity(slot, stat)
                capacity[stat] = total
                if missing > total + 1e-9:
                    payable = False
                lines[stat] = int((missing + roll - 1e-9) // roll) if missing > 0 and roll > 0 else 0
            lines_needed = sum(lines.values())
            effective_value = score.value * (1.0 - lines_needed * self.rails.gear.wishlist.weapon_base_open_line_share)
            row.update({
                "value": score.value,
                "effective_value": effective_value,
                "violation": score.violation,
                "shortfall": {stat: {"needs": amount, "capacity": capacity.get(stat, 0.0)} for stat, amount in shortfall.items() if amount > 0},
                "payable": payable,
                "lines_needed": lines_needed,
            })
            if not payable:
                failures = ", ".join(
                    f"needs {amount:g} {stat}, the set can pay {capacity.get(stat, 0.0):g}"
                    for stat, amount in shortfall.items() if amount > capacity.get(stat, 0.0) + 1e-9
                )
                row["verdict"] = "requirement not payable: " + failures
                continue
            row["verdict"] = "payable"
            offered.append((name, score, lines_needed, row))

        # A weapon requirement is a cost, not a veto: rank every payable base by
        # the value left after the rest of the set spends its required attribute
        # lines. Floors still matter, but only decide an exact effective-value tie.
        ranked = sorted(
            offered,
            key=lambda entry: (
                -float(entry[3]["effective_value"]),
                -entry[1].neg_violation,
                entry[0],
            ),
        )
        for rank, (_name, _score, _lines, row) in enumerate(ranked, start=1):
            row["rank"] = rank
        limit = max(1, self.rails.gear.wishlist.base_candidates)
        chosen = ranked[:limit]
        for name, _score, _lines, row in chosen:
            row["verdict"] = "filled"
        self.base_screen[slot] = sorted(
            rows_by_base.values(),
            key=lambda row: (int(row.get("rank") or 10**9), str(row["base"])),
        )
        choices = [BaseChoice(name) for name, _score, _lines, _row in chosen]
        self._weapon_base_choices[slot] = [BaseChoice(name) for name, _score, _lines, _row in ranked]
        if not choices:
            raise ValueError(f"no payable weapon base for {slot} ({base})")
        return choices

    @staticmethod
    def _payment_label(payment: BasePayment | None) -> str | None:
        """The one attribute line the base screen charged to a base, as it reads."""

        if payment is None:
            return None
        if payment.mod is not None:
            return payment.mod.label
        return "{crafted} " + " / ".join(str(line) for line in (payment.bench or {}).get("rolled_lines") or ())

    @staticmethod
    def _base_requirements(base: str) -> str:
        """What the character must have to wear the base, in PoB's own numbers."""

        record = base_record(base) or {}
        requirements = dict(record.get("requirements") or {})
        level = requirements.pop("level", None)
        parts = [f"{name} {value:g}" for name, value in sorted(requirements.items()) if value]
        if level:
            parts.append(f"lvl {level:g}")
        return ", ".join(parts) or "-"

    def _base_screen_rows(
        self,
        candidates: Sequence[str],
        craftable: Sequence[tuple[str, str]],
        offered: Sequence[tuple[str, Score, BasePayment | None]],
        kept: Sequence[tuple[str, Score, BasePayment | None]],
        chosen: Sequence[tuple[str, Score, BasePayment | None]],
    ) -> list[dict[str, object]]:
        """Every base the screen was offered and why it did or did not survive.

        A base can appear twice: once bare and once with the attribute line the
        screen charged it (D79 rule 4). The ranking itself is not changed here --
        this only records it.
        """

        survived = {(name, id(payment)) for name, _score, payment in kept}
        filled = {(name, id(payment)) for name, _score, payment in chosen}
        rows: list[dict[str, object]] = []
        for name, score, payment in offered:
            key = (name, id(payment))
            record = base_record(name) or {}
            rows.append({
                "base": name,
                "implicit": implicit_of(name),
                "requirements": self._base_requirements(name),
                "drop_level": drop_level(record) if record else None,
                "value": score.value,
                "violation": score.violation,
                "payment": self._payment_label(payment),
                "verdict": "filled" if key in filled else ("lost by value" if key in survived else "lost to the 5% guard"),
            })
        scored_names = {name for name, _score, _payment in offered}
        craftable_names = {name for name, _raw in craftable}
        for name in candidates:
            if name in scored_names:
                continue
            record = base_record(name) or {}
            rows.append({
                "base": name,
                "implicit": implicit_of(name),
                "requirements": self._base_requirements(name),
                "drop_level": drop_level(record) if record else None,
                "value": None,
                "violation": None,
                "payment": None,
                "verdict": "not legal" if name not in craftable_names else "PoB returned no stats",
            })
        return rows

    WEAPON_PAYMENT_SLACK = 0.05  # D79 rule 4: a weapon pays only when no unpaid base is this close

    def _drop_weapon_payments_with_a_free_alternative(
        self, slot: str, base: str,
        scored: Sequence[tuple[str, Score, BasePayment | None]],
        unpaid_values: Sequence[float],
    ) -> list[tuple[str, Score, BasePayment | None]]:
        """Rule 4: a weapon line pays an attribute only when nothing else can.

        Attribute payments belong on jewellery and armour open-or-craft lines,
        but weapons are filled first, so the guard has to live in the weapon's
        own base screen: a paid base is dropped whenever a base that needs NO
        payment at all is within 5% of the paid one's finished value. What
        survives is the case the rule allows -- no unpaid base comes close.
        """

        scored = list(scored)
        if not self._buys_value(base, slot) or not unpaid_values or not any(payment is not None for _n, _s, payment in scored):
            return scored
        best_free = max(unpaid_values)
        kept: list[tuple[str, Score, BasePayment | None]] = []
        for name, score, payment in scored:
            if payment is not None and best_free >= (1.0 - self.WEAPON_PAYMENT_SLACK) * score.value:
                self.log(
                    f"[{slot}] weapon attribute payment dropped: {name} at {score.value:,.0f} against an unpaid base "
                    f"at {best_free:,.0f} (within {self.WEAPON_PAYMENT_SLACK:.0%})"
                )
                continue
            kept.append((name, score, payment))
        return kept or scored

    def base_candidates(self, base: str) -> list[str]:
        item_type = type_of(base)
        names = bases_of_type(item_type, max_level=self.rails.gear.wishlist.base_level_max)
        offered = set(without_excluded(names, self.rails))
        return [n for n in names if n in offered or n == base] or [base]  # #1154: the loadout's excluded bases are never offered; the base asked for (a forced rare base) stays

    def _forced_lacking(self, slot: str, raw: str | None) -> bool:
        """Whether ``raw`` for ``slot`` misses a line the request forces there (such a trial is never sent to PoB)."""

        lines = self.forced_lines.get(slot)
        return bool(lines) and raw is not None and not all(raw_has_affix(raw, line) for line in lines)

    def _unsendable(self, slot: str, base: str, raw: str | None) -> bool:
        """The one gate every finished-item trial of this module passes before PoB sees it: a trial that misses a forced
        line (``_forced_lacking``) or the Boots' pinned movement line (``_lacks_pinned_movement``) is never sent."""

        return self._forced_lacking(slot, raw) or self._lacks_pinned_movement(slot, base, raw)

    def _lacks_pinned_movement(self, slot: str, base: str, raw: str | None) -> bool:
        """#600: whether ``raw`` is a finished Boots of ``base`` (as many affixes as the template has lines) without the
        template's pinned movement line (`30% increased Movement Speed`, any other tier of it counts as without).

        Not applied when the base cannot roll the pinned line (``_pinned_movement_mod`` is ``None``: such a boots is built as
        the template allows, a bench craft or no line) or when a forced line took the movement line's template position."""

        if slot != "Boots" or not raw:
            return False
        pinned = self._pinned_movement_mod(slot, base)
        if pinned is None:
            return False
        template = self._template_for(base, slot)
        forced = self.forced_lines.get(slot)
        if forced and len(forced) <= len(template):
            movement_at = next((index for index, entry in enumerate(template) if entry.kind == "movement"), None)
            if movement_at in self._forced_positions(template, len(forced)):
                return False
        crafted = [row.strip() for row in raw.splitlines() if row.strip().startswith("{crafted}")]
        if len(raw_header_ids(raw)) + bool(crafted) < len(template):
            return False
        if pinned.mod_id in raw_header_ids(raw):
            return False
        want = affix_template(pinned.line)
        return not any(affix_template(row.replace("{crafted}", "", 1)) == want for row in crafted)

    def _forced_pins(self, slot: str, base: str, ilvl: int) -> list[WishlistMod] | None:
        """The mods carrying the slot's forced lines on ``base`` (``[]`` when none forced); ``None`` when the base cannot roll one."""

        lines = self.forced_lines.get(slot)
        if not lines:
            return []
        template = self._template_for(base, slot)
        try:
            return [self._forced_mod(base, ilvl, line, template) for line in lines]
        except ValueError:
            return None

    @staticmethod
    def _is_pinned_movement(slot: str, mod: WishlistMod) -> bool:
        """#600: the boots' movement line is the template's fixed 30% roll; no move loop retiers or drops it."""

        return slot == "Boots" and mod.group == "MovementVelocity"

    def pinned_roll_choices(self, slot: str, base: str) -> list[list[str]]:
        """#600: per pinned template line of ``slot``, the mod id a random roll of ``slot`` must carry (``random_rares(forced=...)``).

        The loop's headroom probes roll random rares of every rare slot; a Boots probe without the template's
        fixed `30% increased Movement Speed` would be a day-1 boots without the line reaching PoB."""

        mod = self._pinned_movement_mod(slot, base)
        return [[mod.mod_id]] if mod is not None else []

    def _pinned_movement_mod(self, slot: str, base: str) -> WishlistMod | None:
        """#600: the boots' template movement mod (30% increased Movement Speed), ``None`` for any other slot."""

        if slot != "Boots":
            return None
        line = next((entry for entry in self._template_for(base, slot) if entry.kind == "movement"), None)
        if line is None:
            return None
        return self._mod_at_tier(base, self.rails.gear.wishlist.item_level_for(slot), str(line.group), int(line.tier or 1))

    def _is_forced_mod(self, slot: str, mod: WishlistMod) -> bool:
        wanted = {affix_template(line) for line in self.forced_lines.get(slot, ())}
        return any(affix_template(text) in wanted for text in (mod.lines or (mod.line,)))

    def _forced_mod(self, base: str, ilvl: int, line: str, template: Sequence[TemplateSlot]) -> WishlistMod:
        """The base's mod carrying the forced line (matched by ``affix_template``), at the tier the template's other lines use."""

        want = affix_template(line)
        tier = next((int(entry.tier) for entry in template if entry.tier is not None), 1)
        for (_kind, group), ladder in self._whole_ladders(base, ilvl).items():
            if any(affix_template(text) == want for mod in ladder for text in (mod.get("lines") or ())):
                mod = self._mod_at_tier(base, ilvl, group, tier)
                if mod is not None and any(affix_template(text) == want for text in (mod.lines or (mod.line,))):
                    return mod
        raise ValueError(f"mod line {line!r} cannot roll on {base}")

    @staticmethod
    def _forced_positions(template: Sequence[TemplateSlot], count: int) -> list[int]:
        """Template indices the forced lines replace: the first open-kind lines, then the last lines backwards; never a new line."""

        if count > len(template):
            raise ValueError(f"{count} forced lines do not fit a template of {len(template)} lines")
        positions = [index for index, entry in enumerate(template) if entry.kind in {"open", "open_or_craft", "craft"}][:count]
        positions += [index for index in reversed(range(len(template))) if index not in positions][: count - len(positions)]
        return positions

    def _build_on_base(
        self,
        result: WishlistSlotResult,
        base: str,
        *,
        sockets: str | None,
        resistance: str | None,
        bench_allowed: bool,
        payment: BasePayment | None,
        order: ScoreOrder = "floors",
    ) -> Score:
        ilvl = result.ilvl
        template = self._template_for(base, result.slot)
        forced_at: dict[int, WishlistMod] = {}
        if forced_text := self.forced_lines.get(result.slot):
            forced_at = {
                position: self._forced_mod(base, ilvl, text, template)
                for position, text in zip(self._forced_positions(template, len(forced_text)), forced_text)
            }
        affixes: list[WishlistMod] = []
        bench: Mapping[str, object] | None = None
        base_payment = payment
        flexible_spent = 0  # flexible lines this item has actually bought
        skip_flexible = 0
        pure_es = self.pure_es if self.pure_es is not None else is_pure_es(self.pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        # A template slot is MANDATORY: "empty" is not a state the finished build
        # can be in, so every judgement below is made against the BARE BASE, never
        # against the empty slot. impale_ballista showed why: with no weapon the
        # main skill cannot be used and costs nothing, so the D63.2 sustain floor
        # is trivially met, and then EVERY bow -- bare or not -- "worsened" it by
        # the same 1.433. Rule 2 refuses anything that worsens a floor, so all 24
        # open candidates and every craft were refused and the bow ended bare. It
        # is the bow's existence that costs the mana, not any line on it.
        if (bare := self._raw(base, ilvl, [], None, sockets)) is not None:
            self.pob.equip({result.slot: bare})
        for index, line in enumerate(template):
            previous = self.objective.score(self.pob.stats(self.objective.stat_keys))
            selected_mod: WishlistMod | None = None
            selected_bench: Mapping[str, object] | None = None
            raw: str | None = None
            selected_score: Score | None = None
            if index in forced_at:
                selected_mod = forced_at[index]  # the request's line takes this template line; nothing is offered for it
            elif line.kind == "fixed":
                selected_mod = self._fixed_es_mod(base, ilvl, int(line.tier or 1)) if pure_es and line.group == "IncreasedLife" else self._mod_at_tier(base, ilvl, str(line.group), int(line.tier or 1))
            elif line.kind == "resistance":
                selected_mod = self._resistance_mod(base, ilvl, resistance or "fire", int(line.tier or 1))
            elif line.kind == "movement":
                selected_mod = self._mod_at_tier(base, ilvl, str(line.group), int(line.tier or 1))
                if selected_mod is None and bench_allowed and self.rails.gear.wishlist.bench_crafts:
                    selected_bench = next((row for row in self.bench_rows(base, ilvl) if row.get("group") == line.group), None)
            elif line.kind in {"open", "open_or_craft", "craft"}:
                if skip_flexible:
                    skip_flexible -= 1
                    result.steps.append(f"{line.kind}: consumed by the gem-level line")
                    continue
                candidates: list[tuple[WishlistMod | None, Mapping[str, object] | None]] = []
                if base_payment is not None and base_payment.families & self._used_families(affixes, bench):
                    self.pob.equip({result.slot: None})
                    result.steps.append("base attribute payment conflicts with a fixed template line")
                    return self.objective.score(self.pob.stats(self.objective.stat_keys))
                payment_mod = base_payment.mod if base_payment is not None else None
                payment_bench = base_payment.bench if base_payment is not None else None
                payment_kind = payment_mod.affix_type if payment_mod is not None else str((payment_bench or {}).get("type") or "")
                payment_fits = (
                    base_payment is not None
                    and payment_kind in {"Prefix", "Suffix"}
                    and line.affix_type in {"either", payment_kind}
                    and ((payment_mod is not None and line.kind in {"open", "open_or_craft"})
                         or (payment_bench is not None and line.kind in {"open_or_craft", "craft"} and bench_allowed and self.rails.gear.wishlist.bench_crafts))
                )
                payment_budget_used = self._attribute_lines_used(excluding=result.slot)
                paying = False
                if payment_fits and payment_budget_used < self.rails.gear.wishlist.attribute_affixes_max:
                    candidates.append((payment_mod, payment_bench))
                    paying = True
                elif payment_fits:
                    result.steps.append("base attribute payment exceeds the set-wide attribute budget")
                # Rule 5: a gem-level property takes the item's WHOLE open budget,
                # so it is only a candidate while no flexible line has been spent.
                allow_gem_level = flexible_spent == 0
                # Rule 5: a two-line mod needs a second open line of this item still free.
                flexible_left = sum(self._flexible(later) for later in template[index:])
                if base_payment is None:
                    candidates.extend(self._open_candidates(
                        base, ilvl, line, affixes, bench,
                        reserve=self._reserve_for(template, index), pure_es=pure_es,
                        bench_allowed=bench_allowed, payment_budget_used=payment_budget_used,
                        allow_gem_level=allow_gem_level,
                        allow_attributes=not self._buys_value(base, result.slot),
                        tier_position=(self._weapon_open_tier_position(template, index) if line.kind == "open" else None),
                        flexible_left=flexible_left,
                        slot=result.slot,
                    ))
                elif not payment_fits:
                    # This line cannot carry the payment, so it may take an ordinary
                    # mod -- but not the affix room the payment still needs, and
                    # never its family. (A line that CAN carry the payment but has
                    # no set-wide budget left takes nothing: the item is discarded
                    # at the end of the template anyway.)
                    prefixes, suffixes = self._affix_room(affixes, bench)
                    candidates.extend(
                        (mod, craft) for mod, craft in self._open_candidates(
                            base, ilvl, line, affixes, bench,
                            reserve=self._reserve_for(template, index), pure_es=pure_es,
                            bench_allowed=False, payment_budget_used=payment_budget_used,
                            allow_gem_level=allow_gem_level,
                            allow_attributes=not self._buys_value(base, result.slot),
                            tier_position=(self._weapon_open_tier_position(template, index) if line.kind == "open" else None),
                            flexible_left=flexible_left,
                            slot=result.slot,
                        )
                        if mod is not None
                        and not (mod.families & base_payment.families)
                        and not (payment_kind == "Prefix" and mod.affix_type == "Prefix" and prefixes >= self.rails.gear.max_prefixes - 1)
                        and not (payment_kind == "Suffix" and mod.affix_type == "Suffix" and suffixes >= self.rails.gear.max_suffixes - 1)
                    )
                # The base screen already charged this exact attribute line to the
                # base it ranked (rule 4). PoB measures it at +0 value, so on a
                # weapon it must not be judged by rule 2's value rule.
                whole_shield = self._gem_takes_whole_item(base, result.slot)
                gem_candidates: list[tuple[WishlistMod | None, Mapping[str, object] | None]] = []
                if whole_shield:
                    # #601: a gem-level line takes the WHOLE shield, so it is never tried beside the placed
                    # Life / resistance lines: it leaves the pool the ordinary pick sees and is tried alone below.
                    gem_candidates = [entry for entry in candidates if _picked_is_gem_level(entry)]
                    candidates = [entry for entry in candidates if not _picked_is_gem_level(entry)]
                picked = self._choose_trial(result.slot, base, ilvl, affixes, bench, candidates, sockets=sockets,
                                            buys_value=False if paying else None, order=order)
                choice_rows = list(self._last_choice_rows)
                if picked is not None and _picked_is_gem_level(picked):
                    keep, rows = self._gem_beats_ordinary_fill(
                        result.slot, base, ilvl, affixes, bench, picked[0] or picked[1], template, index,
                        sockets=sockets, pure_es=pure_es, bench_allowed=bench_allowed,
                        payment_budget_used=payment_budget_used,
                        allow_attributes=not self._buys_value(base, result.slot),
                        order=order,
                        whole_item=whole_shield,
                    )
                    result.gem_level_trials.append({"slot": result.slot, "base": base, "kept": keep, "rows": rows})
                    result.steps.append(
                        f"gem level {rows[0]['line'] if rows else '?'}: "
                        + ("takes the whole open budget" if keep else "loses to ordinary lines")
                    )
                    if not keep:
                        candidates = [entry for entry in candidates if not _picked_is_gem_level(entry)]
                        picked = self._choose_trial(result.slot, base, ilvl, affixes, bench, candidates, sockets=sockets,
                                                    buys_value=False if paying else None, order=order)
                        choice_rows = list(self._last_choice_rows)
                if gem_candidates:
                    gem_picked = self._choose_gem_shield(result.slot, base, ilvl, gem_candidates, sockets=sockets, order=order)
                    choice_rows += list(self._last_choice_rows)
                    if gem_picked is not None:
                        keep, rows = self._gem_beats_ordinary_fill(
                            result.slot, base, ilvl, affixes, bench, gem_picked[0] or gem_picked[1], template, index,
                            sockets=sockets, pure_es=pure_es, bench_allowed=bench_allowed,
                            payment_budget_used=payment_budget_used,
                            allow_attributes=not self._buys_value(base, result.slot),
                            order=order,
                            whole_item=True,
                        )
                        result.gem_level_trials.append({"slot": result.slot, "base": base, "kept": keep, "rows": rows})
                        result.steps.append(
                            f"gem level {rows[0]['line'] if rows else '?'}: "
                            + ("takes the whole open budget" if keep else "loses to ordinary lines")
                        )
                        if keep:
                            # The kept gem line takes the whole shield: the fixed Life / resistance lines
                            # already placed are dropped and the line is rebuilt below on the empty item.
                            affixes.clear()
                            result.extra_resistance = None
                            result.shopping[:] = [entry for entry in result.shopping if entry.get("kind") not in {"life", "resistance_fixed", "extra_resistance"}]
                            result.steps.append("gem level line takes the whole shield: no Life, no resistance, no other line")
                            picked = (gem_picked[0], gem_picked[1], None, None)
                if picked is not None and not _picked_is_gem_level(picked) and _picked_is_two_line(picked):
                    keep, rows = self._gem_beats_ordinary_fill(
                        result.slot, base, ilvl, affixes, bench, picked[0], template, index,
                        sockets=sockets, pure_es=pure_es, bench_allowed=bench_allowed,
                        payment_budget_used=payment_budget_used,
                        allow_attributes=not self._buys_value(base, result.slot),
                        span=picked[0].line_cost, order=order,
                    )
                    result.steps.append(
                        f"two-line {rows[0]['line'] if rows else '?'}: "
                        + ("beats the best ordinary pair" if keep else "loses to the best ordinary pair")
                    )
                    if not keep:
                        candidates = [entry for entry in candidates if not _picked_is_two_line(entry)]
                        picked = self._choose_trial(result.slot, base, ilvl, affixes, bench, candidates, sockets=sockets,
                                                    buys_value=False if paying else None, order=order)
                        choice_rows = list(self._last_choice_rows)
                result.candidate_log.append({
                    "base": base, "line": index, "kind": line.kind, "before": previous.value,
                    "buys_value": self._buys_value(base, result.slot), "rows": choice_rows,
                })
                if picked is not None:
                    selected_mod, selected_bench, raw, selected_score = picked
            else:
                raise ValueError(f"unknown template line kind {line.kind!r}")

            if raw is None and (selected_mod is not None or selected_bench is not None):
                raw = self._raw(base, ilvl, [*affixes, *([selected_mod] if selected_mod else [])], selected_bench or bench, sockets)
                if raw is not None:
                    _count_items(result.slot, [raw])
                    outcome = self.pob.trial_stats([{"item": {"slot": result.slot, "raw": raw}}], self.objective.stat_keys, mode="fast")[0]
                    selected_score = self.objective.score(outcome["stats"]) if outcome.get("ok") and outcome.get("stats") else None
            if raw is None:
                label = line.group or line.kind
                if self._flexible(line):
                    result.steps.append(f"{line.kind}: free line (no objective delta)")
                    result.shopping.append({"kind": "free_line", "line": "anything", "delta": 0.0})
                else:
                    result.steps.append(f"{line.kind} {label}: skipped (base cannot roll it)")
                    result.shopping.append({"kind": line.kind, "line": label, "skipped": True})
                continue
            self.pob.equip({result.slot: raw})
            if selected_mod is not None:
                affixes.append(selected_mod)
            if selected_bench is not None:
                bench = selected_bench
                result.bench = bench
                result.bench_attribute = _is_attribute_mod(bench)
            if base_payment is not None and ((base_payment.mod is not None and selected_mod is not None and selected_mod.mod_id == base_payment.mod.mod_id)
                                             or (base_payment.bench is not None and selected_bench is base_payment.bench)):
                base_payment = None
            current = self.objective.score(self.pob.stats(self.objective.stat_keys))
            if self._flexible(line):
                flexible_spent += 1
                if (selected_mod is not None and selected_mod.gem_level) or (selected_bench is not None and _is_gem_level_mod(selected_bench)):
                    # Rule 5: every remaining flexible line of this item is spent.
                    skip_flexible = sum(self._flexible(later) for later in template[index + 1:])
                elif selected_mod is not None and selected_mod.line_cost > 1:
                    skip_flexible = max(skip_flexible, selected_mod.line_cost - 1)
            label = selected_mod.label if selected_mod is not None else "{crafted} " + " / ".join(str(value) for value in (selected_bench or {}).get("rolled_lines") or ())
            if index in forced_at:
                result.steps.append(f"forced {line.kind} -> {label}")
                result.shopping.append({"kind": "objective_line", "template_kind": "forced", "line": label, "tier": selected_mod.tier,
                                        "forced": True, "mod_id": selected_mod.mod_id})
            elif line.kind in {"open", "open_or_craft", "craft"}:
                share = f", share {selected_mod.share:.2%}" if selected_mod is not None else ""
                result.steps.append(f"{line.kind} {label}: {previous.value:,.0f} -> {current.value:,.0f} (delta {current.value - previous.value:+,.0f}{share})")
                kind = (
                    "attribute" if (selected_mod is not None and selected_mod.attribute) or (selected_bench is not None and _is_attribute_mod(selected_bench)) else
                    "resistance_craft" if selected_bench is not None and _is_elemental_resistance_group(selected_bench.get("group")) else
                    "objective_line"
                )
                result.shopping.append({"kind": kind, "template_kind": line.kind, "line": label, "tier": selected_mod.tier if selected_mod else None,
                                        "delta": current.value - previous.value, "share": selected_mod.share if selected_mod else None,
                                        "line_cost": selected_mod.line_cost if selected_mod else 1,
                                        "mod_id": selected_mod.mod_id if selected_mod else None})
            else:
                result.steps.append(f"{line.kind} {label}")
                kind = {"fixed": "life", "resistance": "resistance_fixed", "movement": "movement"}.get(line.kind, line.kind)
                result.shopping.append({"kind": kind, "line": label, "tier": selected_mod.tier if selected_mod else None,
                                        "mod_id": selected_mod.mod_id if selected_mod else None})

            if line.kind == "resistance":
                extra_element = self._extra_resistance_assignments.get(result.slot)
                if extra_element is not None:
                    extra_mod = self._resistance_mod(base, ilvl, extra_element, 3)
                    # #600: the boots' movement line comes later in the template, but the trial is already a finished-looking
                    # three-affix item: it carries that line, so no 30%-less boots reaches PoB
                    later_movement = next((self._pinned_movement_mod(result.slot, base) for later, entry in enumerate(template) if later > index and entry.kind == "movement" and later not in forced_at), None)
                    extra_raw = self._raw(base, ilvl, [*affixes, *([extra_mod] if extra_mod else []), *([later_movement] if later_movement else [])], bench, sockets)
                    if extra_mod is not None and extra_raw is not None and not self._unsendable(result.slot, base, extra_raw):
                        _count_items(result.slot, [extra_raw])
                        outcome = self.pob.trial_stats(
                            [{"item": {"slot": result.slot, "raw": extra_raw}}], self.objective.stat_keys, mode="fast"
                        )[0]
                        if outcome.get("ok") and outcome.get("stats"):
                            self.pob.equip({result.slot: extra_raw})
                            affixes.append(extra_mod)
                            result.extra_resistance = extra_element
                            result.steps.append(f"extra resistance {extra_mod.label}")
                            result.shopping.append({
                                "kind": "extra_resistance", "line": extra_mod.label, "tier": extra_mod.tier,
                                "element": extra_element, "mod_id": extra_mod.mod_id,
                            })

        if base_payment is not None:
            # The base was ranked at the price of this payment. Do not let it
            # keep the rank if PoB could not place that exact line beside the
            # fixed template affixes.
            self.pob.equip({result.slot: None})
            result.steps.append("base attribute payment could not be crafted with the template")
            result.affixes, result.mod_ids, result.bench_line, result.raw, result.rolled = [], [], None, "", 0
            return self.objective.score(self.pob.stats(self.objective.stat_keys))
        result.base = base
        result.implicit = implicit_of(base)
        result.affixes = affixes
        result.mod_ids = [mod.mod_id for mod in affixes]
        result.bench_line = " / ".join(str(value) for value in (bench or {}).get("rolled_lines") or ()) or None
        result.bench = bench
        result.bench_attribute = bool(bench and _is_attribute_mod(bench))
        result.raw = self._raw(base, ilvl, affixes, bench, sockets) or ""
        result.rolled = len(affixes) + int(bench is not None)
        return self.objective.score(self.pob.stats(self.objective.stat_keys))

    def _keep_incumbent(self, slot: str, result: WishlistSlotResult, score: Score, *, resistance: str | None, order: ScoreOrder = "floors") -> Score:
        incumbent = self.current_raw.get(slot)
        if not incumbent or incumbent == result.raw:
            return score
        if self._forbids_item(slot, incumbent):  # #1152: a weapon with a forbidden line (a recorded build's) is not kept as a competitor
            return score
        prior = self._results_by_raw.get((slot, incumbent))
        if self._unsendable(slot, prior.base if prior is not None and prior.base else result.base, incumbent):
            return score
        if resistance is not None:
            required_group = RESISTANCE_GROUPS[resistance]
            if prior is None or not any(mod.group == required_group for mod in prior.affixes):
                # A global plan chose this element for the slot. Keeping a higher
                # scoring incumbent of another element would invalidate the plan.
                return score
        if (prior.extra_resistance if prior is not None else None) != self._extra_resistance_assignments.get(slot):
            return score
        _count_items(slot, [incumbent])
        outcome = self.pob.trial_stats([{"item": {"slot": slot, "raw": incumbent}}], self.objective.stat_keys, mode="fast")[0]
        if not outcome.get("ok") or not outcome.get("stats"):
            return score
        incumbent_score = self.objective.score(outcome["stats"])
        key = score_key(order)
        if not key(incumbent_score) > key(score):
            return score
        self.pob.equip({slot: incumbent})
        result.raw = incumbent
        result.affixes = list(prior.affixes) if prior is not None else []
        result.mod_ids = list(prior.mod_ids) if prior is not None else []
        result.bench_line = prior.bench_line if prior is not None else None
        result.bench = prior.bench if prior is not None else None
        result.bench_attribute = prior.bench_attribute if prior is not None else False
        result.shopping = list(prior.shopping) if prior is not None else []
        result.rolled = prior.rolled if prior is not None else sum(_affix_counts(incumbent)[:2])
        result.base = prior.base if prior is not None else result.base
        result.implicit = prior.implicit if prior is not None else result.implicit
        result.extra_resistance = prior.extra_resistance if prior is not None else None
        result.kept_incumbent = True
        result.steps.append("incumbent kept: " + (prior.mod_lines if prior is not None else "prior item"))
        return incumbent_score

    # ---- template v4 (2026-09-22): flexible lines over the finished set --------------------
    #
    # The line COUNT and the bench-craft count are the only hard-code left (requirement 1).
    # Everything below starts from today's finished template set (so v4 is never worse than
    # today on the judge) and runs three kinds of move to a fixed point, each judged by
    # ``Objective.better_score`` -- violation first, then value (requirement 4). It is reached
    # from ``fill()`` only when ``flexible_lines`` or ``boots_movement_floor`` is on; both are
    # off by default (see ``WishlistRails``), so a caller that never sets them gets byte-for-byte
    # today's behaviour.

    def _group_tiers(self, base: str, ilvl: int, group: str, *, affix_type: str = "either") -> list[WishlistMod]:
        """Every legal whole-ladder tier of one mod group (not just the closest to a target).

        Used where a group's OWN tier is the thing being decided (the boots
        movement line under ``boots_movement_floor``): the fixed-tier lookup
        ``_mod_at_tier`` only ever returns one clamped tier.
        """

        whole = self._whole_ladders(base, ilvl)
        legal = self.ladders(base, ilvl)
        out: list[WishlistMod] = []
        for (kind, name), full in whole.items():
            if name != group or (affix_type not in (None, "either") and kind != affix_type):
                continue
            legal_ids = {str(mod["mod_id"]) for mod in legal.get((kind, name), ())}
            for rank, mod in enumerate(full, start=1):
                if str(mod["mod_id"]) not in legal_ids:
                    continue
                families = _mod_families(mod.get("mod_id"), mod.get("group"))
                lines = tuple(str(line) for line in (mod.get("lines") or ()))
                out.append(WishlistMod(
                    str(mod["mod_id"]), kind, name, rank, len(full), lines[0] if lines else "",
                    lines=lines, families=families, attribute=_is_attribute_mod(mod),
                ))
        return out

    def _flexible_pool(
        self, base: str, slot: str, ilvl: int,
        other_affixes: Sequence[WishlistMod], bench: Mapping[str, object] | None,
        *, pure_es: bool, bench_allowed: bool, allow_attributes: bool, payment_budget_used: int,
    ) -> list[tuple[WishlistMod | None, Mapping[str, object] | None]]:
        """Every candidate one swappable line of a finished item may take (requirement 2).

        ``other_affixes``/``bench`` are the item's REMAINING lines (the one line
        being reconsidered is excluded), so affix room, family and attribute
        checks are against what stays. ``IncreasedLife`` and an elemental
        resistance are ordinary candidates, each still priced at the slot's
        existing life/resistance tier (requirement 3, ``today's rule for its
        kind``); every other group prices at today's open-line median rule.
        Boots additionally offer every legal ``MovementVelocity`` tier
        (requirement 5), not just the template's fixed one.
        """

        used = self._used_families(other_affixes, bench)
        prefixes, suffixes = self._affix_room(other_affixes, bench)
        attributes = sum(mod.attribute for mod in other_affixes) + int(bench is not None and _is_attribute_mod(bench))

        def room_ok(kind: str) -> bool:
            return not ((kind == "Prefix" and prefixes >= self.rails.gear.max_prefixes) or (kind == "Suffix" and suffixes >= self.rails.gear.max_suffixes))

        out: list[tuple[WishlistMod | None, Mapping[str, object] | None]] = []
        for mod in self._median_mods(base, ilvl, affix_type="either", slot=slot):
            if mod.gem_level or (mod.families & used) or not room_ok(mod.affix_type):
                continue
            if mod.group == "IncreasedLife" or _is_elemental_resistance_group(mod.group):
                continue  # offered below at their own anchor (slot-kind) tier, never the open-line tier
            if mod.attribute and (not allow_attributes or attributes >= 1 or payment_budget_used >= self.rails.gear.wishlist.attribute_affixes_max):
                continue
            out.append((mod, None))
        template = self._template_for(base, slot)
        life_line = next((line for line in template if line.kind == "fixed"), None)
        if life_line is not None:
            life_mod = (
                self._fixed_es_mod(base, ilvl, int(life_line.tier or 1)) if pure_es
                else self._mod_at_tier(base, ilvl, str(life_line.group), int(life_line.tier or 1))
            )
            if life_mod is not None and not (life_mod.families & used) and room_ok(life_mod.affix_type):
                out.append((life_mod, None))
        resistance_line = next((line for line in template if line.kind == "resistance"), None)
        element = self._resistance_assignments.get(slot)
        if resistance_line is not None and element is not None:
            resistance_mod = self._resistance_mod(base, ilvl, element, int(resistance_line.tier or 1))
            if resistance_mod is not None and not (resistance_mod.families & used) and room_ok(resistance_mod.affix_type):
                out.append((resistance_mod, None))
        if slot == "Boots":
            movement_line = next((line for line in template if line.kind == "movement"), None)
            if movement_line is not None:
                for mod in self._group_tiers(base, ilvl, str(movement_line.group), affix_type=movement_line.affix_type):
                    if (mod.families & used) or not room_ok(mod.affix_type):
                        continue
                    out.append((mod, None))
        if bench_allowed and self.rails.gear.wishlist.bench_crafts and bench is None:
            out.extend((None, row) for row in self._bench_candidates(
                base, ilvl, other_affixes, allow_resistance=True,
                attribute_slots_used=payment_budget_used, allow_gem_level=False, allow_attributes=allow_attributes, slot=slot,
            ))
        return out

    @staticmethod
    def _moved_line_entry(mod: WishlistMod | None, craft: Mapping[str, object] | None, *, delta: float | None = None) -> dict[str, object]:
        """The shopping-list entry of a line a move put on an item, classified as construction does."""

        if mod is not None:
            kind = (
                "life" if mod.group == "IncreasedLife" else
                "resistance_fixed" if _is_elemental_resistance_group(mod.group) else
                "movement" if mod.group == "MovementVelocity" else
                "attribute" if mod.attribute else
                "objective_line"
            )
            entry: dict[str, object] = {"kind": kind, "line": mod.label, "tier": mod.tier, "mod_id": mod.mod_id}
        else:
            lines = " / ".join(str(value) for value in (craft or {}).get("rolled_lines") or ())
            kind = (
                "resistance_craft" if _is_elemental_resistance_group((craft or {}).get("group")) else
                "attribute" if craft is not None and _is_attribute_mod(craft) else
                "objective_line"
            )
            entry = {"kind": kind, "line": "{crafted} " + lines, "tier": None, "mod_id": None}
        if delta is not None:
            entry["delta"] = delta
        return entry

    def _reshop(self, result: WishlistSlotResult, removed: WishlistMod, mod: WishlistMod | None, craft: Mapping[str, object] | None, *, delta: float | None = None) -> None:
        """Keep ``result.shopping`` (the delivered shopping list) in step with a line a move changed.

        The entry of the line that left is replaced in place by the line that came; an item whose
        list had no entry for it (a skipped or free line) gets the new one appended.
        """

        entry = self._moved_line_entry(mod, craft, delta=delta)
        for index, line in enumerate(result.shopping):
            if line.get("mod_id") == removed.mod_id and not line.get("skipped"):
                result.shopping[index] = entry
                return
        result.shopping.append(entry)

    def _line_swap_pass(self, results: Sequence[WishlistSlotResult], *, only_slots: frozenset[str] | None = None) -> dict[str, int]:
        """Requirement 4a: one line of one item for any candidate line of that item, to a fixed point.

        Operates on the item's actual occupied lines (its affixes, one bench
        craft untouched) rather than on template line indices, so it is a
        single mechanism for every slot: the general ``flexible_lines`` switch
        runs it over every slot, ``boots_movement_floor`` alone restricts it to
        Boots (so the movement line's own tier is the only thing that can move).
        """

        tried = kept = 0
        pure_es = self.pure_es if self.pure_es is not None else is_pure_es(self.pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        changed, guard = True, 0
        while changed and guard < 20:
            changed, guard = False, guard + 1
            for result in results:
                if not result.raw or not result.base or (only_slots is not None and result.slot not in only_slots):
                    continue
                slot, base, ilvl = result.slot, result.base, result.ilvl
                allow_attributes = not self._buys_value(base, slot)
                payment_budget_used = self._attribute_lines_used(excluding=slot)
                for position, current_mod in enumerate(result.affixes):
                    if self._is_forced_mod(slot, current_mod):
                        continue  # a line the request forces is never swapped out
                    if self._is_pinned_movement(slot, current_mod):
                        continue  # #600: the boots' 30% Movement Speed line is fixed on every day-1 build
                    other_affixes = [mod for index, mod in enumerate(result.affixes) if index != position]
                    pool = [
                        (mod, craft) for mod, craft in self._flexible_pool(
                            base, slot, ilvl, other_affixes, result.bench,
                            pure_es=pure_es, bench_allowed=True,
                            allow_attributes=allow_attributes, payment_budget_used=payment_budget_used,
                        )
                        if not (mod is not None and mod.mod_id == current_mod.mod_id)
                    ]
                    trials: list[tuple[WishlistMod | None, Mapping[str, object] | None, str]] = []
                    for mod, craft in pool:
                        trial_affixes = [*other_affixes, *([mod] if mod is not None else [])]
                        trial_bench = craft if craft is not None else result.bench
                        raw = self._raw(base, ilvl, trial_affixes, trial_bench, result.sockets)
                        if raw is not None and not self._unsendable(slot, base, raw):
                            trials.append((mod, craft, raw))
                    if not trials:
                        continue
                    tried += len(trials)
                    _count_items(slot, [raw for *_c, raw in trials])
                    outcomes = self.pob.trial_stats([{"item": {"slot": slot, "raw": raw}} for *_c, raw in trials], self.objective.stat_keys, mode="fast")
                    current_score = self.objective.score(self.pob.stats(self.objective.stat_keys))
                    best: tuple[WishlistMod | None, Mapping[str, object] | None, str, Score] | None = None
                    for (mod, craft, raw), outcome in zip(trials, outcomes):
                        if not outcome.get("ok") or not outcome.get("stats"):
                            continue
                        score = self.objective.score(outcome["stats"])
                        if better_score(score, current_score) and (best is None or score > best[3]):
                            best = (mod, craft, raw, score)
                    if best is None:
                        continue
                    mod, craft, raw, score = best
                    self.pob.equip({slot: raw})
                    result.affixes = [*other_affixes, *([mod] if mod is not None else [])]
                    if craft is not None:
                        result.bench, result.bench_attribute = craft, _is_attribute_mod(craft)
                        result.bench_line = " / ".join(str(value) for value in craft.get("rolled_lines") or ()) or None
                    result.mod_ids = [candidate.mod_id for candidate in result.affixes]
                    result.raw, result.after = raw, score
                    result.rolled = len(result.affixes) + int(result.bench is not None)
                    new_label = mod.label if mod is not None else "{crafted} " + " / ".join(str(value) for value in (craft or {}).get("rolled_lines") or ())
                    result.steps.append(f"line swap: {current_mod.label} -> {new_label} ({current_score.value:,.0f} -> {score.value:,.0f})")
                    self._reshop(result, current_mod, mod, craft, delta=score.value - current_score.value)
                    self.current_raw[slot] = raw
                    self._results_by_raw[(slot, raw)] = result
                    kept += 1
                    changed = True
        return {"tried": tried, "kept": kept}

    def _two_item_exchange_pass(self, results: Sequence[WishlistSlotResult]) -> dict[str, int]:
        """Requirement 4b: move a floor-carrying line from one item to another, judged as ONE move.

        Bounded: one candidate replacement line per giver (its best ordinary
        value candidate, screened once with a fast trial batch), tried against
        every other item's every retained line as the receiving line, applied
        with a real ``equip`` + ``stats`` (a two-slot change, so PoB's fast
        what-if lane cannot judge it) and accepted only when the WHOLE build's
        score improves under ``better_score``.
        """

        tried = kept = 0
        pure_es = self.pure_es if self.pure_es is not None else is_pure_es(self.pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        items = [result for result in results if result.raw and result.base]
        baseline = self.objective.score(self.pob.stats(self.objective.stat_keys))
        for giver in items:
            floor_mod = next((mod for mod in giver.affixes if mod.group == "IncreasedLife" or _is_elemental_resistance_group(mod.group)), None)
            if floor_mod is None:
                continue
            giver_other = [mod for mod in giver.affixes if mod.mod_id != floor_mod.mod_id]
            pool = [
                (mod, craft) for mod, craft in self._flexible_pool(
                    giver.base, giver.slot, giver.ilvl, giver_other, giver.bench,
                    pure_es=pure_es, bench_allowed=True,
                    allow_attributes=not self._buys_value(giver.base, giver.slot),
                    payment_budget_used=self._attribute_lines_used(excluding=giver.slot),
                )
                if not (mod is not None and (mod.group == "IncreasedLife" or _is_elemental_resistance_group(mod.group)))
            ]
            giver_trials: list[tuple[WishlistMod | None, Mapping[str, object] | None, str]] = []
            for mod, craft in pool:
                affixes = [*giver_other, *([mod] if mod is not None else [])]
                bench = craft if craft is not None else giver.bench
                raw = self._raw(giver.base, giver.ilvl, affixes, bench, giver.sockets)
                if raw is not None and not self._unsendable(giver.slot, giver.base, raw):
                    giver_trials.append((mod, craft, raw))
            if not giver_trials:
                continue
            _count_items(giver.slot, [raw for *_c, raw in giver_trials])
            outcomes = self.pob.trial_stats([{"item": {"slot": giver.slot, "raw": raw}} for *_c, raw in giver_trials], self.objective.stat_keys, mode="fast")
            scored_givers = [
                (mod, craft, raw, self.objective.score(outcome["stats"]))
                for (mod, craft, raw), outcome in zip(giver_trials, outcomes)
                if outcome.get("ok") and outcome.get("stats")
            ]
            if not scored_givers:
                continue
            giver_mod, giver_craft, giver_raw, _giver_score = max(scored_givers, key=lambda entry: entry[3])
            element = next((name for name, group in RESISTANCE_GROUPS.items() if group == floor_mod.group), None)
            placed = False
            for receiver in items:
                if receiver is giver:
                    continue
                # Requirement 3: the moved line is retiered to the RECEIVER's own slot-kind
                # tier, never carried over at the giver's tier -- "today's rule for its kind".
                receiver_template = self._template_for(receiver.base, receiver.slot)
                if floor_mod.group == "IncreasedLife":
                    receiver_life_line = next((line for line in receiver_template if line.kind == "fixed"), None)
                    tier = int(receiver_life_line.tier or 1) if receiver_life_line is not None else floor_mod.tier
                    retiered = self._fixed_es_mod(receiver.base, receiver.ilvl, tier) if pure_es else self._mod_at_tier(receiver.base, receiver.ilvl, "IncreasedLife", tier)
                else:
                    receiver_resistance_line = next((line for line in receiver_template if line.kind == "resistance"), None)
                    tier = int(receiver_resistance_line.tier or 1) if receiver_resistance_line is not None else floor_mod.tier
                    retiered = self._resistance_mod(receiver.base, receiver.ilvl, element, tier) if element else None
                if retiered is None:
                    continue
                for drop_index, dropped in enumerate(receiver.affixes):
                    if dropped.attribute or dropped.mod_id == retiered.mod_id or self._is_pinned_movement(receiver.slot, dropped):
                        continue
                    receiver_other = [mod for index, mod in enumerate(receiver.affixes) if index != drop_index]
                    if retiered.families & self._used_families(receiver_other, receiver.bench):
                        continue
                    receiver_raw = self._raw(receiver.base, receiver.ilvl, [*receiver_other, retiered], receiver.bench, receiver.sockets)
                    if receiver_raw is None or self._unsendable(receiver.slot, receiver.base, receiver_raw):
                        continue
                    tried += 1
                    prior = {giver.slot: giver.raw, receiver.slot: receiver.raw}
                    self.pob.equip({giver.slot: giver_raw, receiver.slot: receiver_raw})
                    new_score = self.objective.score(self.pob.stats(self.objective.stat_keys))
                    if not better_score(new_score, baseline):
                        self.pob.equip(prior)
                        continue
                    giver.affixes = [*giver_other, *([giver_mod] if giver_mod is not None else [])]
                    if giver_craft is not None:
                        giver.bench, giver.bench_attribute = giver_craft, _is_attribute_mod(giver_craft)
                        giver.bench_line = " / ".join(str(value) for value in giver_craft.get("rolled_lines") or ()) or None
                    giver.mod_ids = [mod.mod_id for mod in giver.affixes]
                    giver.raw, giver.rolled = giver_raw, len(giver.affixes) + int(giver.bench is not None)
                    receiver.affixes = [*receiver_other, retiered]
                    receiver.mod_ids = [mod.mod_id for mod in receiver.affixes]
                    receiver.raw, receiver.rolled = receiver_raw, len(receiver.affixes) + int(receiver.bench is not None)
                    for changed_result in (giver, receiver):
                        changed_result.after = new_score
                        self.current_raw[changed_result.slot] = changed_result.raw
                        self._results_by_raw[(changed_result.slot, changed_result.raw)] = changed_result
                    giver.steps.append(f"two-item exchange: {floor_mod.label} moved to {receiver.slot} for {dropped.label}")
                    receiver.steps.append(f"two-item exchange: {floor_mod.label} came from {giver.slot} for {dropped.label}")
                    self._reshop(giver, floor_mod, giver_mod, giver_craft)
                    self._reshop(receiver, dropped, retiered, None)
                    kept += 1
                    baseline = new_score
                    placed = True
                    break
                if placed:
                    break
        return {"tried": tried, "kept": kept}

    def _base_reroll_pass(self, results: Sequence[WishlistSlotResult]) -> dict[str, int]:
        """Requirement 4c: re-choose a finished item's base by what the whole flexible set does with it.

        Rebuilds each alternate base with today's construction pipeline, then
        runs the same line-swap pass (4a) on that one item alone before
        comparing -- ``base's implicit is judged by what the whole set does
        with the line it frees``.
        """

        tried = kept = 0
        for result in results:
            if not result.raw or not result.base:
                continue
            alternates = [base for base in self.base_candidates(result.base) if base != result.base]
            alternates = alternates[: max(0, self.rails.gear.wishlist.base_candidates - 1)]
            if not alternates:
                continue
            current_score = self.objective.score(self.pob.stats(self.objective.stat_keys))
            for candidate_base in alternates:
                tried += 1
                trial = WishlistSlotResult(slot=result.slot, base=candidate_base, ilvl=result.ilvl, sockets=result.sockets)
                self._build_on_base(
                    trial, candidate_base, sockets=result.sockets,
                    resistance=self._resistance_assignments.get(result.slot),
                    bench_allowed=True, payment=None,
                )
                if not trial.raw:
                    self.pob.equip({result.slot: result.raw})  # back to the item as it stands, an earlier alternate may have won
                    continue
                self._line_swap_pass([trial], only_slots=frozenset({result.slot}))
                final_score = self.objective.score(self.pob.stats(self.objective.stat_keys))
                if better_score(final_score, current_score):
                    previous_base = result.base
                    result.base, result.raw = trial.base, trial.raw
                    result.affixes, result.mod_ids = trial.affixes, trial.mod_ids
                    result.bench, result.bench_attribute, result.bench_line = trial.bench, trial.bench_attribute, trial.bench_line
                    result.rolled, result.implicit = trial.rolled, implicit_of(trial.base)
                    result.shopping, result.extra_resistance = list(trial.shopping), trial.extra_resistance
                    result.after = final_score
                    result.steps.append(f"base re-choice: {previous_base} -> {candidate_base}")
                    self.current_raw[result.slot] = result.raw
                    self._results_by_raw[(result.slot, result.raw)] = result
                    current_score = final_score
                    kept += 1
                else:
                    self.pob.equip({result.slot: result.raw})
                    self.current_raw[result.slot] = result.raw  # the trial's own line swaps pointed it at the rejected item
        return {"tried": tried, "kept": kept}

    def improve_flexible_lines(self, results: Sequence[WishlistSlotResult]) -> dict[str, object]:
        """Orchestrates requirement 4's fixed-point move loop; a no-op unless a switch is on."""

        wishlist = self.rails.gear.wishlist
        if not wishlist.flexible_lines and not wishlist.boots_movement_floor:
            return {}
        t0 = time.perf_counter()
        only_slots = None if wishlist.flexible_lines else frozenset({"Boots"})
        line_swap = self._line_swap_pass(list(results), only_slots=only_slots)
        exchange = {"tried": 0, "kept": 0}
        base_reroll = {"tried": 0, "kept": 0}
        if wishlist.flexible_lines:
            exchange = self._two_item_exchange_pass(list(results))
            line_swap_2 = self._line_swap_pass(list(results), only_slots=only_slots)
            line_swap = {"tried": line_swap["tried"] + line_swap_2["tried"], "kept": line_swap["kept"] + line_swap_2["kept"]}
            base_reroll = self._base_reroll_pass(list(results))
            line_swap_3 = self._line_swap_pass(list(results), only_slots=only_slots)
            line_swap = {"tried": line_swap["tried"] + line_swap_3["tried"], "kept": line_swap["kept"] + line_swap_3["kept"]}
        return {
            "moves": {"line_swap": line_swap, "two_item_exchange": exchange, "base_reroll": base_reroll},
            "seconds": time.perf_counter() - t0,
        }

    def fill_slot(self, slot: str, base: str, *, n: int | None = None, sockets: str | None = None, seed: int | None = None,
                  bench: bool = True, _base_candidates: Sequence[BaseChoice] | None = None,
                  replan_resistance: bool = False, order: ScoreOrder = "floors") -> WishlistSlotResult:
        """Fill one slot. ``n`` is accepted for the loot-compatible surface; ``seed`` only breaks an exact tie between
        candidates PoB scored the same (#619), never overrules a number PoB separated; None keeps the first listed.

        ``order`` is the Score order the finished items compete by: the base candidates among
        themselves and the incumbent against the winner ("floors", the default, is the violation-first
        order of construction; the improvement loop passes "priced", D116 / #553). The lines inside one
        item follow the same order (``_choose_trial``)."""

        del n
        self.tie_seed = seed
        t0 = time.perf_counter()
        ilvl = self.rails.gear.wishlist.item_level_for(slot)
        before = self.objective.score(self.pob.stats(self.objective.stat_keys))
        self.pob.equip({slot: None})
        bases = list(_base_candidates) if _base_candidates is not None else self._rank_bases(slot, base, ilvl, sockets, bench_allowed=bench)
        local_resistance_baseline = (
            self._resistance_baseline()
            if (_base_candidates is not None and len(bases) > 1)
            or (_base_candidates is None and (replan_resistance or slot not in self._resistance_assignments))
            else None
        )
        attempts: list[tuple[Score, WishlistSlotResult]] = []
        for candidate in bases:
            self.pob.equip({slot: None})
            resistance = (self._resistance_assignments.get(slot) if local_resistance_baseline is None
                          else self._resistance_for_slot(slot, candidate.base, local_resistance_baseline))
            attempt = WishlistSlotResult(slot=slot, base=candidate.base, ilvl=ilvl, sockets=sockets, before=before)
            score = self._build_on_base(
                attempt,
                candidate.base,
                sockets=sockets,
                resistance=resistance,
                bench_allowed=bench,
                payment=candidate.payment,
                order=order,
            )
            attempt.after = score
            if attempt.raw:
                attempts.append((score, attempt))
        if not attempts:
            result = WishlistSlotResult(slot=slot, base=base, ilvl=ilvl, before=before, after=before, steps=["no template item PoB could craft"])
            incumbent = self.current_raw.get(slot)
            if incumbent and not self._forbids_item(slot, incumbent):  # #1152
                self.pob.equip({slot: incumbent})
                restore_weapon_partner(self.pob, self.uniques, slot)
                result.raw, result.kept_incumbent = incumbent, True
            else:
                self.pob.equip({slot: None})
        else:
            score, result = pick_attempt(attempts, order, tie=None if self.tie_seed is None else self._tie)
            self.pob.equip({slot: result.raw})
            restore_weapon_partner(self.pob, self.uniques, slot)
            # A live replan may also change the base implicit. An incumbent that
            # happens to use the same explicit resistance group could still
            # invalidate its uncapped total, so the caller's snapshot decides
            # whether this new item is kept.
            result.after = score if local_resistance_baseline is not None else self._keep_incumbent(slot, result, score, resistance=resistance, order=order)
            if local_resistance_baseline is not None:
                self._resistance_assignments[slot] = self._resistance_for_slot(slot, result.base, local_resistance_baseline) or "fire"
        result.bases_screened = len(self.base_candidates(base))
        result.bases_filled = tuple(candidate.base for candidate in bases)
        result.base_log = [dict(row) for row in self.base_screen.get(slot, ())]
        if result.raw:
            # A base can appear twice (bare and paid); the first filled row of the
            # winning base is the one the slot actually wears.
            winner = next((row for row in result.base_log if row["base"] == result.base and row["verdict"] == "filled"), None)
            if winner is not None:
                winner["verdict"] = "TAKEN"
        result.seconds = time.perf_counter() - t0
        if result.raw and not (not attempts and result.kept_incumbent):
            self.current_raw[slot] = result.raw
            self._results_by_raw[(slot, result.raw)] = result
        self.log(
            f"[{slot}] wishlist template: {result.base}{f' ({result.implicit})' if result.implicit else ''} | "
            f"{result.rolled} lines (ilvl {ilvl})" + (" [incumbent kept]" if result.kept_incumbent else "") + f" [{result.seconds:.1f}s]"
        )
        for step in result.steps:
            self.log(f"[{slot}]   {step}")
        return result

    # ---- the interface the loop and the pipeline call (#795): each delegates to the member it replaces --------

    def item_level_for(self, slot: str) -> int:
        return self.rails.gear.wishlist.item_level_for(slot)

    def other_weapon_bases(self, base: str) -> list[str]:
        if not type_of(base):
            return []
        return [name for name in self.base_candidates(base) if name != base]

    @property
    def refills_by_value(self) -> bool:
        return True

    def preselect_bases(self, slots: Sequence[str], rare_bases: Mapping[str, str], sockets_of: Mapping[str, str | None]) -> dict[str, BaseChoice]:
        selected = {
            s: self._rank_bases(s, rare_bases[s], self.rails.gear.wishlist.item_level_for(s), sockets_of[s], bench_allowed=True)[0]
            for s in slots
        }
        # The joint kick empties all its victim slots together, so their fixed resistance lines are one small global solve.
        self._plan_resistances({s: choice.base for s, choice in selected.items()})
        return selected

    def refill_victim_slot(self, slot: str, base: str, *, n: int | None, sockets: str | None, seed: int, order: ScoreOrder, preselected: BaseChoice | None = None) -> WishlistSlotResult:
        kwargs = {"_base_candidates": (preselected,)} if preselected is not None else {}
        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order, **kwargs)

    def refill_slot(self, slot: str, base: str, *, n: int | None, sockets: str | None, seed: int, order: ScoreOrder) -> WishlistSlotResult:
        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order, replan_resistance=True)

    def resistance_plan_snapshot(self) -> dict[str, Any]:
        return {name: deepcopy(getattr(self, name)) for name in RESISTANCE_PLAN_ATTRS if hasattr(self, name)}

    def restore_resistance_plan(self, saved: Mapping[str, Any]) -> None:
        for name, value in saved.items():
            setattr(self, name, deepcopy(value))

    def plan_snapshot(self) -> dict[str, Any]:
        # The mutable plan/bookkeeping surfaces that influence a later fill. The ladder, bench and raw-text
        # lookup caches are static lookups and stay warm.
        results_by_raw = getattr(self, "_results_by_raw", {})
        return {
            "resistance": self.resistance_plan_snapshot(),
            "current_results": {
                (slot, raw): deepcopy(results_by_raw[(slot, raw)])
                for slot, raw in self.current_raw.items()
                if (slot, raw) in results_by_raw
            },
        }

    def plan_restore(self, saved: Mapping[str, Any]) -> None:
        self.restore_resistance_plan(saved["resistance"])
        results_by_raw = getattr(self, "_results_by_raw", None)
        if results_by_raw is not None:
            for key, value in saved["current_results"].items():
                results_by_raw[key] = deepcopy(value)

    def carry_result(self, slot: str, old_raw: str, new_raw: str, **fields: Any) -> None:
        prior = self._results_by_raw.get((slot, old_raw))
        if prior is not None:
            moved = deepcopy(prior)
            moved.raw = new_raw
            for name, value in fields.items():
                setattr(moved, name, value)
            self._results_by_raw[(slot, new_raw)] = moved

    def shopping_results(self) -> list[WishlistSlotResult]:
        """The shopping lists for raws still equipped after loop reverts."""

        return [
            self._results_by_raw[(slot, raw)]
            for slot in ordered_slots(self.current_raw)
            if (raw := self.current_raw.get(slot)) is not None and (slot, raw) in self._results_by_raw
        ]

    def _plan_resistances(self, bases_by_slot: Mapping[str, str]) -> ResistancePlan:
        implicit = {element: sum(self._implicit_resistances(base)[element] for base in bases_by_slot.values()) for element in RESISTANCE_GROUPS}
        baseline = self._resistance_baseline()
        for element, value in implicit.items():
            baseline[_RESISTANCE_STAT[element]] += value
        slots: list[tuple[str, Mapping[str, float]]] = []
        extra_slots: list[tuple[str, Mapping[str, float]]] = []
        for slot, base in bases_by_slot.items():
            resistance = next((line for line in self._template_for(base, slot) if line.kind == "resistance"), None)
            if resistance is not None:
                slots.append((slot, self._resistance_values(base, self.rails.gear.wishlist.item_level_for(slot), int(resistance.tier or 1))))
                if not slot.startswith("Weapon"):
                    extra_slots.append((slot, self._all_resistance_values(base, self.rails.gear.wishlist.item_level_for(slot))))
        retained_slots = set(self.current_raw) - set(bases_by_slot)
        retained_extra = {
            slot: element for slot, element in self._extra_resistance_assignments.items()
            if slot in retained_slots
        }
        plan = solve_resistances(
            baseline,
            slots,
            floor=self._resistance_floors(),
            extra_slots=extra_slots,
            max_extra=max(0, self.rails.gear.wishlist.extra_resistance_items - len(retained_extra)),
        )
        self._resistance_assignments = {
            **{slot: element for slot, element in self._resistance_assignments.items() if slot in retained_slots},
            **plan.assignments,
        }
        self._extra_resistance_assignments = {**retained_extra, **plan.extra_assignments}
        self.resistance_plan = plan
        if any(plan.shortfall.values()):
            self.log("wishlist resistance shortfall: " + ", ".join(f"{element} {value:.0f}" for element, value in plan.shortfall.items() if value > 0))
        else:
            self.log("wishlist resistance plan: " + ", ".join(f"{element} +{value:.0f}" for element, value in plan.overcap.items()))
        return plan

    def _verify_resistances(self) -> ResistancePlan:
        """One final PoB readback for the globally assigned template lines."""

        plan = solve_resistances(
            self._resistance_baseline(),
            (),
            floor=self._resistance_floors(),
        )
        self.resistance_plan = ResistancePlan(
            dict(self._resistance_assignments), plan.totals, plan.overcap, plan.shortfall,
            dict(self._extra_resistance_assignments),
        )
        if any(plan.shortfall.values()):
            self.log("wishlist resistance verify shortfall: " + ", ".join(f"{element} {value:.0f}" for element, value in plan.shortfall.items() if value > 0))
        else:
            self.log("wishlist resistance verify: " + ", ".join(f"{element} +{value:.0f}" for element, value in plan.overcap.items()))
        return self.resistance_plan

    def _replace_with_resistance_crafts(self, results: Sequence[WishlistSlotResult]) -> None:
        """Spend an open-or-craft line on resistance only after the finished fixed set needs it."""

        for result in results:
            if not self.objective.violations(self.pob.stats(self.objective.stat_keys)).keys() & set(RESISTANCE_STATS[:3]):
                break
            template = self._template_for(result.base, result.slot)
            if not any(line.kind == "open_or_craft" for line in template):
                continue
            retained_ids = {
                str(line["mod_id"])
                for line in result.shopping
                if line.get("kind") in {"life", "resistance_fixed", "extra_resistance"} and line.get("mod_id")
            }
            retained = [mod for mod in result.affixes if mod.mod_id in retained_ids]
            candidates = [
                row for row in self._bench_candidates(
                    result.base, result.ilvl, retained, allow_resistance=True,
                    attribute_slots_used=self._attribute_lines_used(excluding=result.slot),
                )
                if _is_elemental_resistance_group(row.get("group"))
            ]
            picked = self._choose_trial(result.slot, result.base, result.ilvl, retained, None,
                                        [(None, row) for row in candidates], sockets=result.sockets)
            if picked is None:
                continue
            _mod, craft, raw, score = picked
            assert craft is not None
            previous = self.objective.score(self.pob.stats(self.objective.stat_keys))
            result.resistance_repair_backup = (
                result.raw, list(result.affixes), result.bench, result.bench_attribute,
                result.bench_line, list(result.shopping), result.rolled,
            )
            self.pob.equip({result.slot: raw})
            result.affixes = retained
            result.mod_ids = [mod.mod_id for mod in retained]
            result.bench = craft
            result.bench_attribute = _is_attribute_mod(craft)
            result.bench_line = " / ".join(str(line) for line in craft.get("rolled_lines") or ()) or None
            result.raw = raw
            result.rolled = len(retained) + 1
            result.after = score
            result.shopping = [line for line in result.shopping if line.get("template_kind") != "open_or_craft" and line.get("kind") != "free_line"]
            result.shopping.append({
                "kind": "resistance_craft", "template_kind": "open_or_craft", "line": "{crafted} " + result.bench_line,
                "delta": score.value - previous.value,
            })
            self.current_raw[result.slot] = raw
            self._results_by_raw[(result.slot, raw)] = result

    def _remove_unneeded_resistance(self, results: Sequence[WishlistSlotResult]) -> None:
        """A late base or craft can cap an element; then an earlier repair line goes away."""

        for result in results:
            candidates: list[tuple[list[WishlistMod], Mapping[str, object] | None, str]] = []
            if result.extra_resistance:
                extra_id = next(
                    (str(line["mod_id"]) for line in result.shopping if line.get("kind") == "extra_resistance" and line.get("mod_id")),
                    None,
                )
                kept = [mod for mod in result.affixes if mod.mod_id != extra_id]
                raw = self._raw(result.base, result.ilvl, kept, result.bench, result.sockets)
                if raw is not None and not self._unsendable(result.slot, result.base, raw):
                    candidates.append((kept, result.bench, "extra_resistance"))
            if result.bench is not None and _is_elemental_resistance_group(result.bench.get("group")):
                backup = result.resistance_repair_backup
                if backup is not None:
                    _raw, affixes, bench, _bench_attribute, _bench_line, _shopping, _rolled = backup
                    candidates.append((list(affixes), bench, "resistance_craft"))
                else:
                    raw = self._raw(result.base, result.ilvl, result.affixes, None, result.sockets)
                    if raw is not None and not self._unsendable(result.slot, result.base, raw):
                        candidates.append((list(result.affixes), None, "resistance_craft"))
            for affixes, bench, kind in candidates:
                raw = self._raw(result.base, result.ilvl, affixes, bench, result.sockets)
                if raw is None or self._unsendable(result.slot, result.base, raw):
                    continue
                _count_items(result.slot, [raw])
                outcome = self.pob.trial_stats(
                    [{"item": {"slot": result.slot, "raw": raw}}], RESISTANCE_STATS, mode="fast"
                )[0]
                stats = outcome.get("stats") if outcome.get("ok") else None
                if not stats or any(float(stats.get(key) or 0.0) < self.rails.elemental_resist_floor for key in RESISTANCE_STATS[:3]):
                    continue
                self.pob.equip({result.slot: raw})
                result.affixes = affixes
                result.mod_ids = [mod.mod_id for mod in affixes]
                result.bench = bench
                result.bench_attribute = bool(bench and _is_attribute_mod(bench))
                result.bench_line = " / ".join(str(line) for line in (bench or {}).get("rolled_lines") or ()) or None
                result.raw = raw
                result.rolled = len(affixes) + int(bench is not None)
                result.extra_resistance = None if kind == "extra_resistance" else result.extra_resistance
                if kind == "extra_resistance":
                    self._extra_resistance_assignments.pop(result.slot, None)
                if kind == "resistance_craft" and result.resistance_repair_backup is not None:
                    _prior_raw, _prior_affixes, _prior_bench, _prior_bench_attribute, prior_bench_line, prior_shopping, prior_rolled = result.resistance_repair_backup
                    result.shopping = prior_shopping
                    result.bench_line = prior_bench_line
                    result.rolled = prior_rolled
                    result.resistance_repair_backup = None
                else:
                    result.shopping = [line for line in result.shopping if line.get("kind") != kind]
                result.steps.append(f"{kind} removed after final resistance check")
                self.current_raw[result.slot] = raw
                self._results_by_raw[(result.slot, raw)] = result
                break

    def _reconcile_resistance(self, result: WishlistSlotResult) -> bool:
        """Swap just the solver-owned fixed and extra lines after base selection.

        A final base choice can change an implicit and therefore the global
        assignment. Rebuilding the entire item repeats every open-line base
        screen even though only one fixed resistance changed. All other template
        lines are unchanged and PoB validates the assembled replacement below.
        """

        template = self._template_for(result.base, result.slot)
        fixed = next((line for line in template if line.kind == "resistance"), None)
        wanted = self._resistance_assignments.get(result.slot)
        if fixed is None or wanted is None:
            return False
        fixed_id = next(
            (str(line["mod_id"]) for line in result.shopping if line.get("kind") == "resistance_fixed" and line.get("mod_id")),
            None,
        )
        replacement = self._resistance_mod(result.base, result.ilvl, wanted, int(fixed.tier or 1))
        if fixed_id is None or replacement is None:
            return False
        affixes = [replacement if mod.mod_id == fixed_id else mod for mod in result.affixes]
        prior_extra_id = next(
            (str(line["mod_id"]) for line in result.shopping if line.get("kind") == "extra_resistance" and line.get("mod_id")),
            None,
        )
        affixes = [mod for mod in affixes if mod.mod_id != prior_extra_id]
        wanted_extra = self._extra_resistance_assignments.get(result.slot)
        if wanted_extra is not None:
            extra = self._resistance_mod(result.base, result.ilvl, wanted_extra, 3)
            if extra is None or any(extra.families & mod.families for mod in affixes):
                return False
            affixes.append(extra)
        raw = self._raw(result.base, result.ilvl, affixes, result.bench, result.sockets)
        if raw is None or self._unsendable(result.slot, result.base, raw):
            return False
        self.pob.equip({result.slot: raw})
        result.affixes = affixes
        result.mod_ids = [mod.mod_id for mod in affixes]
        result.raw = raw
        result.rolled = len(affixes) + int(result.bench is not None)
        result.extra_resistance = wanted_extra
        result.shopping = [line for line in result.shopping if line.get("kind") not in {"resistance_fixed", "extra_resistance"}]
        result.shopping.insert(1, {
            "kind": "resistance_fixed", "line": replacement.label, "tier": replacement.tier,
            "mod_id": replacement.mod_id,
        })
        if wanted_extra is not None:
            extra = next(mod for mod in affixes if mod.group == RESISTANCE_GROUPS[wanted_extra] and mod.mod_id != replacement.mod_id)
            result.shopping.insert(2, {
                "kind": "extra_resistance", "line": extra.label, "tier": extra.tier,
                "element": wanted_extra, "mod_id": extra.mod_id,
            })
        result.steps.append("fixed resistance reconciled after final base selection")
        self.current_raw[result.slot] = raw
        self._results_by_raw[(result.slot, raw)] = result
        return True

    def _unmet_weapon_requirement(self, result: WishlistSlotResult) -> dict[str, float]:
        stats = self.pob.stats(tuple(ATTRIBUTE_REQUIREMENTS))
        return {
            stat: requirement - float(stats.get(stat) or 0.0)
            for stat, requirement in self._base_attribute_requirements(result.base).items()
            if requirement > float(stats.get(stat) or 0.0) + 1e-9
        }

    def _refill_unmet_weapon_requirement(self, results: list[WishlistSlotResult], bases_by_slot: Mapping[str, str], sockets_by_slot: Mapping[str, str] | None, *, bench: bool) -> list[WishlistSlotResult]:
        """One fallback only: the rest of the set failed to pay a weapon's cost."""

        by_slot = {result.slot: result for result in results}
        for slot, result in list(by_slot.items()):
            if not self._buys_value(result.base, slot):
                continue
            unmet = self._unmet_weapon_requirement(result)
            if not unmet:
                continue
            choices = self._weapon_base_choices.get(slot, ())
            taken_at = next((index for index, choice in enumerate(choices) if choice.base == result.base), None)
            next_choice = choices[taken_at + 1] if taken_at is not None and taken_at + 1 < len(choices) else None
            record: dict[str, object] = {"slot": slot, "from": result.base, "unmet": unmet, "refilled": False}
            if next_choice is None:
                record["reason"] = "no next payable base"
                self.log(f"[{slot}] weapon requirement still unmet on {result.base}: {unmet}; no next payable base")
                self.weapon_requirement_refills.append(record)
                continue
            for row in self.base_screen.get(slot, ()):
                if row.get("base") == result.base and row.get("verdict") in {"filled", "TAKEN"}:
                    row["verdict"] = "lost after requirement check"
                if row.get("base") == next_choice.base:
                    row["verdict"] = "filled"
            self.current_raw.pop(slot, None)
            retry = self.fill_slot(
                slot,
                bases_by_slot[slot],
                sockets=(sockets_by_slot or {}).get(slot),
                seed=self.tie_seed,  # a refill keeps the seed of the fill it repairs
                bench=bench,
                _base_candidates=(next_choice,),
            )
            by_slot[slot] = retry
            record.update({"to": retry.base, "refilled": bool(retry.raw)})
            self.log(f"[{slot}] weapon requirement still unmet on {result.base}: {unmet}; refilled once with {retry.base}")
            self.weapon_requirement_refills.append(record)
        return [by_slot[slot] for slot in ordered_slots(by_slot)]

    def _snapshot_gear_set(self, label: str, *, score: Score | None = None) -> _GearSetSnapshot:
        """The whole set as it stands now: one PoB readback plus everything a restore needs."""

        return _GearSetSnapshot(
            label=label,
            score=self.objective.score(self.pob.stats(self.objective.stat_keys)) if score is None else score,
            raw_by_slot=dict(self.current_raw),
            results_by_raw={key: deepcopy(result) for key, result in self._results_by_raw.items()},
            resistance_assignments=dict(self._resistance_assignments),
            extra_resistance_assignments=dict(self._extra_resistance_assignments),
        )

    def _restore_gear_set(self, snapshot: _GearSetSnapshot) -> None:
        """Put the snapshot's item in every slot that moved since, and its records back."""

        updates = {
            slot: snapshot.raw_by_slot.get(slot)
            for slot in sorted(set(self.current_raw) | set(snapshot.raw_by_slot))
            if self.current_raw.get(slot) != snapshot.raw_by_slot.get(slot)
        }
        if updates:
            self.pob.equip(updates)
            for slot in updates:
                # PoB clears a slot whose item it finds invalid, so a weapon that
                # moves can drop the skeleton's paired unique (see restore_weapon_partner).
                restore_weapon_partner(self.pob, self.uniques, slot)
        self.current_raw = dict(snapshot.raw_by_slot)
        self._results_by_raw = dict(snapshot.results_by_raw)
        self._resistance_assignments = dict(snapshot.resistance_assignments)
        self._extra_resistance_assignments = dict(snapshot.extra_resistance_assignments)

    def _keep_best_gear_set(self, snapshots: Sequence[_GearSetSnapshot]) -> _GearSetSnapshot | None:
        """End the fill on the best set it held, ordered by ``better_score`` (#188).

        A resistance plan is complete only once every slot is filled, so the
        slot-by-slot comparison in ``_keep_incumbent`` cannot be the judge of the
        fill; the whole set is. ``better_score`` (D58) orders them: violation
        first, value second. A tie keeps the later set, and a set whose maximized
        stat has fallen to zero never wins over one that still has a number --
        the reading ``better_score`` already writes down, applied to whichever
        side of the comparison the broken set is on.

        Returns the restored snapshot, or ``None`` when the current set was kept.
        """

        best = snapshots[0]
        for candidate in snapshots[1:]:
            if (better_score(candidate.score, best.score) or candidate.score == best.score
                    or best.score.value <= 0.0 < candidate.score.value):
                best = candidate
        kept_current = best is snapshots[-1]
        self.log(
            "wishlist fill sets: " + " | ".join(snapshot.log_line for snapshot in snapshots)
            + f" -> kept {best.label}" + ("" if kept_current else " (restored)")
        )
        if kept_current:
            return None
        self._restore_gear_set(best)
        return best

    def fill(self, bases_by_slot: Mapping[str, str], *, sockets_by_slot: Mapping[str, str] | None = None, passes: int = 2, n: int | None = None, seed: int = 1, bench: bool = True) -> list[WishlistSlotResult]:
        order = ordered_slots(bases_by_slot)
        self._fill_bases_by_slot = dict(bases_by_slot)
        self._filling_slots = frozenset(bases_by_slot)
        self._attribute_capacity_cache = {}
        self._weapon_base_choices = {}
        self.weapon_requirement_refills = []
        results: list[WishlistSlotResult] = []
        # The set the fill was handed, scored before any slot moves. The fill may
        # never hand back a set this one outranks (#188).
        snapshots = [self._snapshot_gear_set("start")]
        for pass_index in range(passes):
            # Replacements solve resistance from the same empty-gear baseline as the first
            # pass. Otherwise pass two would count the outgoing template rares and its planned
            # replacements at once, and could leave the finished set uncapped.
            incumbents = {slot: self.current_raw[slot] for slot in order if slot in self.current_raw}
            if incumbents:
                self.pob.equip({slot: None for slot in incumbents})
            # The bare-base screen is the D73 base decision. Plan elemental
            # resistances against exactly those selected implicits, not the base
            # names the skeleton happened to provide.
            selected_bases = {
                slot: self._rank_bases(slot, bases_by_slot[slot], self.rails.gear.wishlist.item_level_for(slot), (sockets_by_slot or {}).get(slot), bench_allowed=bench)
                for slot in order
            }
            plan_bases = {slot: candidates[0].base for slot, candidates in selected_bases.items()}
            self._plan_resistances(plan_bases)
            if incumbents:
                self.pob.equip(incumbents)
            # Pass one only establishes a complete gear context for the final
            # comparison. Pass two still fills every base candidate and chooses
            # the finished item, so spending pass-one time on alternatives cannot
            # affect the base the caller receives.
            fill_bases = {
                slot: (candidates[:1] if passes > 1 and pass_index == 0 else candidates)
                for slot, candidates in selected_bases.items()
            }
            for index, slot in enumerate(order):
                if pass_index:
                    self.pob.equip({slot: None})
                results.append(
                    self.fill_slot(
                        slot,
                        bases_by_slot[slot],
                        n=n,
                        sockets=(sockets_by_slot or {}).get(slot),
                        seed=derive_seed(seed, PURPOSE_WISHLIST_FILL_SLOT, pass_index, index),
                        bench=bench,
                        _base_candidates=fill_bases[slot],
                    )
                )
            snapshots.append(self._snapshot_gear_set(f"pass {pass_index + 1}"))
        actual_results = results[-len(order):] if order else []
        actual = {result.slot: result.base for result in actual_results if result.raw}
        if actual and selected_bases:
            # Replan once more from an empty rare-slot state after base selection.
            # This keeps the global resistance assignment consistent with the
            # base that actually won each slot and avoids counting its implicit
            # twice in the planning baseline.
            saved_raw = {result.slot: result.raw for result in actual_results if result.raw}
            self.pob.equip({slot: None for slot in order})
            self._plan_resistances(actual)
            def resistance_group(result: WishlistSlotResult) -> str | None:
                return next((element for element, group in RESISTANCE_GROUPS.items()
                             if any(mod.group == group for mod in result.affixes)), None)

            reconcile = [
                result
                for result in actual_results
                if result.raw and result.slot in self._resistance_assignments and (
                self._resistance_assignments.get(result.slot) != resistance_group(result)
                or self._extra_resistance_assignments.get(result.slot) != result.extra_resistance
                )
            ]
            if reconcile:
                # The global solve changes only these fixed lines. Restore every
                # completed item first so a retry is scored on the same finished
                # set, then re-fill only the slots whose assignment moved.
                self.pob.equip(saved_raw)
                for result in reconcile:
                    if self._reconcile_resistance(result):
                        continue
                    candidate = next((choice for choice in selected_bases[result.slot] if choice.base == result.base), BaseChoice(result.base))
                    self.current_raw.pop(result.slot, None)
                    results.append(self.fill_slot(
                        result.slot,
                        bases_by_slot[result.slot],
                        sockets=(sockets_by_slot or {}).get(result.slot),
                        seed=self.tie_seed,
                        bench=bench,
                        _base_candidates=(candidate,),
                    ))
            else:
                self.pob.equip(saved_raw)
        final_results = self.shopping_results()
        self._replace_with_resistance_crafts(final_results)
        self._remove_unneeded_resistance(final_results)
        self._extra_resistance_assignments = {
            result.slot: result.extra_resistance
            for result in final_results
            if result.extra_resistance is not None
        }
        self._verify_resistances()
        self._refill_unmet_weapon_requirement(final_results, bases_by_slot, sockets_by_slot, bench=bench)
        if dict(self.current_raw) != snapshots[-1].raw_by_slot:
            # The reconcile, the resistance crafts and the weapon refill moved
            # items after the last pass; that is the set the caller would get.
            snapshots.append(self._snapshot_gear_set("final"))
        if self._keep_best_gear_set(snapshots) is not None:
            self._verify_resistances()
        # Template v4 (#7): starts from the set kept above (#188's best of the fill) and moves it
        # to a fixed point, each move judged by better_score; a no-op unless flexible_lines or
        # boots_movement_floor is on (WishlistRails).
        self.flexible_report = self.improve_flexible_lines(self.shopping_results())
        return results


__all__ = [
    "RARE_SLOT_ORDER",
    "BaseChoice",
    "BasePayment",
    "ResistancePlan",
    "TemplateSlot",
    "WishlistGear",
    "WishlistMod",
    "WishlistSlotResult",
    "attribute_grants",
    "is_pure_es",
    "median_index",
    "rolled_line",
    "solve_resistances",
    "template_for",
]
