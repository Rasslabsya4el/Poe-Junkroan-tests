"""#801: the final line prints the output the objective maximised, under its PoB name."""

import re

from test_issue550_final_line import _line

# stormbrand s1 of artifacts/benchmark/20261010-0422-P1-#604-3 (rows/stormbrand-s1.json): objective FullDPS,
# CombinedDPS is one brand (half of it); the old final line read "dps 1,303,702"
STORM = {"CombinedDPS": 1303702.4056, "FullDPS": 2607404.8113192, "Life": 4697}
STORM_OPT = {"CombinedDPS": 2238247.3, "FullDPS": 4476494.5914305}


def test_stormbrand_final_line_names_and_prints_fulldps():
    ln = _line(STORM, STORM_OPT, "FullDPS")
    assert ln.startswith("  final: FullDPS 2,607,405 (optimistic 4,476,495) life 4697 ")


def test_final_line_number_is_the_stat_after_its_name():
    for stat in ("CombinedDPS", "FullDPS"):
        m = re.match(r"  final: (\w+) ([\d,]+) ", _line(STORM, STORM_OPT, stat))
        assert m.group(1) == stat and m.group(2) == f"{STORM[stat]:,.0f}"
