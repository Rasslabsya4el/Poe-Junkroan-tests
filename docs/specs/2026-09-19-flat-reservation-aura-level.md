# Spec: the level of a flat-reservation aura is a build decision, not the gem rail's 18

## What the lead measured (2026-09-19, while reviewing the castability floor)

The gem rail writes EVERY gem at level 18 (`Skeleton.apply_skills`, `SkeletonGenerator._apply_groups`, and on the
author's side `scripts/benchmark.py normalize_author_gems`). For an aura whose reservation is FLAT mana the level is a
deliberate player choice: PoB's gem data (`vendor/pob/source/src/Data/Skills/*.lua`, `manaReservationFlat` per level)
gives Precision 22 mana at level 1 and 167 at level 18, Clarity 129 at 8 and 251 at 18, Vitality 138 at 11 and 209
at 18.

- Reference fixtures (Tuadh 32 + Zizaran): 66 enabled flat-reservation gems below level 18 on 24 references. Tuadh:
  impale_cyclone Precision 1, shockwave_cyclone Precision 9, winter_orb Clarity 8, spark Vitality 11 / Clarity 17,
  absolution_minions Clarity 14, stormbrand Vitality 15, static_strike / summon_raging_spirits Precision 15,
  lightning_trap Vitality 16, vd_spellslinger Clarity 17, hit_penance_brand Vitality 17.
- Every one of our 33 delivered builds on those 11 references (`artifacts/benchmark/20260919-0130-new18-rules`,
  `20260919-0941-core14-rules`) carries the aura at level 18.
- The author's side: impale_cyclone raw `ManaUnreserved` +73, under our lane -37 (the rail lifted Precision 1 -> 18:
  +145 mana reserved).
- The castability scan of worker `usable-skills-and-max-res-floors` over those runs: shockwave_cyclone s1-s3 have
  12 / 13 / 7 unreserved mana against utility costs of 21-31; Precision at the author's level 9 instead of 18 frees
  73 mana -- all of them castable. The rail, not the build, made them uncastable.

## Rule (DECISIONS entry is the lead's; do not edit docs/DECISIONS.md)

A "flat-reservation aura" = an active gem whose PoB skill types include a reservation type and no mine type, and
whose PoB level data carries `manaReservationFlat` (derive the set from PoB's data through the corpora /
`pob/skill_facts.py`; add the reader there if it is missing; never a name list -- the three names above are test
inputs only).

1. **Our side.** The level of each flat-reservation aura in a skeleton is chosen by PoB: every level from 1 to the
   gem rail's level is tried (`set_skills` + `stats`, about 0.15 s per level) and the best `Score` under the FULL
   objective wins (a level that breaks a floor loses by the ordinary violation order). It is a move of the
   improvement loop's picks step (the reservation room changes with tree and gear), and it runs once at construction
   after the first gear fill. The chosen levels live in the skeleton (serialised in `to_json` / `from_json`), and
   every skills writer uses them (one code path; the gem-count worker has just unified the writers -- use that).
2. **The author's side.** `normalize_author_gems` leaves a flat-reservation aura at `min(the author's level, the
   rail's level)`; everything else is unchanged. Its report line says how many gems were kept low.
3. `describe_build` / `explain` print the chosen level next to the aura when it is not the rail's.

## Numbers to report (one PoB worker; a 5-worker run may be active)

- The flat-reservation aura set as derived from PoB's data (names, count).
- The 58 authors under our lane before / after rule 2: `ManaUnreserved` and `CombinedDPS` for every reference where
  either moves (expected: impale_cyclone back near +73 unreserved; DPS down where the author's low Precision gives
  less accuracy / crit than level 18 did).
- `scripts/benchmark.py shockwave_cyclone impale_cyclone winter_orb --seeds 1 --no-variants --workers 1 --loop
  --loop-seconds 600` on the parent and on your tree: the chosen levels, `ManaUnreserved`, the percent of the author,
  audit errors. A before / after comparison is a measurement, never a test that runs another commit's code.

## Tests

Fast: the derivation of the set from a fake gem-data mapping; the level search on a fake PoB (score rises with level
until a floor breaks at level N -> level N-1 is kept); `normalize_author_gems` keeps Precision 1 and still lifts a
level-14 damage gem to the rail; JSON round trip of the chosen levels. PoB-backed (skip without the runtime): Precision
reserves 22 at level 1 and 167 at level 18 on a bare Duelist.

Check `cmd /c dir /AL` first: `var`, `vendor`, `artifacts` must be junctions. Focused tests, then the whole suite
once, foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
