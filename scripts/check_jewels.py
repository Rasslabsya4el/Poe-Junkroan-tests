"""Row 5 of #434: check the passive-tree jewels of every final build of a benchmark run.

    python scripts/check_jewels.py artifacts/benchmark/<stamp>

Reads `<slug>-s<seed>[-no-..].pob.txt` (the import code of each final build, decoded to PoB XML) and
`results.json` (its `points`, the passive points the build had) from the run folder. Exit 1 when a build
breaks a rule: at most 2 tree jewels; each a RARE Crimson/Viridian/Cobalt Jewel with exactly 1 explicit mod;
each socket allocated; allocated tree points within the build's points.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MAX_JEWELS = 2
_BASES = ("Crimson Jewel", "Viridian Jewel", "Cobalt Jewel")
_ANY_TAG = re.compile(r"^(?:\{[^}]*\})+")


def _active_spec(root: ET.Element) -> ET.Element | None:
    tree = root.find("Tree")
    if tree is None:
        return None
    specs = tree.findall("Spec")
    active = int(tree.get("activeSpec") or 1)
    return specs[active - 1] if 0 < active <= len(specs) else (specs[0] if specs else None)


def _explicit_lines(raw: str) -> tuple[str, str, list[str]]:
    """(rarity, base, explicit lines) of a raw item text; the base is the line after the name."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    rarity = lines[0].removeprefix("Rarity:").strip() if lines and lines[0].startswith("Rarity:") else ""
    base = lines[2] if len(lines) > 2 else ""
    explicit: list[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("Implicits:"):
            explicit = lines[i + 1 + int(ln.split(":")[1]):]
            break
    return rarity, base, explicit


def _count_mods(explicit: list[str], candidates) -> int | None:
    """Mods the explicit lines make up, matched against candidate mods; None when a line matches none."""
    plain = [_ANY_TAG.sub("", ln) for ln in explicit]
    by_first: dict[str, list[tuple[str, ...]]] = {}
    for c in candidates:
        by_first.setdefault(c.lines[0], []).append(c.lines)
        by_first.setdefault(c.template_lines[0], []).append(c.template_lines)
    mods, i = 0, 0
    while i < len(plain):
        for lines in by_first.get(plain[i], []):
            if tuple(plain[i:i + len(lines)]) == lines:
                i += len(lines)
                break
        else:
            return None
        mods += 1
    return mods


def check_build(xml: str, *, candidates, points: int | None = None, allocatable=None) -> tuple[list[tuple[int, str]], str]:
    """(jewels as (nodeId, first line), verdict). Verdict is "OK" or the broken rules joined by "; "."""
    root = ET.fromstring(xml)
    spec = _active_spec(root)
    allocated = {int(n) for n in (spec.get("nodes") or "").split(",") if n.strip()} if spec is not None else set()
    items = {int(i.get("id")): (i.text or "") for i in root.findall("./Items/Item")}
    sockets = [(int(s.get("nodeId")), int(s.get("itemId"))) for s in (spec.findall("./Sockets/Socket") if spec is not None else [])
               if int(s.get("itemId") or 0) != 0]
    broken: list[str] = []
    jewels: list[tuple[int, str]] = []
    for node, item_id in sockets:
        rarity, base, explicit = _explicit_lines(items.get(item_id, ""))
        jewels.append((node, explicit[0] if explicit else "?"))
        if node not in allocated:
            broken.append(f"{node}: socket not allocated")
        if rarity != "RARE" or base not in _BASES:
            broken.append(f"{node}: {rarity or '?'} {base or '?'}, not a RARE Crimson/Viridian/Cobalt Jewel")
            continue
        mods = _count_mods(explicit, candidates)
        if mods is None:
            broken.append(f"{node}: an explicit line matches no jewel mod")
        elif mods != 1:
            broken.append(f"{node}: {mods} explicit mods, not 1")
    if len(sockets) > MAX_JEWELS:
        broken.append(f"{len(sockets)} tree jewels, max {MAX_JEWELS}")
    if points is not None:
        used = len([n for n in allocated if allocatable is None or n in allocatable])
        if used > points:
            broken.append(f"{used} points used, {points} available")
    return jewels, "OK" if not broken else "; ".join(broken)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    from junkroan.optimizer.jewel_lines import jewel_line_candidates
    from junkroan.optimizer.tree_graph import TreeGraph
    from junkroan.pob.session import decode_import_code

    sys.path.insert(0, str(ROOT / "scripts"))
    from benchmark import result_stem

    folder = Path(argv[0])
    results = folder / "results.json"
    rows = json.loads(results.read_text(encoding="utf-8")) if results.is_file() else []
    points_of = {result_stem(r): r.get("points") for r in rows if r.get("ok")}
    candidates = jewel_line_candidates()
    allocatable = TreeGraph.load().allocatable
    files = sorted(folder.glob("*.pob.txt"))
    bad = 0
    for f in files:
        stem = f.name[: -len(".pob.txt")]
        m = re.match(r"(.*)-s(\d+)(-no-.*)?$", stem)
        build, seed = (m[1], m[2]) if m else (stem, "?")
        jewels, verdict = check_build(decode_import_code(f.read_text(encoding="utf-8").strip()), candidates=candidates,
                                      points=points_of.get(stem), allocatable=allocatable)
        bad += verdict != "OK"
        shown = ", ".join(f"{n} '{ln}'" for n, ln in jewels) or "no tree jewels"
        print(f"{build} s{seed}: {shown}: {verdict}")
    print(f"{len(files)} builds, {len(files) - bad} OK, {bad} broken")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
