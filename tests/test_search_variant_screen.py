"""The mutation round's keep rule (#525): one rule for feasible and infeasible variant screens. No PoB: the rows
are the six variant screens of the Frost Blades budget run 2358 (floor = 0.5 x 59,076 = 29,538)."""

from junkroan.search.runner import variant_screen_kept, variant_screen_line

FLOOR = 0.5 * 59_076

ROWS = [  # (tag, screen value, violation, feasible, kept)
    ("Slayer-hrimsorrow-terminus-no-pt", 89_970, 0.042, False, True),
    ("Slayer-hrimsorrow-terminus-void-axe", 53_752, 0.083, False, True),
    ("Slayer-hrimsorrow-void-axe", 48_668, 0.333, False, True),
    ("Slayer-hrimsorrow-no-pt-reaver-sword", 36_757, 0.083, False, True),
    ("Slayer-hrimsorrow-terminus-judgement-staff", 19_155, 3.234, False, False),
    ("Slayer-hrimsorrow-judgement-staff", 21_835, 0.0, True, False),
]


def test_2358_keeps_the_four_over_the_floor_and_drops_the_two_under_it() -> None:
    kept = [tag for tag, value, viol, feas, _k in ROWS
            if variant_screen_line(tag, {"value": value, "violation": viol, "feasible": feas, "seconds": 120.0}, FLOOR)[0]]
    assert kept == [r[0] for r in ROWS if r[4]]
    assert len(kept) == 4


def test_the_dropped_two_print_the_drop_line() -> None:
    for tag, value, viol, feas, want in ROWS:
        ok, line = variant_screen_line(tag, {"value": value, "violation": viol, "feasible": feas, "seconds": 120.0}, FLOOR)
        assert ok is want
        assert line.endswith("-> dropped (below half of the finalists screen)") is (not want)
        assert line.endswith("-> full") is want
    _ok, line = variant_screen_line("x", {"value": 19_155, "violation": 3.234, "feasible": False, "seconds": 120.0}, FLOOR)
    assert line == "  variant screen x: 19,155 (viol 3.234) in 2 min -> dropped (below half of the finalists screen)"


def test_feasibility_does_not_change_the_verdict() -> None:
    for value in (0.0, 1.0, FLOOR - 1, FLOOR, FLOOR + 1):
        assert variant_screen_kept(value, FLOOR) is (value >= FLOOR)
