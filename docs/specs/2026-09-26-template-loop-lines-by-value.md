# Spec 2026-09-26: on a build that meets every floor, the loop re-fills a template slot's open lines by VALUE (CODE ONLY, ~30 min)

Lead: Opus 5.5. Worker: DeepSeek V4.1 Flash. No PoB, no `machine_load`, no benchmarks, no whole suite. Only the files
named below. No scratch files in the repo (`tmp_*`, `_scratch_*`): use your own temp dir. Durations in the report in
human units (principle 7).

## Why (measured by the lead, 2026-09-26)

`--gear wishlist` (template gear). An armour or jewellery item is life + one resistance + ONE flexible
`open_or_craft` line. That line is chosen by `WishlistGear._choose_trial` "violation first" (rule 3, D89): the
candidate that removes the most floor violation wins, value only breaks ties. The choice is made while the slot is
being rebuilt from its bare base, so the build is momentarily missing floors and the line buys a floor. The loop's
gear move re-fills the slot by the SAME deterministic rule, so it rebuilds the same item and the loop never tries
"a damage line here, and the tree pays the floor".

The final gear summaries of 192 template builds (core14-tpl-main3, new18-tpl-main3-lap, ziz-tpl-main3-lap,
main3-tpl-smoke-s4-lap): 1,359 flexible armour/jewellery lines, **698 (51%) added +0 to `CombinedDPS`**; the most
common is "+#% to Chaos Resistance" (195, it buys the `TotalEHP` floor). burning_arrow_snipe s3: both rings carry
Chaos Resistance at +0, where the author wears "Adds # to # Lightning Damage to Attacks".

## The rule

While the build meets every floor (`cur.feasible` in the loop), the loop's gear move on a TEMPLATE slot re-fills its
flexible lines by value: rule 2 (the weapon rule) is applied to armour and jewellery too -- a candidate that worsens
a floor is refused, a +0 candidate is refused, the best value wins. The existing code after the fill already asks the
tree to repair a floor the new item misses (`tree.refine(max_rounds=0, repair_rounds=60)`), and the existing judge
keeps the move only if it beats the incumbent. Construction (gear pass 1/2), the joint kicks and a build that misses
a floor keep today's behaviour exactly.

## Steps

1. `src/junkroan/optimizer/wishlist_gear.py`
   a. `WishlistGear.__init__`: add `self.flexible_by_value = False` with a one-line comment: set only by the loop's
      gear move (spec 2026-09-26), never by construction.
   b. `WishlistGear._choose_trial` (~line 701): today
      `value_first = self._buys_value(base, slot) if buys_value is None else buys_value`.
      Change to `value_first = (self._buys_value(base, slot) or self.flexible_by_value) if buys_value is None else buys_value`.
      An explicit `buys_value=False` (the base-attribute payment, `paying`) stays False. Nothing else in this file.

2. `src/junkroan/optimizer/pipeline.py`, `_improvement_loop`, the branch `elif kind == "gear":` (~lines 1353-1392).
   a. Next to `last_rejected_weapon_base: dict[str, tuple] = {}` (~line 932) add
      `last_rejected_value_fill: dict[str, tuple] = {}`.
   b. In the gear branch, after `move_state = snapshot_move()` and before `self.pob.equip({slot: None})`:
      `by_value = isinstance(loot, WishlistGear) and cur.feasible`.
      If `by_value`: `fingerprint = self._weapon_base_fingerprint(loot, skeleton, slot, config_xml=move_state["xml"])`
      (it is a generic fingerprint of the tree, both lanes, the gems and every other item; reuse it as is). If
      `last_rejected_value_fill.get(slot) == fingerprint`: log
      `f"{label}: value re-fill skipped, nothing changed since the last rejected trial"`, call
      `record_move(f"gear {slot}", t0, cur, cur, kept=False)` and `continue` (copy the shape of the weapon-base
      skip at ~line 1325).
   c. Around the existing `res = loot.fill_slot(...)` call: if `by_value`, set `loot.flexible_by_value = True` just
      before it and reset `loot.flexible_by_value = False` in a `finally:` right after it (the reset must also happen
      when `fill_slot` raises).
   d. When `by_value` and the judge does NOT keep the move (the `if judge(...)` is false), store
      `last_rejected_value_fill[slot] = fingerprint`. When the judge keeps it, `last_rejected_value_fill.pop(slot, None)`.
   e. A one-line comment at 2b with the rule and this spec's file name. Nothing else in this file.

3. Tests (add, never edit an existing test). Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_wishlist_gear.py tests/test_wishlist_gear_quiver.py tests/test_wishlist_gear_offhand.py tests/test_improvement_loop.py tests/test_weapon_base_move.py`
   a. `tests/test_wishlist_gear.py`, copy the shape of
      `test_an_armour_open_line_buys_a_real_floor_repair_but_not_a_rounding_one`: a Helmet whose mods are the life and
      resistance tiers plus `_mod("IncreasedMana", "Suffix", mod_id="Mana", ...)` (repairs a Mana floor shortfall of
      0.05 at +0 value) and `*_tiers("OpenDamage", "Prefix", 8)` with `worth={"OpenDamage4": 9_000.0}`. With the default
      `flexible_by_value = False` the fill buys `Mana`; with `gear.flexible_by_value = True` set before `fill_slot` it
      buys `OpenDamage4` and not `Mana`. Check that `_median_mods` really offers tier 4 of OpenDamage in the fake
      (the existing test `test_templates_fix_the_same_three_line_shape_on_two_builds` relies on it).
   b. Same file: with `flexible_by_value = True`, a helmet whose only flexible candidates are +0 (no `worth`) ends
      with the free line (`shopping[-1] == {"kind": "free_line", "line": "anything", "delta": 0.0}`).
   c. `tests/test_improvement_loop.py`, copy the monkeypatch pattern of
      `test_contract_failed_loop_moves_restore_full_state_and_continue` (a `_Wishlist(_Loot)` subclass set as
      `pipeline_module.WishlistGear`, `fill_slot` accepting `replan_resistance`): record `self.flexible_by_value`
      (use `getattr(self, "flexible_by_value", False)`) at every `fill_slot` call. On a feasible build (the default
      `_Pob`) the gear move's call records True, and after the loop `loot.flexible_by_value is False`. With
      `_Pob(1000.0, life=...)` below the `FLOORED` Life floor (read `FLOORED` at the top of the file) the gear move's
      call records False.
   d. Same file: a slot whose value re-fill is rejected (the script's roll scores below `min_gain`) is not re-filled
      again in the next pass when nothing changed: the second pass logs "value re-fill skipped" and makes no
      `fill_slot` call for that slot's gear move (the kicks' own `fill_slot` calls do not count: filter on the gear
      move, e.g. by counting calls made before the pass's first `reoptimize`, or by the log line).
   If an EXISTING test fails: do not change it; stop and put its name and the failure in the report. Otherwise commit
   with a message naming this spec.

4. Final message: `=== FINAL REPORT ===`, the commit hash, `git diff --stat`, the pytest summary line, and one line per
   step 1a-3d saying where it is (file:line).
