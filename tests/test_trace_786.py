"""#786: trace classes for the day-1 loot base rule (drop level <= 70). PoB-free."""

from junkroan.optimizer import trace
import junkroan.optimizer.trace_786  # noqa: F401
from junkroan.optimizer.trace_786 import loot_base_classes


def _t(base: str, rarity: str = "Rare", slot: str = "Boots") -> dict:
    return {"item": {"slot": slot, "raw": f"Rarity: {rarity}\nSome Name\n{base}\nItem Level: 70"}}


def test_within_70() -> None:
    assert list(loot_base_classes(_t("Iron Greaves"))) == ["loot-base-within-70"]


def test_over_70() -> None:
    assert list(loot_base_classes(_t("Leviathan Greaves"))) == ["loot-base-over-70"]


def test_skipped() -> None:
    assert list(loot_base_classes(_t("Leviathan Greaves", "Unique"))) == []
    assert list(loot_base_classes(_t("Leviathan Greaves", "Magic"))) == []
    assert list(loot_base_classes(_t("No Such Base"))) == []
    assert list(loot_base_classes(_t("Leviathan Greaves", slot="Jewel 1"))) == []
    assert list(loot_base_classes(_t("Leviathan Greaves", slot="Flask 1"))) == []


def test_registered() -> None:
    assert "loot-base-over-70" in trace.classify(_t("Leviathan Greaves"))
    assert "loot-base-within-70" in trace.classify(_t("Iron Greaves"))
