"""Drift test (#425): every rulebook `machine` value that has a rail counterpart equals the rail.

The rulebook (docs/rulebook/loadout-rulebook.json) is the owner's word; the optimizer reads only the
copy in src/junkroan/optimizer/rails_default.json. No runtime code reads the rulebook, so this test is
the only thing that notices when the two files part.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from junkroan.optimizer.rails import DEFAULT_RAILS_PATH, Rails

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_PATH = ROOT / "docs" / "rulebook" / "loadout-rulebook.json"
NO_RAIL = "no rail"

# rulebook key (`<key>` or `<key>.<tier>` inside an entry's `machine` block)
#   -> (attribute path on Rails, rail JSON path for the message, ticket that adds the rail).
# NO_RAIL as the attribute path: the rail does not exist yet, the ticket adds it.
# A known open difference goes into XFAIL: key -> issue number.
TABLE: dict[str, tuple[str, str, str | None]] = {
    "gem_level.day1": ("gems.level", "gems.level", None),
    "gem_quality.day1": ("gems.quality", "gems.quality", None),
    # #802: gm-vaal / gm-transfigured day 1 = the same 18 / 0 pair as every gem; t16 / endgame / mirror are carried, not read
    "vaal_gem.day1.level": ("gems.level", "gems.level", None),
    "vaal_gem.day1.quality": ("gems.quality", "gems.quality", None),
    "vaal_gem.t16": (NO_RAIL, "-", "#802"),
    "vaal_gem.endgame": (NO_RAIL, "-", "#802"),
    "vaal_gem.mirror": (NO_RAIL, "-", "#802"),
    "transfigured_gem.day1.level": ("gems.level", "gems.level", None),
    "transfigured_gem.day1.quality": ("gems.quality", "gems.quality", None),
    # the LOOT item level; #438 adds the template / weapon ilvl keys later
    "item_level_max.day1": ("gear.item_level", "gear.item_level", None),
    "template_item_level.day1": ("gear.wishlist.item_level.default", "gear.wishlist.item_level.default", None),
    "weapon_item_level.day1": ("gear.wishlist.item_level.Weapon 1", "gear.wishlist.item_level.Weapon 1", None),
    "base_level_max.day1": ("gear.wishlist.base_level_max", "gear.wishlist.base_level_max", None),
    "open_mod_never_below_share": ("gear.wishlist.open_mod_never_below_share", "gear.wishlist.open_mod_never_below_share", None),
    "open_mod_two_lines_below_share": (NO_RAIL, "-", "#428"),
    "bench_max_map_tier.day1": ("gear.bench.max_map_tier", "gear.bench.max_map_tier", None),
    "attribute_plus30_nodes_max.day1": (NO_RAIL, "-", "#430"),
    # #785: PoB's "None" is "Kill all" (ConfigOptions.lua:136); the rail is character.bandit
    "bandit.day1": ("bandit", "character.bandit", None),
    "oil_max.day1": ("anoint.oil_max", "anoint.oil_max", None),
    # the j-regular (regular rare jewels) entry: the only one carrying these two keys (#434)
    "useful_mods.day1": ("gear.jewels.lines", "gear.jewels.lines", None),
    "count_max.day1": ("gear.jewels.count_max", "gear.jewels.count_max", None),
    # the t-cluster entry (#433, #602: day 1 has none, sizes [] / passives 0); count_max / notables_max / screen_keep have no rulebook key; t16 / endgame carry the old day-1 / any-type rule, no rails yet
    "sizes.day1": ("gear.clusters.sizes", "gear.clusters.sizes", None),
    "passives.large.day1": ("gear.clusters.passives.large", "gear.clusters.passives.large", None),
    "passives.medium.day1": ("gear.clusters.passives.medium", "gear.clusters.passives.medium", None),
    # o-flasks points at the common rails (item_level_max / base_level_max above, same keys, same values); o-tinctures (#436)
    "tinctures.day1": ("gear.flasks.tinctures", "gear.flasks.tinctures", None),
    # a [min, max] range; the rail (character.level 77) is one number inside it, not a copy
    "level.day1": (NO_RAIL, "-", "#424"),
    # day 1 is read by junkroan.search.sockets.coloured_max("day1") and enforced by socket_step.colour_step (max_picks), not a Rails value; t16 / endgame / mirror are not read yet
    "coloured_max.day1": (NO_RAIL, "-", "#435"),
    "coloured_max.t16": (NO_RAIL, "-", "#435"),
    "coloured_max.endgame": (NO_RAIL, "-", "#435"),
    "coloured_max.mirror": (NO_RAIL, "-", "#435"),
}
XFAIL: dict[str, str] = {}


def _flatten(prefix: str, value: object, out: dict[str, object]) -> None:
    if isinstance(value, dict):
        for sub, leaf in value.items():
            _flatten(f"{prefix}.{sub}", leaf, out)
    else:
        out[prefix] = value


def rulebook_machine_values() -> dict[str, object]:
    """Every `machine` leaf of the rulebook, keyed `<key>` or `<key>.<tier>` (nested keys joined by dots)."""

    data = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for entry in data["entries"]:
        for key, value in (entry.get("machine") or {}).items():
            _flatten(key, value, out)
    return out


def _walk(obj: object, path: str) -> object:
    for part in path.split("."):
        obj = obj[part] if isinstance(obj, Mapping) else getattr(obj, part)
    return obj


def check_key(key: str, rails: Rails) -> None:
    """Raise AssertionError naming the key, both values and both files when rulebook and rail differ."""

    attr_path, json_path, ticket = TABLE[key]
    if attr_path == NO_RAIL:
        pytest.skip(f"{key}: no rail yet, added by {ticket}")
    rulebook_value = rulebook_machine_values()[key]
    rail_value = _walk(rails, attr_path)
    assert rulebook_value == rail_value, (
        f"rulebook/rail drift on `{key}`: rulebook {rulebook_value!r} ({RULEBOOK_PATH.relative_to(ROOT)}) "
        f"!= rail {rail_value!r} at {json_path} ({Path(DEFAULT_RAILS_PATH).relative_to(ROOT)})"
    )


def _param(key: str):
    marks = [pytest.mark.xfail(reason=f"known open difference, {XFAIL[key]}", strict=True)] if key in XFAIL else []
    return pytest.param(key, id=key, marks=marks)


@pytest.mark.parametrize("key", [_param(k) for k in TABLE])
def test_rulebook_machine_value_equals_rail(key: str) -> None:
    check_key(key, Rails.load())


def test_table_covers_every_rulebook_machine_family() -> None:
    # other tiers (t16, endgame, ...) are not day-1 rails; a key whose whole family is absent is unmapped
    families = {k.split(".")[0] for k in TABLE}
    unmapped = sorted(k for k in rulebook_machine_values() if k.split(".")[0] not in families)
    assert not unmapped, f"rulebook machine keys with neither a rail nor a `no rail` row in TABLE: {unmapped}"


def test_drift_is_reported_with_key_and_both_values() -> None:
    rails = Rails.load()
    drifted = dataclasses.replace(rails, gems=dataclasses.replace(rails.gems, level=rails.gems.level + 1))
    with pytest.raises(AssertionError) as err:
        check_key("gem_level.day1", drifted)
    message = str(err.value)
    assert "gem_level.day1" in message
    assert "18" in message and "19" in message
    assert "loadout-rulebook.json" in message and "rails_default.json" in message


def test_cluster_rulebook_cells_move_one_loadout_up() -> None:
    """#602: day 1 none, t16 = the old day-1 rule (large / medium, 12 / 6), endgame = all types, any passives."""

    v = rulebook_machine_values()
    assert v["sizes.day1"] == [] and v["passives.large.day1"] == 0 and v["passives.medium.day1"] == 0
    assert v["sizes.t16"] == ["large", "medium"] and v["passives.large.t16"] == 12 and v["passives.medium.t16"] == 6
    assert v["sizes.endgame"] == "all" and v["passives.large.endgame"] is None and v["passives.medium.endgame"] is None
    rails = Rails.load().gear.clusters
    assert rails.count_max == 0


def test_bandit_day1_is_kill_all() -> None:
    """#785: the rulebook's c-bandits day-1 `machine` value is PoB's "None" ("Kill all") and the rail is the same."""

    assert rulebook_machine_values()["bandit.day1"] == "None"
    assert Rails.load().bandit == "None"
