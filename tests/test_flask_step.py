from dataclasses import dataclass

from junkroan.optimizer.objective import Score
from junkroan.optimizer.flask_step import FlaskSlotResult, flask_log_line, run_flask_step


@dataclass(frozen=True)
class Base:
    name: str
    kind: str
    drop_level: int


@dataclass(frozen=True)
class Mod:
    id: str
    level: int
    affix: str


@dataclass(frozen=True)
class Cand:
    base: Base
    prefix: Mod | None
    suffix: Mod | None

    @property
    def id(self):
        return (self.base.name, self.prefix.id if self.prefix else None, self.suffix.id if self.suffix else None)


class FakeProbe:
    """`value(c)`: the Score value a candidate adds (inactive); `forced_fn(c) -> (value, defence)` what it adds when
    its slot's flag is forced on; `inputs`: slot -> the candidate the build came in with."""

    def __init__(self, value, defence=None, inputs=None, forced_fn=None, active_fn=None, violation=0.0):
        self.value = value
        self.defence_fn = defence or (lambda c: (0.0, 0.0, 0.0))
        self.forced_fn = forced_fn
        self.active_fn = active_fn or (lambda c: False)
        self.violation = violation
        self.inputs = dict(inputs or {})
        self.slots = dict(self.inputs)
        self.flags = {}
        self.put = []
        self.forced_trials = []

    def _derive(self):  # a plain read re-derives every flag (#575)
        self.flags = {s: self.active_fn(c) for s, c in self.slots.items()}

    def score(self):
        self._derive()
        return Score(-self.violation, 100.0 + sum(self.value(c) for c in self.slots.values()))

    def defence(self):
        self._derive()
        t = [self.defence_fn(c) for c in self.slots.values()]
        return tuple(float(sum(x[i] for x in t)) for i in range(3))

    def input_flasks(self):
        return dict(self.inputs)

    def put_input(self, slot, c):
        self.slots[slot] = c

    def measure_active(self, slot, c):
        self.forced_trials.append(c)
        self.slots[slot] = c
        self.flags[slot] = True  # forced, and left set until the next plain read, as PoB does
        v, d = self.forced_fn(c)
        others = [x for s, x in self.slots.items() if s != slot]
        score = Score(-self.violation, 100.0 + sum(self.value(x) for x in others) + v)
        dd = [self.defence_fn(x) for x in others] + [d]
        self.slots.pop(slot)
        return score, tuple(float(sum(x[i] for x in dd)) for i in range(3))

    def snapshot(self):
        return dict(self.slots)

    def restore(self, s):
        self.slots = dict(s)

    def put_flask(self, slot, c):
        self.put.append(c)
        self.slots[slot] = c

    def clear_flask(self, slot):
        self.slots.pop(slot, None)


BASES = [Base("Life", "life", 10), Base("Quicksilver", "utility", 20), Base("Sulphur", "utility", 30),
         Base("Tincture", "tincture", 40), Base("Late", "life", 80)]
MODS = [Mod("p1", 10, "prefix"), Mod("p2", 90, "prefix"), Mod("s1", 20, "suffix")]


def run(value, item_level=84, defence=None, fixed=None, bases=BASES):
    probe = FakeProbe(value, defence)
    res = run_flask_step(probe, bases, lambda b: MODS, lambda b, p, s: Cand(b, p, s),
                         item_level=item_level, base_level_max=70, fixed=fixed)
    return probe, res


def gain(c):
    g = {"Life": 5, "Quicksilver": 4, "Sulphur": 3, "Tincture": 9, "Late": 99}[c.base.name]
    return g + (2 if c.prefix else 0) + (1 if c.suffix else 0)


def test_five_slots_filled_in_rail():
    probe, res = run(gain)
    assert len(res.slots) == 5 and all(r.chosen is not None for r in res.slots)
    assert all(c.base.drop_level <= 70 for c in probe.put)
    assert all(m is None or m.level <= 84 for c in probe.put for m in (c.prefix, c.suffix))
    assert len({r.chosen.id for r in res.slots}) == 5


def test_tincture_best_kept():
    _, res = run(gain)
    first = res.slots[0].chosen
    assert first.base.kind == "tincture"
    assert first.prefix.id == "p1" and first.suffix.id == "s1"
    assert res.score_after > res.score_before


def test_nonpaying_slot_filled_by_defence():
    probe, res = run(lambda c: -1)
    assert all(r.chosen is not None for r in res.slots)  # below the empty slot, still filled
    assert len(probe.slots) == 5


def test_fixed_base_kept_below_empty_with_best_mods():
    fx = BASES[0]

    def value(c):
        return -10 + (2 if c.prefix else 0) + (1 if c.suffix else 0) if c.base is fx else 5

    probe, res = run(value, fixed={"Flask 3": fx})
    r = res.slots[2]
    assert r.chosen.base is fx and r.chosen.prefix.id == "p1" and r.chosen.suffix.id == "s1"
    assert r.score_after < r.score_before and r.tie is None
    assert all(x.chosen.base is not fx for i, x in enumerate(res.slots) if i != 2)
    assert all(c.base is not fx for slot, c in probe.slots.items() if slot != "Flask 3")


def test_fixed_base_bare_when_no_mod_beats():
    fx = Base("Fixed", "life", 99)  # above base_level_max: no drop-level filter for it
    probe, res = run(lambda c: (-5 if c.prefix is None and c.suffix is None else -6) if c.base is fx else 1,
                     fixed={"Flask 1": fx})
    assert res.slots[0].chosen.base is fx
    assert res.slots[0].chosen.prefix is None and res.slots[0].chosen.suffix is None
    assert all(r.chosen.base is not fx for r in res.slots[1:])


def _one_slot(defence, bases=BASES):
    probe = FakeProbe(lambda c: -1, defence)
    res = run_flask_step(probe, bases, lambda b: MODS, lambda b, p, s: Cand(b, p, s),
                         slots=("Flask 1",), item_level=84, base_level_max=70)
    return res.slots[0]


def test_defence_largest_ehp_gain():
    r = _one_slot(lambda c: (7.0, 0.0, 0.0) if c.base.name == "Sulphur" and c.prefix and c.prefix.id == "p1"
                  else (1.0, 9.0, 9.0))
    assert r.tie is None and r.chosen.base.name == "Sulphur" and r.chosen.prefix.id == "p1"
    assert r.score_after == 99.0


def test_defence_ties_broken_by_phys_then_speed_then_first():
    r = _one_slot(lambda c: (5.0, 3.0 if c.base.name == "Quicksilver" and not c.prefix and not c.suffix else 1.0, 0.0))
    assert r.chosen.id == ("Quicksilver", None, None)
    r = _one_slot(lambda c: (5.0, 2.0, 4.0 if c.base.name == "Sulphur" and c.suffix else 1.0))
    assert r.chosen.base.name == "Sulphur" and r.chosen.suffix is not None
    r = _one_slot(lambda c: (5.0, 2.0, 1.0))
    assert r.chosen.id == ("Life", "p1", None)  # a full tie: file order, and a variant ranks above the bare base (R5)


def test_slot_empty_only_when_nothing_trialled():
    _, res = run(lambda c: -1, bases=[BASES[4]])  # only a base above the drop level
    assert all(r.chosen is None and r.tie is None for r in res.slots)


def test_log_line_tie():
    c = Cand(BASES[0], MODS[0], MODS[2])
    line = flask_log_line(FlaskSlotResult("Flask 1", c, 100.0, 99.0, 7, 3.0, "LevelReq"))
    assert line == "flask: Flask 1 'Life' + p1 / s1 (tie: LevelReq), score 100 -> 99, 7 measured, 3 s"
    assert "(tie: file order)" in flask_log_line(FlaskSlotResult("Flask 1", c, 100.0, 99.0, 7, 3.0, "file order"))
    assert "by defence" not in line


def test_mod_over_ilvl_never_put():
    probe, _ = run(gain, item_level=50)
    assert all(m is None or m.id != "p2" for c in probe.put for m in (c.prefix, c.suffix))


def test_log_line():
    c = Cand(BASES[0], MODS[0], MODS[2])
    line = flask_log_line(FlaskSlotResult("Flask 1", c, 100.0, 112.0, 7, 3.0))
    assert line == "flask: Flask 1 'Life' + p1 / s1, score 100 -> 112, 7 measured, 3 s"


def test_pob_flask_probe_only_equips_and_unequips():
    from junkroan.optimizer.flask_probe import PobFlaskProbe

    class Pob:
        def __init__(self):
            self.calls = []

        def equip(self, items, drop_replaced=False):
            self.calls.append(dict(items))

        def set_flasks_active(self, *a, **k):
            raise AssertionError("set_flasks_active must not be called (#575)")

        def flasks_active(self):
            raise AssertionError("flasks_active must not be called (#575)")

    class Cand:
        def raw(self, level):
            return f"raw {level}"

    pob = Pob()
    probe = PobFlaskProbe(pob, lambda: None, item_level=84)
    probe.put_flask("Flask 1", Cand())
    probe.clear_flask("Flask 1")
    assert pob.calls == [{"Flask 1": "raw 84"}, {"Flask 1": None}]


# -- #589 R1-R4: Score compare, the input flask, as-if-active ranking, ties ----------------------------------------------

LIFE, QS, SULPHUR = BASES[0], BASES[1], BASES[2]


def _bare(base):
    return Cand(base, None, None)


def _step(probe, bases=BASES[:3], slots=("Flask 1",), fixed=None):
    return run_flask_step(probe, bases, lambda b: [], lambda b, p, s: Cand(b, p, s), slots=slots,
                          item_level=84, base_level_max=70, fixed=fixed)


def test_row1_equal_violation_the_larger_value_wins():
    # an infeasible build (violation 0.5): a scalar of -1 - violation would hide the value, Score does not
    probe = FakeProbe(lambda c: {"Life": 100, "Quicksilver": 120, "Sulphur": 20}[c.base.name], violation=0.5)
    res = _step(probe)
    assert res.slots[0].chosen.base.name == "Quicksilver"


def test_row2_the_input_flask_stays_on_a_tie_or_a_loss():
    inp = _bare(QS)
    probe = FakeProbe(lambda c: {"Life": 0, "Quicksilver": 120, "Sulphur": 120}[c.base.name], inputs={"Flask 1": inp})
    r = _step(probe).slots[0]
    assert r.chosen is inp and r.tie is None and "by defence" not in flask_log_line(r)
    assert probe.slots["Flask 1"] is inp
    assert r.score_before == r.score_after == 220.0  # the build as it came in


def test_row2_a_tie_on_score_is_broken_by_the_defence_gain_only_strictly():
    inp = _bare(QS)
    probe = FakeProbe(lambda c: 5, lambda c: (9.0, 0.0, 0.0) if c.base.name == "Sulphur" else (1.0, 0.0, 0.0),
                      inputs={"Flask 1": inp})
    assert _step(probe).slots[0].chosen.base.name == "Sulphur"  # equal Score, better TotalEHP: replaced
    probe = FakeProbe(lambda c: 5, lambda c: (1.0, 0.0, 0.0), inputs={"Flask 1": inp})
    assert _step(probe).slots[0].chosen is inp  # a full tie keeps the input


def test_row3_a_candidate_beating_the_input_replaces_it():
    inp = _bare(LIFE)
    probe = FakeProbe(lambda c: {"Life": 100, "Quicksilver": 120, "Sulphur": 10}[c.base.name], inputs={"Flask 1": inp})
    r = _step(probe).slots[0]
    assert r.chosen.base.name == "Quicksilver" and probe.slots["Flask 1"].base.name == "Quicksilver"


def test_fixed_slot_replaces_the_input():
    inp = _bare(QS)
    fx = Base("Divine", "life", 99)
    probe = FakeProbe(lambda c: -50 if c.base is fx else 120, inputs={"Flask 1": inp})
    r = _step(probe, fixed={"Flask 1": fx}).slots[0]
    assert r.chosen.base is fx and probe.slots["Flask 1"].base is fx


def _all_inactive(forced_fn, **kw):
    return FakeProbe(lambda c: 0, forced_fn=forced_fn, **kw)


def test_row4_all_inactive_empty_slot_is_ranked_as_if_active():
    # every plain trial ties with the empty slot; forced, only Sulphur moves PhysicalMaximumHitTaken
    probe = _all_inactive(lambda c: (0, (0.0, 50.0, 0.0) if c.base.name == "Sulphur" else (0.0, 0.0, 0.0)))
    r = _step(probe).slots[0]
    assert r.chosen.base.name == "Sulphur"  # not the first (Life) base of the file
    assert len(probe.forced_trials) >= 3
    assert probe.score() == Score(0.0, 100.0)  # the delivered flask is inactive: still counts 0


def test_row4_forced_value_ranks_first_a_flask_that_moves_nothing_ranks_last():
    probe = _all_inactive(lambda c: ({"Life": 0, "Quicksilver": 7, "Sulphur": 3}[c.base.name], (0.0, 0.0, 0.0)))
    assert _step(probe).slots[0].chosen.base.name == "Quicksilver"


def test_row5_equal_forced_deltas_lower_levelreq_wins_and_the_log_says_so():
    bases = [Base("Hi", "utility", 60), Base("Lo", "utility", 15), Base("Mid", "utility", 30)]
    probe = _all_inactive(lambda c: (0, (0.0, 50.0, 0.0)))
    r = _step(probe, bases=bases).slots[0]
    assert r.chosen.base.name == "Lo" and r.tie == "LevelReq"
    assert "(tie: LevelReq)" in flask_log_line(r)


def test_row5_same_levelreq_falls_to_file_order():
    bases = [Base("A", "utility", 30), Base("B", "utility", 30)]
    probe = _all_inactive(lambda c: (0, (0.0, 50.0, 0.0)))
    r = _step(probe, bases=bases).slots[0]
    assert r.chosen.base.name == "A" and r.tie == "file order"
    assert "(tie: file order)" in flask_log_line(r)


def test_row6_no_forced_flag_leaks_out_of_the_step():
    probe = _all_inactive(lambda c: (0, (0.0, 50.0, 0.0) if c.base.name == "Sulphur" else (0.0, 0.0, 0.0)))
    res = _step(probe, bases=[LIFE, SULPHUR, QS], slots=("Flask 1", "Flask 2"))
    assert probe.forced_trials and all(r.chosen is not None for r in res.slots)
    # what #575 derives for the finished build, with no read by the test in between
    assert probe.flags == {s: probe.active_fn(c) for s, c in probe.slots.items()} == {"Flask 1": False, "Flask 2": False}


def test_all_tie_empty_slot_not_forced_when_a_plain_trial_moves():
    probe = FakeProbe(lambda c: 3 if c.base.name == "Sulphur" else 0, forced_fn=lambda c: (99, (0.0, 0.0, 0.0)))
    r = _step(probe).slots[0]
    assert r.chosen.base.name == "Sulphur" and probe.forced_trials == []


def test_pob_flask_probe_input_and_forced_read():
    from junkroan.optimizer.flask_probe import InputFlask, PobFlaskProbe
    from junkroan.optimizer.objective import Objective

    class Pob:
        def __init__(self):
            self.calls = []

        def equipped_item_raws(self):
            return {"Flask 1": "Rarity: MAGIC\nStable Quicksilver Flask\nLevelReq: 4", "Weapon 1": "x"}

        def flasks_active(self):
            return {"Flask 1": True}

        def equip(self, items, drop_replaced=False):
            self.calls.append(("equip", dict(items)))

        def set_flasks_active(self, active):
            self.calls.append(("active", dict(active)))

        def stats(self, keys, keep_flask_flags=False):
            self.calls.append(("stats", tuple(keys), keep_flask_flags))
            return {"CombinedDPS": 5.0, "TotalEHP": 10.0}

    pob = Pob()
    probe = PobFlaskProbe(pob, lambda: Objective(maximize="CombinedDPS"), item_level=84)
    got = probe.input_flasks()
    assert list(got) == ["Flask 1"] and isinstance(got["Flask 1"], InputFlask)
    assert got["Flask 1"].base.name == "Stable Quicksilver Flask"
    assert got["Flask 1"].active is True
    probe.put_input("Flask 1", got["Flask 1"])
    assert [c[0] for c in pob.calls] == ["equip", "active"] and pob.calls[1][1] == {"Flask 1": True}
    pob.calls.clear()

    class Cand2:
        def raw(self, level):
            return f"raw {level}"

    sc, d = probe.measure_active("Flask 2", Cand2())
    assert sc.value == 5.0 and d == (10.0, 0.0, 0.0)
    assert [c[0] for c in pob.calls] == ["equip", "active", "stats", "equip"] and pob.calls[1][1] == {"Flask 2": True}
    assert pob.calls[2][2] is True and "TotalEHP" in pob.calls[2][1] and "CombinedDPS" in pob.calls[2][1]


# #589 checkpoint 11: a fixed slot whose input already is the fixed base keeps it on a tie (the brain, 2026-10-06)
DIVINE = Base("Divine Life Flask", "life", 60)
DIVINE_MODS = [Mod("p_eff", 10, "prefix"), Mod("s_frd", 20, "suffix")]


def _fixed_step(probe):
    return run_flask_step(probe, BASES[:3], lambda b: DIVINE_MODS, lambda b, p, s: Cand(b, p, s), slots=("Flask 1",),
                          item_level=84, base_level_max=70, fixed={"Flask 1": DIVINE}).slots[0]


def test_fixed_slot_keeps_an_input_of_the_fixed_base_when_every_variant_ties():
    inp = Cand(Base("Ebullient Divine Life Flask of Allaying", "input", 0), None, None)
    probe = FakeProbe(lambda c: 0, forced_fn=lambda c: (0, (0.0, 0.0, 0.0)), inputs={"Flask 1": inp})
    r = _fixed_step(probe)
    assert r.chosen is inp and probe.slots["Flask 1"] is inp  # the output raw is the input's
    assert probe.forced_trials == []  # R5: the as-if-active ranking is never run against an input


def test_fixed_slot_input_of_the_fixed_base_not_replaced_by_an_as_if_active_win():
    inp = Cand(Base("Ebullient Divine Life Flask of Allaying", "input", 0), None, None)
    forced = lambda c: (0, (0.0, 30.0, 0.0) if c.prefix is not None else (0.0, 0.0, 0.0))  # noqa: E731
    probe = FakeProbe(lambda c: 0, forced_fn=forced, inputs={"Flask 1": inp})
    r = _fixed_step(probe)
    assert r.chosen is inp and probe.forced_trials == []  # only a strict plain win replaces it (R5)


def test_fixed_slot_input_of_the_fixed_base_kept_when_it_beats_every_variant():
    inp = Cand(Base("Ebullient Divine Life Flask of Allaying", "input", 0), None, None)
    probe = FakeProbe(lambda c: 9 if c is inp else 1, inputs={"Flask 1": inp})
    assert _fixed_step(probe).chosen is inp


def test_fixed_slot_input_of_another_base_takes_the_fixed_base():
    inp = Cand(Base("Hallowed Life Flask", "input", 0), None, None)
    probe = FakeProbe(lambda c: 0, forced_fn=lambda c: (0, (0.0, 0.0, 0.0)), inputs={"Flask 1": inp})
    r = _fixed_step(probe)
    assert r.chosen.base is DIVINE and probe.slots["Flask 1"].base is DIVINE


# -- #596 R5: the input is kept, a mod variant beats the bare base on a tie, `_is_base` by the base ----------------------

def _divine_step(probe, mods, bases=None):
    return run_flask_step(probe, bases or [DIVINE], lambda b: mods, lambda b, p, s: Cand(b, p, s),
                          slots=("Flask 1",), item_level=84, base_level_max=70, fixed={"Flask 1": DIVINE}).slots[0]


def _magic_input():
    from junkroan.optimizer.flask_probe import InputFlask

    return InputFlask("Rarity: MAGIC\nEbullient Divine Life Flask of Allaying\nLevelReq: 60")


def test_row1a_fixed_slot_input_kept_when_every_variant_ties():
    inp = _magic_input()
    probe = FakeProbe(lambda c: 5, forced_fn=lambda c: (5, (0.0, 0.0, 0.0)), inputs={"Flask 1": inp})
    r = _divine_step(probe, DIVINE_MODS)
    assert r.chosen is inp and probe.slots["Flask 1"] is inp
    assert flask_log_line(r).startswith("flask: Flask 1 'Ebullient Divine Life Flask of Allaying' (input)")
    assert probe.forced_trials == [] and "bare" not in flask_log_line(r)


def test_row1b_fixed_slot_a_strictly_better_variant_replaces_the_input():
    inp = _magic_input()
    probe = FakeProbe(lambda c: 6 if getattr(c, "suffix", None) is not None else 5, inputs={"Flask 1": inp})
    r = _divine_step(probe, DIVINE_MODS)
    assert r.chosen is not inp and r.chosen.base is DIVINE and r.chosen.suffix.id == "s_frd"
    assert "(input)" not in flask_log_line(r)


def test_row2a_a_prefix_variant_tying_the_bare_base_is_placed_without_a_bare_note():
    probe = FakeProbe(lambda c: 5)
    r = _divine_step(probe, [Mod("p_eff", 10, "prefix")])
    assert r.chosen.base is DIVINE and r.chosen.prefix.id == "p_eff" and r.chosen.suffix is None
    assert "bare" not in flask_log_line(r)


def test_row2b_a_base_with_no_variant_in_the_trial_is_placed_bare_and_says_so():
    probe = FakeProbe(lambda c: 5)
    r = _divine_step(probe, [])
    assert r.chosen.id == (DIVINE.name, None, None)
    assert "'Divine Life Flask' + - / - (bare: no variant)" in flask_log_line(r)


def test_row2_a_strictly_worse_variant_leaves_the_bare_base_without_the_no_variant_note():
    probe = FakeProbe(lambda c: 5 if c.prefix is None else 4)
    r = _divine_step(probe, [Mod("p_eff", 10, "prefix")])
    assert r.chosen.prefix is None and "(bare:" not in flask_log_line(r)


def test_row3_is_base_recognises_an_input_by_its_base():
    from junkroan.optimizer.flask_probe import InputFlask
    from junkroan.optimizer.flask_step import _is_base

    divine, hallowed = Base("Divine Life Flask", "life", 60), Base("Hallowed Life Flask", "life", 60)
    eternal, hybrid = Base("Eternal Life Flask", "life", 60), Base("Hallowed Hybrid Flask", "hybrid", 60)
    known = [divine, hallowed, eternal, hybrid, Base("Life Flask", "life", 1)]
    assert _is_base(_magic_input(), divine, known)
    rare = InputFlask("Rarity: RARE\nFoo Bar\nDivine Life Flask\nLevelReq: 60")
    assert _is_base(rare, divine, known) and not _is_base(rare, hallowed, known)
    assert not _is_base(InputFlask("Rarity: MAGIC\nBountiful Hallowed Hybrid Flask of Heat"), hallowed, known)
    assert _is_base(InputFlask("Rarity: MAGIC\nBountiful Hallowed Hybrid Flask of Heat"), hybrid, known)
    assert not _is_base(InputFlask("Rarity: MAGIC\nEternal Life Flask of Warding"), divine, known)
    # a base whose name holds another base's name never matches the shorter one
    assert not _is_base(_magic_input(), known[-1], known) and _is_base(InputFlask("Rarity: MAGIC\nStable Life Flask"), known[-1], known)
