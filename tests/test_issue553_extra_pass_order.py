"""#553 unit 9 (D116): `_finish`'s fixed-point extra pass keeps the floors order, the improvement loop proper the priced one (no PoB).

Floor Life >= 4000 (`FLOORED`). Entry: 1.0e6 CombinedDPS at Life 5000 (violation 0). A Boots roll gives 1.1e6 at Life 3800
(violation 0.05, priced 1.1e6 * 0.95 = 1.045e6): the priced order keeps it, the floors order refuses it."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from junkroan.optimizer.improvement_loop import LoopPlan  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402

from loop_fakes import _Loot, _Pob, _Tree, _finish_pipeline, _finish_skeleton, _patch_generator, _skeleton, loop_over  # noqa: E402

ENTRY, ROLL = 1.0e6, 1.1e6
ROLL_LIFE = 3800.0


def test_the_plans_order_is_priced_for_the_loop_and_floors_for_the_extra_pass() -> None:
    plan = LoopPlan(seed=1, max_passes=1, max_seconds=60.0)
    assert plan.order == "priced" and plan.extra_pass().order == "floors"
    assert LoopPlan.replay("loop", seed=1, passes=1).order == "priced"


def test_the_extra_pass_refuses_a_move_that_raises_violation_and_the_entry_is_kept(monkeypatch) -> None:
    pob = _Pob(ENTRY)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Boots": [("boots-roll", ROLL, ROLL_LIFE)]})
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    _patch_generator(monkeypatch, [])
    p.judging.attach("gear", loot)
    p._take_picks = lambda *_a, **_k: None
    p._tune_lanes = lambda _sk, *, identity=False: {}
    sk = _finish_skeleton()
    sk.rare_bases = {"Boots": "Two-Toned Boots"}

    result = p._finish(BuildResult(skeleton=sk), sk, 0.0,
                       fixed_point=dict(loot=loot, tree=tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0))

    assert [c for c in loot.calls if c[0] == "fill_slot"], "the extra pass must have tried the Boots roll"
    assert pob.value == ENTRY and pob.life == 5000.0  # the roll was refused (or, were it kept, a revert would also read this)
    assert not any("final tuning reverted" in m for m in logs)
    assert result.fixed_point_note == "kept nothing" and result.fixed_point_gain == 0.0
    assert "final feasibility: ok" in logs


def test_the_loop_proper_keeps_the_priced_move(monkeypatch) -> None:
    pob = _Pob(ENTRY)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Boots": [("boots-roll", ROLL, ROLL_LIFE)]})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=_skeleton({"Boots": "Two-Toned Boots"}))
    p.started()

    outcome = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert pob.value == ROLL and pob.life == ROLL_LIFE  # 1.0e6 (viol 0) -> 1.1e6 (viol 0.05): priced 1.045e6, kept
    assert outcome.counts["kept"] >= 1
