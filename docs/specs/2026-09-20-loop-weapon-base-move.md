# Spec: the loop re-chooses the weapon BASE as the build mutates (a new move: "weapon base")

## Why (the user, 2026-09-20)

"A weapon's base is far more than its implicit: its crit chance is THE base of an attack build's crit, its attack speed, and
its base physical damage is most of a physical build's damage. The system can build a non-crit build on a non-crit base and
drift into crit over many mutations without ever changing the base."

Today (read from the code): the search chooses weapon type and base ONCE, on the bare skeleton
(`SkeletonGenerator._screen_weapons`, affix ceiling per base), writes it into `skeleton.rare_bases`, and every later gear
move rolls the slot on THAT base (`pipeline.py`: `loot.fill_slot(slot, skeleton.rare_bases[slot], ...)`). A benchmark build
from a fixture wears the author's base for life. Only the template filler (`--gear wishlist`) re-ranks bases inside the class
when it fills a slot. So in the default (loot) mode the base never follows the build.

## The move

For each RARE weapon slot (`Weapon 1`, and `Weapon 2` when it holds a weapon -- never a shield or quiver; uniques are not
touched), once per loop pass, after the gear moves and before the picks:

1. Candidates = the other legal bases of the SAME item class as the equipped item (`bases_of_type(type_of(base),
   max_level=rails.gear.item_level)` for loot, the template's `area_level` rule for wishlist; the same exclusions the fillers
   use). For each candidate: the equipped item's OWN affixes moved onto that base -- `craft_rare(base, prefixes=, suffixes=,
   ilvl=, ...)` with the same mod ids and rolls and the same bench craft; a base on which any of the mods is not legal is
   skipped (count them). The implicit is the new base's own.
2. ONE fast item what-if per candidate (`trial_stats([{"item": {"slot", "raw"}}], keys, mode="fast")`), scored by the
   objective. The best candidate by `Score`; it is taken only if `better_score(new, cur, min_gain=<the loop's min gain>)`.
   A base whose requirements the build does not meet shows up as a violation and loses by the ordinary rule -- no special case.
3. Taken = `equip` it for real, update `skeleton.rare_bases[slot]` (so later gear moves roll on the new base), then the
   loop's ordinary `judge` with exact restore (item + rare_bases) like a gear move. Ledger row name: `weapon base`.
4. Loot realism: the affixes are the ones the loot roll produced; bases of one class share their spawn pool, so "the same
   roll on another base of the class" is the same luck. Where a class has bases with a different pool (the legality check
   fails), those bases are simply skipped.
5. Cost guard: the move is skipped for a slot when nothing in the build changed since the last time the move judged that
   slot and kept nothing (the fingerprint idea the kick draws use: tree nodes + the slot's raw text + config lanes).

Out of scope here (measure only, item 3 of the numbers): changing the weapon TYPE.

## Tests (fast, fakes)

A crit-heavy fake build on a low-crit base: the high-crit base wins and `skeleton.rare_bases` changes; a candidate base whose
craft is illegal is skipped and counted; a base that raises violation loses on a feasible build; a judged revert restores item
AND `rare_bases`; the fingerprint skip; a shield / quiver / unique in `Weapon 2` is never touched; the ledger row.

## Numbers to report (replay bench, D84; ONE bench run at a time, `--workers 2` by day, `machine_load.py` first)

1. `python scripts/replay_bench.py --builds "artifacts/benchmark/20260919-0941-core14-rules/*.pob.txt;artifacts/benchmark/20260919-0130-new18-rules/*.pob.txt" --move weapon-base --seed 1 --workers 2 --tag weapon-base`
   (add the move name to the bench): improved / unchanged / worse, mean and median gain, seconds per build, split attack /
   spell / minion, and over the builds that start feasible. Per changed build: old base -> new base and the three base
   numbers that differ (crit chance, attacks per second, physical damage range or the implicit).
2. How many candidate bases were skipped for an illegal mod, per class.
3. MEASUREMENT ONLY, no code path in the loop: on the delivered builds of the three acceptance requests and the winner-recall
   searches (`artifacts/search-*/` finalists), re-run the weapon-TYPE screen's ceiling (`_screen_weapons`' logic) on the
   FINISHED build: does the type chosen on the bare skeleton still win? Count agreements / disagreements and the value gap.
4. Focused fast tests; the whole suite once at the end, alone on the machine (`-p no:cacheprovider -p no:faulthandler`).

Rules of the house: one PoB job at a time; bounded waits only (every wait loop has a deadline and matches failure too) and no
background shell left behind; never `git add -A`, nothing under `var/` `vendor/` `artifacts/` into git; no recursive deletes;
do not edit `docs/ROADMAP.md`, `docs/DECISIONS.md`, `CLAUDE.md`. Commit early; the final message begins with
`=== FINAL REPORT ===`.
