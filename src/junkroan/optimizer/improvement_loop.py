"""The improvement loop's plan types and its two pure planning functions (#51, unit 2).

Nothing here imports pipeline.py or touches PoB: `pass_plan` and `kick_plan` return the lists
the old `BuildPipeline` loop method (since removed) built inline, and
`LoopPlan` names the three combinations of flags a caller uses today.
"""

from __future__ import annotations

import copy
import random
import re
import time
from dataclasses import dataclass, field, replace
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping

from junkroan.optimizer.anoint_line import anoint_of, apply_anoint
from junkroan.optimizer.item_bases import base_record, bases_of_type, implicit_of, raw_base_of, type_of
from junkroan.optimizer.judging import MOVE, worse_input
from junkroan.optimizer.loot_gear import LootGear, base_refused, drop_weapon_all_gems, forced_mod_choices, ordered_slots, raw_refused, replaced_refused, weapons_first
from junkroan.optimizer.castability import castability_violations
from junkroan.optimizer.objective import Objective, ScoreOrder, accepts_under, better_score, score_key
from junkroan.optimizer.red_line_gate import red_lines_blocking
from junkroan.optimizer.repair import REPAIR_GAIN_FLOOR, REPAIR_MAX_PASSES
from junkroan.optimizer.seeds import (
    PURPOSE_HEADROOM_ROLLS,
    PURPOSE_HEADROOM_SLOTS,
    PURPOSE_JOINT_FILL_SLOT,
    PURPOSE_JOINT_KICK_RNG,
    PURPOSE_JOINT_ROUND,
    PURPOSE_LOOP_FILL_SLOT,
    PURPOSE_TREE_KICK,
    derive_seed,
)
from junkroan.optimizer.snapshot import FILLER_ALL, FILLER_RAW, Snapshotter, filler_slot
from junkroan.optimizer.socket_step import candidate_sockets
from junkroan.optimizer import yield_probe
from junkroan.optimizer.stage_catalog import loop_move_line, start_line
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_1158 import stamp as base_swap_stamp
from junkroan.optimizer.tree_hygiene import DEAD_ASCENDANCY_SHARE, ascendancy_node_names, ascendancy_swap_candidates, dead_ascendancy_nodes
from junkroan.optimizer.wishlist_gear import WishlistGear, is_shield_gem_level_with_other
from junkroan.pob.headless_runtime_worker import WorkerContractError
from junkroan.pob.host_runtime import PoBHeadlessHostContractError
from junkroan.report_format import human_duration

if TYPE_CHECKING:  # no runtime import: no cycle with pipeline.py
    from junkroan.optimizer.build_result import BuildResult
    from junkroan.optimizer.judging import Judging
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.objective import Score
    from junkroan.optimizer.tree_optimizer import TreeOptimizer
    from junkroan.search.skeleton import Skeleton

PATH_SWAP_REPLAY_STEPS = 12  # #569: a rejected batch holds one step per kept swap, which max_failures does not bound
# #569: every move's budget is a count; the loop's own `max_seconds` is the only clock, and since #956 it is None unless a run
# is started with `--loop-seconds` by hand: no wall clock decides where a build's search stops (its bounds are max_passes, min_gain, the counts)
WEAPON_BASE_TYPES = frozenset({
    "Wand", "Sceptre", "Dagger", "Claw", "One Handed Sword", "One Handed Axe", "One Handed Mace",
    "Staff", "Two Handed Sword", "Two Handed Axe", "Two Handed Mace", "Bow",
})
_ITEM_AFFIX = re.compile(r"^(Prefix|Suffix):\s*(?:\{range:([^}]+)\})?(.*)$")
WEAPON_BASE_NUMBER_LABELS = ("Critical Strike Chance", "Attacks per Second", "Physical Damage")

FIXED_POINT_SEED_OFFSET = 1_000_003  # far from the loop's own 977 * pass and 7919 * pass: the extra pass rolls other gear
FIXED_POINT_MAX_EXTRA_PASSES = 3  # #800: the extra pass repeats until one keeps nothing, at most this many times

# Every name the loop accepts in `moves`: the plan entries of pipeline.py 1416-1421 and "kick-tree" /
# "kick-joint" of 1695 (the replay bench's --move adds names that are not loop moves: anoint, sockets, ...).
LOOP_MOVES = frozenset({
    "refine", "swaps", "corridors", "regions", "ascendancy-swap", "gear", "weapon-base", "picks", "aura levels", "lanes",
    "kick-tree", "kick-joint",
})


@dataclass
class WorkingBuild:
    """The build a loop works on."""

    pob: Any  # PobSession, RecordingPob or a test fake
    judging: Judging
    skeleton: Skeleton
    gear: LootGear  # or WishlistGear
    tree: TreeOptimizer


@dataclass(frozen=True)
class LoopPlan:
    seed: int
    max_passes: int
    max_seconds: float | None
    min_gain: float = 0.005
    loot_n: int | None = None
    kick_draws: tuple[int, ...] = (3, 4)  # () = no kicks (the repair, #1064)
    kind: Literal["loop", "extra pass", "replay", "repair"] = "loop"
    moves: frozenset[str] | None = None
    gain_floor: float = 0.0  # #1064: the repair's per-pass floor (repair.py); carried for the caller, the loop does not stop on it
    first_pass: int = 1  # #1064: the number the run's first pass carries ("repair pass 2" when the repair runs its second pass alone)

    def __post_init__(self) -> None:
        if self.kind not in ("loop", "extra pass", "replay", "repair"):
            raise ValueError(f"unknown loop kind {self.kind!r}")
        if self.first_pass < 1:
            raise ValueError(f"first_pass must be at least 1, got {self.first_pass}")
        if self.moves is not None:
            unknown = sorted(set(self.moves) - LOOP_MOVES)
            if unknown:
                raise ValueError(f"unknown loop move(s) {unknown}; legal moves: {', '.join(sorted(LOOP_MOVES))}")

    def extra_pass(self, repeat: int = 0, *, max_seconds: float | None = None) -> "LoopPlan":
        """The fixed-point check's one pass (pipeline.py 1846-1848). `repeat` k >= 1 is the check's k-th repeat (#800): its
        own seed (offset by k more offsets, or it would re-roll the gear the pass before it rolled) and, when the caller
        passes it, the time that is left of the check's budget instead of the plan's whole `max_seconds`."""
        return LoopPlan(seed=self.seed + (1 + repeat) * FIXED_POINT_SEED_OFFSET, max_passes=1,
                        max_seconds=self.max_seconds if max_seconds is None else max_seconds,
                        min_gain=self.min_gain, loot_n=self.loot_n, kick_draws=self.kick_draws,
                        kind="extra pass", moves=None)

    @classmethod
    def replay(cls, move: str, *, seed: int, passes: int) -> "LoopPlan":
        """Exactly what scripts/replay_bench.py passes to the loop (lines 289, 317-330)."""
        return cls(seed=seed, max_passes=passes if move == "loop" else 1, max_seconds=None, min_gain=0.005,
                   loot_n=None, kind="replay", moves=None if move == "loop" else frozenset((move,)))

    @classmethod
    def repair(cls, *, seed: int) -> "LoopPlan":
        """#1064: the repair of a keystone choice on a finished build (repair.py). At most REPAIR_MAX_PASSES passes of
        the loop's own moves, no kicks, no time limit; the caller runs one pass at a time and reads each pass's gain
        with `repair.should_continue` (the loop itself does not stop on `gain_floor`). Named "repair pass N"."""
        return cls(seed=seed, max_passes=REPAIR_MAX_PASSES, max_seconds=None, min_gain=0.005, loot_n=None,
                   kick_draws=(), kind="repair", moves=None, gain_floor=REPAIR_GAIN_FLOOR)

    @property
    def pass_prefix(self) -> str:
        """The word a pass and its moves are named with: "repair" for the repair, "loop" otherwise."""
        return "repair" if self.kind == "repair" else "loop"

    def pass_label(self, pass_no: int) -> str:
        return f"{self.pass_prefix} pass {pass_no}"

    @property
    def order(self) -> ScoreOrder:
        """The Score order the plan's moves are chosen and kept by: the loop's "priced" one; the fixed-point extra pass
        runs after the final lanes under `_finish`'s feasibility guard and keeps "floors" (#553)."""
        return "floors" if self.kind == "extra pass" else "priced"

    @property
    def local_only(self) -> bool:
        return self.kind == "extra pass"

    @property
    def opening_lanes(self) -> bool:
        return self.kind == "loop"

    @property
    def stage_name(self) -> str | None:
        return "fixed point check" if self.kind == "extra pass" else None


@dataclass(frozen=True)
class LoopOutcome:
    note: str  # today's return string
    stopped: str  # "", "time budget", "max passes"
    kept: tuple[str, ...]  # the last pass's notes
    counts: Mapping[str, int]  # attempted / kept / not_kept / judged_and_reverted / closing_repair_kept (#1008)
    passes: int


@dataclass
class _LoopState:
    """The mutable per-run locals of the loop (#51, unit 3): one per call, every
    closure of the loop reads and writes them as `st.<name>` instead of `nonlocal`. `cur` is set by the loop's
    opening `score_now()`."""

    cur: Score | None = None  # the Score of the build PoB holds now
    kept_total: int = 0
    attempted_total: int = 0  # every plan entry and kick draw started, the lane step and skipped draws included
    judged_reverted_total: int = 0  # only the moves `judge` actually measured and rejected
    # #1008: the tree changes (one `Step` of `tree.refine`'s result = one swap) the closing cost repair kept. A counter
    # beside `kept_total`, never in it: `kept_total` counts moves, and the repair is not a move of the plan (no row in
    # `result.moves`, no `attempted_total` entry), so `kept` / `not_kept` of `LoopOutcome.counts` keep their meaning.
    closing_repair_kept: int = 0
    # the loop's config invariant: `lanes_fresh` is True when the config PoB currently holds is the
    # lane derivation for the build as it currently stands. A snapshot exported while it holds carries
    # those lanes in its own <Config>, so the revert that loads it needs no second derivation (7.1h).
    # False until the loop's own opening derivation (`_tune_lanes` ends in a reconfigure).
    lanes_fresh: bool = False
    changed_since_picks: bool = True  # the picks move runs when a tree, gear or kick move changed the build since it last ran
    changed_since_aura_levels: bool = True  # levels follow every move that can change reservation room
    changed_since_lanes: bool = False  # the choices are judged again at the end of a pass whose moves changed the build
    tree_kept_this_pass: bool = False
    last_rejected_weapon_base: dict[str, tuple] = field(default_factory=dict)
    last_rejected_value_fill: dict[str, tuple] = field(default_factory=dict)
    p: int = 0  # the pass number; 0 before pass 1
    where: str = ""  # the name every move row of the current pass logs under
    notes: list[str] = field(default_factory=list)  # what the current pass kept
    stopped: str = ""


CONTRACT_ERRORS = (PoBHeadlessHostContractError, WorkerContractError)
COST_CLOSE_ROUNDS = 4  # #941 (b): the most repair rounds of the loop's last cost check (the delivered build's final floor repair uses 4)


class RestoreFailedError(RuntimeError):
    """A move's restore failed after the move's own error (#805); its text starts with the first error."""


def _restore_failure_after(first: BaseException, failure: Exception) -> Exception:
    """The exception that escapes `Attempt.__exit__` when the restore fails: its text starts with the FIRST error
    (what a build's row prints), the restore's own failure follows. A failure whose text already starts with the
    first one (a dead handle's refusal carries it, #724) is kept as it is; a contract failure keeps its type and
    failure_state, any other becomes a `RestoreFailedError`; either way the build still fails."""

    first_text = str(first)
    if str(failure).startswith(first_text):
        return failure
    text = f"{first_text} (the restore after it failed: {type(failure).__name__}: {failure})"
    if isinstance(failure, PoBHeadlessHostContractError):
        return PoBHeadlessHostContractError(failure.failure_state, text)
    return RestoreFailedError(text)


def accepts(new: Score, cur: Score, *, min_gain: float, order: ScoreOrder = "priced") -> bool:
    """The one acceptance rule of the loop: every judged move, the path-swap replay's steps and the aura
    levels are kept by this and nothing else (objective.better_loop_score, D116 / #553: the priced score).
    The fixed-point extra pass runs it in the "floors" order (`LoopPlan.order`): it may not lower feasibility."""

    return accepts_under(order)(new, cur, min_gain=min_gain)


@dataclass(frozen=True)
class AttemptTools:
    """What one attempt needs from the loop, as callables, so `Attempt` imports nothing of pipeline.py.

    `st` is the loop's `_LoopState`; `snapshot()` is the loop's `snapshot_move` (quirk 1's order), `restore(state,
    keep_rejections=False)` its `restore_move` (the full restore), `rejudge()` the judging's re-derivation of the
    lanes for the loop's skeleton, `restore_mark(mark, only)` the judging's `restore(mark, only=only)`, `score()`
    the objective's Score of the build PoB holds, `record(...)` the ledger row, `note_drop(row)` the
    `dropped_moves` row; `fresh_costs(score)` (#941) installs the skill costs the build now has and returns the Score
    under them (the given one when no cost moved)."""

    st: _LoopState
    snapshot: Callable[[], dict[str, Any]]
    restore: Callable[..., None]
    rejudge: Callable[[], None]
    restore_mark: Callable[[Any, tuple[str, ...] | None], None]
    score: Callable[[], Score]
    record: Callable[..., None]
    note_drop: Callable[[dict[str, str]], None]
    log: Callable[[str], None]
    min_gain: float
    order: ScoreOrder = "priced"
    fresh_costs: Callable[[Score], Score] | None = None  # #941: the Score under the skill costs as the move left them (None: the frozen ones stand)

    def attempt(self, label: str, *, ledger_name: str | None = None, started: float | None = None,
                before: Score | None = None, armed: bool = True) -> "Attempt":
        return Attempt(self, label, ledger_name=ledger_name, started=started, before=before, armed=armed)


class Attempt:
    """One move's transaction (#51, unit 4): `with tools.attempt(label, ...) as attempt:`.

    Entering takes the snapshot (`attempt.state`). A `PoBHeadlessHostContractError` or `WorkerContractError`
    raised inside the `with` drops the move: the full restore (a failure of it escapes), the `dropped_moves` row,
    the log line and the ledger row; `attempt.dropped` says it happened. Every other exception propagates.

    `started` is the move's clock (None: taken right after the snapshot); `before` is the drop row's `before`
    (quirk 12): None reads the loop's `cur` at the moment of the exception, a Score is the value the site
    captured before the move. `armed=False` keeps the drop off until `arm()`: the pre-checks that follow the
    snapshot but sit outside the error guard (quirk 9).

    `judge_exact` and `judge_partial` are the two revert contracts; both end in the one rule, `accepts`."""

    def __init__(self, tools: AttemptTools, label: str, *, ledger_name: str | None, started: float | None,
                 before: Score | None, armed: bool) -> None:
        self.tools = tools
        self.label = label
        self.ledger_name = ledger_name
        self.started = started
        self._before = before
        self._armed = armed
        self.state: dict[str, Any] = {}
        self.dropped = False

    def __enter__(self) -> "Attempt":
        self.state = self.tools.snapshot()
        if self.started is None:
            self.started = time.perf_counter()
        return self

    def arm(self) -> None:
        self._armed = True

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if exc is None or not self._armed or not isinstance(exc, CONTRACT_ERRORS):
            return False
        tools, st = self.tools, self.tools.st
        before = self._before if self._before is not None else st.cur  # read before the restore moves `cur`
        restore_failure: Exception | None = None
        try:
            tools.restore(self.state)
        except Exception as failure:  # a recovery failure intentionally escapes, behind the first error (#805)
            restore_failure = failure
        if restore_failure is not None:
            raise _restore_failure_after(exc, restore_failure) from restore_failure
        failure_state = str(getattr(exc, "failure_state", ""))
        tools.note_drop({
            "move": self.label,
            "exception": type(exc).__name__,
            "failure_state": failure_state,
            "message": str(exc),
        })
        tools.log(f"{self.label}: dropped after {type(exc).__name__} ({failure_state}): {exc}")
        tools.record(self.ledger_name or self.label, self.started, before, st.cur, kept=False)
        self.dropped = True
        return True

    def judge_exact(self, label: str | None = None) -> bool:
        """Revert contract EXACT: the full snapshot restore with `keep_rejections=True`, the castability refold,
        no rejudge (the snapshot's XML carries its own lanes), then a rescore. The tree moves, the corridors and
        regions and the weapon base use it; the lanes are derived again by the judge before the verdict."""

        return self._judge(label, lambda: self.tools.restore(self.state, keep_rejections=True),
                           reconfigured=False, restores_exact=True)

    def judge_partial(self, undo: Callable[[], None], label: str | None = None, *, reconfigured: bool = False, must_keep: bool = False) -> bool:
        """Revert contract PARTIAL: the move's own `undo`, the castability refold, `rejudge` unless the snapshot's
        lanes were fresh, then a rescore. Gear, the tree kick and the joint kick use it (`reconfigured`: the
        move derived its own lanes already, so the judge does not before the verdict). `must_keep` (#1152): the trial moved
        a slot off an item a current restriction refuses (`replaced_refused`), so its revert would put that item back; the
        trial is kept whatever it scores, and the ledger and `st.cur` say what it scores."""

        return self._judge(label, undo, reconfigured=reconfigured, restores_exact=False, must_keep=must_keep)

    def _judge(self, label: str | None, revert: Callable[[], None], *, reconfigured: bool, restores_exact: bool, must_keep: bool = False) -> bool:
        tools, st = self.tools, self.tools.st
        label = label if label is not None else self.label
        t0 = self.started
        snapshot_fresh = self.state["lanes_fresh"]
        snapshot_mark = self.state["judging"]
        before_score = st.cur
        if not reconfigured:
            tools.rejudge()  # a move is judged under the lanes its own change earns, never the old proof (D45)
        st.lanes_fresh = True
        new = tools.score()
        keep = must_keep or accepts(new, st.cur, min_gain=tools.min_gain, order=tools.order)
        if keep and tools.fresh_costs is not None:
            # #941 (a): the verdict above ran under the skill costs frozen at the pass start; a kept move is judged again under
            # the costs it left (a curse's ManaCost its gear or support raised), and only the kept ones pay for the read
            new = tools.fresh_costs(new)
            keep = must_keep or accepts(new, st.cur, min_gain=tools.min_gain, order=tools.order)
        if keep:
            tools.log(f"{label}: {st.cur.value:,.0f} (viol {st.cur.violation:.3f}) -> {new.value:,.0f} (viol {new.violation:.3f}) kept" + (" (the revert would restore an item a restriction refuses)" if must_keep else "") + f" ({time.perf_counter() - t0:.0f}s)")
            st.cur = new
            st.kept_total += 1
            st.changed_since_picks = True
            st.changed_since_aura_levels = True
            st.changed_since_lanes = True
            tools.record(self.ledger_name or label, t0, before_score, new, kept=True)
            return True
        tools.log(f"{label}: {new.value:,.0f} (viol {new.violation:.3f}) vs {st.cur.value:,.0f} (viol {st.cur.violation:.3f}), reverted ({time.perf_counter() - t0:.0f}s)")
        st.judged_reverted_total += 1
        revert()
        if snapshot_mark is not None:
            # #35 Q2: a castability refold only, when the lanes are derived again below (they re-derive the
            # rest); a fresh snapshot is not re-derived, so the whole mark goes back with it (#34)
            tools.restore_mark(snapshot_mark, None if snapshot_fresh else ("castability",))
        if not snapshot_fresh and not restores_exact:
            tools.rejudge()  # the revert puts the lanes back too, so the next move starts where this one did
        st.cur = tools.score()
        tools.record(self.ledger_name or label, t0, before_score, st.cur, kept=False, reverted_by_judge=True)
        return False


def pass_plan(slots: list[str], weapon_base_slots: list[str], *, has_flat_reservation_aura: bool,
              local_only: bool, moves: frozenset[str] | None, has_ascendancy_points: bool = False) -> list[tuple[str, int, str]]:
    """The `(kind, i, slot)` entries of one pass, pipeline.py 1416-1422.

    `slots` is `ordered_slots(rare)`; `weapon_base_slots` is the list of 1038-1041. `has_ascendancy_points` (#1157): the
    loop was given the rails' ascendancy points, so the ascendancy swap runs after the path swaps."""

    plan = ([("refine", 0, ""), ("swaps", 0, "")]
            + ([("ascendancy-swap", 0, "")] if has_ascendancy_points else [])
            + [("gear", i, s) for i, s in enumerate(slots)]
            + [("weapon-base", i, s) for i, s in enumerate(weapon_base_slots)]
            + [("picks", 0, "")]
            + ([("aura levels", 0, "")] if has_flat_reservation_aura else [])
            + ([] if local_only else [("lanes", 0, "")]))
    if moves is not None:
        if "regions" in moves:
            after_swaps = plan.index(("swaps", 0, "")) + 1
            plan = plan[:after_swaps] + [("regions", 0, "")] + plan[after_swaps:]
        plan = [("corridors", 0, "")] + plan if "corridors" in moves else plan
        plan = [entry for entry in plan if entry[0] in moves]
    return plan


def kick_plan(*, notes: list[str] | tuple[str, ...], stopped: str, local_only: bool,
              moves: frozenset[str] | None, kick_draws: tuple[int, ...]) -> list[tuple[str, int]]:
    """The kick groups of one pass in the loop's order, pipeline.py 1681-1695: `("kick-tree", draws)`
    and `("kick-joint", draws)`; draw `d` of a group runs for `d in range(draws)`. Empty when the
    kicks do not run (a move was kept, the loop stopped, or this is the local-only extra pass)."""

    if notes or stopped or local_only or not kick_draws:  # () = no kicks (the repair, #1064)
        return []
    kicks = [("kick-tree", kick_draws[0]), ("kick-joint", kick_draws[1])]
    if moves is not None:
        kicks = [(name, draws) for name, draws in kicks if name in moves]
    return kicks


# -- loop-only helpers moved from BuildPipeline (#51, unit 5a) ----------------------------------------


def _slots_with_damage_headroom(pob: Any, objective: Objective, rails: Rails, skeleton: Skeleton, loot: LootGear | WishlistGear, slots: list[str], loot_n: int | None, seed: int) -> list[str]:
    """Rare slots ranked by how much the maximized stat would gain if the slot were
    refilled for damage alone (best of a loot roll under the objective without
    floors): the joint stage (D44) empties those first. Poison Spectral Throw: one
    seed's random pick of the right slot gave +23%, the other two seeds never hit it."""

    damage_only = objective.replace(floors={}, relations=())
    keys = damage_only.stat_keys
    base = damage_only.score(pob.stats(keys)).value
    ranked: list[tuple[float, str]] = []
    for j, slot in enumerate(slots):
        forced = getattr(skeleton, "forced_affixes", {}).get(slot) or []
        choices = forced_mod_choices(pob, skeleton.rare_bases[slot], forced, rails.gear.item_level) if forced else ()
        choices = [*choices, *loot.pinned_roll_choices(slot, skeleton.rare_bases[slot])]  # #600: a day-1 template roll carries the slot's pinned line (Boots: 30% increased Movement Speed)
        # #559: a roll of the ranking is a loop gear candidate, so it carries the incumbent's Sockets line as #548's fill does
        incumbent = loot.current_raw.get(slot)
        sockets = candidate_sockets(incumbent, skeleton.rare_bases[slot], skeleton.sockets.get(slot))
        rolls = pob.random_rares(skeleton.rare_bases[slot], n=max(40, (loot_n or rails.gear.loot_best_of_n) // 4), ilvl=rails.gear.item_level, quality=rails.gear.quality, seed=derive_seed(seed, PURPOSE_HEADROOM_ROLLS, j),
                                      **({"sockets": sockets} if sockets is not None else {}),
                                      **({"forced": choices} if choices else {}))  # a forced line rides every roll (#510)
        if slot == "Amulet":  # a roll for the amulet slot carries the build's anoint, as the equipped one will (#432)
            rolls = [{**r, "raw": apply_anoint(r["raw"], loot.anoint)} for r in rolls]
        best = base
        # #601: a random shield with a gem-level line beside any other line is never ranked (the gem line takes the whole shield)
        # #1152: nor one with the all-gems line on a weapon slot
        rolls = drop_weapon_all_gems(rolls, slot, rails, forced)
        roll_trials = [{"item": {"slot": slot, "raw": r["raw"]}} for r in rolls if not is_shield_gem_level_with_other(slot, r["raw"])]
        trial_outcomes = []
        if roll_trials:
            with TRACE.incumbent_sockets(slot, incumbent):
                TRACE.count_candidates(roll_trials)
                trial_outcomes = pob.trial_stats(roll_trials, keys, mode="fast")
        for o in trial_outcomes:
            if o.get("ok") and o.get("stats"):
                best = max(best, damage_only.score(o["stats"]).value)
        ranked.append((best - base, slot))
    ranked.sort(reverse=True)
    return [s for gain, s in ranked if gain > 0]


def _joint_round(pob: Any, objective: Objective, judging: Judging, skeleton: Skeleton, loot: LootGear | WishlistGear, tree: TreeOptimizer, *, i: int, seed: int, loot_n: int | None,
                 rng, ruin_points: int, slots_per_round: int, headroom: Callable[..., list[str]], refine_rounds: int = 6) -> str:
    """One round of the joint ruin-and-recreate (D44), the loop's "kick joint" move (the
    chain's `_joint_reoptimize` stage, its other caller, is gone with D58): two rare slots
    with damage headroom and a random
    tree branch are emptied, then both sides are rebuilt -- on even rounds the gear for damage
    alone and the tree re-spend repairs the floors, on odd rounds the other way round -- and a
    short refine follows. Returns what was ruined, for the caller's log line: keeping or
    reverting the round belongs to the caller, which holds the snapshot."""

    rare_slots = [s for s in skeleton.rare_bases if s not in skeleton.uniques]
    slots = headroom(skeleton, loot, rare_slots, loot_n, derive_seed(seed, PURPOSE_HEADROOM_SLOTS, i))[:slots_per_round] or rng.sample(rare_slots, min(slots_per_round, len(rare_slots)))
    # weapons first, the headroom ranking kept among the rest: a quiver or shield is only valid once the
    # main hand is back (a Bleed Bow seed died here), and a slot refilled with no weapon on is judged blind
    slots = weapons_first(slots)
    victims = tree._random_branches(tree.current_allocated(), ruin_points, rng)
    # #548: the candidates of a slot are judged under its incumbent's sockets, so the raw is taken before the pop
    incumbents = {s: loot.current_raw.get(s) for s in slots}
    sockets_of = {s: candidate_sockets(incumbents[s], skeleton.rare_bases[s], skeleton.sockets.get(s)) for s in slots}
    for s in slots:
        loot.current_raw.pop(s, None)
    pob.equip({s: None for s in slots})
    points = 0
    if victims:
        removed = pob.mutate_nodes(remove=victims)
        after_removal = getattr(tree, "after_real_removal", None)
        if callable(after_removal):
            after_removal(removed)
        points = len(removed["removed_node_ids"])

    damage_only = objective.replace(floors={}, relations=())

    def gear(objective: Objective) -> None:
        # `loot` is the attached "gear" view: it holds `objective` for the fill and gets its own back after
        with judging.lend("gear", objective), ExitStack() as traced:
            for s in slots:
                traced.enter_context(TRACE.incumbent_sockets(s, incumbents[s]))
            selected_bases = loot.preselect_bases(slots, skeleton.rare_bases, sockets_of)
            for j, s in enumerate(slots):
                loot.refill_victim_slot(s, skeleton.rare_bases[s], n=loot_n, sockets=sockets_of[s], seed=derive_seed(seed, PURPOSE_LOOP_FILL_SLOT, i, j), order="priced", preselected=selected_bases.get(s))
            tree.note_build_change()  # #34: the gear PoB holds moved; no hook Score cached on the old one may answer the allocate that follows

    def spend(objective: Objective) -> None:
        if not points:
            return
        with judging.lend("tree", objective):  # `tree` is the attached "tree" view
            tree.allocate(points, allocated=tree.current_allocated())

    # directed, not random: one side is rebuilt for damage alone, the other repairs the floors
    if i % 2 == 0:
        gear(damage_only)
        spend(tree.objective)
    else:
        spend(damage_only)
        gear(loot.objective)
    tree.refine(max_rounds=refine_rounds)
    # judged under lanes derived for the new tree and gear (as the rebuild, D45): a round that dropped the
    # node proving a lane condition (Deflection's endurance charges on Poison Spectral Throw) scored with the
    # old proof, was kept, and the final lanes then broke the EHP floor by 1%
    judging.rejudge(skeleton)
    return f"{slots} + {points} tree points"


def _weapon_item_parts(raw: str) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], int | None, str | None]:
    """Read the explicit mod ids, their rolls, crafted lines, quality and sockets from PoB raw text."""

    prefixes: list[dict[str, object]] = []
    suffixes: list[dict[str, object]] = []
    extra_lines: list[str] = []
    quality: int | None = None
    sockets: str | None = None
    for line in raw.splitlines():
        match = _ITEM_AFFIX.match(line)
        if match:
            mod_id = match.group(3).strip()
            if mod_id and mod_id != "None":
                try:
                    roll = float(match.group(2)) if match.group(2) is not None else 0.5
                except ValueError:
                    roll = 0.5
                entry = {"mod_id": mod_id, "range": roll}
                (prefixes if match.group(1) == "Prefix" else suffixes).append(entry)
            continue
        if line.startswith("{crafted}"):
            extra_lines.append(line)
        elif line.startswith("Quality:"):
            try:
                quality = int(line.split(":", 1)[1].strip().rstrip("%"))
            except ValueError:
                pass
        elif line.startswith("Sockets:"):
            sockets = line.split(":", 1)[1].strip() or None
    return prefixes, suffixes, extra_lines, quality, sockets


def _weapon_base_candidates(rails: Rails, loot: LootGear | WishlistGear, base: str) -> list[str]:
    return loot.other_weapon_bases(base)


def gear_move_base(slot: str, *, skeleton: Skeleton, loot: LootGear | WishlistGear) -> str | None:
    """The base the loop's `gear <slot>` move hands the filler (#1154): the incumbent's, unless the loadout excludes it
    (Prismatic Ring on day 1) and the request did not name it. Then the filler gets an allowed base of the class, the same
    candidates the base swap uses (a template ranks them all, a loot filler rolls that one), and the slot is trialed; the
    clean result stays whatever it scores (`replaced_refused`). None only when the class has no allowed base."""

    base = skeleton.rare_bases[slot]
    if not base_refused(getattr(loot, "rails", None), base, forced_base=getattr(skeleton, "forced_bases", {}).get(slot)):
        return base
    allowed = loot.other_weapon_bases(base)
    return allowed[0] if allowed else None


def base_swap_slots(slots: list[str], *, skeleton: Skeleton, loot: LootGear | WishlistGear, raw_base: Callable[[str], str]) -> list[str]:
    """The gear slots the base swap runs on (#1158): a rare slot (not a unique, not a forced base) whose base has another
    legal base for the loadout (`other_weapon_bases` applies the loadout's excluded bases, Prismatic Ring on day 1)."""

    forced = getattr(skeleton, "forced_bases", {})
    out: list[str] = []
    for slot in slots:
        if slot in skeleton.uniques or slot in forced:
            continue
        base = raw_base(loot.current_raw.get(slot, "")) or skeleton.rare_bases.get(slot, "")
        if base and loot.other_weapon_bases(base):
            out.append(slot)
    return out


def _weapon_raw_base(raw: str) -> str:
    """Find the equipped base, including when wishlist chose inside a class placeholder."""

    return raw_base_of(raw)


def _weapon_base_numbers(raw: str) -> dict[str, str]:
    """The base values PoB writes into raw weapon text, apart from the implicit."""

    numbers: dict[str, str] = {}
    for line in raw.splitlines():
        for label in WEAPON_BASE_NUMBER_LABELS:
            if line.startswith(label + ":"):
                numbers[label] = line.split(":", 1)[1].strip()
    return numbers


def _weapon_base_fingerprint(pob: Any, loot: LootGear | WishlistGear, skeleton: Skeleton, slot: str, *, config_xml: str | None = None) -> tuple:
    """The build surfaces that can make a base trial stale for this slot."""

    light_reader = getattr(pob, "tree_light", None)
    light = light_reader() if callable(light_reader) else {}
    lanes: tuple = ()
    rest: tuple = ()  # gems and every OTHER item: crit multiplier on a ring is what makes a high-crit base pay
    if config_xml:
        try:
            import hashlib
            from xml.etree import ElementTree as ET

            root = ET.fromstring(config_xml)
            rest = tuple(
                hashlib.sha1(ET.tostring(section)).hexdigest() if section is not None else ""
                for section in (root.find("Skills"), root.find("Items"))
            )
            config = root.find("Config")
            if config is not None:
                lanes = tuple(
                    (node.get("id"), tuple(sorted((child.tag, tuple(sorted(child.attrib.items()))) for child in node)))
                    for node in config.findall("ConfigSet")
                )
        except (ET.ParseError, ValueError):
            pass
    if not lanes:
        config_reader = getattr(pob, "config_inputs", None)
        config = config_reader() if callable(config_reader) else {}
        lanes = (("active", tuple(sorted((str(key), repr(value)) for key, value in (config or {}).items())),),)
    return (
        tuple(sorted(int(node) for node in (light or {}).get("user_allocated_node_ids") or ())),
        tuple(sorted(str(node) for node in (light or {}).get("mastery_effect_ids") or ())),
        lanes,
        rest,
        tuple(sorted((str(name), str(text)) for name, text in loot.current_raw.items())),
        skeleton.rare_bases.get(slot),
    )


def _weapon_base_move(
    pob: Any,
    objective: Objective,
    rails: Rails,
    log: Callable[[str], None],
    result: BuildResult,
    skeleton: Skeleton,
    loot: LootGear | WishlistGear,
    slot: str,
    *,
    current_score: Score,
    min_gain: float,
    move_state: Mapping[str, Any],
    snapshot_fresh: bool,
    t0: float,
    judge: Callable[..., bool],
    restore_move: Callable[..., None],
    last_rejected: dict[str, tuple],
    raw_base: Callable[[str], str],
    fingerprint_of: Callable[..., tuple],
    item_parts: Callable[[str], tuple],
    base_numbers: Callable[[str], dict[str, str]],
    candidates_of: Callable[[Any, str], list[str]],
    order: ScoreOrder = "priced",
) -> tuple[bool, str | None]:
    """Try the other legal bases in the equipped weapon's item class."""

    raw = loot.current_raw.get(slot)
    base = raw_base(raw) if raw else ""
    base = base or skeleton.rare_bases.get(slot)
    if not base or not raw or slot in skeleton.uniques or slot in getattr(skeleton, "forced_bases", {}):
        return False, None
    fingerprint = fingerprint_of(loot, skeleton, slot, config_xml=str(move_state.get("xml") or ""))
    if last_rejected.get(slot) == fingerprint:
        log(f"{slot} weapon base: skipped, nothing changed since the last rejected trial")
        return False, None

    prefixes, suffixes, extra_lines, quality, sockets = item_parts(raw)
    before_base_numbers = base_numbers(raw)
    candidates = candidates_of(loot, base)
    if not candidates:
        last_rejected[slot] = fingerprint
        return False, None
    trials: list[tuple[str, str]] = []
    ilvl = loot.item_level_for(slot)
    anoint = anoint_of(raw) if slot == "Amulet" else None
    for candidate in candidates:
        crafted = pob.craft_rare(
            candidate,
            prefixes=prefixes,
            suffixes=suffixes,
            ilvl=ilvl,
            quality=quality,
            sockets=sockets,
            extra_lines=extra_lines,
        )
        # a marked red line no longer skips the base (#1124); no lane is known here: marked on either lane passes
        if crafted.get("problems") or red_lines_blocking(crafted.get("unsupported_lines") or ()) or not crafted.get("raw"):
            item_type = type_of(base)
            result.weapon_base_skipped[item_type] = result.weapon_base_skipped.get(item_type, 0) + 1
            continue
        crafted_raw = apply_anoint(str(crafted["raw"]), anoint) if anoint else str(crafted["raw"])  # the swapped amulet keeps its anoint
        if not drop_weapon_all_gems([{"raw": crafted_raw}], slot, rails, getattr(skeleton, "forced_affixes", {}).get(slot)):
            continue  # #1152: the mod ids copied from the equipped item carry a line the weapon slot never carries (a recorded build's roll)
        trials.append((candidate, crafted_raw))
    if not trials:
        last_rejected[slot] = fingerprint
        return False, None

    pipe_trials = [base_swap_stamp({"item": {"slot": slot, "raw": candidate_raw}}) for _candidate, candidate_raw in trials]
    TRACE.count_candidates(pipe_trials)
    outcomes = pob.trial_stats(
        pipe_trials,
        objective.stat_keys,
        mode="fast",
    )
    best: tuple[Score, str, str] | None = None
    for (candidate, candidate_raw), outcome in zip(trials, outcomes):
        if not outcome.get("ok") or not outcome.get("stats"):
            continue
        score = objective.score(outcome["stats"])
        if best is None or score_key(order)(score) > score_key(order)(best[0]):  # D116: the plan's order
            best = (score, candidate, candidate_raw)
    if best is None or not accepts(best[0], current_score, min_gain=min_gain, order=order):
        last_rejected[slot] = fingerprint
        return False, None

    _fast_score, new_base, new_raw = best
    old_raw, old_base = raw, base
    pob.equip({slot: new_raw})
    loot.current_raw[slot] = new_raw
    skeleton.rare_bases[slot] = new_base

    def revert() -> None:
        restore_move(move_state, keep_rejections=True)

    kept = judge(
        f"{slot} weapon base {old_base} -> {new_base}",
        revert,
        t0,
        ledger_name="weapon base",
        snapshot_fresh=snapshot_fresh,
        restores_exact=True,
        snapshot_mark=move_state["judging"],
    )
    if kept:
        loot.carry_result(slot, old_raw, new_raw, base=new_base, implicit=implicit_of(new_base))
        if result.moves:
            result.moves[-1].update({
                "slot": slot,
                "base_before": old_base,
                "base_after": new_base,
                "base_numbers_before": before_base_numbers,
                "base_numbers_after": base_numbers(new_raw),
                "implicit_before": implicit_of(old_base),
                "implicit_after": implicit_of(new_base),
            })
        return True, f"{slot} base {old_base} -> {new_base}"
    # `judge` has restored the complete XML, item bookkeeping and skeleton. Keep the
    # fingerprint so a later pass does not pay for the same unchanged candidate set.
    last_rejected[slot] = fingerprint
    return False, None


# -- the loop itself (#51, unit 5b) --------------------------------------------------------------------


@dataclass(frozen=True)
class LoopFlags:
    """The three switches the loop body reads. Derived from `LoopPlan.kind`; `ImprovementLoop.run(plan, flags=...)`
    takes them directly only for the unit harnesses (`tests/loop_fakes.py`), which still ask for combinations no kind
    offers (`opening_lanes=False` with moves; `local_only` without a stage name)."""

    local_only: bool
    opening_lanes: bool
    stage_name: str | None

    @classmethod
    def of(cls, plan: LoopPlan) -> "LoopFlags":
        return cls(plan.local_only, plan.opening_lanes, plan.stage_name)


def _gain(before: float, after: float) -> str:
    return f"{after / before - 1:+.1%}" if before > 0 else f"{after:,.0f}"


def _moved(before: Score, after: Score) -> str:
    # a kept move that lowers the value was bought with feasibility: the note names both violations (#181)
    text = _gain(before.value, after.value)
    if after.value < before.value:
        text += f" (viol {before.violation:.3f} -> {after.violation:.3f})"
    return text


class ImprovementLoop:
    """One loop over moves, run to a fixed point (ROADMAP 7.1c), instead of the six stages that
    followed the rebuild (reoptimize, path swaps, gear pass 3, touch-up, joint, re-judged picks):
    each of those is one approximation of one pass of this loop, and each judged its own move by
    its own objective. Here every move -- tree refine, tree path swaps, one rare slot re-rolled
    from empty (with the tree repair its roll may need), the discrete picks -- is kept only when
    the FULL objective (movement floor and sustain in, D28/D34) improves under lanes re-derived
    after the move (D45), by the rule rejudge_picks uses: while a floor is missed any improvement
    of the Score ordering counts, and once feasible the value must grow by `min_gain`. A pass
    whose local moves keep nothing then tries the two kicks (ruin-and-recreate over the tree, and
    over tree and gear together): the local neighbourhood is exhausted, a large one is what is
    left. A kick is a random draw and gets `kick_draws` of them (tree, joint; the chain's 3 and 4
    rounds); every draw is judged and kept on its own, none is skipped because an earlier one was
    kept. A pass that keeps nothing at all is the fixed point and ends the loop; a loop that ran
    out of passes or of time says so in its notes and in what it returns, because a build that
    stopped short of the fixed point is not done.

    The plan's kind says which loop this is: "loop" (opening lanes, lane step, kicks), "extra pass" (the
    fixed-point check's one local pass, `local_only`: no opening lane tuning, no closing lane step, no kicks, no
    "stopped: max passes" note, the pass recorded under `stage_name`), "replay" (the replay bench: the path-swap
    wall-clock branch replaced by its fixed candidate count; refine rounds, gear slots, pick sweeps and kick draws
    are counts already). `plan.moves` restricts a run to named neighbourhoods.

    Everything the loop needs of the pipeline beyond the design's constructor arrives as a callable, looked up by
    the caller at call time (a unit harness fakes them on the instance): `record` (the stage record),
    `take_picks`, `aura_levels` (the flat-reservation aura levels), `joint_round` (the joint kick's round),
    `weapon_raw_base`, `weapon_base_fingerprint`, `weapon_base_move`, `sockets_stale`, `ensure_sockets` and the colour
    step's memory (`socket_memory_get` / `socket_memory_set`, the pipeline's `_socket_lines`)."""

    def __init__(self, build: WorkingBuild, result: BuildResult, *,
                 tune_lanes: Callable[..., dict],
                 picker: Callable[[], Any],
                 log: Callable[[str], None] | None = None,
                 record: Callable[..., None],
                 take_picks: Callable[..., None],
                 aura_levels: Callable[..., dict[str, int]],  # (skeleton, order=)
                 joint_round: Callable[..., str],
                 weapon_raw_base: Callable[[str], str],
                 weapon_base_fingerprint: Callable[..., tuple],
                 weapon_base_move: Callable[..., tuple[bool, str | None]],
                 sockets_stale: Callable[[], bool],
                 ensure_sockets: Callable[[Any], None],
                 socket_memory_get: Callable[[], Any],
                 socket_memory_set: Callable[[Any], None],
                 ascendancy_points: int | None = None) -> None:  # #1157: the rails' ascendancy points; None = no ascendancy-swap in the plan
        self.build = build
        self.pob, self.judging = build.pob, build.judging
        self.skeleton, self.loot, self.tree = build.skeleton, build.gear, build.tree
        self.result = result
        self.log = log if log is not None else (lambda _message: None)
        self._tune_lanes, self._picker = tune_lanes, picker
        self._record, self._take_picks, self._aura_levels_of = record, take_picks, aura_levels
        self._joint_round = joint_round
        self._weapon_raw_base, self._weapon_base_fingerprint = weapon_raw_base, weapon_base_fingerprint
        self._weapon_base_move_of = weapon_base_move
        self._sockets_stale, self._ensure_sockets = sockets_stale, ensure_sockets
        self._socket_memory_get, self._socket_memory_set = socket_memory_get, socket_memory_set
        self._ascendancy_points = ascendancy_points

    @property
    def objective(self) -> Objective:
        """The objective in force NOW: the judging context replaces it on every re-derivation (the pipeline's own `objective` is this)."""

        return self.judging.objective

    # -- the run ---------------------------------------------------------------------------------------

    def run(self, plan: LoopPlan, *, flags: LoopFlags | None = None) -> LoopOutcome:
        flags = flags if flags is not None else LoopFlags.of(plan)
        self._plan, self._flags = plan, flags
        result, skeleton, loot = self.result, self.skeleton, self.loot
        local_only, max_passes, max_seconds = flags.local_only, plan.max_passes, plan.max_seconds
        last_pass = plan.first_pass + max_passes - 1  # the number of this run's last pass (= max_passes unless first_pass moved it)

        t_loop = time.perf_counter()
        self._t_loop = t_loop
        rare = [s for s in skeleton.rare_bases if s not in skeleton.uniques]
        # the construction's fill order: weapons first, so a re-rolled slot is judged with a weapon in hand
        slots = ordered_slots(rare)
        weapon_base_slots = base_swap_slots(slots, skeleton=skeleton, loot=loot, raw_base=self._weapon_raw_base)  # every slot with another base (#1158)
        st = _LoopState()
        self._st = st

        # The loop's own name for the moves before pass 1; the pass loop rewrites it per pass, and a
        # re-entry (the fixed-point check) carries its `stage_name` instead, which is how the ledger
        # tells that pass's rows apart from the loop's own.
        st.where = flags.stage_name or "loop opening"

        self.kept: list[str] = []  # the moves the last pass kept, read back by the fixed-point check
        st.cur = self._score_now()  # the opening lane tune is a recoverable move too
        if result.ledger_construction_value is None:
            result.ledger_construction_value = st.cur.value

        # one transaction per attempt (`tools.attempt(...)`): the snapshot, the contract-error drop and the judge with
        # its two revert contracts live in `Attempt`; these are the callables it works through
        self._tools = AttemptTools(st=st, snapshot=self._snapshot_move, restore=self._restore_move,
                                   rejudge=lambda: self.judging.rejudge(skeleton),
                                   restore_mark=lambda mark, only: self.judging.restore(mark, only=only), score=self._score_now,
                                   record=self._record_move, note_drop=lambda row: result.dropped_moves.append(row),
                                   log=lambda message: self.log(message), min_gain=plan.min_gain, order=plan.order,
                                   fresh_costs=self._score_under_current_costs)

        # the loop's objective is the final lanes' (D60): the list choices (stance, exposure type, Pride's
        # effect) and the identity (bandit, pantheons, the bandit's extra points) used to be judged first in
        # `_finish`, so the loop optimized one number and the build was reported with another -- on
        # loop-smoke-3 the "config (final lanes)" stage stood +43% above the loop's last pass on
        # burning_arrow_snipe s1, +16-18% on bleed_bow, +14.5% on impale_ballista -- and the floors (max hit
        # under Sand vs Blood stance) were judged in the wrong lane. They are judged here, once before pass 1,
        # and the choices again at the end of every pass whose moves changed the build.
        if local_only or not flags.opening_lanes:
            # the fixed-point check's extra pass: `_finish` has just tuned the choices and the identity on
            # this very build, so an opening tuning would only re-judge what PoB already holds
            pass
        else:
            self.log(start_line("loop opening"))  # #711
            self._opening_lanes()

        for st.p in range(plan.first_pass, last_pass + 1):
            t_pass = time.perf_counter()
            self.log(start_line(flags.stage_name or plan.pass_label(st.p)))  # #711
            yield_probe.check(flags.stage_name or plan.pass_label(st.p))  # #621
            self.judging.refresh_castability()
            # the refresh changed the objective: the Score carried into the pass is the Score of the build under
            # THIS objective, read before any move is compared or any `before` is recorded (#181; #167: the carried
            # 215,143 / viol 0 was 215,143 / viol 0.307692 under the refreshed cost)
            st.cur = self._score_now()
            st.notes = []
            st.where = flags.stage_name or plan.pass_label(st.p)  # every move of this pass logs under it
            has_flat_reservation_aura = bool(getattr(skeleton, "flat_reservation_auras", lambda: [])())
            # Neither trunk move is in the default plan; both stay reachable for the replay bench and
            # enter the plan only when `moves` names them. The corridor exchange: on the 96 delivered
            # builds of the two rules campaigns it found a bypass for 79 of 2,583 corridors (3.1%),
            # reached 0.6% of the trunk and kept 2 exchanges. The region challenge (plan B,
            # 2026-09-20; after the path swaps, only in a pass where refine and the swaps kept
            # nothing) gave +0.43% on the bench, but in real loops it kept something on 11 of 180
            # builds (main-smoke, new18-r3, core14-r3, ziz-rules): 0.6% of the loop's gain for 5.7%
            # of its time, the lowest gain per minute of any move; out on the owner's word
            # (2026-09-22, docs/readings/2026-09-22-move-ledger.md).
            st.tree_kept_this_pass = False
            entries = pass_plan(slots, weapon_base_slots, has_flat_reservation_aura=has_flat_reservation_aura, local_only=local_only, moves=plan.moves,
                                has_ascendancy_points=self._ascendancy_points is not None)
            for kind, i, slot in entries:
                if self._safety_net_reached():
                    break
                yield_probe.check(st.where)  # #621: a move
                self.log(loop_move_line(st.p, kind, flags.stage_name, prefix=plan.pass_prefix))  # #711
                t0 = time.perf_counter()
                st.attempted_total += 1
                before = st.cur.value
                started = st.cur
                if kind in ("refine", "swaps"):
                    self._refine_or_swaps(kind, t0, started)
                elif kind in ("corridors", "regions"):
                    self._trunk(kind, t0, started)
                elif kind == "ascendancy-swap":
                    self._ascendancy_swap(t0)
                elif kind == "weapon-base":
                    self._weapon_base(slot, t0, started)
                elif kind == "gear":
                    self._gear(i, slot, t0, started)
                elif kind == "picks":
                    self._picks(t0, before)
                elif kind == "aura levels":
                    self._aura_levels(t0)
                elif kind == "lanes":
                    self._lanes(t0, before)
            # the kicks run when nothing local moved and the loop has not stopped; the fixed-point check measures
            # the local neighbourhood only, so `kick_plan` is empty for it
            self._kicks()
            notes_text = "; ".join(st.notes) or "no change"
            self.kept = list(st.notes)
            if st.stopped:
                notes_text += f"; stopped: {st.stopped}"
            elif st.notes and st.p >= last_pass and not local_only:  # one pass is all the check asks for: that is not stopping short
                st.stopped = "max passes"
                notes_text += f"; stopped: max passes ({max_passes})"
            if (st.stopped or not st.notes) and not local_only:
                # #555: this pass is the loop's last, whatever ended it (max passes after a kept kick, the time budget
                # after a kept gear or picks move, a lanes move that raised): the build leaves on colours the loop judged
                self._judge_colours(time.perf_counter())
            if st.notes and (st.stopped or st.p >= last_pass):
                # #941 (b): the last pass kept a move and no next pass will refresh the frozen skill costs
                notes_text += self._close_on_current_costs()
            self._record(result, st.where, t_pass, notes_text)
            if st.stopped or not st.notes:  # a pass that kept nothing is the fixed point
                break
        # `not_kept` is every started move the build did not keep (the lane step and the kick draws a
        # fingerprint check skipped without measuring included); `judged_and_reverted` is the subset PoB
        # actually scored and rejected. The two differ by the moves that never reached the judge.
        counts = {"attempted": st.attempted_total, "kept": st.kept_total,
                  "not_kept": max(0, st.attempted_total - st.kept_total),
                  "judged_and_reverted": st.judged_reverted_total,
                  "closing_repair_kept": st.closing_repair_kept}  # #1008: tree changes of the last cost repair, not in `kept`
        return LoopOutcome(note=self._note(st), stopped=st.stopped, kept=tuple(self.kept), counts=counts, passes=st.p - plan.first_pass + 1)

    def _safety_net_reached(self) -> bool:
        """#569: the loop's one clock, off unless `max_seconds` was given (#956). Sets `stopped = "time budget"` (loop_stop "time") and logs it once."""
        st, max_seconds = self._st, self._plan.max_seconds
        if max_seconds is None or time.perf_counter() - self._t_loop <= max_seconds:
            return False
        st.stopped = "time budget"
        self.log(f"loop: safety net {human_duration(max_seconds)} reached after pass {st.p}")
        return True

    def _score_under_current_costs(self, scored: Score) -> Score:
        """#941 (a): install the skill costs the build holds now (`Judging.refresh_castability`) and return its Score under
        them: `scored` itself when no cost moved, else one more stats read. The extra PoB work of a kept move is the
        castability read (two state reads, one active-skill stats call, one pool read) and, only when a cost moved, that
        one stats read."""

        before = self.judging.castability_context
        self.judging.refresh_castability()
        if self.judging.castability_context == before:
            return scored
        return self._score_now()

    def _close_on_current_costs(self) -> str:
        """#941 (b): the loop's last pass kept a move, so its final state was judged under costs frozen before that move
        (no later pass refreshes them), and the loop's priced acceptance may also have kept a build whose skill costs more
        than the pool. Read the costs the final build has; while a skill of `audit_castability`'s list is left without the
        mana or life for one use (a `castability_violations` row), buy it back with the tree's repair-only refine, the move
        the delivered build's last floor repair uses, kept only while the violation falls. Returns the note ("" when
        the final build is castable as it stands)."""

        st = self._st
        was = st.cur
        st.cur = self._score_under_current_costs(was)
        missed = castability_violations(self.objective, self.pob.stats(self.objective.stat_keys))
        if not missed:
            return ""
        note = f"; skill costs on the final build: {', '.join(sorted(missed))} (viol {was.violation:.3f} -> {st.cur.violation:.3f})"
        repair_started = time.perf_counter()  # #1008: the repair has no clock of the loop's plan; its time is in the pass's record
        changes = 0
        for _round in range(COST_CLOSE_ROUNDS):
            before = st.cur
            shots = self._snapshotter()
            snapshot = shots.take(xml=True, skeleton=True, filler=FILLER_ALL, history=True, judging=MOVE)
            move = self.tree.refine(max_rounds=0, repair_rounds=60)  # repair only: the cheapest DPS per violation removed
            self.judging.rejudge(self.skeleton)
            st.cur = self._score_under_current_costs(self._score_now())
            if not better_score(st.cur, before):
                shots.restore(snapshot)
                st.cur = self._score_now()
                note += "; repair kept nothing"
                break
            changes += len(getattr(move, "steps", None) or ())  # a round kept is its swaps kept; a reverted round counts none
            note += f"; repair {before.violation:.3f} -> {st.cur.violation:.3f}"
            if not castability_violations(self.objective, self.pob.stats(self.objective.stat_keys)):
                break
        st.closing_repair_kept += changes
        return note + f"; closing repair {human_duration(time.perf_counter() - repair_started)}, {changes} tree changes kept"

    def _note(self, st: _LoopState) -> str:
        plan, flags = self._plan, self._flags
        # #1008: the closing cost repair's tree changes stand beside the moves kept, only when it kept any
        closing = f", {st.closing_repair_kept} tree changes kept in the closing repair" if st.closing_repair_kept else ""
        if flags.local_only:
            return f"{flags.stage_name or 'extra pass'}: {st.kept_total} moves kept{closing}" + (f"; stopped: {st.stopped}" if st.stopped else "")
        ran = st.p - plan.first_pass + 1
        passes = f"{ran} pass" + ("es" if ran != 1 else "")
        if st.stopped == "max passes":
            return f"stopped: max passes ({plan.max_passes}), {st.kept_total} moves kept{closing}"
        if st.stopped:
            return f"stopped: time budget ({human_duration(plan.max_seconds)}) after {passes}, {st.kept_total} moves kept{closing}"
        return f"fixed point after {passes} ({st.kept_total} moves kept{closing})"

    # -- what every move shares ------------------------------------------------------------------------

    def _score_now(self) -> Score:
        return self.objective.score(self.pob.stats(self.objective.stat_keys))

    def _record_move(self, name: str, started: float, before: Score, after: Score, *, kept: bool,
                     reverted_by_judge: bool = False, pass_number: int | None = None) -> None:
        st = self._st
        TRACE.flush(name)
        self.result.moves.append({
            "pass": st.p if pass_number is None else pass_number,
            "where": st.where,
            "move": name,
            "seconds": time.perf_counter() - started,  # the clock the loop's own log lines use
            "before": before.value,
            "after": after.value,
            "kept": bool(kept),
            "reverted_by_judge": bool(reverted_by_judge),
            "violation_before": before.violation,
            "violation_after": after.violation,
        })

    def _snapshotter(self) -> Snapshotter:
        """The holders of the build's state as they are now; every revert goes through `Snapshotter` (#813)."""

        return Snapshotter(pob=self.pob, skeleton=self.skeleton, filler=self.loot, judging=self.judging,
                            trees=lambda: tuple(dict.fromkeys(self.judging.trees() or (self.tree,))))

    def _snapshot_move(self) -> dict[str, Any]:
        st = self._st
        # the gear view's objective, every attached tree's objective and holders, the objective, the gem
        # levels and the castability context are the judging part (`Judging.mark(MOVE)`)
        build = self._snapshotter().take(xml=True, skeleton=True, filler=FILLER_ALL, history=True, judging=MOVE)
        return {
            "build": build,
            "xml": build.xml,
            "lanes_fresh": st.lanes_fresh,
            "cur": st.cur,
            "changed_since_picks": st.changed_since_picks,
            "changed_since_aura_levels": st.changed_since_aura_levels,
            "changed_since_lanes": st.changed_since_lanes,
            "kept_total": st.kept_total,
            "judging": build.judging,
            "picks": copy.deepcopy(self.result.picks),
            "socket_state": self._socket_memory_get(),  # the colour step's memory goes back with the XML it describes (#547)
        }

    def _restore_move(self, state: Mapping[str, Any], *, keep_rejections: bool = False) -> None:
        st = self._st
        # The XML includes the exact lanes from before the failed move. Do not derive or apply
        # anything over it: recovery must restore, not make another scoring decision.
        self._snapshotter().restore(state["build"], keep_rejections=keep_rejections)
        self.result.picks[:] = state["picks"]
        self._socket_memory_set(state["socket_state"])
        st.cur = state["cur"]
        st.kept_total = state["kept_total"]
        st.changed_since_picks = state["changed_since_picks"]
        st.changed_since_aura_levels = state["changed_since_aura_levels"]
        st.changed_since_lanes = state["changed_since_lanes"]
        st.lanes_fresh = state["lanes_fresh"]

    def _fingerprint(self) -> tuple:
        """Everything a kick draw can change: the tree PoB holds (`reoptimize` allocates and
        deallocates, nothing else) and the rare items the filler equipped (`_joint_round` empties
        and refills only those slots, and the filler records what it equipped). Gems, level and
        ascendancy are untouched by both, and the lanes follow tree and items, so an equal
        fingerprint is an equal build. `tree_light` is milliseconds -- the greedy asks for it on
        every step -- and the item side costs no PoB call at all. The exported XML cannot serve:
        PoB reorders its attributes on every load_xml round trip, which is exactly how a draw its
        own objective rejected comes back (measured: two exports of an untouched build are equal,
        an export after load_xml(export) is not)."""

        light = self.pob.tree_light()
        return (light.get("class_id"),
                tuple(sorted(int(n) for n in light.get("user_allocated_node_ids") or ())),
                tuple(sorted(str(m) for m in light.get("mastery_effect_ids") or ())),
                tuple(sorted(self.loot.current_raw.items())))

    def _judge_colours(self, started: float, *, pass_number: int | None = None) -> None:
        """#547: the loop judges the build under the socket colours `_finish` delivers (D60): whiten every socket and
        colour at most `coloured_max` of them by PoB's numbers, as `_finish` does, so the loop's last pass and
        `config (final lanes)` are one number. Not a keep-or-revert move: the delivered build is coloured whatever the
        step says, so its change is kept and the ledger records it. Idle (no PoB call beyond the state read) when
        the sockets and the gems are what the last step left."""

        st = self._st
        if not self._sockets_stale():
            return
        label = f"{st.where} sockets"
        before_score = st.cur
        with self._tools.attempt(label, ledger_name="sockets", started=started, before=before_score):
            self._ensure_sockets(self.loot)
            st.cur = self._score_now()
            self._record_move("sockets", started, before_score, st.cur, kept=st.cur != before_score, pass_number=pass_number)

    # -- the opening -----------------------------------------------------------------------------------

    def _opening_lanes(self) -> None:
        st, tools, skeleton, tree = self._st, self._tools, self.skeleton, self.tree
        label = "loop opening lanes"
        before_opening_lanes = st.cur
        with tools.attempt(label, ledger_name="lanes", before=before_opening_lanes) as attempt:
            tuned = self._tune_lanes(skeleton, identity=True)
            st.lanes_fresh = True  # `_tune_lanes` ends in a reconfigure: this build's own derivation is what PoB holds
            st.cur = self._score_now()
            self._record_move("lanes", attempt.started, before_opening_lanes, st.cur, kept=st.cur != before_opening_lanes, pass_number=0)
            self.log(f"loop lanes: choices {tuned} judged before pass 1: {st.cur.value:,.0f} (viol {st.cur.violation:.3f})")
        self._judge_colours(time.perf_counter(), pass_number=0)  # #547: the colours `_finish` will deliver, judged before pass 1
        if not st.cur.feasible:
            # the tuned lanes can leave a build the construction left feasible infeasible (the first attempt at
            # D60, reverted: viol 0.345 before pass 1, and the loop bought the floor back with a gear roll that
            # cost 40% of the damage). `_finish` repairs exactly this case after its own tuning, with the
            # refine's cheapest-DPS-per-violation repair, and so does the loop before its first pass.
            was = st.cur
            label = "loop lanes tree refine"
            with tools.attempt(label, ledger_name="lanes tree refine", before=was) as attempt:
                tree.refine(max_rounds=12)
                self.judging.rejudge(skeleton)
                st.cur = self._score_now()
            if not attempt.dropped:
                self._record_move("lanes tree refine", attempt.started, was, st.cur, kept=st.cur != was)
                self.log(f"loop lanes: repaired after the tuning: viol {was.violation:.3f} -> {st.cur.violation:.3f}, {was.value:,.0f} -> {st.cur.value:,.0f}")

    # -- the moves of a pass ---------------------------------------------------------------------------

    def _refine_or_swaps(self, kind: str, t0: float, started: Score) -> None:
        # refine and path swaps are two neighbourhoods of the same tree (D27), but two moves: judged
        # as one batch a bad final state reverts the swaps that were kept along the way too
        st, tree = self._st, self.tree
        label = f"{st.where} tree {'refine' if kind == 'refine' else 'path swaps'}"
        with self._tools.attempt(label, ledger_name="refine" if kind == "refine" else "path swaps", started=t0) as attempt:
            failures = tree.restore_failures
            if kind == "refine":
                move = tree.refine(max_rounds=10)
            else:
                # bounded by max_failures (12 in a row) and the subtree count; #569 measured 12-38 tried per call in the weekly run
                move = tree.swap_subtrees(max_size=6, max_seconds=None, max_candidates=None)
            if tree.restore_failures > failures:
                # the optimizer's own snapshot did not bring the build back (see TreeOptimizer._restore):
                # the number this move is judged on is not the tree it left behind
                self.log(f"restore failures in this move: {tree.restore_failures - failures}")
            if attempt.judge_exact():
                st.notes.append(f"{kind} {_moved(started, st.cur)}")
                st.tree_kept_this_pass = True
            elif kind == "swaps" and getattr(move, "steps", None):  # a stand-in optimizer in the unit harnesses returns no move
                replayed = self._replay_path_swaps(move.steps, f"{st.where} tree path swaps")
                if replayed:
                    st.notes.append(f"swaps replay {_moved(started, st.cur)}")
                    st.tree_kept_this_pass = True

    def _replay_path_swaps(self, steps: list, label: str) -> int:
        """Replay a rejected batch one mutation at a time under fresh lanes.

        The normal path-swap pass is deliberately fast and frozen.  A batch
        the pipeline rejects is rare; this bounded replay both salvages its
        true swaps and records the still-unmodelled dependency that made a
        frozen verdict false.
        """

        st, tree, skeleton = self._st, self.tree, self.skeleton
        min_gain = self._plan.min_gain
        kept = 0

        def names(node_ids: list[int]) -> str:
            return ", ".join(
                tree.graph.node(int(node_id)).name if tree.graph.node(int(node_id)) else str(node_id)
                for node_id in node_ids
            )

        def inputs() -> dict[str, object]:
            reader = getattr(self.pob, "config_inputs", None)
            return dict(reader()) if callable(reader) else {}

        rejected_before = 0  # steps this replay has already refused: the reason a later mutation can miss

        for index, step in enumerate(steps):
            if index >= PATH_SWAP_REPLAY_STEPS:
                self.log(f"replay: {index}/{len(steps)} steps")
                break
            t0 = time.perf_counter()
            before_step = st.cur
            what = (f"-{len(step.removed_node_ids)} [{names(step.removed_node_ids)}] -> "
                    f"+{len(step.added_node_ids)} [{names(step.added_node_ids)}]")
            state = self._snapshot_move()
            before_inputs = inputs()

            def mutation_missed(why: str) -> None:
                # never a FALSE verdict: the batch's own mutation is simply not on this tree any
                # more, which is what a rejected earlier step does to the steps that followed it
                depends = "depends on a rejected step" if rejected_before else why
                self.log(f"replay: skipped: {depends} {what}")
                self._restore_move(state, keep_rejections=True)
                self._record_move("swaps replay", t0, before_step, st.cur, kept=False)

            removed = self.pob.mutate_nodes(remove=step.removed_node_ids)
            expected_removed = {int(node) for node in step.removed_node_ids}
            if {int(node) for node in removed.get("removed_node_ids") or ()} != expected_removed:
                mutation_missed("removal no longer matches")
                continue
            added = self.pob.mutate_nodes(add=step.added_node_ids, mastery_effects=step.added_mastery_effects or None)
            expected_added = {int(node) for node in step.added_node_ids}
            if {int(node) for node in added.get("added_node_ids") or ()} != expected_added:
                mutation_missed("allocation no longer matches")
                continue
            self.judging.rejudge(skeleton)
            st.lanes_fresh = True
            honest = self._score_now()
            after_inputs = inputs()
            changed = [
                f"{key}: {before_inputs.get(key)!r} -> {after_inputs.get(key)!r}"
                for key in sorted(set(before_inputs) | set(after_inputs))
                if before_inputs.get(key) != after_inputs.get(key)
            ]
            lost = [key for key in sorted(set(before_inputs) | set(after_inputs))
                    if worse_input(before_inputs.get(key), after_inputs.get(key))]
            keep = accepts(honest, before_step, min_gain=min_gain, order=self._plan.order)
            if keep:
                honest = self._score_under_current_costs(honest)  # #941 (a)
                keep = accepts(honest, before_step, min_gain=min_gain, order=self._plan.order)
            if keep:
                st.cur = honest
                st.kept_total += 1
                st.changed_since_picks = True
                st.changed_since_lanes = True
                tree.history.append(replace(step, before=before_step, after=honest, seconds=time.perf_counter() - t0))
                kept += 1
                self._record_move("swaps replay", t0, before_step, honest, kept=True)
                self.log(f"replay: kept swap {what}: {before_step.value:,.0f} -> {honest.value:,.0f}")
                continue
            # FALSE only when the honest number is really lower (or the lanes lost an input the
            # frozen verdict was counting on). A swap that gains, but by less than the loop's
            # min_gain, was not a false verdict -- it was a true one the acceptance rule refuses.
            if honest < before_step or lost:
                self.log(f"replay: FALSE swap {what}: {before_step.value:,.0f} -> {honest.value:,.0f}, "
                         f"config inputs that changed: {changed}")
            else:
                self.log(f"replay: below min gain {what}: {before_step.value:,.0f} -> {honest.value:,.0f}")
            rejected_before += 1
            self._restore_move(state, keep_rejections=True)
            st.cur = self._score_now()
            self._record_move("swaps replay", t0, before_step, st.cur, kept=False, reverted_by_judge=True)
        return kept

    def _trunk(self, kind: str, t0: float, started: Score) -> None:
        # plan B: the two moves that reconsider the trunk. Budgets are COUNTS so a
        # replay measurement is deterministic; the seconds are the outer guard only.
        # `tree_kept_this_pass` is set by refine and by the path swaps: those are the
        # cheap tree moves the region challenge waits for (corridors is not in the
        # default plan, so it never gates this).
        st, tree = self._st, self.tree
        if kind == "regions" and st.tree_kept_this_pass:
            self.log(f"{st.where} tree region challenge: skipped, a cheaper tree move kept something this pass")
            return
        label = f"{st.where} tree {'corridor exchange' if kind == 'corridors' else 'region challenge'}"
        with self._tools.attempt(label, ledger_name="corridors" if kind == "corridors" else "regions", started=t0) as attempt:
            failures = tree.restore_failures
            if kind == "corridors":
                move = tree.exchange_corridors(max_corridors=40, k=8, slack=2, max_applied=8,
                                               max_seconds=None)
            else:
                move = tree.challenge_regions(per_bucket=16, replacements=12, max_challenges=4,
                                              max_seconds=None)
            if tree.restore_failures > failures:
                self.log(f"restore failures in this move: {tree.restore_failures - failures}")
            elif not getattr(move, "steps", None):
                # the move puts back everything it tried and did not keep, so a move that
                # kept nothing leaves the build it started on: judging it would only buy
                # the number PoB already holds, at the price of a lane derivation
                self.log(f"{label}: nothing kept, skipped ({time.perf_counter() - t0:.0f}s)")
                self._record_move("corridors" if kind == "corridors" else "regions", t0, st.cur, st.cur, kept=False)
                return
            if attempt.judge_exact():
                st.notes.append(f"{kind} {_moved(started, st.cur)}")

    def _weapon_base(self, slot: str, t0: float, started: Score) -> None:
        st, result, skeleton, loot, tree = self._st, self.result, self.skeleton, self.loot, self.tree
        label = f"{st.where} {slot} weapon base"
        with self._tools.attempt(label, ledger_name="weapon base", started=t0, armed=False) as attempt:
            move_state = attempt.state
            if st.last_rejected_weapon_base.get(slot) == self._weapon_base_fingerprint(loot, skeleton, slot, config_xml=move_state["xml"]):
                # A rejected swap has no hidden randomness: the tree, this item and both
                # config lanes still describe the same candidate calculation.
                self.log(f"{slot} weapon base: skipped, nothing changed since the last rejected trial")
                self._record_move("weapon base", t0, st.cur, st.cur, kept=False)
                return
            moves_before = len(result.moves)
            attempt.arm()  # the fingerprint above sits outside the contract-error guard (quirk 9)
            kept, base_note = self._weapon_base_move_of(
                result,
                skeleton,
                loot,
                slot,
                current_score=st.cur,
                min_gain=self._plan.min_gain,
                move_state=move_state,
                snapshot_fresh=move_state["lanes_fresh"],
                t0=t0,
                judge=lambda judged_label, _revert, _t0, **_kwargs: attempt.judge_exact(judged_label),  # the move's own revert is the exact contract
                restore_move=self._restore_move,
                last_rejected=st.last_rejected_weapon_base,
                order=self._plan.order,
            )
            tree.note_build_change()  # #34: kept or reverted, Scores cached during the trial gear are stale
            if kept:
                st.notes.append(base_note or f"{slot} weapon base {_moved(started, st.cur)}")
            elif len(result.moves) == moves_before:
                self._record_move("weapon base", t0, st.cur, st.cur, kept=False)

    def _gear(self, i: int, slot: str, t0: float, started: Score) -> None:
        st, skeleton, loot, tree, pob = self._st, self.skeleton, self.loot, self.tree, self.pob
        label = f"{st.where} {slot}"
        with self._tools.attempt(label, ledger_name=f"gear {slot}", started=t0, armed=False) as attempt:
            move_state = attempt.state
            # On a build that meets every floor a template slot's open lines are re-filled by VALUE (spec
            # 2026-09-26-template-loop-lines-by-value): the floors-first fill rebuilt the same item every pass,
            # so "a damage line here, the tree pays the floor" was never tried (51% of template open lines at +0).
            fill_base = gear_move_base(slot, skeleton=skeleton, loot=loot)
            if fill_base is None:
                # #1154: the incumbent's base is one the loadout never offers and its class has no allowed base to hand over
                self.log(f"{label}: incumbent base {skeleton.rare_bases[slot]} is excluded by the loadout, slot left out of the move")
                self._record_move(f"gear {slot}", t0, st.cur, st.cur, kept=False)
                return
            by_value = loot.refills_by_value and st.cur.feasible
            fill_fingerprint = self._weapon_base_fingerprint(loot, skeleton, slot, config_xml=move_state["xml"]) if by_value else None
            if by_value and st.last_rejected_value_fill.get(slot) == fill_fingerprint:
                self.log(f"{label}: value re-fill skipped, nothing changed since the last rejected trial")
                self._record_move(f"gear {slot}", t0, st.cur, st.cur, kept=False)
                return
            attempt.arm()  # the value-fill fingerprint above sits outside the contract-error guard (quirk 9)
            old_raw = loot.current_raw.get(slot)
            forced_bases = getattr(skeleton, "forced_bases", {})
            snapshot = self._snapshotter().take(xml=move_state["xml"], skeleton=True, filler=filler_slot(slot), history=True)  # the XML is the attempt's own, no second export; the Skeleton counts and the tree steps the trial writes go back with it (#854)
            if raw_refused(loot, slot, old_raw, forced_base=forced_bases.get(slot)):
                loot.current_raw.pop(slot, None)  # #1152: an incumbent a current restriction refuses does not compete (the trial is then kept whatever it scores, see `must_keep`)
            pob.equip({slot: None})  # rolled against the empty slot, as the second gear pass does; the incumbent still competes
            if by_value:
                loot.flexible_by_value = True
            try:
                with TRACE.incumbent_sockets(slot, old_raw):  # #548: the candidates carry the incumbent's sockets
                    res = loot.refill_slot(slot, fill_base, n=self._plan.loot_n, sockets=candidate_sockets(old_raw, fill_base, skeleton.sockets.get(slot)), seed=derive_seed(self._plan.seed, PURPOSE_JOINT_FILL_SLOT, st.p, i), order=self._plan.order)
            finally:
                if by_value:
                    loot.flexible_by_value = False
            if res.raw == old_raw:
                # the incumbent won its own slot and is back on the build: nothing changed, nothing to judge
                self.log(f"{label}: incumbent kept ({time.perf_counter() - t0:.0f}s)")
                self._record_move(f"gear {slot}", t0, st.cur, st.cur, kept=False)
                return
            self.judging.rejudge(skeleton)  # the new item's own lanes first: the repair below is judged under them (D45)
            repair = ""
            rolled = self._score_now()
            if not rolled.feasible:
                # a roll that breaks a floor is not a bad roll until the tree has been asked to pay for it:
                # the chain's gear pass 3 took such a weapon on Bleed Bow s2 (viol 0.123) and the touch-up
                # repaired it, 248,614 -> 653,142, while the loop reverted the same kind of roll (410,048 at
                # viol 0.307 against 264,189 feasible) and ended at 308,127
                tree.refine(max_rounds=0, repair_rounds=60)  # repair only: no feasible round, the cheapest DPS per violation removed
                self.judging.rejudge(skeleton)
                repair = f" after repair viol {rolled.violation:.3f} -> {self._score_now().violation:.3f}"

            def revert(snapshot=snapshot) -> None:
                self._snapshotter().restore(snapshot)  # the snapshot precedes the roll, so the repair goes back with it

            gear_kept = attempt.judge_partial(revert, f"{label}{repair}", reconfigured=True, must_keep=replaced_refused(loot, {slot: old_raw}, forced_bases))
            tree.note_build_change()  # #34: tree.refine(repair) can allocate on the trial gear before the judge; kept or reverted, those Scores are stale
            if gear_kept:
                st.notes.append(f"{slot} {_moved(started, st.cur)}")
                st.last_rejected_value_fill.pop(slot, None)
            elif by_value:
                st.last_rejected_value_fill[slot] = fill_fingerprint

    def _picks(self, t0: float, before: float) -> None:
        st, result, skeleton = self._st, self.result, self.skeleton
        if len(skeleton.main_link) <= 1 and not any(g.picked or g.enabled for g in skeleton.extra_groups):
            # nothing discrete to re-judge: no support to swap, no picked group, and no
            # enabled group the reserving-group drop could give the mana back from (D72)
            self._record_move("picks", t0, st.cur, st.cur, kept=False)
            return
        if not st.changed_since_picks:
            # the re-judge is deterministic on an unchanged build: 374-488 s per pass on Stormbrand for the
            # same verdict, and the time budget ran out before the kicks had their turn (2026-09-15)
            self.log(f"{st.where} picks: skipped, nothing changed since the last re-judge")
            self._record_move("picks", t0, st.cur, st.cur, kept=False)
            return
        label = f"{st.where} picks"
        before_score = st.cur
        with self._tools.attempt(label, ledger_name="picks", started=t0, before=before_score):
            gen = self._picker()
            # one sweep per pass: the loop itself is the repetition rejudge_picks does with max_sweeps
            changes = gen.rejudge_picks(skeleton, reconfigure=self.judging.rejudger(skeleton), min_gain=self._plan.min_gain, max_sweeps=1, order=self._plan.order)
            self._take_picks(result, gen, before=before)
            st.cur = self._score_now()  # rejudge_picks keeps and reverts each swap itself, under the same rule and re-derived lanes
            st.lanes_fresh = True  # its last act is `honest()`: the lanes stand for the link it left behind
            # "the loop itself is the repetition rejudge_picks does with max_sweeps": a sweep that
            # kept something has left a build its own next sweep has never seen, so the next pass
            # runs it again even when nothing else moved -- which is how a second reserving group
            # can be dropped when one was not enough (D72). A sweep that kept nothing is done.
            st.changed_since_picks = bool(changes)
            if changes:
                st.changed_since_aura_levels = True
            if changes:
                st.kept_total += 1
                st.changed_since_lanes = True
                # a change that reads better as its own sentence carries its own text (the
                # reserving-group drop, D72: "dropped Determination (MoMUnreservedShare ...)")
                st.notes.append("picks: " + "; ".join(c.get("text") or f"{c['what']} {c['was']} -> {c['now']} ({_gain(c['before'], c['after'])})" for c in changes))
            self._record_move("picks", t0, before_score, st.cur, kept=bool(changes), reverted_by_judge=not bool(changes))
            self.log(f"{label}: {len(changes)} kept, {before:,.0f} -> {st.cur.value:,.0f} ({time.perf_counter() - t0:.0f}s)")

    def _aura_levels(self, t0: float) -> None:
        st, skeleton = self._st, self.skeleton
        if not st.changed_since_aura_levels:
            self._record_move("aura levels", t0, st.cur, st.cur, kept=False)
            return
        label = f"{st.where} flat-reservation aura levels"
        before_score = st.cur
        with self._tools.attempt(label, ledger_name="aura levels", started=t0, before=before_score) as attempt:
            levels = self._aura_levels_of(skeleton, order=self._plan.order)
            self.judging.rejudge(skeleton)
            new = self._score_now()
            keep = accepts(new, st.cur, min_gain=self._plan.min_gain, order=self._plan.order)
            if keep:
                new = self._score_under_current_costs(new)  # #941 (a)
                keep = accepts(new, st.cur, min_gain=self._plan.min_gain, order=self._plan.order)
            if keep:
                self.log(f"{label}: {st.cur.value:,.0f} (viol {st.cur.violation:.3f}) -> {new.value:,.0f} (viol {new.violation:.3f}) kept ({time.perf_counter() - t0:.0f}s)")
                st.cur = new
                st.kept_total += 1
                st.changed_since_picks = True
                st.changed_since_aura_levels = True
                st.changed_since_lanes = True
                st.notes.append("aura levels " + ", ".join(f"{name} {level}" for name, level in levels.items()))
                self._record_move("aura levels", t0, before_score, new, kept=True)
            else:
                self._restore_move(attempt.state, keep_rejections=True)  # a judged revert, not a contract error: the tree keeps its memory (judge fix v3)
                self.log(f"{label}: reverted ({time.perf_counter() - t0:.0f}s)")
                st.changed_since_aura_levels = False
                self._record_move("aura levels", t0, before_score, st.cur, kept=False, reverted_by_judge=True)

    def _ascendancy_swap(self, t0: float) -> None:
        """#1157: an allocated ascendancy node that moves neither the objective nor TotalEHP by 0.1 % (the audit's
        `dead_ascendancy_nodes`, measured by PoB's own removal) is swapped for the best other pick of its ascendancy that
        PoB measures above it and that costs no more ascendancy points. One attempt per dead node, each judged on its
        own; a node a request named, and a node an earlier swap's removal already took, are left alone. Every pass
        measures the audit again (one batch of at most `ascendancy_points` full trials): a picks or lanes move changes
        the gems without changing the tree, and that can turn a node dead or alive. After a kept swap the dead list is
        measured again, because the swap can change what the next node is worth."""

        st, skeleton, plan = self._st, self.skeleton, self._plan
        before_score = st.cur
        names = ascendancy_node_names()
        forced = {int(n) for n in getattr(skeleton, "forced_ascendancy_nodes", ()) or ()}
        kept_swaps, reverted = 0, 0
        tried: set[int] = set()
        dead_list = dead_ascendancy_nodes(self.pob, objective=self.objective, points_budget=self._ascendancy_points)
        while True:
            dead = next((row for row in dead_list if row.node_id not in tried), None)
            if dead is None:
                break
            tried.add(dead.node_id)
            kept_before = kept_swaps
            allocated = {int(n) for n in self.pob.tree_light().get("user_allocated_node_ids") or ()}
            if dead.node_id in forced or dead.node_id not in allocated:
                continue
            candidates = ascendancy_swap_candidates(dead.node_id, allocated)
            if not candidates:
                continue
            asc_before = {n for n in allocated if n in names}
            trials = [{"remove": [dead.node_id], "add": [cand]} for cand in candidates]
            TRACE.count_candidates(trials)  # generated here, evaluated at the session's PoB boundary
            outcomes = self.pob.trial_stats(trials, self.objective.stat_keys, mode="full")
            best: tuple[Score, int] | None = None
            for cand, outcome in zip(candidates, outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    continue
                removed = {int(n) for n in outcome.get("removed_node_ids") or ()}
                added = {int(n) for n in outcome.get("added_node_ids") or ()}
                asc_after = (asc_before - removed) | {n for n in added if n in names}
                if len(asc_after) > len(asc_before) or removed & forced or cand not in asc_after:
                    continue  # the swap may not cost more points than it frees, nor take a node the request named
                score = self.objective.score(outcome["stats"])
                if best is None or score_key(plan.order)(score) > score_key(plan.order)(best[0]):
                    best = (score, cand)
            if best is None or not accepts(best[0], st.cur, min_gain=DEAD_ASCENDANCY_SHARE, order=plan.order):
                continue
            cand = best[1]
            label = f"{st.where} ascendancy swap {dead.name} -> {names[cand]}"
            with self._tools.attempt(label, ledger_name="ascendancy-swap", started=t0, before=before_score) as attempt:
                applied = self.pob.mutate_nodes(remove=[dead.node_id], add=[cand])
                keep = cand in {int(n) for n in applied.get("allocated_node_ids") or ()} or cand in {int(n) for n in applied.get("added_node_ids") or ()}
                if keep:
                    self.judging.rejudge(skeleton)
                    st.lanes_fresh = True
                    new = self._score_now()
                    keep = accepts(new, st.cur, min_gain=DEAD_ASCENDANCY_SHARE, order=plan.order)
                    if keep:
                        new = self._score_under_current_costs(new)  # #941 (a)
                        keep = accepts(new, st.cur, min_gain=DEAD_ASCENDANCY_SHARE, order=plan.order)
                if keep:
                    self.log(f"{label}: {st.cur.value:,.0f} (viol {st.cur.violation:.3f}) -> {new.value:,.0f} (viol {new.violation:.3f}) kept ({human_duration(time.perf_counter() - t0)})")
                    st.cur = new
                    st.kept_total += 1
                    st.changed_since_picks = st.changed_since_aura_levels = st.changed_since_lanes = True
                    now = {int(n) for n in self.pob.tree_light().get("user_allocated_node_ids") or ()}
                    skeleton.ascendancy_nodes = sorted(n for n in now if n in names)  # pipeline.py rebuilds the tree from it
                    st.notes.append(f"ascendancy swap {dead.name} -> {names[cand]} ({_moved(before_score, new)})")
                    kept_swaps += 1
                else:
                    self._restore_move(attempt.state, keep_rejections=True)  # a judged revert: the tree keeps its memory
                    self.log(f"{label}: reverted ({human_duration(time.perf_counter() - t0)})")
                    reverted += 1
            self.tree.note_build_change()  # the node set changed under every cached Score, kept or put back
            if kept_swaps != kept_before:
                dead_list = dead_ascendancy_nodes(self.pob, objective=self.objective, points_budget=self._ascendancy_points)  # the swap changed what the rest are worth
        self._record_move("ascendancy-swap", t0, before_score, st.cur, kept=bool(kept_swaps), reverted_by_judge=bool(reverted and not kept_swaps))

    def _lanes(self, t0: float, before: float) -> None:
        # the choices follow the build: a pass whose moves changed the tree, the gear or the link is
        # closed by judging them again (D60), so the next pass -- and the fixed point the loop stops
        # at -- is measured under the lanes the build will be reported with. The identity is judged
        # once, before pass 1, and in `_finish`: a bandit or a pantheon does not follow a rare slot.
        st, skeleton = self._st, self.skeleton
        if not st.changed_since_lanes:
            self._record_move("lanes", t0, st.cur, st.cur, kept=False)
            return
        label = f"{st.where} lanes"
        before_score = st.cur
        with self._tools.attempt(label, ledger_name="lanes", started=t0, before=before_score) as attempt:
            tuned = self._tune_lanes(skeleton, identity=False)
            st.lanes_fresh = True
            st.cur = self._score_now()
            st.changed_since_lanes = False
            if tuned:
                self.log(f"{label}: choices {tuned}, {before:,.0f} -> {st.cur.value:,.0f} (viol {st.cur.violation:.3f}, {time.perf_counter() - t0:.0f}s)")
            self._record_move("lanes", t0, before_score, st.cur, kept=st.cur != before_score, reverted_by_judge=False)
        if not attempt.dropped:
            self._judge_colours(time.perf_counter())  # #547: the pass ends on the colours the build is delivered with

    # -- the kicks -------------------------------------------------------------------------------------

    def _kicks(self) -> None:
        # nothing local moved: the neighbourhood is exhausted, so kick. On Cold DoT s3 the chain's
        # ruin-and-recreate round found +46% (139,058 -> 202,875) where the loop's local moves sat at
        # 193,065. While the local moves still keep something the next pass comes first.
        # A kick is one random draw, and one draw mostly misses: in run E the chain's reoptimize kept
        # round 2 of 3 on Cold DoT s1 (+3.1%) and its joint round 4 of 4 (+6.8%); the loop's single
        # draws both missed on the same seed (257,117 and 250,238 against 259,355) and it called that
        # the fixed point (loop-smoke-2, 2026-09-16). So each kick gets the chain's number of draws. Every
        # draw runs and is judged on its own: stopping at the first kept one starved the joint kick (Bleed
        # Bow s1: loop-smoke-2's joint draw found +18.4% in pass 3, loop-smoke-3's second tree draw took that
        # pass with +1.5% and the joint never ran at that state, 148% -> 89%). A kept kick gives the local
        # moves the next pass.
        st, plan = self._st, self._plan
        for group, draws in kick_plan(notes=st.notes, stopped=st.stopped, local_only=self._flags.local_only, moves=plan.moves, kick_draws=plan.kick_draws):
            kick = group.removeprefix("kick-")
            if st.stopped:
                break
            self.log(loop_move_line(st.p, group, self._flags.stage_name, prefix=plan.pass_prefix))  # #711
            for d in range(draws):
                if self._safety_net_reached():
                    break
                t0 = time.perf_counter()
                st.attempted_total += 1
                before_score = st.cur
                label = f"{st.where} kick {kick} (draw {d + 1} of {draws})"
                with self._tools.attempt(label, ledger_name="kick tree" if kick == "tree" else "kick joint", started=t0, before=before_score) as attempt:
                    if kick == "tree":
                        self._kick_tree(attempt, label, d, t0, before_score)
                    else:
                        self._kick_joint(attempt, label, d, t0, before_score)

    def _kick_tree(self, attempt: Attempt, label: str, d: int, t0: float, before_score: Score) -> None:
        st, tree = self._st, self.tree
        snapshot = self._snapshotter().take(xml=attempt.state["xml"], skeleton=True, history=True)  # #854: the judge's rejudge writes the Skeleton counts, `reoptimize` the tree steps
        was = self._fingerprint()
        tree.reoptimize(rounds=1, ruin_points=20, refine_rounds=10, seed=derive_seed(self._plan.seed, PURPOSE_TREE_KICK, st.p, d))  # keeps or restores by its own objective inside
        if self._fingerprint() == was:
            # the draw's own round restored the build (its objective said the ruin did not pay), so the
            # judge would measure the number it already has and revert to the build it already stands on:
            # 135 of 177 reverted tree draws of the 42 core14 logs did exactly that, 21,279 s of them
            self.log(f"{label}: no change, skipped ({time.perf_counter() - t0:.0f}s)")
            self._record_move("kick tree", t0, st.cur, st.cur, kept=False)
            return
        if attempt.judge_partial(lambda snap=snapshot: self._snapshotter().restore(snap)):
            st.notes.append(f"kick tree {_moved(before_score, st.cur)} (draw {d + 1})")

    def _kick_joint(self, attempt: Attempt, label: str, d: int, t0: float, before_score: Score) -> None:
        st, skeleton, loot, tree = self._st, self.skeleton, self.loot, self.tree
        was = self._fingerprint()
        incumbents = dict(loot.current_raw)  # #1152: what the round's victims held, read before it empties them
        snapshot = self._snapshotter().take(xml=attempt.state["xml"], skeleton=True, filler=FILLER_RAW, history=True)  # #854: the round's rejudge writes the Skeleton counts, allocate and refine the tree steps
        # i=d alternates the variant as the chain's rounds do (even: gear for damage, the tree repairs;
        # odd: the tree for damage, the gear repairs); run E's kept joint rounds on Cold DoT were both odd
        ruined = self._joint_round(skeleton, loot, tree, i=d, seed=derive_seed(self._plan.seed, PURPOSE_JOINT_ROUND, st.p), loot_n=self._plan.loot_n,
                                   rng=random.Random(derive_seed(self._plan.seed, PURPOSE_JOINT_KICK_RNG, st.p, d)),  # one stream per draw (#12): a move switched off shifts no later draw
                                   ruin_points=16, slots_per_round=2)

        def revert_joint(snapshot=snapshot) -> None:
            self._snapshotter().restore(snapshot)

        if self._fingerprint() == was:
            # The round emptied and refilled its slots and re-spent its points back to the same build.
            st.lanes_fresh = True  # _joint_round's own reconfigure ran on exactly this build
            self.log(f"{label} {ruined}: no change, skipped ({time.perf_counter() - t0:.0f}s)")
            self._record_move("kick joint", t0, st.cur, st.cur, kept=False)
            return
        joint_kept = attempt.judge_partial(revert_joint, f"{label} {ruined}", reconfigured=True,  # _joint_round derives the lanes itself
                                           must_keep=replaced_refused(loot, incumbents, getattr(skeleton, "forced_bases", {})))  # #1152: no victim is brought back refused
        tree.note_build_change()  # #34: kept or reverted, the round's Scores were cached on a gear PoB may no longer hold
        if joint_kept:
            st.notes.append(f"kick joint {_moved(before_score, st.cur)} (draw {d + 1})")
