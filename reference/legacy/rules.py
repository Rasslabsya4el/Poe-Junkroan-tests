"""Fresh rule objects for the reboot MVP."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ItemRuleSet:
    """Simple item limits for the new build generator."""

    max_item_level: int = 75
    max_explicit_mods: int = 2
    allowed_mod_pools: list[str] = field(default_factory=lambda: ["base"])
    item_realism_floor: float = 50.0


@dataclass(slots=True)
class LaneRuleSet:
    """Simple lane limits for the new reboot MVP."""

    max_character_level: int = 90
    boss_target: str = "pinnacle"
    allow_flasks: bool = False
    allow_influenced_items: bool = False


@dataclass(slots=True)
class RebootRules:
    """Top-level rules object passed through the new pipeline."""

    lane: LaneRuleSet = field(default_factory=LaneRuleSet)
    items: ItemRuleSet = field(default_factory=ItemRuleSet)


@dataclass(frozen=True, slots=True)
class MechanicCondition:
    """Single boolean condition evaluated against a standardized skill row."""

    field_names: tuple[str, ...]
    operator: str
    expected_text: str | None = None
    expected_number: float | None = None


@dataclass(frozen=True, slots=True)
class MechanicConcept:
    """Named ontology concept used as either a primary family or additive tag."""

    concept_id: str
    concept_type: str
    label: str
    description: str
    coverage_tier: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class MechanicRule:
    """Rule that maps standardized skill rows onto ontology concepts."""

    rule_id: str
    concept_id: str
    role: str
    priority: int
    description: str
    sort_order: int
    conditions: tuple[MechanicCondition, ...]


@dataclass(frozen=True, slots=True)
class SkillMechanicsRuleSet:
    """First-pass mechanic ontology rules built on top of standardized skill rows."""

    concepts: tuple[MechanicConcept, ...]
    rules: tuple[MechanicRule, ...]


@dataclass(frozen=True, slots=True)
class ScalingRoute:
    """Single delivery route that a skill can plausibly use in the reboot MVP."""

    route_id: str
    label: str
    description: str
    delivery_kind: str
    sort_order: int
    conditions: tuple[MechanicCondition, ...]
    native_delivery_fields: tuple[str, ...] = ()
    support_enabled_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScalingVector:
    """Single scaling knob scored against a skill plus delivery route pair."""

    vector_id: str
    label: str
    description: str
    probe_value: float
    probe_unit: str
    score_handler: str
    sort_order: int
    allowed_route_ids: tuple[str, ...] = ()
    mechanic_family_id: str | None = None
    conditions: tuple[MechanicCondition, ...] = ()
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MechanicPackage:
    """Special mechanic overlay that can add or subtract score from a vector."""

    package_id: str
    label: str
    description: str
    package_handler: str
    sort_order: int
    eligible_route_ids: tuple[str, ...] = ()
    mechanic_family_id: str | None = None
    conditions: tuple[MechanicCondition, ...] = ()
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MechanicFamily:
    """Shared family for special mechanic overlays that need explicit scoring rules."""

    family_id: str
    label: str
    description: str
    adjustment_handler: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class SkillScalingRuleSet:
    """Declarative route, vector, mechanic-family, and package catalogs for skill scoring."""

    routes: tuple[ScalingRoute, ...]
    vectors: tuple[ScalingVector, ...]
    families: tuple[MechanicFamily, ...]
    packages: tuple[MechanicPackage, ...]


def _truthy(field_name: str) -> MechanicCondition:
    return MechanicCondition(field_names=(field_name,), operator="truthy")


def _any_truthy(*field_names: str) -> MechanicCondition:
    return MechanicCondition(field_names=tuple(field_names), operator="any_truthy")


def _non_null(field_name: str) -> MechanicCondition:
    return MechanicCondition(field_names=(field_name,), operator="non_null")


def _any_non_null(*field_names: str) -> MechanicCondition:
    return MechanicCondition(field_names=tuple(field_names), operator="any_non_null")


def _eq_text(field_name: str, expected_text: str) -> MechanicCondition:
    return MechanicCondition(field_names=(field_name,), operator="eq_text", expected_text=expected_text)


def _eq_number(field_name: str, expected_number: float) -> MechanicCondition:
    return MechanicCondition(field_names=(field_name,), operator="eq_number", expected_number=expected_number)


def _gt_number(field_name: str, expected_number: float) -> MechanicCondition:
    return MechanicCondition(field_names=(field_name,), operator="gt_number", expected_number=expected_number)


def default_skill_mechanics_rule_set() -> SkillMechanicsRuleSet:
    """Return the baseline ontology rules for the reboot numeric skill reports."""

    concepts = (
        MechanicConcept(
            concept_id="minion_shell",
            concept_type="primary_family",
            label="Minion Shell",
            description="Skills that primarily create or drive minion actors.",
            coverage_tier="numeric_shell",
            sort_order=10,
        ),
        MechanicConcept(
            concept_id="dot_payload_shell",
            concept_type="primary_family",
            label="DoT Payload Shell",
            description="Skills whose first useful numeric shell is a direct damage-over-time payload.",
            coverage_tier="numeric_shell",
            sort_order=20,
        ),
        MechanicConcept(
            concept_id="spell_hit_shell",
            concept_type="primary_family",
            label="Spell Hit Shell",
            description="Spell skills that expose an added-damage delivery shell from skill timing.",
            coverage_tier="numeric_shell",
            sort_order=30,
        ),
        MechanicConcept(
            concept_id="attack_hit_shell",
            concept_type="primary_family",
            label="Attack Hit Shell",
            description="Attack skills that expose added-damage or base-multiplier delivery surfaces.",
            coverage_tier="numeric_shell",
            sort_order=40,
        ),
        MechanicConcept(
            concept_id="reservation_utility",
            concept_type="primary_family",
            label="Reservation Utility",
            description="Reservation-based utility skills such as auras, banners, and blessings.",
            coverage_tier="utility_shell",
            sort_order=50,
        ),
        MechanicConcept(
            concept_id="curse_utility",
            concept_type="primary_family",
            label="Curse Utility",
            description="Hexes, marks, and other curse-delivery utility skills.",
            coverage_tier="utility_shell",
            sort_order=60,
        ),
        MechanicConcept(
            concept_id="warcry_utility",
            concept_type="primary_family",
            label="Warcry Utility",
            description="Warcry skills that mostly act as utility shells rather than direct numeric payloads.",
            coverage_tier="utility_shell",
            sort_order=70,
        ),
        MechanicConcept(
            concept_id="movement_utility",
            concept_type="primary_family",
            label="Movement Utility",
            description="Travel, blink, and movement skills whose value is primarily positional.",
            coverage_tier="utility_shell",
            sort_order=80,
        ),
        MechanicConcept(
            concept_id="proxy_utility",
            concept_type="primary_family",
            label="Proxy Utility",
            description="Skills primarily delivered through brands, traps, mines, or totems without a clean first-pass shell.",
            coverage_tier="utility_shell",
            sort_order=90,
        ),
        MechanicConcept(
            concept_id="triggered_or_buff_utility",
            concept_type="primary_family",
            label="Triggered or Buff Utility",
            description="Buff-centric or trigger-centric skills that still need a deeper mechanics overlay.",
            coverage_tier="utility_shell",
            sort_order=100,
        ),
        MechanicConcept(
            concept_id="projectile_delivery",
            concept_type="mechanic_tag",
            label="Projectile Delivery",
            description="Carries projectile-oriented delivery geometry or counts.",
            coverage_tier="tag",
            sort_order=110,
        ),
        MechanicConcept(
            concept_id="area_geometry",
            concept_type="mechanic_tag",
            label="Area Geometry",
            description="Carries a meaningful area radius or area length signal.",
            coverage_tier="tag",
            sort_order=120,
        ),
        MechanicConcept(
            concept_id="duration_window",
            concept_type="mechanic_tag",
            label="Duration Window",
            description="Carries a base duration window that will matter for uptime or stacking models.",
            coverage_tier="tag",
            sort_order=130,
        ),
        MechanicConcept(
            concept_id="cooldown_gated",
            concept_type="mechanic_tag",
            label="Cooldown Gated",
            description="Has a cooldown gate or explicit cooldown type flag.",
            coverage_tier="tag",
            sort_order=140,
        ),
        MechanicConcept(
            concept_id="proxy_delivery",
            concept_type="mechanic_tag",
            label="Proxy Delivery",
            description="Delivered through a proxy subsystem such as brands, traps, mines, or totems.",
            coverage_tier="tag",
            sort_order=150,
        ),
        MechanicConcept(
            concept_id="reservation",
            concept_type="mechanic_tag",
            label="Reservation",
            description="Consumes or modifies a reservation-style resource lane.",
            coverage_tier="tag",
            sort_order=160,
        ),
        MechanicConcept(
            concept_id="movement",
            concept_type="mechanic_tag",
            label="Movement",
            description="Acts as a movement, blink, or travel tool.",
            coverage_tier="tag",
            sort_order=170,
        ),
        MechanicConcept(
            concept_id="triggerable",
            concept_type="mechanic_tag",
            label="Triggerable",
            description="Supports instant or trigger-style delivery semantics.",
            coverage_tier="tag",
            sort_order=180,
        ),
        MechanicConcept(
            concept_id="added_damage_surface",
            concept_type="mechanic_tag",
            label="Added Damage Surface",
            description="Exposes a level-20 added-damage delivery coefficient.",
            coverage_tier="tag",
            sort_order=190,
        ),
        MechanicConcept(
            concept_id="base_multiplier_surface",
            concept_type="mechanic_tag",
            label="Base Multiplier Surface",
            description="Exposes a level-20 base-multiplier delivery coefficient.",
            coverage_tier="tag",
            sort_order=200,
        ),
        MechanicConcept(
            concept_id="dot_surface",
            concept_type="mechanic_tag",
            label="DoT Surface",
            description="Exposes a level-20 raw DoT payload in the standardized DB.",
            coverage_tier="tag",
            sort_order=210,
        ),
    )

    rules = (
        MechanicRule(
            rule_id="primary_minion_shell",
            concept_id="minion_shell",
            role="primary",
            priority=10,
            description="Active minion-creating skills are classified as minion shells first.",
            sort_order=10,
            conditions=(_truthy("flag_type_createsminion"),),
        ),
        MechanicRule(
            rule_id="primary_dot_payload_shell",
            concept_id="dot_payload_shell",
            role="primary",
            priority=20,
            description="Direct damage-over-time skills with a level-20 payload become DoT shells.",
            sort_order=20,
            conditions=(
                _truthy("flag_type_damageovertime"),
                _non_null("l20_dot_total"),
            ),
        ),
        MechanicRule(
            rule_id="primary_spell_hit_shell",
            concept_id="spell_hit_shell",
            role="primary",
            priority=30,
            description="Spell skills with an added-damage delivery surface become spell hit shells.",
            sort_order=30,
            conditions=(
                _truthy("flag_type_spell"),
                _non_null("l20_added_damage_delivery_coef"),
            ),
        ),
        MechanicRule(
            rule_id="primary_attack_hit_shell",
            concept_id="attack_hit_shell",
            role="primary",
            priority=40,
            description="Attack skills with added-damage or base-multiplier delivery become attack hit shells.",
            sort_order=40,
            conditions=(
                _truthy("flag_type_attack"),
                _any_non_null("l20_added_damage_delivery_coef", "l20_base_multiplier_delivery_coef"),
            ),
        ),
        MechanicRule(
            rule_id="primary_reservation_utility",
            concept_id="reservation_utility",
            role="primary",
            priority=50,
            description="Reservation-style utility skills get their own primary family.",
            sort_order=50,
            conditions=(
                _any_truthy(
                    "flag_type_aura",
                    "flag_type_hasreservation",
                    "flag_type_canhaveblessing",
                    "flag_type_banner",
                ),
            ),
        ),
        MechanicRule(
            rule_id="primary_curse_utility",
            concept_id="curse_utility",
            role="primary",
            priority=60,
            description="Curse delivery skills are classified as curse utility.",
            sort_order=60,
            conditions=(
                _any_truthy("flag_type_appliescurse", "flag_type_hex", "flag_type_mark"),
            ),
        ),
        MechanicRule(
            rule_id="primary_warcry_utility",
            concept_id="warcry_utility",
            role="primary",
            priority=70,
            description="Warcries remain utility-first in the numeric ontology.",
            sort_order=70,
            conditions=(_truthy("flag_type_warcry"),),
        ),
        MechanicRule(
            rule_id="primary_movement_utility",
            concept_id="movement_utility",
            role="primary",
            priority=80,
            description="Movement, travel, and blink skills become movement utility shells.",
            sort_order=80,
            conditions=(
                _any_truthy("flag_type_movement", "flag_type_travel", "flag_type_blink"),
            ),
        ),
        MechanicRule(
            rule_id="primary_proxy_utility",
            concept_id="proxy_utility",
            role="primary",
            priority=90,
            description="Proxy-delivered skills without a stronger shell become proxy utility.",
            sort_order=90,
            conditions=(
                _any_truthy(
                    "flag_type_brand",
                    "flag_type_summonstotem",
                    "flag_type_remotemined",
                    "flag_type_trapped",
                ),
            ),
        ),
        MechanicRule(
            rule_id="primary_triggered_or_buff_utility",
            concept_id="triggered_or_buff_utility",
            role="primary",
            priority=100,
            description="Buff or trigger-centric active skills remain utility-first until a deeper mechanics layer exists.",
            sort_order=100,
            conditions=(
                _any_truthy("flag_type_buff", "flag_type_triggerable", "flag_type_instant", "flag_type_cooldown"),
            ),
        ),
        MechanicRule(
            rule_id="tag_projectile_delivery_from_type",
            concept_id="projectile_delivery",
            role="tag",
            priority=10,
            description="Projectile tag from skill type.",
            sort_order=110,
            conditions=(
                _any_truthy("flag_type_projectile"),
            ),
        ),
        MechanicRule(
            rule_id="tag_projectile_delivery_from_counts",
            concept_id="projectile_delivery",
            role="tag",
            priority=11,
            description="Projectile tag from explicit projectile counts.",
            sort_order=111,
            conditions=(
                _any_non_null(
                    "l20_projectile_count",
                    "l20_arrow_count",
                    "l20_chain_count",
                    "l20_split_projectile_count",
                    "l20_pierce_count",
                ),
            ),
        ),
        MechanicRule(
            rule_id="tag_area_geometry",
            concept_id="area_geometry",
            role="tag",
            priority=20,
            description="Area tag from radius or length signals.",
            sort_order=120,
            conditions=(
                _any_non_null("l20_aoe_radius_best", "l20_aoe_length"),
            ),
        ),
        MechanicRule(
            rule_id="tag_duration_window_from_type",
            concept_id="duration_window",
            role="tag",
            priority=30,
            description="Duration tag from duration skill type.",
            sort_order=130,
            conditions=(
                _any_truthy("flag_type_duration"),
            ),
        ),
        MechanicRule(
            rule_id="tag_duration_window_from_values",
            concept_id="duration_window",
            role="tag",
            priority=31,
            description="Duration tag from explicit duration fields.",
            sort_order=131,
            conditions=(
                _any_non_null("l20_duration_primary", "l20_duration_secondary"),
            ),
        ),
        MechanicRule(
            rule_id="tag_cooldown_gated_from_type",
            concept_id="cooldown_gated",
            role="tag",
            priority=40,
            description="Cooldown tag from cooldown skill type.",
            sort_order=140,
            conditions=(
                _any_truthy("flag_type_cooldown"),
            ),
        ),
        MechanicRule(
            rule_id="tag_cooldown_gated_from_value",
            concept_id="cooldown_gated",
            role="tag",
            priority=41,
            description="Cooldown tag from explicit cooldown data.",
            sort_order=141,
            conditions=(
                _non_null("l20_cooldown"),
            ),
        ),
        MechanicRule(
            rule_id="tag_proxy_delivery",
            concept_id="proxy_delivery",
            role="tag",
            priority=50,
            description="Proxy tag from brands, traps, mines, or totems.",
            sort_order=150,
            conditions=(
                _any_truthy(
                    "flag_type_brand",
                    "flag_type_summonstotem",
                    "flag_type_remotemined",
                    "flag_type_trapped",
                ),
            ),
        ),
        MechanicRule(
            rule_id="tag_reservation",
            concept_id="reservation",
            role="tag",
            priority=60,
            description="Reservation tag from aura, banner, blessing, or reservation flags.",
            sort_order=160,
            conditions=(
                _any_truthy(
                    "flag_type_aura",
                    "flag_type_hasreservation",
                    "flag_type_canhaveblessing",
                    "flag_type_banner",
                ),
            ),
        ),
        MechanicRule(
            rule_id="tag_movement",
            concept_id="movement",
            role="tag",
            priority=70,
            description="Movement tag from movement-oriented skill types.",
            sort_order=170,
            conditions=(
                _any_truthy("flag_type_movement", "flag_type_travel", "flag_type_blink"),
            ),
        ),
        MechanicRule(
            rule_id="tag_triggerable",
            concept_id="triggerable",
            role="tag",
            priority=80,
            description="Triggerable tag from instant or triggerable delivery flags.",
            sort_order=180,
            conditions=(
                _any_truthy("flag_type_triggerable", "flag_type_instant"),
            ),
        ),
        MechanicRule(
            rule_id="tag_added_damage_surface",
            concept_id="added_damage_surface",
            role="tag",
            priority=90,
            description="Added-damage surface tag from the level-20 delivery coefficient.",
            sort_order=190,
            conditions=(_non_null("l20_added_damage_delivery_coef"),),
        ),
        MechanicRule(
            rule_id="tag_base_multiplier_surface",
            concept_id="base_multiplier_surface",
            role="tag",
            priority=100,
            description="Base-multiplier surface tag from the level-20 delivery coefficient.",
            sort_order=200,
            conditions=(_non_null("l20_base_multiplier_delivery_coef"),),
        ),
        MechanicRule(
            rule_id="tag_dot_surface",
            concept_id="dot_surface",
            role="tag",
            priority=110,
            description="DoT surface tag from the level-20 raw DoT payload.",
            sort_order=210,
            conditions=(_non_null("l20_dot_total"),),
        ),
    )

    return SkillMechanicsRuleSet(concepts=concepts, rules=rules)


def default_skill_scaling_rule_set() -> SkillScalingRuleSet:
    """Return the baseline route-aware scaling catalogs for the reboot skill scorer."""

    routes = (
        ScalingRoute(
            route_id="self_cast",
            label="Self Cast",
            description="Direct spell casting without a proxy delivery layer.",
            delivery_kind="direct",
            sort_order=10,
            conditions=(_truthy("flag_type_spell"),),
        ),
        ScalingRoute(
            route_id="self_attack",
            label="Self Attack",
            description="Direct attack use from the player without a proxy delivery layer.",
            delivery_kind="direct",
            sort_order=20,
            conditions=(_truthy("flag_type_attack"),),
        ),
        ScalingRoute(
            route_id="trigger",
            label="Trigger",
            description="Triggered delivery route for triggerable skills that do not block trigger supports.",
            delivery_kind="trigger",
            sort_order=30,
            conditions=(
                _any_truthy("flag_type_triggerable", "flag_type_instant"),
                _eq_number("flag_type_disallowtriggersupports", 0),
            ),
        ),
        ScalingRoute(
            route_id="mine",
            label="Mine",
            description="Mine-supported delivery route for skills that can be laid as mines.",
            delivery_kind="proxy",
            sort_order=40,
            conditions=(_any_truthy("flag_type_mineable", "flag_type_remotemined"),),
            native_delivery_fields=("flag_type_remotemined",),
            support_enabled_fields=("flag_type_mineable",),
        ),
        ScalingRoute(
            route_id="trap",
            label="Trap",
            description="Trap-supported delivery route for skills that can be thrown as traps.",
            delivery_kind="proxy",
            sort_order=50,
            conditions=(_any_truthy("flag_type_trappable", "flag_type_trapped"),),
            native_delivery_fields=("flag_type_trapped",),
            support_enabled_fields=("flag_type_trappable",),
        ),
        ScalingRoute(
            route_id="totem",
            label="Totem",
            description="Totem or ballista delivery route for skills that can be delegated to a totem actor.",
            delivery_kind="proxy",
            sort_order=60,
            conditions=(_any_truthy("flag_type_totemable", "flag_type_summonstotem"),),
            native_delivery_fields=("flag_type_summonstotem",),
            support_enabled_fields=("flag_type_totemable",),
        ),
        ScalingRoute(
            route_id="brand",
            label="Brand",
            description="Brand delivery route for skills that naturally operate as brands.",
            delivery_kind="proxy",
            sort_order=70,
            conditions=(_truthy("flag_type_brand"),),
            native_delivery_fields=("flag_type_brand",),
        ),
    )

    families = (
        MechanicFamily(
            family_id="shock_effect_family",
            label="Shock Effect",
            description="Special mechanics whose output formula explicitly scales off shock effect on the enemy.",
            adjustment_handler="lightning_conduit_shock_bonus",
            sort_order=10,
        ),
        MechanicFamily(
            family_id="blood_charge_family",
            label="Blood Charge",
            description="Special mechanics whose output formula explicitly scales per sustained blood charge.",
            adjustment_handler="reap_blood_charge_bonus",
            sort_order=20,
        ),
        MechanicFamily(
            family_id="overlap_family",
            label="Overlap Setup",
            description="Special mechanics whose real output depends on geometry and duration overlap breakpoints.",
            adjustment_handler="toxic_rain_overlap_bonus",
            sort_order=30,
        ),
    )

    vectors = (
        ScalingVector(
            vector_id="cast_speed",
            label="Cast Speed",
            description="How much the skill wants more casts per second from its native action time shell.",
            probe_value=10.0,
            probe_unit="% increased cast speed",
            score_handler="cadence_percentile",
            sort_order=10,
            allowed_route_ids=("self_cast", "brand"),
            conditions=(_truthy("flag_type_spell"),),
            source_fields=("uses_per_second_from_skill_time", "raw_action_time_seconds"),
        ),
        ScalingVector(
            vector_id="attack_speed",
            label="Attack Speed",
            description="How much the skill wants more attacks per second from its native action time shell.",
            probe_value=10.0,
            probe_unit="% increased attack speed",
            score_handler="cadence_percentile",
            sort_order=20,
            allowed_route_ids=("self_attack",),
            conditions=(_truthy("flag_type_attack"),),
            source_fields=("uses_per_second_from_skill_time", "raw_action_time_seconds", "l20_attack_speed_multiplier"),
        ),
        ScalingVector(
            vector_id="trap_delivery_rate",
            label="Trap Delivery Rate",
            description="Trap route cadence shell from native action time after the mandatory Trap support throwing-speed transform.",
            probe_value=1.0,
            probe_unit="trap delivery rate",
            score_handler="trap_delivery_rate_percentile",
            sort_order=21,
            allowed_route_ids=("trap",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=(
                "uses_per_second_from_skill_time",
                "raw_action_time_seconds",
                "SupportTrap.l20_trap_throwing_speed",
            ),
        ),
        ScalingVector(
            vector_id="trap_delivery_multiplicity",
            label="Trap Delivery Multiplicity",
            description="Trap route baseline actor-count factor before any optional multi-instance trap supports.",
            probe_value=1.0,
            probe_unit="trap delivery multiplicity factor",
            score_handler="trap_delivery_multiplicity_percentile",
            sort_order=22,
            allowed_route_ids=("trap",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=("uses_per_second_from_skill_time",),
        ),
        ScalingVector(
            vector_id="trap_delivery_penalty",
            label="Trap Delivery Penalty",
            description="Trap route retained damage factor from the mandatory Trap support transform alone.",
            probe_value=1.0,
            probe_unit="trap delivery penalty factor",
            score_handler="trap_delivery_penalty_percentile",
            sort_order=23,
            allowed_route_ids=("trap",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=("SupportTrap.l20_support_trap_damage_final",),
        ),
        ScalingVector(
            vector_id="mine_delivery_rate",
            label="Mine Delivery Rate",
            description="Mine route cadence shell from native action time before any optional mine throw-speed boosters.",
            probe_value=1.0,
            probe_unit="mine delivery rate",
            score_handler="mine_delivery_rate_percentile",
            sort_order=24,
            allowed_route_ids=("mine",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=("uses_per_second_from_skill_time", "raw_action_time_seconds"),
        ),
        ScalingVector(
            vector_id="mine_delivery_multiplicity",
            label="Mine Delivery Multiplicity",
            description="Mine route baseline actor-count factor before any optional multi-instance mine supports.",
            probe_value=1.0,
            probe_unit="mine delivery multiplicity factor",
            score_handler="mine_delivery_multiplicity_percentile",
            sort_order=25,
            allowed_route_ids=("mine",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=("uses_per_second_from_skill_time",),
        ),
        ScalingVector(
            vector_id="mine_delivery_penalty",
            label="Mine Delivery Penalty",
            description="Mine route retained damage factor from the mandatory mine transform alone.",
            probe_value=1.0,
            probe_unit="mine delivery penalty factor",
            score_handler="mine_delivery_penalty_percentile",
            sort_order=26,
            allowed_route_ids=("mine",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=(
                "SupportBlastchainMine.l20_support_gem_mine_damage_final",
                "SupportHighImpactMine.l20_support_remote_mine_damage_final",
                "SupportLocusMine.l20_support_locus_mine_damage_final",
            ),
        ),
        ScalingVector(
            vector_id="totem_delivery_rate",
            label="Totem Delivery Rate",
            description="Totem route cadence shell from native action time before any optional delegated-actor speed boosters.",
            probe_value=1.0,
            probe_unit="totem delivery rate",
            score_handler="totem_delivery_rate_percentile",
            sort_order=27,
            allowed_route_ids=("totem",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=("uses_per_second_from_skill_time", "raw_action_time_seconds"),
        ),
        ScalingVector(
            vector_id="totem_delivery_multiplicity",
            label="Totem Delivery Multiplicity",
            description="Totem route actor-count factor from explicit totem or ballista cap fields.",
            probe_value=1.0,
            probe_unit="totem delivery multiplicity factor",
            score_handler="totem_delivery_multiplicity_percentile",
            sort_order=28,
            allowed_route_ids=("totem",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=(
                "l20_base_number_of_totems_allowed",
                "l20_additional_totems_allowed",
                "l20_additional_ballista_totems_allowed",
            ),
        ),
        ScalingVector(
            vector_id="totem_delivery_penalty",
            label="Totem Delivery Penalty",
            description="Totem route retained damage factor from the mandatory totem transform alone.",
            probe_value=1.0,
            probe_unit="totem delivery penalty factor",
            score_handler="totem_delivery_penalty_percentile",
            sort_order=29,
            allowed_route_ids=("totem",),
            conditions=(_any_truthy("flag_type_spell", "flag_type_attack"), _non_null("uses_per_second_from_skill_time")),
            source_fields=(
                "SupportSpellTotem.l20_support_totem_damage_final",
                "SupportBallistaTotem.l20_support_totem_damage_final",
            ),
        ),
        ScalingVector(
            vector_id="added_spell_damage",
            label="Added Spell Damage",
            description="Affinity for flat added spell damage through the standardized added-damage delivery coefficient.",
            probe_value=100.0,
            probe_unit="flat added spell damage",
            score_handler="added_damage_delivery_percentile",
            sort_order=30,
            allowed_route_ids=("self_cast", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_truthy("flag_type_spell"), _non_null("l20_added_damage_delivery_coef")),
            source_fields=("l20_added_damage_delivery_coef", "l20_damage_effectiveness", "uses_per_second_from_skill_time"),
        ),
        ScalingVector(
            vector_id="added_attack_damage",
            label="Added Attack Damage",
            description="Affinity for flat added attack damage through the standardized added-damage delivery coefficient.",
            probe_value=100.0,
            probe_unit="flat added attack damage",
            score_handler="added_damage_delivery_percentile",
            sort_order=40,
            allowed_route_ids=("self_attack", "trigger", "mine", "trap", "totem"),
            conditions=(_truthy("flag_type_attack"), _non_null("l20_added_damage_delivery_coef")),
            source_fields=("l20_added_damage_delivery_coef", "l20_damage_effectiveness", "uses_per_second_from_skill_time"),
        ),
        ScalingVector(
            vector_id="base_multiplier_attack",
            label="Attack Base Multiplier",
            description="Affinity for attack-side base multiplier scaling exposed in PoB.",
            probe_value=10.0,
            probe_unit="% more base attack damage",
            score_handler="base_multiplier_delivery_percentile",
            sort_order=50,
            allowed_route_ids=("self_attack", "trigger", "mine", "trap", "totem"),
            conditions=(_truthy("flag_type_attack"), _non_null("l20_base_multiplier_delivery_coef")),
            source_fields=("l20_base_multiplier_delivery_coef", "l20_base_multiplier", "uses_per_second_from_skill_time"),
        ),
        ScalingVector(
            vector_id="critical_scaling",
            label="Critical Scaling",
            description="Affinity for crit-oriented scaling from the level-20 base crit shell.",
            probe_value=100.0,
            probe_unit="% increased critical strike chance",
            score_handler="crit_percentile",
            sort_order=60,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_non_null("l20_crit_chance"),),
            source_fields=("l20_crit_chance", "l20_added_damage_delivery_coef", "l20_base_multiplier_delivery_coef"),
        ),
        ScalingVector(
            vector_id="projectile_count",
            label="Projectile Count",
            description="Affinity for extra projectiles or related delivery fan-out on projectile skills.",
            probe_value=1.0,
            probe_unit="extra projectile",
            score_handler="projectile_fanout_percentile",
            sort_order=70,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(
                _any_truthy(
                    "flag_type_projectile",
                    "flag_type_projectilenumber",
                    "flag_type_projectilesfromuser",
                    "flag_type_projectilespeed",
                    "flag_type_rain",
                ),
            ),
            source_fields=("l20_projectile_count", "l20_arrow_count", "l20_split_projectile_count", "l20_chain_count"),
        ),
        ScalingVector(
            vector_id="aoe_radius",
            label="Area Radius",
            description="Affinity for larger area geometry using the best standardized AoE radius signal.",
            probe_value=10.0,
            probe_unit="% increased area of effect",
            score_handler="aoe_radius_percentile",
            sort_order=80,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_non_null("l20_aoe_radius_best"),),
            source_fields=("l20_aoe_radius_best", "l20_aoe_radius_primary", "l20_aoe_radius_secondary"),
        ),
        ScalingVector(
            vector_id="duration_window",
            label="Duration",
            description="Affinity for longer duration windows on skills that keep effects alive over time.",
            probe_value=20.0,
            probe_unit="% increased duration",
            score_handler="duration_percentile",
            sort_order=90,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_any_truthy("flag_type_duration", "flag_type_auraduration"),),
            source_fields=("l20_duration_primary", "l20_duration_secondary"),
        ),
        ScalingVector(
            vector_id="overlap_setup",
            label="Overlap Setup",
            description="Affinity for geometry-plus-duration overlap mechanics that create extra effective hits or pods.",
            probe_value=1.0,
            probe_unit="overlap breakpoint",
            score_handler="mechanic_stub",
            sort_order=95,
            allowed_route_ids=("self_attack", "mine", "trap", "totem"),
            mechanic_family_id="overlap_family",
            conditions=(_eq_text("name", "Toxic Rain"),),
            source_fields=("l20_arrow_count", "l20_duration_primary", "l20_aoe_radius_best", "l20_dot_chaos_total"),
        ),
        ScalingVector(
            vector_id="cooldown_recovery",
            label="Cooldown Recovery",
            description="Affinity for cooldown recovery on skills that are explicitly cooldown-gated.",
            probe_value=10.0,
            probe_unit="% increased cooldown recovery rate",
            score_handler="cooldown_inverse_percentile",
            sort_order=100,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_any_truthy("flag_type_cooldown", "flag_type_dynamiccooldown"),),
            source_fields=("l20_cooldown",),
        ),
        ScalingVector(
            vector_id="shock_effect",
            label="Shock Effect",
            description="Affinity for enemy-shock-effect scaling on skills whose damage formula explicitly references shock effect.",
            probe_value=10.0,
            probe_unit="% increased shock effect on enemy",
            score_handler="mechanic_stub",
            sort_order=105,
            allowed_route_ids=("self_cast", "trigger", "mine", "trap", "totem"),
            mechanic_family_id="shock_effect_family",
            conditions=(_eq_text("name", "Lightning Conduit"),),
            source_fields=("name",),
        ),
        ScalingVector(
            vector_id="generic_dot_scaling",
            label="Generic DoT Scaling",
            description="Affinity for generic damage-over-time scaling from the total raw DoT payload shell.",
            probe_value=10.0,
            probe_unit="% damage over time multiplier",
            score_handler="dot_total_percentile",
            sort_order=110,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_truthy("flag_type_damageovertime"), _gt_number("l20_dot_total", 0.0)),
            source_fields=("l20_dot_total", "l20_duration_primary", "l20_duration_secondary"),
        ),
        ScalingVector(
            vector_id="fire_dot_scaling",
            label="Fire DoT Scaling",
            description="Affinity for fire-specific DoT scaling from the fire portion of the raw DoT shell.",
            probe_value=10.0,
            probe_unit="% fire damage over time multiplier",
            score_handler="fire_dot_percentile",
            sort_order=120,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_gt_number("l20_dot_fire_total", 0.0),),
            source_fields=("l20_dot_fire_total", "l20_dot_total"),
        ),
        ScalingVector(
            vector_id="cold_dot_scaling",
            label="Cold DoT Scaling",
            description="Affinity for cold-specific DoT scaling from the cold portion of the raw DoT shell.",
            probe_value=10.0,
            probe_unit="% cold damage over time multiplier",
            score_handler="cold_dot_percentile",
            sort_order=130,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_gt_number("l20_dot_cold_total", 0.0),),
            source_fields=("l20_dot_cold_total", "l20_dot_total"),
        ),
        ScalingVector(
            vector_id="lightning_dot_scaling",
            label="Lightning DoT Scaling",
            description="Affinity for lightning-specific DoT scaling from the lightning portion of the raw DoT shell.",
            probe_value=10.0,
            probe_unit="% lightning damage over time multiplier",
            score_handler="lightning_dot_percentile",
            sort_order=140,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_gt_number("l20_dot_lightning_total", 0.0),),
            source_fields=("l20_dot_lightning_total", "l20_dot_total"),
        ),
        ScalingVector(
            vector_id="physical_dot_scaling",
            label="Physical DoT Scaling",
            description="Affinity for physical-specific DoT scaling from the physical portion of the raw DoT shell.",
            probe_value=10.0,
            probe_unit="% physical damage over time multiplier",
            score_handler="physical_dot_percentile",
            sort_order=150,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_gt_number("l20_dot_physical_total", 0.0),),
            source_fields=("l20_dot_physical_total", "l20_dot_total"),
        ),
        ScalingVector(
            vector_id="chaos_dot_scaling",
            label="Chaos DoT Scaling",
            description="Affinity for chaos-specific DoT scaling from the chaos portion of the raw DoT shell.",
            probe_value=10.0,
            probe_unit="% chaos damage over time multiplier",
            score_handler="chaos_dot_percentile",
            sort_order=160,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(_gt_number("l20_dot_chaos_total", 0.0),),
            source_fields=("l20_dot_chaos_total", "l20_dot_total"),
        ),
        ScalingVector(
            vector_id="blood_charge_sustain",
            label="Blood Charge Sustain",
            description="Affinity for sustaining or assuming blood-charge stacks on skills whose formula scales per charge.",
            probe_value=1.0,
            probe_unit="sustained charge stack",
            score_handler="mechanic_stub",
            sort_order=165,
            allowed_route_ids=("self_cast", "trigger", "mine", "trap", "totem"),
            mechanic_family_id="blood_charge_family",
            conditions=(_eq_text("name", "Reap"),),
            source_fields=("name",),
        ),
        ScalingVector(
            vector_id="gem_level_scaling",
            label="Gem Level Scaling",
            description="Affinity for +gem levels using standardized level-20 to max growth ratios.",
            probe_value=1.0,
            probe_unit="+1 gem level",
            score_handler="gem_level_growth_percentile",
            sort_order=170,
            allowed_route_ids=("self_cast", "self_attack", "trigger", "mine", "trap", "totem", "brand"),
            conditions=(
                _any_non_null(
                    "growth_damage_effectiveness_20_to_lmax_ratio",
                    "growth_base_multiplier_20_to_lmax_ratio",
                    "growth_dot_total_20_to_lmax_ratio",
                ),
            ),
            source_fields=(
                "growth_damage_effectiveness_20_to_lmax_ratio",
                "growth_base_multiplier_20_to_lmax_ratio",
                "growth_dot_total_20_to_lmax_ratio",
            ),
        ),
    )

    packages = (
        MechanicPackage(
            package_id="lightning_conduit_shock_package",
            label="Lightning Conduit Shock Package",
            description="Adds route-aware score for the skill's explicit more-damage-per-shock-effect rule.",
            package_handler="lightning_conduit_shock_bonus",
            sort_order=10,
            eligible_route_ids=("self_cast", "trigger", "mine", "trap", "totem"),
            mechanic_family_id="shock_effect_family",
            conditions=(_eq_text("name", "Lightning Conduit"),),
            source_fields=("name",),
        ),
        MechanicPackage(
            package_id="reap_blood_charge_package",
            label="Reap Blood Charge Package",
            description="Adds route-aware score for Reap's explicit more-damage-per-blood-charge rule.",
            package_handler="reap_blood_charge_bonus",
            sort_order=20,
            eligible_route_ids=("self_cast", "trigger", "mine", "trap", "totem"),
            mechanic_family_id="blood_charge_family",
            conditions=(_eq_text("name", "Reap"),),
            source_fields=("name",),
        ),
        MechanicPackage(
            package_id="toxic_rain_overlap_package",
            label="Toxic Rain Overlap Package",
            description="Adds a conservative overlap bonus for Toxic Rain when its projectile, area, and duration shell exists.",
            package_handler="toxic_rain_overlap_bonus",
            sort_order=30,
            eligible_route_ids=("self_attack", "totem", "mine", "trap"),
            mechanic_family_id="overlap_family",
            conditions=(_eq_text("name", "Toxic Rain"),),
            source_fields=("name", "l20_arrow_count", "l20_duration_primary", "l20_dot_chaos_total"),
        ),
    )

    return SkillScalingRuleSet(routes=routes, vectors=vectors, families=families, packages=packages)
