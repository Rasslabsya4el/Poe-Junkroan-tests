# 2026-09-18 D68. Day-1 rare gear may be a deterministic wishlist under realism rails

Status: Accepted

The loot simulation (D19: best of N random rares per slot) is one answer to "what does a day-1
character wear". It has two costs: a build is not reproducible (the seed spread is 41.6 points at
the median, `docs/research/2026-09-18-seed-divergence.md`), and its items are not readable -- five
affixes of which the build uses two, exactly like a real drop and exactly as hard to explain. The
second answer, now in the code behind `BuildPipeline.run(gear_mode="wishlist")` and
`scripts/benchmark.py --gear wishlist`, is the item a person writes down: "on the boots I look for
movement speed, life, resists". `optimizer/wishlist_gear.py` (`WishlistGear`) has the loot filler's
surface (`fill`, `fill_slot`, `current_raw`, a result with `raw` / `rolled` / the scores), so the
pipeline swaps one for the other in construction AND in the improvement loop's per-slot gear move,
where the slot's re-roll becomes a re-fill on the build as it stands. **`gear_mode="loot"` stays the
default until the benchmark says otherwise.**

Realism from data, not from a template. The rails (`rails_default.json` `gear.wishlist`) are the
299 real day-1 rares of the 32 Tuadh references, measured in
`docs/research/2026-09-18-author-rares.md`:

| rail | value | the measurement behind it |
|---|---|---|
| `item_level` | 72, weapons 76 | pooled ilvl median 72 (p10 54, p90 79); Weapon 1 median 76, Weapon 2 77. Our loot rolls a flat 70 (`docs/research/2026-09-18-generated-gear.md`) |
| `useful_mods` | 3, weapons 4, the bench craft counted | a real rare carries 5.17 affixes of which **2.44 are useful** (median 2, weapons 3.40 / 4.14, `useful` = PoB loses >= 0.5% of the objective or breaks a floor without it) |
| `bench_crafts` | 1 | one bench craft on 76% of their rares and never two (the game's rule); their crafts are their best mods, 68% useful against 43% for rolled ones |
| `tier` | every mod at its ladder median | their median tier is T4 at **0.50 of the ladder** on every armour slot (weapons 0.62), and tier does not predict usefulness at all (T1 40% useful, T3 49%, T7+ 43%) |
| `above_median_max` | 1, weapons 2 | 26% of their mods are T1-T2: about one per item |

The ladder is the tiers PoB allows on that base at that item level, best first, and the median
index is `(n - 1) // 2` -- the better of the two middles, which reproduces 0.50 on the common
8-tier ladder (T4). The mods a real rare carries that do nothing for the build are **omitted from
our item rather than typed into it**: that is the whole difference between "3 mods" here and their
5.17, and it is why our items read like the guide authors' wishlists (Zizaran's five starters ask
for 2.65 affixes, every item with a free affix slot) while their tiers stay the authors' own.

Nothing about which mod is chosen is authored: the filler is the existing greedy affix choice of
`gear_filler.py` judged by PoB (`craft_rare` + the item-override `trial_stats`, feasibility before
value, one slot at a time). What the rails fix is only how deep and how good the item may be. There
is no RNG anywhere in it: the candidate order is fixed (family, then tier) and ties go to the
earlier candidate, so the same build and base give the same item -- `fill_slot`'s `n` and `seed`
are accepted and ignored, and a re-fill in the loop is a deterministic function of the build.

Two decisions about the bench craft, both because a rare whose only line is a craft is not an item
a person has: it competes as one more candidate set from the second mod on, and it is counted
inside `useful_mods` (a 3-mod boot is two rolled mods and a craft). The incumbent keeps its slot
when the re-fill scores lower (D43's rule: a pass never trades down).

One rule the greedy needs that the loot filler does not. **The first mod of an empty slot is the
base's entry ticket and is taken whatever it scores**; every later mod must improve the build, and
the finished item must beat the empty slot or the slot stays empty. A base costs attributes and a
level requirement that no single affix pays back -- on the bare rig of gear pass 1 a Savant's Robe
plus one T1 cold resistance is *worse* than no body armour (viol 6.529 -> 6.883), while the
finished three-mod item is better (6.529 -> 5.750). Without the rule the greedy left 5 of
stormbrand's 10 slots empty for ever, because it never got to put anything in them.

What it does to a finished build, before any benchmark: the seed-1 builds of
`20260918-0723-rules-smoke` with their tree, gems and config untouched and every rare slot
re-filled by the wishlist in one pass (the rails' own floors, not the benchmark's author floors).

| build | stat | loot (as delivered) | wishlist | Life | TotalEHP | ms | res F/C/L/chaos | fill |
|---|---|--:|--:|---|---|---|---|--:|
| stormbrand | FullDPS | 1,421,414 | 852,153 (-40%) | 4157 -> 3760 | 10,840 -> 8,978 | 1.23 -> 1.23 | 75/75/75/-22 -> 75/75/75/-52 | 31.4 s |
| bleed_bow | CombinedDPS | 761,035 | 975,679 (+28%) | 5459 -> 3940 | 12,771 -> 8,415 | 1.22 -> 1.20 | 77/76/76/-4 -> 77/76/76/-32 | 28.5 s |

Both directions are the same mechanism and neither is a verdict: the tree under them was grown on
the loot items, and 3 mods per slot is a different budget from the loot's 4.98 affixes. Stormbrand's
attribute-hungry rig loses the spare stats and energy shield the loot gave it for free; Bleed Bow's
wishlist bow (T1 increased physical, T1 flat physical, the attribute-requirement mod, a bench craft)
is simply a better weapon than the one 600 draws found, and the rest of its gear pays for it in life
and EHP. The defence numbers fall because these floors are the rails' (Life 3700), which the items
meet and then stop at -- under the benchmark's author floors (D59/D61) the filler has to buy the
author's life and EHP before it may chase damage. Ten slots cost 28-31 s against the loot's
best-of-600 construction, and the run is reproducible: the same build gives the same items.

End to end the mode runs: stormbrand rebuilt from its skeleton with `gear_mode="wishlist"` and
deliberately tiny budgets (45 tree points, one gear pass, one loop pass) finishes in 206 s at
542,073 with the loop's per-slot gear move firing on the wishlist filler (Helmet +1.4%, Boots
+1.4%, Amulet +11.5%, Ring 1 +9.0%, Weapon 1 +0.6%). That is a wiring check, not a result.

One thing to read in the items and not in the numbers: Bleed Bow's body armour comes out with a
single mod (+44% fire resistance) and its helmet with two. Once every floor is met, a mod that adds
no damage does not clear `min_gain`, so the wishlist leaves the affix slot empty instead of filling
it with something dead -- which is exactly the shape of the guide authors' items (100% of Zizaran's
46 wishlist items have a free affix slot, against 67% of the authors' real rares).

The dead tier rails go with this entry. `max_t1_per_rare`, `max_t2_per_rare` and `max_tier` were
read by nothing the pipeline runs -- `LootGear` enforces none of them (measured: 20% of our rares
carry a mod worse than T8) -- except the weapon-base ceiling screen (D41,
`search/generator._ceiling`), whose comparison of weapon types must not move here. They are out of
`rails_default.json` and out of `GearRails`, and live on as that screen's own constants in
`GearFiller.__init__`.

