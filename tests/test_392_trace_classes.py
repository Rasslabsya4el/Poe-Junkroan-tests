"""#392: the trace counter names the unique tier and the Exalted-Orb bench crafts the rails forbid. PoB-free."""

from junkroan.optimizer import trace


def test_unique_tier_class() -> None:
    assert "unique-tier:5" in trace.classify({"item": {"slot": "Helmet", "raw": "Rarity: Unique\nHonourhome\nSoldier Helmet"}})
    assert "unique-tier:4" in trace.classify({"item": {"slot": "Weapon 1", "raw": "Rarity: Unique\nNatural Hierarchy\nRhex Talisman"}})


def test_exalt_craft_class() -> None:
    assert any(e for e, _, _ in trace._craft_lines()), "no Exalted-cost crafted lines found"
    exalt = "{crafted}18% increased Attack Speed"
    plain = "{crafted}+25 to maximum Life"
    raw = "Rarity: Rare\nX\nBase\n"
    assert "bench-craft-exalt" not in trace.classify({"item": {"slot": "Ring 1", "raw": raw + plain}})
    assert "bench-craft-exalt" in trace.classify({"item": {"slot": "Weapon 1", "raw": raw + exalt}})
    assert "bench-craft-exalt" not in trace.classify({"item": {"slot": "Ring 1", "raw": raw + "{crafted}13% increased Damage"}})  # below the Exalted recipe range (15-17)
