# Poe Junkroan

Machine search for Path of Exile builds: the system proposes build skeletons, optimizes each one with Path of Building
(PoB) as the only judge of strength, and returns ranked builds with the reasons for their shape. Game and PoB terms
(Life, CombinedDPS, Mind over Matter) keep their PoB meaning and are not redefined here.

## Language

### Asking for a build

**Request**:
What the owner asks the system to build: a skill, and optionally a damage mode, ascendancies, items to build around
and a loadout. A request becomes a search. A **day-1 request** (a skill plus any PoB entities the owner names as
forced directions, under the day-1 loadout) is the prototype's unit of acceptance: ad hoc, in the owner's words, no
fixed list (D114 amd 1).
_Avoid_: query, prompt

**Forced direction**:
A PoB entity named in a request (an ascendancy, a unique, a mod line on a rare, a passive node): every skeleton
carries it and the search digs toward it; never a hint the optimizer may drop. A name not in PoB is an error, never
a guess (D114 amd 1).
_Avoid_: hint, preference, bias

**Hypothesis**:
A skeleton proposed in in-game names by a language model: a place to look, never a verdict on strength.
_Avoid_: idea, candidate build

**Skeleton**:
The discrete outline of a build that the optimizer does not change: class, ascendancy, main skill and its damage
mode, supports, keystones, key uniques, auras.
_Avoid_: archetype (for one build), template (that word belongs to gear)

**Damage mode**:
How the main skill's damage is delivered and counted: hit, its own damage over time, ignite, poison, bleed, or
minions. Read off PoB per skill, never assumed.
_Avoid_: damage type (that is physical, fire, ...)

**Screen**:
The cheap first round of a search: many skeletons built on a small budget and ranked, the best kept as finalists.

**Finalist**:
A skeleton that survives the screen and is built in full with several seeds; the best seed is the delivered build.
_Avoid_: top skeleton

**Rig**:
A bare stand-in build (the skill on a minimal tree and gear) used only to compare candidates quickly. A bare rig
favours hits over damage over time.
_Avoid_: test build

### Building one skeleton

**Construction**:
The first part of building a skeleton: config, gear, a greedy tree, gear again, then the tree regrown on the finished
gear.

**Improvement loop**:
The second part: passes of moves over the constructed build until a pass keeps nothing.
_Avoid_: stages, post-processing

**Pass**:
One round of the improvement loop through its moves.

**Move**:
One kind of change the improvement loop tries (a tree move, a gear re-roll, the picks, a kick), kept only when the
objective improves.

**Picks**:
The move that re-chooses the gems the skeleton leaves open, such as which utility gem of a family fills a slot; while
a build is infeasible it may also turn off one reserving socket group.

**Path swap**:
A tree move that re-spends a small subtree whole on a different path.

**Surface**:
One part of a build that PoB holds and the optimizer fills: the passive tree, the ascendancy nodes, the gear (flasks
included), the gems (supports, utility groups, auras) and the config.
_Avoid_: layer

**Kick**:
A move tried only after a pass keeps nothing: a random part of every surface is torn down at once and the build is
regrown around the hole (ruin-and-recreate), several draws each judged whole. A surface joins the kick; it never gets a
break-and-rebuild move of its own.
_Avoid_: perturbation, restart

**Seed**:
One random draw of building a skeleton (its loot rolls and its kicks). One skeleton built with two seeds is two
different builds.

**Trunk**:
The passive nodes most of a tree hangs from; construction lays it down and later moves rarely change it.

**Corridor**:
A run of travel nodes between two key nodes of a tree.

**Reshaping choice**:
A choice (a keystone, a stacking direction, a unique that redirects a resource or a defence) whose value PoB shows only
after the build is rebuilt around it: flipped on the finished build it collapses a floor (Chaos Inoculation sets Life
to 1), so the finished build cannot show what the choice is worth. Its opposite is an **additive choice**: a tick that
moves a number without collapsing a floor (Blood Magic moves ManaUnreserved), judged as one more option inside the
normal search. Which of the two a choice is comes from PoB's numbers, never from a hand list.
_Avoid_: build-defining choice, a keystone that needs its own run

**Ladder**:
How a finished build judges one of its reshaping choices in steps, each dearer than the last: the flip (the choice
switched on the finished build), the repair (a short local rebuild with the choice forced or forbidden), the full
rebuild (its own skeleton run). The repair's verdict is **take** (the repaired variant is at least the parent),
**drop** (below and no longer gaining) or **climbing** (still gaining at its budget end, so it goes on to the full
rebuild).
_Avoid_: keystone variants, mutation (the name of the search round that runs it)

### Bundles

**Bundle**:
A reshaping choice together with what pays for it: a requirement (Chaos Inoculation), its reward (Energy Shield,
chaos immunity) and the variable slots the build refills around it (the Energy Shield sources in tree and gear).
_Avoid_: package, combo, saved bundle

**Bundle graph**:
The graph over everything a loadout allows (tree nodes, masteries, ascendancy nodes, keystones, uniques, unique
jewels, gear, flasks) whose edges link parts that pay together; bundle candidates are read from it, sliced by
loadout, never from a hand list of kinds. A line PoB does not parse joins it only once a layer above PoB has turned
it into a PoB number.
_Avoid_: synergy graph

**Red line**:
A line of a node, unique or affix that PoB shows in red: it parses none of it, or only part. PoB counts it as 0, so
the optimizer never takes it for its strength until a mark stands for it.
_Avoid_: unsupported mod; a guard's "red line N" is a line of the Red list, not this

**Mark**:
What PoB should count when a build holds a red line: the PoB lines that stand for it on each lane, or an explicit
zero with its reason. A mark never chooses a node, an affix or a config.
_Avoid_: tag, override

**Red-line kind**:
The family of a red line that decides its mark by one verdict (an on-kill generator, a ramp, an uptime-dependent
buff); a red line of a kind no verdict covers is counted on the optimistic lane only. The conservative lane is
called the boss lane in the marks.
_Avoid_: kind (that word alone is the kind of a change, D113)

**Stand**:
A synthetic build of one type (spell, attack or minion, by damage type) on which bundles are measured; the stand
without a bundle is the shared base of its type, and each measured (bundle, stand) pair keeps the stand rebuilt
around the bundle as a build openable in PoB.
_Avoid_: bench (D84's replay bench), rig (a bare stand-in inside one request), reference, test build

**Catalogue**:
The stored record of every bundle measured on stands, with its PoB numbers per stand: a list of what a build tries
first, never a model and never a ban. A build retrieves the bundles that paid on stands similar to it and gives each
one PoB check; PoB in the build has the last word.
_Avoid_: bundle library, registry

### Judging a build

**Objective**:
What the optimizer maximizes: the main skill's damage under its damage mode (CombinedDPS per instance, FullDPS where
PoB counts the instances), subject to the floors.
_Avoid_: fitness

**Floor**:
A minimum a PoB stat of the build must reach (Life, TotalEHP, maximum hit taken, movement, sustain, self-degen).
_Avoid_: threshold, gate

**Feasible**:
Meeting every floor. A feasible build beats an infeasible one whatever the damage. Inside the improvement loop a
move is judged by the **Priced score**; the delivered build is still feasible (D116).

**Priced score**:
The improvement loop's order for comparing states: the value scaled down by the violation, the sum of relative floor
misses, so a state that misses a floor scores below its value. On an equal priced score a floor-first order breaks
the tie, which also covers a violation of 1 or more and a value of 0 or less. Applies only inside the loop (acceptance
and candidate choice); construction and the tree optimizer stay violation-first, and the loop ends with a floor repair
(D116). A weapon line is not under it: it takes the best value among the lines that worsen no floor (D116 amd 1). The
formula and its tie rule are in ADR D116.

**Sustain**:
The floor that the build's regeneration, leech and recoup pay for its per-second costs.

**Self-degen**:
The floor that the build loses no Life or Energy Shield while idle, counting no leech and no recoup.

**Rail**:
A realism rule of a loadout that bounds what the optimizer may use (gem levels, how gear is rolled, which uniques
drop, the passive point budget), derived from real builds rather than authored; some rails are enforced as floors.
_Avoid_: gate, limit

**Lane**:
One of the two config readings of every build. The optimistic lane turns on every condition PoB says the build can
use; the conservative lane only those the build proves it generates.
_Avoid_: config profile

**Our lane**:
The config our rules derive, applied to a reference as well, so that our build and the author are judged under the
same config.
_Avoid_: the author's config (that is the reference's own, not used for judging)

**Proof**:
What lets a condition into the conservative lane: a line PoB parses as its source in the build's own items, tree or
gems. A word match is not proof.

**Judging context**:
What a build is judged under at a given moment: its two lanes as PoB holds them, the objective with the ramp,
self-cost and castability read from the build as it stands, and the proof holders tree moves must respect.
_Avoid_: config state

**Ramp budget**:
The seconds a build gets to reach full damage; anything that stacks up (charges, ailment stacks, ramping buffs)
counts only what it reaches inside it.
_Avoid_: warm-up

**Fact**:
A piece of game knowledge PoB cannot compute, stored with its sources and the number it moves. Pending until the owner
approves it, then it enters the conservative numbers.
_Avoid_: note, lore

### Gear

**Loot gear**:
Day-1 rares simulated as found loot: the best of many random rolls per slot plus one bench craft.
_Avoid_: random gear

**Template gear**:
Day-1 rares built from a fixed template per slot class that the owner edits: life on every item that can roll it,
resistances solved for the whole set, the open lines chosen by value. The product's gear. Its flag value (the default)
and its alias are in the layout guide (LAYOUT.md).
_Avoid_: wishlist (its old name)

**Open line**:
A line of a template item that the template leaves free; the optimizer fills it by value or leaves it empty.

**Flask uptime**:
PoB's own flask uptime calculation (the item tooltip's "Flask uptime" line). A Flask slot is `active` only when it
reads "Flask uptime: 100%"; the flag is derived by the PoB worker on every evaluation, ours and the author's alike,
never set by hand (D115). Where PoB prints the line is in ADR D115. A flask with no uptime line (a Life or Mana flask whose effect is
removed at full life / mana) is never active.
_Avoid_: forced-active flasks, "flasks-active" regime

### Progression

**Loadout**:
A named point of a character's progression (day 1, T16 maps, ..., endgame) with the rails that come with it: level,
item level, which uniques, crafts and oils are available.
_Avoid_: stage (the name of the request field that selects a loadout), phase

**Loadout map**:
One `wayfinder:map` per loadout of the rulebook ladder (day-1, T16, endgame, uber-endgame, mirror) and one "after
the prototype"; a ticket lives under the map of the loadout its payoff belongs to, so it is clear what may be touched
now. Only the day-1 map is in focus (D114).

**Day 1**:
The loadout at the end of a league's first day: campaign finished, early maps, self-found rares with bench crafts.

### Measuring the system

**Reference**:
A strong existing PoB (a real character's day-1 snapshot, or a hand-optimized starter guide) that the system rebuilds
from its skeleton and is measured against. References are the **debugging set**: they cover the archetypes where
PoB and the game diverge and the owner's Reading is needed; no reference is acceptance, the weekly core run reports
coverage and stability and gates nothing (D114).
_Avoid_: fixture (the stored file), example build, acceptance set

**Author**:
The player behind a reference, and by extension the reference's own numbers: "% of the author" is our build's
objective over the reference's, under our lane.

**Benchmark**:
Rebuilding references from their skeletons and scoring each build against its author on the median of three seeds.

**Smoke set**:
The six references a change is tried on first, before a full campaign.

**Campaign**:
One benchmark over a whole set of references on one commit, archived and compared as a unit.

**Yardstick**:
The measured seed-to-seed spread a difference must exceed to count as real.
_Avoid_: noise floor

**Audit**:
The machine check of a finished build for errors the numbers cannot show (a dead link, an illegal unique, an unpaid
cost).

**Run issue**:
The GitHub issue the runs daemon opens for one finished whole-set benchmark (a `--set` run that ended rc 0), a
sub-issue of the runs parent (#404). Open means not reviewed; closed with the brain's verdict means reviewed. A fix
ticket that comes out of a review is a sub-issue of its Run issue.
_Avoid_: run report (that is the folder's `report.md`)

**Reading**:
A person's inspection of finished PoBs for logical errors, written down with its verdicts. Every new kind of error a
reading finds becomes an audit check.
_Avoid_: review (that is for code)

**Kind** (of a change; D113):
What a change touches, decided before its test is chosen: **A** the search space (an option allowed or a class
forbidden: rails, rulebook values), **B** the loop's or the evaluation's behaviour, **C** a refactor (every PoB
number identical), **D** speed only, **none** (no optimizer code). The kind picks the test; the test each kind takes is
in the testing guide (TESTING.md).
_Avoid_: test class, change type

**Trace counter**:
The record at the PoB boundary of what the search generated and evaluated, by move and option class, written next to
`moves` in the run's results; the oracle of a kind-A change. Its test formulas and where it is written are in the
testing guide (TESTING.md) and ADR D113.
_Avoid_: considerations log

**Bench** (D84):
The replay bench: one move replayed from the same delivered builds under base and head, the same seed; the test of a
kind-B change and the transcript source of a kind-C change. Its command and its times are in ADR D84 and the testing
guide (TESTING.md).
_Avoid_: mini-benchmark, canary

**Weekly core run**:
The one benchmark that answers "did overall quality move": core14 x 3 seeds on main at the workers the runs daemon
gives it at start, one queue line each Monday, read paired per reference against the previous weekly core run. No
ticket is judged by it. Every row of it that took a structural keystone is rebuilt once more with that keystone
forbidden (D40); those "without <keystone>" rows are part of the same run, not a second run. Its command, its hours
and its row count are in the runs guide (runs.md); the keystone rebuild rule is ADR D40.
_Avoid_: gate, weekly gate, regression run, nightly

**core14**:
The fourteen reference builds the weekly core run takes (the benchmark's `core14` set, `--set core14`), each on three
seeds.

**new18**:
The eighteen reference builds of the D56 intake (the benchmark's `new18` set).

**ziz**:
The second reference set (`--set ziz`): hand-written, heavily optimised Zizaran / Maxroll league starters of 3.25 to
3.29, each at the early-game loadout its manifest names; a guide re-published unchanged under a later league counts
once.

**Ticket run**:
A PoB run queued for one ticket: a bench, a diagnosis, a paired set run. The only other kind of run is the weekly core
run; there is no third kind. Named after its ticket. Its command and its naming example are in the runs guide (runs.md).
_Avoid_: job (in prose), gate, proof run

**Timer**:
A reminder the brain sets in its own chat for a clock time (a check of a run's end, a report due). It lives in that chat
only and dies with it; a hand-off names the time and what to do so the next brain sets it again.
_Avoid_: one-shot, cron

**Paired set run**:
A before/after `benchmark.py` over a whole set on the same seeds (11-14 h per half). Since D113 only the escalation of
a kind-B alert or a whole-loop change, never a ticket's default test.
_Avoid_: test run, pair (alone)

### Working roles

**Keymaster**:
The on-demand session the runs daemon starts for one anomaly of the PoB runs (a failed or stuck job, an unreachable
laptop, an unreadable budget file): it diagnoses that anomaly, fixes what is mechanical, and ends. At most one runs at
a time; there is no standing keymaster chat (D106).

**Parked-on-run**:
A ticket that ORCH sets aside while it waits for a run's result: ORCH removes its `ready-for-agent` label and its own
assignment, and the parking checkpoint's first line names what it waits for (`<!-- parked-on-run: ... -->`). Whoever
posts the result re-adds `ready-for-agent`, and the ticket is then judged like any other. A finishing session never
resumes a parked ticket.

**Run queue**:
The ordered list of benchmark and search runs a machine works through unattended, so that it never idles.

**Heavy job**:
A PoB job of 5 workers or more. Two never run on one host at once (#117): two page the PC's memory, and every PoB
result depends on wall clock, so the second one changes both runs' numbers, not only their speed. The slot totals
stay; the rest of the night goes to light jobs.
_Avoid_: big run, exclusive job

**Filler**:
A build of the weekly core run that an empty machine makes ahead of time. Before the cut it is made on current main
and serves as an early warning; from the cut on it is made at the cut and counts in that week's weekly core run. A
filler starts only on a machine with no PoB run and no heavy load, only in the machine's normal mode, and is stopped
at once (never paused) when any other job needs the machine; its finished builds stay. The older meaning (any PoB job
from a standing list that no issue waits for) is retired. The settlement of 2026-10-10 (#743) and the switch-on order
are in the runs guide (runs.md).
_Avoid_: background run, idle job

**Cut**:
The one commit of main a week's weekly core run measures, taken at the weekly cut-off. Every build of that weekly core
run is made at the cut, whether a filler made it ahead or the Monday line made it; what is merged after the cut is
measured by the next week's run. The cut moves only on the owner's word «пересрез»: the cut becomes main at that
moment, every build made at the old cut is dropped and the week's set starts over; no merge moves it by itself. Its
hour, the switch-on rule (#743) and the re-cut command are in the runs guide (runs.md).
_Avoid_: pin (for the weekly core run), freeze, snapshot
