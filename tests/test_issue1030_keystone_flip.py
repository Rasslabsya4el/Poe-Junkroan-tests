"""#1030 unit 2: `scripts/keystone_flip.py` measures (finished build, keystone) pairs and decides nothing.

The pure part runs without PoB; ONE `pob` smoke runs the real flip of Chaos Inoculation on the spark build."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import keystone_flip as kf  # noqa: E402


def test_delta_pct():
    assert kf.delta_pct(200.0, 150.0) == pytest.approx(-25.0)
    assert kf.delta_pct(-100.0, -50.0) == pytest.approx(50.0)  # relative to |before|
    assert kf.delta_pct(0.0, 5.0) is None
    assert kf.delta_pct(None, 5.0) is None
    assert kf.delta_pct(1, "x") is None
    out = kf.deltas({"Life": 100, "TotalEHP": 0}, {"Life": 1, "TotalEHP": 7}, keys=("Life", "TotalEHP", "Mana"))
    assert out == {"Life": pytest.approx(-99.0), "TotalEHP": None, "Mana": None}


def test_flip_choice_remove_when_already_allocated():
    assert kf.flip_choice([1, 2, 3], 2) == "remove"
    assert kf.flip_choice([1, 2, 3], 9) == "add"
    assert kf.flip_choice([], 9) == "add"


def test_is_collapsed():
    assert kf.is_collapsed(10.0, 4.9)  # fell by more than half
    assert not kf.is_collapsed(10.0, 5.0)  # exactly half is not "more than half"
    assert kf.is_collapsed(10.0, -1.0)  # sign change
    assert kf.is_collapsed(-3.0, 2.0)  # a drawback that turned useful changed sign
    assert not kf.is_collapsed(-3.0, -1.0)  # a smaller drawback is not a collapse
    assert not kf.is_collapsed(0.0, -5.0)  # nothing to lose


def test_collapsed_share_by_count_and_by_value():
    base = {"a": 10.0, "b": 6.0, "c": 4.0, "d": 0.0, "e": -2.0}
    flipped = {"a": 9.0, "b": 2.0, "c": -1.0, "d": 7.0}  # b falls by 2/3, c changes sign, d had no value, e (a drawback) is gone
    got = kf.collapsed_share(base, flipped)
    assert got["n"] == 4  # d (value 0) is not counted; e is (value -2)
    assert got["collapsed"] == ["b", "c"] and got["n_collapsed"] == 2
    assert got["share_count"] == pytest.approx(0.5)
    assert got["value_total"] == pytest.approx(20.0)  # the positive baseline values only
    assert got["value_collapsed"] == pytest.approx(10.0)
    assert got["share_value"] == pytest.approx(0.5)


def test_collapsed_share_missing_key_is_zero():
    base = {"a": 10.0, "b": 10.0, "c": -2.0}
    got = kf.collapsed_share(base, {"a": 10.0})
    # b is gone -> 0 -> fell by more than half; c (a drawback) is gone -> 0: not a sign change, not a collapse
    assert got["collapsed"] == ["b"]
    assert got["n"] == 3 and got["n_collapsed"] == 1
    assert got["share_count"] == pytest.approx(1 / 3)
    assert got["value_total"] == pytest.approx(20.0)
    assert got["value_collapsed"] == pytest.approx(10.0)
    assert got["share_value"] == pytest.approx(0.5)


def test_collapsed_share_empty():
    got = kf.collapsed_share({"a": 0.0}, {})
    assert got["n"] == 0 and got["share_count"] is None and got["share_value"] is None


def test_collapsed_block_leaves_the_keystone_out_and_counts_gone_nodes_as_zero():
    base = {
        "nodes": {"1": {"vp": [0.2, 0.2]}, "2": {"vp": [0.1, 0.1]}, "3": {"vp": [0.1, None]}, "9": {"vp": [0.5, 0.5]}},
        "lines": {"Ring 1#0": {"vp": [0.3, 0.3]}},
    }
    nodes2 = {1: (0.19, 0.19), 3: (0.01, None)}  # node 2 is not held in state 2; node 9 is the keystone
    block = kf.collapsed_block(base, nodes2, {"Ring 1#0": (0.0, 0.0)}, gone=[2], unmeasured=[], keystone_id=9, priced_ok=True)
    nodes = block["value"]["nodes"]
    assert nodes["n"] == 3 and nodes["collapsed"] == ["2", "3"]
    assert block["value"]["lines"]["collapsed"] == ["Ring 1#0"]
    assert block["priced"]["nodes"]["n"] == 2  # node 3 has no priced reading
    assert kf.collapsed_block(base, nodes2, {}, gone=[2], unmeasured=[], keystone_id=9, priced_ok=False)["priced"] is None


def test_collapsed_block_leaves_unmeasured_trials_out_of_both_sides():
    base = {"nodes": {"1": {"vp": [0.2, 0.2]}, "2": {"vp": [0.1, 0.1]}}, "lines": {}}
    block = kf.collapsed_block(base, {1: (0.2, 0.2)}, {}, gone=[], unmeasured=["node:2"], keystone_id=99, priced_ok=True)
    assert block["value"]["nodes"]["n"] == 1 and block["value"]["nodes"]["n_collapsed"] == 0


def test_pending_keystones_skips_the_ones_in_the_json_and_honours_names_and_limit():
    ks = [(3, "Zealot's Oath"), (1, "Chaos Inoculation"), (2, "Acrobatics")]
    assert [n for _i, n in kf.pending_keystones(ks, [])] == ["Acrobatics", "Chaos Inoculation", "Zealot's Oath"]
    assert [n for _i, n in kf.pending_keystones(ks, [{"node_id": 2}])] == ["Chaos Inoculation", "Zealot's Oath"]
    assert [n for _i, n in kf.pending_keystones(ks, [{"node_id": 2}], limit=1)] == ["Chaos Inoculation"]
    assert kf.pending_keystones(ks, [{"node_id": 1}], names=["chaos inoculation"]) == []
    assert kf.pending_keystones(ks, [], names=["chaos inoculation"]) == [(1, "Chaos Inoculation")]
    with pytest.raises(ValueError):
        kf.pending_keystones(ks, [], names=["No Such Keystone"])


def test_relative_marginal():
    assert kf.relative_marginal(100.0, 60.0) == pytest.approx(0.4)
    assert kf.relative_marginal(100.0, 120.0) == pytest.approx(-0.2)
    assert kf.relative_marginal(0.0, 0.0) is None
    assert kf.relative_marginal(None, 1.0) is None


@pytest.mark.pob
def test_chaos_inoculation_on_spark_smoke(tmp_path):
    out = tmp_path / "spark.json"
    start = time.monotonic()
    assert kf.run(["--build", "spark", "--keystone", "Chaos Inoculation", "--limit", "1", "--out", str(out)]) == 0
    seconds = time.monotonic() - start
    payload = json.loads(out.read_text(encoding="utf-8"))
    (row,) = payload["rows"]
    print(f"\nsmoke: whole run {seconds:.1f} s, row {row['seconds']:.1f} s, baseline {json.loads((tmp_path / 'spark.baseline.json').read_text())['seconds']:.1f} s")
    print("flip", row["flip"], "status", row["status"], row["reason"])
    print("Life", row["state1"]["Life"], "->", (row["state2"] or {}).get("Life"))
    print("collapsed", json.dumps({k: {kk: {x: y for x, y in vv.items() if x != 'collapsed'} for kk, vv in v.items()} for k, v in (row["collapsed"] or {}).items() if v}))
    assert "Life" in row["state1"] and "Life" in row["state2"]
    assert "collapsed" in row
    assert (tmp_path / "spark.baseline.json").is_file()
    # resumable: a second run skips the keystone and leaves the row alone
    assert kf.run(["--build", "spark", "--keystone", "Chaos Inoculation", "--out", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["rows"]) == 1
