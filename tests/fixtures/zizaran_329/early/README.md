# Zizaran 3.29 Curse of the Allflame league starters: the early-game loadout of each build

Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are
named `z329_<slug>` because the same slug exists in several leagues).
The files in `tests/fixtures/zizaran_329/` are the authors' own guide PoBs and carry several loadouts each
(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each
file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout
`../manifest.json` names in `early_loadout` -- never from the word "early" in a title.
Regenerate them all with:

```powershell
python scripts/extract_loadout.py
```

| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |
|---|---|---|---|---|---|---|---|---|---|
| gladiator_earthquake.pob.txt | Earthquake Gladiator League Starter | Early Game | Level 68 - Merc Lab (Swap to 1H) | Maps {1,2,3} | Default {1,3} (1 of 2) | inferred (no {n} marker on this item set) | 68 (spec title) | 99 | #1: Earthquake, Brutality, Fist of War ... |
| champion_explosive_arrow.pob.txt | Explosive Arrow Ballista Champion League Starter | Early Game | Level 69 - Merciless Lab | Level 38+ | Default (1 of 1) | inferred (no {n} markers anywhere in this build) | 69 (spec title) | 99 | #2: Explosive Arrow, Ballista Totem, Multiple Projectiles ... |
| juggernaut_boneshatter.pob.txt | Boneshatter Juggernaut League Starter | Early Game {1} | Early Game {1} | Early Game {1} | Default {1,2,3,4,5} (1 of 1) | author marker {1} | 81 (estimated from 114 allocated nodes) | 114 | #1: Boneshatter of Complex Trauma, Volatility, Melee Physical Damage ... |
| elementalist_winter_orb.pob.txt | Winter Orb Elementalist League Starter | Early Game {4} | Level 80 - Uber Lab {4} | Early Game {4} | Midgame {3,4} (1 of 3) | author marker {4} | 80 (spec title) | 113 | #1: Winter Orb, Increased Critical Damage, Infused Channelling ... |
| occultist_essence_drain.pob.txt | Essence Drain / Contagion Occultist League Starter (Goratha, featured by Zizaran) | Slinger 28+ | Slinger 28+ | Slinger 28+ | Slinger 28+ (1 of 8) | identical titles across all three set types | 68 (estimated from 99 allocated nodes) | 99 | #1: Spellslinger, Contagion, Essence Drain ... |

## What the extraction had to decide

- **champion_explosive_arrow**: mainSocketGroup 1 (holds ['Flame Dash', 'Blink Arrow']) -> 2, the group holding 'explosive arrow'
- **occultist_essence_drain**: mainActiveSkill 1 -> 3 ('essence drain' is active skill 3 of 3 in the main group)

## What PoB reads them as (`python scripts/fixture_stats.py zizaran_329/early`, stats.json)

| build | level | nodes | life | EHP | CombinedDPS | FullDPS |
|---|---|---|---|---|---|---|
| gladiator_earthquake | 68 | 99 | 4,093 | 59,677 | 65,215 | 0 |
| champion_explosive_arrow | 69 | 99 | 3,807 | 15,194 | 368,589 | 0 |
| juggernaut_boneshatter | 81 | 114 | 4,527 | 21,325 | 2,455,336 | 0 |
| elementalist_winter_orb | 80 | 113 | 4,127 | 34,536 | 227,895 | 1,139,476 |
| occultist_essence_drain | 68 | 99 | 2,453 | 9,916 | 44,442 | 0 |

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
