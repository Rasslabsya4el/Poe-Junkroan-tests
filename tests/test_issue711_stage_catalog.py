"""#711 unit 1: the step catalog covers every stage name the optimizer records."""

from __future__ import annotations

import ast
from pathlib import Path

from junkroan.optimizer.stage_catalog import (
    GROUPS, STEPS, group_of, loop_move_line, parse_log_line, skipped_line, start_line, step_of,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "junkroan"
# call name -> index of the stage-name argument
NAME_ARG = {"_record": 1, "_record_rejudged": 2, "record_stage": 3, "stage_record": 3, "_stage_record": 1}


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value if isinstance(p, ast.Constant) else "X" for p in node.values)
    return None


def _recorded_names() -> list[tuple[str, str, int]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if fname in NAME_ARG and len(node.args) > NAME_ARG[fname]:
                name = _literal(node.args[NAME_ARG[fname]])
                if name is not None:
                    found.append((name, path.name, node.lineno))
            for kw in node.keywords:
                if kw.arg == "gear_pass_1" and isinstance(kw.value, ast.Tuple):
                    name = _literal(kw.value.elts[0])
                    if name is not None:
                        found.append((name, path.name, node.lineno))
    return found


def test_every_recorded_stage_name_is_in_the_catalog():
    names = _recorded_names()
    assert len(names) > 20  # the scan really found the pipeline's calls
    missing = [f"{name!r} at {file}:{line}" for name, file, line in names if step_of(name) is None]
    assert not missing, "stage names missing from stage_catalog.STEPS: " + "; ".join(missing)


def test_loop_stage_names_resolve():
    for name in ("loop opening", "loop pass 1", "fixed point check"):
        assert group_of(name) == "improvement loop"


def test_group_of_samples():
    assert group_of("loop pass 3") == "improvement loop"
    assert group_of("tree seed toward CombinedDPS") == "construction"
    assert group_of("anoint re-pick") == "finish"
    assert group_of("anoint") == "construction"
    assert group_of("gear pass 1 (rig tree)") == "construction"
    assert group_of("gear pass 1 (empty tree)") == "construction"
    assert group_of("tree refine") == "construction"
    assert group_of("config (final lanes)") == "finish"
    assert group_of("no such step") is None


def test_catalog_is_ordered_by_group():
    order = [GROUPS.index(s.group) for s in STEPS]
    assert order == sorted(order)


def test_line_round_trip():
    assert start_line("tree greedy") == "step start: tree greedy"
    assert skipped_line("flasks") == "step skipped: flasks"
    assert loop_move_line(2, "aura levels") == "loop pass 2 move aura levels"
    assert parse_log_line(start_line("tree greedy")) == ("start", "tree greedy")
    assert parse_log_line(skipped_line("flasks")) == ("skipped", "flasks")
    assert parse_log_line(loop_move_line(2, "kick-tree")) == ("loop_move", (2, "kick-tree"))
    assert loop_move_line(1, "gear", "fixed point check") == "fixed point check move gear"
    assert loop_move_line(1, "gear", None) == "loop pass 1 move gear"
    assert parse_log_line(loop_move_line(1, "gear", "fixed point check")) == ("loop_move", ("fixed point check", "gear"))
    assert parse_log_line("something else") == (None, None)
