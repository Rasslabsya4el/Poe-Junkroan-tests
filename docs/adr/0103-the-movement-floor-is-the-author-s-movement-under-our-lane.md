# 2026-09-26 D103. The movement floor is the author's movement under our lane (amends D55)

Status: Accepted

`scripts/benchmark.py author_floors`: `EffectiveMovementSpeedMod` is read from `author_lane` like TotalEHP (D61), no
longer from the author's own config. impale_cyclone's author reaches 1.35 with his config and 1.0665 under ours
(Cyclone), so the old floor 1.164 was one he failed himself and the reference counted 0 of 3 seeds on BOTH gears; the
new floor is 1.0345, which the loot's 30% boots pass. It is the only one of 58 references whose raw and lane values
differ. Templates still miss it on both cyclone references (T3 boots, 25% increased Movement Speed = 1.027 under
Cyclone): whether the boots' movement line takes the tier the floor needs is the owner's call.
