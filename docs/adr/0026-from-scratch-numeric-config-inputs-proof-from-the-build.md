# 2026-09-11 D26. From-scratch numeric config inputs: proof from the build, numbers from the rails

Status: Accepted

A generated build has no author to copy poison stacks, Trinity resonance or
rage from. `config_rules._numeric_rule` fills the numeric inputs PoB shows
for the build only when the build proves the source with PoB's own numbers
(per-element hit averages for Trinity, `MaximumRage` for rage, `ChillChance`
for chill seconds, PoB's `CanWither` flag, the gem list for spells cast) and
takes the value from `rails_default.json` `assumptions` (resonance 50, rage
50% of max, withered 9 from hits / 15 with the Wither skill, 10 s of chill).
The values are what the reference builds assume, written down with
provenance, never invented per build. Effect: Smite resonance 0 -> 50 is
314k -> 487k on the same build. Ascendancy node text now counts as a source
(Inquisitor's Sanctuary makes consecrated ground); a generator must *create*
the condition ("effect of consecrated ground you create" is a modifier, not
a source).

