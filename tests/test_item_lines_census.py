"""Pure `rare_lines` parsing behind the item-line census (no PoB)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from item_lines_census import rare_lines


def test_prefix_none_is_an_empty_affix_and_is_skipped() -> None:
    raw = """Rarity: RARE
Test Ring
Iron Ring
Prefix: {range:0.5}IncreasedLife7
Prefix: None
Suffix: {range:0.6}FireResist6
Suffix: None
Suffix: None
Implicits: 0
+70 to maximum Life
+40% to Fire Resistance"""

    lines = rare_lines(raw)

    assert lines == {"prefixes": ["IncreasedLife7"], "suffixes": ["FireResist6"], "crafted": 0}


def test_crafted_lines_are_counted_once_each() -> None:
    raw = """Rarity: RARE
Test Boots
Crusader Boots
Prefix: {range:0.5}MovementVelocity5
Suffix: None
Suffix: None
Suffix: None
Implicits: 0
30% increased Movement Speed
{crafted}+25% to Fire Resistance"""

    lines = rare_lines(raw)

    assert lines == {"prefixes": ["MovementVelocity5"], "suffixes": [], "crafted": 1}