"""Red-line marks: the PoB custom-modifier lines that stand for a red line on one lane (#1124, unit 1 of 5).

A red line is a day-1 line (on a node, a unique, a rare affix, a flask) that PoB reads in part or not at all
(`scripts/day1_lines.py`, `docs/research/2026-10-15-day1-red-lines.md`). A mark says which PoB lines to write for
it, per lane: `boss_lane` (the conservative reading, the one a build proves) and `optimistic_lane` (every condition
PoB says the build can use). An empty lane means "no mark on that lane": the record then changes nothing there.

The store is `src/junkroan/mechanics/red_line_marks.json`, a JSON list of records with the fields `line`,
`surfaces`, `sources`, `group`, `kind`, `boss_lane`, `optimistic_lane`, `zero_reason`, `why`, `partial_part` and
the optional `formula`. A missing store is an empty marks object, so nothing changes anywhere (rules 4 and 5).

This module is PoB-free: it reads files and returns text. The lane writers that put the block into a build's
ConfigSet are a later unit.
"""

from __future__ import annotations

import ast
import copy
import json
import math
import operator
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = ["LANES", "DEFAULT_PATH", "ENV_PATH", "RedLineMarks", "load_marks"]

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "mechanics" / "red_line_marks.json"
ENV_PATH = "JUNKROAN_RED_LINE_MARKS"
LANES = ("boss", "optimistic")
PLACEHOLDER = "{formula}"

_LANE_FIELD = {"boss": "boss_lane", "optimistic": "optimistic_lane"}
_LIST_FIELDS = ("surfaces", "sources", "boss_lane", "optimistic_lane")
_TEXT_FIELDS = ("group", "kind", "zero_reason", "why", "partial_part")
_REQUIRED = ("line",) + _LIST_FIELDS + _TEXT_FIELDS

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _norm(line: str) -> str:
    return line.strip()


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _check_lane(lane: str) -> None:
    if lane not in _LANE_FIELD:
        raise ValueError(f"lane must be one of {LANES}, got {lane!r}")


def _check_formula_node(node: ast.AST, text: str) -> None:
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        _check_formula_node(node.left, text)
        _check_formula_node(node.right, text)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        _check_formula_node(node.operand, text)
    elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return
    elif isinstance(node, ast.Name):
        return
    else:
        raise ValueError(f"formula {text!r} uses a construct outside arithmetic over names")


def _check_formula(text: str) -> None:
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"formula {text!r} does not parse: {exc.msg}") from None
    _check_formula_node(tree.body, text)


def _eval_node(node: ast.AST, outputs: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.BinOp):
        return _BINARY[type(node.op)](_eval_node(node.left, outputs), _eval_node(node.right, outputs))
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_eval_node(node.operand, outputs))
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if outputs is None or node.id not in outputs:
            raise KeyError(node.id)
        return outputs[node.id]
    raise ValueError("formula node outside arithmetic")  # _check_formula already rejects these


def _formula_value(text: str, outputs: Mapping[str, Any] | None) -> float:
    tree = ast.parse(text.strip(), mode="eval")
    return float(_eval_node(tree.body, outputs))


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError(f"formula value is not finite: {value!r}")
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _validate(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: a record must be a JSON object")
    missing = [key for key in _REQUIRED if key not in raw]
    if missing:
        raise ValueError(f"{where}: missing fields {missing}")
    line = raw["line"]
    if not isinstance(line, str) or not _norm(line):
        raise ValueError(f"{where}: line must be a non-empty string")
    for key in _LIST_FIELDS:
        value = raw[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{where}: {key} must be a list of strings")
    for key in _TEXT_FIELDS:
        if not isinstance(raw[key], str):
            raise ValueError(f"{where}: {key} must be a string")
    for key in ("boss_lane", "optimistic_lane"):
        if any(not _norm(entry) for entry in raw[key]):
            raise ValueError(f"{where}: {key} holds an empty line")
    has_placeholder = any(PLACEHOLDER in entry for key in ("boss_lane", "optimistic_lane") for entry in raw[key])
    formula = raw.get("formula")
    if formula is not None:
        if not isinstance(formula, str) or not _norm(formula):
            raise ValueError(f"{where}: formula must be a non-empty string")
        _check_formula(formula)
    elif has_placeholder:
        raise ValueError(f"{where}: a lane line holds {PLACEHOLDER} but the record has no formula")
    if not raw["boss_lane"] and not raw["optimistic_lane"] and not _norm(raw["zero_reason"]):
        raise ValueError(f"{where}: a zero record (both lanes empty) must give its zero_reason")
    record: dict[str, Any] = {key: copy.deepcopy(raw[key]) for key in _REQUIRED}
    record["line"] = _norm(line)
    if formula is not None:
        record["formula"] = _norm(formula)
    return record


class RedLineMarks:
    """The marks of one store. Lookups are by exact line text (surrounding whitespace only is normalised)."""

    def __init__(self, records: Iterable[Mapping[str, Any]] = ()) -> None:
        by_line: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(records):
            record = _validate(raw, f"record {index}")
            if record["line"] in by_line:
                raise ValueError(f"duplicate red line {record['line']!r} in the marks store")
            by_line[record["line"]] = record
        self._by_line = by_line

    def __len__(self) -> int:
        return len(self._by_line)

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(record) for record in self._by_line.values())

    def record(self, line: str) -> dict[str, Any] | None:
        record = self._by_line.get(_norm(line))
        return copy.deepcopy(record) if record is not None else None

    def has_record(self, line: str) -> bool:
        return _norm(line) in self._by_line

    def is_marked(self, line: str, lane: str) -> bool:
        _check_lane(lane)
        record = self._by_line.get(_norm(line))
        return bool(record is not None and record[_LANE_FIELD[lane]])

    def block_for(
        self,
        held_lines: Iterable[tuple[str, str]],
        lane: str,
        outputs: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """The PoB lines of one custom-modifier block body for `lane`, from the lines held as (line, source).

        Output: for each marked line in sorted line order, one comment per source (`# red line: ... | source: ...`)
        then the lane's lines. A `{formula}` placeholder takes the formula's value from `outputs`. A line held by
        several sources is written once. No marked line on the lane gives `[]`.
        """
        _check_lane(lane)
        field = _LANE_FIELD[lane]
        sources_by_line: dict[str, set[str]] = {}
        for line, source in held_lines:
            sources_by_line.setdefault(_norm(line), set()).add(str(source))
        block: list[str] = []
        written: set[str] = set()
        for key in sorted(sources_by_line):
            record = self._by_line.get(key)
            if record is None or not record[field]:
                continue
            for source in sorted(sources_by_line[key]):
                block.append(f"# red line: {_one_line(key)} | source: {source}")
            for entry in record[field]:
                text = entry
                if PLACEHOLDER in text:
                    value = _formula_value(record["formula"], outputs)
                    text = text.replace(PLACEHOLDER, _format_number(value))
                if text not in written:
                    written.add(text)
                    block.append(text)
        return block


_EMPTY = RedLineMarks(())


def _env_or_default(path: str | os.PathLike[str] | None) -> Path:
    if path is not None:
        return Path(path)
    override = os.environ.get(ENV_PATH, "").strip()
    return Path(override) if override else DEFAULT_PATH


@lru_cache(maxsize=16)
def _read_store(path_text: str, mtime_ns: int) -> RedLineMarks:
    del mtime_ns  # part of the cache key only: a changed file is read again
    with open(path_text, encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path_text}: not JSON ({exc})") from None
    if not isinstance(raw, list):
        raise ValueError(f"{path_text}: the marks store must be a JSON list of records")
    return RedLineMarks(raw)


def load_marks(path: str | os.PathLike[str] | None = None) -> RedLineMarks:
    """The marks store at `path`; without it, the env override `JUNKROAN_RED_LINE_MARKS`, else the default file.

    A missing file gives an empty marks object. Cached by (path, mtime): a rewritten file is read again.
    """
    target = _env_or_default(path)
    try:
        mtime_ns = target.stat().st_mtime_ns
    except FileNotFoundError:
        return _EMPTY
    return _read_store(os.path.abspath(target), mtime_ns)
