"""#1154 follow-up (brain's owner-answer: a restriction is hard): under the LOOT filler (`refills_by_value` False) an
excluded, unforced incumbent base (Prismatic Ring on day 1) is no longer left out of the `gear <slot>` move. The move
hands the filler an allowed base of the class, the slot is trialed, and the clean result stays even when it scores
lower (`must_keep` of #1152). PoB-free, over the fakes of `loop_fakes`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer import loot_gear
from junkroan.optimizer.improvement_loop import LoopPlan, gear_move_base
from junkroan.optimizer.item_bases import bases_of_type
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

PRISMATIC = "Prismatic Ring"
AMETHYST = "Amethyst Ring"


def _ring(base: str) -> str:
    return f"Rarity: RARE\nLoop Item\n{base}\nItem Level: 86\nImplicits: 0\n"


class _RecordingLoot(_Loot):
    """The loot filler's side: no base ranking, `fill_slot` rolls the base it is handed."""

    def __init__(self, pob, script) -> None:
        super().__init__(pob, script)
        self.rails = Rails.load()  # day 1
        self.handed: list[str] = []

    def fill_slot(self, slot, base, **kwargs):
        self.handed.append(base)
        return super().fill_slot(slot, base, **kwargs)


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _move(monkeypatch, script, *, forced_base: str | None = None):
    pob = _Pob(1000.0)
    loot = _RecordingLoot(pob, {"Ring 1": script})
    loot.current_raw["Ring 1"] = _ring(PRISMATIC)
    skeleton = _skeleton({"Ring 1": PRISMATIC})
    skeleton.forced_bases = {"Ring 1": forced_base} if forced_base else {}
    _patch_generator(monkeypatch, [])
    loop_over(pob, tree=_Tree(pob, []), gear=loot, skeleton=skeleton).run(LoopPlan.replay("gear", seed=1, passes=1))
    return loot, pob


def test_the_loot_filler_is_handed_an_allowed_base_of_the_class() -> None:
    loot = _RecordingLoot(_Pob(1000.0), {})
    skeleton = SimpleNamespace(rare_bases={"Ring 1": PRISMATIC}, forced_bases={})
    base = gear_move_base("Ring 1", skeleton=skeleton, loot=loot)
    assert base in bases_of_type("Ring", max_level=86) and base != PRISMATIC
    skeleton.forced_bases = {"Ring 1": PRISMATIC}
    assert gear_move_base("Ring 1", skeleton=skeleton, loot=loot) == PRISMATIC  # a base the request names stays


def test_an_excluded_incumbent_slot_is_trialed_and_the_lower_scoring_clean_result_stays(monkeypatch) -> None:
    loot, pob = _move(monkeypatch, [(_ring(AMETHYST), 600.0)])
    assert loot.handed and PRISMATIC not in loot.handed  # the slot was trialed on an allowed base
    assert loot.current_raw["Ring 1"] == _ring(AMETHYST) and pob.value == 600.0  # kept although 600 < 1000
    assert not loot_gear.raw_refused(loot, "Ring 1", loot.current_raw["Ring 1"])


def test_a_forced_base_incumbent_keeps_its_slot_and_its_base(monkeypatch) -> None:
    loot, pob = _move(monkeypatch, [(_ring(AMETHYST), 600.0)], forced_base=PRISMATIC)
    assert loot.handed == [PRISMATIC]
    assert loot.current_raw["Ring 1"] == _ring(PRISMATIC) and pob.value == 1000.0  # the worse roll is reverted as before


def test_a_class_with_no_allowed_base_leaves_the_slot_out_as_before() -> None:
    loot = _RecordingLoot(_Pob(1000.0), {})
    loot.other_weapon_bases = lambda base: []  # type: ignore[method-assign]
    skeleton = SimpleNamespace(rare_bases={"Ring 1": PRISMATIC}, forced_bases={})
    assert gear_move_base("Ring 1", skeleton=skeleton, loot=loot) is None
