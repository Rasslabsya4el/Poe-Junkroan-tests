# 2026-09-18 D75. A generator needs its state; an unclassified source is no proof

Status: Accepted; amended by D75 amd 1, D75 amd 2, D75 amd 3

Reading of `gear-loot` (stormbrand, all three seeds): `usePowerCharges` stood on the Caster Mastery "Gain a
Power Charge each second while Channelling a Spell" on a Storm Brand build -- the charge rule's fallback counted
any line it could not classify as a full source, and the picks move took the mastery as a generator. With only
that input off the delivered builds are 0.715 / 0.791 / 0.769 of their reported FullDPS (2,252,054 -> 1,610,742,
2,315,289 -> 1,831,645, 1,651,026 -> 1,269,255): 121 / 138 / 95% of the author, not 169 / 174 / 124.

Three rules, one place (`config_rules`), read by the lane derivation, the generator re-judge, the explanation and
the audit:

1. `GENERATOR_ENABLERS` gains "channelling", and it is the one kind proven by the MAIN skill's own tags: a
   channelled utility gem does not keep "while channelling" up through a fight fought with another skill.
2. A charge source the text does not classify is no proof on the conservative lane (the lane's principle since
   D22; the old fallback "counted as full, as before" contradicted it). The optimistic lane is unchanged.
   "each second" is a 1 s period. The price of the rule is that every real trigger must be classified:
   the first lane diff over the 32 Tuadh references showed three false negatives (a miner's "when your Mine is
   Detonated targeting an Enemy", a trapper's "when your Trap is triggered by an Enemy", "after spending a total
   of 200 mana"), classified by arithmetic in the follow-up (chance x the main skill's throw rate, per-second
   cost / 200), never typed.
3. Audit error "conservative generator proof": a charge or buff input on in a finished build's Baseline whose
   every source fails the same rule.

Banner placement keeps the status quo (the worker's choice, recorded): "when you ... place a Banner" counts as a
full source for a build with a banner gem; whether one placement per Valour cycle sustains a 10 s charge is a
pending fact, not decided here.

**D75 amendment 1 (2026-09-19): the three triggers the rule exposed are classified by arithmetic.** "when your
Mine is Detonated" and "when your Trap is triggered" count chance x the main skill's throw rate (PoB's `Speed`,
one mine or trap per throw; only when the MAIN skill carries the `mine` / `trap` tag, the delivery supports of the
main link included), "after spending a total of N mana" counts `ManaPerSecondCost` / N, and "enemies that die" is
an on-kill source. Conservative lane, old D75 -> amended, over all 58 references: inputs move on exactly four --
exsanguinate_mines `usePowerCharges` on, 2 of 4 (10% x 10.57 mines/s: 2.6 inside the 2.5 s ramp budget),
pyroclast_mine on, 2 of 5 (10% x 9.54), lightning_trap frenzy 3 of 3 and power 3 of 3 (15% x 9.05 traps/s),
winter_orb power 2 -> 3 (61 mana/s / 200). Still open before `ziz-rules`: Enduring Cry (PoB data: 1 endurance
charge per 5 warcry power, a boss is 20 power, cooldown 8 s) and "when you are Hit" (needs a sourced enemy hit
rate).

**D75 amendment 3 (2026-09-19): a warcry grants charges only when the player presses it.** The wiki
(`var/cache/wiki/2026-09-19-autoexertion-extract.md`): a warcry supported by Autoexertion "no longer grant[s] buffs or
charges" but still counts as having Warcried Recently; a triggered warcry likewise is not "used". Rule: a warcry is
pressed unless its OWN socket group holds an enabled Autoexertion, PoB marks the skill triggered, or the item line
that grants it starts with "Trigger". Socketed or item-granted makes no difference: a skill an item grants is a
skill on the bar (the first version of this change demanded a socketed gem and wrongly took the endurance charges
from z327_juggernaut_boneshatter, whose Enduring Cry comes from Kaom's Sign while Autoexertion sits in the weapon;
the lead's lane diff caught it). `conditionUsedWarcryRecently` keeps its rule; measured, it moves 0% CombinedDPS on
the 15 references that carry it. Lane diff over the 58 references, main -> merged (4467bfa): 0 changed -- the rule
guards builds from skeletons, where the picks could pair Autoexertion with Enduring Cry for free charges. Not
decided: the uptime of Warcried Recently (4 s of an 8 s cooldown) and the cast time of pressed warcries, which PoB
does not charge to DPS; `multiplierWarcryUsedRecently` is kept from the author's config and never derived.

