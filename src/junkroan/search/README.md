# search (Phase 5-6, to build)

Outer loop over build skeletons. Fitness of a skeleton is the result of the
optimizer on it.

Planned modules and contracts:

- `skeleton.py`: `Skeleton` dataclass (class, ascendancy, ascendancy notables,
  main skill, damage mode, supports, keystones, uniques, auras, weapon
  archetype) with `to_session(pob)`.
- `candidates.py`: combinatorial generation from corpora; corpus retrieval by
  damage type / delivery / condition; requirement graph from PoB parsed mod
  conditions; LLM hypothesis loader and validator.
- `beam.py`: screen -> top-K -> full optimize -> mutate -> repeat.
- `rank.py`: Pareto front and explanation payload from optimizer traces.

The LLM is an input source here (hypotheses) and an output consumer
(explanations). It is never inside the fitness function.
