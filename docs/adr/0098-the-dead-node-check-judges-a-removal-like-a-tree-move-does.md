# 2026-09-23 D98. The dead-node check judges a removal like a tree move does: real removal, then the lane it stands on

Status: Accepted

Spec `docs/specs/2026-09-22-audit-dead-nodes-and-unequipped-uniques.md` part 1, closing D87's open item ("the audit's
dead-node check is frozen-config blind in the same way"). Measured per node on the 19 flagged rows (12 builds of
`core14-tpl`, `new18-r3`, `new18-tpl`, `ziz-rules`): (a) removal with the config frozen, (b) removal +
`derive_config` and the lane apply, (c) whether the removal cascades. Verdicts: 0 truly dead, 16 travel, 3 proof
holders (the 16 cascading rows cover the 12 flagged builds). The frozen pass was wrong twice over. `pob.trial_stats(..., mode="fast")` does NOT cascade, so a bridge
node measures 0 there while PoB's own removal takes everything it connects: spark 8198 -5.0651%/-4.9799%/-5.0808%
(drops the 1 allocated node 13164 Divine Judgement); Minion Life 10904 and 34880 -90.576%/-77.725%/-77.010% (tpl) and
-76.413% (loot s1), dropping 78 and 79 of 111 allocated nodes on tpl s1 and 67 and 68 on loot s1, with Life, resist
and requirement floors among them; z325 32690 -7.0194% (drops 64882 Disciple of the Unyielding) and 57011 -7.0194%
(drops 32690 and 64882); z326 32690 and 57011 -2.2727% (drop 64882) and 16213 -6.1818% (drops 58921 Disciple of the
Slaughter). And the poison_spark 11984 proof holder moves nothing frozen but -22.466%/-14.605%/-25.667% after the
re-derive, carried by the `custom_mods` lane block (poison stacks 8 of 10.01 -> 6 of 8.01): the boolean
`_lost_proof_inputs` list never changes, so the lane fingerprint is what sees it. Fix, reusing the D87 machinery
(`tree_hygiene._check_config_proof`): only a row the frozen batch called dead/weak gets a real `mutate_nodes` removal
plus `derive_config`; the frozen stats judge it first (travel when other allocated nodes came with it, else live),
the lane delta judges it second (proof), and only what still moves nothing stays an error. `TreeLeaf` gains the
`travel` and `live` statuses and the reader table prints the reason. Audit of the 12 flagged builds: error-severity
dead-node findings 19 -> 0, warnings unchanged; 29 further counted builds of the same runs identical before/after
(41 rows: 21 -> 2 errors, 35 warnings both times). The 2 remaining errors are one Mana Mastery 53188 in
`archmage_volatile_dead` tpl s2 and s3 that moves only `ManaRecoup` -- correct, outside the objective and outside
the flagged table. Nothing changed in the optimizer: those rows only stop being called dead. Whole suite after the
change: 1046 passed, 7 deselected, 0 failed (17 min). A first run under a loaded machine showed 5 failures: 3
real ones from `pipeline.py:368` reading `skeleton.uniques` off the `test_construction_rig` fake -- fixed by giving
the fake the field -- and 2 timing flakes in `test_benchmark_durable`, green in isolation.

