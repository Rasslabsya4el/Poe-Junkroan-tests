# Spec: an item-granted warcry is a skill the player presses (fix the warcry branch before it merges)

Branch `gpt-2026-09-19-warcry-triggered-finish` (12b235a) is right that a warcry supported by Autoexertion, or a
triggered one, grants no charges (wiki extract `var/cache/wiki/2026-09-19-autoexertion-extract.md`). It is WRONG about
item-granted warcries: `warcry_usage_proof` / `warcry_charge_sources` skip a warcry without a `gem_id` unless "another
socketed manual warcry supplies the player-use proof".

The lead's lane diff (main c7c5384 -> the branch, 58 references): exactly one reference changes,
`z327_juggernaut_boneshatter`: `useEnduranceCharges` True -> off, `overrideEnduranceCharges` 4 -> absent. That change
is a false negative. In the fixture the socket group `slot="Ring 1" source="Item:34:Kaom's Sign, Coral Ring"` holds
Enduring Cry ("Grants Level 10 Enduring Cry Skill"), and Autoexertion sits in ANOTHER item (`slot="Weapon 1"`:
Autoexertion, Battlemage's Cry, Vulnerability, Ancestral Cry). A skill granted by an item is an ordinary skill on the
bar: the player presses it. Supports and Autoexertion act only on skills of their own item / socket group, so the
ring's Enduring Cry is neither autoexerted nor triggered, and its endurance charges stand exactly as on main
("enduring cry: 20 Warcry Power / 5 per charge (PoB) = 4 per use; 8.019 s effective cooldown").

## Task

1. In your worktree merge `gpt-2026-09-19-warcry-triggered-finish`.
2. Rule: a warcry is pressed by the player unless (a) its OWN socket group contains an enabled Autoexertion, or (b) PoB
   marks the skill as triggered (`active_skill_entries[].triggered`, or the item line that grants it says
   "Trigger ..."). Whether the gem is socketed or item-granted plays no role; drop the `gem_id` requirement from the
   proof and from the charge sources (keep the field on `Gem` only if something else uses it).
3. Tests: the z327 fixture keeps `useEnduranceCharges` True with 4 sustained (PoB-backed test, skipped without the
   runtime; the worker's test that asserted the opposite is reversed); a synthetic group "Autoexertion + Enduring Cry"
   gets no charge source; an item-granted warcry whose granting line starts with "Trigger" gets none either.
4. Measurement in the report (one PoB session): the conservative lane of all 58 references (`benchmark.SETS` new18,
   core14, ziz; `benchmark.fixture_path`) on main and on your tree. Expected: ZERO references change. Anything else is
   a finding to report. A before / after comparison is a measurement, never a test that runs another commit's code.
5. Check before you start that `var` in your worktree is a junction (`cmd /c dir /AL`): if it is a real directory the
   PoB runtime is missing and PoB-backed tests silently skip (the warcry branch's "182 skipped" was that).
   Focused tests, then the whole suite once in the foreground (expect about 750 passed, not 600). Do not edit
   `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
