"""#189 rule 2: a construction stage record is written after a rejudge of the build it records.

Driving the whole construction method needs PoB, a tree graph and the gear filler, far more than ~150 lines of
fakes, so the record helper is driven with fakes (the order of calls, the recorded value) and the construction
method's own source is checked by its AST: which record each named stage uses, and what stands between the
tree greedy record and gear pass 2's fill.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from types import SimpleNamespace

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.search.skeleton import Skeleton

REJUDGED_BY_HELPER = ("tree seed toward", "tree greedy", "tree rebuilt on gear", "tree refine")


class _Pob:
    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.state = {"CombinedDPS": 100.0, "Life": 5000.0}
        self.inputs: dict = {}

    def config_inputs(self) -> dict:
        return dict(self.inputs)

    def stats(self, keys):
        self.calls.append("stats")
        return {key: self.state.get(key, 0.0) for key in keys}


def _pipeline(inputs_after: dict | None = None):
    calls: list = []
    pob = _Pob(calls)
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob = pob
    pipeline.log = lambda message: None

    def rejudge(skeleton):
        calls.append("rejudge")
        pob.state["CombinedDPS"] = 60.0  # the lane's inputs land: the number moves
        pob.inputs = dict(inputs_after or {})
        return pipeline.judging.objective

    pipeline.judging = SimpleNamespace(rejudge=rejudge, objective=Objective(maximize="CombinedDPS", floors={"Life": 1.0}))
    result = BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Hierophant", main_link=["Shock Nova"]))
    return pipeline, pob, result, calls


def test_record_helper_rejudges_before_it_reads_and_writes_the_rejudged_value() -> None:
    pipeline, pob, result, calls = _pipeline()
    pob.state["CombinedDPS"] = 100.0
    calls.append("last PoB-changing call of the stage")
    pipeline._record_rejudged(result, SimpleNamespace(), "tree greedy", 0.0, "done")
    assert calls[:2] == ["last PoB-changing call of the stage", "rejudge"]
    assert "stats" not in calls[:2]
    assert [s.name for s in result.stages] == ["tree greedy"]
    assert result.stages[0].score_value == 60.0  # the objective after the rejudge, not the value before it
    assert result.stages[0].notes == "done"


def _construct_ast() -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(BuildPipeline.run)))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    return function


def _method(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _stage_name(call: ast.Call, offset: int) -> str:
    arg = call.args[offset]
    if isinstance(arg, ast.Constant):
        return str(arg.value)
    assert isinstance(arg, ast.JoinedStr)  # an f-string: its constant head names the stage
    return "".join(part.value for part in arg.values if isinstance(part, ast.Constant))


def _records(function: ast.FunctionDef) -> dict[str, str]:
    """stage name (constant head) -> the record method that writes it."""

    found: dict[str, str] = {}
    for node in ast.walk(function):
        method = _method(node)
        if method == "_record":
            found[_stage_name(node, 1)] = "_record"
        elif method == "_record_rejudged":
            found[_stage_name(node, 2)] = "_record_rejudged"
    return found


def test_every_stage_from_tree_seed_through_tree_refine_is_recorded_after_a_rejudge() -> None:
    records = _records(_construct_ast())
    for head in REJUDGED_BY_HELPER:
        matching = [method for name, method in records.items() if name.startswith(head)]
        assert matching == ["_record_rejudged"], f"{head}: {matching}"


def _block_with(function: ast.FunctionDef, predicate) -> list[ast.stmt]:
    for node in ast.walk(function):
        for field in ("body", "orelse"):
            block = getattr(node, field, None)
            if isinstance(block, list) and any(predicate(stmt) for stmt in block):
                return block
    raise AssertionError("block not found")


def _calls_in(stmt: ast.stmt) -> list[ast.Call]:
    return [n for n in ast.walk(stmt) if isinstance(n, ast.Call)]


def test_gear_pass_2_fill_starts_from_the_rejudged_tree_greedy_record() -> None:
    function = _construct_ast()

    def is_greedy_record(stmt: ast.stmt) -> bool:
        return any(_method(c) == "_record_rejudged" and _stage_name(c, 2) == "tree greedy" for c in _calls_in(stmt))

    block = _block_with(function, is_greedy_record)
    start = next(i for i, stmt in enumerate(block) if is_greedy_record(stmt))
    fill = next(i for i, stmt in enumerate(block) if i > start and any(_method(c) == "fill" for c in _calls_in(stmt)))
    between = [s for s in block[start + 1:fill] if not (isinstance(s, ast.Expr) and _method(s.value) == "_step_start")]  # #711: the step's start line is a log line, no PoB call
    # only the stage clock stands between the rejudged record and the fill: no PoB-changing call
    assert all(isinstance(s, ast.Assign) and [_method(c) for c in _calls_in(s)] == ["perf_counter"] and "perf_counter" in ast.unparse(s) for s in between), \
        [ast.unparse(s) for s in between]


def test_pickers_end_on_a_full_rejudge_before_their_record() -> None:
    from junkroan.search import generator

    for picker in ("pick_supports", "pick_utilities"):
        source = inspect.getsource(getattr(generator.SkeletonGenerator, picker))
        last_call = [line.strip() for line in source.splitlines() if "self._reconfigure(" in line or "score_now(full=True)" in line][-1]
        assert "full=True" in last_call, (picker, last_call)


def test_gear_pass_2_record_keeps_its_own_rejudge_right_before_it() -> None:
    function = _construct_ast()

    def is_gear_pass_2(stmt: ast.stmt) -> bool:
        return any(_method(c) == "_record" and _stage_name(c, 1) == "gear pass 2 (with tree)" for c in _calls_in(stmt))

    block = _block_with(function, is_gear_pass_2)
    at = next(i for i, stmt in enumerate(block) if is_gear_pass_2(stmt))
    assert [_method(c) for c in _calls_in(block[at - 1])][:1] == ["rejudge"]


def test_tree_greedy_per_node_hook_is_still_gated_on_generators() -> None:
    from junkroan.optimizer import tree_optimizer

    lines = inspect.getsource(tree_optimizer).splitlines()
    hook = next(line for line in lines if "self.after_apply_hook(" in line)
    gated = next(line for line in lines if "self.after_apply_hook is not None" in line)
    assert "generator_effects" in gated and hook.strip().startswith("self.after_apply_hook(")


def _gear_pass_1(inputs_before: dict, inputs_after: dict):
    pipeline, pob, result, calls = _pipeline(inputs_after)
    pob.inputs = dict(inputs_before)
    pob.state["CombinedDPS"] = 100.0  # what the fill left; the rejudge moves it to 60
    pipeline._tune_flat_reservation_aura_levels = lambda skeleton: {}
    pipeline._flat_reservation_stage(result, SimpleNamespace(), gear_pass_1=("gear pass 1 (empty tree)", 0.0))
    return result.stages, calls


def test_aura_path_without_a_changed_input_writes_gear_pass_1_after_the_rejudge() -> None:
    stages, _calls = _gear_pass_1({"a": 1}, {"a": 1})
    assert [s.name for s in stages] == ["gear pass 1 (empty tree)", "flat-reservation aura levels"]
    assert stages[0].score_value == 60.0  # the rejudged value


def test_aura_path_with_a_changed_input_keeps_176s_design() -> None:
    stages, _calls = _gear_pass_1({"a": 1}, {"a": 2})
    assert [s.name for s in stages] == ["gear pass 1 (empty tree)", "config re-derived (after gear pass 1)", "flat-reservation aura levels"]
    assert stages[0].score_value == 100.0  # the record as the fill left it
    assert stages[1].notes == "a 1 -> 2" and stages[1].score_value == 60.0


def test_gear_pass_1_records_in_both_branches_are_rejudged() -> None:
    function = _construct_ast()
    rejudged = {_stage_name(c, 2) for c in ast.walk(function) if _method(c) == "_record_rejudged"}
    assert {"gear pass 1 (rig tree)", "gear pass 1 (empty tree)"} <= rejudged  # the no-aura empty-tree path, the rig-first path
    paired = [c for c in ast.walk(function) if _method(c) == "_flat_reservation_stage" and any(k.arg == "gear_pass_1" for k in c.keywords)]
    assert len(paired) == 1 and "gear pass 1 (empty tree)" in ast.unparse(paired[0])  # the aura path: the helper writes it
    assert not {name for name, method in _records(function).items() if method == "_record" and name.startswith("gear pass 1")}
