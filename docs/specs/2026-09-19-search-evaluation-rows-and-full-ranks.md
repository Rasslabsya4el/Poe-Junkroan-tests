# Spec: the search remembers every evaluation, and can optimize chosen screen ranks in full (the winner-recall test)

Why (`docs/research/2026-09-19-screening-plan.md`): `junkroan build` screens N skeletons cheaply and optimizes the top 2
in full. Whether the skeleton that wins at full depth is inside the screen's top 2 has never been measured: only the
promoted skeletons ever get a full value. This task adds the record and the switch that make the measurement possible.
No change to which skeletons a normal request promotes.

## 1. Evaluation rows

Every search run (`scripts/search.py`, hence `scripts/junkroan.py build`) appends to `<search folder>/evaluations.jsonl`,
one JSON object per line, written as soon as the evaluation ends (a killed run keeps its rows):

    {"request": <skill + the request's echo line or hypothesis id>, "skeleton": <the skeleton's label as in the report>,
     "rung": "rig" | "screen" | "full", "seed": <int or null>, "value": <Score.value>, "violation": <Score.violation>,
     "feasible": <bool>, "seconds": <float>, "commit": <git rev-parse --short HEAD or null>,
     "features": {"class", "ascendancy", "mode", "main_skill", "keystones": [...], "uniques": {slot: name},
                  "variant": <label or "">}}

"rig" = the value the prepared skeleton has after `rig_supports` / `prepare_candidate` (before the screen), if a
number exists there; do not add a PoB calculation that the run does not already make, except one `stats` read.

## 2. `--full-ranks`

`scripts/search.py ... --full-ranks 1,2,3,5,7,9,11,12,13 --seeds 1`: after the screen, optimize in full EXACTLY the
skeletons at those 1-based screen ranks (ranks above the number screened are dropped, duplicates ignored), instead of
the top `--top`; unique / keystone variants are NOT generated for them (`--no-variants` semantics). Same switch on
`scripts/junkroan.py build`. Without the switch nothing changes.

The report (`report.md`) of such a run gets one table and three lines:

    | screen rank | skeleton | screen value | full value | full rank | seconds |
    Spearman rho (screen value, full value) = ...   (n = ...)
    the full-depth winner sits at screen rank R: inside top 2: yes/no, top 3: yes/no, top 5: yes/no
    value at the end of construction and after loop pass 1 for each row (from the build's stages) and their Spearman
    with the full value

Infeasible full builds are listed and ranked last.

## Tests

Fast, with a fake runner: rows are written for rig / screen / full with the fields above and survive an exception in a
later evaluation; `--full-ranks 1,3,9` on 5 screened skeletons optimizes ranks 1 and 3 only; the table's Spearman on
the fixed fake values (screen 5,4,3,2,1 against full 1,2,3,4,5) is -1.0; a run without the switch promotes exactly what
it promoted before (same call list on the fake runner).

One real check, ONE PoB worker (a 5-worker benchmark is running; PoB is slow, not broken):
`python scripts/search.py "Cold Snap" --ascendancies Occultist,Trickster,Elementalist --full-ranks 1,3 --seeds 1
--workers 1 --loop-seconds 300` (use the script's own names for these options if they differ): report the table and
the path of `evaluations.jsonl`, and its row count by rung.

Check `cmd /c dir /AL` first: `var`, `vendor`, `artifacts` must be junctions. Focused tests, then the whole suite once,
foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Other workers are editing `search/runner.py` (one
line each) and `scripts/search.py` (one line): keep edits local. Commit early.
