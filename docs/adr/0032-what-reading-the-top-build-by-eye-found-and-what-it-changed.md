# 2026-09-12 D32. What reading the top build by eye found, and what it changed

Status: Accepted

Fireball Hierophant after D31 (audit clean): The Scales of Justice + Natural
Hierarchy, mana-stacking flat fire, 1.03M conservative. Reading it found:
`conditionUsedWarcryRecently` on in a build with no warcry (the "sustained
by the main skill" set covered conditions that need a specific gem), no
bandit and no pantheon chosen (skeleton defaults), no utility links at all
(no curse, herald, aura, movement skill). Fixed: sustained conditions that
need a gem kind now require it (warcry, movement, travel, channelling,
elemental "used X skill"); "crit recently" needs >= 5% crit chance; bandit
and pantheons are tried and chosen by PoB (EHP breaks ties). Open: utility
links are a generator gap (Phase 5 next item: a PoB-judged utility screen
over auras, heralds, curses and guard/movement skills under the reservation
and sustain relations).

