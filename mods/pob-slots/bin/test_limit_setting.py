"""#1094 unit 2: the weekly plan's price of 1 % (`LIMIT_USD_PER_PCT`) is the setting `limit_usd_per_pct` of
`config/orchestration.json`, with no default: a project whose config names no plan gets `limit_pct` None (the money
column is hidden), never a made-up number.

    python -m pytest -q mods/pob-slots/bin/test_limit_setting.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))

import collect  # noqa: E402


def write_config(root: Path, body: dict) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "orchestration.json").write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root the collector reads its settings from (REPO is the root `settings()` reads by default)."""
    monkeypatch.setattr(collect, "REPO", tmp_path)
    return tmp_path


def test_setting_present_gives_todays_numbers(project):
    """The repo's config names the plan at 16.5 dollars per 1 %: the percentages are the ones drawn today."""
    write_config(project, {"limit_usd_per_pct": 16.5})
    assert collect.limit_usd_per_pct() == 16.5
    # the weekly limit (100 % = 16.5 x 100 dollars): $1 is 1 / 16.5 of 1 % * 100 ...
    assert collect.limit_pct(1.0, 7) == pytest.approx(1.0 / 16.5)
    assert collect.limit_pct(16.5, 1) == pytest.approx(1.0)  # a day keeps the weekly limit
    # a month is against 30 / 7 of the weekly limit (#1013 row 5)
    assert collect.limit_pct(1.0, 30) == pytest.approx(1.0 / (16.5 * 30 / 7))


def test_setting_absent_hides_the_money_column(project):
    """No plan known: no number is invented, `limit_pct` is None for every window, and nothing raises."""
    write_config(project, {"repo": "o/n"})
    assert collect.limit_usd_per_pct() is None
    for days in (1, 7, 30):
        assert collect.limit_pct(1.0, days) is None
        assert collect.limit_pct(0.0, days) is None


def test_no_config_file_is_no_plan(project):
    """A project with no config at all: the same as an absent key."""
    assert collect.limit_usd_per_pct() is None
    assert collect.limit_pct(5.0, 7) is None


@pytest.mark.parametrize("value", [0, -3.0, "16.5", True, None, float("nan"), float("inf"), float("-inf")])
def test_a_value_that_is_not_a_positive_number_is_no_plan(project, value):
    write_config(project, {"limit_usd_per_pct": value})
    assert collect.limit_usd_per_pct() is None
    assert collect.limit_pct(1.0, 7) is None


def test_the_no_plan_payload_survives_json(project):
    """#1094 review: with no plan the payload's limit_pct is null and the payload still round-trips through JSON
    (the monitor parses it); a NaN or Infinity would not."""
    write_config(project, {"repo": "o/n"})
    payload = {"total": {"cost_usd": 1.0, "limit_pct": collect.limit_pct(1.0, 7), "limit_days": 7}}
    back = json.loads(json.dumps(payload))
    assert back["total"]["limit_pct"] is None


def test_the_module_no_longer_holds_a_hard_coded_price():
    """The literal moved out of the module: nothing reads `collect.LIMIT_USD_PER_PCT` any more."""
    assert not hasattr(collect, "LIMIT_USD_PER_PCT")
