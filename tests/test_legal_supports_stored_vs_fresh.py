"""The pure part of scripts/legal_supports_stored_vs_fresh.py (#980 unit 2): compare, the two file shapes, the stem -> name match.
No PoB: the script is loaded by path, and nothing here starts a PobSession."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "legal_supports_stored_vs_fresh.py"
_spec = importlib.util.spec_from_file_location("legal_supports_stored_vs_fresh", SCRIPT)
svf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(svf)


def test_compare_counts_and_names_and_shapes(tmp_path):
    stored78 = [f"Support {i:02d}" for i in range(78)]
    fresh79 = stored78 + ["Added Chaos Damage"]
    # 78 -> 79: one name added, none removed (the Shrapnel Ballista case of 2026-10-13)
    assert svf.compare(stored78, fresh79) == {"stored_n": 78, "fresh_n": 79, "added": ["Added Chaos Damage"], "removed": []}
    # both file shapes read to the same list: the old plain list and the new {"key", "legal"} dict
    plain, keyed = tmp_path / "legal_supports-arc.json", tmp_path / "legal_supports-blade_vortex.json"
    plain.write_text(json.dumps(["Blade Vortex", "Added Chaos Damage"]), encoding="utf-8")
    keyed.write_text(json.dumps({"key": "abc", "legal": ["Blade Vortex", "Added Chaos Damage"]}), encoding="utf-8")
    # the stem resolves to the gem name by lowercase + underscore; a stem with no gem resolves to []
    names = ["Arc", "Shrapnel Ballista", "Blade Vortex"]
    assert svf.read_stored(plain) == svf.read_stored(keyed) == ["Blade Vortex", "Added Chaos Damage"]
    assert svf.resolve_skill("shrapnel_ballista", names) == ["Shrapnel Ballista"]
    assert svf.resolve_skill("no_such_gem", names) == []
