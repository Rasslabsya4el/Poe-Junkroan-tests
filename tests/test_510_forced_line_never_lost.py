"""#510 unit 13: a forced mod line is never sent to PoB missing (PoB-free).

A: the value probe of `useful_lines.line_values_many` builds no removal trial of a protected (forced) line.
B: a recraft trial (affix headers kept, rendered text stripped) still counts as carrying a forced line
   whose mod id is one of the headers left (`forced_classes`).
C: `count_item` works with the value of a protected line unmeasured (`None`).
"""

from __future__ import annotations

from junkroan.optimizer import useful_lines as ul
from junkroan.optimizer.loot_gear import LootGear, _forced_indices
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE, forced_classes

DPS = Objective(maximize="CombinedDPS")
FORCED = "+1 to Level of all Fire Spell Skill Gems"
TEXT = {"Fire": FORCED, "A": "+40 to Strength", "B": "+30 to Dexterity", "C": "+20 to Intelligence"}
ORDER = ["A", "Fire", "B", "C"]


def _raw(ids: list[str]) -> str:
    heads = "\n".join(f"{'Prefix' if i % 2 == 0 else 'Suffix'}: {{range:0.500}}{mod}" for i, mod in enumerate(ids))
    body = "\n".join(f"{{tags:x}}{{{'prefix' if i % 2 == 0 else 'suffix'}}}{TEXT[mod]}" for i, mod in enumerate(ids))
    return f"Rarity: RARE\nonly\nVaal Wand\nItem Level: 84\n{heads}\nImplicits: 0\n{body}"


class _Pob:
    def __init__(self) -> None:
        self.trials: list[dict] = []

    def trial_stats(self, trials, keys, mode="fast"):
        self.trials += trials
        return [{"ok": True, "stats": {"CombinedDPS": 1000.0}} for _ in trials]


def _missing(pob: _Pob, ids_kept: str) -> list[str]:
    """The mod ids (of the headers left) of every trial that lacks `ids_kept`'s header."""

    return [t["item"]["raw"] for t in pob.trials if f"}}{ids_kept}\n" not in t["item"]["raw"] + "\n"]


# --- A: no removal trial of a protected line -------------------------------------------------------------------
def test_a_protected_line_gets_no_removal_trial() -> None:
    raw = _raw(ORDER)
    lines = ul.item_lines(raw)
    fire = next(ln for ln in lines if ln.text == "Fire")

    pob = _Pob()
    TRACE.reset()
    out = ul.line_values_many(pob, DPS, "Weapon 1", [raw], protected=[{fire.index}])

    assert len(pob.trials) == 1 + len(lines) - 1  # the full item and one removal per unprotected line
    assert pob.trials[0]["item"]["raw"] == raw
    assert _missing(pob, "Fire") == []  # every trial still carries the forced header
    assert [ln.text for ln, _v in out[0]] == ORDER and dict((ln.text, v) for ln, v in out[0])["Fire"] is None
    assert all(v is not None for ln, v in out[0] if ln.text != "Fire")
    TRACE.reset()


def test_no_protected_line_is_the_old_trial_list() -> None:
    raw = _raw(ORDER)
    lines = ul.item_lines(raw)
    want = [{"item": {"slot": "Weapon 1", "raw": raw}}, *({"item": ul.trial_item("Weapon 1", raw, [ln])} for ln in lines)]

    for kwargs in ({}, {"protected": None}, {"protected": [frozenset()]}):
        pob = _Pob()
        TRACE.reset()
        out = ul.line_values_many(pob, DPS, "Weapon 1", [raw], **kwargs)
        assert pob.trials == want, kwargs
        assert all(v is not None for _ln, v in out[0])
    TRACE.reset()


def test_the_trace_counter_sees_no_wand_without_the_forced_line() -> None:
    raw = _raw(ORDER)
    fire = next(ln for ln in ul.item_lines(raw) if ln.text == "Fire")
    TRACE.reset()
    TRACE.set_forced({"affixes": {"Weapon 1": [FORCED]}, "affix_mod_ids": {"Weapon 1": [["Fire"]]}})

    ul.line_values_many(_Pob(), DPS, "Weapon 1", [raw], protected=[{fire.index}])
    moves = TRACE.considered()["(unattributed)"]
    assert moves.get("forced-missing:affix:Weapon 1", {"generated": 0})["generated"] == 0
    assert moves["forced:kept"]["generated"] == 4
    TRACE.reset()


def test_count_entries_passes_the_forced_indices_only_when_the_slot_has_forced_lines() -> None:
    class Pob(_Pob):
        def list_item_mods(self, base, **_kw):
            return {"mods": [{"mod_id": "Fire", "type": "Prefix", "lines": [FORCED], "level": 1, "weight": 1}]}

    raw = _raw(ORDER)
    for forced, want_trials in (([FORCED], 4), ([], 5)):
        pob = Pob()
        loot = LootGear(pob, DPS, Rails.load(), log=lambda _m: None)
        if forced:
            loot.forced_lines = {"Weapon 1": forced}
        entries = [{"raw": raw, "score": None}]
        TRACE.reset()
        loot._count_entries("Weapon 1", "Vaal Wand", entries, ul)
        assert len(pob.trials) >= want_trials  # line values (the counted trials, if any, follow)
        probes = [t for t in pob.trials[:want_trials]]
        assert ("Fire" in "".join(t["item"]["raw"] for t in probes)) is True
        if forced:
            assert all("}Fire\n" in t["item"]["raw"] + "\n" for t in probes)
        else:
            assert any("}Fire\n" not in t["item"]["raw"] + "\n" for t in probes)
    TRACE.reset()
    assert _forced_indices  # imported: the helper the caller uses


# --- B: a recraft trial counts as carrying the forced line by its header ----------------------------------------
def _recraft_trial(raw: str, dropped_text: str) -> dict:
    lines = ul.item_lines(raw)
    return {"item": {"slot": "Weapon 1", **ul.trial_item("Weapon 1", raw, [next(ln for ln in lines if ln.text == dropped_text)])}}


FORCED_DICT = {"affixes": {"Weapon 1": [FORCED]}, "affix_mod_ids": {"Weapon 1": [["Fire", "Fire2"]]}}


def test_a_recraft_raw_with_the_forced_header_is_kept() -> None:
    trial = _recraft_trial(_raw(ORDER), "B")

    assert trial["item"].get("recraft") is True and FORCED not in trial["item"]["raw"]  # the text is gone, the header stays
    assert forced_classes(trial, FORCED_DICT) == {"forced:kept"}


def test_a_recraft_raw_without_the_forced_header_is_missing() -> None:
    trial = _recraft_trial(_raw(ORDER), "Fire")

    assert forced_classes(trial, FORCED_DICT) == {"forced-missing:affix:Weapon 1"}


def test_without_mod_ids_or_recraft_the_text_check_is_unchanged() -> None:
    trial = _recraft_trial(_raw(ORDER), "B")
    assert forced_classes(trial, {"affixes": {"Weapon 1": [FORCED]}}) == {"forced-missing:affix:Weapon 1"}  # no id known: no guess
    text_only = {"item": {"slot": "Weapon 1", "raw": _raw(ORDER)}}
    assert forced_classes(text_only, FORCED_DICT) == {"forced:kept"}
    no_recraft = {"item": {"slot": "Weapon 1", "raw": _raw(ORDER).split("Implicits: 0")[0] + "Implicits: 0"}}  # headers only, no recraft flag
    assert forced_classes(no_recraft, FORCED_DICT) == {"forced-missing:affix:Weapon 1"}


def test_loot_gear_notes_the_forced_mod_ids_for_the_trace() -> None:
    class Pob(_Pob):
        def list_item_mods(self, base, **_kw):
            return {"mods": [{"mod_id": "Fire", "type": "Prefix", "lines": [FORCED], "level": 1, "weight": 1}]}

    TRACE.reset()
    TRACE.set_forced({"affixes": {"Weapon 1": [FORCED]}})
    loot = LootGear(Pob(), DPS, Rails.load(), log=lambda _m: None)
    loot.forced_lines = {"Weapon 1": [FORCED]}
    loot._forced_for("Weapon 1", "Vaal Wand")
    assert TRACE.forced()["affix_mod_ids"] == {"Weapon 1": [["Fire"]]}
    TRACE.reset()
    LootGear(Pob(), DPS, Rails.load(), log=lambda _m: None)._forced_for("Weapon 1", "Vaal Wand")  # nothing forced: nothing noted
    assert TRACE.forced() is None


# --- C: count_item with an unmeasured protected line ----------------------------------------------------------
def test_count_item_with_the_forced_value_absent_keeps_it_and_fills_the_rest_by_value() -> None:
    lines = ul.item_lines(_raw(ORDER))
    weight = {"A": 40.0, "B": 30.0, "C": 20.0}
    valued = [(ln, None if ln.text == "Fire" else (weight[ln.text], weight[ln.text])) for ln in lines]
    fire = lines[1].index

    counted = ul.count_item(valued, 3, protected={fire})
    assert [ln.text for ln, _v in counted.kept] == ["A", "Fire", "B"]  # forced + the 2 best of the rest
    assert [ln.text for ln, _v in counted.dropped] == ["C"] and counted.drawbacks == ()

    roomy = ul.count_item(valued, 4, protected={fire})
    assert [ln.text for ln, _v in roomy.kept] == ["A", "Fire", "B", "C"] and roomy.dropped == ()
    tight = ul.count_item(valued, 1, protected={fire})
    assert [ln.text for ln, _v in tight.kept] == ["Fire"]
