"""#1088: the day-1 rulebook page states the floors, and every value equals the rails file's value.

The page is the `day1` loadout of docs/rulebook/loadout-rulebook.json (rebuilt from the entries source by
scripts/build_rulebook.py); the floors are read from src/junkroan/optimizer/rails_default.json. No code reads the
page, so this test is the only thing that notices when the two drift apart. It reads the raw rails JSON on purpose:
the page must never depend on a key that the rails file may drop (targets.CombinedDPS_floor, #1088 unit 2).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = ROOT / "docs" / "rulebook" / "loadout-rulebook.json"
RAILS_PATH = ROOT / "src" / "junkroan" / "optimizer" / "rails_default.json"


def _expected_floor_lines(rails: dict) -> list[str]:
    """The page's floor lines, in order, each value taken from the rails file."""

    floors = rails["floors"]
    mhit = floors["MaximumHitTaken"]
    sustain = rails["sustain"]
    lines = [
        f"Life >= {floors['Life']}",
        f"PhysicalMaximumHitTaken >= {mhit['Physical']}",
        f"FireMaximumHitTaken >= {mhit['Fire']}",
        f"ColdMaximumHitTaken >= {mhit['Cold']}",
        f"LightningMaximumHitTaken >= {mhit['Lightning']}",
        f"FireResist, ColdResist, LightningResist each >= {floors['elemental_resist_each']}",
        f"FireResist, ColdResist, LightningResist goal {floors['elemental_resist_goal']}",
    ]
    chaos = floors["ChaosResist"]
    lines.append("ChaosResist: no floor" if chaos is None else f"ChaosResist >= {chaos}")
    lines += [
        f"EffectiveMovementSpeedMod >= {floors['EffectiveMovementSpeedMod']}",
        f"MoMCastsAfterMaxHit >= {floors['MoMCastsAfterMaxHit']}",
        f"MoMHitFraction >= {floors['MoMHitFraction']}",
        f"sustain (recovery_over_cost) >= {sustain['recovery_over_cost']}",
        f"self-degen (idle_recovery_over_life) >= {sustain['idle_recovery_over_life']}",
    ]
    return lines


def test_day1_page_floors_equal_rails_defaults() -> None:
    page = json.loads(PAGE_PATH.read_text(encoding="utf-8"))
    day1 = next(loadout for loadout in page["loadouts"] if loadout["id"] == "day1")
    rails = json.loads(RAILS_PATH.read_text(encoding="utf-8"))

    assert day1["floors"]["lines"] == _expected_floor_lines(rails), (
        f"day-1 page floors ({PAGE_PATH.relative_to(ROOT)}) differ from rails ({RAILS_PATH.relative_to(ROOT)})"
    )
    # the objective line carries the DPS target; it must follow rails too (code-review finding)
    dps_target = rails["targets"]["CombinedDPS"]
    assert str(dps_target) in day1["floors"]["objective"], (
        f"day-1 page objective line does not name CombinedDPS target {dps_target} of rails"
    )
