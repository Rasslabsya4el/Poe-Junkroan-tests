# 2026-09-11 D23. Gem rails: day-1 gems are 18/0, never 20/20

Status: Accepted

The reference builds (levels 75-81) run every enabled gem at level 17-18
(max 19) with 0 quality; only the main skill sometimes has quality (0-20,
median ~7) from vendor recipes. The skeleton used to set 20/20 everywhere,
which alone made "Cold DoT 162% of the author" out of a build that is 89%
on equal gems (`author + our skills` = 395k vs 228k). `rails_default.json`
now carries `gems.level = 18`, `gems.quality = 0`, `main_skill_quality = 0`,
the pipeline applies them, and every earlier prototype number is void.

