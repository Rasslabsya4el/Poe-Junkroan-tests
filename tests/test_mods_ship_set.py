"""The manifest's mods/pob-slots/test lines are exactly what scripts/mods_ship_set.py computes (rules 1 and 2)."""
from pathlib import Path

from scripts import mods_ship_set as ms
from tools.agentops import core_check

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_test_lines_equal_the_computed_set():
    # compute(stubs=False) is `--no-stubs`: rules 1 and 2 plus the orphan drop (a non-test helper no shipping test
    # imports is not shipped); candidates() alone still lists those helpers as "ships" (not yet dropped)
    computed = {f for f, s in ms.compute(ROOT, stubs=False).items() if s == "ships"}
    listed = {e for e in ms.manifest_entries() if e.startswith(ms.TEST_DIR)}
    assert listed == computed, (sorted(listed - computed), sorted(computed - listed))


def test_no_listed_test_file_has_a_leak_hit():
    patterns = core_check.read_patterns(ROOT / "config" / "core_leak_patterns.json")
    listed = [e for e in ms.manifest_entries() if e.startswith(ms.TEST_DIR)]
    assert [(e, ms.rule1(ROOT, e, patterns)) for e in listed if ms.rule1(ROOT, e, patterns)] == []
