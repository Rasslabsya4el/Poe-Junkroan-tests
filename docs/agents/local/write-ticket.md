# write-ticket: this repo's example and terms

The skill `write-ticket` carries the generic template; this file adds the repo's own filled example.
Game and PoB terms are written as PoB writes them (CLAUDE.md principle 8).

```
Title: Flasks are active only at 100 % Flask uptime in PoB

## For the human
- **What:** in day-1 builds every flask is switched on, even when PoB gives it 0 % uptime, so DPS is overstated.
- **Why:** the owner's word, 2026-10-06: a flask is active only when PoB prints "Flask uptime: 100%".
- **Plan:** the `active` flag is no longer set by hand: it comes from the same calculation PoB shows in the item tooltip; the author is counted by the same rule.
- **Result:** on stormbrand-s4 all 5 flasks switch off, FullDPS 1,753,896 -> 1,552,665; shown by a test on two PoBs and the replay bench on the six smoke builds.
- **Undo:** two-way door (one revert); touches every build that wears flasks.

## For the agent
<facts with file:line, the rule, acceptance rows, "Not in this ticket">
```
