"""#408: an item trial reads the same in fast mode and in full mode.

cold_dot-s4 (Cold Snap, template run 20260926-1759): the Ring 1 and Helmet cold-resistance line swaps of issue #10
are trialled in both modes. Until #398 (895d349) a full-mode trial did not look at the item at all (the full Lua
had no `trial.item` branch), so full read the unchanged build while fast read the swapped item: ColdResist 75 vs
less than 75, CombinedDPS and EnergyShield apart, the issue's "Helmet 0 of 11 vs 11 of 11 keep ColdResist >= 75".
Fast and full now equip the item the same way; this test keeps them equal. Skipped without the runtime or the run folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
BUILD = PROJECT_ROOT / "artifacts" / "benchmark" / "20260926-1759-core14-tpl-main3-s4" / "cold_dot-s4.pob.txt"

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file() or not BUILD.is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}, or the run folder {BUILD} is missing",
)]

SLOTS = ("Ring 1", "Helmet")
CANDIDATES_PER_SLOT = 4
KEYS = ("CombinedDPS", "ColdResist", "Life", "EnergyShield", "FireResist", "LightningResist")
EXACT_KEYS = ("ColdResist", "Life", "EnergyShield")
# Tree-trial reference (scripts/issue408_fast_full.py, 20 node trials per seed on cold_dot seeds 4-6, 2026-10-02): the
# max |fast - full| / full of CombinedDPS over the trials whose node set is the same in both modes is 0 on all three seeds
# (bit-equal). An item trial must not be worse than that; 1e-9 is the float noise floor, not a looser rule.
TREE_TRIAL_COMBINED_DPS_GAP = 1e-9


@pytest.fixture(scope="module")
def pob():
    with PobSession(run_id="test-trial-fast-full-item", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_import_code(BUILD.read_text(encoding="utf-8").strip())
        yield session


def test_item_trials_read_the_same_in_fast_and_full(pob: PobSession) -> None:
    from issue408_fast_full import BASE_KEYS, PoolProvider, _slots_to_items, rel_diff
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.random_parts import apply_mean_parts, main_skill_of
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.wishlist_gear import WishlistGear

    apply_mean_parts(pob)
    skill, _part = main_skill_of(pob.read_state())
    rails = Rails.load()
    objective = objective_for(rails, skill)
    keys = tuple(dict.fromkeys((*BASE_KEYS, *KEYS, *objective.stat_keys)))
    items = dict(_slots_to_items(decode_import_code(BUILD.read_text(encoding="utf-8").strip())))
    pool = {c["slot"]: c["options"] for c in PoolProvider(pob, WishlistGear(pob, objective, rails))({s: items[s] for s in SLOTS})}
    assert set(pool) == set(SLOTS), sorted(pool)

    for slot in SLOTS:
        options = pool[slot][:CANDIDATES_PER_SLOT]
        assert len(options) == CANDIDATES_PER_SLOT, slot
        # the unchanged item first, then the line swaps
        trials = [{"item": {"slot": slot, "raw": items[slot]}}] + [{"item": {"slot": slot, "raw": o["raw"]}} for o in options]
        fast = pob.trial_stats(trials, keys, mode="fast")
        full = pob.trial_stats(trials, keys, mode="full")
        for i, (f, g) in enumerate(zip(fast, full)):
            what = f"{slot} candidate {i} ({'unchanged item' if i == 0 else options[i - 1]['line']})"
            assert f["ok"] and g["ok"], (what, f.get("error"), g.get("error"))
            for key in EXACT_KEYS:
                assert f["stats"][key] == g["stats"][key], f"{what}: {key} fast {f['stats'][key]} vs full {g['stats'][key]}"
            gap = rel_diff(f["stats"]["CombinedDPS"], g["stats"]["CombinedDPS"])
            assert gap <= TREE_TRIAL_COMBINED_DPS_GAP, f"{what}: CombinedDPS fast {f['stats']['CombinedDPS']} vs full {g['stats']['CombinedDPS']} (rel {gap:.3g})"
