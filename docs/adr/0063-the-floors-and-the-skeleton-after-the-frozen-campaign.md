# 2026-09-18 D63. The floors and the skeleton after the frozen-campaign readings

Status: Accepted; amended by D90

Context: the user's reading of the two frozen campaigns (`docs/readings/2026-09-18-frozen-campaigns-part1.md`
and `part2.md`) named twenty-one classes of error. The ones that are a floor, a rail or a fact
about the skeleton are implemented here, inside the one 7.1h reopening (D61), because each of
them changes numbers and they ride with its single rerun. The lane proofs, the ramp numerics and
the D60 redo are separate work.

1. **TotalEHP is floored at the author's** (D61, the user: B), measured on their build under our
   lane, 100%, no slack, beside Life (D59). `scripts/benchmark.py:author_floors`.
2. **An attack build keeps HitChance >= 95** and **a channelling main skill sustains 100%** of
   its per-second cost instead of 85%: both read off the main skill's gem tags in
   `objective_select.with_skill_floors`, on every path that builds the objective, ours and the
   benchmark's. From kinetic_bolt_wander (83%) and shockwave_cyclone (39.3 regen against 43.84
   cost, which passed at 89.6%).
3. **No degen while idle**, replacing D34's -100/s: `NetLifeRegen + NetEnergyShieldRegen +
   SelfCostPerSecond >= 0`, without leech and without recoup, since idle is not hitting. It is a
   relation against the life pool rather than a floor at zero, because a floor of zero has no
   scale of its own: lightning_trap's -12/s would otherwise have counted as twelve missing life
   notables. The sustain relations keep leech and recoup for what the build spends while it
   attacks. From lightning_trap (-12/s, inside the old floor).
4. **Mind over Matter needs 40% of the mana pool unreserved** (the user's number). A floor on a
   derived `MoMUnreservedShare` (`optimizer/keystone_floors.py`) that is 1.0 while PoB's
   `sharedMindOverMatter` is 0, so it costs a build without the keystone nothing and prices the
   keystone inside the very what-if trial that allocates it. From burning_arrow_snipe (10%).
5. **Bandits are always killed** (`rails_default.json` character.bandit,
   `BuildPipeline._rails_identity`): not a judged choice any more, and an author's own bandit
   never survives into our build. From kinetic_fusillade (Alira).
6. **Only rares are rolled, only uniques are fixed**: a MAGIC or NORMAL item of the author's
   becomes a rare slot on its own base (read out of the item name against PoB's base corpus),
   never a carried item. Eight references equip one. From vd_spellslinger.
7. **The skeleton carries nothing that supports nothing**: a socket group with no active gem is
   not carried (the audit's "dead support group", eight references), and a support PoB's own calc
   applies to nothing is dropped from its group -- which is why the skeleton is now derived
   inside the session, with PoB holding the author's build. From vd_spellslinger (Faster Attacks,
   Momentum) and physical_dot (Unleash).
8. **Self-costs are judged per candidate**: the tree never proposes a self-cost line of the main
   skill's kind (`self_cost.tree_patterns` into `forbid_text`), the context is re-derived on every
   reconfigure instead of once on the empty build, and a support that pays a pool per use is a
   self-cost (`mechanics/self_cost_gems.json`: Sacrifice, 20% of current life, from PoB's own gem
   data). From soulrend (the Chaos Mastery taken seven times) and poison_spark (Sacrifice, -4,636
   life per second at its cast rate).

Consequence: every reference moves, so the numbers of the frozen campaigns are not comparable
with anything built after this. The proof is the 7.1h smoke and the rerun, not these commits.

