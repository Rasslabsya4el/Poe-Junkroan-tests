# 2026-09-20 D87. Tree moves see the proofs the conservative lane stands on (the judge fix)

Status: Accepted

Found from the user's "how did a useless Minion Life node survive?" (19.09): tree moves judged removals with the config
frozen, the pipeline re-derived it and reverted the WHOLE batch -- 202 reverted path-swap moves, 11,551 s, 117 kept
swaps lost over the 42 builds of `core14-rules`. Three attempts: (1) re-derive after EVERY real removal -- the reverts
went away and so did half of the search (swap candidates per 120 s move 10 -> 4.75 and 12 -> 7, two RESTORE FAILED):
rejected; (2) honest judging only for SOLE proofs -- the machinery was right and the map was empty, because
winter_orb's `usePowerCharges` stands on the SUM of two lines (an Occultist ascendancy node + Caster Mastery);
(3) merged (4dccc46): a node / mastery effect is a proof HOLDER when the input's own rule, re-run with that node's
lines masked, turns the input off or lowers its number (pure Python over the evidence `derive_config` already holds,
2-3 ms per reconfigure; ascendancy, item and gem lines are fixed evidence). Only a removal set containing a holder
is judged honestly (real removal + reconfigure + exact restore); a judged revert keeps the rejected-subtree memory;
a rejected batch is replayed swap by swap (90 s budget) and every FALSE swap names the config inputs it changed.
Accepted on counts and on the replay bench (D84), not on a seed's value: batches reverted at a loss 5 -> 0, Minion
Life gone from the delivered winter_orb, 61 holder lines and 23 honest judgements (~5 s each against 1-2 s), 0 RESTORE
FAILED, whole suite 876 passed. The replay named the cause of the false swaps: Caster Mastery's power charges in 5 of
6; Intelligence, flask and mark clusters were bystanders of those batches. Open: the audit's dead-node check is
frozen-config blind in the same way (it called Caster Mastery's line "worth zero" while its removal costs 14%).

