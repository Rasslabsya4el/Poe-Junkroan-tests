"""#609: the author's poison_spectral_throw types `count="4"` on Spectral Throw ("4x Spectral Throw").
PoB multiplies FullDPS by it (Calcs.lua activeSkillCount); our search reads the skill at count 1."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark import flag_main_group_for_full_dps, main_gem_count  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

CODE = ROOT / "tests" / "fixtures" / "tuadh_329" / "poison_spectral_throw.pob.txt"


@pytest.mark.pob
def test_author_spectral_throw_read_at_count_one(tmp_path: Path) -> None:
    xml = decode_import_code(CODE.read_text(encoding="utf-8").strip())
    assert main_gem_count(xml, "Spectral Throw") == 4
    with PobSession(run_id="test-609", artifacts_root=tmp_path) as pob:
        pob.load_xml(flag_main_group_for_full_dps(xml))
        before = pob.stats(("CombinedDPS", "FullDPS"))
        lowered = flag_main_group_for_full_dps(xml, count=1, main="Spectral Throw")
        assert main_gem_count(lowered, "Spectral Throw") == 1
        pob.load_xml(lowered)
        after = pob.stats(("CombinedDPS", "FullDPS"))
    print(f"author before {before}\nauthor after  {after}")
    assert after["FullDPS"] < before["FullDPS"]
    assert abs(before["FullDPS"] / after["FullDPS"] - 4) < 0.05  # x4 is exactly the typed count
    assert abs(after["CombinedDPS"] - before["CombinedDPS"]) <= 1e-6 * before["CombinedDPS"]  # the compared stat never had it
