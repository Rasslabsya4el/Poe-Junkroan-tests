# 2026-09-12 D33. Night run: six skills through the search, what broke, what changed

Status: Accepted

Searches: Fireball, Lightning Arrow, Cyclone, Essence Drain, Toxic Rain,
Blade Vortex (all ascendancies, top 2-3, 30-45 min each); references rebuilt
twice. Every finding became a rule or an audit check:

- **Ailments.** PoB applies the main skill's own chill/shock/scorch from the
  hit (`ChillVal`/`ShockVal` vs the ailment threshold) and sets the enemy
  condition itself, so the "enemy is chilled/shocked" checkbox stands for a
  *second* source only: another hitting skill of that element (minions,
  auras, heralds, curses excluded). A Fireball build had "chilled" on from a
  1% cold portion; Storm Brand's 8k lightning hit shocks a Pinnacle boss for
  0% by PoB's own model, so "shocked" is off unless Orb of Storms & co. are
  there. Freezing a boss is optimistic-only. Damaging-ailment proof uses the
  applied probability 1-(1-p)^(hits/s x duration) >= 0.9 instead of a flat
  50% chance (a 14% bleed at 4 hits/s over 5 s is 95%).
- **Sustained conditions** ("used a warcry recently", movement, channelling,
  "used a fire skill") need a gem of that kind; "crit recently" needs >= 5%
  crit chance.
- **Optimistic lane** no longer carries PoB display switches (PvP scaling,
  ignore jewel limits, enemy max resist) and drops any toggle that lowers the
  objective (Unholy Might zeroed a Cyclone Champion). The audit flags
  optimistic < conservative.
- **Generator.** Weapon types the skill cannot use (0 DPS) never win on
  defence (Lightning Arrow got a claw); bows get a quiver screen; mine / trap
  / totem / trigger supports are hypothesis-only (Locus Mine won a bare rig);
  rig supports are picked after cheap gear and half a tree (bare rigs favour
  Decay and Added X).
- **Sustain and the tree.** With the sustain relations in the tree objective
  the greedy bought mana nodes early (Poison ST 33k vs 70k); tree stages now
  optimize without sustain, gear delivers it, the touch-up repairs under the
  full objective. Bandit and pantheons are chosen by PoB.
- **Open, not built (no new features tonight):** numeric skill options and
  gem stage counts (Toxic Rain pods, Blade Vortex blades: PoB default 1 ->
  Blade Vortex screens at 31k), utility links, Warden.

References after the night (author under our conservative lane): Cold DoT
105%, Smite 125%, Poison ST 82%, Spark 78%, Stormbrand 73% (was 126%: the
author's assumed shock is gone; PoB applies none on a Pinnacle boss).

