"""#171 (the fix of the diagnosis #156): `ManaUnreserved >= 0` is a relation of every objective.

36 of 278 rows of the five benchmark runs pinned at @42565a9 ended with `ours_mana_unreserved` < 0,
every one of them with the keystone Eldritch Battery, and every one of them with stage violation 0
and "final feasibility: ok". The only floor that read `ManaUnreserved` on such a build was the cost
relation `ManaCostPool >= ManaCost` (optimizer/rails.py), and `ManaCostPool` adds the whole
`EnergyShield` pool under `EnergyShieldProtectsMana` (optimizer/castability.py), so a mana pool
reserved past zero was invisible to it. PoB itself leaves the number negative
(Modules/CalcPerform.lua:541-543: `ManaReserved` is clamped to the pool, `ManaUnreserved` is not)
and warns on it ("Your unreserved Mana is negative", Modules/BuildDisplayStats.lua:130).

The rails objective now carries `("ManaUnreserved", "ManaOverReserved", 1.0, "Mana")`, which is
`ManaUnreserved >= 0` and nothing else: the derived floor is 0 while the pool is whole. On the
delivered winter_orb fixture (Mana 926, ManaUnreserved -232) it prices 1.0 + 232 / 926 = 1.2505,
so the build the optimizer called feasible is infeasible, while the same build with a whole pool
pays nothing. The cost relation keeps pricing `EnergyShield` into the pool, unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.castability import MANA_OVER_RESERVED_STAT, mana_cost_pool_stat
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "regressions" / "winter-orb-eldritch-battery-s4.pob.txt"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
RELATION = f"ManaUnreserved>={MANA_OVER_RESERVED_STAT}"

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def test_winter_orb_final_build_leaves_mana_unreserved_at_or_above_zero(tmp_path: Path) -> None:
    objective = Rails.load().objective()
    with PobSession(run_id="test-171-eldritch-battery", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(FIXTURE.read_text(encoding="utf-8").strip()))
        stats = pob.stats(objective.stat_keys)

    assert stats["EnergyShieldProtectsMana"]  # the fixture is the Eldritch Battery build of the ticket
    assert float(stats["ManaUnreserved"]) == -232.0 and float(stats["Mana"]) == 926.0
    # what the optimizer judged: the cost floor of the mana pool is met on this very build
    assert mana_cost_pool_stat().fn(stats, objective) >= float(stats.get("ManaCost") or 0.0)

    # what the ticket asks for: the over-reserved pool is a violation of the objective itself,
    # the whole missed floor plus the overflow relative to `Mana`
    violations = objective.violations(stats)
    assert violations[RELATION] == pytest.approx(1.0 + 232.0 / 926.0, abs=5e-4)  # 1.2505
    assert round(violations[RELATION], 3) == 1.251
    assert not objective.score(stats).feasible

    # and a build whose pool is whole pays nothing for it
    whole = {**stats, "ManaUnreserved": 0.0}
    assert RELATION not in objective.violations(whole)
    assert RELATION not in objective.violations({**stats, "ManaUnreserved": 694.0})


def test_over_reserved_pool_is_an_audit_error_with_the_number(tmp_path: Path) -> None:
    """A delivered build with `ManaUnreserved` < 0 is named by the audit (#171 deliverable 2)."""

    from junkroan.optimizer.audit import audit_stats

    objective = Rails.load().objective()
    stats = {"Mana": 926.0, "ManaUnreserved": -232.0, "CombinedDPS": 1.0}
    findings = [f for f in audit_stats(stats, objective) if "ManaUnreserved" in f.detail]
    assert [(f.severity, f.detail) for f in findings] == [
        ("error", "ManaUnreserved = -232.0 < 0: reservation takes 232.0 mana past the pool of Mana = 926.0"),
    ]
    assert not [f for f in audit_stats({**stats, "ManaUnreserved": 12.0}, objective) if "ManaUnreserved" in f.detail]
