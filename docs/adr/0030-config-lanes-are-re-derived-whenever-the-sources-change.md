# 2026-09-11 D30. Config lanes are re-derived whenever the sources change

Status: Accepted

The conservative lane is derived from what the build proves. A pipeline
that derives it once at the start and optimizes for 20 minutes under it is
optimizing under stale assumptions: on Fireball Inquisitor the support
re-pick chose Elemental Focus while "enemy ignited" was still on from the
bare skeleton, and the final honest lanes took the build from 919k to 492k.
Now the lanes are re-derived after every gear pass and after every support
pick; a support that only wins under an assumption it removes is rejected.
The same principle applies to any future stage that changes sources.

