"""#1205: the affix catalog goes into the public test copy as a stand-in under 50 MiB that gives `_affix_catalog` the same answer."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_catalog_standin as m  # noqa: E402

REAL = "src/junkroan/pob/mod_data/poedb_affix_catalog/catalog.json"
STAND = "tests/fixtures/standins/poedb_affix_catalog.json"


def _derive(path: Path, tmp_path: Path, monkeypatch):
    from junkroan.search import hypothesis

    folder = tmp_path / path.stem / "mod_data" / "poedb_affix_catalog"
    folder.mkdir(parents=True)
    (folder / "catalog.json").write_bytes(path.read_bytes())
    monkeypatch.setattr(hypothesis, "CORPUS", folder.parents[1] / "corpus_data")
    hypothesis._affix_catalog.cache_clear()
    try:
        return hypothesis._affix_catalog()
    finally:
        hypothesis._affix_catalog.cache_clear()


def test_standin_is_committed_under_50_mib_and_mapped_in_settings():
    assert (ROOT / STAND).stat().st_size < 50 * 2**20
    settings = json.loads((ROOT / "config/orchestration.json").read_text(encoding="utf-8"))
    assert settings["test_copy_standins"] == {REAL: STAND}


def test_standin_gives_the_same_templates_as_the_real_catalog(tmp_path, monkeypatch):
    assert _derive(ROOT / STAND, tmp_path, monkeypatch) == _derive(ROOT / REAL, tmp_path, monkeypatch)


def test_standin_is_what_the_script_writes():
    catalog = json.loads((ROOT / REAL).read_text(encoding="utf-8"))
    text = json.dumps(m.standin_of(catalog), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert (ROOT / STAND).read_text(encoding="utf-8") == text
