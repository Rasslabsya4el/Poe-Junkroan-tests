import random
from datetime import datetime

from junkroan.runs import yield_plan as yp


def test_basic_shrink():
    assert yp.plan_yield({"A": 6, "B": 3, "C": 1}, 4) == {"A": 4, "B": 2, "C": 0}


def test_no_excess():
    for eff in (10, 12):
        assert yp.plan_yield({"A": 6, "B": 3, "C": 1}, eff) == {"A": 0, "B": 0, "C": 0}


def test_zero_gives_all():
    assert yp.plan_yield({"A": 6, "B": 3, "C": 1}, 0) == {"A": 6, "B": 3, "C": 1}


def test_two_single_jobs():
    assert yp.plan_yield({"A": 1, "B": 1}, 1) == {"A": 1, "B": 0}


def test_single_job():
    assert yp.plan_yield({"A": 5}, 2) == {"A": 3}


def test_equal_jobs():
    r = yp.plan_yield({"A": 2, "B": 2, "C": 2}, 3)
    assert sum(r.values()) == 3 and all(v <= 2 for v in r.values())


def test_property():
    rng = random.Random(621)
    for _ in range(500):
        w = {f"j{i}": rng.randint(1, 8) for i in range(rng.randint(1, 6))}
        eff = rng.randint(0, sum(w.values()) + 3)
        r = yp.plan_yield(w, eff)
        excess = max(0, sum(w.values()) - eff)
        assert sum(r.values()) == excess
        assert all(0 <= r[j] <= w[j] for j in w)
        assert r == yp.plan_yield(w, eff)


def test_round_trip(tmp_path):
    p = yp.yield_path("job1", tmp_path)
    assert p == tmp_path / "artifacts/runs/yield" / "job1.json"
    yp.write_yield(p, 3, 4, datetime(2026, 10, 7, 12, 0))
    assert yp.read_yield(p) == 3
    yp.write_yield(p, 0, 0, None)
    assert yp.read_yield(p) == 0


def test_malformed(tmp_path):
    p = tmp_path / "y.json"
    assert yp.read_yield(p) == 0
    for text in ("", "{", "[]", '{"give_up": -1}', '{"give_up": "2"}', '{"give_up": 1.5}', '{"give_up": true}'):
        p.write_text(text)
        assert yp.read_yield(p) == 0


def test_clear_twice(tmp_path):
    p = yp.yield_path("j", tmp_path)
    yp.write_yield(p, 1, 1, None)
    yp.clear_yield(p)
    yp.clear_yield(p)
    assert not p.exists()


def test_env(tmp_path, monkeypatch):
    monkeypatch.delenv(yp.ENV_VAR, raising=False)
    assert yp.read_yield_from_env() == 0
    p = tmp_path / "e.json"
    yp.write_yield(p, 2, 2, None)
    monkeypatch.setenv(yp.ENV_VAR, str(p))
    assert yp.read_yield_from_env() == 2
