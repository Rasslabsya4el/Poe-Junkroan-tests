# 2026-09-19 D76. One shared rule decides which benchmark rows count

Status: Accepted

`benchmark.py` and `compare_runs.py` use one persisted-row predicate: a row counts when it is `ok`, its last
stage violation is at most `1e-9`, and it has no audit error except `fixed point`. The audit strings are parsed
as `Finding.__str__` writes them, so the check name is the text after severity and before `:`. A fixed-point
finding is a stability result, not an infeasible or logically invalid build; its row remains in the median while
the report names the fixed-point gain separately.

This closes the disagreement in `20260918-1526-gear-loot`: the former benchmark table dropped the three
fixed-point-only rows and reported Burning Arrow / Impale Ballista / SRS as **184 / 92 / 183**, while the
comparison's all-`ok` medians were **179.7 / 92.4 / 158.9**. The common rule yields the latter reference values
and a median of medians of **150.15**. All medians use `statistics.median`, including the mean of the two middle
values for an even number of counted rows. Violation exactly `1e-9` counts; any greater value does not. Existing
rows without persisted audit strings retain the old clean/dirty behavior through `audit_errors`.

**D75 amendment 2 (2026-09-19): a warcry that grants charges per Warcry Power is a classified source; "when you
are Hit" is a pending fact.** Enduring Cry's charges per use are PoB's own numbers -- the gem's constant
`endurance_charge_granted_per_X_monster_power_during_endurance_warcry` (5) against the `WarcryPower` PoB's calc used
(20 against a boss) -- and its period is the `Cooldown` PoB outputs for that skill (3.234-8.019 s on the seven
references), read through the new harness call `PobSession.active_skill_stats` (selects the skill, reads the
output, restores every selection; the restore is tested by an equal XML and equal stats). Any warcry whose skill
data carries a `*_charge_granted_per_X_monster_power*` constant goes through the same code. Seven Zizaran
references get `useEnduranceCharges` back; the two juggernaut_boneshatter references stay off with the reason
"needs the enemy's hit rate: pending fact `enemy_hits_per_second`" (`mechanics/pending_facts.json`, no value).

