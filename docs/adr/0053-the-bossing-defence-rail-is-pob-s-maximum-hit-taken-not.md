# 2026-09-14 D53. The bossing defence rail is PoB's maximum hit taken, not TotalEHP

Status: Accepted

TotalEHP averages block in: on the 14 references it runs from 8,800 (Spark,
20% block) to 38,343 (Summon Raging Spirits, 75% block), and a block build
met the floor with a defence that the user's experience says is a mapping
defence (many boss abilities cannot be blocked). PoB's own "EHP calc
unlucky" halves block, evasion and spell suppression together, and
suppression capped is a bossing layer, so it was refused. PoB's
`<Type>MaximumHitTaken` carries no block, no evasion and no partial
suppression (CalcDefence: suppression enters damage reduction only at
100%), and on the same references it is flat (physical 4,551-6,913).

The floors are now per damage type (physical, fire, cold, lightning) at
the references' lower quartile in the rails (4,700 / 14,800 / 14,600 /
16,000) and at 0.95 x the author's in the benchmark, exactly as life and
resists; chaos is not floored (every day-1 reference runs negative chaos
resistance), like chaos resistance. TotalEHP leaves the objective and
stays in every report as the mapping number; ties among config choices
and bandits break on the smallest maximum hit; the search's Pareto front
ranks DPS against it. Life and the maximum hits are separate rails, as
life and EHP were: a build cannot trade one for the other. Decided with
the user 2026-09-14; the numbers of every earlier run stand under the old
rail.

