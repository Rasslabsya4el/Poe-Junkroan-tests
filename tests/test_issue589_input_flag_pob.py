"""#589 unit 7: putting the input flask back keeps the input's `active` flag (a tincture's flag is never re-derived)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
SMITE = PROJECT_ROOT / "artifacts" / "proof-575" / "builds" / "smite-s4.pob.txt"


@pytest.mark.pob
@needs_pob
@pytest.mark.skipif(not SMITE.is_file(), reason="proof-575 smite build not present")
def test_put_input_keeps_the_tincture_flag(tmp_path: Path) -> None:
    from junkroan.optimizer.flask_lines import FlaskCandidate, flask_bases
    from junkroan.optimizer.flask_probe import PobFlaskProbe
    from junkroan.optimizer.objective import Objective
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-589-input-flag", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(SMITE.read_text(encoding="utf-8").strip()))
        probe = PobFlaskProbe(pob, lambda: Objective(maximize="CombinedDPS"), item_level=84)
        first = pob.stats(["CombinedDPS"])["CombinedDPS"]
        inp = probe.input_flasks()
        assert inp["Flask 4"].active is True
        ruby = {b.name: b for b in flask_bases(100)}["Ruby Flask"]
        probe.put_flask("Flask 4", FlaskCandidate(ruby, None, None))  # a trial candidate, as the step does
        trial = pob.stats(["CombinedDPS"])["CombinedDPS"]  # the plain read derives every flag: the slot's goes False
        probe.clear_flask("Flask 4")
        probe.put_input("Flask 4", inp["Flask 4"])
        flag = pob.flasks_active()["Flask 4"]
        second = pob.stats(["CombinedDPS"])["CombinedDPS"]
        print(f"CombinedDPS first={first} trial={trial} after={second} Flask 4 active={flag}")
        assert flag is True
        assert abs(second - first) <= first * 1e-4
