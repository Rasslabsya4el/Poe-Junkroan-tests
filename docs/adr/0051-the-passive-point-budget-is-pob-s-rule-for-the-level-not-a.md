# 2026-09-14 D51. The passive point budget is PoB's rule for the level, not a fixture count

Status: Accepted

The rails gave every search build 107 passive points at level 77: the
median node count of the references with their ascendancy nodes included.
Their allocatable median is 100, and PoB's own rule (Modules/Build.lua:
level - 1 + quest points, 23 from level 67, + ExtraPoints for killing every
bandit) gives 99 with a bandit reward and 100 without. So every search
build before today carried 7-8 points it could not have, and opened in
PoB with the character level in manual mode at 77 and a red points
counter; the benchmark was never affected (it budgets the author's own
allocatable count). The level stays manual and a rail (77, gems 18); the
budget is `rails.max_passive_points(level)` with the bandit reward, and
the extra point of "kill all bandits" is allocated by the tree optimizer
when that choice is judged against Oak, Kraityn and Alira, so the four
are compared as whole builds. The Phase 6 acceptance numbers for Storm
Brand, Smite, Poison Spectral Throw, Cold Snap and Bleed Bow were measured
at 107 points and are to be re-measured.

