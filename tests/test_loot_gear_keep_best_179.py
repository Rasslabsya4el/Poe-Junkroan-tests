"""`LootGear.fill` never ends on a gear set `Score` orders below one it already held (#179, rule 1),
and a pass in which an emptied slot reads violation inf is built twice, by value and by violation
(rule 2).

The judge (`best_gear_set`) is fed labelled sets as (violation, value) data; the cases are the
measured boneshatter sets of #155's findings plus two shape cases. Tests on a fake PoB check that a
losing pass 2 ends with pass 1's items equipped, `current_raw` matching them, and the weapon partner
put back, and that the two builds of an inf pass are made and judged. No PoB is opened.
"""

from __future__ import annotations

import math

import pytest

from junkroan.optimizer.loot_gear import GearSet, LootGear, _rank, best_gear_set
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.seeds import PURPOSE_LOOT_FILL_SLOT, derive_seed


def _set(label: str, violation: float, value: float) -> GearSet:
    return GearSet(label, Score(neg_violation=-violation, value=value))


CASES = [
    ("boneshatter s6", [("start", 0.000, 220_506), ("pass 1", 0.000, 223_124), ("pass 2 by value", 0.000, 297_387), ("pass 2 by violation", 0.000, 180_617)], "pass 2 by value"),
    ("boneshatter s4", [("start", 0.025, 485_447), ("pass 1", 0.000, 512_653), ("pass 2 by value", 0.164, 661_157), ("pass 2 by violation", 0.000, 713_551)], "pass 2 by violation"),
    ("boneshatter s5", [("start", 0.277, 699_403), ("pass 1", 0.166, 665_017), ("pass 2 by value", 0.159, 954_203), ("pass 2 by violation", 0.097, 665_017)], "pass 2 by violation"),
    ("the pass only loses, no violation-built pass", [("start", 0.000, 100), ("pass 1", 0.000, 100), ("pass 2", 0.023, 120)], "pass 1"),  # the tie keeps the later
    ("the last set is the best", [("start", 0.3, 100), ("pass 1", 0.2, 100), ("pass 2 by value", 0.1, 100), ("pass 2 by violation", 0.1, 100)], "pass 2 by violation"),
]


@pytest.mark.parametrize(("name", "rows", "kept"), CASES, ids=[c[0] for c in CASES])
def test_the_judge_keeps_the_best_labelled_set(name: str, rows: list[tuple[str, float, float]], kept: str) -> None:
    sets = [_set(*row) for row in rows]

    assert best_gear_set(sets).label == kept


def test_a_set_with_no_number_never_beats_one_that_has_one() -> None:
    sets = [_set("start", 0.5, 100.0), _set("pass 1", 0.0, 0.0)]  # feasible only because the skill stopped working

    assert best_gear_set(sets).label == "start"


# -- the fill on a fake PoB -------------------------------------------------------

# item raw -> (Life, CombinedDPS); the floor is Life 4000, Life and DPS add up over the worn items
ITEMS = {"S0": (3900.0, 50.0), "P1": (4100.0, 100.0), "P2": (3900.0, 200.0)}
QUIVER = "QUIVER"
OBJECTIVE = Objective(maximize="CombinedDPS", floors={"Life": 4000.0})


def _s(p: int, i: int) -> int:
    """The draw seed `fill` (default seed 1) gives pass p, slot i."""

    return derive_seed(1, PURPOSE_LOOT_FILL_SLOT, p, i)


class _FakePob:
    """A build whose items add up to the stats. An empty main hand reads DPS 0 and no Life at all
    (infinite violation, finite value: the emptied slot of the second gear pass) unless
    `empty_reads_inf` is off (a spell build: its Life stays, no DPS). Like PoB, a changed main hand
    silently drops the pair slot. `rolls` maps a seed to what `random_rares` returns for it, so the
    two builds of one pass roll the same candidates."""

    def __init__(self, rolls: dict[int, tuple[str, ...]] | None = None, *, items: dict[str, tuple[float, float]] | None = None, empty_reads_inf: bool = True, extra_slots: dict[str, str] | None = None) -> None:
        self.slots: dict[str, str] = {"Weapon 1": "S0", "Weapon 2": QUIVER, **(extra_slots or {})}
        self.items = dict(ITEMS if items is None else items)
        self.rolls = rolls if rolls is not None else {_s(0, 0): ("P1",), _s(1, 0): ("P2",)}
        self.empty_reads_inf = empty_reads_inf
        self.roll_calls: list[int] = []
        self.trial_calls = 0

    def _stats_of(self, slots: dict[str, str]) -> dict[str, float]:
        worn = [self.items[raw] for slot, raw in slots.items() if raw in self.items]
        life, dps = sum(w[0] for w in worn), sum(w[1] for w in worn)
        if "Weapon 1" not in slots:
            return {"CombinedDPS": 0.0} if self.empty_reads_inf else {"Life": life + 4100.0, "CombinedDPS": 0.0}
        return {"Life": life, "CombinedDPS": dps}

    def export_xml(self) -> str:
        items = "".join(f'<Item id="{i}">{raw}</Item>' for i, raw in enumerate(self.slots.values(), 1))
        slots = "".join(f'<Slot name="{slot}" itemId="{i}"/>' for i, slot in enumerate(self.slots, 1))
        return f'<PathOfBuilding><Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>'

    def stats(self, keys):
        return self._stats_of(self.slots)

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        self.roll_calls.append(seed)
        return [{"raw": raw, "mod_ids": set()} for raw in self.rolls[seed]]

    def trial_stats(self, trials, keys, mode="fast"):
        self.trial_calls += 1
        return [{"ok": True, "stats": self._stats_of({**self.slots, t["item"]["slot"]: t["item"]["raw"]})} for t in trials]

    def equip(self, items):
        for slot, raw in items.items():
            if raw is None:
                self.slots.pop(slot, None)
            else:
                self.slots[slot] = raw
            if slot == "Weapon 1" and "Weapon 2" not in items:
                self.slots.pop("Weapon 2", None)
        return {}


def _fill(pob: _FakePob, passes: int = 2, bases: tuple[str, ...] = ("Weapon 1",)) -> tuple[LootGear, list[str]]:
    lines: list[str] = []
    loot = LootGear(pob, OBJECTIVE, Rails.load(), log=lines.append, uniques={"Weapon 2": QUIVER})
    loot.fill({slot: "Base" for slot in bases}, passes=passes, n=1, bench=False)
    return loot, lines


def test_an_inf_pass_is_built_twice_and_the_two_orders_pick_different_weapons() -> None:
    """Pass 1 equips P1 (viol 0, 100). Pass 2 empties the main hand (current reads inf): by value
    the rank is the value alone and takes P2 (viol 0.025, 200); by violation it keeps P1."""

    pob = _FakePob()
    loot, lines = _fill(pob)

    assert pob.roll_calls == [_s(0, 0), _s(1, 0), _s(1, 0)]  # pass 2 rolled the same candidates for both builds
    assert pob.trial_calls == 3  # pass 1, pass 2 by value, pass 2 by violation: one trial batch each
    # by violation (0, 100) ties pass 1 and the later wins; PoB wears it, the partner is back
    assert pob.slots == {"Weapon 1": "P1", "Weapon 2": QUIVER}
    assert loot.current_raw == {"Weapon 1": "P1"}
    assert lines[-1] == (
        "loot fill sets: start viol 0.0250 value 50.0 | pass 1 viol 0.0000 value 100.0"
        " | pass 2 by value viol 0.0250 value 200.0 | pass 2 by violation viol 0.0000 value 100.0"
        " -> kept pass 2 by violation"
    )


def test_the_by_value_set_is_restored_when_a_later_slot_makes_it_the_better_of_the_two() -> None:
    """Two slots. P2 (Life 3700, DPS 200) is what the by-value pass takes for the emptied main hand
    (viol 0.025 at that moment, value 200), P1 (Life 4100, DPS 100) what the by-violation pass takes.
    The body armour fills afterwards and takes BIG (+400 Life): by value ends at P2 + BIG (viol 0,
    200), by violation at P1 + BL (viol 0, 100). The judge keeps by value, and PoB, which stood on
    the by-violation set, is put back to by-value's items."""

    items = {"S0": (3900.0, 50.0), "P1": (4100.0, 100.0), "P2": (3700.0, 200.0), "B0": (0.0, 0.0), "BL": (200.0, 0.0), "BIG": (400.0, 0.0)}
    seeds = {_s(0, 0): ("P1",), _s(0, 1): ("BL",), _s(1, 0): ("P2",), _s(1, 1): ("BIG",)}
    pob = _FakePob(rolls=seeds, items=items, extra_slots={"Body Armour": "B0"})
    loot, lines = _fill(pob, bases=("Weapon 1", "Body Armour"))

    assert pob.slots == {"Weapon 1": "P2", "Weapon 2": QUIVER, "Body Armour": "BIG"}
    assert loot.current_raw == {"Weapon 1": "P2", "Body Armour": "BIG"}
    assert lines[-1].endswith("pass 2 by value viol 0.0000 value 200.0 | pass 2 by violation viol 0.0000 value 100.0 -> kept pass 2 by value")


def test_the_next_pass_goes_on_from_the_better_of_the_two_builds() -> None:
    """Pass 3 rolls from the set the judge would keep out of pass 2 (P1 here) and, its emptied slot
    reading inf as well, is built twice again."""

    pob = _FakePob(rolls={_s(0, 0): ("P1",), _s(1, 0): ("P2",), _s(2, 0): ("P1",)})
    loot, lines = _fill(pob, passes=3)

    assert pob.roll_calls == [_s(0, 0), _s(1, 0), _s(1, 0), _s(2, 0), _s(2, 0)]
    assert pob.slots == {"Weapon 1": "P1", "Weapon 2": QUIVER} and loot.current_raw == {"Weapon 1": "P1"}
    assert "pass 3 by value" in lines[-1] and "pass 3 by violation" in lines[-1]


def test_a_pass_with_no_inf_slot_runs_once() -> None:
    pob = _FakePob(empty_reads_inf=False)
    loot, lines = _fill(pob)

    assert pob.roll_calls == [_s(0, 0), _s(1, 0)] and pob.trial_calls == 2
    assert "by value" not in lines[-1] and "by violation" not in lines[-1]
    assert lines[-1].count("| pass 1 ") == 1 and lines[-1].count("| pass 2 ") == 1


def test_a_single_pass_fill_never_builds_twice() -> None:
    """The construction's one-pass fills: no slot is emptied, `current` is the start set's (finite)."""

    pob = _FakePob()
    _fill(pob, passes=1)

    assert pob.roll_calls == [_s(0, 0)] and pob.trial_calls == 1


def test_the_start_set_is_whatever_was_equipped_whoever_equipped_it() -> None:
    """Pass 1 and pass 2 both lose to the set the build wore when the fill began (S0 here, equipped
    by nobody the filler knows): it is restored, and `current_raw` -- which never held it -- is
    back to what it was at the start."""

    pob = _FakePob(items=dict(ITEMS) | {"S0": (4500.0, 400.0)})
    loot, lines = _fill(pob)

    assert pob.slots == {"Weapon 1": "S0", "Weapon 2": QUIVER}
    assert loot.current_raw == {}
    assert lines[-1].endswith("-> kept start (restored)")


# -- `_rank` as main has it, for the callers that never ask for violation first ------

def _main_rank(current: Score, trial: Score) -> tuple[float, float]:
    """`_rank` as it stands on main (before #179)."""

    if not current.feasible:
        key = (current.violation - trial.violation, trial.value - current.value)
    else:
        key = (1.0 if trial.feasible else -trial.violation, trial.value - current.value)
    return (-math.inf if math.isnan(key[0]) else key[0], -math.inf if math.isnan(key[1]) else key[1])


PAIRS = [
    (Score(-0.5, 0.0), Score(-0.2, 100.0)),
    (Score(-0.5, 10.0), Score(-0.3, 200.0)),
    (Score(0.0, 10.0), Score(-0.3, 200.0)),
    (Score(0.0, 10.0), Score(0.0, 50.0)),
    (Score(-math.inf, 0.0), Score(-0.164, 661_157.0)),
    (Score(-math.inf, 0.0), Score(0.0, 180_617.0)),
    (Score(-math.inf, 0.0), Score(-math.inf, 5.0)),
]


def test_gear_filler_ranks_as_main_does() -> None:
    from junkroan.optimizer.gear_filler import GearFiller

    for current, trial in PAIRS:
        assert GearFiller._rank_key(current, trial) == _main_rank(current, trial)


def test_wishlist_gear_ranks_as_main_does() -> None:
    from junkroan.optimizer.wishlist_gear import _comparable

    for current, trial in PAIRS:
        assert _comparable(current, trial) == _main_rank(current, trial)
        assert _rank(current, trial) == _main_rank(current, trial)


def test_violation_first_ranks_by_the_trial_score() -> None:
    inf_current = Score(-math.inf, 0.0)
    by_value = Score(-0.164, 661_157.0)
    by_violation = Score(0.0, 180_617.0)

    assert _rank(inf_current, by_value) > _rank(inf_current, by_violation)  # main: the value alone, the finding
    assert _rank(inf_current, by_violation, violation_first=True) > _rank(inf_current, by_value, violation_first=True)
