# Spec: a proxy's hits are not the player's -- D80 (the user's base knowledge, confirmed on poewiki 2026-09-19)

The user: "channelling spells on totems gain and give charges to the totems, not to the player: base knowledge of
proxy delivery types". poewiki, read 2026-09-19 (verbatim):

- Totem: "Totems use all of the player's stats that affect their skills ... While totems are not 'you', many stats
  worded as 'you' or 'your' still apply to the skill used by a totem." / "Hits are dealt by the totem; both
  beneficial and detrimental on-hit effects (e.g. leech or reflected damage) will affect the totem, not the
  player." / "They cannot gain rage, frenzy or power charges, offensive buffs, and are ignored by offensive auras."
- Mine: "A mine (or remote mine) is a type of proxy ... Because mines are separate entities, they cannot normally
  grant the player effects on hit or on kill ... They also cannot benefit from effects like leech, except with
  the specific #% of Damage dealt by your Mines is Leeched to you as Life stat."
- Trap: "Players cannot leech health or mana via traps."

So the player's own charges DO raise a proxy's damage (PoB is right: impale_ballista s1 FullDPS 963,133 with
`useFrenzyCharges`, 722,737 without, 0.750) -- but the player must gain them himself. Today `config_rules.charge_rule`
feeds the hit / crit / periodic triggers with the MAIN skill's `HitSpeed` / `Speed` whoever delivers it:

```
impale_ballista (Shrapnel Ballista totems): useFrenzyCharges <- "performs an attack with a ranged weapon that gives
the character a frenzy charge if it hits" x 2.19 hits/s      (the totems' hit rate credited to the player's Frenzy gem)
```

## The rule

1. Delivery of the main skill = proxy when the main skill's tags (the active gem plus the supports of the main
   link, `_main_skill_tags`) carry `totem`, `trap` or `mine` (gem corpus tags; not gem names).
2. With a proxy main skill, every player-subject generator whose rate comes from the main skill's use -- triggers
   `hit`, `crit`, `kill`, the "while channelling" periodic source, and buff proofs whose parsed precondition is
   `HitRecently` / `CritRecently` / `Channelling`-like (D77's `_condition_allows`) -- counts ZERO for the player
   ("the hits are the totem's / trap's / mine's"). The proxy-worded triggers classified in D75 amendment 1 ("when
   your Mine is Detonated", "when your Trap is triggered") and any line PoB parses with a totem / trap / mine
   subject are unaffected. `conditionLeeching` stays on PoB's computed leech (PoB already models proxy leech; report
   what it outputs for exsanguinate_mines and lightning_trap, and if it is positive without a "Damage dealt by
   your Mines is Leeched to you" source, say so in the report -- do not patch it here).
3. A generator that is its own SKILL (the Frenzy gem: "gives the character a frenzy charge if it hits") is the
   player's -- when that gem is not itself delivered by a proxy (no totem / trap / mine support in ITS link) --
   and its rate is THAT SKILL'S OWN rate from PoB, never the main skill's hit rate and never a guess. The user
   (2026-09-19): "a Frenzy gem without the ballista is the only normal way to generate frenzy on ballista builds;
   it may sit on Manaforged Arrows, which triggers when you place a ballista -- that counts as a bow attack ... you
   have all the data, compute it". Measured on impale_ballista (author / our s1), all PoB outputs:
   link `Ensnaring Arrow + Frenzy + Manaforged Arrows`; Frenzy's own `Speed` 0.985 / 1.036 per second with
   `HitChance` 100 (read with `PobSession.active_skill_stats(["Frenzy"], ...)`, merged in 71dc794);
   `TotemPlacementTime` 0.294 / 0.303 s; `ActiveTotemLimit` 6 / 5; `FrenzyChargesDuration` 10.
   - Triggered generator skill (PoB marks the active skill as triggered: Manaforged Arrows, Cast when ..., a
     trigger craft): rate = its own `Speed` x `HitChance` x the line's chance. impale_ballista: ~1.0 charge/s ->
     2 charges inside the 2.5 s budget by the existing ramp arithmetic (2.5 -> 2), the maximum when sustained.
   - Hand-used generator skill on a TOTEM main skill: the player first places the totems, then attacks: time left
     inside the budget = budget - ceil(ActiveTotemLimit / totems per placement) x `TotemPlacementTime` (totems per
     placement from PoB's data for the main link -- e.g. Multiple Totems; if PoB does not expose it, use 1 and say
     so), uses = time left x the generator's own `Speed`; sustained: the share of a `TotemDuration` cycle not spent
     placing. On a TRAP / MINE main skill throwing is continuous: a hand-used generator gets no time (0); a
     triggered one keeps its own rate.
   - Also check that the totem limit itself is reachable inside the budget (limit x placement time / totems per
     placement <= budget); if not, report it -- do not change the instance count here, that is D57's ground.
4. The audit's "conservative generator proof" check follows the same function.

## Numbers to report and tests

- Unit: the Frenzy-gem line with main tags {attack, totem}: triggered, own `Speed` 1.0, `HitChance` 100 -> rate
  1.0/s, 2 charges inside a 2.5 s budget, and the reason names the skill's own rate (never the main skill's 2.19
  hits/s); hand-used with `ActiveTotemLimit` 5, one totem per placement, `TotemPlacementTime` 0.3, own `Speed` 1.0
  -> 1.0 s left -> 1 charge; the same hand-used gem on a {mine} main skill -> 0; the Frenzy gem INSIDE a totem link
  -> 0 (the totem cannot hold the charge). With main tags {attack} and no proxy -> today's behaviour.
  "Gain a Power Charge each second while Channelling a Spell" with main tags
  {spell, channelling, totem} -> 0; with {spell, channelling} -> 1/s. The mine / trap triggers unchanged.
- PoB-backed lane diff over the 58 references (`SETS` new18 + core14 + ziz, authors through
  `derive_config(pob, prefer_rules=True)`, one session): every input that moves, with old / new reason. Expected to
  move: impale_ballista, z325 / z329_champion_explosive_arrow (`useFrenzyCharges` now from the Frenzy skill's own rate: report the charges counted); list anything else.
  Anything that turns ON is a bug.
- impale_ballista author under the lane before / after (FullDPS), and the delivered build
  `artifacts/benchmark/20260919-0130-new18-rules/impale_ballista-s1.pob.txt` re-derived: before 963,133.
Focused tests (`tests/test_charge_rule.py tests/test_config_rules.py tests/test_buff_proof_from_parsed_mods.py
tests/test_audit_and_config_limits.py` plus yours), then the whole suite once, in the foreground; one PoB session at
a time; run scripts as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker:
write the code yourself. Another worker edits `ramp.py` / `ramp_inputs.py` (ailment stacks): stay out of them. Do
not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the lane-diff count in the message.
