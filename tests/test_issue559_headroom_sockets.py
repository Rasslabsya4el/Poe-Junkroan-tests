"""#559 (row 1, PoB-free): the joint kick's victim ranking rolls under the incumbent's `Sockets:` line.

`_slots_with_damage_headroom` rolls each rare slot to rank it; those rolls are loop gear candidates, so (as #548's
fill) they carry the slot incumbent's `Sockets:` line verbatim and their trials run inside the trace's incumbent note.
The fake session records the `random_rares` kwargs, builds the raw its roll would carry, and counts each trial at the
trace's PoB boundary like the real one.
"""

from __future__ import annotations

from junkroan.optimizer.trace import TRACE

from loop_fakes import _Loot, _Pob, _skeleton, loop_over

LINE = "R-R-G B"
GLOVES_BASE = "Fingerless Silk Gloves"
BOOTS_BASE = "Two-Toned Boots"
INC_GLOVES = f"Rarity: Rare\nDoom Grip\n{GLOVES_BASE}\nItem Level: 80\nSockets: {LINE}\nImplicits: 0\n+80 to maximum Life"
BARE_BOOTS = f"Rarity: Rare\nDoom Tread\n{BOOTS_BASE}\nItem Level: 80\nImplicits: 0\n+80 to maximum Life"
SHIELD = "Rarity: Rare\nDoom Wall\nVaal Spirit Shield\nItem Level: 80\nSockets: R-G\n"


def _rolled(slot: str, base: str, sockets: str | None) -> str:
    return f"Rarity: Rare\nRolled {slot}\n{base}\nItem Level: 80\n" + (f"Sockets: {sockets}\n" if sockets else "") + "Implicits: 0\n+80 to maximum Life"


class _RollPob(_Pob):
    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.rolls: list[dict] = []
        self.trialled: list[dict] = []

    def random_rares(self, base, **kwargs):
        self.rolls.append({"base": base, **kwargs})
        slot = {GLOVES_BASE: "Gloves", BOOTS_BASE: "Boots", "Serrated Arrow Quiver": "Weapon 2"}[base]
        return [{"raw": _rolled(slot, base, kwargs.get("sockets"))} for _ in range(2)]

    def trial_stats(self, trials, keys, mode="fast"):
        self.trialled.extend(trials)
        for t in trials:
            TRACE.count_trial(t)
        return []


def _headroom(incumbents: dict[str, str], rare_bases: dict[str, str], sockets: dict | None = None) -> _RollPob:
    TRACE.reset()
    pob = _RollPob(1000.0)
    loot = _Loot(pob, {})
    loot.current_raw.update(incumbents)
    sk = _skeleton(rare_bases)
    sk.sockets = dict(sockets or {})
    p = loop_over(pob, tree=None, gear=loot, skeleton=sk)
    p.headroom(sk, loot, list(rare_bases), 5, 1)
    return pob


def _sockets_asked(pob: _RollPob) -> dict[str, object]:
    return {r["base"]: r.get("sockets") for r in pob.rolls}


def _classes() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for moves in TRACE.considered().values():
        for c, n in moves.items():
            if c.startswith("gear-sockets:"):
                acc = out.setdefault(c, {"generated": 0, "evaluated": 0})
                acc["generated"] += n.get("generated", 0)
                acc["evaluated"] += n.get("evaluated", 0)
    return out


def test_headroom_rolls_carry_the_incumbents_sockets_line() -> None:
    pob = _headroom({"Gloves": INC_GLOVES}, {"Gloves": GLOVES_BASE})
    assert _sockets_asked(pob) == {GLOVES_BASE: LINE}
    assert pob.trialled and all(f"Sockets: {LINE}\n" in t["item"]["raw"] for t in pob.trialled)  # the rolls the ranking judges


def test_headroom_no_incumbent_keeps_the_skeletons_default() -> None:
    pob = _headroom({}, {"Boots": BOOTS_BASE}, {"Boots": "W-W"})
    assert _sockets_asked(pob) == {BOOTS_BASE: "W-W"}


def test_headroom_incumbent_without_a_line_keeps_the_skeletons_default() -> None:
    pob = _headroom({"Boots": BARE_BOOTS}, {"Boots": BOOTS_BASE}, {"Boots": "W-W"})
    assert _sockets_asked(pob) == {BOOTS_BASE: "W-W"}


def test_headroom_other_class_incumbent_keeps_the_skeletons_default() -> None:
    pob = _headroom({"Weapon 2": SHIELD}, {"Weapon 2": "Serrated Arrow Quiver"}, {"Weapon 2": "G-G"})
    assert _sockets_asked(pob) == {"Serrated Arrow Quiver": "G-G"}  # a Quiver cannot hold the Shield's sockets


def test_headroom_trials_run_under_the_incumbent_trace_note() -> None:
    _headroom({"Gloves": INC_GLOVES, "Boots": BARE_BOOTS}, {"Gloves": GLOVES_BASE, "Boots": BOOTS_BASE})
    classes = _classes()
    assert classes["gear-sockets:incumbent"]["generated"] > 0 and classes["gear-sockets:incumbent"]["evaluated"] > 0
    assert classes.get("gear-sockets:missing", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}
    assert "gear-sockets:unclassified" not in classes


def test_headroom_without_an_incumbent_line_has_no_trace_note() -> None:
    _headroom({"Boots": BARE_BOOTS}, {"Boots": BOOTS_BASE})
    assert not _classes()
