# Reboot MVP

`reboot_mvp` is the clean restart layer for the build-architecture work. It keeps the stable Path of Building ingestion boundary in `poe_build_research.pob`, then builds a smaller numeric and rules surface on top of it.

## What lives here

- numeric extraction and normalization for skills, items, and passive data
- reboot-specific rules and reports
- new build logic that should not inherit the older product surface by accident

## What stays in `poe_build_research.pob`

- PoB-derived game data loading
- PoB runtime integration
- existing import and export helpers
- existing low-level tree editing helpers

## Skill data pipeline

The current skill research flow in this directory is:

1. `skill_numeric_table.py`
   Reads PoB skill gem tables and writes raw numeric extracts under `data/skill_numeric_db/`.
2. `skill_standardized_table.py`
   Produces the standardized skill summary and detail tables. The current summary schema version is `1.2.0`.
3. `skill_metric_report.py`
   Builds JSON and Markdown reference reports over the standardized summary.
4. `skill_mechanics_ontology.py`
   Classifies active skill rows into a first-pass mechanics ontology and writes JSON, Markdown, and SQLite outputs.
5. `skill_scaling_report.py`
   Builds route-aware scaling passports plus JSON and Markdown summary reports over the standardized summary and reboot scaling rules.

Generated artifacts for this pipeline live under `data/skill_numeric_db/`.

Current scaling artifacts include:

- `build_scaling_catalog.json`
  Directed build-side requirement -> reward edges over supports, items, passives, masteries, keystones, config toggles, and ascendancy nodes.
- `build_scaling_catalog.md`
  Human-readable snapshot of the build scaling source catalog and its example profile rankings.
- `scaling_pattern_registry.json`
  Clustered pattern registry that groups raw edges into canonical scaling motifs plus their enablers and skill-vector links.
- `scaling_pattern_registry.md`
  Human-readable snapshot of the pattern registry, cluster summary, and example profile pattern rankings.
- `skill_scaling_passports.json`
  Per-skill route passports with vector scores, package overlays, and best-route summaries.
- `skill_scaling_report.json`
  Aggregate route coverage, top route scores, vector toplists, and package application summaries.
- `skill_scaling_report.md`
  Human-readable snapshot of the aggregate scaling report.
- `skill_build_recommendations.json`
  Ranked concrete build sources for selected skill routes, with translation traces and source score breakdowns.
- `skill_build_recommendations.md`
  Human-readable recommendation walkthroughs that show how route metrics map into concrete build surfaces.
- `scaling_atlas.json`
  End-to-end explainability artifact over the catalog, pattern registry, skill passports, and ranked source outputs.
- `scaling_atlas.md`
  Human-readable atlas that documents descriptor roles, bridges, source chains, formulas, and skill walkthroughs.
- `scaling_research_audit.json`
  Cross-artifact audit over descriptor translation coverage, registry/catalog alignment, and reference integrity.
- `scaling_research_audit.md`
  Human-readable audit report with status, gaps, and concrete integrity checks.
- `scaling_system_contract.json`
  Unified machine-readable contract for scripts and agents that reuses the atlas, catalog, passports, pattern registry, and recommendation payloads.
- `scaling_system_contract.md`
  Human-readable overview of the identity model, stage contracts, field inventory, and agent roundtrips.

## Design intent

- keep the PoB boundary stable
- make the new logic explicit and inspectable
- prefer generated reference artifacts over hidden transformations
- let mechanics classification layer on top of numeric normalization instead of mixing the two

## Runtime query surface

For scripts and agent-style callers there is now a small runtime layer on top of
the raw recommendation payloads:

```python
from poe_build_research.reboot_mvp import (
    explain_skill_scaling_package,
    explain_skill_scaling_source,
    query_skill_scaling,
)

query = query_skill_scaling(skill_id="Boneshatter", top_n=3)
best_package = explain_skill_scaling_package(query)
best_source = explain_skill_scaling_source(query)
```

The runtime packet is intentionally simple:

- `request`: which skill, route, and `top_n` the caller asked for.
- `route_summary`: the route-level metric snapshot selected from the skill passports.
- `profile_summary`: the translated descriptor model that the build-side matcher uses.
- `translation.applied_rows`: how route metrics became requirement/reward/tradeoff keys.
- `agent.input`: what the agent receives as build-side demand.
- `agent.formula`: the exact package/source scoring formulas and opportunity-cost fields.
- `agent.output`: the best package ids and source ids in the compact agent-facing form.
- `packages`: full package-level explanations with pattern linkage and bundle penalty.
- `sources`: full source-level explanations with matched rewards, missing requirements, and score breakdowns.

The intended flow is:

1. `skill_scaling_passports` picks the strongest route and exposes route metrics.
2. `build_skill_scaling_profile` translates those metrics into descriptor keys.
3. `query_skill_scaling` returns the final agent packet.
4. `explain_skill_scaling_package` and `explain_skill_scaling_source` let downstream scripts inspect why the top choice won.
