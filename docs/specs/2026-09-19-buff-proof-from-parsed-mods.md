# Spec: a buff / condition is proven by a line PoB parses as its SOURCE, never by a line that merely contains the word

Reading of the campaign's first builds (2026-09-19, bleed_perforate s1: `conditionLeeching (source found in build:
enemies cannot leech life from you)`) and a tally over the conservative lanes of the 58 author references:
`config_rules._generator_proof` accepts ANY line of the build's text that matches a word pattern
(`GENERATORS`: `leech`, `fortif`, `onslaught`, `arcane surge`, `phasing`, ...). It filters a missing enabler and
on-kill lines, but not the consumer of the condition, a cap, a modifier of the buff's effect, a negation, or
another actor's buff. Measured false proofs ("source found in build: <line>", input ON in the conservative lane):

| input | the line that "proved" it | references | what the line really is |
|---|---|---:|---|
| buffFortification | +3 to maximum fortification | 6 | a cap |
| buffFortification | nearby allies count as having fortification equal to yours | 4 | not a source |
| buffArcaneSurge | 20% increased effect of arcane surge on you | 3 | modifies the buff |
| buffArcaneSurge | arcane surge also grants 20% more spell damage to you | 1 | modifies the buff |
| conditionLeeching | 43% / 41% / 34% increased damage while leeching | 3 | the CONSUMER proves itself |
| conditionLeeching | enemies cannot leech life / mana from you | 2 | a negation about enemies |
| conditionLeeching | 0.4% of spell damage leeched as energy shield during effect | 1 | a flask line on an attack build |
| buffAdrenaline | gain adrenaline for 20 seconds when you reach low life | 2 | its own condition (low life) is unproven |
| buffUnholyMight | minions have unholy might | 1 | the minions' buff, not the player's |
| buffElusive | 40% increased elusive effect | 1 | modifies the buff |

The optimizer hunts such holes (D75: it took a mastery as a "generator"), so they inflate OUR builds first.

## What PoB's own parser says (`PobSession.parse_mods`, measured)

```
43% increased Damage while Leeching            -> Damage INC, tag Condition:Leeching          (consumer)
Gain Arcane Surge on Hit with Spells           -> Condition:ArcaneSurge FLAG, tag Condition:HitSpellRecently (source + its precondition)
You have Onslaught while on Low Life           -> Condition:Onslaught FLAG, tag Condition:LowLife
You have Phasing                               -> Condition:Phasing FLAG                       (unconditional source)
+3 to maximum Fortification                    -> MaximumFortification BASE                    (neither)
20% increased Effect of Arcane Surge on you    -> ArcaneSurgeEffect INC                        (neither)
Minions have Unholy Might                      -> MinionModifier LIST                          (another actor)
Enemies Cannot Leech Life From you             -> no mod at all
Melee Hits Fortify                             -> no mod at all (PoB leaves it to the config)
```

## The rule (D76, the lead)

1. A line is a text proof of buff / condition X only when PoB parses it into a mod that SETS X for the player:
   a FLAG mod named `Condition:<X>` (map each entry of `BUFF_VARS` / `GENERATORS` to the condition name PoB uses --
   read it from `config_options()` / PoB's ConfigOptions for that input, do not type a table from memory; where an
   input has no `Condition:` flag in PoB, say so in the report and keep it off the text path), outside
   `MinionModifier` / `EnemyModifier` wrappers.
2. Every `Condition` tag on that source mod is a precondition and must itself be allowed on the conservative lane
   by the rules that already exist (`_conservative_allows`: `HitSpellRecently` is sustained by a spell main skill,
   `LowLife` needs the low-life proof, `KilledRecently` is never true on a boss...). A `Multiplier` / `PerStat` /
   `SkillName` tag that PoB resolves itself is fine. The reason string names the source line and the
   preconditions it rode on.
3. A line PoB does not parse proves nothing by text. The only other ways to prove a buff stay the ones that
   exist: a gem in the build through `ENABLER_GEM_INPUTS`-style rules (check which buffs are granted by a gem --
   Fortify Support, Arcane Surge Support, Withering Step, a Vaal skill... -- and that such a gem counts only when
   it is enabled and, for a support, sits in the MAIN link or in a link the lane already treats as used; report
   the list you find and how each is handled today), `mechanics/unsupported_lines.json`, and PoB's own computed
   stats.
4. `conditionLeeching` is proven by PoB's computed leech only (`LifeLeechGainRate`, `ManaLeechGainRate`,
   `EnergyShieldLeechGainRate` > 0 -- the fallback that exists today becomes the rule); PoB already knows which
   damage types the build deals, so "0.4% of physical attack damage leeched as life" on an elemental-only build
   correctly proves nothing.
5. The `parse_mods` round trip is batched (one call for all candidate lines of a build) and memoised per line
   text for the process; measure the added cost of `derive_config` on stormbrand (before / after, ms) and keep it
   under +15%.
6. The audit check `conservative generator proof` (D75) uses the same function, so a finished build whose buff
   stands on a non-source line gets an audit error.

Do not tune for any one build; if a real source turns out to be unparsed by PoB and common, list it in the report
for the lead -- do not add it to the mechanics file yourself.

## Numbers the tests must reproduce

- Unit (fake `parse_mods` returning the structures above): each row of the measured table is NOT a proof;
  "Gain Arcane Surge on Hit with Spells" proves `buffArcaneSurge` for a spell main skill and not for an attack
  main skill; "You have Onslaught while on Low Life" is not a proof without the low-life proof; "You have
  Phasing" is a proof.
- PoB-backed (skips without `var/cache/pob`): `parse_mods` on the nine lines above gives the mod names / tag
  vars written in this spec (this pins the parser contract at the PoB bump).
- The lane diff over all 58 references (`SETS` new18 + core14 + ziz, authors through
  `derive_config(pob, prefer_rules=True)`, one session): a table reference | input | old value -> new value |
  old reason | new reason, for every input that moves, and the count. Expect the ten rows of the measured table
  to turn off unless another rule proves them (then say which). Anything that turns ON is a bug.
- `tests/fixtures/regressions/stormbrand-gearloot-s2.pob.txt`: report its conservative lane before / after.

Focused tests (`tests/test_config_rules.py tests/test_config_enabler_rules.py tests/test_charge_rule.py
tests/test_audit_and_config_limits.py` plus yours), then the whole suite once, in the foreground; one PoB session
at a time (a 5-worker campaign is running); scripts run as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. Do not edit docs/ROADMAP.md or
docs/DECISIONS.md. Commit on your branch (this directory is your worktree; never add another) with the lane-diff
count in the message. Another worker is editing `charge_sources` / `charge_rule` in the same file (Enduring Cry):
stay out of those two functions.
