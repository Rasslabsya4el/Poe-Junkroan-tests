# 2026-09-11 D11. CombinedDPS is the objective metric

Status: Accepted

PoB's `FullDPS` is populated only for socket groups flagged "include in full
DPS" and reads 0 on half of the imported reference builds. `CombinedDPS`
(hit + DoT of the main skill) is always populated and is what the optimizer
maximizes by default.

