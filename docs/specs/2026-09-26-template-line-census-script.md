# Spec 2026-09-26: `scripts/template_line_census.py`, the +0 open lines of template gear per run (CODE ONLY, ~20 min)

Lead: Opus 5.5. Worker: DeepSeek V4.1 Flash. No PoB, no `machine_load`, no benchmarks, no whole suite. Only the two new
files below. No scratch files in the repo. Durations in the report in human units (principle 7).

## Why

The lead counted by hand (2026-09-26) how many flexible armour / jewellery lines of template gear add +0 to the
objective: 698 of 1,359 in 192 builds. The next template change (spec `2026-09-26-template-loop-lines-by-value.md`)
must move that number; this script is its measurement, run on any benchmark run directory.

## What the logs contain

Every template build log `artifacts/benchmark/<run>/logs/<slug>-s<seed>.log` ends with a gear summary, one line per
slot, two spaces of indent, e.g.

```
  Ring 1: Two-Stone Ring (Fire/Lightning) (+(12-16)% to Fire and Lightning Resistances): life T2 T2/8 +(85-99) to maximum Life; resistance_fixed T5 T5/8 +(24-29)% to Lightning Resistance; objective_line T3 T3/6 +(21-25)% to Chaos Resistance, delta 0.
  Helmet: Great Crown: life T3 T3/10 +(100-114) to maximum Life; resistance_fixed T4 T4/8 +(30-35)% to Cold Resistance; attribute {crafted} +18 to Strength and Dexterity, delta 8,350.
  Weapon 1: Highborn Bow (...): objective_line T4 T4/10 Adds (14-20) to (281-327) Lightning Damage, delta 330,594; objective_line T5 ...
```

The same slot can print such a line several times in one log (kicks); the LAST occurrence per slot is the delivered
item. A slot line counts as a summary line only if its body contains one of `life T`, `objective_line`,
`resistance_fixed`, `attribute`. Slots: Weapon 1, Weapon 2, Body Armour, Helmet, Gloves, Boots, Amulet, Ring 1,
Ring 2, Belt.

## Steps

1. `scripts/template_line_census.py <run dir or name> [<run> ...] [--top 15]`. A bare name resolves to the newest
   `artifacts/benchmark/*<name>` directory (copy the resolution helper of `scripts/compare_runs.py`, do not import
   from it if that pulls PoB). For each log: take the last summary line per slot; skip a Weapon slot whose body has no
   `life T` (a weapon shape: its lines buy value by rule); split the body on `"; "`; a part whose first word is
   `objective_line` or `attribute` is a flexible line; its value is the number after `delta ` (commas removed, a
   trailing "." stripped); it is "+0" when that number is 0. The mod text of a part = the part without its first word,
   without a leading tier token (`T3 T3/6 ` or `{crafted} `) and without `, delta ...`; normalise every `(a-b)` and
   every plain number to `#`.
   Print (markdown, human units if any time appears): per run one row -- builds, flexible lines, +0 lines, +0 share,
   of those `objective_line` / `attribute`; then the `--top` most common +0 mod texts over all runs given, with
   counts; then per build (slug-seed) flexible and +0 counts, sorted by +0 descending, top 12.
2. Check against the lead's numbers, all four runs together:
   `python scripts/template_line_census.py 20260925-0135-core14-tpl-main3 20260925-0516-new18-tpl-main3-lap 20260924-0231-ziz-tpl-main3-lap 20260926-0227-main3-tpl-smoke-s4-lap`
   must give builds 192, flexible lines 1,359 (objective_line 966, attribute 393), +0 lines 698 (objective_line 450,
   attribute 248), and the top +0 mod text `+#% to Chaos Resistance` with 195. If a number differs, find why before
   changing anything and say it in the report; do not tune the parser to the number without a reason.
3. `tests/test_template_line_census.py`: a tiny fake run directory in `tmp_path` with two logs (one slot printed twice:
   the last one counts; one weapon-shape line skipped; one `delta 0.` and one `delta 8,350.`), asserting the counts and
   the normalised mod text. Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_template_line_census.py`
   then commit with a message naming this spec.
4. Final message: `=== FINAL REPORT ===`, the commit hash, `git diff --stat`, the pytest line, and the step-2 output
   (the per-run rows and the top 5 texts).
