# ORCH: what this repo adds

Local counterpart of `docs/agents/orch.md` (issue #148, D109). The core file holds how ORCH works an issue; this file
holds what is this repo's: **every PoB-run and queue line verbatim**, the machine budget, the measured threshold
numbers, the cloud lane, the monitor, Path of Exile sense, and the history behind each rule. Every block quoted below
stood in `docs/agents/orch.md` before the split and binds exactly as it did. An ORCH working an issue that touches
PoB reads this file, not only the core one.

## PoB runs, the queue and the machine budget

The three rules the core file states in general words, verbatim:

> - **The machine.** A subagent adds nothing measurable to ORCH's own process (`claude.exe` 355 MB before and while a
>   subagent ran, 2026-09-26); its load is what its tools start. So: a subagent whose spec opens a PobSession starts only
>   after `python scripts/machine_load.py --need 1 --role other` says GO (a long or wide PoB job goes through
>   `python scripts/runs.py submit` as always); any other subagent starts while the PC has >= 2 GB free RAM
>   (`Get-CimInstance Win32_OperatingSystem`, `FreePhysicalMemory`); below that the issue waits.

> - **Short PoB calls** (<= ~5 min, 1 slot: `describe_build`, `audit_build`, a runtime test) run directly in the
>   `others` share after `python scripts/machine_load.py --need 1 --role other`, and ORCH waits for them. For a
>   planned burst of them reserve slots at planning time: `python scripts/runs.py reserve --host pc --slots 2 --for 1h
>   --issue N` (`--release <id>` when done).

> - **Long PoB runs are not waited for.** Anything longer than ~5 min or wider than 1 slot:
>   `python scripts/runs.py submit --priority P0|P1|P2 --issue N [--note <text>] -- <command>` (the name `P<prio>-#N` (`-<n>` when it exists) is derived, #578;
>   no `--host`: the default `auto` leaves the job movable, so after 15 min queued on a full PC the rebalancer may move
>   it to the laptop, #594; `--host pc` only for `--workers` >= 5 (`HEAVY_WORKERS`) or a pair a ticket pins to the PC
>   for a measured reason, and then `--note` says which; "paired" (D95) alone is never a host reason, and a replay run (`--against`/`--builds`) names no `--host`, #701). A paired run (D95: base and head on one host) is two
>   submits, neither with a `--host`: the base `python scripts/runs.py submit --priority P1 --issue N -- <base command>`,
>   then the head `python scripts/runs.py submit --priority P1 --issue N --after <base job id> -- <head command>`;
>   the head is placed in the queue of the host holding its base and fixed there (`host_reason` `after:<base id>`,
>   #648), so a base the laptop took takes its head with it, and a head whose base ran on the PC stays on the PC. P0 blocks a
>   merge or a decision ORCH waits on, P1 is an open issue's benchmark, P2 campaigns and exploration. A run that needs
>   another run's output is submitted at once with `--after <job id>` (repeatable, #82): the daemon holds it until every
>   named job has ended rc 0, and nobody has to sit and watch the predecessor. An unrelated job (no `--after`) still
>   starts while a chain waits; a dependent one keeps its place in submit order. If a predecessor ends rc != 0 the
>   follower stays queued for ever and the daemon raises a `held_by_failed_predecessor` anomaly for the keymaster --
>   requeue the predecessor or cancel the follower. Then write the
>   checkpoint with the job id and the acceptance rule ("merge if ..."), remove `ready-for-agent` and your assignment:
>   the issue is parked and its place is free for the next ready issue. When the job ends the runs daemon (#48) posts the result into the issue
>   and re-adds `ready-for-agent`; the issue is then an ordinary task: judge the run by the rule, merge or send back.
>   Until #48 lands, also send the keymaster one line "job <id> for #N submitted" so it starts the job through
>   today's queue.

Local addition (#842, #873): a "busy machine" row in a delegation prompt is written as `scripts/burner.py` with the host (laptop) or the night window 01:00-08:00, never as a count of spinners (no CPU burner on the PC between 08:00 and 01:00, `docs/agents/machine.md`); the wording check is `tools/agentops/delegation_load_check.py`.


Local addition: A bisect or probe job whose exit code is the reading is submitted with `--rc-is-reading`, so its failing pins start no keymaster (#501); until a host's daemon runs this code, wrap the command so it exits 0 and prints pytest's rc.

And the machine-budget line elsewhere in the file:

> - **Provisional decisions** (#113). ... A veto runs the whole test suite, so run it after
>   `python scripts/machine_load.py --need 1 --role other`.

The protocols behind them: `docs/agents/runs.md` (the queue), `docs/agents/keymaster.md` (who owns it),
`docs/agents/machine.md` (the budget, the hosts, the laptop).

## The test per kind (D113, 2026-10-02)

A ticket in `area:builds` names its kind before any PoB job (`docs/TESTING.md`): A a search-space rule, B a loop or
evaluation fix, C a refactor, D speed, none. ORCH refuses a paired set run (`benchmark.py` over a set, before and
after) for a kind-A, C, D or none ticket: it re-specs the ticket in one comment (A = rail tests + the trace counter
on a replay-bench pass of 1-2 delivered builds; C = identical PoB call transcript) and goes on. For kind B it runs
D84's bench first (`replay_bench.py --move <m>` on the smoke six, base and head, one seed, about 25 min each) and
submits a set run (14 builds x 1 seed) only on an alert (a build under -15), with the alert's numbers in the submit
comment. One base per main commit serves every head branched from it (#468 refuses an identical pinned run). The
closing comment names the kind and shows its numbers. The queue cut of 2026-10-02 (#485) is the precedent: 28 pair
halves cancelled, the proofs and benches of the same afternoon took 25-50 min each.

## Live rows without TEST RUNS (#73)

The chat "TEST RUNS" is retired; both runs daemons run the queue and the per-anomaly keymaster (`anomalies.py`) stays
as it is. No live row is addressed to "TEST RUNS". A live row of an acceptance table is run by one of two routes:

- A live row that is a PoB job goes through `python scripts/runs.py submit --priority P0|P1|P2 --issue N -- <command>` and the issue parks (the daemon's hand-back
  re-adds `ready-for-agent`).
- A live row that is not a PoB job (a mode change, a drill on a host, a check on the laptop) is run by ORCH itself
  (ssh to the laptop allowed; detached when it waits on the host's state), and ORCH writes its result into the issue.

Before running a live row, ORCH re-reads the issue's comments (the brain's note, #73, 2026-10-01 10:03): a withdrawn
spec stops it. The case: ORCH parked #382 on its drill at 09:38 although the brain had withdrawn the spec at 09:25;
the keymaster ran the drill at 09:43 on that request, and the laptop stayed off the network.

## The merge suite: PoB-free by default (#198)

`docs/agents/orch.md` "Merging" now names the settings keys generically; here is what they hold in this repo.
Every test that opens a `PobSession` or the headless PoB runtime carries the registered pytest mark `pob`
(`pytest.ini`), on top of its existing `skipif`. `config/orchestration.json` sets `merge_suite` to the whole
suite minus `slow` and `pob` (`python -m pytest tests -q -p no:faulthandler -m "not slow and not pob"`), and
`merge_suite_env` to `{"JUNKROAN_NO_POB": "1"}`, which `tools/agentops/merge.py` applies to every suite run --
even one passed through `--suite` -- so a `pob`-marked test cannot start PoB from inside a held merge lock
regardless of what its own selection matches by name. A merge whose issue does need a PoB-backed suite (an
issue not labelled `pob-free`) sends that suite through `python scripts/runs.py submit` instead, per `orch.md` "Merging", never
inside the merge command. Found by #198: the merge of a `pob-free` issue had run `-k "... or port or ..."` by
hand and `port` also matched `support`/`import`/`report`, starting PoB inside the lock for ~5 min.

`pytest.ini`'s own default selection (`addopts`) is PoB-free too since #200, so a worker's own plain `pytest`
call starts no PoB either, and the delegation prompt of an issue without the label `pob-free` names its test
command with the explicit `-m` that keeps the `pob`-marked tests in (`-m pob` or `-m "not slow"`).

## The merge suite runs only the affected tests (#690)

With `merge_select_tests` true in `config/orchestration.json` a merge's pytest suite runs the tests a test-dependency map
selects for the batch's diff (`tools/agentops/test_select.py`, `select_for_diff`) plus every test of an added or changed
`tests/test_*.py`; line 1 of the suite out and the merge.log line read `selected N of M (map <commit8>)` or
`full suite: <reason>` (no map, no green full run, map older than the last green run, a changed file unknown to the map
outside `docs/`, a selection failure). The full suite runs on main after each landing, outside the merge line:
`python -m tools.agentops full-run [--commit <sha>] [--detach]` (`tools/agentops/full_run.py`; one at a time, a landing
during a run sets `var/agentops/full_run.pending`; it waits while the merge line is busy; it rebuilds the map in
`var/agentops/test_map/` under pytest-testmon and the audit-hook plugin, and a red run opens one `needs-triage` issue naming the
failing ids and the branches landed since the last green commit). Measured by #681: median 4.7 % of the suite selected; the risk is an interaction failure outside the diff, which only the full run
on main catches. A flaw seen in a selected run is answered by the full run, never by widening the selection ad hoc. With the laptop route of #685 the suite out's first line is the host line and the selection line is the second.

## The context threshold: today's numbers

> **The context threshold T = B + N x X** (grill Q22, D104). B = ORCH's context right after its start, X = the context
> one issue adds, N = the issues this context has taken (held now plus finished in it). Measured on 2026-09-26 by
> `python scripts/token_meter.py --orch-threshold` over the six finished one-issue ORCH contexts (`orch #49`, `#6`,
> `#24`, `#58`, `#53`, `#60`): **B = 45.9k, X = 50.7k**, so T = 96.6k for N = 1, 147k for 2, and **150k for any
> larger N: T never exceeds 150k** (#104, the context line for Opus 5.5 from #100; over 150k ORCH claims nothing new
> and finishes what it holds, as over T). X was measured while ORCH still did each issue's code itself; with the code in subagents and ORCH holding
> only their reports (<= 30-60 lines) X should fall -- the brain reruns the meter weekly (`--since` a week ago) and
> rewrites these numbers.
>
> **The hard line is 400k** (`context_hard_line`, #1120): at 150k ORCH takes nothing new and finishes what it holds;
> it parks a ticket for context only past 400k, or for a real wait (merge, run, blocker). A parking checkpoint says
> why: `context` with the number, or the wait. T's ceiling and the claiming line stay 150k.

## The header and the routing, with their references

> Orchestration v2, settled in the owner's grill of 2026-09-26 (#45). ORCH is Sonnet 5.5 high, rollback Opus 5.5 high (one background session started by
>
> (D104, #60), and closes each with its numbers; it messages the brain (`docs/agents/brain.md`) only for `needs-info`.
>
> Exactly one ORCH session exists at a time (more than one ORCH is chaos; the owner, 2026-09-26). It holds as many
>
> `Take every ready issue (ready now, in dispatch order: #54, #55, ...). Follow docs/agents/orch.md.` This is the whole
>
>    blocker (`gh issue edit N --add-blocked-by M`, #53); a blocked issue keeps its label and is simply not listed.
>
>    "Done when", merge, close with the numbers, and write its outcome line (#66: `python -m tools.agentops outcome
>
>    can take into the freed place, unless the context is over T. A dispatcher wake (#137: a message naming a ready
>
>   point, not its ceiling: it is recomputed from the outcome log (#66), so it drifts as `routes` shows a route's
>   names exactly one `#N` (the token meter, #47, and the monitor attribute cost and rows by it):
>
>   | subtle optimizer / pipeline / worker-Lua code | `worker-strong` (Sonnet 5.5 high), own worktree | <= 30 lines |
>
>   **Long investigations are split, never dropped** (#104). Sonnet 5 has no hard context line, but its proxy curve
>   falls from 64k and its base context is 45-66k (#67, #100). An investigation expected past ~100k of context is cut
>   into independent questions before delegating, one short subagent each, run in parallel; one that cannot be cut
>   goes to an `effort-*` agent (Opus 5.5), not Sonnet. Splitting is not dearer: cost ~ turns x context, and one context growing
>   45k -> 200k averages ~120k a turn where two halves growing 45k -> ~120k average ~85k, about 30% less.
>
>   numbers; ORCH reads the diff stat and the hunks that change build numbers. `code-review` (the skill) on every
>   unit diff (#1066). ORCH has `Skill` in its `tools:` list again (#104, reverting #102): merging
>   used as shipped; the catalogue costs 5.7k of its base context, so B's bar is <= 41k. A verdict-changing claim of a subagent is checked in PoB before use. A context ends
>   only when none of its subagents is still running. **Judging a report includes writing its outcome line** (#66):
>
> - **Provisional decisions** (#113). ORCH runs `python -m tools.agentops veto N` / `python -m tools.agentops approve N`
>
>   rebased onto the current `main`, the suite green before and after. Optimizer changes merge with benchmark numbers
>   (principle 6; 3-seed medians, smoke first: the "Judging a change" bullet of `docs/agents/workflow.md`). After every
>   prompt always branches from the pushed head, never from a local `main` that outruns `origin/main` (#78). Close the
>
> - **Memory belongs to the brain.** ORCH never writes, edits or deletes the auto-memory (`MEMORY.md` and its files;
>   the owner, 2026-09-26, after `orch #49` edited it). A lesson or preference worth keeping goes into the checkpoint

The "Judging a change" bullet is now in `docs/agents/local/workflow.md`: 3-seed medians, smoke first.

## The cloud lane

> 1. ... **An issue labelled `in-cloud` is not yours** (#121): the owner's standing cloud session is working it on the
>    Cloud session credits, so the dispatcher never lists it -- never claim one, even when re-reading the queue by
>    hand (`gh issue list --label ready-for-agent --search no:assignee` shows it; the label is the answer). It comes
>    back to the local queue by itself, with the label removed, if the cloud lane closes with the issue unfinished.

## A lookup never walks `artifacts/**` (#727)

A `find`, `grep`, `rg` or glob, ORCH's own or a subagent's, starts at a folder named to it and never walks `artifacts/**` or the repo root
recursively: `artifacts/` holds every run snapshot. Case, 2026-10-10: a worker's recursive glob over `artifacts/` passed the
tool's 120 s timeout, was moved to the background and ran 2 h 19 min of CPU; the ORCH session that owned the worker stayed `working`
until the shell was stopped. `docs/agents/orch.md` and the role files carry no line of this repo (ADR 0109), so the rule lives here and in `CLAUDE.md`.

## Looking at the monitor pane (#915)

- `scripts/pane_look.py press` / `hover` / `hover-series` move the owner's pointer only after 120 s without his input; under that they move nothing, print `owner active: ...` and exit 3; nothing lowers the 120 s; `--wait-for-pause` waits at most 10 minutes. The pointer is put back after every look; `look` (a picture) has no rule.
- A series is at most 20 looks (`hover-series x,y ... --out-dir <dir>`); it stops with exit 3 when the pointer is found away from where it was left. Never run a pointer script outside the repo.

## Path of Exile sense

> - **Path of Exile sense.** Meeting the spec's numbers is not enough: before closing an issue that changes builds,
>   look at them for what is obviously wrong in the real game (a config no character has, gear or gems it cannot use,
>   a damage number from a toggle nobody can keep up). Found: `needs-info` with the build and the line. The owner,
>   2026-09-26: ORCH may judge PoE logic, it is not kept away from it; the brain reviews results with the owner.

## The session: this installation's numbers, the monitor, the history

> Current mechanism (#50, one session holding many issues since #60). ORCH is never a standing chat: it is one Claude
>
> - **Start.** ... `claude.exe --bg --name "orch #54 #55 ..." --agent orch --effort high --permission-mode bypassPermissions "Take every ready
>   issue (ready now, in dispatch order: ...). Follow docs/agents/orch.md."` from the repo root.
>
>   held issues to `artifacts/runs/orch_session.json`; the monitor (#52) shows them, each with its subagents, under the
>   ORCH row.
>
>   `needs-info`, #58; or any dead state such as `stopped`), checks that none of its subagents still runs, stops the

The superseded mechanisms, verbatim:

> Superseded mechanisms, kept only so an old handover file still makes sense: one issue per ORCH session (#50,
> 2026-09-26 19:00-20:30; it dropped the grill's Q22 parallelism, D104). Before that (2026-09-18..26) ORCH was the chat
> "Orch" (auto mode, Remote Control OFF), which cleared itself with `clear_session("self")` after every checkpoint and
> relied on the keymaster to wake it ~15 s later -- fragile, because `clear_session("self")` ends the desktop app's
> Claude Code process, so a cleared chat cannot wake itself, and cron jobs and background Bash tasks die with the
> clear (measured 2026-09-26, the reason for this issue). `docs/agents/keymaster.md` no longer has a "Waking ORCH"
> duty; the chat "Orch" itself retires (`docs/agents/owner.md`).

## Models and effort: what was measured here

> On the owner's cost chart Opus 5.5 peaks at xhigh (66.4%) and max is lower (64.8%) at 1.5x the cost; high (64.2%) costs
> about half of xhigh and medium (57.5%) already beats Opus 5 at max (52.3%) at about a fifth of its cost. Rough guide:
>
> or xhigh (the owner, 2026-09-18).
>
> would cost more than the change. GPT workers through `tools/agentops` (#46) stay available as an option (their budget

## Cutting an issue into units: why, and today's numbers (#254)

`docs/agents/orch.md` "Working an issue" now has ORCH cut an issue into units before delegating, and start every
unit with no `needs` side by side. The rule is the owner's word of 2026-09-28 (#254), first on DeepSeek's slow
spawns ("воркер роль отводилась дипсик модели"), then widened to every worker model: "Оркестратор должен резать
таски и параллелить их!!!! Это его задача!!!!" (11:28) -- a mini A/B's arm D (`ab-mini-d`, #260) had tried the
weaker "a further unit starts after the unit before it is merged" and still held one unit per issue with two
pieces done by ORCH itself; the owner named that the opposite of what he asked, so units with no shared `needs`
run side by side, never one after another.

What triggered it, measured over the 42 dispatcher-started ORCH sessions, 2026-09-26 to 2026-09-28 09:52 (#254):

| fact | the number |
|---|---|
| turns per spawn | `worker-strong` 102 (2 343 turns over 23 spawns), `worker` 62 (6 829 over 111) |
| $ per spawn | `worker-strong` 8.92, `worker` 1.64 |
| the cost after a worker's first edit that falls on turns above 100k of context | 87.6 % |
| the 5 dearest of 40 spawns | 51.4 % of $100.07 |
| researchers | 11 spawns against 134 of the workers, 0.3 % of the money |

Not known at #254's triage: what the protocol said then about the size of one delegated unit, and how many of the
23 `worker-strong` spawns carried a whole issue -- nobody had read the protocol for that ticket yet. The rule
above is #254's answer; the numbers that show it holds over the next 20 closed issues (turns per spawn, the share
of spawns that carried a whole issue, the cost per closed issue against $3.76) are a ticket of their own, opened
by the brain after this merges.

## Myself or a subagent: the prices behind 10 own turns (#184)

`docs/agents/orch.md` "Working an issue": ORCH works a piece itself at most 10 own turns on files in its context,
else it delegates, with a `researcher-find` for the places first. Measured for #175's levers ("Orientation context"):

| price | measured |
|---|---|
| ORCH's own turn | $0.044 ($38.02 over 865 turns) |
| a `worker` turn / a `worker-strong` turn | $0.029 / $0.106 |
| what a worker spends before its first edit | $0.50 a spawn ($25.04 over 50 spawns) |
| one `researcher-find` | $0.11 by the median (n = 30) |
| a delegation before its first edit: the researcher, the orientation, two own turns | about $0.70, which is 16 own turns; 10 leaves room for what the own turns add to ORCH's context |

The brain recomputes the number with the weekly rerun of the token meter when a price moved by 20 % or more.

## Where the rules came from

- ORCH as a role, the whole protocol, and the text moved out of CLAUDE.md: #45, the owner's grill of 2026-09-26.
- Every ready issue at once; the context threshold T and Q22: D104, #60; the numbers measured
  2026-09-26 over `orch #49`, `#6`, `#24`, `#58`, `#53`, `#60`; the 150k ceiling: #100, #104. "One subagent per
  issue" (D104, #60) superseded by cutting an issue into units run side by side: the owner, 2026-09-28 (#254).
- The dispatcher, one live session, adoption and `_resolve_outcome`: #50, #58; the wake message: #137.
- Native blockers are never handed out: #53. The `in-cloud` lane: #121.
- Outcome lines and `routes`: #66; the token meter: #47; the monitor: #52.
- `--after <job id>` chains: #82; the runs daemon that posts results and re-adds the label: #48.
- Provisional decisions and their trailer: #113. `git push origin main` before a branch is cut: #78.
- `Skill` back in ORCH's tools: #104, reverting #102.
- Tier 3 back to Sonnet 5 and DeepSeek paused: the owner, 2026-09-26; DeepSeek measured 2026-09-23..26.
- GPT workers through the opencode bridge: #46. GPT research at high or xhigh: the owner, 2026-09-18.
- ORCH may judge PoE logic: the owner, 2026-09-26. Memory stays the brain's: the owner, 2026-09-26, after
  `orch #49` edited it.

## From the role file

Issue #149's mapping (round 2): every repo-specific line the base `.claude/agents/orch.md` (eb7bda3) carried is
already covered above, not just quoted once more: "worker-strong for subtle optimizer / pipeline code" is
`worker-strong`'s domain above; "`python scripts/runs.py submit`", "`machine_load.py`" and P0/P1/P2 are the PoB-runs section above;
"`code-review` on every unit diff" (#1066, was optimizer / pipeline diffs only) is in "The header and the routing" below the threshold
section; the context threshold `T = B + N x X` and its numbers are "The context threshold: today's numbers"
above; "the only session that merges into main" and "benchmark numbers first, principle 6" are ORCH's judging
rule, also below. Nothing from the role file is left in `CLAUDE.md`.
