"""Phase 1 harness ergonomics, proven against the pinned PoB runtime.

- arbitrary config inputs reach PoB and change numbers
- incremental node add/remove works and is fast
- node power report has a usable shape
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from junkroan.pob.session import PobSession, decode_import_code
from timing_bound import bound

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-phase1", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        yield session


def _fresh_fireball(pob: PobSession) -> None:
    pob.set_identity(level=90)
    pob.set_tree(class_id="Witch", ascendancy_id="Elementalist")
    pob.set_skills(main_link=["Fireball", "Spell Echo", "Controlled Destruction", "Increased Critical Strikes"])
    pob.set_config(enemy_state={"is_boss": "Pinnacle"})


def test_config_inputs_change_pob_numbers(pob: PobSession) -> None:
    _fresh_fireball(pob)
    base = pob.calc()

    pob.set_config(enemy_state={"is_boss": "Pinnacle"}, inputs={"usePowerCharges": True})
    with_charges = pob.calc()
    assert with_charges["CritChance"] > base["CritChance"]
    assert with_charges["CombinedDPS"] > base["CombinedDPS"]

    pob.set_config(enemy_state={"is_boss": "Pinnacle"}, inputs={"enemyIsBoss": "Uber"})
    uber = pob.calc()
    assert uber["CombinedDPS"] < base["CombinedDPS"]  # uber bosses have more resistance

    with pytest.raises(PoBHeadlessHostContractError):
        pob.set_config(inputs={"thisIsNotAPobConfigVar": True})


def test_conditional_lane_can_differ_from_baseline(pob: PobSession) -> None:
    _fresh_fireball(pob)
    pob.set_config(enemy_state={"is_boss": "Pinnacle"}, conditional={"inputs": {"usePowerCharges": True}})
    baseline = pob.calc(lane="baseline")
    conditional = pob.calc(lane="conditional")
    assert conditional["CombinedDPS"] > baseline["CombinedDPS"]


def test_incremental_node_mutation_on_reference_build(pob: PobSession) -> None:
    code = (FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()
    xml = decode_import_code(code)
    pob.load_xml(xml)
    before = pob.calc()
    base = pob.mutate_nodes()  # no-op: same accounting as later mutations
    allocated = list(base["allocated_node_ids"])
    assert len(allocated) > 90
    assert base["points_used"] == len(allocated)

    # Find a true leaf: removing it must cascade to nothing else.
    leaf = None
    for candidate in reversed(allocated):
        result = pob.remove_nodes([candidate])
        if result["removed_node_ids"] == [candidate]:
            leaf = candidate
            break
        pob.load_xml(xml)  # removal cascaded; restore and try another
    assert leaf is not None

    t0 = time.perf_counter()
    after_remove = pob.calc()
    elapsed_calc = time.perf_counter() - t0
    assert leaf not in result["allocated_node_ids"]
    assert len(result["allocated_node_ids"]) == len(allocated) - 1
    assert result["points_used"] == len(allocated) - 1

    # Re-add. If the leaf was a mastery, the removal reported its lost effect and
    # re-adding without it must be refused (PoB would otherwise count every option).
    lost_masteries = {int(k): int(v) for k, v in (m.split(":") for m in result["removed_mastery_effects"])}
    if lost_masteries:
        with pytest.raises(PoBHeadlessHostContractError):
            pob.add_nodes([leaf])
    t0 = time.perf_counter()
    result = pob.add_nodes([leaf], mastery_effects=lost_masteries)
    elapsed_mutate = time.perf_counter() - t0
    after_add = pob.calc()
    assert result["added_node_ids"] == [leaf]
    assert abs(after_add["CombinedDPS"] - before["CombinedDPS"]) < 1e-6 * max(1.0, before["CombinedDPS"])
    assert after_remove["CombinedDPS"] <= before["CombinedDPS"] + 1e-6 or after_remove["Life"] <= before["Life"]
    assert elapsed_mutate + elapsed_calc < bound(floor=1.0, factor=7), f"mutate {elapsed_mutate:.2f}s + calc {elapsed_calc:.2f}s"

    with pytest.raises(PoBHeadlessHostContractError):
        pob.add_nodes([999999999])


def test_node_power_report_shape(pob: PobSession) -> None:
    code = (FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()
    pob.load_xml(decode_import_code(code))
    report = pob.node_power()
    assert report["status"] == "accepted", report.get("failure_state")
    rows = report["rows"]
    assert len(rows) > 50
    row = rows[0]
    assert {"node_id", "node_name", "node_power_score", "path_power_score"} <= set(row)


def test_fast_stats_match_full_calc_and_are_fast(pob: PobSession) -> None:
    code = (FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()
    pob.load_xml(decode_import_code(code))
    full = pob.calc()
    keys = ("CombinedDPS", "Life", "TotalEHP", "FireResist")
    fast = pob.stats(keys)
    assert set(fast) == set(keys)
    for key in keys:
        assert fast[key] == full[key], key

    everything = pob.stats()
    assert len(everything) > 500

    t0 = time.perf_counter()
    for _ in range(5):
        pob.stats(keys)
    assert (time.perf_counter() - t0) / 5 < bound(floor=0.05, factor=0.35) # clean build: no recalc, just a read


def test_fast_trials_match_full_trials(pob: PobSession) -> None:
    """PoB's what-if calculator (fast mode) must agree with real allocate+recalc (full mode)."""

    from junkroan.optimizer.tree_graph import TreeGraph

    code = (FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip()
    pob.load_xml(decode_import_code(code))
    graph = TreeGraph.load()
    allocated = {int(n) for n in pob.read_state()["tree_state"]["user_allocated_node_ids"]} | {graph.class_starts["Templar"]}
    cands = [c for c in graph.candidates(allocated, max_depth=4) if c.kind != "mastery"][:25]
    leaves = [n for n in graph.removable_leaves(allocated) if n in graph.allocatable][:5]
    trials = [{"add": [c.node_id]} for c in cands] + [{"remove": [leaf]} for leaf in leaves]
    keys = ("CombinedDPS", "Life", "TotalEHP")

    t0 = time.perf_counter()
    fast = pob.trial_stats(trials, keys, mode="fast")
    fast_seconds = time.perf_counter() - t0
    full = pob.trial_stats(trials, keys, mode="full")

    assert all(r["ok"] for r in fast) and all(r["ok"] for r in full)
    for a, b in zip(full, fast):
        assert a["added_node_ids"] == b["added_node_ids"]
        assert a["removed_node_ids"] == b["removed_node_ids"]
        for key in keys:
            assert abs(a["stats"][key] - b["stats"][key]) <= 1e-6 * max(1.0, abs(a["stats"][key])), key
    assert fast_seconds / len(trials) < bound(floor=0.05, factor=0.35) # ~7 ms measured; generous bound
