from junkroan.optimizer.pipeline import BuildResult


def _line(final, optimistic, stat="CombinedDPS"):
    r = object.__new__(BuildResult)
    r.stages = []
    r.objective_stat = stat
    r.final_stats = final
    r.optimistic_stats = optimistic
    r.pinnacle_ramp_dps = None
    r.pinnacle_ramp_seconds = None
    r.audit = []
    r.moves = []
    r.pob_calls = {}
    r.dropped_moves = []
    r.seconds = 1.0
    r.floors_missed = None  # #704: the summary's floors line reads it

    class _S:
        class_name = "A"
        ascendancy = "B"
        main_link = ["X"]

    r.skeleton = _S()
    return [ln for ln in r.summary().splitlines() if ln.startswith("  final:")][0]


def test_minion_final_line_prints_fulldps():
    ln = _line({"CombinedDPS": 0, "FullDPS": 53095.277, "Life": 1}, {"CombinedDPS": 0, "FullDPS": 104509.0}, "FullDPS")
    assert "53,095" in ln and "104,509" in ln and "CombinedDPS 0 " not in ln and ln.startswith("  final: FullDPS 53,095")


def test_nonminion_final_line_unchanged():
    ln = _line({"CombinedDPS": 1234567, "FullDPS": 1300000, "Life": 1}, {"CombinedDPS": 2000000, "FullDPS": 3})
    assert ln.startswith("  final: CombinedDPS 1,234,567 (optimistic 2,000,000) life 1 ")
