# Zizaran 3.28 Mirage league starters: the early-game loadout of each build

Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are
named `z328_<slug>` because the same slug exists in several leagues).
The files in `tests/fixtures/zizaran_328/` are the authors' own guide PoBs and carry several loadouts each
(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each
file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout
`../manifest.json` names in `early_loadout` -- never from the word "early" in a title.
Regenerate them all with:

```powershell
python scripts/extract_loadout.py
```

| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |
|---|---|---|---|---|---|---|---|---|---|
| champion_explosive_arrow.pob.txt | Explosive Arrow Leaguestarter | Early Game | Level 69 - Merciless Lab | Level 38+ | Default (1 of 1) | inferred | 69 (spec title) | 99 | #2: Explosive Arrow, Ballista Totem, Lesser Multiple Projectiles ... |
| hierophant_kinetic_fusillade.pob.txt | Kinetic Fusillade Ballista Hierophant Leaguestarter (w/ Palsteron) | EarlyMaps | EarlyMaps | EarlyMaps | Default (1 of 1) | identical titles across all three set types | 90 (estimated from 123 allocated nodes) | 123 | #1: Kinetic Fusillade, Ballista Totem, Less Duration ... |
| hierophant_shock_nova_archmage.pob.txt | Shock Nova Archmage Hierophant Leaguestarter (ft. Goratha) | Early Mapping | Early Mapping | Early Mapping | Default (1 of 1) | identical titles; note his 'Early Game' set here is act 1, not maps | 81 (estimated from 114 allocated nodes) | 114 | #1: Archmage, Inspiration, Spell Echo ... |
| juggernaut_boneshatter.pob.txt | Boneshatter of Complex Trauma Juggernaut Leaguestarter | Early Game {1} | Early Game {1} | Early Game {1} | Default {1,2,3,4,5} (1 of 1) | author marker {1} | 81 (estimated from 114 allocated nodes) | 114 | #1: Boneshatter of Complex Trauma, Volatility, Melee Physical Damage ... |

## What the extraction had to decide

- **champion_explosive_arrow**: mainSocketGroup 1 (holds ['Flame Dash', 'Blink Arrow']) -> 2, the group holding 'explosive arrow'

## What PoB reads them as (`python scripts/fixture_stats.py zizaran_328/early`, stats.json)

| build | level | nodes | life | EHP | CombinedDPS | FullDPS |
|---|---|---|---|---|---|---|
| champion_explosive_arrow | 69 | 99 | 3,807 | 15,194 | 368,589 | 0 |
| hierophant_kinetic_fusillade | 90 | 123 | 3,899 | 34,240 | 428,724 | 2,131,956 |
| hierophant_shock_nova_archmage | 81 | 114 | 3,403 | 51,515 | 1,039,024 | 2,077,942 |
| juggernaut_boneshatter | 81 | 114 | 4,527 | 21,325 | 2,455,336 | 0 |

## Caveats

- A guide PoB carries a **config set** per stage as well, and they are not interchangeable (the Essence Drain
  build's "Slinger 28+" set holds the author's leveling crutch `+200% to all resistances`; its "ALTERNATIVE
  SETUP" set holds the custom mods of a Pact of Ghorr staff build). The extractor picks the config set titled
  like the loadout, else the one sharing most of its `{n}` markers, else keeps the build's active one and says so.
- The gems in these files are the authors' own (mostly level 20-21 / quality 20-30). The benchmark does not
  score them that way: `scripts/benchmark.py` writes the rails' gems (level 18, quality 0, the main skill at
  the rails' `main_skill_quality`) onto the author's build before it reads a single number off it, because a
  generated build is always socketed at those (D23, D68). The file keeps the author's values; the row in
  results.json records them as `author_gem_levels`.
- `<Build level>` is the level the loadout is written for (the manifest's `early_loadout.level`, from the spec
  title or estimated from the node count); PoB's auto level mode is switched off in these files so that stated
  level is the one PoB uses.
- Everything else in the file is the author's: the tree is on the league's own tree version and the gear may be
  whatever the author had at that stage. PoB computes it all with the pinned 3.29 data.
