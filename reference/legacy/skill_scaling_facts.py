"""Conservative scaling-fact extraction for skill scaling passports."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from poe_build_research.reboot_mvp.skill_raw_summary import (
    raw_active_skill_sampled_values,
    raw_active_skill_stat_ids,
    raw_active_skill_stat_sources,
    related_raw_active_skill_records,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
CONFIG_SURFACES_PATH = PACKAGE_ROOT.parent / "pob" / "corpus_data" / "config_surfaces.json"
MAX_SOURCE_EXAMPLES = 5
_INTERACTION_TAXONOMY_UPPERCASE_TOKENS = frozenset({"ai", "aoe", "cdr", "dot", "dps", "es"})

_DESCRIBED_SCALING_STAT_IDS = frozenset(
    {
        "alchemists_mark_igniter_creates_burning_ground_%_ignite_damage",
        "alchemists_mark_poisoner_creates_caustic_ground_%_poison_damage",
        "active_skill_additive_spell_damage_modifiers_apply_to_attack_damage_at_%_value",
        "active_skill_ailment_damage_+%_final",
        "active_skill_bleeding_damage_+%_final",
        "active_skill_ignite_damage_+%_final",
        "active_skill_area_damage_+%_final",
        "active_skill_area_of_effect_radius_+%_final",
        "active_skill_hit_ailment_damage_with_projectile_+%_final",
        "active_skill_main_hand_weapon_damage_+%_final",
        "active_skill_merged_damage_+%_final_while_dual_wielding",
        "active_skill_additive_minion_damage_modifiers_apply_to_all_damage_at_%_value",
        "active_skill_minion_attack_speed_+%_final",
        "active_skill_minion_damage_+%_final",
        "active_skill_minion_bleeding_damage_+%_final",
        "active_skill_minion_life_+%_final",
        "active_skill_non_reaper_minion_damage_+%_final",
        "active_skill_non_reaper_minion_maximum_life_+%_final",
        "active_skill_minion_physical_damage_+%_final",
        "active_skill_projectile_damage_+%_final",
        "active_skill_projectile_speed_+%_final",
        "active_skill_projectile_speed_+%_variation_final",
        "active_skill_returning_projectile_damage_+%_final",
        "active_skill_shock_as_though_damage_+%_final",
        "additive_cast_speed_modifiers_apply_to_sigil_repeat_frequency",
        "absolution_blast_chance_to_summon_on_hitting_rare_or_unique_%",
        "attack_skills_have_added_lightning_damage_equal_to_%_of_maximum_mana",
        "attacks_impale_on_hit_%_chance",
        "apply_enemy_impale_damage_to_nearby_enemies_on_killing_blow_%_chance",
        "attack_speed_+%_per_maximum_totem",
        "base_righteous_fire_%_of_max_energy_shield_to_deal_to_nearby_per_minute",
        "base_righteous_fire_%_of_max_life_to_deal_to_nearby_per_minute",
        "base_righteous_fire_%_of_max_mana_to_deal_to_nearby_per_minute",
        "base_number_of_animated_weapons_allowed",
        "base_number_of_arrows",
        "base_number_of_golems_allowed",
        "base_number_of_herald_scorpions_allowed",
        "base_number_of_projectiles",
        "base_number_of_relics_allowed",
        "base_number_of_spectres_allowed",
        "base_number_of_reapers_allowed",
        "base_smite_number_of_targets",
        "base_number_of_zombies_allowed",
        "base_skill_number_of_additional_hits",
        "base_projectile_speed_+%",
        "base_spell_repeat_count",
        "base_chance_to_shock_%",
        "blood_scythe_cost_+%_final_per_charge",
        "blood_scythe_damage_+%_final_per_charge",
        "blood_spears_additional_number_of_spears_if_changed_stance_recently",
        "blood_spears_base_number_of_spears",
        "blood_spears_damage_+%_final_in_blood_stance",
        "bladefall_number_of_volleys",
        "bleed_on_hit_with_attacks_%",
        "chance_to_fork_extra_projectile_%",
        "chance_to_deal_double_damage_%_vs_bleeding_enemies",
        "chance_to_deal_double_damage_%",
        "chaos_damage_resisted_by_highest_resistance",
        "chaos_damage_resisted_by_lowest_resistance",
        "cobra_lash_hit_and_ailment_damage_+%_final_for_each_remaining_chain",
        "dark_pact_chaos_damage_added_from_sacrifice_+%",
        "disintegrate_secondary_beam_angle_+%",
        "dominating_blow_chance_to_summon_on_hitting_unqiue_%",
        "dual_strike_critical_strike_chance_+%_final_against_enemies_on_full_life",
        "dual_strike_damage_+%_final_against_enemies_on_full_life",
        "energy_release_damage_+%_final_per_5%_increased_damage_taken_from_shock_on_target",
        "eye_of_winter_base_explosion_shards",
        "flask_throw_added_chaos_damage_%_of_flask_life_to_recover",
        "freezing_pulse_damage_+%_final_at_long_range",
        "galvanic_field_damage_+%_final_per_5%_increased_damage_taken_from_shock",
        "galvanic_field_radius_+_per_10%_increased_damage_taken_from_shock",
        "gain_%_of_base_wand_damage_as_added_spell_damage",
        "golem_buff_effect_+%",
        "groundslam_damage_to_close_targets_+%_final",
        "herald_of_agony_poison_damage_+%_final",
        "herald_of_light_summon_champion_on_kill",
        "herald_of_light_summon_champion_on_unique_or_rare_enemy_hit_%",
        "herald_of_purity_physical_damage_+%_final",
        "herald_of_thunder_bolt_base_frequency",
        "herald_of_thunder_bolt_frequency_+%",
        "hexblast_%_chance_to_not_consume_hex",
        "hexblast_ailment_damage_+%_final_if_hexed",
        "hexblast_display_innate_remove_hex_100%_chance",
        "hexblast_hit_damage_+%_final_if_hexed",
        "holy_hammers_damage_+%_final_for_initial_hammer_in_cascade",
        "holy_hammers_damage_+%_final_if_consuming_power_charge",
        "holy_hammers_num_additional_hammerslams_if_consuming_power_charge",
        "holy_flame_totem_consecrated_ground_area_+%",
        "holy_sweep_hammerfall_damage_+%_final",
        "holy_sweep_number_of_holy_bolts_to_create",
        "ice_nova_freeze_as_though_damage_+%_final",
        "ice_crash_second_hit_damage_+%_final",
        "ice_crash_third_hit_damage_+%_final",
        "infernal_cry_physical_damage_%_to_add_as_fire_per_5_power_up_to_cap",
        "ice_spear_second_form_critical_strike_chance_+%",
        "ice_spear_second_form_critical_strike_multiplier_+",
        "ice_spear_second_form_projectile_speed_+%_final",
        "kinetic_bolt_forks_apply_to_zig_zags",
        "lancing_steel_damage_+%_final_after_first_hit_on_target",
        "lightning_explosion_mine_aura_damage_taken_+%",
        "lightning_arrow_alt_additional_strikes",
        "lightning_arrow_alt_strike_frequency_ms",
        "lightning_arrow_maximum_number_of_extra_targets",
        "lightning_arrow_stack_limit",
        "mana_void_gain_%_missing_unreserved_mana_as_base_lightning_damage",
        "maximum_virulence_stacks",
        "molten_shell_%_of_absorbed_damage_dealt_as_reflected_fire",
        "molten_shell_damage_absorb_limit_%_of_armour",
        "molten_shell_damage_absorbed_%",
        "molten_shell_max_damage_absorbed",
        "minion_chance_to_deal_double_damage_%",
        "minion_cooldown_recovery_+%",
        "minion_aggravate_bleeding_on_attack_hit_chance_%",
        "minion_withered_effect_+%",
        "modifiers_to_number_of_projectiles_instead_apply_to_splitting",
        "modifiers_to_projectile_count_do_not_apply",
        "maximum_number_of_snapping_adder_projectiles",
        "number_of_chains",
        "number_of_additional_totems_allowed",
        "number_of_allowed_storm_arrows",
        "physical_damage_%_to_add_as_cold",
        "phys_cascade_trap_number_of_cascades",
        "power_siphon_base_fire_at_x_targets",
        "power_siphon_fire_at_all_targets",
        "prismatic_rain_beam_base_frequency_ms",
        "projectile_damage_+%_final_if_pierced_enemy",
        "projectile_number_to_split",
        "projectiles_can_split_from_terrain",
        "quake_slam_fully_charged_explosion_damage_+%_final",
        "rage_slash_vortex_attack_speed_+%_final",
        "retaliation_base_use_window_duration_ms",
        "raised_spectre_level",
        "sanctify_wave_damage_+%_final",
        "skill_base_chaos_damage_%_maximum_energy_shield",
        "skill_base_chaos_damage_%_maximum_life",
        "skill_buff_grants_chance_to_poison_%",
        "skill_double_hits_when_dual_wielding",
        "skill_effect_duration_+%",
        "skill_physical_damage_%_to_convert_to_cold",
        "skill_physical_damage_%_to_convert_to_fire",
        "skill_area_of_effect_+%_final_in_sand_stance",
        "smite_lightning_target_range",
        "snapping_adder_%_chance_to_retain_projectile_on_release",
        "snapping_adder_maximum_projectiles_released",
        "spectres_have_base_duration_ms",
        "spell_impale_on_crit_%_chance",
        "spell_maximum_action_distance_+%",
        "shock_maximum_magnitude_+",
        "shock_nova_ring_chance_to_shock_+%",
        "stun_duration_+%_vs_enemies_that_are_on_full_life",
        "storm_rain_pulse_count",
        "shockwave_slam_explosion_damage_+%_final",
        "support_spellslinger_damage_+%_final",
        "swordstorm_num_hits",
        "trap_%_chance_to_trigger_twice",
        "vaal_upgrade_minion_damage_+%_final",
        "vaal_venom_gyre_capture_x_projectiles_per_second",
        "vaal_volcanic_fissure_crack_repeat_count",
        "viper_strike_dual_wield_attack_speed_+%_final",
        "viper_strike_dual_wield_damage_+%_final",
        "wall_maximum_length",
        "zombie_slam_area_of_effect_+%",
        "zombie_slam_cooldown_speed_+%",
        "active_skill_base_area_of_effect_radius",
        "active_skill_base_radius_+",
        "active_skill_base_secondary_area_of_effect_radius",
        "always_stun_enemies_that_are_on_full_life",
        "base_chance_to_freeze_%",
        "base_cooldown_speed_+%",
        "base_global_chance_to_knockback_%",
        "base_penetrate_elemental_resistances_%",
        "base_skill_effect_duration",
        "base_totem_duration",
        "base_totem_range",
        "cold_ailment_duration_+%",
        "cold_ailment_effect_+%",
        "desecrate_maximum_number_of_corpses",
        "freeze_as_though_dealt_damage_+%",
        "leap_slam_always_knockback_within_range",
        "maximum_life_+%_for_corpses_you_create",
        "nova_spells_cast_at_target_location",
        "ring_of_ice_placement_distance",
        "unearth_base_corpse_level",
    }
)

_DESCRIBED_SCALING_OUTPUT_TOKENS = frozenset(
    {
        "additional_main_hand_hits",
        "additional_projectile",
        "added_lightning",
        "area_of_effect",
        "attack_speed",
        "blasts_per_wave",
        "cast_speed",
        "cooldown_recovery",
        "critical_strike_chance",
        "critical_strike_multiplier",
        "damage",
        "duration",
        "fire_speed",
        "frequency",
        "health",
        "hit_rate",
        "lingering_blades",
        "mana_spend",
        "melee_weapon_range",
        "movement_speed",
        "number_of_projectiles",
        "pods_per_projectile",
        "projectiles_per_interval",
        "radius",
        "spell_base_critical_strike_chance",
        "stun_threshold",
    }
)

_DESCRIBED_SCALING_CONTEXT_TOKENS = frozenset(
    {
        "additional_melee_range",
        "affected_enemy",
        "blade",
        "charge",
        "charges",
        "combo",
        "corpse",
        "curse",
        "enemy",
        "frenzy",
        "maximum_mana",
        "mine",
        "power",
        "projectile",
        "resource",
        "rope",
        "rune",
        "stage",
        "steel_ammo",
        "stun_duration",
        "volley",
        "wave",
    }
)

_INTERACTION_FACT_RECORDS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "fireball.explosion_overlap",
        "skill_gates": ("Fireball",),
        "label": "Explosion overlap",
        "description": (
            "Direct-hit shotgunning is prevented per cast, but separate projectile explosions from the "
            "same cast can overlap on one target when they detonate on other enemies or terrain."
        ),
        "mechanic_tags": ("overlap", "projectile_explosion", "conditional_shotgun"),
        "scaling_axes": ("projectile_count", "area_of_effect", "pierce_chain_fork", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Fireball",
    },
    {
        "source_id": "firestorm.aoe_density_tradeoff",
        "skill_gates": ("Firestorm",),
        "include_transfigured": True,
        "label": "AoE density tradeoff",
        "description": (
            "Increasing area enlarges both the overall storm footprint and each impact radius, but it "
            "also spreads the random impacts over a wider zone. That lowers average single-target hit "
            "density, while extra duration still raises the total impact count."
        ),
        "mechanic_tags": ("area_density_tradeoff", "repeat_impacts", "duration_hit_budget"),
        "scaling_axes": ("area_of_effect", "duration", "positioning", "enemy_size"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Firestorm",
    },
    {
        "source_id": "forbidden_rite.enemy_count_volley_and_projectile_speed",
        "skill_gates": ("Forbidden Rite", "Forbidden Rite of Soul Sacrifice"),
        "label": "Enemy-count volley and projectile speed",
        "description": (
            "Forbidden Rite fires one cursor projectile plus enemy-targeted extra projectiles, so a "
            "single target typically takes two hits while added projectiles mostly improve multi-target "
            "coverage. Projectile speed shortens the delay to impact, while the ground-targeted projectiles "
            "ignore chain, fork, split, and pierce behaviour."
        ),
        "mechanic_tags": ("multi_projectile", "single_target_double_hit", "projectile_speed_scaling"),
        "scaling_axes": ("enemy_count", "projectile_speed", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Forbidden_Rite",
    },
    {
        "source_id": "freezing_pulse.projectile_speed_retention_curve",
        "skill_gates": ("Freezing Pulse",),
        "label": "Projectile speed retention curve",
        "description": (
            "Freezing Pulse always pierces by default and cannot naturally fork or chain. Projectile "
            "speed extends the travel distance before the projectile dissipates, which preserves more "
            "damage and bonus freeze chance at real combat range."
        ),
        "mechanic_tags": ("projectile_speed_scaling", "damage_falloff", "always_pierce"),
        "scaling_axes": ("projectile_speed", "enemy_distance", "freeze_chance", "pierce"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Freezing_Pulse",
    },
    {
        "source_id": "hexblast.hex_gated_aoe_post_hit_consumption",
        "skill_gates": ("Hexblast",),
        "include_transfigured": True,
        "label": "Hex-gated AoE and post-hit consumption",
        "description": (
            "Hexblast's main beam is single-target only. If the target is hexed, the same use also "
            "creates an area hit around that target, but the original target cannot be struck by that "
            "secondary AoE. The hex is removed after damage is dealt, so the hit and ailment bonuses "
            "still benefit from the consumed hex."
        ),
        "mechanic_tags": ("hex_gate", "secondary_aoe", "post_hit_hex_consumption"),
        "scaling_axes": ("hex_uptime", "area_of_effect", "curse_reapplication", "target_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Hexblast",
    },
    {
        "source_id": "holy_flame_totem.piercing_volley_lane_scaling",
        "skill_gates": ("Holy Flame Totem",),
        "label": "Piercing volley lane scaling",
        "description": (
            "Holy Flame Totem channels a piercing stream while consecrated ground is a separate "
            "stationary utility payload. Added projectiles and projectile speed mainly widen and "
            "lengthen the damaging lane, while totem duration governs both fire uptime and ground uptime."
        ),
        "mechanic_tags": ("totem_projectile_lane", "always_pierce", "ground_uptime"),
        "scaling_axes": ("projectile_count", "projectile_speed", "totem_duration", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Holy_Flame_Totem",
    },
    {
        "source_id": "holy_flame_totem_of_ire.fixed_volley_speed_shift",
        "skill_gates": ("Holy Flame Totem of Ire",),
        "label": "Fixed volley with projectile-speed shift",
        "description": (
            "Holy Flame Totem of Ire disables projectile-count scaling and concentrates output into a "
            "fixed fast volley. It keeps the same consecrated-ground utility zone, so scaling shifts "
            "away from extra projectiles toward projectile speed, uptime, and placement."
        ),
        "mechanic_tags": ("fixed_projectile_count", "projectile_speed_shift", "ground_uptime"),
        "scaling_axes": ("projectile_speed", "totem_duration", "totem_limit", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Holy_Flame_Totem_of_Ire",
    },
    {
        "source_id": "ice_spear.second_form_distance_gate",
        "skill_gates": ("Ice Spear",),
        "label": "Second-form distance gate",
        "description": (
            "Ice Spear only gains its massive projectile speed, pierce, and critical bonuses after "
            "travelling a short distance. Single-target damage therefore improves at range, while "
            "close targets often only face the weaker first form."
        ),
        "mechanic_tags": ("second_form", "distance_gate", "crit_scaling"),
        "scaling_axes": ("enemy_distance", "projectile_speed", "critical_strike_chance", "critical_strike_multiplier"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Spear",
    },
    {
        "source_id": "ice_spear_of_splitting.split_target_count_substitution",
        "skill_gates": ("Ice Spear of Splitting",),
        "label": "Split target-count substitution",
        "description": (
            "Ice Spear of Splitting fires one primary shard, then converts projectile-count scaling "
            "into the number of targets the split can seek after colliding with terrain or an enemy. "
            "The split projectiles are already in second form, so terrain setup and nearby enemy count "
            "matter more than close-range first-hit damage."
        ),
        "mechanic_tags": ("split_projectile", "target_count_substitution", "terrain_setup"),
        "scaling_axes": ("projectile_count", "enemy_density", "terrain_setup", "projectile_speed"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Spear_of_Splitting",
    },
    {
        "source_id": "power_siphon.target_count_substitution",
        "skill_gates": ("Power Siphon",),
        "include_transfigured": True,
        "label": "Projectile count becomes target count",
        "description": (
            "Power Siphon fires one projectile at each selected nearby target, and modifiers to number "
            "of projectiles instead increase the number of targets selected. Extra projectiles therefore "
            "mainly improve coverage rather than adding same-target shotgun, while single-target output "
            "still depends on attack repetition and charge scaling."
        ),
        "mechanic_tags": ("target_count_substitution", "coverage_scaling", "anti_shotgun"),
        "scaling_axes": ("projectile_count", "enemy_count", "attack_speed", "power_charges"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Power_Siphon",
    },
    {
        "source_id": "vaal_power_siphon.all_targets_simultaneous",
        "skill_gates": ("Vaal Power Siphon",),
        "label": "All-target simultaneous volley",
        "description": (
            "Vaal Power Siphon fires simultaneously at each nearby enemy instead of using the base "
            "skill's capped target count. That shifts scaling toward enemy count and soul-window reuse, "
            "while support options like Volley are explicitly disallowed."
        ),
        "mechanic_tags": ("all_targets", "simultaneous_volley", "soul_window"),
        "scaling_axes": ("enemy_count", "soul_gain_rate", "attack_speed", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Power_Siphon",
    },
    {
        "source_id": "molten_strike.projectile_overlap",
        "skill_gates": ("Molten Strike", "Vaal Molten Strike"),
        "label": "Projectile overlap",
        "description": (
            "Projectile explosions can overlap on a single target, and the melee strike can stack "
            "with projectile hits in single-target setups."
        ),
        "mechanic_tags": ("overlap", "projectile", "melee_plus_secondary"),
        "scaling_axes": ("projectile_count", "area_of_effect", "projectile_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Molten_Strike",
    },
    {
        "source_id": "ball_lightning.repeat_interval",
        "skill_gates": ("Ball Lightning",),
        "label": "Repeat-hit residency window",
        "description": (
            "Targets are hit repeatedly while they stay inside the orb, but multiple balls from the "
            "same cast share the repeat interval instead of shotgunning together."
        ),
        "mechanic_tags": ("repeat_hit", "area_residency", "anti_shotgun"),
        "scaling_axes": ("projectile_speed", "area_of_effect", "duration", "projectile_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ball_Lightning",
    },
    {
        "source_id": "ball_lightning_of_orbiting.fixed_orbit_interval",
        "skill_gates": ("Ball Lightning of Orbiting",),
        "label": "Fixed orbit interval",
        "description": (
            "Nearby targets are struck every 150ms while they stay inside the orbit, and the orb keeps "
            "that cadence independently per cast. Area only changes the hit radius, while chain, fork, "
            "and pierce do not modify the projectile."
        ),
        "mechanic_tags": ("repeat_hit", "fixed_interval", "area_tag_caveat", "anti_projectile_behaviour"),
        "scaling_axes": ("area_of_effect", "positioning", "trap_multiplicity", "returning_projectiles"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ball_Lightning_of_Orbiting",
    },
    {
        "source_id": "ball_lightning_of_static.fixed_lifetime_hit_cap",
        "skill_gates": ("Ball Lightning of Static",),
        "label": "Fixed lifetime hit cap",
        "description": (
            "The stationary orb keeps a 150ms strike interval and a fixed 2 second lifetime, giving it "
            "a hard per-cast hit budget. Area only changes the strike radius rather than scaling damage."
        ),
        "mechanic_tags": ("repeat_hit", "fixed_interval", "fixed_hit_budget", "area_tag_caveat"),
        "scaling_axes": ("area_of_effect", "trap_multiplicity", "positioning", "cast_repetition"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ball_Lightning_of_Static",
    },
    {
        "source_id": "barrage.sequential_interval_compression",
        "skill_gates": ("Barrage",),
        "label": "Sequential interval compression",
        "description": (
            "Barrage keeps a fixed attack time while firing projectiles in sequence, so extra "
            "projectiles compress the interval between shots instead of lengthening the attack."
        ),
        "mechanic_tags": ("sequential_projectiles", "fixed_attack_time", "hit_rate_scaling"),
        "scaling_axes": ("projectile_count", "attack_speed", "projectile_spread", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Barrage",
    },
    {
        "source_id": "barrage_of_volley_fire.side_cone_nonstack",
        "skill_gates": ("Barrage of Volley Fire",),
        "label": "Side-cone non-stack geometry",
        "description": (
            "The first and last shots in each barrage also fire side cones for extra coverage, but "
            "those side projectiles cannot stack onto the same target as their matching main shot."
        ),
        "mechanic_tags": ("volley_side_cones", "anti_overlap", "sequence_edges"),
        "scaling_axes": ("projectile_count", "attack_speed", "enemy_density", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Barrage_of_Volley_Fire",
    },
    {
        "source_id": "arc.chain_memory_loopback",
        "skill_gates": ("Arc",),
        "label": "Chain memory loopback",
        "description": (
            "The main Arc remembers the last two enemies it hit, so it needs at least three valid "
            "targets before it can loop back onto the same enemy. Each chain also creates a "
            "secondary Arc that hits one additional nearby enemy but cannot chain further."
        ),
        "mechanic_tags": ("chain_memory", "secondary_arc", "repeat_hit_gate"),
        "scaling_axes": ("chain_count", "enemy_density", "target_spacing", "proxy_targets"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Arc",
    },
    {
        "source_id": "vaal_arc.branching_chain_exhaustion_and_lucky_arc_window",
        "skill_gates": ("Vaal Arc",),
        "label": "Branching chain exhaustion and Lucky Arc window",
        "description": (
            "Each Vaal Arc chain branches into two further chains that can only seek enemies not already "
            "hit by that cast, so realized single-cast output scales with target density, spacing, and how "
            "long the chain graph can avoid exhausting valid enemies. The skill also grants a short Lucky "
            "Arc window that improves the hit damage of later Arc casts instead of only the Vaal burst."
        ),
        "mechanic_tags": ("branching_chain", "remaining_chain_scaling", "target_exhaustion", "arc_hit_buff"),
        "scaling_axes": ("enemy_density", "chain_count", "target_spacing", "buff_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Arc",
    },
    {
        "source_id": "arc_of_oscillating.two_target_ping_pong",
        "skill_gates": ("Arc of Oscillating",),
        "label": "Two-target ping-pong chaining",
        "description": (
            "This transfigured version can chain back and forth between only two enemies, and its "
            "secondary chains are allowed to strike enemies that the main arc already hit."
        ),
        "mechanic_tags": ("chain_loop", "secondary_chain", "repeat_hit"),
        "scaling_axes": ("chain_count", "enemy_pairing", "target_spacing", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Arc_of_Oscillating",
    },
    {
        "source_id": "arc_of_surging.split_fanout",
        "skill_gates": ("Arc of Surging",),
        "label": "Split fan-out targeting",
        "description": (
            "This transfigured version does not chain. Instead, it splits from the first struck "
            "enemy toward several nearby targets, so extra hits scale with nearby pack density "
            "rather than chain loops."
        ),
        "mechanic_tags": ("split", "multi_target_fanout", "anti_chain"),
        "scaling_axes": ("enemy_density", "target_spacing", "split_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Arc_of_Surging",
    },
    {
        "source_id": "artillery_ballista.targeted_line_overlap",
        "skill_gates": ("Artillery Ballista",),
        "label": "Targeted line overlap",
        "description": (
            "Arrows land along a targeted line rather than all from the ballista pivot, so same-target "
            "damage scales by centering the line and compressing several impacts through the same hitbox."
        ),
        "mechanic_tags": ("overlap", "targeted_line", "totem_attack"),
        "scaling_axes": ("projectile_count", "totem_placement", "positioning", "enemy_hitbox"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Artillery_Ballista",
    },
    {
        "source_id": "artillery_ballista_of_cross_strafe.crossline_overlap",
        "skill_gates": ("Artillery Ballista of Cross Strafe",),
        "label": "Cross-line overlap pattern",
        "description": (
            "This variant drops arrows in two perpendicular lines. Single-target damage scales by "
            "centering the cross on the enemy so impacts from both lines can overlap."
        ),
        "mechanic_tags": ("overlap", "cross_pattern", "totem_attack"),
        "scaling_axes": ("projectile_count", "totem_placement", "positioning", "enemy_hitbox"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Artillery_Ballista_of_Cross_Strafe",
    },
    {
        "source_id": "artillery_ballista_of_focus_fire.target_split_nonoverlap",
        "skill_gates": ("Artillery Ballista of Focus Fire",),
        "label": "Distributed target split",
        "description": (
            "This version distributes arrows across different enemies instead of stacking impacts on one "
            "target, so extra arrows scale coverage and pack clear more than same-target overlap."
        ),
        "mechanic_tags": ("target_split", "coverage_bias", "totem_attack"),
        "scaling_axes": ("projectile_count", "enemy_density", "target_count", "totem_placement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Artillery_Ballista_of_Focus_Fire",
    },
    {
        "source_id": "lightning_conduit.aoe_targeting_only",
        "skill_gates": ("Lightning Conduit",),
        "include_transfigured": True,
        "activation_mechanic_family_ids": ("shock_effect_family",),
        "activation_package_ids": ("lightning_conduit_shock_package",),
        "label": "AoE targets reach, not hit damage",
        "description": (
            "Area of effect only changes the search radius around the targeted location; the hit itself "
            "is not AoE and does not scale with Area Damage modifiers."
        ),
        "mechanic_tags": ("area_tag_caveat", "target_radius", "anti_area_damage_scaling"),
        "scaling_axes": ("area_of_effect", "shock_uptime", "enemy_density", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Conduit",
    },
    {
        "source_id": "orb_of_storms.lightning_skill_trigger_cadence",
        "skill_gates": ("Orb of Storms",),
        "label": "Lightning-skill trigger cadence",
        "description": (
            "Orb of Storms keeps its own timed strike interval, but also zaps whenever a "
            "Lightning-tagged skill is used near the orb, including attacks, casts, and proxy skills. "
            "Those trigger zaps have no cooldown of their own, except channelled skills only provoke "
            "them every 0.5 seconds."
        ),
        "mechanic_tags": (
            "triggered_extra_strikes",
            "no_internal_cooldown",
            "channel_tick_gate",
            "timed_interval",
        ),
        "scaling_axes": ("lightning_skill_frequency", "cast_speed", "proxy_delivery", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Orb_of_Storms",
    },
    {
        "source_id": "bane.curse_limit_gated_linked_hex_scaling",
        "skill_gates": ("Bane",),
        "include_transfigured": True,
        "label": "Curse-limit gated linked Hex scaling",
        "description": (
            "Bane itself does not consume curse limit, but the Hexes linked to it do. If your curse "
            "limit is already full or too low for all linked Hexes, Bane loses the extra damage and "
            "duration scaling from the missing Hex applications."
        ),
        "mechanic_tags": (
            "curse_limit_gate",
            "linked_hex_scaling",
            "conditional_damage_bonus",
        ),
        "scaling_axes": (
            "curse_limit",
            "linked_hex_count",
            "curse_uptime",
            "trigger_delivery",
        ),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bane",
    },
    {
        "source_id": "blast_rain.targeted_overlap",
        "skill_gates": ("Blast Rain",),
        "label": "Targeted overlap",
        "description": (
            "All explosions overlap at the targeted point, and extra projectiles add extra overlapping "
            "blasts."
        ),
        "mechanic_tags": ("overlap", "targeted_volley", "additional_projectiles"),
        "scaling_axes": ("projectile_count", "area_of_effect", "positioning", "projectile_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blast_Rain",
    },
    {
        "source_id": "blazing_salvo.return_double_impact",
        "skill_gates": ("Blazing Salvo",),
        "label": "Return double-impact",
        "description": (
            "With Returning Projectiles Support, each projectile lands and explodes at the targeted "
            "location, then returns and explodes again, creating a second impact cycle."
        ),
        "mechanic_tags": ("return_projectile", "repeat_hit", "projectile_explosion"),
        "scaling_axes": ("projectile_count", "support_choice", "target_distance", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blazing_Salvo",
    },
    {
        "source_id": "blade_blast.lingering_blade_count_conversion",
        "skill_gates": ("Blade Blast",),
        "label": "Lingering blade count conversion",
        "description": (
            "Blade Blast's own damage handles every detonation. The skill that created the lingering "
            "blades only contributes blade count and placement, so lower-level blade generators can "
            "still be optimal if they create more blades."
        ),
        "mechanic_tags": ("cross_skill_synergy", "lingering_blade", "detonation_count"),
        "scaling_axes": ("lingering_blade_count", "blade_generation_skill", "area_of_effect", "cast_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Blast",
    },
    {
        "source_id": "blade_blast_of_unloading.blade_vortex_stack_dump",
        "skill_gates": ("Blade Blast of Unloading",),
        "label": "Blade Vortex stack dump",
        "description": (
            "This transfigured version ignores lingering blades, detonates up to ten Blade Vortex "
            "blades in sequence, and each detonation scales from Blade Blast while area grows per "
            "blade consumed."
        ),
        "mechanic_tags": ("cross_skill_synergy", "blade_vortex", "sequential_detonation"),
        "scaling_axes": ("blade_vortex_stack_count", "area_of_effect", "duration_uptime", "cast_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Blast_of_Unloading",
    },
    {
        "source_id": "blade_blast_of_dagger_detonation.dagger_spellblade_nova",
        "skill_gates": ("Blade Blast of Dagger Detonation",),
        "label": "Dagger-fed self nova",
        "description": (
            "This version does not detonate lingering blades. Instead it creates a self-centered nova "
            "whose spell damage is fed by equipped dagger damage, with dual daggers each contributing "
            "60%, so weapon damage and close-range positioning replace blade-count scaling."
        ),
        "mechanic_tags": ("weapon_added_damage", "nova_positioning", "no_lingering_blades"),
        "scaling_axes": ("equipped_dagger_damage", "dual_wielding", "cast_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Blast_of_Dagger_Detonation",
    },
    {
        "source_id": "blade_trap.rotation_hit_budget",
        "skill_gates": ("Blade Trap",),
        "label": "Fixed rotation hit budget",
        "description": (
            "Blade Trap ignores weapon attack speed and instead has a fixed per-trap hit budget: two "
            "hits per rotation for 8 total by default, or 10 while dual wielding."
        ),
        "mechanic_tags": ("repeat_hit", "fixed_hit_budget", "dual_wield_scaling"),
        "scaling_axes": ("rotation_count", "dual_wielding", "trap_trigger_rate", "accuracy"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Trap",
    },
    {
        "source_id": "blade_trap_of_greatswords.duration_hit_rate",
        "skill_gates": ("Blade Trap of Greatswords",),
        "label": "Duration-based hit rate",
        "description": (
            "This transfigured version also ignores attack speed, but its damage window is a "
            "duration-based spin with a fixed 5 hits per second, so duration and uptime scale total "
            "hits more than attack speed."
        ),
        "mechanic_tags": ("repeat_hit", "duration_window", "fixed_hit_rate"),
        "scaling_axes": ("duration", "trap_trigger_rate", "uptime", "accuracy"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Trap_of_Greatswords",
    },
    {
        "source_id": "blade_trap_of_laceration.single_rotation_bleed_payout",
        "skill_gates": ("Blade Trap of Laceration",),
        "label": "Single-rotation bleed payout",
        "description": (
            "This version only rotates once, still hits twice per rotation, ignores attack speed, and "
            "loses dual-wield bonuses, so total hit count is fixed while damage focuses on a faster-"
            "bleeding one-rotation payout."
        ),
        "mechanic_tags": ("fixed_hit_budget", "bleed_scaling", "single_rotation"),
        "scaling_axes": ("damage_per_hit", "bleed_damage", "trap_trigger_rate", "accuracy"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Trap_of_Laceration",
    },
    {
        "source_id": "blade_vortex.blade_count_hit_rate_compression",
        "skill_gates": ("Blade Vortex",),
        "label": "Blade-count hit-rate compression",
        "description": (
            "Blade Vortex gains both more damage and higher hit frequency per active blade, so real "
            "single-target output scales with sustaining blade count and keeping targets inside the "
            "orbit rather than only with one-hit damage."
        ),
        "mechanic_tags": ("stacking_hit_rate", "blade_count", "area_residency"),
        "scaling_axes": ("blade_count", "duration", "cast_speed", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Vortex",
    },
    {
        "source_id": "vaal_blade_vortex.homing_fixed_ten_blade_hit_rate",
        "skill_gates": ("Vaal Blade Vortex",),
        "label": "Homing fixed-ten-blade hit rate",
        "description": (
            "Vaal Blade Vortex creates an autonomous vortex with a fixed ten-blade payload and a fixed hit "
            "interval while it lasts, then homes toward nearby enemies instead of orbiting the caster. "
            "That shifts scaling away from normal Blade Vortex restacking loops and toward duration, "
            "pathing, and enemy residency inside the moving vortex."
        ),
        "mechanic_tags": ("autonomous_vortex", "fixed_hit_rate", "homing", "duration_window"),
        "scaling_axes": ("duration", "target_residency", "enemy_density", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Blade_Vortex",
    },
    {
        "source_id": "blade_vortex_of_the_scythe.single_blade_recast_cadence",
        "skill_gates": ("Blade Vortex of the Scythe",),
        "label": "Single-blade recast cadence",
        "description": (
            "This version is capped at one active blade, hits immediately on first cast, and more "
            "active blades do not raise hit rate. Damage therefore scales around recast cadence and "
            "blade duration rather than stack ramp."
        ),
        "mechanic_tags": ("single_instance", "duration_window", "recast_cadence", "immediate_first_hit"),
        "scaling_axes": ("cast_speed", "duration", "hit_rate", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Vortex_of_the_Scythe",
    },
    {
        "source_id": "bladestorm.lingering_storm_repeat_hits",
        "skill_gates": ("Bladestorm",),
        "label": "Lingering storm repeat hits",
        "description": (
            "Bladestorm is split between the initial melee hit and a lingering storm that repeatedly "
            "hits based on attack speed. Single-target payout depends on storm uptime, target "
            "residency inside the storm, and whether Blood or Sand storm behaviour better preserves "
            "those repeat hits."
        ),
        "mechanic_tags": ("lingering_storm", "repeat_hit", "stance_state", "target_residency"),
        "scaling_axes": ("attack_speed", "storm_duration", "positioning", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bladestorm",
    },
    {
        "source_id": "bladestorm_of_uncertainty.random_storm_state_continuous_hits",
        "skill_gates": ("Bladestorm of Uncertainty",),
        "label": "Random storm state continuous hits",
        "description": (
            "This version randomly creates Blood or Sand storms regardless of stance, so realized "
            "damage depends on how often the stationary versus travelling storm states keep their "
            "continuous hits on target rather than on one fixed storm profile."
        ),
        "mechanic_tags": ("random_state", "lingering_storm", "continuous_hits", "state_variance"),
        "scaling_axes": ("attack_speed", "storm_duration", "positioning", "target_residency"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bladestorm_of_Uncertainty",
    },
    {
        "source_id": "blight.debuff_stack_area_scaling",
        "skill_gates": ("Blight",),
        "include_transfigured": True,
        "label": "Debuff-stack area scaling",
        "description": (
            "Blight deals damage through stacking debuffs rather than repeated area hits. Area of "
            "effect changes how many enemies and positions can be tagged by the channel, but Area "
            "Damage modifiers and hit-only added damage supports do not scale the debuff damage "
            "itself."
        ),
        "mechanic_tags": (
            "stacking_debuff",
            "area_application",
            "anti_area_damage_scaling",
            "non_hit_damage",
        ),
        "scaling_axes": ("area_of_effect", "cast_speed", "channel_uptime", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blight",
    },
    {
        "source_id": "vaal_blight.three_stack_burst_shared_twenty_stack_cap",
        "skill_gates": ("Vaal Blight",),
        "label": "Three-stack burst and shared twenty-stack cap",
        "description": (
            "Each Vaal Blight cast can apply at most three damage layers, and those layers count toward "
            "the same twenty-stack cap used by normal Blight. It is also not treated as a channelling "
            "spell for bonus purposes, so the skill scales as a soul-limited stack burst that must be "
            "sequenced with regular Blight instead of as a channel replacement."
        ),
        "mechanic_tags": ("stacking_debuff", "three_stack_burst", "shared_stack_cap", "non_channel"),
        "scaling_axes": ("soul_gain_rate", "enemy_density", "duration", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Blight",
    },
    {
        "source_id": "bladefall.volley_overlap",
        "skill_gates": ("Bladefall",),
        "include_transfigured": True,
        "label": "Volley overlap",
        "description": (
            "A single cast can hit multiple times when adjacent volleys overlap on the same enemy."
        ),
        "mechanic_tags": ("overlap", "volley", "aoe_sequence"),
        "scaling_axes": ("area_of_effect", "additional_volleys", "positioning", "knockback"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bladefall",
    },
    {
        "source_id": "bladefall_of_volleys.aoe_spacing_tradeoff",
        "skill_gates": ("Bladefall of Volleys",),
        "label": "AoE spacing tradeoff",
        "description": (
            "Adjacent volleys can overlap on one target, but more area also increases volley spacing, "
            "so wider coverage can lower single-target overlap while knockback can enable extra re-hits."
        ),
        "mechanic_tags": ("overlap", "aoe_spacing_tradeoff", "volley_sequence"),
        "scaling_axes": ("area_of_effect", "volley_count", "positioning", "knockback"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bladefall_of_Volleys",
    },
    {
        "source_id": "bladefall_of_impaling.overlap_impale_lane",
        "skill_gates": ("Bladefall of Impaling",),
        "label": "Overlap-driven Impale lane",
        "description": (
            "Overlap still governs single-target payout because adjacent waves can re-hit the same "
            "target. This version trades lingering blades and crit-multi scaling for built-in Impale "
            "application, so lane control and overlap matter more than crit burst."
        ),
        "mechanic_tags": ("overlap", "impale_scaling", "lane_control", "no_crit_multiplier"),
        "scaling_axes": ("area_of_effect", "positioning", "knockback", "impale_scaling"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bladefall_of_Impaling",
    },
    {
        "source_id": "bear_trap.secondary_damage_root_scaling",
        "skill_gates": ("Bear Trap", "Bear Trap of Skewers"),
        "label": "Secondary damage root scaling",
        "description": (
            "Bear Trap deals secondary damage rather than a spell hit, and its immobilize duration "
            "scales from the percentage of enemy maximum life dealt by that hit, alongside duration "
            "modifiers."
        ),
        "mechanic_tags": ("secondary_damage", "immobilize_duration", "damage_to_duration"),
        "scaling_axes": ("enemy_max_life", "damage_per_hit", "skill_duration", "trap_trigger_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bear_Trap",
    },
    {
        "source_id": "cremation.projectile_hit_budget",
        "skill_gates": ("Cremation", "Cremation of Exhuming", "Cremation of the Volcano"),
        "label": "Projectile hit budget",
        "description": (
            "Each geyser projectile can hit the same enemy, so extra projectiles raise hits per second "
            "while longer duration raises the total projectile budget."
        ),
        "mechanic_tags": ("repeat_hit", "projectile", "duration_scaling"),
        "scaling_axes": ("projectile_count", "duration", "geyser_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cremation",
    },
    {
        "source_id": "creeping_frost.explosion_shotgun",
        "skill_gates": ("Creeping Frost",),
        "label": "Explosion shotgun overlap",
        "description": (
            "Extra projectiles do not let one projectile hit the same target twice, but separate "
            "explosions from the same cast can overlap and shotgun a target when they collide nearby."
        ),
        "mechanic_tags": ("conditional_shotgun", "projectile_explosion", "anti_direct_shotgun"),
        "scaling_axes": ("projectile_count", "area_of_effect", "pierce_chain_fork", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Creeping_Frost",
    },
    {
        "source_id": "detonate_dead.dual_hit_corpse_scaling",
        "skill_gates": ("Detonate Dead", "Detonate Dead of Chain Reaction"),
        "label": "Dual-hit corpse scaling",
        "description": (
            "Each cast deals two separate hits: a spell hit around the corpse and a corpse-explosion "
            "secondary hit. The corpse explosion scales from corpse life and generic modifiers, not "
            "spell-specific scaling."
        ),
        "mechanic_tags": ("dual_hit", "corpse_scaling", "secondary_damage"),
        "scaling_axes": ("corpse_life", "corpse_supply", "area_of_effect", "generic_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Detonate_Dead",
    },
    {
        "source_id": "detonate_dead_of_chain_reaction.multi_corpse_chain_throughput",
        "skill_gates": ("Detonate Dead of Chain Reaction",),
        "label": "Sequential corpse-chain throughput",
        "description": (
            "This version repeats through up to eight corpses in sequence, so realized damage scales with "
            "corpse supply, nearby corpse density, and how quickly the chain can spend its full corpse "
            "budget instead of only with one detonation's listed hit."
        ),
        "mechanic_tags": ("corpse_chain", "sequential_burst", "corpse_supply", "multi_hit"),
        "scaling_axes": ("corpse_supply", "corpse_density", "cast_speed", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Detonate_Dead_of_Chain_Reaction",
    },
    {
        "source_id": "vaal_detonate_dead.mass_corpse_chain_throughput",
        "skill_gates": ("Vaal Detonate Dead",),
        "label": "Mass corpse-chain throughput",
        "description": (
            "Vaal Detonate Dead spends a large sequence of nearby corpses in one activation, so realized "
            "burst scales with total corpse supply, corpse density in range, and corpse life across the "
            "whole chain instead of only one detonation's listed hit."
        ),
        "mechanic_tags": ("corpse_chain", "multi_corpse_burst", "corpse_supply", "corpse_scaling"),
        "scaling_axes": ("corpse_supply", "corpse_density", "corpse_life", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Detonate_Dead",
    },
    {
        "source_id": "detonate_dead_of_scavenging.native_corpse_only_explosion",
        "skill_gates": ("Detonate Dead of Scavenging",),
        "label": "Native-corpse-only explosion",
        "description": (
            "This version removes the spell hit and only deals the corpse-explosion secondary damage. It "
            "also cannot consume player-created corpses, so single-target damage is constrained by native "
            "corpse availability and corpse life rather than by spell scaling."
        ),
        "mechanic_tags": ("secondary_damage", "corpse_restriction", "corpse_scaling", "no_spell_hit"),
        "scaling_axes": ("corpse_life", "native_corpse_supply", "area_of_effect", "generic_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Detonate_Dead_of_Scavenging",
    },
    {
        "source_id": "volatile_dead.corpse_throughput_orb_cap",
        "skill_gates": ("Volatile Dead",),
        "label": "Corpse throughput and orb cap",
        "description": (
            "Single-target damage is gated by how many corpses can be generated and consumed before "
            "reaching the active orb cap, not just by the spell's listed damage per orb."
        ),
        "mechanic_tags": ("corpse_consumption", "active_orb_cap", "homing_orb"),
        "scaling_axes": ("corpse_generation", "cast_speed", "active_orb_cap", "corpse_supply"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Volatile_Dead",
    },
    {
        "source_id": "volatile_dead_of_confinement.stationary_duration_orbs",
        "skill_gates": ("Volatile Dead of Confinement",),
        "label": "Stationary duration orbs",
        "description": (
            "This transfigured version leaves stationary orbs that detonate after a duration, so overlap "
            "and payout depend on duration, placement, and how many corpses can be converted under the cap."
        ),
        "mechanic_tags": ("corpse_consumption", "stationary_orb", "duration_detonation", "overlap"),
        "scaling_axes": ("corpse_generation", "duration", "positioning", "active_orb_cap"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Volatile_Dead_of_Confinement",
    },
    {
        "source_id": "volatile_dead_of_seething.burst_corpse_conversion_orb_cap",
        "skill_gates": ("Volatile Dead of Seething",),
        "label": "Burst corpse conversion with orb cap",
        "description": (
            "This version converts a larger corpse burst per cast, but realized damage still bottlenecks on "
            "corpse supply and the active orb cap once enough homing orbs are already in flight."
        ),
        "mechanic_tags": ("burst_corpse_conversion", "active_orb_cap", "homing_orb"),
        "scaling_axes": ("corpse_generation", "cast_speed", "active_orb_cap", "corpse_supply"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Volatile_Dead_of_Seething",
    },
    {
        "source_id": "double_strike.dual_hit_single_roll",
        "skill_gates": ("Double Strike",),
        "include_transfigured": True,
        "label": "Dual-hit single-roll attack",
        "description": (
            "One use of Double Strike can hit the same target twice. The two hits are independent "
            "for on-hit behaviours, but they share the same critical strike roll."
        ),
        "mechanic_tags": ("repeat_hit", "dual_hit", "shared_crit_roll"),
        "scaling_axes": ("attack_speed", "on_hit_scaling", "ailment_application", "dual_wielding"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Double_Strike",
    },
    {
        "source_id": "vaal_double_strike.clone_uptime_and_proxy_duplication",
        "skill_gates": ("Vaal Double Strike",),
        "label": "Clone uptime and proxy duplication",
        "description": (
            "Vaal Double Strike front-loads an immediate melee use and then creates two temporary clones "
            "that proxy-repeat the attack for a duration. Realized damage therefore scales with clone "
            "uptime, target stickiness, and attack cadence instead of only the initial melee swing."
        ),
        "mechanic_tags": ("proxy_clone", "duration_window", "melee_repeat", "target_stickiness"),
        "scaling_axes": ("duration", "attack_speed", "target_uptime", "melee_range"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Double_Strike",
    },
    {
        "source_id": "earthquake.aftershock_timing_tradeoff",
        "skill_gates": ("Earthquake",),
        "label": "Aftershock timing tradeoff",
        "description": (
            "Earthquake is a two-hit skill whose delayed aftershock deals the larger hit. Duration "
            "modifiers change the wait before that aftershock, so timing and uptime trade against each "
            "other instead of only scaling raw area."
        ),
        "mechanic_tags": ("aftershock", "duration_timing", "dual_hit"),
        "scaling_axes": ("skill_duration", "attack_speed", "area_of_effect", "dual_wielding"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Earthquake",
    },
    {
        "source_id": "earthquake_of_amplification.duration_snapshot_window",
        "skill_gates": ("Earthquake of Amplification",),
        "label": "Live aftershock recalculation",
        "description": (
            "This transfigured version gains more damage and area from its longer delay, and the "
            "aftershock does not snapshot on the initial swing. Buffs gained or lost before it lands "
            "therefore change the final aftershock."
        ),
        "mechanic_tags": ("duration_scaling", "live_recalculation", "aftershock"),
        "scaling_axes": ("skill_duration", "temporary_buffs", "area_of_effect", "attack_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Earthquake_of_Amplification",
    },
    {
        "source_id": "earthshatter.spike_overlap_breakpoints",
        "skill_gates": ("Earthshatter",),
        "include_transfigured": True,
        "label": "Spike overlap breakpoints",
        "description": (
            "A target can only be struck by one fissure from each attack, but all spikes from that "
            "attack can hit the same enemy. Overlap depends on room geometry, enemy size, and has a "
            "non-linear relationship with increased area of effect."
        ),
        "mechanic_tags": ("overlap", "fissure_vs_spike", "room_geometry"),
        "scaling_axes": ("area_of_effect", "enemy_size", "positioning", "warcry_trigger_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Earthshatter",
    },
    {
        "source_id": "earthshatter_of_fragility.short_fuse_auto_shatter_density",
        "skill_gates": ("Earthshatter of Fragility",),
        "label": "Short-fuse auto-shatter density",
        "description": (
            "This version cannot be detonated by warcries or slams and instead self-shatters after a "
            "short duration. Single-target payout depends on how many short-fuse spikes can be packed "
            "under the enemy before the auto-detonation window expires."
        ),
        "mechanic_tags": ("auto_detonation", "short_duration", "spike_density", "no_manual_shatter"),
        "scaling_axes": ("duration", "fissure_count", "maximum_spikes", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Earthshatter_of_Fragility",
    },
    {
        "source_id": "earthshatter_of_prominence.single_fissure_burst_window",
        "skill_gates": ("Earthshatter of Prominence",),
        "label": "Single-fissure burst window",
        "description": (
            "This version concentrates the skill into one fissure and fewer spikes, but each "
            "shattering spike has much more area and damage. It scales around concentrated burst "
            "windows and spike overlap on large targets rather than broad field coverage."
        ),
        "mechanic_tags": ("single_fissure", "burst_window", "spike_overlap", "large_target"),
        "scaling_axes": ("maximum_spikes", "area_of_effect", "positioning", "warcry_trigger_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Earthshatter_of_Prominence",
    },
    {
        "source_id": "eye_of_winter.speed_gap_shotgun_tradeoff",
        "skill_gates": ("Eye of Winter",),
        "include_transfigured": True,
        "label": "Projectile-speed shotgun tradeoff",
        "description": (
            "Only the shards deal damage, and projectile speed changes the spacing between those "
            "shards. Lower speed can concentrate more shard hits and the final spiral onto one target, "
            "while extra projectiles only affect the final spiral."
        ),
        "mechanic_tags": ("projectile_speed_tradeoff", "sequential_shard_shotgun", "final_spiral"),
        "scaling_axes": ("projectile_speed", "projectile_count", "terrain_collision", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Eye_of_Winter",
    },
    {
        "source_id": "contagion.essence_drain_dual_spread",
        "skill_gates": ("Contagion",),
        "include_transfigured": True,
        "label": "Essence Drain dual-spread payload",
        "description": (
            "If an enemy affected by both Contagion and Essence Drain dies, the Contagion spread "
            "propagates both effects instead of only Contagion."
        ),
        "mechanic_tags": ("cross_skill_synergy", "on_kill_propagation", "dot_spread"),
        "scaling_axes": ("enemy_density", "kill_chain", "duration", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Contagion",
    },
    {
        "source_id": "caustic_arrow.ground_nonstack_projectile_spread",
        "skill_gates": ("Caustic Arrow",),
        "include_transfigured": True,
        "label": "Ground non-stack and spread",
        "description": (
            "Extra projectiles spread caustic ground over a wider area, but overlapping caustic "
            "ground does not stack; pierce, chain, and fork instead create additional separate "
            "ground patches."
        ),
        "mechanic_tags": ("ground_dot", "anti_overlap", "projectile_behaviour"),
        "scaling_axes": ("projectile_count", "pierce_chain_fork", "area_of_effect", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Caustic_Arrow",
    },
    {
        "source_id": "charged_dash.movement_speed_stage_tradeoff",
        "skill_gates": ("Charged Dash", "Charged Dash of Projection"),
        "label": "Movement-speed stage tradeoff",
        "description": (
            "Charged Dash gains stages while the illusion is travelling, so extra movement speed pushes "
            "the path farther but shortens the time available to build stages. The illusion emits a "
            "wave every two attack times and a target can only be hit once per wave, making stage gain, "
            "attack speed, and path length the core single-target levers."
        ),
        "mechanic_tags": ("stage_ramp", "travel_time_tradeoff", "wave_cadence", "single_wave_hit_cap"),
        "scaling_axes": ("movement_speed", "attack_speed", "stage_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Charged_Dash",
    },
    {
        "source_id": "crackling_lance_of_branching.fixed_fanout_coverage",
        "skill_gates": ("Crackling Lance of Branching",),
        "label": "Fixed fanout coverage",
        "description": (
            "This version permanently stays in the low-intensity branching form, so it gives up beam "
            "narrowing and ramping and instead fixes damage around broad fanout coverage and branch "
            "angle."
        ),
        "mechanic_tags": ("branch_fanout", "fixed_state", "coverage_scaling", "no_intensity"),
        "scaling_axes": ("branching_angle", "area_of_effect", "cast_speed", "target_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Crackling_Lance_of_Branching",
    },
    {
        "source_id": "crackling_lance_of_disintegration.narrow_beam_shock_payload",
        "skill_gates": ("Crackling Lance of Disintegration",),
        "label": "Narrow beam shock payload",
        "description": (
            "This version permanently stays in the concentrated high-intensity form, removing side "
            "branches and turning the skill into a narrow lane with better shock application and "
            "maximum-shock scaling."
        ),
        "mechanic_tags": ("concentrated_beam", "shock_scaling", "fixed_state", "no_branching"),
        "scaling_axes": ("maximum_shock_effect", "shock_chance", "cast_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Crackling_Lance_of_Disintegration",
    },
    {
        "source_id": "crackling_lance.stationary_intensity_ramp",
        "skill_gates": ("Crackling Lance",),
        "label": "Stationary intensity ramp",
        "description": (
            "Crackling Lance only gains Intensity from repeated casts and loses it while moving or "
            "teleporting, so realized single-target damage depends on holding a stationary cast chain "
            "long enough to stay in the narrowed high-intensity beam state."
        ),
        "mechanic_tags": ("intensity_ramp", "movement_dropoff", "beam_concentration", "stationary_sequence"),
        "scaling_axes": ("cast_speed", "positioning", "intensity_uptime", "beam_width"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Crackling_Lance",
    },
    {
        "source_id": "exsanguinate.independent_dot_stack_timers",
        "skill_gates": ("Exsanguinate", "Exsanguinate of Transmission"),
        "label": "Independent DoT stack timers",
        "description": (
            "Exsanguinate stacks up to three separate debuffs and each application keeps its own "
            "duration instead of refreshing earlier stacks, so cast cadence and duration scaling both "
            "change how reliably the skill maintains full three-stack damage."
        ),
        "mechanic_tags": ("stacking_dot", "independent_duration", "hybrid_hit_dot", "cast_cycle"),
        "scaling_axes": ("cast_speed", "duration", "dot_stack_count", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Exsanguinate",
    },
    {
        "source_id": "flameblast.channel_release_stage_commitment",
        "skill_gates": ("Flameblast",),
        "label": "Channel release stage commitment",
        "description": (
            "Flameblast deals its real payload on release after building stages, so cast speed changes "
            "the time-to-maximum-stage and how often fully scaled explosions can be committed in actual "
            "boss uptime windows."
        ),
        "mechanic_tags": ("channel_commitment", "stage_ramp", "release_burst", "cast_speed_cycle"),
        "scaling_axes": ("cast_speed", "stage_count", "channel_uptime", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flameblast",
    },
    {
        "source_id": "flameblast_of_celerity.auto_release_three_stage_cycle",
        "skill_gates": ("Flameblast of Celerity",),
        "label": "Auto-release three-stage cycle",
        "description": (
            "This version caps at only three stages and automatically releases at maximum, turning "
            "Flameblast into a short burst loop where cast speed heavily compresses the full damage "
            "cycle instead of only affecting setup time."
        ),
        "mechanic_tags": ("auto_release", "short_stage_cycle", "stage_ramp", "burst_repeat"),
        "scaling_axes": ("cast_speed", "stage_count", "area_of_effect", "burst_cadence"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flameblast_of_Celerity",
    },
    {
        "source_id": "flameblast_of_contraction.radius_collapse_fail_state",
        "skill_gates": ("Flameblast of Contraction",),
        "label": "Radius collapse fail-state",
        "description": (
            "This version loses radius as stages rise, and enough extra stages can collapse the base "
            "radius to zero, so stage scaling is constrained by geometry and not every source of extra "
            "stages is a free damage increase."
        ),
        "mechanic_tags": ("radius_fail_state", "stage_tradeoff", "channel_commitment", "geometry_cap"),
        "scaling_axes": ("stage_count", "cast_speed", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flameblast_of_Contraction",
    },
    {
        "source_id": "frost_blades.return_rehit",
        "skill_gates": ("Frost Blades",),
        "label": "Return re-hit window",
        "description": (
            "Outgoing projectiles do not re-hit their source target, but they can hit once per set on "
            "the return path when projectile speed and spacing allow it."
        ),
        "mechanic_tags": ("return", "repeat_hit", "projectile_set_limit"),
        "scaling_axes": ("projectile_speed", "projectile_count", "return", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Blades",
    },
    {
        "source_id": "frost_blades_of_katabasis.nonstacking_chilling_areas",
        "skill_gates": ("Frost Blades of Katabasis",),
        "label": "Non-stacking chilling area replication",
        "description": (
            "Each melee strike that hits creates its own chilling area, including additional strikes, "
            "but overlapping areas do not stack their damage. Single-target scaling is therefore gated "
            "by how many separate areas can be maintained on the target's position rather than by raw "
            "overlap."
        ),
        "mechanic_tags": (
            "chilling_area",
            "additional_strike_replication",
            "nonstacking_ground",
            "target_residency",
        ),
        "scaling_axes": ("additional_strikes", "positioning", "skill_duration", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Blades_of_Katabasis",
    },
    {
        "source_id": "frostblink_of_wintry_blast.dual_endpoint_hit_and_chill_consume",
        "skill_gates": ("Frostblink of Wintry Blast",),
        "label": "Dual-endpoint hit and chill consume",
        "description": (
            "This version damages in an area at both ends of the teleport, gains more hit damage per "
            "chill on the enemy, and then removes that chill after dealing damage. Realized burst is "
            "therefore gated by endpoint overlap and by preloading a strong chill before the blink."
        ),
        "mechanic_tags": ("dual_endpoint_hit", "chill_consume", "teleport_burst", "positioning_breakpoint"),
        "scaling_axes": ("chill_effect", "positioning", "area_of_effect", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frostblink_of_Wintry_Blast",
    },
    {
        "source_id": "frostbolt.ice_nova_proxy_payload",
        "skill_gates": ("Frostbolt",),
        "label": "Ice Nova proxy payload",
        "description": (
            "Frostbolt projectiles can act as remote anchors for Ice Nova of Frostbolts, which can be "
            "cast off nearby bolts for extra hit damage. Slower projectile travel and better bolt "
            "placement keep that proxy window available for longer."
        ),
        "mechanic_tags": ("proxy_anchor", "cross_skill_synergy", "projectile_residency"),
        "scaling_axes": ("projectile_speed", "projectile_count", "duration", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frostbolt",
    },
    {
        "source_id": "ice_nova.frostbolt_proxy_cast",
        "skill_gates": ("Ice Nova",),
        "label": "Frostbolt proxy cast",
        "description": (
            "Ice Nova can be cast from Frostbolt projectiles instead of only from the caster, so projectile "
            "count, speed, and bolt placement directly change how often those remote novas can overlap a "
            "target or cover separate lanes."
        ),
        "mechanic_tags": ("proxy_anchor", "cross_skill_synergy", "aoe_overlap", "positioning_breakpoint"),
        "scaling_axes": ("projectile_count", "projectile_speed", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Nova",
    },
    {
        "source_id": "ice_nova_of_deep_freeze.expanding_wave_range_and_travel_speed",
        "skill_gates": ("Ice Nova of Deep Freeze",),
        "label": "Expanding wave scales reach and hit timing through area",
        "description": (
            "Ice Nova of Deep Freeze still deals damage in an expanding wave rather than as an instant full "
            "circle, so increased area of effect also increases the wave's maximum reach and travel speed. "
            "Its real freeze delivery therefore scales through area and positioning, not only through the "
            "listed freeze modifiers on the gem."
        ),
        "mechanic_tags": ("expanding_wave", "aoe_range_speed_coupling", "hit_timing", "freeze_delivery"),
        "scaling_axes": ("area_of_effect", "positioning", "enemy_distance", "freeze_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Nova",
    },
    {
        "source_id": "frost_blades.hydrosphere_proxy_release",
        "skill_gates": ("Frost Blades",),
        "label": "Hydrosphere proxy release",
        "description": (
            "Hydrosphere can be struck to release Frost Blades projectiles from range, giving a proxy "
            "target for projectile generation while gated by Hydrosphere's own hit cooldown."
        ),
        "mechanic_tags": ("hydrosphere", "proxy_target", "projectile_release"),
        "scaling_axes": ("hydrosphere_setup", "projectile_count", "positioning", "hit_cooldown"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Blades",
    },
    {
        "source_id": "glacial_cascade.burst_overlap",
        "skill_gates": ("Glacial Cascade",),
        "include_transfigured": True,
        "label": "Burst overlap",
        "description": (
            "Adjacent bursts can overlap on enemies near the center line, allowing two-hit and even "
            "three-hit outcomes when area is scaled high enough."
        ),
        "mechanic_tags": ("overlap", "multi_hit", "burst_sequence"),
        "scaling_axes": ("area_of_effect", "positioning", "enemy_hitbox", "skill_range"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Glacial_Cascade",
    },
    {
        "source_id": "galvanic_field.retarget_cooldown",
        "skill_gates": ("Galvanic Field",),
        "include_transfigured": True,
        "label": "Retarget cooldown and area caveat",
        "description": (
            "Area modifiers only change the field radius, not the field hit damage, and each enemy can "
            "only be targeted once per field interval even when chaining is involved."
        ),
        "mechanic_tags": ("retarget_cooldown", "area_tag_caveat", "chain_shared_cooldown"),
        "scaling_axes": ("area_of_effect", "shock_effect", "enemy_density", "hit_frequency"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Galvanic_Field",
    },
    {
        "source_id": "galvanic_arrow.projectile_speed_range_and_cone",
        "skill_gates": ("Galvanic Arrow",),
        "label": "Projectile-speed range and cone scaling",
        "description": (
            "Projectile speed increases both travel distance and the reach of the secondary lightning cone, "
            "so realized damage scales with range shaping instead of only raw projectile count."
        ),
        "mechanic_tags": ("projectile_speed_scaling", "cone_secondary", "range_scaling"),
        "scaling_axes": ("projectile_speed", "enemy_distance", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Galvanic_Arrow",
    },
    {
        "source_id": "galvanic_arrow_of_energy.cone_only_non_projectile",
        "skill_gates": ("Galvanic Arrow of Energy",),
        "label": "Cone-only non-projectile payload",
        "description": (
            "This version removes the arrow projectiles entirely and keeps only the frontal lightning cone, "
            "so projectile travel and projectile-only scaling no longer shape the skill's realized damage."
        ),
        "mechanic_tags": ("cone_only", "non_projectile", "payload_swap"),
        "scaling_axes": ("area_of_effect", "attack_speed", "positioning", "added_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Galvanic_Arrow_of_Energy",
    },
    {
        "source_id": "galvanic_arrow_of_surging.behind_target_cone_routing",
        "skill_gates": ("Galvanic Arrow of Surging",),
        "label": "Behind-target cone routing",
        "description": (
            "Each arrow creates its lightning cone behind the enemy it hits, so realized single-target "
            "damage depends on projectile routing and target alignment. Unlike the base skill, projectile "
            "speed does not expand the cone area on this version."
        ),
        "mechanic_tags": ("behind_target_cone", "projectile_routing", "variant_caveat"),
        "scaling_axes": ("projectile_count", "pierce_chain_fork", "enemy_alignment", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Galvanic_Arrow_of_Surging",
    },
    {
        "source_id": "lightning_arrow.additional_target_aoe",
        "skill_gates": ("Lightning Arrow",),
        "label": "Additional-target AoE reach",
        "description": (
            "On impact, Lightning Arrow also strikes a few nearby enemies around the target for the same "
            "damage. Area of effect raises that secondary reach, but area damage modifiers do not scale "
            "the extra lightning strikes themselves."
        ),
        "mechanic_tags": ("additional_targets", "area_reach", "secondary_hit"),
        "scaling_axes": ("area_of_effect", "enemy_density", "projectile_accuracy", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Arrow",
    },
    {
        "source_id": "vaal_lightning_arrow.random_flight_and_bolt_coverage",
        "skill_gates": ("Vaal Lightning Arrow",),
        "label": "Random flight and bolt coverage",
        "description": (
            "Vaal Lightning Arrow fires wandering arrows that can redirect before colliding, and each hit "
            "calls a bolt onto nearby enemies. Realized output scales with projectile flight time, enemy "
            "density, and how much secondary bolt coverage the random routing can find."
        ),
        "mechanic_tags": ("wandering_projectiles", "secondary_bolt", "coverage_bias", "random_reroute"),
        "scaling_axes": ("projectile_count", "enemy_density", "flight_time", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Lightning_Arrow",
    },
    {
        "source_id": "ice_shot.cone_overlap",
        "skill_gates": ("Ice Shot", "Vaal Ice Shot"),
        "include_transfigured": True,
        "label": "Cone overlap",
        "description": (
            "A target cannot be hit by its own arrow and cone together, but cones from other arrows or "
            "other impacts can overlap onto that target."
        ),
        "mechanic_tags": ("overlap", "cone_secondary", "multi_arrow"),
        "scaling_axes": ("projectile_count", "area_of_effect", "positioning", "chain_pierce_fork"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Shot",
    },
    {
        "source_id": "ice_nova_of_frostbolts.dual_projectile_repeat",
        "skill_gates": ("Ice Nova of Frostbolts",),
        "label": "Dual Frostbolt repeat routing",
        "description": (
            "When cast near Frostbolts, this nova can expand from up to two projectiles at once and "
            "gains more hit damage. If the cast would repeat, the repeats expand again from those same "
            "projectiles after a short delay."
        ),
        "mechanic_tags": ("dual_proxy_cast", "repeat_from_proxy", "cross_skill_synergy"),
        "scaling_axes": ("projectile_count", "repeat_count", "projectile_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Nova_of_Frostbolts",
    },
    {
        "source_id": "explosive_trap.small_blast_overlap_breakpoints",
        "skill_gates": ("Explosive Trap", "Explosive Trap of Shrapnel"),
        "label": "Small blast overlap breakpoints",
        "description": (
            "Smaller explosions can overlap the target based on the ratio between small and large "
            "radii; +radius improves overlap chance, while increased area can move the skill across "
            "favorable or unfavorable breakpoints."
        ),
        "mechanic_tags": ("overlap", "breakpoint", "secondary_explosions"),
        "scaling_axes": ("radius", "area_of_effect", "enemy_hitbox", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Explosive_Trap",
    },
    {
        "source_id": "explosive_arrow.fuse_delivery_constraints",
        "skill_gates": ("Explosive Arrow",),
        "label": "Fuse delivery constraints",
        "description": (
            "Only arrows that stop in the target add fuses; Pierce, Fork, Chain, Split, and Return "
            "prevent sticking, while ballistas, Mirage Archer, and allies can all feed the same "
            "combined explosion."
        ),
        "mechanic_tags": ("fuse_stack", "projectile_behaviour_gate", "shared_explosion"),
        "scaling_axes": ("attack_speed", "duration", "support_choice", "proxy_sources"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Explosive_Arrow",
    },
    {
        "source_id": "essence_drain.contagion_dual_spread",
        "skill_gates": ("Essence Drain",),
        "include_transfigured": True,
        "label": "Contagion-assisted spread",
        "description": (
            "When an enemy carrying both Essence Drain and Contagion dies, Contagion spreads the "
            "remaining duration of both debuffs to nearby enemies."
        ),
        "mechanic_tags": ("cross_skill_synergy", "duration_carryover", "dot_spread"),
        "scaling_axes": ("enemy_density", "kill_chain", "duration", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Essence_Drain",
    },
    {
        "source_id": "flame_wall.projectile_payload_persistence",
        "skill_gates": ("Flame Wall",),
        "label": "Projectile payload persistence",
        "description": (
            "Projectiles that pass through the wall gain added fire damage and apply the secondary "
            "burning debuff on hit, and that payload persists even if the wall expires or is "
            "replaced before the projectile lands."
        ),
        "mechanic_tags": ("projectile_payload", "secondary_debuff", "persistence"),
        "scaling_axes": ("projectile_skill_selection", "wall_placement", "duration", "ally_projectiles"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flame_Wall",
    },
    {
        "source_id": "herald_of_agony.virulence_sustain_ramp",
        "skill_gates": ("Herald of Agony",),
        "label": "Virulence sustain ramp",
        "description": (
            "Herald of Agony's crawler only exists while Virulence is sustained. Every poison adds Virulence, "
            "higher stacks both strengthen the crawler and decay faster, and dropping to zero removes the "
            "minion entirely."
        ),
        "mechanic_tags": ("proxy_minion", "stack_ramp", "resource_decay", "poison_gate"),
        "scaling_axes": ("poison_application_rate", "maximum_virulence", "virulence_decay", "minion_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Agony",
    },
    {
        "source_id": "herald_of_ash.overkill_burn_pool",
        "skill_gates": ("Herald of Ash",),
        "label": "Overkill burn pool",
        "description": (
            "Herald of Ash only creates its burn when a hit gets the kill, then bases that burn on the "
            "killing hit's overkill damage, including non-fire overkill. The debuff is not Ignite, so its "
            "follow-up scales with burning and damage-over-time modifiers rather than ailment-specific ones."
        ),
        "mechanic_tags": ("kill_condition", "overkill_pool", "damage_over_time", "non_ignite_burn"),
        "scaling_axes": ("hit_size", "kill_rate", "burning_damage", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Ash",
    },
    {
        "source_id": "herald_of_purity.sentinel_uptime_gate",
        "skill_gates": ("Herald of Purity",),
        "label": "Sentinel uptime gate",
        "description": (
            "Herald of Purity's damage comes from Sentinels that are only created on kill or on hitting rare "
            "or unique enemies, then need melee uptime to convert that spawn budget into damage. Realized DPS "
            "therefore depends on keeping the minion cap filled, not just on the herald buff itself."
        ),
        "mechanic_tags": ("proxy_minion", "spawn_gate", "minion_cap", "melee_uptime"),
        "scaling_axes": ("kill_rate", "rare_hit_rate", "minion_limit", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Purity",
    },
    {
        "source_id": "herald_of_thunder.shock_kill_gated_storm_cadence",
        "skill_gates": ("Herald of Thunder",),
        "label": "Shock-kill gated storm cadence",
        "description": (
            "Herald of Thunder's storm only starts when you personally kill a shocked enemy, then deals "
            "secondary damage on a fixed hit cadence that scales with storm frequency and duration rather "
            "than cast speed or spell-damage-only modifiers."
        ),
        "mechanic_tags": ("activation_gate", "secondary_damage", "hit_frequency", "uptime"),
        "scaling_axes": ("shock_uptime", "kill_rate", "hit_frequency", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Thunder",
    },
    {
        "source_id": "herald_of_ice.shatter_gated_secondary_burst",
        "skill_gates": ("Herald of Ice",),
        "label": "Shatter-gated secondary burst",
        "description": (
            "Herald of Ice only explodes when you shatter an enemy yourself, and that explosion is secondary "
            "damage centered on the corpse. Freeze reliability, kill sequencing, and area scaling matter; "
            "spell-damage-only modifiers do not."
        ),
        "mechanic_tags": ("shatter_gate", "secondary_damage", "corpse_anchor", "kill_condition"),
        "scaling_axes": ("freeze_uptime", "kill_rate", "area_of_effect", "added_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Ice",
    },
    {
        "source_id": "flame_surge.burning_source_bonus_window",
        "skill_gates": ("Flame Surge",),
        "label": "Burning-source damage gate",
        "description": (
            "The hit bonus is gated by the target already being Burning, so any external burning "
            "source can enable it. Area scaling also extends the narrow cone and enlarges the "
            "resulting burning-ground footprint."
        ),
        "mechanic_tags": ("cross_skill_burning_gate", "area_length_scaling", "burning_ground_followup"),
        "scaling_axes": ("burning_uptime", "area_of_effect", "skill_pairing", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flame_Surge",
    },
    {
        "source_id": "flame_surge_of_combusting.ignite_dps_snapshot_ground",
        "skill_gates": ("Flame Surge of Combusting",),
        "label": "Ignite-DPS ground snapshot",
        "description": (
            "The created burning ground snapshots the inflicted ignite's DPS. Fire and burning "
            "modifiers scale the ignite rather than double-dipping the ground, while faster-ignite "
            "effects can raise both ignite DPS and the resulting ground DPS."
        ),
        "mechanic_tags": ("ignite_dps_snapshot", "no_double_dip", "faster_ignite_scaling", "ground_followup"),
        "scaling_axes": ("ignite_dps", "faster_ailments", "duration", "ignite_chance"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flame_Surge_of_Combusting",
    },
    {
        "source_id": "flame_dash_of_return.round_trip_double_hit",
        "skill_gates": ("Flame Dash of Return",),
        "label": "Round-trip double hit",
        "description": (
            "This version teleports out and then back, dealing damage at both endpoints and leaving "
            "burning ground across the full round trip. Realized damage depends on positioning that "
            "lets both teleports connect rather than on only one listed hit."
        ),
        "mechanic_tags": ("round_trip", "dual_endpoint_hit", "burning_ground", "positioning_breakpoint"),
        "scaling_axes": ("positioning", "area_of_effect", "cast_speed", "burning_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flame_Dash_of_Return",
    },
    {
        "source_id": "flamethrower_trap.center_residency_nonstack",
        "skill_gates": ("Flamethrower Trap",),
        "include_transfigured": True,
        "label": "Center residency and same-trap non-stack",
        "description": (
            "Each flame deals damage every 0.1 seconds, but a target can only be damaged by one flame "
            "from the same trap at a time even if several overlap at the center. Different traps still "
            "stack, and direct placement plus larger target size increase time spent inside the flames."
        ),
        "mechanic_tags": (
            "fixed_tick_rate",
            "same_trap_nonstack",
            "multi_trap_stack",
            "center_residency",
        ),
        "scaling_axes": ("trap_multiplicity", "positioning", "enemy_size", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flamethrower_Trap",
    },
    {
        "source_id": "frozen_legion.cooldown_charge_proxy_throughput",
        "skill_gates": ("Frozen Legion",),
        "include_transfigured": True,
        "label": "Cooldown-charge proxy throughput",
        "description": (
            "Frozen Legion stores up to six cooldown uses and spends one per statue, with each statue "
            "attacking only once. Attack speed only shortens the statue swing, while cooldown recovery "
            "and stored-use management determine how often the skill can convert casts into actual hits."
        ),
        "mechanic_tags": ("proxy_attack", "cooldown_charges", "single_attack_statue", "throughput_gate"),
        "scaling_axes": ("cooldown_recovery", "stored_uses", "attack_speed", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frozen_Legion",
    },
    {
        "source_id": "hydrosphere.proxy_hit_cooldown",
        "skill_gates": ("Hydrosphere",),
        "label": "Proxy hit cooldown",
        "description": (
            "Hydrosphere behaves like a solid proxy target: projectiles that hit it consume a hit and "
            "trigger their normal projectile behaviours, while chaining skills can only chain off it on "
            "their first hit. The sphere itself can only be hit once per second."
        ),
        "mechanic_tags": (
            "proxy_target",
            "hit_cooldown",
            "projectile_behaviour_proxy",
            "first_chain_only",
        ),
        "scaling_axes": ("chain_count", "returning_projectiles", "projectile_behaviour", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Hydrosphere",
    },
    {
        "source_id": "kinetic_blast.arc_explosion_nonoverlap",
        "skill_gates": ("Kinetic Blast",),
        "label": "Arc explosion non-overlap",
        "description": (
            "A direct collision does not make its own arc explosions overlap a typical target, so extra "
            "projectiles mainly scale terrain-assisted or pack-assisted secondary coverage."
        ),
        "mechanic_tags": ("anti_shotgun", "projectile_explosion", "terrain_assist"),
        "scaling_axes": ("projectile_count", "terrain_geometry", "enemy_density", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Blast",
    },
    {
        "source_id": "kinetic_blast_of_clustering.projectile_to_explosion_conversion",
        "skill_gates": ("Kinetic Blast of Clustering",),
        "label": "Projectile-to-explosion conversion",
        "description": (
            "Kinetic Blast of Clustering still fires only one projectile, and extra projectile scaling "
            "turns into extra explosions instead. Those explosions are spread farther apart rather than "
            "concentrated at the collision point, so area and target size matter more than projectile "
            "count for same-target overlap."
        ),
        "mechanic_tags": ("projectile_to_explosion_conversion", "spread_widening", "overlap_breakpoint"),
        "scaling_axes": ("projectile_count", "area_of_effect", "enemy_hitbox", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Blast_of_Clustering",
    },
    {
        "source_id": "lancing_steel.shard_volley_and_collision_penalty",
        "skill_gates": ("Lancing Steel",),
        "label": "Shard volley and collision penalty",
        "description": (
            "Consuming up to four Steel Shards ramps the attack to triple projectile count, and the "
            "'Hits after the first' penalty applies to projectile collisions and damaging ailments "
            "such as poison."
        ),
        "mechanic_tags": ("steel_shard_volley", "sequential_projectiles", "collision_penalty", "ailment_penalty"),
        "scaling_axes": ("steel_shards", "projectile_count", "poison_scaling", "enemy_overlap"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lancing_Steel",
    },
    {
        "source_id": "lancing_steel_of_spraying.sequential_pierce_same_target_penalty",
        "skill_gates": ("Lancing Steel of Spraying",),
        "label": "Sequential spray with same-target penalty",
        "description": (
            "Lancing Steel of Spraying fires its piercing projectiles in sequence, but hits after the "
            "first on each enemy deal 90% less damage. Same-target scaling therefore comes from keeping "
            "more of the spray on target over the firing window, not from expecting every projectile to "
            "deal full shotgun damage."
        ),
        "mechanic_tags": ("sequential_projectiles", "pierce_lane", "same_target_penalty", "spray_window"),
        "scaling_axes": ("projectile_count", "attack_speed", "enemy_hitbox", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lancing_Steel_of_Spraying",
    },
    {
        "source_id": "lightning_strike.return_same_target_exception",
        "skill_gates": ("Lightning Strike",),
        "label": "Return same-target exception",
        "description": (
            "The initial emitted projectiles cannot immediately hit the same enemy struck by the melee "
            "portion, but returning projectiles can re-hit that target and become the main same-target "
            "scaling lever."
        ),
        "mechanic_tags": ("melee_projectile_partition", "same_target_gate", "return_exception"),
        "scaling_axes": ("return", "projectile_count", "positioning", "strike_range"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Strike",
    },
    {
        "source_id": "lightning_tendrils.third_pulse_crit_cadence",
        "skill_gates": ("Lightning Tendrils",),
        "label": "Third-pulse crit cadence",
        "description": (
            "Lightning Tendrils fires a stronger pulse every third pulse, and that stronger pulse always "
            "crits. Cast speed therefore scales not just raw hit frequency but also how quickly the "
            "skill cycles back to its guaranteed critical burst."
        ),
        "mechanic_tags": ("pulse_cycle", "guaranteed_crit", "burst_cadence"),
        "scaling_axes": ("cast_speed", "critical_strike_multiplier", "channel_uptime", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Tendrils",
    },
    {
        "source_id": "lightning_tendrils_of_escalation.channel_radius_ramp",
        "skill_gates": ("Lightning Tendrils of Escalation",),
        "label": "Channel-time radius ramp",
        "description": (
            "Lightning Tendrils of Escalation replaces the normal stronger-pulse cadence with a "
            "semicircular pulse whose radius grows while channeling, up to a fixed cap. Realized output "
            "therefore depends on staying in channel long enough to earn the larger hit area, not just on "
            "raw cast speed."
        ),
        "mechanic_tags": ("channel_radius_ramp", "coverage_growth", "channel_commitment", "pulse_area"),
        "scaling_axes": ("channel_uptime", "cast_speed", "area_of_effect", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Tendrils_of_Escalation",
    },
    {
        "source_id": "lightning_tendrils_of_eccentricity.fifth_pulse_burst_cadence",
        "skill_gates": ("Lightning Tendrils of Eccentricity",),
        "label": "Fifth-pulse burst cadence",
        "description": (
            "Lightning Tendrils of Eccentricity concentrates its damage into a much larger stronger "
            "pulse every fifth pulse, and that burst always crits. Realized DPS depends on staying in "
            "channel long enough to complete each five-pulse cycle, not just on nominal cast speed."
        ),
        "mechanic_tags": ("pulse_cycle", "guaranteed_crit", "burst_cadence", "channel_commitment"),
        "scaling_axes": ("cast_speed", "channel_uptime", "critical_strike_multiplier", "area_of_effect"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Tendrils_of_Eccentricity",
    },
    {
        "source_id": "vaal_lightning_strike.attack_speed_pulse_rate",
        "skill_gates": ("Vaal Lightning Strike",),
        "label": "Attack-speed pulse rate",
        "description": (
            "The attached orb repeatedly pulses while active, and attack speed scales that pulse cadence, "
            "so the Vaal effect gains damage from attack rate even after the initial strike."
        ),
        "mechanic_tags": ("attached_orb", "pulse_rate", "attack_speed_scaling"),
        "scaling_axes": ("attack_speed", "duration", "projectile_count", "target_attachment"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Lightning_Strike",
    },
    {
        "source_id": "vaal_lightning_strike.additional_strikes_no_extra_orbs",
        "skill_gates": ("Vaal Lightning Strike",),
        "label": "Additional strikes without extra orbs",
        "description": (
            "Additional strike targeting can help the opening hit connect elsewhere, but it does not create "
            "extra orbs; only the original Vaal strike establishes the lingering orb damage source."
        ),
        "mechanic_tags": ("additional_strikes", "single_orb_origin", "target_attachment"),
        "scaling_axes": ("additional_strike_targets", "positioning", "duration", "target_attachment"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Lightning_Strike",
    },
    {
        "source_id": "lacerate.center_double_hit",
        "skill_gates": ("Lacerate", "Lacerate of Butchering", "Lacerate of Haemorrhage"),
        "label": "Center double-hit zone",
        "description": (
            "Enemies positioned in the middle of the slashes can be struck by both halves of the "
            "attack."
        ),
        "mechanic_tags": ("double_hit", "center_overlap", "stance_geometry"),
        "scaling_axes": ("area_of_effect", "angle", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/List_of_attack_skill_gems",
    },
    {
        "source_id": "scourge_arrow.pod_shotgun",
        "skill_gates": ("Scourge Arrow", "Scourge Arrow of Menace"),
        "label": "Pod shotgun limit",
        "description": (
            "Thorn arrows from different pods can converge on one target, but multiple thorn arrows from "
            "the same pod cannot hit that target together."
        ),
        "mechanic_tags": ("shotgun", "pod_overlap", "projectile"),
        "scaling_axes": ("stage_count", "pod_count", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Scourge_Arrow",
    },
    {
        "source_id": "lightning_arrow_of_electrocution.stick_repeat_hits",
        "skill_gates": ("Lightning Arrow of Electrocution",),
        "label": "Stuck-arrow repeat hits",
        "description": (
            "The arrow sticks in the final target and deals several follow-up hits over time."
        ),
        "mechanic_tags": ("repeat_hit", "stuck_projectile", "single_target_ramp"),
        "scaling_axes": ("stuck_arrow_count", "duration", "hit_frequency"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/List_of_attack_skill_gems",
    },
    {
        "source_id": "kinetic_bolt_of_fragmentation.multi_projectile_overlap",
        "skill_gates": ("Kinetic Bolt of Fragmentation",),
        "label": "Fragment overlap",
        "description": (
            "Multiple spawned projectiles from one attack can hit the same target."
        ),
        "mechanic_tags": ("overlap", "fragmentation", "projectile"),
        "scaling_axes": ("projectile_count", "additional_direction_changes", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/List_of_attack_skill_gems",
    },
    {
        "source_id": "poisonous_concoction_of_bouncing.chain_multi_hit",
        "skill_gates": ("Poisonous Concoction of Bouncing",),
        "label": "Bounce chain multi-hit",
        "description": (
            "The bottle can bounce and deal damage multiple times as it chains on ground impacts."
        ),
        "mechanic_tags": ("chain", "multi_hit", "ground_bounce"),
        "scaling_axes": ("chain_count", "projectile_count_modifiers", "area_of_effect"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/List_of_attack_skill_gems",
    },
    {
        "source_id": "armageddon_brand.meteor_attachment_cadence",
        "skill_gates": ("Armageddon Brand",),
        "label": "Meteor attachment cadence",
        "description": (
            "Armageddon Brand only activates while attached, and each activation drops a meteor with travel "
            "time that can miss moving targets. Realized damage therefore depends on both activation frequency "
            "and keeping the enemy branded long enough for the meteor impacts to actually connect."
        ),
        "mechanic_tags": ("brand_attachment", "activation_frequency", "travel_delay", "hit_confirmation"),
        "scaling_axes": ("cast_speed", "brand_duration", "brand_limit", "enemy_movement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Armageddon_Brand",
    },
    {
        "source_id": "armageddon_brand_of_recall.recall_detach_activation_loop",
        "skill_gates": ("Armageddon Brand of Recall",),
        "label": "Recall detachment loop",
        "description": (
            "Armageddon Brand of Recall can be detached and reactivated through Brand Recall, which spends "
            "brand cost to force an activation and bypasses the attached-target hit penalty because that "
            "penalty only applies while the brand is attached."
        ),
        "mechanic_tags": ("brand_recall", "detachment_activation", "attached_penalty_bypass"),
        "scaling_axes": ("brand_recall_cooldown", "mana_budget", "attachment_range", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Armageddon_Brand_of_Recall",
    },
    {
        "source_id": "armageddon_brand_of_volatility.single_activation_throughput",
        "skill_gates": ("Armageddon Brand of Volatility",),
        "label": "Single-activation throughput",
        "description": (
            "Armageddon Brand of Volatility activates exactly once when it attaches, then destroys itself and "
            "cannot be recalled. Its throughput is therefore governed by how quickly you can place and attach "
            "fresh brands rather than by long attachment duration or repeat-frequency scaling."
        ),
        "mechanic_tags": ("single_activation", "brand_attachment", "self_expire", "no_recall"),
        "scaling_axes": ("cast_speed", "brand_limit", "attachment_speed", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Armageddon_Brand_of_Volatility",
    },
    {
        "source_id": "battlemages_cry.first_hit_trigger_budget",
        "skill_gates": ("Battlemage's Cry",),
        "label": "First-hit trigger budget",
        "description": (
            "Battlemage's Cry only triggers its supported spell from the first melee hit of each exerted "
            "attack, and exerts are spent even if the attack is interrupted or misses. Spell output is "
            "therefore limited by exert count, warcry refresh rate, and reliable melee contact."
        ),
        "mechanic_tags": ("trigger_proxy", "first_hit_only", "exert_budget", "melee_contact_gate"),
        "scaling_axes": ("warcry_cooldown_recovery", "attack_speed", "exert_count", "accuracy"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Battlemage%27s_Cry",
    },
    {
        "source_id": "generals_cry.mirage_spawn_cadence",
        "skill_gates": ("General's Cry",),
        "label": "Mirage spawn cadence",
        "description": (
            "General's Cry creates mirage warriors from nearby corpses, but they spawn in a staggered "
            "sequence and each only performs one linked attack before disappearing. Practical DPS depends on "
            "corpse supply, mirage count, and the fixed spawn cadence more than on repeat mechanics."
        ),
        "mechanic_tags": ("proxy_warrior", "corpse_gate", "staggered_spawn", "single_attack"),
        "scaling_axes": ("corpse_supply", "warcry_power", "warcry_cooldown_recovery", "attack_skill_selection"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/General%27s_Cry",
    },
    {
        "source_id": "infernal_cry.dual_payload_exert_loop",
        "skill_gates": ("Infernal Cry",),
        "label": "Dual-payload exert loop",
        "description": (
            "Infernal Cry has two separate damage payloads: a secondary on-death explosion on debuffed "
            "enemies and the Combust melee attack triggered by exerted hits. Clear scales with kill sequencing "
            "and monster life, while single-target scales with how quickly exerted attacks are spent."
        ),
        "mechanic_tags": ("secondary_damage", "on_death_explosion", "exerted_payload", "dual_payload"),
        "scaling_axes": ("kill_rate", "monster_life", "attack_speed", "warcry_cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Infernal_Cry",
    },
    {
        "source_id": "penance_brand.shared_energy_ramp",
        "skill_gates": (
            "Penance Brand",
            "Penance Brand of Conduction",
            "Penance Brand of Dissipation",
        ),
        "label": "Shared Energy ramp",
        "description": (
            "Activation frequency controls time to the shared 20 Energy cap, multiple attached brands "
            "accelerate that ramp, and Brand Recall or other detach effects reset Energy instead of "
            "preserving it."
        ),
        "mechanic_tags": ("shared_counter", "activation_ramp", "detachment_reset"),
        "scaling_axes": ("activation_frequency", "brand_count", "brand_recall", "detachment_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Penance_Brand",
    },
    {
        "source_id": "perforate.blood_overlap_tradeoff",
        "skill_gates": ("Perforate", "Perforate of Bloodshed", "Perforate of Duality"),
        "label": "Blood overlap tradeoff",
        "description": (
            "Blood Stance can land several spike hits on one target at close range, but more area "
            "spreads the spikes and can lower single-target overlap; Sand Stance stays single-hit per "
            "slam."
        ),
        "mechanic_tags": ("multi_hit", "stance_geometry", "aoe_overlap_tradeoff"),
        "scaling_axes": ("area_of_effect", "stance", "positioning", "spike_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Perforate",
    },
    {
        "source_id": "seismic_trap.wave_overlap_positioning",
        "skill_gates": ("Seismic Trap", "Seismic Trap of Swells"),
        "label": "Wave overlap positioning",
        "description": (
            "Increasing area increases each wave radius and can unlock more overlaps, while placing "
            "traps around the target rather than directly under it improves the chance that multiple "
            "waves converge on the same enemy."
        ),
        "mechanic_tags": ("overlap", "trap_positioning", "aoe_breakpoint"),
        "scaling_axes": ("area_of_effect", "trap_placement", "enemy_hitbox", "wave_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Seismic_Trap",
    },
    {
        "source_id": "shockwave_totem.astral_projector_target_relocation",
        "skill_gates": ("Shockwave Totem",),
        "label": "Astral Projector target relocation",
        "description": (
            "Shockwave Totem is a nova spell cast by a totem, so Astral Projector relocates the nova to the "
            "targeted enemy position instead of forcing the pulse to originate only from the totem's base."
        ),
        "mechanic_tags": ("nova_relocation", "totem_proxy", "positioning_breakpoint", "unique_interaction"),
        "scaling_axes": ("targeting", "area_of_effect", "totem_placement", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shockwave_Totem",
    },
    {
        "source_id": "shockwave_totem_of_authority.owner_centered_nova_lock",
        "skill_gates": ("Shockwave Totem of Authority",),
        "label": "Owner-centered nova lock",
        "description": (
            "Shockwave Totem of Authority centers its shockwaves on the character rather than the totem, so "
            "its realized damage depends on staying in range yourself and Astral Projector does not redirect "
            "those pulses away from the owner."
        ),
        "mechanic_tags": ("owner_centered", "totem_proxy", "range_lock", "unique_interaction"),
        "scaling_axes": ("positioning", "area_of_effect", "movement_uptime", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shockwave_Totem_of_Authority",
    },
    {
        "source_id": "shock_nova.dual_ring_overlap",
        "skill_gates": ("Shock Nova",),
        "label": "Dual-ring overlap geometry",
        "description": (
            "Shock Nova has an initial ring and a follow-up larger damaging area, and a target in the "
            "correct band can be struck by both components in one cast. Area of effect changes the ring "
            "geometry and therefore the double-hit breakpoint."
        ),
        "mechanic_tags": ("dual_hit", "aoe_geometry", "positioning_breakpoint"),
        "scaling_axes": ("area_of_effect", "positioning", "enemy_hitbox", "added_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shock_Nova",
    },
    {
        "source_id": "shock_nova_of_procession.repeat_spacing_overlap",
        "skill_gates": ("Shock Nova of Procession",),
        "label": "Repeat-spacing overlap",
        "description": (
            "This version repeats its nova in a line, and area modifiers change both the nova size and the "
            "spacing between repeats. Realized overlap therefore depends on AoE breakpoints, wall stops, "
            "and whether repeated rings can clip the same target path."
        ),
        "mechanic_tags": ("repeating_nova", "aoe_spacing", "wall_stop", "overlap_breakpoint"),
        "scaling_axes": ("area_of_effect", "positioning", "terrain_geometry", "repeat_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shock_Nova_of_Procession",
    },
    {
        "source_id": "purifying_flame.single_hit_per_cast_ground_wave",
        "skill_gates": ("Purifying Flame", "Purifying Flame of Revelations"),
        "label": "Single-hit-per-cast ground wave",
        "description": (
            "The expanding shockwave only damages enemies standing on consecrated ground that were not "
            "already hit by the initial cast, so each enemy can take damage only once per cast. Area of "
            "effect scales the line width, impact explosion, and ground size, while duration extends the "
            "consecrated ground uptime."
        ),
        "mechanic_tags": ("anti_overlap", "ground_wave", "aoe_scaling", "duration_scaling"),
        "scaling_axes": ("area_of_effect", "duration", "positioning", "ground_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Purifying_Flame",
    },
    {
        "source_id": "shrapnel_ballista.multi_arrow_overlap",
        "skill_gates": ("Shrapnel Ballista", "Shrapnel Ballista of Steel"),
        "label": "Multi-arrow overlap",
        "description": (
            "A single ballista attack can land multiple arrows on the same enemy."
        ),
        "mechanic_tags": ("overlap", "projectile", "totem_attack"),
        "scaling_axes": ("arrow_count", "projectile_spread", "positioning"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/List_of_attack_skill_gems",
    },
    {
        "source_id": "rolling_magma.extra_chain_bounces",
        "skill_gates": ("Rolling Magma",),
        "label": "Additional chain bounce scaling",
        "description": (
            "Rolling Magma bounces forward in the same direction, and extra chain count adds extra "
            "bounces instead of redirecting to new targets."
        ),
        "mechanic_tags": ("chain", "ground_bounce", "repeat_hit"),
        "scaling_axes": ("chain_count", "area_of_effect", "projectile_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Projectile",
    },
    {
        "source_id": "rain_of_arrows.multi_hit_density",
        "skill_gates": ("Rain of Arrows",),
        "label": "Multi-hit density",
        "description": (
            "A single enemy can be hit by multiple falling arrows, but extra arrows are added toward "
            "the outer coverage instead of concentrating more hits on one target."
        ),
        "mechanic_tags": ("multi_hit", "volley_density", "coverage_bias"),
        "scaling_axes": ("area_of_effect", "enemy_hitbox", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Rain_of_Arrows",
    },
    {
        "source_id": "rain_of_arrows_of_artillery.forward_line_density",
        "skill_gates": ("Rain of Arrows of Artillery",),
        "label": "Forward line density",
        "description": (
            "This version drops arrows in sequence along a forward line instead of a circular spread. "
            "Additional projectiles add more total impacts along that lane, so single-target damage depends "
            "on line placement and how much of that sequence passes through the target's hitbox."
        ),
        "mechanic_tags": ("forward_lane", "sequential_impacts", "line_overlap"),
        "scaling_axes": ("projectile_count", "area_of_effect", "positioning", "enemy_hitbox"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Rain_of_Arrows_of_Artillery",
    },
    {
        "source_id": "rain_of_arrows_of_saturation.slower_higher_single_target_density",
        "skill_gates": ("Rain of Arrows of Saturation",),
        "label": "Slower, denser arrow rain",
        "description": (
            "This version lands more arrows over a slower sequence, which raises the number of same-target "
            "hits a boss can take from one use even though the arrows arrive less quickly."
        ),
        "mechanic_tags": ("multi_hit", "slower_sequence", "higher_density"),
        "scaling_axes": ("projectile_count", "enemy_hitbox", "positioning", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Rain_of_Arrows_of_Saturation",
    },
    {
        "source_id": "vaal_rain_of_arrows.sequential_volley_density",
        "skill_gates": ("Vaal Rain of Arrows",),
        "label": "Sequential volley density",
        "description": (
            "Vaal Rain of Arrows lands four full arrow sequences onto one target area, so same-target value "
            "depends on keeping enemies inside that repeated rain long enough to take several sequences "
            "instead of treating the skill like one impact."
        ),
        "mechanic_tags": ("sequential_volleys", "multi_sequence", "maim_window", "area_residency"),
        "scaling_axes": ("enemy_hitbox", "target_movement", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Rain_of_Arrows",
    },
    {
        "source_id": "spark.rehit_after_rearm",
        "skill_gates": ("Spark",),
        "label": "Projectile re-arm re-hit",
        "description": (
            "A moving spark can hit the same enemy again after enough travel time or a bounce resets "
            "its hit eligibility."
        ),
        "mechanic_tags": ("repeat_hit", "projectile_rearm", "terrain_bounce"),
        "scaling_axes": ("duration", "projectile_speed", "terrain_density", "pierce"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spark",
    },
    {
        "source_id": "spark.duration_terrain_residency",
        "skill_gates": ("Spark", "Vaal Spark"),
        "include_transfigured": True,
        "label": "Duration-controlled terrain residency",
        "description": (
            "Spark duration controls how long projectiles can stay active, and they ricochet off "
            "terrain for as long as they persist. Enemy hits absorb a spark unless it pierces, and "
            "return mechanics do not help because sparks time out before returning."
        ),
        "mechanic_tags": ("terrain_ricochet", "duration_residency", "pierce_gate", "return_invalid"),
        "scaling_axes": ("duration", "projectile_speed", "terrain_geometry", "pierce"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spark",
    },
    {
        "source_id": "splitting_steel.additional_projectiles_split_targets",
        "skill_gates": ("Splitting Steel",),
        "label": "Additional projectiles become split targets",
        "description": (
            "Splitting Steel always fires one initial projectile, and extra projectile scaling "
            "converts into more split targets instead of more opening shots."
        ),
        "mechanic_tags": ("single_initial_projectile", "projectile_to_split_conversion", "target_fanout"),
        "scaling_axes": ("projectile_count", "enemy_density", "split_targets", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Splitting_Steel",
    },
    {
        "source_id": "splitting_steel_of_ammunition.target_conversion_shard_floor",
        "skill_gates": ("Splitting Steel of Ammunition",),
        "label": "Split-target conversion with shard floor",
        "description": (
            "Projectile-count modifiers become additional split targets, but with no Steel Shards the "
            "skill still launches only one projectile. It can also split at the targeted location "
            "without first colliding with an enemy."
        ),
        "mechanic_tags": ("single_initial_projectile", "projectile_to_split_conversion", "steel_shard_gate", "free_split"),
        "scaling_axes": ("projectile_count", "steel_shards", "split_targets", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Splitting_Steel_of_Ammunition",
    },
    {
        "source_id": "swordstorm.block_window_eight_hit_dual_wield_burst",
        "skill_gates": ("Swordstorm",),
        "label": "Block window with eight-hit dual-wield burst",
        "description": (
            "Swordstorm only becomes usable for a short window after blocking a hit, then delivers eight "
            "unavoidable hits that each combine both weapons' damage. Realized output therefore scales "
            "with block cadence, keeping enemies inside the storm for the full burst, and the quality of "
            "both weapon damage rolls rather than only one hand."
        ),
        "mechanic_tags": ("retaliation_window", "block_gate", "repeat_hit", "dual_wield_combined_damage"),
        "scaling_axes": ("block_rate", "enemy_residency", "dual_wield_damage", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Swordstorm",
    },
    {
        "source_id": "storm_burst.orb_overlap_timing",
        "skill_gates": ("Storm Burst", "Storm Burst of Repulsion"),
        "label": "Orb overlap timing",
        "description": (
            "Orbs spread like buckshot and keep independent 0.4-second jump timers; more area improves "
            "overlap and hit rate without tightening the spread, while cast speed only creates more orbs."
        ),
        "mechanic_tags": ("overlap", "repeat_hit", "independent_interval", "release_explosion"),
        "scaling_axes": ("area_of_effect", "cast_speed", "duration", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Storm_Burst",
    },
    {
        "source_id": "storm_rain.beam_repeat_hits",
        "skill_gates": ("Storm Rain", "Storm Rain of the Conduit", "Storm Rain of the Fence"),
        "label": "Beam repeat-hit cap",
        "description": (
            "Extra projectiles add more active arrows up to the arrow cap, and each grounded arrow can "
            "beam-hit the same enemy multiple times during its active window."
        ),
        "mechanic_tags": ("repeat_hit", "beam_link", "arrow_cap"),
        "scaling_axes": ("projectile_count", "active_arrow_count", "duration", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Storm_Rain",
    },
    {
        "source_id": "thunderstorm.global_attack_speed_stage_ramp_and_thunderburst_rehits",
        "skill_gates": ("Thunderstorm",),
        "label": "Global-attack-speed stage ramp and Thunderburst rehits",
        "description": (
            "Thunderstorm gains stages on a fixed timer scaled by global attack speed, can maintain up to "
            "three storms, and only the Thunderburst projectile package benefits from projectile-count "
            "modifiers. Those projectiles pierce, can split, and may hit the same enemy again after "
            "splitting, so realized output depends on storm uptime, stage count, and burst positioning."
        ),
        "mechanic_tags": ("stage_ramp", "global_attack_speed", "multi_storm_cap", "secondary_projectiles", "split_rehit"),
        "scaling_axes": ("global_attack_speed", "storm_count", "duration", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Thunderstorm",
    },
    {
        "source_id": "storm_call.duration_delay_compression",
        "skill_gates": ("Storm Call",),
        "label": "Duration delay compression",
        "description": (
            "Skill effect duration changes the wait time between placing a Storm Call marker and the "
            "lightning strike. Less duration compresses the delay window for faster realized damage, while "
            "longer duration makes the marker easier to preload but slower to convert into hits."
        ),
        "mechanic_tags": ("delay_window", "duration_scaling", "realized_dps"),
        "scaling_axes": ("duration", "cast_speed", "preload_count", "target_movement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Storm_Call",
    },
    {
        "source_id": "vaal_storm_call.random_strike_window_and_marker_finale",
        "skill_gates": ("Vaal Storm Call",),
        "label": "Random strike window and marker finale",
        "description": (
            "Vaal Storm Call leaves an active marker that repeatedly strikes random nearby enemies before a "
            "final centered bolt resolves and can also trigger the skill's other markers. Realized output "
            "therefore scales with marker uptime, enemy density, and multi-marker setup."
        ),
        "mechanic_tags": ("duration_window", "random_strikes", "marker_finale", "multi_marker_chain"),
        "scaling_axes": ("duration", "enemy_density", "marker_count", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Storm_Call",
    },
    {
        "source_id": "stormblast_mine.undetonated_aura_stack_cap",
        "skill_gates": ("Stormblast Mine",),
        "label": "Undetonated aura stack cap",
        "description": (
            "Each mine applies a local increased-damage-taken aura up to a hard cap, and the aura radius "
            "scales with area and aura modifiers. Aura effect improves the damage-taken bonus per mine but "
            "not the maximum cap, and the debuff can boost other skills while the mines remain undetonated."
        ),
        "mechanic_tags": ("aura_stack", "global_debuff", "cap_scaling", "non_detonated_value"),
        "scaling_axes": ("mine_count", "area_of_effect", "aura_effect", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Stormblast_Mine",
    },
    {
        "source_id": "spectral_helix.low_speed_multi_hit",
        "skill_gates": ("Spectral Helix",),
        "label": "Low-speed multi-hit scaling",
        "description": (
            "Spectral Helix gains single-target damage when reduced projectile speed keeps the spiral on "
            "top of a target for more hits."
        ),
        "mechanic_tags": ("repeat_hit", "projectile_pathing", "speed_scaling"),
        "scaling_axes": ("projectile_speed", "positioning", "bounce_count", "projectile_pathing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Projectile",
    },
    {
        "source_id": "spectral_helix_of_trarthus.trap_spacing_and_dual_wield_routing",
        "skill_gates": ("Spectral Helix of Trarthus",),
        "label": "Trap spacing, random weapon routing, and bounce substitution",
        "description": (
            "Spectral Helix of Trarthus becomes a trap skill: dual wielding throws two spaced traps by "
            "default, each trap uses a random equipped weapon, and projectile-count modifiers add bounces "
            "instead of more traps. Real output therefore scales through trap throw speed, weapon pairing, "
            "bounce count, and where those separate traps land."
        ),
        "mechanic_tags": ("trap_conversion", "dual_trap_spawn", "random_weapon_routing", "bounce_substitution"),
        "scaling_axes": ("trap_throw_speed", "weapon_pairing", "bounce_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Helix_of_Trarthus",
    },
    {
        "source_id": "tornado_shot.secondary_set_collision",
        "skill_gates": ("Tornado Shot",),
        "label": "Secondary-set collision budget",
        "description": (
            "Each primary arrow spawns its own secondary set, and one secondary from each set can collide "
            "with the same enemy, so extra primaries scale overlap sets."
        ),
        "mechanic_tags": ("secondary_projectile", "multi_set_collision", "additional_projectiles"),
        "scaling_axes": ("projectile_count", "secondary_set_count", "positioning", "projectile_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tornado_Shot",
    },
    {
        "source_id": "tornado_shot_of_cloudburst.delayed_payload_arrow_radial_release",
        "skill_gates": ("Tornado Shot of Cloudburst",),
        "label": "Delayed payload arrow radial release",
        "description": (
            "Tornado Shot of Cloudburst fires one payload arrow that lands at the target point before "
            "releasing a circular volley from that impact location, so realized overlap depends on where "
            "the payload lands relative to enemy hitboxes rather than on ordinary bow spread from the player."
        ),
        "mechanic_tags": ("payload_arrow", "radial_secondary_release", "impact_origin"),
        "scaling_axes": ("projectile_speed", "positioning", "enemy_size", "projectile_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tornado_Shot_of_Cloudburst",
    },
    {
        "source_id": "toxic_rain.pod_overlap_breakpoints",
        "skill_gates": ("Toxic Rain",),
        "include_transfigured": True,
        "activation_mechanic_family_ids": ("overlap_family",),
        "activation_package_ids": ("toxic_rain_overlap_package",),
        "label": "Pod overlap breakpoints",
        "description": (
            "Additional projectiles mainly widen pod coverage, while area modifiers change both pod "
            "radius and spread, creating single-target overlap breakpoints instead of linear scaling."
        ),
        "mechanic_tags": ("pod_overlap", "breakpoint", "coverage_bias"),
        "scaling_axes": ("area_of_effect", "projectile_count", "enemy_hitbox", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Toxic_Rain",
    },
    {
        "source_id": "void_sphere.delayed_first_pulse_single_limit",
        "skill_gates": ("Void Sphere",),
        "label": "Delayed first pulse and single-sphere limit",
        "description": (
            "Void Sphere does not pulse immediately on cast, only starts dealing damage after the first "
            "interval, and allows only one active sphere at a time. Single-target value therefore scales "
            "through pulse uptime and target residency rather than by stacking multiple simultaneous spheres."
        ),
        "mechanic_tags": ("delayed_first_hit", "fixed_pulse_interval", "single_instance_limit", "pull_residency"),
        "scaling_axes": ("duration", "area_of_effect", "positioning", "enemy_movement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Void_Sphere",
    },
    {
        "source_id": "void_sphere_of_rending.cooldownless_pulse_density",
        "skill_gates": ("Void Sphere of Rending",),
        "label": "Cooldownless pulse density",
        "description": (
            "Void Sphere of Rending trades radius and duration for faster pulses and no cooldown, but it "
            "still keeps the one-sphere active limit. Its damage scaling is therefore about fitting more "
            "pulse intervals into each short-duration sphere rather than overlapping separate spheres."
        ),
        "mechanic_tags": ("fixed_pulse_interval", "cooldownless_recast", "single_instance_limit", "duration_density"),
        "scaling_axes": ("duration", "cast_speed", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Void_Sphere_of_Rending",
    },
    {
        "source_id": "fire_trap.hit_plus_ground_nonstack",
        "skill_gates": ("Fire Trap",),
        "include_transfigured": True,
        "label": "Hit plus burning ground with non-stacking ground",
        "description": (
            "Fire Trap deals one upfront explosion hit and also leaves burning ground, so single-target "
            "damage combines hit and ground uptime. Overlapping Fire Trap burning ground does not stack, "
            "making extra trap coverage primarily a positioning and duration problem."
        ),
        "mechanic_tags": ("dual_payload", "ground_dot", "anti_overlap"),
        "scaling_axes": ("trap_multiplicity", "duration", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Fire_Trap",
    },
    {
        "source_id": "lightning_spire_trap.impact_site_overlap",
        "skill_gates": ("Lightning Spire Trap",),
        "include_transfigured": True,
        "label": "Impact-site overlap geometry",
        "description": (
            "Area modifiers only enlarge each strike site instead of widening the spire's whole attack "
            "footprint, so more area increases overlap between strike zones. Tight terrain also raises "
            "the chance that several strikes land onto the same target."
        ),
        "mechanic_tags": ("overlap", "area_geometry", "repeat_hit"),
        "scaling_axes": ("area_of_effect", "trap_throwing_speed", "trap_multiplicity", "terrain_size"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Spire_Trap",
    },
    {
        "source_id": "storm_brand.attachment_frequency_uptime",
        "skill_gates": ("Storm Brand",),
        "include_transfigured": True,
        "label": "Attachment-limited activation cadence",
        "description": (
            "Storm Brand only deals damage while attached, activating on a fixed interval that scales "
            "with cast speed. Realized DPS therefore depends on both activation frequency and how long "
            "brands stay attached before detaching or losing their target."
        ),
        "mechanic_tags": ("brand_attachment", "activation_frequency", "uptime_gate"),
        "scaling_axes": ("cast_speed", "brand_duration", "brand_limit", "enemy_longevity"),
        "evidence_basis": "skill_description",
        "evidence_url": "https://www.poewiki.net/wiki/Storm_Brand",
    },
    {
        "source_id": "wintertide_brand.dual_debuff_stage_ramp",
        "skill_gates": ("Wintertide Brand",),
        "label": "Dual-debuff stage ramp",
        "description": (
            "Each Wintertide Brand tracks its own stages and applies its own Wintertide debuff, while "
            "detaching also creates Wintertide's End. The attached debuff and Wintertide's End can both "
            "damage the same enemy, and activation frequency plus duration continue scaling average DPS "
            "because the default attachment window does not reach maximum stage."
        ),
        "mechanic_tags": ("brand_stage_ramp", "dual_debuff", "detachment_payload"),
        "scaling_axes": ("activation_frequency", "brand_duration", "brand_limit", "recast_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Wintertide_Brand",
    },
    {
        "source_id": "incinerate.tick_stage_final_wave",
        "skill_gates": ("Incinerate",),
        "include_transfigured": True,
        "label": "Tick-stage final-wave cycle",
        "description": (
            "Incinerate deals damage on every channelling tick, gains a stage every two ticks, and "
            "releases a final wave when the channel ends after gaining at least one stage. Cast speed "
            "therefore scales both stage gain cadence and how often fully scaled final waves can be fired."
        ),
        "mechanic_tags": ("channel_tick", "stage_ramp", "final_wave"),
        "scaling_axes": ("cast_speed", "channel_uptime", "stage_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Incinerate",
    },
    {
        "source_id": "divine_ire.channel_pulse_beam_split",
        "skill_gates": ("Divine Ire",),
        "include_transfigured": True,
        "label": "Channel pulse and beam split scaling",
        "description": (
            "Divine Ire repeatedly damages nearby enemies while gaining stages, then releases a burst "
            "and beam. Area modifiers scale the channelling pulses but do not change the beam's fixed "
            "geometry, so nearby clear and release-beam scaling diverge."
        ),
        "mechanic_tags": ("dual_payload", "channel_pulse", "beam_geometry_split"),
        "scaling_axes": ("cast_speed", "stage_count", "area_of_effect", "beam_width"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Divine_Ire",
    },
    {
        "source_id": "unearth.projectile_behaviour_corpse_placement",
        "skill_gates": ("Unearth",),
        "label": "Projectile behaviour corpse placement",
        "description": (
            "Unearth creates its corpse where the projectile resolves, so split, fork, chain, pierce, and "
            "return mechanics alter both hit coverage and where follow-up corpse consumers can be supplied."
        ),
        "mechanic_tags": ("corpse_generation", "projectile_resolution", "followup_setup", "terrain_geometry"),
        "scaling_axes": ("projectile_count", "chain", "fork", "return"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Unearth",
    },
    {
        "source_id": "vaal_fireball.async_shotgun",
        "skill_gates": ("Vaal Fireball",),
        "label": "Asynchronous projectile shotgun",
        "description": (
            "Vaal Fireball fires projectiles in sequence, so separate projectiles and their explosions "
            "can each hit the same target."
        ),
        "mechanic_tags": ("sequential_projectile", "shotgun", "projectile_explosion"),
        "scaling_axes": ("projectile_count", "area_of_effect", "duration", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Fireball",
    },
    {
        "source_id": "vaal_ice_nova.enemy_repeat_chain",
        "skill_gates": ("Vaal Ice Nova",),
        "label": "Enemy repeat chain",
        "description": (
            "Each nova that hits an enemy spawns a smaller repeat from that enemy, up to five repeats "
            "total, so more area raises the chance of chaining additional repeats."
        ),
        "mechanic_tags": ("repeat_chain", "enemy_anchor", "aoe_propagation"),
        "scaling_axes": ("area_of_effect", "enemy_density", "positioning", "repeat_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Ice_Nova",
    },
    {
        "source_id": "burning_arrow.hit_to_ignite_split_and_nonstacking_burn_identity",
        "skill_gates": ("Burning Arrow",),
        "label": "Hit-to-ignite split without legacy stacking burn",
        "description": (
            "Burning Arrow is now a direct fire-converted hit with ignite payoff rather than the old "
            "stacking secondary burn, so damage scaling splits between the weapon hit and one strong "
            "ignite application instead of stacking burn layers on the same target."
        ),
        "mechanic_tags": ("ignite_split_scaling", "full_fire_conversion", "single_ignite_identity"),
        "scaling_axes": ("physical_damage", "added_fire_damage", "ignite_magnitude", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Burning_Arrow",
    },
    {
        "source_id": "burning_arrow_of_vigour.max_life_added_fire_hit_and_ignite_payload",
        "skill_gates": ("Burning Arrow of Vigour",),
        "label": "Maximum-life fire payload",
        "description": (
            "Burning Arrow of Vigour adds fire damage from maximum life on top of full physical-to-fire "
            "conversion, so maximum life feeds both the hit and the ignite while attack rate controls how "
            "often that shared payload is delivered."
        ),
        "mechanic_tags": ("maximum_life_added_damage", "ignite_split_scaling", "full_fire_conversion"),
        "scaling_axes": ("maximum_life", "physical_damage", "ignite_magnitude", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Burning_Arrow_of_Vigour",
    },
    {
        "source_id": "vaal_burning_arrow.end_of_flight_explosion_pierce_routing",
        "skill_gates": ("Vaal Burning Arrow",),
        "label": "End-of-flight explosion with pierce routing",
        "description": (
            "Vaal Burning Arrow is ground-targeted and only explodes when the arrow reaches the end of its "
            "flight, after piercing through additional targets on the way. Realized single-target and "
            "clear therefore scale with projectile speed, pierce pathing, and where the flight endpoint is "
            "placed relative to enemies."
        ),
        "mechanic_tags": ("ground_targeted", "end_of_flight_explosion", "pierce_routing"),
        "scaling_axes": ("projectile_speed", "pierce", "distance_to_target", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Burning_Arrow",
    },
    {
        "source_id": "vaal_caustic_arrow.flight_path_ground_trail_nonstack",
        "skill_gates": ("Vaal Caustic Arrow",),
        "label": "Flight-path ground trail with non-stacking damage",
        "description": (
            "Vaal Caustic Arrow flies horizontally, pierces all enemies, and lays caustic ground along its "
            "entire flight path, but each enemy can only be affected by one such ground effect at a time. "
            "Its damage therefore scales by path coverage and refresh control rather than stacking multiple "
            "trails on a single target."
        ),
        "mechanic_tags": ("flight_path_trail", "pierce_all", "ground_dot_nonstack", "horizontal_projectile"),
        "scaling_axes": ("projectile_speed", "flight_path_length", "duration", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Caustic_Arrow",
    },
    {
        "source_id": "vaal_cleave.kill_gated_rare_mod_theft_and_cleave_buff",
        "skill_gates": ("Vaal Cleave",),
        "label": "Kill-gated rare-mod theft and Cleave buff",
        "description": (
            "Vaal Cleave attacks with both weapons at once, but its rare-mod theft and follow-up Cleave "
            "buff only pay out when kills or culls are actually secured. Skill effect duration extends the "
            "stolen-mod window and buff uptime while also lengthening soul gain prevention, so realized "
            "value scales with rare density, cull reliability, and dual-wield hit quality."
        ),
        "mechanic_tags": ("dual_wield_combined_damage", "kill_gate", "rare_mod_theft", "buff_window", "culling_strike"),
        "scaling_axes": ("rare_density", "skill_effect_duration", "cull_reliability", "dual_wield_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Cleave",
    },
    {
        "source_id": "vaal_cold_snap.player_anchor_charge_density_and_cold_dot_stack",
        "skill_gates": ("Vaal Cold Snap",),
        "label": "Player-anchored Frenzy density and cold DoT stacking",
        "description": (
            "Vaal Cold Snap creates a chilling-ground damage field around the player, grants Frenzy Charges "
            "every second per enemy inside it, and its damage over time stacks with other cold DoT "
            "sources. Realized payoff therefore scales with enemy density, field uptime, movement routing, "
            "and how many other cold DoT layers can be maintained."
        ),
        "mechanic_tags": ("player_anchor", "ground_dot", "charge_generation", "dot_stacking"),
        "scaling_axes": ("enemy_density", "duration", "movement_path", "cold_dot_layer_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Cold_Snap",
    },
    {
        "source_id": "vaal_domination.ascended_sentinel_refresh_and_modifier_retention",
        "skill_gates": ("Vaal Domination",),
        "label": "Ascended sentinel refresh and modifier retention",
        "description": (
            "Vaal Domination upgrades an existing Sentinel of Dominance into an Ascended Sentinel that "
            "keeps its monster modifiers, support-gem bonuses, and current buff or debuff state. It also "
            "uses a separate ascended cap and refreshes an existing ascended sentinel when already capped, "
            "so realized damage scales with roster quality, uptime, and kill supply."
        ),
        "mechanic_tags": ("minion_upgrade", "modifier_retention", "separate_cap", "refresh_on_cap"),
        "scaling_axes": ("sentinel_roster", "duration", "kill_rate", "soul_gain_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Domination",
    },
    {
        "source_id": "vaal_earthquake.movement_crack_train_and_step_shockwaves",
        "skill_gates": ("Vaal Earthquake",),
        "label": "Movement-driven crack train and step shockwaves",
        "description": (
            "After the initial slam, moving creates the next crack as soon as the previous one erupts, up "
            "to the skill's crack cap, while each step also emits smaller shockwaves around the player. "
            "Realized output therefore scales with movement speed, path length, enemy residency along the "
            "route, and completing the full crack train before the secondary duration expires."
        ),
        "mechanic_tags": ("movement_driven_repeat", "crack_train", "step_shockwaves", "secondary_duration"),
        "scaling_axes": ("movement_speed", "path_length", "secondary_duration", "enemy_residency", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Earthquake",
    },
    {
        "source_id": "vaal_firestorm.spiral_impact_sequence_and_burning_ground_tradeoff",
        "skill_gates": ("Vaal Firestorm",),
        "label": "Spiral impact train plus burning ground follow-through",
        "description": (
            "Vaal Firestorm drops a fixed spiral of impacts that finishes with a centered hit on the target "
            "point, then leaves burning ground behind. Realized damage therefore splits between keeping "
            "targets inside the sequential impact path and cashing in the lingering ground burn, while spell "
            "damage only scales the hit portion rather than the burning ground."
        ),
        "mechanic_tags": (
            "fixed_impact_sequence",
            "spiral_impact_pattern",
            "burning_ground_followup",
            "split_hit_and_ground_payload",
        ),
        "scaling_axes": ("enemy_residency", "area_of_effect", "fire_dot_multiplier", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Firestorm",
    },
    {
        "source_id": "vaal_flameblast.auto_stage_bursts_and_radius_collapse",
        "skill_gates": ("Vaal Flameblast",),
        "label": "Automatic stage bursts with shrinking radius",
        "description": (
            "Vaal Flameblast charges itself based on cast speed and detonates every three stages until it "
            "reaches fifteen total, while each later burst hits harder but in a smaller area. Its ceiling is "
            "therefore tied to cast speed, area scaling, and whether enemies stay inside the increasingly "
            "tighter late-stage blasts."
        ),
        "mechanic_tags": (
            "automatic_stage_gain",
            "periodic_burst_sequence",
            "radius_collapse",
            "late_stage_damage_ramp",
        ),
        "scaling_axes": ("cast_speed", "area_of_effect", "enemy_movement", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Flameblast",
    },
    {
        "source_id": "vaal_flicker_strike.wound_stack_finisher_and_block_fragmentation",
        "skill_gates": ("Vaal Flicker Strike",),
        "label": "Wound stacking into one finisher with per-wound block rolls",
        "description": (
            "Vaal Flicker Strike's teleports apply zero-damage wound hits, then one finishing strike deals "
            "the combined damage of the wounds on each enemy. Each wound can be blocked separately and a "
            "blocked finisher suppresses damaging ailments and final on-hit payouts, so real scaling is about "
            "landing a huge consolidated finisher rather than dealing damage during the repeats themselves."
        ),
        "mechanic_tags": (
            "zero_damage_wound_hits",
            "combined_finisher",
            "per_wound_block_rolls",
            "single_hit_ailment_payload",
        ),
        "scaling_axes": ("repeat_count", "attack_damage", "crit_scaling", "ailment_scaling"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Flicker_Strike",
    },
    {
        "source_id": "vaal_ground_slam.exertable_radial_wave_close_range_and_fast_soul_loop",
        "skill_gates": ("Vaal Ground Slam",),
        "label": "Exertable radial wave with close-range damage and fast soul reset",
        "description": (
            "Vaal Ground Slam sends a radial wave that deals more damage to close targets and, unlike other "
            "vaal skills, can be exerted by warcries. Its unusually short soul gain prevention also lets kill "
            "dense content recycle the skill quickly, so realized output scales with proximity, exert bonuses, "
            "and how reliably one slam refills the next use."
        ),
        "mechanic_tags": ("radial_wave", "close_range_more_damage", "warcry_exertable", "fast_soul_recycle"),
        "scaling_axes": ("proximity", "warcry_exert_bonuses", "soul_gain_rate", "area_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Ground_Slam",
    },
    {
        "source_id": "vaal_molten_shell.armour_absorb_reflected_pulses_and_separate_guard_cooldown",
        "skill_gates": ("Vaal Molten Shell",),
        "label": "Armour-scaled absorb pool with reflected pulses and separate Guard cooldown",
        "description": (
            "Vaal Molten Shell adds armour and converts absorbed hit damage into reflected fire bursts based "
            "on how much damage the shell has taken, so its payoff scales with armour, duration, and the size "
            "of incoming hits routed into the buff. Because that damage is reflected, it ignores ordinary "
            "damage modifiers and cannot crit, penetrate, ailment, or apply on-hit effects, while also using "
            "its own cooldown lane instead of the normal shared Guard cooldown."
        ),
        "mechanic_tags": (
            "armour_scaled_absorb_pool",
            "reflected_damage_payload",
            "separate_guard_cooldown",
            "no_standard_hit_scaling",
        ),
        "scaling_axes": ("armour", "duration", "incoming_hit_size", "guard_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Molten_Shell",
    },
    {
        "source_id": "vaal_righteous_fire.sacrifice_snapshot_duration_and_nonhit_self_cost",
        "skill_gates": ("Vaal Righteous Fire",),
        "label": "Sacrifice snapshot with duration-vs-recharge tradeoff",
        "description": (
            "Vaal Righteous Fire snapshots a burn from the total Life and Energy Shield it sacrifices on use, "
            "so its damage ceiling scales with larger combined pools rather than steady self-burn sustain like "
            "the normal skill. The self-sacrifice is not a hit and does not interrupt Energy Shield recharge, "
            "while duration scaling boosts both the burn window and soul gain prevention, creating a real "
            "tradeoff between uptime per cast and how fast the vaal skill can cycle again."
        ),
        "mechanic_tags": (
            "life_and_es_sacrifice_snapshot",
            "non_hit_self_cost",
            "duration_vs_soul_gain_tradeoff",
            "recharge_preserving_self_cost",
        ),
        "scaling_axes": ("maximum_life", "maximum_energy_shield", "skill_effect_duration", "soul_gain_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Righteous_Fire",
    },
    {
        "source_id": "vaal_smite.overlapping_bolts_and_priority_aura_window",
        "skill_gates": ("Vaal Smite",),
        "label": "Overlapping bolt areas plus priority aura window",
        "description": (
            "Vaal Smite separates its melee strike from the lightning bolt area, and bolt areas from nearby "
            "enemies can overlap for extra damage on one target even though the area portion is not melee "
            "damage. A successful hit also grants the stronger Vaal Smite aura, which overrides regular Smite's "
            "aura and upgrades subsequent Smite strikes, so realized damage scales with enemy clustering and "
            "how well the aura window is converted into follow-up attacks."
        ),
        "mechanic_tags": (
            "separate_strike_and_bolt_regions",
            "bolt_overlap",
            "priority_aura_override",
            "followup_attack_window",
        ),
        "scaling_axes": ("enemy_clustering", "aura_duration", "attack_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Smite",
    },
    {
        "source_id": "manabond.current_mana_recalc_missing_mana_payload_tradeoff",
        "skill_gates": ("Manabond",),
        "label": "Current-mana recalculation tradeoff",
        "description": (
            "Manabond spends a percentage of maximum mana every cast, but its lightning payload scales from "
            "currently missing unreserved mana while its lateral coverage scales from remaining unreserved mana. "
            "Repeated casts therefore recalculate into a moving damage-versus-area tradeoff instead of snapshotting."
        ),
        "mechanic_tags": ("missing_mana_scaling", "current_mana_recalculation", "mana_cost_tradeoff"),
        "scaling_axes": ("maximum_mana", "unreserved_mana", "mana_recovery", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Manabond",
    },
    {
        "source_id": "vigilant_strike.endurance_charge_bypass_and_stun_refuel_loop",
        "skill_gates": ("Vigilant Strike",),
        "label": "Endurance-charge bypass and stun refuel loop",
        "description": (
            "Vigilant Strike's cooldown can be bypassed by spending an Endurance Charge, and stun-based "
            "charge refunds can feed that spend back into the next attack. Real throughput therefore scales "
            "around charge generation and stun consistency more than around waiting out the base cooldown."
        ),
        "mechanic_tags": ("cooldown_bypass", "endurance_charge_spend", "stun_refuel"),
        "scaling_axes": ("endurance_charge_generation", "stun_uptime", "attack_speed", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vigilant_Strike",
    },
    {
        "source_id": "vaal_venom_gyre.capacity_override_whirling_blades_dump_and_return_rules",
        "skill_gates": ("Vaal Venom Gyre",),
        "label": "Capacity override that cashes out through Whirling Blades",
        "description": (
            "Vaal Venom Gyre does not deal damage by itself; instead it temporarily raises the caught-projectile "
            "cap, instantly fills you to that cap, and continues granting more projectiles over a secondary "
            "duration. Realized damage therefore comes from how efficiently Whirling Blades dumps those stored "
            "projectiles, plus how pierce, fork, chain, and return rules shape the outgoing, returning, and "
            "caught-projectile portions of the loop."
        ),
        "mechanic_tags": (
            "no_direct_damage",
            "caught_projectile_capacity_override",
            "whirling_blades_release_loop",
            "projectile_rule_partition",
        ),
        "scaling_axes": ("caught_projectile_cap", "secondary_duration", "whirling_blades_pathing", "projectile_behaviour"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Venom_Gyre",
    },
    {
        "source_id": "vaal_volcanic_fissure.tracking_multi_eruption_projectile_train",
        "skill_gates": ("Vaal Volcanic Fissure",),
        "label": "Tracking fissure chain with repeated projectile eruptions",
        "description": (
            "Vaal Volcanic Fissure sends out a travelling fissure that erupts at the target point, fires a "
            "burst of molten projectiles, then keeps seeking additional enemies for several more eruptions. "
            "Its real ceiling therefore scales with pack density, pathing, and how often both the travelling "
            "fissure hit and the repeated projectile bursts can connect during the full chain."
        ),
        "mechanic_tags": (
            "travelling_fissure_hit",
            "enemy_seeking_repeat_chain",
            "projectile_eruption_bursts",
            "multi_stage_coverage",
        ),
        "scaling_axes": ("enemy_density", "projectile_count", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Volcanic_Fissure",
    },
    {
        "source_id": "voltaxic_burst.waiting_queue_snapshot_and_shared_counter",
        "skill_gates": ("Voltaxic Burst",),
        "label": "Waiting-queue snapshot with shared cast counter",
        "description": (
            "Each Voltaxic Burst cast waits before detonating, and its more-damage-per-cast multiplier is "
            "checked when that specific burst goes off rather than when it was cast. Shorter duration cashes "
            "out sooner, longer duration builds a bigger waiting queue, different gems share the same waiting "
            "counter, and the corpse explosion is separate secondary damage with its own non-reflecting rules."
        ),
        "mechanic_tags": (
            "delayed_burst_queue",
            "detonation_time_snapshot",
            "shared_waiting_counter",
            "secondary_corpse_explosion",
        ),
        "scaling_axes": ("duration", "cast_rate", "queue_size", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Voltaxic_Burst",
    },
    {
        "source_id": "volcanic_fissure_of_snaking.enemy_seeking_repeat_eruption_train",
        "skill_gates": ("Volcanic Fissure of Snaking",),
        "label": "Enemy-seeking repeat eruption train",
        "description": (
            "Volcanic Fissure of Snaking erupts at the targeted point and then continues toward nearby "
            "enemies for extra eruptions, but it will not automatically retarget enemies already hit by "
            "a previous eruption. Clear and single-target therefore depend on enemy spacing and target order."
        ),
        "mechanic_tags": ("enemy_seeking_fissure", "repeat_eruption", "non_retargeting"),
        "scaling_axes": ("enemy_density", "positioning", "target_ordering", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Volcanic_Fissure_of_Snaking",
    },
    {
        "source_id": "vortex.player_anchor_dual_payload_ground_nonstack",
        "skill_gates": ("Vortex",),
        "label": "Player-anchored hit plus non-stacking ground",
        "description": (
            "Vortex delivers an immediate spell hit around the caster and then leaves a separate cold-damage "
            "ground effect, but overlapping Vortex grounds do not stack and only the highest-damage area "
            "applies. Scaling is therefore split between hit delivery and maintaining one strong ground zone."
        ),
        "mechanic_tags": ("self_anchor", "hit_plus_ground_dot", "ground_dot_nonstack"),
        "scaling_axes": ("area_of_effect", "cast_speed", "damage_over_time", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vortex",
    },
    {
        "source_id": "vortex_of_projection.frostbolt_proxy_sequence",
        "skill_gates": ("Vortex of Projection",),
        "label": "Frostbolt proxy sequence",
        "description": (
            "Casting on Frostbolts converts one use into up to five sequential remote explosions, "
            "destroying the chosen Frostbolts and granting more hit damage and area when cast this way."
        ),
        "mechanic_tags": ("frostbolt_proxy", "sequential_explosions", "projectile_consumption"),
        "scaling_axes": ("frostbolt_count", "cooldown_recovery", "cast_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vortex_of_Projection",
    },
    {
        "source_id": "winter_orb.explosion_overlap",
        "skill_gates": ("Winter Orb",),
        "label": "Explosion overlap",
        "description": (
            "Impact explosions from multiple projectiles can overlap on a target when area is scaled "
            "high enough, with more projectiles demanding more area for consistent stacking."
        ),
        "mechanic_tags": ("overlap", "projectile_explosion", "aoe_breakpoint"),
        "scaling_axes": ("area_of_effect", "projectile_count", "positioning", "stage_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Winter_Orb",
    },
    {
        "source_id": "wave_of_conviction_of_trarthus.single_active_wave_limit",
        "skill_gates": ("Wave of Conviction of Trarthus",),
        "label": "Single active wave limit",
        "description": (
            "Wave of Conviction of Trarthus can only keep one travelling wave active at a time, so recasting "
            "or proxy recasting replaces the previous wave instead of stacking multiple overlapping passes."
        ),
        "mechanic_tags": ("single_instance_limit", "travelling_wave", "proxy_lockout", "throughput_gate"),
        "scaling_axes": ("cast_speed", "duration", "positioning", "proxy_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Wave_of_Conviction_of_Trarthus",
    },
    {
        "source_id": "wave_of_conviction.single_active_wave_range_tradeoff",
        "skill_gates": ("Wave of Conviction",),
        "label": "Single active wave and range tradeoff",
        "description": (
            "Wave of Conviction can hit each enemy only once per travelling pass, its reach scales through "
            "both area of effect and duration, and casting again while one wave is active replaces the "
            "previous wave. Single-target damage therefore trades cast speed against active-wave uptime and "
            "path length instead of stacking multiple simultaneous waves."
        ),
        "mechanic_tags": ("single_instance_limit", "travelling_wave", "single_pass_hit", "range_tradeoff"),
        "scaling_axes": ("cast_speed", "duration", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Wave_of_Conviction",
    },
    {
        "source_id": "whirling_blades.single_pass_travel_lockout_and_dual_wield_combination",
        "skill_gates": ("Whirling Blades",),
        "label": "Single-pass travel hit with dual-wield combination",
        "description": (
            "Whirling Blades moves in a fixed straight-line pass that can hit each enemy only once per use, "
            "then leaves a recovery lockout whose length depends on travelled distance, collision, and attack "
            "time. When dual wielding it averages weapon speed and combines both weapons into one hit, so real "
            "throughput scales with travel pathing and attack-time compression rather than treating it like a "
            "normal stationary melee repeat skill."
        ),
        "mechanic_tags": (
            "single_pass_hit_cap",
            "travel_lockout",
            "attack_time_scaled_movement",
            "dual_wield_combined_hit",
        ),
        "scaling_axes": ("attack_speed", "travel_distance", "collision_pathing", "dual_wield_weapon_mix"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Whirling_Blades",
    },
    {
        "source_id": "wild_strike.secondary_partition_return_exception",
        "skill_gates": ("Wild Strike",),
        "include_transfigured": True,
        "label": "Secondary partition and return exception",
        "description": (
            "Wild Strike splits each attack into a melee hit plus one random secondary branch. "
            "Enemies hit by the melee portion cannot be hit by that use's secondary effect, except "
            "when the cold projectile returns, and keyword-specific modifiers only scale their "
            "matching branch."
        ),
        "mechanic_tags": ("melee_secondary_partition", "return_exception", "keyword_partition", "random_branch"),
        "scaling_axes": ("return", "support_choice", "element_locking", "projectile_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Wild_Strike",
    },
    {
        "source_id": "shattering_steel.fixed_timer_range_partition",
        "skill_gates": ("Shattering Steel", "Shattering Steel of Ammunition"),
        "label": "Fixed-timer range partition",
        "description": (
            "Shattering Steel projectiles detonate after a fixed duration, so projectile speed extends "
            "how far they travel before the shatter. Area modifiers only affect the secondary cone "
            "AoE rather than the flight path."
        ),
        "mechanic_tags": ("fixed_timer_detonation", "projectile_speed_range", "secondary_aoe_only"),
        "scaling_axes": ("projectile_speed", "area_of_effect", "positioning", "enemy_distance"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shattering_Steel",
    },
    {
        "source_id": "spectral_shield_throw.shield_collision_shard_set_budget",
        "skill_gates": ("Spectral Shield Throw", "Spectral Shield Throw of Shattering"),
        "label": "Shield collision shard-set budget",
        "description": (
            "Spectral Shield Throw splits each use into one main shield projectile and collision-spawned "
            "shard sets. Additional projectiles add shards instead of more shield projectiles; each enemy "
            "can take at most one outgoing and one returning shield hit per attack, while extra collision "
            "targets like Hydrosphere or Tornado can generate extra shard sets."
        ),
        "mechanic_tags": ("primary_secondary_projectiles", "collision_spawn", "hit_budget", "proxy_collision_target"),
        "scaling_axes": ("projectile_count", "chain_return", "projectile_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Shield_Throw",
    },
    {
        "source_id": "spectral_shield_throw_of_trarthus.hovering_shard_fan_acceleration",
        "skill_gates": ("Spectral Shield Throw of Trarthus",),
        "label": "Piercing hover point accelerates a stationary shard fan",
        "description": (
            "Spectral Shield Throw of Trarthus sends one piercing shield to a target point, then leaves it "
            "hovering there to fire shards in all directions with an accelerating release rate. Additional "
            "projectiles add shards rather than more shield copies, so real scaling depends on projectile "
            "count, pierce placement, and how long enemies stay inside that stationary shard fan."
        ),
        "mechanic_tags": (
            "piercing_setup_projectile",
            "stationary_shard_emitter",
            "accelerating_release_rate",
            "projectile_to_shard_conversion",
        ),
        "scaling_axes": ("projectile_count", "positioning", "enemy_density", "target_stay_time"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Shield_Throw_of_Trarthus",
    },
    {
        "source_id": "spectral_throw.boomerang_rehit_window",
        "skill_gates": ("Spectral Throw",),
        "label": "Boomerang rehit window",
        "description": (
            "Spectral Throw projectiles travel out and back on a boomerang path, letting the same "
            "projectile rehit a target over time and letting multiple projectiles contact the same "
            "target from one attack. Projectile speed and positioning mainly change how long a target "
            "stays inside the returning path."
        ),
        "mechanic_tags": ("boomerang_projectile", "rehit_window", "multi_projectile_contact"),
        "scaling_axes": ("projectile_speed", "projectile_count", "positioning", "movement_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Throw",
    },
    {
        "source_id": "spectral_throw_of_materialising.return_only_rehit_window",
        "skill_gates": ("Spectral Throw of Materialising",),
        "label": "Return-only rehit window",
        "description": (
            "Spectral Throw of Materialising only deals damage on the return leg, so projectile speed "
            "and movement mostly matter by shifting where the damaging pass happens. It still inherits "
            "the boomerang-style multi-hit behavior on that return path."
        ),
        "mechanic_tags": ("return_only_damage", "boomerang_projectile", "rehit_window"),
        "scaling_axes": ("projectile_speed", "positioning", "movement_speed", "projectile_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Throw_of_Materialising",
    },
    {
        "source_id": "spectral_throw_of_trarthus.nova_lane_rehit_nonshotgun",
        "skill_gates": ("Spectral Throw of Trarthus",),
        "label": "Nova lane rehit without true shotgun",
        "description": (
            "Spectral Throw of Trarthus can route several trap-fired projectiles across one target near "
            "their turn point, but the shared per-attack hit timer prevents true full shotgun behavior. "
            "Projectile speed shifts the effective turn distance, while player attack speed does not "
            "scale the trap's projectile cadence."
        ),
        "mechanic_tags": ("trap_projectile", "rehit_window", "shared_hit_cooldown", "nova_lane"),
        "scaling_axes": ("projectile_speed", "projectile_count", "trap_throwing_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Spectral_Throw_of_Trarthus",
    },
    {
        "source_id": "vaal_spectral_throw.terrain_despawn_spiral_range",
        "skill_gates": ("Vaal Spectral Throw",),
        "label": "Terrain despawn spiral range",
        "description": (
            "Vaal Spectral Throw spirals outward until terrain collision or range break, rather than "
            "cleanly boomeranging back like the base gem. Projectile speed extends the spiral travel "
            "distance, but too much range can desync the return if the player moves too far away."
        ),
        "mechanic_tags": ("spiral_projectile", "terrain_despawn", "projectile_speed_range"),
        "scaling_axes": ("projectile_speed", "duration", "positioning", "movement_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Spectral_Throw",
    },
    {
        "source_id": "lightning_trap.supported_projectile_lanes",
        "skill_gates": ("Lightning Trap",),
        "label": "Supported projectile lanes",
        "description": (
            "Lightning Trap scales through projectile lane behavior: pierce, chain and projectile speed "
            "all change how far and how often trap-fired bolts can connect. Player cast speed does not "
            "change the spell cadence because the triggered trap performs the cast."
        ),
        "mechanic_tags": ("trap_projectile", "pierce_chain_scaling", "projectile_lane"),
        "scaling_axes": ("projectile_speed", "chain_count", "pierce_count", "trap_throwing_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Trap",
    },
    {
        "source_id": "lightning_trap_of_sparking.pierce_terrain_chain_lanes",
        "skill_gates": ("Lightning Trap of Sparking",),
        "label": "Pierce and terrain-chain lanes",
        "description": (
            "Lightning Trap of Sparking fires through the triggering enemy instead of detonating in a "
            "nova, with projectiles piercing targets and chaining from terrain. Its scaling is therefore "
            "about projectile pathing and residency rather than overlapping nova spokes."
        ),
        "mechanic_tags": ("trap_projectile", "pierce", "terrain_chain", "lane_pathing"),
        "scaling_axes": ("projectile_speed", "chain_count", "duration", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Trap_of_Sparking",
    },
    {
        "source_id": "vaal_lightning_trap.soul_limited_pierce_ground",
        "skill_gates": ("Vaal Lightning Trap",),
        "label": "Soul-limited pierce and ground uptime",
        "description": (
            "Vaal Lightning Trap projectiles always pierce, so chain scaling is largely dead, while "
            "duration primarily scales shocked-ground uptime. Extra trap behavior is additionally capped "
            "by soul availability, and triggered traps do not re-arm into repeated activations."
        ),
        "mechanic_tags": ("vaal_trap", "always_pierce", "ground_uptime", "soul_limit"),
        "scaling_axes": ("duration", "trap_count", "soul_gain_rate", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Lightning_Trap",
    },
    {
        "source_id": "tornado.projectile_absorb_reflect_window",
        "skill_gates": ("Tornado",),
        "label": "Projectile absorb and reflect window",
        "description": (
            "Tornado has an initial absorb phase where colliding projectiles can feed stored damage up "
            "to a fixed hit cap, followed by a roaming phase that reflects part of that stored damage. "
            "Duration extends both windows, and only projectile effects that can truly collide with "
            "enemies can contribute to the absorb pool."
        ),
        "mechanic_tags": ("proxy_target", "projectile_absorb", "reflect_window", "hit_cap"),
        "scaling_axes": ("duration", "projectile_count", "hit_rate", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tornado",
    },
    {
        "source_id": "tornado_of_elemental_turbulence.shared_limit_unhittable",
        "skill_gates": ("Tornado of Elemental Turbulence",),
        "label": "Shared limit and unhittable proxy",
        "description": (
            "Tornado of Elemental Turbulence cannot be hit to absorb projectile damage the way base "
            "Tornado can, and it shares the same active tornado limit with base Tornado. Its scaling is "
            "therefore governed by uptime and limit management rather than projectile-feed interactions."
        ),
        "mechanic_tags": ("shared_limit", "unhittable_proxy", "uptime_management"),
        "scaling_axes": ("duration", "cast_speed", "cooldown_recovery", "skill_limit_management"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tornado_of_Elemental_Turbulence",
    },
    {
        "source_id": "blade_flurry.stage_release_burst_breakpoints",
        "skill_gates": ("Blade Flurry",),
        "label": "Stage and release burst breakpoints",
        "description": (
            "Blade Flurry ramps by building stages while channelling, with each stage both adding more "
            "damage and granting an extra release hit when the channel ends. Attack speed changes how "
            "quickly stage cap is reached, while area scaling affects both the repeated hit radius and "
            "the release explosion radius."
        ),
        "mechanic_tags": ("channel_ramp", "stage_breakpoints", "release_burst", "area_scaling"),
        "scaling_axes": ("attack_speed", "channel_duration", "area_of_effect", "stage_cap"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Flurry",
    },
    {
        "source_id": "vaal_blade_flurry.expanding_mark_ring_per_enemy_detonation",
        "skill_gates": ("Vaal Blade Flurry",),
        "label": "Expanding mark ring and per-enemy detonation",
        "description": (
            "Vaal Blade Flurry channels to grow a capture ring, then releases a smaller hit around every "
            "enemy standing inside that ring when the channel ends or stage cap is reached. Its payout is "
            "therefore governed by stage time, ring coverage, and pack positioning rather than only by a "
            "single centered release."
        ),
        "mechanic_tags": ("channel_ramp", "capture_ring", "enemy_centered_detonation", "pack_overlap"),
        "scaling_axes": ("attack_speed", "channel_duration", "area_of_effect", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Blade_Flurry",
    },
    {
        "source_id": "blade_flurry_of_incision.stage_release_crit_breakpoints",
        "skill_gates": ("Blade Flurry of Incision",),
        "label": "Stage and release crit breakpoints",
        "description": (
            "Blade Flurry of Incision still gains an extra release hit per stage, but its stage scaling is "
            "moved from hit damage into critical strike chance. That makes channel time and attack speed "
            "the keys to reaching full crit ramp before release, with max-stage uptime also amplifying its "
            "quality-based critical strike multiplier bonus."
        ),
        "mechanic_tags": ("channel_ramp", "critical_ramp", "release_burst", "stage_breakpoints"),
        "scaling_axes": ("attack_speed", "channel_duration", "critical_strike_chance", "critical_strike_multiplier"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blade_Flurry_of_Incision",
    },
    {
        "source_id": "boneshatter.trauma_ignores_repeats",
        "skill_gates": ("Boneshatter",),
        "include_transfigured": True,
        "label": "Trauma ignores repeats",
        "description": (
            "Repeated attacks from repeat mechanics such as Multistrike do not grant additional Trauma "
            "stacks for Boneshatter, so Trauma throughput scales with real attack cycles and strike "
            "rate rather than repeat count alone."
        ),
        "mechanic_tags": ("trauma_stack_gate", "repeat_caveat", "strike_cycle_scaling"),
        "scaling_axes": ("attack_speed", "repeat_count", "trauma_duration", "stun_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Repeat",
    },
    {
        "source_id": "cold_snap.charge_bypass_self_cast_loop",
        "skill_gates": ("Cold Snap",),
        "label": "Charge bypass self-cast loop",
        "description": (
            "Cold Snap splits into an initial hit plus chilled-ground damage over time, and self-cast use "
            "can bypass the cooldown by spending a Frenzy Charge. Frenzy generation on kill helps sustain "
            "that loop, but triggered casts cannot consume charges to skip the cooldown."
        ),
        "mechanic_tags": ("charge_bypass", "kill_refund", "trigger_restriction", "dual_payload"),
        "scaling_axes": ("frenzy_charge_generation", "kill_density", "cast_speed", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cold_Snap",
    },
    {
        "source_id": "cold_snap_of_power.power_charge_bypass_loop",
        "skill_gates": ("Cold Snap of Power",),
        "label": "Power-charge bypass crit loop",
        "description": (
            "Cold Snap of Power drops the chilled-ground damage-over-time package and instead loops around "
            "critical strikes and Power Charges. Self-cast use can bypass cooldown by spending a Power "
            "Charge, but each critical cast can only refund one charge, so sustain depends on crit "
            "consistency rather than shotgun hits."
        ),
        "mechanic_tags": ("charge_bypass", "critical_charge_return", "single_charge_refund", "burst_cycle"),
        "scaling_axes": ("power_charge_generation", "critical_strike_chance", "cast_speed", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cold_Snap_of_Power",
    },
    {
        "source_id": "bodyswap.corpse_dual_explosion_scaling",
        "skill_gates": ("Bodyswap",),
        "label": "Corpse-fed dual explosion scaling",
        "description": (
            "Bodyswap creates damage at both the caster and destination, and when a corpse is consumed the "
            "target explosion scales from corpse maximum life while also gaining more area of effect. Its "
            "ceiling is therefore tied to corpse quality and placement, not just generic spell scaling, and "
            "the skill cannot be repeated to shortcut those setup constraints."
        ),
        "mechanic_tags": ("dual_explosion", "corpse_life_payload", "area_bonus", "no_repeat"),
        "scaling_axes": ("corpse_life", "corpse_supply", "area_of_effect", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bodyswap",
    },
    {
        "source_id": "bodyswap_of_sacrifice.minion_dual_explosion_scaling",
        "skill_gates": ("Bodyswap of Sacrifice",),
        "label": "Minion-fed dual explosion scaling",
        "description": (
            "Bodyswap of Sacrifice mirrors the dual-explosion pattern of Bodyswap, but consumes a minion "
            "instead of a corpse and scales the target explosion from that minion's maximum life. Minion "
            "supply, minion life, and placement therefore become the real damage gates, with the same "
            "non-repeat constraint preserving the setup cost."
        ),
        "mechanic_tags": ("dual_explosion", "minion_life_payload", "area_bonus", "no_repeat"),
        "scaling_axes": ("minion_life", "minion_supply", "area_of_effect", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Bodyswap_of_Sacrifice",
    },
    {
        "source_id": "dark_pact.skeleton_chain_life_payload",
        "skill_gates": ("Dark Pact",),
        "label": "Skeleton chain and life payload",
        "description": (
            "Dark Pact prefers sacrificing nearby allied skeletons, chaining between them and using their "
            "maximum life to determine added base damage. When no skeletons are available it falls back to "
            "the caster or proxy life pool, so skeleton count, skeleton life, and chain positioning define "
            "the real ceiling more than generic spell scaling alone."
        ),
        "mechanic_tags": ("skeleton_proxy", "life_payload", "chain_setup", "external_supply"),
        "scaling_axes": ("skeleton_count", "minion_life", "cast_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Dark_Pact",
    },
    {
        "source_id": "dark_pact_of_trarthus.ruin_life_burst_cycle",
        "skill_gates": ("Dark Pact of Trarthus",),
        "label": "Ruin threshold life burst",
        "description": (
            "Dark Pact of Trarthus builds Ruin on use and cashes out at seven Ruin by sacrificing 50% of "
            "maximum life to add a large chaos burst. Additional Ruin chance shortens that cycle, so life "
            "pool and casts-to-threshold govern realized DPS more than flat spell repetition alone."
        ),
        "mechanic_tags": ("ruin_cycle", "life_sacrifice", "burst_threshold", "cadence_gate"),
        "scaling_axes": ("maximum_life", "additional_ruin_chance", "cast_speed", "burst_frequency"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Dark_Pact_of_Trarthus",
    },
    {
        "source_id": "corrupting_fever.player_buff_hit_delivery",
        "skill_gates": ("Corrupting Fever",),
        "label": "Player-buff hit delivery",
        "description": (
            "Corrupting Fever is a player-owned buff that turns the player's hits into Corrupted Blood "
            "stack application, refreshing all existing stacks on each new application. The hits do not "
            "need to deal damage, but proxy hits from traps, mines, or totems cannot inherit the buff."
        ),
        "mechanic_tags": ("player_owned_buff", "hit_applied_dot", "proxy_exclusion", "stack_refresh"),
        "scaling_axes": ("player_hit_rate", "buff_uptime", "life_spend_frequency", "stack_cap_reach_time"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Corrupting_Fever",
    },
    {
        "source_id": "desecrate.spectre_bank_corpse_replacement",
        "skill_gates": ("Desecrate",),
        "label": "Spectre-bank corpse replacement",
        "description": (
            "Desecrate is a corpse-supply skill, so its real ceiling depends on corpse level, corpse pool "
            "control, and the follow-up skill using those corpses. Saved spectres can inject their corpse "
            "types into the pool, but those spectral corpses also replace normal detonatable corpses and "
            "can dilute corpse targeting for detonate-style setups."
        ),
        "mechanic_tags": ("corpse_generation", "spectre_bank", "corpse_pool_replacement", "followup_setup"),
        "scaling_axes": ("corpse_level", "corpse_pool_control", "cast_speed", "followup_skill_pairing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Desecrate",
    },
    {
        "source_id": "discharge.charge_bonus_snapshot_burst",
        "skill_gates": ("Discharge", "Discharge of Misery"),
        "label": "Charge snapshot burst cycle",
        "description": (
            "Discharge cashes out all removable charges in one burst, and the consumed charge bonuses still "
            "apply to that same cast before the charges disappear. Real DPS therefore comes from building a "
            "strong charge state, snapshotting it into the explosion, and then refilling charges for the "
            "next burst."
        ),
        "mechanic_tags": ("charge_snapshot", "all_charge_spend", "burst_cycle", "post_spend_refund"),
        "scaling_axes": ("maximum_charges", "charge_generation", "critical_strike_chance", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Discharge",
    },
    {
        "source_id": "ethereal_knives_of_lingering_blades.fixed_arc_blade_field",
        "skill_gates": ("Ethereal Knives of Lingering Blades",),
        "label": "Fixed arc and blade-field conversion",
        "description": (
            "Ethereal Knives of Lingering Blades does not shotgun a single target with multiple knives, but "
            "each projectile leaves behind a Lingering Blade up to a fixed field cap. Its scaling is thus "
            "split between immediate clear and blade-field generation for follow-up blade skills, with the "
            "fixed arc controlling how efficiently it can seed that field."
        ),
        "mechanic_tags": ("fixed_arc", "no_shotgun", "lingering_blades", "field_cap"),
        "scaling_axes": ("projectile_count", "cast_speed", "lingering_blade_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ethereal_Knives_of_Lingering_Blades",
    },
    {
        "source_id": "flicker_strike.charge_bypass_fixed_target_radius",
        "skill_gates": ("Flicker Strike",),
        "label": "Frenzy bypass and fixed target radius",
        "description": (
            "Flicker Strike's cooldown is bypassed by consuming Frenzy Charges, but the teleport target "
            "selection is constrained to a fixed nearby radius that is not enlarged by area or melee strike "
            "range modifiers. Real scaling therefore comes from charge sustain and target density rather "
            "than trying to stretch the teleport geometry."
        ),
        "mechanic_tags": ("charge_bypass", "fixed_target_radius", "movement_attack", "charge_sustain"),
        "scaling_axes": ("frenzy_charge_generation", "attack_speed", "target_density", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flicker_Strike",
    },
    {
        "source_id": "flicker_strike_of_power.power_charge_bypass_cycle",
        "skill_gates": ("Flicker Strike of Power",),
        "label": "Power-charge bypass cycle",
        "description": (
            "Flicker Strike of Power replaces the normal Frenzy Charge loop with a Power Charge loop, "
            "bypassing cooldown by spending Power Charges and refunding them through critical strikes. Its "
            "damage loop is therefore governed by crit reliability and charge sustain, while the teleport "
            "still obeys the same nearby-target constraint as other Flicker variants."
        ),
        "mechanic_tags": ("charge_bypass", "power_charge_cycle", "critical_loop", "movement_attack"),
        "scaling_axes": ("power_charge_generation", "critical_strike_chance", "attack_speed", "target_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flicker_Strike_of_Power",
    },
    {
        "source_id": "frost_bomb.duration_to_detonation_window",
        "skill_gates": ("Frost Bomb",),
        "label": "Duration-to-detonation window",
        "description": (
            "Frost Bomb only deals hit damage on its final explosion; the pulses before detonation do not "
            "hit. Duration scaling therefore stretches both the time until the damaging burst lands and the "
            "length of its exposure and regeneration suppression window, creating a deliberate tradeoff "
            "between faster delivery and longer debuff uptime."
        ),
        "mechanic_tags": ("delayed_burst", "single_hit", "duration_tradeoff", "debuff_uptime"),
        "scaling_axes": ("duration", "cast_speed", "cooldown_recovery", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Bomb",
    },
    {
        "source_id": "frost_bomb_of_forthcoming.duration_paid_burst_window",
        "skill_gates": ("Frost Bomb of Forthcoming",),
        "label": "Duration-paid burst window",
        "description": (
            "Frost Bomb of Forthcoming drops the normal exposure and regeneration suppression in exchange "
            "for a longer-cooldown, longer-duration bomb whose hit and ailment damage scale up with "
            "duration. Its output is therefore paid for by a slower burst window, making duration and "
            "cooldown management part of the damage scaling package instead of just QoL."
        ),
        "mechanic_tags": ("delayed_burst", "duration_payoff", "cooldown_gated", "ailment_scaling"),
        "scaling_axes": ("duration", "cooldown_recovery", "hit_damage", "ailment_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Bomb_of_Forthcoming",
    },
    {
        "source_id": "frost_bomb_of_instability.cooldownless_single_blast_cycle",
        "skill_gates": ("Frost Bomb of Instability",),
        "label": "Cooldownless single-blast cycle",
        "description": (
            "Frost Bomb of Instability removes the base skill's cooldown and debuff package, leaving a "
            "leaner single-blast delivery pattern with less area and slower cast speed. Its scaling moves "
            "away from long orb scheduling and toward raw recast cadence, hit delivery, and coverage per cast."
        ),
        "mechanic_tags": ("cooldownless_burst", "single_blast", "cadence_scaling", "reduced_coverage"),
        "scaling_axes": ("cast_speed", "hit_damage", "area_of_effect", "repeat_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Bomb_of_Instability",
    },
    {
        "source_id": "absolution.sentinel_ramp_refresh_empowered_overlap",
        "skill_gates": ("Absolution",),
        "include_transfigured": True,
        "label": "Sentinel ramp, refresh, and empowered overlap",
        "description": (
            "Absolution scales through sentinel uptime and ramp: kills on debuffed enemies create or "
            "refresh minions, while hits on rare or unique enemies provide a fallback summon chance when "
            "there is nothing to kill. Its empowered blast also uses two AoEs that can overlap on one "
            "target, so duration, summon consistency, and positioning all matter."
        ),
        "mechanic_tags": ("minion_ramp", "fallback_summon", "corpse_refresh", "overlap"),
        "scaling_axes": ("duration", "kill_rate", "hit_rate", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Absolution",
    },
    {
        "source_id": "vaal_absolution.ascended_sentinel_extra_slot_refresh_and_gem_locality",
        "skill_gates": ("Vaal Absolution",),
        "label": "Ascended sentinel extra slot, refresh, and gem locality",
        "description": (
            "Vaal Absolution upgrades one existing sentinel into an Ascended Sentinel that sits outside "
            "the normal regular-sentinel cap, so the burst ceiling depends on already maintaining the "
            "base skill's minion ramp. Recasting refreshes that Ascended Sentinel instead of stacking a "
            "second one, and it only works on sentinels created by the same gem instance."
        ),
        "mechanic_tags": ("vaal_minion_upgrade", "separate_limit", "duration_refresh", "base_skill_dependency"),
        "scaling_axes": ("sentinel_uptime", "duration", "kill_rate", "hit_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Absolution",
    },
    {
        "source_id": "animate_weapon.weapon_supply_and_lingering_blade_feed",
        "skill_gates": ("Animate Weapon",),
        "label": "Weapon supply and lingering blade feed",
        "description": (
            "Animate Weapon's real damage ceiling depends on external weapon supply: it can animate dropped "
            "melee weapons or consume lingering blades generated by other skills. Setup speed, lingering "
            "blade availability, and minion duration therefore directly gate how quickly it reaches full "
            "animated-weapon count."
        ),
        "mechanic_tags": ("minion_supply", "lingering_blades", "external_setup", "ramp"),
        "scaling_axes": ("weapon_supply", "lingering_blade_count", "duration", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Animate_Weapon",
    },
    {
        "source_id": "vaal_animate_weapon.multi_weapon_burst_supply_and_random_unique_rolls",
        "skill_gates": ("Vaal Animate Weapon",),
        "label": "Multi-weapon burst supply and random unique rolls",
        "description": (
            "Vaal Animate Weapon converts multiple dropped melee weapons or lingering blades in one cast, "
            "then transforms them into random unique animated weapons. Its real burst therefore scales "
            "with preloaded blade or weapon supply and how quickly that supply can be rebuilt between "
            "soul-limited activations, not just with one-at-a-time summon cadence."
        ),
        "mechanic_tags": ("vaal_minion_burst", "weapon_supply", "lingering_blades", "random_weapon_roll"),
        "scaling_axes": ("weapon_supply", "lingering_blade_count", "duration", "soul_gain_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Animate_Weapon",
    },
    {
        "source_id": "animate_weapon_of_ranged_arms.ranged_supply_and_lingering_blade_conversion",
        "skill_gates": ("Animate Weapon of Ranged Arms",),
        "label": "Ranged supply and blade conversion",
        "description": (
            "Animate Weapon of Ranged Arms can only animate dropped ranged weapons or Lingering Blades, "
            "and those Lingering Blades are converted into ranged minions instead of the base skill's "
            "melee weapon copies. Its ceiling is therefore gated by external ranged-weapon supply or "
            "blade generation, while minion duration and setup speed determine how quickly it reaches full output."
        ),
        "mechanic_tags": ("minion_supply", "lingering_blades", "ranged_conversion", "external_setup"),
        "scaling_axes": ("ranged_weapon_supply", "lingering_blade_count", "duration", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Animate_Weapon_of_Ranged_Arms",
    },
    {
        "source_id": "animate_weapon_of_self_reflection.main_hand_copy_only",
        "skill_gates": ("Animate Weapon of Self Reflection",),
        "label": "Main-hand copy only",
        "description": (
            "Animate Weapon of Self Reflection no longer scales from dropped weapons or lingering blades. "
            "It only creates copies of the current main-hand melee weapon, so damage is concentrated into "
            "weapon snapshot quality, clone uptime, and recast cadence instead of external blade setup."
        ),
        "mechanic_tags": ("weapon_snapshot", "clone_uptime", "no_external_supply"),
        "scaling_axes": ("weapon_base", "duration", "cast_speed", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Animate_Weapon_of_Self_Reflection",
    },
    {
        "source_id": "animate_guardian.item_loadout_persistence_and_dual_wield_ai",
        "skill_gates": ("Animate Guardian", "Animate Guardian of Smiting"),
        "label": "Item loadout persistence and dual wield AI",
        "description": (
            "Animated Guardian uses equipped items like a player, can dual wield one-handed weapons, and "
            "keeps its item loadout through death and resummon. Real damage scales through weapon choice, "
            "item quality, and keeping the guardian alive rather than only through the gem's base numbers."
        ),
        "mechanic_tags": ("item_loadout", "persistent_minion", "dual_wield", "resummon_lockout"),
        "scaling_axes": ("weapon_base", "itemization", "survivability", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Animate_Guardian",
    },
    {
        "source_id": "arcanist_brand.sequential_trigger_budget",
        "skill_gates": ("Arcanist Brand",),
        "label": "Sequential trigger budget",
        "description": (
            "Arcanist Brand casts linked spells in sequence while attached, so a longer attachment window "
            "and faster activation cadence determine whether the full linked package actually cycles. More "
            "linked spells dilute per-skill trigger frequency unless duration or brand activation rate also grows."
        ),
        "mechanic_tags": ("brand_proxy", "trigger_sequence", "duration_budget", "attachment_cadence"),
        "scaling_axes": ("activation_frequency", "duration", "linked_spell_count", "brand_limit"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Arcanist_Brand",
    },
    {
        "source_id": "blink_mirror_arrow.clone_uptime_and_travel_delay",
        "skill_gates": ("Blink Arrow", "Mirror Arrow"),
        "label": "Clone uptime and travel delay",
        "description": (
            "Blink Arrow and Mirror Arrow deal damage through temporary bow clones that use the player's "
            "bow attack with linked supports. Attack speed and projectile speed affect different parts of "
            "the summon sequence, but the arrow's travel delay is fixed by the skill and not shortened by "
            "target distance."
        ),
        "mechanic_tags": ("proxy_minion", "travel_delay", "clone_uptime", "bow_snapshot"),
        "scaling_axes": ("attack_speed", "projectile_speed", "duration", "cooldown_recovery"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blink_Arrow",
    },
    {
        "source_id": "bombarding_clones.rain_of_arrows_proxy_pattern",
        "skill_gates": ("Blink Arrow of Bombarding Clones", "Mirror Arrow of Bombarding Clones"),
        "label": "Rain of Arrows proxy pattern",
        "description": (
            "Bombarding clones do not use a normal bow attack; they fire a monster Rain of Arrows pattern. "
            "That shifts scaling toward clone uptime, attack cadence, and area coverage, with a portion of "
            "the arrow rain landing directly on nearby targets instead of behaving like a generic player attack."
        ),
        "mechanic_tags": ("proxy_minion", "volley_pattern", "area_targeting"),
        "scaling_axes": ("attack_speed", "duration", "area_of_effect", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blink_Arrow_of_Bombarding_Clones",
    },
    {
        "source_id": "prismatic_clones.elemental_hit_proxy_conversion",
        "skill_gates": ("Blink Arrow of Prismatic Clones", "Mirror Arrow of Prismatic Clones"),
        "label": "Elemental Hit proxy conversion",
        "description": (
            "Prismatic clones use a monster Elemental Hit attack that picks one element per use and fully "
            "converts physical damage to that chosen element. They do not reproduce the normal player-side "
            "secondary ailment AoE, so scaling favors weapon snapshot quality, attack cadence, and elemental "
            "conversion output rather than generic bow clear interactions."
        ),
        "mechanic_tags": ("proxy_minion", "element_choice", "conversion", "missing_secondary_effect"),
        "scaling_axes": ("weapon_base", "attack_speed", "elemental_damage", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blink_Arrow_of_Prismatic_Clones",
    },
    {
        "source_id": "explosive_concoction.ground_targeted_overlap",
        "skill_gates": ("Explosive Concoction",),
        "include_transfigured": True,
        "label": "Ground-targeted overlap",
        "description": (
            "Explosive Concoction's projectile bodies do not hit enemies at all; only their ground-targeted "
            "explosions deal damage. Those explosions can overlap on one target, so extra projectiles and "
            "area investment create same-target shotgun breakpoints instead of acting like normal pierce, "
            "fork, split, or chain scaling."
        ),
        "mechanic_tags": ("overlap", "ground_targeted", "additional_projectiles", "projectile_body_nohit"),
        "scaling_axes": ("projectile_count", "area_of_effect", "enemy_radius", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Explosive_Concoction",
    },
    {
        "source_id": "lightning_warp.distance_duration_dual_hit",
        "skill_gates": ("Lightning Warp",),
        "label": "Distance-scaled delay and dual hit",
        "description": (
            "Lightning Warp deals damage both where the cast resolves and where the caster arrives. Its "
            "delay scales with distance travelled, movement speed, and skill duration, but it always keeps "
            "a hidden minimum delay, so burst cadence comes from duration compression and route length as "
            "much as raw cast speed."
        ),
        "mechanic_tags": ("dual_hit", "distance_delay", "duration_compression", "movement_scaling"),
        "scaling_axes": ("distance", "movement_speed", "skill_duration", "cast_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Warp",
    },
    {
        "source_id": "vaal_lightning_warp.enemy_gather_burst",
        "skill_gates": ("Vaal Lightning Warp",),
        "label": "Enemy-gather burst",
        "description": (
            "Vaal Lightning Warp drags nearby enemies into the targeted area and then bursts them there, "
            "so its value scales with pull coverage, pack size, and how much enemy density can be forced "
            "into one blast rather than with travel-distance cadence."
        ),
        "mechanic_tags": ("enemy_gather", "single_burst", "forced_reposition", "area_capture"),
        "scaling_axes": ("enemy_density", "area_of_effect", "target_positioning", "pack_size"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Lightning_Warp",
    },
    {
        "source_id": "static_strike.beam_uptime_and_attack_inheritance",
        "skill_gates": ("Static Strike",),
        "label": "Beam uptime and attack inheritance",
        "description": (
            "Static Strike's melee hit creates a timed beam window, so total output depends on how long the "
            "window lasts, how often beams pulse, and how many enemies each pulse can reach. The beams "
            "inherit attack-wide properties from the melee hit and scale with area of effect, but not with "
            "area damage, making the granting hit and beam uptime part of the same damage package."
        ),
        "mechanic_tags": ("repeat_hit", "beam_uptime", "attack_inheritance", "area_scaling"),
        "scaling_axes": ("duration", "beam_frequency", "area_of_effect", "attack_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Static_Strike",
    },
    {
        "source_id": "static_strike_of_gathering_lightning.melee_stack_beam_ramp",
        "skill_gates": ("Static Strike of Gathering Lightning",),
        "label": "Melee-stack beam ramp",
        "description": (
            "Static Strike of Gathering Lightning turns the skill into a melee-hit ramp. Melee hits build "
            "Gathering Lightning, and the follow-up beam gains both damage and extra chains from those "
            "stacks, so attack cadence and stack growth determine beam output more than passive beam uptime."
        ),
        "mechanic_tags": ("stack_ramp", "melee_to_beam", "chain_scaling", "followup_hit"),
        "scaling_axes": ("attack_speed", "stack_count", "beam_damage", "chain_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Static_Strike_of_Gathering_Lightning",
    },
    {
        "source_id": "summon_raging_spirit.active_cap_throughput",
        "skill_gates": ("Summon Raging Spirit",),
        "include_transfigured": True,
        "label": "Active-cap throughput",
        "description": (
            "Summon Raging Spirit is a capped-duration swarm skill rather than a permanent summon. Cast "
            "cadence and duration determine how much of the spirit cap is active at once, while enemy "
            "acquisition and travel time decide how much of that cap is actually attacking instead of "
            "repositioning."
        ),
        "mechanic_tags": ("temporary_minion", "active_cap", "duration_ramp", "swarm_throughput"),
        "scaling_axes": ("cast_speed", "duration", "minion_limit", "target_acquisition"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Raging_Spirit",
    },
    {
        "source_id": "summon_holy_relic.attack_trigger_nova_regen_refresh_loop",
        "skill_gates": ("Summon Holy Relic",),
        "label": "Attack-trigger nova and regen refresh loop",
        "description": (
            "Summon Holy Relic only deals damage when your attack hits trigger its nova, so real output "
            "is gated by attack cadence, the relic's 0.3 second local trigger cooldown, and keeping the "
            "relic close enough that the self-anchored nova lands. Its allied regeneration buff refreshes "
            "on each valid trigger and multiple relic regen buffs do not stack, so scaling is about trigger "
            "uptime and nova coverage rather than generic passive minion uptime."
        ),
        "mechanic_tags": ("attack_trigger", "local_cooldown", "self_anchored_nova", "buff_refresh"),
        "scaling_axes": ("attack_rate", "cooldown_recovery", "area_of_effect", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Holy_Relic",
    },
    {
        "source_id": "summon_holy_relic_of_conviction.dual_relic_enemy_anchored_nova_loop",
        "skill_gates": ("Summon Holy Relic of Conviction",),
        "label": "Dual relic enemy-anchored nova loop",
        "description": (
            "Summon Holy Relic of Conviction trades the base regen aura for two relics whose triggered "
            "novas detonate around the nearest enemy instead of around the relics themselves. Damage scales "
            "through attack-hit trigger rate, each relic's 0.3 second cooldown, and keeping both relics in "
            "range to contribute overlapping enemy-anchored novas."
        ),
        "mechanic_tags": ("attack_trigger", "local_cooldown", "dual_relic_limit", "enemy_anchored_nova"),
        "scaling_axes": ("attack_rate", "cooldown_recovery", "relic_count", "target_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Holy_Relic_of_Conviction",
    },
    {
        "source_id": "summon_reaper.consume_buff_and_roster_tradeoff",
        "skill_gates": ("Summon Reaper", "Summon Reaper of Eviscerating"),
        "label": "Consume buff and roster tradeoff",
        "description": (
            "Summon Reaper is a single-minion package that weakens other minions and periodically consumes "
            "nearby allied damageable minions to heal or gain a temporary buff. Real damage scales with "
            "disposable minion supply and keeping the Reaper active rather than with a generic mixed-minion "
            "army."
        ),
        "mechanic_tags": ("minion_consumption", "temporary_buff", "roster_tradeoff", "single_minion_limit"),
        "scaling_axes": ("minion_supply", "duration", "positioning", "support_choice"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Reaper",
    },
    {
        "source_id": "summon_reaper_of_revenants.multi_reaper_budget_without_command_dash",
        "skill_gates": ("Summon Reaper of Revenants",),
        "label": "Multi-Reaper budget without command dash",
        "description": (
            "Summon Reaper of Revenants turns the base one-Reaper command package into a multi-Reaper roster "
            "with lower per-minion damage, the same allied-minion weakening and consume buff loop, and no "
            "recast command dash or forced ultimate. Real output scales with maintaining the full Reaper cap "
            "and disposable minion supply for empower uptime, while accepting that the manual reposition and "
            "burst-command loop from the base gem is gone."
        ),
        "mechanic_tags": ("multi_reaper_limit", "minion_consumption", "roster_tradeoff", "no_command_recast"),
        "scaling_axes": ("reaper_count", "minion_supply", "uptime", "ai_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Reaper_of_Revenants",
    },
    {
        "source_id": "summon_carrion_golem.non_golem_minion_ramp_and_multi_attack_kit",
        "skill_gates": ("Summon Carrion Golem",),
        "label": "Non-golem minion ramp and multi-attack kit",
        "description": (
            "Summon Carrion Golem adds a nearby non-golem minion damage ramp on top of a mixed melee and "
            "cascade skill kit. Real output scales with keeping disposable non-golem allies nearby so the "
            "golem stays at its local damage cap while still connecting with its full attack package."
        ),
        "mechanic_tags": ("nearby_minion_ramp", "temporary_damage_bonus", "mixed_attack_package", "minion_positioning"),
        "scaling_axes": ("nearby_minion_count", "minion_limit", "uptime", "ai_pathing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Carrion_Golem",
    },
    {
        "source_id": "summon_carrion_golem_of_hordes.shared_cooldown_and_global_hordes_mix_limit",
        "skill_gates": ("Summon Carrion Golem of Hordes",),
        "label": "Shared cooldown and global Hordes mix limit",
        "description": (
            "Summon Carrion Golem of Hordes trades the base nearby-minion damage ramp for extra maximum "
            "copies and a faster summon cooldown, but it still shares cooldown and the global golem limit "
            "with other Carrion variants. Damage scales through recast recovery and how the Hordes copies "
            "fit into the total mixed-golem budget rather than through one oversized summon."
        ),
        "mechanic_tags": ("shared_cooldown", "global_minion_limit", "variant_tradeoff", "multi_golem_budget"),
        "scaling_axes": ("cooldown_recovery", "golem_limit", "summon_mix", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Carrion_Golem_of_Hordes",
    },
    {
        "source_id": "summon_carrion_golem_of_scavenging.corpse_feed_empowered_bone_cascade_window",
        "skill_gates": ("Summon Carrion Golem of Scavenging",),
        "label": "Corpse feed and empowered Bone Cascade window",
        "description": (
            "Summon Carrion Golem of Scavenging periodically consumes nearby corpses to heal and gain a "
            "temporary empowerment that upgrades its Bone Cascade sequence. Damage scales with corpse supply "
            "and keeping the empowered window active instead of relying on permanent base-stat ramp."
        ),
        "mechanic_tags": ("corpse_consumption", "temporary_empower", "spell_upgrade_window", "encounter_setup"),
        "scaling_axes": ("corpse_supply", "duration", "cooldown_recovery", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Carrion_Golem_of_Scavenging",
    },
    {
        "source_id": "summon_chaos_golem.sandstorm_nonstacking_and_spike_split_kit",
        "skill_gates": ("Summon Chaos Golem", "Summon Chaos Golem of Hordes"),
        "label": "Nonstacking Sandstorm and spike split kit",
        "description": (
            "Chaos Golem damage is split between direct spike attacks and the Sandstorm chaos damage aura, "
            "but only the highest-damage Sandstorm affects a target at once. Extra copies still help with "
            "coverage and uptime, while single-target scaling depends on the best active aura rather than "
            "stacking identical Sandstorms."
        ),
        "mechanic_tags": ("damage_aura", "nonstacking_effect", "split_attack_package", "coverage_uptime"),
        "scaling_axes": ("aura_damage", "area_of_effect", "golem_limit", "target_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Chaos_Golem",
    },
    {
        "source_id": "summon_chaos_golem_of_the_maelstrom.empowered_wither_aura_nonstacking_damage",
        "skill_gates": ("Summon Chaos Golem of the Maelström",),
        "label": "Empowered Wither aura with nonstacking damage",
        "description": (
            "Summon Chaos Golem of the Maelstrom upgrades Sandstorm into a larger, stronger aura that can "
            "apply Withered, but the damage aura still does not stack with another copy on the same target. "
            "Scaling comes from maximizing the strongest aura and keeping enemies inside overlapping Wither "
            "coverage instead of stacking duplicate aura damage."
        ),
        "mechanic_tags": ("damage_aura", "wither_application", "nonstacking_effect", "area_control"),
        "scaling_axes": ("aura_damage", "wither_stacks", "area_of_effect", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Chaos_Golem_of_the_Maelstr%C3%B6m",
    },
    {
        "source_id": "summon_flame_golem.charged_magma_ball_cone_and_barrage_kit",
        "skill_gates": ("Summon Flame Golem", "Summon Flame Golem of Hordes"),
        "label": "Charged Magma Ball, cone, and barrage kit",
        "description": (
            "Flame Golem rotates between a charged Magma Ball spell with recharge-style availability, a "
            "short-range Flame Wave cone, and an Immolate projectile barrage. Damage scales through keeping "
            "targets in the right range band for the full rotation rather than through one repeatedly "
            "spammable projectile."
        ),
        "mechanic_tags": ("mixed_spell_rotation", "charge_recovery", "range_band", "projectile_barrage"),
        "scaling_axes": ("cooldown_recovery", "area_of_effect", "projectile_damage", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Flame_Golem",
    },
    {
        "source_id": "summon_flame_golem_of_the_meteor.impact_spawn_burning_ground_and_two_spell_followup",
        "skill_gates": ("Summon Flame Golem of the Meteor",),
        "label": "Impact spawn, burning ground, and two-spell followup",
        "description": (
            "Summon Flame Golem of the Meteor front-loads damage into the summon impact, which deals fire "
            "damage and leaves burning ground where the golem lands before its remaining rotation continues "
            "with Flame Wave and Immolate. Damage therefore scales through summon timing, landing location, "
            "and followup uptime rather than a permanent Magma Ball cycle."
        ),
        "mechanic_tags": ("summon_impact", "burning_ground", "frontloaded_burst", "followup_rotation"),
        "scaling_axes": ("impact_damage", "area_of_effect", "duration", "recast_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Flame_Golem_of_the_Meteor",
    },
    {
        "source_id": "summon_ice_golem.close_quarters_barrage_and_chilled_roll",
        "skill_gates": ("Summon Ice Golem", "Summon Ice Golem of Hordes"),
        "label": "Close-quarters barrage and chilled roll",
        "description": (
            "Ice Golem damage is concentrated in a close-range package: melee Shard Slice, a rolling attack "
            "that leaves chilled ground, and an Icicle Barrage that is only used near targets despite its "
            "long travel range. Real output scales with keeping the minion engaged in melee distance so the "
            "full rotation fires instead of only partial poke damage."
        ),
        "mechanic_tags": ("close_range_ai", "mixed_attack_package", "ground_effect", "projectile_sequence"),
        "scaling_axes": ("positioning", "area_of_effect", "attack_speed", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Ice_Golem",
    },
    {
        "source_id": "summon_ice_golem_of_shattering.low_life_death_nova_minion_instability_lockout",
        "skill_gates": ("Summon Ice Golem of Shattering",),
        "label": "Low-life death nova with Minion Instability lockout",
        "description": (
            "Summon Ice Golem of Shattering turns its payoff into a low-life self-detonation that releases a "
            "cold nova, but Minion Instability prevents that built-in effect from happening. Damage scales "
            "through reaching the self-detonation state reliably and preserving the native nova instead of "
            "replacing it with a generic minion death setup."
        ),
        "mechanic_tags": ("low_life_trigger", "death_nova", "keystone_lockout", "variant_tradeoff"),
        "scaling_axes": ("life_threshold", "survivability", "area_of_effect", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Ice_Golem_of_Shattering",
    },
    {
        "source_id": "summon_lightning_golem.single_target_zap_orb_and_storm_nimbus_aura",
        "skill_gates": ("Summon Lightning Golem", "Summon Lightning Golem of Hordes"),
        "label": "Single-target zap orb and Storm Nimbus aura",
        "description": (
            "Lightning Golem alternates between Galvanic Bolt, an Orb of Sparks that can only zap one enemy "
            "per pulse and cannot chain, and Storm Nimbus which grants a temporary added-lightning aura. "
            "Damage scales through maintaining aura uptime and keeping the orb on productive targets rather "
            "than expecting Spark-style screenwide chaining."
        ),
        "mechanic_tags": ("single_target_pulse", "temporary_aura", "projectile_spell_mix", "anti_chain_limit"),
        "scaling_axes": ("duration", "uptime", "target_density", "projectile_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Lightning_Golem",
    },
    {
        "source_id": "summon_stone_golem.roll_slam_taunt_and_high_life_no_es",
        "skill_gates": ("Summon Stone Golem", "Summon Stone Golem of Hordes"),
        "label": "Roll, slam, taunt, and high-life no-ES profile",
        "description": (
            "Stone Golem uses a melee sequence built from Granite Fist, a rolling approach attack, and Slab "
            "Slam with taunt, while also carrying the highest life and no energy shield among golems. Damage "
            "and uptime scale through keeping the golem in melee loops long enough to cycle its heavier "
            "slams rather than through ranged persistence."
        ),
        "mechanic_tags": ("melee_rotation", "movement_attack", "taunt_utility", "durability_profile"),
        "scaling_axes": ("life_pool", "attack_speed", "uptime", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Stone_Golem",
    },
    {
        "source_id": "summon_stone_golem_of_safeguarding.melee_damage_redirect_low_life_tradeoff",
        "skill_gates": ("Summon Stone Golem of Safeguarding",),
        "label": "Melee damage redirect with low-life tradeoff",
        "description": (
            "Summon Stone Golem of Safeguarding redirects part of melee damage from enemy hits onto the "
            "golem, but it pays for that utility with much lower maximum life and a longer summon cooldown. "
            "Damage uptime scales with how well the golem survives the redirected burden rather than with "
            "raw summon count alone."
        ),
        "mechanic_tags": ("damage_redirect", "defensive_utility", "reduced_life", "cooldown_tradeoff"),
        "scaling_axes": ("life_pool", "cooldown_recovery", "survivability", "uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Stone_Golem_of_Safeguarding",
    },
    {
        "source_id": "raise_spectre.corpse_skill_package_and_spectre_bank",
        "skill_gates": ("Raise Spectre", "Raise Spectre of Transience"),
        "label": "Corpse skill package and spectre bank",
        "description": (
            "Raise Spectre inherits the chosen corpse monster's skill package and AI rather than a fixed gem "
            "attack, while saved spectre corpses can be recreated with Desecrate. Damage scales through "
            "corpse selection, support compatibility, and encounter setup instead of a single universal "
            "spectre profile."
        ),
        "mechanic_tags": ("corpse_sourced_minion", "monster_skill_package", "desecrate_bank", "support_compatibility"),
        "scaling_axes": ("corpse_selection", "spectre_limit", "support_choice", "setup_reliability"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Raise_Spectre",
    },
    {
        "source_id": "raise_zombie.single_strike_support_surface_and_player_spell_separation",
        "skill_gates": ("Raise Zombie",),
        "label": "Zombie damage stays on one melee strike support surface",
        "description": (
            "Raised zombies do not inherit a broad monster skill package: their damage comes from one melee "
            "strike attack, so strike-compatible minion supports scale their output while the gem's spell tag "
            "mainly affects the player's cast or trigger shell rather than zombie hit damage."
        ),
        "mechanic_tags": ("fixed_minion_attack_profile", "support_surface", "player_cast_minion_damage_split"),
        "scaling_axes": ("support_choice", "minion_attack_speed", "minion_limit", "trigger_setup"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Raise_Zombie",
    },
    {
        "source_id": "raise_zombie_of_falling.action_speed_drop_and_on_death_payload",
        "skill_gates": ("Raise Zombie of Falling",),
        "label": "Action speed controls descent, then impact and on-death payloads take over",
        "description": (
            "Raise Zombie of Falling deals damage through a delivery loop: the zombie is alive while "
            "falling, descent speed scales with minion action speed, the landing hit is one instant melee "
            "AoE attack that Multistrike cannot repeat, and the zombie then dies to enable unconditional "
            "on-death effects without leaving a corpse or triggering Minion Instability."
        ),
        "mechanic_tags": ("falling_minion_delivery", "action_speed_travel", "instant_impact_attack", "on_death_payload"),
        "scaling_axes": ("minion_action_speed", "minion_limit", "support_choice", "on_death_synergy"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Raise_Zombie_of_Falling",
    },
    {
        "source_id": "raise_zombie_of_slamming.cooldown_queued_slam_priority",
        "skill_gates": ("Raise Zombie of Slamming",),
        "label": "Slams auto-queue off cooldown and outrank most other actions",
        "description": (
            "Raise Zombie of Slamming automatically queues Zombie Slam as soon as its cooldown is ready and "
            "prioritizes that action over everything except movement. Real damage therefore scales through "
            "slam cooldown recovery, zombie uptime on target, and how often minions can stand still long "
            "enough to execute the queued AoE hit."
        ),
        "mechanic_tags": ("cooldown_gated_minion_nuke", "queued_priority_attack", "movement_uptime_tradeoff", "aoe_slam"),
        "scaling_axes": ("minion_cooldown_recovery", "movement_uptime", "minion_limit", "support_choice"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Raise_Zombie_of_Slamming",
    },
    {
        "source_id": "summon_skeletons.cap_and_per_cast_ramp",
        "skill_gates": ("Summon Skeletons",),
        "include_transfigured": True,
        "label": "Cap and per-cast ramp",
        "description": (
            "Summon Skeletons scales by filling and sustaining a temporary skeleton cap. The skill summons "
            "multiple skeletons per cast, the cap itself scales with gem progression and quality, and each "
            "skeleton expires after a duration, so cast cadence, duration, and maximum skeleton count define "
            "sustained active minion output."
        ),
        "mechanic_tags": ("temporary_minion", "summon_cap", "per_cast_multiplicity", "duration_ramp"),
        "scaling_axes": ("cast_speed", "summons_per_cast", "duration", "minion_limit"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Summon_Skeletons",
    },
    {
        "source_id": "vaal_summon_skeletons.army_burst_and_general_window",
        "skill_gates": ("Vaal Summon Skeletons",),
        "label": "Army burst and general window",
        "description": (
            "Vaal Summon Skeletons front-loads a large temporary army led by the general, so output scales "
            "through active-minion uptime and how quickly one cast fills its temporary army window rather "
            "than through one-by-one permanent minion ramp."
        ),
        "mechanic_tags": ("temporary_minion", "burst_army", "general_support", "active_cap_fill"),
        "scaling_axes": ("duration", "summons_per_cast", "minion_limit", "target_acquisition"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Summon_Skeletons",
    },
    {
        "source_id": "dominating_blow.sentinel_ramp_and_caps",
        "skill_gates": ("Dominating Blow",),
        "include_transfigured": True,
        "label": "Sentinel ramp and caps",
        "description": (
            "Dominating Blow's total output is split between the strike and several sentinel families with "
            "separate caps. Rare and unique enemies also provide a fallback chance to summon a normal "
            "sentinel on hit, so hit consistency, kill tempo, and minion duration all affect how reliably "
            "the build reaches and maintains its cap."
        ),
        "mechanic_tags": ("minion_ramp", "summon_caps", "fallback_summon", "dual_scaling"),
        "scaling_axes": ("hit_rate", "kill_rate", "duration", "minion_limit"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Dominating_Blow",
    },
    {
        "source_id": "chain_hook.range_gated_pull_and_cleave",
        "skill_gates": ("Chain Hook", "Chain Hook of Trarthus"),
        "label": "Range-gated pull and cleave",
        "description": (
            "Chain Hook has two delivery modes. At range it throws a chain that pulls the player to the "
            "hooked enemy and deals area damage behind that target; in melee range it skips the pull and "
            "performs the area hit directly. Real damage therefore depends on target distance and where "
            "other enemies stand relative to the hooked target, not just on a stationary strike."
        ),
        "mechanic_tags": ("distance_gate", "forced_reposition", "behind_target_area", "melee_range_override"),
        "scaling_axes": ("enemy_distance", "positioning", "area_of_effect", "target_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Chain_Hook",
    },
    {
        "source_id": "consecrated_path.enemy_targeted_teleport_slam",
        "skill_gates": ("Consecrated Path", "Consecrated Path of Endurance"),
        "label": "Enemy-targeted teleport slam",
        "description": (
            "Consecrated Path teleports to a nearby enemy at the targeted location before slamming and "
            "creating consecrated ground. That makes it a movement attack whose real coverage depends on "
            "enemy placement and landing position, while Multistrike cannot repeat the teleport-slam "
            "sequence for free extra hits."
        ),
        "mechanic_tags": ("enemy_targeted_teleport", "movement_attack", "ground_uptime", "multistrike_lockout"),
        "scaling_axes": ("enemy_density", "target_positioning", "area_of_effect", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Consecrated_Path",
    },
    {
        "source_id": "ensnaring_arrow.projectile_termination_snare_gate",
        "skill_gates": ("Ensnaring Arrow",),
        "label": "Projectile termination gates snare",
        "description": (
            "Ensnaring Arrow only applies its snare when the arrow ends on the enemy. Pierce and fork "
            "therefore prevent ensnaring entirely, while chain or return only allow a snare if the "
            "projectile has no valid continuation and stops on that target. Scaling shifts toward "
            "projectile-behaviour control and snare uptime rather than blindly stacking generic "
            "projectile modifiers."
        ),
        "mechanic_tags": (
            "projectile_termination_gate",
            "anti_pierce_fork",
            "chain_return_caveat",
            "snare_uptime",
        ),
        "scaling_axes": ("pierce_chain_fork", "returning_projectiles", "skill_effect_duration", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ensnaring_Arrow",
    },
    {
        "source_id": "cyclone.moving_channel_contact_uptime",
        "skill_gates": ("Cyclone", "Cyclone of Tumult"),
        "label": "Moving channel contact uptime",
        "description": (
            "Cyclone deals repeated melee hits while channelling and moving, so its listed attack speed only "
            "turns into damage if enemies stay inside the spin radius along the travel path. The base spin "
            "radius is fixed instead of inheriting weapon range, which pushes real scaling toward area "
            "investment and route control; Cyclone of Tumult adds stages that widen the spin and speed the "
            "hits while slowing movement, making stage upkeep part of the same contact problem."
        ),
        "mechanic_tags": ("moving_channel", "repeat_hits", "contact_uptime", "fixed_spin_radius"),
        "scaling_axes": ("attack_speed", "area_of_effect", "movement_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cyclone",
    },
    {
        "source_id": "vaal_cyclone.stationary_pull_duration_window",
        "skill_gates": ("Vaal Cyclone",),
        "label": "Stationary pull-duration window",
        "description": (
            "Vaal Cyclone spins in place for a fixed duration, repeatedly damaging nearby enemies while "
            "pulling them inward. Real output therefore depends on how much enemy density the pull can keep "
            "inside the spin radius for that window, while duration scaling stretches both the damage window "
            "and the self-locking commitment instead of acting like ordinary movement Cyclone."
        ),
        "mechanic_tags": ("stationary_spin", "enemy_pull", "duration_window", "density_capture"),
        "scaling_axes": ("duration", "area_of_effect", "enemy_density", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Cyclone",
    },
    {
        "source_id": "ethereal_knives.preset_spread_no_shotgun",
        "skill_gates": ("Ethereal Knives", "Ethereal Knives of the Massacre"),
        "label": "Preset spread without same-target shotgun",
        "description": (
            "Ethereal Knives variants distribute knives in preset geometry rather than converging them onto "
            "one point, and multiple knives from one cast cannot hit the same target. Base Ethereal Knives "
            "uses a fixed fan while Ethereal Knives of the Massacre fires a circle, so extra projectiles and "
            "positioning mainly change lane or ring coverage instead of creating single-target overlap."
        ),
        "mechanic_tags": ("preset_spread", "no_shotgun", "coverage_geometry", "positioning"),
        "scaling_axes": ("projectile_count", "cast_speed", "projectile_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ethereal_Knives",
    },
    {
        "source_id": "flame_dash.shared_blink_charges_and_burning_path",
        "skill_gates": ("Flame Dash",),
        "label": "Shared blink charges and burning path",
        "description": (
            "Flame Dash is a stored-use Blink skill rather than a pure spam spell: it banks multiple uses, "
            "shares cooldown with other Blink skills, and leaves burning ground across its travelled path. "
            "Real damage and mobility therefore depend on charge routing, path coverage, and cooldown "
            "recovery, while the dash still interrupts channeling even when the first use feels nearly instant."
        ),
        "mechanic_tags": ("stored_uses", "shared_blink_cooldown", "burning_path", "channel_interrupt"),
        "scaling_axes": ("cooldown_recovery", "charge_management", "distance", "burning_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Flame_Dash",
    },
    {
        "source_id": "icicle_mine.detonation_sequence_projectile_ramp",
        "skill_gates": ("Icicle Mine", "Icicle Mine of Sabotage"),
        "label": "Detonation-sequence projectile ramp",
        "description": (
            "Icicle Mine fires projectiles outward from each mine and gains an additional projectile for every "
            "two prior mines in the same detonation sequence. It also grants a stacking critical-strike aura "
            "against nearby enemies, so real output depends on mine count, detonation order, and keeping "
            "targets inside the mine cluster; Icicle Mine of Sabotage keeps that geometry but upgrades the aura."
        ),
        "mechanic_tags": ("mine_sequence", "additional_projectiles", "outward_nova", "stacking_aura"),
        "scaling_axes": ("mines_per_sequence", "detonation_order", "projectile_count", "enemy_proximity"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Icicle_Mine",
    },
    {
        "source_id": "icicle_mine_of_fanning.targeted_cone_sequence",
        "skill_gates": ("Icicle Mine of Fanning",),
        "label": "Targeted cone detonation sequence",
        "description": (
            "Icicle Mine of Fanning keeps the sequence-based projectile ramp, but fires a smaller projectile "
            "set toward a selected enemy instead of a full circular nova. That shifts scaling toward targeted "
            "cone placement and single-lane coverage, while mine count and detonation order still determine "
            "how many projectiles the sequence produces."
        ),
        "mechanic_tags": ("mine_sequence", "targeted_cone", "additional_projectiles", "enemy_targeting"),
        "scaling_axes": ("mines_per_sequence", "detonation_order", "projectile_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Icicle_Mine_of_Fanning",
    },
    {
        "source_id": "frenzy.pre_hit_charge_snapshot_and_sequence_cap",
        "skill_gates": ("Frenzy", "Frenzy of Onslaught"),
        "label": "Pre-hit charge snapshot and sequence-limited gain",
        "description": (
            "Frenzy variants calculate their per-charge damage and speed bonuses from the Frenzy Charges "
            "you had before the hit lands, so the same attack does not scale off the charge it grants. "
            "Multistrike and Ancestral Call also only grant one Frenzy Charge per attack sequence, and "
            "Frenzy of Onslaught only converts charges into Onslaught when that pre-hit state was already "
            "at maximum."
        ),
        "mechanic_tags": (
            "pre_hit_charge_snapshot",
            "sequence_limited_charge_gain",
            "multistrike_caveat",
            "ancestral_call_caveat",
        ),
        "scaling_axes": ("frenzy_charge_count", "attack_speed", "charge_generation_uptime", "target_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frenzy_of_Onslaught",
    },
    {
        "source_id": "puncture.moving_target_bleed_payoff",
        "skill_gates": ("Puncture", "Puncture of Shanking"),
        "label": "Moving-target bleed payoff",
        "description": (
            "Puncture's bleed deals its real payoff when the target is moving, so encounter pattern and "
            "forced movement matter as much as the listed ailment value. Because the bleed window is also "
            "sensitive to skill duration, duration investment changes how long that movement-amplified "
            "damage can be exploited."
        ),
        "mechanic_tags": ("moving_target_bleed", "forced_movement_payoff", "duration_window", "hybrid_hit_ailment"),
        "scaling_axes": ("bleed_damage", "skill_effect_duration", "enemy_movement", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Puncture",
    },
    {
        "source_id": "reap.shared_blood_charge_refresh_and_proxy_limit",
        "skill_gates": ("Reap",),
        "activation_mechanic_family_ids": ("blood_charge_family",),
        "activation_package_ids": ("reap_blood_charge_package",),
        "label": "Shared Blood Charges with proxy limits",
        "description": (
            "Reap's Blood Charges are shared across all Reap gems, refresh their duration whenever a new "
            "charge is gained, and are not built for the player by proxy hits such as totems. Real scaling "
            "therefore depends on maintaining your own hit cadence to keep the shared charge pool alive "
            "instead of assuming every remote cast source can build or refresh it."
        ),
        "mechanic_tags": ("shared_charge_pool", "duration_refresh", "proxy_generation_limit", "self_hit_uptime"),
        "scaling_axes": ("blood_charge_count", "duration", "cast_speed", "proxy_usage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Reap",
    },
    {
        "source_id": "vaal_reap.preloads_expanded_blood_charge_cap",
        "skill_gates": ("Vaal Reap",),
        "activation_mechanic_family_ids": ("blood_charge_family",),
        "activation_package_ids": ("reap_blood_charge_package",),
        "label": "Preloads an expanded Blood Charge cap",
        "description": (
            "Vaal Reap temporarily grants +4 maximum Blood Charges and immediately fills the enlarged cap, "
            "effectively pre-stacking base Reap before the follow-up cast chain begins. Its value therefore "
            "scales with how much of that preloaded window you can convert into regular Reap hits before "
            "the buff expires."
        ),
        "mechanic_tags": (
            "temporary_max_charge_increase",
            "preloaded_charge_pool",
            "followup_burst_window",
            "shared_reap_resource",
        ),
        "scaling_axes": ("blood_charge_count", "buff_duration", "cast_speed", "burst_window"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Reap",
    },
    {
        "source_id": "viper_strike.dual_wield_double_poison_cycle",
        "skill_gates": ("Viper Strike",),
        "exclude_skill_ids": ("SummonedSpiderViperStrike",),
        "label": "Dual-wield double poison cycle",
        "description": (
            "Player Viper Strike hits with each weapon separately while dual wielding, so one attack can "
            "create two hit events and two poison applications. Its built-in poison duration overrides the "
            "normal base poison duration and scales with both skill effect duration and ailment duration, "
            "making poison stack upkeep a combined attack-speed and duration problem."
        ),
        "mechanic_tags": (
            "dual_wield_double_hit",
            "double_poison_application",
            "override_poison_duration",
            "stack_maintenance",
        ),
        "scaling_axes": ("dual_wield_state", "attack_speed", "skill_effect_duration", "ailment_duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Viper_Strike",
    },
    {
        "source_id": "summoned_spider_viper_strike.always_poison_dual_wield_duration_cycle",
        "skill_gates": ("Viper Strike",),
        "include_skill_ids": ("SummonedSpiderViperStrike",),
        "label": "Always-poison dual-wield spider cycle",
        "description": (
            "The spider Viper Strike variant always poisons and can strike with both weapons while dual "
            "wielding, so one minion attack can deliver two poison applications. Its poison duration is also "
            "explicitly tied to skill duration scaling, making uptime a combined minion-speed and duration problem."
        ),
        "mechanic_tags": ("always_poison", "dual_wield_double_hit", "poison_duration_override"),
        "scaling_axes": ("minion_attack_speed", "skill_effect_duration", "poison_duration", "minion_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Skill%3ASummonedSpiderViperStrike",
    },
    {
        "source_id": "viper_strike_of_the_mamba.single_poison_duration_cycle",
        "skill_gates": ("Viper Strike of the Mamba",),
        "label": "Single merged poison cycle",
        "description": (
            "Viper Strike of the Mamba combines both weapons into one hit and one poison instead of "
            "creating separate dual-wield applications. Its poison duration still scales with skill effect "
            "and ailment duration, so over-attacking before the poison expires wastes the variant's "
            "intended cadence and pushes scaling toward duration-aligned attack speed rather than maximum "
            "hit frequency."
        ),
        "mechanic_tags": (
            "merged_dual_wield_hit",
            "single_poison_application",
            "duration_cadence",
            "ailment_cycle",
        ),
        "scaling_axes": ("attack_speed", "skill_effect_duration", "ailment_duration", "poison_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Viper_Strike_of_the_Mamba",
    },
    {
        "source_id": "alchemists_mark.ailment_ground_snapshot_and_proxy_limits",
        "skill_gates": ("Alchemist's Mark",),
        "label": "Ailment ground snapshot with trigger limits",
        "description": (
            "Alchemist's Mark snapshots the strongest ignite or poison on the marked target into burning "
            "or caustic ground, but each ground effect can only be created once per second. Proliferated "
            "ignites and hits from proxies such as traps or totems cannot create the ground, while the "
            "ground duration is independent of the source ailment duration, so scaling favors strong "
            "direct-hit ailment applications over proxy spam or long-duration upkeep."
        ),
        "mechanic_tags": (
            "ailment_snapshot",
            "per_ground_type_trigger_cap",
            "proxy_exclusion",
            "proliferation_exclusion",
        ),
        "scaling_axes": ("ignite_dps", "poison_dps", "hit_cadence", "mark_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Alchemist%27s_Mark",
    },
    {
        "source_id": "blast_rain_of_trarthus.directional_wave_and_dual_debuff_application",
        "skill_gates": ("Blast Rain of Trarthus",),
        "label": "Directional wave with dual debuff application",
        "description": (
            "Blast Rain of Trarthus applies its burning debuff both on the landing impact and on the fire "
            "wave released afterward, so target placement can catch enemies with both coverage zones while "
            "still only using one arrow. Because the wave is the real area payoff and extra projectile "
            "modifiers do not add arrows, damage scaling leans on positioning, radius, and projectile-damage "
            "scaling for the burn rather than generic projectile-count stacking."
        ),
        "mechanic_tags": (
            "impact_and_wave_application",
            "single_arrow_lock",
            "directional_area_coverage",
            "projectile_damage_dot_scaling",
        ),
        "scaling_axes": ("area_of_effect", "projectile_damage", "target_positioning", "burning_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Blast_Rain_of_Trarthus",
    },
    {
        "source_id": "cleave.dual_wield_combined_hit_geometry",
        "skill_gates": ("Cleave",),
        "exclude_skill_ids": ("HeraldOfAgonyMinionCleave",),
        "label": "Combined dual-wield hit geometry",
        "description": (
            "Cleave combines both weapons into one simultaneous hit when dual wielding, averaging their "
            "attack times and folding both damage rolls into a single area strike with the skill's built-in "
            "penalty. Real scaling therefore depends on how well the two weapons pair on speed and damage, "
            "rather than on alternating-hand attack patterns."
        ),
        "mechanic_tags": ("combined_dual_wield_hit", "averaged_attack_time", "single_area_strike"),
        "scaling_axes": ("main_hand_damage", "off_hand_damage", "attack_speed", "weapon_pairing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cleave",
    },
    {
        "source_id": "herald_of_agony_minion_cleave.virulence_ramp_single_crawler_melee_fallback",
        "skill_gates": ("Cleave",),
        "include_skill_ids": ("HeraldOfAgonyMinionCleave",),
        "label": "Virulence-ramped crawler melee fallback",
        "description": (
            "The Agony Crawler is capped at one active minion and gains attack speed and damage from Virulence "
            "stacks, so this internal melee fallback scales with poison-driven Virulence upkeep and crawler "
            "uptime rather than with any standalone player weapon geometry."
        ),
        "mechanic_tags": ("virulence_ramp", "single_minion_cap", "minion_fallback_attack"),
        "scaling_axes": ("virulence_stacks", "poison_application_rate", "minion_uptime", "minion_attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Herald_of_Agony",
    },
    {
        "source_id": "cleave_of_rage.rage_radius_and_dual_weapon_pairing",
        "skill_gates": ("Cleave of Rage",),
        "label": "Rage-fed radius with locked weapon pairing",
        "description": (
            "Cleave of Rage still combines both weapons into one hit, but it requires a dual-wielded axe "
            "and sword pair, gains rage on attack hit, and expands its radius per five rage. Its effective "
            "clear and overlap window therefore scale with rage generation and maintenance, not just static "
            "area modifiers."
        ),
        "mechanic_tags": (
            "combined_dual_wield_hit",
            "weapon_type_lock",
            "rage_generation",
            "rage_scaled_radius",
        ),
        "scaling_axes": ("rage_generation", "rage_uptime", "area_of_effect", "weapon_pairing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Melee_skill",
    },
    {
        "source_id": "cobra_lash.remaining_chain_damage_routing",
        "skill_gates": ("Cobra Lash",),
        "label": "Remaining-chain damage routing",
        "description": (
            "Cobra Lash deals more hit and ailment damage for each remaining chain, which means earlier "
            "links in the chain are the highest-value applications and each spent chain lowers later damage. "
            "The skill therefore scales not only with total chain count, but with routing that preserves "
            "high-value early hits on priority targets before the projectile bounces away."
        ),
        "mechanic_tags": ("remaining_chain_damage", "frontloaded_chain_damage", "routing_sensitive"),
        "scaling_axes": ("chain_count", "projectile_routing", "single_target_priority", "poison_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Cobra_Lash",
    },
    {
        "source_id": "dual_strike.combined_hit_attack_time_and_range_selection",
        "skill_gates": ("Dual Strike",),
        "label": "Combined hit with averaged speed and longest range",
        "description": (
            "Dual Strike merges both weapons into one strike, averages the attack time of both hands, and "
            "uses the larger weapon range if the pair differs. That makes real scaling sensitive to off-hand "
            "speed and range support even though the skill delivers one combined hit."
        ),
        "mechanic_tags": (
            "combined_dual_wield_hit",
            "averaged_attack_time",
            "highest_weapon_range",
            "pairing_sensitive",
        ),
        "scaling_axes": ("attack_speed", "weapon_range", "main_hand_damage", "off_hand_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Dual_Strike",
    },
    {
        "source_id": "dual_strike_of_ambidexterity.main_hand_damage_offhand_speed",
        "skill_gates": ("Dual Strike of Ambidexterity",),
        "label": "Main-hand damage keyed to off-hand attack time",
        "description": (
            "Dual Strike of Ambidexterity still strikes with both weapons at once, but it specifically uses "
            "the off-hand weapon's attack time while granting more damage to the main hand and requiring two "
            "different melee weapon types. Its scaling therefore pushes toward a slow, high-damage main hand "
            "paired with a fast off-hand weapon to drive the sequence speed."
        ),
        "mechanic_tags": (
            "combined_dual_wield_hit",
            "off_hand_attack_time",
            "main_hand_damage_bias",
            "weapon_type_mismatch_requirement",
        ),
        "scaling_axes": ("main_hand_damage", "off_hand_attack_speed", "weapon_pairing", "attack_cadence"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Dual_Strike_of_Ambidexterity",
    },
    {
        "source_id": "crushing_fist.retaliation_usable_state_and_shared_pool",
        "skill_gates": ("Crushing Fist",),
        "label": "Retaliation usable-state windows and shared pool rules",
        "description": (
            "Crushing Fist only becomes usable after a block event, then spends that usable state when cast "
            "unless a remain-usable modifier preserves it. Different retaliation skills can become usable "
            "from the same blocked hit without consuming each other, while copies of Crushing Fist share the "
            "same usability and cooldown, so scaling depends on block cadence and retaliation rotation rather "
            "than only the skill's own base cooldown."
        ),
        "mechanic_tags": (
            "block_gated_usable_state",
            "retaliation_rotation",
            "same_skill_shared_cooldown",
            "different_skill_independent_usability",
        ),
        "scaling_axes": ("block_rate", "retaliation_uptime", "cooldown_recovery_rate", "skill_rotation"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Retaliation",
    },
    {
        "source_id": "conflagration.stuck_arrow_chain_explosion_and_proximity_trigger",
        "skill_gates": ("Conflagration",),
        "label": "Stuck-arrow chain explosion payoff",
        "description": (
            "Conflagration leaves arrows stuck in the ground, then turns nearby enemy movement into the real "
            "payoff by exploding those arrows, applying its fire debuff, and chaining detonations through "
            "other embedded arrows in range. Because only a limited number of arrows can stay embedded at "
            "once, effective scaling depends on arrow density, target movement, and overlap-friendly "
            "positioning rather than only on raw firing cadence."
        ),
        "mechanic_tags": (
            "stuck_projectiles",
            "proximity_trigger",
            "chain_explosion",
            "embedded_arrow_cap",
        ),
        "scaling_axes": ("projectile_count", "area_of_effect", "target_positioning", "debuff_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Conflagration",
    },
    {
        "source_id": "divine_blast.implosion_then_delayed_larger_explosion",
        "skill_gates": ("Divine Blast",),
        "label": "Two-stage delayed explosion payoff",
        "description": (
            "Divine Blast first strikes with an implosion, then leaves energy behind that detonates shortly "
            "after in a larger and more damaging explosion. Its real scaling therefore leans on keeping "
            "targets inside the delayed second stage and on radius or positioning that make the larger "
            "explosion the dominant damage event instead of treating the beam contact as the full payload."
        ),
        "mechanic_tags": (
            "two_stage_hit",
            "delayed_explosion",
            "larger_second_stage",
            "positioning_sensitive",
        ),
        "scaling_axes": ("area_of_effect", "target_positioning", "target_control", "hit_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Divine_Blast",
    },
    {
        "source_id": "divine_retribution.block_gated_cross_wave_burst_coverage",
        "skill_gates": ("Divine Retribution",),
        "label": "Block-gated cross-wave retaliation coverage",
        "description": (
            "Divine Retribution cannot be used freely: a block opens only a short retaliation window, and "
            "each use releases four cross-pattern waves made of repeated bursts. Effective scaling therefore "
            "depends on reliable block cadence and on area or spacing that let multiple wave segments pass "
            "through the target during that brief usable state, not on ordinary repeat casting."
        ),
        "mechanic_tags": (
            "block_gated_use_window",
            "retaliation_skill",
            "multi_wave_bursts",
            "cross_pattern_coverage",
        ),
        "scaling_axes": ("block_chance", "retaliation_uptime", "area_of_effect", "target_spacing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Divine_Retribution",
    },
    {
        "source_id": "elemental_hit.element_selection_prehit_ailment_window_and_conversion_routing",
        "skill_gates": ("Elemental Hit",),
        "label": "Element choice sequencing with pre-hit ailment gating",
        "description": (
            "Elemental Hit chooses one element before each attack, avoids choosing the same element twice in "
            "a row, and only gets its enlarged area from ailments already matching that chosen element on "
            "the target. Added fire, cold, and lightning from gear still all feed the hit before the "
            "non-chosen portions are removed by conversion rules, so real scaling depends on pre-applied "
            "ailments, element sequencing, and conversion-aware added damage instead of only the gem's "
            "listed per-ailment multiplier."
        ),
        "mechanic_tags": (
            "rotating_element_choice",
            "no_same_element_twice",
            "prehit_ailment_gate",
            "pre_conversion_added_damage",
        ),
        "scaling_axes": (
            "elemental_ailment_coverage",
            "added_elemental_damage",
            "conversion_routing",
            "hit_sequence",
        ),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Elemental_Hit",
    },
    {
        "source_id": "elemental_hit_of_the_spectrum.triple_element_payload_per_hit",
        "skill_gates": ("Elemental Hit of the Spectrum",),
        "label": "All-three-elements payload on every hit",
        "description": (
            "Elemental Hit of the Spectrum drops the rotating single-element cycle and instead fires one "
            "projectile that always carries fire, cold, and lightning before splashing area damage around "
            "the enemy it hits. That shifts scaling toward stacking multi-element added damage and ailment "
            "coverage on the same hit, rather than solving the base skill's element sequencing and chosen-"
            "element setup."
        ),
        "mechanic_tags": (
            "triple_element_payload",
            "on_hit_area_splash",
            "all_elements_single_hit",
            "multi_ailment_setup",
        ),
        "scaling_axes": (
            "added_elemental_damage",
            "elemental_ailment_coverage",
            "projectile_hit_consistency",
            "area_of_effect",
        ),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Elemental_Hit_of_the_Spectrum",
    },
    {
        "source_id": "infernal_blow.enemy_debuff_stack_vs_splash",
        "skill_gates": ("Infernal Blow",),
        "label": "Direct-hit charge stacks and non-chaining corpse blasts",
        "description": (
            "Infernal Blow only applies its charged debuff to enemies struck directly, while splash and other "
            "nearby hits only receive the uncharged corpse-explosion debuff. The charged explosion also "
            "cannot chain new debuffs onward, and repeats such as Multistrike only add one charge per "
            "attack sequence, so real scaling depends on direct-hit cadence rather than generic repeat or "
            "splash target count."
        ),
        "mechanic_tags": (
            "direct_hit_only_charges",
            "splash_uncharged_only",
            "non_chaining_explosions",
            "sequence_limited_charge_gain",
        ),
        "scaling_axes": ("attack_speed", "direct_hit_uptime", "repeat_behavior", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Infernal_Blow",
    },
    {
        "source_id": "infernal_blow_of_immolation.self_debuff_one_charge_per_use",
        "skill_gates": ("Infernal Blow of Immolation",),
        "label": "Self-stored debuff with one charge per use",
        "description": (
            "Infernal Blow of Immolation stores its charged debuff on the player instead of on enemies, so "
            "the payoff is a self-timed detonation rather than an enemy death chain. It only gains one "
            "charge debuff per use even with Multistrike, Ancestral Call, or Melee Splash hitting multiple "
            "targets, which makes attack sequence count and timing more important than raw nearby-enemy "
            "coverage."
        ),
        "mechanic_tags": ("self_stored_debuff", "sequence_limited_charge_gain", "multitarget_no_extra_charges"),
        "scaling_axes": ("attack_speed", "use_count", "debuff_duration", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Infernal_Blow_of_Immolation",
    },
    {
        "source_id": "pestilent_strike.remaining_poison_transfer",
        "skill_gates": ("Pestilent Strike",),
        "label": "Remaining poison transfer on kill",
        "description": (
            "Pestilent Strike turns a poisoned enemy's remaining poison damage into a one-second secondary "
            "debuff on nearby enemies when that target dies, using half of the poison damage still left on "
            "the corpse. Because all poison sources transfer and poison duration raises the amount still "
            "remaining at death, the skill scales with poison stack depth, duration, and add-spawn geometry "
            "rather than only the strike's own hit pattern."
        ),
        "mechanic_tags": (
            "on_kill_poison_transfer",
            "remaining_damage_snapshot",
            "all_poison_sources_contribute",
            "spawn_dependent_spread",
        ),
        "scaling_axes": ("poison_damage", "poison_duration", "kill_timing", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Pestilent_Strike",
    },
    {
        "source_id": "reave.shared_stage_pool_and_vaal_cap_extension",
        "skill_gates": ("Reave", "Reave of Refraction", "Vaal Reave"),
        "label": "Shared stage pool with Vaal cap extension",
        "description": (
            "Reave variants share the same stage upkeep model: hitting keeps stages alive, missing for "
            "three seconds makes them fall off incrementally, and that timer cannot be extended with "
            "duration scaling. Vaal Reave can raise the maintained stack cap beyond the normal limit and "
            "that expanded cap applies back to socketed Reave gems, so real damage scaling depends on stage "
            "maintenance uptime and Vaal setup windows."
        ),
        "mechanic_tags": (
            "shared_stage_pool",
            "hit_maintenance",
            "non_scalable_falloff_timer",
            "vaal_cap_extension",
        ),
        "scaling_axes": ("stage_count", "hit_uptime", "vaal_setup_window", "area_scaling"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Reave",
    },
    {
        "source_id": "tempest_shield.block_triggered_chain_arc",
        "skill_gates": ("Tempest Shield",),
        "label": "Block-triggered lightning chain",
        "description": (
            "Tempest Shield only deals damage when you successfully block a direct attack or spell, then "
            "fires a lightning arc from the attacker that chains to nearby enemies. Its real output "
            "therefore scales with incoming hit frequency, block uptime, enemy density around the blocker, "
            "and any extra chain sources that extend each proc."
        ),
        "mechanic_tags": ("block_trigger", "incoming_hit_gate", "chain_arc", "enemy_density_scaling"),
        "scaling_axes": ("block_chance", "incoming_hit_rate", "chain_count", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tempest_Shield",
    },
    {
        "source_id": "creeping_frost_of_floes.mobile_chilling_area_enemy_tracking",
        "skill_gates": ("Creeping Frost of Floes",),
        "label": "Enemy-tracking chilling area with fixed projectile count",
        "description": (
            "Creeping Frost of Floes is locked to a single projectile, then converts the real payoff into a "
            "chilling area that actively creeps toward nearby enemies after the projectile lands or contacts "
            "a target. Its output therefore scales with how long that moving ground effect can stay attached "
            "to enemies, while area management is constrained by the variant's cap on active chilling areas."
        ),
        "mechanic_tags": ("single_projectile_lock", "enemy_tracking_ground_dot", "contact_detonation", "area_cap"),
        "scaling_axes": ("duration", "area_of_effect", "enemy_proximity", "ground_dot_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Creeping_Frost_of_Floes",
    },
    {
        "source_id": "eviscerate.dual_wave_close_range_double_hit",
        "skill_gates": ("Eviscerate",),
        "label": "Dual-wave close-range double hit",
        "description": (
            "Eviscerate only becomes usable for a short retaliation window after you block, then attacks in "
            "two rectangular waves that open outward in a V shape. Targets near the centerline can be missed "
            "at long range but clipped by both waves up close, so real damage scales with block uptime and "
            "close-range positioning rather than reading like a simple single-swipe retaliation."
        ),
        "mechanic_tags": ("retaliation_window", "dual_wave", "close_range_double_hit", "v_shape_gap"),
        "scaling_axes": ("block_rate", "retaliation_uptime", "target_distance", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Eviscerate",
    },
    {
        "source_id": "explosive_trap_of_magnitude.single_burst_no_secondary_explosions",
        "skill_gates": ("Explosive Trap of Magnitude",),
        "label": "Single burst without secondary explosions",
        "description": (
            "Explosive Trap of Magnitude removes the normal follow-up smaller explosions and concentrates its "
            "damage into one larger trap burst. That changes the skill from an overlap and repeat-explosion "
            "problem into a single detonation payload, and even modifiers that would add smaller explosions "
            "do not restore the missing secondary hits."
        ),
        "mechanic_tags": ("single_burst", "no_secondary_explosions", "overlap_removed", "support_choice"),
        "scaling_axes": ("trap_throwing_speed", "area_of_effect", "single_target_focus", "support_choice"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Explosive_Trap_of_Magnitude",
    },
    {
        "source_id": "frost_wall.projectile_lane_control_and_staggered_sections",
        "skill_gates": ("Frost Wall",),
        "label": "Projectile lane control with staggered wall sections",
        "description": (
            "Frost Wall creates its wall in staggered sections, damages and pushes enemies caught under the "
            "spawn, then blocks monsters and most projectiles while still letting the caster's own "
            "projectiles pass through. That makes the skill's damage and utility scale with wall length, "
            "lane placement, and how well the barrier shapes enemy or projectile routing instead of acting "
            "like a conventional stationary AoE."
        ),
        "mechanic_tags": ("projectile_barrier", "self_projectile_exception", "staggered_section_spawn", "pushback"),
        "scaling_axes": ("wall_length", "skill_duration", "cooldown_recovery_rate", "projectile_alignment"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frost_Wall",
    },
    {
        "source_id": "frostblink.dual_endpoint_hit_and_shared_blink_cooldown",
        "skill_gates": ("Frostblink",),
        "label": "Dual-endpoint hit with shared Blink cooldown",
        "description": (
            "Frostblink damages and leaves chilled ground at both ends of the teleport, while its cooldown "
            "recovers faster from hitting enemies and is shared with other Blink skills. Real output and "
            "mobility therefore scale with endpoint placement, pack density, and cooldown routing rather "
            "than only the listed hit damage on one landing point."
        ),
        "mechanic_tags": ("dual_endpoint_hit", "shared_blink_cooldown", "enemy_hit_cdr", "chilled_ground_path"),
        "scaling_axes": ("cooldown_recovery", "positioning", "distance", "enemy_density"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Frostblink",
    },
    {
        "source_id": "glacial_hammer_family.third_hit_counter_alignment_and_reset_rules",
        "skill_gates": ("Glacial Hammer", "Glacial Hammer of Shattering"),
        "label": "Third-hit counter alignment and reset rules",
        "description": (
            "Glacial Hammer variants pay off every third consecutive strike, but that counter only advances "
            "while the sequence stays uninterrupted and will reset if you stop attacking for too long or "
            "break the chain. Multistrike usually lines its own third repeat up with the skill's third-hit "
            "payoff, while Ruthless can drift out of sync, so real burst scaling depends on repeat-support "
            "alignment and uninterrupted attack uptime."
        ),
        "mechanic_tags": ("consecutive_hit_counter", "interrupt_reset", "multistrike_alignment", "ruthless_desync"),
        "scaling_axes": ("attack_speed", "animation_uptime", "repeat_supports", "burst_alignment"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Glacial_Hammer_of_Shattering",
    },
    {
        "source_id": "vaal_glacial_hammer.frost_wall_ring_entrapment",
        "skill_gates": ("Vaal Glacial Hammer",),
        "label": "Frost Wall-like ring entrapment window",
        "description": (
            "Vaal Glacial Hammer traps the target in a temporary ring of ice that behaves like a circular "
            "Frost Wall, blocking most movement and projectiles through the perimeter while the skill window "
            "lasts. That means its real payoff scales with how much damage can be forced into the lockdown "
            "window, and duration scaling stretches both the entrapment time and the accompanying soul gain "
            "prevention."
        ),
        "mechanic_tags": ("ring_barrier", "frost_wall_like_entrapment", "projectile_block", "duration_window"),
        "scaling_axes": ("skill_duration", "positioning", "target_lockdown", "soul_gain_prevention"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Vaal_Glacial_Hammer",
    },
    {
        "source_id": "ground_slam_family.fixed_wave_travel_speed_spacing_and_repeat_window",
        "skill_gates": ("Ground Slam", "Ground Slam of Earthshaking"),
        "label": "Fixed wave travel speed creates spacing and repeat timing windows",
        "description": (
            "Ground Slam releases a forward-travelling shockwave whose travel speed stays fixed instead of "
            "scaling up with attack speed. Faster attack speed only lets you launch more waves, so close "
            "targets get hit earlier than distant targets and repeated slams can stack separate wave timings "
            "down the same lane. Real output therefore scales with spacing, repeat rhythm, and keeping "
            "enemies inside the wave path rather than behaving like an instant cone."
        ),
        "mechanic_tags": (
            "fixed_wave_travel_speed",
            "travel_time_spacing",
            "repeat_window",
            "lane_hit_timing",
        ),
        "scaling_axes": ("attack_speed", "target_distance", "positioning", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ground_Slam",
    },
    {
        "source_id": "sunder.wave_overwrite_shockwave_fanout_and_aoe_width",
        "skill_gates": ("Sunder",),
        "label": "Wave overwrite, shockwave fanout, and AoE width define real coverage",
        "description": (
            "Sunder is a travelling sequence of hit areas rather than an instant cone, and using it again "
            "stops the previous wave instead of letting multiple base waves persist together. Each area can "
            "also make several struck enemies release secondary shockwaves, so real clear and single-target "
            "output scales with enemy density, lane positioning, and getting shockwave fanout instead of only "
            "the initial wave contact. Area scaling mainly widens the wave and the spawned shockwaves rather "
            "than materially extending the lane length."
        ),
        "mechanic_tags": (
            "travelling_wave",
            "wave_overwrite",
            "secondary_shockwave_fanout",
            "aoe_width_scaling",
        ),
        "scaling_axes": ("attack_speed", "enemy_density", "positioning", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Sunder",
    },
    {
        "source_id": "sunder_of_earthbreaking.concurrent_waves_fast_cadence_and_shockwave_density",
        "skill_gates": ("Sunder of Earthbreaking",),
        "label": "Concurrent waves trade per-area fanout for faster lane coverage",
        "description": (
            "Sunder of Earthbreaking runs its wave areas much faster and can keep more than one wave active "
            "at once, so attack speed scales into concurrent lane coverage instead of only replacing the "
            "previous wave. It also travels through more areas but lets fewer enemies in each area spawn "
            "shockwaves, shifting real damage toward repeat wave throughput and positioning coverage rather "
            "than the base gem's denser per-area shockwave fanout."
        ),
        "mechanic_tags": (
            "concurrent_waves",
            "fast_area_cadence",
            "shockwave_emitter_cap",
            "lane_coverage",
        ),
        "scaling_axes": ("attack_speed", "enemy_density", "positioning", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Sunder_of_Earthbreaking",
    },
    {
        "source_id": "sunder_of_trarthus.midflight_retarget_chain_and_shockwave_routing",
        "skill_gates": ("Sunder of Trarthus",),
        "label": "Mid-flight retargeting makes routing and spacing part of the damage budget",
        "description": (
            "Sunder of Trarthus can restart its travelling wave toward another enemy mid-flight, so real "
            "coverage scales with enemy spacing and routing opportunities instead of only a fixed straight "
            "lane. It still inherits the same secondary shockwave behavior as Sunder, so pack layout and AoE "
            "width both matter when trying to convert one cast into multiple routed hit clusters."
        ),
        "mechanic_tags": (
            "midflight_retarget",
            "restart_chain",
            "secondary_shockwave_fanout",
            "routing_dependence",
        ),
        "scaling_axes": ("enemy_spacing", "positioning", "attack_speed", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Sunder_of_Trarthus",
    },
    {
        "source_id": "tectonic_slam.third_slam_charge_counter_and_repeat_alignment",
        "skill_gates": ("Tectonic Slam",),
        "label": "Third-slam charge spending and repeat alignment drive fissure uptime",
        "description": (
            "Tectonic Slam only spends an Endurance Charge on every third slam when your current charges are "
            "above the minimum floor, and repeats from Multistrike count toward that same third-slam counter. "
            "Its per-Endurance-Charge fissure branching and area bonuses still apply to every slam even when "
            "no charge is actually consumed, so real output depends on repeat cadence, minimum-charge floors, "
            "and how reliably you maintain charges between each forced spend."
        ),
        "mechanic_tags": (
            "third_slam_counter",
            "repeat_counts",
            "minimum_charge_floor",
            "branching_aoe_scaling",
        ),
        "scaling_axes": ("attack_speed", "repeat_count", "endurance_charge_count", "minimum_endurance_charges"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tectonic_Slam",
    },
    {
        "source_id": "tectonic_slam_of_cataclysm.full_charge_dump_branching_nova_tradeoff",
        "skill_gates": ("Tectonic Slam of Cataclysm",),
        "label": "Full-charge dumps convert every use into one branching burst package",
        "description": (
            "Tectonic Slam of Cataclysm consumes all current Endurance Charges on every use and turns them "
            "into one burst of more damage, more area, and more fissure branching chance based on charges "
            "removed. That makes the skill scale around charge generation cadence and committing each attack "
            "as a full-charge dump, instead of the base gem's rolling every-third-slam spend loop."
        ),
        "mechanic_tags": (
            "full_charge_dump",
            "branching_fissure_burst",
            "single_burst_commit",
            "charge_spend_scaling",
        ),
        "scaling_axes": ("endurance_charge_count", "charge_generation", "attack_speed", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Tectonic_Slam_of_Cataclysm",
    },
    {
        "source_id": "heavy_strike.dual_wield_weapon_alternation",
        "skill_gates": ("Heavy Strike",),
        "label": "Dual-wield Heavy Strike alternates weapons",
        "description": (
            "Heavy Strike can still be used while dual wielding eligible one-handed axes, swords, or maces, "
            "but it alternates between the two weapons instead of combining them into one merged hit. Real "
            "damage quality therefore depends on both weapon profiles and alternation rhythm rather than only "
            "the stronger hand's strike stats."
        ),
        "mechanic_tags": (
            "dual_wield_usable",
            "weapon_alternation",
            "main_offhand_profile_split",
            "hit_pattern_variance",
        ),
        "scaling_axes": ("main_hand_damage", "off_hand_damage", "attack_speed", "weapon_choice"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Heavy_Strike",
    },
    {
        "source_id": "heavy_strike_of_trarthus.spell_damage_increases_only_no_more_less_or_crown_of_eyes_stack",
        "skill_gates": ("Heavy Strike of Trarthus",),
        "label": "Only additive spell damage scaling applies",
        "description": (
            "Heavy Strike of Trarthus routes only increases and reductions to spell damage into its attack "
            "damage. More or less spell damage modifiers do not apply, and the rule does not stack with "
            "Crown of Eyes style conversions, so real scaling wants additive spell damage and intelligence "
            "without assuming multiplicative spell-damage payoffs carry over."
        ),
        "mechanic_tags": (
            "spell_damage_conversion_rule",
            "increases_reductions_only",
            "no_more_less_scaling",
            "no_crown_of_eyes_stack",
        ),
        "scaling_axes": ("increased_spell_damage", "intelligence", "attack_speed", "gear_choice"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Heavy_Strike_of_Trarthus",
    },
    {
        "source_id": "glacial_shield_swipe.retaliation_window_and_no_trigger_or_proxy_use",
        "skill_gates": ("Glacial Shield Swipe",),
        "label": "Retaliation-only self use window",
        "description": (
            "Glacial Shield Swipe only becomes usable for a short retaliation window after you block, and "
            "like other retaliation skills it cannot be exerted, triggered, or used by proxies. Its real "
            "damage scaling therefore depends on personal block loops and incoming hit rate because the skill "
            "cannot be outsourced to totems, traps, mines, or trigger setups."
        ),
        "mechanic_tags": ("retaliation_window", "block_gate", "no_trigger_use", "no_proxy_use"),
        "scaling_axes": ("block_chance", "incoming_hit_rate", "retaliation_uptime", "self_cast_presence"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Glacial_Shield_Swipe",
    },
    {
        "source_id": "holy_hammers.enemy_contact_cascade_and_power_charge_side_columns",
        "skill_gates": ("Holy Hammers",),
        "label": "Enemy-contact cascades with power-charge side columns",
        "description": (
            "Holy Hammers starts with a slam that calls down a hammer, then each hammer that connects with an "
            "enemy causes another hammer to cascade farther forward until the cascade cap is reached. "
            "Consuming a Power Charge adds two side columns to that pattern, so real damage scales with pack "
            "alignment, cascade chaining opportunities, and charge sustain rather than only the first impact."
        ),
        "mechanic_tags": (
            "enemy_contact_cascade",
            "cascade_cap",
            "power_charge_side_columns",
            "line_coverage",
        ),
        "scaling_axes": ("enemy_density", "positioning", "power_charge_generation", "area_of_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Holy_Hammers",
    },
    {
        "source_id": "holy_strike.weapon_stat_copy_armament_followup_and_cursor_alignment",
        "skill_gates": ("Holy Strike",),
        "label": "Holy Armaments copy your weapon lane",
        "description": (
            "Holy Strike summons Holy Armaments on a successful hit, and those armaments attack with you when "
            "you use the skill while following your cursor direction instead of independently picking their own "
            "lane. Real damage therefore scales with weapon quality, formation uptime, and cursor-aligned "
            "positioning because the armament pack only pays off when its copied follow-up swings stay on the "
            "same target line."
        ),
        "mechanic_tags": (
            "holy_armament_followup",
            "weapon_stat_copy",
            "cursor_direction_targeting",
            "formation_uptime",
        ),
        "scaling_axes": ("weapon_damage", "attack_speed", "positioning", "formation_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Holy_Strike",
    },
    {
        "source_id": "holy_sweep.initial_hit_enemy_selection_for_random_hammers",
        "skill_gates": ("Holy Sweep",),
        "label": "Only struck enemies can receive hammerfalls",
        "description": (
            "Holy Sweep first performs the full-circle melee hit, then only enemies struck by that sweep become "
            "eligible for the random Holy Hammer follow-up impacts. Those hammerfalls cannot be evaded, so real "
            "damage scales with initial sweep coverage and enemy clustering because missed targets never enter "
            "the secondary-hit pool."
        ),
        "mechanic_tags": (
            "initial_hit_gate",
            "random_followup_targeting",
            "secondary_impacts",
            "cannot_be_evaded",
        ),
        "scaling_axes": ("area_of_effect", "enemy_density", "accuracy", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Holy_Sweep",
    },
    {
        "source_id": "ice_crash.three_stage_ring_partition_single_hit_per_use",
        "skill_gates": ("Ice Crash",),
        "label": "Three range bands but one hit per use",
        "description": (
            "Ice Crash resolves as three outward stages, but a target can only be hit by one of those stages "
            "from a single use instead of taking all three hits at once. Real damage therefore scales with AoE "
            "and range band placement to catch targets in the best stage rather than assuming same-target stage "
            "overlap exists."
        ),
        "mechanic_tags": (
            "three_stage_pattern",
            "single_hit_per_use",
            "range_banding",
            "no_stage_overlap",
        ),
        "scaling_axes": ("area_of_effect", "positioning", "enemy_hitbox", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Crash",
    },
    {
        "source_id": "ice_crash_of_cadence.alternating_weapon_roles_single_wave_cycle",
        "skill_gates": ("Ice Crash of Cadence",),
        "label": "Alternating weapon roles on a single-wave cycle",
        "description": (
            "Ice Crash of Cadence replaces the normal three-stage pattern with one wave and alternates weapons "
            "between uses, giving the main-hand slam the damage-biased hit and the off-hand slam the larger "
            "area. Real damage scales with how well your weapon pair matches those alternating roles instead of "
            "treating every swing as the same payload."
        ),
        "mechanic_tags": (
            "single_wave_pattern",
            "alternating_weapon_cycle",
            "main_hand_damage_bias",
            "off_hand_area_bias",
        ),
        "scaling_axes": ("main_hand_damage", "off_hand_area_of_effect", "weapon_pairing", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Crash_of_Cadence",
    },
    {
        "source_id": "ice_trap.sequential_rune_overlap_and_repeat_trigger_scaling",
        "skill_gates": ("Ice Trap",),
        "label": "Sequential runes can overlap on centered targets",
        "description": (
            "Ice Trap creates a sequence of runic explosions with nested radii instead of a single isolated "
            "blast, so centered or larger targets can be clipped by multiple pulses from one trigger. Real "
            "damage scales with trap placement, hitbox size, and repeat-trigger support because the skill's "
            "payoff comes from stacked sequential coverage rather than one explosion."
        ),
        "mechanic_tags": (
            "sequential_rune_explosions",
            "nested_area_overlap",
            "repeat_trigger_scaling",
            "trap_placement_sensitive",
        ),
        "scaling_axes": ("trap_placement", "enemy_hitbox", "area_of_effect", "trigger_twice_chance"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Trap",
    },
    {
        "source_id": "ice_trap_of_hollowness.center_deadzone_and_namelock_miss_risk",
        "skill_gates": ("Ice Trap of Hollowness",),
        "label": "Ring-only blast with a center dead zone",
        "description": (
            "Ice Trap of Hollowness explodes in a ring that does not hit the center, and name-lock throwing can "
            "place that dead zone directly on a target. Real damage therefore scales with off-center placement "
            "and trigger control because the skill can completely miss center-anchored enemies even when the "
            "trap appears to land on top of them."
        ),
        "mechanic_tags": ("ring_explosion", "center_deadzone", "name_lock_miss_risk", "trigger_control"),
        "scaling_axes": ("trap_placement", "enemy_hitbox", "area_of_effect", "trigger_control"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Ice_Trap_of_Hollowness",
    },
    {
        "source_id": "kinetic_bolt.spell_damage_conversion_does_not_stack_with_wand_mastery",
        "skill_gates": ("Kinetic Bolt",),
        "label": "Spell-damage conversion is additive-only",
        "description": (
            "Kinetic Bolt only converts increases and reductions to spell damage into attack damage, so more "
            "or less spell damage does not scale the attack. Its built-in conversion also does not stack with "
            "the matching wand mastery, which makes real scaling hinge on additive spell-damage sources and "
            "zig-zag fork geometry instead of assuming every spell multiplier double-dips."
        ),
        "mechanic_tags": (
            "additive_spell_damage_conversion",
            "no_more_less_spell_damage_scaling",
            "wand_mastery_nonstack",
            "fork_geometry",
        ),
        "scaling_axes": ("increased_spell_damage", "wand_choice", "fork_count", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Bolt",
    },
    {
        "source_id": "kinetic_fusillade.hovering_projectile_cap_and_delayed_auto_release",
        "skill_gates": ("Kinetic Fusillade",),
        "label": "Hover stack cap with delayed auto-release",
        "description": (
            "Kinetic Fusillade stores hovering projectiles around the player up to a hard cap, then releases "
            "the bank after you stop creating more for a short duration. Those projectiles seek nearby targets "
            "and chain on release, or fire in your facing direction if nothing is available, so real damage "
            "depends on managing stack cap, release timing, and target density rather than only raw attack rate."
        ),
        "mechanic_tags": (
            "hovering_projectile_cap",
            "delayed_auto_release",
            "target_seek_release",
            "chain_followup",
        ),
        "scaling_axes": ("projectile_count", "release_timing", "enemy_density", "chain_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Fusillade",
    },
    {
        "source_id": "kinetic_fusillade_of_detonation.hovering_projectile_cap_and_sequential_self_detonation",
        "skill_gates": ("Kinetic Fusillade of Detonation",),
        "label": "Hover stack cap with sequential detonations",
        "description": (
            "Kinetic Fusillade of Detonation still banks hovering projectiles around the player, but the stored "
            "shots explode in sequence after the release delay instead of homing and chaining. Real damage "
            "therefore scales with reaching the hover cap and keeping enemies inside the detonation area for the "
            "full sequential burst rather than with target-seeking projectile travel."
        ),
        "mechanic_tags": (
            "hovering_projectile_cap",
            "delayed_auto_release",
            "sequential_self_detonation",
            "area_burst_window",
        ),
        "scaling_axes": ("projectile_count", "release_timing", "area_of_effect", "enemy_stationary_time"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Fusillade_of_Detonation",
    },
    {
        "source_id": "kinetic_rain.projectile_impacts_spawn_distinct_non_projectile_anomalies",
        "skill_gates": ("Kinetic Rain",),
        "label": "Impact volleys spawn distinct non-projectile anomalies",
        "description": (
            "Each Kinetic Rain projectile impact creates a separate Kinetic Anomaly follow-up at the landing "
            "point, and that anomaly is its own non-projectile damage payload instead of just a delayed copy of "
            "the rain hit. Real scaling therefore splits between the projectile volley and anomaly uptime, with "
            "projectile supports helping the rain while anomaly caps, trigger timing, and proximity behavior "
            "govern how much of the follow-up damage is actually realized."
        ),
        "mechanic_tags": (
            "dual_payload_skill",
            "projectile_impact_spawn",
            "non_projectile_followup",
            "support_profile_split",
            "anomaly_cap",
        ),
        "scaling_axes": ("projectile_count", "support_selection", "enemy_density", "duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Rain",
    },
    {
        "source_id": "kinetic_rain_of_impact.direct_impact_only_no_anomaly_followup",
        "skill_gates": ("Kinetic Rain of Impact",),
        "label": "Direct-impact rain without anomaly follow-up",
        "description": (
            "Kinetic Rain of Impact realizes its payload on the marked projectile impacts rather than on delayed "
            "Kinetic Anomaly follow-ups. Real scaling therefore favors impact coverage, area overlap, and "
            "marker placement because there is no separate anomaly uptime loop to recover misplaced hits."
        ),
        "mechanic_tags": ("direct_impact_only", "telegraphed_marker_pattern", "area_overlap", "no_anomaly_loop"),
        "scaling_axes": ("projectile_count", "area_of_effect", "attack_speed", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Kinetic_Rain_of_Impact",
    },
    {
        "source_id": "leap_slam.fixed_execution_time_and_instant_startup_recovery",
        "skill_gates": ("Leap Slam",),
        "label": "Fixed travel cadence with instant-startup recovery",
        "description": (
            "Leap Slam's execution time is driven by weapon attack time and attack-speed modifiers rather than "
            "by jump distance, so long and short leaps resolve on the same cadence. The skill also regains an "
            "instant startup if you stop chaining it for long enough, while the landing hit still checks "
            "accuracy, making real performance a combined cadence, routing, and hit-confirmation problem."
        ),
        "mechanic_tags": (
            "distance_independent_execution_time",
            "instant_startup_recovery",
            "accuracy_check",
            "travel_skill_cadence",
        ),
        "scaling_axes": ("weapon_base_attack_time", "attack_speed", "accuracy", "movement_pattern"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Leap_Slam",
    },
    {
        "source_id": "leap_slam_of_groundbreaking.short_hop_slam_cadence_and_displacement",
        "skill_gates": ("Leap Slam of Groundbreaking",),
        "label": "Short-hop slam cadence with forced displacement",
        "description": (
            "Leap Slam of Groundbreaking can only travel a short distance, but trades the base gem's added "
            "attack-time travel tax for a heavier local slam with a larger landing radius. In practice it "
            "scales like a close-range repositioning slam that repeatedly knocks enemies out of the landing "
            "spot and front-loads full-life stun setups, rather than like a general long-path traversal tool."
        ),
        "mechanic_tags": (
            "short_travel_cap",
            "slam_cadence_tradeoff",
            "forced_enemy_displacement",
            "full_life_stun_setup",
        ),
        "scaling_axes": ("attack_speed", "area_of_effect", "positioning", "stun_window"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Leap_Slam_of_Groundbreaking",
    },
    {
        "source_id": "lightning_strike_of_arcing.hit_confirmed_chain_projectile_ramp",
        "skill_gates": ("Lightning Strike of Arcing",),
        "label": "Hit-confirmed chain projectile ramp",
        "description": (
            "Lightning Strike of Arcing replaces the normal projectile fan with one projectile that chains "
            "repeatedly and gains more damage for each chain, and that projectile cannot miss if the melee hit "
            "already connected. Real scaling therefore depends on getting the strike hit confirmed and feeding "
            "the chain path through dense packs or secondary targets so the projectile can ramp before reaching "
            "priority enemies."
        ),
        "mechanic_tags": (
            "single_chain_projectile",
            "damage_per_chain_ramp",
            "hit_confirmed_secondary_projectile",
            "pack_pathing",
        ),
        "scaling_axes": ("chain_count", "enemy_density", "melee_hit_uptime", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Lightning_Strike_of_Arcing",
    },
    {
        "source_id": "molten_shell.absorbed_hit_snapshot_and_reflected_explosion_rules",
        "skill_gates": ("Molten Shell",),
        "label": "Absorbed-hit scaling with reflected explosion rules",
        "description": (
            "Molten Shell's payoff depends on how much post-mitigation hit damage the shell absorbs before it "
            "expires, because the detonation damage is derived from that absorbed pool after the armour bonus is "
            "applied. The explosion counts as reflected damage, so it cannot crit, penetrate, inflict ailments, "
            "or benefit from ordinary hit-scaling tricks, which pushes optimization toward armour and damage-taken "
            "routing rather than generic spell damage scaling."
        ),
        "mechanic_tags": (
            "absorbed_hit_snapshot",
            "post_mitigation_buffer",
            "reflected_explosion",
            "no_standard_hit_scaling",
        ),
        "scaling_axes": ("armour", "buff_uptime", "incoming_hit_size", "guard_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Molten_Shell",
    },
    {
        "source_id": "molten_strike_of_the_zenith.fifth_attack_projectile_spike_and_multi_target_split",
        "skill_gates": ("Molten Strike of the Zenith",),
        "label": "Every-fifth-strike projectile spike",
        "description": (
            "Molten Strike of the Zenith stores a repeating five-attack cycle where every fifth swing launches "
            "extra molten projectiles with a much larger damage multiplier. Those projectiles are divided among "
            "the enemies hit by the strike, so real damage scales with preserving the fifth-hit burst for the "
            "right target state instead of diluting it into wide melee contact."
        ),
        "mechanic_tags": (
            "repeating_attack_cycle",
            "fifth_attack_burst",
            "projectile_split_across_targets",
            "burst_alignment",
        ),
        "scaling_axes": ("attack_cycle_length", "projectile_count", "target_isolation", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Molten_Strike_of_the_Zenith",
    },
    {
        "source_id": "orb_of_storms_of_squalls.relocating_orb_trigger_loop_and_strike_budget",
        "skill_gates": ("Orb of Storms of Squalls",),
        "label": "Relocating orb with a limited strike budget",
        "description": (
            "Orb of Storms of Squalls teleports to a struck enemy whenever it fires, can retrigger from your "
            "Lightning skills inside its radius, and has no non-channel trigger cooldown between those checks. "
            "That makes its damage a routing problem between trigger frequency, relocation path, split coverage, "
            "and the orb's limited total strike count before it dissipates."
        ),
        "mechanic_tags": (
            "orb_relocation",
            "lightning_skill_retrigger",
            "split_beam_coverage",
            "limited_strike_budget",
        ),
        "scaling_axes": ("cast_speed", "lightning_skill_frequency", "enemy_density", "orb_lifespan"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Orb_of_Storms_of_Squalls",
    },
    {
        "source_id": "plague_bearer.expected_poison_storage_and_toggle_uptime",
        "skill_gates": ("Plague Bearer",),
        "label": "Expected-poison storage with toggle uptime",
        "description": (
            "Plague Bearer stores expected poison damage, meaning poison base DPS times duration, rather than the "
            "post-mitigation damage actually suffered by enemies. Its value therefore scales with how efficiently "
            "you can build Plague Value during Incubating and convert it during Infecting, with edge interactions "
            "such as self-reflected poisons from The Golden Rule also charging the storage pool."
        ),
        "mechanic_tags": (
            "expected_poison_storage",
            "incubating_vs_infecting_toggle",
            "storage_conversion_window",
            "self_reflection_synergy",
        ),
        "scaling_axes": ("poison_dps", "poison_duration", "toggle_uptime", "plague_value_generation"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Plague_Bearer",
    },
    {
        "source_id": "poisonous_concoction.projectile_explosion_overlap_and_life_flask_charge_budget",
        "skill_gates": ("Poisonous Concoction",),
        "label": "Explosion overlap gated by life flask charges",
        "description": (
            "Poisonous Concoction can overlap multiple projectile explosions onto one target with enough area and "
            "additional projectile support, which turns volley geometry into real single-target scaling. That "
            "overlap is still bounded by the skill's life-flask charge consumption, so sustained damage depends "
            "on both overlap setup and flask charge economy rather than on projectile count alone."
        ),
        "mechanic_tags": (
            "projectile_explosion_overlap",
            "additional_projectile_shotgun",
            "life_flask_charge_spend",
            "sustain_budget",
        ),
        "scaling_axes": ("projectile_count", "area_of_effect", "flask_charge_recovery", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Poisonous_Concoction",
    },
    {
        "source_id": "pyroclast_mine.initial_blast_plus_mortar_overlap_with_nonstacking_exposure",
        "skill_gates": ("Pyroclast Mine",),
        "label": "Initial blast plus mortar overlap",
        "description": (
            "A single Pyroclast Mine detonation can damage the same enemy with the mine's initial blast and with "
            "multiple falling mortar explosions, while consecutive detonations add more projectiles to later mines "
            "in the sequence. The nearby Fire Exposure aura does not stack between mines, so real scaling comes "
            "from overlap and detonation ordering rather than from carpeting the target with redundant exposure."
        ),
        "mechanic_tags": (
            "initial_blast_overlap",
            "mortar_multi_hit",
            "consecutive_detonation_projectiles",
            "nonstacking_exposure_aura",
        ),
        "scaling_axes": ("detonation_sequence_length", "projectile_count", "area_overlap", "mine_placement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Pyroclast_Mine",
    },
    {
        "source_id": "pyroclast_mine_of_sabotage.stronger_nonstacking_exposure_over_lower_hit_damage",
        "skill_gates": ("Pyroclast Mine of Sabotage",),
        "label": "Stronger exposure aura with lower hit damage",
        "description": (
            "Pyroclast Mine of Sabotage keeps the normal mine pattern of an initial detonation followed by mortar "
            "projectiles, but shifts its payoff away from raw hit damage and toward a stronger Fire Exposure aura. "
            "Because that aura still does not stack between mines, real scaling comes from keeping one sabotage "
            "mine covering the target while using placement and sequencing to preserve mortar overlap instead of "
            "spamming redundant exposure sources."
        ),
        "mechanic_tags": (
            "stronger_nonstacking_exposure",
            "initial_blast_plus_mortar_pattern",
            "overlap_preservation",
            "reservation_tradeoff",
        ),
        "scaling_axes": ("exposure_uptime", "detonation_sequence_length", "area_overlap", "mine_placement"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Pyroclast_Mine_of_Sabotage",
    },
    {
        "source_id": "rage_vortex.rage_spend_weapon_lock_and_enemy_contact_stall",
        "skill_gates": ("Rage Vortex",),
        "label": "Rage-spend storm with per-use weapon lock",
        "description": (
            "Rage Vortex spends rage up front to create one ragestorm whose damage and radius scale with the rage "
            "sacrificed, and whose hit frequency scales with your attack speed. While dual wielding, each use "
            "alternates weapons, but an ongoing ragestorm stays locked to the weapon that created it, so real "
            "damage depends on hand parity and on keeping enemies inside the storm long enough to slow its travel."
        ),
        "mechanic_tags": (
            "rage_spend_snapshot",
            "per_use_weapon_lock",
            "attack_speed_tick_rate",
            "enemy_contact_stall",
        ),
        "scaling_axes": ("rage_pool", "attack_speed", "main_hand_off_hand_parity", "positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Rage_Vortex",
    },
    {
        "source_id": "rage_vortex_of_berserking.following_storm_with_accelerating_rage_upkeep",
        "skill_gates": ("Rage Vortex of Berserking",),
        "label": "Following storm with accelerating rage upkeep",
        "description": (
            "Rage Vortex of Berserking trades the base gem's up-front rage spend for a ragestorm that follows you "
            "and drains rage faster and faster while it remains active. That makes the skill scale around rage "
            "generation, proximity uptime, and routing through packs to keep the attached storm dealing damage, "
            "rather than around one-time burst spending."
        ),
        "mechanic_tags": (
            "following_ragestorm",
            "accelerating_rage_drain",
            "sustain_uptime",
            "attached_aoe_pathing",
        ),
        "scaling_axes": ("rage_generation", "attack_speed", "enemy_proximity_uptime", "movement_pattern"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Rage_Vortex_of_Berserking",
    },
    {
        "source_id": "righteous_fire.self_burn_sustain_and_nonstacking_aura_rules",
        "skill_gates": ("Righteous Fire",),
        "label": "Self-burn sustain with nonstacking aura damage",
        "description": (
            "Righteous Fire's real ceiling is set by whether you can sustain its self-burn through fire "
            "resistance, regeneration, and damage-taken modifiers, because the buff does not let spell damage "
            "scale Righteous Fire's own burn. Multiple Righteous Fire auras also do not stack on enemies, so the "
            "highest-damage source wins and optimization shifts toward sustain and aura uptime rather than piling "
            "up duplicate sources."
        ),
        "mechanic_tags": (
            "self_burn_sustain",
            "nonstacking_enemy_aura",
            "spell_buff_not_self_scaling",
            "damage_taken_modifiers",
        ),
        "scaling_axes": ("fire_resistance", "life_regeneration", "damage_taken_modifiers", "area_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Righteous_Fire",
    },
    {
        "source_id": "righteous_fire_of_arcane_devotion.mana_fueled_dot_with_spell_damage_scaling",
        "skill_gates": ("Righteous Fire of Arcane Devotion",),
        "label": "Mana-fueled RF with spell-damage scaling",
        "description": (
            "Righteous Fire of Arcane Devotion rewrites the normal Righteous Fire loop by basing its burn on "
            "maximum mana, letting spell damage modifiers scale the damage over time, and replacing the old spell "
            "damage buff with cast speed. Because the effect still burns you down until 1 life remains, its real "
            "damage profile is a mana-pool and sustain problem rather than a straight copy of life-based RF."
        ),
        "mechanic_tags": (
            "maximum_mana_burn_base",
            "spell_damage_applies_to_dot",
            "cast_speed_buff",
            "one_life_termination",
        ),
        "scaling_axes": ("maximum_mana", "spell_damage", "self_recovery", "uptime_control"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Righteous_Fire_of_Arcane_Devotion",
    },
    {
        "source_id": "scorching_ray.stage_ramp_refresh_and_max_stage_exposure",
        "skill_gates": ("Scorching Ray",),
        "label": "Stage ramp with max-stage exposure",
        "description": (
            "Scorching Ray applies a lingering burning debuff on first contact, refreshes it while enemies stay in "
            "the beam, ramps that debuff up to 8 stages on continued channel ticks, and only applies Fire Exposure "
            "once maximum stages are reached. Different exiles or totems inflict separate Scorching Ray debuffs, "
            "so real scaling comes from maintaining beam contact, cast-speed-driven turn control, and stacking "
            "multiple sources instead of treating it like a single static DoT."
        ),
        "mechanic_tags": (
            "lingering_debuff_refresh",
            "stage_ramp",
            "max_stage_exposure",
            "independent_source_stacking",
        ),
        "scaling_axes": ("cast_speed", "beam_contact_uptime", "multi_source_overlap", "fire_exposure_effect"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Scorching_Ray",
    },
    {
        "source_id": "scorching_ray_of_immolation.independent_stage_debuffs_without_exposure",
        "skill_gates": ("Scorching Ray of Immolation",),
        "label": "Independent stage debuffs without exposure",
        "description": (
            "Scorching Ray of Immolation keeps the same lingering staged debuff behavior, and different exiles or "
            "totems still apply separate debuffs that gain stages independently, but this version drops the base "
            "gem's max-stage Fire Exposure. That shifts scaling toward raw beam DPS, cast-speed-controlled stage "
            "gain, and maintaining multiple independent beams instead of using the skill as an exposure engine."
        ),
        "mechanic_tags": (
            "lingering_debuff_refresh",
            "stage_ramp",
            "independent_source_stacking",
            "no_exposure_tradeoff",
        ),
        "scaling_axes": ("cast_speed", "beam_contact_uptime", "multi_source_overlap", "raw_damage_over_time"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Scorching_Ray_of_Immolation",
    },
    {
        "source_id": "searing_bond.link_network_uptime_and_nonhit_dot_rules",
        "skill_gates": ("Searing Bond",),
        "label": "Link network uptime and non-hit DoT rules",
        "description": (
            "Searing Bond's damage depends on keeping the caster and totems within link range and line of sight so "
            "the beam network stays active; the beams disappear when range or terrain breaks the link and reappear "
            "when the link is restored. Because the bond is pure burning damage over time and never hits, real "
            "scaling comes from network uptime, totem count and placement, and DoT modifiers rather than "
            "penetration or on-hit effects."
        ),
        "mechanic_tags": (
            "beam_network_uptime",
            "line_of_sight_break",
            "nonhit_dot",
            "totem_placement",
        ),
        "scaling_axes": ("totem_count", "placement", "line_of_sight", "damage_over_time"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Searing_Bond",
    },
    {
        "source_id": "searing_bond_of_detonation.power_charge_totem_cap_and_detonation_snapshot",
        "skill_gates": ("Searing Bond of Detonation",),
        "label": "Power-charge totem cap with detonation scaling",
        "description": (
            "Searing Bond of Detonation ties its active totem cap to your maximum Power Charges and detonates all "
            "totems from this skill when that cap is reached, applying the beam's damage over time in an area for "
            "a duration. Because the detonation gains more damage per totem detonated, real scaling comes from "
            "power-charge-supported cap increases, synchronized placement, and clustered releases instead of only "
            "maintaining passive beam uptime."
        ),
        "mechanic_tags": (
            "power_charge_totem_cap",
            "cap_triggered_detonation",
            "per_totem_more_multiplier",
            "clustered_totem_release",
        ),
        "scaling_axes": ("maximum_power_charges", "totem_count", "totem_placement", "detonation_timing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Searing_Bond_of_Detonation",
    },
    {
        "source_id": "shield_of_light.block_gated_ally_wave_echo_and_shield_defence_scaling",
        "skill_gates": ("Shield of Light",),
        "label": "Block-gated ally waves with shield-defence scaling",
        "description": (
            "Shield of Light cannot be used freely; it becomes available after you block and then sends a damaging "
            "wave that can create up to four additional waves from allies around the first enemy struck. Its damage "
            "scales from shield armour and energy shield instead of normal weapon logic, so real scaling depends on "
            "block uptime, shield defences, and ally positioning around the first contact target."
        ),
        "mechanic_tags": (
            "block_gated_use_window",
            "ally_wave_echo",
            "max_four_extra_waves",
            "shield_defence_scaling",
        ),
        "scaling_axes": ("block_uptime", "shield_armour", "shield_energy_shield", "ally_positioning"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shield_of_Light",
    },
    {
        "source_id": "siege_ballista.ballista_origin_distance_scaling_and_totem_subclass_rules",
        "skill_gates": (
            "Siege Ballista",
            "Siege Ballista of Splintering",
            "Siege Ballista of Trarthus",
        ),
        "label": "Ballista-origin scaling with totem subclass rules",
        "description": (
            "Siege Ballista skills are bow attacks executed by ballista totems, so they inherit the ballista "
            "subclass rules of higher totem cap, faster summon speed, and shorter placement range. For distance-based "
            "effects, the game measures from the totem rather than the player, which makes real scaling depend on "
            "totem count, placement, and totem-side positioning instead of only player location."
        ),
        "mechanic_tags": (
            "ballista_subclass_rules",
            "totem_origin_distance_check",
            "higher_totem_cap",
            "totem_side_positioning",
        ),
        "scaling_axes": ("totem_count", "totem_positioning", "summon_speed", "placement_range"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Siege_Ballista",
    },
    {
        "source_id": "siege_ballista_of_splintering.buildup_forking_bolt_and_fork_branching",
        "skill_gates": ("Siege Ballista of Splintering",),
        "label": "Build-up volley with fork branching",
        "description": (
            "Siege Ballista of Splintering trades the base gem's piercing shot for a stronger bolt that has a "
            "noticeable build-up before firing and then forks into secondary branches. Because the transfigured "
            "version also gains extra fork behavior, its practical scaling is shaped by fork branch coverage and "
            "the totem's firing cadence rather than a simple single-line projectile path."
        ),
        "mechanic_tags": (
            "buildup_before_fire",
            "forking_bolt",
            "extra_fork_branching",
            "totem_attack_cycle",
        ),
        "scaling_axes": ("fork_count", "projectile_branching", "totem_attack_speed", "projectile_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Siege_Ballista_of_Splintering",
    },
    {
        "source_id": "siege_ballista_of_trarthus.ring_deployment_single_volley_and_expiry",
        "skill_gates": ("Siege Ballista of Trarthus",),
        "label": "Ring deployment with single-volley expiry",
        "description": (
            "Siege Ballista of Trarthus summons a ring of ballistae at the targeted location, each one fires a "
            "single piercing shot, and then immediately expires. Its real ceiling therefore depends on ring "
            "placement, how many totems can fire into the same pack or boss window, and how often you can repeat "
            "that short-lived volley pattern."
        ),
        "mechanic_tags": (
            "ring_totem_formation",
            "single_volley_totems",
            "expire_after_attack",
            "wide_placement_range",
        ),
        "scaling_axes": ("totem_count", "placement_range", "volley_overlap", "repeat_deployment_rate"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Siege_Ballista_of_Trarthus",
    },
    {
        "source_id": "siphoning_trap.enemy_beam_count_scales_self_regen_and_dot_coverage",
        "skill_gates": ("Siphoning Trap",),
        "label": "Enemy beam count drives regen and DoT coverage",
        "description": (
            "Siphoning Trap tethers beams to the closest enemies, damages those enemies over time, and simultaneously "
            "grants life and mana regeneration based on how many enemies are currently affected. Because spell damage "
            "also scales the damage over time and quality raises the enemy cap, real scaling depends on maintaining "
            "beam coverage over many targets instead of reading it like a fixed single-target trap."
        ),
        "mechanic_tags": (
            "closest_enemy_beam_selection",
            "enemy_count_scaled_regen",
            "beam_target_cap",
            "spell_damage_scales_dot",
        ),
        "scaling_axes": ("enemy_count", "beam_target_cap", "life_regeneration", "mana_regeneration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Siphoning_Trap",
    },
    {
        "source_id": "siphoning_trap_of_pain.cooldownless_high_target_cap_tradeoff",
        "skill_gates": ("Siphoning Trap of Pain",),
        "label": "Cooldownless higher-cap trap with regen tradeoff",
        "description": (
            "Siphoning Trap of Pain drops the base gem's self-regeneration beam effect, but in exchange it loses the "
            "cooldown and can affect more enemies while dealing higher damage over time. That shifts real scaling "
            "toward repeat cast frequency and larger beam coverage windows instead of using the trap as a defensive "
            "regen engine."
        ),
        "mechanic_tags": (
            "no_cooldown_variant",
            "higher_target_cap",
            "regen_removed_tradeoff",
            "repeatable_dot_setup",
        ),
        "scaling_axes": ("enemy_count", "repeat_cast_frequency", "damage_over_time_multiplier", "beam_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Siphoning_Trap_of_Pain",
    },
    {
        "source_id": "smite.additional_strike_double_hit_and_nonshotgunning_bolt_rules",
        "skill_gates": ("Smite",),
        "label": "Additional strikes can double-hit, but bolts do not shotgun",
        "description": (
            "Smite's melee swing and lightning bolt are separate damage regions, with the bolt area not counting as "
            "melee damage. A target normally cannot be hit twice by the same strike sequence, and overlapping bolt "
            "areas from one use do not shotgun the same enemy, but additional strike targeting can still create a "
            "melee hit from one strike and a bolt hit from another on the same target. Real scaling therefore "
            "depends on strike replication and positioning instead of assuming simple AoE overlap."
        ),
        "mechanic_tags": (
            "separate_melee_and_bolt_regions",
            "bolt_aoe_not_melee_damage",
            "nonshotgunning_bolt_overlap",
            "additional_strike_double_hit",
        ),
        "scaling_axes": ("additional_strike_targets", "enemy_positioning", "attack_speed", "aoe_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Smite",
    },
    {
        "source_id": "smite_of_divine_judgement.secondary_area_strike_tradeoff",
        "skill_gates": ("Smite of Divine Judgement",),
        "label": "Strike plus secondary area rewards overlap positioning",
        "description": (
            "Smite of Divine Judgement still plays as a strike with a separate secondary area payload rather than a "
            "single inseparable melee hit. That means real scaling depends on placing enemies where the attack and "
            "the follow-up area both matter, while the transfigured version shifts away from the base gem's broader "
            "aura-centric utility package."
        ),
        "mechanic_tags": (
            "separate_strike_and_area_regions",
            "secondary_area_component",
            "overlap_positioning",
            "aura_utility_tradeoff",
        ),
        "scaling_axes": ("enemy_positioning", "area_coverage", "attack_speed", "hit_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Smite_of_Divine_Judgement",
    },
    {
        "source_id": "snipe.stage_release_timing_and_multilink_trigger_behavior",
        "skill_gates": ("Snipe",),
        "label": "Stage release timing governs fallback and linked-skill output",
        "description": (
            "Snipe stores stages while channeling and, on release, triggers a linked non-channeling bow skill once "
            "per stored stage. If there is no compatible linked bow skill it falls back to firing its own arrow, "
            "while releasing before completing a first real stage produces no shot at all. Community testing also "
            "shows that sufficiently charged releases can trigger multiple linked bow skills together, so scaling is "
            "sensitive to stage timing and link setup instead of only the tooltip's per-stage more damage."
        ),
        "mechanic_tags": (
            "per_stage_trigger_release",
            "minimum_one_stage_to_fire",
            "fallback_self_arrow",
            "multi_link_release_behavior",
        ),
        "scaling_axes": ("stage_count", "attack_speed", "release_timing", "linked_skill_count"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Snipe",
    },
    {
        "source_id": "somatic_shell.chain_shell_propagation_and_first_hit_application_cap",
        "skill_gates": ("Somatic Shell",),
        "label": "Shell chain propagation is capped by first-hit application rules",
        "description": (
            "Somatic Shell places absorb shields on hit targets, redirecting part of incoming hit damage into the "
            "shell until it breaks. A depleted shell explodes and launches a seeking projectile that can apply a new "
            "shell, but each skill use or shell explosion can only apply a shell to the first enemy it hits, the "
            "same target cannot immediately receive a fresh shell again, and the total number of live shells is "
            "capped. That makes pack routing and shell break cadence part of the damage loop."
        ),
        "mechanic_tags": (
            "shell_absorb_pool",
            "explosion_chain_propagation",
            "first_hit_shell_application_cap",
            "same_target_reapply_lockout",
        ),
        "scaling_axes": ("hit_damage_into_shell", "projectile_count", "enemy_pack_density", "chain_pathing"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Somatic_Shell",
    },
    {
        "source_id": "soulrend.homing_pierce_dual_payload_and_travel_uptime",
        "skill_gates": ("Soulrend",),
        "label": "Homing pierce projectile carries both hit and travelling DoT",
        "description": (
            "Soulrend combines two payloads: the projectile hit itself and the chaos damage over time field that "
            "travels with the projectile. Because the projectile homes toward enemies, pierces all targets, and its "
            "damage over time is explicitly scaled by spell damage, real scaling depends on keeping targets inside "
            "the travelling effect rather than valuing it as a plain single-hit projectile."
        ),
        "mechanic_tags": (
            "dual_payload_hit_plus_dot",
            "homing_projectile",
            "pierce_all_targets",
            "spell_damage_scales_dot",
        ),
        "scaling_axes": ("projectile_travel_time", "projectile_speed", "spell_damage", "enemy_proximity_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Soulrend",
    },
    {
        "source_id": "soulrend_of_reaping.pure_hit_projectile_without_dot_or_homing",
        "skill_gates": ("Soulrend of Reaping",),
        "label": "Pure hit projectile drops the DoT, homing, and pierce package",
        "description": (
            "Soulrend of Reaping strips out the base skill's travelling damage over time field, homing behavior, and "
            "inherent full pierce. The transfigured version is therefore a much more direct hit-and-crit projectile "
            "package whose real scaling leans on coverage and hit quality instead of maintaining a travelling DoT "
            "uptime shell."
        ),
        "mechanic_tags": (
            "pure_hit_projectile",
            "no_dot_payload",
            "no_homing",
            "no_inherent_pierce",
        ),
        "scaling_axes": ("crit_scaling", "projectile_speed", "hit_damage", "projectile_coverage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Soulrend_of_Reaping",
    },
    {
        "source_id": "soulrend_of_the_spiral.spiral_multi_projectile_dot_coverage",
        "skill_gates": ("Soulrend of the Spiral",),
        "label": "Spiral multi-projectile layout expands travelling DoT coverage",
        "description": (
            "Soulrend of the Spiral fires five projectiles in a spiral pattern while keeping the skill's homing, full "
            "pierce, and travelling chaos damage over time behavior. That turns its real ceiling into a projectile "
            "patterning and uptime problem, where enemy clustering and projectile travel determine how much of the "
            "spiral can connect instead of treating it like a single-lane Soulrend shot."
        ),
        "mechanic_tags": (
            "spiral_projectile_pattern",
            "multi_projectile_dot_coverage",
            "homing_projectile",
            "pierce_all_targets",
        ),
        "scaling_axes": ("projectile_count", "projectile_speed", "enemy_clustering", "travel_uptime"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Soulrend_of_the_Spiral",
    },
    {
        "source_id": "spellslinger.shared_trigger_cooldown_wand_gate_and_reservation_lock",
        "skill_gates": ("Spellslinger",),
        "label": "Wand trigger gate and shared cooldown cap the whole payload",
        "description": (
            "Spellslinger only triggers supported spells when a non-triggered wand attack fires projectiles, while "
            "the supported package reserves its own locked mana share and is constrained by Spellslinger's cooldown "
            "and cooldown recovery loop. Real scaling therefore depends on attack cadence, cooldown recovery, and "
            "how many supported spells you are trying to feed through that trigger cadence instead of reading the "
            "added wand damage line in isolation."
        ),
        "mechanic_tags": (
            "nontriggered_wand_projectile_requirement",
            "shared_trigger_cooldown",
            "reservation_locked_to_supported_package",
            "cooldown_recovery_scaled_trigger_rate",
        ),
        "scaling_axes": ("attack_speed", "cooldown_recovery_rate", "supported_spell_count", "wand_damage"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Skill%3ASpellslinger",
    },
    {
        "source_id": "split_arrow.distinct_target_fan_scales_clear_not_single_target",
        "skill_gates": ("Split Arrow",),
        "label": "Distinct-target fan pattern scales clear more than single target",
        "description": (
            "Split Arrow naturally fans arrows toward different targets, so its baseline scaling is about how many "
            "enemies each attack can touch rather than same-target shotgunning. Extra arrows and other projectile "
            "multipliers mainly widen that clear footprint, which makes pack density and target availability a large "
            "part of the skill's real ceiling."
        ),
        "mechanic_tags": (
            "distinct_target_fan_pattern",
            "clear_first_projectile_layout",
            "no_baseline_same_target_shotgun",
            "extra_arrow_clear_scaling",
        ),
        "scaling_axes": ("projectile_count", "enemy_density", "projectile_speed", "attack_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Split_Arrow",
    },
    {
        "source_id": "split_arrow_of_splitting.split_branches_expand_coverage_without_same_target_rehits",
        "skill_gates": ("Split Arrow of Splitting",),
        "label": "Split branches widen coverage but do not rehit the same target",
        "description": (
            "Split Arrow of Splitting turns projectile scaling into split coverage, and because it can split from "
            "terrain the practical footprint can become much larger than the initial volley. But split projectiles "
            "are still treated as the same projectile after splitting, so they do not repeatedly hit the same enemy. "
            "Real scaling is therefore about terrain abuse, target count, and branch coverage rather than expecting "
            "the split branches to shotgun a boss."
        ),
        "mechanic_tags": (
            "projectile_split_branching",
            "terrain_split_enable",
            "same_projectile_after_split",
            "no_same_target_rehit",
        ),
        "scaling_axes": ("split_count", "terrain_proximity", "enemy_density", "projectile_speed"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Projectile",
    },
    {
        "source_id": "storm_call_of_trarthus.global_marker_sync_and_boiling_blood_overlap",
        "skill_gates": ("Storm Call of Trarthus",),
        "label": "One marker expiry resolves the whole field and layers blood pools",
        "description": (
            "Storm Call of Trarthus does not resolve each marker in isolation: when one marker expires, bolts also "
            "strike every other marker you have placed. Each impact leaves a Boiling Blood pool behind, so real "
            "scaling depends on how densely you stack markers and how much of the secondary ground effect can "
            "overlap instead of valuing each cast as a standalone delayed hit."
        ),
        "mechanic_tags": (
            "shared_marker_expiry",
            "all_markers_strike_together",
            "boiling_blood_ground_followup",
            "secondary_overlap_scaling",
        ),
        "scaling_axes": ("marker_count", "cast_speed", "area_overlap", "secondary_duration"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Storm_Call_of_Trarthus",
    },
    {
        "source_id": "stormbind.rune_paint_upgrade_and_chain_detonation_loop",
        "skill_gates": ("Stormbind",),
        "label": "Rune painting, upgrade channeling, and chain detonation form one loop",
        "description": (
            "Stormbind is a two-step damage loop: the main skill paints hindering runes, then Rune Blast channels to "
            "improve those runes based on mana spent before releasing to detonate the targeted rune and surrounding "
            "runes in a chain reaction. Real scaling therefore depends on rune placement density, channel time, and "
            "mana-spend throughput instead of only reading the listed per-rune improvement stats."
        ),
        "mechanic_tags": (
            "two_step_rune_loop",
            "channelled_rune_upgrade",
            "chain_detonation",
            "mana_spend_scaled_improvement",
        ),
        "scaling_axes": ("rune_count", "mana_spend", "channel_time", "detonation_overlap"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Stormbind",
    },
    {
        "source_id": "stormbind_of_teleportation.rune_chain_with_teleport_reposition_lockout",
        "skill_gates": ("Stormbind of Teleportation",),
        "label": "Teleport detonation adds a cooldown-routed reposition layer",
        "description": (
            "Stormbind of Teleportation keeps the same rune-paint and Rune Blast chain-reaction package, but the "
            "detonation can also reposition you to the targeted rune and that teleport is gated if you have "
            "detonated runes recently. That adds a placement-and-cooldown routing layer to scaling, because damage "
            "windows and movement value both depend on when you cash out the rune field."
        ),
        "mechanic_tags": (
            "two_step_rune_loop",
            "chain_detonation",
            "conditional_teleport_reposition",
            "recent_detonation_teleport_lockout",
        ),
        "scaling_axes": ("rune_count", "mana_spend", "detonation_timing", "reposition_distance"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Stormbind_of_Teleportation",
    },
    {
        "source_id": "shield_charge.distance_scaled_single_hit_and_shield_stat_damage",
        "skill_gates": ("Shield Charge",),
        "label": "Distance-scaled single hit with shield-stat damage",
        "description": (
            "Shield Charge has two execution modes: a moving charge that damages during travel and on arrival, and "
            "a stationary bash against nearby targets. Each enemy can only be hit once per use, the recovery is "
            "governed by the gem's own attack time rather than weapon base speed, and hit damage plus stun scaling "
            "ramp with charge distance while using shield stats instead of normal weapon-hit logic."
        ),
        "mechanic_tags": (
            "travel_vs_stationary_mode",
            "single_hit_per_use",
            "distance_scaled_damage",
            "shield_stat_damage",
        ),
        "scaling_axes": ("travel_distance", "movement_speed", "global_attack_speed", "shield_defences"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shield_Charge",
    },
    {
        "source_id": "shield_crush.two_wave_overlap_and_shield_only_scaling",
        "skill_gates": ("Shield Crush",),
        "label": "Two-wave overlap with shield-only scaling",
        "description": (
            "Shield Crush emits three segmented waves, with enemies able to be hit by two overlapping waves at "
            "once. Because the skill is always treated as an off-hand shield attack, shield value and shield-based "
            "bonuses scale it while weapon-specific attack modifiers do not, so real scaling comes from overlap "
            "positioning and shield defences rather than weapon tech."
        ),
        "mechanic_tags": (
            "two_wave_overlap",
            "always_offhand_shield_attack",
            "shield_only_scaling",
            "overlap_positioning",
        ),
        "scaling_axes": ("area_of_effect", "enemy_distance", "shield_defences", "on_hit_synergies"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shield_Crush",
    },
    {
        "source_id": "shield_crush_of_the_chieftain.armour_only_fire_scaling_and_central_wave_overlap",
        "skill_gates": ("Shield Crush of the Chieftain",),
        "label": "Armour-only fire scaling with central-wave overlap",
        "description": (
            "Shield Crush of the Chieftain keeps the double-wave overlap behavior, but shifts its scaling to fire "
            "damage based only on shield armour and enlarges the central wave instead of growing overall radius "
            "with gem levels. That makes its real ceiling depend on armour-heavy shields and positioning targets "
            "where the enlarged middle wave overlaps a side wave."
        ),
        "mechanic_tags": (
            "two_wave_overlap",
            "armour_only_shield_scaling",
            "enlarged_central_wave",
            "fire_conversion_tradeoff",
        ),
        "scaling_axes": ("shield_armour", "central_wave_area", "enemy_distance", "area_overlap"),
        "evidence_basis": "community_mechanics_note",
        "evidence_url": "https://www.poewiki.net/wiki/Shield_Crush_of_the_Chieftain",
    },
)


def _normalized_description(record: Mapping[str, Any]) -> str:
    tooltip_text = record.get("tooltip_text")
    if isinstance(tooltip_text, str):
        normalized = " ".join(tooltip_text.split())
        if normalized:
            return normalized
    label = record.get("label")
    if isinstance(label, str) and label:
        return f"Path of Building exposes '{label}' as a skill-specific config surface."
    return "Path of Building exposes a skill-specific config surface for this skill."


@lru_cache(maxsize=1)
def _config_surface_records() -> tuple[dict[str, Any], ...]:
    payload = json.loads(CONFIG_SURFACES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected dict payload in {CONFIG_SURFACES_PATH}")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise RuntimeError(f"Expected list of records in {CONFIG_SURFACES_PATH}")

    records: list[dict[str, Any]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        predicates = raw_record.get("predicates")
        if not isinstance(predicates, dict) or set(predicates) != {"ifSkill"}:
            continue

        if_skill = predicates.get("ifSkill")
        skill_gates: list[str] = []
        if isinstance(if_skill, str) and if_skill:
            skill_gates.append(if_skill)
        elif isinstance(if_skill, list):
            skill_gates.extend(skill_name for skill_name in if_skill if isinstance(skill_name, str) and skill_name)
        if not skill_gates:
            continue

        source_id = raw_record.get("var")
        if not isinstance(source_id, str) or not source_id:
            continue

        label = raw_record.get("label")
        section = raw_record.get("section")
        input_type = raw_record.get("type")
        records.append(
            {
                "source_id": source_id,
                "label": label if isinstance(label, str) and label else source_id,
                "description": _normalized_description(raw_record),
                "section": section if isinstance(section, str) else "",
                "input_type": input_type if isinstance(input_type, str) else "",
                "include_transfigured": bool(raw_record.get("include_transfigured")),
                "skill_gates": tuple(skill_gates),
            }
        )

    return tuple(records)


def _match_skill_gate(skill_name: str, skill_gate: str, *, include_transfigured: bool) -> str | None:
    if skill_name == skill_gate:
        return "exact_name"
    if include_transfigured and skill_name.startswith(f"{skill_gate} of "):
        return "transfigured_name"
    return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _raw_record_label(raw_record: Mapping[str, Any]) -> str:
    record_id = raw_record.get("record_id")
    if isinstance(record_id, str) and record_id:
        return record_id
    skill_id = raw_record.get("skill_id")
    variant_id = raw_record.get("variant_id")
    if isinstance(skill_id, str) and skill_id:
        if isinstance(variant_id, str) and variant_id and variant_id != skill_id:
            return f"{skill_id}:{variant_id}"
        return skill_id
    if isinstance(variant_id, str) and variant_id:
        return variant_id
    return "unknown_raw_record"


def _is_described_scaling_stat(stat_id: str) -> bool:
    if stat_id in _DESCRIBED_SCALING_STAT_IDS:
        return True
    if stat_id.startswith("corrosive_shroud_"):
        return True
    if "_per_" not in stat_id:
        return False
    if any(token in stat_id for token in ("damage", "radius", "cost")):
        return True
    if (
        any(token in stat_id for token in _DESCRIBED_SCALING_OUTPUT_TOKENS)
        and any(token in stat_id for token in _DESCRIBED_SCALING_CONTEXT_TOKENS)
    ):
        return True
    return False


def _described_scaling_facts(skill_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    fact_buckets: dict[str, dict[str, Any]] = {}

    for raw_record in related_raw_active_skill_records(skill_row):
        raw_record_label = _raw_record_label(raw_record)
        for stat_id in raw_active_skill_stat_ids(raw_record):
            if not _is_described_scaling_stat(stat_id):
                continue

            bucket = fact_buckets.setdefault(
                stat_id,
                {
                    "fact_id": f"described_scaling:{stat_id}",
                    "fact_kind": "described_scaling",
                    "source_id": stat_id,
                    "label": stat_id,
                    "description": "Raw skill stat encodes explicit on-gem scaling or a built-in damage interaction.",
                    "matched_sources": [],
                    "matched_raw_records": [],
                    "sampled_values": {},
                },
            )

            for matched_source in raw_active_skill_stat_sources(raw_record, stat_id):
                if matched_source not in bucket["matched_sources"]:
                    bucket["matched_sources"].append(matched_source)

            if raw_record_label not in bucket["matched_raw_records"]:
                bucket["matched_raw_records"].append(raw_record_label)

            sampled_values = raw_active_skill_sampled_values(raw_record, stat_id)
            if sampled_values and not bucket["sampled_values"]:
                bucket["sampled_values"] = sampled_values

    return list(fact_buckets.values())


def _normalize_interaction_taxonomy_slug(raw_value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", raw_value.strip().lower()).strip("_")
    return slug or "unknown"


def _interaction_taxonomy_label(raw_value: str) -> str:
    label_parts: list[str] = []
    for token in raw_value.replace("-", "_").split("_"):
        if not token:
            continue
        if token in _INTERACTION_TAXONOMY_UPPERCASE_TOKENS:
            label_parts.append(token.upper())
            continue
        if token.isdigit():
            label_parts.append(token)
            continue
        label_parts.append(token.capitalize())
    return " ".join(label_parts) or raw_value


def _build_interaction_taxonomy_entries(
    usage_counts: Mapping[str, int],
    *,
    taxonomy_prefix: str,
    entry_id_key: str,
) -> tuple[tuple[dict[str, Any], ...], dict[str, str]]:
    entries: list[dict[str, Any]] = []
    raw_value_to_id: dict[str, str] = {}
    used_slugs: set[str] = set()

    for sort_order, raw_value in enumerate(sorted(usage_counts), start=1):
        base_slug = _normalize_interaction_taxonomy_slug(raw_value)
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        used_slugs.add(slug)

        taxonomy_id = f"{taxonomy_prefix}:{slug}"
        raw_value_to_id[raw_value] = taxonomy_id
        entries.append(
            {
                entry_id_key: taxonomy_id,
                "slug": slug,
                "label": _interaction_taxonomy_label(raw_value),
                "raw_value": raw_value,
                "usage_count": usage_counts[raw_value],
                "sort_order": sort_order,
            }
        )

    return tuple(entries), raw_value_to_id


@lru_cache(maxsize=1)
def _interaction_taxonomy_state() -> dict[str, Any]:
    mechanic_tag_usage_counts: dict[str, int] = {}
    scaling_axis_usage_counts: dict[str, int] = {}

    for record in _INTERACTION_FACT_RECORDS:
        for raw_value in record["mechanic_tags"]:
            mechanic_tag_usage_counts[raw_value] = mechanic_tag_usage_counts.get(raw_value, 0) + 1
        for raw_value in record["scaling_axes"]:
            scaling_axis_usage_counts[raw_value] = scaling_axis_usage_counts.get(raw_value, 0) + 1

    mechanic_tag_catalog, mechanic_tag_ids = _build_interaction_taxonomy_entries(
        mechanic_tag_usage_counts,
        taxonomy_prefix="mechanic_tag",
        entry_id_key="mechanic_tag_id",
    )
    scaling_axis_catalog, scaling_axis_ids = _build_interaction_taxonomy_entries(
        scaling_axis_usage_counts,
        taxonomy_prefix="scaling_axis",
        entry_id_key="scaling_axis_id",
    )
    return {
        "catalog": {
            "mechanic_tags": mechanic_tag_catalog,
            "scaling_axes": scaling_axis_catalog,
        },
        "mechanic_tag_ids": mechanic_tag_ids,
        "scaling_axis_ids": scaling_axis_ids,
    }


def build_interaction_taxonomy_catalog() -> dict[str, list[dict[str, Any]]]:
    taxonomy_catalog = _interaction_taxonomy_state()["catalog"]
    return {
        "mechanic_tags": [dict(entry) for entry in taxonomy_catalog["mechanic_tags"]],
        "scaling_axes": [dict(entry) for entry in taxonomy_catalog["scaling_axes"]],
    }


def _interaction_activation_refs(record: Mapping[str, Any]) -> list[dict[str, str]]:
    activation_refs: list[dict[str, str]] = []
    for family_id in record.get("activation_mechanic_family_ids", ()):
        if isinstance(family_id, str) and family_id:
            activation_refs.append({"catalog_key": "families", "catalog_id": family_id})
    for package_id in record.get("activation_package_ids", ()):
        if isinstance(package_id, str) and package_id:
            activation_refs.append({"catalog_key": "packages", "catalog_id": package_id})
    return activation_refs


def _interaction_facts(skill_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    skill_name = skill_row.get("name")
    if not isinstance(skill_name, str) or not skill_name:
        return []
    skill_id = skill_row.get("skill_id")
    interaction_taxonomy_state = _interaction_taxonomy_state()
    mechanic_tag_ids: Mapping[str, str] = interaction_taxonomy_state["mechanic_tag_ids"]
    scaling_axis_ids: Mapping[str, str] = interaction_taxonomy_state["scaling_axis_ids"]

    facts: list[dict[str, Any]] = []
    for record in _INTERACTION_FACT_RECORDS:
        included_skill_ids = record.get("include_skill_ids", ())
        if included_skill_ids:
            if not isinstance(skill_id, str) or not skill_id or skill_id not in included_skill_ids:
                continue
        excluded_skill_ids = record.get("exclude_skill_ids", ())
        if isinstance(skill_id, str) and skill_id and skill_id in excluded_skill_ids:
            continue
        matched_skill_gate = None
        match_basis = None
        for skill_gate in record["skill_gates"]:
            match_basis = _match_skill_gate(
                skill_name,
                skill_gate,
                include_transfigured=bool(record.get("include_transfigured")),
            )
            if match_basis is None:
                continue
            matched_skill_gate = skill_gate
            break
        if matched_skill_gate is None or match_basis is None:
            continue

        mechanic_tags = list(record["mechanic_tags"])
        scaling_axes = list(record["scaling_axes"])
        fact_payload = {
            "fact_id": f"interaction:{record['source_id']}",
            "fact_kind": "interaction_mechanic",
            "source_id": record["source_id"],
            "label": record["label"],
            "description": record["description"],
            "mechanic_tags": mechanic_tags,
            "mechanic_tag_ids": [mechanic_tag_ids[raw_value] for raw_value in mechanic_tags],
            "scaling_axes": scaling_axes,
            "scaling_axis_ids": [scaling_axis_ids[raw_value] for raw_value in scaling_axes],
            "evidence_basis": record["evidence_basis"],
            "evidence_url": record["evidence_url"],
            "match_basis": match_basis,
            "matched_skill_gate": matched_skill_gate,
        }
        activation_refs = _interaction_activation_refs(record)
        if activation_refs:
            fact_payload["activation_refs"] = activation_refs
        activation_mechanic_family_ids = record.get("activation_mechanic_family_ids")
        if activation_mechanic_family_ids:
            fact_payload["activation_mechanic_family_ids"] = list(activation_mechanic_family_ids)
        activation_package_ids = record.get("activation_package_ids")
        if activation_package_ids:
            fact_payload["activation_package_ids"] = list(activation_package_ids)

        facts.append(fact_payload)

    return facts


def build_interaction_mechanic_facts(skill_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _interaction_facts(skill_row)


def _config_surface_facts(skill_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    skill_name = skill_row.get("name")
    if not isinstance(skill_name, str) or not skill_name:
        return []

    facts: list[dict[str, Any]] = []
    for record in _config_surface_records():
        matched_skill_gate = None
        match_basis = None
        for skill_gate in record["skill_gates"]:
            match_basis = _match_skill_gate(
                skill_name,
                skill_gate,
                include_transfigured=bool(record["include_transfigured"]),
            )
            if match_basis is None:
                continue
            matched_skill_gate = skill_gate
            break
        if matched_skill_gate is None or match_basis is None:
            continue

        facts.append(
            {
                "fact_id": f"config_surface:{record['source_id']}",
                "fact_kind": "config_surface",
                "source_id": record["source_id"],
                "label": record["label"],
                "description": record["description"],
                "section": record["section"],
                "input_type": record["input_type"],
                "include_transfigured": record["include_transfigured"],
                "match_basis": match_basis,
                "matched_skill_gate": matched_skill_gate,
            }
        )

    return facts


def _package_overlay_facts(
    route_payloads: Sequence[Mapping[str, Any]],
    package_catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    package_buckets: dict[str, dict[str, Any]] = {}
    for route_payload in route_payloads:
        route_id = route_payload.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            continue
        applied_packages = route_payload.get("applied_packages")
        if not isinstance(applied_packages, list):
            continue
        for package_payload in applied_packages:
            if not isinstance(package_payload, dict):
                continue
            package_id = package_payload.get("package_id")
            if not isinstance(package_id, str) or not package_id:
                continue
            bucket = package_buckets.setdefault(
                package_id,
                {
                    "matched_route_ids": [],
                    "target_vector_ids": [],
                    "notes": [],
                },
            )
            _append_unique(bucket["matched_route_ids"], route_id)

            target_vector_id = package_payload.get("target_vector_id")
            if isinstance(target_vector_id, str) and target_vector_id:
                _append_unique(bucket["target_vector_ids"], target_vector_id)

            note = package_payload.get("note")
            if isinstance(note, str) and note:
                _append_unique(bucket["notes"], note)

    facts: list[dict[str, Any]] = []
    for package_id in sorted(package_buckets):
        metadata = package_catalog_by_id.get(package_id, {})
        label = metadata.get("label")
        description = metadata.get("description")
        mechanic_family_id = metadata.get("mechanic_family_id")
        bucket = package_buckets[package_id]
        facts.append(
            {
                "fact_id": f"package_overlay:{package_id}",
                "fact_kind": "package_overlay",
                "source_id": package_id,
                "label": label if isinstance(label, str) and label else package_id,
                "mechanic_family_id": mechanic_family_id if isinstance(mechanic_family_id, str) and mechanic_family_id else None,
                "description": (
                    description
                    if isinstance(description, str) and description
                    else "Route-aware package overlay applied for this skill."
                ),
                "matched_route_ids": list(bucket["matched_route_ids"]),
                "target_vector_ids": list(bucket["target_vector_ids"]),
                "notes": list(bucket["notes"]),
            }
        )
    return facts


def build_skill_scaling_facts(
    skill_row: Mapping[str, Any],
    route_payloads: Sequence[Mapping[str, Any]],
    package_catalog_by_id: Mapping[str, Mapping[str, Any]],
    interaction_facts: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    facts = _described_scaling_facts(skill_row)
    resolved_interaction_facts = interaction_facts if interaction_facts is not None else _interaction_facts(skill_row)
    facts.extend(dict(fact) for fact in resolved_interaction_facts)
    facts.extend(_config_surface_facts(skill_row))
    facts.extend(_package_overlay_facts(route_payloads, package_catalog_by_id))
    return sorted(facts, key=lambda fact: (str(fact["fact_kind"]), str(fact["source_id"])))


def build_scaling_fact_summary(skill_payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    skills_with_facts = 0
    total_fact_count = 0
    kind_counts: dict[str, int] = {}
    source_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    skill_kind_buckets: dict[str, dict[str, Any]] = {}
    coverage_order = {
        "described_and_interaction": 0,
        "described_only": 1,
        "interaction_only": 2,
        "other_fact_only": 3,
        "no_facts": 4,
    }
    coverage_buckets: dict[str, dict[str, Any]] = {
        "described_and_interaction": {
            "coverage_id": "described_and_interaction",
            "label": "Described + interaction",
            "skill_count": 0,
            "example_skills": [],
        },
        "described_only": {
            "coverage_id": "described_only",
            "label": "Described only",
            "skill_count": 0,
            "example_skills": [],
        },
        "interaction_only": {
            "coverage_id": "interaction_only",
            "label": "Interaction only",
            "skill_count": 0,
            "example_skills": [],
        },
        "other_fact_only": {
            "coverage_id": "other_fact_only",
            "label": "Config/package only",
            "skill_count": 0,
            "example_skills": [],
        },
        "no_facts": {
            "coverage_id": "no_facts",
            "label": "No facts",
            "skill_count": 0,
            "example_skills": [],
        },
    }
    missing_interaction_skills: list[dict[str, Any]] = []

    for skill_payload in skill_payloads:
        display_name = skill_payload.get("display_name")
        skill_id = skill_payload.get("skill_id")
        facts = skill_payload.get("scaling_facts")
        if not isinstance(display_name, str) or not isinstance(facts, list):
            continue
        skill_key = skill_id if isinstance(skill_id, str) and skill_id else display_name
        if facts:
            skills_with_facts += 1
        total_fact_count += len(facts)
        skill_fact_kinds: set[str] = set()

        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fact_kind = fact.get("fact_kind")
            source_id = fact.get("source_id")
            label = fact.get("label")
            if not isinstance(fact_kind, str) or not isinstance(source_id, str):
                continue
            skill_fact_kinds.add(fact_kind)
            kind_counts[fact_kind] = kind_counts.get(fact_kind, 0) + 1

            bucket = source_buckets.setdefault(
                (fact_kind, source_id),
                {
                    "fact_kind": fact_kind,
                    "source_id": source_id,
                    "label": label if isinstance(label, str) and label else source_id,
                    "fact_count": 0,
                    "skill_names": set(),
                    "example_skills": [],
                },
            )
            bucket["fact_count"] += 1
            if display_name in bucket["skill_names"]:
                continue
            bucket["skill_names"].add(display_name)
            if len(bucket["example_skills"]) < MAX_SOURCE_EXAMPLES:
                bucket["example_skills"].append(display_name)

        for fact_kind in sorted(skill_fact_kinds):
            bucket = skill_kind_buckets.setdefault(
                fact_kind,
                {
                    "fact_kind": fact_kind,
                    "skill_keys": set(),
                    "example_skills": [],
                },
            )
            if skill_key in bucket["skill_keys"]:
                continue
            bucket["skill_keys"].add(skill_key)
            if len(bucket["example_skills"]) < MAX_SOURCE_EXAMPLES:
                bucket["example_skills"].append(display_name)

        if not skill_fact_kinds:
            coverage_bucket = coverage_buckets["no_facts"]
        elif "described_scaling" in skill_fact_kinds and "interaction_mechanic" in skill_fact_kinds:
            coverage_bucket = coverage_buckets["described_and_interaction"]
        elif "described_scaling" in skill_fact_kinds:
            coverage_bucket = coverage_buckets["described_only"]
        elif "interaction_mechanic" in skill_fact_kinds:
            coverage_bucket = coverage_buckets["interaction_only"]
        else:
            coverage_bucket = coverage_buckets["other_fact_only"]
        coverage_bucket["skill_count"] += 1
        if len(coverage_bucket["example_skills"]) < MAX_SOURCE_EXAMPLES:
            coverage_bucket["example_skills"].append(display_name)
        if "interaction_mechanic" not in skill_fact_kinds:
            missing_interaction_skills.append(
                {
                    "skill_id": skill_id if isinstance(skill_id, str) else "",
                    "display_name": display_name,
                    "coverage_id": coverage_bucket["coverage_id"],
                    "fact_kinds": sorted(skill_fact_kinds),
                }
            )

    source_counts = [
        {
            "fact_kind": bucket["fact_kind"],
            "source_id": bucket["source_id"],
            "label": bucket["label"],
            "fact_count": bucket["fact_count"],
            "skill_count": len(bucket["skill_names"]),
            "example_skills": list(bucket["example_skills"]),
        }
        for bucket in source_buckets.values()
    ]
    source_counts.sort(key=lambda row: (row["fact_kind"], -int(row["skill_count"]), row["source_id"]))

    skill_kind_coverage = [
        {
            "fact_kind": bucket["fact_kind"],
            "skill_count": len(bucket["skill_keys"]),
            "example_skills": list(bucket["example_skills"]),
        }
        for bucket in skill_kind_buckets.values()
    ]
    skill_kind_coverage.sort(key=lambda row: (row["fact_kind"], -int(row["skill_count"])))

    skills_with_interaction = len(skill_kind_buckets.get("interaction_mechanic", {}).get("skill_keys", set()))
    skills_with_described = len(skill_kind_buckets.get("described_scaling", {}).get("skill_keys", set()))
    ordered_coverage_buckets = [
        coverage_buckets["described_and_interaction"],
        coverage_buckets["described_only"],
        coverage_buckets["interaction_only"],
        coverage_buckets["other_fact_only"],
        coverage_buckets["no_facts"],
    ]
    missing_interaction_skills.sort(
        key=lambda row: (
            coverage_order.get(str(row["coverage_id"]), len(coverage_order)),
            str(row["display_name"]),
            str(row["skill_id"]),
        )
    )

    return {
        "skills_with_facts": skills_with_facts,
        "skills_without_facts": len(skill_payloads) - skills_with_facts,
        "total_fact_count": total_fact_count,
        "kind_counts": [
            {
                "fact_kind": fact_kind,
                "fact_count": fact_count,
            }
            for fact_kind, fact_count in sorted(kind_counts.items())
        ],
        "skill_kind_coverage": skill_kind_coverage,
        "interaction_coverage": {
            "skills_with_described_scaling": skills_with_described,
            "skills_with_interaction_mechanic": skills_with_interaction,
            "skills_without_interaction_mechanic": len(skill_payloads) - skills_with_interaction,
            "missing_interaction_skills": missing_interaction_skills,
            "coverage_buckets": [
                {
                    "coverage_id": bucket["coverage_id"],
                    "label": bucket["label"],
                    "skill_count": bucket["skill_count"],
                    "example_skills": list(bucket["example_skills"]),
                }
                for bucket in ordered_coverage_buckets
            ],
        },
        "source_counts": source_counts,
    }
