# 2026-09-18 D62. The knowledge loop: facts PoB cannot compute, researched on demand, approved by the user

Status: Accepted; amended by D62 amd 1, D62 amd 2, D62 amd 3, D62 amd 4

Context: the user's readings keep finding numbers our lane types without knowing them
(Sigil of Power 50 where the range is 0-4, Wither 15, nine VD orbs, mines with 4% unreserved
mana), and the user cannot know all of Path of Exile either. v1 died of stored interpretations
(D5); what is needed is the opposite: a small store of facts PoB does not compute, each with a
number and the place it plugs into.

Decision (with the user):
- A fact names its hook (a config input, a count, a floor, an audit check) or it is not stored.
  Basic mechanics by delivery type and skill class (mines reserve mana, proxies and on-kill,
  trigger breakpoints, channelling, ailment formulas) come from the wiki into
  `mechanics/delivery_types.json`, looked up by gem tags, never read as prose by an agent.
- A gap is detected two ways. By machine: a numeric input PoB shows for the skill with neither a
  derivation rule nor a fact behind it (today such inputs silently get a ceiling). By reading:
  the first time a skill is built, its wiki page is fetched and kept raw under `var/cache/wiki/`,
  and the main model reads it once for mechanics PoB cannot see (the user: the hint whether
  there is anything to dig for, a multi-hit for instance, is usually on that page).
- A gap becomes a brief for a GPT model (the GPT-era research harness, now `tools/agentops research`,
  #46/#65; the vendor provider in `opencode.json`); the build runs meanwhile on the conservative default with the number marked
  "unresearched". The answer lands as a fact with status pending, its sources and confidence
  (two independent sources or the wiki / a developer; "not found" is an answer).
- Pending facts touch only the optimistic lane and a note "would move the number by X%"; the
  conservative number uses approved facts only (the user: yes). The user approves from one table:
  fact, number, sources, confidence, which builds it moves and by how much.
- Facts carry the game version; a PoB bump marks them "verify again".
- Questions of the kind "is this keystone good" (Imbalanced Guard) are analyses, not facts: PoB
  under a hit-size profile answers them; research only checks the profile.
Order: after the speed work (7.1h 1-3) and with the rules of the two readings, whose first facts
are the two reports of 2026-09-18 (`docs/research/2026-09-18-game-knowledge*.md`).

D62, amended 2026-09-18 (the same day): Reddit is reached only by GPT through the Codex CLI's
`--search` (the GPT-era research harness, now removed, #65, superseded by `tools/agentops research`'s
websearch, #46; opencode's fetcher and the main model's browser are both
refused); a report that cites neither Reddit nor the wiki is a failed task. The wiki is read by the
main model in its browser and kept twice under `var/cache/wiki/`: the raw page, and a compact
extract (mechanics and interaction sections, gem numbers; no navigation, acquisition, recipes,
level tables or version history) which is the only form an agent reads afterwards (the user:
agents should not read 95% of a page for nothing). The user's answers on the first facts: VD with
a regular Spell Cascade = 6 orbs; mines out = what the ramp budget and the throw rate place, bounded
by what the unreserved mana can reserve; Elemental Overload follows the wiki (proxies' crits do
activate it for that skill; minions do not interact); Clever Construction counts as x1.10 for trap
builds. The wiki outranks the user's memory where they differ (the user).

D62, amended 2026-09-18 (second): the approval table. The user rejected a table of facts:
only decisions go to them (sources disagree, or PoB cannot compute the value, and the choice
changes builds), each with the options and the consequence for the system; a fact never
stands alone. Numbers that follow from the build's own rates inside the ramp budget (Sigil of
Power stages, Wither stacks from totems, Pride's effect, corpses consumed recently, poisons
applied recently) are arithmetic, computed by the config rules, never researched or asked. What
the lane typed is checked before anything is asked. Research briefs carry only practice
questions the wiki, PoB and arithmetic cannot answer, and a number from one setup is not a
fact until its generality is shown. Answers of this round: VD with a regular Spell Cascade =
9 orbs (Reddit convention; the user); Pyroclast ~3.3 hits per mine on a boss (pending
generality); Arrow Nova on Shrapnel Ballista works; Imbalanced Guard is not a fact but a
mapping-view number: physical damage reduction against a 1,000 and a 3,000 hit from the
build's armour, with and without the keystone (A/(A+5H) against min(0.5, 2A/(2A+5H))).

D62, amended 2026-09-18 (third): ramp-type numbers, implemented. A stack / stage / "recently"
count is arithmetic -- `value = min(cap, rate x 2.5 s)` -- computed by `optimizer/ramp_inputs.py`
from PoB's own numbers: the rate from this build's stats (`ManaCost` x `Speed` = mana spent per
second, `HitSpeed`, `PoisonStacks` / `PoisonDuration`), the cap from PoB (the bisection in
`judge_stack_options`, a skill's own maximum in `pob/skill_facts.py`), the per-unit cost from the
gem's level data (Sigil of Power 379 mana per stage at 18, Wither's 0.28 s pulse, Pride 19% -> 38%).
Measured: spark's Sigil of Power 50 -> 1 stage and intensity 50 -> 4 (the optimistic lane keeps the
cap), poison_spectral_throw's withered stacks 9 -> 12, poison_spark's 15 -> 8 (the author typed 6)
and its "poisons applied recently" 12 where we had none. Pride is not a free MIN/MAX choice: the
conservative lane takes MIN plus a `<CustomModifierBlock>` for the part of the 4 s ramp reached in
2.5 s (+9% more physical damage taken at gem level 18; PoB's parser takes whole percents only, so
it rounds down), the optimistic lane keeps MAX; `pipeline._apply_config` writes the block back
because `set_config` drops it. Two facts PoB has not got are `mechanics/notes.json` records with
their source: Pride's 4 s ramp, and 1 of Perforate's 7 Blood Stance spikes overlapping one target.

And the cliff is gone: `RampBudget >= RampSeconds` cost bleed_perforate a Sand Stance worth 647,425
for a feasible Blood Stance worth 189,005, 13% of budget. Since every count the conservative lane
controls is now written at a value inside the budget, the floor is satisfied by construction; what
stays a floor is the one binary state no count can hold at a partial value, the stacked skill part
("10 Blades"): `RampBudget >= RampStages`. `RampSeconds` is still computed and reported, and an
ailment ramp over budget is a warning in the audit (Viper Strike's 4.2 s), not an infeasible build.
Proof: bleed_perforate s3 now picks Sand at 601,832 conservative (the difference to 647,425 is
Pride, judged mid-ramp), `tests/test_ramp_inputs.py`.

D62, amended 2026-09-18 (fourth): the pending store, implemented.
`src/junkroan/mechanics/pending_facts.json` holds every researched fact that is not yet approved,
read only through `mechanics/pending_facts.py`; a record names its hook or it is not stored, and a
record with no source or an unknown status is a loading error. One field decides what it does, so
approval is a one-word edit: **pending** acts on the optimistic lane only, **approved** on both,
**disputed** on neither (and then it must carry the range and the disagreement; the user's table is
`docs/research/2026-09-18-pending-facts-table.md`). A fact that *lowers* a number and has no lane to
live in -- a cost, a floor, an instance count -- cannot be "optimistic only" without making the
optimistic number the pessimistic one (the audit's own lane check forbids that), so while it is
pending it is computed and reported as "would move the conservative number by X%" and charged to
nothing. Two hooks: **Trauma is a self-hit PoB counts nowhere** (`optimizer/self_cost.py`; PoB
parses `trauma_strike_self_damage_per_trauma` into the gem's level data and maps it to no modifier,
so the per-stack number is PoB's own -- `skill_facts.effectiveness_stat` runs PoB's effectiveness
interpolation and gets 146 at gem 20, the number the report quotes -- while the mechanic, a hit of
`per stack x stacks` on every attack hit that gains one, is the fact); and **at most three Blood
Stance spikes reach one boss** (`optimizer/ramp_inputs.perforate_spike_overlap`), a ceiling on the
optimistic lane, which was claiming all seven. Measured: static_strike with Trauma Support at the
rails' gems pays 126 x 6 = 756 per attack x 1.99 hits/s = 1,503 life/s against +65/s of idle
recovery, so approving it flips D63.3's floor by 1,438/s (41% of the 3,466 life pool per second);
bleed_perforate's optimistic lane falls from 360,005 to 193,828 (-46.2%) with its conservative
105,434 untouched. `tests/test_pending_facts.py`.

