"""#1123 stand check: `python scripts/red_line_stand_check.py <marks.json|folder> [--stands spell,attack,minion] [--limit N]`

Applies each red-line mark with a non-empty lane to its stand and reads whether one of the seven PoB outputs
moved (CombinedDPS, TotalEHP, Life, EnergyShield, Mana, LifeRegenRecovery, PhysicalMaximumHitTaken).

Stands: the seed-4 finished builds of spark (spell), smite (attack) and summon_raging_spirits (minion) in the
newest weekly core run folder under artifacts/benchmark/. A stand's PoB import is `<slug>-s4.pob.txt` in that
folder, the file `benchmark.py` writes from each row's import code (`out_dir / f"{stem}.pob.txt"`, :1507); the row
file `rows/<slug>-s4.json` is its record and must exist.

Lanes: `boss_lane` is the conservative lane, the Baseline config set (PobSession.set_config writes it as the
active set, session.py:596), read by `stats()` (session.py:1136). `optimistic_lane` is the Conditional config set
(session.py:595), read by `calc(lane="conditional")` (session.py:666-672). Each lane's block is written into its
own set and the stand is restored from its original XML before the next lane, so no record sees another's block.
`apply_custom_mods` (ramp_inputs.py:539) writes into Baseline only, so the optimistic lane uses `write_conditional`.

Record fields: line, group, kind, boss_lane[], optimistic_lane[], zero_reason, why, optional type (spell / attack /
minion; none = all three stands), optional formula (arithmetic over the stand's baseline outputs and the record's
optional `vars` map; `{formula}` in a lane line takes its value, two decimals), optional stand_blind {reason_kind, why}
(#1123): a non-zero record that moves no output on any stand is counted as stand-blind (`result.stand_blind`, exit 0)
instead of unchanged (exit 1), and a stand_blind record that DOES move an output is stale (`result.stale_stand_blind`, exit 1).

Exit 0 when every non-zero record moved an output on some stand and lane, or is stand-blind; 1 when a record without
stand_blind moved none, or a stand_blind record moved one; 2 on a bad input.
"""

from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.ramp_inputs import apply_custom_mods  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402
from check_red_line_marks import STAND_BLIND_KINDS  # noqa: E402

OUTPUT_KEYS = ("CombinedDPS", "TotalEHP", "Life", "EnergyShield", "Mana", "LifeRegenRecovery", "PhysicalMaximumHitTaken")
STANDS = {"spell": "spark", "attack": "smite", "minion": "summon_raging_spirits"}  # type -> slug of its seed-4 build
STAND_SEED = 4
LANES = ("boss_lane", "optimistic_lane")
BLOCK_TITLE = "junkroan: red-line marks"
UNSUPPORTED_KINDS = ROOT / "src" / "junkroan" / "mechanics" / "unsupported_lines.json"
BENCH_DIR = ROOT / "artifacts" / "benchmark"
CORE_FOLDER = re.compile(r"^(\d{8}-\d{4})-P\d+-core(?:-(\d+))?$")
CONDITIONAL_SET = re.compile(r'(<ConfigSet [^>]*title="Conditional"[^>]*?)(/?)>')
FORMULA_NAMES = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RELATIVE_TOLERANCE = 1e-6

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}


def known_kinds() -> set[str]:
    return {str(kind["id"]) for kind in json.loads(UNSUPPORTED_KINDS.read_text(encoding="utf-8"))["kinds"]}


def newest_core_folder(bench_dir: Path) -> Path:
    """The weekly core run folder with the latest stamp (`YYYYMMDD-HHMM-P<n>-core[-k]`); a bare `-core` is run 1."""

    best: tuple[tuple[str, int], Path] | None = None
    for path in (sorted(bench_dir.iterdir()) if bench_dir.is_dir() else []):
        match = CORE_FOLDER.match(path.name)
        if path.is_dir() and match:
            key = (match.group(1), int(match.group(2) or 1))
            if best is None or key > best[0]:
                best = (key, path)
    if best is None:
        raise FileNotFoundError(f"no weekly core run folder in {bench_dir}")
    return best[1]


def stand_files(folder: Path) -> dict[str, Path]:
    """The PoB import file of each stand, checked against its row file."""

    files: dict[str, Path] = {}
    for stand_type, slug in STANDS.items():
        pob_file = folder / f"{slug}-s{STAND_SEED}.pob.txt"
        row_file = folder / "rows" / f"{slug}-s{STAND_SEED}.json"
        missing = [str(path) for path in (pob_file, row_file) if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"stand {stand_type} ({slug}) incomplete in {folder}: missing {missing}")
        files[stand_type] = pob_file
    return files


def load_records(path: Path) -> list[dict[str, Any]]:
    """A marks file (a list, or {"records": [...]}), or every such *.json file of a folder, in name order."""

    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    records: list[dict[str, Any]] = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        rows = data.get("records") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError(f"{file}: expected a list of records or {{\"records\": [...]}}")
        records.extend(rows)
    return records


def safe_eval(expr: str, names: Mapping[str, float]) -> float:
    """Arithmetic over known names only: numbers, + - * / **, unary signs and parentheses. No calls, no attributes."""

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 64:
                raise ValueError(f"exponent too large in formula {expr!r}")
            try:
                return float(_OPS[type(node.op)](left, right))
            except ZeroDivisionError as error:
                raise ValueError(f"division by zero in formula {expr!r}") from error
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"unknown name {node.id!r} in formula {expr!r}")
            return float(names[node.id])
        raise ValueError(f"not arithmetic in formula {expr!r}")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"formula {expr!r} does not parse") from error
    return walk(tree)


def fill_formula(lines: Sequence[str], value: float | None) -> list[str]:
    if value is None:
        return list(lines)
    return [line.replace("{formula}", f"{value:.2f}") for line in lines]


def record_stands(rec: Mapping[str, Any], selected: Sequence[str]) -> list[str]:
    """The stands a record is measured on: its type's stand, or all selected stands when it has no type."""

    stand_type = rec.get("type") or ""
    if not stand_type or stand_type == "any":
        return list(selected)
    if stand_type not in STANDS:
        raise ValueError(f"record {rec.get('line')!r}: unknown type {stand_type!r}")
    return [stand_type] if stand_type in selected else []


def differs(before: Any, after: Any) -> bool:
    if before is None or after is None:
        return before != after
    return abs(float(after) - float(before)) > RELATIVE_TOLERANCE * max(1.0, abs(float(before)))


def write_conditional(pob: Any, text: str) -> None:
    """The optimistic lane's block: the same shape as `apply_custom_mods` writes, into the Conditional set."""

    xml = pob.export_xml()
    block = f'<CustomModifierBlock title="{BLOCK_TITLE}" enabled="true"># conditional red-line marks\n{escape(text)}</CustomModifierBlock>'
    new, count = CONDITIONAL_SET.subn(lambda m: m.group(1) + ">" + block + ("</ConfigSet>" if m.group(2) else ""), xml, count=1)
    if not count:
        raise ValueError("no Conditional config set in the build XML: cannot write the optimistic lane")
    pob.load_xml(new)


def read_lane(pob: Any, lane: str) -> dict[str, Any]:
    if lane == "boss_lane":
        return dict(pob.stats(list(OUTPUT_KEYS)))
    return dict(pob.calc(lane="conditional"))


@dataclass
class Row:
    group: str
    records: int = 0
    changed: int = 0
    zero: int = 0
    new_kind: int = 0
    stand_blind: int = 0


@dataclass
class Item:
    line: str
    group: str
    stands: str
    reason_kind: str = ""
    why: str = ""


@dataclass
class CheckResult:
    rows: list[Row] = field(default_factory=list)
    unchanged: list[Item] = field(default_factory=list)
    stand_blind: list[Item] = field(default_factory=list)
    stale_stand_blind: list[Item] = field(default_factory=list)
    not_measured: list[str] = field(default_factory=list)

    def row(self, group: str) -> Row:
        for row in self.rows:
            if row.group == group:
                return row
        row = Row(group)
        self.rows.append(row)
        return row


def check_records(records: Sequence[Mapping[str, Any]], pobs: Mapping[str, Any], *, stands: Sequence[str] = tuple(STANDS),
                  limit: int | None = None) -> CheckResult:
    """Measure every record on its stands, lane by lane. `pobs` maps a stand type to an open session."""

    selected = [stand for stand in STANDS if stand in stands]
    records = list(records)[:limit] if limit else list(records)
    known = known_kinds()
    var_names = {name for rec in records for name in (rec.get("vars") or {})}
    formula_names = {name for rec in records if rec.get("formula") for name in FORMULA_NAMES.findall(str(rec["formula"]))}
    keys = list(OUTPUT_KEYS) + sorted(name for name in formula_names - var_names if name not in OUTPUT_KEYS)
    originals: dict[str, str] = {}
    baselines: dict[str, dict[str, Any]] = {}
    lane_before: dict[str, dict[str, dict[str, Any]]] = {}
    for stand in selected:
        pob = pobs[stand]
        originals[stand] = pob.export_xml()
        baselines[stand] = dict(pob.stats(keys))
        lane_before[stand] = {lane: read_lane(pob, lane) for lane in LANES}

    result = CheckResult()
    for rec in records:
        group = str(rec.get("group") or "-")
        line = str(rec.get("line") or "")
        row = result.row(group)
        row.records += 1
        if rec.get("kind") and rec["kind"] not in known:
            row.new_kind += 1
        lanes = {lane: [str(item) for item in (rec.get(lane) or [])] for lane in LANES}
        if not any(lanes.values()):
            row.zero += 1
            continue
        targets = record_stands(rec, selected)
        if not targets:
            result.not_measured.append(line)
            continue
        moved = False
        for stand in targets:
            moved = _measure(pobs[stand], originals[stand], baselines[stand], lane_before[stand], rec, lanes) or moved
        item = Item(line, group, ",".join(targets), *_blind_of(rec))
        blind = bool(rec.get("stand_blind"))
        if moved:
            row.changed += 1
            if blind:
                result.stale_stand_blind.append(item)
        elif blind:
            row.stand_blind += 1
            result.stand_blind.append(item)
        else:
            result.unchanged.append(item)
    return result


def _blind_of(rec: Mapping[str, Any]) -> tuple[str, str]:
    stand_blind = rec.get("stand_blind") or {}
    return str(stand_blind.get("reason_kind", "")), str(stand_blind.get("why", ""))


def _measure(pob: Any, original: str, baseline: Mapping[str, Any], before: Mapping[str, Mapping[str, Any]],
             rec: Mapping[str, Any], lanes: Mapping[str, list[str]]) -> bool:
    value = None
    if rec.get("formula"):
        names = {**baseline, **{key: float(val) for key, val in (rec.get("vars") or {}).items()}}
        value = safe_eval(str(rec["formula"]), names)
    why = " ".join(str(rec.get("why") or "red-line mark").split())
    moved = False
    for lane in LANES:
        if not lanes[lane]:
            continue
        lines = fill_formula(lanes[lane], value)
        text = "\n".join(f"# {why}\n{item}" for item in lines)
        if lane == "boss_lane":
            apply_custom_mods(pob, [(escape(text), BLOCK_TITLE)])
        else:
            write_conditional(pob, text)
        after = read_lane(pob, lane)
        pob.load_xml(original)
        base = before[lane]
        moved = any(differs(base.get(key), after.get(key)) for key in OUTPUT_KEYS) or moved
    return moved


def exit_code(result: CheckResult) -> int:
    return 1 if result.unchanged or result.stale_stand_blind else 0


def format_table(result: CheckResult) -> str:
    head = f"{'group':<30} {'records':>8} {'changed':>8} {'zero':>6} {'new-kind':>9} {'stand-blind':>12}"
    lines = [head]
    for row in result.rows:
        lines.append(f"{row.group:<30} {row.records:>8} {row.changed:>8} {row.zero:>6} {row.new_kind:>9} {row.stand_blind:>12}")
    total = [sum(getattr(row, name) for row in result.rows) for name in ("records", "changed", "zero", "new_kind", "stand_blind")]
    lines.append(f"{'total':<30} {total[0]:>8} {total[1]:>8} {total[2]:>6} {total[3]:>9} {total[4]:>12}")
    return "\n".join(lines)


def format_stand_blind(result: CheckResult) -> str:
    if not result.stand_blind:
        return "no stand_blind record"
    out = [f"stand_blind records that move no PoB output, by reason ({len(result.stand_blind)}):"]
    for reason in STAND_BLIND_KINDS:
        count = sum(1 for item in result.stand_blind if item.reason_kind == reason)
        if count:
            out.append(f"  {reason}: {count}")
    for reason in STAND_BLIND_KINDS:
        items = [item for item in result.stand_blind if item.reason_kind == reason]
        if items:
            out.append(f"{reason} ({len(items)}):")
            out += [f"  [{item.group}] {item.stands}: {item.line}" for item in items]
    return "\n".join(out)


def format_stale_stand_blind(result: CheckResult) -> str:
    if not result.stale_stand_blind:
        return "no stand_blind record moved a PoB output"
    out = [f"stand_blind records that DO move a PoB output (stale, exit 1) ({len(result.stale_stand_blind)}):"]
    out += [f"  [{item.group}] {item.stands}: {item.line} ({item.reason_kind})" for item in result.stale_stand_blind]
    return "\n".join(out)


def format_unchanged(result: CheckResult) -> str:
    if not result.unchanged:
        return "every non-zero record without stand_blind moved a PoB output on its stand"
    out = [f"non-zero records that changed nothing and carry no stand_blind ({len(result.unchanged)}):"]
    out += [f"  [{item.group}] {item.stands}: {item.line}" for item in result.unchanged]
    return "\n".join(out)


def _open_pob(stand_type: str, path: Path) -> Any:
    from junkroan.pob.session import PobSession

    pob = PobSession(run_id=f"issue1123-{stand_type}")
    pob.__enter__()
    pob.load_import_code(path.read_text(encoding="utf-8").strip())
    return pob


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("marks", type=Path, help="a marks JSON file, or a folder of part files")
    ap.add_argument("--stands", default=",".join(STANDS), help="comma list of spell, attack, minion (default all three)")
    ap.add_argument("--limit", type=int, default=None, help="measure only the first N records")
    ap.add_argument("--stand-folder", type=Path, default=None, help="a weekly core run folder (default: the newest)")
    return ap


def main(argv: Sequence[str] | None = None, *, open_pob: Callable[[str, Path], Any] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stands = [s for s in args.stands.split(",") if s]
    if not stands or any(s not in STANDS for s in stands):
        print(f"--stands must be a comma list of {', '.join(STANDS)}", file=sys.stderr)
        return 2
    started = time.monotonic()
    try:
        folder = args.stand_folder or newest_core_folder(BENCH_DIR)
        files = stand_files(folder)
        records = load_records(args.marks)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    for stand in stands:
        print(f"stand {stand}: {files[stand]}")
    opener = open_pob or _open_pob
    pobs: dict[str, Any] = {}
    try:
        for stand in stands:
            pobs[stand] = opener(stand, files[stand])
        result = check_records(records, pobs, stands=stands, limit=args.limit)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        for pob in pobs.values():
            if hasattr(pob, "close"):
                pob.close()
    print(format_table(result))
    print(format_stand_blind(result))
    print(format_stale_stand_blind(result))
    print(format_unchanged(result))
    if result.not_measured:
        print(f"not measured (stand not selected): {len(result.not_measured)} records")
    print(f"done in {human_duration(time.monotonic() - started)}")
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
