# 2026-09-12 D41. Weapon bases are screened by their affix ceiling, loot N stays

Status: Accepted

Measurement first (`scripts/weapon_experiment.py`, artifacts/weapon_experiment.json):
on every reference build the author's rare weapon (and shield/quiver) alone
was replaced, tree and the rest untouched, CombinedDPS as a share of the
author's over 19 weapon slots:

| weapon slot filled by | median | min | max |
|---|---|---|---|
| loot best-of-200 (the rails) | 103% | 91% | 113% |
| loot best-of-1000 | 113% | 93% | 129% |
| greedy affix ceiling under the tier caps | 130% | 100% | 154% |

So the weapon slot is not weak against the authors at equal tree and config:
N=200 already matches them, and a bigger N would leave the day-1 calibration
(D19/D21). The weak weapons seen in generated builds (a Terror Claw on Blade
Trap, an Immolate pick to make up for a bad weapon) came from the base
screen: every weapon type was judged by the best of 40 random rolls on a
bare rig that was still below every floor, so the lexicographic score
rewarded whichever roll carried life, not the type that carries the skill.

`SkeletonGenerator._ceiling`: weapon, shield and quiver bases are now
scored by their greedy affix ceiling (`GearFiller`, one craft per base,
~2 s) under the objective with floors and relations removed: damage only,
since a weapon's job is damage and the floors are bought elsewhere later.
The ceiling is a screening score, never the item: the final weapon is
still loot best-of-200 plus a bench craft. Armour and jewellery keep the
roll screen (their bases differ in defence, which the floors see).

Then the A/B (same code, weapon type forced by the request) said the bare
rig cannot rank weapon types at all: Blade Trap Trickster, sword ceiling
224 > claw 192 on the rig, but claw 65,014 > sword 49,610 as finished
builds. Without a tree and supports flat damage looks best; the claw's
attack speed only pays once the tree multiplies it. So the ceiling screen
picks the rig's favourite and keeps up to two runner-up types (ceiling at
least half the best) as `Skeleton.weapon_alternatives`; the search's
mutation round rebuilds each finalist with each alternative weapon setup
(shield or quiver adjusted), and the table ranks them together, the same
way keystones are decided (D40). The weapon base is shown in the table.

Blade Trap Trickster with the variants: rig ceilings sword 224, dagger
200, rapier 195, claw 192; as builds Demon Dagger 89,868, Harpy Rapier
59,118, Midnight Blade 49,610 (the rig's favourite came last). The
shortlist of two missed the claw (65,014 when forced), which the dagger
beats anyway; the earlier 85k claw build came from a run before the
ramp rail and the aggravation rule.

