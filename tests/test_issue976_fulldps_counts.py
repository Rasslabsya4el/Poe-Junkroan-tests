"""#976: a corpse count (Volatile Dead) and a mirage's gem count, measured once in PoB.

`FullDPS` multiplies each included skill's `TotalDPS` by its gem count (Calcs.lua:287-289, `activeSkillCount`), and a
mirage adds `TotalDPS * mirage.count * activeSkillCount` (Calcs.lua:249-252). Each place loads one existing fixture
build, sets the gem count to two values, and reads `TotalDPS` and `FullDPS` (and the count it wrote). Measurement
only: no src/ change, no count is fixed here.

#981: every term PoB adds into `FullDPS` is named and printed per build and count (`_fulldps_parts`, read per skill
through `active_skill_stats`), and the terms are asserted to sum to `FullDPS` within REL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TUADH = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
RUNTIME_PRESENT = (PROJECT_ROOT / "var" / "cache" / "pob").is_dir()
needs_runtime = pytest.mark.skipif(not RUNTIME_PRESENT, reason="PoB runtime not present")
REL = 1e-3  # the ticket's 0.1 %

VD_FIXTURE = "archmage_volatile_dead.pob.txt"  # group 1: Volatile Dead (count 6), the only FullDPS group
MIRAGE_FIXTURE = "impale_ballista.pob.txt"  # group 1: Rain of Arrows (count 3) + Mirage Archer (count 1)

# the per-skill outputs `_fulldps_parts` reads (PoB's own output keys, one skill at a time)
PARTS_KEYS = ["TotalDPS", "ImpaleDPS", "BleedDPS", "IgniteDPS", "BurningGroundDPS", "CausticGroundDPS",
              "TotalPoisonDPS", "DecayDPS", "CorruptingBloodDPS", "TotalDot", "CullMultiplier"]


def _build_xml(fixture: str, gem_name: str, count: int, *, drop_gem: str | None = None, out_of_full_dps: str | None = None) -> str:
    """The fixture's build XML with the gem `gem_name` at `count`; optionally drop one gem, or take a group out of FullDPS."""

    root = ElementTree.fromstring(decode_import_code((TUADH / fixture).read_text(encoding="utf-8").strip()))
    gems = [gem for gem in root.iter("Gem") if gem.get("nameSpec") == gem_name]
    assert len(gems) == 1, f"{fixture}: expected one {gem_name} gem, found {len(gems)}"
    gems[0].set("count", str(count))
    if drop_gem is not None:
        for skill in root.iter("Skill"):
            for gem in skill.findall("Gem"):
                if gem.get("nameSpec") == drop_gem:
                    skill.remove(gem)
    if out_of_full_dps is not None:
        for skill in root.iter("Skill"):
            if any(gem.get("nameSpec") == out_of_full_dps for gem in skill.findall("Gem")):
                skill.set("includeInFullDPS", "false")
    return ElementTree.tostring(root, encoding="unicode")


def _measure(pob: PobSession) -> tuple[float, float]:
    stats = pob.stats(("TotalDPS", "FullDPS"))
    return float(stats["TotalDPS"]), float(stats["FullDPS"])


def _print(label: str, count: int, total: float, full: float) -> None:
    print(f"[#976 {label}] count={count} TotalDPS={total:.3f} FullDPS={full:.3f} ratio FullDPS/(TotalDPS*count)={full / (total * count):.6f}")


def _included_skills(pob: PobSession) -> list[tuple[str, str]]:
    """(active_skill_id, PoB skill name) of every enabled active skill in an includeInFullDPS socket group."""

    state = pob.read_state().get("skills_state") or {}
    return [
        (entry["active_skill_id"], entry["name"])
        for group in state.get("socket_groups", [])
        if group.get("include_in_full_dps") and group.get("enabled")
        for entry in group.get("active_skill_entries", [])
        if entry.get("enabled")
    ]


def _fulldps_parts(pob: PobSession, count: int) -> list[tuple[str, float]]:
    """The named terms PoB's `calcFullDPS` adds into `combinedDPS` for the loaded build (Calcs.lua:176-385).

    Each number is read per included skill from PoB's own skill output (`read_active_skill_stats`), because PoB's
    `SkillDPS` table cannot be read as a scalar. Per skill: `TotalDPS x count` (:287-289), `ImpaleDPS x count`
    (:314-316, summed into "Full Impale DPS" added once at :367-369), `TotalPoisonDPS x count` (:307-309, capped at
    :359), `DecayDPS` (:317, :371). The ailment terms (:291-366) take the maximum over the included skills and are
    added once, at count 1: Best Bleed / Ignite / Burning Ground / Caustic Ground / Corrupting Blood DPS. The
    `DotDpsCap` (:359, :379) is not reached by these builds (see the FullDotDPS line). A `TotalDot` (:320) or a
    culling term (:381-384) would need the DotCanStack flag or the cull multiplier, neither read here: the helper
    asserts they are absent instead of inventing them. No mirage (no Mirage Archer gem in these builds) and no minion.
    """

    skills = _included_skills(pob)
    assert skills, "no includeInFullDPS skill in the build"
    reads = pob.active_skill_stats([skill_id for skill_id, _ in skills], PARTS_KEYS)
    for skill_id, name in skills:
        row = reads[skill_id]
        assert float(row.get("TotalDot", 0.0)) == 0.0, f"{name}: TotalDot is not zero (DotCanStack is not read here)"
        assert float(row.get("CullMultiplier", 1.0)) <= 1.0, f"{name}: a culling term is not computed here"

    def value(skill_id: str, key: str) -> float:
        return float(reads[skill_id].get(key, 0.0))

    def best(key: str) -> tuple[float, str]:
        return max(((value(skill_id, key), name) for skill_id, name in skills), default=(0.0, ""))

    parts: list[tuple[str, float]] = [(f"{name}: TotalDPS x count", value(skill_id, "TotalDPS") * count) for skill_id, name in skills]
    impale = sum(value(skill_id, "ImpaleDPS") * count for skill_id, _ in skills)
    poison = sum(value(skill_id, "TotalPoisonDPS") * count for skill_id, _ in skills)
    decay = sum(value(skill_id, "DecayDPS") for skill_id, _ in skills)
    if impale > 0:
        parts.append(("Full Impale DPS", impale))
    if poison > 0:
        parts.append(("Full Poison DPS", poison))
    if decay > 0:
        parts.append(("Full Decay DPS", decay))
    for label, key in (
        ("Best Bleed DPS", "BleedDPS"),
        ("Best Ignite DPS", "IgniteDPS"),
        ("Best Burning Ground DPS", "BurningGroundDPS"),
        ("Best Caustic Ground DPS", "CausticGroundDPS"),
        ("Best Corrupting Blood DPS", "CorruptingBloodDPS"),
    ):
        top, source = best(key)
        if top > 0:
            parts.append((f"{label} ({source})", top))
    return parts


def _print_parts(label: str, count: int, parts: list[tuple[str, float]], total: float, full: float, full_dot: float) -> None:
    print(f"[#981 {label}] count={count}  (main socket group TotalDPS = {total:,.3f}, shown for reference only)")
    for name, value in parts:
        print(f"  {name:<52} {value:>14,.3f}")
    summed = sum(value for _, value in parts)
    print(f"  {'sum of the parts':<52} {summed:>14,.3f}")
    print(f"  {'FullDPS (PoB, calcFullDPS combinedDPS)':<52} {full:>14,.3f}")
    print(f"  {'gap: sum of the parts - FullDPS':<52} {summed - full:>14,.3f}  {(summed - full) / full:+.4%}")
    print(f"  {'FullDotDPS (PoB output, DoT terms only)':<52} {full_dot:>14,.3f}")


def _read_totals(pob: PobSession) -> tuple[float, float, float]:
    stats = pob.stats(("TotalDPS", "FullDPS", "FullDotDPS"))
    return float(stats["TotalDPS"]), float(stats["FullDPS"]), float(stats["FullDotDPS"])


@needs_runtime
@pytest.mark.pob
def test_volatile_dead_fulldps_is_the_sum_of_its_parts() -> None:
    measured: dict[int, tuple[list[tuple[str, float]], float]] = {}
    with PobSession(run_id="test-issue981-volatile-dead", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        for count in (3, 10):
            pob.load_xml(_build_xml(VD_FIXTURE, "Volatile Dead", count))
            total, full, full_dot = _read_totals(pob)
            parts = _fulldps_parts(pob, count)
            _print_parts("volatile-dead", count, parts, total, full, full_dot)
            measured[count] = (parts, full)
    for count in (3, 10):
        parts, full = measured[count]
        summed = sum(value for _, value in parts)
        assert summed == pytest.approx(full, rel=REL), f"volatile-dead at count {count}: sum of the parts {summed:.3f} != FullDPS {full:.3f}"


@needs_runtime
@pytest.mark.pob
@pytest.mark.xfail(
    strict=True,
    reason=(
        "measured on PoB (impale_ballista.pob.txt, Rain of Arrows gem count 1 and 2, group 2 out of FullDPS): "
        "the fixture build (with Mirage Archer) has TotalDPS 54,891.142 at both counts and FullDPS 76,239.866 at 1 "
        "(ratio 1.388928) and 146,359.874 at 2 (ratio 1.333183); without Mirage Archer FullDPS is 60,781.678 at 1 "
        "(ratio 1.107313) and 115,443.496 at 2 (ratio 1.051568). The mirage term (with minus without) is 15,458.189 "
        "at 1 and 30,916.377 at 2, ratio T(2)/T(1) = 2.000000, linear in the gem count; the residual without the "
        "mirage (5,890.5 at 1, 5,661.2 at 2) is not constant and not located here (#981 names it: see the control test)"
    ),
)
def test_mirage_fulldps_applies_the_gem_count_once() -> None:
    """Group 2 (Shrapnel Ballista, 6x) is taken out of FullDPS so only the Rain of Arrows group is counted.

    A = the fixture (Rain of Arrows + Mirage Archer): FullDPS must equal TotalDPS x count at both counts (asserted
    first, literally). B = the same build without Mirage Archer: the mirage term T = FullDPS(A) - FullDPS(B) must be
    linear in the count (T(2) == 2 x T(1)), and B's FullDPS must equal TotalDPS x count.
    """

    measured: dict[tuple[str, int], tuple[float, float]] = {}
    with PobSession(run_id="test-issue976-mirage", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        for count in (1, 2):
            pob.load_xml(_build_xml(MIRAGE_FIXTURE, "Rain of Arrows", count, out_of_full_dps="Shrapnel Ballista"))
            measured["mirage", count] = _measure(pob)
            _print("mirage A (with Mirage Archer)", count, *measured["mirage", count])
            pob.load_xml(_build_xml(MIRAGE_FIXTURE, "Rain of Arrows", count, drop_gem="Mirage Archer", out_of_full_dps="Shrapnel Ballista"))
            measured["control", count] = _measure(pob)
            _print("mirage B (no Mirage Archer)", count, *measured["control", count])
    for count in (1, 2):
        total, full = measured["mirage", count]
        assert full == pytest.approx(total * count, rel=REL), f"mirage build at count {count}: FullDPS != TotalDPS x count"
    term = {count: measured["mirage", count][1] - measured["control", count][1] for count in (1, 2)}
    print(f"[#976 mirage] mirage term T(1)={term[1]:.3f} T(2)={term[2]:.3f} T(2)/T(1)={term[2] / term[1]:.6f}")
    assert term[2] == pytest.approx(2 * term[1], rel=REL), "mirage term is not linear in the gem count"
    for count in (1, 2):
        total, full = measured["control", count]
        assert full == pytest.approx(total * count, rel=REL), f"control at count {count}: FullDPS != TotalDPS x count"


# #981: the MORE rounding split inside calcFullDPS, per gem count of Rain of Arrows on the ballista control. PoB rounds
# the product of one stat's MORE mods to 2 decimals per ModDB level (ModDB.lua:183-188 `result * round(modResult, 2)`,
# then x the parent's product; ModList.lua:139-148 the same). calcFullDPS builds its env on the main env's cached
# DB (Calcs.lua:425 -> CalcSetup.lua:586-588), so the base mods (CalcSetup.lua:488-585, here `Damage` MORE 4 per
# FrenzyCharge, :514) sit in the parent DB while the tree's sit in the child: Rain of Arrows' `Damage` MORE (weapon
# cfg) is 1.24 (Point Blank) x 1.40 (Tree:63620) x 1.12 (Base) = 1.94432 inside calcFullDPS, and 1.24 x round(1.12 x
# 1.40 = 1.568) = 1.24 x 1.57 = 1.9468 in the isolated read. Measured (in-process probe, PoB v2.67.2, count 1):
# TotalDPS 31,783.733 isolated vs 31,740.608 in calcFullDPS (-43.126), ImpaleDPS 22,952.354 vs 22,921.211 (-31.143),
# BleedDPS 6,119.859 both; with the 2-decimal rounding switched off both reads are 31,803.638 / 22,966.728 and the
# sum of the parts equals FullDPS exactly. A PoB rounding, not a count or flag of ours.
MORE_ROUNDING_SPLIT_PER_COUNT = -74.269


@needs_runtime
@pytest.mark.pob
def test_ballista_control_fulldps_is_the_sum_of_its_parts() -> None:
    """impale_ballista.pob.txt without Mirage Archer, Shrapnel Ballista out of FullDPS, Rain of Arrows gem count 1 and 2.

    The parts read per skill (isolated: the skill as the main skill) are Rain of Arrows TotalDPS x count, Full Impale
    DPS (x count) and Best Bleed DPS (once); FullDPS is computed by calcFullDPS on the cached DB, where PoB's MORE
    rounding split takes 74.269 per count off (see MORE_ROUNDING_SPLIT_PER_COUNT). That term is a named part: the
    gap without it is +0.122 % / +0.129 % (outside REL), with it the parts sum to FullDPS.
    """

    measured: dict[int, tuple[list[tuple[str, float]], float]] = {}
    with PobSession(run_id="test-issue981-ballista-control", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        for count in (1, 2):
            pob.load_xml(_build_xml(MIRAGE_FIXTURE, "Rain of Arrows", count, drop_gem="Mirage Archer", out_of_full_dps="Shrapnel Ballista"))
            total, full, full_dot = _read_totals(pob)
            parts = _fulldps_parts(pob, count)
            parts.append(("MORE rounding split in calcFullDPS x count",MORE_ROUNDING_SPLIT_PER_COUNT * count))
            _print_parts("impale_ballista control (no Mirage Archer)", count, parts, total, full, full_dot)
            measured[count] = (parts, full)
    for count in (1, 2):
        parts, full = measured[count]
        summed = sum(value for _, value in parts)
        without_term = summed - MORE_ROUNDING_SPLIT_PER_COUNT * count
        assert without_term - full == pytest.approx(-MORE_ROUNDING_SPLIT_PER_COUNT * count, rel=REL), (
            f"ballista control at count {count}: the gap sum of the parts - FullDPS is {without_term - full:.3f}, not the "
            f"calcFullDPS MORE rounding split {-MORE_ROUNDING_SPLIT_PER_COUNT * count:.3f} (ModDB.lua:183-188, Damage MORE "
            "1.94432 in calcFullDPS vs 1.9468 isolated)"
        )
        assert summed == pytest.approx(full, rel=REL), (
            f"ballista control at count {count}: sum of the parts incl. the calcFullDPS MORE rounding split "
            f"{MORE_ROUNDING_SPLIT_PER_COUNT * count:.3f} is {summed:.3f} != FullDPS {full:.3f}"
        )
