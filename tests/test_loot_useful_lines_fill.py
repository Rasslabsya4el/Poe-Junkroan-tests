"""`LootGear.fill_slot` / `fill` apply the `g-useful-n` rule (issue #437, unit 2): fake PoB, no runtime.

The fake scores an item as 1000 + the sum of its lines' weights (a line = a Prefix:/Suffix: mod id), the
build as the sum over the worn items, so a line's value is its weight and every number is known.
"""

from __future__ import annotations

import dataclasses

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.useful_lines import TOP_K, item_lines

DPS = Objective(maximize="CombinedDPS")


def _raw(name: str, ids: list[str]) -> str:
    lines = "\n".join(f"{'Prefix' if i % 2 == 0 else 'Suffix'}: {{range:0.500}}{mod}" for i, mod in enumerate(ids))
    return f"Rarity: RARE\n{name}\nIron Ring\nItem Level: 84\n{lines}\nImplicits: 0"


class _FakePob:
    def __init__(self, weights: dict[str, float], rolled: dict[str, list[dict]], resist: dict[str, float] | None = None) -> None:
        self.weights = weights
        self.rolled = rolled  # base -> rolled items
        self.resist = resist or {}
        self.worn: dict[str, str | None] = {}
        self.batches: list[list[str]] = []  # the raws of every trial_stats call

    def _value(self, raw: str | None) -> float:
        return sum(self.weights[ln.text] for ln in item_lines(raw)) if raw else 0.0

    def stats(self, keys):
        total = 1000.0 + sum(self._value(r) for r in self.worn.values())
        return {k: self.resist.get(k, total if k == "CombinedDPS" else 0.0) for k in keys}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        return list(self.rolled.get(base, []))

    def trial_stats(self, trials, keys, mode="fast"):
        self.batches.append([t["item"]["raw"] for t in trials])
        out = []
        for t in trials:
            slot, raw = t["item"]["slot"], t["item"]["raw"]
            total = 1000.0 + sum(self._value(r) for s, r in self.worn.items() if s != slot) + self._value(raw)
            out.append({"ok": True, "stats": {"CombinedDPS": total}})
        return out

    def equip(self, items):
        self.worn.update(items)

    def export_xml(self) -> str:
        # what `LootGear.fill` reads for the start gear set (#179 unit 2): the worn items, as PoB writes them
        from xml.sax.saxutils import escape

        worn = [(slot, raw) for slot, raw in self.worn.items() if raw]
        items = "".join(f'<Item id="{i}">{escape(raw)}</Item>' for i, (_s, raw) in enumerate(worn, 1))
        slots = "".join(f'<Slot name="{slot}" itemId="{i}"/>' for i, (slot, _r) in enumerate(worn, 1))
        return f'<PathOfBuilding><Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>'

    def list_bench_mods(self, base, ilvl=None):
        return {"mods": []}

    def list_item_mods(self, base, **_kw):
        return {"mods": []}


def _rare(name: str, ids: list[str]) -> dict:
    return {"raw": _raw(name, ids), "mod_ids": ids}


def test_only_the_top_k_are_counted_and_the_counted_winner_is_delivered() -> None:
    weights = {"Big": 60.0, "Mid": 10.0, "Mid2": 10.0, "Mid3": 10.0, "Good": 40.0, "Good2": 40.0, "Fine": 5.0, "Fine2": 5.0, "Bad": -8.0}
    # c0: the best raw (1090) but counting drops one Mid -> 1080; c1: raw 1085, nothing to drop -> 1085, it wins;
    # c2 carries a drawback that stays; c10 and c11 are 11th and 12th by raw Score, so they are never counted
    c0 = _rare("c0", ["Big", "Mid", "Mid2", "Mid3"])
    c1 = _rare("c1", ["Good", "Good2", "Fine"])
    c2 = _rare("c2", ["Fine", "Fine2", "Bad"])
    fillers = [_rare(f"c{i}", [f"F{i}"]) for i in range(3, 12)]
    weights |= {f"F{i}": (12 - i) * 0.1 for i in range(3, 12)}
    pob = _FakePob(weights, {"Iron Ring": [c0, c1, c2, *fillers]})
    logs: list[str] = []
    loot = LootGear(pob, DPS, Rails.load(), log=logs.append)

    res = loot.fill_slot("Ring 1", "Iron Ring", n=12, bench=False)

    assert res.raw == c1["raw"] and pob.worn == {"Ring 1": c1["raw"]} and loot.current_raw == {"Ring 1": c1["raw"]}
    assert res.after_loot.value == 1085.0 and res.dropped == [] and res.drawbacks == []
    # three round trips: the 12 rolls, the line values of the top K, the one counted item that lost a line
    assert len(pob.batches[0]) == 12 and len(pob.batches) == 3 and len(pob.batches[2]) == 1
    names_in_line_batch = {f"c{i}" for i in range(12) for raw in pob.batches[1] if f"\nc{i}\n" in raw}
    assert names_in_line_batch == {f"c{i}" for i in range(TOP_K)}
    assert "counted" not in logs[0]  # nothing dropped on the winner: the log line is today's


def test_a_dropped_line_and_a_kept_drawback_are_named_in_the_log() -> None:
    weights = {"A": 40.0, "B": 25.0, "C": 10.0, "D": 3.0, "Z": 0.0, "Bad": -8.0}
    cand = _rare("only", ["A", "B", "C", "D", "Z", "Bad"])
    pob = _FakePob(weights, {"Iron Ring": [cand]})
    logs: list[str] = []
    loot = LootGear(pob, DPS, Rails.load(), log=logs.append)

    res = loot.fill_slot("Ring 1", "Iron Ring", n=1, bench=False)

    assert [ln.text for ln in item_lines(res.raw)] == ["A", "B", "C", "Bad"]
    assert res.dropped == ["D", "Z"] and res.drawbacks == ["Bad"] and (res.lines_counted, res.lines_total) == (3, 6)
    assert res.after_loot.value == 1000 + 40 + 25 + 10 + 3 - 8 and res.after_count.value == 1000 + 40 + 25 + 10 - 8
    assert "counted 3 of 6: dropped [D, Z], drawback kept [Bad]" in logs[0]
    assert res.mod_ids == ["A", "B", "C", "Bad"]


SLOTS = {"Body Armour": "Simple Robe", "Amulet": "Coral Amulet", "Belt": "Leather Belt", "Ring 1": "Iron Ring"}
SURPLUS = {"Body Armour": 4.0, "Amulet": 3.0, "Belt": 2.0, "Ring 1": 1.0}  # the value of each slot's surplus Fire line


def _extra_setup(fire: tuple[float, float], extra_items: int = 2) -> tuple[_FakePob, LootGear, list[str]]:
    weights: dict[str, float] = {}
    rolled: dict[str, list[dict]] = {}
    for i, (slot, base) in enumerate(SLOTS.items()):
        ids = [f"L{i}a", f"L{i}b", f"L{i}c", f"FireResist{i}"]  # N_slot = 3: the Fire line is the weakest useful one
        weights |= dict(zip(ids, (300.0, 200.0, 100.0, SURPLUS[slot])))
        rolled[base] = [_rare(slot, ids)]
    resist = {"FireResist": fire[0], "FireResistMax": fire[1], "ColdResist": 75.0, "ColdResistMax": 75.0, "LightningResist": 75.0, "LightningResistMax": 75.0}
    rails = Rails.load()
    rails = dataclasses.replace(rails, gear=dataclasses.replace(rails.gear, wishlist=dataclasses.replace(rails.gear.wishlist, extra_resistance_items=extra_items)))
    logs: list[str] = []
    pob = _FakePob(weights, rolled, resist)
    return pob, LootGear(pob, DPS, rails, log=logs.append), logs


def _fire_slots(pob: _FakePob) -> list[str]:
    return [slot for slot, raw in pob.worn.items() if raw and any(ln.text.startswith("FireResist") for ln in item_lines(raw))]


def test_extra_resistance_keeps_at_most_extra_resistance_items_lines() -> None:
    pob, loot, logs = _extra_setup((60.0, 75.0))
    loot.fill(SLOTS, passes=1, n=1, bench=False)
    assert sorted(_fire_slots(pob)) == ["Amulet", "Body Armour"]  # the two largest surplus Fire lines (4 and 3); Belt (2) and Ring (1) do not
    assert sum("extra resistance kept" in m for m in logs) == 2
    assert all(len(item_lines(pob.worn[s])) == 4 for s in ("Body Armour", "Amulet"))
    assert all(len(item_lines(pob.worn[s])) == 3 for s in ("Belt", "Ring 1"))
    assert {s: loot.current_raw[s] for s in SLOTS} == pob.worn


def test_extra_resistance_reads_the_item_count_from_the_rails_and_stops_at_cap() -> None:
    pob, loot, _logs = _extra_setup((60.0, 75.0), extra_items=1)
    loot.fill(SLOTS, passes=1, n=1, bench=False)
    assert _fire_slots(pob) == ["Body Armour"]  # one item only: the largest surplus line

    capped, loot, logs = _extra_setup((75.0, 75.0))
    loot.fill(SLOTS, passes=1, n=1, bench=False)
    assert _fire_slots(capped) == [] and not any("extra resistance" in m for m in logs)


def test_the_recorded_gear_set_holds_the_item_with_its_extra_resistance_line() -> None:
    # merge of #437 with #179 unit 2: the extra-resistance step runs before the final set is recorded
    pob, loot, _logs = _extra_setup((60.0, 75.0))
    recorded: list = []
    keep = loot._keep_best_gear_set
    loot._keep_best_gear_set = lambda sets, **kw: (recorded.extend(sets), keep(sets, **kw))[1]  # type: ignore[method-assign]
    loot.fill(SLOTS, passes=1, n=1, bench=False)
    final = recorded[-1]
    assert final.equipped == pob.worn == final.current_raw
    assert sorted(s for s, raw in final.equipped.items() if any(ln.text.startswith("FireResist") for ln in item_lines(raw))) == ["Amulet", "Body Armour"]


class _RecraftPob(_FakePob):
    """Raws carry rendered affix text; `recraft` marks the raw it re-rendered."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.recrafted: list[str] = []
        self.trial_items: list[dict] = []

    def trial_stats(self, trials, keys, mode="fast"):
        self.trial_items.extend(t["item"] for t in trials)
        return super().trial_stats(trials, keys, mode=mode)

    def recraft(self, raw: str) -> str:
        self.recrafted.append(raw)
        return raw + "\n# rerendered"


def test_a_header_removal_is_trialled_and_delivered_with_a_recraft_on_a_real_shaped_raw() -> None:
    raw = (
        "Rarity: RARE\nonly\nIron Ring\nItem Level: 84\nPrefix: {range:0.500}A\nSuffix: {range:0.500}B\nSuffix: {range:0.500}C\nImplicits: 0\n"
        "{tags:x}{prefix}+1 A\n{tags:x}{suffix}+1 B\n{tags:x}{suffix}+1 C"
    )
    pob = _RecraftPob({"A": 40.0, "B": 25.0, "C": 0.0}, {"Iron Ring": [{"raw": raw, "mod_ids": ["A", "B", "C"]}]})
    loot = LootGear(pob, DPS, Rails.load(), log=lambda _m: None)

    res = loot.fill_slot("Ring 1", "Iron Ring", n=1, bench=False)

    assert [ln.text for ln in item_lines(raw)] == ["A", "B", "C"]
    assert res.dropped == ["C"] and len(pob.recrafted) == 1  # delivered through pob.recraft once
    assert res.raw == pob.recrafted[0] + "\n# rerendered" and pob.worn == {"Ring 1": res.raw} and loot.current_raw == {"Ring 1": res.raw}
    assert "{suffix}" not in pob.recrafted[0] and "Suffix: {range:0.500}C" not in pob.recrafted[0]
    # the roll trial and the full candidate carry no flag; the 3 line trials and the counted item do
    assert [bool(it.get("recraft")) for it in pob.trial_items] == [False, False, True, True, True, True]
    assert all(it["raw"] != raw for it in pob.trial_items if it.get("recraft"))
