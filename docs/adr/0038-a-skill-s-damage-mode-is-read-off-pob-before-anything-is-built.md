# 2026-09-12 D38. A skill's damage mode is read off PoB before anything is built

Status: Accepted

Written 2026-09-26 from commit 491981b ("Mode probe (D38 draft)") and `src/junkroan/search/modes.py`; the entry was
never written into the old `docs/DECISIONS.md`.

A build's idea (Essence Drain as a DoT, Lightning Arrow as a poison delivery) is fixed before any rig or screen,
because a bare rig always favours the hit: a hit is cheap to scale, a DoT needs the investment only the full pipeline
makes. So a skill's modes come from PoB: its hit, own DoT, ignite, poison and bleed DPS on a neutral rig (a mode exists
when its number is > 0), and ascendancies are ranked per mode by what their notables add to that mode's stat alone.
The result is a text report (`scripts/probe_modes.py`) that can be read before anything is built; the skeleton carries
the mode, and the objective maximizes that mode's stat (FullDPS for minions, D37).
