# 2026-09-12 D31. Unique availability, resource sustain, and a machine audit of every build

Status: Accepted

Three logical errors the first Fireball search shipped, all caught by eye:
a helmet PoB still lists but the game removed ten leagues ago (Malachai's
Awakening), the same mastery effect selected on two nodes, and a Blood
Magic build spending 255 life per second with 37 regen. Now:

- **Availability** is read from PoB's own `Source:` line per unique and
  classified (`core` = world drop, `boss`, `boss_uber`, `mechanic`,
  `vendor`, `upgrade`, `legacy` = "No longer obtainable"). The rails allow
  `core` with level requirement <= 70; Tuadh's five uniques are all core.
  Legacy uniques are validation errors. Rarity *within* core (Goldrim vs
  Headhunter) comes from the community drop-rate tier list (wiki guide
  "Analysis of unique item tiers", T0 rarest .. T5 most common, fetched
  through the user's own browser because the wiki blocks bots; snapshot in
  `corpus_data/unique_tiers.json` with the page date) plus the wiki's
  `drop_enabled` flag (325 dead uniques, Malachai's Awakening among them,
  become `legacy` even where PoB has no Source line). Rails: tiers 3-5;
  Tuadh's five uniques are T3-T5, T2 is 0.8% of unique drops. Core uniques
  without tier data pass. poe.ninja prices were rejected: league-end prices
  do not reflect a league start. 556 of 1,332 uniques pass the rail.
- **Sustain**: for each resource the main skill spends, regen + leech gain
  rate + recoup must cover 85% of PoB's per-second cost, plus unreserved
  life >= life cost. Calibrated on the references (Spark 90% from regen,
  Ignite Penance Brand 99%, attack builds via leech). Known false
  positive: duration buffs as the main skill (Corrupting Fever) where PoB's
  per-second cost assumes continuous casting.
- **One effect per mastery**: the tree optimizer no longer proposes an
  effect already selected elsewhere (PoB headless accepted duplicates).
- **Audit** (`optimizer/audit.py`, `scripts/audit_build.py`): duplicate
  mastery effects, legacy / out-of-rails uniques, gems above the rails,
  every missed floor and relation with its numbers. Runs at the end of every
  pipeline, is printed in the search report, and any error sinks the build
  in the ranking. The rule for the operator is the same: open the top PoBs
  and look; every new class of mistake becomes an audit check.

