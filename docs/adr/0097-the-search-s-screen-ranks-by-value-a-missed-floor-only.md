# 2026-09-22 D97. The search's screen ranks by value; a missed floor only breaks ties

Status: Accepted

Reading `docs/readings/2026-09-22-winner-recall.md` (screening-plan test 1: Fireball, Essence Drain, Raise Zombie; 20
screened, 10 optimized in full each). Pooled Spearman screen -> full 0.53 (0.21, 0.75); the full-depth winner was in
the screen's top 2 on 2 of 3 requests. The miss was the ranking rule: `scripts/search.py` sorted the screen
feasibility first, and Raise Zombie's winner (Templar/Guardian, second-best screen DPS, 0.008 short of a floor like
five other skeletons) was ranked 15th. Every screen-infeasible skeleton that ever reached full depth ended feasible
(violations 0.008-0.276): the screen cannot buy floors, the full optimize does (D58). Rule: the screen sorts by value,
violation breaks ties; the finals keep feasibility first (`scripts/search.py:413`). Re-ranked on the recorded rows the
winner is in the top 2 on 3 of 3. Loop pass 1 predicts the full result far better (0.84-0.92) -- the middle rung of
the plan's item 2 is the next step if recall fails again; the exploration quota for true late bloomers (Essence
Drain's Raider, screen 15 -> full 3) stays open.

