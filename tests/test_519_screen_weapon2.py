"""#519 unit 2: the unique screen never tries a Weapon 2 unique PoB's real equip refuses. PoB-free."""

import pytest

from junkroan.optimizer.rails import Rails
from junkroan.search.generator import SkeletonGenerator

SHIELD = "Kaltenhalt"


class _FakePob:
    def __init__(self, w1: dict | None) -> None:
        self.w1 = w1
        self.reads = 0
        self.w2_names: list[str] = []

    def read_state(self) -> dict:
        self.reads += 1
        slots = {"Weapon 1": {"item": self.w1}} if self.w1 else {}
        return {"items_state": {"slots": slots}}

    def unique_item(self, name: str) -> dict:
        return {"raw": f"Rarity: Unique\n{name}\nBase"}

    def trial_stats(self, trials, keys, mode="fast"):
        for t in trials:
            if t["item"]["slot"] == "Weapon 2":
                self.w2_names.append(t["item"]["raw"].splitlines()[1])
        return [{"ok": True, "stats": {"CombinedDPS": 1000.0, "Life": 5000.0}} for _ in trials]


def _run(w1: dict | None) -> _FakePob:
    rails = Rails.load()
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.rails, gen.objective, gen.pob = rails, rails.objective(), _FakePob(w1)
    gen._score = lambda: gen.objective.score({"CombinedDPS": 1000.0, "Life": 5000.0})
    gen.screen_uniques(slots=("Weapon 2",), availability=("core", "league", "drop-restricted", "boss"), max_level=100)
    return gen.pob


def test_shield_not_tried_next_to_two_handed_sword() -> None:
    pob = _run({"base_type": "Infernal Sword", "type_label": "Two Handed Sword"})
    assert pob.w2_names == []
    assert pob.reads == 1


def test_shield_tried_next_to_one_hander() -> None:
    pob = _run({"base_type": "Rusted Sword", "type_label": "One Handed Sword"})
    assert SHIELD in pob.w2_names
    assert pob.reads == 1


def test_only_quivers_next_to_bow() -> None:
    pob = _run({"base_type": "Short Bow", "type_label": "Bow"})
    assert pob.w2_names and SHIELD not in pob.w2_names
    assert pob.reads == 1


def test_base_type_fallback_for_two_hander() -> None:
    pob = _run({"base_type": "Infernal Sword"})
    assert pob.w2_names == []
