"""#456: a benchmark with no counted row must not exit 0."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from benchmark import exit_code_for  # noqa: E402
from test_benchmark_counted_rows import full_row  # noqa: E402


def failed(slug: str) -> dict:
    return {"ok": False, "slug": slug, "seed": 1, "error": "boom"}


def test_all_failed_exits_2() -> None:
    assert exit_code_for([failed(f"b{i}") for i in range(6)]) == 2
    assert exit_code_for([]) == 2


def test_one_counted_of_six_exits_0() -> None:
    rows = [full_row("b0", 1, 1.0)] + [failed(f"b{i}") for i in range(1, 6)]
    assert exit_code_for(rows) == 0
