from junkroan.optimizer.audit import audit_xml


def _xml(item_lines: list[str]) -> str:
    body = "\n".join(["Rarity: RARE", "Crafted Item", "Agate Amulet", *item_lines])
    return (
        '<PathOfBuilding><Items activeItemSet="1"><Item id="1">' + body + "</Item>"
        '<ItemSet id="1"><Slot name="Amulet" itemId="1"/></ItemSet></Items></PathOfBuilding>'
    )


def _count_findings(lines: list[str]):
    return [f for f in audit_xml(_xml(lines)) if f.check == "crafted mod count"]


HYBRID = ["{crafted}Regenerate 16 Life per second", "{crafted}Regenerate 2.4 Mana per second"]
ANOINT = ["{enchant}{crafted}Allocates Acrimony"]


def test_hybrid_craft_is_one_mod():
    assert _count_findings(ANOINT + HYBRID) == []


def test_two_separate_crafts_fail():
    lines = ["{crafted}+31 to maximum Life", "{crafted}+12% to Fire Resistance"]
    assert len(_count_findings(lines)) == 1


def test_multimod_lifts_limit_to_three():
    lines = ["Can have up to 3 Crafted Modifiers", "{crafted}+31 to maximum Life", "{crafted}+12% to Fire Resistance"]
    assert _count_findings(lines) == []
