# Sessions: what this repo adds

Local counterpart of `docs/agents/sessions.md` (issue #148, D109). The core file holds the new-chat rule, the
follow-up and the cost rules; below are this repo's own: the opening line, the keymaster, the whole **Limit handover
protocol** (the run queue, the campaigns, the handover file) and the measured cost numbers. Every block quoted stood
in `docs/agents/sessions.md` before the split and binds exactly as it did.

## The header

> Moved from the ROADMAP's "Chat / session protocol", "Limit handover protocol" and "Model / cost protocol" on
> 2026-09-26. Who does what is CLAUDE.md "Roles" and the protocols `docs/agents/brain.md`, `orch.md`, `keymaster.md`
> (orchestration v2, #45). Which chat resets how: the brain by the owner's /clear, when the brain proposes it (this
> section's follow-up rule); one ORCH works every ready issue in parallel through its subagents (`docs/agents/orch.md`, D104); the keymaster
> never clears itself, the owner clears it when it grows. "The lead" below is the brain.

## A new chat: the opening line and the dated rules

> - A new chat opens with: "Продолжаем poe-junkroan-v2. Прочитай CLAUDE.md, GLOSSARY.md, открытые `wayfinder:map`
>   issue и docs/STATE.md, проверь `git log -5`, `gh issue list`, и продолжай."
>
> - The lead asks the owner to open a new chat only when all of these hold (the owner's rule, 2026-09-15, restated
>   2026-09-18 after a switch was proposed with tasks still running): the app's background-task panel is EMPTY -- the
>
>   `artifacts/runs/queue.log` and the current run's `.out`.
>
> - The hand-off (the owner, 2026-09-16; the copy-block form since 2026-10-15, #1086): when the lead asks for a new chat
>   it ends with a copy block: one fenced code block holding one start line, `/wayfinder <N>`, never `/clear`. The state
>   (what runs, the queue, the rules) is in `docs/STATE.md` and the tickets, never in the pasted text.

The owner's hours at the PC, and the language every hand-off is written in:

>   at the PC: weekdays 09:00-01:00, weekends 11:00-01:00 (never at night). About once a day, preferably right after a
>
>   In Russian; the copy block holds one start line and nothing else.

The machine's runner here is `run_queue.py`, relaunched through WMI; the watchers re-arm from
`artifacts/runs/queue.log`.

## Limit handover protocol (the owner, 2026-09-16)

The whole section, verbatim:

> When the owner says the lead's limit is about to run out, the lead does this once, then stops; a cheaper session keeps
> the machine busy until the reset without doing any logic. First done 2026-09-16.
>
> 0. **Find the moment, do not stop at once (the owner, 2026-09-20: "always reason like this").** ASK the owner how much
>    of the lead's limit is used and how the other weekly limits stand, then propose the most efficient moment to hand
>    over and the way to the reset. The reasoning, as a table for the owner: a long run snapshots the code when it
>    STARTS, so what matters is which code in flight changes BUILD numbers, when each piece can be merged (only the lead
>    merges), and how many hours of queued runs would go stale without it (say it in hours: "the template campaigns,
>    34 h"). Put no-regret runs first (a baseline smoke that every later comparison needs) so the machine works while
>    the code lands; start the campaigns only on the final code; a CANARY (one or two full builds through the new code
>    paths) runs before any campaign that follows a fresh merge. Name a fallback if a worker is late (filler seeds on
>    the baseline code in front of the campaigns) and a HARD CEILING of the limit (93% used) at which the handover
>    happens as it stands -- notify the owner when the ceiling is hit and list which runs go on unmerged code. Spend
>    nothing on features that touch no run of the window when the other limits are short too. Between notifications
>    stay silent: every message costs the limit being saved.
> 1. **The window.** Hours from now to the reset the owner names (write it to `artifacts/runs/reset_at.txt` as
>    `YYYY-MM-DD HH:MM`).
> 2. **The plan: a fixed list of runs, counted in builds.** In priority order: proofs of pending rules (smoke set x 3
>    seeds), the campaigns (`--set new18`, `--set core14`), rule pairs (with / without a flag), extra seeds
>    (`--seed 4 --seeds 3`). Hours per run = builds x ~88 min a build / workers (smoke-frozen's pace;
>    `scripts/run_progress.py` computes it). Fill the window plus 10%; `run_progress.py` must say "covers the reset".
> 3. **Gates are lines in the queue, not judgements.** A change whose proof runs during the window gets
>    `scripts/compare_runs.py <control> <candidate> --min-delta -5 --revert-commit <hash>` queued right after its proof
>    run: PASS keeps it, FAIL reverts it before the campaigns start. The working tree must be clean at the handover (the
>    revert needs it).
> 4. **The handover file** `docs/handover/<date>-<model>.md`: the plan table (run, command, hours, what it is for, the
>    issue it serves), the mechanical rules (runner alive check; a failed run re-queued once; after every run a block in
>    the Backlog with rc, report path, the compare table verbatim, `control:` named; never a reading, rule, code, ADR,
>    `GLOSSARY.md` or issue edit; commits of this file only), and the **Backlog for the lead** (one checkbox per run: what
>    the lead does with it on return). `docs/STATE.md` gets one line pointing at the file; memory gets one note.
> 5. **Transparency.** [#45: no hourly posts and no `/loop`: the keymaster posts on the owner's question and on events
>    that need the owner (`docs/agents/keymaster.md`); the heartbeat file below stays, it costs no tokens.] A detached
>    heartbeat (`junkroan.exe scripts/run_progress.py --every 900`, launched with the WMI
>    command) rewrites `artifacts/runs/progress.md` every 15 minutes: builds finished / total per run, alive /
>    STALLED?, ETAs, plan end vs reset, first line "now HH:MM" as the freshness stamp. The keeping session posts that
>    file every hour on the hour and after every run (a `/loop 1h` whose prompt is "post artifacts/runs/progress.md";
>    never a silent hour). The owner watches the queue through that file, never through the app's task panel (the runs
>    are detached processes and never appear there). Lesson of 2026-09-16: a 2-hour "check, post only if something is
>    wrong" rule produced a 4-hour silence.
> 6. **The prompt** for the keeping chat (the keymaster since #45): the copy block, one fenced code block holding one
>    start line; the state (the first check, what runs, the queue with ETAs, the rules, the reset time) is in
>    `docs/STATE.md` and the tickets, never in the pasted text. Russian.
> 7. **On return** the lead reads the Backlog top to bottom before `docs/STATE.md`, records every run on its issue
>    (numbers, rules closed, the reading request), then continues.

## Cost: the measured numbers

> - Measured for #45 (20 old lead chats replayed, cost from cache reads, which are ~97-99% of tokens): no resets 637 $;
>   autocompact at the default ~900k 602 $; at 400k 319 $; a clear at every task boundary 141 $; a clear only above
>   150k 241 $; a clear at every boundary plus a 400k autocompact 138 $ for 9 mid-task compactions. Hence ORCH clears
>   after every issue and autocompact stays at the default (~90%). A subagent spawn cost ~60k tokens before any work
>   (the 34 KB CLAUDE.md was ~9k of it, likely paid twice when a role file ordered a re-read), an `Explore` on Haiku ~24k;
>   the target after #45 is <= 30k.

## Where the rules came from

- The three protocols moved out of the frozen ROADMAP: 2026-09-26.
- Orchestration v2, one ORCH holding every ready issue: #45, D104.
- The new-chat conditions: the owner, 2026-09-15, restated 2026-09-18.
- The copy block (one start line): the owner, 2026-10-15 (#1086). The earlier ready-to-paste follow-up with a context
  block: the owner, 2026-09-16, superseded by it.
- The limit handover protocol: the owner, 2026-09-16; step 0 ("always reason like this"): the owner, 2026-09-20.
- No hourly posts and no `/loop` since #45; the 4-hour silence that killed the 2-hour rule: 2026-09-16.
- The cost table: measured for #45 over 20 replayed chats.
