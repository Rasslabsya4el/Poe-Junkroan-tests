"""#596 row 4: the flask step keeps smite's input Divine Life Flask on the fixed Flask 1 slot (it is not replaced by an as-if-active pick)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
SMITES = sorted((PROJECT_ROOT / "artifacts" / "proof-575" / "builds").glob("smite*.pob.txt"))
INPUT_NAME = "Ebullient Divine Life Flask of Allaying"
FLOOR = 646_456


@pytest.mark.pob
@needs_pob
@pytest.mark.skipif(len(SMITES) != 1, reason="proof-575 smite build not present (or not one file)")
def test_flask_step_keeps_the_smite_input_divine_flask_on_flask_1(tmp_path: Path) -> None:
    from junkroan.optimizer.flask_lines import FlaskCandidate, flask_base, flask_bases, flask_mods
    from junkroan.optimizer.flask_probe import PobFlaskProbe
    from junkroan.optimizer.flask_step import SLOTS as FLASK_SLOTS, run_flask_step
    from junkroan.optimizer.flask_trace import DIVINE_BASE
    from junkroan.optimizer.objective import Objective
    from junkroan.pob.session import PobSession, decode_import_code

    item_level, base_level_max = 84, 84
    with PobSession(run_id="test-596-keep-input", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(SMITES[0].read_text(encoding="utf-8").strip()))
        probe = PobFlaskProbe(pob, lambda: Objective(maximize="CombinedDPS"), item_level=item_level)
        before = pob.stats(["CombinedDPS"])["CombinedDPS"]
        inp1 = probe.input_flasks()["Flask 1"].raw(item_level)
        assert INPUT_NAME in inp1, inp1  # the fixture's own Flask 1
        bases = [b for b in flask_bases(base_level_max) if b.kind != "tincture"]
        step = run_flask_step(
            probe, bases, lambda b: flask_mods(b, item_level), lambda b, p, s: FlaskCandidate(b, p, s),
            slots=FLASK_SLOTS, item_level=item_level, base_level_max=base_level_max,
            fixed={FLASK_SLOTS[0]: flask_base(DIVINE_BASE)},
        )
        after = pob.stats(["CombinedDPS"])["CombinedDPS"]
        raw1 = probe.input_flasks()["Flask 1"].raw(item_level)
        print(f"Flask 1 after step: {raw1.splitlines()[:3]}; CombinedDPS before={before} after={after}; {step.measured} measured")
        assert INPUT_NAME in raw1, raw1
        assert round(after) >= FLOOR, after  # 646,456 is the rounded figure
