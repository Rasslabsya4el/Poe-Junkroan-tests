"""#1153: every build carries a movement spell and a movement skill, never Smoke Mine. PoB-free (fakes).

The owner's rule: slot `movement_spell` is one of Dash, Frostblink, Flame Dash; slot `movement_skill` is Shield
Charge (only with a shield in Weapon 2) or Leap Slam, linked with Faster Attacks and Momentum when the build has
the linked sockets for it (3-link), else alone. Smoke Mine and Lightning Warp are refused in both slots. A build
with a Staff in Weapon 1 whose Leap Slam "Attack Time" is >= `movement_skill_skip_attack_time_s` skips the
skill. Which member of a slot is PoB's call (the fake PoB below prices Smoke Mine highest on purpose). The pair
does not count against `utilities.max_groups`. Rail tests with the trace counter at the PoB boundary
(`generated(x) > 0 and evaluated(x) > 0`, `evaluated(forbidden) = 0`), D113 kind A.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton, SocketGroup

# the fake PoB's price of each gem (CombinedDPS added); Smoke Mine and Lightning Warp are the tempting best
VALUE = {
    "Dash": 5.0, "Frostblink": 7.0, "Flame Dash": 6.0, "Smoke Mine": 100.0, "Lightning Warp": 90.0,
    "Leap Slam": 3.0, "Shield Charge": 4.0, "Whirling Blades": 80.0,
    "Faster Attacks": 0.5, "Momentum": 0.5, "Haste": 5.0, "Determination": 5.0, "Grace": 5.0,
}
FORBIDDEN = ("Smoke Mine", "Lightning Warp")


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


class _Pob:
    """The PoB boundary: every stats read sees the gems linked at that moment and records them."""

    def __init__(self, skeleton: Skeleton) -> None:
        self.skeleton = skeleton
        self.seen: set[str] = set()

    def stats(self, keys) -> dict:
        gems = [g for grp in self.skeleton.extra_groups if grp.enabled for g in grp.gems]
        self.seen.update(gems)
        return {key: 0.0 for key in keys} | {"CombinedDPS": 100.0 + sum(VALUE.get(g, 0.0) for g in gems), "Life": 100.0, "TotalEHP": 1.0, "EnemyCurseLimit": 4.0}


def _gen(skeleton: Skeleton, *, shield: bool = True, weapon1: str = "One Handed Sword", attack_time: float = 0.8,
         linked_slot: str | None = None, aura_pool: tuple[str, ...] = ()) -> tuple[SkeletonGenerator, _Pob]:
    pob = _Pob(skeleton)
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    rails = Rails.load()
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=4, movement_skill_required=True, movement=rails.movement)
    gen.objective = Objective(maximize="CombinedDPS")
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    gen._set_main_link = lambda *_a, **_k: None
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    gen._weapon1_type = lambda: weapon1
    gen._weapon2_is_shield = lambda: shield
    gen._skill_attack_time = lambda _name: attack_time
    gen._linked_slot = lambda _skeleton, _n: linked_slot
    real = SkeletonGenerator.utility_candidates
    gen.utility_candidates = lambda sk: {"movement": real(gen, sk)["movement"], "aura": list(aura_pool)}
    return gen, pob


def _skeleton(*carried: str) -> Skeleton:
    return Skeleton(class_name="Marauder", ascendancy="Juggernaut", main_link=["Cleave"],
                    extra_groups=[SocketGroup(gems=[name], slot="Helmet", label=name) for name in carried])


def _counter(cls: str) -> tuple[int, int]:
    row = TRACE.considered()["picks"].get(cls) or {"generated": 0, "evaluated": 0}
    return row["generated"], row["evaluated"]


def _run(gen: SkeletonGenerator, skeleton: Skeleton, max_groups: int = 4) -> list[SocketGroup]:
    added = gen.pick_utilities(skeleton, max_groups=max_groups)
    TRACE.flush("picks")
    return added


def test_the_allowed_lists_live_in_the_rails_file() -> None:
    mv = Rails.load().movement
    assert set(mv.spell) == {"Dash", "Frostblink", "Flame Dash"}
    assert set(mv.skill) == {"Shield Charge", "Leap Slam"}
    assert set(mv.forbidden) == set(FORBIDDEN)
    assert mv.shield_only == ("Shield Charge",)
    assert mv.skill_links == ("Faster Attacks", "Momentum") and mv.skill_links_for == ("Leap Slam",) and mv.skill_link_sockets == 3
    assert mv.skill_skip_weapon == "Staff" and mv.skill_skip_attack_time_s == 1.0


def test_smoke_mine_and_lightning_warp_are_refused_in_both_slots() -> None:
    skeleton = _skeleton()
    gen, pob = _gen(skeleton)

    added = _run(gen, skeleton)

    names = [g.gems[0] for g in added]
    assert names == ["Frostblink", "Shield Charge"], names  # PoB's pick inside each slot, 7 > 6 > 5 and 4 > 3
    assert not pob.seen & set(FORBIDDEN), "PoB never sees a refused gem"
    assert "Whirling Blades" not in pob.seen, "an attack travel skill outside both lists is not offered either"
    for name in FORBIDDEN:
        assert _counter(f"gem:{name}") == (0, 0), name
    assert _counter("movement-forbidden") == (0, 0)
    generated, evaluated = _counter("movement-spell")
    assert generated > 0 and evaluated > 0, (generated, evaluated)
    generated, evaluated = _counter("movement-skill")
    assert generated > 0 and evaluated > 0, (generated, evaluated)


def test_a_build_with_dash_only_gets_a_movement_skill_and_no_second_spell() -> None:
    skeleton = _skeleton("Dash")
    gen, pob = _gen(skeleton, shield=False)

    added = _run(gen, skeleton)

    assert [g.gems for g in added] == [["Leap Slam"]], "no shield in Weapon 2: Shield Charge is refused, Leap Slam is the slot"
    assert "Shield Charge" not in pob.seen
    assert _counter("movement-spell") == (0, 0), "the spell slot was already filled by the author's Dash"
    assert _counter("movement-skill")[0] > 0 and _counter("movement-skill")[1] > 0


def test_a_shield_makes_shield_charge_an_option_and_pob_picks_by_the_objective() -> None:
    skeleton = _skeleton("Dash")
    gen, pob = _gen(skeleton, shield=True)

    added = _run(gen, skeleton)

    assert [g.gems[0] for g in added] == ["Shield Charge"]  # 4 > Leap Slam 3
    assert {"Shield Charge", "Leap Slam"} <= pob.seen


@pytest.mark.parametrize("slot, gems", [("Gloves", ["Leap Slam", "Faster Attacks", "Momentum"]), (None, ["Leap Slam"])])
def test_the_skill_is_linked_with_faster_attacks_and_momentum_only_with_the_linked_sockets(slot: str | None, gems: list[str]) -> None:
    skeleton = _skeleton("Dash")
    gen, _pob = _gen(skeleton, shield=False, linked_slot=slot)

    added = _run(gen, skeleton)

    assert [g.gems for g in added] == [gems]
    if slot:
        assert added[0].slot == slot, "the linked group sits where the 3-link is"


def test_only_leap_slam_is_linked_with_the_supports_shield_charge_stands_alone() -> None:
    skeleton = _skeleton("Dash")
    gen, _pob = _gen(skeleton, shield=True, linked_slot="Gloves")

    options = gen._movement_options(skeleton, "skill", ["Shield Charge", "Leap Slam"], Rails.load().movement)

    assert {tuple(gems) for gems, _slot in options} == {("Shield Charge",), ("Leap Slam", "Faster Attacks", "Momentum")}


@pytest.mark.parametrize("attack_time, kept", [(1.1, False), (1.0, False), (0.8, True)])
def test_a_staff_build_skips_the_skill_at_a_slow_leap_slam(attack_time: float, kept: bool) -> None:
    skeleton = _skeleton("Dash")
    gen, _pob = _gen(skeleton, shield=False, weapon1="Staff", attack_time=attack_time)

    added = _run(gen, skeleton)

    assert [g.gems[0] for g in added] == (["Leap Slam"] if kept else [])
    generated, evaluated = _counter("movement-skill")
    if kept:
        assert generated > 0 and evaluated > 0, (generated, evaluated)
    else:
        assert (generated, evaluated) == (0, 0), "a skipped slot counts nothing: the probe is no option written as the slot's group"
        assert _counter("gem:Leap Slam") == (0, 0)


def test_the_skip_is_for_a_staff_only() -> None:
    skeleton = _skeleton("Dash")
    gen, _pob = _gen(skeleton, shield=False, weapon1="One Handed Sword", attack_time=1.5)

    assert [g.gems[0] for g in _run(gen, skeleton)] == ["Leap Slam"]


def test_the_pair_does_not_count_against_max_groups() -> None:
    skeleton = _skeleton()
    gen, _pob = _gen(skeleton, aura_pool=("Haste", "Determination", "Grace"))

    added = _run(gen, skeleton, max_groups=2)

    names = [g.gems[0] for g in added]
    assert {"Frostblink", "Shield Charge"} <= set(names)
    assert len([n for n in names if n not in ("Frostblink", "Shield Charge")]) == 2, names  # two utilities besides the pair
    assert len(names) == 4


def test_the_rejudge_keeps_a_picked_movement_group_inside_its_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The re-judge swaps a picked Frostblink only for another member of the spell slot (never Smoke Mine, never a
    skill), and a linked skill group keeps its supports through the swap."""

    skeleton = Skeleton(class_name="Marauder", ascendancy="Juggernaut", main_link=["Cleave"], extra_groups=[
        SocketGroup(gems=["Frostblink"], slot="Helmet", label="Frostblink", picked=True),
        SocketGroup(gems=["Shield Charge", "Faster Attacks", "Momentum"], slot="Gloves", label="Shield Charge", picked=True)])
    gen, pob = _gen(skeleton)
    gen.legal_supports = lambda _sk: []
    gen.drop_reserving_group = lambda *_a, **_k: None
    gen._set_main_link_raw = lambda *_a, **_k: None
    monkeypatch.setattr(Skeleton, "refresh_minion_counts", lambda self, *_a, **_k: {})
    gen.pob.skeleton = skeleton

    gen.rejudge_picks(skeleton, max_sweeps=1)
    TRACE.flush("picks")

    assert not pob.seen & set(FORBIDDEN) and "Whirling Blades" not in pob.seen
    assert skeleton.extra_groups[0].gems[0] in ("Frostblink", "Flame Dash", "Dash")
    assert skeleton.extra_groups[1].gems[1:] == ["Faster Attacks", "Momentum"]
    assert skeleton.extra_groups[1].gems[0] in ("Shield Charge", "Leap Slam")
    assert _counter("movement-forbidden")[1] == 0
