"""#51 unit 2: the improvement loop's plan types and its two pure planning functions."""

from __future__ import annotations

import dataclasses

import pytest

from junkroan.optimizer.improvement_loop import (
    FIXED_POINT_SEED_OFFSET, LOOP_MOVES, LoopPlan, _LoopState, kick_plan, pass_plan,
)

SLOTS = ["Weapon 1", "Body Armour", "Helmet"]
WB = ["Weapon 1"]


def test_kind_flags():
    base = dict(seed=1, max_passes=2, max_seconds=60.0)
    loop = LoopPlan(**base)
    extra = LoopPlan(**base, kind="extra pass")
    replay = LoopPlan(**base, kind="replay")
    assert (loop.local_only, loop.opening_lanes, loop.stage_name) == (False, True, None)
    assert (extra.local_only, extra.opening_lanes, extra.stage_name) == (True, False, "fixed point check")
    assert (replay.local_only, replay.opening_lanes, replay.stage_name) == (False, False, None)


def test_unknown_move_raises():
    with pytest.raises(ValueError, match="nonsense"):
        LoopPlan(seed=1, max_passes=1, max_seconds=None, moves=frozenset({"refine", "nonsense"}))
    with pytest.raises(ValueError):
        LoopPlan(seed=1, max_passes=1, max_seconds=None, moves=frozenset({"anoint"}))
    LoopPlan(seed=1, max_passes=1, max_seconds=None, moves=LOOP_MOVES)


def test_move_set():
    assert LOOP_MOVES == {"refine", "swaps", "corridors", "regions", "ascendancy-swap", "gear", "weapon-base", "picks",
                          "aura levels", "lanes", "kick-tree", "kick-joint"}


def test_extra_pass():
    plan = LoopPlan(seed=7, max_passes=5, max_seconds=90.0, min_gain=0.01, loot_n=4, kick_draws=(1, 2),
                    moves=frozenset({"refine"}))
    extra = plan.extra_pass()
    assert FIXED_POINT_SEED_OFFSET == 1_000_003
    assert extra == LoopPlan(seed=7 + 1_000_003, max_passes=1, max_seconds=90.0, min_gain=0.01, loot_n=4,
                             kick_draws=(1, 2), kind="extra pass", moves=None)
    assert plan.kind == "loop"  # frozen: the original is unchanged
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.seed = 1  # type: ignore[misc]


def test_replay_equals_replay_bench_arguments():
    # scripts/replay_bench.py 289 and 317-330: selected = None if move == "loop" else frozenset((move,));
    # loot_n=None, max_passes=passes if move == "loop" else 1, max_seconds=None, min_gain=0.005,
    # opening_lanes=False (local_only False, kick_draws default)
    loop = LoopPlan.replay("loop", seed=5, passes=3)
    assert (loop.seed, loop.max_passes, loop.max_seconds, loop.min_gain, loop.loot_n, loop.kick_draws, loop.moves) == (5, 3, None, 0.005, None, (3, 4), None)
    assert (loop.local_only, loop.opening_lanes) == (False, False)
    gear = LoopPlan.replay("gear", seed=5, passes=3)
    assert gear.max_passes == 1 and gear.moves == frozenset({"gear"}) and gear.kind == "replay"
    with pytest.raises(ValueError):
        LoopPlan.replay("anoint", seed=5, passes=3)


# pipeline.py 1416: refine, swaps, gear per slot, weapon-base per slot, picks, [aura levels], [lanes]
def test_pass_plan_default():
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=None) == [
        ("refine", 0, ""), ("swaps", 0, ""),
        ("gear", 0, "Weapon 1"), ("gear", 1, "Body Armour"), ("gear", 2, "Helmet"),
        ("weapon-base", 0, "Weapon 1"), ("picks", 0, ""), ("lanes", 0, ""),
    ]


# #1157: the ascendancy swap sits after the path swaps and before the gear, only when the rails give points
def test_pass_plan_ascendancy_entry():
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=None, has_ascendancy_points=True) == [
        ("refine", 0, ""), ("swaps", 0, ""), ("ascendancy-swap", 0, ""),
        ("gear", 0, "Weapon 1"), ("gear", 1, "Body Armour"), ("gear", 2, "Helmet"),
        ("weapon-base", 0, "Weapon 1"), ("picks", 0, ""), ("lanes", 0, ""),
    ]
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"ascendancy-swap"}), has_ascendancy_points=True) == [
        ("ascendancy-swap", 0, "")]
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"ascendancy-swap"})) == []


def test_pass_plan_aura_flag():
    plan = pass_plan(SLOTS, WB, has_flat_reservation_aura=True, local_only=False, moves=None)
    assert plan[-3:] == [("picks", 0, ""), ("aura levels", 0, ""), ("lanes", 0, "")]
    assert len(plan) == 9


def test_pass_plan_local_only_drops_lanes():
    plan = pass_plan(SLOTS, WB, has_flat_reservation_aura=True, local_only=True, moves=None)
    assert plan[-2:] == [("picks", 0, ""), ("aura levels", 0, "")]
    assert ("lanes", 0, "") not in plan


def test_pass_plan_empty_slots():
    assert pass_plan([], [], has_flat_reservation_aura=False, local_only=False, moves=None) == [
        ("refine", 0, ""), ("swaps", 0, ""), ("picks", 0, ""), ("lanes", 0, "")]


# pipeline.py 1417-1422: regions inserted right after swaps, corridors first, then the filter by name
def test_pass_plan_moves_filter():
    full = frozenset({"corridors", "regions", "refine", "swaps", "gear"})
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=full) == [
        ("corridors", 0, ""), ("refine", 0, ""), ("swaps", 0, ""), ("regions", 0, ""),
        ("gear", 0, "Weapon 1"), ("gear", 1, "Body Armour"), ("gear", 2, "Helmet"),
    ]
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"regions"})) == [("regions", 0, "")]
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"corridors"})) == [("corridors", 0, "")]
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"weapon-base", "picks"})) == [
        ("weapon-base", 0, "Weapon 1"), ("picks", 0, "")]
    # a move named but absent from the pass (no aura flag) yields nothing for it
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"aura levels"})) == []
    # kick names in moves select no pass entry
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=False, moves=frozenset({"kick-tree"})) == []
    # local_only with "lanes" named: lanes is not built, so it is filtered away
    assert pass_plan(SLOTS, WB, has_flat_reservation_aura=False, local_only=True, moves=frozenset({"lanes"})) == []


# pipeline.py 1681-1699
def test_kick_plan():
    both = dict(notes=[], stopped="", local_only=False, moves=None, kick_draws=(3, 4))
    assert kick_plan(**both) == [("kick-tree", 3), ("kick-joint", 4)]
    assert kick_plan(**{**both, "notes": ["gear kept"]}) == []
    assert kick_plan(**{**both, "stopped": "time budget"}) == []
    assert kick_plan(**{**both, "local_only": True}) == []
    assert kick_plan(**{**both, "moves": frozenset({"kick-tree"})}) == [("kick-tree", 3)]
    assert kick_plan(**{**both, "moves": frozenset({"kick-joint"})}) == [("kick-joint", 4)]
    assert kick_plan(**{**both, "moves": frozenset({"refine"})}) == []
    assert kick_plan(**{**both, "moves": frozenset({"kick-tree", "kick-joint"}), "kick_draws": (1, 2)}) == [("kick-tree", 1), ("kick-joint", 2)]
    assert kick_plan(**{**both, "kick_draws": (0, 2)}) == [("kick-tree", 0), ("kick-joint", 2)]


def test_loop_state_starts_where_the_loop_locals_started():
    """#51 unit 3: the values the loop's old pipeline method initialised its locals with."""
    st = _LoopState()
    assert (st.kept_total, st.attempted_total, st.judged_reverted_total, st.p, st.stopped) == (0, 0, 0, 0, "")
    assert (st.lanes_fresh, st.changed_since_picks, st.changed_since_aura_levels, st.changed_since_lanes) == (False, True, True, False)
    assert st.tree_kept_this_pass is False and st.cur is None
    assert st.last_rejected_weapon_base == {} and st.last_rejected_value_fill == {} and st.notes == []
    other = _LoopState()
    st.last_rejected_weapon_base["Weapon 1"] = ("x",)
    st.notes.append("n")
    assert other.last_rejected_weapon_base == {} and other.notes == []  # one state per call, nothing shared
