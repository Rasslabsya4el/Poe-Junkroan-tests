"""D71: the picks move can give reservation back, without PoB.

The defect (rules-smoke run 20260918-0723, stormbrand s3): the tree took Mind over Matter in loop
pass 1, `MoMUnreservedShare` (the rule #608 replaced by MoMCastsAfterMaxHit) landed at 0.324 against a floor of 0.40, and the build stayed
infeasible for nine more passes -- no move of the loop can lower mana reservation. The tree moves
only allocate and deallocate nodes, the gear moves roll items, and the picks swap one utility gem
for another of the same family but never drop a group.

The fake PoB here is a build made of socket groups: each group reserves some mana and pays some
damage, and `ManaUnreserved` follows which groups the last `set_skills` left enabled -- which is
exactly the witness the move reads, so a group that reserves nothing is invisible to it whatever
its name says.
"""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.keystone_floors import mom_casts_stat
from junkroan.optimizer.objective import Objective, Score, better_score
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton, SocketGroup

# Mind over Matter is on (`sharedMindOverMatter` 40, no Eldritch Battery, a max hit of 1,000, ManaCost 100):
# the keystone drains 0.4 x 0.8 x 1,000 = 320 mana, so MoMCastsAfterMaxHit is (ManaUnreserved - 320) / 100,
# floored at 3 by the rails (rails_default.json, #608)
MOM = Objective(maximize="CombinedDPS", floors={"MoMCastsAfterMaxHit": 3.0}, derived=(mom_casts_stat(),))
# ... and a floor no drop can ever buy: what the build is short of when reservation is not the problem
LIFE = Objective(maximize="CombinedDPS", floors={"Life": 4000.0}, derived=(mom_casts_stat(),))

MANA = 1000.0
BASE = 1000.0
LIFE_POOL = 3000.0


class _Pob:
    """`groups`: gem name -> (mana reserved, damage paid). The enabled set is whatever the last
    `set_skills` wrote, so the build really is the one the move applied."""

    def __init__(self, groups: dict[str, tuple[float, float]]) -> None:
        self.groups = dict(groups)
        self.enabled = set(groups)
        self.applied: list[tuple[str, ...]] = []  # the enabled set of every set_skills, in order

    def set_skills(self, *, main_link, slot, level, quality, main_quality, main_part, extra_groups,
                   main_counts=None, main_minion_skills=None, main_instance_counts=(),
                   main_disabled_indices=()) -> None:
        # the per-index count / disabled state the skills writer now sends (a zero-fielded minion
        # is `enabled=False` with count 1): this fake judges only which groups are enabled
        self.enabled = {g["gems"][0]["gem_name"] for g in extra_groups if g.get("enabled", True) and g["gems"]}
        self.applied.append(tuple(sorted(self.enabled)))

    def stats(self, keys) -> dict:
        reserved = sum(self.groups[n][0] for n in self.enabled)
        value = BASE + sum(self.groups[n][1] for n in self.enabled)
        return {k: 0.0 for k in keys} | {
            "CombinedDPS": value, "Mana": MANA, "ManaUnreserved": MANA - reserved,
            "LifeUnreserved": 0.0, "Life": LIFE_POOL, "sharedMindOverMatter": 40.0, "ManaCost": 100.0, "PhysicalMaximumHitTaken": 1000.0,
        }


def _generator(pob: _Pob, *, objective: Objective = MOM, log=None) -> SkeletonGenerator:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0))
    gen.objective = objective
    gen.log = log or (lambda _m: None)
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    return gen


def _skeleton(names) -> Skeleton:
    # a main skill PoB counts once (no minions, no brands): `refresh_minion_counts` needs no PoB call
    groups = [SocketGroup(gems=list(n) if isinstance(n, (list, tuple)) else [n], slot="Helmet",
                          label=(n[0] if isinstance(n, (list, tuple)) else n), picked=True) for n in names]
    return Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball"], extra_groups=groups)


def _casts(pob: _Pob, objective: Objective = MOM) -> float:
    return objective.derived_values(pob.stats(objective.stat_keys))["MoMCastsAfterMaxHit"]


# -- (a) infeasible on a reservation floor: the group whose removal buys it is dropped ------------


def test_an_infeasible_build_drops_the_reserving_group_that_restores_feasibility() -> None:
    """Determination reserves 700 of 1,000 mana (300 left, 0 casts after the 320 the keystone drains, against the floor of 3) and pays 200
    damage; the movement skill beside it reserves nothing. Feasibility comes first, so the aura goes
    even though the build loses damage with it -- and the log line names the floor the drop bought."""

    pob = _Pob({"Determination": (700.0, 200.0), "Flame Dash": (0.0, 10.0)})
    logs: list[str] = []
    gen = _generator(pob, log=logs.append)
    sk = _skeleton(["Determination", "Flame Dash"])

    before = gen.objective.score(pob.stats(MOM.stat_keys))
    assert not before.feasible and round(_casts(pob), 3) == 0.0 and before.value == 1210.0

    change = gen.drop_reserving_group(sk)

    assert change is not None and change["what"] == "dropped" and change["was"] == "Determination"
    assert (change["before"], change["after"]) == (1210.0, 1010.0)
    assert change["text"] == "dropped Determination (MoMCastsAfterMaxHit 0.000 -> 6.800, -16.5%)"
    assert logs == ["picks: dropped Determination (MoMCastsAfterMaxHit 0.000 -> 6.800, -16.5%)"]
    # the group stays in the build, disabled (buff_gems' rule): nothing is ever removed
    assert [g.gems[0] for g in sk.extra_groups if not g.enabled] == ["Determination"] and len(sk.extra_groups) == 2
    assert pob.enabled == {"Flame Dash"} and gen.objective.score(pob.stats(MOM.stat_keys)).feasible


def test_a_group_that_reserves_nothing_is_never_a_candidate() -> None:
    """The move reads PoB's reservation, not gem names: a group that hands no mana back when it is
    disabled is not a candidate, even when dropping it would raise the number. Here the build is
    short of a floor no drop can buy (life), and the only group reserves nothing."""

    pob = _Pob({"Purity of Elements": (0.0, -200.0)})  # a group PoB charges no reservation for
    gen = _generator(pob, objective=LIFE)
    sk = _skeleton(["Purity of Elements"])

    assert not gen.objective.score(pob.stats(LIFE.stat_keys)).feasible  # 3,000 life against a floor of 4,000
    assert gen.drop_reserving_group(sk) is None
    assert all(g.enabled for g in sk.extra_groups) and pob.enabled == {"Purity of Elements"}
    assert pob.applied[-1] == ("Purity of Elements",), "the trial was measured and the build put back"


def test_a_drop_that_buys_no_floor_is_not_kept() -> None:
    """A reserving group is a candidate, not a verdict: dropping this aura leaves the missed floor
    exactly where it was (the build is short of life, not of mana) and costs 200 damage, so the
    Score falls and the group stays on."""

    pob = _Pob({"Herald of Ash": (100.0, 200.0)})  # reserves, and the mana was never the problem
    gen = _generator(pob, objective=LIFE)
    sk = _skeleton(["Herald of Ash"])

    assert gen.drop_reserving_group(sk) is None
    assert all(g.enabled for g in sk.extra_groups) and pob.enabled == {"Herald of Ash"}


# -- (b) a feasible build: the move is inert ------------------------------------------------------


def test_a_feasible_build_tries_nothing() -> None:
    """Reservation is paid back to buy a floor, never to buy damage: on a build that misses nothing
    the move applies no trial at all, so it costs not one PoB call."""

    pob = _Pob({"Determination": (300.0, -300.0)})  # dropping it would raise the value by 30%
    gen = _generator(pob)
    sk = _skeleton(["Determination"])

    assert gen.objective.score(pob.stats(MOM.stat_keys)).feasible
    assert gen.drop_reserving_group(sk) is None
    assert pob.applied == [] and all(g.enabled for g in sk.extra_groups)


# -- (c) two reserving groups: the better Score wins, one per pass --------------------------------


def test_the_better_of_two_drops_is_kept_and_only_one_per_pass() -> None:
    """Both auras can go and either drop restores feasibility, so the Score ordering decides on the
    value: Herald of Ash, because the build keeps Determination's 200 damage. One drop per pass --
    the pass that follows judges the build this one left behind."""

    pob = _Pob({"Determination": (300.0, 200.0), "Herald of Ash": (250.0, 100.0)})
    gen = _generator(pob)
    sk = _skeleton(["Determination", "Herald of Ash"])

    assert round(_casts(pob), 3) == 1.3  # 550 of 1,000 reserved: 450 - 320 = 130 mana, against the floor of 3 casts

    change = gen.drop_reserving_group(sk)

    assert change is not None and change["was"] == "Herald of Ash"
    assert (change["before"], change["after"]) == (1300.0, 1200.0)
    assert pob.enabled == {"Determination"}
    assert [g.gems[0] for g in sk.extra_groups if not g.enabled] == ["Herald of Ash"], "one drop, not both"
    # both groups were tried, one at a time, and the build was put back between the trials
    assert pob.applied[:2] == [("Herald of Ash",), ("Determination",)]


def test_a_multi_gem_group_is_named_whole() -> None:
    """A socket group is dropped whole, so the log names it whole: the author's link on stormbrand s3
    is Wrath + More Duration + Smite, and "dropped Wrath" would hide the two gems that went with it."""

    pob = _Pob({"Wrath": (700.0, 200.0)})
    logs: list[str] = []
    gen = _generator(pob, log=logs.append)
    sk = _skeleton([["Wrath", "More Duration", "Smite"]])

    change = gen.drop_reserving_group(sk)

    assert change is not None and change["was"] == "Wrath + More Duration + Smite"
    assert logs == ["picks: dropped Wrath + More Duration + Smite (MoMCastsAfterMaxHit 0.000 -> 6.800, -16.7%)"]


def test_a_drop_rejected_under_re_derived_lanes_is_put_back() -> None:
    """The verification every pick goes through (D45): the winner is applied, the lanes are derived
    again, and a drop that only won under the old proof is re-enabled."""

    pob = _Pob({"Determination": (700.0, 200.0)})
    logs: list[str] = []
    gen = _generator(pob, log=logs.append)
    sk = _skeleton(["Determination"])

    def reconfigure(*, full: bool, castability_context) -> None:  # the honest lanes take the mana away again (a jewel's own reservation)
        pob.enabled = {"Determination"}

    assert gen.drop_reserving_group(sk, reconfigure=reconfigure) is None
    assert all(g.enabled for g in sk.extra_groups)
    assert [m for m in logs if "rejected under re-derived lanes" in m]


# -- the rule itself ------------------------------------------------------------------------------


def test_better_score_is_feasibility_first_then_min_gain() -> None:
    """The one acceptance rule the loop, the re-judged picks and the drop all share."""

    infeasible = Score(neg_violation=-0.1, value=2000.0)
    feasible = Score(neg_violation=0.0, value=1000.0)
    assert better_score(feasible, infeasible, min_gain=0.005), "a drop that buys the floor wins at half the value"
    assert not better_score(infeasible, feasible, min_gain=0.005)
    assert not better_score(Score(neg_violation=0.0, value=1004.0), feasible, min_gain=0.005), "below min_gain"
    assert better_score(Score(neg_violation=0.0, value=1005.0), feasible, min_gain=0.005)
    assert better_score(Score(neg_violation=-0.05, value=1.0), infeasible, min_gain=0.005), "less infeasible, any value"


def test_a_floor_bought_by_killing_the_build_is_not_bought() -> None:
    """A floor that is met because the skill stopped working is not met (stormbrand-s1, plan B's
    replay bench: a region challenge reached FullDPS 0 at violation 0 and was kept)."""

    infeasible = Score(neg_violation=-0.012, value=100.0)
    dead_but_feasible = Score(neg_violation=0.0, value=0.0)
    assert not better_score(dead_but_feasible, infeasible, min_gain=0.005)
    assert not better_score(Score(neg_violation=0.0, value=-5.0), infeasible, min_gain=0.005), "a negative value either"

    # a build that already has nothing is still judged by the old rule: anything is an improvement
    nothing = Score(neg_violation=-0.5, value=0.0)
    assert better_score(Score(neg_violation=-0.5, value=50.0), nothing, min_gain=0.005)
    assert better_score(Score(neg_violation=0.0, value=0.0), nothing, min_gain=0.005), "less infeasible, still nothing"

    # feasible against feasible is untouched
    feasible = Score(neg_violation=0.0, value=1000.0)
    assert better_score(Score(neg_violation=0.0, value=1005.0), feasible, min_gain=0.005)
    assert not better_score(Score(neg_violation=0.0, value=1004.0), feasible, min_gain=0.005)
