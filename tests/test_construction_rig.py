"""The opt-in rig-first construction arm and its benchmark cutoff, without PoB."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.improvement_loop import ImprovementLoop
from junkroan.optimizer.judging import PobLanes
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.seeds import (
    PURPOSE_CONSTRUCT_GEAR,
    PURPOSE_CONSTRUCT_GEAR_PASSES,
    PURPOSE_CONSTRUCT_RIG_FINAL_GEAR,
    PURPOSE_CONSTRUCT_RIG_GEAR,
    derive_seed,
)
from junkroan.optimizer import pipeline as pipeline_module


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402


class _Pob:
    """The tree and scalar-stat surfaces construction needs."""

    def __init__(self) -> None:
        self.nodes: set[int] = set()
        self.events: list[tuple] = []
        self.fulldps_shortcut = False
        self.mean_parts = None

    def set_tree(self, *, class_id: str, ascendancy_id: str, ascendancy_nodes: list[int]) -> None:
        self.nodes = set(ascendancy_nodes)
        self.events.append(("set tree", class_id, ascendancy_id, tuple(sorted(self.nodes))))

    def add_nodes(self, nodes: list[int]) -> None:
        self.nodes.update(nodes)
        self.events.append(("add nodes", tuple(nodes)))

    def mutate_nodes(self, **_kwargs) -> dict:
        return {"points_used": len(self.nodes)}

    def stats(self, keys) -> dict:
        return {key: 0.0 for key in keys} | {"CombinedDPS": 100.0}

    @staticmethod
    def read_state() -> dict:
        return {"skills_state": {"socket_groups": []}}

    def export_xml(self) -> str:
        return f"<Build nodes={','.join(str(n) for n in sorted(self.nodes))}/>"


class _Skeleton:
    class_name = "Witch"
    ascendancy = "Elementalist"
    ascendancy_nodes = [1]
    keystones = [9]
    level = 10
    mode = "hit"
    main_link = ["Fireball"]
    main_part = "Fireball"
    gem_counts: dict[str, int] = {}
    rare_bases = {"Weapon 1": "Driftwood Wand"}
    uniques: dict[str, str] = {}
    sockets: dict[str, str] = {}
    pure_es = False
    forbid_keystones: list[str] = []
    scaling = None
    extra_groups: list = []
    utility_groups = 0

    def apply(self, pob: _Pob, **_kwargs) -> None:
        pob.set_tree(
            class_id=self.class_name,
            ascendancy_id=self.ascendancy,
            ascendancy_nodes=self.ascendancy_nodes,
        )
        pob.add_nodes(self.keystones)

    def refresh_minion_counts(self, _pob: _Pob, **_kwargs) -> dict:
        return {}

    def tune_minion_skills(self, _pob: _Pob, _score, **_kwargs) -> dict:
        return {}

    @staticmethod
    def flat_reservation_auras() -> list[str]:
        return []


class _Tree:
    instances: list["_Tree"] = []

    def __init__(self, pob: _Pob, objective: Objective, *, max_trials: int, **_kwargs) -> None:
        self.pob = pob
        self.objective = objective
        self.max_trials = max_trials
        self.graph = SimpleNamespace()
        self.history: list = []
        self.allocations: list[tuple[int, int, tuple[int, ...]]] = []
        self.invalidations = 0
        type(self).instances.append(self)

    def forbid(self, _names) -> None:
        pass

    def forbid_text(self, _texts) -> None:
        pass

    def allocate(self, points: int):
        self.allocations.append((points, self.max_trials, tuple(sorted(self.pob.nodes))))
        start = 100 + 10 * (len(self.allocations) - 1)
        self.pob.add_nodes(list(range(start, start + points)))
        return SimpleNamespace(stopped_reason="budget", points_spent=points)

    def invalidate_after_recovery(self) -> None:
        self.invalidations += 1


class _Loot:
    instances: list["_Loot"] = []

    def __init__(self, pob: _Pob, objective: Objective, _rails, **_kwargs) -> None:
        self.pob = pob
        self.objective = objective
        self.fills: list[tuple[int, int, int, tuple[int, ...]]] = []
        type(self).instances.append(self)

    def fill(self, _bases, *, passes: int, n: int, seed: int, **_kwargs) -> None:
        self.fills.append((passes, n, seed, tuple(sorted(self.pob.nodes))))


def _derived() -> SimpleNamespace:
    lane = SimpleNamespace(inputs={}, reasons={})
    return SimpleNamespace(conservative=lane, optimistic=SimpleNamespace(inputs={}, reasons={}), stack_caps={}, ailment_stack_caps={})


class _StubLanes(PobLanes):
    """The session's own lane source, with the lane read answering `_derived()` and the write doing nothing."""

    def read(self):
        return _derived()

    def write(self, _skeleton, _lanes) -> None:
        return None


def _run_construction(monkeypatch: pytest.MonkeyPatch, construction: str):
    _Tree.instances = []
    _Loot.instances = []
    monkeypatch.setattr(pipeline_module, "TreeOptimizer", _Tree)
    monkeypatch.setattr(pipeline_module, "LootGear", _Loot)
    monkeypatch.setattr(pipeline_module, "objective_for", lambda _rails, _skill, objective, **_kwargs: objective)
    # the opening's ramp and self-cost live in the judging context (optimizer/judging.py), which
    # imports them from their own modules at the call
    monkeypatch.setattr("junkroan.optimizer.ramp.context_changes", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("junkroan.optimizer.ramp.with_ramp", lambda objective, **_kwargs: objective)
    monkeypatch.setattr("junkroan.optimizer.self_cost.context_for", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("junkroan.optimizer.self_cost.with_self_cost", lambda objective, _context: objective)
    monkeypatch.setattr(pipeline_module, "self_cost_tree_patterns", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(pipeline_module, "encode_import_code", lambda xml: f"code:{xml}")
    monkeypatch.setattr("junkroan.search.hypothesis.active_gems", lambda: {})

    rails = SimpleNamespace(
        gems=SimpleNamespace(level=18, quality=0, main_quality=0),
        gear=SimpleNamespace(construction_best_of_n=600),
        forbidden_node_text=(),
        utility_max_groups=0, attribute_plus30_nodes_max=1,
    )
    pob = _Pob()
    pipeline = BuildPipeline(pob, rails, objective=Objective(maximize="CombinedDPS"), construction=construction)
    pipeline._rails_identity = lambda _skeleton: None
    judging = pipeline.judging
    judging.lanes = _StubLanes(pob)  # the lanes read as `_derived()`, their write a no-op
    judging.refresh_castability = lambda *_args, **_kwargs: None
    judging.post_holders = lambda *_args, **_kwargs: None
    judging.rejudge = lambda *_args, **_kwargs: judging.objective
    judging.reads.main_group = lambda: ([], False, ())
    pipeline._rebuild_tree = lambda _skeleton, _tree, _points: "rebuilt"
    monkeypatch.setattr(ImprovementLoop, "run", lambda *_args, **_kwargs: pytest.fail("construction-only entered the improvement loop"))

    result = pipeline.run(
        _Skeleton(),
        tree_points=10,
        tree_max_trials=17,
        construction_only=True,
    )
    return result, pob, _Tree.instances, _Loot.instances


def test_classic_construction_keeps_the_existing_stage_order(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _pob, trees, loots = _run_construction(monkeypatch, "classic")

    assert [stage.name for stage in result.stages] == [
        "skeleton applied",
        "config (conservative lane)",
        "gear pass 1 (empty tree)",
        "tree greedy",
        "gear pass 2 (with tree)",
        "tree rebuilt on gear",
    ]
    assert trees[0].allocations == [(8, 17, (1, 9))]
    assert loots[0].fills == [
        (1, 600, derive_seed(1, PURPOSE_CONSTRUCT_GEAR), (1, 9)),
        (2, 600, derive_seed(1, PURPOSE_CONSTRUCT_GEAR_PASSES), tuple(range(1, 2)) + (9,) + tuple(range(100, 108))),
    ]


def test_rig_first_uses_the_rig_only_for_gear_pass_one(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _pob, trees, loots = _run_construction(monkeypatch, "rig-first")

    assert [stage.name for stage in result.stages] == [
        "skeleton applied",
        "config (conservative lane)",
        "rig gear",
        "rig tree",
        "gear pass 1 (rig tree)",
        "tree greedy",
        "gear pass 2 (with tree)",
        "tree rebuilt on gear",
    ]
    assert trees[0].allocations == [
        (5, 300, (1, 9)),
        (8, 17, (1, 9)),
    ], "the ordinary greedy starts after the temporary rig tree was reset"
    assert trees[0].invalidations == 1
    assert loots[0].fills == [
        (1, 40, derive_seed(1, PURPOSE_CONSTRUCT_RIG_GEAR), (1, 9)),
        (1, 600, derive_seed(1, PURPOSE_CONSTRUCT_RIG_FINAL_GEAR), (1, 9, 100, 101, 102, 103, 104)),
        (2, 600, derive_seed(1, PURPOSE_CONSTRUCT_GEAR_PASSES), (1, 9, 110, 111, 112, 113, 114, 115, 116, 117)),
    ]


def test_construction_only_requires_and_ends_at_the_tree_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _pob, _trees, _loots = _run_construction(monkeypatch, "classic")

    assert result.stages[-1].name == "tree rebuilt on gear"
    assert result.final_stats["CombinedDPS"] == 100.0
    assert result.import_code.startswith("code:<Build")

    # the rails carry their gem levels: the judging context binds them when the pipeline is built
    pipeline = BuildPipeline(object(), SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0)),
                             objective=Objective(maximize="CombinedDPS"))
    with pytest.raises(ValueError, match="construction_only requires"):
        pipeline.run(SimpleNamespace(), construction_only=True, rebuild_tree=False)


def _construction_row(slug: str, kwargs: dict) -> dict:
    return {
        "ok": True,
        "slug": slug,
        "seed": 1,
        "gear_mode": "loot",
        "variant": "",
        "seconds": 1.0,
        "points": 10,
        "stat": "CombinedDPS",
        "author_raw": 100.0,
        "author_lane": 100.0,
        "author_ramp": None,
        "author_gem_levels": {"level": 18.0, "quality": 0.0},
        "author_gems_normalized": 0,
        "author_flat_reservation_auras_kept_low": 0,
        "author_life": 100.0,
        "author_ehp": 100.0,
        "author_ehp_raw": 100.0,
        "author_maxhit": 100.0,
        "ours_maxhit": 100.0,
        "author_mana_unreserved": 10.0,
        "ours_mana_unreserved": 10.0,
        "aura_levels": {},
        "ours": 120.0,
        "ours_optimistic": 120.0,
        "ours_life": 100.0,
        "ours_ehp": 100.0,
        "ours_ramp": None,
        "ratio_lane": 1.2,
        "ratio_raw": 1.2,
        "keystones": ["A test keystone"],
        "audit": [],
        "audit_errors": 0,
        "fixed_point_gain": 0.0,
        "fixed_point_note": "",
        "castability_calls": 0,
        "castability_seconds": 0.0,
        "dropped_moves": [],
        "stages": [{"name": "tree rebuilt on gear", "seconds": 1.0, "value": 120.0, "violation": 0.0, "notes": ""}],
        "summary": "construction summary",
        "import_code": "test import",
        "xml": "<Build/>",
    }


def test_benchmark_construction_only_writes_one_post_rebuild_row_without_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls: list[dict] = []
    monkeypatch.setattr(benchmark, "ROOT", root)
    monkeypatch.setattr(benchmark, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(benchmark.time, "strftime", lambda _format: "20260920-0000")
    monkeypatch.setattr(benchmark, "_pob_build_dir", lambda _stamp: tmp_path / "not-a-pob-build-directory")

    def run_one(slug: str, **kwargs) -> dict:
        calls.append(kwargs)
        return _construction_row(slug, kwargs)

    monkeypatch.setattr(benchmark, "run_one", run_one)
    monkeypatch.setattr(sys, "argv", [
        "benchmark.py", "alpha", "--workers", "1", "--construction", "rig-first",
        "--construction-only", "--tag", "rig",
    ])

    assert benchmark.main() == 0
    assert len(calls) == 1
    assert calls[0]["construction"] == "rig-first"
    assert calls[0]["construction_only"] is True

    rows = json.loads((root / "artifacts" / "benchmark" / "20260920-0000-rig" / "results.json").read_text(encoding="utf-8"))
    assert rows[0]["stages"][-1]["name"] == "tree rebuilt on gear"
