# 2026-09-23 D100. The region challenge leaves the default loop; a removed move shifts the kicks' random draws; our tree graph disagrees with PoB on a bridge

Status: Accepted

(1) Regions off (the owner's call on the move-ledger reading, D93; branch `opus-2026-09-22-regions-off`, merged fdf6d6b).
Paired smoke `noregions-smoke` @3c579ea against `main-smoke-aa` @585ae29 (same seeds; builds 1-4 ran on 3 queue
workers while the owner played, and values there matched to the digit, so load did not move numbers): 13 of 18 builds
identical to the digit; median of medians 138.6 -> 132.8 (cold_dot -22.1 from ONE build, s3 360,273 -> 221,705, 11 ->
6 passes; burning_arrow_snipe -6.4; stormbrand +1.1 with s1 +5%, s2 +2%, s3 -17%). Regions kept nothing in either run
(0 of 65 tries on `main-smoke-aa`). Every one of the five diverging builds has the same move history up to a kick,
and the kick then draws a different candidate (cold_dot s3 pass 4 kick joint: nothing in aa, +2,499 without regions):
the region challenge consumed the shared random stream, so removing it re-draws every later kick -- a new seed for the
kicks, not a loss caused by the removal. On expected value the move is 0.6% of the loop's gain for 5.7% of its time
over 180 builds; it goes. Kept as a switch like corridors.
(2) Consequence for judging: any change that draws random numbers, or stops drawing them, reshuffles the kicks, so a
paired smoke measures a different lottery ticket on every build that reaches a kick. Proposal (not coded): each move
gets its own random stream derived from (build seed, move name, pass), so a paired run keeps identical kicks and shows
only what the change itself does.
(3) Found while checking D98 (the lead, one PoB call): on spark-s1 (core14-tpl) `TreeGraph` says node 8198 has two
allocated neighbours (55993, 13164) and `cascade_if_removed` = {8198} -- a removable leaf -- while PoB's own removal
takes 8198 AND 13164 Divine Judgement (CombinedDPS 1,018,180 -> 966,608). Our pure-Python graph and PoB disagree on
connectivity somewhere; the optimizer's leaf moves and cascade estimates stand on that graph. Open: find the edge(s)
where they disagree over the delivered trees of the recent runs (graph-only sweep + one PoB removal per disagreement).

