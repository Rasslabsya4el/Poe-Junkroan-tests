"""Aggravated bleeding proves "enemy is moving" in the conservative lane (D40): PoB
does not parse Jagged Technique's line, and the moving multiplier is the only way
to represent it. Pure: no PoB."""

from junkroan.optimizer.config_rules import _conservative_allows

PREDS = {"ifMod": "BleedChance"}


def test_jagged_technique_proves_moving_and_crimson_dance_removes_it() -> None:
    ok, why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 1.5}, "Bleeding you inflict is Aggravated")
    assert ok and "Aggravated" in why
    ok, why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 1.5}, "Bleeding you inflict is Aggravated\nYour Bleeding does not deal extra Damage while the Enemy is moving and cannot be Aggravated")
    assert not ok and "Crimson Dance" in why
    ok, why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 1.5}, "100% increased Physical Damage")
    assert not ok and "state assumption" in why


def test_chance_to_aggravate_counts_by_uptime() -> None:
    text = "25% chance to Aggravate Bleeding on targets you Hit with Attacks"
    ok, why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 2.0, "BleedDuration": 5.0}, text)  # 10 hits: 94%
    assert ok and "94%" in why
    ok, why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 1.0, "BleedDuration": 5.0}, text)  # 5 hits: 76%
    assert not ok and "76%" in why
    crit = "25% chance to Aggravate Bleeding on targets you Critically Strike with Attacks"
    ok, _why = _conservative_allows("conditionEnemyMoving", PREDS, {"Speed": 2.0, "BleedDuration": 5.0, "CritChance": 30.0}, crit)  # 7.5% per hit, 10 hits: 54%
    assert not ok
