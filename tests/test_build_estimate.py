import json
from pathlib import Path

from junkroan.runs.build_estimate import FALLBACK_SECONDS, _from_history, estimate_build


def _run(root: Path, name: str, loop: float, rows: dict[str, list[float]]) -> Path:
    d = root / name
    (d / "rows").mkdir(parents=True)
    (d / "args.json").write_text(json.dumps({"loop_seconds": loop}))
    for slug, secs in rows.items():
        for i, s in enumerate(secs):
            (d / "rows" / f"{slug}-s{i}.json").write_text(
                json.dumps({"ok": True, "slug": slug, "seconds": s})
            )
    return d


def setup_function(_):
    _from_history.cache_clear()


def test_source1_this_run(tmp_path):
    run = _run(tmp_path / "b", "r1", 100, {"smite": [10, 30, 20], "spark": [999]})
    s, src = estimate_build("smite", run, 100, tmp_path / "b")
    assert s == 20 and src == "this run's median of 3 smite builds"


def test_source2_history_skips_other_loop_and_newest_wins(tmp_path):
    b = tmp_path / "b"
    _run(b, "20260101-a", 100, {"smite": [50]})
    _run(b, "20260102-b", 100, {"smite": [60, 80]})
    _run(b, "20260103-c", 999, {"smite": [1]})
    s, src = estimate_build("smite", tmp_path / "none", 100, b)
    assert s == 70 and src == "20260102-b's median of 2 smite builds"


def test_source3_weekly_all_builds(tmp_path):
    b = tmp_path / "b"
    _run(b, "20260101-x-gate-1", 100, {"spark": [10, 20, 60]})
    _run(b, "20260102-other", 100, {"spark": [5]})
    s, src = estimate_build("smite", tmp_path / "none", 100, b)
    assert s == 20 and src == "the weekly run 20260101-x-gate-1's median of all 3 builds"


def test_source4_fallback(tmp_path):
    s, src = estimate_build("smite", tmp_path / "none", 100, tmp_path / "empty")
    assert s == FALLBACK_SECONDS and src == "no rows: the fallback 68.6 min"
