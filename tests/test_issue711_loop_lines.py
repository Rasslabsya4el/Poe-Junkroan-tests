"""#711 unit 3: the improvement loop's own log lines (pass start, move start), a log line only."""

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.stage_catalog import loop_move_line, parse_log_line, start_line

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over


def _run(monkeypatch, logs):
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)], "Boots": [("b1", 1022.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    result = p.started()
    outcome = p.run(LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5))
    return result, outcome


def test_loop_writes_a_line_per_pass_and_per_move_before_the_move(monkeypatch) -> None:
    logs: list[str] = []
    result, outcome = _run(monkeypatch, logs)

    parsed = [(i, parse_log_line(m)) for i, m in enumerate(logs)]
    moves = [(i, v) for i, (k, v) in parsed if k == "loop_move"]
    assert outcome.passes == 2
    assert {p for _i, (p, _m) in moves} == {1, 2}
    pass1 = [m for _i, (p, m) in moves if p == 1]
    assert pass1 == ["refine", "swaps", "gear", "gear", "weapon-base", "picks", "lanes"]
    # the lines agree with the catalogue's own writer
    assert all(logs[i] == loop_move_line(p, m) for i, (p, m) in moves)
    # start lines: opening once, one per pass, each before that pass's moves
    starts = [(i, v) for i, (k, v) in parsed if k == "start"]
    assert [v for _i, v in starts] == ["loop opening", "loop pass 1", "loop pass 2"]
    first_move_1 = min(i for i, (p, _m) in moves if p == 1)
    first_move_2 = min(i for i, (p, _m) in moves if p == 2)
    assert starts[1][0] < first_move_1 < starts[2][0] < first_move_2
    # a move line comes before that move's own kept/reverted text
    first_gear = next(i for i, (p, m) in moves if p == 1 and m == "gear")
    assert any("Gloves" in m or "Boots" in m for m in logs[first_gear + 1:])
    assert not any("Gloves" in m or "Boots" in m for m in logs[:first_gear] if parse_log_line(m)[0] is None and "gear" in m)
    last = [v for _i, v in moves if v[0] == 2][-2:]
    assert last == [(2, "kick-tree"), (2, "kick-joint")]
    assert start_line("loop opening") in logs


def test_the_lines_change_no_number(monkeypatch) -> None:
    logs: list[str] = []
    with_lines, out_a = _run(monkeypatch, logs)
    silent: list[str] = []
    again, out_b = _run(monkeypatch, silent)
    stages = lambda r: [(s.name, s.notes) for s in r.stages]
    assert stages(with_lines) == stages(again)
    assert out_a.kept == out_b.kept and out_a.counts == out_b.counts
    # the pre-change expectations of test_a_gear_move_over_min_gain_is_kept...
    assert [n for n, _ in stages(with_lines)] == ["tree rebuilt on gear", "loop pass 1", "loop pass 2"]
    assert stages(with_lines)[1][1] == "Gloves +2.0%" and stages(with_lines)[2][1] == "no change"
    kept = [m for m in logs if parse_log_line(m)[0] is None]
    assert kept  # the loop's own lines are still there


def test_the_fixed_point_check_pass_writes_its_own_move_lines(monkeypatch) -> None:
    logs: list[str] = []
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Gloves": [("g1", 1002.0)], "Boots": [("b1", 1003.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    p.started()
    plan = LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5).extra_pass()
    p.run(plan)

    parsed = [parse_log_line(m) for m in logs]
    moves = [v for k, v in parsed if k == "loop_move"]
    assert moves and all(w == "fixed point check" for w, _m in moves)
    assert not any(m.startswith("loop pass") and " move " in m for m in logs)
    assert [v for k, v in parsed if k == "start"] == ["fixed point check"]
    assert [m for _w, m in moves] == ["refine", "swaps", "gear", "gear", "weapon-base", "picks"]
