# Coding standards

What the `code-review` Standards axis reads, and what every agent writes against. One rule per line, each ending with
its source in parentheses; every rule is already written in the file it names, none is new. A rule a review finds
missing here is a ticket for the brain, never a line added in passing. Not reviewed because tooling enforces it: the
last line of part 1.

## 1. Core rules

Verbatim from `docs/agents/core-standards.md` (the core file, listed in `tools/agentops/core_manifest.txt`; copied here
because a review sub-agent reads files and follows no `@` import; `tests/test_coding_standards.py` keeps the copy equal).

- The code carries no ledgers, proof surfaces, waivers, blocker taxonomies or publication gates: a function returns a result or raises. (docs/agents/core-block.md, principle 5)
- Validation is a test that measures the outcome, never a schema check. (docs/agents/core-block.md, principle 5; docs/agents/workflow.md)
- No parallel registry of tasks or decisions beside GitHub issues, `GLOSSARY.md` and `docs/adr/`. (docs/agents/core-block.md, principle 5)
- A decision becomes an ADR only when it is hard to reverse, surprising and a real trade-off; the rest lives in the commit message with its numbers. (docs/agents/core-block.md, principle 5; docs/agents/workflow.md)
- A new ADR takes the highest number in `docs/adr/` plus one; an amendment lives inside its ADR. (docs/agents/core-block.md, "Domain docs")
- Human-facing text writes a duration in a unit a human reads: seconds only under ~90 s, then minutes, then hours and minutes past ~90 min; machine files keep raw seconds. (docs/agents/core-block.md, principle 7)
- A rate is quoted per minute, never per 100 s. (docs/agents/core-block.md, principle 7)
- Each commit carries its before/after numbers in the message. (docs/agents/workflow.md)
- A red suite is never merged around: fix the code, or the data the failing tests read, then merge through the merge command. (docs/agents/workflow.md)
- A test that judges built data judges data built from the code being merged, never stale data left in a checkout. (docs/agents/workflow.md)
- A term in a report that is not in `GLOSSARY.md` is a finding for the brain. (docs/agents/core-block.md, "Skills are hard steps")
- A draft of a comment, a table or a report goes to the session's scratchpad directory, never into the repo. (docs/agents/core-block.md, "Every agent, always")
- A process an agent starts never opens a console window of its own: it inherits the session's hidden console or goes through the repo's hidden launcher. (docs/agents/core-block.md, "Every agent, always")
- Every wait is bounded, and a background shell is stopped before the report. (docs/agents/core-block.md, "Every agent, always")
- A skill is called with the Skill tool at the step that names it, before that step's first edit, and the report carries its line. (docs/agents/core-block.md, "Skills are hard steps")
- A git merge or rebase conflict is worked by the agent itself, without a skill. (docs/agents/core-block.md, "Every agent, always")
- Pocock's skills are used as shipped, never copied or overridden. (docs/agents/orch.md; docs/agents/core-block.md, "Big efforts")
- A ticket is opened or rewritten only after calling the skill `write-ticket`. (docs/agents/core-block.md, "Every agent, always")
- A subagent never decides what a domain fact means or which rule to write. (docs/agents/core-block.md, "Roles")
- A permission-guard refusal is final: never retried in another form; the exact call goes into the issue. (docs/agents/workflow.md)
- Enforced by tooling, not reviewed: the tracker guard (labels and areas on `gh`), the permission guard's red list, the worker git and process guards, the leak check of the core's files. (tools/hooks/tracker_guard.py; tools/hooks/permission_guard.py; tools/hooks/worker_git_guard.py; tools/hooks/worker_process_guard.py; tools/agentops/core_check.py)

## 2. This repo's rules

Product (CLAUDE.md principles 1-8; "PoB" is Path of Building, the numeric oracle).

- PoB is the only judge of strength: no prose reasoning about strength, no hand-written scaling weights, no "this should be good". (CLAUDE.md, principle 1)
- The LLM never picks passive nodes, item affixes or config toggles; those are optimizer decisions. (CLAUDE.md, principle 2)
- When candidates are needed (uniques, notables, supports that touch a damage type), query the corpora in `src/junkroan/pob/` (`tag_corpus`, `mod_corpus`, `game_corpus`); never enumerate game content from model memory. (CLAUDE.md, principle 3)
- "What does X scale with" comes from PoB's parsed mod data and from measured PoB deltas, not from curated prose. (CLAUDE.md, principle 4)
- The only hand-maintained knowledge is `src/junkroan/mechanics/` (facts PoB cannot compute), kept small and machine-readable; if PoB computes it, it does not belong there. (CLAUDE.md, principle 4; docs/agents/local/workflow.md)
- Validation is a test that measures the outcome, which here means a test that measures build strength. (CLAUDE.md, principle 5)
- Every stat, output, config var, mod line, item, base, skill, keystone, mechanic and floor keeps its exact PoB / in-game English name, never translated; messages to the owner are in Russian. (CLAUDE.md, principle 8)
- Every duration a script renders goes through `junkroan.report_format.human_duration`. (CLAUDE.md, principle 7; src/junkroan/report_format.py)
- The objective metric is `CombinedDPS` per instance, `FullDPS` only for main skills whose instance count is a PoB stat. (docs/LAYOUT.md; docs/adr/0057-the-objective-stays-combineddps-fulldps-is-the-author-s.md)
- A Flask slot is `active` only when it reads "Flask uptime: 100%"; the flag is derived by the PoB worker on every evaluation and never set by hand. (GLOSSARY.md, "Flask uptime"; docs/adr/0115-a-flask-is-active-only-at-pobs-own-100-percent-uptime.md)

Code shape (docs/agents/local/workflow.md, "Before optimizer code"; docs/LAYOUT.md).

- Write the measurement first: which PoB metric proves the change, on which benchmark build. (docs/agents/local/workflow.md, "Before optimizer code")
- Keep modules small and pure; `PobSession` is the only stateful thing. (docs/agents/local/workflow.md, "Before optimizer code")
- One calc is ~0.1 s: budget thousands per skeleton and prefer incremental mutations to a full re-apply. (docs/agents/local/workflow.md, "Before optimizer code")
- When a task needs game knowledge, write a corpus query, not a paragraph. (docs/agents/local/workflow.md, "Before optimizer code")
- `src/junkroan/pob/` is inherited and stable: do not add features there except through the roadmap "harness" tasks, and never add gates or ledgers. (docs/LAYOUT.md)
- `reference/legacy/` is read-only and never imported; v1 concepts (rails reports, decision ledgers, proof packets, skill passports) are not resurrected. (docs/LAYOUT.md; docs/agents/local/workflow.md, "Do not resurrect v1")
- Every new kind of error becomes an audit check and a general rule, never a patch for one build. (docs/agents/local/workflow.md, "The audit")
- Every search run writes its ranked set into its own dated folder `artifacts/search-<skill>/<YYYYMMDD-HHMM>/`; a later run deletes nothing of it. (docs/LAYOUT.md)
- The core files carry no line of this repo; this repo's own lines live in `docs/agents/local/`. (CLAUDE.md, "What this repo adds to a role")

The test of a change's kind (decide the kind before choosing the test; CLAUDE.md principle 6, `docs/TESTING.md`, ADR 0113).

- A change that is kind A (search space) but also touches selection, loop control, evaluation values or termination is kind B. (docs/TESTING.md, section 1)
- Kind A: rail tests plus the trace counter at the PoB boundary, `generated(x) > 0 and evaluated(x) > 0` or `evaluated(forbidden) = 0`; never a before/after set run or a metric gain. (docs/TESTING.md, section 2; docs/adr/0113-a-change-is-proven-by-the-test-of-its-kind-the-weekly-gate-on-main-alone-says-whether-quality-moved.md)
- Kind B: a test that encodes the defect plus the replay bench (`replay_bench.py --move <m>`) on the smoke six; a paired set run only when the bench alerts or the whole loop changes. (docs/TESTING.md, section 2; docs/adr/0084-a-change-to-a-move-is-judged-on-the-replay-bench-a-campaign.md)
- Kind C (refactor): an identical PoB call transcript, base against head (`--record-calls`, `compare_calls.py`), finals equal to the digit; any difference makes the change A or B. (docs/TESTING.md, section 2)
- Kind D (speed only): the suite, the same transcript and interleaved base/head timings; no quality claim. (docs/TESTING.md, section 2)
- Kind none (no optimizer code): the suite and no PoB job. (docs/TESTING.md, section 2)
- Whether overall quality moved is answered only by the weekly core run; no ticket is judged by it. (docs/TESTING.md, section 2; CLAUDE.md, principle 6)
- The closing comment names the kind and shows its numbers (A move x class counts, B paired table, C "identical, N calls, finals equal", D timings, none the suite line). (docs/TESTING.md, section 3)

Machine load and runs (CLAUDE.md, "Every agent, always" and "What this repo adds to a role").

- Run `python scripts/machine_load.py --need N --role other` before anything that opens a PobSession, and wait only on GO. (CLAUDE.md, "Every agent, always"; docs/agents/machine.md)
- A PoB job longer than ~5 min or wider than 1 slot goes only through `runs submit`. (CLAUDE.md, "Every agent, always"; docs/agents/runs.md)
- Benches run with `--workers 2`, never next to one's own pytest; a plain `pytest` starts no PoB, and tests of the mark `pob` run with `-m pob` or `-m "not slow"`, after `machine_load.py`. (CLAUDE.md, "What this repo adds to a role"; pytest.ini)
- Fast tests do not need PoB; tests that need the runtime skip when `var/cache/pob` is missing. (docs/LAYOUT.md)
- A long run is launched as a detached process, never from the session shell; detaching goes through the repo's hidden launcher named in its machine doc. (docs/agents/workflow.md; docs/agents/core-block.md, "Every agent, always")
- No CPU burner on the PC between 08:00 and 01:00; a "busy machine" row goes through `scripts/burner.py` (laptop or night). (CLAUDE.md, "Every agent, always")
- A snapshot or a directory junction is never deleted (deletion follows the junction), and a worktree is never deleted. (CLAUDE.md, "Every agent, always"; docs/agents/core-block.md, "Every agent, always"; docs/agents/machine.md)
- A lookup (`find`, `grep`, `rg`, a glob) starts at a named folder and never walks `artifacts/**` or the repo root recursively. (CLAUDE.md, "What this repo adds to a role")
