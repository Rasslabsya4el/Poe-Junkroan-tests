from datetime import date

from junkroan.runs import weekly_fillers as wf

MON = date(2026, 10, 12)


def test_count_cpu_row3():
    assert wf.filler_count(8, 20.0, 4.0, 3.2, 12, 0.80) == 2  # memory room 5


def test_count_three_row1():
    assert wf.filler_count(3, 20.0, 4.0, 3.2, 12, 0.0) == 3  # 12 cores, mem for 5, 3 slots


def test_count_zero_cases():
    assert wf.filler_count(3, 20.0, 4.0, None, 12, 0.0) == 0
    assert wf.filler_count(3, 20.0, 4.0, 0, 12, 0.0) == 0
    assert wf.filler_count(3, 3.0, 4.0, 1.0, 12, 0.0) == 0
    assert wf.filler_count(3, 20.0, 4.0, 1.0, 12, 1.0) == 0


def test_next_stems_row4():
    missing = [f"row{i:02d}" for i in range(21)]
    got = wf.next_stems(missing, ["row00", "row02"], 3)
    assert got == ["row01", "row03", "row04"]
    assert wf.next_stems(["a", "a", "b"], [], 5) == ["a", "b"]


def test_choose_cut_row4():
    missing = [f"row{i:02d}" for i in range(21)]
    cmds = wf.choose("abc123", "artifacts/benchmark/W", missing, ["row00"], 3, MON, 0, "main1")
    assert [c.key for c in cmds] == ["row01", "row02", "row03"]
    assert all(c.pin == "abc123" and c.kind == "cut" for c in cmds)
    assert cmds[0].command == "python scripts/benchmark.py --resume artifacts/benchmark/W --row row01"


def test_choose_full_folder_falls_to_warn():
    cmds = wf.choose("abc123", "F", [], [], 1, MON, 0, "main1")
    assert cmds[0].kind == "warn"


def test_weekly_set_size_and_wrap_row5():
    import benchmark
    total = len(benchmark.SETS["core14"]) * len(wf.WARN_SEEDS)
    assert total == len(wf.warn_rows(MON, 0))
    first = wf.warn_rows(MON, 0)[0]
    assert wf.warn_rows(MON, total)[0] == first
    assert wf.warn_rows(MON, total - 1)[0] == wf.warn_rows(MON, 0)[-1]
    assert wf.warn_rows(MON, total - 1)[1] == first
    assert first == (benchmark.SETS["core14"][0], 4)
    assert wf.warn_rows(MON, 0)[1] == (benchmark.SETS["core14"][0], 5)


def test_choose_warn_row5():
    cmds = wf.choose(None, None, [], ["absolution_minions:4"], 2, MON, 0, "main1")
    assert cmds[0].command == ("python scripts/benchmark.py absolution_minions --seed 5 --seeds 1 --no-variants "
                               "--gear wishlist --tag warn-20261012")
    assert cmds[0].pin == "main1" and cmds[1].key == "absolution_minions:6"
