# 2026-09-11 D29. Hypotheses are names; everything below them is measured

Status: Accepted

`search/hypothesis.py` defines what an LLM may propose (class, ascendancy,
main skill, optional supports / keystones / ascendancy notables / uniques /
rare bases, all by in-game name, validated against the corpora) and
`search/generator.py` fills every blank by PoB: rare bases per slot by
best-of-40 rolls per candidate base (weapon type included; skill-made,
experimental and demigod bases excluded), ascendancy notables greedily by
objective gain per point, supports greedily over the supports PoB links
(day-1 gems only; trigger supports are a delivery choice and stay
hypothesis-only after Cast when Stunned won a bare rig), and a unique screen
that tries every unique of a slot's type as an item trial. `scripts/search.py`
runs prepare -> screen -> full optimize in parallel processes and writes a
report with import codes. Supports chosen on a bare rig favour flat added
damage, so the full optimize re-picks them under the real tree and gear.

