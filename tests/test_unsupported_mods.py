"""Lines PoB cannot model are named in the audit (ROADMAP Phase 4). Needs the PoB runtime."""

from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_unsupported_mods
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.pob, pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")]
def test_unsupported_lines_are_named_with_their_source() -> None:
    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "regular_viper_strike.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test_unsupported") as pob:
        parsed = pob.parse_mods(["Bleeding you inflict is Aggravated", "+10 to Strength"])
        assert parsed[0]["unsupported"] and not parsed[1]["unsupported"]
        pob.load_xml(xml)
        findings = audit_unsupported_mods(pob)
    assert all(f.check == "not modelled by PoB" and f.severity == "warning" for f in findings)
    assert not any("Flask" in f.detail for f in findings)
    assert all("\n" not in f.detail for f in findings)
