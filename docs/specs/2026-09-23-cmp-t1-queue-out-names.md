# Task T1 (model comparison, 2026-09-23): every queue line writes its own .out file

CODE ONLY, about 20 minutes. Do NOT start Path of Building, `machine_load`, benchmarks or the whole test suite. Do
not read files other than those named. No scratch files in the repository.

## The bug

`scripts/run_queue.py` ~line 229: `name = f"{datetime.now():%Y%m%d-%H%M}-{tag.group(1) if tag else 'run'}"`, then
`out = RUNS / f"{name}.out"` and `out.open("w", ...)`. Two queue lines without `--tag` that start in the same minute
(e.g. two `compare_runs.py` lines) get the same name, and the second overwrites the first (lost on 2026-09-22 22:23).

## Steps

1. In `scripts/run_queue.py`, make the name unique: when no `--tag`, use the script's file stem instead of `run`
   (`compare_runs`, `gear_transplant` ...: the first `scripts/<name>.py` in the command, `run` if none); and if
   `RUNS / f"{name}.out"` already exists, append `-2`, `-3`, ... until it does not. Put this in a small pure function
   `out_name(cmd: str, now: datetime, runs_dir: Path) -> str` next to the loop and call it there.
2. Tests in `tests/test_run_queue_out_name.py` (new file, `tmp_path`, no PoB): a tagged command -> `<stamp>-<tag>`;
   an untagged `compare_runs.py` command -> `<stamp>-compare_runs`; a second identical call after creating the first
   file -> `...-2`; a command with no `scripts/` path -> `...-run`.
3. Run exactly: `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_run_queue_out_name.py`
   Fix until green; `git add` the two files; commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, `git diff --stat`, the pytest line.
