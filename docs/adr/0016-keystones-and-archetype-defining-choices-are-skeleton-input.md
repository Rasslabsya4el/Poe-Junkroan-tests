# 2026-09-11 D16. Keystones and archetype-defining choices are skeleton input, not tree-optimizer output

Status: Accepted

From-scratch runs on Stormbrand (author's gear/config, empty tree, 96 points)
reached 41% of the author's CombinedDPS with greedy + swap. The author's tree
relies on Eldritch Battery + Mind over Matter for EHP; neither keystone is
worth anything alone, so single-candidate trials never take them and the
optimizer buys EHP with ~20 points of life nodes instead. This is expected:
multi-component synergies are what the skeleton layer proposes (combinatorial,
mod retrieval, LLM hypotheses) and what the search compares. The tree
optimizer's contract is "fill the best tree given the skeleton", which the
30-point recovery tests validate (100-115%). The from-scratch experiment
therefore pre-allocates the author's keystones as skeleton input; iterated
ruin-and-recreate (`TreeOptimizer.reoptimize`) is added to escape greedy
local optima within that contract.

