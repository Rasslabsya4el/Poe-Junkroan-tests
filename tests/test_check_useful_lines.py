import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_useful_lines import check_build  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.useful_lines import ItemLine  # noqa: E402

RAILS = Rails.load()
POS, NEG, ZERO = (0.0, 1.0), (0.0, -1.0), (0.0, 0.0)
STATS = [("+1 to Strength", POS), ("+2 to Dexterity", POS), ("+3 to Intelligence", POS)]
FIRE = ("+30% to Fire Resistance", POS)


def ring(*lines):
    return [(ItemLine(i, "explicit", t), v) for i, (t, v) in enumerate(lines)]


def run(*rings):
    table = {f"raw{n}": vals for n, vals in enumerate(rings)}
    items = [(f"Ring {n + 1}", "Two-Stone Ring", f"raw{n}") for n in range(len(rings))]
    return check_build(items, lambda slot, raw: table[raw], RAILS)


def test_five_lines_red():
    assert run(ring(*[(f"+{i} to Strength", POS) for i in range(5)]))


def test_three_lines_plus_drawback_green():
    assert not run(ring(*STATS, ("-5 to all", NEG)))


def test_fourth_resistance_line_green_alone_third_item_red():
    assert not run(ring(*STATS, FIRE))
    assert not run(ring(*STATS, FIRE), ring(*STATS, FIRE))
    assert run(ring(*STATS, FIRE), ring(*STATS, FIRE), ring(*STATS, FIRE))


def test_fourth_line_not_resistance_red():
    assert run(ring(*STATS, ("+4 to Strength", POS)))


def test_neutral_counts():
    assert run(ring(*STATS, ("+9 to Dexterity", ZERO), ("+8 to Intelligence", ZERO)))
