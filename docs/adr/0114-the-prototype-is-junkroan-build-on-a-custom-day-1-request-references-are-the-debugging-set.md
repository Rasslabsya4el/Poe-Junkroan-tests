# 2026-10-02 D114. The prototype is `junkroan build` on a custom day-1 request; references are the debugging set

Status: Accepted; amended by D114 amd 1, D114 amd 2, D114 amd 3

brain charted the map). Supersedes the acceptance reading of 2026-09-18 (the Tuadh benchmark as the yardstick:
"every reference at or above the author, best of 3 seeds") as the finish line; the benchmark stays as the debugging
instrument and as the weekly gate's regression signal (D113).

Why now: on 2026-10-02 the repo held 52 open tickets of every kind and ORCH took whichever was `ready-for-agent`, so
work whose payoff is a later loadout (far-sight packages, endgame ascendancies, the crafting oracle) competed for
ORCH and PoB time with the day-1 rails and the loop fixes, and nobody could say how far the prototype was from done.
The acceptance counter read "19 of 32 references at or above the author". The owner (12:15): the prototype is the
day-1 loadout, full focus on the foundation and the development pipeline, nothing for T16+ now; and (к1): the
prototype has no task of covering references, it must build builds without them, correctly and within the floors;
references exist to close the archetypes where PoB and the game diverge and his review is needed.

Decision:

1. The destination: `junkroan build` on a custom day-1 request (a skill, or an ascendancy plus something) delivers
   ranked builds with explanations, correct and within the day-1 floors, under 2 h per request on 5 workers. The
   acceptance is the five conditions of #1 (Request, Correctness, Fixed point, Reading, Debugging coverage); the
   request list is a fixed six the owner writes, plus ad hoc ones (к6; superseded by amendment 1: no fixed list).
2. References are the debugging set: they cover the archetypes where PoB and the game diverge and the owner's
   Reading is needed. The weekly core14 x 3 gate reports coverage and stability and gates nothing (D113); `ziz` is
   reported, never gated.
3. Floors: the standing day-1 floors on the rulebook page (Life 4,500 and the ones the rails already hold: the
   resistances, the recovery floor); DPS is never a floor, it is the objective; a request carries only its exceptions
   (к7).
4. One `wayfinder:map` per loadout of the rulebook ladder (day-1 #486, T16 #502, endgame #503, uber-endgame #504,
   mirror #505) and one "after the prototype" (#476); only the day-1 map is in focus (к8). The boundary rule (к9): a
   ticket is in the day-1 map if a custom day-1 request can hit it or it is a foundation fix (loop correctness,
   determinism, pipeline cost). A refactor is out until a fix's checkpoint names it as its blocker (к4). The
   pipeline-cost tickets go first in dispatch order and the builds tickets run beside them, never behind a gate (к3).

Consequences: #1 rewritten to the five conditions; the tickets re-homed under their loadout maps (#440 #18 ->
endgame, #394 -> T16, #28 #19 #29 #12 -> after the prototype); the refactors #32 #51 left open outside every map;
the six requests are the owner's own ticket (`wayfinder:task`) and #4 takes them as input; the first Reading
request comes after the first weekly gate, not before. The map's fog: the request grammar `junkroan build` takes,
the floors as machine values with one rail test, the audit check per known error kind, the 2 h budget measured on
the first request before any speed work. `CONTEXT.md`: day-1 request, debugging set, loadout map.

## Amendment 1 (2026-10-02, the owner in [The six acceptance requests](https://github.com/Rasslabsya4el/Poe-Junkroan/issues/507))

Decision 1's "the request list is a fixed six the owner writes, plus ad hoc ones" is replaced: there is no fixed
list. Every acceptance request is ad hoc, in the owner's words, made of things PoB knows: a skill, and optionally
any PoB entity the search is pushed toward (an ascendancy, a unique item, a mod line on a rare, a passive node:
notable, keystone or mastery), in any combination. Each named thing is a **forced direction**: every skeleton of
the search carries it, the search digs in that direction, nothing drops it as a hint. A name not in PoB is an
error, never a guess (principle 3). The day-1 floors apply unless the request says otherwise (к7 unchanged). The
2 h budget is measured on the owner's first ad hoc request. The owner, verbatim: "Я не хочу их прописывать потому
что это может быть что угодно. И система должна быть готова к этому. ... это может быть рандомный уник или скажем
какой то аффикс на рарке и нод в дереве помимо скилла ... подтолкнуть систему копать в ту сторону и форсить ее
это делать".

Consequences: #1 condition 1 and #4 rewritten; `CONTEXT.md` day-1 request and forced direction; the request
grammar left the map's fog as [the request grammar](https://github.com/Rasslabsya4el/Poe-Junkroan/issues/510) under #4.

## Amendment 2 (2026-10-03, the owner in the brain chat at 16:04)

Decision 1's "under 2 h per request on 5 workers" is replaced: there is no hard time line. 2 h is too little for a
request with forced directions: the search covers every class and ascendancy, so its enumeration is wider than one
reference's. At most a cap of about 5 h for a request that is simple and wide in its enumeration. The number bounds
what the optimizer may spend (seeds, the mutation round, the unique variants) and what a 5-worker job takes from
the shared machine by day; it is not a floor and gates nothing. Measured before the word, on the brain's two
requests of 2026-10-03 (#4): 1 h 55 min for `Lightning Strike` alone (6 of 12 full-optimize seeds dead at 1 s,
#519) and 2 h 55 min for `Frost Blades` with three forced directions (Hrimsorrow, Fangs of Frost, a Ring 1 mod
line; prepare 3 min 35 s, screen 10 min, full optimize 1 h 47 min, mutation round 51 min).

Consequences: #1 condition 1, #4 and the map's destination (#486) rewritten; the fog line "the 2 h budget
measured on the first request" closed; a ticket on the cap only when a request's echo estimate (#524) or its run
passes 5 h.

## Amendment 3 (2026-10-15, the owner in the brain chat, [grill round 1](https://github.com/Rasslabsya4el/Poe-Junkroan/blob/main/docs/research/2026-10-15-acceptance-conditions-state.md))

The five conditions are re-read against the code of 2026-10-15 (no wall clock in the search since #956; workers
sized from free slots since D113 amd 2; the fixed point measured per build by the audit's extra pass since #800;
the weekly line running core14 only). The owner, verbatim: "разве время теперь вообще релевантно если мы сняли
любые лимиты по времени? Теперь единственный лимит у любых билдов это 16 прогонов улучшений" (15:5x) and the
round-1 answers (16:2x: к1 "да", к3 "а", к4 the Builds-tab flow, "условие готово" "ну пускай Б", к5 "а").

1. **Request** (replaces amendment 2's cap): a request's only bounds are the improvement loop's own
   (`max_passes` 16, `min_gain` 0.5 %); the job takes the free slots (#570). The duration is a line of the report,
   never a condition, and no ticket is opened on a long run (Searing Bond, 7 h 39 min on 1 worker, is not a
   defect). Amendment 2's "about 5 h on 5 workers" is withdrawn.
2. **Correctness** unchanged; the floors (Life 4,500 and the others of `rails_default.json`) are written as text
   on the rulebook's day-1 page, which today states none.
3. **Fixed point** holds on rank 1 of each request: the audit's extra pass gains less than 1 % there. The other
   delivered builds carry their own figure in the report; theirs is not a condition.
4. **Reading** is the Builds-tab flow: the delivered builds appear as rows of the monitor's Builds tab (Open PoB,
   one line what to look at); the owner reads them and comments to the brain; the brain removes the read rows. A
   new kind of logical error he names becomes an audit check before anything else.
5. **Debugging coverage** = the weekly core14 x 3 run, reported, gating nothing; new18 and ziz run on demand
   only, never on the weekly line. The "32 references" of the 2026-10-02 text are withdrawn.
6. **Done** = three accepted requests in a row, different skills, at least one with forced directions. An
   accepted request: its rank 1 passed the audit and the floors (2), is at a fixed point (3), and the owner's
   reading of it (4) found no new kind of logical error.

Consequences: the five conditions live in the map's body (#486, "Acceptance"); #1 is closed into the map and #3
(the owner's reading) moves under #486; a ticket for the floors on the rulebook page; `docs/STATE.md`'s
Constraints and Waiting sections lose their "2 h" / "5 h" / "gate" wording.
