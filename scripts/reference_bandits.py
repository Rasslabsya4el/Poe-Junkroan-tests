"""#785 row 1: the reference fixtures of the sets whose author took a bandit other than "kill all" (no PoB)."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark import SETS, fixture_path  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402

KILL_ALL = "None"  # PoB's Build.bandit value for "kill all" (PoB Modules/ConfigOptions.lua)


def author_bandit(slug: str) -> str:
    xml = decode_import_code(fixture_path(slug).read_text(encoding="utf-8").strip())
    return ET.fromstring(xml).find("Build").get("bandit") or KILL_ALL


def rows(sets: tuple[str, ...] = ("core14", "smoke", "new18", "ziz")) -> list[tuple[str, str, str]]:
    seen: dict[str, str] = {}
    out = []
    for name in sets:
        for slug in SETS[name]:
            bandit = seen.setdefault(slug, author_bandit(slug))
            if bandit != KILL_ALL:
                out.append((name, slug, bandit))
    return out


if __name__ == "__main__":
    total = sum(len(SETS[s]) for s in ("core14", "smoke", "new18", "ziz"))
    print(f"{'set':8} {'name':45} bandit")
    for name, slug, bandit in rows():
        print(f"{name:8} {slug:45} {bandit}")
    print(f"{len(rows())} of {total} (set, name) rows carry a bandit other than kill all")
