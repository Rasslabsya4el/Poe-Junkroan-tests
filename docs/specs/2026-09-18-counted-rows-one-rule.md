# Spec: one rule for which benchmark rows count, in `benchmark.py`'s report and in `compare_runs.py`

Two scripts summarize the same `results.json` by different rules, and the fixed-point check (888c02b) made
the difference visible on `artifacts/benchmark/20260918-1526-gear-loot`:

- `scripts/benchmark.py` (report.md, lines ~529-567) counts a row only when `audit_errors == 0` and the last
  stage's violation is <= 1e-9, labels the rest "(infeasible, not counted)", and takes `vals[len(vals) // 2]`
  as the median -- the UPPER of two when a row dropped out. Its table says burning_arrow_snipe 184%,
  impale_ballista 92%, summon_raging_spirits 183%.
- `scripts/compare_runs.py` (`summarize`) counts every `ok` row, feasible or not, with `statistics.median`.
  Its numbers: 179.7, 92.4, 158.9; median of medians 150.2.

The three rows `benchmark.py` dropped carry one audit error each, and it is the fixed-point finding ("the loop
was not at a fixed point: one more pass gained +2.8% / +2.3% / +1.4%"). That finding is about stability
(ROADMAP Phase 7 definition of done, item 3), not about the build: `_fixed_point_check` keeps what the extra
pass gained, the delivered build is feasible and its number is real. Dropping the row hides a valid seed and,
with the upper-of-two median, biases the reference upward (SRS 183 instead of 158.9).

## The rule (the lead's decision, 2026-09-18)

A row counts toward a reference's median when all three hold: `ok`; the last stage's violation <= 1e-9; it has
no audit error other than fixed-point ones. The median is `statistics.median` (the mean of the middle two on
an even count). One function, imported by both scripts (put it in `src/junkroan/optimizer/` next to the audit
or in a small `scripts`-importable module -- your choice, no duplication).

- `results.json` stores audit findings as strings (`"[error] fixed point: ..."`, `"[warning] ..."`); read the
  check name from the string the way `Finding.__str__` writes it (look it up, do not guess the format). Keep
  old results.json files readable: a run without fixed-point findings must summarize exactly as before under
  `compare_runs.py`'s old rule whenever every row is feasible and audit-clean.
- `benchmark.py` report: the label becomes "(infeasible, not counted)" only for violation > 1e-9, "(audit
  error, not counted)" for a non-fixed-point audit error; a fixed-point-only row is counted and keeps its
  "fixed point" column value. Add one summary line under the medians table: "not at a fixed point (> 1%): N of
  M builds".
- `compare_runs.py`: same counting rule; the "audit errors A/B" column stays; add "not counted A/B".
- Add `scripts/benchmark.py --rereport <run dir or tag>`: rewrite `report.md` of a finished run from its
  `results.json` with the current rule, touching nothing else (no PoB). If the report needs fields
  `results.json` does not hold, say which in the report and rewrite only the medians tables.

## Numbers the tests must reproduce (from `artifacts/benchmark/20260918-1526-gear-loot/results.json`)

Ratios to the author under our lane, seeds 1/2/3, audit errors in brackets, every row violation 0:

| reference | s1 | s2 | s3 | median, new rule |
|---|---|---|---|---|
| bleed_bow | 156.5 | 141.4 | 140.3 | 141.4 |
| burning_arrow_snipe | 136.6 [1, fixed point] | 179.7 | 183.8 | 179.7 |
| cold_dot | 112.4 | 97.1 | 131.1 | 112.4 |
| impale_ballista | 119.4 [1, fixed point] | 92.4 | 80.1 | 92.4 |
| stormbrand | 169.4 | 174.1 | 124.2 | 169.4 |
| summon_raging_spirits | 182.5 | 156.5 | 158.9 [1, fixed point] | 158.9 |

Median of medians 150.2 (150.15). Copy the minimal fields of those 18 rows into a test fixture (do not read
`artifacts/` from a test). Further unit cases: a row with violation 0.2 is not counted; a row with
`"[error] mod family: ..."` is not counted; two counted rows 80 and 92 give 86.0; a FAILED row is not counted
and shows as failed.

Then run `--rereport` on `20260918-1526-gear-loot` and paste the new medians table into the report; run
`compare_runs.py loot600-smoke gear-loot --min-delta -100` and paste its output. Tests: your new ones plus
`python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/ -k "benchmark or compare"`, then the whole
suite once, in the foreground. Commit on your branch with the numbers in the message.
