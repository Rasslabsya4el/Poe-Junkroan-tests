"""Gear transplant measurement helpers, without the PoB runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from gear_transplant import (  # noqa: E402
    MAX_HIT_KEYS,
    RESIST_KEYS,
    _row_without_import_code,
    _top_base_rows,
    active_items,
    active_rare_slots,
    clear_rare_slots,
    item_view,
    json_safe,
    markdown_report,
    metric_row,
    render_items,
    run_references,
    safe_ratio,
    tier_positions,
    write_pob_files,
)
from junkroan.optimizer.objective import Objective  # noqa: E402


XML = """<PathOfBuilding><Items activeItemSet="1">
<Item id="1">Rarity: RARE
Rare Boots
Titan Greaves
Sockets: R-R-B-B</Item>
<Item id="2">Rarity: UNIQUE
Unique Ring
Coral Ring</Item>
<Item id="3">Rarity: RARE
Rare Jewel
Cobalt Jewel</Item>
<Item id="4">Rarity: MAGIC
Magic Flask
Granite Flask</Item>
<ItemSet id="1"><Slot name="Boots" itemId="1"/><Slot name="Ring 1" itemId="2"/>
<Slot name="Jewel 1" itemId="3"/><Slot name="Flask 1" itemId="4"/></ItemSet></Items></PathOfBuilding>"""


class FakePob:
    def __init__(self, items: dict[str, str]) -> None:
        self.items = dict(items)
        self.calls: list[dict[str, object]] = []

    def equip(self, updates: dict[str, object]) -> None:
        self.calls.append(dict(updates))
        for slot, raw in updates.items():
            if raw is None:
                self.items.pop(slot, None)
            else:
                self.items[slot] = str(raw)


def test_only_active_equipment_rares_are_emptied_and_the_unique_survives() -> None:
    items = active_items(XML)
    rares = active_rare_slots(XML)
    pob = FakePob(items)

    assert rares == {"Boots": type(next(iter(rares.values())))(base="Titan Greaves", sockets="R-R-B-B")}
    clear_rare_slots(pob, rares)

    assert pob.calls == [{"Boots": None}]
    assert "Boots" not in pob.items
    assert pob.items["Ring 1"] == active_items(XML)["Ring 1"], "the unique remains equipped"
    assert "Jewel 1" in pob.items and "Flask 1" in pob.items


def test_author_stats_at_the_exact_author_floors_are_feasible_in_the_metric_row() -> None:
    objective = Objective(
        maximize="FullDPS",
        floors={"Life": 4000.0, "TotalEHP": 12000.0, "FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 75.0},
    )
    author = {
        "FullDPS": 500_000.0,
        "Life": 4000.0,
        "TotalEHP": 12000.0,
        "FireResist": 75.0,
        "ColdResist": 75.0,
        "LightningResist": 75.0,
        "PhysicalMaximumHitTaken": 5000.0,
        "FireMaximumHitTaken": 5000.0,
        "ColdMaximumHitTaken": 5000.0,
        "LightningMaximumHitTaken": 5000.0,
    }
    row = metric_row("author", "spell", objective, author, author, author, seconds={"total": 1.0})

    assert row["a"]["feasible"] is True
    assert row["b_loot"]["feasible"] is True
    assert row["c_wishlist"]["feasible"] is True
    assert row["loot_ratio"] == row["wishlist_ratio"] == 1.0


def test_a_failed_reference_becomes_a_row_and_does_not_stop_the_next_reference() -> None:
    def runner(slug: str) -> dict[str, object]:
        if slug == "bad":
            raise RuntimeError("fixture failed")
        return {"ok": True, "slug": slug}

    rows = run_references(["bad", "good"], runner)

    assert rows[0]["ok"] is False and "RuntimeError: fixture failed" in str(rows[0]["error"])
    assert rows[1] == {"ok": True, "slug": "good"}


def test_a_zero_or_nonfinite_author_metric_has_no_ratio() -> None:
    assert safe_ratio(100.0, 0.0) is None
    assert safe_ratio(100.0, float("inf")) is None


def test_weapon_tier_position_override_parses_a_comma_list() -> None:
    assert tier_positions("0.35, 0.50,0.57") == (0.35, 0.5, 0.57)
    with pytest.raises(Exception, match="0..1 list"):
        tier_positions("0.35,1.2")


def test_an_infinite_violation_cannot_destroy_a_finished_run() -> None:
    """A build with no weapon has infinite violation; the results file must still write.

    The candidate tables carry the violation before and after every line, and a
    weapon slot starts empty, so `inf` reaches the payload. With allow_nan=False
    that used to raise after all six references had been measured.
    """

    payload = {"rows": [{"violation": float("inf"), "rows": [{"before_violation": float("-inf"), "after": 1.5}]}],
               "flag": True, "count": 3, "name": "x"}

    safe = json_safe(payload)

    assert json.loads(json.dumps(safe, allow_nan=False)) == {
        "rows": [{"violation": None, "rows": [{"before_violation": None, "after": 1.5}]}],
        "flag": True, "count": 3, "name": "x",
    }


def test_each_finished_build_is_written_as_its_own_pob_file_per_arm(tmp_path) -> None:
    rows = [
        {"ok": True, "slug": "bleed_bow", "wishlist_gear": {"import_code": "CODE-A"}, "loot_gear": {"import_code": "CODE-L"}},
        {"ok": True, "slug": "stormbrand", "wishlist_gear": {}, "loot_gear": {}},
        {"ok": False, "slug": "cold_dot", "wishlist_gear": {"import_code": "CODE-B"}},
    ]

    written = write_pob_files(rows, tmp_path, "fix3")

    assert [path.name for path in written] == ["fix3-bleed_bow.pob.txt", "fix3-bleed_bow-loot.pob.txt"]
    assert (tmp_path / "fix3-bleed_bow.pob.txt").read_text(encoding="utf-8") == "CODE-A"
    assert (tmp_path / "fix3-bleed_bow-loot.pob.txt").read_text(encoding="utf-8") == "CODE-L"


def test_both_arms_keep_their_import_code_out_of_the_results_json() -> None:
    row = {"ok": True, "slug": "x",
           "wishlist_gear": {"items": {}, "import_code": "A"},
           "loot_gear": {"items": {}, "import_code": "L"}}

    stripped = _row_without_import_code(row)

    assert sorted(stripped["wishlist_gear"]) == ["items"]
    assert sorted(stripped["loot_gear"]) == ["items"]
    assert row["loot_gear"]["import_code"] == "L"  # the caller's row is untouched


RAW_ITEM = (
    "Rarity: RARE\nFoo Bar\nImperial Bow\nItem Level: 76\nQuality: 20\nImplicits: 1\n"
    "{tags:elemental}(20-24)% increased Elemental Damage with Attack Skills\n"
    "{tags:physical_damage}{prefix}Adds 19 to 38 Physical Damage\n"
    "{crafted}26% increased Damage over Time\n"
)


def test_a_finished_item_is_read_back_into_the_shape_the_template_arm_reports() -> None:
    view = item_view(RAW_ITEM)

    assert view["base"] == "Imperial Bow"
    assert view["implicit"] == "(20-24)% increased Elemental Damage with Attack Skills"
    assert view["mods"] == [
        {"line": "Adds 19 to 38 Physical Damage", "tier": None, "crafted": False},
        {"line": "26% increased Damage over Time", "tier": None, "crafted": True},
    ]
    assert view["raw"] == RAW_ITEM


def test_the_three_item_sections_use_one_renderer_and_the_same_slot_order() -> None:
    items = {"Boots": item_view(RAW_ITEM), "Weapon 1": item_view(RAW_ITEM)}

    out = render_items("x loot items", items)

    assert out[1] == "## x loot items"
    assert [line for line in out if line.startswith("- ")][0].startswith("- Weapon 1: Imperial Bow")  # weapons first
    assert "  - {crafted} 26% increased Damage over Time" in out
    assert render_items("x author items", {})[-1] == "- (none)"


def test_the_weapon_base_table_keeps_the_taken_base_and_uses_the_effective_value_rank() -> None:
    rows = [
        {"base": f"Filler {index}", "value": 900_000.0, "effective_value": 900_000.0, "rank": index + 3, "verdict": "payable"}
        for index in range(12)
    ] + [{"base": "Bone Bow", "value": 664_663.0, "effective_value": 664_663.0, "rank": 2, "verdict": "TAKEN"},
         {"base": "Imperial Bow", "value": 700_000.0, "effective_value": 679_000.0, "rank": 1, "verdict": "payable"}]

    kept = _top_base_rows(rows)

    assert len(kept) == 8 and [row["base"] for row in kept[:2]] == ["Imperial Bow", "Bone Bow"]
    assert all(row["of_bases"] == 14 for row in kept)
    assert "Imperial Bow" in {row["base"] for row in kept}


def test_the_report_carries_the_author_loot_and_template_items_and_the_base_table() -> None:
    snapshot = {"value": 100.0, "feasible": True, "violation": 0.0, "life": 1.0, "total_ehp": 1.0,
                "max_hits": dict.fromkeys(MAX_HIT_KEYS, 1.0), "resists": dict.fromkeys(RESIST_KEYS, 1.0)}
    row = {
        "ok": True, "slug": "burning_arrow_snipe", "seed": 1, "damage_mode": "DoT", "stat": "CombinedDPS",
        "a": snapshot, "b_loot": snapshot, "c_wishlist": snapshot,
        "loot_ratio": 0.928, "wishlist_ratio": 0.696, "loot_life_ratio": 1.0, "wishlist_life_ratio": 1.0,
        "loot_ehp_ratio": 1.0, "wishlist_ehp_ratio": 1.0, "seconds": {"total": 10.0, "wishlist": 4.0},
        "author_items": {"Weapon 1": item_view(RAW_ITEM)},
        "loot_gear": {"items": {"Weapon 1": item_view(RAW_ITEM)}},
        "wishlist_gear": {"items": {"Weapon 1": {"base": "Bone Bow", "implicit": "", "mods": [], "bench": None}},
                          "weapon_bases": {"Weapon 1": [
                                {"base": "Bone Bow", "implicit": "", "requirements": "dex 80, lvl 23", "drop_level": 23,
                                 "value": 664_663.0, "effective_value": 664_663.0, "violation": 0.0, "payment": None, "verdict": "TAKEN", "of_bases": 22}]}},
    }

    text = markdown_report([row], [])

    for heading in ("## burning_arrow_snipe author items", "## burning_arrow_snipe loot items",
                    "## burning_arrow_snipe wishlist items",
                    "## burning_arrow_snipe Weapon 1: bases PoB was offered"):
        assert heading in text
    assert "| Bone Bow | - | dex 80, lvl 23 | 23 | 664,663 | 664,663 | 0 | - | - | - | TAKEN |" in text
    assert "*of 22 bases*" in text


LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]


@pytest.mark.slow
@pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason="pinned PoB runtime not present")
@pytest.mark.pob
def test_cold_dot_loot_transplant_is_finite_and_preserves_unique_slots() -> None:
    from gear_transplant import measure_reference

    row = measure_reference("cold_dot", loot_n=25, log=lambda _line: None)

    assert row["ok"], row.get("error")
    assert row["b_loot"]["value"] is not None
    assert row["b_loot"]["value"] < float("inf")
    assert all(row["protected_items_unchanged"]["loot"].values())
    assert all(row["unique_items_unchanged"]["loot"].values())
