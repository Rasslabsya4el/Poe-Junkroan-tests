# Spec: land the "a triggered warcry grants no charges" commits, minus one check the wiki refutes

Branch `gpt-2026-09-19-charge-triggers-warcry-when-hit` carries three commits made AFTER its merge into main
(71dc794): 00edf00, 82c631b, ea14cb7 (`config_rules.py` +59, `ramp_inputs.py` +3, `audit.py` +5,
`tests/test_charge_triggers_warcry_when_hit.py` +45). They add `Gem.gem_id / triggered / autoexerted`,
`warcry_usage_proof` and make `warcry_charge_sources` skip a warcry that is triggered or supported by Autoexertion.

The wiki (extract: `var/cache/wiki/2026-09-19-autoexertion-extract.md`) confirms the charge part and refutes one line:

- "Supported warcries no longer grant buffs or charges" (3.25.0: "Supported Warcries do not grant Buffs or Charges to
  you or Allies") -> an autoexerted Enduring Cry is NOT an endurance-charge source. Keep.
- "Triggering a warcry does not count as 'using' a warcry for `when you use a Warcry`, but it does count as warcrying
  for `when you Warcry` effects ... and also as having `Warcried Recently`" -> the new check in `_conservative_allows`
  (`key == "UsedWarcryRecently" and warcry_usage_proven is False -> False`) is WRONG for an autoexerted warcry: it
  still makes "Warcried Recently" true. Remove that check and the `warcry_usage_proven` parameter that only feeds it;
  `conditionUsedWarcryRecently` keeps its present rule (a warcry gem in the build + what PoB shows).

## Task

1. In your worktree (branched from current main) cherry-pick or merge the three commits; main has moved a lot in
   `config_rules.py` (D77 buff proofs, D80 proxy delivery, D78 ailment caps) and `audit.py` (D78 x D80): resolve
   keeping main's logic and adding the warcry part.
2. Remove the `UsedWarcryRecently` check as above; adjust the tests that pinned it (assert the opposite: a build whose
   only warcry is autoexerted keeps `conditionUsedWarcryRecently` when the present rule grants it, and gets NO warcry
   charge source).
3. Measurement, one PoB session, no benchmark: the conservative lane of all 58 references
   (`benchmark.SETS`: new18, core14, ziz26 -- resolve fixtures with `benchmark.fixture_path`) on parent main and on
   your tree; the lead's baseline dump of main's lane is
   `C:\Users\user\AppData\Local\Temp\claude\C--Coding-poe-junkroan-v2\00155a5a-ad2c-4453-9bbf-c551fbe3dac1\scratchpad\lane_d80.json`
   (`{slug: {"inputs", "reasons"}}`, made before D78: ailment-cap keys may differ, ignore those). Report every
   reference whose lane changes and why. Expected: only references with an autoexerted or triggered warcry that used to
   prove an endurance / other charge lose that charge; `conditionUsedWarcryRecently` changes nowhere (15 references
   carry it today). A before / after comparison is a measurement in the report, never a test that runs another
   commit's code.
4. Focused tests, then the whole suite once, foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`.
   Commit early.
