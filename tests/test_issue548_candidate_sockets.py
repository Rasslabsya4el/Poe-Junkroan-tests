"""#548 (row 1, PoB-free): a loop gear candidate is judged under the incumbent's `Sockets:` line.

The colour step (`sync_gear_sockets`) writes a coloured line into `loot.current_raw[slot]`; the loop's re-rolled
candidates were rolled with the skeleton's `sockets` (normally None) and so were judged without the socket colour's
gem quality the incumbent has. Fakes of tests/loop_fakes.py; the fill records the `sockets` argument it
was given and builds the raw its roll would carry, then counts it at the trace's PoB boundary.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.seeds import PURPOSE_JOINT_KICK_RNG, derive_seed
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import WishlistGear

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

LINE = "R-R-G B"
GLOVES_BASE = "Fingerless Silk Gloves"
INC_GLOVES = f"Rarity: Rare\nDoom Grip\n{GLOVES_BASE}\nItem Level: 80\nSockets: {LINE}\nImplicits: 0\n+80 to maximum Life"
BARE_BOOTS = "Rarity: Rare\nDoom Tread\nTwo-Toned Boots\nItem Level: 80\nImplicits: 0\n+80 to maximum Life"
SHIELD = "Rarity: Rare\nDoom Wall\nVaal Spirit Shield\nItem Level: 80\nSockets: R-G\n"


def _rolled(slot: str, base: str, sockets: str | None) -> str:
    return f"Rarity: Rare\nRolled {slot}\n{base}\nItem Level: 80\n" + (f"Sockets: {sockets}\n" if sockets else "") + "Implicits: 0\n+80 to maximum Life"


class _SockLoot(_Loot):
    """`_Loot` whose roll carries the `sockets` it was asked for, counted at the trace's PoB boundary like the real fill."""

    def fill_slot(self, slot, base, *, n=None, sockets=None, seed=1, **kwargs):
        raw = _rolled(slot, base, sockets)
        TRACE.count_candidates([{"items": {slot: raw}}])
        TRACE.count_trial({"items": {slot: raw}})
        return super().fill_slot(slot, base, n=n, sockets=sockets, seed=seed)


def _asked(loot: _Loot) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in loot.calls:
        if c[0] == "fill_slot":
            out.setdefault(c[1], []).append(c[4])
    return out


def _loop(monkeypatch, incumbents: dict[str, str], rare_bases: dict[str, str], sockets: dict | None = None):
    TRACE.reset()
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _SockLoot(pob, {})
    loot.current_raw.update(incumbents)
    sk = _skeleton(rare_bases, main_link=("Puncture",))
    sk.sockets = dict(sockets or {})
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    _patch_generator(monkeypatch, [])
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5), result=p.started())
    return loot


def _joint(incumbents: dict[str, str], rare_bases: dict[str, str], sockets: dict | None = None, *, loot_cls=_SockLoot):
    TRACE.reset()
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = loot_cls(pob, {})
    loot.current_raw.update(incumbents)
    sk = _skeleton(rare_bases, main_link=("Fireball",))
    sk.sockets = dict(sockets or {})
    slots = list(rare_bases)
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, headroom=lambda *_a, **_k: slots)
    p.joint_round(sk, loot, tree, i=0, seed=1, loot_n=5, rng=random.Random(derive_seed(1, PURPOSE_JOINT_KICK_RNG)), ruin_points=16, slots_per_round=2, refine_rounds=6)
    return loot


def test_gear_move_candidates_carry_the_incumbents_sockets(monkeypatch) -> None:
    loot = _loop(monkeypatch, {"Gloves": INC_GLOVES}, {"Gloves": GLOVES_BASE, "Boots": "Two-Toned Boots"})
    asked = _asked(loot)
    assert asked["Gloves"][0] == LINE  # the gear move, first in the walk
    assert asked["Boots"][0] is None  # no incumbent: today's argument


def test_gear_move_incumbent_without_a_sockets_line_keeps_the_skeletons_argument(monkeypatch) -> None:
    loot = _loop(monkeypatch, {"Boots": BARE_BOOTS}, {"Boots": "Two-Toned Boots"}, {"Boots": "W-W"})
    assert _asked(loot)["Boots"][0] == "W-W"


def test_gear_move_other_class_incumbent_keeps_the_skeletons_argument(monkeypatch) -> None:
    loot = _loop(monkeypatch, {"Weapon 2": SHIELD}, {"Weapon 2": "Serrated Arrow Quiver"}, {"Weapon 2": "G-G"})
    assert _asked(loot)["Weapon 2"][0] == "G-G"  # a Quiver cannot hold the Shield's sockets


def test_joint_kick_candidates_carry_the_incumbents_sockets() -> None:
    loot = _joint({"Gloves": INC_GLOVES, "Boots": BARE_BOOTS}, {"Gloves": GLOVES_BASE, "Boots": "Two-Toned Boots"}, {"Boots": "W-W"})
    asked = _asked(loot)
    assert asked["Gloves"] == [LINE]  # popped from current_raw before the fill, still the incumbent's line
    assert asked["Boots"] == ["W-W"]  # the incumbent had no line


def test_joint_kick_other_class_incumbent_keeps_the_skeletons_argument() -> None:
    loot = _joint({"Weapon 2": SHIELD, "Gloves": INC_GLOVES}, {"Weapon 2": "Serrated Arrow Quiver", "Gloves": GLOVES_BASE}, {"Weapon 2": "G-G"})
    asked = _asked(loot)
    assert asked["Weapon 2"] == ["G-G"] and asked["Gloves"] == [LINE]


def test_joint_kick_wishlist_ranks_its_bases_under_the_incumbents_sockets() -> None:
    ranked: list[tuple[str, str | None]] = []

    class _Wish(_SockLoot, WishlistGear):
        def __init__(self, pob, script):
            _SockLoot.__init__(self, pob, script)
            self.rails = SimpleNamespace(gear=SimpleNamespace(wishlist=SimpleNamespace(item_level_for=lambda _s: 80)))

        def _rank_bases(self, slot, base, ilvl, sockets, *, bench_allowed=True):
            ranked.append((slot, sockets))
            return [SimpleNamespace(base=base)]

        def _plan_resistances(self, bases):
            pass

        def fill_slot(self, slot, base, *, n=None, sockets=None, seed=1, _base_candidates=None, **kwargs):
            return _SockLoot.fill_slot(self, slot, base, n=n, sockets=sockets, seed=seed)

    loot = _joint({"Gloves": INC_GLOVES}, {"Gloves": GLOVES_BASE}, loot_cls=_Wish)
    assert ranked == [("Gloves", LINE)] and _asked(loot)["Gloves"] == [LINE]


def test_trace_counts_the_incumbent_class_and_no_missing_in_a_loop_gear_move(monkeypatch) -> None:
    _loop(monkeypatch, {"Gloves": INC_GLOVES}, {"Gloves": GLOVES_BASE})
    classes: dict[str, dict[str, int]] = {}
    for moves in TRACE.considered().values():  # summed over moves: a later move's counter never hides an earlier one
        for c, n in moves.items():
            if c.startswith("gear-sockets:"):
                acc = classes.setdefault(c, {"generated": 0, "evaluated": 0})
                acc["generated"] += n.get("generated", 0)
                acc["evaluated"] += n.get("evaluated", 0)
    assert classes["gear-sockets:incumbent"]["generated"] > 0 and classes["gear-sockets:incumbent"]["evaluated"] > 0
    assert classes.get("gear-sockets:missing", {"evaluated": 0})["evaluated"] == 0
    assert "gear-sockets:unclassified" not in classes
