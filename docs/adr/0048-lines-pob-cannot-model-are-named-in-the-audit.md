# 2026-09-14 D48. Lines PoB cannot model are named in the audit

Status: Accepted

`audit_unsupported_mods` runs every mod line a finished build carries
(item implicits and explicits except flasks, allocated notables and
keystones, the chosen mastery effects) through PoB's own parser
(`PobSession.parse_mods`) and lists the lines PoB marks unsupported, each
with where it comes from: "10% chance to Aggravate Bleeding on targets you
Hit with Attacks (Bloodletting): worth zero in every number here". The
numbers stay honest (they never counted these), the reader learns what
the build has that they do not. On-kill charge generation and "enemies
cannot leech" show up the same way; they are true zeros in PoB.

