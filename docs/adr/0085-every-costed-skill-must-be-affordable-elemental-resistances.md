# 2026-09-20 D85. Every costed skill must be affordable; elemental resistances fill the build's own maximum

Status: Accepted

The user's reading of `core14-rules` physical_dot (19.09): "Unreserved mana 8. How is the player supposed to use Flame
Dash or Shield Charge?" and "Max cold res is 76 and the build has 75". Two floors of the Objective, so tree, gear,
picks and the reservation-drop move (D72) all see them.
(A) **Castability = PoB's own warning rule** (`Calcs.lua` 433-456, "You do not have enough Mana to use: ..."): for every
enabled skill of the player with a cost -- triggered ones included (poewiki Trigger: "Their cost must be paid
normally"), the player's own summon skills included, minion attacks and gems disabled by D83 excluded -- cost <= pool,
where the pool is unreserved mana + energy shield when the calculation's modDB carries `EnergyShieldProtectsMana`
(Eldritch Battery; read per calculation, so a trial that drops the keystone sees its own flag), a skill with a
reservation of its own is checked against pool + that reservation, equality passes; life costs against unreserved
life. The MAIN skill's relations are live in every trial (`ManaCostPool >= ManaCost`); the largest cost of the other
skills is a frozen number refreshed after a skills write, at each loop pass and at the final audit (one shared
computation: 7 reads / 6.1 s per stormbrand build against 718 / 112 s before the budget, trajectory byte-identical).
(B) **Resistances**: `FireResist >= FireResistMax` etc., the maximum read from PoB as Resist + MissingResist; the
constant 75 and every fixed author resistance floor are gone (the author's raised maximum is already floored by the
maximum-hit floors, D53).
Measured on the 96 delivered builds of `new18-rules` + `core14-rules` and the 32 authors: 15 builds (37 skills) and 1
author cannot use a skill -- every finding is in PoB's own list name for name, zero false positives; 12 builds and 6
authors sit below their own maximum; 6 authors run Eldritch Battery and are clean. Known consequence: the gem rail's
level-18 Precision / Clarity inflates reservation (D86 in work: the level of a flat-reservation aura is PoB's choice).
The floors' own cost in damage is not measured yet: the replay bench (D84) measures it. Branches
`gpt-2026-09-19-usable-skills-and-max-res-floors` -> `...-amendment` -> `...castability-refresh-budget`.

