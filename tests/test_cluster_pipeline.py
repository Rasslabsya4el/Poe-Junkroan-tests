"""#433 unit 6: the cluster step wired into the pipeline.

Plain tests (a fake session, no PoB): `_jewel_args` carries the cluster raw and its allocation (the path to the socket
and the inner nodes) into every `set_tree`; `_drop_stray_jewels` drops a cluster whose socket ended unallocated with
its carried state; the end re-pick leaves cluster sockets alone; `_cluster_step` writes one `clusters` stage with
`cluster_log_line` per placed cluster and loads the build back when the lanes take the gain away; `replay_bench` knows
the `cluster` move.

`pob` tests (row 5, the witness): a short Stormbrand build of #434 (the setup of `tests/test_jewel_pipeline.py`) with
the cluster step before the jewel step: the report of the step (clusters placed with socket / size / enchant / notables /
points, Score before -> after, trials, wall time), the same cluster and inner allocation in `read_state` after the
loop's tree rebuild, `points_over` 0, audit errors 0.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer import pipeline as pipeline_module
from junkroan.optimizer.cluster_lines import ClusterCandidate, ClusterEnchant
from junkroan.optimizer.cluster_step import ClusterStepResult, PlacedCluster
from junkroan.optimizer.jewel_step import PlacedJewel
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import ClusterRails
from junkroan.pob.session import PobSession, decode_import_code, is_cluster_jewel_raw
from tests.test_jewel_pipeline import FakePob, Line, _pipeline, _placed, _result, needs_pob

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
TRICKSTER = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_326" / "early" / "trickster_blight_of_contagion.pob.txt"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CLUSTER_RAW = "Rarity: RARE\nDay-1 Large Cluster\nLarge Cluster Jewel\nItem Level: 72\nCluster Jewel Node Count: 12"
ENCH = ClusterEnchant("large", "affliction_chaos_damage", "chaos_damage", ("Added Small Passive Skills grant: 12% increased Chaos Damage",))


def _cluster_placed(socket: int, path: tuple[int, ...] = (), **kw) -> PlacedCluster:
    return PlacedCluster(socket_id=socket, candidate=ClusterCandidate("large", ENCH, ("Wicked Pall",), 12), score_before=100.0, score_after=150.0,
                         measured=40, path=path, seconds=3.0, **kw)


def _with_clusters(p: BuildPipeline, socket: int = 9, path: tuple[int, ...] = (7, 9, 70001, 70002)) -> None:
    p._clusters = {socket: CLUSTER_RAW}
    p._cluster_nodes = {socket: path}
    p._cluster_placed = [_cluster_placed(socket, path)]


# -- set_tree carries the clusters and their allocation ------------------------------------------------------------


def test_jewel_args_carry_clusters_first_with_their_allocation() -> None:
    p = _pipeline(FakePob())
    assert p._jewel_args() == {}
    p._jewels = {5: "plain jewel"}
    assert p._jewel_args() == {"jewels": {5: "plain jewel"}}  # no cluster: the call the jewel step alone made
    _with_clusters(p)
    args = p._jewel_args()
    assert list(args["jewels"]) == [9, 5] and args["jewels"][9] == CLUSTER_RAW
    assert args["nodes"] == [7, 9, 70001, 70002]
    p._jewels = {}
    assert p._jewel_args() == {"jewels": {9: CLUSTER_RAW}, "nodes": [7, 9, 70001, 70002]}


def test_reset_and_rebuild_pass_the_cluster_and_its_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    pob.mutate_nodes = lambda **_k: {"points_used": 0}
    p = _pipeline(pob)
    _with_clusters(p)
    p.judging.rejudge = lambda *_a, **_k: p.objective
    score = p.objective.score({"CombinedDPS": 100.0})
    tree = SimpleNamespace(objective=p.objective, history=[], repair_estimate_mode="sum", current_score=lambda: (score, None), invalidate_after_recovery=lambda **_k: None,
                           allocate=lambda *_a, **_k: None, refine=lambda **_k: None)
    skeleton = SimpleNamespace(class_name="Templar", ascendancy="Inquisitor", ascendancy_nodes=[], keystones=[], scaling=None)
    p._rebuild_tree(skeleton, tree, 10)
    p._reset_construction_tree(skeleton, tree)
    assert len(pob.set_tree_calls) == 3  # sum, cover, reset
    for call in pob.set_tree_calls:
        assert call["jewels"] == {9: CLUSTER_RAW} and call["nodes"] == [7, 9, 70001, 70002]


def test_points_used_is_pobs_count_with_the_inner_nodes() -> None:
    pob = FakePob()
    outer, inner = [1, 2, 3, 7, 9], [70001, 70002, 70003, 70004]
    pob.mutate_nodes = lambda **_k: {"points_used": len(outer) + len(inner)}  # PoB's CountAllocNodes counts every allocNode, inner ones too
    p = _pipeline(pob)
    assert p._points_used() == 9


# -- _finish / _drop_stray_jewels --------------------------------------------------------------------------------------


def test_drop_stray_drops_an_orphan_cluster_with_its_state_and_keeps_the_allocated_one() -> None:
    pob = FakePob(allocated=(1, 7, 9, 70001, 70002))
    pob.held = {9: CLUSTER_RAW, 20: CLUSTER_RAW.replace("Large", "Medium")}  # 20: its socket is no longer allocated
    p = _pipeline(pob)
    p._clusters = dict(pob.held)
    p._cluster_nodes = {9: (7, 9, 70001, 70002), 20: (20, 70101)}
    p._cluster_placed = [_cluster_placed(9), _cluster_placed(20)]
    assert p._drop_stray_jewels() == [20]  # a build with clusters and no step jewel is touched
    assert pob.removed == [20] and set(pob.held) == {9}
    assert set(p._clusters) == {9} and set(p._cluster_nodes) == {9} and [c.socket_id for c in p._cluster_placed] == [9]
    assert p._jewel_args()["nodes"] == [7, 9, 70001, 70002]  # nothing of the orphan is carried on
    assert p._drop_stray_jewels() == []


def test_finish_drops_the_orphan_cluster_before_anything_else() -> None:
    class Stop(Exception):
        pass

    pob = FakePob(allocated=(1,))
    pob.held = {9: CLUSTER_RAW}
    p = _pipeline(pob)
    _with_clusters(p)

    def boom(_keys):
        assert pob.held == {}, "the orphan cluster must be gone before `_finish` measures or exports anything"
        raise Stop

    pob.stats = boom
    with pytest.raises(Stop):
        p._finish(_result(), SimpleNamespace(), time.perf_counter())


def test_the_end_repick_leaves_cluster_sockets_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob(value=100.0, allocated=(1, 5, 9, 70001))
    pob.held = {5: "life", 9: CLUSTER_RAW}
    touched: list[int] = []

    class Probe:
        def score(self):
            return pob.value

        def remove_jewel(self, socket):
            touched.append(socket)
            pob.held.pop(socket, None)

        def put_jewel(self, socket, candidate):
            touched.append(socket)
            pob.held[socket] = candidate.id

    p = _pipeline(pob)
    p._jewel_probe = lambda *_a, **_k: Probe()
    p.judging.rejudge = lambda *_a, **_k: p.objective
    p._jewels = {5: "life"}
    p._jewel_placed = [PlacedJewel(5, Line("life"), 90.0, 100.0, 2, ((Line("life"), 100.0),))]
    _with_clusters(p, 9, (7, 9, 70001))
    result = _result()
    p._jewel_repick(result, SimpleNamespace(keystones=[]), SimpleNamespace(), 10, 6)
    assert 9 not in touched and pob.held[9] == CLUSTER_RAW
    assert [m["move"] for m in result.moves] == ["jewel socket 5"]  # one row per jewel, none for the cluster
    assert p._clusters == {9: CLUSTER_RAW} and p._cluster_nodes == {9: (7, 9, 70001)} and [c.socket_id for c in p._cluster_placed] == [9]


# -- the step -------------------------------------------------------------------------------------------------------------


def _cluster_pipeline(pob: FakePob, monkeypatch: pytest.MonkeyPatch, *, count_max: int = 2) -> BuildPipeline:
    p = _pipeline(pob)
    p.rails = SimpleNamespace(gear=SimpleNamespace(clusters=ClusterRails(count_max=count_max, sizes=["large", "medium"], passives={"large": 12, "medium": 6}), item_level=70,
                                                    wishlist=SimpleNamespace(item_level_for=lambda slot: 72)))
    monkeypatch.setattr(pipeline_module, "cluster_enchants", lambda size: (ENCH,))
    pob.cluster_graph = lambda _socket: []
    p._jewel_probe = lambda *_a, **_k: object()
    p.judging.rejudge = lambda *_a, **_k: setattr(pob, "value", p._after_lanes) or p.objective
    p._after_lanes = 140.0
    return p


def _fake_step(pob: FakePob, monkeypatch: pytest.MonkeyPatch, value_with_cluster: float, seen: dict) -> None:
    placed = _cluster_placed(9, (7, 9, 70001, 70002))

    def fake(_probe, enchants, notables_for, make_candidate, *, count_max, notables_max, screen_keep, socket_size, **_k):
        seen.update(count_max=count_max, notables_max=notables_max, screen_keep=screen_keep, enchants=enchants)
        seen["candidate"] = make_candidate("large", ENCH, ("Wicked Pall",))
        seen["socket_size"] = socket_size(5)
        pob.value, pob.held = value_with_cluster, {9: CLUSTER_RAW}
        return ClusterStepResult(placed=[placed], score_before=100.0, score_after=value_with_cluster, trials=123, seconds=75.0, stopped_reason="count_max 2 reached")

    monkeypatch.setattr(pipeline_module, "run_cluster_step", fake)


def _step_args():
    node = SimpleNamespace(expansion_size=2)
    tree_full = SimpleNamespace(graph=SimpleNamespace(node=lambda nid: node if nid == 5 else None, is_inner_socket=lambda nid: False))
    loot = SimpleNamespace(item_level_for=lambda slot: 72)
    return SimpleNamespace(keystones=[]), loot, tree_full


def test_the_step_is_recorded_and_its_state_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    pob.cluster_graph = lambda _s: []
    p = _cluster_pipeline(pob, monkeypatch)
    seen: dict = {}
    _fake_step(pob, monkeypatch, 150.0, seen)
    skeleton, loot, tree_full = _step_args()
    result = _result()
    p._cluster_step(result, skeleton, loot, tree_full, 10, 6)
    assert seen["count_max"] == 2 and seen["notables_max"] == 2 and seen["screen_keep"] == 6 and set(seen["enchants"]) == {"large", "medium"}
    assert seen["candidate"].passives == 12 and seen["socket_size"] == 2  # the rails' passives, the tree node's expansion size
    assert p._clusters == {9: CLUSTER_RAW} and p._cluster_nodes == {9: (7, 9, 70001, 70002)} and [c.socket_id for c in p._cluster_placed] == [9]
    assert pob.loaded == []
    stage = result.stages[-1]
    assert stage.name == "clusters"
    assert "cluster: socket 9 large 'affliction_chaos_damage' + Wicked Pall" in stage.notes
    assert "1 placed" in stage.notes and "Score 100 -> 150" in stage.notes and "123 trials" in stage.notes and "75 s" in stage.notes, stage.notes
    assert any(line.startswith("cluster: socket 9") for line in p.logged)
    assert not any("reverted" in line for line in p.logged)


def test_the_step_is_loaded_back_when_the_lanes_take_the_gain_away(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    p = _cluster_pipeline(pob, monkeypatch)
    p._after_lanes = 90.0
    _fake_step(pob, monkeypatch, 150.0, {})
    skeleton, loot, tree_full = _step_args()
    result = _result()
    p._cluster_step(result, skeleton, loot, tree_full, 10, 6)
    assert pob.loaded == ["xml-0"]
    assert p._clusters == {} and p._cluster_nodes == {} and p._cluster_placed == [] and p._jewel_args() == {}
    assert any("clusters: reverted (100 -> 90)" in line for line in p.logged), p.logged
    assert "reverted" in result.stages[-1].notes


def test_the_step_with_nothing_placed_records_one_stage_and_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pob = FakePob()
    p = _cluster_pipeline(pob, monkeypatch)
    monkeypatch.setattr(pipeline_module, "run_cluster_step", lambda *_a, **_k: ClusterStepResult(score_before=100.0, score_after=100.0, trials=57, seconds=5.0,
                                                                                                stopped_reason="cluster 1: best option does not beat the build"))
    skeleton, loot, tree_full = _step_args()
    result = _result()
    p._cluster_step(result, skeleton, loot, tree_full, 10, 6)
    assert result.stages[-1].name == "clusters" and "0 placed" in result.stages[-1].notes and "57 trials" in result.stages[-1].notes
    assert p._jewel_args() == {} and pob.loaded == []


def test_the_step_is_skipped_without_cluster_support_or_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "run_cluster_step", lambda *_a, **_k: pytest.fail("the step must not run"))
    skeleton, loot, tree_full = _step_args()
    p = _cluster_pipeline(FakePob(), monkeypatch, count_max=0)
    p._cluster_step(_result(), skeleton, loot, tree_full, 10, 6)
    bare = FakePob()
    q = _cluster_pipeline(bare, monkeypatch)
    q.pob = SimpleNamespace(stats=bare.stats)  # a session that cannot hold jewels
    q._cluster_step(_result(), skeleton, loot, tree_full, 10, 6)


def test_the_cluster_step_runs_before_the_jewel_step() -> None:
    source = Path(pipeline_module.__file__).read_text(encoding="utf-8")
    assert source.index("self._cluster_step(result, skeleton, loot, tree_full") < source.index("self._jewel_step(result, skeleton, tree_full") < source.index("repick_supports and not screen")


def test_replay_bench_has_the_cluster_move() -> None:
    import replay_bench

    assert "cluster" in replay_bench.LEGAL_MOVES and replay_bench.validate_move("cluster") == "cluster"


# -- PoB: the witness (row 5) ---------------------------------------------------------------------------------------------


def _build_and_report(xml: str, run_id: str) -> dict:
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.audit import audit_build
    from junkroan.optimizer.jewel_probe import PobJewelProbe
    from junkroan.optimizer.objective import Objective
    from junkroan.optimizer.rails import Rails, max_passive_points
    from junkroan.optimizer.tree_graph import TreeGraph

    rails = Rails.load()
    rails = dataclasses.replace(rails, gear=dataclasses.replace(rails.gear, jewels=dataclasses.replace(rails.gear.jewels, count_max=1)))  # the regular jewel step is #434's: one jewel keeps the run short
    lines: list[str] = []
    with PobSession(run_id=run_id, artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        skeleton = skeleton_from_xml(xml, pob=pob)
        pipeline = BuildPipeline(pob, rails, log=lines.append)
        started = time.perf_counter()
        result = pipeline.run(skeleton, loot_n=20, gear_passes=1, gear_mode="wishlist", pick_utilities=False, tree_max_trials=60,
                              loop_max_passes=1, loop_max_seconds=60.0, fixed_point_check=False)
        elapsed = time.perf_counter() - started
        held = pob.socketed_jewels()
        state = pob.read_state()["tree_state"]
        allocated = {int(n) for n in state["user_allocated_node_ids"]}
        extra_points = int(pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)  # the budget the pipeline spends to (`_spend_extra_points`: PoB's level rule + ExtraPoints), not the level rule alone
        probe = PobJewelProbe(pob, lambda: Objective(maximize="CombinedDPS"), TreeGraph.load(), points=max_passive_points(skeleton.level, extra_points))
        graphs = {socket: [n.id for n in probe.cluster_graph(socket)] for socket, raw in held.items() if is_cluster_jewel_raw(raw)}
        points_over = probe.points_over()
        findings = audit_build(pob, rails=rails, objective=pipeline.objective, skeleton=skeleton)
        carried = dict(pipeline._cluster_nodes)
        clusters_state = list(pipeline._cluster_placed)
    return dict(lines=lines, result=result, held=held, state=state, allocated=allocated, graphs=graphs, elapsed=elapsed, 
                findings=findings, carried=carried, placed=clusters_state, points_over=points_over, extra_points=extra_points)


def _print_report(case: str, got: dict) -> None:
    from junkroan.report_format import human_duration

    stages = [s for s in got["result"].stages if s.name in ("tree rebuilt on gear", "clusters", "jewels")]
    print(f"\n[{case}] short build {human_duration(got['elapsed'])}; stages: {[s.name for s in got['result'].stages]}")
    for stage in stages:
        print(f"  {stage.name}: {stage.notes}")
    for placed in got["placed"]:
        c = placed.candidate
        print(f"  placed: socket {placed.socket_id} size {c.size} enchant {c.enchant.id} notables {list(c.notables)} points {len(placed.path)} "
              f"Score {placed.score_before:.6g} -> {placed.score_after:.6g}, {placed.measured} measured, {human_duration(placed.seconds)}")
    print(f"  clusters in the export: {sorted(got['graphs'])}; points_over {got['points_over']} (budget with ExtraPoints {got['extra_points']}); audit errors: {[str(f) for f in got['findings'] if f.severity == 'error']}")


def _assert_witness(got: dict, *, want_cluster: bool, audit_clean: bool = True) -> None:
    result, state, allocated = got["result"], got["state"], got["allocated"]
    names = [s.name for s in result.stages]
    assert "clusters" in names and "jewels" in names and names.index("clusters") < names.index("jewels")
    stage = next(s for s in result.stages if s.name == "clusters")
    assert "trials" in stage.notes and "Score" in stage.notes and "placed" in stage.notes
    held_clusters = {socket for socket, raw in got["held"].items() if is_cluster_jewel_raw(raw)}
    in_state = {int(e["node_id"]) for e in state.get("cluster_jewel_items") or []}
    assert in_state == held_clusters == set(got["carried"])
    assert len(held_clusters) <= 2 and len(got["placed"]) == len(held_clusters)
    if want_cluster:
        assert held_clusters, "a cluster pays on this build"
    for socket in held_clusters:
        assert socket in allocated
        assert set(got["carried"][socket]) <= allocated, "the carried path and inner nodes are all allocated in read_state"
        inner = set(got["graphs"][socket])
        assert inner & allocated, "an inner node of the cluster is allocated"
    assert got["points_over"] <= 0, got["points_over"]
    if audit_clean:
        assert not [f for f in got["findings"] if f.severity == "error"], got["findings"]


@needs_pob
def test_short_stormbrand_build_runs_the_cluster_step_before_the_jewels() -> None:
    xml = decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip())
    got = _build_and_report(xml, "test-cluster-pipeline")
    _print_report("stormbrand", got)
    _assert_witness(got, want_cluster=False)


@needs_pob
def test_short_trickster_build_runs_the_cluster_step() -> None:
    """The second case, for a build whose author runs a Large cluster at 32763. The short build ends infeasible
    (pob-433, j-20261003-1720-594d: ManaUnreserved -233, viol 3.616 after `tree rebuilt on gear`), so no cluster pays
    here and none is required; the witness that a paying cluster is kept is `tests/test_cluster_witness_pob.py` on the
    author's own (feasible) tree. Here: the stage runs, and whatever is placed is carried and within the budget. The
    audit is not asserted clean: its errors (ManaUnreserved -233, pob-433c j-20261003-2022-89ab, 0 clusters placed) stand
    before the cluster stage, so they are the short build's, not the step's."""

    xml = decode_import_code(TRICKSTER.read_text(encoding="utf-8").strip())
    got = _build_and_report(xml, "test-cluster-pipeline-trickster")
    _print_report("trickster", got)
    _assert_witness(got, want_cluster=False, audit_clean=False)


def test_day1_rails_have_no_cluster_jewels_and_the_step_never_reaches_pob(monkeypatch: pytest.MonkeyPatch) -> None:
    """#602: day 1 carries count_max 0; the real day-1 rails skip the step, so evaluated(cluster jewel) = 0."""

    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.trace import TRACE

    day1 = Rails.load().gear.clusters
    assert day1.count_max == 0 and day1.sizes == []
    monkeypatch.setattr(pipeline_module, "run_cluster_step", lambda *_a, **_k: pytest.fail("the step must not run"))
    skeleton, loot, tree_full = _step_args()
    pob = FakePob()
    p = _cluster_pipeline(pob, monkeypatch)
    p.rails.gear.clusters = day1
    puts: list = []
    pob.put_jewel = lambda *a, **k: puts.append(a)
    p._cluster_step(_result(), skeleton, loot, tree_full, 10, 6)
    assert puts == []
    assert not any(k.startswith("cluster") for k in getattr(TRACE, "evaluated", {}) or {})
