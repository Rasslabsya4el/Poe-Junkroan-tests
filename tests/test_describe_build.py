"""Persistence lookups used by the human-facing build description."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from describe_build import _ledger_row  # noqa: E402


def test_describe_reads_the_search_row_beside_the_build(tmp_path: Path) -> None:
    build = tmp_path / "01 Elementalist.pob.txt"
    build.touch()
    (tmp_path / "01 Elementalist.json").write_text(
        '{"ok": true, "moves": [{"move": "refine", "kept": true}]}',
        encoding="utf-8",
    )
    (tmp_path / "results.json").write_text(
        '[{"ok": true, "slug": "other", "seed": 1, "moves": []}]',
        encoding="utf-8",
    )

    assert _ledger_row(build)["moves"][0]["move"] == "refine"
