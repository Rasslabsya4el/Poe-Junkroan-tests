"""Row 5 of #433: check the cluster jewels of every final build of a benchmark run.

    python scripts/check_clusters.py artifacts/benchmark/<stamp>

Reads `*.pob.txt` (the import code of each final build, decoded to PoB XML) from the run folder and lists
per build its cluster jewels (size, node count, notables, enchant). Exit 1 when a build breaks a day-1 rule
(rulebook `t-cluster`, rails `gear.clusters`): node count not 12 (Large) / 6 (Medium), more than 2 notables,
a Small Cluster Jewel, an "Added Small Passive Skills also grant" line, or more than `count_max` cluster jewels.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_ANY_TAG = re.compile(r"^(?:\{[^}]*\})+")
_NOTABLE = "1 Added Passive Skill is "


def _parse(raw: str) -> dict:
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    out = {"base": lines[2] if len(lines) > 2 else "", "count": None, "notables": [], "enchant": [], "also": False}
    for ln in lines:
        if ln.startswith("Cluster Jewel Node Count:"):
            out["count"] = int(ln.split(":")[1])
        plain = _ANY_TAG.sub("", ln)
        if plain.startswith(_NOTABLE):
            out["notables"].append(plain[len(_NOTABLE):])
        elif plain.startswith("Added Small Passive Skills"):
            out["enchant"].append(plain)
            if plain.startswith("Added Small Passive Skills also grant"):
                out["also"] = True
    return out


def check_build(xml: str, *, rails=None) -> tuple[list[tuple[str, int | None, list[str], list[str]]], str]:
    """(cluster jewels as (size, node count, notables, enchant), verdict); verdict is "OK" or the broken rules joined by "; "."""
    if rails is None:
        from junkroan.optimizer.rails import Rails

        rails = Rails.load().gear.clusters
    root = ET.fromstring(xml)
    jewels, broken = [], []
    for item in root.findall("./Items/Item"):
        info = _parse(item.text or "")
        m = re.match(r"(Small|Medium|Large) Cluster Jewel$", info["base"])
        if not m:
            continue
        size = m[1].lower()
        jewels.append((size, info["count"], info["notables"], info["enchant"]))
        tag = f"{size} cluster"
        if size not in rails.sizes:
            broken.append(f"{tag}: size not allowed")
        elif info["count"] != rails.passives[size]:
            broken.append(f"{tag}: {info['count']} passives, not {rails.passives[size]}")
        if len(info["notables"]) > rails.notables_max:
            broken.append(f"{tag}: {len(info['notables'])} notables, max {rails.notables_max}")
        if info["also"]:
            broken.append(f"{tag}: an 'Added Small Passive Skills also grant' line")
    if len(jewels) > rails.count_max:
        broken.append(f"{len(jewels)} cluster jewels, max {rails.count_max}")
    return jewels, "OK" if not broken else "; ".join(broken)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    from junkroan.pob.session import decode_import_code

    files = sorted(Path(argv[0]).glob("*.pob.txt"))
    bad = 0
    for f in files:
        jewels, verdict = check_build(decode_import_code(f.read_text(encoding="utf-8").strip()))
        bad += verdict != "OK"
        shown = "; ".join(f"{s} {n} nodes, notables {nt}, {en}" for s, n, nt, en in jewels) or "no cluster jewels"
        print(f"{f.name[: -len('.pob.txt')]}: {shown}: {verdict}")
    print(f"{len(files)} builds, {len(files) - bad} OK, {bad} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
