"""The skeleton read from an export does not depend on the order of its <Slot> elements (#493):
PoB writes them in Lua pairs() order, which differs between worker processes. No PoB."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from build_from_skeleton import skeleton_from_xml  # noqa: E402
from test_skeleton_from_xml import _synthetic  # noqa: E402

_ITEMS = {
    "Ring 2": "Rarity: RARE\nDoom Loop\nIron Ring\nSockets: R",
    "Body Armour": "Rarity: RARE\nDoom Shell\nSimple Robe\nSockets: B-B-B-B",
    "Amulet": "Rarity: UNIQUE\nAtziri's Foible\nPaua Amulet",
    "Belt": "Rarity: UNIQUE\nHeadhunter\nLeather Belt",
    "Helmet": "Rarity: RARE\nDoom Crown\nIron Hat",
    "Flask 2": "Rarity: MAGIC\nDivine Life Flask of Staunching",
    "Flask 1": "Rarity: MAGIC\nGranite Flask of Stone",
    "Jewel 2": "Rarity: RARE\nBeast Eye\nCobalt Jewel",
    "Jewel 1": "Rarity: RARE\nBeast Gaze\nCobalt Jewel",
    "Strange Slot": "Rarity: RARE\nOdd\nIron Ring",
    "Another Slot": "Rarity: RARE\nOdd2\nIron Ring",
}


def _xml(order: list[str]) -> str:
    return _synthetic([("Fireball", True)], items={k: _ITEMS[k] for k in order})


def test_dict_order_does_not_follow_the_slot_element_order() -> None:
    forward = list(_ITEMS)
    sk1 = skeleton_from_xml(_xml(forward))
    sk2 = skeleton_from_xml(_xml(forward[::-1]))
    sk3 = skeleton_from_xml(_xml(forward[3:] + forward[:3]))
    assert sk1.rare_bases and sk1.flasks and sk1.jewels and sk1.uniques, "the fixture must exercise every dict"
    for other in (sk2, sk3):
        for field in ("uniques", "rare_bases", "sockets", "flasks", "jewels"):
            assert list(getattr(sk1, field)) == list(getattr(other, field)), field
    assert list(sk1.rare_bases)[:3] == ["Body Armour", "Helmet", "Ring 2"], "RARE_SLOT_ORDER first"
    assert list(sk1.rare_bases)[3:] == ["Another Slot", "Strange Slot"], "unknown slots after, sorted by name"
