# Spec 2026-09-22: two counting holes -- the audit's dead-node verdict, and a skeleton unique that is never equipped

Lead: Opus 5.5. Worker: one coder in its own worktree (this spec is given to TWO coders independently to compare
models: do your own work, do not look for another branch). Investigation first, then the smallest fix; each part
has a STOP rule.

## Why

Reading `docs/readings/2026-09-22-templates-vs-loot.md`: builds are lost to counting holes on both gears (loot and
template). (The template boots / movement part moved to `docs/specs/2026-09-22-template-shape.md`.) Build files are
PoB import codes `<reference>-s<seed>.pob.txt` in the run folders under `C:\Coding\poe-junkroan-archive\benchmark\`
(`results.json` and `report.md` beside them; `scripts/describe_build.py` reads one like a person).

### Part 1: the audit's "dead tree node" verdict

| run | reference | seeds rejected | nodes the audit calls dead |
|---|---|---|---|
| 20260921-2020-core14-tpl | spark | s1-s3 | 8198 Chance to Ignite, Freeze and Shock |
| 20260920-1618-new18-r3 | poison_spark | s1-s3 | 11984 Chance to Poison with Spells |
| 20260921-0929-new18-tpl, 20260920-1618-new18-r3 | kinetic_bolt_wander | tpl s1-s3, loot s1 | 10904 + 34880 Minion Life |
| 20260922-0524-ziz-rules | z325_gladiator_spectral_shield_throw | s1 | 32690 Area of Effect per Endurance Charge, 57011 Stun Duration per Endurance Charge |
| 20260922-0524-ziz-rules | z326_trickster_blight_of_contagion | s1 | 32690, 16213 Attack Speed per Frenzy Charge, 57011 |

Code: `src/junkroan/optimizer/audit.py` (~680, `audit_findings`), D87 in `docs/DECISIONS.md` (tree moves see the
proofs the conservative lane stands on: a node can be the necessary proof of a conservative-lane config input, e.g.
"enemy is shocked / poisoned" or a charge count). D87's open item says the audit judges nodes with the config FROZEN.

1.1 For every flagged node above, on the build file, measure with PoB: (a) removal with the config frozen (what the
    audit does now), (b) removal followed by re-deriving the config lanes the way the pipeline does
    (`optimizer/config_rules.derive_config`), (c) whether the node is a travel node (its removal disconnects other
    allocated nodes). Report one row per node: build, node, (a) objective / floors change, (b) change, (c) yes / no,
    verdict: truly dead / proof holder / travel.
1.2 Fix, only for the kinds 1.1 proves wrong: the audit's dead-node check judges a removal the way D87's tree moves
    do (a proof holder is not dead; a travel node is judged with what it connects). Reuse the D87 machinery; do not
    write a second one.
1.3 STOP rule: a node that is truly dead after (b) and (c) stays an error -- then the optimizer kept a useless node:
    report which loop move kept it if the build's results / logs show it, and fix nothing in the optimizer.

### Part 2: a skeleton unique that is never equipped (found by the lead 2026-09-22, item examples)

burning_arrow_snipe, all six builds of `20260920-1618-new18-r3` and `20260921-0929-new18-tpl`: the build log says
`uniques: Belt: Prismweave, Weapon 2: The Poised Prism`, the exported XML holds the item `The Poised Prism` (Primal
Arrow Quiver) in its item list, and the active item set's `<Slot name="Weapon 2" itemId="0"/>` is EMPTY: the build is
judged without its quiver (the author wears it). A pure-XML scan by the lead of the five runs `new18-r3`, `core14-r3`,
`new18-tpl`, `core14-tpl`, `ziz-rules` (skeleton uniques from each build log's `uniques:` line against the active item
set; mind `&apos;` in item names): 111 skeleton unique placements, 105 equipped, 6 empty -- exactly these six.

2.1 Find why (a quiver needs a bow in Weapon 1: the order in which the skeleton equips, a gear or weapon-base move
    that re-equips Weapon 1, or anything else you can show).
2.2 Fix: every skeleton unique is equipped in the final build; the smallest change at the cause.
2.3 Audit: a new pure check (no PoB) -- a skeleton unique missing from its slot in the build's active item set is an
    `error` finding `skeleton unique not equipped: <slot>: <name>`. It must flag exactly the six builds above on those
    five runs and nothing else (report the count).

## Numbers to report (in the final report)

- A. Part 2: the cause in one paragraph with file:line; construction-only burning_arrow_snipe seed 1 (loot) before
  / after: Weapon 2 item, construction value; the new audit check's counts on the five runs.

- B. Part 1 table (1.1), and -- if fixed -- the audit on all 12 flagged builds before / after (count of dead-node
  findings) and on 12 control builds with no dead-node finding today (any 12 counted builds of the same runs):
  their findings must be identical before / after.
- C. Fast test files you touched: pytest summary; the whole suite once at the end: summary line.
- D. Your own cost: wall time of your work, tool calls / turns if you can see them.

## Rules

- Your worktree reaches `var/`, `vendor/` and `artifacts/` through junctions: read them, write only under
  `artifacts/`, never delete anything there, never remove the worktree.
- PoB budget: check `python scripts/machine_load.py --need 1 --role other` before PoB work; at most 2 PoB processes of
  yours at once, never next to your own pytest; one whole-suite run. Waits bounded (steps of at most 10 min); stop
  every background shell you start before your final report.
- Commit on your branch with the numbers in the message. Do not merge into main.
- Durations for a human: seconds under ~90 s, then minutes, then hours + minutes.
- Principles (CLAUDE.md): PoB is the only judge; no game numbers from memory; no gates, ledgers or waivers.
