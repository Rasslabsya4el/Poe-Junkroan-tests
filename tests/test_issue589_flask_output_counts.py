from junkroan.optimizer.trace_output import trace_output_from_xml


def _xml(flasks: dict[int, str], extra_slots: str = "") -> str:
    items = "".join(f"<Item id=\"{n}\">Rarity: MAGIC\nName\n{txt}</Item>" for n, txt in flasks.items())
    slots = "".join(f"<Slot name=\"Flask {n}\" itemId=\"{n}\"/>" for n in flasks)
    return (f"<PathOfBuilding><Items activeItemSet=\"1\">{items}"
            f"<ItemSet id=\"1\">{slots}{extra_slots}</ItemSet></Items></PathOfBuilding>")


def test_five_flasks_with_divine():
    f = {1: "Divine Life Flask", 2: "Quicksilver Flask", 3: "Granite Flask", 4: "Basalt Flask", 5: "Diamond Flask"}
    out = trace_output_from_xml(_xml(f))
    assert out["flask-slot-empty"] == 0 and out["flask-divine-life"] == 1


def test_three_flasks_no_divine():
    f = {1: "Quicksilver Flask", 2: "Granite Flask", 3: "Basalt Flask"}
    out = trace_output_from_xml(_xml(f))
    assert out["flask-slot-empty"] == 2 and out["flask-divine-life"] == 0


def test_no_flasks():
    out = trace_output_from_xml(_xml({}))
    assert out["flask-slot-empty"] == 5 and out["flask-divine-life"] == 0 and "flask-active" not in out


def test_unknown_item_id_counts_empty():
    xml = _xml({1: "Granite Flask"}, "<Slot name=\"Flask 2\" itemId=\"99\"/>")
    out = trace_output_from_xml(xml)
    assert out["flask-slot-empty"] == 4
