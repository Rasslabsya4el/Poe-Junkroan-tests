# 2026-09-14 D54. Hit chance is capped by universal means only; picks are judged again on the finished build

Status: Accepted

A Smite benchmark build took both Accuracy Mastery ("40% more Accuracy
Rating against Unique Enemies") and Mark Mastery ("50% more against Marked
Enemy"): the objective judges hit chance against a unique boss, so those
two lines capped it at 100% while normal monsters would be hit at ~70%. Hit
chance is a gate on whether damage happens at all, and the user's rule is
that it is capped by universal means, so that the boss-judged hit chance is
a lower bound for maps (bosses have more evasion). Rails `tree.forbidden_text`
(regexes over passive lines): the tree optimizer never allocates a node whose
every line matches nor a mastery effect that matches (`TreeOptimizer.forbid_text`;
today the two accuracy effects, 23152 and 57597); the audit warns when a build
carries one. The same file is the place for the next line of this kind.

Picks: supports and utilities were chosen on the rig (supports once more after
gear pass 2) and never judged again; a Smite Slayer kept Immolate over Trinity
(no fire or cold in its hits when supports were judged, Anger and Herald of Ice
came later) and Flammability over Elemental Weakness (Anger in, Herald of Ice
not yet). `SkeletonGenerator.rejudge_picks`, a pipeline stage after the joint
one: every support slot (not the request's fixed ones) and every picked utility
group against every alternative, one at a time, kept when the objective under
re-derived lanes gains 0.5%; a short refine when anything changed; sweeps until
one changes nothing. The fixed-point form of what the stages approximate.

