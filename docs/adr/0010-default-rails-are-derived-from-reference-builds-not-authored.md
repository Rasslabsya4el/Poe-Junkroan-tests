# 2026-09-11 D10. Default rails are derived from reference builds, not authored

Status: Accepted

Ten day-1 SSF-style builds by Tuadh (3.29 Exarch & Eater runs, levels 75-81)
were loaded into PoB and measured (`tests/fixtures/tuadh_329/stats.json`).
Defaults in `src/junkroan/optimizer/rails_default.json` take the lower
quartile as floors (life, EHP, elemental resist) and the median as the DPS
target. v1's hand-picked rails (level 90, 1 prefix + 1 suffix per rare,
200k DPS) were both stricter and looser than reality: real day-1 rares carry
4-7 explicit mods, and real day-1 builds sit at level 77 with uncapped chaos
resistance. Rails are regenerated when the reference set changes.

