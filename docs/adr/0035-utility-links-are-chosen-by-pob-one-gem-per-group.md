# 2026-09-12 D35. Utility links are chosen by PoB, one gem per group

Status: Accepted

Generated builds had a single link. `SkeletonGenerator.pick_utilities` now
adds up to 4 utility socket groups (rails `utilities.max_groups`): auras,
heralds, curses and marks, guards, golems, banners, warcries, plus one
movement skill (rails `movement_skill_required`, every reference build has
one; PoB is indifferent, so the instant blink family wins ties). Candidates
come from the gem corpus tags (base gems only, transfigured variants
skipped), each is a real group in PoB, and the objective decides under mana
reservation, sustain and the floors; the lanes are re-derived on every
acceptance and a pick that only won under the old lanes is rejected.
Fireball Hierophant: 1.04M -> 1.51M with Flame Dash, Flammability,
Zealotry and Arcane Cloak (69 s). Runs in the full pipeline after the
support re-pick; hypothesis-given groups are kept.

