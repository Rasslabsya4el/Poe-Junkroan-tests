"""Row 5 of #434: scripts/check_jewels.py on synthetic PoB XML (no PoB session)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_jewels import check_build  # noqa: E402
from junkroan.optimizer.jewel_lines import jewel_line_candidates  # noqa: E402
from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT  # noqa: E402

SOURCE = Path(os.environ.get("JUNKROAN_POB_SOURCE") or DEFAULT_SOURCE_ROOT)
pytestmark = pytest.mark.skipif(not (SOURCE / "src" / "Data" / "ModJewel.lua").is_file(), reason=f"PoB source data not present at {SOURCE}")

CANDS = jewel_line_candidates(SOURCE) if (SOURCE / "src" / "Data" / "ModJewel.lua").is_file() else ()
ONE = next((c for c in CANDS if len(c.lines) == 1), None)
OTHER = next((c for c in CANDS if len(c.lines) == 1 and c.group != ONE.group), None)
HYBRID = next((c for c in CANDS if len(c.lines) == 2), None)


def _item(i: int, lines, rarity="RARE", base="Crimson Jewel") -> str:
    body = "\n".join(["Rarity: " + rarity, "Name", base, "Item Level: 72", "Implicits: 0", *lines])
    return f'<Item id="{i}">\n{body}\n</Item>'


def _xml(items: list[str], sockets: list[tuple[int, int]], nodes=(1, 2, 3, 4, 5, 6)) -> str:
    sock = "".join(f'<Socket nodeId="{n}" itemId="{i}"/>' for n, i in sockets)
    return (f'<PathOfBuilding><Tree activeSpec="1"><Spec nodes="{",".join(map(str, nodes))}"><Sockets>{sock}</Sockets></Spec></Tree>'
            f'<Items>{"".join(items)}</Items></PathOfBuilding>')


def _verdict(xml: str, **kw) -> str:
    return check_build(xml, candidates=CANDS, **kw)[1]


def test_two_valid_jewels_ok() -> None:
    xml = _xml([_item(1, ONE.lines), _item(2, OTHER.lines, base="Cobalt Jewel")], [(1, 1), (2, 2)])
    jewels, verdict = check_build(xml, candidates=CANDS)
    assert verdict == "OK" and [n for n, _ in jewels] == [1, 2]


def test_three_jewels_fail() -> None:
    xml = _xml([_item(i, ONE.lines) for i in (1, 2, 3)], [(1, 1), (2, 2), (3, 3)])
    assert "3 tree jewels" in _verdict(xml)


def test_magic_jewel_fails() -> None:
    assert "not a RARE" in _verdict(_xml([_item(1, ONE.lines, rarity="MAGIC")], [(1, 1)]))


def test_two_mods_fail() -> None:
    assert "2 explicit mods" in _verdict(_xml([_item(1, ONE.lines + OTHER.lines)], [(1, 1)]))


def test_hybrid_one_mod_ok_with_range_tag() -> None:
    lines = ["{range:0.5}" + HYBRID.lines[0], HYBRID.lines[1]]
    assert _verdict(_xml([_item(1, lines)], [(1, 1)])) == "OK"


def test_unallocated_socket_fails() -> None:
    assert "socket not allocated" in _verdict(_xml([_item(1, ONE.lines)], [(99, 1)]))


def test_points_over_fails() -> None:
    xml = _xml([_item(1, ONE.lines)], [(1, 1)])
    assert _verdict(xml, points=6) == "OK"
    assert "6 points used, 5 available" in _verdict(xml, points=5)
