"""#575 row 1: the flask-uptime derivation on its inputs, PoB-free.

The worker derives every Flask slot's `active` flag from PoB's own "Flask uptime" arithmetic
(ItemsTab.lua:4916-4993): active iff it prints "Flask uptime: 100%". The arithmetic lives in
`_FLASK_UPTIME_LUA`; these tests run those very Lua lines in a plain Lua 5.1 (lupa) with a stub `build`,
so what is tested is the text production sends to PoB, not a mirror. No PobSession, no PoB launch.
"""

from __future__ import annotations

import pytest

lupa = pytest.importorskip("lupa", reason="lupa runs the worker's Lua without PoB (pip install lupa)")

from junkroan.pob.headless_runtime_worker import _FLASK_UPTIME_LUA  # noqa: E402

_STUBS = r"""
function mk_modDB(vals, flags)
  return {
    Sum = function(self, kind, cfg, name) return vals[kind .. ':' .. name] or 0 end,
    More = function(self, cfg, name) return vals['MORE:' .. name] or 1 end,
    Flag = function(self, cfg, name) return (flags and flags[name]) and true or false end,
  }
end
function mk_item(kind, data)
  local d = { duration = 6, chargesUsed = 20, gainMod = 1, instantPerc = 0, lifeBase = 0, manaBase = 0,
              lifeTotal = 0, manaTotal = 0, lifeAdditional = 0 }
  for k, v in pairs(data or {}) do d[k] = v end
  return { base = { flask = kind }, flaskData = d }
end
build = { configTab = { input = {} }, buildFlag = false }
"""

_EXPORTS = """
return { calc = flask_uptime_calc, line = flask_uptime_line, of = flask_uptime_of, uptimes_for = flask_uptimes_for,
         derive = derive_flask_flags, snapshot = flask_flags_snapshot, restore = flask_flags_restore }
"""


def _runtime():
    from lupa import lua51

    rt = lua51.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(_STUBS)
    return rt, rt.execute("\n".join(_FLASK_UPTIME_LUA) + _EXPORTS)


def _line(fn, **inputs) -> tuple[bool, str | None]:
    rt, api = _runtime()
    p = {"duration": 6, "chargesUsed": 20, "generated": 0, "perFlask": 0, "notConsume": 0}
    p.update(inputs)
    r = api.calc(rt.table_from(p))
    if r is None:
        return False, None
    return bool(r["full"]), api.line(r)


def test_diamond_flask_needs_3_33_charges_per_second_for_100_percent() -> None:
    # Diamond Flask: chargesUsed 20, duration 6 (two 3 s ticks), gainMod 1: 6 s x g / 20 >= 1  ->  g >= 3.33/s
    assert _line(None, generated=10 / 3 + 1e-9) == (True, "Flask uptime: 100%")
    full, line = _line(None, generated=3.3)
    assert full is False and line == "Flask uptime: 98% average, 98% minimum"  # 6 x 3.3 / 20 = 99 % less float dust
    assert _line(None, generated=3.0) == (False, "Flask uptime: 90% average, 90% minimum")


def test_no_generation_prints_zero_percent_average_and_minimum() -> None:
    assert _line(None) == (False, "Flask uptime: 0% average, 0% minimum")


def test_one_charge_per_second_and_25_percent_not_consume() -> None:
    # ItemsTab.lua:4984-4992: minimum ignores not-consume (6 x 1 / 20 = 30 %); the average divides the
    # charges used by (100 - 25) % : 6 x 1 / 15 = 40 %
    assert _line(None, generated=1.0, notConsume=25) == (False, "Flask uptime: 40% average, 30% minimum")


def test_not_consume_100_is_full_without_any_generation() -> None:
    assert _line(None, notConsume=100) == (True, "Flask uptime: 100%")


def test_per_empty_flask_generation_counts_on_5_second_ticks() -> None:
    # duration 10: per3 = 9 s, per5 = 10 s; minimum = 9 x 0.5 + 10 x 0.4 = 8.5 of 20 charges (42 %);
    # average = (0.5 + 0.4) x 10 = 9 of 20 charges (45 %)
    assert _line(None, duration=10, generated=0.5, perFlask=0.4) == (False, "Flask uptime: 45% average, 42% minimum")


def test_a_flask_that_cannot_be_used_prints_no_line() -> None:
    assert _line(None, chargesUsed=0) == (False, None)
    assert _line(None, duration=0) == (False, None)


def test_utility_flask_reads_generation_and_not_consume_off_the_modDB() -> None:
    rt, api = _runtime()
    item = rt.eval("mk_item({})")
    db = rt.eval("mk_modDB({ ['BASE:FlaskChargesGenerated'] = 1.0, ['BASE:FlaskChanceNotConsumeCharges'] = 25 })")
    r = api.of(item, db, rt.table_from({}), 0)
    assert api.line(r) == "Flask uptime: 40% average, 30% minimum"
    # the utility-only source and the gain modifiers: (1 + 1) x 1.5 = 3 charges/s
    db = rt.eval("mk_modDB({ ['BASE:FlaskChargesGenerated'] = 1.0, ['BASE:UtilityFlaskChargesGenerated'] = 1.0, ['INC:FlaskChargesGained'] = 50 })")
    r = api.of(item, db, rt.table_from({}), 0)
    assert api.line(r) == "Flask uptime: 90% average, 90% minimum"
    # a Life-only source never reaches a utility flask
    db = rt.eval("mk_modDB({ ['BASE:LifeFlaskChargesGenerated'] = 9.0 })")
    assert api.line(api.of(item, db, rt.table_from({}), 0)) == "Flask uptime: 0% average, 0% minimum"


def test_life_and_mana_flasks_print_no_line_unless_the_effect_is_not_removed() -> None:
    rt, api = _runtime()
    out = rt.table_from({"LifeRecoveryRateMod": 1, "ManaRecoveryRateMod": 1})
    life = rt.eval("mk_item({ life = true }, { lifeBase = 1000, lifeTotal = 1000, duration = 6 })")
    mana = rt.eval("mk_item({ mana = true }, { manaBase = 100, manaTotal = 100, duration = 6 })")
    db = rt.eval("mk_modDB({ ['BASE:FlaskChargesGenerated'] = 9.0 })")
    assert api.of(life, db, out, 0) is None
    assert api.of(mana, db, out, 0) is None
    # "effect not removed" (a flask mod or a PoB flag): the line appears, over the recovery duration
    life_kept = rt.eval("mk_item({ life = true }, { lifeBase = 1000, lifeTotal = 1000, duration = 6, lifeEffectNotRemoved = true })")
    assert api.line(api.of(life_kept, db, out, 0)) == "Flask uptime: 100%"  # 6 s x 9 / 20 charges
    flag_db = rt.eval("mk_modDB({ ['BASE:FlaskChargesGenerated'] = 1.0 }, { ManaFlaskEffectNotRemoved = true })")
    assert api.line(api.of(mana, flag_db, out, 0)) == "Flask uptime: 30% average, 30% minimum"
    # an instant-only recovery (instantPerc 100) has no duration: no line
    instant = rt.eval("mk_item({ life = true }, { lifeBase = 1000, lifeTotal = 500, instantPerc = 100, duration = 6, lifeEffectNotRemoved = true })")
    assert api.of(instant, db, out, 0) is None


def test_derive_sets_the_three_flag_places_and_recalculates_only_when_a_flag_changed() -> None:
    rt, api = _runtime()
    rt.execute(
        r"""
        world = { gen = 0, calcs = 0 }
        local db = {
          Sum = function(self, kind, cfg, name) if name == 'FlaskChargesGenerated' then return world.gen end return 0 end,
          More = function() return 1 end, Flag = function() return false end,
        }
        local function slot(selId, active)
          return { selItemId = selId, active = active, controls = { activate = { state = active } } }
        end
        build.itemsTab = {
          items = { [1] = mk_item({}), [2] = mk_item({}) },
          slots = { ['Flask 1'] = slot(1, true), ['Flask 2'] = slot(2, false), ['Flask 3'] = slot(0, true) },
          activeItemSet = { ['Flask 1'] = { active = true }, ['Flask 2'] = { active = false }, ['Flask 3'] = { active = true } },
        }
        build.calcsTab = { mainEnv = { modDB = db }, mainOutput = {} }
        runCallback = function(name) world.calcs = world.calcs + 1 build.buildFlag = false end
        """
    )
    flags = lambda: rt.eval(  # noqa: E731
        "{ build.itemsTab.slots['Flask 1'].active, build.itemsTab.slots['Flask 1'].controls.activate.state, "
        "build.itemsTab.activeItemSet['Flask 1'].active, build.itemsTab.slots['Flask 2'].active, world.calcs }"
    )
    # no generation: Flask 1 (saved active) goes inactive in all three places, one recalc; the empty Flask 3 is not touched
    api.derive()
    assert [flags()[i] for i in (1, 2, 3, 4, 5)] == [False, False, False, False, 1]
    assert rt.eval("build.itemsTab.slots['Flask 3'].active") is True
    # nothing changed: zero extra calcs
    api.derive()
    assert flags()[5] == 1
    # a source appears (4 charges/s >= 3.33): both flasks active, again one recalc
    rt.execute("world.gen = 4")
    api.derive()
    assert [flags()[i] for i in (1, 2, 3, 4, 5)] == [True, True, True, True, 2]
    api.derive()
    assert flags()[5] == 2
    # snapshot / restore put the flags back through the same three places
    snap = api.snapshot()
    rt.execute("world.gen = 0")
    api.derive()
    assert flags()[1] is False
    api.restore(snap)
    assert [flags()[i] for i in (1, 2, 3, 4)] == [True, True, True, True]
