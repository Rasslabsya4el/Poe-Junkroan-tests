# 2026-09-11 D4. LLM proposes, scripts decide

Status: Accepted

The LLM generates skeleton hypotheses and explanations. It never selects
nodes, affixes, or config values. Rationale: LLM PoE knowledge is shallow and
hallucination-prone; putting it in the critical path is what made v1 trees bad.
Making its errors cheap (discarded by PoB fitness) is the fix, not making it
right through prompts or catalogs.

