"""Rails: what a build is allowed to assume, as code.

Numbers come from `rails_default.json` (derived from the reference builds, see
DECISIONS D10); legality constraints are always on (attribute requirements,
unreserved mana). Rails produce an `Objective`, so every optimizer sees the same
floors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from junkroan.optimizer.keystone_floors import HIT_FRACTION_KEY, energy_shield_recharge_for_costs_stat, mom_casts_stat
from junkroan.optimizer.castability import MANA_COST_POOL_STAT, MANA_OVER_RESERVED_STAT, mana_cost_pool_stat, mana_over_reserved_stat
from junkroan.optimizer.objective import ELEMENTAL_RESIST_RELATIONS, SUSTAIN_RESOURCES, Objective, sustain_cost_stat, sustain_cost_stat_name
from junkroan.optimizer.ramp import RAMP_RELATION, RampContext, ramp_budget_stat, ramp_stages_stat, ramp_stat
from junkroan.optimizer.self_cost import STAT_NAME as SELF_COST_STAT, self_cost_stat
from junkroan.mechanics.bench_unlocks import legal as bench_unlock_legal

DEFAULT_RAILS_PATH = Path(__file__).with_name("rails_default.json")

CHAOS_INOCULATION = "Chaos Inoculation"


def life_floor_key(forced_keystones: Iterable[str] = ()) -> str:
    """The floor that holds the defence pool a build is judged on (#1044): `Life`, or `EnergyShield`
    when Chaos Inoculation is among the forced keystones (its Life is 1, the pool is Energy Shield).
    Matched by name, case-insensitively; no other floor depends on it."""

    forced = {str(name).strip().lower() for name in forced_keystones}
    return "EnergyShield" if CHAOS_INOCULATION.lower() in forced else "Life"


def pool_floor_for(floors: Mapping[str, float], forced_keystones: Iterable[str] = ()) -> dict[str, float]:
    """`floors` with its `Life` entry moved to `life_floor_key(forced_keystones)`, the value kept (#1044).
    Without Chaos Inoculation forced it is a plain copy, the same keys in the same order."""

    key = life_floor_key(forced_keystones)
    if key == "Life" or "Life" not in floors:
        return dict(floors)
    out = {k: v for k, v in floors.items() if k != "Life"}
    out[key] = floors["Life"]
    return out


def _wishlist_rails(raw: Mapping[str, object]) -> "WishlistRails":
    """The `gear.wishlist` block of a rails file; a file without it keeps the dataclass numbers."""

    defaults = WishlistRails()
    tier = raw.get("tier") or {}
    raw_positions = raw.get("weapon_open_tier_positions")
    # The first weapon census exposed one position only. Old rail files still
    # mean "use that position for every open weapon line".
    if raw_positions is None and raw.get("weapon_open_tier_position") is not None:
        raw_positions = (raw["weapon_open_tier_position"],)
    positions = tuple(float(position) for position in (raw_positions or defaults.weapon_open_tier_positions))
    return WishlistRails(
        item_level={str(k): int(v) for k, v in (raw.get("item_level") or defaults.item_level).items()},
        bench_crafts=int(raw.get("bench_crafts", defaults.bench_crafts)),
        area_level=int(raw.get("area_level", defaults.area_level)),
        base_level_max=int(raw.get("base_level_max", defaults.base_level_max)),
        base_candidates=int(raw.get("base_candidates", defaults.base_candidates)),
        attribute_affixes_max=int(raw.get("attribute_affixes_max", defaults.attribute_affixes_max)),
        weapon_open_lines=int(raw.get("weapon_open_lines", defaults.weapon_open_lines)),
        weapon_open_tier_positions=positions,
        weapon_base_open_line_share=float(raw.get("weapon_base_open_line_share", defaults.weapon_base_open_line_share)),
        open_mod_never_below_share=float(raw.get("open_mod_never_below_share", defaults.open_mod_never_below_share)),
        open_mod_two_lines_below_share=float(raw.get("open_mod_two_lines_below_share", defaults.open_mod_two_lines_below_share)),
        extra_resistance_items=int(raw.get("extra_resistance_items", defaults.extra_resistance_items)),
        quiver_weapon_shape=bool(raw.get("quiver_weapon_shape", defaults.quiver_weapon_shape)),
        flexible_lines=bool(raw.get("flexible_lines", defaults.flexible_lines)),
        boots_movement_floor=bool(raw.get("boots_movement_floor", defaults.boots_movement_floor)),
    )


def _cluster_rails(raw: Mapping[str, object]) -> "ClusterRails":
    d = ClusterRails()
    return ClusterRails(
        count_max=int(raw.get("count_max", d.count_max)),
        sizes=[str(x) for x in raw.get("sizes", d.sizes)],
        passives={str(k): int(v) for k, v in dict(raw.get("passives") or d.passives).items()},
        notables_max=int(raw.get("notables_max", d.notables_max)),
        screen_keep=int(raw.get("screen_keep", d.screen_keep)),
    )


def _bench_rails(raw: Mapping[str, object]) -> "BenchRails":
    defaults = BenchRails()
    max_tier = raw.get("max_map_tier", defaults.max_map_tier)
    return BenchRails(
        max_map_tier=int(max_tier) if max_tier is not None else None,
        unknown_tier_allowed=bool(raw.get("unknown_tier_allowed", defaults.unknown_tier_allowed)),
        excluded_cost_currencies=tuple(str(value) for value in (raw.get("excluded_cost_currencies") or defaults.excluded_cost_currencies)),
    )


@dataclass(frozen=True, slots=True)
class WishlistRails:
    """The template-driven day-1 wishlist (D79).

    Measured on the 299 real day-1 rares of the 32 Tuadh references
    (`docs/research/2026-09-18-author-rares.md`): item level median 72 pooled and 76-77
    on the weapons; 5.17 affixes per rare of which 2.44 are useful to the build (median 2,
    weapons 3.40 / 4.14), one bench craft on 76% of them and never two; median tier T4 at
    0.50 of its ladder, 26% of mods at T1-T2 (about one per item).

    The base is part of the wishlist too (D73): `area_level` is the day-1 area level whose
    drop level a base may not exceed (77 = T10 maps, `docs/research/2026-09-18-day1-gear.md`),
    `base_candidates` how many of the class's bases are filled and compared, and
    `attribute_affixes_max` how many ITEMS of the complete template set may carry an attribute
    affix beyond implicits -- three, the 32 authors' own median (D79 rule 4,
    `scripts/fixture_attribute_affixes.py`: 1 item on 3 references, 2 on 9, 3 on 9, 4 on 6,
    5 on 3, 6 on 2; mean 3.09, max 6). One item never carries two (D73, the user's rule),
    because the base's implicit is the cheap and certain place attributes come from.
    """

    item_level: Mapping[str, int] = field(default_factory=lambda: {"default": 72, "Weapon 1": 76, "Weapon 2": 76})
    bench_crafts: int = 1
    area_level: int = 77  # T10 maps, the day-1 zone level (D73); no longer a base cap, see base_level_max
    base_level_max: int = 70  # day-1 template base drop level cap (#438, the owner's rule)
    base_candidates: int = 3  # bases of the class, best first by PoB on the bare base, that are filled and compared
    attribute_affixes_max: int = 3  # rare ITEMS of the set that may carry one attribute affix; the 32 authors' median (scripts/fixture_attribute_affixes.py); implicits do not count
    weapon_open_lines: int = 2  # natural weapon lines; the third (last) template line is its one bench craft (#429: weapon = 3 lines)
    weapon_open_tier_positions: tuple[float, ...] = (0.35, 0.50, 0.57)  # top-1/2/3 useful-line midpoint: 32 Tuadh authors and our loot (owner approved 2026-09-20)
    weapon_base_open_line_share: float = 0.0294  # each attribute line reduces a payable weapon base's effective value by this measured armour/jewellery share
    open_mod_never_below_share: float = 0.002  # ordinary group share below this is never a day-1 assumption
    open_mod_two_lines_below_share: float = 0.01  # an open mod with a share in [never_below, this) occupies two template lines
    extra_resistance_items: int = 2  # fourth-line T3 resistance payments, only when fixed lines and implicits miss cap
    # Template v4 (docs/specs/2026-09-22-template-v4-flexible-lines.md): the line COUNT and the
    # bench-craft count stay the only hard-code; the KIND on every line becomes a PoB decision.
    # Three independent switches, each measurable alone.
    # Requirement 1: a quiver gets the weapon's 3-open+1-craft shape instead of the armour shape
    # (life + resistance + one open-or-craft line). On by default: a quiver is a weapon-shape
    # item -- its lines buy the objective's value, not floors.
    quiver_weapon_shape: bool = True
    flexible_lines: bool = True  # requirements 2-4: every armour/jewellery line is a PoB decision, then the move loop (line swap, two-item exchange, base re-choice) runs to a fixed point
    boots_movement_floor: bool = True  # requirement 5: boots' movement line picks its own tier by PoB instead of a fixed T3, so the EffectiveMovementSpeedMod floor can make it buy a higher one

    def item_level_for(self, slot: str) -> int:
        return int(self.item_level.get(slot, self.item_level.get("default", 72)))

    @property
    def weapon_open_tier_position(self) -> float:
        """Compatibility read for callers that still ask for one position."""

        return self.weapon_open_tier_positions[0] if self.weapon_open_tier_positions else 0.0

@dataclass(frozen=True, slots=True)
class BenchRails:
    max_map_tier: int | None = 10
    unknown_tier_allowed: bool = False
    excluded_cost_currencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JewelRails:
    """Day-1 regular rare jewels (rulebook `j-regular`, #434): at most `count_max` jewels of `lines` useful line each."""

    count_max: int = 2
    lines: int = 1


@dataclass(frozen=True, slots=True)
class ClusterRails:
    """Rare cluster jewels (rulebook `t-cluster`, #433): sizes, passives per size, caps. Day 1 has none (#602: count_max 0)."""

    count_max: int = 0
    sizes: list[str] = field(default_factory=list)
    passives: Mapping[str, int] = field(default_factory=lambda: {"large": 0, "medium": 0})
    notables_max: int = 2
    screen_keep: int = 6


@dataclass(frozen=True, slots=True)
class FlaskRails:
    """Day-1 flasks (rulebook `o-flasks` / `o-tinctures`, #436): `slots` flask slots; tinctures allowed. Item level and base level are the common rails (`item_level`, `wishlist.base_level_max`), never a copy."""

    slots: int = 5
    tinctures: bool = True
    flask_utility_crafting: bool = True  # #1162: false on day 1 (rails_default.json gear.flasks): no utility flask is crafted, only Life / Mana / Hybrid


@dataclass(frozen=True, slots=True)
class GearRails:
    max_explicit_mods: int = 6
    max_prefixes: int = 3
    max_suffixes: int = 3
    item_level: int = 70  # the loot path's flat item level (D19); the wishlist path reads `wishlist.item_level`
    quality: int = 20
    max_uniques: int = 2
    influence_allowed: bool = False
    loot_best_of_n: int = 200  # day-1 realism: best of N random rares per slot (D19)
    construction_best_of_n: int = 200  # the two construction rolls only: the spread is born in that loot (2026-09-18), rails_default.json says the numbers
    wishlist: WishlistRails = field(default_factory=WishlistRails)  # the template-driven alternative (D79)
    bench: BenchRails = field(default_factory=BenchRails)
    jewels: JewelRails = field(default_factory=JewelRails)
    clusters: ClusterRails = field(default_factory=ClusterRails)
    flasks: FlaskRails = field(default_factory=FlaskRails)
    weapon_forbidden_lines: tuple[str, ...] = ()  # #1152: the line text (after the "+N") a Weapon 1 / Weapon 2 rare never carries; rails_default.json says which
    excluded_bases: frozenset[str] = frozenset()  # #1154: the base names (case-folded) the loaded loadout never offers to a slot; `gear.bases_excluded_by_loadout` of rails_default.json, picked by `Rails.load(loadout=)`


@dataclass(frozen=True, slots=True)
class GemRails:
    """Day-1 gems: the reference builds run level 17-19 gems with 0 quality
    (main skill occasionally Q7-20 from vendor recipes). 20/20 everywhere
    inflated Cold DoT by ~70% before this rail existed (D23)."""

    level: int = 18
    quality: int = 0
    main_quality: int = 0
    main_link_max: int = 5  # gm-links: one group of 5 (1 active + 4 supports) ...
    other_link_max: int = 4  # ... every other group at most 4


@dataclass(frozen=True, slots=True)
class AnointRails:
    """Anointment oils (#432): the highest oil a build may use; rulebook entry t-anoint, day1."""

    oil_max: str = "Black"


@dataclass(frozen=True, slots=True)
class MovementRails:
    """The movement pair every build carries (#1153; the owner's word): one `spell` (Dash, Frostblink, Flame Dash) and one
    `skill` (Shield Charge only with a shield in Weapon 2, or Leap Slam), `forbidden` in both slots (Smoke Mine, Lightning
    Warp). Leap Slam (`skill_links_for`) is linked with `skill_links` when an item has `skill_link_sockets` free linked sockets, else alone; the other skill stands alone. A
    `skill_skip_weapon` build whose Leap Slam "Attack Time" is at least `skill_skip_attack_time_s` skips the skill. A
    transfigured variant belongs to its base gem's slot (rulebook gm-transfigured). The lists are rails_default.json's."""

    spell: tuple[str, ...] = ()
    skill: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    shield_only: tuple[str, ...] = ()
    skill_links: tuple[str, ...] = ()
    skill_links_for: tuple[str, ...] = ()
    skill_link_sockets: int = 3
    skill_skip_weapon: str = ""
    skill_skip_attack_time_s: float | None = None


def _movement_rails(utilities: Mapping[str, object]) -> MovementRails:
    names = lambda key: tuple(str(n) for n in (utilities.get(key) or ()))  # noqa: E731
    skip = utilities.get("movement_skill_skip_attack_time_s")
    return MovementRails(
        spell=names("movement_spell"), skill=names("movement_skill"), forbidden=names("movement_forbidden"),
        shield_only=names("movement_skill_needs_shield"), skill_links=names("movement_skill_links"), skill_links_for=names("movement_skill_links_for"),
        skill_link_sockets=int(utilities.get("movement_skill_link_sockets", 3)),
        skill_skip_weapon=str(utilities.get("movement_skill_skip_weapon") or ""),
        skill_skip_attack_time_s=float(skip) if skip is not None else None,
    )


@dataclass(frozen=True, slots=True)
class Rails:
    name: str = "day1_yellow_maps"
    loadout: str = "day1"  # which loadout's per-loadout rails (today only `gear.bases_excluded_by_loadout`) this object carries (#1154)
    level: int = 77
    bandit: str = "None"  # PoB's bandit choice; "None" = killed them all, the two passive points (the user's rail, 2026-09-18)
    pantheon_major: str | None = "None"  # PoB's major god; "None" = no god (rulebook c-pantheon: no Pantheon on day 1, #392); None (JSON null) = the optimizer chooses
    pantheon_minor: str | None = "None"  # PoB's minor god; same convention as pantheon_major
    passive_points: int = 107
    ascendancy_points: int = 8  # four labyrinths by the time of the references
    life_floor: float = 3700.0
    max_hit_floors: Mapping[str, float] = field(default_factory=dict)  # {<Type>MaximumHitTaken: floor}: the bossing defence rail (D53)
    elemental_resist_floor: float = 75.0
    chaos_resist_floor: float | None = None
    movement_speed_floor: float | None = 1.2  # PoB EffectiveMovementSpeedMod; reference lower quartile (D28)
    sustain_factor: float = 0.85  # regen + leech + recoup must cover this share of per-second cost, per resource (D31)
    idle_recovery_factor: float = 0.0  # net life + ES recovery without leech or recoup, as a share of the life pool: no degen while idle (2026-09-18, replaces D34's -100/s)
    unique_availability: tuple[str, ...] = ("core",)  # PoB "Source:" classes a day-1 build may use (D31)
    unique_max_req_level: int = 70
    unique_allowed_tiers: tuple[int, ...] = (3, 4, 5)  # wiki drop-rate tiers; None (no data) passes when the class is allowed (D31)
    mom_hit_fraction: float = 0.8  # f of MoMCastsAfterMaxHit (#608): the share of PhysicalMaximumHitTaken the rail takes through Mind over Matter
    extra_floors: Mapping[str, float] = field(default_factory=dict)  # any other floor from rails_default.json "floors" (expressions with "+" allowed)
    utility_max_groups: int = 4  # utility socket groups besides the main link (D35)
    movement_skill_required: bool = True
    movement: MovementRails = field(default_factory=MovementRails)  # the movement spell + skill pair, outside utility_max_groups (#1153)
    fill_step: bool = True  # the fill step after the utility pick (#1156): free sockets get the gems PoB counts, outside utility_max_groups
    fill_min_gain: float = 0.005  # a fill gem is kept when TotalEHP or the objective rises by at least this share
    fill_max_objective_loss: float = 0.001  # ... and the objective falls by at most this share
    mana_cost_buffer: float = 1.0  # unreserved mana must cover cost * buffer
    ramp_seconds: float | None = 2.5  # ceiling on seconds of attacking until the build reaches ramp_fraction of its PoB DPS (D39)
    ramp_fraction: float = 0.8
    ramp_seconds_by_component: Mapping[str, float] = field(default_factory=dict)  # {"poison": 4.0}: components whose mechanic is the ramp get more (D43)
    gear: GearRails = field(default_factory=GearRails)
    gems: GemRails = field(default_factory=GemRails)
    anoint: AnointRails = field(default_factory=AnointRails)
    assumptions: Mapping[str, float] = field(default_factory=dict)  # numeric config defaults, see rails_default.json
    dps_target: float | None = 375_000.0  # informational; never a cross-skill objective
    forbidden_node_text: tuple[str, ...] = ()  # regexes over passive lines the tree never allocates (conditional accuracy; rails_default.json "tree")
    attribute_plus30_nodes_max: int | None = None  # rulebook t-nodes: +30 attribute nodes the tree may take; 1 on day-1 (rails_default.json "tree"), None = no cap (#430)

    @classmethod
    def load(cls, path: Path = DEFAULT_RAILS_PATH, *, loadout: str = "day1") -> "Rails":
        raw = json.loads(path.read_text(encoding="utf-8"))
        floors, gear, gems = raw.get("floors", {}), raw.get("gear", {}), raw.get("gems", {})
        return cls(
            name=str(raw.get("name", "rails")),
            loadout=loadout,
            level=int(raw.get("character", {}).get("level", 77)),
            bandit=str(raw.get("character", {}).get("bandit") or "None"),
            pantheon_major=raw.get("character", {}).get("pantheon_major", "None"),
            pantheon_minor=raw.get("character", {}).get("pantheon_minor", "None"),
            passive_points=max_passive_points(int(raw.get("character", {}).get("level", 77))),
            life_floor=float(floors.get("Life", 3700)),
            max_hit_floors={f"{t}MaximumHitTaken": float(v) for t, v in (floors.get("MaximumHitTaken") or {}).items() if isinstance(v, (int, float))},
            elemental_resist_floor=float(floors.get("elemental_resist_goal", floors.get("elemental_resist_each", 75))),
            chaos_resist_floor=(float(floors["ChaosResist"]) if floors.get("ChaosResist") is not None else None),
            movement_speed_floor=(float(floors["EffectiveMovementSpeedMod"]) if floors.get("EffectiveMovementSpeedMod") is not None else None),
            gear=GearRails(
                item_level=int(gear.get("item_level", 70)),
                max_explicit_mods=int(gear.get("max_explicit_mods_per_rare", 6)),
                max_uniques=int(gear.get("max_uniques", 2)),
                influence_allowed=bool(gear.get("influence_allowed", False)),
                loot_best_of_n=int(gear.get("loot_best_of_n", 200)),
                construction_best_of_n=int(gear.get("construction_best_of_n", 200)),
                wishlist=_wishlist_rails(gear.get("wishlist") or {}),
                bench=_bench_rails(gear.get("bench") or {}),
                jewels=JewelRails(count_max=int((gear.get("jewels") or {}).get("count_max", 2)), lines=int((gear.get("jewels") or {}).get("lines", 1))),
                clusters=_cluster_rails(gear.get("clusters") or {}),
                flasks=FlaskRails(slots=int((gear.get("flasks") or {}).get("slots", 5)), tinctures=bool((gear.get("flasks") or {}).get("tinctures", True)),
                                  flask_utility_crafting=bool((gear.get("flasks") or {}).get("flask_utility_crafting", True))),
                weapon_forbidden_lines=tuple(str(t) for t in (gear.get("weapon_forbidden_lines") or ())),
                excluded_bases=frozenset(str(b).strip().casefold() for b in ((gear.get("bases_excluded_by_loadout") or {}).get(loadout) or ())),
            ),
            gems=GemRails(level=int(gems.get("level", 18)), quality=int(gems.get("quality", 0)), main_quality=int(gems.get("main_skill_quality", 0)), main_link_max=int(gems.get("main_link_max", 5)), other_link_max=int(gems.get("other_link_max", 4))),
            anoint=AnointRails(oil_max=str((raw.get("anoint") or {}).get("oil_max", AnointRails.oil_max))),
            assumptions={**{k: float(v) for k, v in raw.get("assumptions", {}).items() if isinstance(v, (int, float))},
                         **({"ramp_seconds": float(raw["ramp"]["seconds_to_full_dps"])} if raw.get("ramp", {}).get("seconds_to_full_dps") is not None else {})},
            sustain_factor=float(raw.get("sustain", {}).get("recovery_over_cost", 0.85)),
            idle_recovery_factor=float(raw.get("sustain", {}).get("idle_recovery_over_life", 0.0)),
            unique_availability=tuple(raw.get("uniques", {}).get("allowed_availability", ["core"])),
            unique_max_req_level=int(raw.get("uniques", {}).get("max_req_level", 70)),
            unique_allowed_tiers=tuple(int(t) for t in raw.get("uniques", {}).get("allowed_tiers", [3, 4, 5])),
            ramp_seconds=(float(raw["ramp"]["seconds_to_full_dps"]) if raw.get("ramp", {}).get("seconds_to_full_dps") is not None else None),
            ramp_fraction=float(raw.get("ramp", {}).get("fraction_of_full_dps", 0.8)),
            ramp_seconds_by_component={str(k): float(v) for k, v in (raw.get("ramp", {}).get("seconds_by_component") or {}).items()},
            extra_floors={k: float(v) for k, v in floors.items() if isinstance(v, (int, float)) and k not in ("Life", "TotalEHP", "MaximumHitTaken", "elemental_resist_each", "elemental_resist_goal", "ChaosResist", "EffectiveMovementSpeedMod", HIT_FRACTION_KEY)},
            mom_hit_fraction=float(floors.get(HIT_FRACTION_KEY, 0.8)),
            utility_max_groups=int(raw.get("utilities", {}).get("max_groups", 4)),
            movement_skill_required=bool(raw.get("utilities", {}).get("movement_skill_required", True)),
            movement=_movement_rails(raw.get("utilities", {})),
            fill_step=bool(raw.get("utilities", {}).get("fill_step", True)),
            fill_min_gain=float(raw.get("utilities", {}).get("fill_min_gain", 0.005)),
            fill_max_objective_loss=float(raw.get("utilities", {}).get("fill_max_objective_loss", 0.001)),
            dps_target=(float(raw.get("targets", {}).get("CombinedDPS")) if raw.get("targets") else None),
            forbidden_node_text=tuple(str(t) for t in (raw.get("tree", {}).get("forbidden_text") or [])),
            attribute_plus30_nodes_max=(int(raw["tree"]["attribute_plus30_nodes_max"]) if raw.get("tree", {}).get("attribute_plus30_nodes_max") is not None else None),
        )

    def unique_allowed(self, record: Mapping[str, object]) -> bool:
        """A uniques-corpus record passes the day-1 rails: availability class, level, drop-rate tier."""

        if record.get("availability", "core") not in self.unique_availability:
            return False
        if int(record.get("req_level") or 0) > self.unique_max_req_level:
            return False
        tier = record.get("tier")
        return tier is None or int(tier) in self.unique_allowed_tiers

    def bench_allowed(self, row: Mapping[str, object]) -> bool:
        return bench_unlock_legal(
            row.get("unlock"),
            max_map_tier=self.gear.bench.max_map_tier,
            unknown_tier_allowed=self.gear.bench.unknown_tier_allowed,
            excluded_cost_currencies=self.gear.bench.excluded_cost_currencies,
        )

    def objective(self, *, maximize: str = "CombinedDPS", extra_floors: Mapping[str, float] | None = None, forced_keystones: Iterable[str] = ()) -> Objective:
        floors: dict[str, float] = {
            life_floor_key(forced_keystones): self.life_floor,  # #1044: EnergyShield when Chaos Inoculation is forced
            **self.max_hit_floors,  # bossing defence: maximum hit taken per damage type (D53), never TotalEHP
        }
        if self.chaos_resist_floor is not None:
            floors["ChaosResist"] = self.chaos_resist_floor
        if self.movement_speed_floor is not None:
            floors["EffectiveMovementSpeedMod"] = self.movement_speed_floor
        floors.update(self.extra_floors)
        if extra_floors:
            floors.update(extra_floors)
        ctx = RampContext(fraction=self.ramp_fraction, seconds=self.ramp_seconds, seconds_by_component=dict(self.ramp_seconds_by_component)) if self.ramp_seconds is not None else None
        return Objective(
            maximize=maximize,
            floors=floors,
            # self-cost lines (Chaos Mastery, a life-paying support) enter the idle-recovery relation by name;
            # MoMCastsAfterMaxHit is far above its floor unless Mind over Matter (or another "damage taken from mana") is on
            derived=(*((ramp_stat(ctx), ramp_budget_stat(ctx), ramp_stages_stat(ctx)) if ctx is not None else ()), self_cost_stat(), mom_casts_stat(self.mom_hit_fraction), energy_shield_recharge_for_costs_stat(), mana_cost_pool_stat(), mana_over_reserved_stat(), *(sustain_cost_stat(r) for r in SUSTAIN_RESOURCES)),
            relations=(
                *((RAMP_RELATION,) if ctx is not None else ()),
                *ELEMENTAL_RESIST_RELATIONS,
                ("Str", "ReqStr", 1.0),
                ("Dex", "ReqDex", 1.0),
                ("Int", "ReqInt", 1.0),
                # The selected main skill remains live during every PoB trial;
                # `with_castability_floors` adds the frozen maximum for the
                # other enabled player skills.
                # The mana pool itself is never reserved past zero: `ManaOverReserved` is 0 while the
                # pool is whole, so this relation is exactly `ManaUnreserved >= 0`, on every build,
                # Eldritch Battery or not, and with no relaxation for a build that pays nothing from
                # mana (#171, finding 1 of #155). PoB warns on the same number ("Your unreserved Mana
                # is negative", Modules/BuildDisplayStats.lua:130); the cost relation below keeps
                # pricing EnergyShield into the pool, because that is about the COST of a skill.
                ("ManaUnreserved", MANA_OVER_RESERVED_STAT, 1.0, "Mana"),
                (MANA_COST_POOL_STAT, "ManaCost", 1.0, "Mana"),
                ("LifeUnreserved", "LifeCost", 1.0, "Life"),
                # no degen while idle: what the build recovers per second when it is NOT hitting -- regen
                # only, no leech, no recoup, minus the self-costs PoB does not count -- may not be negative
                # (2026-09-18, replacing D34's -100/s). The life pool is the scale of the shortfall, so
                # -12/s is 0.003 and -1,316/s is 0.33, not 12 and 1,316 against a floor of zero
                (f"NetLifeRegen+NetEnergyShieldRegen+{SELF_COST_STAT}", "Life", self.idle_recovery_factor, "Life"),
                # sustain: what the build recovers per second must cover its per-second cost, for every resource it spends;
                # the cost side is PoB's <resource>PerSecondCost, a totem skill's own cost per totem lifetime instead (#808)
                ("ManaRegenRecovery+ManaLeechGainRate+ManaRecoup", sustain_cost_stat_name("Mana"), self.sustain_factor),
                ("LifeRegenRecovery+LifeLeechGainRate+LifeRecoup", sustain_cost_stat_name("Life"), self.sustain_factor),
                ("EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts", sustain_cost_stat_name("ES"), self.sustain_factor),
            ),
        )


# PoB's own table (Modules/Build.lua `acts`, from poewiki Passive_skill): quest passive points by the act a
# character of that level has reached. Points = level - 1 + quest points + ExtraPoints (killing every
# bandit: PoB's mainOutput.ExtraPoints). The first rails budget was 107 at level 77, the median of the
# references' nodes counted with their ascendancy; the allocatable median is 100 and PoB's formula gives
# 99 with a bandit reward, 100 with none. Every search build before 2026-09-14 carried 7-8 points too many.
_QUEST_POINTS = ((1, 0), (12, 2), (22, 4), (32, 6), (40, 7), (44, 9), (50, 12), (54, 15), (60, 18), (64, 20), (67, 23))


def max_passive_points(level: int, extra: int = 0) -> int:
    """Passive points a character of this level can have allocated (PoB's rule)."""

    quest = 0
    for at_level, points in _QUEST_POINTS:
        if level >= at_level:
            quest = points
    return max(0, int(level) - 1 + quest + int(extra))


__all__ = ["max_passive_points", "Rails", "GearRails", "GemRails", "AnointRails", "WishlistRails", "BenchRails", "DEFAULT_RAILS_PATH"]
