# Layout and commands

Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there. CLAUDE.md sections "Layout" and "Commands" (with "Bumping PoB" and the objective metric).

## Layout

```
src/junkroan/pob/         INHERITED, STABLE. Headless PoB runtime + game-data corpora.
                          Entry point for new code: session.py (PobSession).
                          Do not add features here except through the roadmap
                          "harness" tasks. Never add gates/ledgers.
src/junkroan/optimizer/   Tree graph (pure Python), Objective, TreeOptimizer
                          (greedy + swap, PoB in the loop). Gear filler and
                          config rules to come. `scripts/recover_tree.py` is
                          the experiment harness. (Phase 1-4)
src/junkroan/search/      Skeleton model (skeleton.py). Candidate generation,
                          beam / evolutionary search, Pareto ranking to come. (Phase 5-6)
                          `optimizer/pipeline.py` turns a Skeleton into a build;
                          `scripts/build_from_skeleton.py` is the entry point.
src/junkroan/mechanics/   Hand-maintained non-PoB facts, JSON, small.
scripts/                  Runnable entry points (smoke_pob.py, later benchmarks).
tests/                    pytest. Fast tests do not need PoB; tests that need the
                          runtime skip when var/cache/pob is missing.
docs/                     STATE (live runs), ARCHITECTURE, LEGACY, ROADMAP (frozen history);
                          adr/ (decisions D1..), agents/ (skill config and working protocols).
GLOSSARY.md                The project's vocabulary (glossary only).
reference/legacy/         Read-only source material from v1. Never import.
vendor/pob/source/        PoB Lua data files used to regenerate corpora.
locks/pob.lock.json       Pinned PoB release (v2.67.2, PoE 3.29). var/ holds the runtime.
tests/fixtures/           Reference builds (Tuadh 3.29 day-1 runs) + stats.json.
```

## Commands

```powershell
python -m pytest -q -m "not slow"   # unit + contract tests (~5 s)
python scripts/smoke_pob.py         # boots PoB headless, builds a Fireball Witch, prints stats
python scripts/fixture_stats.py     # loads every reference build, prints/records its stats
python scripts/build_from_skeleton.py --from-fixture stormbrand --author-floors   # rebuild a reference from its skeleton
python scripts/search.py Fireball --ascendancies Elementalist,Inquisitor --top 2  # search (docs/HYPOTHESES.md for LLM input)
python scripts/junkroan.py build --skill "Storm Brand" --mode hit --ascendancy Hierophant,Inquisitor --level 80   # request -> search (docs/REQUEST.md); `junkroan build` / `python -m junkroan.cli` once `pip install -e .` has run; --dry-run echoes only, --no-variants is the cheapest run
python scripts/audit_build.py "artifacts/search-fireball/<YYYYMMDD-HHMM>/*.pob.txt"       # machine audit of finished builds (D31)
python scripts/describe_build.py "artifacts/search-fireball/<YYYYMMDD-HHMM>/01 *.pob.txt"  # read a build like a person: tree, gems, items, config, stats
```

Every search run writes its ranked set (`NN *.pob.txt`, `.json`, `report.md`) into its own dated folder
`artifacts/search-<skill>/<YYYYMMDD-HHMM>/` (same stamp as `report-<stamp>.md` and the Path of Building copy
`search <skill> <date> <time>`); a later run deletes nothing of it. The skill root keeps one `report.md`, the latest
run's, whose first line names the folder (`Latest run: <path>`); no junction, no symlink. The request echo prints
the folder (`results: <path>`).

The day-1 gear flag is `--gear` of `scripts/benchmark.py`: `template` is the value and the default; `wishlist` is its
alias and stays as the module and pipeline mode name.

If `var/cache/pob/<tag>/app` is missing, `PobSession` downloads the pinned
release via `release_manager.py` (~630 MB) on first use.

Bumping PoB: `python -m junkroan.pob.release_manager pob pin --version vX.Y.Z`,
re-clone `vendor/pob/source` at that tag, update `locks/pob.source.lock.json`,
run the three corpus `build` CLIs, run `scripts/fixture_stats.py`, run tests.
The worker's Lua strings call PoB internals (`ImportFromNodeList`, tab APIs);
a bump can change signatures. Fix them in `headless_runtime_worker.py`.

Objective metric: `CombinedDPS` per instance, and `FullDPS` only for main
skills whose instance count is a PoB stat (minions and totems today, brands
next; D57). Elsewhere FullDPS is only populated for socket groups flagged
"include in full DPS" and is 0 on many imported builds.
