# 2026-09-23 D99. A weapon's pair is put back after a refill; the audit flags a skeleton unique the build does not wear

Status: Accepted

Spec part 2. Cause: a quiver is legal in Weapon 2 only while Weapon 1 holds a bow (`ItemsTab.lua:2457`
`IsItemValidForSlot`, Weapon 2 branch ~2492-2496), and `ItemSlotControl.lua:94-96` `Populate()` clears an illegal
slot without a word -- every equip in the worker ends with `PopulateSlots()` (`headless_runtime_worker.py:843`). A
gear pass that empties Weapon 1 (`loot_gear.fill`'s clear loop; the loop's gear move at `pipeline.py:1356`) dropped
the skeleton's The Poised Prism silently and never put it back: 6 of the burning_arrow_snipe builds of
`new18-r3`/`new18-tpl` (111 skeleton unique placements on the five runs, 105 worn, these 6 empty); the item stays in
the XML item list while the active set has `Weapon 2 itemId="0"`. Fix: `loot_gear.restore_weapon_partner(pob,
uniques, slot)` re-equips the other weapon slot from the skeleton's uniques (`_WEAPON_PARTNER`), called at the end of
`LootGear.fill_slot` and `WishlistGear.fill_slot`; the pipeline reads the skeleton's unique raws once
(`pipeline.py:368`) and hands them to both gears (`replay_bench.py`, `gear_transplant.py` too). Construction-only
burning_arrow_snipe seed 1 (loot): 848,445 -> 984,532 (+16.0%), `Weapon 2 | 44 | Rarity: UNIQUE | The Poised Prism`.
New check `audit.audit_skeleton_uniques(xml, uniques)`: a skeleton unique whose name is on no worn item of the active
set is an `error` finding `skeleton unique not equipped: <slot>: <name>`; `audit_build` takes an optional `skeleton`
and the pipeline passes the one it built. On the five runs: 6 findings over 66 builds with skeleton uniques -- exactly
the six builds, nothing else.

