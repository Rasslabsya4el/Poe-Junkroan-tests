# Testing: which test a change gets, and how long it takes (D113)

One page, read before any `runs submit`. Every ticket in `area:builds` names its kind in its body before the first
PoB job; a ticket without a kind gets no PoB job. The rule's reasons and numbers are in D113 and D84; the queue
protocol is `docs/agents/runs.md` ("Which runs are not fillers"). Durations below are measured on this machine.

## 1. Decide the kind

| kind | what changed | examples |
|---|---|---|
| A | the search space: an option becomes allowed, or a class is forbidden (rails, rulebook values, templates, bases, oils, sockets, cluster sizes, unique tiers) | #392 (uniques T5 only), #436 (flasks), #433 (cluster jewels), #429 (template lines) |
| B | how the loop or the evaluation behaves (a move's logic, judging, the objective, trial_stats, seeds) | #179 (loot fill ends on its best set), #398 (an emptied slot's trial), #464 (seed collisions), #419 |
| C | a refactor: every PoB number must stay identical | #35, #42, #51 (judging context, loop as a module) |
| D | speed only | a cache, a faster parser |
| none | no optimizer code: docs, process, orchestration, runs daemon, monitor, research notes, maps, Run issues | #495, #490, #486 |

If a change is A but also touches selection, loop control, evaluation values or termination, it is B.

## 2. The test per kind, and its time

| kind | PoB-free tests | PoB test | time | NEVER |
|---|---|---|---|---|
| A | rail / unit tests: the forbidden value refused, the allowed one accepted | the trace counter (#498) on a replay-bench pass of 1-2 delivered builds where the option is legal: `generated(x) > 0 and evaluated(x) > 0`; for a restriction `evaluated(forbidden) = 0 and output(forbidden) = 0` on every build; one witness fixture where x is the known-best move | **minutes** (one pass on 2 builds, 2-5 workers) | a before/after set run; a metric gain as proof; "a lower median = failure" |
| B | a test that encodes the defect (invariant or differential), PoB-free where the defect allows | D84's bench: `replay_bench.py --move <m>` on the smoke six delivered builds, base and head at one seed, per-build paired deltas and structural counts | **21-25 min per side** on 5 workers (about 50 min for base + head) | a per-ticket paired set run, unless the bench ALERTS (a build under -15) or the whole loop changes: then 14 builds x 1 seed (~5 h at 3 workers), a further seed block only by a rule written before it |
| C | the suite | identical PoB call transcript base vs head (`replay_bench.py --record-calls`, `compare_calls.py`) and finals equal to the digit (D95); until #493 lands, the first-difference clause of #35/#42 | **about 25 min per side** on 5 workers | tolerating any difference: a difference means the change is A or B |
| D | the suite + C's transcript | interleaved base/head timings on one host | under 1 h | a quality claim |
| none | the suite (`pytest`, PoB-free, ~14 min for the whole suite in the merge command) | none | 0 PoB-hours | any PoB job |
| main | - | the weekly core run: `python scripts/benchmark.py --set core14 --gear wishlist --seed 4 --seeds 3 --workers auto`, one `runs submit --no-issue` line each Monday, P2, pinned at main, named `P2-core-<dd.mm>` by `submit` (#578); read paired per reference against the previous core run: `python scripts/weekly_report.py --core P2-core-<dd.mm> --previous <the previous core run>` (writes `report-weekly.md` into its folder, gates nothing) | **hours set by the slots the runs daemon gives it** (`--workers auto`, resolved at start to the free room: about 6 h at 7 by day on an empty PC; D113 amd 2), once a week | judging a ticket by it; "rerun until green" (one fresh seed block on an alert, then revert if confirmed) |

What a paired set run costs, for the record: one half of core14 x 3 seeds = 14 h 10 min at 3 workers; one half of
the smoke six x 3 seeds = 11 h on the laptop. The smoke set's own A/A noise is -11.5 points at the median, so such a
pair cannot see the 1-10 point effects a ticket claims; that is why no ticket is judged by one (D113).

## 3. Who does what

- **The brain** writes the kind into the ticket with its acceptance rows (the numbers the closing comment must show)
  and submits the weekly core run line on Monday.
- **ORCH** refuses a paired set run for a kind-A, C, D or none ticket (it re-specs the ticket, a one-line comment,
  and goes on); for kind B it runs the bench first and submits a set run only on an alert, with the alert's numbers in
  the submit comment. A worker never submits a PoB job of its own (`docs/agents/runs.md`).
- **The closing comment** names the kind and shows its numbers: A = the move x class counts of the pass and its
  duration; B = the per-build paired table of the bench (gain, seconds, counts); C = "identical, N calls, finals
  equal"; D = the timing table; none = the suite line.

## 4. When a build goes to the owner (a Reading, `GLOSSARY.md`)

The owner reads finished PoBs for the errors numbers cannot show (a nonsensical item, a dead node, a flask that
makes no sense). A reading request names the folder, the exact files (the best seed per reference with its % of the
author) and what to look at, never a folder alone. He is asked in exactly these cases:

- **After every weekly core run**: the best-seed build of every reference whose median moved against the previous weekly core run
  by more than that reference's own spread, and of every reference a rule merged that week touches (the rule named).
- **After a kind-A rule lands**: one build from the trace pass where the new option was picked (the witness), so the
  feature is seen in a real build, not in a count.
- **When an audit cannot judge**: a new kind of error the brain suspects; the reading's verdict becomes an audit
  check (`GLOSSARY.md`, Reading).
- **Never** for kind-B or kind-C proofs (numbers decide), for fillers, or for single seeds of a run.

## 5. Commands

```bash
python scripts/machine_load.py --need 5 --role other
python scripts/replay_bench.py --builds "artifacts/benchmark/<run>/*.pob.txt" --move picks --seed 1 --workers 5 --tag b<issue>-base --record-calls artifacts/proof-<issue>/base
python scripts/replay_bench.py --builds "artifacts/benchmark/<run>/*.pob.txt" --move picks --seed 1 --workers 5 --tag b<issue>-head --record-calls artifacts/proof-<issue>/head --against b<issue>-base
python scripts/compare_calls.py artifacts/proof-<issue>/base artifacts/proof-<issue>/head
```

Longer than ~5 min or wider than 1 slot: through `python scripts/runs.py submit`, pinned (`docs/agents/runs.md`).
