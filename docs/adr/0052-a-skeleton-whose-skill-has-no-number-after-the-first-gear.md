# 2026-09-14 D52. A skeleton whose skill has no number after the first gear pass is refused

Status: Accepted

The Smite search's PoB folder held four "builds" with 26-28 passive nodes:
weapon variants (staff, sceptre) that inherited the sword finalist's
supports, and Close Combat leaves Smite at 0 DPS on either weapon. The
greedy stopped at once ("no candidate improves the objective"), every
later stage ran on nothing, the support re-pick eventually found a number
(8-31k), and the search ranked them next to the real builds and wrote
them to PoB. The variant screen (86d2d1b) now drops such variants, and
`BuildPipeline.run` raises after gear pass 1 when the objective is not
positive with a weapon in hand: a build with no number is not a build to
optimize, and the search records the failure instead of a result. Follow-up done
2026-09-15: before refusing, the pipeline lets PoB choose the supports
again on that rig when the link carries any support the request did not
fix, so a staff Smite is judged with supports a staff can carry; the
refusal remains for a skill with no number under any support.

