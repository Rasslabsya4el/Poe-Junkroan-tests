"""#391: the owner's page db (cells, notes) and decisions folded into the rulebook entries."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
ENTRIES = json.loads((ROOT / "docs/rulebook/loadout-rulebook.entries.json").read_text(encoding="utf-8"))
BY = {e["id"]: e for e in ENTRIES["entries"]}
DUMP = json.loads((FIX / "rulebook_391_dump.json").read_text(encoding="utf-8"))
SETTLED = ["u-tiers", "i-bases", "i-bench", "c-pantheon", "cf-state"]


def test_cells_verbatim():
    assert len(DUMP["cells"]) == 15
    for c in DUMP["cells"]:
        ent, lo = c["id"].split("--")
        assert BY[ent]["rules"][lo] == c["text"], c["id"]


def test_notes_verbatim():
    notes = [n for n in DUMP["notes"] if n["note"]]
    assert len(notes) == 5
    for n in notes:
        assert n["note"] in BY[n["id"]]["user_note"], n["id"]
    old = "интересно было бы чтобы ты спарсил"
    un = BY["c-pantheon"]["user_note"]
    assert un.index(old) < un.index(next(n["note"] for n in notes if n["id"] == "c-pantheon"))


def test_decisions():
    for i in SETTLED:
        assert "question" not in BY[i], i
    for i in ("u-tiers", "i-bases", "i-bench", "c-pantheon"):
        assert BY[i]["status"] == "settled"
        assert "assumed" not in BY[i]
    assert sum("question" in e for e in ENTRIES["entries"]) == 5
    assert BY["u-tiers"]["rules"]["day1"] == "T5"
    assert BY["u-tiers"]["rules"]["t16"] == "до T4"
    assert BY["u-tiers"]["rules"]["endgame"] == "до T1 включительно; + босс-дроп"
    assert BY["i-bases"]["rules"]["day1"] == "базы до 70; ilvl: loot gear 70, template (wishlist) gear 72, оружие 76"
    assert BY["i-bench"]["rules"]["day1"].endswith("; крафты за Exalted Orb — нет (только с T16)")
    assert BY["c-pantheon"]["rules"]["day1"] == "нет"
    assert BY["c-pantheon"]["rules"]["t16"] == "все силы и апгрейды"
    assert "«pinnacle boss ramp» 10 с (утверждено, #27)" in BY["cf-state"]["explain"]


def test_machine_unchanged():
    before = json.loads((FIX / "rulebook_391_machine_before.json").read_text(encoding="utf-8"))
    built = json.loads((ROOT / "docs/rulebook/loadout-rulebook.json").read_text(encoding="utf-8"))
    after = {e["id"]: e["machine"] for e in built["entries"] if "machine" in e}
    assert after == before
    src = {i: e["machine"] for i, e in BY.items() if "machine" in e}
    assert all(before[i] == m for i, m in src.items())
