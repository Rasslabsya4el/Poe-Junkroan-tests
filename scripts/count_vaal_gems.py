"""Count Vaal gems (corpus is_vaal_gem) in the delivered PoB import codes of a run (#802 row 9).

usage: python scripts/count_vaal_gems.py <run .out file | benchmark folder | *.pob.txt>
Each import code is decoded (base64 + zlib -> XML); <Gem> elements are resolved against the
game_corpus active gems with is_vaal_gem.
"""
from __future__ import annotations

import base64
import re
import sys
import zlib
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import json  # noqa: E402

CORPUS = ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "active_gems.json"


def vaal_keys(records) -> set[str]:
    keys: set[str] = set()
    for r in records:
        if r.get("is_vaal_gem"):
            for f in ("name", "game_id", "record_id", "granted_effect_id", "variant_id"):
                if r.get(f):
                    keys.add(str(r[f]))
    return keys


def decode_code(code: str) -> str:
    code = code.strip()
    return zlib.decompress(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))).decode("utf-8")


def vaal_gems_in_xml(xml: str, keys: set[str]) -> list[str]:
    out = []
    for g in ET.fromstring(xml).iter("Gem"):
        if any(g.get(a) in keys for a in ("gemId", "nameSpec", "skillId", "variantId")):
            out.append(g.get("nameSpec") or g.get("skillId") or "?")
    return out


def vaal_gems_in_code(code: str, keys: set[str]) -> list[str]:
    return vaal_gems_in_xml(decode_code(code), keys)


def find_files(arg: Path) -> list[Path]:
    if arg.is_dir():
        return sorted(arg.glob("*.pob.txt"))
    if arg.name.endswith(".pob.txt"):
        return [arg]
    text = arg.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^report:\s*(.+?)\?report\.md\s*$", text, re.M)
    cands = []
    if m:
        folder = Path(m.group(1).strip().replace("\\", "/"))
        cands.append(folder)
        cands.append(ROOT / "artifacts" / "benchmark" / folder.name)
    cands.append(ROOT / "artifacts" / "benchmark" / arg.stem)
    for c in cands:
        if c.is_dir() and list(c.glob("*.pob.txt")):
            return sorted(c.glob("*.pob.txt"))
    raise SystemExit("no delivered codes on disk; tried: " + ", ".join(str(c) for c in cands))


def main(argv: list[str]) -> int:
    keys = vaal_keys(json.loads(CORPUS.read_text(encoding="utf-8"))["records"])
    total = 0
    for f in find_files(Path(argv[1])):
        names = vaal_gems_in_code(f.read_text(encoding="utf-8"), keys)
        total += len(names)
        print(f"{f.name[:-len('.pob.txt')]}: {len(names)} {names}")
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
