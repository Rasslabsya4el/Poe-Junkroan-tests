"""#806: rebuilding the rulebook from its hand-written source reproduces the committed file (no rule lost)."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "docs" / "rulebook"


def test_rebuild_equals_committed(tmp_path, monkeypatch):
    for f in BOOK.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setattr(sys, "argv", ["build_rulebook"])
    import build_rulebook

    monkeypatch.setattr(build_rulebook, "BOOK", tmp_path)
    build_rulebook.main()
    new = json.loads((tmp_path / "loadout-rulebook.json").read_text(encoding="utf-8"))
    old = json.loads((BOOK / "loadout-rulebook.json").read_text(encoding="utf-8"))
    o = {e["id"]: e for e in old["entries"]}
    n = {e["id"]: e for e in new["entries"]}
    assert set(o) == set(n)
    differ = sorted(i for i in o if o[i] != n[i])
    assert differ == [], f"{len(differ)} of {len(o)} entries differ: {differ}"
    assert {e["id"] for e in old["entries"] if "machine" in e} == {e["id"] for e in new["entries"] if "machine" in e}
    assert sum("machine" in e for e in new["entries"]) == 15
    assert new == old
