"""Pure template-gear census parsing (no PoB)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from template_line_census import mod_text, parse_log, run_lines  # noqa: E402

LOG1 = "\n".join([
    "  Helmet: Test Helm: life T3 T3/10 +(100-114) to maximum Life; attribute T3 T3/6 +5 to Strength, delta 100.",
    "  Weapon 1: Test Bow (10% increased Damage): objective_line T4 T4/7 (17-20)% increased Attack Speed, delta 5,000.",
    "  Body Armour: Test Plate: life T6 T6/13 +(100-114) to maximum Life; objective_line T3 T3/6 +(21-25)% to Chaos Resistance, delta 0.",
    "  Helmet: Test Helm: life T3 T3/10 +(100-114) to maximum Life; attribute T3 T3/6 +18 to Strength and Dexterity, delta 8,350.",
])

LOG2 = "\n".join([
    "  Gloves: Test Gauntlets: life T2 T2/9 +(100-114) to maximum Life; attribute {crafted} +18 to Strength and Dexterity, delta 0.",
])


def test_last_summary_per_slot_wins_and_weapon_shape_is_skipped() -> None:
    lines = parse_log(LOG1)

    assert [(line.kind, line.value, line.text) for line in lines] == [
        ("attribute", 8350, "+# to Strength and Dexterity"),
        ("objective_line", 0, "+#% to Chaos Resistance"),
    ]


def test_plain_numbers_and_ranges_normalise_to_hash() -> None:
    assert mod_text("objective_line T4 T4/7 (17-20)% increased Attack Speed, delta 5,000.") == "#% increased Attack Speed"
    assert mod_text("attribute {crafted} +18 to Strength and Dexterity, delta 8,350.") == "+# to Strength and Dexterity"


def test_run_lines_counts_flexible_and_zero_lines(tmp_path: Path) -> None:
    logs = tmp_path / "run" / "logs"
    logs.mkdir(parents=True)
    (logs / "alpha-s1.log").write_text(LOG1, encoding="utf-8")
    (logs / "beta-s1.log").write_text(LOG2, encoding="utf-8")

    builds = run_lines(tmp_path / "run")
    all_lines = [line for build_lines in builds.values() for line in build_lines]

    assert {name: len(build_lines) for name, build_lines in builds.items()} == {"alpha-s1": 2, "beta-s1": 1}
    assert len(all_lines) == 3
    assert sum(1 for line in all_lines if line.zero) == 2
    assert [line.text for line in all_lines if line.zero] == [
        "+#% to Chaos Resistance",
        "+# to Strength and Dexterity",
    ]