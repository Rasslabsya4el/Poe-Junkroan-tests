# Task T2 (model comparison, 2026-09-23): `compare_runs.py --per-build`

CODE ONLY, about 30 minutes. Do NOT start Path of Building, `machine_load`, benchmarks or the whole test suite. Do
not read files other than those named. No scratch files in the repository.

## What

`scripts/compare_runs.py` compares two benchmark runs per reference (median / spread). For paired readings the lead
also needs a per-BUILD table, which today is assembled by hand. Each run folder has `results.json`: a list of rows
(or a dict holding the list under `rows` / `results`) with `slug`, `seed`, `ours` (the build's value), `ratio_lane`,
`seconds`, `move_rows` (list of dicts with an int `pass`) and `pob_calls` (dict: kind -> dict with a `seconds`
number, or a number). Read `scripts/compare_runs.py` to see how it finds the two run folders and loads them.

## Steps

1. Add a flag `--per-build` to `scripts/compare_runs.py`. When set, after the existing output print one markdown
   table over the builds present in BOTH runs, matched by (slug, seed), sorted by slug then seed:
   `| slug | seed | A value | B value | delta % | A passes | B passes | A PoB | B PoB | A build | B build |`
   passes = max `pass` in `move_rows` (0 if none); PoB = the sum of the `seconds` of every `pob_calls` entry;
   build = `seconds`. Durations through `junkroan.report_format.human_duration` (seconds under ~90 s, then minutes,
   then hours). Put the table building in a pure function `per_build_rows(a_rows, b_rows) -> list[dict]` and the
   rendering in `per_build_table(rows) -> str`.
2. Tests in `tests/test_compare_per_build.py` (new, pure data, no PoB): two small fake row lists -> the matched rows,
   the delta %, max pass, PoB sum (both `pob_calls` shapes), a build present in one run only is skipped, and the
   rendered table's header line.
3. Run exactly: `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_compare_per_build.py`
   Fix until green; `git add` the two files; commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, `git diff --stat`, the pytest line.
