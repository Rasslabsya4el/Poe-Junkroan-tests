# 2026-09-18 D70. Reliquarian is a searchable ascendancy; ascendancy picks may be stat-carrying plain nodes

Status: Accepted

Reliquarian was skipped by the search as "not a player ascendancy" and its picks were invisible to
the generator. Both halves were wrong.

**PoB scores it.** Measured on a bare Scion rig, one hub option at a time: Kaom's Roots +100 Life,
Elevore +25% spell suppression, Xirgil's Crank +12.9% CombinedDPS, Presence of Chayula -242 Life /
+246 ES. The options of one hub are mutually exclusive and PoB refuses the second one outright, so
the generator offers them as alternatives, never as a set. The user's rule on top of the numbers:
Reliquarian's passives are replaced every league, so it belongs in the search on this league's tree
and a previous-league Reliquarian PoB is never a fixture.

`NOT_PLAYER_ASCENDANCIES` is now `{"luminary"}` only -- Luminary is the 3.29 Mercenary system, not a
player ascendancy in PoB.

**A pick may be a plain node.** `SkeletonGenerator._ascendancy_picks` is now the notables plus the
stat-carrying neighbours of the notables that carry no stats themselves, which is how Reliquarian's
unique-item nodes and Ascendant's class hubs are reached at all. 27 of the 37 ascendancies are
unchanged; Ascendant (+30 candidates), Assassin (+4) and Reliquarian (+30) gain candidates, and
every one of them is judged by PoB like any other pick. PoB's "did not materialize" refusal (the
second option of a hub, the Warden symptom) is caught and the build restored, so a refused pick
costs a trial and nothing else. Commit dc25f62.

