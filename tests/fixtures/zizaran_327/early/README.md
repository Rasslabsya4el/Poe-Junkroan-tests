# Zizaran 3.27 Keepers of the Flame league starters: the early-game loadout of each build

Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are
named `z327_<slug>` because the same slug exists in several leagues).
The files in `tests/fixtures/zizaran_327/` are the authors' own guide PoBs and carry several loadouts each
(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each
file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout
`../manifest.json` names in `early_loadout` -- never from the word "early" in a title.
Regenerate them all with:

```powershell
python scripts/extract_loadout.py
```

| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |
|---|---|---|---|---|---|---|---|---|---|
| champion_explosive_arrow.pob.txt | Explosive Arrow Champion Leaguestarter | Early Game | Level 69 - Merciless Lab | Level 38+ | Default (1 of 1) | inferred | 69 (spec title) | 99 | #2: Explosive Arrow, Ballista Totem, Lesser Multiple Projectiles ... |
| elementalist_lightning_conduit.pob.txt | Lightning Conduit Elementalist Leaguestarter | Early Game {4} | Early Game {4} | Early Game {4} | Default (1 of 1) | author marker {4} | 85 (estimated from 118 allocated nodes) | 118 | #1: Lightning Conduit, Lightning Penetration, Elemental Focus ... |
| gladiator_earthquake.pob.txt | Earthquake Gladiator Leaguestarter | Early Game | Level 68 - Merc Lab (Swap to 1H) | Maps {1,2,3} | Default {1,3} (1 of 2) | inferred | 68 (spec title) | 99 | #1: Earthquake, Brutality, Fist of War ... |
| juggernaut_boneshatter.pob.txt | Bleed Boneshatter Juggernaut Leaguestarter | Early Game {1} | Early Game {1} | Early Game {1} | Default {1,2,3,4} (1 of 2) | author marker {1} | 82 (estimated from 115 allocated nodes) | 115 | #1: Boneshatter of Complex Trauma, Volatility, Melee Physical Damage ... |
| slayer_earthshatter.pob.txt | Earthshatter Slayer Leaguestarter (ft. Carn) | Basic gear {2} | Early Maps {2} | Early Maps {2} | Default (1 of 1) | author marker {2} | 65 (estimated from 98 allocated nodes) | 98 | #1: Earthshatter, Overexertion, Fortify ... |
| hierophant_storm_burst.pob.txt | Storm Burst Totems Hierophant Leaguestarter (ft. Oscrix) | Early Maps {1} | Early Maps {1} Merc Lab | Early Maps {1} | Early Maps {1} (1 of 4) | author marker {1} | 66 (estimated from 99 allocated nodes) | 99 | #3: Storm Burst, Physical to Lightning, Lightning Penetration ... |
| assassin_poison_spark.pob.txt | Poison Spark Assassin Leaguestarter (ft. Goratha) | Poison Spark Maps (Reverse Chill) | Poison Spark Maps (Reverse Chill) | Poison Spark Maps (Reverse Chill) | Default (1 of 1) | identical titles across all three set types | 87 (estimated from 120 allocated nodes) | 120 | #1: Spark of the Nova, Unbound Ailments, Spell Echo ... |
| necromancer_raise_spectre.pob.txt | Forged Frostbearer Spectre Necromancer Leaguestarter (ft. Helm Breaker) | Early 6L Rare {1} | LvLing lvl 92 Trigger wand {1} | Early Rare 6 link {1} | Early {1} (1 of 13) | author marker {1} | 92 (spec title) | 125 | #2: Minion Damage, Raise Spectre, Spell Echo ... |

Not extracted (no `early_loadout` in the manifest: the build has no staged loadouts): assassin_poison_cremation.

## What the extraction had to decide

- **champion_explosive_arrow**: mainSocketGroup 1 (holds ['Flame Dash', 'Blink Arrow']) -> 2, the group holding 'explosive arrow'
- **hierophant_storm_burst**: mainSocketGroup 1 (holds ['Cast when Damage Taken', 'Eternal Blessing', 'Determination']) -> 3, the group holding 'storm burst'

## What PoB reads them as (`python scripts/fixture_stats.py zizaran_327/early`, stats.json)

| build | level | nodes | life | EHP | CombinedDPS | FullDPS |
|---|---|---|---|---|---|---|
| champion_explosive_arrow | 69 | 99 | 3,807 | 15,194 | 368,589 | 0 |
| elementalist_lightning_conduit | 85 | 118 | 5,083 | 29,417 | 3,169,254 | 0 |
| gladiator_earthquake | 68 | 99 | 4,093 | 59,677 | 49,267 | 0 |
| juggernaut_boneshatter | 82 | 115 | 4,554 | 21,135 | 1,819,655 | 0 |
| slayer_earthshatter | 65 | 98 | 4,364 | 5,849 | 692,579 | 0 |
| hierophant_storm_burst | 66 | 99 | 3,434 | 16,698 | 77,567 | 232,353 |
| assassin_poison_spark | 87 | 120 | 3,840 | 12,093 | 281,656 | 0 |
| necromancer_raise_spectre | 92 | 125 | 5,823 | 130,529 | 0 | 3,104,039 |

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
