from junkroan.optimizer.socket_colours import ColourCandidate as C, pick_colours


def cands(n=4):
    return [C("Body Armour", i, f"g{i}", "R") for i in range(n)]


def additive(gains, base=100.0):
    def trial(picks):
        return base + sum(gains[p.gem] for p in picks)
    return trial


def test_two_picks_best_first():
    gains = {"g0": 1, "g1": 5, "g2": 3, "g3": -2}
    seen = []
    r = pick_colours(cands(), additive(gains), 100.0, 2, on_trial=lambda p, s: seen.append(s))
    assert [p.gem for p in r.picks] == ["g1", "g2"]
    assert r.score_after == 108 and r.score_before == 100
    assert r.trials == 7 and len(seen) == 7


def test_no_gain_no_pick():
    gains = {"g0": 0, "g1": -1, "g2": -3, "g3": -2}
    r = pick_colours(cands(), additive(gains), 100.0, 3)
    assert r.picks == [] and r.score_after == 100 and r.trials == 4


def test_round_two_scored_with_first_applied():
    def trial(picks):
        names = {p.gem for p in picks}
        s = 100.0
        if "g0" in names:
            s += 5
        if "g1" in names:
            s += 2
        if names == {"g0", "g1"}:
            s += 10
        if "g2" in names:
            s += 4
        return s
    cs = cands(3)
    r = pick_colours(cs, trial, 100.0, 2)
    assert [p.gem for p in r.picks] == ["g0", "g1"]
    assert r.score_after == 117


def test_same_position_never_both():
    cs = [C("Helmet", 0, "a", "R"), C("Helmet", 0, "a", "B"), C("Helmet", 1, "b", "G")]
    r = pick_colours(cs, lambda ps: 100.0 + 3 * len(ps), 100.0, None)
    assert len({(p.slot, p.position) for p in r.picks}) == len(r.picks) == 2


def test_unlimited_stops_when_no_gain():
    gains = {"g0": 1, "g1": 5, "g2": -3, "g3": -2}
    r = pick_colours(cands(), additive(gains), 100.0, None)
    assert [p.gem for p in r.picks] == ["g1", "g0"]
    assert r.score_after == 106


def test_better_callable_lower_is_better():
    gains = {"g0": 1, "g1": -5, "g2": -3, "g3": 2}
    r = pick_colours(cands(), additive(gains), 100.0, 2, better=lambda n, o: n < o)
    assert [p.gem for p in r.picks] == ["g1", "g2"]
    assert r.score_after == 92


def test_zero_max_or_empty():
    def boom(_):
        raise AssertionError
    for cs, mp in ((cands(), 0), ([], 3)):
        r = pick_colours(cs, boom, 7.0, mp)
        assert (r.picks, r.score_before, r.score_after, r.trials) == ([], 7.0, 7.0, 0)


def test_on_round_lists_each_rounds_options():
    cands = [C("Body Armour", i, f"g{i}", "R") for i in range(4)]
    rounds = []
    pick_colours(cands, lambda picks: float(len(picks) + picks[-1].position), 0.0, 2, on_round=rounds.append)
    assert [len(r) for r in rounds] == [4, 3]
    assert all(len(o) == k + 1 for k, r in enumerate(rounds) for o in r)
