"""#619 unit 3: `kicks tried N / kept K` per build and the `--seeds` spread. No PoB: hand-built rows."""

import importlib.util
from conftest import pc_only
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import replay_bench as rb  # noqa: E402

BASE = "b5f0134"


def _move(name, after, kept):
    return {"pass": 1, "where": "loop pass 1", "move": name, "before": 100.0, "after": after, "kept": kept}


def _row(seed, after, moves):
    return {"ok": True, "reference": f"b@seed{seed}", "source": "b.pob.txt", "seed": seed, "value_after": after, "moves": moves}


def test_kicks_tried_and_kept():
    row = _row(1, 100.0, [_move("kick tree", 100.0, False), _move("kick joint", 110.0, True),
                          _move("kick tree", 100.0, False), _move("refine", 120.0, True)])
    assert rb.kick_counts(row) == (3, 1)
    assert rb.kick_lines([row]) == ["- b@seed1: kicks tried 3 / kept 1"]


def test_spread_equal_finals():
    rows = [_row(s, 200.0, [_move("refine", 200.0, True)]) for s in (1, 2, 3)]
    [item] = rb.seed_spread(rows)
    assert item["spread_percent"] == 0.0 and item["distinct_finals"] == 1 and item["distinct_move_lists"] == 1


def test_spread_different_finals():
    rows = [_row(1, 90.0, [_move("refine", 90.0, True)]), _row(2, 100.0, [_move("refine", 100.0, True)]),
            _row(3, 110.0, [_move("swaps", 110.0, True)])]
    [item] = rb.seed_spread(rows)
    assert abs(item["spread_percent"] - 20.0) < 1e-9
    assert item["distinct_finals"] == 3 and item["distinct_move_lists"] == 3
    assert "spread 20.00% of median after; 3 distinct move list(s), 3 distinct final(s)" in "\n".join(rb.seed_spread_lines(rows))


@pc_only
def test_seeds_one_report_equals_old_rendering():
    results = ROOT / "artifacts" / "replay" / "20261010-0046-b632-loop-base-13842c0" / "results.json"
    data = json.loads(results.read_text(encoding="utf-8"))
    # #816: a broken start is read base against head only; this test is about the rest of the report, so the rows start feasible
    data["rows"] = [{**row, "start_violated": []} for row in data["rows"]]
    old_src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:scripts/replay_bench.py"], capture_output=True, text=True, check=True).stdout
    old_path = ROOT / "scripts" / "_old_replay_bench_619.py"
    old_path.write_text(old_src, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location("_old_replay_bench_619", old_path)
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        kw = dict(stamp=data["stamp"], move=data["move"], passes=data["passes"], workers=data["workers"], seconds=data["seconds"])
        before = old.render_report(data["rows"], **kw)
        after = rb.render_report(data["rows"], **kw)
    finally:
        old_path.unlink()
    assert "Seed spread" not in after
    new_lines = after.split("\n")
    start = new_lines.index("## Kicks per build")
    end = start + 2
    while end < len(new_lines) and new_lines[end].startswith("- "):
        end += 1
    assert "\n".join(new_lines[:start - 1] + new_lines[end:]) == before
