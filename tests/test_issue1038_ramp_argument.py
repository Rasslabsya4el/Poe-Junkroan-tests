"""#1038 unit 1: the ramp budget is an argument from `derive_config` to its readers, not a module global.

Two builds derived in sequence with different `ramp_seconds` assumptions must not read each other's value,
neither at derivation time nor later through `DerivedConfig.recheck` (a closure that outlives its derivation:
under the old global it read whatever the LAST `derive_config` had written). Pure: no PoB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from junkroan.optimizer import config_rules
from junkroan.optimizer.config_rules import conservative_generator_issue, derive_config
from junkroan.optimizer.tree_graph import TreeGraph

SRC = Path(__file__).resolve().parents[1] / "src"
STATS = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "EnduranceChargesMax": 3, "EnduranceChargesDuration": 10, "PowerChargesMax": 3, "PowerChargesDuration": 10, "Speed": 4.34, "CritChance": 50}
SOURCE = "30% chance to gain a power charge on hit"  # 30% x 4.34 hits/s x ramp: 0.5 s -> 0.65 charges (off), 1.0 s -> 1.30 (on)
FILLER = "+10 to strength"
VAR = "usePowerCharges"
PROVEN = {VAR: True, "overridePowerCharges": 1}


class _Pob:
    def config_options(self, predicates: Any = None, **_kw: Any) -> list[dict[str, Any]]:
        return [{"var": VAR, "shown": True, "refs": []}]

    def stats(self, keys: Any = None) -> dict[str, Any]:
        return dict(STATS) if keys is None else {}

    def config_inputs(self) -> dict[str, Any]:
        return {}

    def read_state(self) -> dict[str, Any]:
        item = {"explicit_affixes": [SOURCE, FILLER]}
        return {"gear_slots": {"slots": {"Ring 1": {"item": item}}}, "tree_state": {}, "skills_state": {}}


def _derive(ramp: float | None):
    return derive_config(_Pob(), graph=TreeGraph.load(), assumptions={} if ramp is None else {"ramp_seconds": ramp})


def test_the_module_global_is_gone() -> None:
    assert not hasattr(config_rules, "_RAMP_SECONDS")
    hits = [str(p) for p in SRC.rglob("*.py") if "_RAMP_SECONDS" in p.read_text(encoding="utf-8")]
    assert hits == []  # `grep -c _RAMP_SECONDS src/` = 0


def test_two_builds_with_different_ramp_windows_do_not_read_each_other() -> None:
    leaks = 0
    for ramp, expect_on in ((0.5, False), (1.0, True), (0.5, False), (1.0, True), (None, True)):  # None: no assumption, the default 2.5 s
        lane = _derive(ramp).conservative
        if (lane.inputs.get(VAR) is True) != expect_on:
            leaks += 1
    assert leaks == 0


def test_a_recheck_keeps_the_ramp_of_its_own_derivation() -> None:
    short, long_ = _derive(0.5), _derive(1.0)  # `long_` is derived last: under a global it would answer for `short` too
    assert short.conservative.inputs.get(VAR) is None and long_.conservative.inputs.get(VAR) is True
    assert long_.recheck(VAR, [FILLER]).inputs == PROVEN  # only the unrelated line is masked: the proof stands, with the 1.30 charges the 1 s window reaches
    assert short.recheck(VAR, [FILLER]) is None  # never proven in `short`: nothing to re-run
    again = _derive(0.5)  # a later derivation does not move `long_`
    assert again.conservative.inputs.get(VAR) is None
    assert long_.recheck(VAR, [FILLER]).inputs == PROVEN


def test_conservative_generator_issue_takes_the_ramp_as_an_argument() -> None:
    assert conservative_generator_issue(VAR, STATS, SOURCE, frozenset(), ramp_seconds=0.5) is not None
    assert conservative_generator_issue(VAR, STATS, SOURCE, frozenset(), ramp_seconds=1.0) is None
    assert conservative_generator_issue(VAR, STATS, SOURCE, frozenset()) is None  # a caller that passes nothing: the 2.5 s default
    assert config_rules.DEFAULT_RAMP_BUDGET_S == pytest.approx(2.5)
