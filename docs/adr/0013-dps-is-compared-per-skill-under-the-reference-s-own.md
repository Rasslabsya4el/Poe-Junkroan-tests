# 2026-09-11 D13. DPS is compared per skill under the reference's own assumptions

Status: Accepted

Raw CombinedDPS is not comparable across skills: Spark in the reference set
shows ~350k because its author did not set full-DPS/hit-count options, while
Winter Orb has both self-cast and totem groups flagged and counted. So the
optimizer's acceptance is always relative to the same-skill reference under
identical config and socket-group flags. The global DPS numbers in
`rails_default.json` are a sanity floor, never a cross-skill target.
Hit-multiplicity assumptions (projectile overlap, instance counts) are the
kind of non-PoB fact that belongs in `mechanics/notes.json`.

