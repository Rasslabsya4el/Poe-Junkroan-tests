"""#1094 unit 3a: the cost_cut payload carries the plan price beside limit_pct (one additive key of `total`).

The mod's Cost tab reads `total.limit_usd_per_pct` for its per-row % column and its money lines; with no plan the
price and the percent are both None. pytest test_limit_price_1094.py
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cost_cut import PRICES, UNTIL, close, turn  # noqa: E402
import collect  # noqa: E402
import token_meter as tm  # noqa: E402


def _cut(tmp_path, monkeypatch, config):
    if config is not None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "orchestration.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(collect, "REPO", tmp_path)
    since, until = collect.period_window(7, UNTIL)
    return collect.cost_cut([turn(ts=UNTIL - timedelta(hours=1), inp=1_000_000)], PRICES, tm, since=since, until=until)


def test_payload_carries_the_plan_price(tmp_path, monkeypatch):
    r = _cut(tmp_path, monkeypatch, {"limit_usd_per_pct": 16.5})
    assert r["total"]["limit_usd_per_pct"] == 16.5
    assert close(r["total"]["limit_pct"], 1.0 / 16.5)


def test_no_plan_the_price_and_the_percent_are_none(tmp_path, monkeypatch):
    r = _cut(tmp_path, monkeypatch, None)
    assert "limit_usd_per_pct" in r["total"] and r["total"]["limit_usd_per_pct"] is None
    assert r["total"]["limit_pct"] is None
