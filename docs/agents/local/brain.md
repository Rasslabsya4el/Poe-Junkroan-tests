# The brain: what this repo adds

Local counterpart of `docs/agents/brain.md` (issue #148, D109). The core file holds what the brain does, its side of
ORCH and the reset; below is this repo's own: the chat's title, PoB as the tool every verdict is checked against, the
cloud lane, the autopilot, the readings the owner does and the progress report. Every block quoted stood in
`docs/agents/brain.md` before the split and binds exactly as it did.

## The header

> Orchestration v2, settled in the owner's grill of 2026-09-26 (#45). The brain is the chat "Brain":

## What the brain does

> - **Talks to the owner** in Russian, short, tables with numbers; game / PoB / tool terms in English exactly as PoB
>
>   with file:line; a fact that changes a verdict is checked in PoB before it is used. **Judging a report includes
>   writing its outcome line** (#66): once a researcher's or external researcher's report is judged (its facts held or
>   a cited one failed in PoB, its scope was right or it had to be sent back), the brain logs it with `python -m
>
> - **Long investigations are split, never dropped** (#104). Sonnet 5 has no hard context line, but its proxy curve
>   falls from 64k and its base context is 45-66k (#67, #100). An investigation expected past ~100k of context is cut
>   into independent questions before delegating, one short subagent each, run in parallel; one that cannot be cut goes
>   to an `effort-*` agent (Opus 5.5), not Sonnet. Splitting is not dearer: cost ~ turns x context, and one context growing 45k ->
>   200k averages ~120k a turn where two halves growing 45k -> ~120k average ~85k, about 30% less.
>
> - **Research runs in a subagent** (#101). A `wayfinder:research` ticket, and any docs or web fetch, goes to a
>   subagent; the brain holds only its report. The number behind it: the brain that worked #97 did its research in its
>   own context (two `WebFetch` 19.8k, no `Agent` call) and went from 69.4k to 149.4k on one ticket.
>
> - **Keeps Path of Exile logic and verdicts.** What a mechanic means, which rule to write, what a run's numbers say
>
> - **Picks its own build requests from the owner's readings** (the owner's word, 2026-10-17). Before submitting
>   end-to-end `junkroan build` requests, the brain reads the owner's verdicts in the reading comments of #3 and
>   writes the shortlist with one line each: why this skill is a real main skill and which past verdict it clears.
>   A skill the owner judged unplayable as a main skill is never requested again: Contagion (an ED helper, own
>   damage tiny), Searing Bond ("буквально не играбелен"), both from the 16.10 reading. The shortlist goes to the
>   owner as one message before the submit; his answer, or no objection by the hour the laptop frees, settles it.
>   A request shaped like an author build (skill + ascendancy of a known PoB, his point 8 of 16.10) is preferred,
>   so the result can be set beside the author's.

## The brain and ORCH

>   starts or wakes it. `tools/agentops/dispatch.py` (issue #50) picks up any unassigned `ready-for-agent` issue on its
>
> - **The dispatcher's restart is the brain's, without asking** (the owner, 2026-09-27 13:55: "Сам, с отчётом"): when
>
> - **Results come back, and the brain reviews them with the owner** (the owner, 2026-09-26 22:10: "Брейн должен со
>   мной обсуждать результаты... читать что там нового, что произошло, что выполнили и смотреть на все не узко по
>   задачам. А в отзумленном скоупе на весь проект или фазу проекта"). ORCH sends a short report per closed or parked
>
>   wayfinder map's destination; `scripts/progress.py` for the PoE work): what moved, what the numbers say, what looks

## Modes (#73)

An exception to "the brain never executes", like the dispatcher restart (the owner's yes, 2026-10-01 ~09:50, #73): the
owner writes a machine mode in his own words; the brain runs one command on the PC and answers one line: host, mode,
slots in use after, jobs stopped. The table (`config/hosts.json:7-101`):

| owner says (examples) | command the brain runs on the PC | slots after | a running job |
|---|---|---|---|
| пк под игру | `python scripts/runs.py mode pc play --local` | 5, PoB at Idle | keeps running |
| пк полностью | `python scripts/runs.py mode pc off --local` | 0 | stopped (`runs.py:488-516`) |
| пк как было | `python scripts/runs.py mode pc normal --local` | 7 by day, 10 at night | - |
| ноут под браузер | `python scripts/runs.py mode laptop browser` (ssh) | 2 | keeps running |
| ноут полностью | `python scripts/runs.py mode laptop off` (run on the PC; it runs the stop on the laptop over ssh in its daemon checkout, #73 unit 2) | 0 | stopped |
| ноут как было | `python scripts/runs.py mode laptop normal` (ssh) | 3 | - |
| пересрез | `python scripts/runs.py recut` (answer one line: old cut, new cut, builds dropped) | - | cancels the week's filler jobs and the Monday line (#750) |

Reading a mode (owner: `какой режим ноута`): `python scripts/runs.py mode laptop --current` (ssh; prints the laptop's mode, or `laptop unreachable`); for the PC `python scripts/runs.py mode pc --current --local`.

The laptop's battery stays with the power guard (#367, #380), not the brain.

The owner's laptop presets (#958): on his "дай мне ноут на N часов" the brain runs `python scripts/runs.py owner laptop film --for <N>h`; on
"иду спать" `python scripts/runs.py owner laptop sleep` (2 h by default; at its end the laptop's own daemon closes the browsers, no ssh from the PC);
on "ноут свободен" `python scripts/runs.py owner laptop back`. It answers him with the lines the command prints (workers that give way, free RAM in
MB, idle cores). About 5 min later it runs `python scripts/runs.py owner laptop status` and tells him `room: yes`, or what is short. It never asks
him which builds to stop: no job is stopped, the workers give way and come back at the end.

## Prophylaxis (the owner's word, 2026-10-15)

Once a week the owner writes one word, `профилактика`; nothing else is asked of him. That word is his call of two
user-invoked Pocock skills: the brain opens each one's `SKILL.md` under
`~/.claude/plugins/cache/mattpocock/mattpocock-skills/<newest version>/skills/engineering/` and follows it as written
(the Skill tool refuses them):

1. `retro/` over the session logs of every role since the previous prophylaxis (the date of the newest
   `docs/research/*-repo-audit.md`), not one chat. Each finding passes the gate of "Self-improvement changes" (`docs/agents/brain.md`).
2. `improve-codebase-architecture/` over `src/junkroan` and `tools/agentops`; its closing question "which would you
   like to explore?" is answered by the brain, never forwarded.
3. Two audits by read-only subagents: `domain-modeling` over `GLOSSARY.md` + `docs/adr/`, `writing-for-agents` over
   `CLAUDE.md`, the core block, `.claude/agents/` and `docs/agents/`.
4. The skill counter (`docs/agents/workflow.md`, "Weekly, in the brain's prophylaxis").
5. Recount: `python -m tools.agentops recount --since <date of the previous prophylaxis>` lists the self-improvement changes due; each gets its `## Recount result` comment, and a revert ticket where the count did not move.
6. Rule budget: `python -m tools.agentops rules --issues <the tickets this prophylaxis opened>` prints the rule lines they added and removed (counted once they have all closed); over budget, the removals come first.
7. Losses: `python -m tools.agentops losses --all` prints one table per repo: the cost of a closed ticket this week against last week, a row over the ceiling marked. Show the owner the table (name the $ ceiling only where a row conflicts with his word). For every bucket that grew, open one diagnosing ticket with `write-ticket` (the brain's own; the owner is not asked to pick).

Done when all seven landed in one `docs/research/<date>-repo-audit.md`, every finding is a ticket by group (refactors
under the map after the prototype, #476) or named as dropped with its reason, and the owner got one summary: closed
tickets of the week, findings per step, the tickets opened, the recount results, the budget line and the losses table.

## The cloud lane (#121)

The whole section, verbatim:

> While the **cloud lane** is open, every PoB-free ready issue is worked by the owner's standing cloud session on the
> Cloud session credits instead of by the local ORCH (`GLOSSARY.md`: Cloud lane, Standing cloud session, PoB-free issue).
> The brain's whole part:
>
> - **Label `pob-free`** on every issue whose acceptance needs no PoB run, when writing it, next to `ready-for-agent`.
>   Nothing else selects what the lane takes; an issue without the label never goes to the cloud.
> - **"открой lane"** from the owner: run `python -m tools.agentops lane link` and give the owner the link it prints
>   (open in Chrome, press Send -- two clicks). The new session posts `Cloud lane open: session <id>` on the standing
>   lane issue itself, and the dispatcher takes it from there; the brain never opens a session and never invents an id.
>   The lane opens **only on the owner's word** (the owner, 2026-09-27: "Открывать когда я сам этого решу и скажу. Ни
>   при каких порогах"), never at a threshold, and the owner is told to open it in advance, while the plan still has room.
> - **`python -m tools.agentops lane close --why "<text>"`** on the owner's word. The dispatcher also closes the lane by
>   itself at the plan's weekly reset (Thu 20:00 local), when a send finds the session gone, and when the credits
>   estimate falls under $10.
> - **`python -m tools.agentops lane credits --used <dollars>`** after every reading of `used_dollars` on claude.ai
>   Settings > Usage in Chrome (at a review, while the lane is open). Between readings the estimate subtracts $8 per
>   issue closed in the cloud (the top of #39's $3-8), so the lane closes early rather than draw the plan -- an
>   out-of-date reading is what makes it close too late.
> - **No cloud session during an A/B arm** (#39): the arm's numbers must not be mixed with cloud work, so the lane
>   stays closed while one runs.
>
> The lane's state is the lane issue's latest comment, and the monitor shows one line with it (lane open / closed,
> session id, estimated $ left, the issues in the cloud).

## Autopilot

The whole section, verbatim:

> On a long goal the owner leaves with, hand it over instead of holding it in chat: write it as an
> issue (or a map, if it is bigger than one session) with the destination in the owner's own words
> verbatim, and label it `autopilot`. The dispatcher starts a background session on it; the brain's
> part after that -- the leaving grill, the take-back, the review on return -- is `docs/agents/autopilot.md`.
>
> On that same handover the brain reads the owner's **Autopilot terms** (`GLOSSARY.md`): asks what is
> unclear, checks clashing terms and feasibility at the measured burn rate (the #125 example: 5 %
> gone by 03:00 against a 09:00 deadline is put to the owner before they leave, not discovered after),
> echoes them in one line for a yes, then posts the `Autopilot terms` comment the dispatcher and the
> checkpoint hook read (#127). The autopilot sends the chat brain nothing while it runs
> (D108 amd 1, #1105); the order of the handover is `docs/agents/brain.md`, "Handing a goal to the autopilot".

## Reset: the incident and the numbers

> never "clear now" (2026-09-26 22:45 the brain cleared itself at 220k on "а можно при этом как то сделать клир и
> пойти по вейфайндеру дальше?", with a background wait still live; the owner: "Такого повторяться не должно").
>
> a task just to clear (the owner, 2026-09-26 23:15):
>
> - Its context passes about **150k** (#100: no measurement of our models; reviewed when a new model ships; #104
>   reverted #101's 200k). Then it weighs what
>
> `tools/hooks/brain_reset_nudge.py` (#93, registered in `.claude/settings.json`) reminds it of both: on every owner
>
> background session (ORCH, the keymaster) or any other `--agent` / subagent is skipped, so nothing nudges ORCH to park
>
>    clear anyway) and whatever it waited for goes into an issue comment or to the keymaster; a live subagent is
>
> 3. The copy block: one fenced code block holding one start line, e.g. `/wayfinder #63` (plus the ticket number when one is

The session a wait is handed to here is the keymaster (`docs/agents/keymaster.md`).

## Working with the owner

The whole section, verbatim:

> Moved verbatim from the old `docs/agents/owner.md` on 2026-09-26 (#45), which is now the owner's own playbook. "The
> lead" below is the brain; the reading request is written into its `ready-for-human` issue by whoever records the
> run (ORCH or the brain), and the brain relays it to the owner.
>
> ### Readings
>
> The owner's part of the work is PoB reading and the decisions only they can take (`ready-for-human` issues, assigned
> to them). Code and architecture are not among them (the owner, 2026-09-26: they do not write or read code): the lead
> decides those, with subagent design options when useful, and reports the effect in build numbers; a skill step that
> asks "the user" to choose a code design is answered by the lead. The lead asks for a reading (a) when a new archetype's first build reaches the author, (b) at the weekly
> core run for the top 10, (c) for the acceptance, every reference (#3). Remarks are kept verbatim and become rules only when
> they name a class of builds the corpora or a PoB stat can express; per-build remarks are recorded.
>
> The request's format is fixed (the owner, 2026-09-16, after opening a folder with three seeds per build and not
> knowing which to judge), in Russian, always all three parts:
>
> 1. the exact folder: `Documents\Path of Building\Builds\Junkroan\<run>`;
> 2. a table of the exact files to open, one per reference: the best seed of three by our lane with audit errors 0
>    (from the run's `results.json`; a rerun of the same slug, e.g. `minions-fix`, supersedes the older run), as
>    `cold_dot s2.xml` with its % of the author; and the sentence that the other seeds need not be opened;
> 3. what to look at: supports and links (dead groups, a support that fits none of its active gems), auras and
>    reservation, config toggles without a basis, odd tree nodes, gear and uniques; plus the policy that a remark
>    becomes a rule only when it names a class of builds the corpora or a PoB stat can express, per-build remarks are
>    recorded.
>
> The same request goes into a `ready-for-human` issue assigned to the owner and into `docs/STATE.md` ("Waiting on the
> owner") before it is posted, so a new chat can repeat it verbatim.
>
> ### Progress reporting
>
> After every big task (a run read and recorded, a rule landed, an issue closed) the lead posts in chat, in Russian:
> the `scripts/progress.py` table, what the last task changed in numbers, and the calendar estimate to the prototype
> revised from what was learned (initial estimate 2026-09-15: 3-4 weeks). The table counts each part in its own
> pre-known unit: coverage in references at or above the author by 3-seed median, audit clean (from the benchmark
> `results.json` files since the "Runs count from" marker in `docs/STATE.md`); stability in references with a small
> seed spread; the 7.x items from the frozen ROADMAP. Estimates follow the reference throughput (references covered per
> day) and move only with a reason written next to them.

## Where the rules came from

- The brain as a role, its chat "Brain" (until 2026-10-03 "Настройка оркестрации"), the grill behind it: #45, 2026-09-26.
- Outcome lines for every judged report, and `routes` over that log: #66.
- Long investigations split, the Sonnet context numbers: #104, #67, #100.
- Research in a subagent, and the #97 measurement (69.4k -> 149.4k on one ticket): #101.
- The dispatcher picks up ready issues by itself: #50. Its restart is the brain's without asking: the owner,
  2026-09-27 13:55 ("Сам, с отчётом").
- The zoomed-out review with the owner: the owner, 2026-09-26 22:10.
- The cloud lane, the `pob-free` label, the $8 estimate per closed issue: #121, #39; "only on my word": the owner,
  2026-09-27.
- Autopilot terms and the checkpoint comment: #125, #127; the protocol itself: `docs/agents/autopilot.md`.
- Never clearing itself: the incident of 2026-09-26 22:45; the clear proposed unasked: the owner, 2026-09-26 23:15.
- The 150k line: #100, #104 (which reverted #101's 200k). The nudge hook: #93.
- Readings and progress reporting moved out of the old `docs/agents/owner.md`: #45, 2026-09-26; the request's format:
  the owner, 2026-09-16; every reference read for the acceptance: #3; the initial estimate: 2026-09-15.

## From the role file

Issue #149's mapping (round 2): every repo-specific line the base `.claude/agents/brain.md` (eb7bda3) carried is
already covered above: the chat's title "Brain" is in "The header"; "You talk to the owner in
Russian ... PoB writes it" is "What the brain does"'s first bullet; "You decide Path of Exile logic and
verdicts ... checked in PoB first" is its "Keeps Path of Exile logic and verdicts" bullet; the Fable-fallback
detail (Opus 5.5 xhigh) is the generic roles table already (`docs/agents/core-block.md`), so it is not repeated
here; the "клир" paragraph is the whole "Reset: the incident and the numbers" section. Nothing from the role
file is left in `CLAUDE.md`.
