# 2026-09-11 D28. Movement speed is a rail, delivered by gear; gear passes are monotone

Status: Accepted

The 10 reference builds sit at PoB `EffectiveMovementSpeedMod` 1.19-1.43
(lower quartile 1.22; boots carry 22-30% MS). Generated builds had 0.95-1.17
and boots without movement speed. `rails_default.json` floors now carry
`EffectiveMovementSpeedMod: 1.2`. The tree stages optimize *without* that
floor (`Objective.without`): the tree cannot buy movement speed efficiently
and, with the floor, Spark's greedy tree lost 22% DPS chasing it; boots and
the bench craft (20-24% MS) deliver it in the gear passes. Gear passes now
keep the incumbent item as a candidate, so a later pass never trades down;
a third gear pass runs under the finished tree (the pass-2 weapons had been
chosen while the tree still lacked attributes: Stormbrand best-of-200 on
the final tree was +15%/+26% over them) followed by a short tree touch-up.

