# 2026-09-11 D5. No hand-written scaling interpretations

Status: Accepted

v1's `skill_scaling_facts.py`, `rules.py`, passports, catalogs, registries and
atlases are not carried forward. They encode static weights that cannot express
conditional value ("evasion matters only if item X is worn"), go stale per
patch, and were bounded by author knowledge. Replacements: retrieval over PoB
parsed mods (including conditions) and measured PoB deltas.

