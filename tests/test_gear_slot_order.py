"""The weapon slots are filled first, and no ranking key is ever nan (2026-09-18).

An attack build with an empty weapon slot deals no damage at all: its violation is infinite and
its CombinedDPS missing, so every candidate for every other slot scored exactly the same, and
`_rank`'s inf - inf = nan made the pick arbitrary -- nan wins against nothing and loses to
nothing, so whichever candidate PoB returned first kept the slot. bleed_bow filled eight slots
that way before its bow went on (a body armour picked for "Reflects Physical Damage").

`RARE_SLOT_ORDER` now starts with the weapon slots -- in both fillers, in every gear pass of the
construction and in the improvement loop's per-slot moves -- and a nan key becomes -inf: such a
candidate is worth the least, not an unordered amount. A spell is unaffected (PoB scores it
without a weapon), so the order is unconditional. The rest of the order is unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.audit import audit_skeleton_uniques, worn_unique_names
from junkroan.optimizer.gear_filler import GearFiller
from junkroan.optimizer.loot_gear import RARE_SLOT_ORDER, WEAPON_SLOTS, LootGear, _rank, ordered_slots, weapons_first
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import _comparable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

DPS = Objective(maximize="CombinedDPS")
NOTHING = Score(neg_violation=-math.inf, value=-math.inf)  # no weapon: infinite violation, no number at all


# -- the order -------------------------------------------------------------------


def test_the_fill_order_starts_with_the_weapon_slots() -> None:
    assert WEAPON_SLOTS == ("Weapon 1", "Weapon 2")  # "Weapon 2" is the shield / quiver slot too
    assert RARE_SLOT_ORDER[:2] == WEAPON_SLOTS
    # the rest is the order it always had, so older logs read the same
    assert RARE_SLOT_ORDER[2:] == ("Body Armour", "Helmet", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2")


def test_ordered_slots_puts_the_weapons_first_and_an_unknown_slot_last() -> None:
    held = {"Body Armour": "", "Ring 1": "", "Weapon 2": "", "Weapon 1": "", "Trinket": ""}
    assert ordered_slots(held) == ["Weapon 1", "Weapon 2", "Body Armour", "Ring 1", "Trinket"]
    assert ordered_slots(["Boots", "Helmet"]) == ["Helmet", "Boots"]  # a build with no weapon slot is untouched


def test_weapons_first_keeps_the_callers_own_ranking_among_the_rest() -> None:
    """The joint kick ranks its slots by damage headroom and keeps that ranking: only the weapon
    slots move to the front, and the sort is stable."""

    assert weapons_first(["Belt", "Weapon 2", "Gloves", "Weapon 1"]) == ["Weapon 1", "Weapon 2", "Belt", "Gloves"]
    assert weapons_first(["Belt", "Gloves"]) == ["Belt", "Gloves"]


# -- the ranking -----------------------------------------------------------------


def test_no_ranking_key_is_nan_when_a_candidate_leaves_the_build_without_a_number() -> None:
    """inf - inf and -inf - -inf are both nan; every filler's key turns them into -inf."""

    key = _rank(NOTHING, NOTHING)
    assert not any(math.isnan(k) for k in key)
    assert key == (-math.inf, -math.inf)
    assert GearFiller._rank_key(NOTHING, NOTHING) == key  # the three fillers rank by one definition
    assert _comparable(NOTHING, NOTHING) == key


def test_a_candidate_with_a_number_beats_one_without() -> None:
    real = Score(neg_violation=-2.0, value=1000.0)
    assert _rank(NOTHING, real) > _rank(NOTHING, NOTHING)
    assert _rank(NOTHING, NOTHING) < _rank(NOTHING, Score(neg_violation=-math.inf, value=1.0))


class _BlindPob:
    """A build with no number at all (the empty weapon slot's state: `stats` answers nothing, so
    the objective reads a missing value and an infinite shortfall) and two rolls for the slot --
    one that leaves it there, one that carries a real number."""

    def __init__(self) -> None:
        self.equipped: list[dict] = []

    def stats(self, keys):
        return {}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        return [{"raw": "blind", "mod_ids": set()}, {"raw": "real", "mod_ids": set()}]

    def trial_stats(self, trials, keys, mode="fast"):
        return [
            {"ok": True, "stats": {} if t["item"]["raw"] == "blind" else {"CombinedDPS": 500.0, "Life": 5000.0}}
            for t in trials
        ]

    def equip(self, items):
        self.equipped.append(dict(items))


def test_the_roll_that_gives_the_build_a_number_wins_the_slot() -> None:
    """With nan keys the first roll PoB returned kept the slot whatever the others were worth
    (nan > anything is False). The blind roll now ranks last and the real one is equipped."""

    pob = _BlindPob()
    loot = LootGear(pob, Objective(maximize="CombinedDPS", floors={"Life": 4000}), Rails.load())

    res = loot.fill_slot("Body Armour", "Simple Robe", n=2, bench=False)

    assert res.raw == "real" and res.after_loot.value == 500.0
    assert pob.equipped == [{"Body Armour": "real"}] and loot.current_raw == {"Body Armour": "real"}


# -- the fillers walk the order --------------------------------------------------


class _OrderPob:
    """Enough of PobSession for `LootGear.fill` to reach every slot's roll and come back with
    nothing: the bases are named after their slots, so the rolls record the order."""

    def __init__(self) -> None:
        self.rolled: list[str] = []

    def stats(self, keys):
        return {k: 0.0 for k in keys} | {"CombinedDPS": 1000.0}

    def export_xml(self):  # the fill reads the set it starts from (#179): an empty build
        return "<PathOfBuilding><Items activeItemSet=\"1\"><ItemSet id=\"1\"/></Items></PathOfBuilding>"

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        self.rolled.append(base)
        return []

    def trial_stats(self, trials, keys, mode="fast"):
        return []


def test_the_loot_filler_rolls_the_weapon_slots_before_the_rest() -> None:
    pob = _OrderPob()
    bases = {slot: f"base {slot}" for slot in ("Boots", "Body Armour", "Weapon 2", "Weapon 1", "Amulet")}

    LootGear(pob, DPS, Rails.load()).fill(bases, passes=1, n=4)

    assert pob.rolled == [f"base {s}" for s in ("Weapon 1", "Weapon 2", "Body Armour", "Boots", "Amulet")]


# -- against the pinned PoB ------------------------------------------------------


def _rare_bases(xml: str) -> dict[str, str]:
    """slot -> base of every rare the reference wears (line 3 of PoB's item text)."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    by_id: dict[str, tuple[str, str]] = {}
    for item in items.findall("Item"):
        lines = [ln.strip() for ln in (item.text or "").splitlines() if ln.strip()]
        rarity = next((ln.split(":", 1)[1].strip().upper() for ln in lines if ln.startswith("Rarity:")), "")
        if len(lines) > 2:
            by_id[item.get("id")] = (rarity, lines[2])
    active = items.get("activeItemSet") or "1"
    item_set = next((s for s in items.findall("ItemSet") if s.get("id") == active), None)
    out: dict[str, str] = {}
    for slot in (item_set.findall("Slot") if item_set is not None else items.findall("Slot")):
        name, item_id = slot.get("name"), slot.get("itemId")
        if not name or item_id in (None, "0") or "Swap" in name or "Abyssal" in name or name.startswith("Flask"):
            continue
        rarity, base = by_id.get(item_id, ("", ""))
        if rarity == "RARE" and base:
            out[name] = base
    return out


@pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
@pytest.mark.pob
def test_bleed_bow_fills_its_bow_first_and_judges_the_body_armour_with_a_number() -> None:
    """The build this was measured on: with every rare off, PoB gives bleed_bow no DPS at all,
    so the eight slots the old order filled before the bow were judged blind. The bow goes first
    now, and the body armour is judged against a real CombinedDPS."""

    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((FIXTURES / "bleed_bow.pob.txt").read_text(encoding="utf-8").strip())
    rares = _rare_bases(xml)
    assert "Weapon 1" in rares and ordered_slots(rares)[0] == "Weapon 1"

    with PobSession(run_id="test-slot-order", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        pob.equip({slot: None for slot in rares})
        bare = pob.stats(("CombinedDPS",))["CombinedDPS"]
        wanted = {s: rares[s] for s in ("Weapon 1", "Weapon 2", "Body Armour") if s in rares}
        results = LootGear(pob, DPS, Rails.load()).fill(wanted, passes=1, n=20, bench=False)

    assert bare == 0  # nothing for the other eight slots to be judged by
    assert [r.slot for r in results][: len(wanted)] == ordered_slots(wanted)
    assert results[0].slot == "Weapon 1" and results[0].after_loot.value > 0
    body = next(r for r in results if r.slot == "Body Armour")
    assert body.before.value > 0, "the body armour is judged with a weapon in hand"


# -- the skeleton's unique in Weapon 2 comes back ---------------------------------


def _worn_id(xml: str, slot: str) -> str:
    root = ET.fromstring(xml)
    items = root.find("Items")
    active = next(s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1"))
    return next((s.get("itemId") or "0" for s in active.findall("Slot") if s.get("name") == slot), "0")


def _slot_text(xml: str, slot: str) -> str:
    root = ET.fromstring(xml)
    items = root.find("Items")
    by_id = {i.get("id"): (i.text or "") for i in items.findall("Item")}
    return by_id[_worn_id(xml, slot)]


@pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
@pytest.mark.pob
def test_filling_weapon_one_puts_the_skeleton_quiver_back_in_weapon_two() -> None:
    """An empty Weapon 1 makes a quiver in Weapon 2 invalid, and PoB's Populate() drops it without a
    word at the end of the equip (ItemSlotControl.lua:94); the fill that follows put a bow on and
    never restored it, so the build was judged without its unique (6 of the 5 archived runs'
    burning_arrow_snipe builds). `LootGear.fill_slot` now equips the slot's skeleton unique again
    once the slot it depends on is filled. Without the mapping the loss still happens -- the same
    calls, side by side."""

    from junkroan.pob.session import PobSession, decode_import_code

    xml = decode_import_code((FIXTURES / "burning_arrow_snipe.pob.txt").read_text(encoding="utf-8").strip())
    bow = _rare_bases(xml)["Weapon 1"]
    quiver_raw = _slot_text(xml, "Weapon 2")
    gear = {"Weapon 2": quiver_raw}  # slot -> raw, what the pipeline passes from the skeleton
    names = {"Weapon 2": "The Poised Prism"}

    with PobSession(run_id="test-quiver-restore", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        pob.equip({"Weapon 1": None})
        assert _worn_id(pob.export_xml(), "Weapon 2") == "0"  # PoB took the invalid quiver with Weapon 1

        LootGear(pob, DPS, Rails.load()).fill_slot("Weapon 1", bow, n=4, bench=False)
        lost = pob.export_xml()
        assert _worn_id(lost, "Weapon 1") != "0"
        assert "The Poised Prism" not in worn_unique_names(lost)
        assert [f.detail for f in audit_skeleton_uniques(lost, names)] == ["Weapon 2: The Poised Prism"]

        LootGear(pob, DPS, Rails.load(), uniques=gear).fill_slot("Weapon 1", bow, n=4, bench=False)
        kept = pob.export_xml()

    assert _worn_id(kept, "Weapon 1") != "0"
    assert "The Poised Prism" in worn_unique_names(kept)
    assert audit_skeleton_uniques(kept, names) == []
