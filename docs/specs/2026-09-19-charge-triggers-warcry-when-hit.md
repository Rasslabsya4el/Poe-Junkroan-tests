# Spec (before `ziz-rules`): Enduring Cry is a classified endurance-charge source; "when you are Hit" is a pending fact, not a guess

D75 (an unclassified charge source is no proof on the conservative lane) moved 10 of the 26 Zizaran references.
Seven of them lose `useEnduranceCharges` on one line, Enduring Cry's own description ("performs a warcry ... the
user and allied players also gain endurance charges", trigger `other`):
z325_gladiator_spectral_shield_throw, z325_slayer_ground_slam, z326_berserker_volcanic_fissure,
z327_gladiator_earthquake, z327_slayer_earthshatter, z328_hierophant_shock_nova_archmage, z329_gladiator_earthquake.
Two lose it on "30% chance to gain an Endurance Charge when you are Hit" (z327 / z329_juggernaut_boneshatter).

## 1. Enduring Cry, by arithmetic from PoB's own data (no typed constants)

- Charges per use: PoB's skill data, `vendor/pob/source/src/Data/Skills/act_str.lua` `skills["EnduringCry"]`
  `constantStats` `endurance_charge_granted_per_X_monster_power_during_endurance_warcry` = 5 -> one charge per
  5 warcry power. Warcry power against a boss: PoB's config sets `WarcryPower` BASE 20 for a boss
  (`Modules/ConfigOptions.lua`, the `enemyIsBoss` branches; the `multiplierWarcryPower` tooltip says "Power is
  assumed to be 20 if your target is a Boss"). So floor(20 / 5) = 4 per use. Read both numbers from the corpus /
  PoB (the game corpus has the gem's stats; the 20 through a PoB readback of the WarcryPower the calc used, or
  from the config's own default) -- if either cannot be read, stop and say so in the report.
- Period: the warcry's cooldown as PoB computes it for the build (the gem's 8 s base, cooldown recovery applied);
  find the stat PoB outputs for a warcry's cooldown and read it; if the build's Enduring Cry group is not the main
  skill PoB needs the group selected to output it -- use the cheapest correct way (a trial or a temporary main
  group switch restored afterwards) and measure its cost.
- Rule: trigger `warcry`; counts only when the Enduring Cry gem is in the build and ENABLED; rate = charges per
  use / cooldown; the usual duration cap and ramp budget (D39) apply -- one use inside the 2.5 s ramp budget is
  4 charges at once, so the ramp count is min(max charges, 4 x uses inside the budget, at least one use).
  The player presses it on cooldown: that is the same assumption the lane already makes for
  `UsedWarcryRecently` (check how that condition is proven today and reuse the same proof, do not add a second
  notion of "uses a warcry").
- Generalise only as far as the data goes: any warcry gem whose skill data carries a
  `*_charge_granted_per_X_monster_power*` constant is handled by the same code; list which gems that is.

## 2. "when you are Hit": off, and said so

The rate is the ENEMY's hit rate, which PoB does not compute and the rails do not hold. Add trigger `when_hit`
that is classified (so the reason reads "needs the enemy's hit rate: pending fact `enemy_hits_per_second`", not
"unclassified") and counts 0 on the conservative lane. If `src/junkroan/mechanics/` has the pending-facts store
(D62 amendment 4, e66c001), register `enemy_hits_per_second` there as pending with no value, the two references
it would move, and the optimistic-lane hook; otherwise only the classified reason.

## Numbers the tests must reproduce

- Unit: Enduring Cry line + gem enabled, cooldown 8.0, `EnduranceChargesMax` 3, duration 10: rate 0.5/s, `use`
  True, no override (3 of 3 inside the ramp budget). Gem present but disabled: `use` False. Charges per use read
  as 4 from power 20 and the constant 5 (assert the two inputs, not the literal 4).
- Unit: "30% chance to gain an Endurance Charge when you are Hit": trigger `when_hit`, rate 0, the reason names
  the pending fact.
- PoB-backed (skips without `var/cache/pob`): the seven references above get `useEnduranceCharges` True again
  through `derive_config(pob, prefer_rules=True)`; the two juggernaut references stay off with the new reason.
- No regression: the conservative lane (inputs) of the 32 Tuadh references and of the other 17 Zizaran references
  is identical before and after (one PoB session; list anything that moves and why).

Focused tests, then the whole suite once, in the foreground; one PoB session at a time; run scripts as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. Do not edit docs/ROADMAP.md or
docs/DECISIONS.md. Commit on your branch (this directory is your worktree; never add another) with the numbers
in the message.
