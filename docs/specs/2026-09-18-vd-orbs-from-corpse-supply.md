# Spec: Volatile Dead orbs per cast follow the corpse supply (arithmetic, not a constant)

Today `search/skeleton.instance_counts` gives a corpse-fed skill (Volatile Dead, Cremation, Detonate Dead...)
a fixed count = corpses consumed per cast x cascade areas (VD: 3 x 3 = 9 with a regular Spell Cascade), from PoB's
skill data (`skill_facts.corpses_consumed_per_cast`, `cascade_areas`). The user's reading of the Reddit sources
(2026-09-18): 9 holds only when the corpse SUPPLY per VD cast is at least 9 -- Desecrate makes 5 corpses per cast
(PoB constant), the pool is capped at 10 (12 with Undertaker's +2), and a Desecrate linked to Spell Cascade makes
3 areas x 5 = 10 at once; a plain Desecrate alternating 1:1 with VD supplies ~5, so ~5 orbs.

Rule: orbs per cast = min(consumed_per_cast x areas_of_the_consumer, supply), supply = min(pool_cap,
corpses_created_per_cast(creator) x areas_of_the_creator x casts_of_creator_per_consumer_cast); casts ratio =
1 for a triggered pair (Spellslinger triggers both per attack) and for hand-cast alternation (the default; the
same halving `ramp_inputs.corpses_consumed_recently` uses), 2 if the build carries two creator casts per consumer
(not modelled today: leave a TODO, ratio 1). Every number from PoB's data: creator/consumer/areas via skill_facts
and the socket-group links (a Spell Cascade support in the creator's group -> its areas; Awakened Spell Cascade ->
its own areas), the pool cap from the Desecrate gem's own stat plus Undertaker's +2 when that ascendancy node is
allocated (corpus ascendancies.json). No consumer/creator -> the count stays as today (1).

Measure and report: instance_counts on tests/fixtures/tuadh_329/archmage_volatile_dead.pob.txt (Desecrate + Spell
Cascade: expect 9) and vd_spellslinger.pob.txt (Spellslinger + Desecrate + Spell Cascade: 9), and on a copy of the
archmage fixture with Spell Cascade removed from the Desecrate group (expect 5); the author's FullDPS under our lane
for each (benchmark's flag_main_group_for_full_dps with the derived count).

Tests: unit tests with fake skill data for the three cases above and for the Undertaker cap (12); a PoB-backed test
(skip without var/cache/pob) on archmage_volatile_dead asserting 9 and on the Cascade-less copy asserting 5. Run
`python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_corpse_counts.py tests/test_skeleton_from_xml.py`
plus your tests, then the whole suite once, in the foreground. Commit on your branch with the numbers in the message.
