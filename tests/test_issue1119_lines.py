"""Issue #1119 unit 1 (lines): every day-1 line with its surface, source and parse outcome.

Fake rails and a tiny corpus only: no PoB session, no real corpus files. The expected rows are literal
values worked out from the rule in `scripts/day1_lines.py`, never recomputed by the code under test.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from day1_lines import Day1Corpus, day1_rows, parse_modcache  # noqa: E402
from junkroan.optimizer.rails import BenchRails, GearRails, Rails, WishlistRails  # noqa: E402


def fake_rails(item_level: dict[str, int] | None = None, map_tier: int = 10) -> Rails:
    return Rails(
        gear=GearRails(
            wishlist=WishlistRails(item_level=item_level or {"default": 72}),
            bench=BenchRails(max_map_tier=map_tier),
        ),
    )


def rows_of(rails: Rails, **parts) -> list[dict]:
    return list(day1_rows(rails, Day1Corpus(**parts)))


def pick(rows: list[dict], surface: str) -> list[tuple]:
    return sorted((r["line"], r["source"], r["outcome"]) for r in rows if r["surface"] == surface)


def test_tree_surfaces_take_every_node_with_its_modcache_outcome():
    rows = rows_of(
        fake_rails(),
        passives=[
            {"node_id": 6, "is_notable": True, "name": "Twin Terrors", "stats": ["10% increased Damage"]},
            {"node_id": 7, "is_notable": False, "name": "Small", "stats": ["+5 to Strength"]},
        ],
        keystones=[{"node_id": 3354, "name": "Lone Messenger", "stats": ["Lone line"]}],
        masteries=[{"node_id": 9, "mastery_effects": [{"effect_id": 1, "stats": ["Mastery line"]}]}],
        ascendancies=[{"ascendancy_id": "Abyssal", "nodes": [{"node_id": 40, "stats": ["Asc line"]}]}],
        modcache={"10% increased Damage": "full", "Lone line": "none"},
        parse_outcomes={"Asc line": {"ok": True, "unsupported": True, "extra": "x", "mod_types": ["BASE"]}},
    )
    assert pick(rows, "notable") == [("10% increased Damage", 6, "full")]
    assert pick(rows, "keystone") == [("Lone line", 3354, "none")]
    assert pick(rows, "mastery") == [("Mastery line", 9, "missing")]
    assert pick(rows, "ascendancy") == [("Asc line", 40, "partial")]


def test_unique_passes_only_the_day_one_unique_rails_and_no_jewel_or_tincture():
    rows = rows_of(
        fake_rails(),
        uniques=[
            {"name": "Good Unique", "type": "Boots", "availability": "core", "req_level": 60, "tier": 4,
             "lines": ["+25 to Strength", "Flavour"]},
            {"name": "Legacy", "type": "Boots", "availability": "legacy", "req_level": 10, "tier": 4, "lines": ["x"]},
            {"name": "Too High", "type": "Boots", "availability": "core", "req_level": 71, "tier": 4, "lines": ["y"]},
            {"name": "Tier One", "type": "Boots", "availability": "core", "req_level": 10, "tier": 1, "lines": ["z"]},
            {"name": "Tincture Thing", "type": "Tincture", "availability": "core", "req_level": 1, "tier": 5, "lines": ["t"]},
            {"name": "Jewel One, Ghastly Eye Jewel", "type": "Jewel", "availability": "core", "req_level": 0,
             "tier": None, "lines": ["j"]},
        ],
        modcache={"+25 to Strength": "full"},
    )
    assert pick(rows, "unique") == [
        ("+25 to Strength", "Good Unique", "full"),
        ("Flavour", "Good Unique", "missing"),
    ]


def test_unique_jewel_needs_the_owner_form_day_one_loadout():
    rows = rows_of(
        fake_rails(),
        uniques=[
            {"name": "Amanamu's Gaze, Ghastly Eye Jewel", "type": "Jewel", "availability": "core", "req_level": 0,
             "tier": None, "lines": ["Jewel line A"]},
            {"name": "Brutal Restraint, Timeless Jewel", "type": "Jewel", "availability": "core", "req_level": 0,
             "tier": None, "lines": ["Jewel line B"]},
            {"name": "Unlisted, Viridian Jewel", "type": "Jewel", "availability": "core", "req_level": 0,
             "tier": None, "lines": ["Jewel line C"]},
        ],
        unique_jewel_form={
            "amanamu-s-gaze": {"loadout": "endgame"},
            "brutal-restraint": {"loadout": "day1"},
        },
        modcache={"Jewel line B": "partial"},
    )
    assert pick(rows, "unique_jewel") == [("Jewel line B", "Brutal Restraint, Timeless Jewel", "partial")]


def test_gear_affix_rolls_the_midpoint_and_keeps_only_item_level_and_spawning_mods():
    rows = rows_of(
        fake_rails({"default": 72}),
        explicit=[
            {"id": "Strength1", "type": "Suffix", "level": 1, "template": ["+(8-12) to Strength"], "spawns": True},
            {"id": "TooHigh", "type": "Prefix", "level": 73, "template": ["+5 to Life"], "spawns": True},
            {"id": "Edge", "type": "Prefix", "level": 72, "template": ["+5 to Dexterity"], "spawns": True},
            {"id": "NoSpawn", "type": "Prefix", "level": 5, "template": ["+9 to Intelligence"], "spawns": False},
        ],
        modcache={"+15 to Strength": "full", "+(8-12) to Dexterity": "full"},
    )
    # the midpoint of (8-12) is 10; a range-keyed cache entry is not evidence for a rolled line
    assert pick(rows, "gear_affix") == [
        ("+10 to Strength", "Strength1", "full"),
        ("+5 to Dexterity", "Edge", "missing"),
    ]


def test_bench_craft_obeys_the_map_tier_of_its_unlock():
    rows = rows_of(
        fake_rails(map_tier=10),
        bench=[
            {"id": "BenchTen", "type": "Prefix", "level": 10, "template": ["+(20-30) to Armour"],
             "unlock": {"where": "map", "tier": 10}},
            {"id": "BenchTwelve", "type": "Prefix", "level": 10, "template": ["+(20-30) to Evasion"],
             "unlock": {"where": "map", "tier": 12}},
        ],
    )
    assert pick(rows, "gear_affix") == [("+25 to Armour", "BenchTen", "missing")]


def test_flask_mods_follow_the_item_level_rail():
    rows = rows_of(
        fake_rails({"default": 72}),
        flasks=[
            {"id": "FlaskA", "type": "Prefix", "level": 60, "lines": ["+ Flask line"]},
            {"id": "FlaskB", "type": "Suffix", "level": 80, "lines": ["- Flask line"]},
        ],
        modcache={"+ Flask line": "none"},
    )
    assert pick(rows, "flask") == [("+ Flask line", "FlaskA", "none")]


def test_parse_outcomes_file_wins_over_modcache_and_a_line_in_neither_is_missing():
    rows = rows_of(
        fake_rails(),
        passives=[{"node_id": 1, "is_notable": True, "stats": ["Both"]}],
        modcache={"Both": "none"},
        parse_outcomes={"Both": {"ok": True, "unsupported": False, "extra": None, "mod_types": ["BASE"]}},
    )
    assert pick(rows, "notable") == [("Both", 1, "full")]


def test_parse_outcome_without_mods_is_none_and_with_extra_is_partial():
    rows = rows_of(
        fake_rails(),
        passives=[{"node_id": 2, "is_notable": True, "stats": ["No mods", "Extra text"]}],
        parse_outcomes={
            "No mods": {"ok": False, "unsupported": True, "extra": None, "mod_types": []},
            "Extra text": {"ok": True, "unsupported": True, "extra": "rest", "mod_types": ["FLAG"]},
        },
    )
    assert pick(rows, "notable") == [("Extra text", 2, "partial"), ("No mods", 2, "none")]


def test_parse_modcache_classifies_the_cache_tail():
    text = "\n".join(
        [
            'c["+15 to Strength"]={{[1]={name="Str"}},nil}',
            'c["Empty line"]={{},nil}',
            'c["Only extra"]={nil," Only extra "}',
            'c["Partial line"]={{[1]={name="Y"}},"extra text "}',
            'local c=...c["Escaped \\"q\\""]={nil," Escaped "}',
        ]
    )
    assert parse_modcache(text) == {
        "+15 to Strength": "full",
        "Empty line": "none",
        "Only extra": "none",
        "Partial line": "partial",
        'Escaped "q"': "none",
    }
