"""#616 R6: a bare input flask gives way to a same-base mod variant that ties it on every measure."""

from junkroan.optimizer.flask_probe import InputFlask
from junkroan.optimizer.flask_step import flask_log_line, run_flask_step
from junkroan.optimizer.trace_output import trace_output_from_xml
from tests.test_flask_step import Base, Cand, FakeProbe, Mod

QS = Base("Quicksilver Flask", "utility", 20)
SULPHUR = Base("Sulphur Flask", "utility", 30)
DIVINE = Base("Divine Life Flask", "life", 60)
PREFIX = Mod("p_qs", 10, "prefix")
BARE_QS = "Rarity: NORMAL\nQuicksilver Flask\nLevelReq: 20"
MOD_INPUT = ("Rarity: MAGIC\nEbullient Divine Life Flask of Allaying\nItem Level: 62\nImplicits: 0\n"
             "{range:0.5}+10% increased Amount Recovered")


def _step(probe, bases, mods=()):
    return run_flask_step(probe, bases, lambda b: list(mods) if b is bases[0] else [], lambda b, p, s: Cand(b, p, s),
                          slots=("Flask 1",), item_level=84, base_level_max=70).slots[0]


def _xml(raw):
    return (f'<PathOfBuilding><Items activeItemSet="1"><Item id="1">{raw}</Item>'
            f'<ItemSet id="1"><Slot name="Flask 1" itemId="1"/></ItemSet></Items></PathOfBuilding>')


def test_row1_bare_input_gives_way_to_a_same_base_variant_that_ties():
    inp = InputFlask(BARE_QS)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _step(probe, [QS], [PREFIX])
    assert r.chosen is not inp and r.chosen.base is QS and r.chosen.prefix is PREFIX
    assert probe.slots["Flask 1"] is r.chosen
    line = flask_log_line(r)
    assert "(input bare: variant placed)" in line and "(input)" not in line
    assert r.score_before == r.score_after == 105.0
    # the output holds a variant: no bare base left for the trace class
    out = trace_output_from_xml(_xml("Rarity: MAGIC\nBountiful Quicksilver Flask\nPrefix: {range:0.5}X1\nSuffix: None"))
    assert out["flask-bare-base-output"] == 0


def test_row1_variant_with_a_suffix_or_both_also_replaces():
    inp = InputFlask(BARE_QS)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _step(probe, [QS], [Mod("s_qs", 10, "suffix")])
    assert r.chosen.suffix is not None and r.input_bare


def test_row2_every_candidate_strictly_worse_keeps_the_input():
    inp = InputFlask(BARE_QS)
    probe = FakeProbe(lambda c: 5 if c is inp else 1, inputs={"Flask 1": inp})
    r = _step(probe, [QS], [PREFIX])
    assert r.chosen is inp and not r.input_bare and probe.slots["Flask 1"] is inp
    assert "(input)" in flask_log_line(r) and "input bare" not in flask_log_line(r)


def test_row2b_a_tying_candidate_of_another_base_keeps_the_input():
    inp = InputFlask(BARE_QS)
    # the same-base variant is worse; Sulphur (another base) ties the input
    probe = FakeProbe(lambda c: 5 if c is inp or c.base is SULPHUR else 1, inputs={"Flask 1": inp})
    r = _step(probe, [QS, SULPHUR], [PREFIX])
    assert r.chosen is inp and not r.input_bare


def test_row2b_another_base_tying_does_not_block_a_same_base_variant_tie():
    inp = InputFlask(BARE_QS)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _step(probe, [SULPHUR, QS], [])
    assert r.chosen is inp  # no variant trialled for Quicksilver: nothing to place
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = run_flask_step(probe, [SULPHUR, QS], lambda b: [PREFIX] if b is QS else [], lambda b, p, s: Cand(b, p, s),
                       slots=("Flask 1",), item_level=84, base_level_max=70).slots[0]
    assert r.input_bare and r.chosen.base is QS and r.chosen.prefix is PREFIX


def test_row3_an_input_with_a_mod_is_kept_on_a_tie():
    inp = InputFlask(MOD_INPUT)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _step(probe, [DIVINE], [Mod("p_eff", 10, "prefix")])
    assert r.chosen is inp and not r.input_bare and probe.slots["Flask 1"] is inp
    assert "(input)" in flask_log_line(r)


def test_bare_is_read_from_the_raw_not_from_missing_prefix_lines():
    inp = InputFlask("Rarity: MAGIC\nEbullient Divine Life Flask of Allaying\nItem Level: 62\nImplicits: 0")
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    assert _step(probe, [DIVINE], [Mod("p_eff", 10, "prefix")]).chosen is inp  # name line is not a base name
    bare_magic = InputFlask("Rarity: MAGIC\nDivine Life Flask\nItem Level: 62\nImplicits: 0")
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": bare_magic})
    assert _step(probe, [DIVINE], [Mod("p_eff", 10, "prefix")]).input_bare
    with_line = InputFlask("Rarity: MAGIC\nDivine Life Flask\nItem Level: 62\nImplicits: 0\n+10% increased Amount Recovered")
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": with_line})
    assert _step(probe, [DIVINE], [Mod("p_eff", 10, "prefix")]).chosen is with_line


# -- R6 widen: the input's base gets its variants even when it ranks below the top KEEP_BASES on the screen ------------

A1, A2, A3 = Base("A1 Flask", "utility", 1), Base("A2 Flask", "utility", 2), Base("A3 Flask", "utility", 3)
QS_LATE = Base("Quicksilver Flask", "utility", 20)  # 4th on the screen: every candidate ties, the lowest LevelReq first


def _widen_step(probe):
    bases = [A1, A2, A3, QS_LATE]
    return run_flask_step(probe, bases, lambda b: [PREFIX] if b is QS_LATE else [], lambda b, p, s: Cand(b, p, s),
                          slots=("Flask 1",), item_level=84, base_level_max=70).slots[0]


def test_row1c_bare_input_whose_base_ranks_fourth_still_gets_its_variant():
    inp = InputFlask(BARE_QS)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _widen_step(probe)
    assert r.chosen is not inp and r.chosen.base is QS_LATE and r.chosen.prefix is PREFIX and r.input_bare
    assert probe.slots["Flask 1"] is r.chosen
    assert "(input bare: variant placed)" in flask_log_line(r) and "(input)" not in flask_log_line(r)
    out = trace_output_from_xml(_xml("Rarity: MAGIC\nBountiful Quicksilver Flask\nPrefix: {range:0.5}X1\nSuffix: None"))
    assert out["flask-bare-base-output"] == 0


def test_row1d_input_with_a_mod_does_not_widen_beyond_the_top_three():
    inp = InputFlask("Rarity: MAGIC\nBountiful Quicksilver Flask\nItem Level: 62\nImplicits: 0\n"
                     "{range:0.5}+10% increased Amount Recovered")
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = _widen_step(probe)
    assert r.chosen is inp and not r.input_bare and "(input)" in flask_log_line(r)
    assert not [c for c in probe.put if getattr(c, "base", None) is QS_LATE and c.prefix is not None]
    # 1 input measure + 4 bare screens; the three top bases have no mods and the input base got no variant trial
    assert r.measured == 1 + 4
