"""Row 1 of #434: the line candidates of a day-1 rare jewel, read from PoB's data files."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from junkroan.optimizer.jewel_lines import JEWEL_BASES, jewel_line_candidates, rare_jewel_raw
from junkroan.optimizer.rails import Rails
from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT

SOURCE = Path(os.environ.get("JUNKROAN_POB_SOURCE") or DEFAULT_SOURCE_ROOT)
pytestmark = pytest.mark.skipif(not (SOURCE / "src" / "Data" / "ModJewel.lua").is_file(), reason=f"PoB source data not present at {SOURCE}")


def test_group_counts_per_base_and_union() -> None:
    cands = jewel_line_candidates(SOURCE)
    per_base = {b: sum(b in c.bases for c in cands) for b in JEWEL_BASES}
    assert per_base == {"Crimson Jewel": 124, "Viridian Jewel": 132, "Cobalt Jewel": 126}
    assert len(cands) == 163
    assert len({c.group for c in cands}) == 163  # one tier per spawnable group
    assert Counter(len(c.bases) for c in cands) == {3: 96, 2: 27, 1: 40}


def test_candidate_shape_and_no_corrupted() -> None:
    cands = jewel_line_candidates(SOURCE)
    assert {c.affix_type for c in cands} <= {"Prefix", "Suffix"}
    for c in cands:
        assert c.base == c.bases[0]
        assert c.base == next(b for b in JEWEL_BASES if b in c.bases)
    mace = next(c for c in cands if c.mod_id == "MaceDamageJewel")
    assert mace.lines == ("15% increased Damage with Maces or Sceptres",)  # (14-16) at 0.5


def test_raw_text_is_one_mod_with_all_its_lines() -> None:
    cands = jewel_line_candidates(SOURCE)
    hybrids = [c for c in cands if len(c.template_lines) > 1]
    assert len(hybrids) == 7  # one mod, several lines: still one candidate
    for c in cands:
        raw = rare_jewel_raw(c)
        lines = raw.split("\n")
        assert lines[0] == "Rarity: RARE" and lines[2] == c.base
        explicit = lines[lines.index("Implicits: 0") + 1:]
        assert len(explicit) == len(c.template_lines)
        for line, template in zip(explicit, c.template_lines):
            assert line.startswith("{range:0.5}") == ("(" in template)
        assert c.id == " / ".join(c.lines) and c.id
    single = next(c for c in cands if len(c.bases) == 1)
    with pytest.raises(ValueError):
        rare_jewel_raw(single, base=next(b for b in JEWEL_BASES if b not in single.bases))


def test_rail_loads_two_jewels_one_line() -> None:
    jewels = Rails.load().gear.jewels
    assert (jewels.count_max, jewels.lines) == (2, 1)
