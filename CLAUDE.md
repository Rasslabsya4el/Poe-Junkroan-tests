# Poe Junkroan v2

Machine search for Path of Exile builds. Path of Building (PoB) is the numeric
oracle; scripts optimize; the LLM only proposes hypotheses and explains results.

This file is already in your context: do not re-read it. Read what your role
and task need: `GLOSSARY.md` (the vocabulary), `docs/STATE.md` (what runs now),
`docs/ARCHITECTURE.md`, and the rule files indexed below. Work items are GitHub
issues (section "Agent skills"). `docs/ROADMAP.md` is frozen history. Do not
read `reference/legacy/` unless a task says so.

## What this project is

User asks for a build ("Fireball", "something around item X", "bow poison").
The system searches over build *skeletons* (class, ascendancy, main skill, damage
mode, supports, keystones, key uniques, auras), and for each skeleton runs a
deterministic optimizer over passive tree, rare gear and config with PoB in the
loop. Output is a ranked Pareto set of PoB import codes with an explanation of
why each build is shaped the way it is. The goal is to find strong non-meta
builds that a human would not assemble by hand, not to reproduce poe.ninja.

## Non-negotiable principles

1. **PoB is the only judge of strength.** A change to a build is good if PoB's
   numbers say so under the objective function. No prose reasoning about
   strength, no hand-written scaling weights, no "this should be good".
2. **The LLM never picks passive nodes, item affixes or config toggles.** Those
   are optimizer decisions. The LLM proposes skeleton hypotheses, writes search
   space definitions, and explains results.
3. **Retrieval over recall.** When candidates are needed (uniques, notables,
   supports that touch a damage type), query the corpora in `src/junkroan/pob/`
   (`tag_corpus`, `mod_corpus`, `game_corpus`). Never enumerate game content from
   model memory.
4. **Interpretations are derived, not authored.** "What does X scale with" comes
   from PoB's parsed mod data and from measured PoB deltas, not from curated
   prose. The only hand-maintained knowledge is `src/junkroan/mechanics/`
   (facts PoB cannot compute, e.g. corpse supply, overlap breakpoints), kept
   small and machine-readable.
5. **No process ceremony** (`docs/agents/core-block.md`, principle 5, general words). Locally: this repo's own
   v1 died of exactly this ceremony, and the test that "measures the outcome" there means a test that measures
   build strength.
6. **Every optimizer change is proven by the test of its kind, with numbers** (D113).
   A search-space rule (an allowed option or a restriction) by rail tests and the
   trace counter at the PoB boundary (`generated(x) > 0 and evaluated(x) > 0`, or
   `evaluated(forbidden) = 0`) in minutes, never by a metric gain; a loop or
   evaluation fix by a bug-specific test plus D84's replay bench on the builds where
   the defect reproduces, a full paired run only on an alert; a refactor by an
   identical PoB call transcript (D95). Whether overall quality moved is answered
   only by the weekly core run (core14 x 3 seeds on main, `scripts/benchmark.py`). The closing
   comment names the kind and shows its numbers, not schema checks.
7. **Durations for a human** (`docs/agents/core-block.md`, principle 7, general words). Locally: the owner said
   so twice ("я не понимаю что значит 2000с", 2026-09-18 and again 2026-09-20); the one helper every script
   renders a duration through is `junkroan.report_format.human_duration`; a report that breaks the rule is sent back.
8. **GAME AND POB TERMS ARE WRITTEN AS POB WRITES THEM, NEVER TRANSLATED** (the
   owner, 2026-09-22: "как ты читаешь параметр/стат/формулировку, так и пишешь...
   главное не на русском, я не играю в пое на русском"). Messages to the owner are
   in Russian, but every stat, output, config var, mod line, item, base, skill,
   keystone, mechanic and floor keeps its exact PoB / in-game English name:
   `PhysicalMaximumHitTaken` (not "максимальный удар"), `EffectiveMovementSpeedMod`,
   `Life`, `CombinedDPS`, "+% increased Spell Damage", Two-Stone Ring, Mind over
   Matter. Player slang in Cyrillic (лайф, резы) is tolerated; a Russian translation
   of a game term is not. Applies to every report, table, State entry and agent
   report the owner reads.

## Roles (orchestration v2)

The core rows (brain, ORCH, dispatcher, researchers, external researcher, workers) are in
`docs/agents/core-block.md`, imported at the end of this file; this repo's own values for them (the brain's chat
title, `worker-strong`'s domain, Reddit as the external researcher's forum) live in `docs/agents/local/brain.md`,
`docs/agents/local/orch.md` and `docs/agents/research.md`. Here the keymaster owns PoB runs. The core block's
wayfinder section is generic; locally, the owner runs its commands and the brain says when an effort becomes a
map. This repo also runs one role the core does not know:

| role | where | model / effort | job | protocol |
|---|---|---|---|---|
| keymaster | one background session per anomaly, started by the runs daemon (`anomalies.py`), no standing chat | Sonnet 5.5 medium | diagnoses one anomaly (a failed/stuck job, laptop unreachable, a bad budget file), fixes what is mechanical, ends | `docs/agents/keymaster.md`, `docs/agents/runs.md` |

## Where the rules live

`docs/agents/core-block.md` (imported below) holds the core protocols' own list under the same heading; this
repo also keeps its own:

- Which test a change gets (its kind, D113) and how long it takes: `docs/TESTING.md`
- Layout, commands, bumping PoB, the objective metric: `docs/LAYOUT.md`
- PobSession cheat sheet, known harness limitations: `docs/POBSESSION.md`
- Rails worth remembering (gems, gear, config, pipeline, uniques, degen): `docs/RAILS.md`
- The machine budget, detached launches, worktree junctions: `docs/agents/machine.md`
- The run queue: `docs/agents/runs.md`

Every agent, always (the core half — its own worktree, tests in the foreground, every wait bounded, own
background shells stopped, never delete a worktree — is in `docs/agents/core-block.md`, imported below): run
`python scripts/machine_load.py --need N --role other` before anything that
opens a PobSession, and a PoB job longer than ~5 min or wider than 1 slot only
through the keymaster (`runs submit`); never delete a snapshot or a directory
junction (deletion follows the junction: `docs/agents/machine.md`); never start a CPU burner (a spinner, a
stress loop) on the PC between 08:00 and 01:00: a "busy machine" row goes through `scripts/burner.py` (laptop or night).

## Agent skills

### Issue tracker

GitHub Issues of `Rasslabsya4el/Poe-Junkroan` (private). See `docs/agents/issue-tracker.md`.

Triage labels and domain docs are generic across any repo running this core; see `docs/agents/core-block.md`
(imported below).

## What this repo adds to a role

The core role files in `.claude/agents/` (all but `keymaster.md`) carry no line of this repo (ADR 0109); their
generic wording already states the shared rule, so it is not repeated here. `brain.md`'s and `orch.md`'s own
lines live in `docs/agents/local/brain.md` / `docs/agents/local/orch.md` instead, never here. What is left is
the handful of facts a generic role file's wording cannot carry:

- `worker` / `worker-strong`: benches size their workers from the free slots (`docs/agents/machine.md`, the budget section), never next to your own pytest (the PobSession /
  machine-budget rule itself is in "Every agent, always" above). A plain `pytest` starts no PoB; tests of the
  mark `pob` run with `-m pob` or `-m "not slow"`, after `machine_load.py`, and past ~5 min go through `runs submit`.
- `worker-strong`'s "subtle core logic" means the optimizer, pipeline and headless worker's Lua, where a wrong
  detail changes build numbers; its measurement is the test of the change's kind (principle 6, D113,
  `docs/TESTING.md`): the trace counter for a search-space rule, the replay bench for a loop fix, an identical PoB
  call transcript for a refactor; never a whole-set benchmark run of its own.
- `researcher-how`'s re-search rule was learned from #68 (2026-09-26): both wrong facts of that day were
  negatives the source itself refuted.
- Every role's lookups (`find`, `grep`, `rg`, a glob): they start at a folder named to them and never walk `artifacts/**` or the repo root recursively (a worker's 120 s tool timeout once left such a walk running for hours, #727).
- Every role's "domain fact" is a Path of Exile mechanic; every role's "numeric tool" or "long external run" is
  PoB / a PobSession.

## The orchestration core

Principles 5 and 7 in general words, the wayfinder section, the core rows of "Roles", the core protocols under
"Where the rules live", the core half of "Every agent, always", and the generic parts of "Core conventions":

@docs/agents/core-block.md
