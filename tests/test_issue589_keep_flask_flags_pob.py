"""#589 unit 5: `PobSession.stats(keep_flask_flags=True)` keeps a flag forced just before; the next default read derives again (#575)."""

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
def test_keep_flask_flags_holds_a_forced_flag_for_one_read(tmp_path: Path) -> None:
    from junkroan.optimizer.flask_lines import FlaskCandidate, flask_bases
    from junkroan.pob.session import PobSession, decode_import_code

    ruby = {b.name: b for b in flask_bases(100)}["Ruby Flask"]
    key = "FireResistTotal"
    with PobSession(run_id="test-589-keep", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(STORMBRAND.read_text(encoding="utf-8").strip()))
        pob.equip({"Flask 1": FlaskCandidate(ruby, None, None).raw(84)}, drop_replaced=True)
        base = pob.stats([key])[key]
        assert pob.flask_uptimes()["Flask 1"]["full"] is False
        assert pob.flasks_active()["Flask 1"] is False
        pob.set_flasks_active({"Flask 1": True})
        forced = pob.stats([key], keep_flask_flags=True)[key]
        assert pob.flasks_active()["Flask 1"] is True, "flag held after the keep read"
        back = pob.stats([key])[key]
        print(f"{key}: X={base} forced={forced} back={back}")
        assert forced != base
        assert back == base
        assert pob.flasks_active()["Flask 1"] is False
