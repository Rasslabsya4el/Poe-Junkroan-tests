# Spec: two floors the user's reading asked for -- every socketed skill must be castable; resistances cap at the build's own maximum

The user read `artifacts/benchmark/20260919-0941-core14-rules/physical_dot-s*.pob.txt` (2026-09-19):

1. "Unreserved mana 8. How is the player supposed to use Flame Dash or Shield Charge, or any other non-life-cost
   skill in the build? The system does not account for it, it must be fixed." (s3: `ManaUnreserved` 18, the helmet
   holds Flame Dash, the shield Shield Charge; the main skill costs life.)
2. "Max cold res is 76 and the build has 75. The rails must cap not 75 but the raised maximum resistance."

## Floor A: every enabled active skill the player presses must be affordable

- For every enabled socket group's active skills that the player USES (not triggered, not supported by a trigger
  support, not a reservation skill, not a skill whose cost is life when the pool in question is mana; read these
  facts from PoB: `active_skill_entries[].triggered`, skill types / reservation flags, the per-skill cost stats of
  `PobSession.active_skill_stats` -- `ManaCost`, `LifeCost`, whatever PoB exposes -- never from gem names):
  `ManaUnreserved >= that skill's ManaCost`, and the same for a life cost against `LifeUnreserved` (a life cost must
  leave the character alive: cost < unreserved life). One floor relation per resource on the LARGEST such cost; the
  violation is scaled like the other relations (see how `Str >= ReqStr` and the self-cost floor are scaled in
  `objective.py` / `objective_select.py`).
- It is a floor of the Objective, so the tree, gear, picks and the reservation-drop move (D72) all see it; the picks
  must not add a utility the build cannot cast.
- Audit: "skill cannot be cast: <gem> costs N mana, M unreserved" (error).
- Sustain of the MAIN skill stays what it is (D63.2); this floor is about being able to press a button at all.

## Floor B: the elemental resistance floor is the build's maximum resistance

- Today the floor is the constant `elemental_resist_floor` 75 (`Rails.objective`). Replace it by a relation against
  PoB's own maximum (the output stats PoB computes for the three maxima; find their names in PoB's output, do not
  assume): `FireResist >= FireResistMax` etc. A build that raises its maximum (the Armour Mastery "+1% to all maximum
  Elemental Resistances", purity auras, uniques) must fill it. Chaos keeps its own rail.
- The benchmark's author floors (`author_floors`) cap the author's side the same way: compare like with like.
- The day-1 template gear's resistance plan (`wishlist_gear.solve_resistances(floor=75.0)`) takes the same maximum
  (another worker is changing that file on branch `gpt-2026-09-19-day1-gear-templates-amendment`: make this a small,
  local edit -- a parameter -- so the merge is mechanical).

## Numbers to report (one PoB session; a 5-worker search is running, PoB is slow, not broken)

- Over the finished runs `artifacts/benchmark/20260919-0130-new18-rules` and `20260919-0941-core14-rules` (96 builds,
  read the `.pob.txt` files, do not rebuild): how many builds break floor A (list: build, skill, cost, unreserved) and
  how many sit below their own maximum resistance (list: build, element, value, maximum). Same two counts for the 32
  AUTHORS under our lane (an author who breaks A is a finding to report, not to fix).
- `scripts/benchmark.py physical_dot --seeds 1 --no-variants --workers 1 --loop --loop-seconds 300` on the parent
  and on your tree: the number, `ManaUnreserved`, the costs of Flame Dash / Shield Charge, the resistances and their
  maxima. A before / after comparison is a measurement, never a test that runs another commit's code.

Tests: fast ones for both relations (a fake stats mapping), the audit check, the author-floor symmetry; PoB-backed
ones skip without the runtime. Check `cmd /c dir /AL` first: `var`, `vendor`, `artifacts` must be junctions. Focused
tests, then the whole suite once, foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
