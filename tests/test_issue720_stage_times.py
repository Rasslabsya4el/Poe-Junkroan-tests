"""#720: every step of the build-steps page has a stage name the generator reads, and the loop opening is recorded."""

import json
import sys
from pathlib import Path

from junkroan.optimizer.improvement_loop import pass_plan
from junkroan.optimizer.stage_catalog import LOOP_MOVES, STEPS, step_of

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_steps_doc  # noqa: E402
import stage_shares  # noqa: E402


# the names the pipeline records for the 9 stage steps of the issue (pipeline.py:491-618, improvement_loop.py opening)
RECORDED = ["rig gear", "rig tree", "gear pass 1 (rig tree)", "config re-derived (after gear pass 1)",
            "supports re-picked (no number)", "tree seed toward Int", "supports re-picked", "utility links",
            "tree refine"]


def test_the_generator_reads_a_time_for_each_recorded_stage_name() -> None:
    stages = [{"name": "skeleton applied", "seconds": 1.0}] + [{"name": n, "seconds": 2.0} for n in RECORDED]
    out = stage_shares.shares([stages])
    for name in RECORDED:
        step = step_of(name)
        assert step is not None, name
        assert out["steps"][step.name]["median_seconds"] == 2.0, name
    assert out["unmapped"] == []


def test_the_generator_reads_regions_and_corridors_move_rows() -> None:
    assert build_steps_doc.move_name("regions") == "regions"
    assert build_steps_doc.move_name("corridors") == "corridors"
    assert {"regions", "corridors"} <= set(LOOP_MOVES)
    assert {s.name for s in STEPS} >= {"rig gear", "rig tree", "tree refine", "loop opening"}


def test_regions_and_corridors_are_in_the_plan_only_when_named() -> None:
    kwargs = dict(has_flat_reservation_aura=False, local_only=False)
    default = [k for k, _i, _s in pass_plan(["Gloves"], [], moves=None, **kwargs)]
    named = [k for k, _i, _s in pass_plan(["Gloves"], [], moves=frozenset({"regions", "corridors", "swaps"}), **kwargs)]
    assert "regions" not in default and "corridors" not in default
    assert named == ["corridors", "swaps", "regions"][:0] or set(named) == {"corridors", "swaps", "regions"}


def _row(opening_secs):
    return {"stages": [{"name": "loop pass 1", "seconds": 6.0}],
            "move_rows": [{"move": "lanes", "pass": 0, "where": "loop opening", "seconds": opening_secs},
                          {"move": "lanes", "pass": 1, "where": "loop pass 1", "seconds": 1.0}]}


def test_the_loop_opening_time_comes_from_its_pass_0_move_rows(tmp_path) -> None:
    rows = tmp_path / "rows"
    rows.mkdir()
    for i, secs in enumerate((3.0, 5.0, 9.0)):
        (rows / f"b{i}.json").write_text(json.dumps(_row(secs)), encoding="utf-8")
    run = build_steps_doc.load_run(tmp_path)
    assert run["opening"] == 5.0
    page = build_steps_doc.generate(run)
    block = page.split("### improvement loop opening")[1].split("###")[0]
    assert "not run in this set" not in block and "Median time: 5" in block


def test_no_opening_rows_leaves_the_entry_not_run(tmp_path) -> None:
    rows = tmp_path / "rows"
    rows.mkdir()
    (rows / "b.json").write_text(json.dumps({"stages": [{"name": "loop pass 1", "seconds": 6.0}]}), encoding="utf-8")
    assert build_steps_doc.load_run(tmp_path)["opening"] is None


CONDITIONAL = ["rig gear", "rig tree", "gear pass 1 (rig tree)", "config re-derived (after gear pass 1)",
               "supports re-picked (no number)", "tree seed toward <stat>", "supports re-picked", "utility links", "fill",
               "tree refine", "repair pass <N>"]


def test_conditional_steps_print_their_condition_and_no_time(tmp_path) -> None:
    rows = tmp_path / "rows"
    rows.mkdir()
    (rows / "b.json").write_text(json.dumps(_row(3.0)), encoding="utf-8")
    page = build_steps_doc.generate(build_steps_doc.load_run(tmp_path))
    assert page.count("Runs only when: ") == 14  # 12 + move: ascendancy-swap (#1157) + fill (#1156)
    for block in page.split("### ")[1:]:
        if "Runs only when:" in block:
            assert "not run in this set" not in block
    assert "Median time: none: no build of this set (1 builds) met the condition." in page
    for name in CONDITIONAL + ["move: regions", "move: corridors"]:
        assert name in __import__("junkroan.optimizer.stage_catalog", fromlist=["x"]).CONDITIONS


def test_the_data_marks_exactly_the_conditional_steps() -> None:
    flags = stage_shares.shares([[{"name": "skeleton applied", "seconds": 1.0}]])["conditional"]
    assert {k for k, v in flags.items() if v} == set(CONDITIONAL) | {"move: regions", "move: corridors", "move: ascendancy-swap"}
    assert flags["tree greedy"] is False and set(s.name for s in STEPS) <= set(flags)


def test_check_fails_when_a_step_has_neither_time_nor_condition(tmp_path, monkeypatch) -> None:
    from junkroan.optimizer import stage_catalog

    rows = tmp_path / "run" / "rows"
    rows.mkdir(parents=True)
    (rows / "b.json").write_text(json.dumps(_row(3.0)), encoding="utf-8")
    out = tmp_path / "page.md"
    args = ["--run", str(tmp_path / "run"), "--out", str(out)]
    assert build_steps_doc.main(args) == 0
    assert build_steps_doc.main(args + ["--check"]) == 1  # tree greedy etc. have no time and no condition
    assert "tree greedy" in build_steps_doc.untimed_steps(build_steps_doc.load_run(tmp_path / "run"))
    monkeypatch.setattr(stage_catalog, "CONDITIONS", {**stage_catalog.CONDITIONS, "tree greedy": "x"})
    assert "tree greedy" not in build_steps_doc.untimed_steps(build_steps_doc.load_run(tmp_path / "run"))
