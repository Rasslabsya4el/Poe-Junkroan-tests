"""#526: every search run writes into its own dated folder; a later run deletes nothing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import search  # noqa: E402


def _build(i: int) -> dict:
    return {"import_code": f"CODE{i}", "xml": "<x/>", "value": i, "tag": f"t{i}"}


def _run(out_dir, stamp: str, n: int) -> str:
    run_dir = out_dir / stamp
    report = ["# Search: x", f"{n} builds"]
    for i in range(1, n + 1):
        spares = [{"tag": f"t{i}", "seed": 2, "import_code": "S"}] if i == 1 else []
        search.write_build_files(run_dir, f"{i:02d} b{i}", _build(i), spares)
    search.publish_report(out_dir, run_dir, report)
    return "\n".join(report) + "\n"


def test_two_runs_two_folders(tmp_path):
    first = tmp_path / "20261003-2300"
    _run(tmp_path, "20261003-2300", 2)
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    report2 = _run(tmp_path, "20261003-2301", 1)
    second = tmp_path / "20261003-2301"
    assert len(list(first.glob("[0-9][0-9] *.pob.txt"))) == 3  # 2 builds + one spare seed
    assert len(list(second.glob("[0-9][0-9] *.pob.txt"))) == 2  # 1 build + one spare seed
    assert {p.name: p.read_bytes() for p in first.iterdir()} == before
    head, rest = (tmp_path / "report.md").read_text(encoding="utf-8").split("\n", 1)
    assert str(second) in head
    assert rest == report2


def test_echo_prints_folder(tmp_path):
    line = search.echo_line("plan: x", tmp_path / "20261003-2300")
    assert str(tmp_path / "20261003-2300") in line.splitlines()[-1]
