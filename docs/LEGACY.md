# Legacy inventory

Source: `C:\Coding\Poe Junkroan` (v1, developed with Codex, May-July 2026).
This file records what v2 took, what it left, and why. Nothing in v1 is a
source of truth for v2.

## Taken (into `src/junkroan/pob/`, package renamed from `poe_build_research`)

| v1 module | Why kept |
|---|---|
| `headless_runtime_worker.py`, `headless_runtime_adapter.py`, `headless_wrapper.lua` | The actual PoB driver. Worker constants from `proof_*` modules were inlined; worker `PYTHONPATH` is now set by the adapter. |
| `host_runtime.py`, `release_manager.py`, `artifacts.py` | Session layout, pinned release download and hash verification, path helpers. |
| `calc_snapshot.py`, `import_code_verifier.py` | Stat normalization and native import round-trip. |
| `tree_version_contract.py`, `tree_payload_normalization.py`, `graph_tree_authoring.py`, `tree_authoring_tools.py` | Tree corpus, adjacency, BFS closure, node search. Will be partially replaced by the Phase 1 tree graph helper. Their "blocker" vocabulary is tolerated, not extended. |
| `game_corpus.py`, `tag_corpus.py`, `mod_corpus.py`, `item_mod_lookup.py`, `skill_requirements.py`, `support_legality_readback.py` | Corpus loaders and lookups. |
| `poedb_affix_ingestion.py` + `mod_data/poedb_affix_catalog/` | 84,907 wearable affixes with tiers and weights. HTML snapshots are gitignored (97 MB); `refresh` regenerates. |
| `corpus_data/`, `tag_data/`, `mod_data/*.json` | Parsed game data (549 active gems, 261 supports, 1,062 bases, 2,415 passives, 54 keystones, 351 masteries, 34 ascendancies, 569 config surfaces). |
| `vendor/pob/source/`, `locks/pob.lock.json`, `schemas/pob/` subset | Regeneration inputs and the few schemas the kept tests use. |
| 7 test files | Only those covering kept modules. |

## Kept as read-only reference (`reference/legacy/`)

- `skill_scaling_facts.py`: 353 community mechanics notes. Mining source for
  `mechanics/`. Do not import.
- `rules.py`: v1 mechanic/scaling rule sets. Historical only.
- `direct_build_early_game_rails.py`: source of the default `Rails` numbers
  and ascendancy node id lists.
- `SKILL_STANDARDIZATION.md`, `reboot_mvp_README.md`, `old_SKILL.md`,
  `old_PRODUCT_SPEC.md`: what v1 intended, for context.

## Dropped, and why

| v1 area | Size | Reason |
|---|---|---|
| `direct_build_materializer.py`, `one_shot_direct_build_primitives.py`, `direct_build_repair.py`, `pre_pob_hypothesis_triage.py` | ~12k lines | Publication gates and hypothesis bookkeeping. Add validation surface, not capability. |
| `proof_blank_state.py`, `proof_boots_item.py`, `proof_export_reopen.py` | ~3k | Proof-of-concept ceremony frozen into modules. |
| `action_cost_value_ledger.py`, `generic_pob_action_history.py`, `comparison_protocol.py`, `calc_snapshot_diff.py`, `surface_impact_classification.py`, `pathing_opportunity_cost.py`, `mechanic_coverage.py` | ~5k | Ledgers and classifiers. No optimizer inside. |
| `live_control.py`, `workspace.py`, `evaluate.py` | ~2.6k | GUI launch probe and fixture-driven evaluation; superseded by headless. |
| `reboot_mvp/` (all) | ~33k + 625 MB data | Skill scaling passports, catalogs, pattern registry, atlas, audit, contract, recommendations. Hand-authored interpretations (see DECISIONS D5). Build-side files were 145 lines of never-called import aliases. |
| Six sibling skills (`poe-build-review`, `poe-craft-planner`, ...) | prompts only | Stubs. Their goals reappear in "Later" on the roadmap as optimizer variants. |
| `SKILL.md` (449 lines) + 12 mandatory reference docs | | Procedure-heavy prompt. v2 uses `CLAUDE.md`. |
| `tools/`, `.orchestrator/`, `docs/project/`, `fresh-direct-build-proof/` | | Codex skill packaging and orchestration state. |

## What v1's single end-to-end run showed

`fresh-direct-build-proof/full-run-20260718-130239-c003`: Fireball Inquisitor,
level 90, FullDPS 112,589 against a 200,000 floor, no damage multiplier support
in the link. An earlier "accepted" run had -60 chaos resistance and accuracy
nodes on a spell build. The rails caught bad builds reliably; nothing made
them good. That is the gap v2 closes with the optimizer.
