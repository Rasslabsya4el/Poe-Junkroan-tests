"""The search's seed fan-out and the best-of selection (D71). No PoB: the pipeline results
are fakes with known Scores, which is exactly what the selection sees."""

from junkroan.search.runner import best_by_seed, format_seeds, seed_jobs, seed_spread


def result(tag: str, seed: int, value: float, *, feasible: bool = True, violation: float = 0.0) -> dict:
    """What `runner.optimize` returns, cut down to the fields the selection reads."""

    return {"ok": True, "tag": tag, "seed": seed, "value": value, "feasible": feasible,
            "violation": violation if not feasible else 0.0, "seconds": 100.0 * seed, "import_code": f"{tag}-s{seed}"}


def test_every_finalist_is_fanned_out_into_one_job_per_seed() -> None:
    """2 finalists x 3 seeds = 6 jobs, all in the same pool (the point of the fan-out)."""

    jobs = seed_jobs([("skA", "Inquisitor-0", 1), ("skB", "Hierophant-1", 1)], 3)
    assert len(jobs) == 6
    assert [(tag, seed) for _sk, tag, seed in jobs] == [("Inquisitor-0", 1), ("Inquisitor-0", 2), ("Inquisitor-0", 3),
                                                        ("Hierophant-1", 1), ("Hierophant-1", 2), ("Hierophant-1", 3)]
    assert [sk for sk, _t, _s in jobs] == ["skA", "skA", "skA", "skB", "skB", "skB"]


def test_seeds_count_up_from_the_job_s_own_first_seed() -> None:
    """A mutation variant continues from the seed its parent won with."""

    assert [s for _sk, _t, s in seed_jobs([("sk", "mut", 4)], 2)] == [4, 5]
    assert [s for _sk, _t, s in seed_jobs([("sk", "mut", 7)], 1)] == [7]
    assert [s for _sk, _t, s in seed_jobs([("sk", "mut", 1)], 0)] == [1]  # seeds < 1 still builds once


def test_the_best_seed_by_value_is_delivered_and_the_others_kept() -> None:
    runs = [result("Inquisitor-0", 1, 690_113), result("Inquisitor-0", 2, 806_199), result("Inquisitor-0", 3, 741_002)]
    winners, others = best_by_seed(runs)
    assert len(winners) == 1 and winners[0]["seed"] == 2 and winners[0]["value"] == 806_199
    assert [r["seed"] for r in others] == [3, 1]  # every seed that is not delivered, best first
    assert winners[0]["seed_values"] == [806_199, 741_002, 690_113]
    assert [(d["seed"], d["best"]) for d in winners[0]["seed_runs"]] == [(1, False), (2, True), (3, False)]


def test_a_feasible_seed_beats_a_higher_infeasible_one() -> None:
    """Feasibility first, then the violation, then the value: the objective's Score order."""

    winners, others = best_by_seed([result("t", 1, 2_000_000, feasible=False, violation=0.4), result("t", 2, 500_000)])
    assert winners[0]["seed"] == 2 and winners[0]["value"] == 500_000
    assert [r["seed"] for r in others] == [1]


def test_between_two_infeasible_seeds_the_smaller_violation_wins() -> None:
    winners, _ = best_by_seed([result("t", 1, 900_000, feasible=False, violation=0.9), result("t", 2, 100_000, feasible=False, violation=0.1)])
    assert winners[0]["seed"] == 2


def test_a_tie_keeps_the_lowest_seed() -> None:
    winners, others = best_by_seed([result("t", 3, 500_000), result("t", 1, 500_000), result("t", 2, 500_000)])
    assert winners[0]["seed"] == 1 and [r["seed"] for r in others] == [2, 3]


def test_each_finalist_keeps_its_own_best() -> None:
    """The tag is the finalist; seeds of different finalists never compete."""

    winners, others = best_by_seed([result("a", 1, 10.0), result("a", 2, 30.0), result("b", 1, 50.0), result("b", 2, 20.0)])
    assert {w["tag"]: w["seed"] for w in winners} == {"a": 2, "b": 1}
    assert {(r["tag"], r["seed"]) for r in others} == {("a", 1), ("b", 2)}


def test_a_single_seed_is_its_own_winner() -> None:
    winners, others = best_by_seed([result("a", 1, 10.0)])
    assert others == [] and winners[0]["seed"] == 1 and len(winners[0]["seed_runs"]) == 1


def test_the_spread_is_max_minus_min_over_the_best() -> None:
    assert seed_spread([806_199, 741_002, 690_113]) == (806_199 - 690_113) / 806_199
    assert round(seed_spread([806_199, 741_002, 690_113]), 4) == 0.1440
    assert seed_spread([500.0]) == 0.0 and seed_spread([]) == 0.0 and seed_spread([0.0, 0.0]) == 0.0


def test_the_report_line_names_the_seed_and_every_value() -> None:
    winners, _ = best_by_seed([result("t", 1, 690_113), result("t", 2, 806_199), result("t", 3, 741_002)])
    assert format_seeds(winners[0]) == "best of 3 seeds (seed 2): 806,199 / 741,002 / 690,113; spread 14.4% of the best."
    one, _ = best_by_seed([result("t", 5, 806_199)])
    assert format_seeds(one[0]) == "one seed (seed 5): 806,199."
    assert format_seeds({}) == ""
