"""An anoint (the amulet enchant line `Allocates <notable>`) as PoB sees it (#432).

PoB parses the line to a `GrantedPassive` mod (ModParser.lua:5485) and CalcSetup allocates the node
with no path (CalcSetup.lua:1285-1296); it is not counted in the passive points
(PassiveSpec.lua:823-841). The enchant form in item text is `{enchant}<line>`, counted in `Implicits:`
(Item.lua:1827, :1973).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")

BUILD = "arc_archmage"
NOTABLE = "Combat Stamina"  # recipe ClearOil, VerdantOil, BlackOil: '5% increased maximum Life'
DAY1_OILS = {"ClearOil", "SepiaOil", "AmberOil", "VerdantOil", "TealOil", "AzureOil", "IndigoOil", "VioletOil", "CrimsonOil", "BlackOil"}


def _notable() -> dict:
    records = json.loads((PROJECT_ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "passives.json").read_text(encoding="utf-8"))["records"]
    return next(r for r in records if r["is_notable"] and r["name"] == NOTABLE)


def _amulet_raw(xml: str) -> str:
    items = ET.fromstring(xml).find("Items")
    active = next(s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1"))
    item_id = next(s.get("itemId") for s in active.findall("Slot") if s.get("name") == "Amulet")
    return next(i.text for i in items.findall("Item") if i.get("id") == item_id).strip("\n\t ")


def _anointed(raw: str, notable: str) -> str:
    """The same amulet with `{enchant}Allocates <notable>` ahead of its implicits, counted in `Implicits:`."""

    lines = raw.splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.startswith("Implicits:"))
    lines[at] = f"Implicits: {int(lines[at].split(':')[1]) + 1}"
    lines.insert(at + 1, f"{{enchant}}Allocates {notable}")
    return "\n".join(lines)


@needs_pob
@pytest.mark.pob
def test_anoint_allocates_the_notable_for_free_and_the_fast_trial_agrees_with_the_full_equip() -> None:
    recipe = _notable()["recipe"]
    assert set(recipe) <= DAY1_OILS, recipe

    xml = decode_import_code((FIXTURES / f"{BUILD}.pob.txt").read_text(encoding="utf-8").strip())
    raw = _amulet_raw(xml)
    anointed = _anointed(raw, NOTABLE)
    node_id = int(_notable()["node_id"])

    with PobSession(run_id="test-anoint-pob", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        pob.equip({"Amulet": raw})  # the text this test re-equips, so the baseline is the same item
        before_tree = pob.mutate_nodes()
        before_life = pob.stats(("Life",))["Life"]
        assert node_id not in before_tree["allocated_node_ids"]
        assert pob.granted_passives() == ()

        fast = pob.trial_stats([{"item": {"slot": "Amulet", "raw": anointed}}], ("Life", "TotalEHP"), mode="fast")[0]
        assert fast["ok"], fast
        assert pob.granted_passives() == (), "a trial restores the build"

        pob.equip({"Amulet": anointed})
        after_tree = pob.mutate_nodes()
        after_life = pob.stats(("Life",))["Life"]
        full_ehp = pob.stats(("TotalEHP",))["TotalEHP"]
        # (a) the node is allocated in PoB's calc, through the grant and not through the tree
        assert pob.granted_passives() == (node_id,)
        assert node_id not in after_tree["allocated_node_ids"]
        assert after_life > before_life
        # (b) not counted in the passive points
        assert after_tree["points_used"] == before_tree["points_used"]
        assert after_tree["allocated_node_ids"] == before_tree["allocated_node_ids"]

        # PoB's equip path (ItemsTab:CreateDisplayItemFromRaw -> CopyAnointsAndEldritchImplicits,
        # ItemsTab.lua:1817-1829) hands the worn amulet's anoint to a new amulet that has none, so the
        # plain text equipped over the anointed one keeps the node; the line goes by emptying the slot first.
        pob.equip({"Amulet": raw})
        assert pob.granted_passives() == (node_id,)
        pob.equip({"Amulet": None})
        pob.equip({"Amulet": raw})
        gone_tree = pob.mutate_nodes()
        # (c) without the line the node is gone
        gone_life = pob.stats(("Life",))["Life"]
        assert pob.granted_passives() == ()
        assert gone_life == pytest.approx(before_life)
        assert gone_tree["points_used"] == before_tree["points_used"]

    print(f"\nanoint {NOTABLE} on {BUILD}: Life {before_life} -> {after_life}; fast trial Life {fast['stats']['Life']}, TotalEHP {fast['stats']['TotalEHP']}; full TotalEHP {full_ehp}")
    assert fast["stats"]["Life"] == pytest.approx(after_life, rel=0.001)
    assert fast["stats"]["TotalEHP"] == pytest.approx(full_ehp, rel=0.001)
