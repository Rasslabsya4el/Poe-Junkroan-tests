# Spec (URGENT, before the campaign): a "while Channelling" generator is no proof on a build that does not channel; an unclassified generator is no proof on the conservative lane

Reading of `gear-loot` (2026-09-18, `artifacts/benchmark/20260918-1526-gear-loot/stormbrand-s{1,2,3}`): Storm Brand
(not a channelled skill; no channelled gem is the main skill) carries `usePowerCharges=true` on the conservative
lane. The log's reason: `usePowerCharges (gain a power charge each second while channelling a spell (unclassified
source: counted as ...` -- the Caster Mastery "Gain a Power Charge each second while Channelling a Spell". The picks
move even takes that mastery as a generator (`generator Caster Mastery: judged with usePowerCharges on: 746,251`).
The build then stacks "per Power Charge" nodes (Disciple of the Forbidden, Instability) on charges it never has.

Measured in PoB on the three delivered builds (FullDPS, `usePowerCharges` on -> off, nothing else touched):

| build | on | off | off / on | charges |
|---|---|---|---|---|
| stormbrand s1 | 2,252,054 | 1,384,231 | 0.615 | 5/5 |
| stormbrand s2 | 2,315,289 | 1,611,848 | 0.696 | 4/4 |
| stormbrand s3 | 1,651,026 | 1,090,766 | 0.661 | 4/4 |

Against the author's 1,329,611 that is 104 / 121 / 82% instead of the reported 169 / 174 / 124%.

Two gaps in `src/junkroan/optimizer/config_rules.py`, both general:

1. `GENERATOR_ENABLERS` knows banner, warcry, mine, trap, totem, mark -- not **channelling**. A generator line (or
   a buff-proof line) that holds only "while channelling" needs a channelled skill, and the state lasts only while
   the build's MAIN skill is the channelled one: a Storm Brand build with some channelled utility gem does not
   channel through the fight. So the kind "channelling" is satisfied by the main skill's own gem tags (corpus
   `active_gems.json` `tag_keys`, tag `channelling`), not by the union over every gem. The other kinds keep today's
   union semantics.
2. `charge_rule`'s fallback "a source the text does not classify counts as before (found: on)" contradicts the
   lane's principle (the conservative lane needs proof). An unclassified source is no proof on the conservative
   lane: `use<Kind>Charges` stays off unless a classified source sustains it; the reason names the line as
   "unclassified source: not counted"; the optimistic lane may keep counting it. While there, "each second" is a
   period of 1 s (`every N seconds` is matched today, `each second` is not): "Gain a Power Charge each second while
   Channelling a Spell" on a channelled main skill is periodic, 1 per second; "25% chance to gain an Endurance
   Charge each second while Channelling" is chance 0.25, period 1.

Everything that reads these proofs follows from one place -- the conservative config, the picks move's
generator candidates (a generator whose enabler is missing or whose source is unclassified is not judged), the
explanation text -- no second copy of the rule.

Audit (every new kind of error becomes a check): an error when a charge or buff input is ON in the conservative
lane of a finished build and every source line behind it has a missing enabler (now including channelling) or is
unclassified. On the three stormbrand builds above the audit must report it (they were built before the fix).

## Numbers the tests must reproduce

- Unit, `charge_sources("Power", "Gain a Power Charge each second while Channelling a Spell", gem_tags)`: with a
  non-channelled main skill `needs == "channelling"`; with a channelled main skill `needs is None`, trigger
  `periodic`, period 1.0, chance 1.0. The Endurance line above: chance 0.25, period 1.0. (If the signature needs the
  main skill's tags, add a parameter; keep the old call sites working.)
- Unit, `charge_rule` with one unclassified source only: `use` is False, the reason contains "not counted".
- PoB-backed (skips without `var/cache/pob`): copy `artifacts/benchmark/20260918-1526-gear-loot/stormbrand-s2.pob.txt`
  to `tests/fixtures/regressions/stormbrand-gearloot-s2.pob.txt`; `derive_config` on it gives no
  `usePowerCharges` in the conservative lane, and with that lane applied FullDPS is 1,611,848 within 0.5% (report
  the value you get and any other input that moved; if another input moves, say which and why -- do not tune to the
  number). The audit on the original file reports the new error.
- No regression where channelling is real: on `tests/fixtures/tuadh_329/shockwave_cyclone.pob.txt` (Cyclone main) the
  conservative lane's charge inputs are the same before and after your change (print both).
- Report how many of the 32 Tuadh references + 26 ziz references change their conservative config at all under the
  new rules (author builds through `derive_config`, before/after, one table: reference, input, reason). This is the
  "which builds it moves" number; expect few.

Run `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_config_rules*.py tests/test_audit*.py`
plus your tests, then the whole suite once, in the foreground; PoB work with at most one session at a time (the
machine is running a 5-worker benchmark); run scripts as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`.
Commit on your branch with the numbers in the message. Speed matters: the 28 h campaign waits for this merge.
