# 2026-09-11 D12. The worker's Lua tracks the pinned PoB version

Status: Accepted

`headless_runtime_worker.py` generates Lua that calls PoB internals. A PoB
bump can change those signatures (v2.67 added `className` as the first
argument of `PassiveSpec:ImportFromNodeList`). This is accepted: the fix is
a one-line change per drift, verified by `tests/test_reference_fixtures.py`,
which loads all reference builds and compares stats to the recorded ones.

