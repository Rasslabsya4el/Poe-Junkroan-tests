# 2026-09-11 D14. Base game mechanics are not curated as prose

Status: Accepted

v1 had no wiki-derived explanations of mines, traps, brands, charges, crit or
evasion; its `mechanic_coverage_data` was a coverage map of corpus tags, not
mechanics text. v2 does not add such a knowledge base. Where a mechanic changes
the *search* (which supports pair with a skill, what a brand needs to be
attached, how charges are generated), the fact is expressed as a rule in
`search/candidates.py` or `optimizer/config_rules.py` backed by corpus data,
or as a `mechanics/notes.json` record when PoB cannot compute it. Explanatory
prose for the LLM is not needed for the search and is a hallucination surface.

