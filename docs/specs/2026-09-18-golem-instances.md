# Spec: golem gems count golems, not gem x limit

Problem (found 2026-09-18 by the over-limit-gems work, D65): `derived_counts` (src/junkroan/search/skeleton.py,
used by `benchmark.py` to flag the author's main group for full DPS and by the pipeline for our build) gives
EVERY golem gem `ActiveGolemLimit` instances, so a build with three golem gems and a limit of 3 counts nine
golems in PoB's FullDPS, where the game summons three (one per gem; a single golem gem may summon up to the
limit only when it is the only golem gem). Fix the count: with G golem gems (corpus tag "golem" on the active
gem; see how derived_counts finds golems today) and limit L = PoB's `ActiveGolemLimit`, each golem gem counts
`L // G` instances and the remainder goes, one each, to the first gems in socket-group order until L is
reached; a build with G > L keeps the first L gems at 1 (the skeleton already drops the extra ones at
derivation, D65). Minions of other kinds are unaffected.

Measure and put in the report: `derived_counts` before/after on tests/fixtures/tuadh_329/cold_dot.pob.txt
(4 golem gems, limit read from PoB) and on summon_raging_spirits.pob.txt (no golems: unchanged), with the
FullDPS the author's build reads when its golem groups are flagged for full DPS with the old and the new
counts (use `benchmark.flag_main_group_for_full_dps` only if it applies; otherwise read the counts alone).

Tests: a unit test with a fake PoB (style of tests/test_skeleton_from_xml.py or tests/test_over_limit_gems.py)
for G=1,L=3 -> 3; G=3,L=3 -> 1 each; G=2,L=3 -> 2 and 1; G=4,L=3 -> 1,1,1,0; plus a PoB-backed test on cold_dot
(skip when var/cache/pob is missing) asserting the new counts. Run
`python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_skeleton_from_xml.py tests/test_over_limit_gems.py`
plus your tests, then the whole suite once.
