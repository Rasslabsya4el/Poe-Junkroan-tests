# 2026-09-12 D42. Skill parts named "Maximum" are assumptions, never picked

Status: Accepted

The first benchmark run (scripts/benchmark.py) had Spark at 399% of the
author: the part picker (D36) had taken PoB's "Maximum Hits" part, which
multiplies the number by 1 + floor(duration / 0.66), every projectile
hitting the target for its whole life; the author runs "1 Hit". PoB's
parts are of two kinds: a state the player builds and holds ("10 Blades",
"5 Stages"; the ramp rail judges the time it takes) and an assumption
about the fight ("Maximum Hits"). `generator.part_is_assumption`: a part
named Max / Maximum is never chosen for the conservative number; the
picker takes the best of the remaining parts.

The same run also found the over-reservation scale bug: with the author's
auras on a bare rig, ManaUnreserved is negative against a ManaCost of 0,
and the relation shortfall was divided by max(1, floor) = 1, so it
counted as a violation of 300 while a missing 786 life cost counted 0.83.
The tree greedy took Blood Magic (Physical DoT: 173 -> 3.6 "violation")
and the build ended unable to cast (audit error). Dividing the shortfall by
|observed| gave a constant 1.0 for any over-reservation (no gradient: a
Physical DoT seed ended at ManaUnreserved -118 with nothing pulling it
up). Relations may now name a pool as a fourth element (`("ManaUnreserved",
"ManaCost", 1.0, "Mana")`): when the pool is over-reserved the violation
is the whole floor (1.0 if there is a cost) plus the excess relative to
the pool, so every reservation node shrinks it; a plain shortfall stays
relative to the floor. The benchmark also rebuilds each reference without
each keystone the tree took (D40) and keeps the best per reference.

