"""ROADMAP 7.1c: the improvement loop's keep/revert rules, without PoB.

The build is two numbers here (the maximized stat and one floored stat): a snapshot
remembers them and `load_xml` puts them back, so an unfaithful revert would show up as
the "no change" invariant of `_record`.
"""

from types import SimpleNamespace

import pytest

from junkroan.optimizer.judging import tune_choices, write_lanes
from junkroan.optimizer.castability import MANA_COST_POOL_STAT
from junkroan.optimizer.improvement_loop import FIXED_POINT_SEED_OFFSET, LoopFlags, LoopOutcome, LoopPlan
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult, loop_stop_label
from junkroan.optimizer.seeds import (
    PURPOSE_HEADROOM_ROLLS,
    PURPOSE_HEADROOM_SLOTS,
    PURPOSE_JOINT_KICK_RNG,
    PURPOSE_JOINT_FILL_SLOT,
    PURPOSE_LOOP_FILL_SLOT,
    PURPOSE_TREE_KICK,
    derive_seed,
)
from junkroan.optimizer.tree_optimizer import Step
from junkroan.pob.headless_runtime_worker import WorkerContractError
from junkroan.pob.host_runtime import PoBHeadlessHostContractError

from judging_fakes import pob_judging
from loop_fakes import FLOORED, _Loot, _TemplateLoot, _Pob, _Tree, _finish_pipeline, _finish_skeleton, _patch_generator, _skeleton, loop_over


def _pipeline(pob: _Pob, reconfigures: list, *, calls: list | None = None) -> BuildPipeline:
    """A `BuildPipeline` (via `__new__`) for the tests of its non-loop methods (`_fixed_point_check`, `_guarded_step`):
    the loop itself runs through `loop_over` and `LoopRig.run`."""

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p.rails = SimpleNamespace(gear=SimpleNamespace(loot_best_of_n=200, item_level=86, quality=20), ascendancy_points=None)  # #1157: no ascendancy-swap in these plans
    p.log = lambda _m: None
    p.judging = pob_judging(p)
    p.objective = FLOORED

    def reconfigure(_sk) -> None:
        reconfigures.append(1)
        if calls is not None:
            calls.append(("reconfigure",))

    # the loop re-judges through its judging context: `rejudge(skeleton)`, or through the generator's
    # port `rejudge(skeleton, castability=...)`
    p.judging.rejudge = lambda sk, **_kwargs: reconfigure(sk)
    p._take_picks = lambda *_a, **_k: None

    def tune_lanes(sk, *, identity: bool = False) -> dict:
        if calls is not None:
            calls.append(("tune_lanes", identity))
        reconfigure(sk)  # the real one ends in a reconfigure, which is what makes the lanes fresh (D60)
        return {}

    p._tune_lanes = tune_lanes  # the choices and the identity are PoB's judgement: stubbed here (D60)
    joint_round = p._joint_round

    def joint_round_attached(sk, loot, tree, *args, **kwargs):
        p.judging.attach("gear", loot)
        p.judging.attach("tree", tree)
        return joint_round(sk, loot, tree, *args, **kwargs)

    p._joint_round = joint_round_attached
    return p


def _started(p: BuildPipeline, sk) -> BuildResult:
    result = BuildResult(skeleton=sk)
    p._record(result, "tree rebuilt on gear", 0.0)  # the stage the loop follows: the baseline of the invariant
    return result


def test_a_pass_that_keeps_nothing_is_the_fixed_point(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [1001.0])  # +0.1%, below min_gain
    loot = _Loot(pob, {"Gloves": [("g1", 1002.0)], "Boots": [("b1", 1003.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    sweeps = _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "loop pass 1"]
    assert result.stages[-1].notes == "no change"
    assert "fixed point after 1 pass" in note and "0 moves kept" in note
    assert len(pob.loaded) == 4  # refine, swaps and both slots reverted; the 7 kick draws changed nothing and were skipped (7.1h)
    assert pob.equipped[:2] == [{"Gloves": None}, {"Boots": None}]  # RARE_SLOT_ORDER (this skeleton has no weapon slot)
    assert pob.equipped[2] == {"Boots": None, "Gloves": None}  # the kick joint empties two slots at once
    assert [c for c in tree.calls if c[0] == "reoptimize"] == [("reoptimize", 1, 20, 10, derive_seed(1, PURPOSE_TREE_KICK, 1, d)) for d in range(3)]
    assert pob.value == 1000.0 and loot.current_raw == {} and sweeps == [1]


def test_the_loop_hands_its_own_loot_n_to_every_slot_re_roll() -> None:
    """The construction rolls draw `gear.construction_best_of_n` (600 since 2026-09-18); the loop's
    per-slot re-rolls are untouched -- they pass the `loot_n` the run was given (None on a normal
    run, which `LootGear.fill_slot` resolves to `gear.loot_best_of_n` = 200)."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=None))

    re_rolls = [c for c in calls if c[0] == "fill_slot"]
    assert re_rolls and {c[3] for c in re_rolls} == {None}  # never 600, and never a number of the loop's own


def test_the_per_slot_moves_walk_the_weapon_slots_first() -> None:
    """A gear move empties the slot it re-rolls, and an attack build with an empty weapon slot
    has no number at all, so every later slot would be judged blind. The loop iterates the slots
    in the fillers' own order (`ordered_slots`): weapons, then the rest as before."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots", "Body Armour": "Simple Robe", "Weapon 2": "Serrated Arrow Quiver",
                    "Weapon 1": "Short Bow"}, main_link=("Puncture",))  # no support: the picks move is skipped
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=None))

    walked = [c[1] for c in calls if c[0] == "fill_slot"]
    assert walked[:4] == ["Weapon 1", "Weapon 2", "Body Armour", "Boots"]  # the rest are the kicks' own slots


def test_a_gear_move_over_min_gain_is_kept_and_a_small_one_is_reverted(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])  # the tree never moves the number
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)], "Boots": [("b1", 1022.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "loop pass 1", "loop pass 2"]
    assert result.stages[1].notes == "Gloves +2.0%" and result.stages[2].notes == "no change"
    assert "fixed point after 2 passes" in note and "1 moves kept" in note
    assert "xml4" not in pob.loaded  # the kept Gloves snapshot was never loaded back (xml1 is opening lanes)
    assert loot.current_raw == {"Gloves": "g1"}  # Boots (+0.2%) restored to what it was: nothing
    assert pob.value == 1020.0


def test_max_passes_stops_the_loop_and_says_so(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])
    loot = _Loot(pob, {})
    sk = _skeleton({})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[-1].notes == "refine +10.0%; stopped: max passes (1)"
    assert "stopped: max passes (1)" in note and "1 moves kept" in note
    assert [s.name for s in result.stages].count("loop pass 1") == 1


def test_the_incumbent_winning_its_slot_is_not_a_move(monkeypatch) -> None:
    pob = _Pob(1000.0)
    reconfigures: list = []
    tree = _Tree(pob, [1100.0], [1210.0])  # both tree moves kept, so the pass is not empty for another reason
    loot = _Loot(pob, {})
    loot.current_raw["Boots"] = "b0"
    sk = _skeleton({"Boots": "Two-Toned Boots"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, reconfigures=reconfigures)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert pob.loaded == []  # nothing reverted: both tree moves were kept and the slot never changed
    # lanes re-derived for each kept tree move, and not for the incumbent; the opening tuning and the
    # lanes step closing a pass that kept a move derive once each too (D60)
    assert len(reconfigures) == 4
    assert loot.current_raw == {"Boots": "b0"} and pob.equipped == [{"Boots": None}]
    assert result.stages[-1].notes.startswith("refine +10.0%; swaps +10.0%") and "2 moves kept" in note


def test_a_re_judged_pick_is_a_kept_move_with_its_gain(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {})
    sk = _skeleton({})

    class _Gen:  # rejudge_picks keeps its own swap: it leaves the build at the new number
        def __init__(self, pob, rails, *, objective=None, log=None, castability_context=None, castability_metrics=None) -> None:
            self.pob, self.picks = pob, ()

        def rejudge_picks(self, skeleton, *, reconfigure=None, min_gain=0.005, max_sweeps=3, order="floors"):
            if self.pob.value >= 1030.0:
                return []
            self.pob.value = 1030.0
            return [{"what": "support", "was": "Immolate", "now": "Trinity", "before": 1000.0, "after": 1030.0}]

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=3, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[1].notes == "picks: support Immolate -> Trinity (+3.0%)"
    assert result.stages[2].notes == "no change"
    assert "fixed point after 2 passes" in note and "1 moves kept" in note


def test_refine_kept_and_path_swaps_reverted_are_two_moves() -> None:
    """The bad end state of the swaps must not take the refine with it (the 7.1c smoke run)."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])  # refine +10%, the swaps leave it where they found it
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[-1].notes == "refine +10.0%; stopped: max passes (1)"
    assert len(pob.loaded) == 1 and pob.value == 1100.0  # only the swaps were reverted
    assert "1 moves kept" in note


def test_move_ledger_accounts_for_kept_reverted_and_dropped_moves(monkeypatch) -> None:
    """The construction value plus kept gains reaches the state `_finish` receives.

    This is the ledger's accounting identity: judged reverts and contract-dropped
    moves are present, but neither gets to change the summed value.
    """

    class _DroppingLoot(_Loot):
        def fill_slot(self, *args, **kwargs):
            raise WorkerContractError("bad_payload", "gear payload rejected")

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])  # refine is kept; path swaps are judged and reverted
    loot = _DroppingLoot(pob, {})
    sk = _finish_skeleton()
    sk.rare_bases = {"Boots": "Two-Toned Boots"}
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()
    _patch_generator(monkeypatch, [])

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))
    p, _derived, _logs = _finish_pipeline(monkeypatch, pob, tree, {})
    p._finish(result, sk, 0.0)

    assert any(move["move"] == "refine" and move["kept"] for move in result.moves)
    assert any(move["move"] == "path swaps" and move["reverted_by_judge"] for move in result.moves)
    assert any(move["move"] == "gear Boots" and not move["kept"] for move in result.moves)
    assert result.dropped_moves and result.dropped_moves[0]["move"] == "loop pass 1 Boots"
    assert result.ledger_construction_value == 1000.0
    assert result.ledger_value_before_final_lanes == 1100.0
    assert result.ledger_identity_error == pytest.approx(0.0, abs=1e-6)


def test_the_default_plan_runs_neither_trunk_move() -> None:
    """The corridor exchange (a bypass for 79 of 2,583 corridors on 96 builds, 2 exchanges kept) and
    the region challenge (kept something on 11 of 180 builds in real loops, 0.6% of the loop's gain
    for 5.7% of its time, 2026-09-22) are out of the default plan and reachable only when `moves`
    names them (the replay bench)."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], calls=calls, corridor_values=[9999.0], region_values=[1300.0])
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert [c[0] for c in calls if c[0] in ("exchange_corridors", "challenge_regions")] == []
    assert not [move for move in result.moves if move["move"] in ("corridors", "regions")]


_WITH_REGIONS = frozenset({"refine", "swaps", "regions"})  # the replay bench's way into the region challenge


def test_the_region_challenge_records_a_try_when_it_keeps_nothing_and_none_when_it_is_skipped() -> None:
    """A move that ran and kept nothing is a try the ledger must show the seconds of; a move the
    pass never reached (a cheaper tree move kept something) is not a try at all."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [], region_values=[])  # every tree move keeps nothing, the regions included
    p = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=_skeleton({}, main_link=("Fireball",)))
    result = p.started()
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=_WITH_REGIONS))
    ran = [move for move in result.moves if move["move"] == "regions"]
    assert len(ran) == 1 and not ran[0]["kept"] and ran[0]["before"] == ran[0]["after"]
    assert all(move["where"].startswith("loop ") for move in result.moves)  # not a re-entry's rows

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])  # refine keeps something, so the region challenge is never reached
    p = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=_skeleton({}, main_link=("Fireball",)))
    result = p.started()
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=_WITH_REGIONS))
    assert [move for move in result.moves if move["move"] == "regions"] == []


def test_a_pass_whose_cheaper_tree_moves_kept_nothing_runs_the_region_challenge() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], calls=calls, region_values=[1300.0])  # refine and swaps keep nothing
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=_WITH_REGIONS))

    assert result.stages[-1].notes == "regions +30.0%; stopped: max passes (1)"
    assert [c[0] for c in calls if c[0] == "challenge_regions"] == ["challenge_regions"]
    assert pob.value == 1300.0


def test_a_trunk_move_that_kept_nothing_is_not_judged_at_all() -> None:
    """The move puts back every attempt it did not keep, so the build is the one it started on:
    judging it would buy the number PoB already holds at the price of a lane derivation."""

    pob = _Pob(1000.0)
    reconfigures: list = []
    tree = _Tree(pob, [])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, reconfigures=reconfigures)
    result = p.started()

    # `opening_lanes=False` without a count budget is a combination no `LoopPlan` kind gives: the flags say it
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=frozenset({"corridors", "regions"})),
          flags=LoopFlags(local_only=False, opening_lanes=False, stage_name=None))  # as the replay bench calls it

    assert reconfigures == [], "a move that kept nothing must not pay for a lane derivation"
    assert pob.loaded == [] and pob.value == 1000.0


def test_the_replay_bench_can_ask_for_either_trunk_move_alone() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1500.0], swap_values=[1600.0], calls=calls, corridor_values=[1700.0], region_values=[1800.0])
    loot = _Loot(pob, {"Boots": [("b1", 1900.0)]}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=frozenset({"corridors"})))

    assert [c[0] for c in calls if c[0] in ("refine", "swap_subtrees", "exchange_corridors", "challenge_regions", "fill_slot")] == ["exchange_corridors"]
    assert pob.value == 1700.0


def test_a_judged_revert_keeps_the_optimizer_memory_a_dropped_move_does_not() -> None:
    """A move the judge measured and reverted leaves the build exactly where it started, so the
    verdicts measured on that same build still hold (`_rejected_subtrees` is keyed by the allocated
    set). Only a contract error -- where the build is not the one those answers were measured on --
    throws them away. v2 cleared them on every revert and winter_orb's passes 4 and 5 re-tried the
    identical five path-swap candidates for 97 s."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])  # refine kept, the swaps reverted
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    invalidations = [call for call in tree.calls if call[0] == "invalidate_after_recovery"]
    assert invalidations and all(keep for _name, keep in invalidations), "a judged revert keeps the memory"

    class _Exploding(_Tree):
        def swap_subtrees(self, *, max_size: float, max_seconds: float, max_candidates=None):
            raise WorkerContractError("calc", "worker died")

    pob = _Pob(1000.0)
    tree = _Exploding(pob, [1100.0])
    p = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    invalidations = [call for call in tree.calls if call[0] == "invalidate_after_recovery"]
    assert invalidations and not any(keep for _name, keep in invalidations), "a contract error clears the memory"


def test_a_rejected_path_batch_replays_the_true_swap_and_logs_the_false_one() -> None:
    """The replay starts from the batch snapshot, honours fresh lanes, and keeps only the true step."""

    class _ReplayPob(_Pob):
        def __init__(self) -> None:
            super().__init__(1000.0)
            self.nodes = {1, 2}
            self.config = {"usePowerCharges": True}
            self._snapshots: dict[str, tuple[float, float, set[int], dict[str, object]]] = {}

        def export_xml(self) -> str:
            token = f"xml{len(self._snapshots) + 1}"
            self._snapshots[token] = (self.value, self.life, set(self.nodes), dict(self.config))
            return token

        def load_xml(self, token: str) -> None:
            self.loaded.append(token)
            self.value, self.life, self.nodes, self.config = self._snapshots[token][0], self._snapshots[token][1], set(self._snapshots[token][2]), dict(self._snapshots[token][3])

        def config_inputs(self) -> dict:
            return dict(self.config)

        def mutate_nodes(self, remove=None, add=None, mastery_effects=None):
            del mastery_effects
            self.nodes.difference_update(remove or ())
            self.nodes.update(add or ())
            return {"removed_node_ids": list(remove or ()), "added_node_ids": list(add or ())}

    class _ReplayTree(_Tree):
        def __init__(self, pob: _ReplayPob) -> None:
            super().__init__(pob, [])
            self.graph = SimpleNamespace(node=lambda node_id: SimpleNamespace(name={1: "True old", 2: "False old", 3: "True new", 4: "False new"}.get(node_id, str(node_id))))
            self.steps = [
                Step(3, "true", "path", 1, [3], None, FLOORED.score({"CombinedDPS": 1000, "Life": 5000}), FLOORED.score({"CombinedDPS": 1020, "Life": 5000}), 1, 0.0, removed_node_ids=[1]),
                Step(4, "false", "path", 1, [4], None, FLOORED.score({"CombinedDPS": 1020, "Life": 5000}), FLOORED.score({"CombinedDPS": 1030, "Life": 5000}), 1, 0.0, removed_node_ids=[2]),
            ]

        def swap_subtrees(self, *, max_size: int, max_seconds: float, max_candidates=None):
            self.pob.nodes = {3, 4}
            self.pob.value = 1030.0  # frozen config says both swaps won
            self.history.extend(self.steps)
            return SimpleNamespace(steps=self.steps)

    pob = _ReplayPob()
    tree = _ReplayTree(pob)
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    logs: list[str] = []

    def reconfigure(_sk) -> None:
        pob.config["usePowerCharges"] = 4 not in pob.nodes
        pob.value = 1020.0 if pob.nodes == {2, 3} else (900.0 if 4 in pob.nodes else 1000.0)

    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    p.judging.rejudge = lambda sk_, **_kwargs: reconfigure(sk_)
    result = p.started()
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert pob.nodes == {2, 3} and pob.value == 1020.0
    assert [step.name for step in tree.history] == ["true"]
    assert any("replay: FALSE swap -1 [False old] -> +1 [False new]: 1,020 -> 900" in line for line in logs)
    assert any("usePowerCharges: True -> False" in line for line in logs)


def test_the_replay_labels_false_below_min_gain_and_a_step_that_lost_its_mutation() -> None:
    """Three verdicts, three names. FALSE is reserved for a step whose honest number is really
    lower (or whose lanes lost an input): a step that gains less than the loop's min_gain was a
    true verdict the acceptance rule refuses, and a step whose mutation is no longer on the tree
    because an earlier step was rejected never measured anything at all."""

    class _LabelPob(_Pob):
        def __init__(self) -> None:
            super().__init__(1000.0)
            self.nodes = {1, 2, 3}
            self._snapshots: dict[str, tuple[float, float, set[int]]] = {}

        def export_xml(self) -> str:
            token = f"xml{len(self._snapshots) + 1}"
            self._snapshots[token] = (self.value, self.life, set(self.nodes))
            return token

        def load_xml(self, token: str) -> None:
            self.loaded.append(token)
            self.value, self.life, self.nodes = self._snapshots[token][0], self._snapshots[token][1], set(self._snapshots[token][2])

        def config_inputs(self) -> dict:
            return {}

        def mutate_nodes(self, remove=None, add=None, mastery_effects=None):
            del mastery_effects
            gone = [node for node in (remove or ()) if node in self.nodes]
            self.nodes.difference_update(gone)
            self.nodes.update(add or ())
            return {"removed_node_ids": gone, "added_node_ids": list(add or ())}

    values = {
        frozenset({1, 2, 3}): 1000.0,
        frozenset({11, 2, 3}): 900.0,    # the first step is really worse under honest lanes
        frozenset({1, 2, 13}): 1002.0,   # the third gains +0.2%, under the 0.5% min_gain
        frozenset({2, 12, 13}): 700.0,   # the batch's own end state, which the judge rejects
    }

    class _LabelTree(_Tree):
        def __init__(self, pob: _LabelPob) -> None:
            super().__init__(pob, [])
            self.graph = SimpleNamespace(node=lambda node_id: SimpleNamespace(name=f"n{node_id}"))
            score = FLOORED.score({"CombinedDPS": 1000, "Life": 5000})
            self.steps = [
                Step(11, "false", "path", 1, [11], None, score, score, 1, 0.0, removed_node_ids=[1]),
                Step(12, "orphan", "path", 1, [12], None, score, score, 1, 0.0, removed_node_ids=[11]),
                Step(13, "small", "path", 1, [13], None, score, score, 1, 0.0, removed_node_ids=[3]),
            ]

        def swap_subtrees(self, *, max_size: int, max_seconds: float, max_candidates=None):
            self.pob.nodes = {2, 12, 13}
            self.pob.value = 2000.0  # the frozen config said the whole batch won
            self.history.extend(self.steps)
            return SimpleNamespace(steps=self.steps)

    pob = _LabelPob()
    tree = _LabelTree(pob)
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    logs: list[str] = []
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    p.judging.rejudge = lambda _sk, **_kwargs: setattr(pob, "value", values.get(frozenset(pob.nodes), 500.0))
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert any("replay: FALSE swap -1 [n1] -> +1 [n11]: 1,000 -> 900" in line for line in logs)
    assert any("replay: skipped: depends on a rejected step -1 [n11] -> +1 [n12]" in line for line in logs)
    assert any("replay: below min gain -1 [n3] -> +1 [n13]: 1,000 -> 1,002" in line for line in logs)
    assert not any("FALSE" in line and "n13" in line for line in logs), "a small true gain is not a false verdict"
    assert pob.nodes == {1, 2, 3} and pob.value == 1000.0  # nothing of the batch survived


def test_path_swap_replay_walks_every_step_whatever_the_clock_says(monkeypatch) -> None:
    """#569: the replay has no clock; its steps are bounded by the batch (<= max_candidates, 12), so it walks all of them."""

    from junkroan.optimizer import pipeline as mod

    # Every `perf_counter()` call costs this fake clock 100 s: a clock-bound replay would stop after one step.
    ticks = iter(range(0, 1_000))
    monkeypatch.setattr(mod.time, "perf_counter", lambda: float(next(ticks)) * 100.0)

    class _BudgetTree(_Tree):
        def __init__(self, pob: _Pob) -> None:
            super().__init__(pob, [])
            self.graph = SimpleNamespace(node=lambda node_id: SimpleNamespace(name=str(node_id)))
            score = FLOORED.score({"CombinedDPS": 1000, "Life": 5000})
            self.steps = [Step(node_id, str(node_id), "path", 1, [node_id + 10], None, score, score, 1, 0.0, removed_node_ids=[node_id]) for node_id in range(1, 4)]

        def swap_subtrees(self, *, max_size: int, max_seconds: float, max_candidates=None):
            self.pob.value = 900.0
            self.history.extend(self.steps)
            return SimpleNamespace(steps=self.steps)

    pob = _Pob(1000.0)
    tree = _BudgetTree(pob)
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    logs: list[str] = []
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=1_000_000.0, min_gain=0.005, loot_n=5))

    assert not any("budget" in line and "replay" in line for line in logs)
    assert len([line for line in logs if line.startswith("replay: skipped")]) == 3  # all three steps were visited


def test_a_gear_roll_that_breaks_a_floor_is_kept_when_the_tree_repairs_it() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], repairs=[(1300.0, 4200.0)], calls=calls)
    loot = _Loot(pob, {"Boots": [("b1", 1500.0, 3000.0)]}, calls=calls)  # +50% but 1000 life short of the floor
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    i = next(j for j, c in enumerate(calls) if c[0] == "fill_slot")
    assert calls[i + 1:i + 4] == [("reconfigure",), ("refine", 0, 60), ("reconfigure",)]
    # judge did not reconfigure a second time; the pass that kept a move closes with the choices judged again (D60)
    assert calls[i + 4:] == [("tune_lanes", False), ("reconfigure",)]
    assert result.stages[-1].notes == "Boots +30.0%; stopped: max passes (1)"
    assert pob.value == 1300.0 and pob.life == 4200.0 and loot.current_raw == {"Boots": "b1"}
    assert "1 moves kept" in note


def test_a_gear_roll_the_tree_cannot_repair_is_reverted_with_its_repair() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], repairs=[], calls=calls)  # the repair round finds nothing: still infeasible
    # D116 / #553: +10% at 0.25 violation prices at 1100 * 0.75 = 825 < 1000, so the loop's priced order reverts it
    # (the 1500 roll of the test above would price at 1125 and be kept without the repair)
    loot = _Loot(pob, {"Boots": [("b1", 1100.0, 3000.0)]}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    i = next(j for j, c in enumerate(calls) if c[0] == "fill_slot")
    assert calls[i + 1:i + 4] == [("reconfigure",), ("refine", 0, 60), ("reconfigure",)]
    assert result.stages[-1].notes == "no change"  # the kicks found nothing either
    assert pob.value == 1000.0 and pob.life == 5000.0 and loot.current_raw == {}
    assert "fixed point after 1 pass" in note and "0 moves kept" in note


def test_the_kicks_run_only_when_the_local_moves_kept_nothing() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    # pass 1: refine +0.1% (reverted), then the kick joint's own refine finds +2%; pass 2: nothing anywhere
    tree = _Tree(pob, [1001.0, 1020.0], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=3, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[1].notes == "kick joint +2.0% (draw 1)" and result.stages[2].notes == "no change"
    assert [c for c in calls if c[0] == "reoptimize"][:3] == [("reoptimize", 1, 20, 10, derive_seed(1, PURPOSE_TREE_KICK, 1, d)) for d in range(3)]  # the kick tree's three draws came first, and found nothing
    assert "fixed point after 2 passes" in note and "1 moves kept" in note
    assert pob.value == 1020.0


def test_every_kick_draw_runs_and_is_judged_on_its_own() -> None:
    """Run E's chain kept reoptimize round 2 of 3 and joint round 4 of 4 on Cold DoT s1; the loop's
    one draw each missed on the same seed and was called the fixed point (loop-smoke-2). Stopping
    at the first kept draw starved the joint kick (Bleed Bow s1, loop-smoke-3: 148% -> 89%), so
    every draw of both kicks runs and is judged on its own."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1001.0], reopt_values=[1000.0, 1030.0], calls=calls)  # draw 1 misses, draw 2 finds +3%
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=3, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[1].notes == "kick tree +3.0% (draw 2)"  # draw 3 and the four joint draws ran too and found nothing
    assert result.stages[2].notes == "no change"  # pass 2: 3 tree draws and 4 joint draws, nothing
    reopts = [c for c in calls if c[0] == "reoptimize"]
    assert reopts == [("reoptimize", 1, 20, 10, derive_seed(1, PURPOSE_TREE_KICK, 1, d)) for d in range(3)] + [("reoptimize", 1, 20, 10, derive_seed(1, PURPOSE_TREE_KICK, 2, d)) for d in range(3)]
    branches = [c for c in calls if c[0] == "_random_branches"]
    assert len(branches) == 8 and len({b[2] for b in branches}) == 8  # the joint draws differ: the rng advances
    assert [c for c in calls if c[0] == "allocate"] == [("allocate", 2, True), ("allocate", 2, False)] * 4  # variants alternate as the chain's rounds
    assert "fixed point after 2 passes" in note and "1 moves kept" in note and pob.value == 1030.0


def test_a_pass_that_kept_a_local_move_does_not_kick() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1100.0], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert result.stages[-1].notes.startswith("refine +10.0%")
    assert not [c for c in calls if c[0] in ("reoptimize", "_random_branches")]


def test_joint_round_draws_the_same_randoms_in_the_same_order() -> None:
    """The kick's draws must not move when the chain's `_joint_reoptimize` stage is deleted (D58):
    two rounds of `_joint_round` on the stage's own rng (`random.Random(derive_seed(seed, PURPOSE_JOINT_KICK_RNG))`, seed 1) make
    exactly the calls the pre-refactor stage made, minus the snapshots the stage itself took."""

    import random

    calls: list = []
    pob = _Pob(1000.0, calls=calls)
    tree = _Tree(pob, [], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves", "Weapon 1": "Wand"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    rng = random.Random(derive_seed(1, PURPOSE_JOINT_KICK_RNG))

    def roll(i: int, j: int) -> int:  # the headroom pre-pass of round i seeds its own roll j
        return derive_seed(derive_seed(1, PURPOSE_HEADROOM_SLOTS, i), PURPOSE_HEADROOM_ROLLS, j)

    for i in (0, 1):
        p.joint_round(sk, loot, tree, i=i, seed=1, loot_n=5, rng=rng, ruin_points=16, slots_per_round=2, refine_rounds=6)

    assert calls == [
        ("random_rares", "Two-Toned Boots", 40, roll(0, 0)),
        ("random_rares", "Fingerless Silk Gloves", 40, roll(0, 1)),
        ("random_rares", "Wand", 40, roll(0, 2)),
        ("_random_branches", 16, 0.112924),
        ("equip", ("Gloves", "Weapon 1")),
        ("mutate_nodes", (7, 8)),
        ("fill_slot", "Weapon 1", "Wand", 5, None, derive_seed(1, PURPOSE_LOOP_FILL_SLOT, 0, 0), False),  # even round: the gear for damage alone
        ("fill_slot", "Gloves", "Fingerless Silk Gloves", 5, None, derive_seed(1, PURPOSE_LOOP_FILL_SLOT, 0, 1), False),
        ("allocate", 2, True),  # ... and the tree re-spend repairs the floors
        ("refine", 6, 60),
        ("reconfigure",),
        ("random_rares", "Two-Toned Boots", 40, roll(1, 0)),
        ("random_rares", "Fingerless Silk Gloves", 40, roll(1, 1)),
        ("random_rares", "Wand", 40, roll(1, 2)),
        ("_random_branches", 16, 0.750459),
        ("equip", ("Boots", "Weapon 1")),
        ("mutate_nodes", (7, 8)),
        ("allocate", 2, False),  # odd round: the tree for damage alone, the gear repairs
        ("fill_slot", "Weapon 1", "Wand", 5, None, derive_seed(1, PURPOSE_LOOP_FILL_SLOT, 1, 0), True),
        ("fill_slot", "Boots", "Two-Toned Boots", 5, None, derive_seed(1, PURPOSE_LOOP_FILL_SLOT, 1, 1), True),
        ("refine", 6, 60),
        ("reconfigure",),
    ]


def test_a_kick_draw_that_left_the_build_unchanged_is_skipped_without_a_judge() -> None:
    """`reoptimize` keeps or restores by its own objective inside, so a draw it restored hands the
    loop the build it already stands on: 135 of the 177 reverted tree draws of the 42 core14 logs
    (21,279 s) were exactly that. An identical export is an identical build, whose number cannot pass
    `better` (gain 0 < min_gain) and whose revert would load what PoB already holds: no reconfigure,
    no recalc, no load_xml (7.1h)."""

    pob = _Pob(1000.0)
    reconfigures: list = []
    calls: list = []
    logs: list[str] = []
    tree = _Tree(pob, [], calls=calls)  # nothing any tree move does changes the number
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, reconfigures=reconfigures, calls=calls, log=logs.append)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert [c for c in calls if c[0] == "reoptimize"] == [("reoptimize", 1, 20, 10, derive_seed(1, PURPOSE_TREE_KICK, 1, d)) for d in range(3)]  # every draw still ran
    assert sum(1 for m in logs if "no change, skipped" in m) == 7  # 3 tree draws + 4 joint draws, none of them judged
    assert len(pob.loaded) == 2  # only the refine and the path swaps were reverted
    # the opening lanes 1, refine 1, swaps 1, and one inside each joint round: the loop's first snapshot is
    # taken after the opening derivation (D60), so the refine's revert reuses the lanes it carries
    assert len(reconfigures) == 1 + 1 + 1 + 4
    assert "fixed point after 1 pass" in note and "0 moves kept" in note and pob.value == 1000.0


def test_a_kick_draw_that_changed_the_build_is_still_judged() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    logs: list[str] = []
    tree = _Tree(pob, [], reopt_values=[1030.0], calls=calls)  # the first tree draw moves the number
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls, log=logs.append)
    result = p.started()

    note = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5)).note

    assert result.stages[-1].notes.startswith("kick tree +3.0% (draw 1)")
    assert any("kick tree (draw 1 of 3): 1,000 (viol 0.000) -> 1,030" in m for m in logs)  # judged, not skipped
    assert "1 moves kept" in note and pob.value == 1030.0


def test_a_revert_reuses_the_lanes_its_snapshot_carries() -> None:
    """A snapshot exported while the applied config is the lane derivation for that build carries
    those lanes in its own <Config>: the `load_xml` that reverts to it puts them back, so the second
    derivation the revert used to do is a re-derivation of what PoB already holds (7.1h). Only the
    loop's very first snapshot is not known to be fresh."""

    pob = _Pob(1000.0)
    reconfigures: list = []
    # refine and path swaps +0.1%, and the three tree draws move the number a little too: below
    # min_gain, so all five are judged and reverted (the four joint draws change nothing and are skipped)
    tree = _Tree(pob, [1001.0], [1001.0], reopt_values=[1001.0, 1002.0, 1003.0])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, reconfigures=reconfigures)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert len(pob.loaded) == 5 and pob.value == 1000.0  # refine, swaps and the three tree draws reverted
    # the opening lanes 1 (D60: the loop's first snapshot now follows a derivation of its own, so the
    # refine's revert reuses it), refine 1, swaps 1, the three tree draws 1 each, the four joint rounds
    # 1 each (their own, inside _joint_round). Before the change every revert derived a second time: 18.
    assert len(reconfigures) == 1 + 1 + 1 + 3 + 4


def test_the_picks_move_is_skipped_when_nothing_changed_since_it_ran(monkeypatch) -> None:
    pob = _Pob(1000.0)
    tree = _Tree(pob, [1001.0] * 8)  # every refine +0.1%: reverted
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)]})  # pass 1: the gloves roll +2% is kept; pass 2: the incumbent
    sk = _skeleton({"Gloves": "Fingerless Silk Gloves"}, main_link=("Fireball", "Spell Echo"))
    sweeps = _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=3, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert result.stages[1].notes == "Gloves +2.0%"
    assert sweeps == [1], "the re-judge ran once, in the pass that changed the build; pass 2 skipped it"
    assert result.stages[2].notes == "no change"


# -- D60: the loop judges under the final lanes ------------------------------------------------


def test_the_lanes_are_judged_before_pass_1_and_after_a_pass_that_changed_the_build(monkeypatch) -> None:
    """The loop's objective is the final lanes' (D60): the choices and the identity are judged once
    before pass 1, and the choices again at the end of every pass whose moves changed the build; a
    pass that kept nothing (the fixed point) does not judge them again."""

    calls: list = []
    pob = _Pob(1000.0, calls=calls)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)]})
    sk = _skeleton({"Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert [c for c in calls if c[0] == "tune_lanes"] == [("tune_lanes", True), ("tune_lanes", False)]
    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "loop pass 1", "loop pass 2"]
    assert result.stages[1].notes == "Gloves +2.0%" and result.stages[2].notes == "no change"


def test_the_pre_loop_tuning_repairs_a_build_its_own_lanes_left_infeasible() -> None:
    """The defect that reverted the first attempt at D60 (7aa1c08 / 6250168): the lanes tuned before
    pass 1 left the same build infeasible (viol 0.345) and the loop bought the floor back with a gear
    roll that cost 40% of the damage. `_finish` repairs exactly this case after its own tuning
    (`refine(max_rounds=12)`, then the lanes derived once more), and so does the loop."""

    calls: list = []
    pob = _Pob(1000.0, calls=calls)
    logs: list[str] = []
    tree = _Tree(pob, [], calls=calls)
    base_refine = tree.refine

    def refine(*, max_rounds: int, repair_rounds: int = 60):
        out = base_refine(max_rounds=max_rounds, repair_rounds=repair_rounds)
        if max_rounds == 12:  # the repair round: the tree buys the floor back
            pob.life = 4200.0
        return out

    tree.refine = refine

    def tune_lanes(sk, *, identity: bool = False) -> dict:
        calls.append(("tune_lanes", identity))
        pob.life = 3000.0  # the judged stance is the damage one: 1,000 life under the floor
        p.judging.rejudge(sk)
        return {"bloodSandStance": "BLOOD"}

    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls, log=logs.append, tune_lanes=tune_lanes)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert [call for call in calls if call[0] != "export_xml"][:4] == [
        ("tune_lanes", True), ("reconfigure",), ("refine", 12, 60), ("reconfigure",)
    ]
    assert pob.life == 4200.0, "the loop enters its first pass feasible, under the lanes it will be reported with"
    assert any("repaired after the tuning: viol 0.250 -> 0.000" in m for m in logs)
    assert result.stages[-1].notes == "no change"  # the repair is not a move: it is the price of the lanes


def _tune(p: BuildPipeline, sk, derived, *, guard: bool = False) -> dict:
    """The list choices judged by PoB (D24) as the pipeline judges them: `tune_choices` under the
    pipeline's objective, writing each trial through `write_lanes`."""

    def log(message: str) -> None:
        p.log(message)

    return tune_choices(p.pob, sk, derived, objective=p.objective,
                        write=lambda skeleton, lanes: write_lanes(p.pob, skeleton, lanes, log=log), log=log, guard=guard)


def test_a_second_tuning_round_really_compares_the_values() -> None:
    """The bug that reverted the first attempt at D60: the lane write (`write_lanes`) merged the remembered choice
    over the value under trial, so every round after the first compared identical configs and kept
    the first value of the list. Two rounds on a PoB whose number follows the input must both choose
    the best value, not the first."""

    class _StancePob:
        stance = None

        def set_config(self, **kw):
            self.stance = kw["inputs"].get("bloodSandStance")

        def stats(self, keys):
            return {k: 0.0 for k in keys} | {"CombinedDPS": 200.0 if self.stance == "BLOOD" else 100.0, "Life": 5000.0}

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = _StancePob()
    p.judging = pob_judging(p)
    p.objective = FLOORED
    sk = SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})

    def fresh():  # what a re-derivation hands the second round: PoB's own default, not the judged value
        return SimpleNamespace(choices={"bloodSandStance": ["SAND", "BLOOD"]},
                               conservative=SimpleNamespace(inputs={"bloodSandStance": "SAND"}, reasons={}),
                               optimistic=SimpleNamespace(inputs={"bloodSandStance": "SAND"}, reasons={}))

    assert _tune(p, sk, fresh()) == {"bloodSandStance": "BLOOD"}
    assert sk.tuned_choices == {"bloodSandStance": "BLOOD"} and p.pob.stance == "BLOOD"
    assert _tune(p, sk, fresh()) == {"bloodSandStance": "BLOOD"}, "the second round compared SAND with BLOOD, not BLOOD with BLOOD"
    assert sk.tuned_choices == {"bloodSandStance": "BLOOD"} and p.pob.stance == "BLOOD"


def test_the_exposure_flags_follow_the_judged_choice_and_are_re_judged_with_it() -> None:
    """Elemental Army's exposure: the chosen element's condition is on, the other two off, and both
    the choice and its flags are remembered (D60) -- without blocking the next round, which is free
    to move the exposure to another element when the build changed under it."""

    class _ExposurePob:
        best = "Cold"
        type_ = None

        def set_config(self, **kw):
            self.type_ = kw["inputs"].get("elementalArmyExposureType")

        def stats(self, keys):
            return {k: 0.0 for k in keys} | {"CombinedDPS": 300.0 if self.type_ == self.best else 100.0, "Life": 5000.0}

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = _ExposurePob()
    p.judging = pob_judging(p)
    p.objective = FLOORED
    sk = SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})

    def fresh():
        return SimpleNamespace(choices={"elementalArmyExposureType": ["Fire", "Cold", "Lightning"]},
                               conservative=SimpleNamespace(inputs={}, reasons={}), optimistic=SimpleNamespace(inputs={}, reasons={}))

    assert _tune(p, sk, fresh()) == {"elementalArmyExposureType": "Cold"}
    assert sk.tuned_choices == {"elementalArmyExposureType": "Cold", "conditionEnemyFireExposure": False,
                                "conditionEnemyColdExposure": True, "conditionEnemyLightningExposure": False}

    p.pob.best = "Lightning"  # the build moved under it (a support swapped, the gear changed)
    assert _tune(p, sk, fresh()) == {"elementalArmyExposureType": "Lightning"}
    assert sk.tuned_choices == {"elementalArmyExposureType": "Lightning", "conditionEnemyFireExposure": False,
                                "conditionEnemyColdExposure": False, "conditionEnemyLightningExposure": True}


# -- D66: the delivered build is never less feasible than the fixed point the loop reached --------


def test_keep_if_feasible_judges_feasibility_only() -> None:
    """The rule of every step after the loop: it may fail to raise the number, but it may never buy
    the number with a floor. Value is the loop's business, so only the violation is compared."""

    from junkroan.optimizer.objective import Score
    from junkroan.optimizer.pipeline import keep_if_feasible

    feasible, broken, worse = Score(neg_violation=0.0, value=1000.0), Score(neg_violation=-0.076, value=2000.0), Score(neg_violation=-0.2, value=9e9)
    assert keep_if_feasible(feasible, Score(neg_violation=0.0, value=1100.0))  # feasible and better
    assert keep_if_feasible(feasible, Score(neg_violation=0.0, value=900.0))  # feasible and worse: still not our business
    assert not keep_if_feasible(feasible, broken), "a step that introduced a violation, however much value it bought"
    assert keep_if_feasible(broken, Score(neg_violation=-0.076, value=1.0)), "an equally infeasible state is not less feasible"
    assert keep_if_feasible(broken, feasible)  # a step that repaired the floor
    assert not keep_if_feasible(broken, worse), "a violation that grew"


def test_a_guarded_step_that_raises_the_value_and_keeps_feasibility_is_kept() -> None:
    pob = _Pob(1000.0)
    p = _pipeline(pob, [])
    logs: list[str] = []
    p.log = logs.append
    sk = _skeleton({})
    sk.tuned_choices, sk.pantheon_major, sk.pantheon_minor, sk.bandit = {}, "None", "None", "None"

    def step() -> str:
        pob.value, sk.pantheon_minor = 1300.0, "Shakari"
        return "tuned"

    out, kept = p._guarded_step(sk, "identity", step)

    assert (out, kept) == ("tuned", True)
    assert pob.value == 1300.0 and sk.pantheon_minor == "Shakari" and pob.loaded == []
    assert not [m for m in logs if m.startswith("reverted:")]


def test_a_guarded_step_that_breaks_a_floor_is_reverted_and_logged() -> None:
    """The defect this rule closes: a step after the loop leaves the build infeasible and the
    pipeline reports it (rules-smoke stormbrand s3, MoMCastsAfterMaxHit 1.2 < 3)."""

    pob = _Pob(1000.0)
    p = _pipeline(pob, [])
    logs: list[str] = []
    p.log = logs.append
    sk = _skeleton({})
    sk.tuned_choices, sk.pantheon_major, sk.pantheon_minor, sk.bandit = {"bloodSandStance": "SAND"}, "None", "None", "None"
    restored: list[int] = []

    def step() -> str:
        pob.value, pob.life = 5000.0, 3600.0  # +400% of the number, 400 life under the floor
        sk.tuned_choices["bloodSandStance"] = "BLOOD"
        sk.pantheon_major = "Lunaris"
        return "tuned"

    out, kept = p._guarded_step(sk, "choice inputs", step, restore=lambda: restored.append(1))

    assert (out, kept) == (None, False)
    assert pob.value == 1000.0 and pob.life == 5000.0 and len(pob.loaded) == 1  # the snapshot put the build back
    assert sk.tuned_choices == {"bloodSandStance": "SAND"} and sk.pantheon_major == "None" and restored == [1]
    assert [m for m in logs if m.startswith("reverted:")] == [
        "reverted: choice inputs broke Life = 3600.000 < 4000 (1,000 viol 0.000 -> 5,000 viol 0.100)"]


def _stance_case() -> tuple:
    """A choice whose whole list is less feasible than the build the tuning started from: the var is
    not in the derived lane (PoB is at its own default, feasible), and both values break the life
    floor. The existing comparison of the values with each other cannot see this -- it only ranks
    SAND against BLOOD -- so without the guard the best of a bad list is delivered."""

    class _StancePob:
        stance = None  # PoB's own default until the tuning writes one: 5,000 life, no damage

        def set_config(self, **kw):
            self.stance = kw["inputs"].get("bloodSandStance")

        def stats(self, keys):
            life, dps = {"SAND": (3000.0, 9000.0), "BLOOD": (3500.0, 5000.0)}.get(self.stance, (5000.0, 100.0))
            return {k: 0.0 for k in keys} | {"CombinedDPS": dps, "Life": life}

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = _StancePob()
    p.log = lambda _m: None
    p.judging = pob_judging(p)
    p.objective = FLOORED
    sk = SimpleNamespace(bandit="None", pantheon_major="None", pantheon_minor="None", user_config={}, tuned_choices={})
    derived = SimpleNamespace(choices={"bloodSandStance": ["SAND", "BLOOD"]},
                              conservative=SimpleNamespace(inputs={}, reasons={}), optimistic=SimpleNamespace(inputs={}, reasons={}))
    return p, sk, derived


def test_a_choice_that_is_the_best_of_its_list_and_still_less_feasible_is_put_back() -> None:
    """`tune_choices(guard=True)`, the per-choice half of the rule: the values are judged
    against each other as before (D24), and the winner against the build the tuning started from."""

    p, sk, derived = _stance_case()
    logs: list[str] = []
    p.log = logs.append

    assert _tune(p, sk, derived, guard=True) == {}
    assert derived.conservative.inputs == {} and derived.optimistic.inputs == {} and p.pob.stance is None
    assert sk.tuned_choices == {}
    assert logs == ["reverted: choice bloodSandStance = 'BLOOD' broke Life = 3500.000 < 4000"]


def test_the_loop_s_own_lane_tuning_is_not_guarded() -> None:
    """The loop is allowed to tune into a violation and buy the floor back with the tree afterwards
    (D60, `loop lanes: repaired after the tuning`), so the guard is `_finish`'s alone."""

    p, sk, derived = _stance_case()

    assert _tune(p, sk, derived) == {"bloodSandStance": "BLOOD"}
    assert sk.tuned_choices == {"bloodSandStance": "BLOOD"} and p.pob.stance == "BLOOD"


def test_finish_guards_its_tuning_steps_and_reports_the_final_feasibility(monkeypatch) -> None:
    """A tuning step that raises the value and keeps feasibility is kept, and the log carries the
    verdict the benchmark reads."""

    pob = _Pob(1000.0)
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, _Tree(pob, []), {})
    p._tune_identity = lambda _sk, _d: (pob.__setattr__("value", 1300.0), {"pantheon_minor": "Shakari"})[1]
    sk = _finish_skeleton()
    result = BuildResult(skeleton=sk)

    p._finish(result, sk, 0.0)

    assert pob.value == 1300.0 and pob.loaded == []
    assert "final feasibility: ok" in logs
    assert not [m for m in logs if m.startswith("reverted:") or m.startswith("final tuning reverted:")]
    assert "choices {'pantheon_minor': 'Shakari'}" in result.stages[-1].notes and "final feasibility: ok" in result.stages[-1].notes


def test_finish_reverts_a_tuning_step_that_introduces_a_violation(monkeypatch) -> None:
    """stormbrand s3 / cold_dot s2 of the rules-smoke run were delivered infeasible. Whatever a step
    after the loop buys, it may not buy it with a floor: the step goes back."""

    pob = _Pob(1000.0)
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, _Tree(pob, []), {})

    def identity(_sk, _d) -> dict:
        pob.value, pob.life = 9000.0, 3600.0  # nine times the damage, 400 life under the floor
        return {"pantheon_major": "Lunaris"}

    p._tune_identity = identity
    sk = _finish_skeleton()
    result = BuildResult(skeleton=sk)

    p._finish(result, sk, 0.0)

    assert pob.value == 1000.0 and pob.life == 5000.0, "the build the loop handed over, not the one the step bought"
    assert sk.pantheon_major == "None" and len(pob.loaded) == 1
    assert [m for m in logs if m.startswith("reverted:")] == [
        "reverted: identity broke Life = 3600.000 < 4000 (1,000 viol 0.000 -> 9,000 viol 0.100)"]
    assert "final feasibility: ok" in logs and "choices" not in result.stages[-1].notes


def test_finish_falls_back_to_the_pre_finish_snapshot_when_it_cannot_repair(monkeypatch) -> None:
    """The violation the guards cannot revert: the final lane derivation itself, which is what the
    build honestly is. The repair path runs (the refine's cheapest-DPS repair, then the repair-only
    round the gear move uses) and, when the build is still less feasible than the fixed point the
    loop reached, the pre-`_finish` snapshot is what is delivered."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [], repairs=[])  # the tree cannot buy the floor back
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {"Life": 3000.0})  # the honest lanes: 1,000 life short
    sk = _finish_skeleton()
    result = BuildResult(skeleton=sk)

    p._finish(result, sk, 0.0)

    assert [c[:3] for c in tree.calls] == [("refine", 12, 60), ("refine", 0, 60)]  # both repair rounds were tried
    # the repair bought nothing and went back first, then the whole of `_finish` went back
    assert [m for m in logs if m.startswith("reverted:")] == [
        "reverted: repair after the final lanes bought nothing (viol 0.250 -> 0.250, 1,000 -> 1,000 if kept)"]
    assert pob.value == 1000.0 and pob.life == 5000.0 and len(pob.loaded) == 2
    assert [m for m in logs if m.startswith("final tuning reverted:")] == [
        "final tuning reverted: Life = 3000.000 < 4000 (viol 0.000 -> 0.000, value 1,000 -> 1,000)"
        "; the stages above it describe a build that was not delivered"]
    assert "final feasibility: ok" in logs
    assert "final tuning reverted:" in result.stages[-1].notes and "final feasibility: ok" in result.stages[-1].notes


def test_finish_repairs_on_the_full_objective_not_the_trees_own(monkeypatch) -> None:
    """The defect behind cold_dot s2: the repair gate asked `_trees[1].current_score()`, whose
    objective is the full one `without("EffectiveMovementSpeedMod")` (D28), so a build short of the
    movement floor was never offered the repair at all. The gate reads `self.objective`."""

    pob = _Pob(1000.0, life=3600.0)  # already 400 life short when the loop hands the build over
    tree = _Tree(pob, [], repairs=[(1000.0, 4200.0)])  # the repair-only round buys the floor back
    tree.objective = FLOORED.without("Life")  # ... and the tree itself cannot see that floor
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()

    p._finish(BuildResult(skeleton=sk), sk, 0.0)

    assert [c[:3] for c in tree.calls] == [("refine", 12, 60), ("refine", 0, 60)]
    assert pob.life == 4200.0 and "final feasibility: ok" in logs and pob.loaded == []


def test_finish_keeps_a_repair_that_pays_and_reverts_one_that_does_not(monkeypatch) -> None:
    """The repair rounds refine under the tree's own objective (the full one without the movement
    floor, D28), so a round that paid there can be flat under the objective the build is delivered
    on. It is judged by the same rule as every other step: kept only when the Score improves."""

    pob = _Pob(1000.0, life=3600.0)
    tree = _Tree(pob, [], repairs=[(600.0, 4100.0)])  # 40% of the value for the floor: feasibility first, so kept
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()
    p._finish(BuildResult(skeleton=sk), sk, 0.0)
    assert pob.value == 600.0 and pob.life == 4100.0 and pob.loaded == [] and "final feasibility: ok" in logs

    pob = _Pob(1000.0, life=3600.0)
    tree = _Tree(pob, [], repairs=[(600.0, 3600.0)])  # 40% of the value and not one point of the floor: reverted
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()
    p._finish(BuildResult(skeleton=sk), sk, 0.0)
    assert pob.value == 1000.0 and pob.life == 3600.0
    assert [m for m in logs if m.startswith("reverted:")] == [
        "reverted: repair after the final lanes bought nothing (viol 0.100 -> 0.100, 1,000 -> 600 if kept)"]


def test_finish_reports_a_build_the_loop_itself_left_infeasible(monkeypatch) -> None:
    """stormbrand s3 and cold_dot s2 as they really were: infeasible before `_finish` ran, and at
    exactly the same violation after it. Nothing is reverted -- there is nothing better to go back
    to -- and the log says which floor is missed instead of "ok"."""

    pob = _Pob(1000.0, life=3600.0)
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, _Tree(pob, [], repairs=[]), {})
    sk = _finish_skeleton()
    result = BuildResult(skeleton=sk)

    p._finish(result, sk, 0.0)

    # the repair round found nothing and went back; so did the final floor repair's one round (#553, a second load);
    # `_finish` itself has nothing better to fall back to
    assert pob.value == 1000.0 and pob.life == 3600.0 and len(pob.loaded) == 2
    assert not [m for m in logs if m.startswith("final tuning reverted:")]
    assert [m for m in logs if m.startswith("final feasibility:")] == [
        "final feasibility: Life = 3600.000 < 4000 (viol 0.100; the loop handed `_finish` a build at 0.100)"]
    assert "final feasibility: Life = 3600.000 < 4000" in result.stages[-1].notes


def test_finish_runs_the_fixed_point_pass_inside_the_feasibility_guard(monkeypatch) -> None:
    """The two rules meet here (7.3 + D66): the extra pass of local moves runs after the repair and
    before the final check, its gain is kept, and the verdict lands on the stage it left behind."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [], repairs=[])
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    loot = _Loot(pob, {"Boots": [("b1", 1020.0)]})  # the extra pass finds +2% the loop had missed
    sk = _finish_skeleton()
    sk.rare_bases = {"Boots": "Two-Toned Boots"}
    result = BuildResult(skeleton=sk)

    p._finish(result, sk, 0.0, fixed_point={"loot": loot, "tree": tree, "loot_n": 5, "seed": 1,
                                            "min_gain": 0.005, "max_seconds": 600.0, "enabled": True})

    # #800: the pass that kept +2% is followed by a second one that keeps nothing: the delivered build is a fixed point of the
    # extra pass, so the last pass's gain is 0 and there is no audit error (it was one extra pass before #800)
    assert [s.name for s in result.stages] == ["config (final lanes)", "fixed point check", "fixed point check"]
    assert pob.value == 1020.0 and result.fixed_point_gain == 0.0 and result.fixed_point_note == "kept nothing"
    assert result.fixed_point_moved and result.fixed_point_passes == 2
    assert "final feasibility: ok" in logs and "final feasibility: ok" in result.stages[-1].notes
    assert [f.severity for f in result.audit if f.check == "fixed point"] == []


# -- 7.3: the fixed-point check ----------------------------------------------------------------


def _checked(pob: _Pob, calls: list) -> BuildPipeline:
    """A pipeline for `_fixed_point_check`: how the loop ended reaches it as the `loop_outcome` argument."""

    return _pipeline(pob, [], calls=calls)


def test_the_fixed_point_check_keeps_nothing_on_a_build_that_is_at_its_fixed_point() -> None:
    """The finished build, one more pass of local moves: every move below `min_gain` is reverted, so
    the pass keeps nothing, the gain is 0 and there is no finding. No kick and no lane tuning runs:
    the check measures the local neighbourhood `_finish` may have moved, not a new search."""

    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    logs: list[str] = []
    p.log = logs.append
    tree = _Tree(pob, [1001.0], calls=calls)  # refine +0.1%, below min_gain
    loot = _Loot(pob, {"Boots": [("b1", 1002.0)]}, calls=calls)  # and the roll +0.2%
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0)

    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "fixed point check"]
    assert result.stages[-1].notes == "no change"
    # the moves log under the stage, not under "loop pass 1": the loop is over by the time this runs
    assert [m.split(":")[0] for m in logs if m.startswith("fixed point check") and " move " not in m] == [
        "fixed point check tree refine", "fixed point check tree path swaps",
        "fixed point check Boots", "fixed point check"]
    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == "kept nothing"
    assert findings == []
    assert not [c for c in calls if c[0] in ("reoptimize", "_random_branches", "tune_lanes")], "no kicks, no lane tuning"
    assert pob.value == 1000.0 and loot.current_raw == {}


def test_the_fixed_point_check_is_an_audit_error_when_the_last_extra_pass_still_gains() -> None:
    """A build whose extra passes never settle (each improves it by 2%, #800: three passes, then the limit) was not at a fixed point:
    the build keeps the gains and the audit says so with the last number (ROADMAP 7.3)."""

    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    tree = _Tree(pob, [], calls=calls)
    loot = _Loot(pob, {"Boots": [("b1", 1020.0), ("b2", 1040.4), ("b3", 1061.208)]}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0)

    assert abs(result.fixed_point_gain - 0.02) < 1e-9 and result.fixed_point_note == "Boots +2.0%"
    assert [(f.severity, f.check) for f in findings] == [("error", "fixed point")]
    assert findings[0].detail == ("the loop was not at a fixed point: one more pass gained +2.0% (Boots +2.0%); "
                                  "the limit of 3 extra passes ended the repeats")
    assert pob.value == 1061.208 and loot.current_raw == {"Boots": "b3"}, "a gain is never thrown away"
    assert result.stages[-1].name == "fixed point check" and result.stages[-1].notes == "Boots +2.0%"
    # the rolls are seeded away from every pass the loop ran, or the check would re-roll the last pass's gear
    # (and every repeat has a seed of its own, or it would re-roll the gear the pass before it rolled)
    seeds = [c[5] for c in calls if c[0] == "fill_slot"]
    assert seeds == [derive_seed(1 + k * FIXED_POINT_SEED_OFFSET, PURPOSE_JOINT_FILL_SLOT, 1, 0) for k in (1, 2, 3)]
    assert derive_seed(1, PURPOSE_JOINT_FILL_SLOT, 1, 0) not in seeds and len(set(seeds)) == 3


def test_a_gain_at_or_below_one_percent_is_a_warning_not_an_error() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    tree = _Tree(pob, [1008.0, 1016.064, 1024.192512], calls=calls)  # +0.8% a pass, three passes: over min_gain, under the 1% error threshold
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0)

    assert abs(result.fixed_point_gain - 0.008) < 1e-9 and result.fixed_point_note == "refine +0.8%"
    assert [(f.severity, f.check) for f in findings] == [("warning", "fixed point")]
    assert findings[0].detail == ("the loop was not at a fixed point: one more pass gained +0.8% (refine +0.8%); "
                                  "the limit of 3 extra passes ended the repeats")


def test_a_loop_that_stopped_on_its_time_budget_is_not_asked_for_another_pass() -> None:
    """The build is already known not to be at a fixed point: that is recorded, and no pass runs."""

    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    tree = _Tree(pob, [1500.0], calls=calls)
    loot = _Loot(pob, {"Boots": [("b1", 2000.0)]}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0, loop_outcome=LoopOutcome("", "time budget", (), {}, 1))

    assert calls == [] and [s.name for s in result.stages] == ["tree rebuilt on gear"], "no pass ran"
    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == "stopped on the time budget"
    assert [(f.severity, f.check, f.detail) for f in findings] == [("warning", "fixed point", "stopped on the time budget: not at a fixed point")]
    assert pob.value == 1000.0


def test_a_loop_that_ran_out_of_passes_is_not_at_a_fixed_point_either() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    result = _started(p, _skeleton({}, main_link=("Fireball",)))

    findings = p._fixed_point_check(result, _skeleton({}, main_link=("Fireball",)), _Loot(pob, {}, calls=calls), _Tree(pob, [1500.0], calls=calls),
                                    loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0, loop_outcome=LoopOutcome("", "max passes", (), {}, 1))

    assert calls == [] and result.fixed_point_note == "stopped on the pass limit"
    assert [(f.severity, f.check) for f in findings] == [("warning", "fixed point")]


def test_an_extra_pass_that_runs_out_of_time_is_not_a_fixed_point_either() -> None:
    """A pass that never judged every move kept nothing because it was cut short, not because the
    build is at a fixed point: reporting "kept nothing" for it would be a false clean."""

    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    tree = _Tree(pob, [1500.0], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=-1.0)

    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == "the extra pass stopped on the time budget"
    assert [(f.severity, f.check, f.detail) for f in findings] == [("warning", "fixed point", "the extra pass stopped on the time budget: not at a fixed point")]


def test_the_fixed_point_check_does_nothing_when_it_is_switched_off() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    p = _checked(pob, calls)
    tree = _Tree(pob, [1500.0], calls=calls)
    loot = _Loot(pob, {"Boots": [("b1", 2000.0)]}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)

    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0, enabled=False)

    assert findings == [] and calls == []
    assert [s.name for s in result.stages] == ["tree rebuilt on gear"]
    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == ""
    assert pob.value == 1000.0


def test_run_threads_the_fixed_point_flag_into_the_check() -> None:
    """`run(fixed_point_check=...)` is on by default and reaches `_fixed_point_check` through the
    `fixed_point` kwargs `_finish` is given; the loop's own passes are not touched by the flag."""

    import inspect

    assert inspect.signature(BuildPipeline.run).parameters["fixed_point_check"].default is True
    assert inspect.signature(BuildPipeline._finish).parameters["fixed_point"].default is None
    src = inspect.getsource(BuildPipeline.run)
    assert '"enabled": fixed_point_check' in src and "fixed_point={" in src


def test_the_extra_pass_leaves_the_loops_own_passes_alone() -> None:
    """The check runs the loop's pass body (`local_only`), so a normal loop must be unchanged by it:
    the same pass still tunes the lanes, still kicks when nothing local moved, and still says it
    stopped on the pass limit."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, calls=calls)
    result = p.started()

    outcome = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))
    note = outcome.note

    assert [c for c in calls if c[0] == "tune_lanes"] == [("tune_lanes", True)]
    assert [c[0] for c in calls].count("reoptimize") == 3  # the kicks still ran
    assert outcome.stopped == "" and list(outcome.kept) == []
    assert "fixed point after 1 pass" in note


# -- D71: the picks move can drop a reserving group -----------------------------------------------


def test_the_picks_note_carries_a_changes_own_text(monkeypatch) -> None:
    """A reserving-group drop reads as its own sentence ("dropped Determination (MoMCastsAfterMaxHit
    1.2 -> 3.4, -8.1%)"), not as "was -> now": a change that brings its own `text` is logged
    with it, and every other change keeps the was/now line."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball", "Controlled Destruction"))

    ran: list[int] = []

    class _Gen:
        def __init__(self, pob, rails, *, objective=None, log=None, castability_context=None, castability_metrics=None) -> None:
            self.pob, self.picks = pob, ()

        def rejudge_picks(self, skeleton, *, reconfigure=None, min_gain=0.005, max_sweeps=3, order="floors"):
            if ran:
                return []
            ran.append(1)
            self.pob.value = 920.0  # a drop costs damage and buys the floor: feasibility first
            return [{"what": "dropped", "was": "Determination", "now": "off", "before": 1000.0, "after": 920.0,
                     "text": "dropped Determination (MoMCastsAfterMaxHit 1.200 -> 3.400, -8.1%)"},
                    {"what": "support", "was": "Immolate", "now": "Trinity", "before": 920.0, "after": 920.0}]

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=2, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert result.stages[1].notes == ("picks: dropped Determination (MoMCastsAfterMaxHit 1.200 -> 3.400, -8.1%); "
                                      "support Immolate -> Trinity (+0.0%)")


def test_a_pass_whose_picks_kept_something_runs_them_again_next_pass(monkeypatch) -> None:
    """"The loop itself is the repetition rejudge_picks does with max_sweeps": a sweep that kept
    something left a build its own next sweep has never seen, so the picks run again even when
    nothing else moved -- which is how a second reserving group is dropped when one was not enough
    (D71). Two drops here, one per pass, and the third pass's sweep keeps nothing."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [])  # nothing but the picks ever moves the number
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball", "Controlled Destruction"))
    values = [900.0, 850.0]

    class _Gen:
        def __init__(self, pob, rails, *, objective=None, log=None, castability_context=None, castability_metrics=None) -> None:
            self.pob, self.picks = pob, ()

        def rejudge_picks(self, skeleton, *, reconfigure=None, min_gain=0.005, max_sweeps=3, order="floors"):
            if not values:
                return []
            before, self.pob.value = self.pob.value, values.pop(0)
            return [{"what": "dropped", "was": "an aura", "now": "off", "before": before, "after": self.pob.value,
                     "text": f"dropped an aura ({self.pob.value:,.0f})"}]

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert [s.notes for s in result.stages[1:]] == ["picks: dropped an aura (900)", "picks: dropped an aura (850)", "no change"]
    assert pob.value == 850.0


def test_the_picks_move_runs_for_a_one_gem_link_that_carries_a_group(monkeypatch) -> None:
    """The guard used to ask only for a support to swap or a group the picker chose. A build with one
    gem in its link and the author's own auras has neither -- and it is exactly the build the
    reserving-group drop exists for, so an enabled group is reason enough to re-judge (D71)."""

    from junkroan.search.skeleton import SocketGroup

    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    sk.extra_groups = [SocketGroup(gems=["Determination"], slot="Helmet", label="Determination")]  # not picked: the author's
    sweeps = _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert sweeps == [1], "the re-judge ran: the group is something discrete to judge"


def test_apply_config_carries_the_judged_choices_and_the_users_numbers_win() -> None:
    """The remembered choices are merged over the derived lanes at every reconfigure, and the user's
    own numbers over both (D26/D60)."""

    captured: dict = {}
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = SimpleNamespace(set_config=lambda **kw: captured.update(kw))
    p.judging = pob_judging(p)
    sk = SimpleNamespace(bandit="Alira", pantheon_major="None", pantheon_minor="None",
                         user_config={"multiplierMineDetonatedRecently": 10},
                         tuned_choices={"bloodSandStance": "BLOOD", "multiplierMineDetonatedRecently": 42})
    derived = SimpleNamespace(conservative=SimpleNamespace(inputs={"bloodSandStance": "SAND", "enemyIsBoss": True, "conditionEnemyIgnited": True}),
                              optimistic=SimpleNamespace(inputs={"bloodSandStance": "SAND", "enemyIsBoss": True}))

    write_lanes(p.pob, sk, derived, log=lambda message: p.log(message))

    assert captured["bandit"] == "Alira"
    assert captured["inputs"] == {"bloodSandStance": "BLOOD", "conditionEnemyIgnited": True, "multiplierMineDetonatedRecently": 10}
    assert captured["conditional"]["inputs"] == {"bloodSandStance": "BLOOD", "multiplierMineDetonatedRecently": 10}


@pytest.mark.parametrize("error_type", [PoBHeadlessHostContractError, WorkerContractError])
@pytest.mark.parametrize("failed_move", ["opening lanes", "refine", "swaps", "gear", "picks", "lanes", "kick", "joint"])
def test_contract_failed_loop_moves_restore_full_state_and_continue(monkeypatch, error_type, failed_move) -> None:
    """A contract error after a partial move restores every mutable surface and only drops that move."""

    import junkroan.optimizer.improvement_loop as improvement_loop_module
    import junkroan.optimizer.pipeline as pipeline_module

    failed_once = False

    class _Wishlist(_TemplateLoot):
        def fill_slot(self, slot, base, *, n=None, sockets=None, seed=1, replan_resistance=False, order="floors"):
            nonlocal failed_once
            if failed_move == "gear" and not failed_once:
                failed_once = True
                mutate()
                raise error_type("bad_payload", "gear payload rejected")
            return super().fill_slot(slot, base, n=n, sockets=sockets, seed=seed)

    monkeypatch.setattr(pipeline_module, "WishlistGear", _Wishlist)
    pob = _Pob(1000.0)
    logs: list[str] = []
    tree = _Tree(pob, [])
    tree.history = ["kept-before"]
    tree._trial_memo = {"static": "stale"}
    tree._trial_carry = {"static": "stale"}
    tree._barren = {"static"}
    tree._stage_depth = 3
    loot = _Wishlist(pob, {})
    loot._bench_cache = {"static": ["lookup"]}
    loot._mod_families = {"static": {"lookup": "family"}}
    sk = _skeleton({"Boots": "Two-Toned Boots"})
    sk.tuned_choices = {"stance": "SAND"}
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    result = p.started()
    result.picks = [{"what": "before"}]
    # Every pass opens by freezing the skill costs, which installs the `ManaCostPool`
    # derived stat into each objective in use. The restore must put back the objective
    # the failed move found, not the one the loop was built with, so compare without it.
    def _costless(objective):
        return objective.replace(derived=tuple(d for d in objective.derived if d.name != MANA_COST_POOL_STAT))

    original_objective = _costless(p.objective)
    original_tree_objective = _costless(tree.objective)

    def mutate() -> None:
        pob.value, pob.life = 777.0, 1234.0
        sk.tuned_choices["stance"] = "BLOOD"
        loot.current_raw["Boots"] = "broken raw"
        loot._resistance_assignments["Boots"] = "fire"
        loot.resistance_plan = {"assignment": "fire"}
        tree.history.append("bad-step")
        tree.objective = FLOORED.without("Life")
        p.objective = FLOORED.without("Life")
        result.picks.append({"what": "bad"})

    if failed_move == "picks":
        class _Gen:
            def __init__(self, *_args, **_kwargs) -> None:
                self.picks = ()

            def rejudge_picks(self, *_args, **_kwargs):
                mutate()
                raise error_type("bad_payload", "picks payload rejected")

        monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    elif failed_move in {"opening lanes", "lanes"}:
        original_tune_lanes = p.tune_lanes

        def tune_lanes(skeleton, *, identity=False):
            nonlocal failed_once
            should_fail = (failed_move == "opening lanes" and identity) or (failed_move == "lanes" and not identity)
            if not should_fail or failed_once:
                return original_tune_lanes(skeleton, identity=identity)
            failed_once = True
            mutate()
            raise error_type("bad_payload", f"{failed_move} payload rejected")

        p.tune_lanes = tune_lanes
        # The lane move only runs after an accepted local move. This makes the later pass prove
        # the failed lane operation did not abort the loop.
        tree.values = [1020.0]
        _patch_generator(monkeypatch, [])
    else:
        _patch_generator(monkeypatch, [])

    original_refine = tree.refine

    def refine(*, max_rounds, repair_rounds=60):
        nonlocal failed_once
        if failed_move == "refine" and not failed_once:
            failed_once = True
            mutate()
            raise error_type("bad_payload", "refine payload rejected")
        return original_refine(max_rounds=max_rounds, repair_rounds=repair_rounds)

    tree.refine = refine
    original_swaps = tree.swap_subtrees

    def swaps(*, max_size, max_seconds, max_candidates=None):
        nonlocal failed_once
        if failed_move == "swaps" and not failed_once:
            failed_once = True
            mutate()
            raise error_type("bad_payload", "swaps payload rejected")
        return original_swaps(max_size=max_size, max_seconds=max_seconds)

    tree.swap_subtrees = swaps

    original_reoptimize = tree.reoptimize

    def reoptimize(**kwargs):
        nonlocal failed_once
        if failed_move == "kick" and not failed_once:
            failed_once = True
            mutate()
            raise error_type("bad_payload", "kick payload rejected")
        return original_reoptimize(**kwargs)

    tree.reoptimize = reoptimize
    joint_calls: list[int] = []
    if failed_move == "joint":
        def joint_round(*_args, **_kwargs):
            nonlocal failed_once
            joint_calls.append(1)
            if not failed_once:
                failed_once = True
                mutate()
                raise error_type("bad_payload", "joint payload rejected")
            return "joint recovery"

        p.joint_round = joint_round
    p.run(LoopPlan(seed=1, max_passes=2 if failed_move in {"opening lanes", "lanes"} else 1, max_seconds=600.0,
                   min_gain=0.005, loot_n=5, kick_draws=(0, 2) if failed_move == "joint" else (2, 0)))

    expected_move = {
        "opening lanes": "loop opening lanes",
        "refine": "loop pass 1 tree refine",
        "swaps": "loop pass 1 tree path swaps",
        "gear": "loop pass 1 Boots",
        "picks": "loop pass 1 picks",
        "lanes": "loop pass 1 lanes",
        "kick": "loop pass 1 kick tree (draw 1 of 2)",
        "joint": "loop pass 1 kick joint (draw 1 of 2)",
    }[failed_move]
    assert result.dropped_moves == [{
        "move": expected_move,
        "exception": error_type.__name__,
        "failure_state": "bad_payload",
        "message": f"{failed_move} payload rejected",
    }]
    assert (pob.value, pob.life) == ((1020.0, 5000.0) if failed_move in {"opening lanes", "lanes"} else (1000.0, 5000.0))
    assert sk.tuned_choices == {"stance": "SAND"}
    assert loot.current_raw == {} and loot._resistance_assignments == {"Boots": "cold"}
    assert loot.resistance_plan == {"assignment": "cold"}
    assert tree.history == ["kept-before"] and _costless(tree.objective) == original_tree_objective
    assert tree._trial_memo == {} and tree._trial_carry == {} and tree._barren == set() and tree._stage_depth == 0
    assert loot._bench_cache == {"static": ["lookup"]}
    assert loot._mod_families == {"static": {"lookup": "family"}}
    assert _costless(p.objective) == original_objective and result.picks == [{"what": "before"}]
    assert any(expected_move in line and error_type.__name__ in line for line in logs)
    if failed_move in {"opening lanes", "lanes"}:
        assert any(stage.name == "loop pass 2" for stage in result.stages), "the loop continued after the failed lane move"
    elif failed_move == "joint":
        assert len(joint_calls) == 2, "the loop continued to the later joint kick draw"
    else:
        assert any(call[0] == "reoptimize" for call in tree.calls), "the loop continued to a later kick draw"


def test_dropped_moves_are_reported_in_the_summary_and_final_audit(monkeypatch) -> None:
    pob = _Pob(1000.0)
    p, _derived, _logs = _finish_pipeline(monkeypatch, pob, _Tree(pob, []), {})
    sk = _finish_skeleton()
    result = BuildResult(skeleton=sk, dropped_moves=[{
        "move": "loop pass 1 Boots",
        "exception": "WorkerContractError",
        "failure_state": "bad_payload",
        "message": "payload rejected",
    }])

    p._finish(result, sk, 0.0)

    assert "dropped moves: 1" in result.summary()
    assert [(finding.severity, finding.check) for finding in result.audit] == [("warning", "dropped moves")]


def test_summary_reports_zero_dropped_moves() -> None:
    result = BuildResult(skeleton=_skeleton({}))

    assert "dropped moves: 0" in result.summary()


class _ValueWishlist(_TemplateLoot):
    """A template filler for spec 2026-09-26-template-loop-lines-by-value: records `flexible_by_value` at every fill
    and carries what the kicks read from a wishlist filler."""

    def __init__(self, pob, script, calls=None) -> None:
        super().__init__(pob, script, calls)
        self.flexible_by_value = False
        self.flags: list[bool] = []
        self._resistance_assignments = {}
        self.resistance_plan = {}

    def item_level_for(self, slot: str) -> int:
        return 72

    def preselect_bases(self, slots, rare_bases, sockets_of):
        return {s: SimpleNamespace(base=rare_bases[s]) for s in slots}

    def fill_slot(self, slot, base, *, n=None, sockets=None, seed=1, replan_resistance=False, _base_candidates=None, order="floors"):
        self.flags.append(self.flexible_by_value)
        return super().fill_slot(slot, base, n=n, sockets=sockets, seed=seed)


def test_the_loop_re_fills_a_template_slot_by_value_only_on_a_feasible_build(monkeypatch) -> None:
    import junkroan.optimizer.improvement_loop as improvement_loop_module
    import junkroan.optimizer.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "WishlistGear", _ValueWishlist)
    flags = {}
    for label, life in (("feasible", 5000.0), ("missing Life", 3000.0)):
        pob = _Pob(1000.0, life=life)
        tree = _Tree(pob, [1100.0])  # a kept refine: the pass is not empty, so no kick fills a slot after the gear move
        loot = _ValueWishlist(pob, {"Boots": [("b1", 1101.0, life)]})
        sk = _skeleton({"Boots": "Two-Toned Boots"})
        _patch_generator(monkeypatch, [])
        p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
        p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))
        flags[label] = (loot.flags[0], loot.flexible_by_value)

    assert flags == {"feasible": (True, False), "missing Life": (False, False)}


def test_a_rejected_value_re_fill_is_not_tried_again_while_nothing_changed(monkeypatch) -> None:
    import junkroan.optimizer.improvement_loop as improvement_loop_module
    import junkroan.optimizer.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "WishlistGear", _ValueWishlist)
    pob = _Pob(1000.0)
    logs: list[str] = []
    tree = _Tree(pob, [1100.0])  # pass 1 keeps the refine before the gear move; pass 2 keeps nothing
    loot = _ValueWishlist(pob, {"Boots": [("b1", 1101.0)]})  # +0.1%: below min_gain, the judge reverts it
    sk = _skeleton({"Boots": "Two-Toned Boots"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)

    p.run(LoopPlan(seed=1, max_passes=2, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert loot.flags.count(True) == 1  # pass 2's gear move made no fill; the kicks' fills are never by value
    assert any("value re-fill skipped, nothing changed since the last rejected trial" in m for m in logs)
    assert loot.flexible_by_value is False


# -- #38: `loop_stop` (BuildPipeline.run reads `LoopOutcome.stopped` through `loop_stop_label`) ----


def test_a_zero_time_budget_stops_the_loop_on_its_first_move(monkeypatch) -> None:
    """`ImprovementLoop.run` checks its budget before every move in the plan (pipeline.py ~1251); a
    budget of 0 s is exhausted before the first one, which is the smallest unit that reaches the
    "time budget" stop without a real PoB session or a mocked clock."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1100.0])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    outcome = p.run(LoopPlan(seed=1, max_passes=4, max_seconds=0.0, min_gain=0.005, loot_n=5))
    note = outcome.note

    assert outcome.stopped == "time budget"
    assert "stopped: time budget" in note
    assert loop_stop_label(outcome.stopped) == "time"


def test_a_pass_that_keeps_nothing_maps_to_converged(monkeypatch) -> None:
    """The ordinary fixed point (`test_a_pass_that_keeps_nothing_is_the_fixed_point`'s own scenario):
    `LoopOutcome.stopped` stays "" and `loop_stop_label` reads that as "converged"."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1001.0])  # +0.1%, below min_gain: the pass keeps nothing
    loot = _Loot(pob, {"Gloves": [("g1", 1002.0)], "Boots": [("b1", 1003.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    result = p.started()

    outcome = p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5))
    note = outcome.note

    assert outcome.stopped == ""
    assert "fixed point after 1 pass" in note
    assert loop_stop_label(outcome.stopped) == "converged"


def test_max_passes_also_reads_as_converged() -> None:
    """`loop_stop` names only two states (converged / time, #38): a pass-limit stop -- rare, the
    default is 16 -- is not a third one; `_fixed_point_check` treats it the same as the time budget
    (both are "not at a fixed point"), but `loop_stop_label` groups it with "converged" since it is
    not the time budget."""

    assert loop_stop_label("max passes") == "converged"
