# Zizaran 3.26 Secrets of the Atlas league starters: the early-game loadout of each build

Part of the second reference set for the benchmark (`scripts/benchmark.py --set ziz`, where these builds are
named `z326_<slug>` because the same slug exists in several leagues).
The files in `tests/fixtures/zizaran_326/` are the authors' own guide PoBs and carry several loadouts each
(an item set, a tree spec, a skill set and a config set per stage). The benchmark reads one build, so each
file here is one stage of one author build, cut out by `scripts/extract_loadout.py` from the loadout
`../manifest.json` names in `early_loadout` -- never from the word "early" in a title.
Regenerate them all with:

```powershell
python scripts/extract_loadout.py
```

| file | author build | item set | tree spec | skill set | config set | linked by | level (source) | nodes | main group |
|---|---|---|---|---|---|---|---|---|---|
| trickster_blight_of_contagion.pob.txt | Blight of Contagion Trickster Leaguestarter | Maps {2} | Maps {2} | Maps {2} | Default (1 of 1) | author marker {2}; build has no separate early-maps gear set | 97 (estimated from 130 allocated nodes) | 130 | #1: Blight of Contagion, Infused Channelling, Controlled Destruction ... |
| chieftain_righteous_fire.pob.txt | Righteous Fire Chieftain Leaguestarter (w/ Pohx) | Level 61-80 {4} | Lvl 61-80 {4} | Level 61-80 {4,5} | Default {1,2,3,4,5,6,7,8} (1 of 2) | author marker {4} | 80 (item-set title) | 110 | #4: Righteous Fire, Burning Damage, Elemental Focus ... |
| berserker_volcanic_fissure.pob.txt | Earthshatter / Volcanic Fissure Berserker Leaguestarter (w/ imExile) | fresh maps | maps | fresh maps | Default (1 of 2) | inferred | 64 (estimated from 97 allocated nodes) | 97 | #1: Earthshatter, Lifetap, Pulverise ... |
| necromancer_zombie_army_early.pob.txt | Zoo Necromancer Leaguestarter, leveling + early/mid PoB (w/ Helm Breaker) | Early 6L Rare {1} | LvLing Tree lvl 92 {1} | Early Rare 6 link {1} | Early {1} (1 of 8) | author marker {1} | 92 (spec title) | 125 | #2: Raise Zombie, Multistrike, Minion Damage ... |
| elementalist_lightning_conduit.pob.txt | Lightning Conduit Elementalist Leaguestarter | Early Game {4} | Early Game {4} | Early Game {4} | Default (1 of 1) | author marker {4} | 85 (estimated from 118 allocated nodes) | 118 | #1: Lightning Conduit, Lightning Penetration, Elemental Focus ... |
| elementalist_wave_of_conviction.pob.txt | Wave of Conviction Ignite Elementalist Leaguestarter | Early Game | Level 68+ - Respec | Maps | Default (1 of 1) | inferred | 68 (spec title) | 99 | #1: Wave of Conviction, Cruelty, Ignite Proliferation ... |
| gladiator_earthquake.pob.txt | Bleed Earthquake Gladiator Leaguestarter | Early Game | Level 68 - Merc Lab (Swap to 1H) | Maps {1,2,3} | Default {1,3} (1 of 2) | inferred | 68 (spec title) | 99 | #1: Earthquake, Brutality, Fist of War ... |

Not extracted (no `early_loadout` in the manifest: the build has no staged loadouts): necromancer_zombie_army_late.

## What the extraction had to decide

- **chieftain_righteous_fire**: mainSocketGroup 3 (holds (no gem)) -> 4, the group holding 'righteous fire'
- **berserker_volcanic_fissure**: config set: no title or marker of the loadout names one, kept the build's active set 'Default' of ['Default', 'Fissure']
- **berserker_volcanic_fissure**: no socket group of the kept skill set holds 'Volcanic Fissure of Snaking': mainSocketGroup 1 -> 1, the largest live group (4 gems: ['Earthshatter', 'Lifetap', 'Pulverise', 'Overexertion'])
- **berserker_volcanic_fissure**: mainActiveSkill left at 1: the corpus lists no active gem of ['volcanic fissure of snaking'] in the main group
- **necromancer_zombie_army_early**: mainSocketGroup 9 (holds ['Shield Charge', 'Faster Attacks']) -> 2, the group holding 'raise zombie'
- **necromancer_zombie_army_early**: mainActiveSkill 3 -> 1 ('raise zombie' is active skill 1 of 3 in the main group)

## What PoB reads them as (`python scripts/fixture_stats.py zizaran_326/early`, stats.json)

| build | level | nodes | life | EHP | CombinedDPS | FullDPS |
|---|---|---|---|---|---|---|
| trickster_blight_of_contagion | 97 | 130 | 5,281 | 29,166 | 1,427,005 | 1,601,474 |
| chieftain_righteous_fire | 80 | 110 | 4,507 | 26,814 | 155,185 | 572,846 |
| berserker_volcanic_fissure | 64 | 97 | 3,129 | 18,591 | 233,943 | 0 |
| necromancer_zombie_army_early | 92 | 125 | 5,856 | 139,042 | 0 | 4,209,223 |
| elementalist_lightning_conduit | 85 | 118 | 5,083 | 29,417 | 3,169,254 | 0 |
| elementalist_wave_of_conviction | 68 | 99 | 3,898 | 24,038 | 422,725 | 1,019,313 |
| gladiator_earthquake | 68 | 99 | 4,093 | 59,677 | 49,267 | 0 |

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
