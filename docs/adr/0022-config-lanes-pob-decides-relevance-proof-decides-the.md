# 2026-09-11 D22. Config lanes: PoB decides relevance, proof decides the conservative lane

Status: Accepted

PoB's config tab already evaluates, per input, whether anything in the build
references the condition (`control.shown()` over `mainEnv.conditionsUsed` and
friends). The worker exposes that verdict with the referencing sources. The
optimistic lane enables every referenced toggle. The conservative (boss) lane
additionally requires proof the build generates the condition: PoB's own
ailment chance / DoT stats, leech rates, or generator text found in the
build's items, allocated nodes and gems (charges, onslaught, fortify...).
Kill-based and player-state conditions stay off in the boss lane. Numeric
inputs are never invented: kept from the build, or taken from PoB's own
estimates (poison stacks). Ailment proof needs a real chance (>= 50%) or a
DoT/effect stat; PoB shows the enemy-ailment checkboxes without predicates,
so the ailment is read from the var name. Reference: Ignite Penance Brand
hits always shock and chill, so conservative = the author's number exactly;
optimistic = 176%. Skill-specific options (`ifSkill`, e.g. Cold Snap "Bypass
CD?") are assumptions, optimistic lane only: it was worth +56% on Cold DoT.

