# Spec: the wishlist item is bounded by how likely it is to roll, computed from PoB's spawn weights -- D79

The user (2026-09-18): "the wishlist of mods must not be dictated by Tuadh directly; these mods must emerge from
calculation". (2026-09-19): wishlist replaces the loot simulation as THE gear only after the lead says it is ready.

It is not ready. `gear-wishlist` @04bc1d6, cold_dot s2, Weapon 1 (a "day-1" Void Sceptre):

```
T1/1 +1 to Level of all Spell Skill Gems / T1/1 +1 to Level of all Cold Spell Skill Gems /
T1/4 +(29-33)% to Cold Damage over Time Multiplier / T1/7 (85-99)% increased Cold Damage
```

PoB's own spawn weights on a sceptre (`vendor/pob/source/src/Data/ModExplicit.lua`): 50, 250, 70 and 40, where a
common mod weighs 1000. All four on one item is an item nobody rolls in a league. The rails
(`rails_default.json` `gear.wishlist`: `useful_mods` 3 / 4, `tier.rule` "ladder_median", `above_median_max`) bound
the TIER position and the mod COUNT -- both numbers copied from Tuadh's rares -- and know nothing of a mod's
rarity; a one-tier ladder ("+1 to Level of ...", `T1/1`) even counts as "median". The loot simulation never had
this problem: it rolls with the weights.

## The rule: one knob, N

An item is described by its constraints -- a set of (mod group, minimum tier) pairs on a base at an item level;
the other affixes are "anything". Its probability of coming out of ONE random rare roll is computable from PoB's
weights (`PobSession.list_item_mods(base, ilvl=...)` already returns the legal mods with tier ladders and
weights): per affix slot a mod group with tiers >= the minimum has share `sum(weights of accepted tiers) / total
weight of the pool` (prefix and suffix pools apart; a group can appear once; the number of affixes follows the
same distribution `random_rares` uses -- read it from there, do not invent one). Compute P(item satisfies all its
constraints) exactly for up to three constrained prefixes and three constrained suffixes (inclusion of the
"which slots" arrangements; an approximation is fine only if you test it against a Monte-Carlo run of
`random_rares` and it is within 20%).

The wishlist item is then: the best item (by the objective, as today: greedy, PoB trials, feasibility before
value) among those with `P(item) >= 1 / N`, N = `rails.gear.construction_best_of_n` (600 today) -- the same knob
the loot simulation has, so the two models describe the same day-1 player: "the best rare a player who sees N
rares of this base can expect to own". The greedy adds or tightens one constraint at a time, choosing the
candidate with the best objective among those that keep P >= 1/N; when two constraints compete, a looser tier of
a rare mod may beat the top tier of it -- that choice is the point. Rolled values: the expected value of the mod
over the accepted tiers and the roll range (weights respected), not the best tier's midpoint.

## Three more rules from the user's reading of the wishlist items (2026-09-19)

Full items of `gear-wishlist` cold_dot s2: Body Armour = "+28 to Strength" and nothing else; Gloves = a 9% area
craft only; life on ONE of ten items (the shield). The filler stops as soon as "no mod improves the objective",
i.e. once the floors are met -- and the user's verdict is unconditional:

1. **Life on every item (a rail).** On a life build every rare slot whose base can roll maximum life carries a
   life mod: "there is never too much life, least of all on day 1". Energy shield instead on a pure ES build (the
   skeleton holds Chaos Inoculation, or the author's EnergyShield is at least twice the Life -- keep the test in
   one function; no ES reference exists yet, so unit-test it only). The life mod is placed FIRST, before the
   greedy, at the best tier the probability budget leaves room for next to the item's other constraints (so it is
   inside P >= 1/N, never outside), and it is never dropped by a later step. Rails key:
   `gear.wishlist.pool_mod_on_every_slot: true`.
2. **No empty affix while the budget allows a relevant one.** After the mods that raise the objective are
   exhausted, the remaining probability budget is spent on defensive headroom the build can use: candidates ranked
   by `TotalEHP`, then `Life`, then the smallest elemental maximum hit (PoB trials, the same machinery). Reason,
   measured: on the AUTHOR's tree one wishlist fill equals one loot fill (102.9% against 108.8% of the author's
   gear), but in the pipeline loot wins 150.2 to 106.5 -- loot rares arrive with 5-6 affixes, most of them life /
   resistances / attributes, and the tree stage that follows converts that headroom into damage; the wishlist's
   2-4-mod items leave the tree to pay for defences. Report the tree's life / resistance / attribute node count
   after gear pass 2 on stormbrand before and after this change.
3. **The shopping list.** The wishlist is what the player should craft or buy at this stage, so each slot's
   result keeps, per mod, the measured marginal value (objective delta or headroom delta when it was added) and
   the mod's probability share; `explain` prints per slot: base, then the mods in order of importance with those
   two numbers, and the item's P. This is the text the user reads; keep it to one line per mod.

Speed is part of this task, not a later one (the user): today a slot costs 12-17 s and a build's gear 16-29 min
against loot's 3-12. Profile first (where do the seconds go: `craft_rare` round trips, `list_item_mods`,
`list_bench_mods`, trials?), then cache per (base, ilvl), batch the crafts and trials of one greedy step into one
round trip each, and screen bases with one batched trial. Target: a build's wishlist gear time at or below loot's
on stormbrand (9.6 min) -- report before / after per slot.

Removed from the rails: `useful_mods`, `tier.rule`, `above_median_max` (they become outputs to report, not
inputs). Kept: item level, the base choice (D73) and its attribute payment, `attribute_affixes_max`, one bench
craft (deterministic, outside the probability), the weapons-first order, the bow fix (the slot the main skill
needs is never left empty).

## Numbers to report and tests

- Unit (fake mod tables): a two-constraint item's P equals the hand-computed value; adding the +1-gems group
  (weight 50 of 12,000) to an item already at P = 1/500 is refused at N = 600 and accepted at N = 60,000; a looser
  tier is chosen when the top tier does not fit.
- Monte-Carlo check (PoB-backed, skips without `var/cache/pob`): for three constraint sets on a Void Sceptre at
  ilvl 76, the computed P against the frequency over 20,000 `random_rares` rolls, within 20%.
- PoB-backed: the cold_dot author with every rare emptied, Weapon 1 filled by the new rule at N = 600: print the
  item, its P, and the same for N = 60 and N = 6000; the four-mod sceptre above must be impossible at N = 600
  (print its P).
- `scripts/gear_transplant.py --set smoke` (one PoB session; ~1 h): wishlist C/A per reference against the old
  rule's 146.4 / 68.5 / 141.6 / 68.6 / 103.0 / 105.9 (bleed_bow, burning_arrow_snipe, cold_dot, impale_ballista,
  stormbrand, SRS; median 104.4) and against loot's B/A (median 96.6 at N = 600). Report the mods-per-item and
  tier-rank distribution that COMES OUT, next to the authors' 2.44 useful mods and 0.55 rank
  (`docs/research/2026-09-18-author-rares.md`) -- an output check, not a target.
- Time: seconds per slot before / after (today 12-17 s per slot); cache `list_item_mods` per (base, ilvl).
Focused tests, then the whole suite once, in the foreground; one PoB session at a time (a 5-worker benchmark is
running); run scripts as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker:
write the code yourself. Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
