# Mechanics notes (hand-maintained)

The only curated game knowledge in the project. Each record is a fact that
Path of Building does **not** compute but that changes whether a PoB-optimal
build is actually good: corpse supply, orb caps, projectile overlap
breakpoints, uptime limits, targeting quirks.

Rules:

- If PoB computes it, it does not belong here.
- Every record must be machine-usable: `effect` is `constraint`, `penalty`
  or `note`, with numeric `params` when they exist, so the optimizer or the
  ranker can apply it without reading prose.
- Add a record only when a benchmark or a user report shows PoB-only ranking
  is misleading for that skill. Do not bulk-import.
- Mining source: `reference/legacy/skill_scaling_facts.py` (353 notes).

Schema (`notes.json`):

```json
{
  "id": "volatile_dead.orb_cap",
  "skill_gates": ["Volatile Dead"],
  "effect": "constraint" | "penalty" | "note",
  "summary": "one sentence",
  "params": {"key": number},
  "applies_to": "single_target" | "clear" | "both",
  "source": "url"
}
```

## Warning-only notes

Notes with `effect: "note"` and no `params` are warnings, not constraints.
The report layer prints them next to the build; the ranker ignores them.
Numbers get added only from in-game measurement or a wiki page that states
them explicitly.
