"""#816: a replay on a start broken by today's rules is read as base against head only. No PoB."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import render_report  # noqa: E402

FLOORS = ["FireMaximumHitTaken", "FireResist>=FireResistMax", "MoMCastsAfterMaxHit", "PhysicalMaximumHitTaken", "TotalEHP"]
PERCENT = re.compile(r"[+-]\d+\.\d\d%")


def _row(reference: str, *, recorded: float, replayed: float, gain: float, violated: list[str], violation: float = 0.0) -> dict:
    return {
        "ok": True, "reference": reference, "source": reference, "move": "loop", "seed": 1,
        "stat": "CombinedDPS", "value_before": replayed, "value_after": replayed * (1 + gain / 100.0),
        "gain_percent": gain, "recorded_value": recorded, "replayed_value": replayed,
        "replayed_over_recorded": replayed / recorded, "start_infeasible": bool(violated),
        "start_violated": violated, "seconds": 10.0, "kept": 1, "not_kept": 13,
        "judged_and_reverted": 4, "violation_before": violation, "violation_after": violation, "audit_errors": 0,
    }


def _kwargs() -> dict:
    return dict(stamp="t", move="loop", passes=1, workers=1, seconds=30.0)


def test_broken_start_is_named_first_and_has_no_percent_against_start() -> None:
    storm = _row("stormbrand", recorded=2_115_491.0, replayed=1_590_000.0, gain=-24.67, violated=FLOORS, violation=1.0741)
    ok = _row("bleed_bow", recorded=969_206.0, replayed=969_206.0, gain=3.0, violated=[])
    other = [dict(storm, gain_percent=-20.0), dict(ok, gain_percent=4.0)]
    report = render_report([storm, ok], against=(Path("other/results.json"), other), **_kwargs())
    lines = report.splitlines()

    broken = [line for line in lines if line.startswith("Start broken")]
    assert len(broken) == 1
    assert broken[0] == "Start broken: stormbrand: violation 1.0741, floors: " + ", ".join(FLOORS)
    assert lines.index(broken[0]) < next(i for i, line in enumerate(lines) if line.startswith("| reference"))
    row = next(line for line in lines if line.startswith("| stormbrand |"))
    assert not PERCENT.search(row)
    assert "x |" not in row  # no replayed / recorded ratio
    # gain statistics and the 'does not reproduce' notes do not carry the broken build's percent
    assert "-24.67" not in report and "0.752x" not in report
    assert "**over all builds** (1 builds)" in report
    # the pair stays: base against head still lists the broken-start build
    assert "**over all builds** (2 builds)" in report.split("## Paired Comparison")[1]


def test_feasible_rows_render_byte_for_byte_as_before() -> None:
    spec = importlib.util.spec_from_file_location("replay_bench_head_816", ROOT / "tests" / "_replay_bench_before_816.py")
    old = importlib.util.module_from_spec(spec)
    sys.modules["replay_bench_head_816"] = old
    spec.loader.exec_module(old)
    rows = [_row("stormbrand", recorded=2_115_491.0, replayed=2_115_491.0, gain=2.47, violated=[]),
            _row("bleed_bow", recorded=969_206.0, replayed=900_000.0, gain=0.0, violated=[])]
    against = [dict(row, gain_percent=row["gain_percent"] + 1.0) for row in rows]
    for move in ("loop", "weapon-base"):
        kw = dict(stamp="t", move=move, passes=1, workers=1, seconds=30.0, against=(Path("o/results.json"), against), trace=True)
        assert render_report(rows, **kw) == old.render_report(rows, **kw)
