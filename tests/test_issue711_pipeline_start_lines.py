"""#711 unit 2: `BuildPipeline.run` writes a start line before each construction / finish step and a skipped line for a
conditional step that does not run, PoB-free. The lines are log only: the stage names are the run's own."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer import pipeline as pipeline_module
from junkroan.optimizer.improvement_loop import ImprovementLoop
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.stage_catalog import STEPS, parse_log_line, skipped_line, start_line, step_of

from test_construction_rig import _Loot, _Pob, _Skeleton, _StubLanes, _Tree


class _Auras(_Skeleton):
    def __init__(self) -> None:
        self.aura_levels: dict[str, int] = {}

    def apply_skills(self, _pob, **_kwargs) -> None:
        pass

    @staticmethod
    def flat_reservation_auras() -> list[str]:
        return ["Hatred"]


class _RefineTree(_Tree):
    def refine(self, **_kwargs) -> None:
        pass


class _GearLoot(_Loot):
    current_raw: dict = {}  # no amulet: the anoint step reports skipped
    uniques: dict = {}


def _run(monkeypatch: pytest.MonkeyPatch, *, construction: str = "classic", skeleton=None, **kwargs):
    _Tree.instances = []
    _Loot.instances = []
    monkeypatch.setattr(pipeline_module, "TreeOptimizer", _RefineTree)
    monkeypatch.setattr(pipeline_module, "LootGear", _GearLoot)
    monkeypatch.setattr(pipeline_module, "objective_for", lambda _rails, _skill, objective, **_kw: objective)
    monkeypatch.setattr("junkroan.optimizer.ramp.context_changes", lambda *_a, **_kw: {})
    monkeypatch.setattr("junkroan.optimizer.ramp.with_ramp", lambda objective, **_kw: objective)
    monkeypatch.setattr("junkroan.optimizer.self_cost.context_for", lambda *_a, **_kw: None)
    monkeypatch.setattr("junkroan.optimizer.self_cost.with_self_cost", lambda objective, _context: objective)
    monkeypatch.setattr(pipeline_module, "self_cost_tree_patterns", lambda *_a, **_kw: ())
    monkeypatch.setattr(pipeline_module, "encode_import_code", lambda xml: f"code:{xml}")
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {})

    rails = SimpleNamespace(
        gems=SimpleNamespace(level=18, quality=0, main_quality=0),
        gear=SimpleNamespace(construction_best_of_n=600, clusters=SimpleNamespace(count_max=0), jewels=SimpleNamespace(count_max=0)),
        forbidden_node_text=(), utility_max_groups=0, attribute_plus30_nodes_max=1,
    )
    pob = _Pob()
    lines: list[str] = []
    pipeline = BuildPipeline(pob, rails, objective=Objective(maximize="CombinedDPS"), construction=construction, log=lines.append)
    pipeline._rails_identity = lambda _skeleton: None
    judging = pipeline.judging
    judging.lanes = _StubLanes(pob)
    judging.refresh_castability = lambda *_a, **_kw: None
    judging.post_holders = lambda *_a, **_kw: None
    judging.rejudge = lambda *_a, **_kw: judging.objective
    judging.reads.main_group = lambda: ([], False, ())
    pipeline._rebuild_tree = lambda _skeleton, _tree, _points: "rebuilt"
    pipeline._jewel_repick = lambda *_a, **_kw: None
    pipeline.improve = lambda *_a, **_kw: SimpleNamespace(stopped="", note="loop stub")

    def finish(result, _skeleton, t_all, **_kw):  # `_finish` itself is not under test: its first act is the start line
        pipeline._step_start("config (final lanes)")
        pipeline._record(result, "config (final lanes)", t_all)
        return result

    pipeline._finish = finish
    monkeypatch.setattr(ImprovementLoop, "run", lambda *_a, **_kw: pytest.fail("the loop stub was bypassed"))
    result = pipeline.run(skeleton or _Skeleton(), tree_points=10, tree_max_trials=17, **kwargs)
    return result, lines


def _marks(lines: list[str]) -> list[tuple[str, str]]:
    return [(kind, name) for kind, name in (parse_log_line(line) for line in lines) if kind in ("start", "skipped")]


def _index(name: str) -> int:
    return next(i for i, step in enumerate(STEPS) if step.name == name)


def test_full_run_starts_every_step_in_catalog_order_before_its_stage_line(monkeypatch: pytest.MonkeyPatch) -> None:
    result, lines = _run(monkeypatch, skeleton=_Auras(), pick_utilities=True)
    marks = _marks(lines)
    started = [name for kind, name in marks if kind == "start"]
    assert [_index(n) for n in started] == sorted(_index(n) for n in started), started
    assert started == [
        "skeleton applied", "config (conservative lane)", "gear pass 1 (empty tree)", "flat-reservation aura levels",
        "tree greedy", "gear pass 2 (with tree)", "tree rebuilt on gear", "config (final lanes)",
    ]
    skipped = [name for kind, name in marks if kind == "skipped"]
    assert {"rig gear", "rig tree", "gear pass 1 (rig tree)", "supports re-picked (no number)", "tree seed toward <stat>",
            "supports re-picked", "utility links", "tree refine", "anoint", "flasks", "clusters", "jewels", "anoint re-pick"} <= set(skipped)
    for stage in result.stages:
        starts = [i for i, line in enumerate(lines) if line == start_line(stage.name)]
        summaries = [i for i, line in enumerate(lines) if parse_log_line(line)[0] is None and stage.name in line]
        assert len(starts) == 1, stage.name
        assert starts[0] < summaries[0], stage.name
        assert step_of(stage.name) is not None


def test_rig_first_marks_the_classic_gear_pass_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, lines = _run(monkeypatch, construction="rig-first")
    marks = _marks(lines)
    assert [n for k, n in marks if k == "start"][2:5] == ["rig gear", "rig tree", "gear pass 1 (rig tree)"]
    assert ("skipped", "gear pass 1 (empty tree)") in marks
    assert ("skipped", "rig gear") not in marks


def test_screen_run_marks_its_skipped_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, lines = _run(monkeypatch, screen=True)
    marks = _marks(lines)
    assert ("start", "tree refine") in marks
    for name in ("tree rebuilt on gear", "anoint", "flasks", "clusters", "jewels", "supports re-picked", "utility links", "anoint re-pick"):
        assert ("skipped", name) in marks, name
    assert ("start", "tree rebuilt on gear") not in marks


def test_rebuild_tree_false_marks_rebuild_clusters_and_jewels_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, lines = _run(monkeypatch, rebuild_tree=False)
    marks = _marks(lines)
    for name in ("tree rebuilt on gear", "clusters", "jewels", "tree refine"):
        assert ("skipped", name) in marks, name
    assert ("start", "tree rebuilt on gear") not in marks
    assert ("start", "config (final lanes)") in marks


def test_the_lines_change_no_stage_and_no_pob_call(monkeypatch: pytest.MonkeyPatch) -> None:
    result, lines = _run(monkeypatch, skeleton=_Auras())
    with monkeypatch.context() as quiet:
        quiet.setattr(BuildPipeline, "_step_start", lambda self, name: None)
        quiet.setattr(BuildPipeline, "_step_skipped", lambda self, *names: None)
        quiet_result, quiet_lines = _run(quiet, skeleton=_Auras())
    assert [s.name for s in result.stages] == [s.name for s in quiet_result.stages]
    assert [s.score_value for s in result.stages] == [s.score_value for s in quiet_result.stages]
    assert [parse_log_line(line)[0] for line in quiet_lines if parse_log_line(line)[0]] == []
    assert len(lines) > len(quiet_lines)
    assert skipped_line("rig gear") in lines
