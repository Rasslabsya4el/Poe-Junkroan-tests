"""The `g-useful-n` counting rule (issue #437, unit 1): fake line values, no PoB."""

from __future__ import annotations

import dataclasses

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.useful_lines import (
    TOP_K,
    ItemLine,
    count_item,
    extra_resistance_keep,
    item_lines,
    line_values,
    n_slot,
    needs_recraft,
    rerank_top_k,
    resistance_element,
    without_lines,
)

RAW = """Rarity: RARE
Random 1
Iron Ring
Crafted: true
Item Level: 84
Quality: 20
Prefix: {range:0.500}IncreasedLife7
Prefix: None
Prefix: {range:0.250}IncreasedMana3
Suffix: {range:0.600}FireResist6
Suffix: {range:0.100}ColdResist2
Implicits: 1
+25% to Fire Resistance
-20 to maximum Life
{crafted}+1% to Lightning Resistance
{crafted}+30 to Dexterity"""


def _lv(values: list[float], start_kind: str = "explicit") -> list[tuple[ItemLine, tuple[float, float]]]:
    return [(ItemLine(i, start_kind, f"line{i}"), (0.0, float(v))) for i, v in enumerate(values)]


def test_row1_ring_keeps_three_best_and_the_drawback() -> None:
    counted = count_item(_lv([40, 25, 10, 3, 0, -8]), 3)
    assert [v for _l, v in counted.kept] == [(0, 40), (0, 25), (0, 10), (0, -8)]
    assert [v for _l, v in counted.dropped] == [(0, 3), (0, 0)]
    assert [v for _l, v in counted.drawbacks] == [(0, -8)]


def test_row2_the_craft_competes_as_a_line() -> None:
    lines = _lv([40, 25, 10])
    lines.append((ItemLine(3, "craft", "+x"), (0.0, 30.0)))
    counted = count_item(lines, 3)
    assert [ln.index for ln, _v in counted.kept] == [0, 1, 3]
    assert [ln.index for ln, _v in counted.dropped] == [2]


def test_ties_go_to_the_earlier_line_and_neutral_tolerance() -> None:
    counted = count_item(_lv([5, 5, 5, 1e-12]), 2)
    assert [ln.index for ln, _v in counted.kept] == [0, 1]
    assert [ln.index for ln, _v in counted.dropped] == [2, 3]  # 1e-12 is neutral, 5 is surplus


def test_row3_rerank_counts_only_the_first_k() -> None:
    calls: list[str] = []
    table = {"A": (60.0, "rawA"), "B": (80.0, "rawB")}

    def fn(c: str):
        calls.append(c)
        return table[c][0], table[c][1], None

    win = rerank_top_k(["A", "B"], TOP_K, fn)
    assert win.candidate == "B" and win.counted_raw == "rawB" and win.rank_key == 80.0

    calls.clear()
    many = [f"c{i}" for i in range(200)]
    rerank_top_k(many, TOP_K, lambda c: (calls.append(c) or 0.0, c, None))
    assert TOP_K == 10
    assert calls == many[:10] and "c10" not in calls


def test_rerank_first_wins_a_tie() -> None:
    win = rerank_top_k(["a", "b"], 10, lambda c: (1.0, c, None))
    assert win.candidate == "a"


def test_row4_extra_resistance_keep() -> None:
    dropped = {
        "Ring 1": [("Fire", "ring-fire", 30.0)],
        "Ring 2": [("Fire", "ring2-fire", 20.0), ("Cold", "ring2-cold", 99.0)],
        "Belt": [("Fire", "belt-fire", 10.0)],
    }
    assert extra_resistance_keep(dropped, {"Fire"}) == [("Ring 1", "ring-fire"), ("Ring 2", "ring2-fire")]
    assert extra_resistance_keep(dropped, set()) == []
    # one line per slot: Ring 1's two Fire lines give only the larger
    two = {"Ring 1": [("Fire", "a", 5.0), ("Fire", "b", 7.0)], "Belt": [("Fire", "c", 1.0)]}
    assert extra_resistance_keep(two, {"Fire"}, max_items=5) == [("Ring 1", "b"), ("Belt", "c")]


def test_resistance_element() -> None:
    assert resistance_element("FireResist3") == "Fire"
    assert resistance_element("LightningResist1") == "Lightning"
    assert resistance_element("+43% to Cold Resistance") == "Cold"
    assert resistance_element("{crafted}+12% to Fire Resistance") == "Fire"
    assert resistance_element("+12% to Fire and Cold Resistances") is None
    assert resistance_element("FireAndColdResist2") is None
    assert resistance_element("AllResistances3") is None
    assert resistance_element("+10% to all Elemental Resistances") is None
    assert resistance_element("+30% to Chaos Resistance") is None


def test_item_lines_and_without_lines() -> None:
    lines = item_lines(RAW)
    assert [(ln.kind, ln.text) for ln in lines] == [
        ("prefix", "IncreasedLife7"),
        ("prefix", "IncreasedMana3"),
        ("suffix", "FireResist6"),
        ("suffix", "ColdResist2"),
        ("explicit", "-20 to maximum Life"),
        ("craft", "+1% to Lightning Resistance / +30 to Dexterity"),
    ]
    assert [ln.index for ln in lines] == list(range(6))
    original = RAW.splitlines()
    for ln in lines:
        out = without_lines(RAW, [ln]).splitlines()
        expected = [p for i, p in enumerate(original) if i not in ln.positions]
        assert out == expected
        assert len(out) == len(original) - len(ln.positions)
    assert len(next(ln for ln in lines if ln.kind == "craft").positions) == 2
    # nothing removed -> the very same string; trailing newline is kept
    assert without_lines(RAW, []) == RAW
    assert without_lines(RAW + "\n", [lines[0]]).endswith("Dexterity\n")
    # deleting the last line does not leave a dangling newline behind
    assert without_lines(RAW, [lines[-1]]).endswith("-20 to maximum Life")


REAL_RAW = """Rarity: RARE
Random 1
Iron Ring
Crafted: true
Item Level: 84
Quality: 20
Prefix: {range:0.500}IncreasedLife7
Prefix: {range:0.250}IncreasedMana3
Suffix: {range:0.600}FireResist6
Suffix: {range:0.100}StrengthAndDexterity2
Suffix: None
Implicits: 1
+25% to Fire Resistance
{tags:life}{prefix}+70 to maximum Life
{tags:mana}{prefix}+30 to maximum Mana
{tags:attribute}{suffix}+34 to Strength
{tags:attribute}{suffix}+34 to Dexterity
{tags:elemental,resistance}{suffix}+30% to Fire Resistance
-20 to maximum Life
{tags:life}{crafted}+1% to Lightning Resistance
{crafted}+30 to Dexterity"""


def test_item_lines_of_a_real_shaped_raw_do_not_count_the_rendered_text() -> None:
    lines = item_lines(REAL_RAW)
    assert [(ln.kind, ln.text) for ln in lines] == [
        ("prefix", "IncreasedLife7"),
        ("prefix", "IncreasedMana3"),
        ("suffix", "FireResist6"),
        ("suffix", "StrengthAndDexterity2"),
        ("explicit", "-20 to maximum Life"),
        ("craft", "+1% to Lightning Resistance / +30 to Dexterity"),
    ]
    assert needs_recraft(REAL_RAW, [lines[0]]) and not needs_recraft(REAL_RAW, [lines[4]]) and not needs_recraft(REAL_RAW, [lines[5]])
    assert not needs_recraft(RAW, [item_lines(RAW)[0]])  # headers only: nothing to re-render
    assert without_lines(REAL_RAW, []) == REAL_RAW

    out = without_lines(REAL_RAW, [lines[1]]).splitlines()  # one header removed
    assert out == [
        "Rarity: RARE", "Random 1", "Iron Ring", "Crafted: true", "Item Level: 84", "Quality: 20",
        "Prefix: {range:0.500}IncreasedLife7", "Suffix: {range:0.600}FireResist6", "Suffix: {range:0.100}StrengthAndDexterity2", "Suffix: None",
        "Implicits: 1", "+25% to Fire Resistance",
        "{custom}-20 to maximum Life",  # the plain line is kept as {custom} so Item:Craft() keeps it
        "{tags:life}{crafted}+1% to Lightning Resistance", "{crafted}+30 to Dexterity",  # the bench craft is untouched
    ]
    # an explicit line or the craft removed alone: a plain cut, the rendered text stays
    assert without_lines(REAL_RAW, [lines[4]]) == REAL_RAW.replace("-20 to maximum Life\n", "")
    assert without_lines(REAL_RAW, [lines[5]]).endswith("-20 to maximum Life")
    # header + explicit line: the explicit line is gone, nothing is left to write as {custom}
    both = without_lines(REAL_RAW, [lines[0], lines[4]])
    assert "maximum Life" not in both.split("Implicits")[1] and "{custom}" not in both
    # a recrafted raw (rendered text, {custom} line) counts the same lines and survives a second removal
    again = without_lines(without_lines(REAL_RAW, [lines[1]]), [])
    assert [(ln.kind, ln.text) for ln in item_lines(again)][-2:] == [("explicit", "-20 to maximum Life"), ("craft", "+1% to Lightning Resistance / +30 to Dexterity")]


def test_trial_item_carries_recraft_only_when_a_header_goes() -> None:
    from junkroan.optimizer.useful_lines import trial_item

    lines = item_lines(REAL_RAW)
    assert trial_item("Ring 1", REAL_RAW, [lines[2]])["recraft"] is True
    assert trial_item("Ring 1", REAL_RAW, [lines[4]]) == {"slot": "Ring 1", "raw": without_lines(REAL_RAW, [lines[4]])}
    assert trial_item("Ring 1", REAL_RAW, []) == {"slot": "Ring 1", "raw": REAL_RAW}
    assert "recraft" not in trial_item("Ring 1", RAW, [item_lines(RAW)[0]])


def test_n_slot_reads_the_template() -> None:
    rails = Rails.load()
    assert n_slot("Fake Ring", "Ring 1", rails) == 3
    assert n_slot("Fake Wand", "Weapon 1", rails) == rails.gear.wishlist.weapon_open_lines + 1
    wider = dataclasses.replace(rails, gear=dataclasses.replace(rails.gear, wishlist=dataclasses.replace(rails.gear.wishlist, weapon_open_lines=5)))
    assert n_slot("Fake Wand", "Weapon 1", wider) == 6


class _FakePob:
    """Scores a trial as the number of Prefix/Suffix lines it keeps times 10 (DPS)."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[dict]] = []
        self.fail_on = fail_on

    def trial_stats(self, trials, keys, *, mode="full"):
        self.calls.append(list(trials))
        out = []
        for t in trials:
            raw = t["item"]["raw"]
            out.append({"ok": True, "stats": {"CombinedDPS": 10.0 * raw.count("Prefix: {") + 100.0 * raw.count("FireResist6")}})
        if self.fail_on:
            out[1] = {"ok": False, "error": "boom"}
        return out


def test_line_values_one_call_and_values() -> None:
    pob = _FakePob()
    values = line_values(pob, Objective(maximize="CombinedDPS"), "Ring 1", RAW)
    assert len(pob.calls) == 1 and len(pob.calls[0]) == 1 + 6
    assert pob.calls[0][0]["item"] == {"slot": "Ring 1", "raw": RAW}
    got = {ln.text: v for ln, v in values}
    assert got["IncreasedLife7"] == (0.0, 10.0)
    assert got["FireResist6"] == (0.0, 100.0)
    assert got["ColdResist2"] == (0.0, 0.0)
    assert len(values) == 6


def test_line_values_raises_on_a_failed_trial() -> None:
    import pytest

    with pytest.raises(RuntimeError, match=r"\[Ring 1\].*IncreasedLife7"):
        line_values(_FakePob(fail_on="x"), Objective(maximize="CombinedDPS"), "Ring 1", RAW)
