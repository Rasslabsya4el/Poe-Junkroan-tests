"""Check the amulet anoint of finished builds (#432).

    python scripts/check_anoints.py <run dir | build .xml | build .pob.txt> [...]

For every build: the Amulet carries exactly one `Allocates <notable>` enchant line, its notable is in the day1 set
(`anoint_candidates(rails.anoint.oil_max)`), and the notable is not also allocated on the tree. An amulet whose base
cannot be anointed (`cannotBeAnointed`, the talismans) is excepted and named. A run directory is read one level deep
(its `*.pob.txt` import codes and `*.xml`), never into a subfolder or through a junction.

PoB's `missing_anoint_warning` ("You have eligible items missing an anoint") is a calculation warning the headless worker
reads while PoB runs; it is not written to the build XML, so this script cannot check it.

Exit 0 when every build is clean, 1 on a violation.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.anoint_candidates import anoint_candidates  # noqa: E402
from junkroan.optimizer.anoint_line import can_anoint  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import decode_import_code  # noqa: E402

_ALLOCATES = re.compile(r"^(?:\{[^}]*\})*Allocates (.+?)\s*$")


@dataclass
class AnointRow:
    name: str
    notable: str | None = None
    excepted: bool = False
    base: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def line(self) -> str:
        if self.problems:
            return f"{self.name}: VIOLATION {'; '.join(self.problems)}"
        if self.excepted:
            return f"{self.name}: ok, excepted: the amulet base {self.base!r} cannot be anointed"
        return f"{self.name}: ok, Allocates {self.notable}"


def _amulet_text(root: ET.Element) -> str | None:
    items = root.find("Items")
    if items is None:
        return None
    sets = items.findall("ItemSet")
    active = next((s for s in sets if s.get("id") == (items.get("activeItemSet") or "1")), sets[0] if sets else None)
    if active is None:
        return None
    item_id = next((s.get("itemId") for s in active.findall("Slot") if s.get("name") == "Amulet"), None)
    if item_id in (None, "0"):
        return None
    return next(((i.text or "").strip() for i in items.findall("Item") if i.get("id") == item_id), None)


def _tree_nodes(root: ET.Element) -> set[int]:
    tree = root.find("Tree")
    if tree is None:
        return set()
    specs = tree.findall("Spec")
    if not specs:
        return set()
    at = int(tree.get("activeSpec") or 1) - 1
    spec = specs[at] if 0 <= at < len(specs) else specs[0]
    return {int(n) for n in (spec.get("nodes") or "").split(",") if n.strip()}


def check_xml(xml: str, day1: dict[str, int], name: str = "build") -> AnointRow:
    """One build's row. `day1` maps a notable's name to its node id."""

    row = AnointRow(name)
    root = ET.fromstring(xml)
    text = _amulet_text(root)
    if not text:
        row.problems.append("no Amulet equipped")
        return row
    lines = [ln.strip() for ln in text.splitlines()]
    row.base = lines[2] if len(lines) > 2 else ""
    found = [m.group(1) for ln in lines if (m := _ALLOCATES.match(ln))]
    if not can_anoint(row.base):
        row.excepted = True
        if found:
            row.problems.append(f"the amulet base {row.base!r} cannot be anointed but carries {found}")
        return row
    if len(found) != 1:
        row.problems.append(f"{len(found)} Allocates lines on the Amulet (expected exactly 1)")
        return row
    row.notable = found[0]
    if row.notable not in day1:
        row.problems.append(f"{row.notable!r} is not in the day1 set")
    elif day1[row.notable] in _tree_nodes(root):
        row.problems.append(f"{row.notable!r} is also allocated on the tree (node {day1[row.notable]})")
    return row


def _builds(paths: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in paths:
        path = Path(raw)
        files = sorted([*path.glob("*.pob.txt"), *path.glob("*.xml")]) if path.is_dir() else [path]
        for file in files:
            text = file.read_text(encoding="utf-8").strip()
            out.append((file.name, text if text.startswith("<") else decode_import_code(text)))
    return out


def main(argv: list[str] | None = None, *, day1: dict[str, int] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    if day1 is None:
        day1 = {c.name: c.node_id for c in anoint_candidates(Rails.load().anoint.oil_max)}
    builds = _builds(argv)
    if not builds:
        print("no builds found")
        return 2
    rows = [check_xml(xml, day1, name) for name, xml in builds]
    for row in rows:
        print(row.line())
    bad = sum(not r.ok for r in rows)
    excepted = [r.name for r in rows if r.excepted and r.ok]
    print(f"{bad} of {len(rows)} builds violate" + (f"; excepted (cannot be anointed): {', '.join(excepted)}" if excepted else "")
          + "; missing_anoint_warning: not in the XML, not checked")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
