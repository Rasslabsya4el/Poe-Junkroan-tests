# 2026-09-18 D73. Day-1 gear solves attributes and resistances implicit-first: bases before affixes

Status: Accepted; amended by D73 amd 1

The user, 2026-09-18: **item bases are the cheap, guaranteed half of a day-1 item.** A base with the
right implicit -- Onyx Amulet +16 to all attributes, Agate / Jade / Turquoise amulets, Two-Stone and
Prismatic rings, a Rustic Sash's global physical damage -- drops from mapping by the million and a
loot filter shows it at any rarity, while every affix has to be rolled or crafted (and a day-1 item
gets one easy bench craft at most). So attributes and resistances are solved implicit-first: the
base per slot is chosen for the build's needs, then **at most one** attribute affix or craft on the
item, then one or two useful mods. Tree nodes for attributes and resistances are poor value outside
stackers. The system credited implicits with nothing at all: the wishlist filler (D68) took whatever
base the skeleton handed it, and the base screen (D41) chose a jewellery base by rolling 40 random
rares on each -- an implicit judged through the noise of the affixes rolled on top of it.

**What the filler does now** (`optimizer/wishlist_gear.py`, wishlist mode only; the loot simulation
is untouched). For **every** rare slot, not only the jewellery:

1. the **class** stays the skeleton's -- a bow build stays on bows, a body armour slot stays a body
   armour -- because which weapon the build fights with and which slot carries which item is a
   decision about the build, already made with a number (the weapon ceiling screen, D41);
2. inside that class, every base a day-1 character can find is a candidate: PoB's `not_for_sale`
   (atlas-only, Synthesis, Necropolis), `experimental_base`, `demigods` and the talismans are out,
   and so is any base whose **drop level is above `gear.wishlist.area_level` = 77**, the area level
   of the T10 maps a day-1 character runs (`docs/research/2026-09-18-day1-gear.md`, PoE Wiki map
   tiers). That cap is what rules out a Vermillion Ring (80) or a Crystal Belt (79) -- and it caught
   a real one: bleed_bow's author wears a Conqueror's Helmet, drop level 78, which no day-1
   character has. The level-1 bases are **in** (Rustic Sash, Coral / Paua / Iron Ring, Coral
   Amulet): their implicits are free and that is the whole point;
3. every candidate is judged **bare** -- nothing on the item but its implicit and its own defence or
   damage -- in one item-override trial each (7 ms), feasibility before value;
4. the best `base_candidates` = 3 are each filled with the wishlist affixes and the best **finished**
   item wins the slot. A base is never asked to pay for itself bare; the item is.

`Rails.gear.wishlist` gains `area_level` 77, `base_candidates` 3 and **`attribute_affixes_max` 1**:
at most one affix from the attribute families per item, rolled or crafted, the implicit not counted.
The attribute mods are not a hand-written list -- PoB tags them itself (`mod_tags` "attribute", on
the explicit ladders and on the bench rows alike), so +30 to Strength, +16 to all Attributes and the
hybrid "+X to Strength and Dexterity" are all recognised and a resistance mod is not.

The search's base screen (`search/generator.screen_bases`) skips the armour and jewellery slots in
wishlist mode and names only the class: 40 random rolls per base to pick a base the filler will
overrule is wasted PoB time. The weapon screen is unchanged. `SkeletonGenerator` takes `gear_mode`
and `search/runner.prepare_candidate` passes it; the loot path's candidate set is byte-identical
(checked base by base at max levels 60/70/77).

**One tie-break, and why it is needed.** An attack build whose weapon slot is not filled yet has no
number at all: bleed_bow with its ten rares stripped scores 0 DPS at an *infinite* violation, and
there every body armour of every defence type scores exactly the same. `loot_gear._rank` compares a
candidate with the state it came from, and inf - inf is nan, which loses to nothing and wins against
nothing -- so the first candidate in the list won, and the list was in name order: Arena Plate,
Ambush Mitts, Ambush Boots, Agate Amulet. (`_comparable` now gives such a candidate -inf instead.)
The tie goes to **the base the slot came in with** -- someone chose it with a number the filler does
not have here -- then to the base that drops deepest, which is the class's strongest, then to the
name. The same nan blinds the greedy affix choice of both fillers while the build has no weapon;
that is a separate fix with its own measurement (the honest one is to fill the weapon first).

**Measured**, on the seed-1 builds of `20260918-0723-rules-smoke` with their tree, gems and config
untouched and every rare slot re-filled in one pass under the rails' own floors -- the wishlist
filler with base choice against the same filler without it (D68):

| build | stat | D68 | D71 | Life | TotalEHP | res F/C/L | Str/Dex/Int vs req | fill |
|---|---|--:|--:|---|---|---|---|--:|
| stormbrand | FullDPS | 900,313 | **1,183,678 (+31.5%)** | 3478 -> 3791 | 7,800 -> 8,682 | 75/75/75 both | 339/154/638 vs 146/102/152 -> 404/136/553 vs 180/102/154 | 28 s -> 103 s |
| bleed_bow | CombinedDPS | 751,998 | **826,575 (+9.9%)** | 3144 -> 3132 | 3,280 -> 3,295 | 17/34/-54 both | 332/192/163 vs 194/185/146 -> 322/157/153 vs 146/151/146 | 15 s -> 51 s |

Both builds keep every floor they met and pay for the damage with nothing. Stormbrand's rings become
Coral Rings (+25 life implicit) instead of Two-Stone, its amulet a Citrine (+20 Str/Dex) instead of
a Jade, its weapons Void Sceptres (40% increased elemental damage) instead of the author's Karui and
Blood Sceptres; bleed_bow keeps every armour base it came with (the tie above), swaps the
over-level helmet for a Lion Pelt and the bow for a Harbinger (40% increased critical strike
chance), and its attribute requirements fall by 48 Str and 34 Dex because the bases stopped costing
what the affixes then had to pay back. The finished stormbrand amulet reads exactly like the rule:
**Citrine Amulet (+20 to Strength and Dexterity) - +15 to all Attributes - +122 to maximum Life -
+28 to maximum Energy Shield (craft)**. Three bases filled instead of one costs 3.4x the fill time
(10 slots: 28 -> 103 s, 15 -> 51 s), which is 1-2 minutes per build.

Not measured here: the benchmark. `gear_mode="loot"` is still the default (D68) and nothing in the
loot path moved, so this changes no benchmark number until the wishlist mode is gated on one.

### 2026-09-18, amendment: a base is ranked with the cheapest payment of its own requirement

The user, 2026-09-18: *"how does the system know that between a helmet with 100 armour at Strength
100 and one with 400 armour at Strength 155 it should pick the second, paying the 55 Strength?"* It
did not. The screen judged every base bare, and a base whose attribute requirement the build does
not meet breaks the `Str >= ReqStr` relation, which puts it below **every** feasible base and out of
the three that get filled. The 55 Strength is one affix; whether 400 armour is worth one affix is a
question only PoB can answer, and it was never asked.

**The rule.** A candidate base whose bare trial breaks nothing but the attribute relations is
re-trialled with one attribute mod on it and ranked by that trial. "Nothing but": the constraints
its bare trial misses that the **empty slot did not already miss** must all be `Str/Dex/Int >=
Req*` -- a +Strength suffix buys Strength, not life, resistance or movement speed, and a floor the
empty slot already missed is not the base's doing. What the item can pay is read from PoB, never
from a constant: the explicit ladders at the rails' tier rule (the median tier, plus the best legal
tier while the slot's above-median allowance is unspent) and the bench crafts, both recognised by
PoB's own `attribute` mod tag, with the amount parsed off the mod's own line at the roll the filler
crafts (`min + 0.5 * (max - min)`, PoB's `itemLib.applyRange`) -- so "+(36-40) to Strength" pays 38,
"+(15-19) to Strength and Dexterity" pays 17 of each, and the bench's "+28 to Dexterity" pays 28.
The cheapest payment that closes **every** gap wins: one that leaves the above-median allowance
unspent first, then the one that pays most for the attribute with the largest gap (a hybrid or an
all-attributes mod is what closes two), then the mod id. A gap no single mod covers is not paid --
the base stays infeasible, and the loop's later re-fill sees the build's attributes as they then
are. The payment is kept only when PoB ranks the paid item above the bare one.

**The price is inside the comparison.** The mod travels into the fill as a placed mod: it counts
against `useful_mods` and against `attribute_affixes_max`, so the 400-armour helmet arrives with two
free useful mods and the 100-armour one with three, and the finished items decide. The log names
it: `Lion Pelt (Dex 150: paid by +40 to Dexterity)`, `Sinner Tricorne (Dex 138: paid by +28 to
Dexterity craft)`.

**One guard, and the measurement that forced it.** A paid base outranks a cheaper one on the bare
trial by construction -- it is the heavier base -- so three paid bases can fill the screen and the
cheap base never gets built. Measured on burning_arrow_snipe s1's weapon: the Citadel Bow (185
Dexterity against the build's 159) and two more Dexterity-short bows pushed the Ivory Bow out of the
three, and the finished Citadel Bow, one mod poorer, was **2,053,778 against the Ivory Bow's
2,112,360 (-2.8%)**. So when every base the screen keeps had to be paid for, the best base that
needed no payment is kept as well (`keep` + 1 bases filled). With it, PoB chose the Ivory Bow again
at 2,112,360.

**Measured**, seed-1 builds of `20260918-0723-rules-smoke`, one slot emptied and re-filled under the
rails' objective, the filler with the amendment against the filler without it:

| build | slot | without | with | bases the screen filled, without -> with |
|---|---|--:|--:|---|
| burning_arrow_snipe | Weapon 1 | 2,112,360 Ivory Bow | 2,112,360 Ivory Bow | Ivory/Sniper/Decurve -> Citadel/Highborn/Thicket **+ Ivory** |
| burning_arrow_snipe | Body Armour | 1,871,481 Saintly Chainmail (3 mods) | 1,871,481 Saintly Chainmail (Dex 151 paid by +28 Dex craft, 2 mods) | + Assassin's Garb |
| bleed_bow | Body Armour | 761,035 Astral Plate | 761,035 Astral Plate | Astral/Necromancer Silks/Savant's Robe -> Astral/Vaal Regalia/Widowsilk Robe |
| impale_ballista | Body Armour | 72,629 Astral Plate | 72,629 Astral Plate | Astral/Destroyer Regalia/Spidersilk -> Astral/Widowsilk/Occultist's Vestment |
| stormbrand | Boots | 728,117 Goliath Greaves | 728,117 Goliath Greaves | Goliath/Titan/Dragonscale -> Slink/Stealth/Goliath |
| stormbrand | Helmet | 710,771 Hubris Circlet | 710,771 Hubris Circlet | unchanged |
| cold_dot | Body Armour | 346,573 Vaal Regalia | 346,573 Vaal Regalia | unchanged |
| summon_raging_spirits | Body Armour | FullDPS 1,456,366 Carnal Armour | FullDPS 1,456,366 Carnal Armour | unchanged |

So on these eight slots the amendment moves **which bases PoB gets to compare** and no number: the
heavy bases now reach the fill and PoB keeps choosing the light ones. That is the honest result --
the blind spot is closed at no cost, not a gain. It costs one `list_item_mods`, one
`list_bench_mods` and one craft per base that has a gap, plus a second trial round trip:
stormbrand's helmet slot went 4.6 s -> 5.0 s.

Against PoB (`tests/test_wishlist_gear_pob.py`): the cold_dot fixture with its helmet off has 112
Dexterity, and the Lion Pelt (150), Sinner Tricorne (138), Silken Hood (138) and Ursine Pelt (114)
are each ranked with the mod that closes their own gap and are feasible on `Dex >= ReqDex` with it
on; the Hubris Circlet, which the build already meets, is paid nothing.

