"""#702: the Shock, Chill, Scorch, Brittle and Sap a build's own hits earn are typed into the config lane.

Kind (D113): evaluation fix. Rows 1-5 and 7 of the issue's table on hit_penance_brand-s4 (a 2026-10-05 gate build,
`artifacts/benchmark/20261005-1220-gate-20261005/`) and on the author fixture; row 6 is a text check of the three
files; the pure `ailment_ramp` and the 0.90 uptime cut-off need no PoB. Row 8 is the replay bench, not here."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import OWN_HIT_MIN_UPTIME, ailment_ramp, derive_config, own_hit_ailments, ELEMENT_HIT_KEYS
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
S4 = PROJECT_ROOT / "artifacts" / "benchmark" / "20261005-1220-gate-20261005" / "hit_penance_brand-s4.pob.txt"
AUTHOR = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "hit_penance_brand.pob.txt"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

T = 6_349_995.2388096  # row 1: the boss ailment threshold of the build (level 84, Pinnacle)
S4_D0, S4_D = 355_313.6996, 30.0
AUTHOR_D0, AUTHOR_D = 181_201.71875, 25.0


# --- pure, no PoB: the ramp iteration and the uptime bar ---------------------------------------------------------

def test_ailment_ramp_s4_shock_rows_2_and_3() -> None:
    effects, mean, steady = ailment_ramp(d0=S4_D0, threshold=T, k=50.0, effect_mod=1.0, maximum=50.0, other_damage_taken=S4_D, hits=3)
    assert effects == pytest.approx((15.78, 16.52, 16.55), abs=0.01)
    assert steady == pytest.approx(16.55, abs=0.01)
    assert mean == pytest.approx(10.77, abs=0.01)  # S_0 = 0: (0 + S_1 + S_2) / 3
    assert int(mean + 0.5) == 11


def test_ailment_ramp_author_shock() -> None:
    effects, mean, steady = ailment_ramp(d0=AUTHOR_D0, threshold=T, k=50.0, effect_mod=1.0, maximum=50.0, other_damage_taken=AUTHOR_D, hits=4)
    assert effects[:3] == pytest.approx((12.05, 12.51, 12.52), abs=0.01)
    assert mean == pytest.approx(9.27, abs=0.01)
    assert steady == pytest.approx(12.52, abs=0.01)
    assert int(mean + 0.5) == 9


def test_ailment_ramp_without_damage_taken_is_flat_and_capped() -> None:
    effects, mean, steady = ailment_ramp(d0=84_369.66, threshold=T, k=50.0, effect_mod=1.0, maximum=30.0, other_damage_taken=None, hits=3)
    assert effects == pytest.approx((8.88, 8.88, 8.88), abs=0.01) and steady == pytest.approx(8.88, abs=0.01)
    assert mean == pytest.approx(8.88 * 2 / 3, abs=0.01)  # the first hit meets no chill yet
    capped = ailment_ramp(d0=1e12, threshold=T, k=50.0, effect_mod=1.0, maximum=30.0, other_damage_taken=None, hits=2)
    assert capped[0] == (30.0, 30.0) and capped[2] == 30.0


class _FakePob:
    """Just enough session for own_hit_ailments: one lightning hit of fixed damage, `chance` % Shock per hit, one hit per second."""

    def __init__(self, chance: float) -> None:
        self.chance = chance
        self.set_calls: list[dict] = []
        self.checkpoints = 0
        self.rollbacks = 0

    def config_checkpoint(self) -> None:
        self.checkpoints += 1

    def config_rollback(self) -> None:
        self.rollbacks += 1

    def read_state(self) -> dict:
        return {"config_state": {}}

    def set_config(self, **kw) -> None:
        self.set_calls.append(kw)

    def stats(self, keys=None) -> dict:
        full = {"LightningHitAverage": S4_D0, "LightningCritAverage": S4_D0, "CritChance": 0.0, "HitTime": 1.0,
                "MaximumShock": 50.0, "ShockChanceOnHit": self.chance, "ShockChanceOnCrit": 0.0, "ShockEffectMod": 1.0,
                "ShockDuration": 2.0, "EnemyAilmentThreshold": T, "AilmentMinimumShock": 5.0}
        return {k: v for k, v in full.items() if keys is None or k in keys}


def test_uptime_bar_is_point_nine() -> None:
    assert OWN_HIT_MIN_UPTIME == 0.90
    keep = _FakePob(70.0)  # 2 hits per 2 s: 1 - 0.3^2 = 0.91
    rows = own_hit_ailments(keep, keep.stats(), boss="Pinnacle", ramp_seconds=2.5)
    assert len(rows) == 1 and rows[0].uptime == pytest.approx(0.91) and rows[0].applies and rows[0].typed > 0
    assert keep.checkpoints == keep.rollbacks == 1  # the probe leaves the config as it found it
    drop = _FakePob(60.0)  # 1 - 0.4^2 = 0.84
    rows = own_hit_ailments(drop, drop.stats(), boss="Pinnacle", ramp_seconds=2.5)
    assert len(rows) == 1 and rows[0].uptime == pytest.approx(0.84) and not rows[0].applies
    assert "needs 90%" in rows[0].why


# --- row 6: the claim is gone from the three files ---------------------------------------------------------------

CLAIM = re.compile(r"applies?\s+(?:those\s+|it\s+|them\s+)?by itself|PoB applies", re.IGNORECASE)


@pytest.mark.parametrize("rel", ["src/junkroan/optimizer/config_rules.py", "tests/test_config_rules.py", "src/junkroan/mechanics/pending_facts.json"])
def test_no_pob_applies_hit_shock_by_itself_claim(rel: str) -> None:
    text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    assert [m.group(0) for m in CLAIM.finditer(text)] == []


# --- rows 1-5 and 7 on the benches -------------------------------------------------------------------------------

def _load(pob: PobSession, path: Path) -> dict:
    pob.load_xml(decode_import_code(path.read_text(encoding="utf-8").strip()))
    stats = pob.stats()
    stats.update(pob.stats(ELEMENT_HIT_KEYS))
    return stats


def _lane_dps(pob: PobSession, inputs: dict) -> float:
    state = pob.read_state()["config_state"]
    pob.set_config(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None",
                   pantheon_minor=state.get("pantheon_minor") or "None", enemy_state={"is_boss": "Pinnacle"},
                   inputs={k: v for k, v in inputs.items() if k != "enemyIsBoss"})
    return pob.stats(("CombinedDPS",))["CombinedDPS"]


@pytest.fixture(scope="module")
def s4(tmp_path_factory):
    if not S4.is_file():
        pytest.skip(f"{S4} not present")
    with PobSession(run_id="test-702-s4", artifacts_root=tmp_path_factory.mktemp("s4")) as pob:
        stats = _load(pob, S4)
        yield pob, stats


@needs_pob
@pytest.mark.pob
def test_s4_rows_1_to_4(s4) -> None:
    pob, stats = s4
    baseline = stats["CombinedDPS"]
    assert baseline == pytest.approx(810_563.71, abs=1)
    rows = {r.ailment: r for r in own_hit_ailments(pob, stats, boss="Pinnacle", ramp_seconds=2.5)}
    shock = rows["Shock"]
    assert shock.threshold == pytest.approx(6_349_995, abs=1)  # row 1
    assert shock.d0 == pytest.approx(355_314, abs=0.5) and shock.other_damage_taken == pytest.approx(30, abs=0.5)  # row 2
    assert shock.effects == pytest.approx((15.78, 16.52, 16.55), abs=0.01) and shock.steady == pytest.approx(16.55, abs=0.01)  # row 3
    assert shock.typed == 11 and shock.applies  # row 4
    assert pob.stats(("CombinedDPS",))["CombinedDPS"] == pytest.approx(baseline, abs=1e-6)  # the probe left no trace
    lane = derive_config(pob).conservative
    assert lane.inputs["conditionEnemyShocked"] is True and lane.inputs["conditionShockEffect"] == 11
    assert _lane_dps(pob, lane.inputs) == pytest.approx(914_316, abs=1)  # row 4: 810,564 -> 914,316


@needs_pob
@pytest.mark.pob
def test_s4_trace_counter_row_7(tmp_path) -> None:
    if not S4.is_file():
        pytest.skip(f"{S4} not present")
    with PobSession(run_id="test-702-trace", artifacts_root=tmp_path) as pob:  # a fresh load: the build's config carries no typed effect yet
        _load(pob, S4)
        TRACE.reset()
        lane = derive_config(pob).conservative
        generated = [c["conditionShockEffect"] for c in TRACE.considered().values() if "conditionShockEffect" in c]
        assert sum(c["generated"] for c in generated) > 0 and sum(c["evaluated"] for c in generated) == 0  # the probe inside derive_config is muted
        _lane_dps(pob, lane.inputs)
        counts = [c["conditionShockEffect"] for c in TRACE.considered().values() if "conditionShockEffect" in c]
        assert sum(c["generated"] for c in counts) > 0 and sum(c["evaluated"] for c in counts) > 0


@needs_pob
@pytest.mark.pob
def test_author_fixture_row_5(tmp_path) -> None:
    with PobSession(run_id="test-702-author", artifacts_root=tmp_path) as pob:
        stats = _load(pob, AUTHOR)
        shock = next(r for r in own_hit_ailments(pob, stats, boss="Pinnacle", ramp_seconds=2.5) if r.ailment == "Shock")
        assert shock.d0 == pytest.approx(AUTHOR_D0, abs=0.5) and shock.other_damage_taken == pytest.approx(AUTHOR_D, abs=0.5)
        assert shock.hits == 4
        assert shock.mean == pytest.approx(9.27, abs=0.01) and shock.steady == pytest.approx(12.52, abs=0.01) and shock.typed == 9
        state = pob.read_state()["config_state"]
        pob.set_config(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None",
                       pantheon_minor=state.get("pantheon_minor") or "None", enemy_state={"is_boss": "Pinnacle"},
                       inputs={"conditionEnemyShocked": True, "conditionShockEffect": shock.typed}, preserve="all")
        assert pob.stats(("CombinedDPS",))["CombinedDPS"] == pytest.approx(810_535, abs=1)
