# 2026-09-19 D80. A proxy's hits are not the player's; a generator skill counts at its own rate

Status: Accepted

The user's base knowledge, confirmed on poewiki (Totem / Mine / Trap, quoted in
`var/cache/wiki/2026-09-19-proxies-extract.md`): a totem, trap or mine uses the skill with the PLAYER's offensive
stats -- so the player's charges do raise a proxy's damage, PoB is right (impale_ballista s1: FullDPS 963,133 with
`useFrenzyCharges`, 722,737 without) -- but the hits are the proxy's: on-hit / on-crit / on-kill gains, leech and
"while channelling" states are not the player's, and a totem cannot hold frenzy or power charges at all.

Rules (`config_rules`, shared with the audit): with a main skill that carries `totem`, `trap` or `mine` (the active
gem plus the supports of the main link), every player-subject generator or condition fed by the main skill's use
(`hit`, `crit`, `kill`, "while channelling", `HitRecently`, `CritRecently`) counts zero; the proxy-worded triggers of
D75 amendment 1 are unaffected. A generator that is its own skill (the Frenzy gem) is the player's when its link
holds no proxy support, and it counts at THAT SKILL'S OWN PoB rate (`PobSession.active_skill_stats`): triggered
(Manaforged Arrows: 0.985-1.036 per second on impale_ballista, placing a ballista is the bow attack that triggers
it) -> 2 charges inside the 2.5 s budget; hand-used on a totem build -> the time left after placing the totem limit
(`TotemPlacementTime` 0.30 s x 5); hand-used on a trap / mine build -> none. The lead's first draft zeroed the
hand-used case without looking; the user: "you have all the data, compute it".

Lane diff over the 58 references (the lead's run): 7 move, nothing turns on -- `overrideFrenzyCharges` 2 on
impale_ballista and both champion_explosive_arrow builds; `conditionHitRecently` off on exsanguinate_mines,
pyroclast_mine, lightning_trap, impale_ballista; `conditionCritRecently` off on z328_hierophant_kinetic_fusillade.
impale_ballista s1 re-derived: 963,133 -> 804,735.

