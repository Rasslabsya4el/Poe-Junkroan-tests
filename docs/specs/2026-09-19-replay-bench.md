# Spec: the replay bench -- judge a change to a move from the same finished builds, in minutes

Why (`docs/research/2026-09-19-judging-plan.md`, measured on our own campaigns): one build's noise inside a reference is
15% of its value; the smoke six x 3 seeds sees only effects of ~15%, the full 32 x 3 of ~6%; identical code on other
seeds "shows" -2.0% at the median and -14.5% on cold_dot; the same seed does not carry over between code versions
(r = +0.10). Most optimizer changes are worth 2-5%. The strongest pairing we have is the same STARTING BUILD: run the
move from a delivered build, before and after the code change, and compare gain and seconds.
`scripts/whole_tree_mip_experiment.py` (merged) already loads a delivered benchmark build, but with the RAILS floors
(the run files do not persist the author floors): reuse its loading code and rebuild the reference's author floors the
way the benchmark does (`scripts/benchmark.py`: `prepare_author` + `author_floors`, memoised per reference).

## The script

`scripts/replay_bench.py --builds "<glob of delivered .pob.txt>" --move <name> [--passes 1] [--seed S] [--workers 5]
--tag <tag>` writes `artifacts/replay/<stamp>-<tag>/results.json` + `report.md`.

For each build: load the XML (keep its tree version as the benchmark does), rebuild the pipeline state the improvement
loop needs (skeleton read back from the build the way a reference's skeleton is read, the objective with the
reference's author floors exactly as the run that produced the build had them, lanes re-derived with
`derive_config(prefer_rules=True)`, the gear filler seeded with the build's own items), then run the named move and
judge it with the pipeline's own judge:

- `--move loop` = whole passes of `_improvement_loop` (`--passes N`, default 1), no wall-clock budget;
- `--move refine | swaps | gear | picks | kick-tree | kick-joint` = that move alone, once;
- budgets inside a move are counted in TRIALS or draws, never seconds, so that two runs of the same code with the same
  seed do the same work (where the loop only has a seconds budget today, add the count alongside and use it here).

Row: reference, source build, value before, value after, gain %, seconds, kept / reverted, violation before / after,
audit errors after, the ledger's move rows when the move-ledger task is merged. `report.md`: per-build table, then
median gain %, mean gain %, builds improved / unchanged / worse, total seconds, and -- given `--against <other run>` --
the paired comparison of two runs over the same builds: median and mean difference of gain, a bootstrap 90% interval
over BUILDS (2,000 resamples, seed 1), wins / ties / losses, seconds ratio.

## Numbers to report (acceptance)

Builds: the six best smoke seeds named in `docs/specs/2026-09-19-whole-tree-mip-experiment.md`.
1. **A/A**: `--move loop --passes 1 --seed 1` twice on the same code: every build's value after must agree to 0.5%
   (report the largest disagreement and where it comes from if it is not 0: a wall-clock branch is a bug of the bench).
2. **Different seed**: `--seed 2` against `--seed 1`: report the spread -- this is the bench's own noise floor.
3. **Seconds**: the whole six-build run, one pass, on 5 workers: target under 25 minutes.
A before / after comparison is a measurement, never a test that runs another commit's code.

Tests (fast, fake pipeline): the paired report on two fixed result files (gains 1, 2, 3 against 2, 2, 5: median
difference +1, wins 2, ties 1, losses 0); a move named on the command line that the loop does not have is an error
that lists the legal names. Check `cmd /c dir /AL` first (junctions). Focused tests, then the whole suite once,
foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
