"""#1154 send-back: the loop's `gear <slot>` move never carries a base the loadout excludes, not even the incumbent's
(search-space rail met in the loop, PoB-free; the replay bench re-measures `base:Prismatic Ring` evaluated = 0).

The template filler ranks the bases of the slot's item class (`WishlistGear.base_candidates`, the real rule is used
here) and exempted the base it was handed, which the gear move always set to the incumbent's. A day-1 build that holds
a Prismatic Ring therefore trialled nothing but Prismatic Rings. The move now hands the filler an allowed base of the
class (a template ranks the whole class, a loot filler rolls that one); a base the request names stays.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.item_bases import bases_of_type
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.wishlist_gear import WishlistGear

from loop_fakes import _Loot, _Pob, _skeleton, _Tree, _TemplateLoot, _patch_generator, loop_over

PRISMATIC = "Prismatic Ring"


def _raw(base: str) -> str:
    return f"Rarity: RARE\nLoop Item\n{base}\nItem Level: 86\nQuality: 20\nSockets: R-R\nImplicits: 0\n"


class _RankingTemplate(_TemplateLoot):
    """A template filler that trials one item per base the REAL `WishlistGear.base_candidates` offers for the base it is
    handed (what `_rank_bases` sends to PoB), and records which bases it was handed and which it trialled."""

    def __init__(self, pob, rails: Rails) -> None:
        super().__init__(pob, {})
        self.rails = rails
        self._ranker = object.__new__(WishlistGear)
        self._ranker.rails = rails
        self.flexible_by_value = False
        self._resistance_assignments, self.resistance_plan = {}, {}
        self.handed: list[str] = []
        self.trialled: list[str] = []

    def preselect_bases(self, slots, rare_bases, sockets_of):
        return {}

    def fill_slot(self, slot, base, *, n=None, sockets=None, seed=1, replan_resistance=False, _base_candidates=None, order="floors"):
        self.handed.append(base)
        for candidate in self._ranker.base_candidates(base):
            trial = {"item": {"slot": slot, "raw": _raw(candidate)}}
            TRACE.count_candidates([trial])
            TRACE.count_trial(trial)
            self.trialled.append(candidate)
        return SimpleNamespace(raw=self.current_raw.get(slot))  # the incumbent wins its slot: nothing to judge


class _PlainLoot(_Loot):
    """The loot filler's side: no base ranking, `fill_slot` rolls the base it is handed."""

    def __init__(self, pob) -> None:
        super().__init__(pob, {})
        self.rails = Rails.load()
        self.handed: list[str] = []

    def fill_slot(self, slot, base, **kwargs):
        self.handed.append(base)
        return super().fill_slot(slot, base, **kwargs)


def _gear_move(monkeypatch, loot, skeleton) -> None:
    pob = loot.pob
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=_Tree(pob, []), gear=loot, skeleton=skeleton)
    rig.run(LoopPlan.replay("gear", seed=1, passes=1))


def _evaluated() -> dict[str, int]:
    out: dict[str, int] = {}
    for classes in TRACE.considered().values():
        for name, cell in classes.items():
            out[name] = out.get(name, 0) + cell["evaluated"]
    return out


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _template(monkeypatch, *, forced: bool = False):
    pob = _Pob(1000.0)
    loot = _RankingTemplate(pob, Rails.load())  # day 1
    loot.current_raw["Ring 1"] = _raw(PRISMATIC)
    skeleton = _skeleton({"Ring 1": PRISMATIC})
    skeleton.forced_bases = {"Ring 1": PRISMATIC} if forced else {}
    _gear_move(monkeypatch, loot, skeleton)
    return loot


def test_a_day1_gear_trial_never_carries_the_incumbents_excluded_base_and_the_slot_still_gets_trials(monkeypatch) -> None:
    loot = _template(monkeypatch)
    seen = _evaluated()

    assert PRISMATIC not in loot.handed and loot.handed  # the slot was refilled, on an allowed base of its class
    assert loot.trialled.count(PRISMATIC) == 0
    assert seen.get(f"base:{PRISMATIC}", 0) == 0 and seen.get("base-excluded-by-loadout", 0) == 0
    assert len(set(loot.trialled)) > 1 and seen.get("base:Amethyst Ring", 0) > 0  # the other ring bases are evaluated
    assert set(loot.handed) <= set(bases_of_type("Ring", max_level=86))


def test_a_base_the_request_names_stays_the_slots_base(monkeypatch) -> None:
    loot = _template(monkeypatch, forced=True)

    assert loot.handed == [PRISMATIC]  # forced: kept as the filler's base, the exemption of base_candidates applies


def test_a_filler_that_ranks_no_bases_is_handed_an_allowed_base_for_an_excluded_incumbent_slot(monkeypatch) -> None:
    pob = _Pob(1000.0)
    loot = _PlainLoot(pob)
    loot.current_raw["Ring 1"] = _raw(PRISMATIC)
    skeleton = _skeleton({"Ring 1": PRISMATIC})
    skeleton.forced_bases = {}

    _gear_move(monkeypatch, loot, skeleton)

    assert loot.handed and PRISMATIC not in loot.handed  # trialed on an allowed base of the class (the joint #1154 follow-up rule)


def test_an_allowed_incumbent_base_is_refilled_as_before(monkeypatch) -> None:
    pob = _Pob(1000.0)
    loot = _RankingTemplate(pob, Rails.load())
    loot.current_raw["Ring 1"] = _raw("Amethyst Ring")
    skeleton = _skeleton({"Ring 1": "Amethyst Ring"})
    skeleton.forced_bases = {}

    _gear_move(monkeypatch, loot, skeleton)

    assert loot.handed == ["Amethyst Ring"] and PRISMATIC not in loot.trialled
