# Spec: make the tree's reasons visible, catch dead nodes, and write custom mods readably (no optimizer change)

The user read two builds of `core14-rules` and concluded the pipeline is broken: "ugly single dead-end nodes", "+10%
minion life here gives literally nothing", "two masteries I do not understand at all". The lead measured it (throwaway
script, kept as the reference for this task:
`docs/research/scripts/2026-09-19-dead-nodes.py`):
on the 14 best builds of `artifacts/benchmark/20260919-0941-core14-rules`, removing every removable leaf one at a
time through `PobSession.trial_stats([{"remove": [node]}], keys, mode="fast")`:

| | |
|---|---:|
| allocated points, 14 builds | 1,411 |
| dead leaves (nothing PoB computes moves) | 3 (winter_orb s2: Minion Life, Caster Mastery; poison_spectral_throw s1: Mana Leech) |
| weak leaves (judged DPS < 0.2% and life / EHP / max hits / resists / movement < 0.5%, mana not broken) | 25 (1.8%) |

and the "absurd" masteries of physical_dot s3 are PoB-correct: the Ascendant's Trickster node grants "1% more Damage for
each different type of Mastery you have Allocated", so removing ANY of its seven masteries costs 1.43% CombinedDPS
(fast and full mode agree) -- the mastery TYPE is what is bought, the effect inside it is a tie. The reader could
not see any of this. This task makes it visible and catches the real leftovers; it does NOT change how the tree is
optimized (that is a separate decision the user and the lead are discussing).

## Two corrections found after the first draft of this spec (read them first)

- **A leaf that moves nothing in a frozen-config trial may be a PROOF holder.** winter_orb s2's Caster Mastery looked
  dead in the lead's table, but its effect is what the conservative lane stands `usePowerCharges` on: with the
  config re-derived after the removal the build loses 14% (241,402 -> 207,552, the run's own log). So the audit and
  the "why" table must, for every leaf that comes out dead or weak, remove it for real, re-derive the config
  (`derive_config`, the way the pipeline's judge does), read the stats and restore -- a handful of nodes per build.
  Such a node is reported as "holds the proof of <input>", never as dead. Corrected expectation on the 14 files: 2
  dead (Minion Life in winter_orb s2, Mana Leech in poison_spectral_throw s1), not 3.
- **PoB's node tooltip is not the reference for FullDPS.** The user's screenshot of Minion Offence Mastery showed
  -1.4% Combined DPS and -0.3% Full DPS: the tooltip recomputes the main skill only and divides the same loss by the
  whole FullDPS. `trial_stats(mode="full")` gives -1.43% / -1.49%. The table reports `trial_stats` numbers and says,
  once, in its header that PoB's tooltip can show a smaller FullDPS percentage. (In the regular 3.29 tree the
  Ascendant's Trickster node is "2% more Damage for each different type of Mastery"; the lead's "1%" came from the
  ruthless tree file. Your text search must work on the tree version the build uses.)

## Task

1. **Audit check "dead tree node"** (`optimizer/audit.py`, PoB-backed like the other stat checks): every removable
   leaf (`TreeGraph.removable_leaves`, masteries included) whose removal moves none of the objective's stat keys nor
   any floor stat is an ERROR naming the node; a leaf that fails the "weak" test above is a WARNING with what it
   moves. Use the build's own objective stat keys where the audit has them, else the key list of the lead's script.
   One `trial_stats` batch per build (about 5 s). Reproduce the table above on the same 14 files in a test or in the
   report (3 dead, 25 weak; say so if your key set gives other counts and why).
2. **`describe_build` / `explain`: a "why is it there" table for the tree**: every leaf with what removing it costs
   (judged stat %, life, EHP, the floor it holds up if its removal breaks one: attribute requirement, mana
   unreserved, sustain, resistance, movement). Sort by value, weakest first, so a reader sees at once which points
   are thin. When a mastery's removal costs the same as every other mastery of the build, say why in one line: find
   the allocated node or item line that scales with the number or the types of allocated masteries by text search
   over the build's own allocated nodes (tree data incl. ascendancy nodes) and item lines -- do not hard-code
   Trickster.
3. **Mastery effect tie-break**: NOT in this task (optimizer change). Only REPORT, for the 14 files, how many
   allocated masteries have an effect whose own contribution is zero while another effect of the same mastery would
   raise life / EHP / a resistance (one trial batch per mastery: swap the effect, read the stats).
4. **Custom mods are written readably** (the user: "I ask that the comment with the description goes on its own line,
   e.g. `# text`; it will be more readable"). Today the pipeline writes each custom-mod block with its explanation on
   the same line / in the same text. Find every writer of PoB's custom mods text (config_rules custom-mod block,
   ramp / stack caps, ailment caps D78, Pride etc.) and emit, per mod: a comment line `# <why this mod is here>` then
   the mod line(s) on the next line(s). PoB must still parse every mod exactly as before: a PoB-backed test compares
   the stats of a reference build before / after the format change (bit-identical), and the audit's parsers of these
   blocks keep working.
5. Check `cmd /c dir /AL` first: `var`, `vendor`, `artifacts` must be junctions. Focused tests, then the whole suite
   once, foreground (a 5-worker search is running: PoB is slow, not broken). Do not edit `docs/ROADMAP.md` or
   `docs/DECISIONS.md`. Commit early. Other workers are editing `audit.py` (buffs ended by skill use) and
   `config_rules.py`: keep edits local, add new functions rather than reshaping old ones.
