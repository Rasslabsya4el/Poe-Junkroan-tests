"""Build a complete PoB build from a skeleton: coordinate descent over gear,
tree and config with PoB as the judge.

    gear (loot sim or wishlist, empty tree)  ->  tree (greedy)  ->  gear again  ->  tree
    rebuilt on gear  ->  the improvement loop (tree, gear, picks, kicks) to a
    fixed point  ->  config lanes  ->  the fixed-point check  ->  export

Each stage only knows the objective and PoB numbers. The skeleton fixes class,
ascendancy, keystones, gems, uniques and rare bases.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field, fields, replace
from contextlib import ExitStack
from typing import Any, Callable, Mapping, Sequence

from junkroan.optimizer.anoint_candidates import OIL_ORDER, anoint_candidates
from junkroan.optimizer.anoint_line import anoint_of, apply_anoint, can_anoint
from junkroan.optimizer.anoint_step import pick_anoint, repick_anoint
from junkroan.optimizer.audit import Finding, audit_build, missed_constraints
from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.explain import explain
from junkroan.optimizer.cluster_lines import ClusterCandidate, DAY1_PASSIVES, cluster_enchants, cluster_notables
from junkroan.optimizer.cluster_step import PlacedCluster, cluster_log_line, run_cluster_step
from junkroan.optimizer.cluster_trace import TracingClusterProbe, count_generated as count_generated_clusters, count_inner_skipped
from junkroan.optimizer.flask_lines import FlaskCandidate, flask_base, flask_base_allowed, flask_bases, flask_mods
from junkroan.optimizer.flask_probe import PobFlaskProbe
from junkroan.optimizer.flask_step import SLOTS as FLASK_SLOTS, flask_log_line, run_flask_step
from junkroan.optimizer.flask_trace import DIVINE_BASE, NO_DIVINE_CLASS, TracingFlaskProbe, count_generated as count_flasks_generated
from junkroan.optimizer.jewel_lines import jewel_line_candidates
from junkroan.optimizer.jewel_probe import PobJewelProbe, cluster_links_of, scalar
from junkroan.optimizer.jewel_trace import TracingJewelProbe, count_generated
from junkroan.optimizer.tree_trace import SEED_MOVE, count_zero as count_zero_tree_rails
from junkroan.optimizer.jewel_step import PlacedJewel, jewel_log_line, repick_jewels, run_jewel_step
from junkroan.optimizer.item_bases import base_record, bases_of_type, implicit_of, type_of
from junkroan.optimizer.judging import (
    MOVE, TREE, Judging, Mark, PobLanes, PobReads, lane_memo, restore_lanes, switch_off_unproven_charges, trauma_stacks, tune_choices, tune_given_choices, worse_input as _worse_input,
)
from junkroan.optimizer.stage_catalog import skipped_line, start_line
from junkroan.optimizer.seeds import (
    PURPOSE_CONSTRUCT_GEAR,
    PURPOSE_CONSTRUCT_GEAR_PASSES,
    PURPOSE_CONSTRUCT_RIG_FINAL_GEAR,
    PURPOSE_CONSTRUCT_RIG_GEAR,
    PURPOSE_HEADROOM_ROLLS,
    PURPOSE_HEADROOM_SLOTS,
    PURPOSE_JOINT_FILL_SLOT,
    PURPOSE_JOINT_KICK_RNG,
    PURPOSE_JOINT_ROUND,
    PURPOSE_LOOP_FILL_SLOT,
    PURPOSE_TREE_KICK,
    PURPOSE_TREE_TIES,
    derive_seed,
)
from junkroan.optimizer.loot_gear import LootGear, forced_mod_choices, ordered_slots, weapons_first
from junkroan.optimizer.move_ledger import render_move_table, render_pob_calls, tree_churn_metrics
from junkroan.optimizer.socket_step import candidate_sockets, colour_step, socket_lines, socket_state, sync_gear_sockets
from junkroan.optimizer.vaal_delivery import deliver_vaal_twins
from junkroan.optimizer.wishlist_gear import WishlistGear, is_pure_es
from junkroan.optimizer.objective import MAX_HIT_KEYS, Objective, Score, ScoreOrder, better_score, bossing_defence, score_key
from junkroan.optimizer.objective_select import forced_keystones_of, objective_for
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from junkroan.search.generator import SkeletonGenerator
from junkroan.optimizer.ramp import ramp_dps, ramp_context
from junkroan.optimizer.ramp_inputs import RAGE_INPUT, uncapped_ailment_stack_xml
from junkroan.optimizer import spectre_overlap
from junkroan.optimizer.spectre_overlap import spectre_overlap_stats
from junkroan.optimizer.self_cost import tree_patterns as self_cost_tree_patterns, trauma_lane_note
from junkroan.optimizer.rails import Rails, max_passive_points
from junkroan.optimizer.repair import (
    REPAIR_MAX_PASSES, BundleParts, RepairChoice, RepairOutcome, repair_gains, repair_verdict, resolve_keystone_id, should_continue, split_bundle,
)
from junkroan.optimizer.snapshot import FILLER_RAW, SKELETON_IDENTITY, SKELETON_WHOLE, Snapshotter
from junkroan.optimizer.tree_graph import Links, cluster_socket_size
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.optimizer import yield_probe
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import PobSession, encode_import_code
from junkroan.report_format import human_duration
from junkroan.search.skeleton import Skeleton
from junkroan.optimizer.improvement_loop import (
    WEAPON_BASE_NUMBER_LABELS, WEAPON_BASE_TYPES, AttemptTools, ImprovementLoop, LoopFlags,
    FIXED_POINT_MAX_EXTRA_PASSES, LoopOutcome, LoopPlan, WorkingBuild, _LoopState, _joint_round, _slots_with_damage_headroom, _weapon_base_candidates, _weapon_base_fingerprint, _weapon_base_move,
    _weapon_base_numbers, _weapon_item_parts, _weapon_raw_base, accepts, kick_plan, pass_plan,
)  # noqa: F401  (the constants are re-exports)
from junkroan.optimizer.build_result import BuildResult, REPORT_KEYS, StageRecord, commit_stage, record_stage, stage_record, take_picks  # noqa: F401  (re-exports)

SCREEN_LOOT_N = 60  # the cheap roll a screen ranks skeletons with

GEAR_MODES = {"loot": LootGear, "wishlist": WishlistGear}  # D19's loot simulation (the default) and D79's fixed templates


def wire_tree_rails(tree: TreeOptimizer, skeleton: Skeleton, *, forbidden_text: Sequence[str], protected: frozenset[int] | None = None) -> None:
    """The rails every TreeOptimizer of a run carries, wired after construction (#1038): the skeleton's forbidden
    keystones, the request's protected nodes when given, and the forbidden node text (conditional accuracy and the
    like never cap a gate, rails "tree"), which the trace counter `forbidden_node_text` is armed with."""

    tree.forbid(skeleton.forbid_keystones)
    if protected is not None:
        tree.protected = protected  # the request's forced nodes are never removed (#510)
    tree.forbid_text(forbidden_text)
    tree.audit_forbidden_text = tuple(forbidden_text)


def build_tree_optimizer(pob: Any, objective: Objective, rails: Rails, *, log: Callable[[str], Any], skeleton: Skeleton | None = None,
                         forbidden_text: Sequence[str] = (), protected: frozenset[int] | None = None, **search: Any) -> TreeOptimizer:
    """The one place a TreeOptimizer of the pipeline is constructed (#1038): the main run's two and the seeder's.

    Every one carries the rails' +30 attribute node cap (rulebook t-nodes, #430) and counts it (`attribute_cap_exceeded`).
    With a `skeleton` the forbidden keystones, protected nodes and forbidden node text are wired at once
    (`wire_tree_rails`); the main run has them only after its lanes are opened, so it wires them in `wire_tree`.
    `search` is the caller's own budget (max_depth, max_trials, skip_inert, cluster_candidates): a stage that must stay
    cheap keeps TreeOptimizer's defaults."""

    tree = TreeOptimizer(pob, objective, attribute_requirement_nodes_max=rails.attribute_plus30_nodes_max, log=log, **search)
    tree.audit_attribute_cap = rails.attribute_plus30_nodes_max
    if skeleton is not None:
        wire_tree_rails(tree, skeleton, forbidden_text=forbidden_text, protected=protected)
    return tree


def construction_loot_n(rails: Rails, loot_n: int | None, screen: bool) -> int:
    """How many rares the two construction rolls draw per slot (gear pass 1 on the empty tree,
    gear pass 2 with the tree).

    The seed-to-seed spread of a rebuilt reference is born in gear pass 1's loot roll and the
    deterministic tree greedy amplifies it (measured 2026-09-18): `gear.construction_best_of_n`
    = 600 instead of 200 lifted the greedy stage by +6.7 points (stormbrand) and +35.5 points
    (bleed_bow) of the author's number and cut the spread by 7.5 / 8.4 points, for +22 / +39 s
    per construction. An explicit `loot_n` from the caller wins, a screen keeps its small roll,
    and the improvement loop's per-slot re-rolls keep `gear.loot_best_of_n`.
    """

    if loot_n:
        return loot_n
    return SCREEN_LOOT_N if screen else rails.gear.construction_best_of_n


FEASIBILITY_TOLERANCE = 1e-9  # the same slack `Objective.violations` uses against PoB's 1.19999 vs 1.2
FINAL_FLOOR_REPAIR_ROUNDS = 4  # #553 rule 3: the most rounds of the last floor repair before a build is delivered


def keep_if_feasible(before: Score, after: Score, *, tolerance: float = FEASIBILITY_TOLERANCE) -> bool:
    """Is a finishing step allowed to stand? (D66)

    The delivered build is never less feasible than the fixed point the improvement loop reached.
    Value is the loop's business; a step that runs after it -- the list choices, the identity, the
    lanes -- may fail to raise the number, but may never buy it with a floor. So the only question
    asked of such a step is whether it introduced or grew a violation."""

    return after.violation <= before.violation + tolerance


def broken_floors(objective: Objective, before: Mapping[str, float], stats: Mapping[str, Any]) -> str:
    """The constraints a step introduced or grew, as "MoMUnreservedShare = 0.324 < 0.4": what the
    revert note says. `before` is `objective.violations(...)` of the state the step started from."""

    full = {**stats, **objective.derived_values(stats)}
    after = objective.violations(stats)
    parts: list[str] = []
    for key, value in sorted(after.items(), key=lambda kv: kv[0]):
        was = before.get(key, 0.0)
        if value <= was + FEASIBILITY_TOLERANCE:
            continue
        floor, observed = objective.floors.get(key), full.get(key)
        if floor is not None and isinstance(observed, (int, float)):
            parts.append(f"{key} = {float(observed):.3f} < {floor:g}")
        else:
            parts.append(f"{key} (viol {was:.3f} -> {value:.3f})")
    return "; ".join(parts) or "the objective"


def tune_flat_reservation_aura_levels(pob: Any, objective: Objective, rails: Any, skeleton: Skeleton, *, order: ScoreOrder = "floors") -> dict[str, int]:
    """Choose each enabled flat-reservation aura's level with the complete current objective.

    PoB's level data identifies these gems (`manaReservationFlat` on a non-mine reservation
    skill).  Every legal rail level is a real skills write and score, so a level that makes a
    mana, sustain, or defensive floor fail loses under the ordinary Score ordering.  The first
    equal score wins, which keeps the lowest reservation when PoB finds no numeric distinction.
    `order` is the Score order of the choice ("floors" by default; the improvement loop passes
    "priced", D116 / #553).
    """

    key = score_key(order)

    find_auras = getattr(skeleton, "flat_reservation_auras", None)
    if not callable(find_auras):  # lightweight loop fakes have no gem data surface
        return {}
    names = find_auras()
    if not names:
        skeleton.aura_levels.clear()
        return {}
    rail = rails.gems.level
    skeleton.aura_levels = {name: level for name, level in skeleton.aura_levels.items() if name in names}
    for name in names:
        best: tuple[Score, int] | None = None
        for level in range(1, rail + 1):
            skeleton.aura_levels[name] = level
            skeleton.apply_skills(pob, gem_level=rail, gem_quality=rails.gems.quality,
                                  main_quality=rails.gems.main_quality)
            score = objective.score(pob.stats(objective.stat_keys))
            if best is None or key(score) > key(best[0]):
                best = (score, level)
        if best is not None and best[1] < rail:
            skeleton.aura_levels[name] = best[1]
        else:
            skeleton.aura_levels.pop(name, None)
    skeleton.apply_skills(pob, gem_level=rail, gem_quality=rails.gems.quality,
                          main_quality=rails.gems.main_quality)
    return dict(skeleton.aura_levels)


def loop_stop_label(stopped: str) -> str:
    """#38: the improvement loop's own stop reason (`LoopOutcome.stopped`) -> `BuildResult.loop_stop`. "" (a pass that kept nothing) and "max passes" both read
    as "converged"; only "time budget" reads as "time" (`_fixed_point_check`'s own comment: the
    loop stops on one of two things, its time budget and its pass limit)."""

    return "time" if stopped == "time budget" else "converged"


def protected_nodes_of(skeleton: Skeleton, selected_effects: Mapping[int, int] | None = None) -> frozenset[int]:
    """The nodes the request's forced ids pin: each forced node by its id, each forced mastery effect by the
    mastery node that carries it in the build (`selected_effects`: node -> effect id, from the build's tree)."""

    forced = frozenset(int(n) for n in getattr(skeleton, "forced_nodes", ()))
    if not forced or not selected_effects:
        return forced
    from junkroan.optimizer.tree_graph import TreeGraph

    return forced | TreeGraph.load().protected_nodes(forced, selected_effects)


def forced_lines_of(skeleton: Skeleton) -> dict[str, list[str]]:
    return {slot: list(lines) for slot, lines in getattr(skeleton, "forced_affixes", {}).items()}


def _rebuild_trace_line(label: str, grown: Score, grown_viol: dict[str, float], delivered: Score, delivered_viol: dict[str, float]) -> str:
    """One line per rebuild attempt (#617): the score the greedy and refine climbed (construction objective) and the
    one the build is delivered on, each with the floors it misses, largest relative miss first."""

    def floors(viol: dict[str, float]) -> str:
        return ": " + ", ".join(f"{k} {v:.3g}" for k, v in sorted(viol.items(), key=lambda kv: -kv[1]) if v > 0) if any(v > 0 for v in viol.values()) else ""

    return (f"rebuild {label}: construction {grown.value:,.0f} (viol {grown.violation:.3f}{floors(grown_viol)}) | "
            f"delivered {delivered.value:,.0f} (viol {delivered.violation:.3f}{floors(delivered_viol)})")


@dataclass(frozen=True)
class _FinishEntry:
    """What `_finish` measures and keeps of the build the loop handed over (#814): the entry numbers, the snapshot
    that the D66 fallback loads back with its colour memory and lanes, and the lanes derived on it."""

    t0: float
    stats: dict
    score: Score
    moves_before_final_lanes: int
    gear: Any
    shots: Snapshotter
    snapshot: Any
    sockets: Any
    derived: Any
    lanes: Any



def _snapshotter(pipeline: Any, skeleton: Skeleton, *, filler: Any = None, trees: Callable[[], Any] | None = None) -> Snapshotter:
    """The holders of the build's state as they are now; every revert here goes through `Snapshotter` (#813).
    `trees` are the judging's attached trees unless a site names its own."""

    return Snapshotter(pob=pipeline.pob, skeleton=skeleton, filler=filler, judging=pipeline.judging, trees=trees or (lambda: pipeline.judging.trees()))


class BuildPipeline:
    # Class default, so a pipeline the unit harnesses build with `__new__` carries
    # it too; a real build gets its own metrics from the property below.
    _castability_metrics: CastabilityMetrics | None = None

    @property
    def objective(self) -> Objective:
        """The full objective the build is judged under."""

        return self.judging.objective

    @objective.setter
    def objective(self, objective: Objective) -> None:
        self.judging.objective = objective

    def __init__(self, pob: PobSession, rails: Rails | None = None, *, objective: Objective | None = None,
                 log: Callable[[str], None] | None = None, construction: str = "classic") -> None:
        if construction not in {"classic", "rig-first"}:
            raise ValueError(f"unknown construction {construction!r}: one of classic, rig-first")
        self.pob = pob
        self.rails = rails or Rails.load()
        self.log = log or (lambda _m: None)
        self.construction = construction
        self._castability_metrics = CastabilityMetrics()
        self.judging = Judging(PobLanes(pob, log=lambda message: self.log(message)),
                               PobReads(pob, gems=self.rails.gems, log=lambda message: self.log(message), metrics=self._castability_metrics),
                               objective=objective or self.rails.objective(), log=lambda message: self.log(message))

    @property
    def castability_metrics(self) -> CastabilityMetrics:
        """What the frozen skill-cost reads cost this build (calls and seconds)."""

        if self._castability_metrics is None:
            self._castability_metrics = CastabilityMetrics()
        return self._castability_metrics

    @castability_metrics.setter
    def castability_metrics(self, metrics: CastabilityMetrics) -> None:
        self._castability_metrics = metrics

    def _flat_reservation_stage(self, result: BuildResult, skeleton: Any, gear_pass_1: tuple[str, float] | None = None) -> None:
        """The flat-reservation aura levels, after the config re-derivation (#176). `gear_pass_1` is (name, t0) of the
        gear pass 1 record this call writes (#189): with a changed config input the record keeps the value from
        before the rejudge and the `config re-derived` line carries the rejudge (#176); with none, the rejudge
        comes first and the record is written after it."""

        t0 = time.perf_counter()
        pending = self._stage_record(result, *gear_pass_1) if gear_pass_1 else None
        inputs_before = dict(self.pob.config_inputs()) if hasattr(self.pob, "config_inputs") else {}
        self.judging.rejudge(skeleton)  # levels are judged under the first gear fill's own lane
        inputs_after = dict(self.pob.config_inputs()) if hasattr(self.pob, "config_inputs") else {}
        changed = [f"{key} {inputs_before.get(key)} -> {inputs_after.get(key)}"
                   for key in sorted(set(inputs_before) | set(inputs_after)) if inputs_before.get(key) != inputs_after.get(key)]
        if pending is not None and not changed:
            self._record(result, *gear_pass_1)  # no re-derived line: the gear pass 1 record itself follows the rejudge
        elif pending is not None:
            self._commit_stage(result, pending)
        if changed:  # a correction, not a move (#176): its effect is charged to nothing else
            self._step_start("config re-derived (after gear pass 1)")
            self._record(result, "config re-derived (after gear pass 1)", t0, ", ".join(changed))
            t0 = time.perf_counter()
        else:
            self._step_skipped("config re-derived (after gear pass 1)")
        self._step_start("flat-reservation aura levels")
        aura_levels = self._tune_flat_reservation_aura_levels(skeleton)
        self.judging.rejudge(skeleton)
        self._record(result, "flat-reservation aura levels", t0, ", ".join(f"{name} {level}" for name, level in aura_levels.items()) or "rail")

    def _record_rejudged(self, result: BuildResult, skeleton: Any, name: str, t0: float, notes: str = "") -> None:
        """A construction stage record written after a rejudge of the build it records (#189): the config
        carries the lane's inputs at the point the stage is recorded. A correction, never gated by `better_score`."""

        self.judging.rejudge(skeleton)
        self._record(result, name, t0, notes)

    def _step_start(self, name: str) -> None:
        """#711: the log line that says a step has begun (the monitor reads it back); no PoB call."""

        self.log(start_line(name))

    def _step_skipped(self, *names: str) -> None:
        """#711: the log line of a conditional step that does not run for this build."""

        for name in names:
            self.log(skipped_line(name))

    def _record(self, result: BuildResult, name: str, t0: float, notes: str = "") -> None:
        record_stage(self.pob, self.objective, result, name, t0, notes, self.log)

    def _stage_record(self, result: BuildResult, name: str, t0: float, notes: str = "") -> StageRecord:
        """The record of the build PoB holds now, not yet written to the result."""

        return stage_record(self.pob, self.objective, result, name, t0, notes)

    def _commit_stage(self, result: BuildResult, record: StageRecord) -> None:
        commit_stage(result, record, self.log)

    @staticmethod
    def _tree_nodes(pob: PobSession) -> set[int]:
        reader = getattr(pob, "tree_light", None)
        if not callable(reader):
            return set()
        state = reader() or {}
        return {int(node) for node in state.get("user_allocated_node_ids") or ()}

    def wire_tree(self, tree: TreeOptimizer, skeleton: Skeleton, *, forbidden_text: tuple[str, ...], protected: frozenset[int] | None = None) -> None:
        """One TreeOptimizer's per-run wiring (#51): the forbidden keystones and node text, the request's
        protected nodes when given, and the five hooks that keep the judging lanes with every move."""

        def restore_tree_context(context: object) -> None:
            # an XML restore includes its lanes; restore the matching objective without re-deriving them
            if isinstance(context, Mark):
                self.judging.restore(context)

        wire_tree_rails(tree, skeleton, forbidden_text=forbidden_text, protected=protected)
        self._tree_forbidden_text = tuple(forbidden_text)  # what the seeder of this run is wired with too (`_seed_scaling`)
        tree.enabler_hook = lambda cand, trial: self._value_with_enabled(skeleton, tree, cand, trial)
        tree.after_apply_hook = lambda _cand: self.judging.rejudge(skeleton)
        tree.after_proof_removal_hook = lambda _applied: self.judging.rejudge(skeleton)
        tree.snapshot_context_hook = lambda: self.judging.mark(TREE)
        tree.restore_context_hook = restore_tree_context

    def _tree_optimizers(self, pob, tree_max_depth, tree_max_trials, cluster_candidates, skip_inert):
        """The two TreeOptimizers of a run; both carry the rails' +30 attribute node cap (rulebook t-nodes, #430)."""

        common = dict(max_depth=tree_max_depth, max_trials=tree_max_trials, cluster_candidates=cluster_candidates, skip_inert=skip_inert)
        tree = build_tree_optimizer(pob, self.judging.cut("tree_construction"), self.rails, log=self.log, **common)
        tree_full = build_tree_optimizer(pob, self.judging.cut("tree"), self.rails, log=self.log, **common)
        self.judging.attach("tree_construction", tree)
        self.judging.attach("tree", tree_full)
        tree.cluster_links = tree_full.cluster_links = lambda: BuildPipeline._cluster_links(self)  # a placed cluster's nodes hang off its outer socket (#433)
        return tree, tree_full

    def _cluster_links(self) -> Links | None:
        """The extra connectivity edges of the cluster jewels the build carries (`_clusters`): read from PoB once per
        carried set (the subgraph is a function of the jewel text), None, and no PoB read, when the build carries none."""

        clusters = getattr(self, "_clusters", None)
        if not clusters:
            return None
        key = tuple(sorted(clusters.items()))
        cached = getattr(self, "_cluster_links_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, cluster_links_of(self.pob, sorted(clusters)))
            self._cluster_links_cache = cached
        return cached[1]

    def run(self, skeleton: Skeleton, *, tree_points: int | None = None, loot_n: int | None = None, gear_passes: int = 2, seed: int = 1,
            gear_mode: str = "loot",
            screen: bool = False, repick_supports: bool = False, pick_utilities: bool = True,
            rebuild_tree: bool = True, tree_max_depth: int = 6, tree_max_trials: int = 300,
            loop_max_passes: int = 16, loop_max_seconds: float | None = None, loop_min_gain: float = 0.005,
            loop_kick_draws: tuple[int, int] = (3, 4), cluster_candidates: bool = False, skip_inert: bool = False,
            fulldps_shortcut: bool = False, fixed_point_check: bool = True, construction_only: bool = False) -> BuildResult:
        """Construction (skeleton, config lanes, gear, greedy tree, gear again, the tree rebuilt on
        the gear, the discrete picks), then the improvement loop to a fixed point, then `_finish`,
        which closes with the fixed-point check (`fixed_point_check`, ROADMAP 7.3).

        The six stages that used to follow the rebuild -- tree refine + reoptimize, tree path swaps,
        gear pass 3, tree touch-up, joint tree+gear, picks re-judged -- are gone (D58): each was one
        approximation of one pass of the loop judged by its own objective, and the loop beat the
        chain on every smoke reference (cold_dot 137 vs 119, bleed_bow 147 vs 116, SRS 242 vs 198,
        impale_ballista 84 vs 65, stormbrand 165 vs 124, burning_arrow 200 vs 169).

        screen=True: the cheap version for ranking many skeletons (small loot N, greedy tree, one
        refine, no rebuild / re-picks / loop).

        `gear_mode`: "loot" (the default, D19) rolls best of N random rares per slot;
        "wishlist" (D79) writes the deterministic template item instead -- the same filler in
        construction and in the improvement loop's per-slot gear move, where the slot's re-roll
        becomes a re-fill on the build as it stands. The loot simulation stays the default until
        the benchmark says otherwise."""

        if gear_mode not in GEAR_MODES:
            raise ValueError(f"unknown gear_mode {gear_mode!r}: one of {sorted(GEAR_MODES)}")
        construction = getattr(self, "construction", "classic")
        if construction not in {"classic", "rig-first"}:
            raise ValueError(f"unknown construction {construction!r}: one of classic, rig-first")
        if construction_only and (screen or not rebuild_tree):
            raise ValueError("construction_only requires the non-screen tree rebuild")
        yield_probe.check("start")  # #621
        t_all = time.perf_counter()
        self.pob.fulldps_shortcut = fulldps_shortcut # approximate (off by default: the speed-both-2 gate of 2026-09-18 failed at -6.4 points for -10% time): PobSession.trial_stats
        self.objective = objective_for(self.rails, skeleton.main_link[0], self.objective, mode=skeleton.mode, forced_keystones=forced_keystones_of(skeleton))  # mode stat / FullDPS for minions (D37, D38)
        if screen:
            loot_n = loot_n or SCREEN_LOOT_N
            gear_passes = 1
        construction_n = construction_loot_n(self.rails, loot_n, screen)  # 600 by default (2026-09-18); the loop keeps loot_best_of_n
        result = BuildResult(skeleton=skeleton, objective_stat=self.objective.maximize, gear_mode=gear_mode)
        pob = self.pob
        reset_calls = getattr(pob, "reset_pob_calls", None)
        if callable(reset_calls):
            reset_calls()
        self._socket_lines = None  # #547: what the last colour step left (`socket_state`); None = no step ran on this build yet
        self._jewels: dict[int, str] = {}  # #434: the jewels the step placed ({socket node id: raw item text}); every later set_tree passes them
        self._jewel_placed: list[PlacedJewel] = []  # the step's own record of them, for the end re-pick
        self._clusters: dict[int, str] = {}  # #433: the cluster jewels the step placed ({socket node id: raw}); carried like `_jewels`
        self._cluster_nodes: dict[int, tuple[int, ...]] = {}  # their allocation (path to the socket + inner nodes), carried by every set_tree
        self._cluster_placed: list[PlacedCluster] = []
        self._flasks: dict[str, str] = {}  # #436: the flasks the step placed ({slot: raw item text}); `_restore_flasks` puts them back if a later move dropped one
        self._anoint_first = None  # the amulet anoint step's pick, read by the end re-pick (#432)
        self._anoint_all: list = []  # the candidates that step measured
        self._rails_identity(skeleton)

        self._step_start("skeleton applied")
        t0 = time.perf_counter()
        skeleton.apply(pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality, main_quality=self.rails.gems.main_quality)
        self.judging.refresh_castability()
        part_note = ""
        if skeleton.main_part is None:
            from junkroan.search.generator import SkeletonGenerator

            gen = self._generator()
            _idx, part_name = gen.pick_skill_part(skeleton)
            self._take_picks(result, gen, before=None)
            part_note = f"part {part_name!r}" if part_name else ""
        else:
            from junkroan.optimizer.random_parts import mean_parts_for

            pob.mean_parts = mean_parts_for(skeleton.main_link[0], skeleton.main_part)  # a random-element skill: the mean over its element parts
        if pob.mean_parts:
            part_note = (part_note + " " if part_note else "") + f"parts {pob.mean_parts} averaged (random element)"
        counts_before = dict(skeleton.gem_counts)
        counts = skeleton.refresh_minion_counts(pob, gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality,
                                                main_quality=self.rails.gems.main_quality, log=self.log)
        chosen = skeleton.tune_minion_skills(pob, lambda: self.objective.score(pob.stats(self.objective.stat_keys)), gem_level=self.rails.gems.level, gem_quality=self.rails.gems.quality, main_quality=self.rails.gems.main_quality) if counts else {}
        if counts_before != skeleton.gem_counts or chosen:
            self.judging.refresh_castability()
        self._record(result, "skeleton applied", t0, part_note + (f" minions {counts}" if counts else "") + (f" minion skills {chosen}" if chosen else ""))

        # config lanes first so every later evaluation sees a defensible config
        self._step_start("config (conservative lane)")
        t0 = time.perf_counter()
        opening = self.judging.open(skeleton)
        derived, triggered = opening.lanes, opening.triggered
        self._record(result, "config (conservative lane)", t0, f"{len(derived.conservative.inputs)} inputs on")

        pure_es = bool(skeleton.pure_es) or is_pure_es(pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        # the skeleton's unique raws, so the filler can put a weapon's pair back after a refill
        # (a gear pass that empties Weapon 1 drops a unique quiver silently, D99)
        unique_gear = {slot: pob.unique_item(name)["raw"] for slot, name in skeleton.uniques.items()}
        gear_objective = self.judging.cut("gear")
        loot = (WishlistGear(pob, gear_objective, self.rails, log=self.log, pure_es=pure_es, uniques=unique_gear)
                if gear_mode == "wishlist" else LootGear(pob, gear_objective, self.rails, log=self.log, uniques=unique_gear))
        loot.forced_lines = forced_lines_of(skeleton)  # the request's forced affixes (#510)
        self.judging.attach("gear", loot)
        # movement speed is a gear floor (boots, D28): the tree cannot buy it efficiently and
        # would waste points chasing it, so tree stages optimize without that floor
        # ... and resource sustain is cheaper from gear (mana leech / regen affixes) than from
        # the tree, where chasing it early cost Poison Spectral Throw half its greedy DPS;
        # the construction stages use that tree; the loop drives `tree_full`, which carries sustain,
        # so the sustain floor enters once the gear that pays for it is on the build
        tree, tree_full = self._tree_optimizers(pob, tree_max_depth, tree_max_trials, cluster_candidates, skip_inert)
        tree.tie_seed = tree_full.tie_seed = derive_seed(seed, PURPOSE_TREE_TIES)  # #619: two seeds part ways where PoB scored two nodes equal
        # a passive or mastery whose text is a self-cost for the main skill is not a candidate at all
        # (the user on soulrend s1's Chaos Mastery: "you cannot take this unless something else
        # triggers your chaos skills"); the floor prices the ones the build already carries
        self_cost_text = () if triggered else self_cost_tree_patterns(tree.graph, self.judging.main_tags)

        protected = self._protected_nodes(skeleton)  # the holder of a forced mastery effect is fixed once the skeleton is applied
        for opt in (tree, tree_full):
            self.wire_tree(opt, skeleton, forbidden_text=(*self.rails.forbidden_node_text, *self_cost_text), protected=protected)
        self.judging.post_holders(derived, (tree, tree_full))
        # PoB's own limit for the level without the bandit reward (rails.max_passive_points); the points for
        # killing every bandit are allocated in `_tune_identity`, once the tree exists to spend them on
        points = tree_points or max_passive_points(skeleton.level)
        used = self._points_used()

        if construction == "rig-first":
            self._step_start("rig gear")
            t0 = time.perf_counter()
            loot.fill(skeleton.rare_bases, sockets_by_slot=skeleton.sockets, passes=1, n=40, seed=derive_seed(seed, PURPOSE_CONSTRUCT_RIG_GEAR))
            self._record(result, "rig gear", t0)

            self._step_start("rig tree")
            t0 = time.perf_counter()
            old_max_trials = tree.max_trials
            tree.max_trials = 300
            try:
                rig_alloc = tree.allocate(points // 2)
            finally:
                tree.max_trials = old_max_trials
            self._record(result, "rig tree", t0, rig_alloc.stopped_reason)

            self._step_start("gear pass 1 (rig tree)")
            t0 = time.perf_counter()
            loot.fill(skeleton.rare_bases, sockets_by_slot=skeleton.sockets, passes=1, n=construction_n, seed=derive_seed(seed, PURPOSE_CONSTRUCT_RIG_FINAL_GEAR))
            self._record_rejudged(result, skeleton, "gear pass 1 (rig tree)", t0)

            # The rig is only a partner for the first full gear fill. The ordinary greedy tree must
            # start from the same fixed skeleton tree as the classic construction.
            self._reset_construction_tree(skeleton, tree)
            self.judging.rejudge(skeleton)
            self._step_skipped("gear pass 1 (empty tree)")
            if skeleton.flat_reservation_auras():
                self._flat_reservation_stage(result, skeleton)
            else:
                self._step_skipped("config re-derived (after gear pass 1)", "flat-reservation aura levels")
        else:
            self._step_skipped("rig gear", "rig tree", "gear pass 1 (rig tree)")
            self._step_start("gear pass 1 (empty tree)")
            t0 = time.perf_counter()
            loot.fill(skeleton.rare_bases, sockets_by_slot=skeleton.sockets, passes=1, n=construction_n, seed=derive_seed(seed, PURPOSE_CONSTRUCT_GEAR))
            if skeleton.flat_reservation_auras():
                # #176 and #189: the stage helper writes this record, after its rejudge unless a config input changed
                self._flat_reservation_stage(result, skeleton, gear_pass_1=("gear pass 1 (empty tree)", t0))
            else:
                self._record_rejudged(result, skeleton, "gear pass 1 (empty tree)", t0)
                self._step_skipped("config re-derived (after gear pass 1)", "flat-reservation aura levels")
        if not result.stages[-1].score_value > 0 and self._revivable_supports(skeleton):
            # no number, and the link carries supports another weapon chose (a weapon variant inherits the sword
            # finalist's Close Combat, which zeroes Smite on a staff or a sceptre): the supports are chosen again on
            # this rig before any tree is grown (D52 follow-up), and the later re-pick and re-judge refine them
            self._step_start("supports re-picked (no number)")
            t0 = time.perf_counter()
            self._record(result, "supports re-picked (no number)", t0, self._revive_supports(skeleton, result))
        else:
            self._step_skipped("supports re-picked (no number)")
        if not result.stages[-1].score_value > 0:
            # no number with a weapon in hand: the main skill cannot be used as the skeleton stands (Smite with Close
            # Combat on a staff or a sceptre: 0 DPS); a Smite search once optimized four such weapon variants for 15 min
            # each, to 20-31k with 26 nodes, and ranked them next to the real builds
            raise ValueError(f"{skeleton.main_link[0]} has no {self.objective.maximize} with this skeleton (weapon {skeleton.rare_bases.get('Weapon 1') or skeleton.uniques.get('Weapon 1') or 'none'}, link {skeleton.main_link[1:]}): the skill cannot be used as it stands")

        if skeleton.scaling and skeleton.scaling.get("stat"):
            self._step_start(f"tree seed toward {skeleton.scaling['stat']}")
            t0 = time.perf_counter()
            note = self._seed_scaling(skeleton, points)
            used = self._points_used()
            self._record_rejudged(result, skeleton, f"tree seed toward {skeleton.scaling['stat']}", t0, note)
        else:
            self._step_skipped("tree seed toward <stat>")

        self._step_start("tree greedy")
        t0 = time.perf_counter()
        alloc = tree.allocate(max(0, points - used))
        # the rejudge before this record is also the rejudge gear pass 2's fill starts from: nothing stands between
        self._record_rejudged(result, skeleton, "tree greedy", t0, alloc.stopped_reason)

        self._step_start("gear pass 2 (with tree)")
        t0 = time.perf_counter()
        # incumbents compete and never trade down (D43: a fresh pass on the finished tree lost Smite 498k -> 317k)
        loot.fill(skeleton.rare_bases, sockets_by_slot=skeleton.sockets, passes=gear_passes, n=construction_n, seed=derive_seed(seed, PURPOSE_CONSTRUCT_GEAR_PASSES))
        self.judging.rejudge(skeleton)  # gear and tree changed the sources; keep the lanes honest for what follows
        self._record(result, "gear pass 2 (with tree)", t0)

        if rebuild_tree and not screen:
            # the greedy tree was grown before the gear existed; grown again on the finished gear it can be
            # a different tree (Viper Strike: a 95-node cascade re-spent with the gear in place, 477k -> 970k; D45)
            self._step_start("tree rebuilt on gear")
            t0 = time.perf_counter()
            # #617: grown on the construction view the regrown tree dropped mana sustain (901k -> 162k on summon_raging_spirits s4); the gear that pays for it is on now
            self._record_rejudged(result, skeleton, "tree rebuilt on gear", t0, self._rebuild_tree(skeleton, tree_full, points))
            result.construction_tree = sorted(self._tree_nodes(pob))
        else:
            self._step_skipped("tree rebuilt on gear")
            if not result.construction_tree:
                result.construction_tree = sorted(self._tree_nodes(pob))

        if construction_only:
            return self._finish_construction(result, t_all)

        if screen:
            self._step_skipped("anoint", "flasks")
        if not screen:
            self._anoint_step(result, skeleton, loot)  # #432: the amulet's anoint, on the finished tree and gear, before the supports are judged
        if not screen:
            self._flask_step(result, skeleton)  # #436: day-1 flasks and tinctures, after gear and the anoint, before the jewels and the supports are judged
        if rebuild_tree and not screen:
            self._cluster_step(result, skeleton, loot, tree_full, points, tree_max_depth)  # #433: day-1 rare cluster jewels, before the regular jewels: a regular jewel never takes a cluster socket first
            self._jewel_step(result, skeleton, tree_full, points, tree_max_depth)  # #434: day-1 rare jewels, before the supports are chosen again
        else:
            self._step_skipped("clusters", "jewels")

        if repick_supports and not screen:
            # the screen's supports were chosen on a bare rig; choose again with tree and gear in place
            from junkroan.search.generator import SkeletonGenerator

            self._step_start("supports re-picked")
            t0 = time.perf_counter()
            before = list(skeleton.main_link)
            value_before = self.objective.score(pob.stats(self.objective.stat_keys)).value
            gen = self._generator()
            gen.pick_supports(skeleton, n_supports=self.rails.gems.main_link_max - 1, reconfigure=self.judging.rejudger(skeleton))
            self._take_picks(result, gen, before=value_before)
            self._record(result, "supports re-picked", t0, f"{before[1:]} -> {skeleton.main_link[1:]}")
        else:
            self._step_skipped("supports re-picked")

        max_groups = skeleton.utility_groups if skeleton.utility_groups is not None else self.rails.utility_max_groups
        from junkroan.search.generator import movement_pair_missing, utility_groups_used

        # the movement pair is outside max_groups (#1153): a build at the cap still gets the picker while a slot is empty
        if pick_utilities and not screen and (utility_groups_used(skeleton.extra_groups, self.rails) < max_groups
                                              or movement_pair_missing(skeleton.extra_groups, skeleton.main_link, self.rails)):
            from junkroan.search.generator import SkeletonGenerator

            self._step_start("utility links")
            t0 = time.perf_counter()
            value_before = self.objective.score(pob.stats(self.objective.stat_keys)).value
            gen = self._generator()
            added = gen.pick_utilities(skeleton, max_groups=max_groups, reconfigure=self.judging.rejudger(skeleton))
            self._take_picks(result, gen, before=value_before)
            self._record(result, "utility links", t0, ", ".join(g.gems[0] for g in added) or "none")
        else:
            self._step_skipped("utility links")

        if pick_utilities and not screen and getattr(self.rails, "fill_step", False):
            self._fill_step(result, skeleton)  # #1156: the free sockets get the gems PoB counts, outside max_groups
        else:
            self._step_skipped("fill")

        if not result.construction_tree:
            result.construction_tree = sorted(self._tree_nodes(pob))

        if screen:
            self._step_start("tree refine")
            t0 = time.perf_counter()
            tree.refine(max_rounds=8)
            self._record_rejudged(result, skeleton, "tree refine", t0)
            # a screen has no improvement loop: its own refine is the last construction stage, so the
            # ledger's identity starts after it and is not off by that stage's gain
            result.ledger_construction_value = result.stages[-1].score_value
            self._step_skipped("anoint re-pick")
            return self._finish(result, skeleton, t_all)

        self._step_skipped("tree refine")
        result.ledger_construction_value = result.stages[-1].score_value  # construction ends here; the loop's ledger starts

        # D58: one loop over moves -- tree refine, tree path swaps, one rare slot re-rolled at a
        # time, the discrete picks, and the two kicks when nothing local moved -- run to a fixed
        # point under the full objective, in place of the six chain stages that used to follow
        loop_plan = LoopPlan(seed=seed, max_passes=loop_max_passes, max_seconds=loop_max_seconds, min_gain=loop_min_gain, loot_n=loot_n,
                             kick_draws=loop_kick_draws, kind="loop", moves=None)
        outcome = self.improve(WorkingBuild(pob=self.pob, judging=self.judging, skeleton=skeleton, gear=loot, tree=tree_full), result, loop_plan)
        result.loop_stop = loop_stop_label(outcome.stopped)  # #38
        self._anoint_repick(result, skeleton, loot)  # #432: the final tree decides the anoint again, before the final lanes
        self._jewel_repick(result, skeleton, tree_full, points, tree_max_depth)  # #434: each jewel's line measured again on the final tree and gear
        return self._finish(result, skeleton, t_all, fixed_point={"loot": loot, "tree": tree_full, "loot_n": loot_n, "seed": seed,
                                                                  "min_gain": loop_min_gain, "max_seconds": loop_max_seconds,
                                                                  "enabled": fixed_point_check, "loop_outcome": outcome})

    @staticmethod
    def _revivable_supports(skeleton: Skeleton) -> bool:
        """Does the main link carry a support the request did not fix (one PoB may choose again)?"""

        enablers = skeleton.enablers()
        return any(s not in skeleton.fixed_supports and s not in enablers for s in skeleton.main_link[1:])

    def _revive_supports(self, skeleton: Skeleton, result: BuildResult) -> str:
        """The main link's supports chosen again by PoB on the rig as it stands (the fixed ones
        stay), for a skeleton whose skill has no number with the supports it inherited."""

        from junkroan.search.generator import SkeletonGenerator

        before = list(skeleton.main_link)
        gen = self._generator()
        gen.pick_supports(skeleton, n_supports=min(max(1, len(before) - 1), self.rails.gems.main_link_max - 1), reconfigure=self.judging.rejudger(skeleton))
        self._take_picks(result, gen, before=0.0)
        return f"{before[1:]} -> {skeleton.main_link[1:]}"

    def _tune_flat_reservation_aura_levels(self, skeleton: Skeleton, *, order: ScoreOrder = "floors") -> dict[str, int]:
        # getattr: a loop fake without a session still reaches the no-aura exit, which touches none of the three
        return tune_flat_reservation_aura_levels(getattr(self, "pob", None), getattr(self, "objective", None), getattr(self, "rails", None), skeleton, order=order)

    def _joint_round(self, skeleton: Skeleton, loot: LootGear | WishlistGear, tree: TreeOptimizer, *, i: int, seed: int, loot_n: int | None,
                     rng, ruin_points: int, slots_per_round: int, refine_rounds: int = 6) -> str:
        return _joint_round(self.pob, self.objective, self.judging, skeleton, loot, tree, i=i, seed=seed, loot_n=loot_n, rng=rng, ruin_points=ruin_points,
                            slots_per_round=slots_per_round, headroom=self._slots_with_damage_headroom, refine_rounds=refine_rounds)

    @staticmethod
    def _weapon_item_parts(raw: str) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], int | None, str | None]:
        return _weapon_item_parts(raw)

    def _weapon_base_candidates(self, loot: LootGear | WishlistGear, base: str) -> list[str]:
        return _weapon_base_candidates(self.rails, loot, base)

    @staticmethod
    def _weapon_raw_base(raw: str) -> str:
        return _weapon_raw_base(raw)

    @staticmethod
    def _weapon_base_numbers(raw: str) -> dict[str, str]:
        return _weapon_base_numbers(raw)

    def _weapon_base_fingerprint(self, loot: LootGear | WishlistGear, skeleton: Skeleton, slot: str, *, config_xml: str | None = None) -> tuple:
        return _weapon_base_fingerprint(self.pob, loot, skeleton, slot, config_xml=config_xml)

    def _weapon_base_move(
        self,
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
        order: ScoreOrder = "priced",
    ) -> tuple[bool, str | None]:
        # every overridable pipeline method is read off self here, at call time, so an instance-attribute fake still takes effect
        return _weapon_base_move(
            self.pob, self.objective, getattr(self, "rails", None), lambda message: self.log(message), result, skeleton, loot, slot,
            current_score=current_score, min_gain=min_gain, move_state=move_state, snapshot_fresh=snapshot_fresh, t0=t0, judge=judge,
            restore_move=restore_move, last_rejected=last_rejected, order=order, raw_base=self._weapon_raw_base, fingerprint_of=self._weapon_base_fingerprint,
            item_parts=self._weapon_item_parts, base_numbers=self._weapon_base_numbers, candidates_of=self._weapon_base_candidates,
        )

    def improve(self, build: WorkingBuild, result: BuildResult, plan: LoopPlan) -> LoopOutcome:
        """Run the improvement loop on `build` under `plan`, log its note and return its outcome (#51 unit 7)."""

        outcome = self._run_loop(build, result, plan, None)
        self.log(outcome.note)
        return outcome

    def repair(self, build: WorkingBuild, result: BuildResult, choice: RepairChoice, *, seed: int = 1) -> RepairOutcome:
        """#1064: the short repair of a keystone choice on a finished build. The keystone is held (`force`: allocated with its
        path, pinned, the points paid by the tree's own weakest-leaf removal; `forbid`: removed, held out of the tree, the
        freed points spent by the pipeline's spare-point step), then at most `REPAIR_MAX_PASSES` loop passes run one at a time
        ("repair pass N", no kicks) and `repair.should_continue` ends them. The verdict is by the objective value only."""

        t_all = time.perf_counter()
        skeleton, tree = build.skeleton, build.tree
        parts = split_bundle(choice, tree.graph, skeleton) if choice.bundle else None  # #1147: a bundle splits before any PoB call
        if parts is None:
            node_id = resolve_keystone_id(tree.graph, choice.keystone)
            label = tree.graph.nodes[node_id].name
        else:
            label = parts.label
        self.judging.refresh_castability()
        start = self.objective.score(self.pob.stats(self.objective.stat_keys)).value  # the finished build, before the choice
        if parts is not None:
            note = self._repair_force_bundle(build, parts)
        elif choice.direction == "force":
            note = self._repair_force(build, node_id)
        else:
            note = self._repair_forbid(build, node_id)
        self._commit_stage(result, self._stage_record(result, "repair pass 0", t_all, f"{choice.direction} {label}: {note}"))
        plan = LoopPlan.repair(seed=seed)
        values: list[float] = []
        gains: list[float] = []
        cleared: list[bool] = []  # a pass that started infeasible and ended feasible is not "under the floor" (#1064)
        for number in range(1, REPAIR_MAX_PASSES + 1):
            violation_before = result.stages[-1].violation
            self.improve(build, result, replace(plan, max_passes=1, first_pass=number))
            values.append(result.stages[-1].score_value)
            cleared.append(violation_before > FEASIBILITY_TOLERANCE and result.stages[-1].violation <= FEASIBILITY_TOLERANCE)
            gains = repair_gains(start, values)
            if not should_continue(gains, cleared):
                break
        return RepairOutcome(start=start, values=values, gains=gains, verdict=repair_verdict(start, values), seconds=time.perf_counter() - t_all)

    def _repair_trees(self, build: WorkingBuild) -> list[TreeOptimizer]:
        return list({id(t): t for t in (build.tree, *self.judging.trees())}.values())

    def _rejudge_recut(self, skeleton: Skeleton) -> None:
        self.judging.rejudge(skeleton)
        self.judging.recut()  # the views re-cut from the full objective after the last re-judge, as the replay bench does

    def _repair_force(self, build: WorkingBuild, node_id: int) -> str:
        """The keystone allocated with its path and pinned; the points over the budget leave through the tree's weakest leaves."""

        name = build.tree.graph.nodes[node_id].name
        self._refuse_forbidden_keystones(build.skeleton, (name,))
        return self._hold_forced(build, (node_id,))

    def _repair_force_bundle(self, build: WorkingBuild, parts: BundleParts) -> str:
        """#1147: every part of a bundle held the way `_repair_force` holds a keystone: appended to `forced_nodes`,
        allocated with its path, pinned, the points over the budget paid by the weakest leaves."""

        self._refuse_forbidden_keystones(build.skeleton, parts.keystone_names)
        notes: list[str] = []
        if parts.uniques:  # the gear first: the weakest-leaf removals of the tree hold are then judged with the unique worn
            notes.append(self._hold_uniques(build, parts.uniques))
        if parts.forced_ids:
            notes.append(self._hold_forced(build, parts.forced_ids, ascendancy_ids=parts.ascendancy_ids))
        else:
            self._rejudge_recut(build.skeleton)  # the lanes and views read the gear that now carries the unique
        return "; ".join(notes)

    def _hold_uniques(self, build: WorkingBuild, uniques: Sequence[tuple[str, str]]) -> str:
        """#1147 unit 4: every unique of a bundle put on the finished build the way a requested unique is held: in the
        skeleton's `uniques` and `forced_uniques` (so no gear or weapon move replaces it), its slot off the rare bases
        (the loop's gear move refills rare slots only), the filler's own item of the slot forgotten and the unique's raw
        kept for the weapon-partner restore, then equipped."""

        from junkroan.search.runner import _is_two_hander, apply_unique_picks

        skeleton, gear = build.skeleton, build.gear
        for slot, name in uniques:
            raw = self.pob.unique_item(name)["raw"]
            off_hand_dropped = slot == "Weapon 1" and "Weapon 2" in skeleton.rare_bases and _is_two_hander(name) and "Weapon 2" not in skeleton.forced_bases
            apply_unique_picks(skeleton, {slot: name})  # before the slot is forced: a forced slot keeps its rare base
            skeleton.forced_uniques[slot] = name
            gear.uniques[slot] = raw
            gear.current_raw.pop(slot, None)
            self.pob.equip({slot: raw})
            if off_hand_dropped:  # a two-hander leaves no shield (the skeleton's own rule); PoB would only drop it silently
                gear.current_raw.pop("Weapon 2", None)
                self.pob.equip({"Weapon 2": None})
        return f"{', '.join(f'{name} in {slot}' for slot, name in uniques)}"

    @staticmethod
    def _refuse_forbidden_keystones(skeleton: Skeleton, names: Sequence[str]) -> None:
        for name in names:
            if name.lower() in {k.lower() for k in skeleton.forbid_keystones}:
                raise ValueError(f"cannot force {name}: the skeleton forbids it")

    def _hold_forced(self, build: WorkingBuild, node_ids: Sequence[int], *, ascendancy_ids: frozenset[int] = frozenset()) -> str:
        skeleton, tree = build.skeleton, build.tree
        extra = int(self.pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)
        before = self._points_used()
        budget = max(max_passive_points(skeleton.level, extra), before)  # a build already over the rule keeps its own total
        for node_id in node_ids:
            if node_id not in skeleton.forced_nodes:
                skeleton.forced_nodes.append(node_id)
        skeleton.apply_forced_nodes(self.pob)
        if ascendancy_ids:  # ascendancy points are apart from the passive budget; PoB does not cap them itself
            used = int(self.pob.mutate_nodes().get("ascendancy_points_used") or 0)
            allowed = int(getattr(getattr(self, "rails", None), "ascendancy_points", 8))
            if used > allowed:
                raise ValueError(f"the bundle's ascendancy nodes need {used} ascendancy points, the rails allow {allowed}")
        protected = self._protected_nodes(skeleton)
        for opt in self._repair_trees(build):
            opt.protected = protected
        self._rejudge_recut(skeleton)
        dropped = 0
        refused: list[int] = []  # #1164: leaves whose real removal took more than the leaf itself, out of this trim for good
        while self._points_used() > budget:
            stats = self.pob.stats(tree.objective.stat_keys)
            allocated = tree.current_allocated()
            leaves = [leaf for leaf in tree._weakest_leaves(allocated, stats) if leaf not in refused]
            if not leaves:
                raise RuntimeError(
                    f"repair: {self._points_used()} points against the budget {budget} and no leaf to remove"
                    + (f" (refused, their removal cascaded: {refused})" if refused else "")
                )
            removed = self.pob.remove_nodes([leaves[0]])
            taken = [int(n) for n in removed.get("removed_node_ids") or ()]
            if len(taken) > 1:  # #1164 rule 1: the graph's leaf is not PoB's, a cut takes exactly one node; put it back whole, next leaf
                self._restore_cut(tree, removed, taken, allocated)
                refused.append(leaves[0])
                continue
            lost = sorted(n for n in taken if n in protected)
            if lost:  # #1147: the second net, a single removed node that is itself forced; the repair would measure a build without the choice
                raise RuntimeError(f"repair: removing leaf {leaves[0]} took the forced nodes {lost}")
            tree.after_real_removal(removed)
            dropped += 1
        self._rejudge_recut(skeleton)
        return f"{self._points_used() - before:+d} points over the finished build after {dropped} leaf removals (budget {budget})"

    def _restore_cut(self, tree: TreeOptimizer, removed: Mapping[str, object], taken: Sequence[int], before: set[int]) -> None:
        """#1164: the tree as it stood before a real removal, put back from the removal's own answer. PoB allocates the added
        nodes in list order, each by its own shortest path from what is allocated at that moment, so the taken nodes go back
        nearest-first from the surviving tree (BFS over the graph), each adjacent to what is already allocated, and a mastery
        node with the effect it held. The allocation is read back and compared with `before`."""

        pending = set(taken)
        frontier = deque(sorted(before - pending))
        order: list[int] = []
        while frontier:
            for neighbour in sorted(tree.graph.neighbours(frontier.popleft())):
                if neighbour in pending:
                    pending.discard(neighbour)
                    order.append(neighbour)
                    frontier.append(neighbour)
        order.extend(sorted(pending))  # a link the graph does not hold (a cluster subgraph): PoB's own path finds it
        effects: dict[int, int] = {}
        for raw in removed.get("removed_mastery_effects") or ():
            node, _, effect = str(raw).partition(":")  # no shared parser: every reader of "node:effect" splits it inline
            if node.isdigit() and effect.isdigit():
                effects[int(node)] = int(effect)
        self.pob.add_nodes(order, mastery_effects=effects or None)
        if tree.current_allocated() != before:
            raise RuntimeError("repair: a refused leaf removal could not be put back; the tree is not the one before the cut")

    def _repair_forbid(self, build: WorkingBuild, node_id: int) -> str:
        """The keystone out of the tree and held out of every tree; the freed points are spent once at once (the passes
        only trade equal counts, a tree move that adds nodes is a kick or a gear victim's)."""

        skeleton = build.skeleton
        name = build.tree.graph.nodes[node_id].name
        if node_id in {int(n) for n in skeleton.forced_nodes}:
            raise ValueError(f"cannot forbid {name}: the skeleton forces it")
        skeleton.keystones = [k for k in skeleton.keystones if int(k) != node_id]
        if name.lower() not in {k.lower() for k in skeleton.forbid_keystones}:
            skeleton.forbid_keystones.append(name)
        for opt in self._repair_trees(build):
            opt.forbid([name])
        before = self._points_used()
        if node_id in {int(n) for n in self.pob.tree_light().get("user_allocated_node_ids") or ()}:
            removed = self.pob.remove_nodes([node_id])
            build.tree.after_real_removal(removed)
        freed = before - self._points_used()
        self._rejudge_recut(skeleton)
        self._last_spend_names = []
        spent = self._spend_extra_points(skeleton)
        names = ", ".join(self._last_spend_names)
        self._rejudge_recut(skeleton)
        return f"{freed} points freed, {spent} spent" + (f" on {names}" if names else "")

    def _run_loop(self, build: WorkingBuild, result: BuildResult, plan: LoopPlan, flags: LoopFlags | None) -> LoopOutcome:
        # every pipeline method the loop calls is looked up at call time, so an instance-attribute fake still takes effect
        loop = ImprovementLoop(
            build, result,
            tune_lanes=lambda *args, **kwargs: self._tune_lanes(*args, **kwargs),
            picker=lambda: self._generator(),
            log=lambda message: self.log(message),
            record=lambda *args, **kwargs: self._record(*args, **kwargs),
            take_picks=lambda *args, **kwargs: self._take_picks(*args, **kwargs),
            aura_levels=lambda sk, order="priced": self._tune_flat_reservation_aura_levels(sk, order=order),  # the loop's move: D116 / #553; the extra pass hands "floors"
            joint_round=lambda *args, **kwargs: self._joint_round(*args, **kwargs),
            weapon_raw_base=lambda raw: self._weapon_raw_base(raw),
            weapon_base_fingerprint=lambda *args, **kwargs: self._weapon_base_fingerprint(*args, **kwargs),
            weapon_base_move=lambda *args, **kwargs: self._weapon_base_move(*args, **kwargs),
            ascendancy_points=self.rails.ascendancy_points,  # #1157: the ascendancy-swap move runs only when the rails give points
            sockets_stale=lambda: self._sockets_stale(),
            ensure_sockets=lambda gear: self._ensure_sockets(gear),
            socket_memory_get=lambda: getattr(self, "_socket_lines", None),
            socket_memory_set=lambda value: setattr(self, "_socket_lines", value),
        )
        return loop.run(plan, flags=flags)

    def _guarded_step(self, skeleton: Skeleton, label: str, run: Callable[[], Any], *, restore: Callable[[], None] | None = None) -> tuple[Any, bool]:
        """One step of `_finish`, kept only when it did not lower feasibility (D66, `keep_if_feasible`).

        The snapshot is exported while the applied config is this build's own lane derivation, so the
        `load_xml` that reverts puts the lanes back with it -- the rule the improvement loop's `revert()`
        follows for a fresh snapshot. `restore` puts back whatever the step mutated outside PoB and the
        skeleton (the derived lanes it wrote its chosen values into)."""

        pob = self.pob
        stats = pob.stats(self.objective.stat_keys)
        before, before_violations = self.objective.score(stats), self.objective.violations(stats)
        shots = _snapshotter(self, skeleton)
        # XML + the identity written on the skeleton; a re-judge inside the step moves the contexts, the revert puts them back (#34);
        # steps a reverted step allocated are not in the explanation (as `_rebuild_tree`)
        snapshot = shots.take(xml=True, skeleton=SKELETON_IDENTITY, history=True, judging=MOVE)
        out = run()
        stats = pob.stats(self.objective.stat_keys)
        after = self.objective.score(stats)
        if keep_if_feasible(before, after):
            return out, True
        note = broken_floors(self.objective, before_violations, stats)
        shots.restore(snapshot)
        if restore is not None:
            restore()
        self.log(f"reverted: {label} broke {note} ({before.value:,.0f} viol {before.violation:.3f} -> {after.value:,.0f} viol {after.violation:.3f})")
        return None, False

    def _fixed_point_check(self, result: BuildResult, skeleton: Skeleton, loot: LootGear | WishlistGear, tree: TreeOptimizer, *,
                           loot_n: int | None, seed: int, min_gain: float, max_seconds: float | None, enabled: bool = True,
                           loop_outcome: LoopOutcome | None = None) -> list[Finding]:
        """ROADMAP 7.3: the loop ends at a pass that keeps nothing, and `_finish` then tunes the list
        choices and the identity -- which moves the landscape the loop stopped on, so the build it
        reports is not known to be at a fixed point any more. One more pass of the loop's local moves
        (refine, path swaps, the per-slot gear re-rolls, the picks; no kicks, no lane tuning) is run
        here on the same code path and the same acceptance rule, with gear rolls seeded away from
        every pass the loop ran. Whatever it gains the build keeps; how much it gained is the measure
        of how far from a fixed point the finished build was, and above 1% that is an audit error, so
        a non-optimal build cannot pass as done. A loop that stopped on its time budget or on its pass
        limit is already known not to be at a fixed point: that is recorded and no pass is run."""

        if not enabled:
            return []
        stopped = loop_outcome.stopped if loop_outcome is not None else ""
        if stopped:  # the loop stops on one of two things: its time budget and its pass limit
            note = "stopped on the time budget" if stopped == "time budget" else "stopped on the pass limit"
            result.fixed_point_gain, result.fixed_point_note = 0.0, note
            return [Finding("warning", "fixed point", f"{note}: not at a fixed point")]
        main_plan = LoopPlan(seed=seed, max_passes=1, max_seconds=max_seconds, min_gain=min_gain, loot_n=loot_n, kind="loop")
        build = WorkingBuild(pob=self.pob, judging=self.judging, skeleton=skeleton, gear=loot, tree=tree)
        t_check = time.perf_counter()
        gain, kept, passes, limit = 0.0, [], 0, ""
        result.fixed_point_moved, result.fixed_point_passes = False, 0
        while True:
            remaining = None if max_seconds is None else max_seconds - (time.perf_counter() - t_check)
            if passes and remaining is not None and remaining <= 0:
                limit = f"the time budget ended the repeats after {passes} extra pass{'es' if passes != 1 else ''}"
                break
            before = self.objective.score(self.pob.stats(self.objective.stat_keys)).value
            # the first pass has the whole budget (as before #800); a repeat has what is left of it, the loop's clock being its own
            extra = self.improve(build, result, main_plan.extra_pass(passes, max_seconds=remaining if passes else None))
            passes += 1
            kept = list(extra.kept)
            result.fixed_point_passes = passes
            if extra.stopped and not kept:
                # the extra pass itself ran out of time before it had judged every move: "kept nothing" would
                # report a fixed point the build was never measured against
                result.fixed_point_gain, result.fixed_point_note = 0.0, "the extra pass stopped on the time budget"
                return [Finding("warning", "fixed point", "the extra pass stopped on the time budget: not at a fixed point")]
            gain = (result.stages[-1].score_value / before - 1.0) if (kept and before > 0) else 0.0
            if not kept:
                break  # a pass that kept nothing: the delivered build is a fixed point of the extra pass
            result.fixed_point_moved = True  # what the last pass kept stays in the build: `_finish` re-derives the lanes for it
            if extra.stopped:
                limit = f"the extra pass stopped on the time budget after {passes} extra pass{'es' if passes != 1 else ''}"
                break
            if passes >= FIXED_POINT_MAX_EXTRA_PASSES:
                limit = f"the limit of {FIXED_POINT_MAX_EXTRA_PASSES} extra passes ended the repeats"
                break
            self.log(f"fixed point check: extra pass {passes} kept {gain:+.1%} ({'; '.join(kept)}): another pass")
        # the gain and the note are the LAST pass's: what the delivered build still found (a build whose repeat kept nothing reads "kept nothing")
        result.fixed_point_gain, result.fixed_point_note = gain, "; ".join(kept) or "kept nothing"
        if gain > 0:
            return [Finding("error" if gain > 0.01 else "warning", "fixed point",
                            f"the loop was not at a fixed point: one more pass gained {gain:+.1%} ({result.fixed_point_note}); {limit}")]
        if passes > 1:
            self.log(f"fixed point check: reached after {passes} extra passes")
        return []

    def _final_floor_repair(self, result: BuildResult, skeleton: Skeleton) -> str:
        """#553 rule 3 (D116): the delivered build must meet every floor, and the loop's moves are judged by a priced score
        that lets an intermediate state stay infeasible. The existing floor move alone (the tree's repair-only refine, the
        one the loop's gear roll and `_finish` use), judged by `better_score` (violation first), is repeated until the
        violation is 0, a round keeps nothing, or `FINAL_FLOOR_REPAIR_ROUNDS` rounds ran. A round that keeps nothing goes
        back to its snapshot. Returns the note for the stage ("" when no round kept anything)."""

        pob, tree = self.pob, self.judging.view("tree")
        kept_rounds = 0
        first = self._delivered_score()
        for k in range(1, FINAL_FLOOR_REPAIR_ROUNDS + 1):
            before = self._delivered_score()
            if before.feasible:
                break
            t0 = time.perf_counter()
            shots = _snapshotter(self, skeleton)
            snapshot = shots.take(xml=True, skeleton=SKELETON_WHOLE, history=True, judging=MOVE)  # #854: the round's rejudge writes the Skeleton counts, and the restore does not rejudge
            tree.refine(max_rounds=0, repair_rounds=60)  # repair only: the cheapest DPS per violation removed
            self.judging.rejudge(skeleton)
            after = self._delivered_score()
            kept = better_score(after, before)
            if not kept:
                shots.restore(snapshot)
            self.log(f"final floor repair round {k}: violation {before.violation:.3f} -> {after.violation:.3f} ({'kept' if kept else 'nothing kept'})")
            result.moves.append({
                "pass": max((int(m.get("pass") or 0) for m in result.moves), default=0), "where": "final floor repair", "move": "final floor repair",
                "seconds": time.perf_counter() - t0, "before": before.value, "after": after.value if kept else before.value, "kept": kept,
                "reverted_by_judge": not kept, "violation_before": before.violation, "violation_after": after.violation if kept else before.violation,
            })
            if not kept:
                break
            kept_rounds += 1
        if not kept_rounds:
            return ""
        last = self._delivered_score()
        return f"final floor repair: {kept_rounds} round(s) kept, viol {first.violation:.3f} -> {last.violation:.3f}"

    def _finish(self, result: BuildResult, skeleton: Skeleton, t_all: float, *, fixed_point: dict | None = None) -> BuildResult:
        """The delivery of the build, one named step per block, in this order (#814); a step takes what it reads
        and returns what it changes."""

        pob = self.pob
        entry = self._finish_entry(result, skeleton)
        derived = entry.derived
        choices = self._tune_final_lanes(skeleton, derived, entry.lanes)
        repaired = self._repair_after_final_lanes(skeleton)
        self._record_final_lanes(result, entry, derived, choices, repaired)
        extra_audit, derived = self._fixed_point_step(result, skeleton, fixed_point, entry.gear, derived)

        if self.judging.castability_context is not None:  # #941: the final lanes and the fixed-point pass moved the build; the floor repair below judges the costs it has now
            self.judging.refresh_castability()
        # `entry` is measured under the objective as `_finish` was handed it; only the repair path's
        # `judging.rejudge` can change that objective (a ramp context the final lanes moved), and it runs
        # only on a build that is already infeasible, so the comparison is between like and like
        score = self.objective.score(pob.stats(self.objective.stat_keys))
        reverted = score.violation > entry.score.violation + FEASIBILITY_TOLERANCE
        verdict = ""
        if reverted:
            verdict, extra_audit, score = self._fall_back_to_entry(result, entry, derived, extra_audit)
        derived = self._floor_repair_and_verdict(result, skeleton, entry, derived, score, verdict)

        # the optimistic lane only: dropping a toggle from it cannot move the conservative numbers the
        # feasibility above is measured on. After a fallback nothing runs on the build at all -- what is
        # delivered is the loop's fixed point as it stood
        self._prune_and_deliver(skeleton, derived, reverted)
        self._enforce_charge_proof()  # #908: the gems are final; the Baseline carries no charge toggle the audit's proof refuses
        self._read_delivered_numbers(result, skeleton)
        self._export_and_audit(result, skeleton, extra_audit, entry.moves_before_final_lanes)
        return self._explain_and_map(result, skeleton, entry.gear, t_all)

    def _finish_entry(self, result: BuildResult, skeleton: Skeleton) -> _FinishEntry:
        """The build the loop handed over, measured and snapshotted before the final lanes touch it (D66); the lanes
        are derived once more on it."""

        pob = self.pob
        self._step_start("config (final lanes)")
        t0 = time.perf_counter()
        self._drop_stray_jewels()  # #434: a socket a later step freed holds no jewel in the export
        # the fixed point the loop reached is the floor the delivered build may not fall below (D66):
        # on the rules-smoke run two builds were reported infeasible (stormbrand s3 MoMUnreservedShare
        # 0.324 < 0.4, cold_dot s2 EffectiveMovementSpeedMod 1.140 < 1.164) and nothing between the
        # loop and the export was ever asked whether it had made that worse
        entry_stats = pob.stats(self.objective.stat_keys)
        entry = self.objective.score(entry_stats)
        result.ledger_value_before_final_lanes = entry.value
        self.log(f"final entry: {entry.value:,.0f} (viol {entry.violation:.3f}), sockets {socket_lines(pob) if hasattr(pob, 'equipped_item_raws') else 'n/a'}")
        moves_before_final_lanes = len(result.moves)
        gear = self.judging.view("gear")
        entry_shots = _snapshotter(self, skeleton, filler=gear)
        entry_snapshot = entry_shots.take(xml=True, skeleton=SKELETON_WHOLE, filler=FILLER_RAW, history=True, judging=MOVE)  # #854: the fixed-point pass writes main_link, extra_groups, aura_levels, the counts and the tree steps
        entry_sockets = getattr(self, "_socket_lines", None)  # the colour step's memory that goes with the entry snapshot
        derived = self.judging.relane(skeleton)
        return _FinishEntry(t0=t0, stats=entry_stats, score=entry, moves_before_final_lanes=moves_before_final_lanes, gear=gear,
                            shots=entry_shots, snapshot=entry_snapshot, sockets=entry_sockets, derived=derived, lanes=lane_memo(derived))

    def _tune_final_lanes(self, skeleton: Skeleton, derived, before_choices) -> dict[str, str]:
        """The two guarded tuning steps over the final lanes (choice inputs, identity); the choices they made."""

        pob = self.pob
        # the lane derivation itself is not revertible by a guard -- it is what the build honestly is --
        # so it is answered by the final check below; the tuning steps are guarded one by one
        chosen, _kept = self._guarded_step(skeleton, "choice inputs",
                                           lambda: tune_choices(pob, skeleton, derived, objective=self.judging.objective,
                                                                write=self.judging.lanes.write, log=lambda message: self.log(message), guard=True),
                                           restore=lambda: restore_lanes(derived, before_choices))
        choices: dict[str, str] = dict(chosen or {})
        before_identity = lane_memo(derived)
        identity, _kept = self._guarded_step(skeleton, "identity", lambda: self._tune_identity(skeleton, derived),
                                             restore=lambda: restore_lanes(derived, before_identity))
        choices.update(identity or {})
        return choices

    def _repair_after_final_lanes(self, skeleton: Skeleton) -> str:
        """An infeasible build after the final lanes is repaired under the FULL objective, and the repair is reverted
        when it bought nothing; the note for the stage record ("" when nothing was repaired)."""

        pob = self.pob
        repaired = ""
        score = self.objective.score(pob.stats(self.objective.stat_keys))
        self.log(f"final lanes tuned (choices, identity): {score.value:,.0f} (viol {score.violation:.3f})")
        if not score.feasible and self.judging.trees():
            # the final lanes moved a number a stage had judged under older lanes: repair under the FULL
            # objective (the refine's cheapest-DPS repair), then derive the lanes once more. Judged on
            # `self.objective` and not on the loop tree's `current_score()`, whose objective is the full one
            # `without("EffectiveMovementSpeedMod")`: cold_dot s2 ended 1.140 < 1.164 and the repair path
            # never ran, because the tree's own objective does not carry that floor
            before = score
            shots = _snapshotter(self, skeleton)
            snapshot = shots.take(xml=True, skeleton=SKELETON_WHOLE, history=True, judging=MOVE)  # #854: the repair's rejudge writes the Skeleton counts, and the restore does not rejudge
            self.judging.view("tree").refine(max_rounds=12)
            self.judging.relane(skeleton)
            score = self.objective.score(pob.stats(self.objective.stat_keys))
            if not score.feasible:
                self.judging.view("tree").refine(max_rounds=0, repair_rounds=60)  # repair only, as the loop's gear move
                self.judging.rejudge(skeleton)
                score = self.objective.score(pob.stats(self.objective.stat_keys))
            if score > before:
                repaired = f"; repaired after the final lanes: viol {before.violation:.3f} -> {score.violation:.3f}, {before.value:,.0f} -> {score.value:,.0f}"
            else:
                # the repair is judged by the same rule as everything else here: the tree refines under its
                # own objective (the full one without the movement floor, D28), so a round that paid there
                # can be flat or worse under the objective the build is delivered on -- and a repair that
                # buys no feasibility is only a DPS bill
                would_be = score
                shots.restore(snapshot)
                score = self.objective.score(pob.stats(self.objective.stat_keys))
                self.log(f"reverted: repair after the final lanes bought nothing "
                         f"(viol {before.violation:.3f} -> {would_be.violation:.3f}, {before.value:,.0f} -> {would_be.value:,.0f} if kept)")
        return repaired

    def _record_final_lanes(self, result: BuildResult, entry: _FinishEntry, derived, choices: dict[str, str], repaired: str) -> None:
        """The stage record of the final lanes."""

        # #435: gems are final here. Every socket goes white (since 3.29 a white socket takes any gem), then the
        # colour step gives at most `coloured_max("day1")` sockets a colour where PoB's +10 % quality pays.
        # #547: the loop already ran it (D60), and this call is idle while the sockets and gems are what that step
        # left: the colouring delivered is the one the loop last judged, never a fresh pick over it
        self._ensure_sockets(entry.gear)

        result.config_reasons = dict(derived.conservative.reasons)
        self._record(result, "config (final lanes)", entry.t0, f"{len(derived.conservative.inputs)} conservative / {len(derived.optimistic.inputs)} optimistic" + (f"; choices {choices}" if choices else "") + repaired)

    def _fixed_point_step(self, result: BuildResult, skeleton: Skeleton, fixed_point: dict | None, gear, derived) -> tuple[list, Any]:
        """The one more pass of local moves; the audit findings it leaves and the lanes derived for the build it left."""

        # the tuning above moved the landscape the loop stopped on: one more pass of local moves says
        # whether the build is still at a fixed point, and the build keeps whatever that pass gained (7.3).
        # It runs inside the feasibility guard, not after it: its own acceptance rule (`better`) is
        # feasibility-first, so it cannot lower feasibility, but the check below is what makes that a
        # guarantee of the delivered build rather than of one step of it (D66)
        extra_audit = self._fixed_point_check(result, skeleton, **fixed_point) if fixed_point else []
        if result.fixed_point_moved:
            # an extra pass kept a move: the optimistic lane is pruned, and the reasons reported, on
            # the derivation for the build it left behind, not for the one the stage above measured
            derived = self.judging.relane(skeleton)
            result.config_reasons = dict(derived.conservative.reasons)
        self._ensure_sockets(gear)  # a fixed-point re-roll can bring an item with rails sockets
        return extra_audit, derived

    def _fall_back_to_entry(self, result: BuildResult, entry: _FinishEntry, derived, extra_audit: list) -> tuple[str, list, Score]:
        """D66: nothing after the loop bought value with a floor, so the build goes back to the one the loop handed
        over; the verdict text, the audit findings that remain and the score of the build now loaded."""

        pob = self.pob
        # nothing after the loop bought value with a floor: back to the build the loop handed over,
        # byte for byte. The snapshot was exported under the loop's own lanes and carries them in its
        # <Config>, so it is loaded and nothing is applied over it -- the fixed-point pass's own gains
        # go back with it, so its finding and its gain go too
        note = broken_floors(self.objective, self.objective.violations(entry.stats), pob.stats(self.objective.stat_keys))
        entry.shots.restore(entry.snapshot)
        self._socket_lines = entry.sockets  # the entry XML holds the colouring that memory describes (#547)
        restore_lanes(derived, entry.lanes)  # the derivation `_finish` opened with: this same build's own
        result.config_reasons = dict(derived.conservative.reasons)
        extra_audit = [f for f in extra_audit if "was not at a fixed point" not in f.detail]
        result.fixed_point_gain, result.fixed_point_note = 0.0, "reverted with the final tuning"
        result.fixed_point_moved, result.fixed_point_passes = False, 0
        self._ensure_sockets(entry.gear)  # the entry build was loaded back with its own, unwhitened sockets
        score = self.objective.score(pob.stats(self.objective.stat_keys))
        verdict = (f"final tuning reverted: {note} (viol {entry.score.violation:.3f} -> {score.violation:.3f}, "
                   f"value {entry.score.value:,.0f} -> {score.value:,.0f}); the stages above it describe a build that was not delivered")
        self.log(verdict)
        return verdict + "; ", extra_audit, score

    def _floor_repair_and_verdict(self, result: BuildResult, skeleton: Skeleton, entry: _FinishEntry, derived, score: Score, verdict: str):
        """The last repair of a broken floor and the feasibility verdict on the last stage; the lanes derived for the
        build the repair left behind."""

        pob = self.pob
        # #553 rule 3 (D116): the last point where the build can still change before the verdict below; a floor still
        # broken here is bought back by the floor move alone, and a build that stays infeasible fails the audit as before
        if not score.feasible and self.judging.view("tree") is not None:
            repair_note = self._final_floor_repair(result, skeleton)
            if repair_note:
                derived = self.judging.relane(skeleton)  # the derivation for the build the repair left behind
                result.config_reasons = dict(derived.conservative.reasons)
                verdict += f"{repair_note}; "
            score = self.objective.score(pob.stats(self.objective.stat_keys))
        feasibility = "final feasibility: ok" if score.feasible else (
            f"final feasibility: {broken_floors(self.objective, {}, pob.stats(self.objective.stat_keys))}"
            f" (viol {score.violation:.3f}; the loop handed `_finish` a build at {entry.score.violation:.3f})")
        self.log(feasibility)
        result.stages[-1].notes += f"; {verdict}{feasibility}"  # the verdict on the delivered build, on the last stage the log prints
        return derived

    def _prune_and_deliver(self, skeleton: Skeleton, derived, reverted: bool) -> None:
        """The optimistic lane's prune (skipped after a fallback), then the gems and flasks the delivered build wears."""

        pruned = [] if reverted else self._prune_optimistic(skeleton, derived)
        if pruned:
            self.log(f"optimistic lane: dropped {pruned} (each lowered the objective; an interaction, not an assumption)")
        self._deliver_vaal_twins()  # #802: gems are final; the delivered numbers below are those of the Vaal form
        self._restore_flasks()  # #436: the delivered build wears the flasks the step placed, active

    def _enforce_charge_proof(self) -> list[str]:
        """#908: the last word on the conservative lane's charge toggles is the audit's own proof, asked on the delivered
        build. The lane was derived before the steps above changed the gems (the Vaal delivery moved Frenzy's own `Speed`
        from 0.72 to 0.00 on impale_ballista s4), and nothing re-derived it after them. Returns the toggles switched off."""

        if not all(callable(getattr(self.pob, name, None)) for name in ("export_xml", "load_xml", "stats")):
            return []  # a PoB without the surface (a fake in a test) has no Baseline to read
        off = switch_off_unproven_charges(self.pob)
        if off:
            self.log(f"charge proof: {', '.join(off)} switched off in Baseline (the audit's proof refuses it on the delivered build)")
        return off

    def _read_delivered_numbers(self, result: BuildResult, skeleton: Skeleton) -> None:
        """The delivered build's numbers: the two calc lanes, the report stats, the floors it misses, the ramp DPS."""

        pob = self.pob
        result.conservative_stats = pob.calc("baseline")
        result.optimistic_stats = pob.calc("conditional")
        if hasattr(pob, "read_state"):  # #542, #1143 (D62): a mortar spectre under Volley overlaps on one target, on every lane the fact acts on
            overlap = spectre_overlap_stats(pob, result.conservative_stats)
            if overlap is not None:
                result.optimistic_stats = overlap.optimistic
                if overlap.conservative is not None:  # approved: the delivered conservative number carries the overlap
                    result.conservative_stats = overlap.conservative
                    result.config_reasons[spectre_overlap.FACT_ID] = overlap.note
                else:
                    result.pending_facts.append(overlap.note)
                self.log(f"overlap fact: {overlap.note}")
        result.final_stats = pob.stats(REPORT_KEYS)
        objective_stats = pob.stats(self.objective.stat_keys)
        result.final_stats.update(self.objective.derived_values(objective_stats))
        result.final_stats.setdefault(self.objective.maximize, objective_stats.get(self.objective.maximize))  # #1057: the maximised output under its own name
        result.floors_missed = missed_constraints(objective_stats, self.objective)  # #704: the delivered build's own objective evaluation
        pinnacle_seconds = float(getattr(self.rails, "assumptions", {}).get("pinnacle_ramp_seconds", 10.0))
        ctx = ramp_context(self.objective)
        if ctx is not None:
            result.pinnacle_ramp_seconds = pinnacle_seconds
            # The delivered conservative lane intentionally caps ailments at
            # 2.5 s. The second, report-only number asks the same time model
            # at 10 s, so it temporarily restores only those stack surfaces.
            shots = _snapshotter(self, skeleton)
            snapshot = shots.take(xml=True)
            uncapped = uncapped_ailment_stack_xml(snapshot.xml)
            if uncapped != snapshot.xml:
                pob.load_xml(uncapped)  # the report-only change itself, not a restore
                pinnacle_stats = pob.stats(self.objective.stat_keys)
                shots.restore(snapshot)
                result.pinnacle_ramp_dps = ramp_dps(pinnacle_stats, self.objective.maximize, pinnacle_seconds, replace(ctx, ailment_stacks={}))
            else:
                result.pinnacle_ramp_dps = ramp_dps(objective_stats, self.objective.maximize, pinnacle_seconds, ctx)

    def _export_and_audit(self, result: BuildResult, skeleton: Skeleton, extra_audit: list, moves_before_final_lanes: int) -> None:
        """The export (XML, import code), the tree leaves and the audit of the delivered build, the ledger identity."""

        pob = self.pob
        self._drop_stray_jewels()  # the lanes' repair may have freed a socket too
        result.xml = pob.export_xml()
        result.import_code = encode_import_code(result.xml)
        from junkroan.optimizer.tree_hygiene import analyze_tree_leaves

        result.tree_leaves = analyze_tree_leaves(pob, objective=self.objective, mastery_context=True, links=self._cluster_links())
        result.audit = audit_build(pob, rails=self.rails, objective=self.objective, tree_leaves=result.tree_leaves,
                                   castability_metrics=self.castability_metrics, skeleton=skeleton) + extra_audit
        if result.ledger_construction_value is not None and result.ledger_value_before_final_lanes is not None:
            kept_gain = sum(float(move["after"]) - float(move["before"]) for move in result.moves[:moves_before_final_lanes] if move.get("kept"))
            result.ledger_identity_error = (result.ledger_construction_value + kept_gain - result.ledger_value_before_final_lanes)
        result.castability_calls = self.castability_metrics.calls
        result.castability_seconds = self.castability_metrics.seconds
        if result.dropped_moves:
            result.audit.append(Finding("warning", "dropped moves", f"{len(result.dropped_moves)} improvement-loop move(s) dropped after PoB contract failures"))

    def _explain_and_map(self, result: BuildResult, skeleton: Skeleton, gear, t_all: float) -> BuildResult:
        """The reading of the delivered build into the result: keystones, pending facts, mapping, shopping, tree steps,
        the explanation, the lanes check, the PoB call count, the tree churn and the total time."""

        pob = self.pob
        result.keystones = self._keystones()
        self.log(f"keystones: {', '.join(result.keystones) or 'none'}" + (f" (forbidden: {', '.join(skeleton.forbid_keystones)})" if skeleton.forbid_keystones else ""))
        # what an unapproved research fact would do to the number we deliver (D62): computed once on
        # the finished build, never charged to it. A session that cannot be read back (the unit
        # harnesses' stand-ins) reports nothing; there is no number to report from.
        if hasattr(pob, "read_state"):
            _gems, _triggered, levels = self.judging.refresh_main_group()  # the gem levels of the link as it is delivered
            note = trauma_lane_note(pob.stats(("HitSpeed", "Speed", "NetLifeRegen", "NetEnergyShieldRegen", "Life")),
                                    levels, trauma_stacks(pob))
            if note:
                result.pending_facts.append(note)
                self.log(f"pending fact: {note}")
        from junkroan.optimizer.config_rules import build_text
        from junkroan.optimizer.mapping import KEYS as MAPPING_KEYS, mapping_lines
        from junkroan.search.hypothesis import active_gems

        gem_names = [*skeleton.main_link, *(g for grp in skeleton.extra_groups for g in grp.gems)]
        result.mapping = mapping_lines(pob.stats(MAPPING_KEYS), build_text(pob), gem_names, {n: r.get("tag_keys") or () for n, r in active_gems().items()})
        shopping = gear.shopping_results() if gear is not None else []
        if shopping:
            result.gear_shopping = [
                {"slot": item.slot, "base": item.base, "implicit": item.implicit, "lines": list(item.shopping)}
                for item in shopping
            ]
        for opt in self.judging.trees():
            result.tree_steps.extend({"name": s.name, "kind": s.kind, "cost": s.cost, "gain": s.gain} for s in opt.history)
        result.explanation = explain(result)
        self.log(result.explanation)
        c, o = result.conservative_stats.get("CombinedDPS") or 0, result.optimistic_stats.get("CombinedDPS") or 0
        if o < c * 0.999:
            result.audit.append(Finding("error", "lanes", f"optimistic DPS {o:,.0f} < conservative {c:,.0f}: an optimistic toggle hurts the build"))
        for finding in result.audit:
            self.log(f"audit {finding}")
        result.pob_calls = pob.pob_calls() if callable(getattr(pob, "pob_calls", None)) else {}
        trees = self.judging.trees()
        graph = getattr(trees[0], "graph", None) if trees else None
        result.tree_churn = tree_churn_metrics(result.construction_tree, self._tree_nodes(pob), graph=graph)
        result.seconds = time.perf_counter() - t_all
        return result

    def _value_with_enabled(self, skeleton: Skeleton, tree: TreeOptimizer, cand, trial: dict):
        """A candidate node that generates charges or gains Rage on hit, judged with what it enables:
        allocate it for real, derive the lanes (the generator turns its toggle on when the numbers say
        so; the ramp derives `multiplierRage` from the node's own text), score under the optimizer's
        objective, restore. None when the lanes do not change (nothing enabled)."""

        from junkroan.optimizer.objective import Score

        pob = self.pob
        held = pob.config_inputs()
        before = {k: v for k, v in held.items() if str(k).startswith("use") and str(k).endswith("Charges")}
        rage_before = held.get(RAGE_INPUT) or 0
        with self.judging.trial():  # export on entry, load back on exit; the new lanes are scored under the old contexts (Q9)
            removal = {"remove": list(trial["remove"])} if trial.get("remove") else {}  # a refine swap: the tree it would leave
            applied = pob.mutate_nodes(add=[cand.node_id], mastery_effects=trial.get("mastery") or None, **removal)
            if not applied.get("added_node_ids"):
                return None
            # PoB has now told us exactly which nodes the allocation added. A charge toggle can only
            # go from off to on if one of them (or the mastery effect chosen for it) generates that
            # kind, so when none does, `derive_config` -- ~1 s of the ~2.9 s this call costs -- has
            # nothing to find and is not run (speed audit 2026-09-18: 86% of the calls end here).
            universe = {f"use{kind}Charges" for kind in tree.CHARGE_KINDS} | set(before)
            off = {k for k in universe if before.get(k) is not True}
            grants = tree.generator_kinds([int(n) for n in applied["added_node_ids"]], trial.get("mastery") or {})
            gains_rage = TreeOptimizer.RAGE_KIND in grants  # PoB hides the Rage option until a source is allocated, so the lanes must see the node
            if not gains_rage and not any(f"use{kind}Charges" in off for kind in grants):
                return None
            derived = self.judging.lanes.read()
            after = {k: v for k, v in derived.conservative.inputs.items() if str(k).startswith("use") and str(k).endswith("Charges")}
            rage_after = (derived.conservative.inputs.get(RAGE_INPUT) or 0) if gains_rage else rage_before
            if not any(after.get(k) is True and before.get(k) is not True for k in after) and rage_after == rage_before:
                return None
            self.judging.lanes.write(skeleton, derived)
            score = tree.objective.score(pob.stats(tree.objective.stat_keys))
            enabled = [f"{k} on" for k in after if after.get(k) is True and before.get(k) is not True]
            if rage_after != rage_before:
                enabled.append(f"{RAGE_INPUT} {rage_before} -> {rage_after}")
            self.log(f"generator {cand.name}: judged with {', '.join(enabled)}: {score.value:,.0f} (viol {score.violation:.3f})")
            return score

    def _generator(self) -> "SkeletonGenerator":
        """A picker that shares this build's frozen skill-cost context."""

        from junkroan.search.generator import SkeletonGenerator

        return SkeletonGenerator(self.pob, self.rails, objective=self.objective, log=self.log,
                                 castability_context=self.judging.castability_context, castability_metrics=self.castability_metrics)

    def _tune_lanes(self, skeleton: Skeleton, *, identity: bool) -> dict[str, str]:
        """The lanes as `_finish` derives them, so the loop judges its moves under the objective the
        build is reported with (D60): the list choices (stance, exposure type, Pride's effect) judged
        by PoB, and with `identity` the bandit and the pantheons too (the bandit's extra points spent).
        The chosen values stay on the skeleton and every later reconfigure re-applies them."""

        derived = self.judging.relane(skeleton)
        chosen = tune_choices(self.pob, skeleton, derived, objective=self.judging.objective, write=self.judging.lanes.write,
                              log=lambda message: self.log(message), guard=False)
        if identity:
            chosen.update(self._tune_identity(skeleton, derived))
        self.judging.rejudge(skeleton)  # the lanes the build now stands under, ramp included
        return chosen

    PANTHEON_MAJOR = ("None", "TheBrineKing", "Lunaris", "Solaris", "Arakaali")
    PANTHEON_MINOR = ("None", "Gruthkul", "Yugul", "Abberath", "Tukohama", "Garukhan", "Ralakesh", "Ryslatha", "Shakari")

    def _rails_identity(self, skeleton: Skeleton) -> None:
        """Identity the rails fix instead of the optimizer choosing it: the bandit and, when the rail
        is not None, the two pantheon gods (#392). Kill them all,
        always (the user, 2026-09-18) -- the passive points beat every reward, and that is what
        every PoB people play from carries. An author's own bandit rides in with their skeleton
        (Alira on kinetic_fusillade s2) and stays in the author's row; ours never keeps it."""

        if skeleton.bandit != self.rails.bandit:
            self.log(f"bandit: {skeleton.bandit!r} -> {self.rails.bandit!r} (rails)")
            skeleton.bandit = self.rails.bandit
        for attr in ("pantheon_major", "pantheon_minor"):
            rail = getattr(self.rails, attr)
            if rail is not None and getattr(skeleton, attr) != rail:
                self.log(f"{attr}: {getattr(skeleton, attr)!r} -> {rail!r} (rails)")
                setattr(skeleton, attr, rail)

    def _tune_identity(self, skeleton: Skeleton, derived) -> dict[str, str]:
        """The pantheons are choices unless the rails fix them (a rail value that is not None is set
        and tried against nothing, #392): try each, keep the best objective score, ties broken by EHP
        (pantheons rarely move DPS). The bandit is not a choice any more -- the rails kill them all
        (`run`) -- so what is left of it is spending the passive points that pays."""

        chosen: dict[str, str] = {}
        self.judging.lanes.write(skeleton, derived)
        self._spend_extra_points(skeleton)  # killing every bandit pays in passive points (PoB's ExtraPoints)
        for attr, options in (("pantheon_major", self.PANTHEON_MAJOR), ("pantheon_minor", self.PANTHEON_MINOR)):
            rail = getattr(self.rails, attr)
            if rail is not None:
                setattr(skeleton, attr, rail)
                chosen[attr] = rail
                continue
            best = None
            for value in options:
                setattr(skeleton, attr, value)
                self.judging.lanes.write(skeleton, derived)
                stats = self.pob.stats((*self.objective.stat_keys, *MAX_HIT_KEYS))
                key = (self.objective.score(stats), bossing_defence(stats))
                if best is None or key > best[0]:
                    best = (key, value)
            setattr(skeleton, attr, best[1])
            chosen[attr] = best[1]
        self.judging.lanes.write(skeleton, derived)
        return chosen

    def _spend_extra_points(self, skeleton: Skeleton) -> int:
        """Passive points the build may still allocate under PoB's rule for its level and bandit
        (ExtraPoints from killing every bandit), spent by the tree optimizer under the full objective."""

        extra = int(self.pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)
        spare = max_passive_points(skeleton.level, extra) - self._points_used()
        tree = self.judging.view("tree")
        if spare <= 0 or tree is None:
            return 0
        # #865 rule 4: the step judges under the objective the delivered numbers are read under. The "tree" view is the full
        # objective minus the movement floor (a gear floor by design for the tree loop), so for this one call it lends the
        # full objective and gets its own back, also on an exception; a refresh made during the lend is dropped (`lend`).
        full = self.judging.objective
        stats = self.pob.stats(full.stat_keys)
        self.log(
            f"spare-point step: violation under the tree view {sum(tree.objective.violations(stats).values()):.6f}, "
            f"under the delivered objective {sum(full.violations(stats).values()):.6f}"
        )
        tree.note_build_change()  # a hook Score cached under the other objective is not an answer under this one
        try:
            with self.judging.lend("tree", full):
                allocation = tree.allocate(spare, spend_on_tie=True)  # #865: a tie is judged again on the floors' margins, not a stop
                self._last_spend_names = [str(getattr(step, "name", "?")) for step in getattr(allocation, "steps", ())]  # #1064: what the repair's note names
                return allocation.points_spent
        finally:
            tree.note_build_change()  # and what the lent objective cached is not an answer under the view's own

    def _ensure_sockets(self, gear) -> None:
        """#435: the delivered build has at most `coloured_max` R/G/B sockets, each with a gem of its colour, and
        every other socket white. Runs `colour_step` only when the equipped socket strings differ from what the
        last step left (a first call, a loaded-back entry build, a re-rolled item); otherwise no trial at all."""

        if not self._sockets_stale():
            return
        colour_step(self.pob, self.objective, lambda new, cur: better_score(new, cur), lambda message: self.log(message))
        if gear is not None:
            sync_gear_sockets(gear, self.pob)
        self._socket_lines = socket_state(self.pob)

    def _deliver_vaal_twins(self) -> None:
        """#802 rules 2-3: once, after the last gem decision and before the delivered numbers are read, every gem with a Vaal
        version is written as it (Vaal half off, level / quality as they stand); the colouring memory follows the new names."""

        pob = self.pob
        if not all(callable(getattr(pob, name, None)) for name in ("export_xml", "load_xml", "read_state")):
            return  # a PoB without the surface (a fake in a test) has no gem list to write
        gems = getattr(self.rails, "gems", None)
        if gems is None:
            return  # a lightweight rails stand-in has no loadout pair to count the delivered gems against
        if deliver_vaal_twins(pob, self.objective, self.log, level_rail=gems.level, quality_rail=max(gems.quality, gems.main_quality)):
            self._socket_lines = socket_state(pob)

    def _sockets_stale(self) -> bool:
        """True when the colour step has to run: no step ran on this build, or the sockets strings or the gems differ
        from what the last step left (a loaded-back entry build, a re-rolled item, a swapped gem; #547)."""

        if not (hasattr(self.pob, "equipped_item_raws") and hasattr(self.pob, "equip") and hasattr(self.pob, "read_state")):
            return False  # a PoB without the socket capability (a fake in a test) has nothing to whiten or colour
        return getattr(self, "_socket_lines", None) != socket_state(self.pob)

    def _prune_optimistic(self, skeleton: Skeleton, derived) -> list[str]:
        """An optimistic toggle is an assumption in the build's favour; one that lowers
        the objective (Unholy Might zeroed a Cyclone Champion) is an interaction PoB
        models, so it leaves the lane. One pass, each optimistic-only toggle removed alone."""

        extra = [k for k, v in derived.optimistic.inputs.items() if v is True and derived.conservative.inputs.get(k) is not True]
        if not extra:
            return []

        def optimistic_value() -> float:
            self.judging.lanes.write(skeleton, derived)
            return float(self.pob.calc("conditional").get("CombinedDPS") or 0)

        full = optimistic_value()
        dropped: list[str] = []
        for var in extra:
            derived.optimistic.inputs.pop(var, None)
            without = optimistic_value()
            if without > full * 1.01:
                dropped.append(var)
                derived.optimistic.reasons[var] = f"off: lowers the optimistic objective ({full:,.0f} -> {without:,.0f} without it)"
                full = without
            else:
                derived.optimistic.inputs[var] = True
        if dropped:
            self.judging.lanes.write(skeleton, derived)
        return dropped

    def _slots_with_damage_headroom(self, skeleton: Skeleton, loot: LootGear | WishlistGear, slots: list[str], loot_n: int | None, seed: int) -> list[str]:
        return _slots_with_damage_headroom(self.pob, self.objective, self.rails, skeleton, loot, slots, loot_n, seed)

    # -- day-1 rare jewels (#434) ---------------------------------------------------------------------------------

    def _jewel_args(self) -> dict[str, Any]:
        """`set_tree(jewels=..., nodes=...)` for the jewels the steps placed; nothing when they placed none (a session
        without the argument keeps working). The cluster jewels come first (a Medium may sit in a Large's socket) and
        carry their allocation (#433): the inner nodes exist only while their jewel sits in the socket, so `set_tree`
        allocates the path to the socket and the inner nodes after it has applied the cluster."""

        clusters = dict(getattr(self, "_clusters", None) or {})
        jewels = {**clusters, **(getattr(self, "_jewels", None) or {})}
        args: dict[str, Any] = {"jewels": jewels} if jewels else {}
        nodes = sorted({n for socket in clusters for n in (getattr(self, "_cluster_nodes", None) or {}).get(socket, ())})
        if nodes:
            args["nodes"] = nodes
        return args

    def _jewel_probe(self, skeleton: Skeleton, tree_full: TreeOptimizer, points: int, tree_max_depth: int, *, item_level: int | None = None) -> PobJewelProbe:
        extra = {} if item_level is None else {"item_level": item_level}
        return PobJewelProbe(self.pob, lambda: self.objective, tree_full.graph, points=points, max_depth=tree_max_depth,
                             excluded=lambda: tree_full.excluded_nodes, protected=frozenset(skeleton.keystones) | self._protected_nodes(skeleton), **extra)

    def _forget_tree_answers(self) -> None:
        for opt in getattr(self, "_trees", ()):
            invalidate = getattr(opt, "invalidate_after_recovery", None)
            if callable(invalidate):
                invalidate()

    # -- day-1 rare cluster jewels (#433) -------------------------------------------------------------------------

    def _lane_item_level(self, loot: LootGear | WishlistGear) -> int:
        """The item level the lane crafts its rares at (wishlist 72, loot 70): the cluster jewel is crafted at the same."""

        return loot.item_level_for("default")

    def _cluster_step(self, result: BuildResult, skeleton: Skeleton, loot: LootGear | WishlistGear, tree_full: TreeOptimizer, points: int, tree_max_depth: int) -> None:
        """Up to `rails.gear.clusters.count_max` rare cluster jewels (size, enchant, up to `notables_max` notables, the
        socket and the inner path), every one measured by PoB. Runs before the regular jewels. The step stays only when
        the build, with its lanes derived again, scores above what it was before: else it is loaded back as it was."""

        pob = self.pob
        rails = self.rails.gear.clusters
        if rails.count_max <= 0 or not callable(getattr(pob, "socketed_jewels", None)) or not callable(getattr(pob, "cluster_graph", None)):
            self._step_skipped("clusters")
            return
        self._step_start("clusters")
        t0 = time.perf_counter()
        before = self.objective.score(pob.stats(self.objective.stat_keys))
        shots = _snapshotter(self, skeleton)
        snapshot = shots.take(xml=True)  # the XML only: `rejudge` re-derives the judging after a revert
        ilvl = self._lane_item_level(loot)
        probe = TracingClusterProbe(self._jewel_probe(skeleton, tree_full, points, tree_max_depth, item_level=ilvl))
        enchants = {size: cluster_enchants(size) for size in rails.sizes}
        notables: dict[tuple[str, str], list[str]] = {}

        def notables_for(enchant: Any, size: str) -> list[str]:
            if (size, enchant.id) not in notables:
                notables[(size, enchant.id)] = [n.name for n in cluster_notables(enchant, ilvl)]
            return notables[(size, enchant.id)]

        def make_candidate(size: str, enchant: Any, names: tuple[str, ...]) -> ClusterCandidate:
            candidate = ClusterCandidate(size, enchant, tuple(names), int(rails.passives.get(size, DAY1_PASSIVES[size])))
            count_generated_clusters([candidate])
            return candidate

        def socket_size(node_id: int) -> int | None:
            node = tree_full.graph.node(node_id)
            return None if node is None else cluster_socket_size(node)

        with TRACE.move("cluster"):
            count_generated_clusters(())
            step = run_cluster_step(probe, enchants, notables_for, make_candidate, count_max=rails.count_max, notables_max=rails.notables_max,
                                    screen_keep=rails.screen_keep, socket_size=socket_size, is_inner=tree_full.graph.is_inner_socket)
            count_inner_skipped(len(step.inner_skipped))
        for placed in step.placed:
            self.log(cluster_log_line(placed, placed.seconds))
        tail = f"{len(step.placed)} placed ({step.stopped_reason}); Score {step.score_before:.6g} -> {step.score_after:.6g}, {step.trials} trials, {human_duration(step.seconds)}"
        if not step.placed:
            self._record(result, "clusters", t0, tail)
            return
        held = pob.socketed_jewels()
        self._cluster_placed = list(step.placed)
        self._clusters = {c.socket_id: held[c.socket_id] for c in step.placed if c.socket_id in held}
        self._cluster_nodes = {c.socket_id: tuple(c.path) for c in step.placed if c.socket_id in held}
        self.judging.rejudge(skeleton)
        after = self.objective.score(pob.stats(self.objective.stat_keys))
        if not after > before:
            shots.restore(snapshot)
            self.judging.rejudge(skeleton)
            self._clusters, self._cluster_nodes, self._cluster_placed = {}, {}, []
            self.log(f"clusters: reverted ({before.value:,.0f} -> {after.value:,.0f})")
            tail = f"reverted ({before.value:,.0f} -> {after.value:,.0f}); " + tail
        self._forget_tree_answers()
        self._record(result, "clusters", t0, "; ".join(cluster_log_line(c, c.seconds) for c in self._cluster_placed) + ("; " if self._cluster_placed else "") + tail)

    def _jewel_step(self, result: BuildResult, skeleton: Skeleton, tree_full: TreeOptimizer, points: int, tree_max_depth: int) -> None:
        """Up to `rails.gear.jewels.count_max` rare jewels of one line each, every one measured by PoB: the line in the
        cheapest socket, then the socket that pays for it. The step stays only when the build, with its lanes derived
        again, scores above what it was before: else the build is loaded back as it was."""

        pob = self.pob
        count_max = self.rails.gear.jewels.count_max
        if count_max <= 0 or not callable(getattr(pob, "socketed_jewels", None)):
            self._step_skipped("jewels")
            return
        self._step_start("jewels")
        t0 = time.perf_counter()
        before = self.objective.score(pob.stats(self.objective.stat_keys))
        shots = _snapshotter(self, skeleton)
        snapshot = shots.take(xml=True)  # the XML only: `rejudge` re-derives the judging after a revert
        probe = TracingJewelProbe(self._jewel_probe(skeleton, tree_full, points, tree_max_depth))
        candidates = jewel_line_candidates()
        with TRACE.move("jewel"):
            count_generated(candidates)
            step = run_jewel_step(probe, candidates, count_max=count_max)
        for jewel in step.jewels:
            self.log(jewel_log_line(jewel, jewel.seconds))
        if not step.jewels:
            self._record(result, "jewels", t0, f"none placed ({step.stopped_reason}); {step.measured} measured")
            return
        self._jewel_placed = list(step.jewels)
        held = pob.socketed_jewels()
        self._jewels = {j.socket_id: held[j.socket_id] for j in step.jewels if j.socket_id in held}
        self.judging.rejudge(skeleton)
        after = self.objective.score(pob.stats(self.objective.stat_keys))
        if not after > before:
            shots.restore(snapshot)
            self.judging.rejudge(skeleton)
            self._jewels, self._jewel_placed = {}, []
            self.log(f"jewels: reverted ({before.value:,.0f} -> {after.value:,.0f})")
            note = f"reverted ({before.value:,.0f} -> {after.value:,.0f}); {step.measured} measured"
        else:
            note = "; ".join(f"socket {j.socket_id} '{j.candidate.id}'" for j in step.jewels) + f"; {step.measured} measured"
        self._forget_tree_answers()
        self._record(result, "jewels", t0, note)

    def _drop_stray_jewels(self) -> list[int]:
        """Take out every jewel whose socket is not allocated (a later step freed it): the export writes no jewel
        in an unallocated socket. A cluster jewel goes with its inner nodes (PoB takes the subgraph out with the jewel)
        and leaves the carried cluster state. Only a build the jewel or cluster step placed jewels in is touched."""

        pob = self.pob
        if not getattr(self, "_jewel_placed", None) and not getattr(self, "_cluster_placed", None):
            return []
        allocated = {int(n) for n in pob.tree_light().get("user_allocated_node_ids") or ()}
        stray = [socket for socket in pob.socketed_jewels() if socket not in allocated]
        for socket in stray:
            pob.remove_jewel(socket)
            (getattr(self, "_jewels", None) or {}).pop(socket, None)
            (getattr(self, "_clusters", None) or {}).pop(socket, None)
            (getattr(self, "_cluster_nodes", None) or {}).pop(socket, None)
        if stray:
            self._jewel_placed = [j for j in getattr(self, "_jewel_placed", None) or [] if j.socket_id not in stray]
            self._cluster_placed = [c for c in getattr(self, "_cluster_placed", None) or [] if c.socket_id not in stray]
            self.log(f"jewels: dropped {stray} (socket no longer allocated)")
        return stray

    def _jewel_repick(self, result: BuildResult, skeleton: Skeleton, tree_full: TreeOptimizer, points: int, tree_max_depth: int) -> None:
        """The end re-pick: each placed jewel's line measured again on the final tree and gear among the ten best of
        its own pick plus the current one. One `result.moves` row per jewel keeps the ledger's identity."""

        pob = self.pob
        self._drop_stray_jewels()
        if not getattr(self, "_jewel_placed", None):
            return
        probe = TracingJewelProbe(self._jewel_probe(skeleton, tree_full, points, tree_max_depth))
        kept_jewels: list[PlacedJewel] = []
        for jewel in self._jewel_placed:
            t0 = time.perf_counter()
            before = self.objective.score(pob.stats(self.objective.stat_keys))
            with TRACE.move("jewel re-pick"):
                measured = {jewel.candidate.id: jewel.candidate}
                for candidate, _score in jewel.ranking[:10]:
                    measured.setdefault(candidate.id, candidate)
                count_generated(measured.values())
                (picked,) = repick_jewels(probe, [jewel], top=10)
            changed = picked.candidate.id != jewel.candidate.id
            if changed:
                self.judging.rejudge(skeleton)
            after = self.objective.score(pob.stats(self.objective.stat_keys))
            seconds = time.perf_counter() - t0
            kept_jewels.append(replace(picked, seconds=seconds))
            self.log(jewel_log_line(replace(picked, score_before=before.value, score_after=after.value), seconds)
                     + (f" (was '{jewel.candidate.id}')" if changed else " (line kept)"))
            result.moves.append({
                "pass": 0, "where": "jewel re-pick", "move": f"jewel socket {jewel.socket_id}", "seconds": seconds,
                "before": before.value, "after": after.value, "kept": bool(changed), "reverted_by_judge": False,
                "violation_before": before.violation, "violation_after": after.violation,
            })
        self._jewel_placed = kept_jewels
        held = pob.socketed_jewels()
        self._jewels = {j.socket_id: held[j.socket_id] for j in kept_jewels if j.socket_id in held}
        self._forget_tree_answers()

    # ---- the fill step (#1156) ----------------------------------------------------------------------------

    def _fill_step(self, result: BuildResult, skeleton: Skeleton) -> None:
        """After the utility pick: every free socket gets the aura, guard, herald or buff gem PoB counts as better by the rails'
        keep rule (`SkeletonGenerator.pick_fill`); a candidate with config choices of its own is measured under each of them."""

        self._step_start("fill")
        t0 = time.perf_counter()
        value_before = self.objective.score(self.pob.stats(self.objective.stat_keys)).value
        gen = self._generator()

        def tune(sk: Skeleton, choices: dict[str, list[str]]) -> dict[str, str]:
            derived = self.judging.relane(sk)
            return tune_given_choices(self.pob, sk, derived, choices, objective=self.judging.objective,
                                      write=self.judging.lanes.write, log=lambda message: self.log(message))

        with TRACE.move("fill"):
            added = gen.pick_fill(skeleton, reconfigure=self.judging.rejudger(skeleton), tune=tune,
                                  hold_config=lambda: self.judging.hold_config(skeleton))
        self._take_picks(result, gen, before=value_before)
        self.judging.rejudge(skeleton)
        self._record(result, "fill", t0, ", ".join(g.gems[0] for g in added) or "none")

    # ---- day-1 flasks and tinctures (#436) -----------------------------------------------------------------

    def _flask_step(self, result: BuildResult, skeleton: Skeleton) -> None:
        """Up to `rails.gear.flasks.slots` magic flasks / tinctures, every pick measured by PoB (`run_flask_step`),
        the `active` flags derived by PoB's own flask uptime calc (#575), never set here. A life build always carries
        a Divine Life Flask in the first slot (#589): the placement is kept, never reverted. Item level is the common
        `gear.item_level` rail, the base level cap `gear.wishlist.base_level_max`.
        #1162: with `flask_utility_crafting` false (day 1) only Flask 1 is trialled; Flask 2..N get no craft trial and
        stay as the build came in (empty on day 1), and the pool holds no utility flask (every base that is not Life,
        Mana or Hybrid, tinctures included)."""

        pob = self.pob
        rails = getattr(self.rails.gear, "flasks", None)
        if rails is None or rails.slots <= 0 or not callable(getattr(pob, "equip", None)):
            self._step_skipped("flasks")
            return
        self._step_start("flasks")
        t0 = time.perf_counter()
        item_level = int(self.rails.gear.item_level)
        base_level_max = int(self.rails.gear.wishlist.base_level_max)
        utility_ok = rails.flask_utility_crafting  # #1162: day 1 has no utility flask in the pool, and only Flask 1 is crafted
        bases = [b for b in flask_bases(base_level_max) if flask_base_allowed(b, rails)]
        slots = FLASK_SLOTS[:rails.slots] if utility_ok else FLASK_SLOTS[:1]
        before = self.objective.score(pob.stats(self.objective.stat_keys))
        probe = TracingFlaskProbe(PobFlaskProbe(pob, lambda: self.objective, item_level=item_level))
        made: list[FlaskCandidate] = []

        def make(base: Any, prefix: Any, suffix: Any) -> FlaskCandidate:
            made.append(FlaskCandidate(base, prefix, suffix))
            return made[-1]

        pure_es = bool(skeleton.pure_es) or is_pure_es(pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
        fixed = None
        if not pure_es:
            fixed = {FLASK_SLOTS[0]: flask_base(DIVINE_BASE)}
        with TRACE.move("flask"):
            step = run_flask_step(probe, bases, lambda b: flask_mods(b, item_level), make, slots=slots,
                                  item_level=item_level, base_level_max=base_level_max, fixed=fixed)
            count_flasks_generated(made)
            if fixed is not None and not any(r.chosen is not None and DIVINE_BASE in r.chosen.base.name for r in step.slots):
                TRACE.add_evaluated([NO_DIVINE_CLASS])
        lines = [flask_log_line(r) for r in step.slots]
        for line in lines:
            self.log(line)
        self._flasks = {r.slot: r.chosen.raw(item_level) for r in step.slots if r.chosen is not None}
        self.judging.rejudge(skeleton)
        after = self.objective.score(pob.stats(self.objective.stat_keys))
        note = "; ".join(lines) + f"; {before.value:,.0f} -> {after.value:,.0f}; {step.measured} measured"
        self._record(result, "flasks", t0, note)

    def _restore_flasks(self) -> list[str]:
        """The flasks the step placed are in their slots; whatever a later move dropped (an item-set rewrite empties
        the slot) is equipped again. The `active` flags are derived by PoB's uptime calc (#575), nothing sets them
        here. Returns the slots it fixed."""

        pob = self.pob
        placed = getattr(self, "_flasks", None)
        if not placed:
            return []
        held = pob.equipped_item_raws()
        fixed: list[str] = []
        for slot, raw in placed.items():
            if not held.get(slot):
                pob.equip({slot: raw})
                fixed.append(slot)
        if fixed:
            self.log(f"flasks: put back {fixed} (a later move dropped them)")
        return fixed

    # ---- the amulet's anoint (#432) ------------------------------------------------------------------------

    @staticmethod
    def _amulet_holder(loot: LootGear | WishlistGear) -> dict[str, str] | None:
        """The dict holding the amulet's raw as the build wears it: the filler's own item, else the skeleton's unique."""

        if loot.current_raw.get("Amulet"):
            return loot.current_raw
        uniques = loot.uniques
        if uniques and uniques.get("Amulet"):
            return uniques
        return None

    def _anoint_classes(self) -> dict[str, str]:
        """notable name -> `oil:<highest oil of its recipe>`, over every notable of the tree (the rail's side and the forbidden one)."""

        return {c.name: f"oil:{c.highest_oil}" for c in anoint_candidates(OIL_ORDER[-1])}

    def _anoint_trace_generated(self, label: str, names: list[str], classes: dict[str, str], *, forbidden: bool) -> None:
        """#432: candidates built, by the highest oil of the recipe; the classes above `oil_max` are written as 0 so the
        forbidden side shows as 0, not as absent."""

        with TRACE.move(label):
            for n in names:
                TRACE.add_generated([classes.get(n, "oil:unknown")])
            if forbidden:
                limit = OIL_ORDER.index(self.rails.anoint.oil_max)
                for oil in {c for c in classes.values() if OIL_ORDER.index(c[4:]) > limit}:
                    TRACE.add_generated([oil], 0)
                    TRACE.add_evaluated([oil], 0)

    def _anoint_measurer(self, plain_raw: str, names: list[str], label: str = "anoint", classes: dict[str, str] | None = None):
        """`measure(name | None) -> float` for `pick_anoint`, and the `Score` of each name it has judged.

        None is a full equip of the emptied slot with the plain raw: a fast trial of plain text over a worn amulet
        that carries an anoint may inherit it (PoB `CopyAnointsAndEldritchImplicits`), a full equip does not. The
        named ones are one fast batch (an item trial with an explicit `Allocates` line equals the full equip, 0.0%,
        tests/test_anoint_pob.py), run with the plain amulet worn."""

        keys = self.objective.stat_keys
        scores: dict[str | None, Score] = {}

        def measure(name: str | None) -> float:
            if name is None and None not in scores:
                self.pob.equip({"Amulet": None})
                self.pob.equip({"Amulet": plain_raw})
                scores[None] = self.objective.score(self.pob.stats(keys))
            elif name is not None and name not in scores:
                todo = [n for n in dict.fromkeys([name, *names]) if n not in scores]
                outcomes = self.pob.trial_stats([{"item": {"slot": "Amulet", "raw": apply_anoint(plain_raw, n)}} for n in todo], keys, mode="fast")
                with TRACE.move(label):
                    for n in todo:
                        TRACE.add_evaluated([(classes or {}).get(n, "oil:unknown")])
                for n, outcome in zip(todo, outcomes):
                    ok = outcome.get("ok") and outcome.get("stats")
                    scores[n] = self.objective.score(outcome["stats"]) if ok else Score(float("-inf"), 0.0)
            return scalar(scores[name])  # pick_anoint ranks plain floats: `scalar` keeps `Score`'s key (#537)

        return measure, scores

    def _set_amulet_anoint(self, skeleton: Skeleton, loot: LootGear | WishlistGear, notable: str | None) -> bool:
        """Equip the amulet with `notable`'s anoint (None: none), keep the generators and the raw books in step.
        True when the amulet's raw changed. Always equips: the measuring left the plain amulet on."""

        holder = self._amulet_holder(loot)
        old_raw = holder["Amulet"]
        new_raw = apply_anoint(old_raw, notable)
        self.pob.equip({"Amulet": None})  # a plain raw equipped over an anointed amulet keeps the old anoint (PoB copies it)
        self.pob.equip({"Amulet": new_raw})
        loot.anoint = notable
        if new_raw == old_raw:
            return False
        holder["Amulet"] = new_raw
        loot.carry_result("Amulet", old_raw, new_raw)
        self.judging.rejudge(skeleton)  # the notable's own lanes, as after every gear change
        return True

    def _anoint_exclude(self, candidates: list) -> set[str]:
        nodes = self._tree_nodes(self.pob)
        return {c.name for c in candidates if c.node_id in nodes}

    def _anoint_step(self, result: BuildResult, skeleton: Skeleton, loot: LootGear | WishlistGear) -> None:
        """The amulet's anoint, picked on the finished tree and gear (#432): every notable within the oil rail that the
        tree does not already hold is measured against the same amulet with no anoint; the best one is kept only if
        it beats no anoint. The generators carry it from here, so every later amulet raw has it."""

        holder = self._amulet_holder(loot)
        if holder is None:
            self.log("anoint: skipped, no amulet on the build")
            self._step_skipped("anoint")
            return
        self._step_start("anoint")
        t0 = time.perf_counter()
        lines = holder["Amulet"].splitlines()
        base = lines[2].strip() if len(lines) > 2 else ""
        if not can_anoint(base):
            self.log(f"anoint: skipped, the amulet base {base!r} cannot be anointed")
            return
        try:
            plain = apply_anoint(holder["Amulet"], None)
        except ValueError as exc:
            self.log(f"anoint: skipped, {exc}")
            return
        candidates = anoint_candidates(self.rails.anoint.oil_max)
        exclude = self._anoint_exclude(candidates)
        names = [c.name for c in candidates if c.name not in exclude]
        classes = self._anoint_classes()
        self._anoint_trace_generated("anoint", names, classes, forbidden=True)
        measure, scores = self._anoint_measurer(plain, names, "anoint", classes)
        pick = pick_anoint(names, measure)
        self._anoint_first, self._anoint_all = pick, candidates
        self._set_amulet_anoint(skeleton, loot, pick.chosen)
        before = scores[None].value
        after = scores[pick.chosen].value if pick.chosen else before
        self._record(result, "anoint", t0, f"anoint: {pick.chosen or 'none (no anoint beat the plain amulet)'}, score {before:,.0f} -> {after:,.0f}, "
                                            f"{pick.measured} measured, {human_duration(time.perf_counter() - t0)}")

    def _anoint_repick(self, result: BuildResult, skeleton: Skeleton, loot: LootGear | WishlistGear) -> None:
        """After the loop: the tree and gear are final, so the anoint is judged again among the first pick's ten best and
        the one worn, with the notables now on the tree left out (the tree may have bought the anointed notable)."""

        first = getattr(self, "_anoint_first", None)
        holder = self._amulet_holder(loot)
        if first is None or holder is None:
            self._step_skipped("anoint re-pick")
            return
        self._step_start("anoint re-pick")
        t0 = time.perf_counter()
        keys = self.objective.stat_keys
        before = self.objective.score(self.pob.stats(keys))
        worn = anoint_of(holder["Amulet"])
        exclude = self._anoint_exclude(getattr(self, "_anoint_all", []))
        names = [n for n in dict.fromkeys([*(n for n, _s in first.ranked[:10]), *([worn] if worn else [])]) if n not in exclude]
        classes = self._anoint_classes()
        self._anoint_trace_generated("anoint-repick", names, classes, forbidden=True)
        measure, scores = self._anoint_measurer(apply_anoint(holder["Amulet"], None), names, "anoint-repick", classes)
        pick = repick_anoint(first, worn, measure, exclude=exclude)
        changed = self._set_amulet_anoint(skeleton, loot, pick.chosen)
        after = self.objective.score(self.pob.stats(keys))
        if changed and before > after:  # the fast trials and the full calculation disagreed: the worn anoint stays
            self._set_amulet_anoint(skeleton, loot, worn)
            pick, changed, after = replace(pick, chosen=worn), False, self.objective.score(self.pob.stats(keys))
        if changed:
            result.moves.append({"pass": max((int(m.get("pass") or 0) for m in result.moves), default=0), "where": "anoint re-pick", "move": "anoint re-pick",
                                 "seconds": time.perf_counter() - t0, "before": before.value, "after": after.value, "kept": True, "reverted_by_judge": False,
                                 "violation_before": before.violation, "violation_after": after.violation})
        verdict = f"{worn or 'none'} -> {pick.chosen or 'none'}" if changed else f"kept {worn or 'none'}"
        self._record(result, "anoint re-pick", t0, f"anoint re-pick: {verdict}, score {before.value:,.0f} -> {after.value:,.0f}, "
                                                    f"{pick.measured} measured, {human_duration(time.perf_counter() - t0)}")

    def _delivered_score(self) -> Score:
        """The score of the state PoB holds now under `self.objective`: the number `_record` writes."""

        return self.objective.score(self.pob.stats(self.objective.stat_keys))

    def _rebuild_tree(self, skeleton: Skeleton, tree: TreeOptimizer, points: int) -> str:
        """Reset the tree to ascendancy + fixed keystones (+ the scaling seed), grow it again with
        the greedy allocator on the gear as it stands, refine briefly; keep it only if it scores
        higher under the objective the build is delivered on (`self.objective`, the one `_record` scores
        with, #170), else restore the previous tree (D45). The tree is GROWN on the loop's tree view
        (with sustain, without movement; the optimizer passed in, #617); only keep / revert and the sum-or-cover pick read the delivered one."""

        pob = self.pob
        shots = _snapshotter(self, skeleton, trees=lambda: (tree,))
        snapshot = shots.take(xml=True)
        before_stats = pob.stats(self.objective.stat_keys)
        before = self.objective.score(before_stats)  # the state the previous stage recorded
        before_grown, before_grown_stats = tree.current_score()
        trace = [_rebuild_trace_line("before", before_grown, tree.objective.violations(before_grown_stats), before, self.objective.violations(before_stats))]
        # two regrows, one per repair estimate of the greedy (optimistic "sum", then "cover"; see
        # TreeOptimizer._repair_estimate): on eight finished builds each won some by 5-30% and the
        # optimistic one twice ended where no swap could repair it; PoB keeps the better tree
        attempts: list[tuple[Any, Any, str, list]] = []  # (score, snapshot of the grown build's XML, note, history slice)
        for mode in ("sum", "cover"):
            shots.restore(snapshot)
            mode_start = shots.take(history=True)  # what this mode's growth adds to `tree.history` is cut back after it
            history_mark = mode_start.history[0][1]
            tree.repair_estimate_mode = mode
            try:
                pob.set_tree(class_id=skeleton.class_name, ascendancy_id=skeleton.ascendancy, ascendancy_nodes=skeleton.ascendancy_nodes, **self._jewel_args())
                self._restore_fixed_tree(skeleton, tree)
                if skeleton.scaling and skeleton.scaling.get("stat"):
                    self._seed_scaling(skeleton, points)
                tree.allocate(max(0, points - self._points_used()))
                tree.refine(max_rounds=8)
                grown, _s = tree.current_score()  # construction objective: the repair trigger belongs to growing
                if grown.value > before_grown.value and grown.violation > before_grown.violation:
                    # worth repairing: the regrown tree is stronger but short of a floor (Cold DoT: 225k with a 0.18
                    # violation lost to 167k feasible and the seed ended at 73% of the author); more refine rounds
                    # trade some of the surplus for the floor before the comparison
                    tree.refine(max_rounds=16)
                    grown, grown_stats = tree.current_score()  # what refine climbed, after the extra rounds
                else:
                    grown_stats = _s
                # compare under lanes derived for the new tree: a tree that lost the node proving a lane condition
                # would otherwise score with the old tree's proof and win on paper only (a second, late rebuild judged
                # that way lost Hit Penance Brand 132 -> 98% and Stormbrand 130 -> 90% on the 3-seed benchmark)
                self.judging.rejudge(skeleton)
                after_stats = pob.stats(self.objective.stat_keys)
                after = self.objective.score(after_stats)  # what `_record` reads next
                trace.append(_rebuild_trace_line(mode, grown, tree.objective.violations(grown_stats), after, self.objective.violations(after_stats)))
            finally:
                tree.repair_estimate_mode = "sum"
            attempts.append((after, shots.take(xml=True), f"{mode} {after.value:,.0f} (viol {after.violation:.3f})", tree.history[history_mark:]))
            shots.restore(mode_start)
        best = max(attempts, key=lambda a: a[0])
        note = "; ".join(a[2] for a in attempts) + " | " + " | ".join(trace)
        for line in trace:
            self.log(line)
        if better_score(best[0], before):
            shots.restore(best[1])
            tree.history.extend(best[3])
            return f"{before.value:,.0f} (viol {before.violation:.3f}) -> {best[0].value:,.0f} (viol {best[0].violation:.3f}) kept [{note}]"
        shots.restore(snapshot)  # the snapshot carries the previous tree and its lanes
        return f"{best[0].value:,.0f} (viol {best[0].violation:.3f}) vs {before.value:,.0f} (viol {before.violation:.3f}), reverted [{note}]"

    def _reset_construction_tree(self, skeleton: Skeleton, tree: TreeOptimizer) -> None:
        """Remove the temporary rig tree while retaining the skeleton's fixed tree choices."""

        self.pob.set_tree(
            class_id=skeleton.class_name,
            ascendancy_id=skeleton.ascendancy,
            ascendancy_nodes=skeleton.ascendancy_nodes,
            **self._jewel_args(),
        )
        self._restore_fixed_tree(skeleton, tree)
        tree.invalidate_after_recovery()
        tree.history.clear()

    def _seed_scaling(self, skeleton: Skeleton, points: int) -> str:
        """Scaling direction from the request: climb the stat first, PoB judges the rest later (docs/REQUEST.md 5)."""

        stat = str(skeleton.scaling["stat"])
        share = float(skeleton.scaling.get("seed_points", 0.4))
        used = self._points_used()
        seed_points = max(0, min(points - used, int(round((points - used) * share))))
        # The seeder climbs one raw stat, so it is built like the main optimizers for every RAIL (the +30 attribute cap,
        # the forbidden node text incl. the self-cost lines, the forbidden keystones, the protected nodes: a seed
        # that takes a node the rails forbid hands it to every later stage, which never removes a node for being
        # forbidden) but for none of their JUDGEMENT: no `judging.cut` objective (its floors and sustain relations
        # would bend a "climb this stat" order), no `judging.attach`, and none of the five hooks (enabler_hook,
        # after_apply_hook, after_proof_removal_hook, snapshot/restore context): each is a lane re-derivation or a
        # full PoB judge per kept step, and the caller's `_record_rejudged` / `rejudge` runs the lanes once after the
        # whole seed. `tie_seed` stays unset (first listed wins on a tie, as before: threading the build seed in would
        # move picks on ties) and so does `cluster_links` (unchanged from the hand-built seeder; a rebuild that carries a
        # placed cluster is where it could matter, left to the brain). The seed stage stays cheap: it keeps
        # TreeOptimizer's defaults max_depth 6, max_trials 300, skip_inert False.
        seeder = build_tree_optimizer(self.pob, Objective(maximize=stat), self.rails, log=self.log, skeleton=skeleton,
                                      forbidden_text=getattr(self, "_tree_forbidden_text", tuple(self.rails.forbidden_node_text)),
                                      protected=self._protected_nodes(skeleton))
        with TRACE.move(SEED_MOVE):
            count_zero_tree_rails()
            seed = seeder.allocate(seed_points)
        return f"{seed.points_spent} points; {stat} = {self.pob.stats((stat,)).get(stat)}"

    def _take_picks(self, result: BuildResult, gen: "SkeletonGenerator", *, before: float | None) -> None:
        take_picks(result, gen, before=before)

    def _keystones(self) -> list[str]:
        from junkroan.optimizer.tree_graph import TreeGraph

        graph = TreeGraph.load()
        allocated = {int(n) for n in (self.pob.read_state().get("tree_state") or {}).get("user_allocated_node_ids") or []}
        return sorted(n.name for n in graph.nodes.values() if n.kind == "keystone" and n.node_id in allocated)

    def _protected_nodes(self, skeleton: Skeleton) -> frozenset[int]:
        """`protected_nodes_of` with the mastery effects the build holds now (a forced effect pins its holder)."""

        if not getattr(skeleton, "forced_nodes", ()):
            return frozenset()
        effects: dict[int, int] = {}
        for entry in self.pob.tree_light().get("mastery_effect_ids") or ():
            node, _, effect = str(entry).partition(":")
            if node.isdigit() and effect.isdigit():
                effects[int(node)] = int(effect)
        return protected_nodes_of(skeleton, effects)

    def _restore_fixed_tree(self, skeleton: Skeleton, tree: TreeOptimizer) -> None:
        """After a `set_tree` to the bare class: the fixed keystones and the request's forced nodes go back in
        (a regrow never evaluates a tree without them), and the trees' protected sets follow the new holders."""

        if skeleton.keystones:
            self.pob.add_nodes(skeleton.keystones)
        if getattr(skeleton, "forced_nodes", ()):
            skeleton.apply_forced_nodes(self.pob)
            protected = self._protected_nodes(skeleton)
            for opt in {id(t): t for t in (tree, *self.judging.trees())}.values():
                opt.protected = protected

    def _points_used(self) -> int:
        return int(self.pob.mutate_nodes()["points_used"])

    def _finish_construction(self, result: BuildResult, t_all: float) -> BuildResult:
        """Export the post-construction build without running final lanes or the loop."""

        objective_stats = self.pob.stats(self.objective.stat_keys)
        result.final_stats = self.pob.stats(REPORT_KEYS)
        result.final_stats.update(self.objective.derived_values(objective_stats))
        result.final_stats.setdefault(self.objective.maximize, objective_stats.get(self.objective.maximize))  # #1057: the maximised output under its own name
        result.conservative_stats = dict(result.final_stats)
        result.optimistic_stats = dict(result.final_stats)
        result.xml = self.pob.export_xml()
        result.import_code = encode_import_code(result.xml)
        result.seconds = time.perf_counter() - t_all
        return result


__all__ = ["BuildPipeline", "BuildResult", "StageRecord"]
