# Spec: a benchmark run is durable and readable while it runs

Two facts from the night of 2026-09-18/19:

1. Every run directory under `artifacts/benchmark/` older than 2026-09-18 15:26 was lost to an unexplained
   recursive delete (`results.json`, `report.md`, logs of 25+ runs, the two frozen campaigns among them). Only the
   XML copies in the PoB Builds folder and the numbers typed into the docs survive; every `compare_runs.py` gate
   against those runs is gone.
2. `scripts/benchmark.py` writes `results.json`, `report.md` and the `.pob.txt` files only when the WHOLE run ends.
   The campaign `new18-rules` runs ~16 h: bleed_perforate s1 came back at 343% of the author at 02:20 and its
   build cannot be opened before the evening; a crash at hour 15 would lose 50 finished builds.

## Changes

1. `benchmark.py`: the moment a build finishes (in the parent, as each future completes) write
   `<run dir>/<slug>-s<seed>[-no-<keystone>].pob.txt`, the same file's XML into the PoB Builds folder exactly as the
   end-of-run code does today, and the row into `<run dir>/rows/<stem>.json`; rewrite `results.json` (all rows so
   far, atomically: temp file + `os.replace`) and `report.md` (through the existing report function; mark it
   "partial: N of M builds" in its first line) after every finished build. The end-of-run output stays byte-identical
   to today's for a complete run except that first line. `--rereport` keeps working.
2. `scripts/run_queue.py`: after a benchmark command ends (any rc), copy `results.json`, `report.md`, `rows/`,
   `logs/` and the `.pob.txt` files of its run directory to `<archive>/benchmark/<stamp>/`, where `<archive>` is the
   environment variable `JUNKROAN_ARCHIVE` or, unset, `C:\Coding\poe-junkroan-archive` (outside the repository and
   outside `artifacts/`, so nothing that walks a worktree's junctions can reach it). Log one line with the file
   count. A failed copy is logged and never fails the queue. Also copy the run's `.out` file.
3. `src/junkroan/optimizer/explain.py`: the "Numbers:" line prints the objective's own stat and names it
   (archmage_volatile_dead s1 printed "37,694 DPS conservative" -- CombinedDPS -- for a build whose objective and
   trajectory are FullDPS 1,796,945). Same for the optimistic-lane line.

## Tests

- A fake `run_one` (monkeypatched) returning rows with a delay: after the first finishes, `results.json` holds 1
  row, its `.pob.txt` and `rows/*.json` exist and `report.md` starts with "partial: 1 of 3"; after the last one
  the report has no "partial" line and equals the report built the old way from the same rows.
- A killed run (raise in the third build's future): the first two rows are on disk.
- `run_queue`: with `JUNKROAN_ARCHIVE` pointing to a temp dir, a finished fake run directory is copied (count
  asserted), a missing run directory logs and returns; nothing under the source is modified.
- `explain`: a result whose objective maximizes FullDPS prints the FullDPS value and the word "FullDPS".
Focused tests, then the whole suite once, in the foreground. Do not run real benchmarks (a 5-worker campaign is
running). Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch (this directory is your
worktree; never add another).
