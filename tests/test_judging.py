"""The judging context (#35, step 1a of #32): the lanes and the objective's views in one module,
every number unchanged. On fakes, no PoB."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer import judging as judging_module
from junkroan.optimizer.judging import (
    compute_proof_holders,
    lane_memo,
    main_group,
    plan_config,
    restore_lanes,
    trauma_stacks,
    tune_choices,
    write_lanes,
)
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from judging_fakes import BASE, _Graph, _judging, _Lanes, _lanes, _Reads, _view, pob_judging

FLOORED = Objective(maximize="CombinedDPS", floors={"Life": 4000.0})


def _skeleton(**overrides) -> SimpleNamespace:
    base = dict(bandit="None", pantheon_major="Lunaris", pantheon_minor="None", user_config={}, tuned_choices={})
    return SimpleNamespace(**{**base, **overrides})


class _ConfigPob:
    """`config_inputs` and `set_config` only: what a lane write reads and writes."""

    def __init__(self, current: dict | None = None) -> None:
        self.current = dict(current or {})
        self.calls: list[tuple] = []
        self.written: dict | None = None

    def config_inputs(self) -> dict:
        self.calls.append(("config_inputs",))
        return dict(self.current)

    def set_config(self, **kwargs) -> None:
        self.calls.append(("set_config",))
        self.written = kwargs


# -- plan_config: the merge order ----------------------------------------------------------------


def test_plan_config_merges_preserved_then_lane_then_tuned_then_user() -> None:
    current = {"multiplierRage": 20, "customNumber": 7, "conditionOnConsecratedGround": True,
               "overrideBleedStackPotential": 3, "enemyIsBoss": "Pinnacle", "bandit": "Alira", "enemyHit": 999}
    lanes = _lanes({"multiplierRage": 30, "enemyIsBoss": "Pinnacle", "overrideBleedStackPotential": 2,
                    "multiplierBleedsOnEnemy": 4, "bloodSandStance": "SAND", "multiplierMineDetonatedRecently": 1},
                   {"multiplierRage": 50, "bloodSandStance": "SAND", "conditionEnemyIgnited": True},
                   custom_mods=(("line", "title"),))
    plan = plan_config(current, lanes, tuned_choices={"bloodSandStance": "BLOOD", "multiplierMineDetonatedRecently": 42},
                       user_config={"multiplierMineDetonatedRecently": 10},
                       known_vars={"multiplierRage", "customNumber", "multiplierBleedsOnEnemy"})

    # preserved numeric (customNumber) < lane (Rage 30 over 20) < tuned (BLOOD) < user (10 over 42);
    # booleans, the native overrides, enemyIsBoss and the identity vars are never preserved
    assert plan.inputs == {"multiplierRage": 30, "customNumber": 7, "multiplierBleedsOnEnemy": 4,
                           "bloodSandStance": "BLOOD", "multiplierMineDetonatedRecently": 10}
    assert plan.conditional == {"inputs": {"multiplierRage": 50, "customNumber": 7, "bloodSandStance": "BLOOD",
                                           "conditionEnemyIgnited": True, "multiplierMineDetonatedRecently": 10}}
    assert plan.stack_caps == {"overrideBleedStackPotential": 2, "multiplierBleedsOnEnemy": 4}
    assert plan.dropped == ["enemyHit"], "a fixture var PoB does not know is dropped, not preserved"
    assert plan.custom_mods == (("line", "title"),)
    assert plan.enemy_state == {"is_boss": "Pinnacle"} and plan.preserve == "none"


def test_plan_config_caps_the_users_poison_count_at_the_counted_stacks() -> None:
    lanes = _lanes({}, ailment_stack_caps={"poison": SimpleNamespace(counted=12)})
    plan = plan_config({}, lanes, tuned_choices=None, user_config={"multiplierPoisonOnEnemy": 40}, known_vars=set())
    assert plan.inputs == {"multiplierPoisonOnEnemy": 12}
    below = plan_config({}, lanes, tuned_choices=None, user_config={"multiplierPoisonOnEnemy": 5}, known_vars=set())
    assert below.inputs == {"multiplierPoisonOnEnemy": 5}
    flag = plan_config({}, lanes, tuned_choices=None, user_config={"multiplierPoisonOnEnemy": True}, known_vars=set())
    assert flag.inputs == {"multiplierPoisonOnEnemy": True}, "a boolean is not a count"


def test_write_lanes_hands_set_config_exactly_the_plan_and_logs_the_dropped_vars() -> None:
    pob = _ConfigPob({"enemyHit": 999, "multiplierRage": 20})
    logs: list[str] = []
    plan = write_lanes(pob, _skeleton(bandit="Alira"), _lanes({"conditionEnemyIgnited": True}), log=logs.append)

    assert pob.calls == [("config_inputs",), ("set_config",)]
    assert pob.written == {"bandit": "Alira", "pantheon_major": "Lunaris", "pantheon_minor": "None",
                           "enemy_state": {"is_boss": "Pinnacle"}, "inputs": plan.inputs,
                           "conditional": plan.conditional, "preserve": "none"}
    assert plan.inputs == {"multiplierRage": 20, "conditionEnemyIgnited": True}
    assert logs == ["fixture config var dropped: enemyHit (unknown to PoB)"]


def test_q12_the_proof_checks_writer_reads_identity_back_preserves_numbers_and_skips_the_merge(monkeypatch) -> None:
    """Q12: `write_lanes_preserving_numbers` (tree_hygiene's dead-leaf proof check) writes the
    re-derived lanes with the bandit and pantheons read back from PoB and `preserve="numeric"`, and
    without tuned choices, user numbers, a poison cap or a dropped-var check -- unlike `write_lanes`."""

    from junkroan.optimizer.judging import write_lanes_preserving_numbers

    ramp_calls: list[tuple] = []
    monkeypatch.setattr(judging_module, "apply_custom_mods",
                        lambda pob, mods, *, replace_ailment_stacks: ramp_calls.append(("custom_mods", mods, replace_ailment_stacks)))
    monkeypatch.setattr(judging_module, "apply_ailment_stack_caps", lambda pob, caps: ramp_calls.append(("stack_caps", caps)))

    class _Pob(_ConfigPob):
        def read_state(self) -> dict:
            self.calls.append(("read_state",))
            return {"config_state": {"bandit": "Kraityn", "pantheon_major": "", "pantheon_minor": "Gruthkul"}}

    pob = _Pob({"enemyHit": 999, "multiplierRage": 20})
    lanes = _lanes({"multiplierRage": 30, "enemyIsBoss": "Pinnacle", "overrideBleedStackPotential": 2, "multiplierBleedsOnEnemy": 4,
                    "multiplierPoisonOnEnemy": 40},
                   {"conditionEnemyShocked": True, "overrideIgniteStackPotential": 1},
                   custom_mods=(("line", "title"),), ailment_stack_caps={"poison": SimpleNamespace(counted=12)})

    assert write_lanes_preserving_numbers(pob, lanes) is None
    assert pob.calls == [("read_state",), ("set_config",)], "no config_inputs read: nothing preserved or dropped here"
    assert pob.written == {"bandit": "Kraityn", "pantheon_major": "None", "pantheon_minor": "Gruthkul",
                           "enemy_state": {"is_boss": "Pinnacle"},
                           "inputs": {"multiplierRage": 30, "multiplierBleedsOnEnemy": 4, "multiplierPoisonOnEnemy": 40},
                           "conditional": {"inputs": {"conditionEnemyShocked": True}},
                           "preserve": "numeric"}
    assert ramp_calls == [("custom_mods", (("line", "title"),), True),
                          ("stack_caps", {"overrideBleedStackPotential": 2, "multiplierBleedsOnEnemy": 4})]


# -- compute_proof_holders (D87) -----------------------------------------------------------------

ASCENDANCY_LINE = "gain a power charge after spending a total of 200 mana"
MASTERY_LINE = "gain a power charge each second while channelling a spell"
MASTERY, EFFECT = 60, 33089


def _mastery_graph() -> _Graph:
    return _Graph({MASTERY: SimpleNamespace(name="Caster Mastery", stats=(), mastery_effects=((EFFECT, (MASTERY_LINE,)), (99, ("something else",))))})


def _power_lanes(recheck) -> SimpleNamespace:
    lane = SimpleNamespace(proof_lines={"usePowerCharges": (ASCENDANCY_LINE, MASTERY_LINE)},
                           inputs={"usePowerCharges": True, "overridePowerCharges": 3}, reasons={})
    return SimpleNamespace(conservative=lane, recheck=recheck)


def test_a_proof_standing_on_the_sum_of_two_lines_makes_the_mastery_a_holder() -> None:
    """winter_orb: `usePowerCharges` stands on the SUM of an ascendancy line and the Caster Mastery's;
    neither is sole, and without the mastery the rule turns the input off."""

    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        rates = {ASCENDANCY_LINE: 0.4, MASTERY_LINE: 1.0}
        left = sum(rate for line, rate in rates.items() if line not in dict(masked))
        keys = ("usePowerCharges", "overridePowerCharges")
        return ProofRecheck(rule="charge_rule", keys=keys, inputs={} if left < 1.2 else {keys[0]: True, keys[1]: 3})

    reads: list[int] = []
    holders, undecidable = compute_proof_holders(_mastery_graph(), {MASTERY}, {MASTERY: EFFECT}, _power_lanes(recheck),
                                                 lambda: reads.append(1) or "")

    assert holders == {(MASTERY, EFFECT): {"usePowerCharges": (True, None), "overridePowerCharges": (3, None)}}
    assert undecidable == {} and reads == [], "a rule that can be re-run never reads the build text"


def test_a_rule_that_cannot_be_re_run_falls_back_to_the_sole_proof_test_and_reads_the_text_once() -> None:
    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        return ProofRecheck(rule="judge_stack_options", keys=(var,), inputs=None)

    reads: list[int] = []

    def text_with(*lines: str):
        def read() -> str:
            reads.append(1)
            return "\n".join(lines)
        return read

    # the ascendancy line is fixed evidence beside the mastery: not a sole proof, not a holder
    holders, undecidable = compute_proof_holders(_mastery_graph(), {MASTERY}, {MASTERY: EFFECT}, _power_lanes(recheck),
                                                 text_with(ASCENDANCY_LINE, MASTERY_LINE))
    assert holders == {} and undecidable == {"usePowerCharges": "judge_stack_options"} and reads == [1]

    # the mastery carries every proof line and each appears once in the build: the sole proof
    graph = _Graph({MASTERY: SimpleNamespace(name="Caster Mastery", stats=(), mastery_effects=((EFFECT, (ASCENDANCY_LINE, MASTERY_LINE)),))})
    holders, _ = compute_proof_holders(graph, {MASTERY}, {MASTERY: EFFECT}, _power_lanes(recheck), text_with(ASCENDANCY_LINE, MASTERY_LINE))
    assert holders == {(MASTERY, EFFECT): {"usePowerCharges": (True, None)}}


def test_post_holders_over_the_production_reads_posts_the_same_holders_as_the_pure_function() -> None:
    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        keys = ("usePowerCharges", "overridePowerCharges")
        held = {keys[0]: True, keys[1]: 1 if MASTERY_LINE in dict(masked) else 3}
        return ProofRecheck(rule="charge_rule", keys=keys, inputs=held)

    graph = _mastery_graph()
    pob = SimpleNamespace(read_state=lambda: {"tree_state": {"user_allocated_node_ids": [MASTERY], "mastery_effect_ids": [f"{MASTERY}:{EFFECT}"]}})
    logs: list[str] = []
    judging = Judging(PobLanes(pob, log=logs.append), PobReads(pob, gems=None, log=logs.append), log=logs.append)
    tree = SimpleNamespace(graph=graph, proof_holders=None)
    judging.post_holders(_power_lanes(recheck), (tree,))

    expected, _ = compute_proof_holders(graph, {MASTERY}, {MASTERY: EFFECT}, _power_lanes(recheck), "")
    assert tree.proof_holders == expected == {(MASTERY, EFFECT): {"overridePowerCharges": (3, 1)}}
    assert len(logs) == 1 and logs[0].startswith("proof holders: Caster Mastery [effect 33089] -> overridePowerCharges 3 -> 1 (")


# -- the small readbacks, the memo and the tuning ------------------------------------------------


def test_main_group_returns_the_gem_levels_instead_of_setting_them() -> None:
    state = {"skills_state": {"main_socket_group_id": 2, "socket_groups": [
        {"socket_group_id": 1, "gems": [{"gem_name": "Arc", "skill_id": "Arc", "level": 20}], "active_skill_entries": [{"triggered": True}]},
        {"socket_group_id": 2, "gems": [{"gem_name": "Soulrend", "skill_id": "Soulrend", "level": 18},
                                        {"gem_name": "Trauma", "skill_id": "SupportTrauma"}],
         "active_skill_entries": [{"triggered": False}]}]}}
    gems, triggered, levels = main_group(SimpleNamespace(read_state=lambda: state))
    assert gems == ["Soulrend", "Trauma"] and triggered is False
    assert levels == (("Soulrend", 18), ("SupportTrauma", 20))


def test_trauma_stacks_reads_the_lane_and_a_stand_in_without_config_has_none() -> None:
    assert trauma_stacks(SimpleNamespace(config_inputs=lambda: {"traumaStacks": 12})) == 12.0
    assert trauma_stacks(SimpleNamespace(config_inputs=lambda: {"traumaStacks": True})) == 0.0
    assert trauma_stacks(SimpleNamespace()) == 0.0


def test_lane_memo_round_trips_both_lanes_and_their_reasons() -> None:
    lanes = _lanes({"a": 1}, {"b": True})
    lanes.conservative.reasons["a"] = "why"
    memo = lane_memo(lanes)
    lanes.conservative.inputs["a"], lanes.optimistic.inputs["c"] = 2, 3
    lanes.conservative.reasons.clear()
    restore_lanes(lanes, memo)
    assert lanes.conservative.inputs == {"a": 1} and lanes.optimistic.inputs == {"b": True}
    assert lanes.conservative.reasons == {"a": "why"}


def test_tune_choices_drops_the_var_under_trial_from_the_memory_and_writes_through_the_given_writer() -> None:
    """D60's pop: a remembered value would be merged over the value under trial."""

    written: list[str] = []
    state = {"stance": None}

    def write(skeleton, lanes) -> None:
        merged = {**lanes.conservative.inputs, **(skeleton.tuned_choices or {})}
        state["stance"] = merged.get("bloodSandStance")
        written.append(state["stance"])

    pob = SimpleNamespace(stats=lambda keys: {k: 0.0 for k in keys} | {"CombinedDPS": 200.0 if state["stance"] == "BLOOD" else 100.0, "Life": 5000.0})
    skeleton = _skeleton(tuned_choices={"bloodSandStance": "SAND"})
    lanes = SimpleNamespace(choices={"bloodSandStance": ["SAND", "BLOOD"]}, conservative=SimpleNamespace(inputs={}, reasons={}),
                            optimistic=SimpleNamespace(inputs={}, reasons={}))

    assert tune_choices(pob, skeleton, lanes, objective=FLOORED, write=write, log=lambda _m: None) == {"bloodSandStance": "BLOOD"}
    assert written == ["SAND", "BLOOD", "BLOOD"] and skeleton.tuned_choices == {"bloodSandStance": "BLOOD"}


# -- layer 2: Judging through its ports ----------------------------------------------------------

from junkroan.optimizer.judging import (  # noqa: E402
    CASTABILITY,
    CASTABILITY_SCOPE,
    MOVE,
    RAMP,
    SELF_COST,
    TREE,
    VIEWS,
    UNSET,
    Judging,
    PobLanes,
    PobReads,
)


def _tagged(tag: str):
    """An installer that marks the objective it rewrote, so a test reads which refreshes reached a view."""

    def install(objective, *args, **kwargs):
        return objective.replace(maximize=f"{objective.maximize}+{tag}")

    return install


@pytest.fixture
def tagged(monkeypatch):
    """The three installers `Judging` applies, replaced by taggers (they are imported at call time)."""

    monkeypatch.setattr("junkroan.optimizer.ramp.with_ramp", lambda objective, **_changes: _tagged(RAMP)(objective))
    monkeypatch.setattr("junkroan.optimizer.self_cost.with_self_cost", lambda objective, _ctx: _tagged(SELF_COST)(objective))
    monkeypatch.setattr("junkroan.optimizer.castability.with_castability_floors",
                        lambda _pob, objective, *, context: _tagged(CASTABILITY)(objective))


def test_rejudge_reads_in_todays_order_self_cost_before_ramp(tagged) -> None:
    """`rejudge` (the full re-judge after a move): counts, lanes read and written, self-cost, castability only when the
    counts moved, ramp, holders. Self-cost before ramp (Q11; the opening does ramp first)."""

    calls: list = []
    judging, _trees, _gear = _judging(calls)
    judging.rejudge(SimpleNamespace())
    assert calls == ["minion_counts", "read", "write", "main_group", "self_cost", "ramp", "holders"]
    assert judging.main_gem_levels == (("Soulrend", 18),)

    calls.clear()
    judging, _trees, _gear = _judging(calls, counts_changed=True)
    judging.rejudge(SimpleNamespace())
    assert calls == ["minion_counts", "read", "write", "main_group", "self_cost", "castability", "ramp", "holders"]

    calls.clear()
    judging, _trees, _gear = _judging(calls)
    frozen = SimpleNamespace(read=False)
    judging.rejudge(SimpleNamespace(), castability=frozen)
    assert calls == ["minion_counts", "read", "write", "main_group", "self_cost", "ramp", "holders"], "a given context is not read again"
    assert judging.castability_context is frozen


def test_refresh_costs_prices_the_build_and_installs_a_given_castability_without_reading_it(tagged) -> None:
    calls: list = []
    judging, _trees, _gear = _judging(calls)
    assert judging.refresh_costs() is judging.objective
    assert calls == ["main_group", "self_cost"]
    calls.clear()
    frozen = SimpleNamespace(read=False)
    judging.refresh_costs(castability=frozen)
    assert calls == ["main_group", "self_cost"] and judging.castability_context is frozen


def test_q1_the_gear_view_follows_every_refresh(tagged) -> None:
    """Q1 (as amended by #34): the ramp, the self-cost and the castability reach the objective, both
    trees and the gear filler's copy alike."""

    calls: list = []
    judging, trees, gear = _judging(calls, counts_changed=True)
    judging.rejudge(SimpleNamespace())

    assert judging.objective.maximize == "dps+self_cost+castability+ramp"
    assert [tree.objective.maximize for tree in trees] == ["dps+self_cost+castability+ramp"] * 2
    assert gear.objective.maximize == "dps+self_cost+castability+ramp"
    assert VIEWS["gear"].follows == frozenset({SELF_COST, CASTABILITY, RAMP}) and not VIEWS["gear"].receives_holders


def test_q5_no_self_cost_before_the_opening_sets_the_main_tags(tagged) -> None:
    calls: list = []
    judging, trees, _gear = _judging(calls)
    judging.main_tags = judging_module.UNSET
    before = (judging.objective, trees[0].objective)
    judging.refresh_self_cost()
    assert calls == [] and (judging.objective, trees[0].objective) == before


def test_the_holders_go_to_the_attached_trees_as_copies_and_a_graphless_tree_gets_none(tagged) -> None:
    calls: list = []
    judging, trees, gear = _judging(calls)
    judging.post_holders(_lanes({}))
    assert calls == ["holders"]
    assert trees[0].proof_holders == trees[1].proof_holders == {7: {"usePowerCharges": (True, None)}}
    assert trees[0].proof_holders is not trees[1].proof_holders and gear.proof_holders == {}

    calls.clear()
    lone = _view(BASE)  # no graph: nothing to attribute, and PoB is not asked
    lone.proof_holders = {1: {}}
    judging.post_holders(_lanes({}), (lone,))
    assert calls == [] and lone.proof_holders == {}


def test_the_view_registry_cuts_what_run_builds_its_trees_with() -> None:
    assert VIEWS["tree_construction"].cut(BASE) == BASE.without("EffectiveMovementSpeedMod").without_sustain()
    assert VIEWS["tree"].cut(BASE) == BASE.without("EffectiveMovementSpeedMod")
    assert VIEWS["gear"].cut(BASE) is BASE
    for name in ("tree_construction", "tree"):
        assert VIEWS[name].follows == frozenset({SELF_COST, CASTABILITY, RAMP}) and VIEWS[name].receives_holders


def test_q6_a_tree_mark_restores_the_objective_the_trees_their_holders_and_the_gear(tagged) -> None:
    """Q6: the tree optimizer's restore hook puts back the objective, the trees' objectives and the
    holders and the gear filler's objective (#34), without a castability refold -- and neither
    the mark nor the restore asks PoB anything."""

    calls: list = []
    judging, trees, gear = _judging(calls)
    trees[0].proof_holders = {5: {"usePowerCharges": (True, None)}}
    mark = judging.mark(TREE)
    judging.refresh_castability(SimpleNamespace(read=False))
    trees[0].proof_holders = {}
    judging.restore(mark)

    assert calls == []
    assert judging.objective is BASE and trees[1].objective.maximize == "dps"
    assert trees[0].proof_holders == {5: {"usePowerCharges": (True, None)}}
    assert gear.objective.maximize == "dps", "the gear filler goes back with the trees (#34)"


def test_q2_a_castability_mark_refolds_the_frozen_costs_alone_without_a_read(tagged) -> None:
    """Q2: a judged revert whose snapshot is fresh gets the castability refold only: the snapshot's
    frozen context is installed into every view (the gear filler's too), nothing is derived."""

    calls: list = []
    judging, trees, gear = _judging(calls)
    frozen = SimpleNamespace(read=False)
    judging.castability_context = frozen
    mark = judging.mark(CASTABILITY_SCOPE)
    judging.castability_context = SimpleNamespace(read=True)
    judging.restore(mark)

    assert calls == [] and judging.castability_context is frozen
    assert gear.objective.maximize == "dps+castability" and judging.objective.maximize == "dps+castability"
    assert all(tree.objective.maximize.endswith("+castability") for tree in trees)


def test_a_move_mark_round_trips_everything_without_a_pob_call(tagged) -> None:
    calls: list = []
    judging, trees, gear = _judging(calls)
    judging.main_gem_levels = judging_module.UNSET
    judging.castability_context = None
    mark = judging.mark(MOVE)
    judging.rejudge(SimpleNamespace())  # a move: every view and the gem levels change
    calls.clear()
    judging.restore(mark)

    assert calls == []
    assert judging.objective is BASE and gear.objective is BASE
    assert [tree.objective for tree in trees] == [VIEWS["tree_construction"].cut(BASE), VIEWS["tree"].cut(BASE)]
    assert trees[0].proof_holders == {} and judging.main_gem_levels is judging_module.UNSET

    judging.rejudge(SimpleNamespace())
    judging.restore(mark, only=("objective",))
    # only the full objective is put back; the views (the gear filler's too, #34) keep the refresh
    assert judging.objective is BASE and gear.objective.maximize.endswith("+ramp") and trees[1].objective.maximize.endswith("+ramp")
    with pytest.raises(ValueError):
        judging.mark("everything")


def test_q9_a_trial_restores_the_xml_and_writes_no_view(tagged) -> None:
    """Q9: the enabler hook scores new lanes under the contexts the views already hold."""

    calls: list = []
    judging, trees, gear = _judging(calls)
    views = (judging.objective, trees[0].objective, trees[1].objective, gear.objective)
    with judging.trial():
        judging.lanes.write(None, judging.lanes.read())
    assert calls == ["snapshot", "read", "write", "restore xml"]
    assert (judging.objective, trees[0].objective, trees[1].objective, gear.objective) == views

    calls.clear()
    with pytest.raises(RuntimeError):
        with judging.trial():
            raise RuntimeError("a contract error inside the trial")
    assert calls == ["snapshot", "restore xml"], "the build comes back whatever happens inside"


# -- the views by role (#42 B1) -------------------------------------------------------------------


def test_attach_takes_the_roles_of_views_replaces_and_detaches() -> None:
    judging = Judging(_Lanes([]), _Reads([]), objective=BASE)
    assert judging.objective is BASE and judging.trees() == () and judging.view("tree") is None
    with pytest.raises(ValueError):
        judging.attach("tree_full", _view(BASE))
    first, second = _view(BASE), _view(BASE)
    judging.attach("tree", first)
    judging.attach("tree", second)
    assert judging.view("tree") is second and judging.trees() == (second,), "attaching a role again replaces it"
    judging.attach("tree", None)
    assert judging.view("tree") is None and judging.trees() == ()
    judging.attach("gear", None)  # detaching a role never attached is a no-op
    assert judging.view("gear") is None


def test_the_views_are_walked_in_views_order_whatever_the_attach_order(tagged) -> None:
    """followers, holder_targets, mark(TREE) and mark(MOVE) walk tree_construction, tree, gear --
    the order 1a produced from `trees=(construction tree, loop tree)` then the gear filler."""

    calls: list = []
    judging = Judging(_Lanes(calls), _Reads(calls), objective=BASE)
    construction, loop, gear = _view(BASE, graph=_Graph({})), _view(BASE), _view(BASE)
    judging.attach("gear", gear)
    judging.attach("tree", loop)
    judging.attach("tree_construction", construction)

    assert judging.trees() == (construction, loop)
    assert judging.followers(CASTABILITY) == [construction, loop, gear]
    assert judging.followers(RAMP) == [construction, loop, gear] == judging.followers(SELF_COST)
    assert judging.holder_targets() == (construction, loop)
    assert [tree for tree, _objective, _holders in judging.mark(TREE).parts["trees"]] == [construction, loop]
    move = judging.mark(MOVE)
    assert [tree for tree, _objective, _holders in move.parts["trees"]] == [construction, loop]
    assert move.parts["gear"] == (gear, BASE)


def test_cut_is_the_role_cut_of_the_full_objective_now() -> None:
    judging = Judging(_Lanes([]), _Reads([]), objective=BASE)
    for role in VIEWS:
        assert judging.cut(role) == VIEWS[role].cut(BASE)
    assert judging.cut("tree_construction") == BASE.without("EffectiveMovementSpeedMod").without_sustain()
    judging.objective = FLOORED
    assert judging.cut("tree") == FLOORED.without("EffectiveMovementSpeedMod") and judging.cut("gear") is FLOORED


# -- the new operations (#42 B2, B3, B4) -----------------------------------------------------------


class _FreshLanes(_Lanes):
    """A LaneSource whose every read derives new lanes, so a test can tell which read it got."""

    def read(self):
        super().read()
        return _lanes({"read": self.calls.count("read")})


@pytest.fixture
def main_gems(monkeypatch):
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {"soulrend": {"tag_keys": ["spell", "chaos"]}})


def test_q10_q11_open_writes_the_lanes_twice_then_ramp_before_self_cost_on_the_full_objective_only(tagged, main_gems) -> None:
    """Q10: the opening derives and writes the lanes twice; its contexts use the second lanes.
    Q11: ramp before self-cost. It writes the full objective only, never a view: a second `run` on
    the same pipeline must not refresh the previous run's views."""

    calls: list = []
    judging, trees, gear = _judging(calls)
    judging.lanes = _FreshLanes(calls)
    judging.main_tags = judging_module.UNSET
    views = (trees[0].objective, trees[1].objective, gear.objective)

    opening = judging.open(SimpleNamespace(main_link=["Soulrend", "Trauma"]))

    assert calls == ["read", "write", "read", "write", "ramp", "main_group", "self_cost"]
    assert opening == judging_module.Opening(opening.lanes, False) and opening.lanes.conservative.inputs == {"read": 2}
    assert judging.objective.maximize == "dps+ramp+self_cost"
    assert judging.main_tags == frozenset({"spell", "chaos"}) and judging.main_gem_levels == (("Soulrend", 18),)
    assert (trees[0].objective, trees[1].objective, gear.objective) == views
    assert trees[0].proof_holders == {} and trees[1].proof_holders == {}


def test_q11_open_contexts_wraps_ramp_before_self_cost_and_rejudge_the_other_way(tagged, main_gems) -> None:
    calls: list = []
    judging, _trees, _gear = _judging(calls)
    assert judging.open_contexts(SimpleNamespace(main_link=["Soulrend"]), _lanes({})) is False
    assert calls == ["ramp", "main_group", "self_cost"]
    assert judging.objective.maximize == "dps+ramp+self_cost"

    calls.clear()
    judging, _trees, _gear = _judging(calls)
    judging.rejudge(SimpleNamespace())
    assert calls.index("self_cost") < calls.index("ramp")
    assert judging.objective.maximize == "dps+self_cost+ramp"


def test_q4_relane_reads_and_writes_the_lanes_and_nothing_else(tagged) -> None:
    calls: list = []
    judging, trees, gear = _judging(calls)
    trees[0].proof_holders = {5: {"usePowerCharges": (True, None)}}
    before = (judging.objective, trees[0].objective, trees[1].objective, gear.objective, judging.main_gem_levels)

    lanes = judging.relane(SimpleNamespace())

    assert lanes is judging.lanes.lanes and calls == ["read", "write"], "no ramp, self-cost or holders read"
    assert (judging.objective, trees[0].objective, trees[1].objective, gear.objective, judging.main_gem_levels) == before
    assert trees[0].proof_holders == {5: {"usePowerCharges": (True, None)}}


def test_q7_lend_gives_the_view_back_its_own_objective_and_drops_a_refresh_made_meanwhile(tagged) -> None:
    calls: list = []
    judging, trees, gear = _judging(calls)
    lent = Objective(maximize="lent")
    own = trees[1].objective

    with judging.lend("tree", lent) as view:
        assert view is trees[1] and trees[1].objective is lent
        judging.refresh_castability(SimpleNamespace(read=False))
        assert trees[1].objective.maximize == "lent+castability", "the refresh reaches the lent objective"
    assert trees[1].objective is own, "and is dropped when the lend ends (Q7)"
    assert gear.objective.maximize == "dps+castability", "a view not lent keeps its refresh"

    with pytest.raises(RuntimeError):
        with judging.lend("gear", lent):
            assert gear.objective is lent
            raise RuntimeError("inside the lend")
    assert gear.objective.maximize == "dps+castability"

    judging.attach("tree", None)
    with pytest.raises(LookupError):
        with judging.lend("tree", lent):
            pass


def test_q8_recut_sets_every_attached_view_to_its_cut_of_the_full_objective(tagged) -> None:
    calls: list = []
    judging, trees, gear = _judging(calls)
    judging.rejudge(SimpleNamespace())  # every view follows the refresh, the gear filler's too (Q1, #34)
    assert gear.objective.maximize == judging.objective.maximize == "dps+self_cost+ramp"

    judging.recut()

    assert trees[0].objective == VIEWS["tree_construction"].cut(judging.objective)
    assert trees[1].objective == VIEWS["tree"].cut(judging.objective)
    assert gear.objective is judging.objective


def test_rejudger_routes_full_and_costs_only_and_passes_the_castability_context(tagged) -> None:
    import inspect

    calls: list = []
    judging, _trees, _gear = _judging(calls)
    port = judging.rejudger(SimpleNamespace())
    frozen = SimpleNamespace(read=False)

    assert port(full=True, castability_context=frozen) is judging.objective
    assert calls == ["minion_counts", "read", "write", "main_group", "self_cost", "ramp", "holders"]
    assert judging.castability_context is frozen

    calls.clear()
    other = SimpleNamespace(read=False)
    assert port(full=False, castability_context=other) is judging.objective
    assert calls == ["main_group", "self_cost"] and judging.castability_context is other

    calls.clear()
    port(full=False, castability_context=None)
    assert calls == ["main_group", "self_cost"] and judging.castability_context is other, "None installs nothing"

    # today's generator looks for these two names in the callback's signature; both are required
    params = inspect.signature(port).parameters
    assert [(name, param.kind, param.default) for name, param in params.items()] == [
        ("full", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty),
        ("castability_context", inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty)]


def test_refresh_main_group_reads_the_group_and_keeps_the_gem_levels() -> None:
    calls: list = []
    judging, _trees, _gear = _judging(calls)
    judging.main_gem_levels = judging_module.UNSET
    assert judging.refresh_main_group() == (["Soulrend"], False, (("Soulrend", 18),))
    assert calls == ["main_group"] and judging.main_gem_levels == (("Soulrend", 18),)


# -- the production adapters make today's PoB calls in today's order -------------------------------


class _RecordingPob:
    """Every surface the production adapters touch, each call recorded."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def config_inputs(self) -> dict:
        self.calls.append("config_inputs")
        return {"traumaStacks": 0}

    def set_config(self, **_kwargs) -> None:
        self.calls.append("set_config")

    def read_state(self) -> dict:
        self.calls.append("read_state")
        return {"skills_state": {"main_socket_group_id": 1, "socket_groups": [
            {"socket_group_id": 1, "gems": [{"gem_name": "Soulrend", "skill_id": "Soulrend", "level": 18}],
             "active_skill_entries": [{"triggered": False}]}]},
            "tree_state": {"user_allocated_node_ids": [], "mastery_effect_ids": []}}


def test_the_production_adapters_read_in_the_order_the_pipeline_did(monkeypatch) -> None:
    pob = _RecordingPob()
    lanes = SimpleNamespace(conservative=SimpleNamespace(inputs={}, reasons={}, proof_lines={}),
                            optimistic=SimpleNamespace(inputs={}, reasons={}), stack_caps={}, ailment_stack_caps={})

    def derive(_pob, prefer_rules=True, **_options):
        pob.calls.append("derive_config")
        return lanes

    monkeypatch.setattr("junkroan.optimizer.config_rules.derive_config", derive)
    monkeypatch.setattr("junkroan.optimizer.config_rules.build_text", lambda _pob, *_a, **_k: pob.calls.append("build_text") or "")
    monkeypatch.setattr("junkroan.optimizer.castability.castability_context",
                        lambda _pob, *, metrics=None: pob.calls.append("castability_context") or SimpleNamespace(mana_cost=None, life_cost=None))

    class _Skeleton:
        gem_counts: dict = {}
        main_link = ["Soulrend"]
        bandit, pantheon_major, pantheon_minor, user_config, tuned_choices = "None", "None", "None", {}, {}

        def refresh_minion_counts(self, _pob, **_kwargs):
            pob.calls.append("refresh_minion_counts")
            self.gem_counts = {"Soulrend": 2}  # the counts moved: the castability is read again

    judging = Judging(PobLanes(pob), PobReads(pob, gems=SimpleNamespace(level=18, quality=0, main_quality=0)))
    judging.objective, judging.main_tags = Objective(maximize="CombinedDPS"), frozenset({"chaos"})
    judging.attach("tree_construction", SimpleNamespace(objective=Objective(maximize="CombinedDPS"), proof_holders={}, graph=_Graph({})))
    judging.rejudge(_Skeleton())

    # derive, write (config_inputs, set_config), main group, self-cost text and Trauma stacks,
    # castability, the part name for the ramp, the tree state for the holders; the link PoB holds is read first (#550:
    # the counts are refreshed for it, not for the skeleton's own link)
    assert pob.calls == ["read_state", "refresh_minion_counts", "derive_config", "config_inputs", "set_config", "read_state", "build_text",
                         "config_inputs", "castability_context", "read_state", "read_state"]


def test_the_production_adapters_open_in_the_order_the_pipelines_opening_did(monkeypatch) -> None:
    """`run`'s opening (pipeline.py 414-436 at 7d9a2f6): derive + write twice, the part name for the
    ramp, the main group, then the self-cost's build text before its Trauma stacks."""

    pob = _RecordingPob()
    lanes = SimpleNamespace(conservative=SimpleNamespace(inputs={}, reasons={}, proof_lines={}),
                            optimistic=SimpleNamespace(inputs={}, reasons={}), stack_caps={}, ailment_stack_caps={})

    def derive(_pob, prefer_rules=True, **_options):
        pob.calls.append("derive_config")
        return lanes

    monkeypatch.setattr("junkroan.optimizer.config_rules.derive_config", derive)
    monkeypatch.setattr("junkroan.optimizer.config_rules.build_text", lambda _pob, *_a, **_k: pob.calls.append("build_text") or "")
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {"soulrend": {"tag_keys": ["chaos"]}})
    skeleton = SimpleNamespace(main_link=["Soulrend"], bandit="None", pantheon_major="None", pantheon_minor="None",
                               user_config={}, tuned_choices={})

    judging = Judging(PobLanes(pob), PobReads(pob, gems=SimpleNamespace(level=18, quality=0, main_quality=0)),
                      objective=Objective(maximize="CombinedDPS"))
    opening = judging.open(skeleton)

    assert pob.calls == ["derive_config", "config_inputs", "set_config", "derive_config", "config_inputs", "set_config",
                         "read_state", "read_state", "build_text", "config_inputs"]
    assert opening.lanes is lanes and opening.triggered is False
    assert judging.main_tags == frozenset({"chaos"}) and judging.main_gem_levels == (("Soulrend", 18),)


# -- BuildPipeline over Judging: the properties, the delegates and the quirks they keep ------------


def test_a_fresh_judging_holds_nothing_until_it_is_set_and_unset_forgets() -> None:
    """What a pipeline's judged attributes meant (properties over its judging context until #42
    S3c): nothing is set on a fresh judging context -- no objective, no main tags or gem levels (UNSET), no
    castability context, no view -- a value set is read back, and UNSET forgets it again."""

    judging = Judging(_Lanes([]), _Reads([]))
    assert judging.objective is UNSET and judging.main_tags is UNSET and judging.main_gem_levels is UNSET
    assert judging.castability_context is None and judging.trees() == () and judging.view("gear") is None
    tree, gear = _view(BASE), _view(BASE)
    judging.objective, judging.main_tags = BASE, frozenset({"spell"})
    judging.attach("tree_construction", tree)
    judging.attach("gear", gear)
    assert judging.objective is BASE and judging.trees() == (tree,) and judging.view("tree_construction") is tree and judging.view("gear") is gear
    assert judging.main_tags == frozenset({"spell"})
    judging.main_tags = UNSET
    assert judging.main_tags is UNSET and not judging.main_tags
    judging.main_gem_levels = (("Arc", 20),)
    judging.main_gem_levels = UNSET
    assert judging.main_gem_levels is UNSET


def test_q4_a_lane_write_touches_no_view_and_posts_no_holders() -> None:
    """Q4: `_finish` derives and writes the lanes through the judging context's lane write
    (`write_lanes`), which is a PoB write and nothing else -- no ramp, no self-cost, no holders
    reach the objective or a view."""

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.log = _ConfigPob(), lambda _m: None
    p.judging = pob_judging(p)
    tree, gear = _view(BASE), _view(BASE)
    tree.proof_holders = {5: {"usePowerCharges": (True, None)}}
    p.objective = BASE
    p.judging.attach("tree_construction", tree)
    p.judging.attach("gear", gear)
    p.judging.lanes.write(_skeleton(), _lanes({"usePowerCharges": False}))
    assert p.pob.calls == [("config_inputs",), ("set_config",)]
    assert p.objective is BASE and tree.objective is BASE and gear.objective is BASE
    assert tree.proof_holders == {5: {"usePowerCharges": (True, None)}}


def test_q6_the_tree_hooks_run_wires_restore_a_tree_mark_and_nothing_for_none(monkeypatch) -> None:
    """Q6 through the hooks `run` wires on its two trees (a construction-only run of the
    construction-rig harness): the snapshot hook takes a tree mark, the restore hook puts back the
    trees' objectives and holders and the gear filler's (`Judging.mark(TREE)` / `restore`,
    pinned on its own above), and a snapshot taken before the hook was wired (None) restores
    nothing."""

    from test_construction_rig import _run_construction

    _result, _pob, trees, loots = _run_construction(monkeypatch, "classic")
    wired = [tree for tree in trees if getattr(tree, "restore_context_hook", None) is not None]
    assert len(wired) == 2 and all(tree.snapshot_context_hook is not None for tree in wired)
    for tree in wired:
        tree.proof_holders = {5: {"usePowerCharges": (True, None)}}
    gear = loots[-1]
    objectives = [tree.objective for tree in wired]
    gear_at_mark = gear.objective
    mark = wired[0].snapshot_context_hook()

    moved = Objective(maximize="moved")
    for tree in wired:
        tree.objective, tree.proof_holders = moved, {}
    gear.objective = moved
    wired[0].restore_context_hook(None)  # a snapshot taken before the hook was wired restores nothing
    assert all(tree.objective is moved and tree.proof_holders == {} for tree in wired)

    wired[0].restore_context_hook(mark)
    assert all(tree.objective is objective for tree, objective in zip(wired, objectives))
    assert all(tree.proof_holders == {5: {"usePowerCharges": (True, None)}} for tree in wired)
    assert gear.objective is gear_at_mark, "the gear filler's objective goes back with the trees' (#34)"


def test_q9_the_enabler_hook_scores_new_lanes_under_the_old_contexts(monkeypatch) -> None:
    """Q9: a generator candidate is allocated, its lanes derived and written, and it is scored under
    the tree's objective as it stands -- no ramp, self-cost or holders refresh -- then the build
    comes back through the trial."""

    calls: list[str] = []

    class _Pob:
        def config_inputs(self):
            calls.append("config_inputs")
            return {}

        def export_xml(self):
            calls.append("export_xml")
            return "xml"

        def mutate_nodes(self, add=None, mastery_effects=None):
            calls.append("mutate_nodes")
            return {"added_node_ids": list(add or ())}

        def stats(self, keys):
            calls.append("stats")
            return {key: 0.0 for key in keys} | {"dps": 321.0}

        def load_xml(self, xml):
            calls.append(f"load_xml {xml}")

    lanes = _lanes({"usePowerCharges": True})

    class _RecordingLanes(PobLanes):
        """The session's lane source (its export and load are the trial's), the read and the write recorded."""

        def read(self):
            calls.append("derive_config")
            return lanes

        def write(self, _skeleton, _lanes) -> None:
            calls.append("apply_config")

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.log = _Pob(), lambda _m: None
    p.judging = pob_judging(p, lanes=_RecordingLanes(p.pob))
    tree = SimpleNamespace(objective=Objective(maximize="dps"), CHARGE_KINDS=("Power",), proof_holders={},
                           generator_kinds=lambda nodes, mastery: {"Power"})
    p.objective = BASE
    p.judging.attach("tree_construction", tree)
    views = (p.objective, tree.objective)

    score = p._value_with_enabled(_skeleton(), tree, SimpleNamespace(node_id=5, name="Charge node"), {})

    assert score.value == 321.0
    assert calls == ["config_inputs", "export_xml", "mutate_nodes", "derive_config", "apply_config", "stats", "load_xml xml"]
    assert (p.objective, tree.objective) == views and tree.proof_holders == {}


def test_q10_q11_the_opening_derives_and_writes_twice_then_ramp_before_self_cost(monkeypatch) -> None:
    """Q10: the opening derives and writes the lanes twice (a cap can depend on inputs the first
    write sets). Q11: it wraps the ramp before the self-cost, the other way round from `rejudge`."""

    import junkroan.optimizer.pipeline as pipeline_module
    from test_construction_rig import _Loot, _Pob, _Skeleton, _Tree, _derived

    events: list[str] = []
    monkeypatch.setattr(pipeline_module, "TreeOptimizer", _Tree)
    monkeypatch.setattr(pipeline_module, "LootGear", _Loot)
    monkeypatch.setattr(pipeline_module, "objective_for", lambda _rails, _skill, objective, **_kwargs: objective)
    monkeypatch.setattr("junkroan.optimizer.ramp.context_changes", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("junkroan.optimizer.ramp.with_ramp", lambda objective, **_kwargs: events.append("ramp") or objective)
    monkeypatch.setattr("junkroan.optimizer.self_cost.context_for", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("junkroan.optimizer.self_cost.with_self_cost", lambda objective, _context: events.append("self_cost") or objective)
    monkeypatch.setattr(pipeline_module, "self_cost_tree_patterns", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(pipeline_module, "encode_import_code", lambda xml: f"code:{xml}")
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {})
    monkeypatch.setattr("junkroan.optimizer.config_rules.build_text", lambda *_a, **_k: "")

    rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), gear=SimpleNamespace(construction_best_of_n=600),
                            forbidden_node_text=(), utility_max_groups=0, attribute_plus30_nodes_max=1)
    pipeline = BuildPipeline(_Pob(), rails, objective=Objective(maximize="CombinedDPS"))
    pipeline._rails_identity = lambda _skeleton: None
    judging = pipeline.judging

    class _EventLanes(PobLanes):
        def read(self):
            events.append("derive")
            return _derived()

        def write(self, _skeleton, _lanes) -> None:
            events.append("write")

    judging.lanes = _EventLanes(pipeline.pob)
    judging.refresh_castability = lambda *_args, **_kwargs: None
    judging.post_holders = lambda *_args, **_kwargs: events.append("holders")
    judging.rejudge = lambda *_args, **_kwargs: events.append("reconfigure") or judging.objective
    judging.reads.main_group = lambda: ([], False, ())
    pipeline._rebuild_tree = lambda _skeleton, _tree, _points: "rebuilt"

    pipeline.run(_Skeleton(), tree_points=10, construction_only=True)

    assert events[:7] == ["derive", "write", "derive", "write", "ramp", "self_cost", "holders"]
    trees = pipeline.judging.trees()
    assert trees[0].objective == Objective(maximize="CombinedDPS").without("EffectiveMovementSpeedMod").without_sustain()
    assert trees[1].objective == Objective(maximize="CombinedDPS").without("EffectiveMovementSpeedMod")
    assert pipeline.judging.view("gear") is _Loot.instances[-1]
