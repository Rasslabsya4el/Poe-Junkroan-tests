# 2026-09-11 D17. Trials go through PoB's own what-if calculator

Status: Accepted

`calcs.getMiscCalculator(build)` returns a function that computes a full
output table for an override (addNodes, removeNodes, repSlotName + repItem,
toggleFlask) in one calc pass without touching the build. Measured: 7 ms per
node trial vs 166 ms for allocate + OnFrame + restore, with identical results.
The optimizer evaluates candidates in this mode; real mutations are applied
only for the chosen step. Node removal in this mode does not cascade, so it
is used for graph-verified leaves only. Gear trials will use `repItem`; gem
trials mutate the socket group and restore, as PoB's own gem sorter does.

