# Workflow: what this repo adds

Local counterpart of `docs/agents/workflow.md` (issue #148, D109). The core file holds the flow (issue, worktree,
review, numbers, commit); below are the sections and lines that are this repo's own: PoB as the judge, the machine's
run queue, the benchmark, the audit, and this repo's history. Every block quoted below stood in
`docs/agents/workflow.md` before the split and binds exactly as it did.

## The header

> Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there.
>
> Orchestration v2 (#45) changed who does what: "the lead" below is the brain where it talks to the owner and
> sentences marked **[#45]** are superseded as noted, the rest stands.

The `**[v2]**` markers of the core file are these `**[#45]**` markers.

## Inside "How to work in this repo"

> `ready-for-human` for the owner's; the prototype's acceptance is #1. A
>
> (`code-review` against the issue) **[#1066: `code-review` on every unit diff]**, then the benchmark numbers (principle 6)
>
> and keep `artifacts/runs/queue.txt` non-empty so the machine never idles
> (`docs/agents/runs.md`). When asking the owner for a new chat, hand them the
>
> alone **[#45: the brain does this; one ORCH works every ready issue in parallel, `docs/agents/orch.md`]**. After every big task post `scripts/progress.py`'s table and the
> revised estimate (`docs/agents/owner.md`) **[#45: the brain, procedure in `docs/agents/brain.md`]**;
> Path of Exile logic and every conclusion stay on the lead (the model of the
> main chat: Fable 5.1 until 2026-09-22, Opus 5.5 until #45); subagents of any
> Claude model and effort do the rest **[#45: replaced by CLAUDE.md "Roles" and
> `docs/agents/orch.md` "Models and effort"; the brain is Fable 5.1 high, fallback Opus 5.5 xhigh]**.
>
> parsed by agents into tables. The lead runs the work like a team lead (the
> user, 2026-09-18): it keeps several agents running at once on non-overlapping
>
> issues with evidence. Wall-clock progress is what counts. **[#45: the team-lead sentences are superseded: tokens
> first, but the PoB machine never idles; ORCH takes one issue at a time, parks it on a long PoB run and does the work
> itself unless it is one of the delegation cases in `docs/agents/orch.md`; the brain writes the issues.]**

So here: the machine's work queue is `artifacts/runs/queue.txt` (`docs/agents/runs.md`), the progress table is
`python scripts/progress.py`, and Path of Exile logic stays on the lead.

## The architecture review

> - Every few days, and before a large change to a hot module, run
>   `/improve-codebase-architecture` on the files that change most
>   (`git log --name-only`); a refactor it proposes is proven like any optimizer
>   change: the same builds to the digit, or benchmark numbers.

## The limit handover

> - When the lead's limit runs short: `docs/agents/sessions.md` "Limit handover protocol", step 0 FIRST -- ask the owner how much is left, then
>   propose the most efficient handover moment (which code in flight changes build numbers, when it can be merged, how many
>   hours of queued runs go stale without it; baseline runs first, campaigns on the final code, a canary after a fresh
>   merge, a hard ceiling with a notification). Never just stop, never let a 30-hour campaign start on code known to be stale.

The protocol itself is in `docs/agents/local/sessions.md`.

## Before optimizer code

> - Before writing optimizer code, write the measurement first: what PoB metric
>   proves the change works, on which benchmark build.
> - Keep modules small and pure. `PobSession` is the only stateful thing.
> - One calc is ~0.1 s. Budget for thousands of calcs per skeleton. Prefer
>   incremental mutations (add/remove a node) to full re-apply.
> - When a task needs game knowledge, write a corpus query, not a paragraph.
> - When in doubt whether something belongs in `mechanics/`: if PoB computes it,
>   it does not belong there.

## Judging a change

> - Judging a change: the seed spread is 41.6 points at the median and up to 109
>   (measured, `docs/research/2026-09-18-seed-divergence.md`), so a change is
>   judged only on 3-seed medians (`scripts/benchmark.py --seeds 3
>   --no-variants`). Smoke it first on the six-reference smoke set (18 builds,
>   ~5.3 h on 5 workers, measured on `rules-smoke`), run the full 32 references
>   (the `new18` + `core14` campaigns, ~28 h together) only for what passed the
>   smoke. Chase a lagging reference no further than a general cause; per-build
>   tuning is not a fix.

## Long runs

The core file keeps the detached-process rule; what it does not keep is where a long PoB run goes here:

> and prepare the next fix. **[#45: a PoB run longer than ~5 min or wider than 1 slot goes to the keymaster
> (`python scripts/runs.py submit`, `docs/agents/keymaster.md`); ORCH parks the issue instead of waiting, `docs/agents/orch.md` step 3.]**

## The audit

> - After every search or rebuild: run the audit and open the top PoB builds
>   yourself (supports, auras, config, tree) for logical errors the numbers
>   cannot see. Every new kind of error becomes an audit check and a general
>   rule, never a patch for one build.

## Do not resurrect v1

> - Do not resurrect v1 concepts: rails reports, decision ledgers, hypothesis
>   bundles, proof packets, early-game lanes, skill passports, scaling atlases.
>   If a v1 idea seems needed, check `docs/LEGACY.md` for why it was dropped.

## Where the rules came from

- The whole file moved verbatim out of CLAUDE.md: #45, 2026-09-26.
- Who is "the lead" after orchestration v2, and every `**[#45]**` marker: #45.
- The prototype's acceptance: #1.
- The seed spread of 41.6 points at the median, up to 109: measured 2026-09-18,
  `docs/research/2026-09-18-seed-divergence.md`.
- The team-lead sentences: the owner, 2026-09-18.
- The model of the main chat: Fable 5.1 until 2026-09-22, Opus 5.5 until #45.
- A long PoB run goes through the keymaster and the issue is parked: #45, #48, #50.
