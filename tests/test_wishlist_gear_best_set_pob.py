"""#188 item 4, in the pinned PoB: the fill of `gear pass 2 (with tree)` on boneshatter.

The fixture is the build state `z329_juggernaut_boneshatter` s4 reaches just before that fill
(the same replay `scripts/diag178_probe.py` measures): the run is driven to that point and
stopped there, which is the only way to get the state -- it is the whole optimizer's output,
not a file. #178 measured the fill going violation 0.4051 -> 0.8930 with `CombinedDPS`
1,056,242 -> 1,055,825; by the rule of #188 it must now end at 0.4051 or better, and if it
hands back the set it started with, every PoB output must equal the one read before the fill.

Multi-minute and PoB-backed: marked `slow` (pytest.ini runs `-m "not slow"` by default).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

# #178, `z329_juggernaut_boneshatter` s4, wishlist gear, the fill of `gear pass 2 (with tree)`
START_VIOLATION = 0.4051
START_VALUE = 1_056_242.0


class _StopAfterTheFill(Exception):
    """Ends the run once the one fill under test has returned; run_one turns it into a row."""


@pytest.mark.slow
@pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason="pinned PoB runtime not present")
def test_boneshatter_gear_pass_2_fill_never_ends_below_the_set_it_started_with(tmp_path) -> None:
    import benchmark
    from junkroan.optimizer.wishlist_gear import WishlistGear

    original_fill = WishlistGear.fill
    seen: dict = {}

    def slots_without_a_record(gear: WishlistGear) -> list[str]:
        """Item 1: `_results_by_raw` must describe what `current_raw` says is equipped."""

        return [slot for slot, raw in gear.current_raw.items() if (slot, raw) not in gear._results_by_raw]

    def probe(self, bases_by_slot, **kwargs):
        # the two-pass fill of `gear pass 2 (with tree)`; the construction fills pass passes=1
        if seen or int(kwargs.get("passes", 2)) < 2:
            return original_fill(self, bases_by_slot, **kwargs)
        before_outputs = dict(self.pob.stats())
        before = self.objective.score(self.pob.stats(self.objective.stat_keys))
        before_raw = dict(self.current_raw)
        before_missing = slots_without_a_record(self)
        lines: list[str] = []
        outer_log = self.log

        def tee(line: str) -> None:
            lines.append(line)
            outer_log(line)

        self.log = tee
        try:
            original_fill(self, bases_by_slot, **kwargs)
        finally:
            self.log = outer_log
        after_outputs = dict(self.pob.stats())
        seen.update(
            before=before,
            after=self.objective.score(self.pob.stats(self.objective.stat_keys)),
            before_raw=before_raw,
            after_raw=dict(self.current_raw),
            before_outputs=before_outputs,
            after_outputs=after_outputs,
            set_lines=[line for line in lines if line.startswith("wishlist fill sets:")],
            before_missing=before_missing,
            after_missing=slots_without_a_record(self),
        )
        raise _StopAfterTheFill()

    WishlistGear.fill = probe
    try:
        row = benchmark.run_one(
            "z329_juggernaut_boneshatter",
            log_path=str(tmp_path / "boneshatter-s4.log"),
            seed=4,
            gear_mode="wishlist",
            construction="classic",
            loop_seconds=1.0,
            author_cache=str(PROJECT_ROOT / "artifacts" / "test-runs" / "issue188-author"),
        )
    finally:
        WishlistGear.fill = original_fill

    assert seen, f"the fill was never reached: {row.get('error')}\n{row.get('trace')}"
    assert row["ok"] is False and "_StopAfterTheFill" in row["error"], row.get("error")

    # the fixture is the state #178 measured
    assert seen["before"].violation == pytest.approx(START_VIOLATION, abs=5e-4)
    assert seen["before"].value == pytest.approx(START_VALUE, rel=1e-5)

    # the rule of #188
    assert seen["after"].violation <= START_VIOLATION + 5e-4
    assert seen["after"].violation <= seen["before"].violation + 1e-9
    assert len(seen["set_lines"]) == 1, seen["set_lines"]
    if not seen["before_missing"]:
        assert seen["after_missing"] == [], seen["after_missing"]

    kept_start = seen["after_raw"] == seen["before_raw"]
    if kept_start:
        assert "-> kept start (restored)" in seen["set_lines"][0]
        assert seen["after_outputs"] == seen["before_outputs"]
    else:
        assert "-> kept start" not in seen["set_lines"][0]
        assert seen["after"].value > 0.0
