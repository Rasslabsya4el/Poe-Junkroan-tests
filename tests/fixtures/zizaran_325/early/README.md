# Zizaran 3.25 Settlers of Kalguur league starters: the early-game loadout of each build

Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are
named `z325_<slug>` because the same slug exists in several leagues).
The files in `tests/fixtures/zizaran_325/` are the authors' own guide PoBs and carry several loadouts each
(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each
file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout
`../manifest.json` names in `early_loadout` -- never from the word "early" in a title.
Regenerate them all with:

```powershell
python scripts/extract_loadout.py
```

| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |
|---|---|---|---|---|---|---|---|---|---|
| hierophant_ice_nova_archmage.pob.txt | Ice Nova Archmage Hierophant Leaguestarter | Early Game | Level 68 - Merciless Lab | Level 31 - Maps | Default (1 of 1) | inferred | 68 (spec title) | 99 | #1: Firestorm, Archmage, Lightning Penetration ... |
| gladiator_lacerate.pob.txt | Bleed Lacerate Gladiator Leaguestarter | Early Game | Level 68 - Merc Lab (Swap to 1H) | Level 38 - Maps | Default (1 of 1) | inferred | 68 (spec title) | 98 | #1: Sunder, Fist of War, Chance to Bleed ... |
| slayer_ground_slam.pob.txt | Ground Slam Slayer Leaguestarter | Basic gear (Blood magic) | Leveling (Cruel lab - Merc lab) | Blood Magic | Default (1 of 1) | inferred | 61 (estimated from 94 allocated nodes) | 94 | #1: Vaal Ground Slam of Earthshaking, Fist of War, Fortify ... |
| gladiator_eviscerate_retaliate.pob.txt | Eviscerate & Retaliate Gladiator Leaguestarter (ft. Goratha) | Early Game | Level 68 - Merc Lab | Level 38 - Maps | Default (1 of 1) | inferred | 68 (spec title) | 103 | #1: Sunder, Chance to Bleed, Fist of War ... |
| berserker_ground_slam_autocry.pob.txt | Autocry Slammer Berserker Leaguestarter | Early Game {5} | Early Game {5} | Maps {1,2,4,5} | Default (1 of 1) | author marker {5} | 85 (estimated from 118 allocated nodes) | 118 | #2: Ground Slam of Earthshaking, Brutality, Melee Physical Damage ... |
| gladiator_spectral_shield_throw.pob.txt | Bleed SST Gladiator Leaguestarter | Early {3} | Level 74 + Merc Lab {3} | Maps {2,3,4} | Default (1 of 1) | author marker {3} | 74 (spec title) | 105 | #1: Spectral Shield Throw, Vicious Projectiles, Brutality ... |
| champion_explosive_arrow.pob.txt | Explosive Arrow Ballista Champion Leaguestarter | Early Game | Level 69 - Merciless Lab | Level 38+ | Default (1 of 1) | inferred | 69 (spec title) | 99 | #2: Explosive Arrow, Ballista Totem, Lesser Multiple Projectiles ... |

## What the extraction had to decide

- **hierophant_ice_nova_archmage**: no socket group of the kept skill set holds 'Ice Nova of Frostbolts (Archmage)': mainSocketGroup 2 -> 1, the largest live group (5 gems: ['Firestorm', 'Archmage', 'Lightning Penetration', 'Inspiration', 'Intensify'])
- **hierophant_ice_nova_archmage**: mainActiveSkill left at 1: the corpus lists no active gem of ['ice nova of frostbolts', 'ice nova of frostbolts (archmage)'] in the main group
- **gladiator_lacerate**: no socket group of the kept skill set holds 'Lacerate of Haemorrhage': mainSocketGroup 1 -> 1, the largest live group (4 gems: ['Sunder', 'Fist of War', 'Chance to Bleed', 'Cruelty'])
- **gladiator_lacerate**: mainActiveSkill left at 1: the corpus lists no active gem of ['lacerate of haemorrhage'] in the main group
- **slayer_ground_slam**: mainActiveSkill left at 2: the main skill 'vaal ground slam of earthshaking' is a Vaal gem (two entries, the author's pick stands)
- **champion_explosive_arrow**: mainSocketGroup 1 (holds ['Flame Dash', 'Blink Arrow']) -> 2, the group holding 'explosive arrow'

## What PoB reads them as (`python scripts/fixture_stats.py zizaran_325/early`, stats.json)

| build | level | nodes | life | EHP | CombinedDPS | FullDPS |
|---|---|---|---|---|---|---|
| hierophant_ice_nova_archmage | 68 | 99 | 2,723 | 26,398 | 457,582 | 0 |
| gladiator_lacerate | 68 | 98 | 4,186 | 50,943 | 241,545 | 0 |
| slayer_ground_slam | 61 | 94 | 3,309 | 5,407 | 6,093,139 | 0 |
| gladiator_eviscerate_retaliate | 68 | 103 | 3,675 | 10,663 | 255,415 | 0 |
| berserker_ground_slam_autocry | 85 | 118 | 5,421 | 30,091 | 1,209,181 | 0 |
| gladiator_spectral_shield_throw | 74 | 105 | 4,404 | 45,940 | 578,920 | 0 |
| champion_explosive_arrow | 69 | 99 | 3,807 | 15,840 | 315,844 | 0 |

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
