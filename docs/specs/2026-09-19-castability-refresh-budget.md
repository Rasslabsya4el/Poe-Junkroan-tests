# Spec: second amendment to the castability / maximum-resistance floors -- the refresh must not tax every move

Branch `gpt-2026-09-19-usable-skills-amendment` (528675e), verified by the lead's foreman: the rule is right (Eldritch
Battery pool read from the calculation's own modDB flag, live main-skill relations, triggered skills covered, PoB's
reservation clause) and NOT mergeable for one reason of cost and three small ones. Your FIRST command in your worktree:
`git merge gpt-2026-09-19-usable-skills-amendment`. Work on top of it.

## 1. The cost (measured by the foreman on this branch)

`with_castability_floors` costs 1.2-2.7 s per call (soulrend 2,701 / 1,643 ms, physical_dot 1,998 / 1,162 ms) against
24-35 ms for `stats` and 6-11 ms for a fast trial: `active_skill_stats` does one full MAIN recalculation per enabled
player skill (12 on soulrend). `BuildPipeline._refresh_castability` (`pipeline.py` ~1161) calls it FOUR times with no
shared computation (the pipeline's objective, both tree optimizers, the gear filler), and `_reconfigure` runs once or
twice per judged move of the improvement loop and inside the generator's candidate loops (`generator.py` ~449, 460,
625, 666, 917): about 5-11 s of PoB time added to every judged move and every candidate.

Required:
- One computation per refresh, shared by every objective (the way `_refresh_self_cost` builds its `ctx` once).
- The FROZEN largest costs are refreshed only (i) after a write of the skills surface (`set_skills` / a kept or tried
  pick, link or utility change), (ii) once at the start of each improvement-loop pass, (iii) at the final audit. A tree
  move, a gear move, a lanes move and a judge's revert do NOT recompute them (the live main-skill relations already
  follow the main skill's cost inside every trial). A revert restores the previous frozen values from the move's
  snapshot instead of recomputing.
- Inside the generator's candidate loops a candidate that ADDS or replaces one skill recomputes only what it changed:
  new largest = max(the largest over the unchanged skills, the candidate skill's own cost) -- one `active_skill_stats`
  read for one skill, not for all.
- Report, on `tests/fixtures/tuadh_329/soulrend_chaos_dot.pob.txt` and `stormbrand`: calls and seconds of
  `with_castability_floors` (or its replacement) during `scripts/benchmark.py stormbrand --seeds 1 --no-variants
  --workers 1 --loop --loop-seconds 600`, before (528675e) and after; target: under 2% of the build's seconds, and the
  number of judged moves per pass within 5% of main's (count `judge` lines in the two logs; main = run the same
  command in a checkout of main if no such log exists under `artifacts/benchmark/`). A before / after comparison is a
  measurement, never a test that runs another commit's code.

## 2. `resist_floors` still reaches other callers

`scripts/build_from_skeleton.py` (~461, the documented `--author-floors` path) and seven experiment scripts still call
`objective.resist_floors()`, which now returns the AUTHOR's maxima as OUR fixed floors (worse than before the branch:
it was `min(author, 75)`). Remove the fixed elemental-resistance floors from every caller (grep `resist_floors`); the
own-maximum relations are the rail. Delete `resist_floors` if nothing legitimate is left, with its `__all__` entry.

## 3. Life cost: PoB's rule, not a stricter one

`Calcs.lua` 433-456 warns when `totalPool < cost`; equality passes. The frozen life relation is `strict`
(`math.nextafter`) while the live one is not. Make both PoB's: not strict. Remove the `"strict"` fifth element and its
handling in `objective.py` / `audit.py` if nothing else uses it.

## 4. Small repairs

- `audit_stats`: the live mana relation's left side is now `ManaCostPool`, so `"Unreserved" in a` no longer marks it an
  ERROR; a missed `ManaCostPool` / `LifeUnreserved` cost relation is an error again (one test).
- `audit.py` `__all__` lost `audit_dead_tree_nodes`: put it back.
- `tests/test_ramp_inputs.py` (~207) now asserts `{"ColdResist>=ColdResistMax": 1/78}`: a number that changes with
  every gear roll. The test is about the stance choice and the ramp budget: assert those, and do not assert
  feasibility or the violation dict.
- KEEP (the lead's decision): `self._gear.objective` is refreshed by `with_ramp` and `with_self_cost` like the tree
  optimizers' objectives -- the gear filler judges under the pipeline's own objective. Say so in the commit message.

Tests: fast ones for the refresh policy on a fake PoB that counts `active_skill_stats` calls -- a loop pass with three
tree moves, one gear move and one reverted move makes exactly ONE full computation; a utility candidate makes exactly
one single-skill read; a revert restores the old frozen values without any read. Check `cmd /c dir /AL` first
(junctions). Focused tests, then the whole suite once, foreground. Do not edit `docs/ROADMAP.md` or
`docs/DECISIONS.md`. Commit each numbered part apart, early.
