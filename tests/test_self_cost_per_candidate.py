"""Self-costs PoB does not count are judged per candidate, not once (the user's reading of
2026-09-18, rules 4 and 19): the Chaos Mastery the tree took seven times on soulrend s1 and the
Sacrifice support a pick added to poison_spark were both free in the numbers that judged them.

No PoB: the tree side is the graph's own text, the context side is stats in and a number out.
"""

from types import SimpleNamespace

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.judging import UNSET
from junkroan.optimizer.objective import DerivedStat, Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.self_cost import STAT_NAME, context_for, gem_self_costs, self_cost_per_second, tree_patterns
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.optimizer.tree_optimizer import TreeOptimizer

from judging_fakes import pob_judging, rebind_session

CHAOS = frozenset({"chaos", "spell"})
LINE = "Lose 10% of Life and Energy Shield when you use a Chaos Skill"


def test_the_tree_never_proposes_a_self_cost_line_of_the_main_skills_kind() -> None:
    import re

    graph = TreeGraph.load()
    patterns = tree_patterns(graph, CHAOS)
    assert len(patterns) == 1 and re.fullmatch(patterns[0], LINE), patterns
    assert tree_patterns(graph, frozenset({"fire", "spell"})) == (), "another skill pays nothing for a chaos line"

    opt = TreeOptimizer(None, Rails.load().objective(), graph=graph)
    _nodes, effects = opt.forbid_text(patterns)
    chaos_effects = {eid for node in graph.nodes.values() for eid, stats in node.mastery_effects or () if any(LINE.lower() in s.lower() for s in stats)}
    assert effects >= len(chaos_effects) >= 1, "the Chaos Mastery effect is off the table (counted once per mastery node carrying it)"
    assert chaos_effects <= opt.excluded_mastery_effects


def test_a_support_that_pays_life_per_use_is_a_self_cost() -> None:
    """Sacrifice sacrifices 20% of current life on every use; PoB turns that life into added chaos
    damage and into no cost at all (mechanics/self_cost_gems.json)."""

    assert gem_self_costs()["sacrifice"] == ("LifeUnreserved", 0.2)
    ctx = context_for("", frozenset({"lightning", "spell"}), main_triggered=False, main_gems=["Spark", "Sacrifice", "Cruelty"])
    assert dict(ctx.fractions) == {"LifeUnreserved": 0.2}
    # poison_spark s1: 4,333 life at 5.35 casts per second
    assert abs(self_cost_per_second({"LifeUnreserved": 4333, "Speed": 5.35}, ctx) + 4636.31) < 0.01
    assert context_for("", frozenset(), main_triggered=True, main_gems=["Spark", "Sacrifice"]).fractions == ()
    assert context_for("", frozenset(), main_triggered=False, main_gems=["Spark", "Cruelty"]).fractions == ()


class _StatePob:
    """Enough PoB for `build_text` and the main-group readback."""

    def __init__(self, gems, text_lines=(), triggered=False):
        self.gems, self.text_lines, self.triggered = list(gems), list(text_lines), triggered

    def read_state(self):
        return {
            "skills_state": {"main_socket_group_id": 1, "socket_groups": [
                {"socket_group_id": 1, "gems": [{"gem_name": g, "enabled": True} for g in self.gems],
                 "active_skill_entries": [{"triggered": self.triggered}]}]},
            "tree_state": {"user_allocated_node_ids": [], "mastery_effect_ids": []},
            "gear_slots": {"slots": {"Gloves": {"item": {"explicit_affixes": list(self.text_lines)}}}},
        }


def _pipeline(pob, tags=CHAOS):
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p.log = lambda _m: None
    p.judging = pob_judging(p)
    p.objective = Rails.load().objective()
    p.judging.main_tags = tags
    p.judging.attach("tree_construction", SimpleNamespace(objective=Rails.load().objective()))
    return p


def _loss(objective, stats):
    return objective.derived_values(stats)[STAT_NAME]


def test_the_context_is_re_derived_from_the_build_as_it_now_stands() -> None:
    """A line the tree takes later, and a support a pick adds later, are in the numbers that judge
    the next move -- the whole point: the context used to be computed once on the empty build."""

    stats = {"Life": 4000, "EnergyShield": 500, "LifeUnreserved": 4000, "Speed": 4.0}
    p = _pipeline(_StatePob(["Soulrend", "Efficacy"]))
    p.judging.refresh_self_cost()
    assert _loss(p.objective, stats) == 0.0

    p.pob = _StatePob(["Soulrend", "Efficacy"], text_lines=[LINE])  # the mastery is taken
    rebind_session(p)
    p.judging.refresh_self_cost()
    assert abs(_loss(p.objective, stats) + 0.1 * (4000 + 500) * 4.0) < 1e-9
    assert abs(_loss(p.judging.trees()[0].objective, stats) + 1800.0) < 1e-9, "the tree is judged under it too"

    p.pob = _StatePob(["Soulrend", "Sacrifice"], text_lines=[LINE])  # and a life-paying support beside it
    rebind_session(p)
    p.judging.refresh_self_cost()
    assert abs(_loss(p.objective, stats) + (1800.0 + 0.2 * 4000 * 4.0)) < 1e-9

    p.pob = _StatePob(["Soulrend", "Sacrifice"], text_lines=[LINE], triggered=True)  # Spellslinger: the player uses nothing
    rebind_session(p)
    p.judging.refresh_self_cost()
    assert _loss(p.objective, stats) == 0.0


def test_refreshing_before_the_main_skill_is_known_does_nothing() -> None:
    p = _pipeline(_StatePob(["Soulrend"]))
    p.judging.main_tags = UNSET
    before = p.objective
    p.judging.refresh_self_cost()
    assert p.objective is before


class _PickPob:
    """A support link whose PoB output is deliberately blind to life paid per use."""

    def __init__(self, link: list[str], values: dict[str, float]) -> None:
        self.link, self.values = list(link), dict(values)

    def set_skills(self, *, main_link, **_kw) -> None:
        self.link = list(main_link)

    def stats(self, keys) -> dict:
        return {key: 0.0 for key in keys} | {
            "CombinedDPS": self.values[self.link[1] if len(self.link) > 1 else ""], "Life": 100.0, "NetLifeRegen": 0.0,
        }


def _pick_generator(pob: _PickPob, objective: Objective) -> SkeletonGenerator:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0, main_link_max=5, other_link_max=4))
    gen.objective = objective
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    return gen


def _self_cost_objective(pob: _PickPob, costs: dict[str, float]) -> Objective:
    return Objective(
        maximize="CombinedDPS",
        relations=((f"NetLifeRegen+{STAT_NAME}", "Life", 0.0, "Life"),),
        derived=(DerivedStat(STAT_NAME, (), lambda _stats, _objective: costs.get(pob.link[1], 0.0)),),
    )


def test_rejudge_rejects_a_damage_pick_that_adds_self_cost() -> None:
    """The old pick accepted Sacrifice on its PoB damage before this derived cost refreshed."""

    pob = _PickPob(["Spark", "Faster Projectiles"], {"Faster Projectiles": 100.0, "Sacrifice": 200.0, "Efficacy": 120.0})
    costs = {"Sacrifice": -200.0}
    gen = _pick_generator(pob, _self_cost_objective(pob, costs))
    gen.legal_supports = lambda _skeleton: ["Sacrifice", "Efficacy"]
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=list(pob.link))
    modes: list[bool] = []

    def reconfigure(*, full: bool = True, castability_context=None) -> Objective:
        modes.append(full)
        return _self_cost_objective(pob, costs)

    changes = gen.rejudge_picks(skeleton, reconfigure=reconfigure)

    assert skeleton.main_link == ["Spark", "Efficacy"]
    assert [(change["was"], change["now"]) for change in changes] == [("Faster Projectiles", "Efficacy")]
    assert False in modes and modes[-1] is True
    assert gen.objective.score(pob.stats(gen.objective.stat_keys)).feasible


def test_an_infeasible_pick_only_keeps_a_violation_lowering_candidate() -> None:
    """A higher-DPS pick cannot deepen an existing derived-stat violation."""

    pob = _PickPob(["Spark", "Faster Projectiles"], {"Faster Projectiles": 200.0, "Cruelty": 300.0, "Efficacy": 90.0})

    def objective() -> Objective:
        shares = {"Faster Projectiles": 0.2, "Cruelty": 0.1, "Efficacy": 0.3}
        return Objective(maximize="CombinedDPS", floors={"MoMCastsAfterMaxHit": 0.4},
                         derived=(DerivedStat("MoMCastsAfterMaxHit", (), lambda _stats, _objective: shares[pob.link[1]]),))

    gen = _pick_generator(pob, objective())
    gen.legal_supports = lambda _skeleton: ["Cruelty", "Efficacy"]
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=list(pob.link))

    def reconfigure(*, full: bool, castability_context) -> Objective:
        return objective()

    changes = gen.rejudge_picks(skeleton, reconfigure=reconfigure)

    assert skeleton.main_link == ["Spark", "Efficacy"]
    assert [(change["was"], change["now"]) for change in changes] == [("Faster Projectiles", "Efficacy")]
    assert abs(gen.objective.score(pob.stats(gen.objective.stat_keys)).violation - 0.1) < 1e-9


def test_support_pick_scores_a_life_costing_candidate_after_its_objective_refreshes() -> None:
    """The construction pick follows the same full-objective rule as the re-judge."""

    pob = _PickPob(["Spark"], {"": 100.0, "Sacrifice": 200.0, "Efficacy": 120.0})
    costs = {"Sacrifice": -200.0}

    def objective() -> Objective:
        support = pob.link[1] if len(pob.link) > 1 else ""
        return Objective(
            maximize="CombinedDPS",
            relations=((f"NetLifeRegen+{STAT_NAME}", "Life", 0.0, "Life"),),
            derived=(DerivedStat(STAT_NAME, (), lambda _stats, _objective: costs.get(support, 0.0)),),
        )

    gen = _pick_generator(pob, objective())
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=["Spark"])

    def reconfigure(*, full: bool, castability_context) -> Objective:
        return objective()

    gen.pick_supports(skeleton, n_supports=1, legal=["Sacrifice", "Efficacy"], reconfigure=reconfigure)

    assert skeleton.main_link == ["Spark", "Efficacy"]
    assert gen.objective.score(pob.stats(gen.objective.stat_keys)).feasible


def test_reconfigure_calls_the_callback_with_exactly_full_and_castability_context() -> None:
    """`SkeletonGenerator._reconfigure` calls the pipeline's `Rejudge` port through one fixed
    signature (#42 S2): every call carries exactly the keywords `full` and `castability_context`,
    with `castability_context` the generator's own at the time of the call -- never guessed
    per callback with `inspect.signature`."""

    pob = _PickPob(["Spark", "Faster Projectiles"], {"Faster Projectiles": 100.0, "Sacrifice": 200.0, "Efficacy": 120.0})
    costs = {"Sacrifice": -200.0}
    gen = _pick_generator(pob, _self_cost_objective(pob, costs))
    gen.legal_supports = lambda _skeleton: ["Sacrifice", "Efficacy"]
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=list(pob.link))

    calls: list[dict] = []

    def reconfigure(*, full: bool, castability_context) -> Objective:
        calls.append({"full": full, "castability_context": castability_context, "generators_own": gen.castability_context})
        return _self_cost_objective(pob, costs)

    gen.rejudge_picks(skeleton, reconfigure=reconfigure)

    assert calls, "the callback must be invoked at least once over the run"
    for call in calls:
        assert set(call) - {"generators_own"} == {"full", "castability_context"}
        assert call["castability_context"] is call["generators_own"], "castability_context must be the generator's own at the time of the call"
