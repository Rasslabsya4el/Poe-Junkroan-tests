"""Renders docs/rulebook/loadout-rulebook.json into the page the user edits (published as a claude.ai artifact).

    python scripts/build_rulebook.py && python scripts/build_rulebook_page.py [--out artifacts/rulebook/loadout-rulebook.html]

The page keeps the user's cell edits (db collection `cells`, doc id "<entry>--<loadout>") and notes (collection
`notes`, doc id = entry id, "_general" for the page-level note). The lead reads both, folds them into
loadout-rulebook.entries.json, rebuilds and republishes; the JSON stays the file the system reads.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "docs" / "rulebook"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "rulebook" / "loadout-rulebook.html")
    args = ap.parse_args()
    book = json.loads((BOOK / "loadout-rulebook.json").read_text(encoding="utf-8"))
    template = (BOOK / "site" / "rulebook.template.html").read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    assert template.count(marker) == 1
    data = json.dumps(book, ensure_ascii=False).replace("</", "<\\/")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.replace(marker, data), encoding="utf-8")
    print(f"{args.out}: {len(book['entries'])} entries, {args.out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
