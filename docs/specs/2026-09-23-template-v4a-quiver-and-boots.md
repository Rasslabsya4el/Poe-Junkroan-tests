# Spec 2026-09-23: template v4, piece a -- the quiver takes the weapon shape; why the cyclones' template boots miss the movement floor

Lead: Opus 5.5. Worker: one coder, about ONE hour of work. `--gear wishlist` only; the loot path stays byte-identical.
Context (read, do not implement all of it): `docs/specs/2026-09-22-template-v4-flexible-lines.md` (the whole v4; this is
its first piece). You MAY reuse code from branch `sonnet-2026-09-22-template-v4` (`git show sonnet-2026-09-22-template-
v4:<path>`): its `quiver_weapon_shape` switch in `src/junkroan/optimizer/rails.py` / `rails_default.json` /
`wishlist_gear.template_for` and its tests are a working start; its "flexible lines" loop is NOT part of this piece.

## 1. Quiver = weapon shape (the owner's decision)

Rails switch `gear.wishlist.quiver_weapon_shape` (default ON after this piece): a quiver gets `weapon_open_lines`
natural lines ranked by VALUE at the weapon tier positions + one bench craft, no fixed life / resistance line
(`wishlist_gear.template_for`; `_buys_value` must read the per-instance rails).

## 2. Cyclone boots and `EffectiveMovementSpeedMod` -- find the cause first

Every template build of impale_cyclone and shockwave_cyclone ended at `EffectiveMovementSpeedMod` 1.027 (floors 1.164
and 1.0345) while template boots elsewhere carry +25% movement speed. Load, with PoB, ONE build file each:
`C:\Coding\poe-junkroan-archive\benchmark\20260921-0929-new18-tpl\impale_cyclone-s1.pob.txt`, `...\shockwave_cyclone-s1
.pob.txt`, and `C:\Coding\poe-junkroan-archive\benchmark\20260920-1618-new18-r3\impale_cyclone-s1.pob.txt` (loot),
plus the author `tests/fixtures/tuadh_329/impale_cyclone.pob.txt`; read PoB's breakdown of `EffectiveMovementSpeedMod`
(`calc` snapshot / the stat's breakdown: every source with its value -- boots line, tree, skill, buffs, penalties).
One table per build. Then:
- if the template boots are the cause (no movement line, or too low a tier), fix it in `wishlist_gear` so the boots
  take the lowest movement tier that meets the build's floor, within the tiers the template already allows;
- if the cause is elsewhere (a channelled-skill penalty, a buff the config does not prove, the floor read wrongly),
  change NOTHING and report the chain with numbers. That is a correct result, not a failure.

## Numbers to report

- A. `python scripts/gear_transplant.py bleed_bow impale_ballista impale_cyclone shockwave_cyclone --seed 1` (check its
  `--help` for the template / switch flags; at most 2 PoB workers): template % of the author and feasibility, switch
  off -> on; each quiver's lines off -> on.
- B. The part-2 tables and the cause in one paragraph.
- C. The loot section of one reference before / after: identical.
- D. Focused tests: pytest summary line. Do NOT run the whole suite in this piece (the lead runs it at merge).

## Rules

- Stop at about one hour of work: commit what works, report what is left. A small finished piece beats a big
  unfinished one.
- Worktree junctions `var/`, `vendor/`, `artifacts/`: read them, write only under `artifacts/`, never delete there.
- PoB: `python scripts/machine_load.py --need 2 --role other` first, wait for GO in steps of at most 10 min; at most 2
  PoB processes; no scratch files in the repository (use your temp dir); stop every background shell you start.
- Commit on your branch with the numbers in the message. Durations for a human (seconds under ~90 s, then minutes).
- Game and PoB terms verbatim in English; no game numbers from memory.
