# Skill Standardization

This document describes the reboot MVP skill data pipeline, the standardized schema, and the generated reports that sit on top of it.

## Pipeline

The skill pipeline in `reboot_mvp` is intentionally layered:

1. `skill_numeric_table.py` extracts raw skill gem data from the PoB-backed source tables.
2. `skill_standardized_table.py` turns those raw rows into a consistent numeric skill schema.
3. `skill_metric_report.py` builds reference JSON and Markdown reports over the standardized summary.
4. `skill_mechanics_ontology.py` classifies active skills into a first-pass mechanic ontology and persists the result to SQLite plus JSON and Markdown reports.

Each stage writes artifacts into `data/skill_numeric_db/` so the outputs are inspectable without stepping through the code.

## Raw numeric outputs

`skill_numeric_table.py` writes the first normalized layer from the PoB skill source. These rows preserve the source-oriented fields and level snapshots needed for later transforms.

The raw output is still close to the upstream skill table structure. It is useful for auditability, but not yet ideal for comparing skills against each other.

## Standardized outputs

`skill_standardized_table.py` produces the main comparison layer. The current summary schema version is `1.2.0`.

The standardized outputs are:

- `skill_standardized_summary.json`
- `skill_standardized_summary.csv`
- `skill_standardized_levels.json`
- `skill_standardized_levels.csv`
- `skill_standardized_column_catalog.json`

These outputs flatten the raw source into shared numeric columns so spells, attacks, damage-over-time skills, utility skills, and proxy skills can be compared on a common surface.

## Core formulas

The standardized layer exposes a small set of direct formulas that other reports depend on.

### Timing

- `raw_action_time_seconds = castTime if present else attackTime`
- `uses_per_second_from_skill_time = 1 / raw_action_time_seconds`

This is only the skill-time rate from the source table. It is not a final in-game action rate model and does not include build-specific speed scaling.

### Mana pacing

- `mana_per_second = mana_cost * uses_per_second_from_skill_time`

This is a simple pacing signal for resource pressure at baseline skill timing.

### Added damage delivery

- `added_damage_delivery_coef = damage_effectiveness * uses_per_second_from_skill_time`

This is a numeric delivery coefficient for flat added damage, not a final ranking across mechanics.

### Base multiplier delivery

- `base_multiplier_delivery_coef = base_multiplier * uses_per_second_from_skill_time`

This is the same idea applied to the base damage multiplier surface.

## Payload and growth fields

The standardized schema keeps the direct payload and progression fields that matter most for first-pass comparison:

- `damage_effectiveness`
- `base_multiplier`
- `crit_chance`
- `crit_effect`
- `base_ultimatum_*` style snapshot values when present
- projectile, area, duration, cooldown, reservation, and cost fields

The goal is not to model every mechanic in one table. The goal is to expose the stable numeric shell that later layers can reason about.

## Metric reference reports

`skill_metric_report.py` reads `skill_standardized_summary.json` and produces:

- `skill_metric_reference_report.json`
- `skill_metric_reference_report.md`

These reports summarize the main standardized columns, slice distributions, and coverage counts. They are intended as quick reference artifacts for research and schema review.

The metric report also records the source summary schema version so downstream consumers can detect schema drift.

## Mechanics ontology outputs

`skill_mechanics_ontology.py` reads the standardized summary and classifies rows into a first-pass ontology. It currently classifies only rows where `family == "active_gems"`.

It writes:

- `skill_mechanics_ontology.sqlite`
- `skill_mechanics_ontology_report.json`
- `skill_mechanics_ontology_report.md`

The ontology layer separates two ideas:

- primary family assignment
- additive mechanic tags

Current coverage statuses are:

- `numeric_shell`
- `utility_shell`
- `needs_rule`
- `out_of_scope`

`out_of_scope` is used for non-active rows. `needs_rule` means the row is active but none of the current ontology primary rules matched it yet.

## Layer boundaries

The intended architecture is:

- `poe_build_research.pob` provides stable source ingestion and PoB-facing integration
- raw numeric extraction preserves source fidelity
- standardized skill tables expose comparable numeric columns
- metric reports document the numeric surface
- mechanics ontology adds explicit classification without hiding the underlying numbers

That separation is deliberate. Numeric normalization and mechanic interpretation should evolve independently so schema changes and rule changes stay easy to audit.
