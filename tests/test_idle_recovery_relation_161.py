"""#161: the delivered build must satisfy the rails' idle-recovery relation.

The build in the fixture is the one the loop delivered for
`z325_berserker_ground_slam_autocry` seed 4 of the run
`20260927-0322-ziz-tpl-main3-s4` (pipeline pinned at 42565a9). Its audit line is
``relation: NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond = -15.6 < 0 x
Life = 7970.0``: the loop reached a fixed point while the relation was still
missed, because the shortfall is worth only 15.6 / 7970 = 0.002 of violation and
every move that buys life regeneration pays for it with the Defiant Stand
notable, whose removal costs `useEnduranceCharges` and `useFrenzyCharges`
(-14.8% CombinedDPS) under the re-derived lanes. PoB-backed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGRESSIONS = PROJECT_ROOT / "tests" / "fixtures" / "regressions"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

IDLE_RECOVERY_SUM = "NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond"


@pytest.mark.xfail(
    strict=True,
    reason="#161: the delivered ground_slam_autocry s4 build is at "
           "NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond = -15.6 < 0 x Life = 7970",
)
def test_ground_slam_autocry_s4_meets_the_idle_recovery_relation(tmp_path: Path) -> None:
    relation = next(rel for rel in Rails.load().objective().relations if rel[0] == IDLE_RECOVERY_SUM)
    parts = tuple(part.strip() for part in relation[0].split("+"))
    with PobSession(run_id="test-161-idle-recovery", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((REGRESSIONS / "ground-slam-autocry-tpl-s4.pob.txt").read_text(encoding="utf-8").strip()))
        stats = pob.stats((*parts, relation[1]))

    # `SelfCostPerSecond` is derived, not a PoB stat: absent it counts as 0, as `Objective._value` does.
    recovered = sum(float(stats[key]) for key in parts if isinstance(stats.get(key), (int, float)))
    pool = float(stats[relation[1]])
    assert recovered >= float(relation[2]) * pool, f"{relation[0]} = {recovered:.1f} with {relation[1]} = {pool:.0f}"
