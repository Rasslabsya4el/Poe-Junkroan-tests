# Spec (URGENT, before the campaign): classify three real charge triggers D75 turned off -- mine detonated, trap triggered, mana spent

D75 (merged, ecc150f): a charge source the text does not classify is no proof on the conservative lane. The lane
diff old rule -> new rule over the 32 Tuadh references found three lines that are real sources and were only
"unclassified" (`charge_sources` trigger `other`), so three references lost inputs they legitimately hold:

| reference | input lost | the line |
|---|---|---|
| exsanguinate_mines | usePowerCharges | 10% chance to gain a Power Charge when your Mine is Detonated targeting an Enemy |
| pyroclast_mine | usePowerCharges | the same line |
| lightning_trap | useFrenzyCharges, usePowerCharges | 15% chance to gain a Frenzy / Power Charge when your Trap is triggered by an Enemy |
| winter_orb (kept by another source) | -- | Gain a Power Charge after Spending a total of 200 Mana |

Classify them by arithmetic from PoB's own numbers, in `config_rules.charge_sources` / `charge_rule`, the same way
`hit`, `crit` and `periodic` are today (rate per second -> sustained over the charge duration, capped at the
maximum, and never more than `ramp_seconds` of gaining, D39). No constants typed from memory.

1. Trigger `mine` -- "when your mine is detonated": rate = chance x count x the main skill's throws per second
   x the rails assumption `mine_detonation_fraction` (already in `NUMERIC_ASSUMPTION_DEFAULTS`, 1.0). Counts only
   when the MAIN skill carries the `mine` tag (`main_tags`; a Blastchain / High-Impact Mine support on the main
   link gives it, the corpus tag logic is already there for `GENERATOR_ENABLERS`): a utility mine does not sustain
   charges. One mine per throw (conservative; PoB's per-throw mine count is not read here -- say so in the reason).
   Throws per second: the stat the rule already reads as `hits` (`HitSpeed` or `Speed`) -- verify on
   exsanguinate_mines with a PoB readback that it is the mine throwing rate and report the value.
2. Trigger `trap` -- "when your trap is triggered": the same with the `trap` tag and the trap throwing rate; every
   thrown trap is triggered (the boss stands on it -- the same assumption PoB's trap DPS makes).
3. Trigger `mana_spent` -- "after spending a total of N mana": rate = count x `ManaPerSecondCost` / N, N parsed
   from the line, `ManaPerSecondCost` from PoB's stats (add it to the stat keys the rule is given if it is not
   there). 0 when the build pays no mana.
4. `ON_KILL_TRIGGER` also matches "enemies that die" / "dies" (Cold Snap's "enemies that die while in the area have
   a chance to grant frenzy charges" is an on-kill source and should read "no kills on a boss", not
   "unclassified"). Check the pattern does not swallow a non-kill line in the corpora: grep the three corpus text
   sources for `\bdies?\b` and list in the report every distinct line it newly matches.

The missing-enabler semantics stay: a `mine` / `trap` line on a build with no mine / trap gem at all keeps
`needs`. New here is only that the RATE needs the main skill to be the mine / trap.

## Numbers the tests must reproduce

Unit (fake stats, `ramp_seconds` 2.5):
- mine: chance 0.10, `Speed` 4.0, `PowerChargesDuration` 30, `PowerChargesMax` 3, main tags {mine, spell}: rate 0.40/s,
  sustained 3 (capped), within the ramp 1.0 -> `use` True, override 1. The same line with main tags {spell} only and
  gem tags containing mine: rate 0, `use` False, the reason says the main skill is not a mine.
- trap: chance 0.15, `Speed` 2.0, duration 10, max 3, main tags {trap}: rate 0.30/s, 0.75 within the ramp -> report
  what the existing rounding rule gives (look at how `hit` handles a fraction below 1; do the same, do not invent).
- mana_spent: N 200, `ManaPerSecondCost` 100, duration 10, max 3: rate 0.5/s, 1.25 within the ramp -> override 1.
  `ManaPerSecondCost` 0 -> `use` False.
- "enemies that die while in the area have a chance to grant frenzy charges" -> trigger `kill`.

PoB-backed (skips without `var/cache/pob`), author builds through `derive_config(pob, prefer_rules=True)`:
print and report, for exsanguinate_mines, pyroclast_mine, lightning_trap and winter_orb, the conservative lane's
charge inputs and reasons before (main at ecc150f) and after, with the rates. Assert only what follows from the
rule (the mine / trap / mana lines appear as counted sources with a positive rate), not a DPS number.
Then the no-regression check: the conservative lane of the other 28 Tuadh references is byte-identical before and
after (one session, inputs + reasons compared; list any reference that moves and why).

Run `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_charge_rule.py tests/test_config_rules.py
tests/test_config_enabler_rules.py tests/test_audit_and_config_limits.py` plus your tests, then the whole suite
once, in the foreground; one PoB session at a time; scripts run as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. Do not edit docs/ROADMAP.md or
docs/DECISIONS.md (the lead records it). Commit on your branch with the numbers in the message. Speed matters: the
28 h campaign starts around 00:20 and must carry this.
