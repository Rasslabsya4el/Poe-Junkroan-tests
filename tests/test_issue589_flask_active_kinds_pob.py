"""#589 row 4: a RESIST flask (Ruby) and a UTILITY flask (Silver) below 100 % uptime are inactive after a stats read (#575, D115)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
STORMBRAND = PROJECT_ROOT / "tests" / "fixtures" / "stormbrand_s4_flasks_saved_active.pob.txt"


@pytest.mark.pob
@needs_pob
def test_resist_and_utility_flask_below_full_uptime_are_inactive_after_a_stats_read(tmp_path: Path) -> None:
    from junkroan.optimizer.flask_lines import FlaskCandidate, flask_bases
    from junkroan.pob.session import PobSession, decode_import_code

    bases = {b.name: b for b in flask_bases(100)}
    ruby, silver = bases["Ruby Flask"], bases["Silver Flask"]
    with PobSession(run_id="test-589-kinds", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(STORMBRAND.read_text(encoding="utf-8").strip()))
        pob.equip(
            {"Flask 1": FlaskCandidate(ruby, None, None).raw(84), "Flask 2": FlaskCandidate(silver, None, None).raw(84)},
            drop_replaced=True,
        )
        pob.set_flasks_active(True)
        assert pob.flasks_active()["Flask 1"] and pob.flasks_active()["Flask 2"], "forced on before the read"
        pob.stats(["FullDPS"])
        up = pob.flask_uptimes()
        active = pob.flasks_active()
        for slot in ("Flask 1", "Flask 2"):
            print(f"{slot}: uptime {up[slot]} flasks_active {active[slot]}")
        for slot in ("Flask 1", "Flask 2"):
            assert up[slot]["full"] is False, up[slot]
            assert active[slot] is False, (slot, up[slot], active[slot])
