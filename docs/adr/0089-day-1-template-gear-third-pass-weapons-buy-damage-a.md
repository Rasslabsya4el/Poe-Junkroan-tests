# 2026-09-20 D89. Day-1 template gear, third pass: weapons buy damage; a template slot is judged against its bare base

Status: Accepted; amended by D92

Amends D79 (spec `docs/specs/2026-09-20-day1-gear-templates-weapons-buy-damage.md`, Opus coder, merged 66db266;
`--gear wishlist` only, the loot gear stays the default until the smoke pair is read). `gear_transplant`, smoke six,
seed 1, template / author: cold_dot 83.8 -> 103.2%, bleed_bow 68.3 -> 124.5, summon_raging_spirits 94.1 -> 119.4,
stormbrand 91.6 -> 148.6, burning_arrow_snipe 40.2 -> 69.6, impale_ballista 30.5 -> 81.6; median 76.0 -> 111.3
against the loot's 109.3. The rules: a weapon is four lines ranked by VALUE (violation-first ranking let a +0
attribute line beat +142k DPS); a +0 line on a weapon is refused by name; removing less than 0.01 of violation is not
a purchase; the attribute budget counts ITEMS and is the authors' median (3 of 32 Tuadh sets,
`scripts/fixture_attribute_affixes.py`); a gem-level mod takes the whole open budget and must win on measurement
(offered once, lost); resistance tiers are the authors' medians again (overcap fell on all six); hybrid mods keep both
lines. **The baseline rule:** a slot the template fills is mandatory, so "does not worsen a floor" and every "value
before" are read with the BARE BASE equipped, never the empty slot -- with no weapon the skill costs nothing, the
sustain floor is trivially met, and every bow "worsened" it by the same 1.433 (impale_ballista's bow stayed bare:
26.8%). The user read the six sets (2026-09-20): tiers are buyable on day 1; the ES-regen craft near a rare / unique
enemy is a good boss line (mapping backlog: it does not sustain while mapping); Eldritch Battery without Mind over
Matter recharges without interruption, so recharge counts as sustain of an ES cost (spec
`2026-09-20-eldritch-battery-recharge-sustains.md`, in work). Known and next: the base screen sorts violation before
value, so a weapon base with a requirement loses to the base that asks for nothing (burning_arrow_snipe: Bone Bow,
level 23, over the author's and the loot's Imperial Bow) -- the user: weapon bases (crit chance, attack speed, base
physical damage, implicit) are among the strongest choices of an attack build and must be searched and RE-CHOSEN as
the build mutates; the weapon-bases spec follows. A branch must never track files under `artifacts/`: this one did
(force-added by an earlier worker) and the queue's snapshot lost its junction; untracked again in the merge.

