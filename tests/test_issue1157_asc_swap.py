"""#1157 unit 2: the `ascendancy-swap` loop move swaps a dead ascendancy node for a better reachable one.

PoB-free: a fake session holds the real Inquisitor ascendancy graph (ids from `ascendancies.json`) and gives every
node a worth in fractions of CombinedDPS. The move runs inside the real `ImprovementLoop` (tests/loop_fakes.py).

Inquisitor, start 61871. Branches: 43193 -> 19417 Instruments of Virtue -> 27055 -> 13851 Zeal, and 19417 -> 35739 ->
3154 Justice; 662 -> 53884 -> 37486 -> 48214 Inevitable Judgement; 10635 -> 39790 Sanctuary -> 57222 -> 32816 Pious
Path; 60769 -> 40059 Augury of Penitence.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from junkroan.optimizer.improvement_loop import LOOP_MOVES, LoopPlan
from junkroan.optimizer.snapshot import SKELETON_WHOLE, Snapshotter
from junkroan.optimizer.trace import TRACE, classify
from junkroan.optimizer.tree_graph import CORPUS_ROOT
from junkroan.optimizer.tree_hygiene import ascendancy_swap_candidates

from loop_fakes import _Loot, _Pob, _Tree, loop_over

START = 61871
VIRTUE, ZEAL, JUSTICE, INEVITABLE, SANCTUARY, PIOUS, AUGURY = 19417, 13851, 3154, 48214, 39790, 32816, 40059


def _inquisitor() -> dict:
    recs = json.loads((CORPUS_ROOT / "ascendancies.json").read_text(encoding="utf-8"))["records"]
    return next(r for r in recs if r["ascendancy_id"] == "Inquisitor")


PARENT = {int(n["node_id"]): int(n["incoming_node_ids"][0]) for n in _inquisitor()["nodes"] if not n.get("is_ascendancy_start")}


def _chain(node: int) -> list[int]:
    out = []
    while node != START:
        out.append(node)
        node = PARENT[node]
    return out


class _AscPob(_Pob):
    """The real Inquisitor graph; PoB's removal cascades to the nodes a removed node holds up, PoB's AllocNode brings the
    path. CombinedDPS = 1000 * (1 + sum of the allocated nodes' worth) + whatever a refine added to `value`."""

    def __init__(self, allocated, worth, *, calls=None) -> None:
        super().__init__(1000.0, calls=calls)
        self.allocated, self.worth = set(allocated), dict(worth)
        self.trial_calls: list[tuple[list, str]] = []
        self.mutate_calls: list[tuple[list, list]] = []

    def _stats(self, alloc, keys):
        dps = (1 + sum(self.worth.get(n, 0.0) for n in alloc)) * self.value
        return {k: 0 for k in keys} | {"CombinedDPS": dps, "Life": self.life, "TotalEHP": 5000.0}

    def stats(self, keys):
        return self._stats(self.allocated, keys)

    def tree_light(self) -> dict:
        self.calls.append(("tree_light",))
        return {"class_id": "Templar", "user_allocated_node_ids": sorted(self.allocated), "mastery_effect_ids": []}

    def _simulate(self, remove, add) -> set[int]:
        alloc = set(self.allocated)
        for node in remove:
            alloc -= {n for n in alloc if node in _chain(n)}
        for node in add:
            alloc |= set(_chain(node))
        return alloc

    def trial_stats(self, trials, keys, mode="fast"):
        self.trial_calls.append((list(trials), mode))
        out = []
        for trial in trials:
            TRACE.count_trial({"add": list(trial.get("add", ())), "remove": list(trial.get("remove", ()))})  # what the session does
            new = self._simulate(trial.get("remove", ()), trial.get("add", ()))
            out.append({"ok": True, "error": None, "added_node_ids": sorted(new - self.allocated),
                        "removed_node_ids": sorted(self.allocated - new), "stats": self._stats(new, keys)})
        return out

    def mutate_nodes(self, remove=None, add=None, mastery_effects=None):
        self.mutate_calls.append((list(remove or ()), list(add or ())))
        new = self._simulate(remove or (), add or ())
        added, removed = sorted(new - self.allocated), sorted(self.allocated - new)
        self.allocated = new
        return {"allocated_node_ids": sorted(new), "added_node_ids": added, "removed_node_ids": removed, "points_used": len(new)}

    def export_xml(self) -> str:
        token = f"xml{len(self._snapshots) + 1}"
        self._snapshots[token] = (self.value, self.life, frozenset(self.allocated))
        return token

    def load_xml(self, token: str) -> None:
        self.value, self.life, alloc = self._snapshots[token]
        self.allocated = set(alloc)


class _OverpromisingPob(_AscPob):
    """A trial that reads better than the swap really is: the real measurement after the swap refuses it."""

    def trial_stats(self, trials, keys, mode="fast"):
        out = super().trial_stats(trials, keys, mode)
        for trial, one in zip(trials, out):
            if trial.get("add"):
                one["stats"] = {**one["stats"], "CombinedDPS": one["stats"]["CombinedDPS"] * 1.5}  # only the swap trials; the audit's removals stay true
        return out


def _run(allocated, worth, *, forced=(), refine=(), passes=1, moves=("ascendancy-swap",), pob_class=_AscPob):
    TRACE.reset()
    pob = pob_class(allocated, worth)
    skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=sorted(allocated),
                               forced_ascendancy_nodes=list(forced), main_link=["Fireball"], rare_bases={}, uniques={},
                               sockets={}, extra_groups=[])
    tree = _Tree(pob, list(refine))
    rig = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=skeleton)
    rig.ascendancy_points = len(allocated)
    outcome = rig.run(LoopPlan(seed=1, max_passes=passes, max_seconds=None, min_gain=0.005, kind="replay", moves=frozenset(moves)))
    return pob, skeleton, tree, rig, outcome


def _counts() -> dict:
    return TRACE.considered().get("ascendancy-swap", {}).get("ascendancy-swap", {"generated": 0, "evaluated": 0})


def test_the_move_is_a_loop_move() -> None:
    assert "ascendancy-swap" in LOOP_MOVES


def test_a_dead_notable_is_swapped_for_a_better_reachable_node() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, 60769: 0.01, AUGURY: 0.10}  # Virtue is worth nothing; Augury is one point behind 60769
    pob, skeleton, tree, rig, _ = _run(allocated, worth)
    assert pob.allocated == {43193, 60769, AUGURY}
    assert pob.mutate_calls == [([VIRTUE], [AUGURY])]  # a swap of two nodes, never a rebuild of the tree
    assert skeleton.ascendancy_nodes == sorted({43193, 60769, AUGURY})
    assert tree.build_changes == 1
    row = [m for m in rig.result.moves if m["move"] == "ascendancy-swap"][-1]
    assert row["kept"] and row["after"] > row["before"]
    counts = _counts()
    assert counts["generated"] > 0 and counts["evaluated"] == counts["generated"]


def test_the_best_of_several_reachable_nodes_is_kept_and_a_costlier_one_never_is() -> None:
    allocated = {43193, VIRTUE, 60769, 10635}
    worth = {43193: 0.01, 60769: 0.01, 10635: 0.01, AUGURY: 0.10, SANCTUARY: 0.05, PIOUS: 0.50}  # Pious Path needs 3 points, one is freed
    pob, skeleton, _tree, _rig, _ = _run(allocated, worth)
    assert pob.allocated == {43193, 60769, 10635, AUGURY}
    assert len(pob.allocated) <= 4  # the points after the swap never exceed the points before
    tried = {t["add"][0] for trials, _mode in pob.trial_calls for t in trials if t.get("add")}
    assert {AUGURY, SANCTUARY, PIOUS} <= tried  # every other pick of the ascendancy was measured, the costly one included


def test_no_better_node_changes_nothing() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, 60769: 0.01, AUGURY: 0.0, SANCTUARY: -0.2}
    pob, skeleton, tree, rig, _ = _run(allocated, worth)
    assert pob.allocated == allocated and pob.mutate_calls == []
    assert skeleton.ascendancy_nodes == sorted(allocated)
    assert getattr(tree, "build_changes", 0) == 0
    assert not [m for m in rig.result.moves if m["move"] == "ascendancy-swap"][-1]["kept"]
    counts = _counts()
    assert counts["generated"] > 0 and counts["evaluated"] > 0


def test_a_swap_the_real_measurement_refuses_is_put_back() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, 60769: 0.01, AUGURY: 0.0}
    pob, skeleton, tree, rig, _ = _run(allocated, worth, pob_class=_OverpromisingPob)
    assert pob.mutate_calls == [([VIRTUE], [AUGURY])]  # tried ...
    assert pob.allocated == allocated and skeleton.ascendancy_nodes == sorted(allocated)  # ... and rolled back
    row = [m for m in rig.result.moves if m["move"] == "ascendancy-swap"][-1]
    assert not row["kept"] and row["reverted_by_judge"]


def test_no_dead_node_generates_nothing() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, VIRTUE: 0.02, 60769: 0.01, AUGURY: 0.10}
    pob, _skeleton, _tree, _rig, _ = _run(allocated, worth)
    assert pob.allocated == allocated
    assert _counts() == {"generated": 0, "evaluated": 0}
    assert not [t for trials, _mode in pob.trial_calls for t in trials if t.get("add")]


def test_two_dead_nodes_are_swapped_in_one_pass() -> None:
    allocated = {43193, VIRTUE, 60769, 662, 53884, 37486, INEVITABLE, 10635}
    worth = {43193: 0.01, 60769: 0.01, 662: 0.01, 53884: 0.01, 37486: 0.01, 10635: 0.01, AUGURY: 0.10, SANCTUARY: 0.08}
    pob, skeleton, _tree, rig, _ = _run(allocated, worth)
    assert pob.allocated == {43193, 60769, AUGURY, 662, 53884, 37486, 10635, SANCTUARY}
    assert [(r, a) for r, a in pob.mutate_calls] == [([VIRTUE], [AUGURY]), ([INEVITABLE], [SANCTUARY])]
    assert skeleton.ascendancy_nodes == sorted(pob.allocated)


def test_a_node_the_request_named_is_never_swapped_out() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, 60769: 0.01, AUGURY: 0.10}
    pob, skeleton, _tree, _rig, _ = _run(allocated, worth, forced=[VIRTUE])
    assert pob.allocated == allocated and pob.mutate_calls == []
    assert not [t for trials, _mode in pob.trial_calls for t in trials if t.get("add")]


def test_a_second_pass_measures_the_audit_again() -> None:
    allocated = {43193, VIRTUE, 60769}
    worth = {43193: 0.01, 60769: 0.01, AUGURY: 0.0}  # nothing better: the first run is clean
    one, *_ = _run(allocated, worth, refine=[1100.0], passes=1, moves=("refine", "ascendancy-swap"))
    two, *_ = _run(allocated, worth, refine=[1100.0], passes=2, moves=("refine", "ascendancy-swap"))
    assert len(one.trial_calls) > 0
    assert len(two.trial_calls) == 2 * len(one.trial_calls)  # no memo of a "clean" build: gems and lanes the tree fingerprint does not hold can turn a node dead or alive


class _GemTree(_Tree):
    """The second refine also changes the gems (a channelling skill is picked): the tree and the gear stay as they were."""

    def __init__(self, pob, values, skeleton) -> None:
        super().__init__(pob, values)
        self.skeleton = skeleton

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        out = super().refine(max_rounds=max_rounds, repair_rounds=repair_rounds)
        if self.pob.value > 1100.0:  # the second pass's refine
            self.skeleton.main_link = ["Contagion"]
            self.pob.worth[AUGURY] = 0.10  # Augury counts only with the new skill
        return out


def test_a_gem_change_between_two_passes_makes_the_second_pass_swap() -> None:
    allocated = {43193, VIRTUE, 60769}
    TRACE.reset()
    pob = _AscPob(allocated, {43193: 0.01, 60769: 0.01, AUGURY: 0.0})
    skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=sorted(allocated),
                               forced_ascendancy_nodes=[], main_link=["Fireball"], rare_bases={}, uniques={}, sockets={}, extra_groups=[])
    rig = loop_over(pob, tree=_GemTree(pob, [1100.0, 1200.0], skeleton), gear=_Loot(pob, {}), skeleton=skeleton)
    rig.ascendancy_points = len(allocated)
    rig.run(LoopPlan(seed=1, max_passes=2, max_seconds=None, min_gain=0.005, kind="replay", moves=frozenset(("refine", "ascendancy-swap"))))
    assert pob.mutate_calls == [([VIRTUE], [AUGURY])]  # pass 1 measured and found nothing; pass 2 measured again and swapped
    assert pob.allocated == {43193, 60769, AUGURY}


class _SynergyPob(_AscPob):
    """Inevitable Judgement is worth 20 % only next to Augury of Penitence."""

    def _stats(self, alloc, keys):
        out = super()._stats(alloc, keys)
        if AUGURY in alloc and INEVITABLE in alloc:
            out["CombinedDPS"] += 0.2 * self.value
        return out


def test_the_dead_list_is_measured_again_after_a_kept_swap() -> None:
    allocated = {43193, VIRTUE, 60769, 662, 53884, 37486, INEVITABLE, 10635}
    worth = {43193: 0.01, 60769: 0.01, 662: 0.01, 53884: 0.01, 37486: 0.01, 10635: 0.01, AUGURY: 0.10, SANCTUARY: 0.08}
    pob, _skeleton, _tree, _rig, _ = _run(allocated, worth, pob_class=_SynergyPob)
    # Inevitable Judgement is dead at first; once Augury stands it is worth 20 %, so it is not swapped out on the old list
    assert pob.mutate_calls == [([VIRTUE], [AUGURY])]
    assert INEVITABLE in pob.allocated
    swap_trials = [t for trials, _mode in pob.trial_calls for t in trials if t.get("add")]
    assert {tuple(t["remove"]) for t in swap_trials} == {(VIRTUE,)}  # no swap trial for the node the first swap made alive
    audits = [trials for trials, _mode in pob.trial_calls if not any(t.get("add") for t in trials)]
    assert len(audits) == 2  # the audit before the first swap and the audit after it


def test_a_revert_to_a_build_before_the_swap_takes_the_ascendancy_nodes_back_with_the_tree() -> None:
    """Every whole-build revert (a kick's, the fixed-point entry's, the final repair's) takes the whole Skeleton with the XML
    (`skeleton=True` / `SKELETON_WHOLE`), so `ascendancy_nodes` goes back with the tree that `pipeline.py` rebuilds from it."""

    allocated = {43193, VIRTUE, 60769}
    for scope in (True, SKELETON_WHOLE):
        TRACE.reset()
        pob = _AscPob(allocated, {43193: 0.01, 60769: 0.01, AUGURY: 0.10})
        skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=sorted(allocated),
                                   forced_ascendancy_nodes=[], main_link=["Fireball"], rare_bases={}, uniques={}, sockets={}, extra_groups=[],
                                   tuned_choices={})
        tree = _Tree(pob, [])
        rig = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=skeleton)
        rig.ascendancy_points = len(allocated)
        shots = Snapshotter(pob=pob, skeleton=skeleton, filler=None, judging=rig.judging, trees=lambda: (tree,))
        before = shots.take(xml=True, skeleton=scope)
        rig.run(LoopPlan(seed=1, max_passes=1, max_seconds=None, min_gain=0.005, kind="replay", moves=frozenset(("ascendancy-swap",))))
        assert skeleton.ascendancy_nodes == sorted({43193, 60769, AUGURY}) and AUGURY in pob.allocated  # the swap was kept
        shots.restore(before)
        assert pob.allocated == allocated
        assert skeleton.ascendancy_nodes == sorted(allocated)


def test_candidates_are_the_picks_of_the_same_ascendancy_not_yet_allocated() -> None:
    cands = ascendancy_swap_candidates(VIRTUE, {43193, VIRTUE, 60769})
    assert VIRTUE not in cands and 43193 not in cands and 60769 not in cands
    assert all(n in PARENT for n in cands)  # every one is a node of the Inquisitor
    assert START not in cands
    assert {JUSTICE, ZEAL, INEVITABLE, SANCTUARY, PIOUS, AUGURY} <= set(cands)


def test_the_trace_class_marks_a_trial_that_adds_an_ascendancy_node() -> None:
    assert "ascendancy-swap" in classify({"remove": [VIRTUE], "add": [AUGURY]})
    assert "ascendancy-swap" not in classify({"remove": [VIRTUE]})  # the audit's own removal trial
    assert "ascendancy-swap" not in classify({"add": [1]})  # a passive node
