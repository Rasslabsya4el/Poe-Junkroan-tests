# optimizer (Phase 1-4, to build)

Deterministic inner loop. Pure functions over a `PobSession`. No LLM.

Planned modules and contracts:

- `objective.py`: `Objective(score: Callable[[stats], float], constraints: list[Constraint])`,
  `Rails` dataclass (level, point budget, resist/life/EHP floors, affix tier
  and ilvl limits, influence/unique policy).
- `tree_graph.py`: adjacency and cost helpers over the canonical tree corpus
  (no PoB needed).
- `tree_optimizer.py`: `optimize_tree(pob, skeleton, objective, rails) -> TreeResult`
  with an `actions` trace (node added/removed, marginal gain).
- `gear_filler.py`: `fill_gear(pob, skeleton, objective, rails) -> GearResult`
  producing PoB raw item text per slot plus a trace.
- `config_rules.py`: `derive_config(skeleton, state) -> (conservative, optimistic)`.

Definition of done for each module was in `docs/ROADMAP.md` (frozen 2026-09-26; new work is GitHub issues). Every module gets
a benchmark fixture test that asserts PoB numbers.
