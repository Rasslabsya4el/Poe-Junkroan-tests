"""#616 R7: two flasks of one utility base add nothing PoB sees, so on a full tie the worn base loses (a tie-break, not a ban)."""

from conftest import needs_skill_source
from junkroan.optimizer.flask_probe import InputFlask
from junkroan.optimizer.flask_step import flask_log_line, run_flask_step
from junkroan.optimizer.trace_output import trace_output_from_xml
from tests.test_flask_step import Base, Cand, FakeProbe, Mod

RUBY = Base("Ruby Flask", "utility", 8)  # the lower LevelReq: it would win a plain tie
SAPPHIRE = Base("Sapphire Flask", "utility", 18)
DIVINE = Base("Divine Life Flask", "life", 60)
BARE_RUBY = "Rarity: NORMAL\nRuby Flask\nLevelReq: 8"
P_RUBY, P_SAPPH, P_LIFE = Mod("p_ruby", 10, "prefix"), Mod("p_sapph", 10, "prefix"), Mod("p_life", 10, "prefix")
MODS = {RUBY: [P_RUBY], SAPPHIRE: [P_SAPPH], DIVINE: [P_LIFE]}


def _step(probe, bases, slots=("Flask 4",)):
    return run_flask_step(probe, bases, lambda b: MODS.get(b, []), lambda b, p, s: Cand(b, p, s),
                          slots=slots, item_level=84, base_level_max=70).slots


def test_row1_a_worn_base_loses_a_full_tie_to_a_new_base():
    probe = FakeProbe(lambda c: 5, inputs={"Flask 3": InputFlask(BARE_RUBY)})
    r = _step(probe, [RUBY, SAPPHIRE])[0]
    assert r.chosen.base is SAPPHIRE and r.chosen.prefix is P_SAPPH
    assert probe.slots["Flask 4"] is r.chosen
    line = flask_log_line(r)
    assert "(tie: worn base)" in line, line


def test_row1b_the_worn_base_also_loses_when_the_other_slot_was_decided_by_this_step():
    probe = FakeProbe(lambda c: 5)
    first, second = _step(probe, [RUBY, SAPPHIRE], slots=("Flask 1", "Flask 2"))
    assert first.chosen.base is RUBY  # nothing worn yet: the lower LevelReq wins as before
    # the Ruby variant is taken (`used`): only the bare Ruby is left, and it loses on the variant step already
    assert second.chosen.base is SAPPHIRE and second.chosen.prefix is P_SAPPH


def test_row2_a_worn_base_that_strictly_wins_is_placed():
    probe = FakeProbe(lambda c: (9 if c.base is RUBY else 5), inputs={"Flask 3": InputFlask(BARE_RUBY)})
    r = _step(probe, [RUBY, SAPPHIRE])[0]
    assert r.chosen.base is RUBY
    assert "worn base" not in flask_log_line(r)


def test_row3_ladder_the_variant_step_comes_before_the_worn_step():
    # Sapphire has no mod: its bare base is the only new-base candidate; the worn Ruby variant ties it fully
    probe = FakeProbe(lambda c: 5, inputs={"Flask 3": InputFlask(BARE_RUBY)})
    r = run_flask_step(probe, [RUBY, SAPPHIRE], lambda b: [P_RUBY] if b is RUBY else [], lambda b, p, s: Cand(b, p, s),
                       slots=("Flask 4",), item_level=84, base_level_max=70).slots[0]
    assert r.chosen.base is RUBY and r.chosen.prefix is P_RUBY


def test_row4_life_flasks_are_not_ruled():
    inp = InputFlask("Rarity: NORMAL\nDivine Life Flask\nLevelReq: 60")

    def run(inputs):
        probe = FakeProbe(lambda c: 5, inputs=inputs)
        return _step(probe, [DIVINE, RUBY])[0]

    with_worn = run({"Flask 1": inp})
    without = run({})
    assert with_worn.chosen.base is without.chosen.base is RUBY  # LevelReq 8 < 60, worn Divine changes nothing
    assert with_worn.tie == without.tie != "worn base"
    # the same layout with Divine ranked first by LevelReq: still picked while worn
    low = Base("Divine Life Flask", "life", 1)
    probe = FakeProbe(lambda c: 5, inputs={"Flask 1": inp})
    r = run_flask_step(probe, [low, SAPPHIRE], lambda b: [P_LIFE] if b is low else [], lambda b, p, s: Cand(b, p, s),
                       slots=("Flask 4",), item_level=84, base_level_max=70).slots[0]
    assert r.chosen.base is low and "worn base" not in flask_log_line(r)


def _xml(raws):
    items = "".join(f'<Item id="{n}">{raw}</Item>' for n, raw in raws.items())
    slots = "".join(f'<Slot name="Flask {n}" itemId="{n}"/>' for n in raws)
    return (f'<PathOfBuilding><Items activeItemSet="1">{items}'
            f'<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>')


MAGIC_RUBY = "Rarity: MAGIC\nBountiful Ruby Flask of the Curlew\nItem Level: 62\nImplicits: 0\n+10% increased Amount Recovered"
MAGIC_RUBY2 = "Rarity: MAGIC\nPotent Ruby Flask of Rupturing\nItem Level: 62\nImplicits: 0"


@needs_skill_source
def test_row5_three_ruby_flasks_count_two():
    out = trace_output_from_xml(_xml({1: "Rarity: NORMAL\nRuby Flask", 2: MAGIC_RUBY, 3: MAGIC_RUBY2}))
    assert out["flask-duplicate-base-output"] == 2


def test_row5_two_divine_life_flasks_count_zero():
    out = trace_output_from_xml(_xml({1: "Rarity: NORMAL\nDivine Life Flask", 2: "Rarity: NORMAL\nDivine Life Flask"}))
    assert out["flask-duplicate-base-output"] == 0


def test_row5_no_duplicates_is_written_as_zero():
    out = trace_output_from_xml(_xml({1: "Rarity: NORMAL\nRuby Flask", 2: MAGIC_RUBY.replace("Ruby", "Sapphire")}))
    assert out["flask-duplicate-base-output"] == 0
    assert trace_output_from_xml(_xml({}))["flask-duplicate-base-output"] == 0


# R7 in the R3 forced search: a forced read turns on one slot only, so a worn twin would measure a win
def _forced_step(forced_fn, bases, inputs=None, mods=None):
    probe = FakeProbe(lambda c: 0, forced_fn=forced_fn, inputs=inputs or {"Flask 3": InputFlask(BARE_RUBY)})
    mods = MODS if mods is None else mods
    r = run_flask_step(probe, bases, lambda b: mods.get(b, []), lambda b, p, s: Cand(b, p, s),
                       slots=("Flask 4",), item_level=84, base_level_max=70).slots[0]
    return probe, r


def _ruby_wins(c):
    return (9 if c.base is RUBY else 5), (0.0, 0.0, 0.0)


def test_a_forced_search_a_worn_base_with_a_forced_win_still_loses_to_a_new_base():
    probe, r = _forced_step(_ruby_wins, [RUBY, SAPPHIRE])
    assert r.chosen.base is SAPPHIRE
    assert "(tie: worn base)" in flask_log_line(r)
    assert [c.base.name for c in probe.slots.values()].count("Ruby Flask") == 1  # one Ruby in the build: duplicate output 0


def test_b_forced_search_worn_base_is_placed_when_no_new_candidate_exists():
    _, r = _forced_step(_ruby_wins, [RUBY])
    assert r.chosen.base is RUBY and "worn base" not in flask_log_line(r)


def test_c_plain_measure_a_worn_base_that_strictly_wins_stays():
    probe = FakeProbe(lambda c: (9 if c.base is RUBY else 5), inputs={"Flask 3": InputFlask(BARE_RUBY)})
    r = _step(probe, [RUBY, SAPPHIRE])[0]
    assert r.chosen.base is RUBY and "worn base" not in flask_log_line(r)
    assert not probe.forced_trials


def test_d_forced_search_nothing_worn_is_as_before():
    probe, r = _forced_step(_ruby_wins, [RUBY, SAPPHIRE], inputs={"Flask 3": InputFlask(
        "Rarity: NORMAL\nDivine Life Flask\nLevelReq: 60")})
    assert r.chosen.base is RUBY and r.tie is None
    _, r = _forced_step(lambda c: (5, (0.0, 0.0, 0.0)), [RUBY, SAPPHIRE], inputs={"Flask 3": InputFlask(
        "Rarity: NORMAL\nDivine Life Flask\nLevelReq: 60")})
    assert r.chosen.base is RUBY and r.tie == "LevelReq"
