# Spec (D77 amendment 1): a buff that ends when the character uses a skill is not held while fighting

## The hole

The conservative lane grants `buffElusive` with the reason "Withering Step in an enabled link grants this buff; shown
by PoB" on six references. The wiki (extract with quotes:
`var/cache/wiki/2026-09-19-buffs-ended-by-skill-use-extract.md`): "Using any skill ends Withering Step's effects and
removes all buffs, except the debuff on enemies." A character that is dealing damage does not have that Elusive.

What it buys today (author's build under our conservative lane, `buffElusive` on -> off, PoB 2.67.2; copy
`config_inputs()`-style lane inputs and drop the one key, `set_config` replaces the whole input set):

| reference | EffectiveMovementSpeedMod | TotalEHP | CombinedDPS |
|---|---|---|---|
| poison_spark | 1.440 -> 1.240 | 12,395 -> 11,156 (-10.0%) | 371,416 = |
| soulrend_chaos_dot | 1.380 -> 1.180 | 21,740 -> 19,566 (-10.0%) | 189,287 = |
| poison_spectral_throw | 1.400 -> 1.200 | 24,226 -> 21,804 (-10.0%) | 163,659 = |
| regular_viper_strike | 1.520 -> 1.320 | 14,405 -> 12,965 (-10.0%) | 635,963 = |
| toxic_rain | 1.560 -> 1.360 | 14,824 -> 13,341 (-10.0%) | 355,844 = |
| z327_assassin_poison_spark | 1.728 -> 1.428 | 11,077 -> 9,748 (-12.0%) | 213,502 = |

+0.20 movement speed is the WHOLE movement floor (`EffectiveMovementSpeedMod >= 1.2`, delivered by boots, D55): a
socketed Withering Step pays the floor for free and adds 10% EHP under the EHP floor. DPS never showed it.

## Rule (general, not a patch for one gem)

A buff whose source skill's own rules say it ends (or is replaced) when the character uses a skill is not counted
in the conservative lane -- neither for damage nor for the floors. The Withered debuff Withering Step leaves on
enemies is a separate thing and keeps its present ramp rule.

The fact PoB cannot compute goes into `src/junkroan/mechanics/` (small, machine-readable, with the wiki URL and the
quote): a list "buff ends on skill use" keyed by PoB granted-effect id. Two entries today, both from the extract:
Withering Step (Elusive, Phasing) and Phase Run (its primary buff: movement speed, Phasing; "Using any skill while
Phase Run is active will replace the primary buff"; triggered skills do not count as using a skill -- irrelevant for
us, the main skill is used). Resolve the effect ids from the gem corpus, never type them from memory.

## Task

1. `config_rules.py`: where D77 proves a buff from "an enabled link grants this buff", a source listed in the new
   mechanics fact proves nothing; the reason string says so ("Withering Step's buffs end when any skill is used
   (wiki)"). If another, legitimate source proves the same buff (Nightblade / Mistwalker-style "gain Elusive on
   Critical Strike" with D77's preconditions), the buff stays. Same for Phasing inputs if the lane grants any from
   these two skills.
2. Phase Run: first MEASURE what PoB does -- socket Phase Run (enabled) into a reference that lacks it and read
   `EffectiveMovementSpeedMod`. If PoB counts its movement speed with no config input to switch, the judged state
   must not carry it: report the options you see in PoB (a skill part, a per-gem flag, a config input) and implement
   the one that needs no name list beyond the mechanics fact; if none exists, add an AUDIT check ("buff ended by
   skill use counted: <gem>") and say so in the report -- do not invent a PoB patch.
3. Audit: a finished build whose conservative config still holds a buff proven only by such a skill is an error
   (`audit.py`, next to "conservative generator proof").
4. Tests: the mechanics fact loads; a lane with Withering Step alone does not get `buffElusive`; with a crit-based
   Elusive source that D77 accepts it does; the audit check fires on a build that carries the input anyway. Fast tests
   without PoB where possible; PoB-backed ones skip without the runtime.
5. Measurement in the report (one PoB session, no benchmark): the table above reproduced from your tree (the "off"
   column must now be what the lane yields by itself), plus the conservative lane of all 58 references
   (`benchmark.SETS` new18, core14, ziz26; fixtures through `benchmark.fixture_path`) before / after: every changed
   reference and why. Expected: exactly the six references lose `buffElusive`; anything else is a finding to report,
   not to tune away. A before / after comparison is a measurement, never a test that runs another commit's code.
6. Another worker (`gpt-2026-09-19-warcry-triggered-finish`) is editing `config_rules.py` and `audit.py` right now
   (warcry charge sources): keep your edits local to the buff-proof path so the merge is mechanical.

Focused tests, then the whole suite once, foreground; scripts run as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. Do not edit `docs/ROADMAP.md` or
`docs/DECISIONS.md`. Commit early.
