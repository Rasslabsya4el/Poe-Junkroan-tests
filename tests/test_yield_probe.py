"""#621 unit 4: the yield probes. Fake PoB only; no PobSession."""

from __future__ import annotations

import pytest
from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over
from test_cluster_step import FakeProbe as ClusterProbe
from test_cluster_step import run as cluster_run
from test_flask_step import gain as flask_gain
from test_flask_step import run as flask_run

from junkroan.optimizer import yield_probe
from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.yield_probe import BuildDeferred


@pytest.fixture(autouse=True)
def _disarmed():
    yield_probe.disarm()
    yield
    yield_probe.disarm()


def _loop(monkeypatch):
    pob = _Pob(1000.0)
    tree = _Tree(pob, [1001.0])
    loot = _Loot(pob, {"Gloves": [("g1", 1002.0)], "Boots": [("b1", 1003.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    return rig, rig.started()


PLAN = LoopPlan(seed=1, max_passes=4, max_seconds=600.0, min_gain=0.005, loot_n=5)


def test_disarmed_check_is_a_no_op():
    assert not yield_probe.armed()
    assert yield_probe.check("anything") is None


def test_armed_calls_the_callback_with_the_stage():
    seen = []
    yield_probe.arm(seen.append)
    assert yield_probe.armed()
    yield_probe.check("a")
    yield_probe.check("b")
    assert seen == ["a", "b"]
    yield_probe.disarm()
    yield_probe.check("c")
    assert seen == ["a", "b"]


def test_armed_with_restores_the_previous_state_even_on_exception():
    outer = []
    with yield_probe.armed_with(outer.append):
        with pytest.raises(RuntimeError):
            with yield_probe.armed_with(lambda s: (_ for _ in ()).throw(RuntimeError(s))):
                yield_probe.check("x")
        yield_probe.check("y")
        assert outer == ["y"]
    assert not yield_probe.armed()


def test_build_deferred_is_a_base_exception_with_stage_and_note():
    err = BuildDeferred("loop pass 1", "owner reserved")
    assert isinstance(err, BaseException) and not isinstance(err, Exception)
    assert (err.stage, err.note) == ("loop pass 1", "owner reserved")


def test_loop_probes_stage_boundary_pass_and_moves(monkeypatch):
    rig, result = _loop(monkeypatch)
    seen = []
    with yield_probe.armed_with(seen.append):
        rig.run(PLAN)
    assert "loop pass 1" in seen  # the pass probe
    assert seen.count("loop pass 1") >= 3  # the pass plus its moves
    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "loop pass 1"]


def test_stage_boundary_probe_sees_the_recorded_stage(monkeypatch):
    seen = []
    with yield_probe.armed_with(seen.append):
        rig, _result = _loop(monkeypatch)  # `started()` records "tree rebuilt on gear" through record_stage
    assert seen == ["tree rebuilt on gear"]


def test_a_deferral_at_a_loop_pass_propagates_unchanged(monkeypatch):
    rig, _result = _loop(monkeypatch)
    raised = BuildDeferred("loop pass 1")

    def cb(stage):
        if stage == "loop pass 1":
            raise raised

    with yield_probe.armed_with(cb):
        with pytest.raises(BuildDeferred) as info:
            rig.run(PLAN)
    assert info.value is raised


def test_a_deferral_at_a_stage_boundary_propagates_unchanged(monkeypatch):
    rig, _result = _loop(monkeypatch)
    raised = BuildDeferred("loop pass 1")

    def cb(stage):
        raise raised

    with yield_probe.armed_with(cb):
        with pytest.raises(BuildDeferred) as info:
            rig.record(rig.result, "x", 0.0)
    assert info.value is raised


def test_pipeline_run_probes_start_first_and_propagates_the_deferral():
    pipe = BuildPipeline.__new__(BuildPipeline)
    seen = []

    def cb(stage):
        seen.append(stage)
        raise BuildDeferred(stage)

    with yield_probe.armed_with(cb):
        with pytest.raises(BuildDeferred) as info:
            pipe.run(object())
    assert seen == ["start"] and info.value.stage == "start"


def test_a_no_op_recorder_changes_neither_outputs_nor_pob_calls(monkeypatch):
    def run_once(armed):
        rig, result = _loop(monkeypatch)
        if armed:
            with yield_probe.armed_with(lambda _s: None):
                outcome = rig.run(PLAN)
        else:
            outcome = rig.run(PLAN)
        pob = rig.pob
        return outcome.note, [(s.name, s.score_value, s.notes) for s in result.stages], pob.value, list(pob.loaded), list(pob.equipped)

    assert run_once(False) == run_once(True)


def test_flask_step_probes_per_slot_and_per_base():
    seen = []
    with yield_probe.armed_with(seen.append):
        flask_run(flask_gain)
    assert seen and set(seen) == {"flasks"}
    assert len(seen) > 5  # five slots plus the bases of each


def test_cluster_step_probes_per_cluster_and_per_socket_option():
    probe = ClusterProbe({100: 2, 101: 1}, {"large": 50.0, "medium": 10.0}, budget=4)
    seen = []
    with yield_probe.armed_with(seen.append):
        cluster_run(probe, count_max=1)
    assert set(seen) == {"clusters"} and len(seen) >= 3  # one cluster + two socket options
