"""Shared fakes for the improvement loop's tests (#51 unit 8): the three fake builds (`_Pob`, `_Tree`, `_Loot`), the
production `Judging` over a fake PoB with no `BuildPipeline`, and `loop_over(...)`, which runs a `LoopPlan` on them.

Imported by the tests as `from loop_fakes import ...` (pytest's default import mode puts `tests/` on `sys.path`).
`BuildPipeline.__new__` appears here once, in `_finish_pipeline`, for the tests that also drive `_finish` (not the loop).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from junkroan.optimizer.build_result import BuildResult, record_stage
from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.improvement_loop import (
    ImprovementLoop,
    LoopFlags,
    LoopOutcome,
    LoopPlan,
    WorkingBuild,
    _joint_round,
    _slots_with_damage_headroom,
    _weapon_base_candidates,
    _weapon_base_fingerprint,
    _weapon_base_move,
    _weapon_base_numbers,
    _weapon_item_parts,
    _weapon_raw_base,
)
from junkroan.optimizer.gear_interface import GearInterface
from junkroan.optimizer.item_bases import bases_of_type, type_of
from junkroan.optimizer.judging import PobLanes
from junkroan.optimizer.objective import Objective, better_score
from junkroan.optimizer.pipeline import BuildPipeline, tune_flat_reservation_aura_levels
from junkroan.optimizer.socket_step import colour_step, socket_state, sync_gear_sockets
from junkroan.optimizer.tree_optimizer import Step

from judging_fakes import pob_judging

FLOORED = Objective(maximize="CombinedDPS", floors={"Life": 4000})  # a floor a gear roll can break and the tree repair

class _Pob:
    def __init__(self, value: float, *, life: float = 5000.0, calls: list | None = None) -> None:
        self.value, self.life = value, life
        self._snapshots: dict[str, tuple[float, float]] = {}
        self.loaded: list[str] = []
        self.equipped: list[dict] = []
        self.calls = calls if calls is not None else []

    def stats(self, keys):
        return {k: 0 for k in keys} | {"CombinedDPS": self.value, "Life": self.life}

    def tree_light(self) -> dict:
        # the fake's whole build is its two numbers, so they stand for the tree the loop fingerprints
        self.calls.append(("tree_light",))
        return {"class_id": "Witch", "user_allocated_node_ids": [int(self.value), int(self.life)], "mastery_effect_ids": []}

    def export_xml(self) -> str:
        token = f"xml{len(self._snapshots) + 1}"
        self._snapshots[token] = (self.value, self.life)
        self.calls.append(("export_xml", token))
        return token

    def load_xml(self, token: str) -> None:
        self.loaded.append(token)
        self.calls.append(("load_xml", token))
        self.value, self.life = self._snapshots[token]

    def equip(self, items: dict) -> None:
        self.equipped.append(items)
        self.calls.append(("equip", tuple(sorted(items))))

    def mutate_nodes(self, remove=None, add=None, mastery_effects=None):
        self.calls.append(("mutate_nodes", tuple(remove or ())))
        return {"removed_node_ids": list(remove or ()), "points_used": 0}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):  # #559: the headroom ranking rolls with a `sockets` too
        self.calls.append(("random_rares", base, n, seed))
        return []  # no roll beats the incumbent: the joint round falls back to its random slot pick

    def craft_rare(self, base, **_kwargs):  # #1158: the base swap runs on every slot; the fake crafts nothing, so no candidate is tried
        return {"raw": "", "problems": ["fake pob crafts nothing"], "unsupported_lines": []}

    def trial_stats(self, trials, keys, mode="fast"):
        return []

    def calc(self, lane: str) -> dict:  # the two-lane snapshot `_finish` puts in the report
        return {"CombinedDPS": self.value, "Life": self.life}


class _Tree:
    """`values`: what a refine leaves the number at, one entry per call (then it does nothing);
    `swap_values` the same for the path swaps, `reopt_values` for a ruin-and-recreate draw, `repairs`
    the (value, life) a repair-only refine (`max_rounds=0`, the gear move's) reaches -- empty means
    the tree cannot repair the roll."""

    def __init__(self, pob: _Pob, values, swap_values=(), repairs=(), reopt_values=(), calls: list | None = None,
                 corridor_values=(), region_values=()) -> None:
        self.pob, self.values = pob, list(values)
        self.swap_values, self.repairs, self.reopt_values = list(swap_values), list(repairs), list(reopt_values)
        # plan B's two trunk moves: an empty script means "this move kept nothing", which is what
        # the loop skips without judging (the move puts back everything it tried)
        self.corridor_values, self.region_values = list(corridor_values), list(region_values)
        self.calls = calls if calls is not None else []
        self.objective = FLOORED
        self.restore_failures = 0
        self.history: list = []  # the kept steps `_finish` puts in the build explanation

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        self.calls.append(("refine", max_rounds, repair_rounds))
        if max_rounds == 0:  # repair only
            if self.repairs:
                self.pob.value, self.pob.life = self.repairs.pop(0)
        elif self.values:
            self.pob.value = self.values.pop(0)
        return SimpleNamespace(steps=[])

    def swap_subtrees(self, *, max_size: int, max_seconds: float, max_candidates=None):
        self.calls.append(("swap_subtrees", max_size, max_seconds))
        if self.swap_values:
            self.pob.value = self.swap_values.pop(0)
        return SimpleNamespace(steps=[])

    def exchange_corridors(self, *, max_corridors: int, k: int, slack: int, max_applied: int, max_seconds):
        self.calls.append(("exchange_corridors", max_corridors, k, slack, max_applied, max_seconds))
        if self.corridor_values:
            self.pob.value = self.corridor_values.pop(0)
            return SimpleNamespace(steps=[Step(node_id=1, name="corridor", kind="corridor", cost=1,
                                               added_node_ids=[], mastery_effect=None, before=None, after=None,
                                               candidates_evaluated=1, seconds=0.0)])
        return SimpleNamespace(steps=[])

    def challenge_regions(self, *, per_bucket: int, replacements: int, max_challenges: int, max_seconds):
        self.calls.append(("challenge_regions", per_bucket, replacements, max_challenges, max_seconds))
        if self.region_values:
            self.pob.value = self.region_values.pop(0)
            return SimpleNamespace(steps=[Step(node_id=1, name="region", kind="region", cost=1,
                                               added_node_ids=[], mastery_effect=None, before=None, after=None,
                                               candidates_evaluated=1, seconds=0.0)])
        return SimpleNamespace(steps=[])

    def reoptimize(self, *, rounds: int, ruin_points: int, refine_rounds: int, seed: int):
        self.calls.append(("reoptimize", rounds, ruin_points, refine_rounds, seed))
        if self.reopt_values:
            self.pob.value = self.reopt_values.pop(0)
        return SimpleNamespace(steps=[])

    def current_allocated(self) -> set:
        return {1, 2, 3}

    def _random_branches(self, allocated, target_points: int, rng) -> list:
        self.calls.append(("_random_branches", target_points, round(rng.random(), 6)))  # the draw pins the rng order
        return [7, 8]

    def allocate(self, points: int, allocated=None):
        self.calls.append(("allocate", points, bool(self.objective.floors)))
        return SimpleNamespace(steps=[], points_spent=points)

    def note_build_change(self) -> None:  # #34: the pipeline tells the trees about a gear move
        self.build_changes = getattr(self, "build_changes", 0) + 1

    def invalidate_after_recovery(self, *, keep_rejections: bool = False) -> None:
        self.calls.append(("invalidate_after_recovery", keep_rejections))
        self._trial_memo = {}
        self._trial_carry = {}
        self._barren = set()
        self._stage_depth = 0
        if not keep_rejections:
            self._rejected_subtrees = set()


class _Loot(GearInterface):
    """`script`: slot -> [(raw, value[, life]), ...]; once a slot's script is spent the incumbent wins it.

    Answers `GearInterface` as the loot filler does (#795); item level 86 is the fake rails' `gear.item_level`."""

    def __init__(self, pob: _Pob, script, calls: list | None = None) -> None:
        self.pob, self.script = pob, {k: list(v) for k, v in script.items()}
        self.current_raw: dict[str, str] = {}
        self.uniques: dict[str, str] = {}
        self.anoint = None
        self.forced_lines: dict[str, list[str]] = {}
        self.objective = FLOORED
        self.calls = calls if calls is not None else []

    def item_level_for(self, slot: str) -> int:
        return 86

    def other_weapon_bases(self, base: str) -> list[str]:
        item_type = type_of(base)
        return [name for name in bases_of_type(item_type, max_level=86) if name != base] if item_type else []

    def resistance_plan_snapshot(self) -> dict:  # the loot filler has no plan (#795: the pipeline asks the gear, not its class)
        return {}

    def restore_resistance_plan(self, saved) -> None:
        pass

    def shopping_results(self) -> list:
        return []

    def fill_slot(self, slot: str, base: str, *, n=None, sockets=None, seed: int = 1, order="floors"):
        self.calls.append(("fill_slot", slot, base, n, sockets, seed, bool(self.objective.floors)))
        rolls = self.script.get(slot) or []
        roll = rolls.pop(0) if rolls else (self.current_raw.get(slot), self.pob.value, self.pob.life)
        raw, self.pob.value = roll[0], roll[1]
        if len(roll) > 2:
            self.pob.life = roll[2]
        if raw is not None:
            self.current_raw[slot] = raw
        return SimpleNamespace(raw=raw)



class _TemplateLoot(_Loot):
    """A template filler for the loop's tests: answers the template side of `GearInterface` the way `WishlistGear` does
    (refills by value, re-plans resistances on a gear move, snapshots its resistance plan); its `fill_slot` takes the
    `replan_resistance` and `_base_candidates` keywords the real one takes."""

    def __init__(self, pob, script, calls=None) -> None:
        super().__init__(pob, script, calls)
        self._resistance_assignments: dict = {"Boots": "cold"}
        self.resistance_plan: dict = {"assignment": "cold"}

    @property
    def refills_by_value(self) -> bool:
        return True

    def refill_victim_slot(self, slot, base, *, n, sockets, seed, order, preselected=None):
        kwargs = {"_base_candidates": (preselected,)} if preselected is not None else {}
        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order, **kwargs)

    def refill_slot(self, slot, base, *, n, sockets, seed, order):
        return self.fill_slot(slot, base, n=n, sockets=sockets, seed=seed, order=order, replan_resistance=True)

    def resistance_plan_snapshot(self) -> dict:
        import copy

        return {name: copy.deepcopy(getattr(self, name)) for name in ("_resistance_assignments", "_extra_resistance_assignments", "resistance_plan") if hasattr(self, name)}

    def restore_resistance_plan(self, saved) -> None:
        import copy

        for name, value in saved.items():
            setattr(self, name, copy.deepcopy(value))

    def plan_snapshot(self) -> dict:
        return {"resistance": self.resistance_plan_snapshot(), "current_results": {}}

    def plan_restore(self, saved) -> None:
        self.restore_resistance_plan(saved["resistance"])


def _skeleton(rare_bases: dict, main_link=("Fireball", "Controlled Destruction")) -> SimpleNamespace:
    return SimpleNamespace(class_name="Witch", ascendancy="Elementalist", main_link=list(main_link),
                           rare_bases=dict(rare_bases), uniques={}, sockets={}, extra_groups=[])



def _patch_generator(monkeypatch, changes: list) -> list:
    seen: list[int] = []

    class _Gen:
        def __init__(self, pob, rails, *, objective=None, log=None, castability_context=None, castability_metrics=None) -> None:
            self.picks = ()

        def rejudge_picks(self, skeleton, *, reconfigure=None, min_gain=0.005, max_sweeps=3, order="floors"):
            seen.append(max_sweeps)
            return list(changes)

    monkeypatch.setattr("junkroan.search.generator.SkeletonGenerator", _Gen)
    return seen



class _LifeLanes(PobLanes):
    """The session's lane source whose read answers `derived` and whose write applies the
    conservative lane's "Life" input to the fake PoB's life."""

    def __init__(self, pob, derived) -> None:
        super().__init__(pob)
        self.derived = derived

    def read(self):
        return self.derived

    def write(self, _skeleton, lanes) -> None:
        self.pob.life = lanes.conservative.inputs.get("Life", self.pob.life)



def _finish_pipeline(monkeypatch, pob: _Pob, tree: _Tree, lanes: dict, *, choices: dict | None = None):
    """`_finish` driven on the fake PoB: everything it reports with (the audit, the explanation, the
    import code, the mapping) is stubbed away, and what is left is the order of the steps, the guard
    and the final feasibility check. `lanes` is what `derive_config` returns as the conservative
    inputs, and the stubbed lane write really applies them -- that is how a lane derivation moves
    a number here."""

    derived = SimpleNamespace(choices=dict(choices or {}), custom_mods=(), charge_rates={}, stack_caps={},
                              conservative=SimpleNamespace(inputs=dict(lanes), reasons={}),
                              optimistic=SimpleNamespace(inputs=dict(lanes), reasons={}))
    monkeypatch.setattr("junkroan.optimizer.pipeline.encode_import_code", lambda _xml: "code")
    monkeypatch.setattr("junkroan.optimizer.pipeline.audit_build", lambda _pob, rails=None, objective=None, **_kwargs: [])
    monkeypatch.setattr("junkroan.optimizer.pipeline.switch_off_unproven_charges", lambda _pob: [])  # #908: the audit's proof is read from a real Baseline; the fake has none
    monkeypatch.setattr("junkroan.optimizer.pipeline.explain", lambda _result: "")
    monkeypatch.setattr("junkroan.optimizer.config_rules.build_text", lambda _pob: "")
    monkeypatch.setattr("junkroan.optimizer.mapping.mapping_lines", lambda *_a, **_k: [])
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {})

    logs: list[str] = []
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p.rails = SimpleNamespace(gear=SimpleNamespace(loot_best_of_n=200, item_level=86, quality=20), ascendancy_points=None)  # #1157: no ascendancy-swap in these plans
    p.log = logs.append
    p.judging = pob_judging(p, lanes=_LifeLanes(pob, derived))
    p.objective = FLOORED
    p.judging.attach("tree_construction", tree)
    p.judging.attach("tree", tree)
    p.judging.rejudge = lambda _sk, **_kwargs: None
    p._prune_optimistic = lambda _sk, _d: []
    p._keystones = lambda: []
    p._tune_identity = lambda _sk, _d: {}
    return p, derived, logs


def _finish_skeleton() -> SimpleNamespace:
    sk = _skeleton({}, main_link=("Fireball",))
    sk.tuned_choices, sk.pantheon_major, sk.pantheon_minor, sk.bandit = {}, "None", "None", "None"
    sk.forbid_keystones, sk.user_config = [], {}
    return sk



# -- the loop over a fake build, with no BuildPipeline ----------------------------------------------------


class _SocketMemory:
    """The colour step's memory (`_socket_lines`) and the two steps the loop calls through it, as
    `BuildPipeline._sockets_stale` / `_ensure_sockets` run them (#435, #547) over the rig's session."""

    def __init__(self, rig: "LoopRig") -> None:
        self.rig, self._socket_lines = rig, None

    def _sockets_stale(self) -> bool:
        pob = self.rig.pob
        if not (hasattr(pob, "equipped_item_raws") and hasattr(pob, "equip") and hasattr(pob, "read_state")):
            return False  # a PoB without the socket capability (a fake in a test) has nothing to whiten or colour
        return self._socket_lines != socket_state(pob)

    def _ensure_sockets(self, gear) -> None:
        if not self._sockets_stale():
            return
        colour_step(self.rig.pob, self.rig.objective, lambda new, cur: better_score(new, cur), lambda message: self.rig.log(message))
        if gear is not None:
            sync_gear_sockets(gear, self.rig.pob)
        self._socket_lines = socket_state(self.rig.pob)


class LoopRig:
    """What `loop_over` returns: the production `Judging` over the fake PoB, the loop's collaborators, and `run(plan)`.

    `pob`, `rails`, `log`, `castability_metrics`, `judging` and `objective` (the judging context's) are readable and
    writable like a pipeline's, because the tests set and read them the same way."""

    def __init__(self, pob, *, tree, gear, skeleton, rails, log, judging, castability_metrics, socket_owner) -> None:
        self.pob, self.tree, self.gear, self.skeleton = pob, tree, gear, skeleton
        self.rails, self.log, self.castability_metrics = rails, log, castability_metrics
        self.judging = judging if judging is not None else pob_judging(self)
        self.sockets = socket_owner if socket_owner is not None else _SocketMemory(self)
        self.result: BuildResult | None = None
        self.ascendancy_points: int | None = None  # #1157: the rails' ascendancy points; None = the loop has no ascendancy-swap entry
        # every collaborator is set by `loop_over`, each replaceable
        self.tune_lanes = self.picks = self.take_picks = self.record_of = self.aura_levels = None
        self.headroom = self.joint_round = self.weapon_raw_base = self.weapon_base_fingerprint = self.weapon_base_move = None

    @property
    def objective(self) -> Objective:
        return self.judging.objective

    @objective.setter
    def objective(self, objective: Objective) -> None:
        self.judging.objective = objective

    def attach_views(self) -> None:
        """Attach the loop's filler as "gear" and its tree as "tree", as `BuildPipeline.run` does before the loop."""

        self.judging.attach("gear", self.gear)
        self.judging.attach("tree", self.tree)

    def record(self, result: BuildResult, name: str, t0: float, notes: str = "") -> None:
        self.record_of(result, name, t0, notes)

    def started(self) -> BuildResult:
        """A result carrying the stage the loop follows: the baseline of the "no change" invariant of `record`."""

        self.result = BuildResult(skeleton=self.skeleton)
        self.record(self.result, "tree rebuilt on gear", 0.0)
        return self.result

    def run(self, plan: LoopPlan, *, flags: LoopFlags | None = None, result: BuildResult | None = None) -> LoopOutcome:
        """One loop (`ImprovementLoop.run`) over this build. `flags` only for a combination no `LoopPlan` kind gives."""

        self.attach_views()
        result = result if result is not None else (self.result if self.result is not None else self.started())
        self.result = result
        loop = ImprovementLoop(
            WorkingBuild(pob=self.pob, judging=self.judging, skeleton=self.skeleton, gear=self.gear, tree=self.tree), result,
            tune_lanes=lambda *args, **kwargs: self.tune_lanes(*args, **kwargs),
            picker=lambda: self.picks(),
            log=lambda message: self.log(message),
            record=lambda *args, **kwargs: self.record_of(*args, **kwargs),
            take_picks=lambda *args, **kwargs: self.take_picks(*args, **kwargs),
            aura_levels=lambda sk, order="priced": self.aura_levels(sk, order=order),
            joint_round=lambda *args, **kwargs: self.joint_round(*args, **kwargs),
            weapon_raw_base=lambda raw: self.weapon_raw_base(raw),
            weapon_base_fingerprint=lambda *args, **kwargs: self.weapon_base_fingerprint(*args, **kwargs),
            weapon_base_move=lambda *args, **kwargs: self.weapon_base_move(*args, **kwargs),
            sockets_stale=lambda: self.sockets._sockets_stale(),
            ensure_sockets=lambda gear: self.sockets._ensure_sockets(gear),
            socket_memory_get=lambda: getattr(self.sockets, "_socket_lines", None),
            socket_memory_set=lambda value: setattr(self.sockets, "_socket_lines", value),
            ascendancy_points=self.ascendancy_points,
        )
        return loop.run(plan, flags=flags)


def loop_over(pob, *, tree, gear, skeleton, objective: Objective | None = FLOORED, tune_lanes: Callable[..., dict] | None = None,
              picks: Callable[[], Any] | None = None, take_picks: Callable[..., None] | None = None, log: Callable[[str], None] | None = None,
              record: Callable[..., None] | None = None, aura_levels: Callable[..., dict] | None = None, joint_round: Callable[..., str] | None = None,
              headroom: Callable[..., list] | None = None, weapon_raw_base: Callable[[str], str] | None = None,
              weapon_base_fingerprint: Callable[..., tuple] | None = None, weapon_base_move: Callable[..., tuple] | None = None,
              rails: Any = None, judging=None, castability_metrics: CastabilityMetrics | None = None, socket_owner=None,
              reconfigures: list | None = None, calls: list | None = None) -> LoopRig:
    """The improvement loop over a fake PoB, with no `BuildPipeline`: the production `Judging` over `pob` (as
    `pob_judging` builds it) and every collaborator `ImprovementLoop.__init__` asks for, each replaceable by the keyword
    of its name (`picks` is the picker, `headroom` the joint kick's victim ranking). The defaults are the production
    functions, except the three the unit harnesses always stubbed: `tune_lanes` (the choices and the identity are PoB's
    judgement; the stub re-judges like the real one and answers `{}`), `take_picks` (a no-op) and, on a judging context
    built here, `rejudge` (a recorder: each call appends to `reconfigures`, and `("reconfigure",)` to `calls`).

    `judging` shares an existing context (a harness that also drives `_finish`); `socket_owner` shares the colour step's
    memory with it (an object with `_socket_lines`, `_sockets_stale()` and `_ensure_sockets(gear)`).
    `rig.run(LoopPlan(...), flags=LoopFlags(...) | None)` returns the `LoopOutcome`."""

    metrics = castability_metrics if castability_metrics is not None else CastabilityMetrics()
    rails = rails if rails is not None else SimpleNamespace(gear=SimpleNamespace(loot_best_of_n=200, item_level=86, quality=20))
    rig = LoopRig(pob, tree=tree, gear=gear, skeleton=skeleton, rails=rails, log=log if log is not None else (lambda _message: None),
                  judging=judging, castability_metrics=metrics, socket_owner=socket_owner)

    def reconfigure(_sk) -> None:
        if reconfigures is not None:
            reconfigures.append(1)
        if calls is not None:
            calls.append(("reconfigure",))

    def stub_tune_lanes(sk, *, identity: bool = False) -> dict:
        if calls is not None:
            calls.append(("tune_lanes", identity))
        reconfigure(sk)  # the real one ends in a reconfigure, which is what makes the lanes fresh (D60)
        return {}

    if judging is None:
        rig.judging.rejudge = lambda sk, **_kwargs: reconfigure(sk)  # the loop re-judges through its judging context
    if objective is not None:
        rig.objective = objective
    rig.tune_lanes = tune_lanes or stub_tune_lanes
    rig.picks = picks or (lambda: _generator(rig))
    rig.take_picks = take_picks or (lambda *_a, **_k: None)
    rig.record_of = record or (lambda result, name, t0, notes="": record_stage(rig.pob, rig.objective, result, name, t0, notes, rig.log))
    rig.aura_levels = aura_levels or (lambda sk, order="priced": tune_flat_reservation_aura_levels(rig.pob, rig.objective, rig.rails, sk, order=order))  # as pipeline.py wires it (D116 / #553)
    rig.headroom = headroom or (lambda sk, loot, slots, loot_n, seed: _slots_with_damage_headroom(rig.pob, rig.objective, rig.rails, sk, loot, slots, loot_n, seed))
    rig.weapon_raw_base = weapon_raw_base or _weapon_raw_base
    rig.weapon_base_fingerprint = weapon_base_fingerprint or (lambda loot, sk, slot, **kw: _weapon_base_fingerprint(rig.pob, loot, sk, slot, **kw))

    def joint(sk, loot, tree_, *, i, seed, loot_n, rng, ruin_points, slots_per_round, refine_rounds=6) -> str:
        rig.judging.attach("gear", loot)
        rig.judging.attach("tree", tree_)
        return _joint_round(rig.pob, rig.objective, rig.judging, sk, loot, tree_, i=i, seed=seed, loot_n=loot_n, rng=rng, ruin_points=ruin_points,
                            slots_per_round=slots_per_round, headroom=lambda *a, **k: rig.headroom(*a, **k), refine_rounds=refine_rounds)

    rig.joint_round = joint_round or joint
    rig.weapon_base_move = weapon_base_move or (lambda *args, **kwargs: _weapon_base_move(
        rig.pob, rig.objective, rig.rails, lambda message: rig.log(message), *args, raw_base=lambda raw: rig.weapon_raw_base(raw),
        fingerprint_of=lambda *a, **k: rig.weapon_base_fingerprint(*a, **k), item_parts=_weapon_item_parts, base_numbers=_weapon_base_numbers,
        candidates_of=lambda loot, base: _weapon_base_candidates(rig.rails, loot, base), **kwargs))
    return rig


def _generator(rig: LoopRig):
    """The picker `BuildPipeline._generator` builds, looked up at call time so a test's patch of the class takes effect."""

    from junkroan.search.generator import SkeletonGenerator

    return SkeletonGenerator(rig.pob, rig.rails, objective=rig.objective, log=rig.log,
                             castability_context=rig.judging.castability_context, castability_metrics=rig.castability_metrics)
