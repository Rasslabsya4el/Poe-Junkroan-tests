"""#429 unit 1: every day-1 template slot's resistance line rolls 36-41 % ("Рез T3 на каждом слоте", rulebook i-day1-templates)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from junkroan.optimizer.wishlist_gear import RESISTANCE_GROUPS, WishlistGear, template_for
from junkroan.pob.session import PobSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

ILVL = 72  # WishlistRails.item_level default for every armour / jewellery slot
# one corpus base per template key (the "Focus" key has no base in this PoB's corpus)
SLOT_BASES = {
    "Helmet": "Hubris Circlet", "Gloves": "Sorcerer Gloves", "Body Armour": "Astral Plate", "Boots": "Sorcerer Boots",
    "Belt": "Leather Belt", "Shield": "Titanium Spirit Shield", "Ring": "Two-Stone Ring", "Amulet": "Onyx Amulet",
    "Quiver": "Broadhead Arrow Quiver",
}


def test_every_slot_resistance_line_rolls_36_to_41(tmp_path) -> None:
    with PobSession(run_id="test-template-resistance-t3", artifacts_root=tmp_path) as pob:
        gear = WishlistGear(pob, None)
        for slot, base in SLOT_BASES.items():
            line = next(line for line in template_for(base, slot, quiver_weapon_shape=False) if line.kind == "resistance")
            for element, group in RESISTANCE_GROUPS.items():
                mod = gear._mod_at_tier(base, ILVL, group, int(line.tier or 1))
                assert mod is not None, (slot, element)
                match = re.search(r"\((\d+)-(\d+)\)%", mod.text)
                assert match is not None, (slot, element, mod.text)
                assert (int(match.group(1)), int(match.group(2))) == (36, 41), (slot, element, line.tier, mod.text)
