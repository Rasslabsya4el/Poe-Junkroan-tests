"""#569: the improvement loop's moves stop on counts; the loop's own clock is only a safety net. PoB-free."""

import time as real_time
from types import SimpleNamespace

from junkroan.optimizer.improvement_loop import LoopPlan

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

ALL_TREE_MOVES = frozenset({"refine", "swaps", "corridors", "regions"})


def _jumping_clock(step: float = 60.0):
    now = [0.0]

    def perf_counter() -> float:
        now[0] += step
        return now[0]

    return SimpleNamespace(perf_counter=perf_counter)


def _rig(monkeypatch, *, calls=None, logs=None):
    pob = _Pob(1000.0, calls=calls)
    tree = _Tree(pob, [1100.0, 1150.0, 1160.0], swap_values=[1200.0], corridor_values=[1210.0], region_values=[1300.0], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=tree, gear=loot, skeleton=_skeleton({}, main_link=("Fireball",)), calls=calls,
                    log=(logs.append if logs is not None else None))
    return pob, tree, rig


def _run(monkeypatch, *, clock, max_seconds=None, max_passes=4):
    calls: list = []
    logs: list = []
    if clock is not None:
        monkeypatch.setattr("junkroan.optimizer.improvement_loop.time", clock)
        monkeypatch.setattr("junkroan.optimizer.tree_optimizer.time", clock)
    pob, _tree, rig = _rig(monkeypatch, calls=calls, logs=logs)
    outcome = rig.run(LoopPlan(seed=1, max_passes=max_passes, max_seconds=max_seconds, min_gain=0.005, loot_n=5, moves=ALL_TREE_MOVES))
    return outcome, calls, logs, pob.value


def test_the_clock_does_not_change_the_moves(monkeypatch) -> None:
    real = _run(monkeypatch, clock=SimpleNamespace(perf_counter=real_time.perf_counter))
    slow = _run(monkeypatch, clock=_jumping_clock())

    assert real[0].passes == slow[0].passes and real[0].stopped == slow[0].stopped == ""
    assert real[0].counts == slow[0].counts
    assert real[1] == slow[1] and real[3] == slow[3]
    assert any(c[0] == "swap_subtrees" for c in real[1])


def test_the_loop_passes_counts_only_to_the_tree(monkeypatch) -> None:
    seen: dict[str, list] = {"swaps": [], "corridors": [], "regions": []}
    pob, tree, rig = _rig(monkeypatch)
    for name, attr in (("swaps", "swap_subtrees"), ("corridors", "exchange_corridors"), ("regions", "challenge_regions")):
        original = getattr(tree, attr)

        def spy(*, _o=original, _n=name, **kwargs):
            seen[_n].append(kwargs)
            return _o(**kwargs)

        setattr(tree, attr, spy)
    rig.run(LoopPlan(seed=1, max_passes=1, max_seconds=7200.0, min_gain=0.005, loot_n=5, moves=ALL_TREE_MOVES))

    assert seen["swaps"] and all(k["max_size"] == 6 and k["max_seconds"] is None and k["max_candidates"] is None for k in seen["swaps"])
    assert seen["corridors"] and all(k["max_seconds"] is None for k in seen["corridors"])
    assert seen["regions"] and all(k["max_seconds"] is None for k in seen["regions"])


def test_the_safety_net_stops_the_loop_and_says_so(monkeypatch) -> None:
    outcome, _calls, logs, _value = _run(monkeypatch, clock=_jumping_clock(), max_seconds=100.0)

    assert outcome.stopped == "time budget"
    assert "stopped: time budget" in outcome.note
    net = [line for line in logs if line.startswith("loop: safety net ")]
    assert len(net) == 1 and net[0].endswith(" reached after pass 1"), logs
