# 2026-10-06 D115. A Flask slot is active only at PoB's own 100 % flask uptime, ours and the author's

Status: Accepted

калькуляции фласк аптайма»). Supersedes #436's "each slot active" for the day-1 flask step and the benchmark's
`flasks-active` author regime.

Why: the gate of 2026-10-05 delivered 34 of 34 rows with every placed flask active (140 flasks), and of the 56 slots
that print an uptime line exactly one printed "Flask uptime: 100%"; most printed "0% average, 0% minimum" (no charge
generation at all). PoB counted their whole effect at 0 % uptime: stormbrand-s4 FullDPS 1,753,896 as saved,
1,552,665 with the flags derived (#575 row 2).

Decision:

1. A Flask slot's `active` flag is derived, never set: it is true iff PoB's own uptime calculation for that item in
   that build (`ItemsTab.lua`, the tooltip's "Flask uptime" branch) prints "Flask uptime: 100%". A flask without an
   uptime line is never active.
2. It binds at the PoB boundary: the headless worker derives the flags before every stats read, every trial and the
   export, so a move that brings a charge-generation source is credited in the same evaluation, and the delivered
   XML carries exactly the derived flags. No Python code sets a flag by hand (`set_flasks_active` stays for tests).
3. The author is measured under the same rule: `AUTHOR_REGIME = "flasks-uptime-100"`, memo
   `<slug>-flasks-uptime-100.json`.

Consequences: on day 1 almost no utility flask is active (no reachable generation source outside the Ascendant's
Pathfinder node and a few uniques); builds that counted flasks lose that share of FullDPS, the rule's intended
effect. What an inactive slot should hold is not settled here (#529, the owner's reading). Hard to reverse: the
step, the worker and the benchmark's author numbers all follow it.
