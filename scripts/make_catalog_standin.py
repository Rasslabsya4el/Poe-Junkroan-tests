"""Writes the stand-in of the PoEDB affix catalog for the public test copy (#1205).

The real catalog (src/junkroan/pob/mod_data/poedb_affix_catalog/catalog.json) is 77 MB, over the 50 MiB a test copy may
carry. Its only reader, `junkroan.search.hypothesis._affix_catalog`, uses `pages` and, per affix, `page_id`,
`section_kind`, `text`; the stand-in keeps exactly those, compact. Run after the catalog is regenerated:
    python scripts/make_catalog_standin.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/junkroan/pob/mod_data/poedb_affix_catalog/catalog.json"
STANDIN = ROOT / "tests/fixtures/standins/poedb_affix_catalog.json"
AFFIX_FIELDS = ("page_id", "section_kind", "text")


def standin_of(catalog: dict) -> dict:
    """The catalog cut to the fields `_affix_catalog` reads."""
    return {
        "pages": catalog["pages"],
        "affixes": [{k: a.get(k) for k in AFFIX_FIELDS} for a in catalog["affixes"]],
    }


def main() -> None:
    catalog = json.loads(SOURCE.read_text(encoding="utf-8"))
    text = json.dumps(standin_of(catalog), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    STANDIN.parent.mkdir(parents=True, exist_ok=True)
    STANDIN.write_text(text, encoding="utf-8", newline="\n")
    print(f"{STANDIN.relative_to(ROOT)}: {len(text.encode()) / 2**20:.1f} MiB")


if __name__ == "__main__":
    main()
