"""#12: one random stream per kick-joint draw, so switching a move off shifts no later draw. PoB-free."""

from __future__ import annotations

import random

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.seeds import PURPOSE_JOINT_KICK_RNG, derive_seed

from loop_fakes import _Loot, _Pob, _Tree, _skeleton, loop_over

_SEED = 1
_DRAWS = 4


def _run(moves: frozenset[str], headroom) -> list[tuple[int, list[float]]]:
    """The kick-joint rounds of one pass-1 loop run: (draw index, the first values the round's generator would yield)."""

    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves", "Weapon 1": "Wand"}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, headroom=headroom)
    p.started()
    seen: list[tuple[int, list[float]]] = []
    joint_round = p.joint_round

    def spy(sk_, loot_, tree_, *, i, rng, **kwargs):
        probe = random.Random()
        probe.setstate(rng.getstate())  # look at the generator without consuming it
        seen.append((i, [probe.random() for _ in range(3)]))
        return joint_round(sk_, loot_, tree_, i=i, rng=rng, **kwargs)

    p.joint_round = spy
    p.run(LoopPlan(seed=_SEED, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, kick_draws=(0, _DRAWS), moves=moves))
    return seen


def test_a_move_switched_off_shifts_no_kick_joint_draw() -> None:
    # The state-dependent consumption of the shared stream is stood in for by the headroom ranking: with the
    # "swaps" move on, the victim slots come from `rng.sample` (an empty ranking), with it off from the ranking.
    # Before #12 that changed what every later round drew; now each (pass, draw) owns its generator.
    on = _run(frozenset({"swaps", "kick-joint"}), headroom=lambda sk, loot, slots, loot_n, seed: [])
    off = _run(frozenset({"kick-joint"}), headroom=lambda sk, loot, slots, loot_n, seed: ["Boots", "Gloves"])
    assert len(on) == len(off) == _DRAWS
    assert on == off


def test_the_generator_of_a_draw_is_seeded_by_pass_and_draw() -> None:
    seen = _run(frozenset({"kick-joint"}), headroom=lambda sk, loot, slots, loot_n, seed: [])
    assert [i for i, _ in seen] == list(range(_DRAWS))
    for i, values in seen:
        expected = random.Random(derive_seed(_SEED, PURPOSE_JOINT_KICK_RNG, 1, i))  # pass 1
        assert values == [expected.random() for _ in range(3)]
