"""The 4th resistance line (an extra resistance line on up to 2 items) is given only under the cap (#429)."""

from __future__ import annotations

from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import solve_resistances

# One fixed resistance line (40 fire); four armour-like slots that could each carry an extra line.
_FIXED = [("Body Armour", {"fire": 40.0})]


def _extras(value: float) -> list[tuple[str, dict[str, float]]]:
    return [
        (slot, {"fire": value, "cold": value, "lightning": value})
        for slot in ("Helmet", "Gloves", "Boots", "Belt")
    ]


def _max_extra() -> int:
    return Rails.load().gear.wishlist.extra_resistance_items


def test_rail_allows_two_extra_resistance_items() -> None:
    assert _max_extra() == 2


def test_build_at_the_cap_gets_no_extra_resistance_lines() -> None:
    # every element is at the 75 cap without extras.
    baseline = {"FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 75.0}

    plan = solve_resistances(baseline, _FIXED, floor=75.0, extra_slots=_extras(12.0), max_extra=_max_extra())

    assert plan.extra_assignments == {}
    assert not any(plan.shortfall.values())


def test_build_10_under_the_cap_gets_at_least_one_and_at_most_two_extra_lines() -> None:
    # lightning 65 is 10 under the 75 cap; the fixed fire line cannot help it.
    baseline = {"FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 65.0}

    # 12 per extra line: one line closes the 10 gap, so exactly one is given.
    one = solve_resistances(baseline, _FIXED, floor=75.0, extra_slots=_extras(12.0), max_extra=_max_extra())
    assert len(one.extra_assignments) == 1
    assert set(one.extra_assignments.values()) == {"lightning"}
    assert not any(one.shortfall.values())

    # 3 per extra line: four slots could not close it either; the rail caps the lines at 2.
    capped = solve_resistances(baseline, _FIXED, floor=75.0, extra_slots=_extras(3.0), max_extra=_max_extra())
    assert len(capped.extra_assignments) == 2
    assert capped.shortfall["lightning"] == 4.0


def test_build_60_under_the_cap_still_gets_at_most_two_extra_lines() -> None:
    # lightning 15 is 60 under the 75 cap; one T3 line (38.5) is not enough, two are.
    baseline = {"FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 15.0}

    plan = solve_resistances(baseline, _FIXED, floor=75.0, extra_slots=_extras(38.5), max_extra=_max_extra())

    assert len(plan.extra_assignments) == 2
    assert set(plan.extra_assignments.values()) == {"lightning"}
    assert plan.shortfall["lightning"] == 0.0

    # 160 short: three lines would be needed, still only two are given.
    far = solve_resistances({**baseline, "LightningResist": -85.0}, _FIXED, floor=75.0, extra_slots=_extras(38.5), max_extra=_max_extra())
    assert len(far.extra_assignments) == 2
    assert far.shortfall["lightning"] == 83.0
