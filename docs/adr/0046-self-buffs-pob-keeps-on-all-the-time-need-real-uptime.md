# 2026-09-13 D46. Self-buffs PoB keeps on all the time need real uptime

Status: Accepted

Phase 6 acceptance on Smite (free ascendancy): the top builds carried
Ambush as a utility link and 100% critical strike chance with a 6.0
multiplier; PoB applies a skill's self-buff whenever the gem is in the
build, and Ambush's buff lasts 1.5 s per 5 s cooldown (and is consumed
by the next one-handed melee attack). The utility picker (D35) had found
the strongest number PoB offers, which was a 30% uptime assumption.

`pob/skill_facts.py` reads cooldown and base buff duration from the
pinned PoB skill data; `buff_uptime` = duration / cooldown when both
exist (None for auras, heralds, Blood Rage: always-on is right). The
utility picker skips gems with uptime below 0.9 (Ambush 0.3, Molten
Shell 0.75; Flame Dash 1.0 stays), the audit warns when such a gem sits
in a build. Also found there: the unique screen offered quivers as
Weapon 2 for sword builds (PoB's what-if accepts the item, the real
equip fails, and the variant runs died); a quiver is offered only when
the main hand is a bow, a shield only when it is not.

