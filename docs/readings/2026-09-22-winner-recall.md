# Reading 2026-09-22: screen winner recall on three requests (Opus 5.5 lead)

Test 1 of `docs/research/2026-09-19-screening-plan.md`: three searches (Fireball hit, Essence Drain DoT, Raise Zombie
minion), 20 skeletons screened each, ten spread over the screen ranking (screen ranks 1-3, 5-11 odd, 13-17 odd)
optimized in full, one seed, `evaluations.jsonl` in `artifacts/search-<skill>/`. Table built by a Sonnet agent, no
PoB; the cause checked by the lead on the rows.

| request | Spearman screen -> full (95% CI) | full winner's screen rank | winner by screen VALUE only | Spearman loop pass 1 -> full |
|---|---|---:|---:|---:|
| Fireball | 0.66 (0.05, 0.91) | 2 | 2 | 0.92 |
| Essence Drain | 0.65 (0.03, 0.91) | 1 | 1 | 0.84 |
| Raise Zombie | 0.27 (-0.43, 0.77) | 15 | 2 | 0.87 |
| pooled, 30 pairs | 0.53 (0.21, 0.75) | top 2 in 2 of 3 | top 2 in 3 of 3 | |

All 30 full-depth builds are feasible. Late bloomers: Fireball Witch/Necromancer screen 9 -> full 3; Essence Drain
Ranger/Raider screen 15 -> full 3 (a true one: its screen DPS is genuinely low); Raise Zombie Templar/Guardian screen
15 -> full 1.

## What it says

1. **Raise Zombie's miss is the ranking rule, not the screen's information.** `scripts/search.py` sorted the screen
   feasibility first. Six Raise Zombie skeletons missed a floor at the screen by the same 0.008; Templar/Guardian had
   the second-best screen DPS (240,681) and was ranked 15th behind every feasible skeleton, then won at full depth.
   Across every search on disk, all four screen-infeasible skeletons that reached full depth ended feasible (screen
   violations 0.008, 0.008, 0.05, 0.276): a cheap screen cannot buy floors, the full optimize does (D58). Fixed: the
   screen ranks by value, violation only breaks ties (D97). With that rule the winner is inside the screen's top 2 on
   3 of 3 requests.
2. **The middle rung predicts almost perfectly** (loop pass 1 -> full: 0.84-0.92), the screen only moderately (0.53
   pooled). If top-2 recall ever fails again under the value-first rule, the next step is the plan's item 2: promote
   the top ~5 to loop pass 1 and 2 from there.
3. A true late bloomer exists (Essence Drain's Raider, screen 15 -> full 3), so the plan's exploration quota (one
   middle-rung slot in five for a skeleton from outside the screen's top) keeps its reason; not coded yet.
4. Three requests are a small sample (the plan asks for 30+ pairs, we have 30 but only 3 winners); re-run test 1 after
   the next big loop change.
