# 2026-09-26 D102. On a feasible build the loop re-fills a template slot's open lines by value

Status: Accepted

`--gear wishlist` only; merged 1a58ee8 (spec `docs/specs/2026-09-26-template-loop-lines-by-value.md`, reading
`docs/readings/2026-09-26-template-weak-tail.md`). Over 192 template builds 698 of 1,359 flexible armour / jewellery
lines (51%) added +0 `CombinedDPS` (`scripts/template_line_census.py`): D89's rule 3 buys a floor first, and it ran
while the slot was rebuilt from its bare base, i.e. while the build missed floors; the loop re-filled the slot by the
same deterministic rule, so "a damage line here, the tree pays the floor" was never tried (burning_arrow_snipe: both
rings "+(21-25)% to Chaos Resistance" at +0). Now, when the incumbent build meets every floor, the loop's gear move fills
that one slot with `WishlistGear.flexible_by_value` set: rule 2 (the weapon rule) applies to armour and jewellery too
(a line that worsens a floor or adds +0 is refused, the best value wins); the existing tree repair and judge decide; a
rejected re-fill is skipped while the build's fingerprint (tree, lanes, gems, items) is unchanged. Construction, the
kicks and an infeasible build keep rule 3. The owner, same day: three lines per armour / jewellery item stays the
day-1 level (Tuadh authors carry 5.4, the loot 6.0, templates 3.2); template work changes WHICH lines, never how many.
Also fixed that day (47b03b3, a bug, not a rule): a one-handed weapon in Weapon 2 took the shield template ("One Hand
Sword" against the corpus's "One Handed Sword"): smite 77.9 -> 94.6, regular_viper_strike 90.6 -> 95.2 (templates,
seeds 1-3, `offhand-fix-tpl` against core14-tpl-main3). D102's own verdict: `tpl-byvalue-smoke-s4` against
`main3-tpl-smoke-s4-lap`, per build, plus the census's +0 share (59% on that baseline).

