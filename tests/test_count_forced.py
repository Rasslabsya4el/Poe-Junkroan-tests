"""#510 re-merge with #437: counting (`useful_lines.count_item`) never drops a forced line of the slot.

Fake PoB, no runtime. An item is a ring rolled with `Prefix:`/`Suffix:` headers and the rendered text of each
affix after the implicit block (as PoB writes it); the fake scores a header by its weight, and `recraft`
re-renders the text from the headers left. The forced line has weight 0 (PoB values it neutral), so counting
would drop it on any other item.
"""

from __future__ import annotations

import re

from junkroan.optimizer.loot_gear import LootGear, raw_carries
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.useful_lines import count_item, item_lines

DPS = Objective(maximize="CombinedDPS")
FORCED = "+1 to Level of all Fire Spell Skill Gems"
TEXT = {"Fire": FORCED, "A": "+40 to Strength", "B": "+30 to Dexterity", "C": "+20 to Intelligence", "D": "+10 to maximum Life"}
WEIGHT = {"Fire": 0.0, "A": 40.0, "B": 30.0, "C": 20.0, "D": 10.0}
MODS = {"mods": [{"mod_id": "Fire", "type": "Prefix", "lines": [FORCED], "level": 1, "weight": 100}]}
ORDER = ["A", "Fire", "B", "C", "D"]  # the forced line sits in the middle of the item


def _raw(ids: list[str], *, rendered: bool = True) -> str:
    heads = "\n".join(f"{'Prefix' if i % 2 == 0 else 'Suffix'}: {{range:0.500}}{mod}" for i, mod in enumerate(ids))
    body = "\n".join(f"{{tags:x}}{{{'prefix' if i % 2 == 0 else 'suffix'}}}{TEXT[mod]}" for i, mod in enumerate(ids)) if rendered else ""
    return f"Rarity: RARE\nonly\nIron Ring\nItem Level: 84\n{heads}\nImplicits: 0" + (f"\n{body}" if body else "")


class _Pob:
    def __init__(self) -> None:
        self.worn: dict[str, str | None] = {}
        self.recrafted: list[str] = []

    def _value(self, raw: str | None) -> float:
        return sum(WEIGHT[ln.text] for ln in item_lines(raw)) if raw else 0.0

    def stats(self, keys):
        return {k: 1000.0 + sum(self._value(r) for r in self.worn.values()) for k in keys}

    def list_item_mods(self, base, **_kw):
        return MODS

    def list_bench_mods(self, base, ilvl=None):
        return {"mods": []}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None, forced=None):
        return [{"raw": _raw(ORDER), "mod_ids": list(ORDER)}]

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": {"CombinedDPS": 1000.0 + self._value(t["item"]["raw"])}} for t in trials]

    def recraft(self, raw: str) -> str:
        self.recrafted.append(raw)
        heads = [m.group(1) for m in re.finditer(r"^(?:Prefix|Suffix): \{range:[^}]*\}(\w+)$", raw, re.M)]
        head_block = raw.split("\nImplicits: 0")[0]
        body = "\n".join(f"{{tags:x}}{{{'prefix' if i % 2 == 0 else 'suffix'}}}{TEXT[mod]}" for i, mod in enumerate(heads))
        return head_block + "\nImplicits: 0" + (f"\n{body}" if body else "")

    def equip(self, items):
        self.worn.update(items)


def _fill(forced: list[str]):
    pob = _Pob()
    loot = LootGear(pob, DPS, Rails.load(), log=lambda _m: None)
    if forced:
        loot.forced_lines = {"Ring 1": forced}
    return pob, loot.fill_slot("Ring 1", "Iron Ring", n=1, bench=False)


def test_a_forced_line_valued_neutral_stays_on_the_delivered_item_and_is_one_of_the_slots_lines() -> None:
    pob, res = _fill([FORCED])

    assert raw_carries(res.raw, FORCED) and pob.worn == {"Ring 1": res.raw}
    assert "Fire" not in res.dropped
    # a ring holds 3 lines; the forced one is one of them, the 2 best of the others fill the rest (never a fourth)
    assert [ln.text for ln in item_lines(res.raw)] == ["A", "Fire", "B"]
    assert res.dropped == ["C", "D"] and (res.lines_counted, res.lines_total) == (3, 5)
    assert res.after_count.value == 1000 + 40 + 30


def test_the_same_item_without_a_forced_line_drops_the_neutral_line_as_on_main() -> None:
    pob, res = _fill([])

    assert not raw_carries(res.raw, FORCED)
    assert res.dropped == ["Fire", "D"] and [ln.text for ln in item_lines(res.raw)] == ["A", "B", "C"]
    assert (res.lines_counted, res.lines_total) == (3, 5) and res.after_count.value == 1000 + 40 + 30 + 20


def test_count_item_without_protected_lines_is_the_old_rule_byte_for_byte() -> None:
    lines = item_lines(_raw(ORDER))
    valued = [(ln, (WEIGHT[ln.text], WEIGHT[ln.text])) for ln in lines]

    assert count_item(valued, 3) == count_item(valued, 3, protected=()) == count_item(valued, 3, protected=frozenset())
    kept = [ln.text for ln, _v in count_item(valued, 3).kept]
    assert kept == ["A", "B", "C"]
    protected = count_item(valued, 3, protected={lines[1].index})
    assert [ln.text for ln, _v in protected.kept] == ["A", "Fire", "B"] and [ln.text for ln, _v in protected.dropped] == ["C", "D"]
