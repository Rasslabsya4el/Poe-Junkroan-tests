# Build request: the checklist

A build request describes a build idea along the surfaces a PoB build has.
The agent walks the user through this checklist; every item can be
**fixed** (one value), **constrained** (a set or a range) or **free** (the
system decides with PoB). Names are resolved against the corpora; an
unknown name is rejected with a message, never guessed. Before anything
runs, the request is echoed back: how each item was understood, how many
builds it expands to, and roughly how long that takes.

The JSON form (`scripts/search.py --request file.json`) mirrors the list, and so
do the flags of `junkroan build` (`python scripts/junkroan.py build --skill ... --mode ...
--ascendancy A,B --unique "Body Armour=Hyrri's Ire" --scaling Int:0.4 --dry-run`;
`junkroan build` / `python -m junkroan.cli build` need `pip install -e .`);
a request file and flags combine, flags win. `--no-variants --seeds 1` is the
cheapest run: no unique variants, no mutation round and one build per finalist
instead of the default three seeds.
`auto` means free. Lists mean "one of these" (enumerated) for choice items
and "all of these" for set items (supports, utilities, keystones).

## 1. The idea

- `why`: one paragraph, kept verbatim in the report. What the build is
  about, in the user's words.
- `level` (default 77) and `stage` (default `day1`): which rails apply.
  Other rails knobs: `floors` overrides (`{"Life": 4000, "ChaosResist": 0}`),
  `unique_tiers` (default T4-T5), `gem_level` (default 18), `ramp_seconds`
  (default 2.5: seconds of attacking until 80% of the PoB DPS is up, D39;
  poison components get 4 s, weighted by their DPS share, D43).

## 2. The damage skill

- `skill`: the main active gem. Required unless `skill_from` is given.
- `skill_from`: a corpus filter to pick the skill by PoB (`{"tags": ["spell",
  "fire"]}`), expensive.
- `mode`: `hit` | `dot` | `ignite` | `poison` | `bleed` | `minion` | `auto`.
  `auto` reads the composition off PoB (`scripts/probe_modes.py`) and takes
  the primary component; list several to compare them.
- `part`: PoB skill part ("10 Blades"), default auto (PoB picks).
- `delivery`: `self` (default) | a trigger/totem/trap/mine support by name
  (`"Spellslinger"`, `"Cast On Critical Strike"`, `"Spell Totem"`). Naming it
  here fixes it in the link.

## 3. More damage links

- `damage_links`: `{"count": 2 | [2, 4] | "auto", "from": {"tags": [...]},
  "mode": "dot" | [...], "full_dps": true}`. Extra groups whose DPS counts in
  FullDPS; the picker adds gems from the filter under the socket budget.
- `sockets`: `default` (6/4/4/4/3/3 by slot) or explicit per slot.

## 4. Class and ascendancy

- `ascendancy`: one id, a list, or `auto` (all, expensive). Class follows.
- `ascendancy_nodes`: names to fix; the rest auto.

## 5. Scaling direction

- `scaling`: `{"stat": "Dex" | "Int" | "Str" | "Life" | "Mana" |
  "EnergyShield" | "PowerCharges" | ..., "seed_points": 0.4}`. Any PoB stat.
  The tree spends the seed share of points climbing the stat first, then
  optimizes DPS; the report shows the DPS with and without those branches.

## 6. Keystones

- `nodes`: passive names the build must allocate (CLI `--nodes "A,B"`): a notable,
  a keystone, or a mastery effect (matched by its stat text). Exact name, case
  insensitive, against PoB's passives/keystones/masteries; a name PoB does not know is
  an error line (`unknown passive node 'X'`), never a guess. Forced: no build without it
  is sent to PoB.
- `keystones`: alias of `nodes` for keystones (its names are added to `nodes`).
  `forbid_keystones`: never.

## 7. Uniques and forced mod lines

- `uniques`: `{slot: name}` fixed. `unique_slots`: `auto` (the unique screen may
  fill up to the rails' count) | `none`.
- `affixes`: `{key: [mod line text]}` (CLI `--affixes "Wand=+1 to Level of all Fire
  Spell Skill Gems"`, repeatable, lines of one key accumulate). `key` is a slot
  (`Helmet`, `Ring 1`, `Weapon 1`...) or an item class (`Wand`, `Shield`, `Body
  Armour`...). A weapon class (`Wand`) fills `Weapon 1` and is added to `weapon_types`;
  `Shield`/`Quiver` fill `Weapon 2`; `Ring` is refused (name `Ring 1` or `Ring 2`);
  `Weapon 1`/`Weapon 2` as a key need exactly one class in `weapon_types`. The line
  must be a mod that can roll on that item class (PoEDB affix catalog in
  `src/junkroan/pob/mod_data`: sections normal, master, essence, delve; numbers are
  ignored in the match); otherwise `unknown mod line ...` / `mod line ... cannot roll on
  <class>`. A slot that also has a unique in `uniques` is an error.
- The dry-run echo lists every forced direction as `fixed ...`.

## 8. Jewels

- `jewels`: `{"Jewel 1": "<raw PoB item text>"}`, timeless jewels with their
  seed included; the socket becomes a required node. Cluster jewels: not
  modelled yet, raw text is accepted as fixed.

## 9. Gear bases and weapon type

- `rare_bases`: `{slot: base}` fixed. `weapon_types`: a list of item classes
  the weapon screen may choose from (`["Wand", "Sceptre"]`), or `auto`.

## 10. Supports and utilities

- `supports`: names kept in the main link; `forbid_supports`: never picked.
- `utilities`: gem names kept as their own groups (auras, curses...);
  `forbid_utilities`; `utility_groups` count (default 4).

## 11. Config assumptions

- Lanes are derived from the build (conservative = proven). `config`:
  explicit numeric inputs the user vouches for (`{"multiplierRage": 20}`),
  reported as the user's assumptions.

## 12. Budget

- `top`: skeletons to fully optimize (default 2); `seeds` (default 3): how many
  times each finalist is built. One seed of loot rolls and loop kicks is worth
  ~17 points of the author (D71), so every finalist is built `seeds` times in
  parallel, the best by Score is the delivered build and the others are kept
  next to it (`<slug>-s<seed>.pob.txt`) with their numbers in the report;
  `workers` (default 5); `max_builds`: hard cap on candidates and full builds;
  the echo refuses to start above it.
- The echo's estimate: screening every candidate (~3 min each) plus the
  finalists' full builds (~40 min each), both in waves of `workers`.

## What the echo shows

```
skill: Lightning Strike (fixed)   mode: auto -> hit (composition: hit 1,240, ignite 60)
ascendancy: Slayer, Deadeye (2 candidates)   scaling: none
uniques: none fixed, screen up to 2 (T4+)   supports: auto   utilities: auto (4 groups)
expands to 2 candidates (ascendancies 2 x modes 1) screened, top 2 x 3 seeds = 6 full builds, ~83 min on 5 workers
```
