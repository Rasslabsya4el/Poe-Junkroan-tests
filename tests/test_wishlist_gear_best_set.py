"""#188: the wishlist fill ends with the best whole gear set it held, ordered by Score.

No PoB runtime: the ordering, the log line and the whole-set snapshot/restore are tested with
the Scores #178 measured (`z329_juggernaut_boneshatter` s4 and `burning_arrow_snipe` s4). The
same rule against the live pinned PoB is `test_wishlist_gear_best_set_pob.py`.
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistSlotResult, _GearSetSnapshot


class _RecordingPob:
    """Just the slots and the equip calls, so "nothing was re-equipped" is an assertion."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.equip_calls: list[dict] = []

    def equip(self, updates):
        self.equip_calls.append(dict(updates))
        for slot, raw in updates.items():
            if raw:
                self.items[slot] = raw
            else:
                self.items.pop(slot, None)

    def stats(self, keys=None):  # never reached: every test hands its Score in
        raise AssertionError("no PoB readback is needed for the ordering")


def _gear_set(label: str, violation: float, value: float, suffix: str) -> _GearSetSnapshot:
    """One whole-set snapshot: two slots whose items carry the pass in their raw text."""

    raw_by_slot = {"Gloves": f"Titan Gauntlets|{suffix}", "Ring 2": f"Amethyst Ring|{suffix}"}
    return _GearSetSnapshot(
        label=label,
        score=Score(neg_violation=-violation, value=value),
        raw_by_slot=dict(raw_by_slot),
        results_by_raw={
            (slot, raw): WishlistSlotResult(slot=slot, base=raw.split("|")[0], ilvl=83, raw=raw, steps=[suffix])
            for slot, raw in raw_by_slot.items()
        },
        resistance_assignments={"Gloves": "fire", "Ring 2": "cold"},
        extra_resistance_assignments={"Ring 2": suffix},
    )


def _end_of_fill(snapshots: list[_GearSetSnapshot]):
    """The end-of-fill comparison with the last snapshot equipped, as `fill` leaves it."""

    pob = _RecordingPob()
    lines: list[str] = []
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), Rails.load(), log=lines.append)
    current = snapshots[-1]
    gear.current_raw = dict(current.raw_by_slot)
    gear._results_by_raw = dict(current.results_by_raw)
    gear._resistance_assignments = dict(current.resistance_assignments)
    gear._extra_resistance_assignments = dict(current.extra_resistance_assignments)
    pob.items = dict(current.raw_by_slot)
    pob.equip_calls.clear()
    restored = gear._keep_best_gear_set(snapshots)
    return gear, pob, lines, restored


def test_the_fill_ends_on_the_start_set_when_both_passes_scored_below_it() -> None:
    """#178 on z329_juggernaut_boneshatter s4, the fill of `gear pass 2 (with tree)`."""

    snapshots = [
        _gear_set("start", 0.4051, 1_056_242.0, "start"),
        _gear_set("pass 1", 1.0240, 1_055_825.0, "p1"),
        _gear_set("pass 2", 0.8930, 1_055_825.0, "p2"),
    ]

    gear, pob, lines, restored = _end_of_fill(snapshots)

    assert restored is snapshots[0]
    assert pob.items == snapshots[0].raw_by_slot
    assert gear.current_raw == snapshots[0].raw_by_slot
    assert set(gear._results_by_raw) == set(snapshots[0].results_by_raw)
    assert [result.steps for result in gear.shopping_results()] == [["start"], ["start"]]
    assert gear._resistance_assignments == {"Gloves": "fire", "Ring 2": "cold"}
    assert gear._extra_resistance_assignments == {"Ring 2": "start"}
    assert lines == [
        "wishlist fill sets: start viol 0.4051 value 1,056,242.0 | pass 1 viol 1.0240 value 1,055,825.0 "
        "| pass 2 viol 0.8930 value 1,055,825.0 -> kept start (restored)"
    ]


def test_at_equal_violation_the_fill_ends_on_the_higher_value_set() -> None:
    """#178 on burning_arrow_snipe s4: 1,162,159 -> 1,043,126 at violation 1.24."""

    snapshots = [
        _gear_set("start", 1.24, 1_162_159.0, "start"),
        _gear_set("pass 1", 1.24, 1_043_126.0, "p1"),
    ]

    gear, pob, lines, restored = _end_of_fill(snapshots)

    assert restored is snapshots[0]
    assert pob.items == snapshots[0].raw_by_slot
    assert gear.current_raw == snapshots[0].raw_by_slot
    assert lines == [
        "wishlist fill sets: start viol 1.2400 value 1,162,159.0 | pass 1 viol 1.2400 value 1,043,126.0 "
        "-> kept start (restored)"
    ]


def test_the_fill_keeps_its_own_last_set_when_it_is_the_best_and_re_equips_nothing() -> None:
    snapshots = [
        _gear_set("start", 1.24, 1_043_126.0, "start"),
        _gear_set("pass 1", 0.8930, 1_055_825.0, "p1"),
        _gear_set("pass 2", 0.0, 1_162_159.0, "p2"),
    ]

    gear, pob, lines, restored = _end_of_fill(snapshots)

    assert restored is None
    assert pob.equip_calls == []
    assert gear.current_raw == snapshots[-1].raw_by_slot
    assert lines == [
        "wishlist fill sets: start viol 1.2400 value 1,043,126.0 | pass 1 viol 0.8930 value 1,055,825.0 "
        "| pass 2 viol 0.0000 value 1,162,159.0 -> kept pass 2"
    ]


def test_a_tie_keeps_the_later_set() -> None:
    snapshots = [
        _gear_set("start", 0.4051, 1_056_242.0, "start"),
        _gear_set("pass 1", 0.4051, 1_056_242.0, "p1"),
    ]

    gear, pob, lines, restored = _end_of_fill(snapshots)

    assert restored is None
    assert pob.equip_calls == []
    assert gear.current_raw == snapshots[-1].raw_by_slot
    assert lines[0].endswith("-> kept pass 1")


def test_a_set_whose_maximized_stat_fell_to_zero_never_wins() -> None:
    """`better_score`'s own reading of a broken skill, applied on both sides of the comparison."""

    snapshots = [
        _gear_set("start", 0.0, 0.0, "start"),
        _gear_set("pass 1", 0.8930, 1_055_825.0, "p1"),
    ]

    gear, pob, lines, restored = _end_of_fill(snapshots)

    assert restored is None
    assert gear.current_raw == snapshots[-1].raw_by_slot
    assert lines[0].endswith("-> kept pass 1")


def test_the_whole_set_snapshot_survives_a_later_fill_and_restores_items_and_records() -> None:
    """Item 1: the records are copied, so a late repair pass cannot rewrite the snapshot."""

    pob = _RecordingPob()
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), Rails.load())
    start = WishlistSlotResult(slot="Gloves", base="Titan Gauntlets", ilvl=83, raw="Titan Gauntlets|start",
                               steps=["start"], extra_resistance="fire")
    gear.current_raw = {"Gloves": start.raw, "Belt": "Leather Belt|kept"}
    gear._results_by_raw = {("Gloves", start.raw): start}
    gear._resistance_assignments = {"Gloves": "fire"}
    gear._extra_resistance_assignments = {"Gloves": "fire"}
    pob.items = dict(gear.current_raw)

    snapshot = gear._snapshot_gear_set("start", score=Score(neg_violation=-0.4051, value=1_056_242.0))

    # the fill moves one slot, leaves the other, and rewrites the record it replaced
    filled = WishlistSlotResult(slot="Gloves", base="Ambush Mitts", ilvl=83, raw="Ambush Mitts|p2", steps=["p2"])
    gear.pob.equip({"Gloves": filled.raw})
    gear.current_raw["Gloves"] = filled.raw
    gear._results_by_raw = {("Gloves", filled.raw): filled}
    gear._resistance_assignments = {"Gloves": "lightning"}
    gear._extra_resistance_assignments = {}
    start.steps.append("rewritten by a later repair")
    start.extra_resistance = "cold"
    pob.equip_calls.clear()

    gear._restore_gear_set(snapshot)

    assert pob.items == {"Gloves": "Titan Gauntlets|start", "Belt": "Leather Belt|kept"}
    assert pob.equip_calls == [{"Gloves": "Titan Gauntlets|start"}]  # the untouched slot is not re-equipped
    assert gear.current_raw == {"Gloves": "Titan Gauntlets|start", "Belt": "Leather Belt|kept"}
    restored = gear._results_by_raw[("Gloves", "Titan Gauntlets|start")]
    assert restored.steps == ["start"] and restored.extra_resistance == "fire"
    assert gear._resistance_assignments == {"Gloves": "fire"}
    assert gear._extra_resistance_assignments == {"Gloves": "fire"}
