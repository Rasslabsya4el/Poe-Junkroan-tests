from junkroan.optimizer.trace_output import trace_output_from_xml


def _xml(flasks: dict[int, tuple[str, str]]) -> str:
    """flasks: slot -> (rarity, text after the rarity line)."""
    items = "".join(f"<Item id=\"{n}\">Rarity: {r}\nName\n{txt}</Item>" for n, (r, txt) in flasks.items())
    slots = "".join(f"<Slot name=\"Flask {n}\" itemId=\"{n}\"/>" for n in flasks)
    return (f"<PathOfBuilding><Items activeItemSet=\"1\">{items}"
            f"<ItemSet id=\"1\">{slots}</ItemSet></Items></PathOfBuilding>")


MAGIC = "Granite Flask\nPrefix: {range:0.5}FlaskFullInstantRecovery1\nSuffix: None"


def test_two_bare_of_five():
    f = {1: ("NORMAL", "Divine Life Flask"), 2: ("NORMAL", "Quicksilver Flask"),
         3: ("MAGIC", MAGIC), 4: ("MAGIC", MAGIC), 5: ("MAGIC", MAGIC)}
    assert trace_output_from_xml(_xml(f))["flask-bare-base-output"] == 2


def test_all_magic_is_zero():
    f = {n: ("MAGIC", MAGIC) for n in range(1, 6)}
    assert trace_output_from_xml(_xml(f))["flask-bare-base-output"] == 0


def test_empty_slot_is_not_bare():
    f = {1: ("NORMAL", "Divine Life Flask")}
    out = trace_output_from_xml(_xml(f))
    assert out["flask-bare-base-output"] == 1 and out["flask-slot-empty"] == 4


def test_game_import_magic_flask_is_not_bare():
    f = {1: ("MAGIC", "Name")}
    xml = _xml(f).replace("Name\nName", "Ebullient Divine Life Flask of Allaying\nUnique ID: x\nItem Level: 62")
    assert trace_output_from_xml(xml)["flask-bare-base-output"] == 0


def test_magic_with_bare_base_name_line_is_bare():
    xml = _xml({1: ("MAGIC", "Name")}).replace("Name\nName", "Divine Life Flask\nItem Level: 62\nImplicits: 0")
    assert trace_output_from_xml(xml)["flask-bare-base-output"] == 1


def test_normal_divine_life_is_bare():
    assert trace_output_from_xml(_xml({1: ("NORMAL", "Divine Life Flask")}))["flask-bare-base-output"] == 1


def test_decoded_smite_flasks_none_bare():
    from pathlib import Path
    from junkroan.pob.session import decode_import_code
    p = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "flask_bare" / "smite-s4.pob.txt"
    out = trace_output_from_xml(decode_import_code(p.read_text(encoding="utf-8").strip()))
    assert out["flask-bare-base-output"] == 0 and out["flask-slot-empty"] == 0
