"""A random-element skill is scored as the mean over its element parts (the user's reading
2026-09-18, elemental_hit; research 2026-09-18-game-knowledge-2 2): PoB shows one part as if
every hit were that element. The groups come from PoB's own part names; `PobSession.mean_parts`
makes every readback and fast trial average them."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from junkroan.optimizer.random_parts import element_groups, main_skill_of, mean_parts_for, random_element_groups
from junkroan.pob import skill_facts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
needs_skill_data = pytest.mark.skipif(not skill_facts._blocks(), reason="PoB skill data not present")


def test_element_groups_come_from_the_part_names_alone() -> None:
    eh = ("Fire Attack", "Fire AoE", "Cold Attack", "Cold AoE", "Lightning Attack", "Lightning AoE")
    assert element_groups(eh) == [(1, 3, 5), (2, 4, 6)]
    ws = ("Fire hit", "Fire explosion", "Lightning hit", "Lightning bolt", "Cold hit", "Icy wave")
    assert element_groups(ws) == [(1, 3, 5)]  # the secondaries differ by more than the element word: single parts
    assert element_groups(("0 Blades", "5 Blades", "10 Blades")) == []
    assert element_groups(("Fire", "Cold")) == []  # two of three elements is not a random group
    assert main_skill_of({"skills_state": {"main_socket_group_id": "g1", "socket_groups": [
        {"socket_group_id": "g0", "active_skill_entries": [{"name": "Wrong", "part_index": 2}]},
        {"socket_group_id": "g1", "active_skill_entries": [{"name": "Elemental Hit", "part_index": 3}]}]}}) == ("Elemental Hit", 3)


@needs_skill_data
def test_only_random_element_skills_are_averaged_and_only_inside_their_group() -> None:
    assert skill_facts.part_names("ElementalHit") == ("Fire Attack", "Fire AoE", "Cold Attack", "Cold AoE", "Lightning Attack", "Lightning AoE")
    assert skill_facts.part_names("BladeVortex") == ("0 Blades", "5 Blades", "10 Blades") and skill_facts.part_names("Cyclone") == ()
    assert random_element_groups("Elemental Hit") == [(1, 3, 5), (2, 4, 6)]
    assert mean_parts_for("Elemental Hit", None) == (1, 3, 5) and mean_parts_for("Elemental Hit", 4) == (2, 4, 6)
    assert mean_parts_for("Wild Strike", 5) == (1, 3, 5) and mean_parts_for("Wild Strike", 2) is None  # a secondary stays single
    assert mean_parts_for("Blade Vortex", 2) is None  # a stacked state, not a random element
    assert mean_parts_for("Elemental Hit of the Spectrum", 1) is None  # PoB's parts are Attack / AoE Explosion: no element parts


@pytest.mark.pob
@needs_pob
def test_readbacks_and_fast_trials_average_the_parts_and_leave_the_build_alone(tmp_path: Path) -> None:
    from junkroan.optimizer.random_parts import apply_mean_parts
    from junkroan.pob.session import PobSession

    code = Path(next(iter(glob.glob(str(PROJECT_ROOT / "tests" / "fixtures" / "**" / "elemental_hit.pob.txt"), recursive=True)))).read_text(encoding="utf-8").strip()
    keys = ["CombinedDPS", "Life", "MainHand.FireHitAverage", "MainHand.ColdHitAverage", "MainHand.LightningHitAverage"]
    with PobSession(run_id="test-random-parts", artifacts_root=tmp_path) as pob:
        pob.load_import_code(code)
        assert main_skill_of(pob.read_state()) == ("Elemental Hit", 1)
        per_part = {}
        for part in (1, 3, 5):
            pob.mean_parts = (part,)
            per_part[part] = pob.stats(keys)
        # the author's Elemental Hit (Tuadh): each part carries its own element only
        assert per_part[1]["MainHand.FireHitAverage"] > 0 and per_part[1]["MainHand.ColdHitAverage"] == 0
        assert per_part[3]["MainHand.ColdHitAverage"] > 0 and per_part[5]["MainHand.LightningHitAverage"] > 0
        assert len({round(per_part[p]["CombinedDPS"]) for p in per_part}) == 3
        assert apply_mean_parts(pob) == (1, 3, 5)
        mean = pob.stats(keys)
        for key in ("CombinedDPS", "MainHand.FireHitAverage"):
            assert abs(mean[key] - sum(per_part[p][key] for p in per_part) / 3) < 1e-6
        assert mean["Life"] == per_part[1]["Life"]
        trial = pob.trial_stats([{"add": []}], ["CombinedDPS", "Life"], mode="fast")[0]
        assert trial["ok"] and abs(trial["stats"]["CombinedDPS"] - mean["CombinedDPS"]) < 1e-6 and trial["stats"]["Life"] == mean["Life"]
        assert main_skill_of(pob.read_state()) == ("Elemental Hit", 1)  # the selected part is restored every time
        pob.mean_parts = None
        assert abs(pob.stats(keys)["CombinedDPS"] - per_part[1]["CombinedDPS"]) < 1e-6
