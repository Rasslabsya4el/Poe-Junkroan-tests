# 2026-09-12 D39. Time to full DPS is a rail (ceiling on a derived stat)

Status: Accepted

PoB's DPS is a steady state: the Puncture Gladiator (843k bleed) had chosen
Crimson Dance, whose number assumes eight bleeds already on the target, at
1.39 attacks per second. Nothing in the objective saw the 5.8 s of attacking
that takes; a player does. Ramp-up is never stated numerically by build
authors, so the rail is a bar set by feel and tuned from experience.

`optimizer/ramp.py` derives `RampSeconds` from PoB's own outputs: stack
potential x max stacks and duration for bleed and ignite, `PoisonStacks` and
`PoisonDuration`, `Speed`/`HitSpeed`. DPS(t) = M(t) x sum of components,
each ailment climbing linearly to its steady state over `stacks needed /
stacks applied per second`; hits and non-stacking DoTs are immediate; M(t)
holds stacked skill parts ("10 Blades", one per cast) and withered from
hits (Withering Touch). `RampSeconds` is the first t reaching 80% of the
steady state. `Objective` gained `ceilings` and `derived` stats for it:
derived stats are computed in Python from the fetched PoB stats, so every
stage, the rig screens and every what-if trial see the ceiling for free,
and the tree optimizer can only take Crimson Dance when the attack rate
makes it fit (or buys attack speed to make it fit).

Measured at 80%: references Poison Spectral Throw 2.2 s, Viper Strike 4.2 s
(5.4 s poisons, the slowest author build), Ignite Penance Brand 0.3 s, hit
and RF-type builds 0; generated Puncture with Crimson Dance 4.6 s, Blade
Trap 0. Ceiling first set at 4.5 s so every reference passed; the user's
play experience overruled it ("4.5 is far too much, 2.5 at most"), so the
ceiling is 2.5 s and the Viper Strike reference is knowingly outside it.
This is the one rail set by feel rather than by the references. Not modelled yet: charges, rage, Trinity
resonance, impale stacks, withered from a Wither totem, the 1-stack bleed
roll average. Each becomes a component when experience says it matters.

