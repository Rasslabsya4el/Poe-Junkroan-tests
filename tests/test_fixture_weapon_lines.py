"""Pure helpers behind the value-based weapon-line census."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fixture_weapon_lines import explicit_lines, summary_rows, without_line


def test_explicit_line_removal_preserves_every_other_item_line() -> None:
    raw = """Rarity: RARE
Test Item
Test Bow
Implicits: 1
(20-30)% increased Elemental Damage with Attack Skills
Adds 10 to 20 Fire Damage
{crafted}+25 to Dexterity
Item Level: 76"""

    lines = explicit_lines(raw)

    assert [line for _index, line in lines] == ["Adds 10 to 20 Fire Damage", "{crafted}+25 to Dexterity"]
    deleted = without_line(raw, lines[0][0])
    assert "Adds 10 to 20 Fire Damage" not in deleted
    assert "{crafted}+25 to Dexterity" in deleted
    assert "Item Level: 76" in deleted


def test_summary_uses_value_ranked_useful_lines_and_only_matched_tiers() -> None:
    weapons = [{
        "source": "author",
        "kind": "attack",
        "lines": [
            {"line": "best", "share": 0.20, "tier": 2, "of": 10},
            {"line": "second", "share": 0.10, "tier": 4, "of": 10},
            {"line": "unmatched", "share": 0.05, "tier": None, "of": None},
            {"line": "junk", "share": 0.009, "tier": 1, "of": 10},
        ],
    }]

    summary = summary_rows(weapons)[0]

    assert summary["median_useful_lines"] == 3
    assert summary["top_1"] == {"lines": 1, "matched": 1, "median_tier": 2.0, "median_relative_position": 1 / 9}
    assert summary["top_2"] == {"lines": 1, "matched": 1, "median_tier": 4.0, "median_relative_position": 3 / 9}
    assert summary["top_3"] == {"lines": 1, "matched": 0, "median_tier": None, "median_relative_position": None}
    assert summary["all_useful"]["matched"] == 2
