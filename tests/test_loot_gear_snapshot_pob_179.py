"""#179 unit 4: the whole-gear-set snapshot of `LootGear` round-trips in real PoB.

`LootGear.fill` reads its start set off `pob.export_xml()` and re-equips a snapshot from that text; the
fake-PoB tests (test_loot_gear_keep_best_179.py) cannot say whether PoB gives back the same numbers.
Build: the Champion Explosive Arrow fixture (Thicket Bow + Broadhead Arrow Quiver, the weapon partner).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from junkroan.optimizer.loot_gear import LootGear, _equipped_raws, restore_weapon_partner
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_329" / "champion_explosive_arrow.pob.txt"
BASES = {"Weapon 1": "Thicket Bow", "Body Armour": "Conquest Lamellar", "Boots": "Wyvernscale Boots"}
N, SEED_A, SEED_B = 4, 11, 29

pytestmark = [
    pytest.mark.pob,
    pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}"),
]


def _same(a: dict, b: dict) -> list[str]:
    """Keys whose values differ (exact, or 1e-9 relative for floats), with both values."""

    diffs = []
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if x != y and not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12):
                diffs.append(f"{key}: {x!r} != {y!r}")
        elif x != y:
            diffs.append(f"{key}: {x!r} != {y!r}")
    return diffs


@pytest.fixture()
def rig(tmp_path):
    xml = decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())
    rails = Rails.load()
    with PobSession(run_id="test-loot-gear-snapshot-179", artifacts_root=tmp_path) as pob:
        pob.load_xml(xml)
        start_stats = pob.stats(("CombinedDPS", "Life", "TotalEHP"))
        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": start_stats["Life"] * 0.97, "TotalEHP": start_stats["TotalEHP"] * 0.95},
            relations=rails.objective().relations,
        )
        keys = tuple(dict.fromkeys((*objective.stat_keys, "CombinedDPS", "Life")))
        quiver = _equipped_raws(pob.export_xml(), ["Weapon 2"])["Weapon 2"]
        assert quiver, "the fixture's Weapon 2 quiver must be read off the export"
        loot = LootGear(pob, objective, rails, uniques={"Weapon 2": quiver})  # as the pipeline does: the skeleton's unique partner
        yield pob, loot, keys, ["Weapon 1", "Weapon 2", *[s for s in BASES if s != "Weapon 1"]]


def _strip(pob, loot) -> None:
    """Empty the filled slots and the filler's record (the day-1 loot setup), so a fill ends on items it rolled."""

    pob.equip({slot: None for slot in BASES})
    loot.current_raw = {}


def test_restore_best_snapshot_gives_back_every_output(rig) -> None:
    pob, loot, keys, touched = rig
    _strip(pob, loot)
    loot.fill(BASES, passes=2, n=N, seed=SEED_A, bench=False)
    snap = loot._gear_set("snap", _equipped_raws(pob.export_xml(), touched))
    outputs = pob.stats(keys)
    raw_copy = dict(snap.current_raw)
    assert raw_copy, "the fill must have put items into current_raw"

    _strip(pob, loot)
    loot.fill(BASES, passes=2, n=N, seed=SEED_B, bench=False)
    assert _equipped_raws(pob.export_xml(), touched) != snap.equipped, "the second fill must end on another set"
    # the second fill ended on its own best set; put the snapshot back by hand, as _keep_best_gear_set does
    now = _equipped_raws(pob.export_xml(), touched)
    updates = {slot: raw for slot, raw in snap.equipped.items() if now.get(slot) != raw}
    if updates:
        pob.equip(updates)
        for slot in updates:
            restore_weapon_partner(pob, loot.uniques, slot)
    loot.current_raw = dict(snap.current_raw)

    assert _same(outputs, pob.stats(keys)) == []
    assert loot.current_raw == raw_copy


def test_restore_start_set_gives_back_the_start_outputs(rig) -> None:
    pob, loot, keys, touched = rig
    start_xml_equipped = _equipped_raws(pob.export_xml(), touched)
    before = pob.stats(keys)
    start = loot._gear_set("start", start_xml_equipped)

    _strip(pob, loot)
    loot.fill(BASES, passes=2, n=N, seed=SEED_A, bench=False)
    now = _equipped_raws(pob.export_xml(), touched)
    updates = {slot: raw for slot, raw in start.equipped.items() if now.get(slot) != raw}
    assert updates, "the fill must have changed something for the restore to mean anything"
    pob.equip(updates)
    for slot in updates:
        restore_weapon_partner(pob, loot.uniques, slot)

    assert _same(before, pob.stats(keys)) == []
