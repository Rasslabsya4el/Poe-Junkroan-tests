"""Every reference build must load into the pinned PoB and produce sane numbers.

Guards against PoB API drift (a bump of locks/pob.lock.json that silently breaks
import) and against fixture rot. Skipped without the local PoB runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def test_all_reference_builds_load_and_calc(tmp_path: Path) -> None:
    sources = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
    recorded = {row["slug"]: row for row in json.loads((FIXTURES / "stats.json").read_text(encoding="utf-8"))}
    assert len(sources["builds"]) == 32  # ten 3.29 runs + bow and minion runs from 3.26-3.28 (2026-09-14) + one run per further archetype (2026-09-15, D56)

    with PobSession(run_id="test-fixtures", artifacts_root=tmp_path) as pob:
        for build in sources["builds"]:
            code = (FIXTURES / f"{build['slug']}.pob.txt").read_text(encoding="utf-8").strip()
            pob.load_xml(decode_import_code(code))
            stats = pob.calc()
            assert stats["Life"] > 2500, build["slug"]
            assert max(stats["CombinedDPS"], stats.get("FullDPS") or 0) > 50_000, build["slug"]  # minion builds carry their damage in FullDPS (D37)
            # Recorded stats.json is the reference; a PoB bump that moves numbers
            # by more than 2% must be looked at and stats.json regenerated on purpose.
            ref = recorded[build["slug"]]
            assert abs(stats["CombinedDPS"] - ref["CombinedDPS"]) <= 0.02 * max(1.0, ref["CombinedDPS"]), build["slug"]
            assert abs(stats["Life"] - ref["Life"]) <= 0.02 * ref["Life"], build["slug"]
