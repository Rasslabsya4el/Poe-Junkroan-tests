# 2026-09-14 D47. The build explains itself from the trace, never from prose

Status: Accepted

The search's output was a table and import codes; reading a build meant
opening PoB. `optimizer/explain.py` writes the "why" from what the
pipeline recorded, and only from that: `TreeOptimizer.history` keeps
every kept step with its measured gain, the pipeline keeps PoB's picks
(skill part, supports, utilities) with the value before and after, the
config lanes carry the proof text of every conservative input, and the
search adds the numbers of the variants rebuilt as whole builds (without
each keystone, with each alternative weapon). No sentence is authored
about strength; each carries the number it came from (principle 1).
The search table gets a Pareto column: a build is on the front when no
other clean, feasible build has both more DPS and more EHP.

