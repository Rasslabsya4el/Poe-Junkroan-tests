# Hypotheses: what the LLM may propose

The LLM's only input to the search is a list of *hypotheses*. A hypothesis is
a skeleton written with in-game names. It is validated against the corpora
(`junkroan.search.hypothesis.validate`) and turned into a `Skeleton`; the
pipeline then builds the tree, the rare gear and the config with PoB as the
judge. Nothing in a hypothesis is trusted for strength: it is a *place to
look*, and every blank it leaves is filled by measurement
(`junkroan.search.generator`).

## Format

```json
{
  "request": "Fireball",
  "hypotheses": [
    {
      "name": "Fireball ignite Elementalist",
      "class": "Witch",
      "ascendancy": "Elementalist",
      "main_skill": "Fireball",
      "supports": ["Burning Damage", "Deadly Ailments"],
      "extra_groups": [["Flammability"], ["Herald of Ash"], ["Flame Dash"]],
      "keystones": ["Elemental Overload"],
      "ascendancy_nodes": ["Shaper of Flames", "Mastermind of Discord"],
      "uniques": {"Weapon 1": "Pledge of Hands"},
      "rare_bases": {"Body Armour": "Vaal Regalia"},
      "why": "Ignite with proliferation; Elementalist guarantees the ignite and gives exposure."
    }
  ]
}
```

Required: `class`, `ascendancy`, `main_skill`. Everything else is optional
and, when omitted, is chosen by PoB:

| field | when omitted |
|---|---|
| `supports` | greedy over every support PoB links to the skill (day-1 gems only, no trigger supports) |
| `ascendancy_nodes` | greedy by objective gain per point (8 points) |
| `rare_bases` | best-of-40 loot rolls per candidate base per slot; weapon type included |
| `keystones` | the tree optimizer allocates keystones like any node |
| `uniques` | none; the unique screen reports uniques that beat the rares |

Given values are *hints*: a listed support stays in the link if PoB accepts
it; a listed keystone starts allocated and the tree optimizer may drop it;
a listed unique is equipped and stays.

## What is rejected

Unknown gem, keystone, unique, base or ascendancy names (exact in-game
names, case-insensitive). Awakened / Enhance / Empower / Enlighten
supports (not day-1). A unique in a slot its type cannot occupy. A slot with
both a unique and a rare base. An ascendancy of the wrong class.

## What is never in a hypothesis

Passive node ids, item affixes, config toggles, numeric assumptions. Those
are optimizer decisions (CLAUDE.md, principle 2). A hypothesis that tries to
smuggle them in is invalid.

## Retrieval, not recall

When writing hypotheses, query the corpora for names instead of recalling
them: `corpus_data/active_gems.json` (skills and tags),
`support_gems.json`, `keystones.json`, `uniques.json` (with PoB-parsed
mods), `scaling_vectors.md` (which vectors reward what: `per:FrenzyCharge`,
`cond:LowLife` ... with payoff sources and enablers). The `why` field is
kept verbatim for the report and never influences the search.
